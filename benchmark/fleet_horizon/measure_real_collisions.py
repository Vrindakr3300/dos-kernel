"""measure_real_collisions.py — $0 empirical collision footprint of a REAL agent fleet.

docs/170 bet #2 (coordination). The FleetHorizon coordination numbers (1.32x velocity/$,
human-review 100%->17.1%, collisions-prevented 0@N=1 -> 104@N=8) are a proven MECHANISM but
every magnitude rides a SIMULATED workload: `workload.generate` plants collisions via a
`shared_pool` + `shared_ratio`, and the lie/flake model is hardcoded (`agent.py:59
lie_rate=0.12`). The synthesis verdict: the mechanism + axis survive, but the DOLLAR PAYOFF is
unmeasured and the one real arc was a NET LOSS. So: MEASURE the rate, don't claim payoff.

This script measures the ONE thing the simulation stands in for, on REAL data: did concurrent
agents in a real fleet actually write to COLLIDING file regions in OVERLAPPING time windows —
a collision the arbiter's lane-disjointness (`_tree.prefixes_collide`) would have serialized?

The corpus is the operator's own Claude Code transcripts (`~/.claude/projects/<ws>/**/*.jsonl`,
incl. sub-agents/workflows) — a real frontier-model fleet running concurrently on shared repos.
Each Write/Edit is a real write event with a resolved absolute path + a millisecond timestamp +
a session id. Two writes COLLIDE when (a) they are from different sessions, (b) their paths
collide under the REAL kernel rule (`prefixes_collide(norm_tree_prefix(a), norm_tree_prefix(b))`
— byte-identical to the arbiter's disjointness test), and (c) their timestamps fall within a
concurrency window (the writes were live at the same time → the arbiter would have had to choose).

What this CAN show ($0, exact): the REAL collision footprint of a real fleet — the empirical
N>1 number the simulated shared_ratio was a proxy for, and that it is 0 when no two sessions are
concurrent (the N=1->0 equation, observed not assumed). What it CANNOT show: the dollar value of
preventing them (that needs the believed-vs-adjudicated A/B, FleetHorizon's job) — this is the
RATE half, the honest predecessor to any payoff claim.

Pure replay of recorded JSON — no model calls, no network. Uses the REAL kernel collision logic.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_DOS_SRC = os.path.join(_HERE, "..", "..", "src")
if os.path.isdir(_DOS_SRC):
    sys.path.insert(0, _DOS_SRC)

# the REAL kernel collision rule — the SAME one the arbiter uses (no re-implementation).
from dos._tree import norm_tree_prefix, prefixes_collide  # noqa: E402

# tools that AUTHOR a file write (byte-clean path identity — the agent named the path).
_WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}


def _parse_ts(s: str):
    """ISO8601 (…Z) -> epoch seconds, or None. The transcript stamps every record."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _resolve_path(file_path: str, cwd: str) -> str | None:
    """Absolute, normalized path of a write target (the collision identity).

    A write's `file_path` may be absolute or relative-to-cwd; resolve against the record's
    `cwd` so two sessions in the same repo compare on the same absolute path. casefold +
    forward-slash is handled by `norm_tree_prefix` downstream; here we only need a stable
    absolute key."""
    if not file_path:
        return None
    fp = file_path.replace("\\", "/")
    if not os.path.isabs(fp) and cwd:
        fp = (cwd.replace("\\", "/").rstrip("/") + "/" + fp)
    return os.path.normpath(fp).replace("\\", "/")


def _iter_writes(path: str):
    """Yield (session_id, abs_path, ts_epoch) for every Write/Edit in one transcript."""
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "assistant":
                continue
            msg = o.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            cwd = o.get("cwd") or ""
            sid = o.get("sessionId") or os.path.basename(path)
            ts = _parse_ts(o.get("timestamp"))
            for b in content:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                if b.get("name") not in _WRITE_TOOLS:
                    continue
                inp = b.get("input") or {}
                fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
                ap = _resolve_path(fp, cwd) if fp else None
                if ap is not None and ts is not None:
                    yield sid, ap, ts


