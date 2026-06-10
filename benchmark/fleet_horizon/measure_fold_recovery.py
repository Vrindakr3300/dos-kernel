"""measure_fold_recovery — the $0 recoverability/backoff measure under the docs/219 fold-consumer A/B.

> **docs/219 designs a live A/B of a fold-CONSUMER that re-dispatches a dead child's
> own unit (the safe action). Its decisive question is NOT "does it harm?" (it
> structurally cannot — it fires only on a certain-terminal `<synthetic>` death, so
> re-dispatch is additive and never perturbs a healthy fold) but **"does additive
> recovery beat rate-limit-WAVE futility?"** — because the deaths arrive in waves
> (`measure_fold_deaths.py`: 80–94% of a fan-out dying together), and re-dispatching
> INTO the same wave just dies again (docs/219 §5). This script answers that question
> $0 from the fossils already on disk, the docs/190 "measure the rate before you
> spend on the run" rung: for every harness-death, how long until the ACCOUNT is
> healthy again (the next HEALTHY subagent completion anywhere) — the minimum backoff
> a re-dispatch would need to recover.**

Why account-wide, not per-session: a `<synthetic>` rate-limit is an ACCOUNT-level
limit (every concurrent agent shares it). So the cleanest empirical signal that the
limit had lifted at time T is that SOME subagent completed HEALTHY at T. "Time from a
death to the next healthy completion anywhere in the account" is therefore a valid
upper bound on when a re-dispatch of that dead unit COULD have succeeded. A short gap
⇒ backoff recovers ⇒ arm B viable; a long gap (the account stayed limited for hours)
⇒ re-dispatch is futile until reset ⇒ arm B is harmless-but-futile (the docs/219 §6
distinction from docs/205's harmful net-negative).

What this CAN show ($0, exact): the wave structure (how bursty the deaths are) and
the recovery-window distribution (the backoff arm B needs). What it CANNOT show: that
a re-dispatched unit produces a CORRECT deliverable (Wall §3 presence-not-correctness),
nor the live token cost — those need the actual A/B (docs/219 §4). This is the RATE
half, the honest predecessor to the payoff claim — exactly the posture of its sibling
`measure_real_collisions.py` (docs/190) and `measure_fold_deaths.py` (docs/197).

Byte-clean for the same reason the verb is (docs/138): the dead/healthy split reuses
the SHIPPED kernel verdict (`result_state`), keyed on the harness-authored
`model=="<synthetic>"` stamp — a different byte-author than the judged worker.

Run ($0, no network, read-only):

    python benchmark/fleet_horizon/measure_fold_recovery.py
    python benchmark/fleet_horizon/measure_fold_recovery.py --json
    python benchmark/fleet_horizon/measure_fold_recovery.py --wave-gap-sec 120
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path


def _ensure_dos_on_path() -> None:
    here = Path(__file__).resolve()
    src = here.parents[2] / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _default_projects_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


def _parse_ts(s) -> float | None:
    """ISO8601 (…Z) → epoch seconds, or None. Same parser as measure_real_collisions."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _workflow_transcripts(projects_dir: Path) -> list[str]:
    pat = str(projects_dir / "**" / "subagents" / "workflows" / "*" / "agent-*.jsonl")
    return sorted(glob.glob(pat, recursive=True))


def _terminal_record_and_verdict(path: str):
    """One pass: the LAST assistant record (raw, for its timestamp) + the kernel verdict.

    Reuses `result_state.terminal_evidence_from_record` + `classify_terminal` for the
    dead/healthy grammar (no re-implementation of the `<synthetic>` rule), and grabs the
    top-level `timestamp` off the same record. Returns (verdict, ts_epoch | None,
    sessionId | None) or None if unreadable / no assistant record.
    """
    from dos import result_state as rs

    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return None
    last_obj = None
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except (ValueError, TypeError):
            continue
        m = o.get("message")
        if isinstance(m, dict) and m.get("role") == "assistant":
            last_obj = o
    if last_obj is None:
        return None
    ev = rs.terminal_evidence_from_record(last_obj)
    if ev is None:
        return None
    verdict = rs.classify_terminal(ev)
    return verdict, _parse_ts(last_obj.get("timestamp")), last_obj.get("sessionId")


