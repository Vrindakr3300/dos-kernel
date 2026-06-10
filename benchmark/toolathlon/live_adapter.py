"""Adapt a LIVE Toolathlon run (an on-disk task result dir) into the frozen `Trajectory` the
replay scorer already understands, so the SAME DOS detectors that scored the published
`Toolathlon-Trajectories` dataset (docs/157) score our own live `eval_client.py` runs.

This is the bridge from DETECT-on-frozen-data to DETECT-on-a-run-we-just-drove: nothing about the
detectors changes — only the reader. A live task dir (under `<out>/finalpool/<task>/`) carries:
  - `traj_log.json`  — {messages, key_stats, status, ...}; `messages` is the OpenAI-style chat list,
                       already DECODED (not a JSON string like the published dataset).
  - `eval_res.json`  — {"pass": bool, "failure": str}; the THIRD-PARTY verifier's verdict.
  - `status.json`    — {"preprocess","running","evaluation"}; `evaluation` is the bool label too.

We assemble exactly the dict shape `trajectory.parse_record` expects (`task_status` + `messages`),
so the adapter is a thin re-key, and the pure scorer stays the single source of detector logic.

I/O lives here (the boundary); the detector fold stays pure in `replay.py`. Mirrors the
`dataset.py` / `replay.py` split.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator, Optional

from .trajectory import Trajectory, parse_record


def _read_json(p: Path) -> Optional[dict]:
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def live_record(task_dir: Path) -> Optional[dict]:
    """Build a dataset-shaped record from a live task result dir, or None if it has no trajectory.

    The published dataset names a run by `<model>_<run>` + `task_name`; here the task name is the
    dir name and the model/run come from the caller. We carry the third-party label from
    `eval_res.json:pass` (preferred — it is the verifier's own bool) falling back to
    `status.json:evaluation`.
    """
    traj = _read_json(task_dir / "traj_log.json")
    if not traj or not isinstance(traj.get("messages"), list):
        return None
    ev = _read_json(task_dir / "eval_res.json") or {}
    st = _read_json(task_dir / "status.json") or {}
    # `pass` is the verifier's bool; None when the run errored before eval (excluded downstream).
    passed = ev.get("pass")
    if passed is None:
        passed = st.get("evaluation")
    return {
        "task_name": task_dir.name,
        # parse_record reads task_status.evaluation; mirror the dataset key so nothing else changes.
        "task_status": {"evaluation": passed},
        "messages": traj.get("messages", []),
    }


def iter_live_trajectories(results_dir: Path) -> Iterator[Trajectory]:
    """Yield a parsed `Trajectory` per task under `<results_dir>/finalpool/<task>/`.

    Skips dirs with no readable trajectory (e.g. a task whose download errored mid-flight) — a
    missing run is logged-by-skip, never guessed, the same discipline as the dataset reader.
    """
    pool = results_dir / "finalpool"
    if not pool.is_dir():
        return
    for entry in sorted(pool.iterdir()):
        if not entry.is_dir():
            continue
        rec = live_record(entry)
        if rec is not None:
            yield parse_record(rec)


def _score_dirs(dirs: list[Path]) -> list[dict]:
    """Fold the docs/157 detectors over every live trajectory under the given result dirs (deduped
    by task name; first dir wins). Returns one scalar-only row per task — the durable artifact."""
    from .replay import dangling_fired, tool_stream_fired, tool_stream_peak  # local: avoid cycle
    from .trajectory import terminal_error_fired, to_tool_stream

    seen: set[str] = set()
    rows: list[dict] = []
    for d in dirs:
        for tj in iter_live_trajectories(d):
            if tj.task_name in seen:
                continue
            seen.add(tj.task_name)
            rows.append(
                {
                    "task": tj.task_name,
                    "passed": tj.passed,
                    "n_tool_steps": len(to_tool_stream(tj).steps),
                    "dangling_fired": dangling_fired(tj),
                    "tool_stream_peak": tool_stream_peak(tj).name,
                    "tool_stream_fired": tool_stream_fired(tj),
                    "terminal_error_fired": terminal_error_fired(tj),
                }
            )
    return rows


if __name__ == "__main__":  # pragma: no cover - operator CLI, exercised by hand
    import csv
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 guard
    paths = [Path(a) for a in sys.argv[1:]] or [
        Path(__file__).parent / "_live" / "results" / name
        for name in ("smoke_find_alita", "smoke5", "pure_local_batch")
    ]
    rows = _score_dirs(paths)
    if not rows:
        print("no live trajectories found under:", *map(str, paths))
        sys.exit(1)
    fails = [r for r in rows if r["passed"] is False]
    fired = [
        r
        for r in rows
        if r["dangling_fired"] or r["tool_stream_fired"] or r["terminal_error_fired"]
    ]
    fired_fail = [r for r in fired if r["passed"] is False]
    for r in sorted(rows, key=lambda r: (r["tool_stream_peak"] == "ADVANCING", r["task"])):
        flag = " <-- FIRE" if (r["dangling_fired"] or r["tool_stream_fired"] or r["terminal_error_fired"]) else ""
        print(
            f'{r["task"]:28s} pass={str(r["passed"]):5s} steps={r["n_tool_steps"]:<3d} '
            f'dangling={str(r["dangling_fired"]):5s} ts={r["tool_stream_peak"]:9s} '
            f'term_err={str(r["terminal_error_fired"]):5s}{flag}'
        )
    print("-" * 78)
    print(
        f"runs={len(rows)} FAIL={len(fails)} fires={len(fired)} fires-on-fail={len(fired_fail)} "
        f"| recall={len(fired_fail)}/{len(fails)} precision={len(fired_fail)}/{len(fired) or 1}"
    )
    out = paths[0].parent / "live_scored_rows.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", out)