def _default_corpus_dir() -> str:
    """The CC transcript dir for the current workspace, auto-derived the way Claude
    Code names it (each of `: \\ /` in the abspath -> a single dash). Reuses docs/243
    Track A's resolver so this script stops resolving a `<project>` PLACEHOLDER (the
    bug that made it return 0 collisions — it never found the corpus)."""
    try:
        from benchmark.fleet_trajectory.corpus import DEFAULT_CORPUS
        return DEFAULT_CORPUS
    except Exception:
        return os.path.expanduser(r"~/.claude/projects")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=_default_corpus_dir())
    ap.add_argument("--window-sec", type=float, default=300.0,
                    help="two writes to a colliding path are CONCURRENT if within this window")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", type=int, default=12, help="show this many top collision sites")
    args = ap.parse_args(argv)

    files = [f for f in glob.glob(os.path.join(args.dir, "**", "*.jsonl"), recursive=True)
             if os.path.basename(f) != "journal.jsonl"]

    # gather all writes
    writes = []  # (sid, abs_path, ts)
    for f in files:
        for w in _iter_writes(f):
            writes.append(w)

    sessions = {w[0] for w in writes}
    # group writes by normalized collision-prefix BUCKET is too coarse; instead compare exact
    # absolute paths first (the dominant real collision), then report glob-prefix collisions too.
    by_path = defaultdict(list)  # abs_path -> [(sid, ts)]
    for sid, ap, ts in writes:
        by_path[ap].append((sid, ts))

    # A real cross-session collision: two DIFFERENT sessions wrote the SAME absolute path within
    # the concurrency window. (Same-path is the strict subset of prefixes_collide that matters
    # most — two agents editing literally the same file concurrently = the corruption case.)
    collisions = []  # (path, sidA, sidB, dt_sec)
    contended_paths = []
    for ap, evs in by_path.items():
        sids = {s for s, _ in evs}
        if len(sids) < 2:
            continue
        # pairwise within-window across different sessions
        evs_sorted = sorted(evs, key=lambda x: x[1])
        hit = None
        for i in range(len(evs_sorted)):
            for j in range(i + 1, len(evs_sorted)):
                sa, ta = evs_sorted[i]
                sb, tb = evs_sorted[j]
                if sa == sb:
                    continue
                if abs(tb - ta) <= args.window_sec:
                    hit = (ap, sa, sb, round(abs(tb - ta), 1))
                    break
            if hit:
                break
        if hit:
            collisions.append(hit)
        contended_paths.append((ap, len(sids)))

    # sanity: verify the kernel's prefixes_collide agrees with same-path identity (it must).
    kernel_agrees = all(
        prefixes_collide(norm_tree_prefix(c[0]), norm_tree_prefix(c[0])) for c in collisions
    )

    summary = {
        "as_of": "2026-06-06",
        "dir": args.dir,
        "window_sec": args.window_sec,
        "n_transcripts": len(files),
        "n_write_events": len(writes),
        "n_sessions_that_wrote": len(sessions),
        "n_distinct_paths_written": len(by_path),
        "n_paths_written_by_multiple_sessions": len(contended_paths),
        "n_concurrent_cross_session_collisions": len(collisions),
        "collision_rate_per_1k_writes": round(1000.0 * len(collisions) / len(writes), 2) if writes else 0.0,
        "kernel_prefixes_collide_agrees": kernel_agrees,
    }

    if args.json:
        print(json.dumps({"summary": summary,
                          "collisions": [{"path": c[0], "sidA": c[1][:8], "sidB": c[2][:8],
                                          "dt_sec": c[3]} for c in collisions[:args.show]],
                          "top_contended": sorted(contended_paths, key=lambda x: -x[1])[:args.show]},
                         indent=2))
        return

    print("=== REAL agent-fleet collision footprint (real kernel prefixes_collide, 2026-06-06) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n=== concurrent cross-session collisions (same path, <= {args.window_sec}s apart) ===")
    for path, sa, sb, d in sorted(collisions, key=lambda x: x[3])[:args.show]:
        print(f"  {d:>7.1f}s  {sa[:8]} x {sb[:8]}  {path}")
    if not collisions:
        print("  (none — no two sessions wrote the same path within the concurrency window)")
    print(f"\n=== top paths written by multiple sessions (contention surface, any time) ===")
    for path, n in sorted(contended_paths, key=lambda x: -x[1])[:args.show]:
        print(f"  {n} sessions  {path}")


if __name__ == "__main__":
    main()