# ---------------------------------------------------------------------------
# Wave detection — split a sorted death-time list into bursts.
# ---------------------------------------------------------------------------
def _waves(death_ts: list[float], gap_sec: float) -> list[tuple[float, float, int]]:
    """Group sorted death timestamps into waves. Two deaths are in the same wave if
    they are within `gap_sec`. Returns [(start_ts, end_ts, size), …]. PURE."""
    if not death_ts:
        return []
    ts = sorted(death_ts)
    waves: list[tuple[float, float, int]] = []
    start = prev = ts[0]
    size = 1
    for t in ts[1:]:
        if t - prev <= gap_sec:
            size += 1
        else:
            waves.append((start, prev, size))
            start = t
            size = 1
        prev = t
    waves.append((start, prev, size))
    return waves


_BUCKETS = [
    ("<=60s", 60.0),
    ("<=5m", 300.0),
    ("<=30m", 1800.0),
    ("<=1h", 3600.0),
    ("<=6h", 21600.0),
    (">6h", float("inf")),
]


def _bucket(gap: float | None) -> str:
    if gap is None:
        return "never"
    for label, hi in _BUCKETS:
        if gap <= hi:
            return label
    return ">6h"


def _pctl(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[i]


def measure(projects_dir: Path, wave_gap_sec: float) -> dict:
    """The recoverability/backoff measure over the real workflow-subagent corpus."""
    paths = _workflow_transcripts(projects_dir)

    states: Counter = Counter()
    dead_ts: list[float] = []                 # death times (account-wide)
    healthy_ts: list[float] = []              # healthy completion times (account-wide)
    dead_no_ts = healthy_no_ts = 0

    for p in paths:
        res = _terminal_record_and_verdict(p)
        if res is None:
            states["UNREADABLE"] += 1
            continue
        verdict, ts, _sid = res
        states[verdict.state.value] += 1
        if verdict.dead:
            if ts is None:
                dead_no_ts += 1
            else:
                dead_ts.append(ts)
        elif verdict.state.value == "HEALTHY":
            if ts is None:
                healthy_no_ts += 1
            else:
                healthy_ts.append(ts)

    healthy_sorted = sorted(healthy_ts)

    # The headline: per death, the gap to the next HEALTHY completion ANYWHERE in the
    # account (the account-level rate-limit recovery — when a re-dispatch could succeed).
    recovery_gaps: list[float] = []           # finite gaps only
    bucket_counts: Counter = Counter()
    never = 0
    for d in dead_ts:
        i = bisect_right(healthy_sorted, d)
        if i < len(healthy_sorted):
            gap = healthy_sorted[i] - d
            recovery_gaps.append(gap)
            bucket_counts[_bucket(gap)] += 1
        else:
            never += 1
            bucket_counts["never"] += 1

    # Wave structure (account-wide): how bursty are the deaths?
    waves = _waves(dead_ts, wave_gap_sec)
    wave_sizes = [w[2] for w in waves]
    wave_durs = [w[1] - w[0] for w in waves]

    # Per-wave recovery: from each wave's END, the gap to the next healthy completion.
    wave_recovery: list[float] = []
    wave_never = 0
    for _start, end, _size in waves:
        i = bisect_right(healthy_sorted, end)
        if i < len(healthy_sorted):
            wave_recovery.append(healthy_sorted[i] - end)
        else:
            wave_never += 1

    n_dead = len(dead_ts)
    recovered = len(recovery_gaps)
    within = {
        label: sum(1 for g in recovery_gaps if g <= hi)
        for label, hi in _BUCKETS if hi != float("inf")
    }

    return {
        "as_of_note": "stamp the run date at the call site (Date.now() unavailable in-kernel)",
        "transcripts": len(paths),
        "states": dict(states),
        "deaths_with_ts": n_dead,
        "deaths_without_ts": dead_no_ts,
        "healthy_with_ts": len(healthy_ts),
        # --- the headline: recovery-window (backoff) distribution ---
        "recovery": {
            "deaths_measured": n_dead,
            "recovered_eventually": recovered,
            "never_recovered_in_corpus": never,
            "median_gap_sec": _pctl(recovery_gaps, 50),
            "p90_gap_sec": _pctl(recovery_gaps, 90),
            "bucket_counts": dict(bucket_counts),
            "frac_recovered_within": {
                label: (cnt / n_dead) if n_dead else None
                for label, cnt in within.items()
            },
        },
        # --- wave structure ---
        "waves": {
            "wave_gap_sec": wave_gap_sec,
            "n_waves": len(waves),
            "max_wave_size": max(wave_sizes) if wave_sizes else 0,
            "median_wave_size": _pctl([float(s) for s in wave_sizes], 50),
            "median_wave_duration_sec": _pctl(wave_durs, 50),
            "p90_wave_duration_sec": _pctl(wave_durs, 90),
            "median_wave_recovery_sec": _pctl(wave_recovery, 50),
            "p90_wave_recovery_sec": _pctl(wave_recovery, 90),
            "waves_never_recovered": wave_never,
        },
    }


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        if x >= 3600:
            return f"{x/3600:.1f}h"
        if x >= 60:
            return f"{x/60:.1f}m"
        return f"{x:.1f}s"
    return str(x)


def _print_text(r: dict) -> None:
    n = r["transcripts"]
    print(f"workflow subagent transcripts: {n}")
    if not n:
        print("  (none found — pass --projects PATH)")
        return
    print(f"  states: {r['states']}")
    rec = r["recovery"]
    nd = rec["deaths_measured"]
    print()
    print(f"recovery window — per death, time to the next ACCOUNT-WIDE healthy completion")
    print(f"  (this is the minimum BACKOFF a re-dispatch (docs/219 arm B) would need):")
    print(f"  deaths measured        : {nd}")
    print(f"  recovered eventually   : {rec['recovered_eventually']}  "
          f"({100*rec['recovered_eventually']/nd:.1f}% of deaths)" if nd else "")
    print(f"  never recovered (corpus): {rec['never_recovered_in_corpus']}")
    print(f"  median gap             : {_fmt(rec['median_gap_sec'])}")
    print(f"  p90 gap                : {_fmt(rec['p90_gap_sec'])}")
    print(f"  fraction recovered within:")
    for label, frac in rec["frac_recovered_within"].items():
        if frac is not None:
            print(f"     {label:<6} : {100*frac:5.1f}%")
    w = r["waves"]
    print()
    print(f"wave structure (deaths within {_fmt(w['wave_gap_sec'])} = one wave):")
    print(f"  n waves                : {w['n_waves']}")
    print(f"  max wave size          : {w['max_wave_size']}")
    print(f"  median wave size       : {_fmt(w['median_wave_size'])}")
    print(f"  median wave duration   : {_fmt(w['median_wave_duration_sec'])}")
    print(f"  median wave recovery   : {_fmt(w['median_wave_recovery_sec'])}  "
          f"(from wave-end to next healthy)")
    print(f"  p90 wave recovery      : {_fmt(w['p90_wave_recovery_sec'])}")
    print(f"  waves never recovered  : {w['waves_never_recovered']}")
    print()
    print("read: a SHORT recovery window ⇒ backoff recovers ⇒ arm B viable; a LONG one")
    print("(hours) ⇒ re-dispatch is harmless-but-futile until the limit resets (docs/219 §6).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure the fold-death recovery window + wave structure (docs/219 "
                    "fold-consumer A/B de-risking). $0, read-only.")
    ap.add_argument("--projects", default=None, metavar="PATH",
                    help="the Claude Code projects dir (default: ~/.claude/projects)")
    ap.add_argument("--wave-gap-sec", type=float, default=120.0,
                    help="deaths within this gap are one wave (default 120s)")
    ap.add_argument("--json", action="store_true", help="emit the full result object")
    args = ap.parse_args(argv)

    _ensure_dos_on_path()
    projects = Path(args.projects) if args.projects else _default_projects_dir()
    result = measure(projects, args.wave_gap_sec)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
