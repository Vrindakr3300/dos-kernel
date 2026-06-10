"""Analyze the recorded dangling-intent A/B — does the WARN CONVERT a premature stop? (docs/152 FIX half)

Reads the recorded `none` vs `resurface` trajectories (live_ab.py output) and answers the
load-bearing question docs/151/152 isolated: of the tasks where `dangling_intent` FIRED (the agent
ended on "I still need to X" and the wrapper re-surfaced its own sentence for one more turn), did the
`resurface` arm FINISH the work the `none` arm left undone?

Honest accounting (the docs/143 attribution discipline):
  * The arms re-seed a fresh DB per run, so they are NOT verifier-paired bit-for-bit — compare per
    task_id, and trust the per-verifier-pass rate (low-variance) over all-or-nothing success at small N.
  * The headline is the CONVERSION rate on the FIRED subset: of tasks where the warn fired in the
    resurface arm, the fraction where resurface's verifier-pass exceeded none's on the same task. A
    warn that fires but does not convert (the model couldn't do the step even when reminded) is the
    measured can-do-step-when-nudged decay docs/151 §1 flags -- report it, do not hide it.
  * Also report the BARE firing rate (how often the warn fired at all -- the DETECT half, expected
    ~26% of failed runs per docs/152) and the feasible-rate (did resurface BREAK any task none passed
    -- the backfire guard).

Pure replay of the recorded JSON -- no model calls. Rerunnable: point it at any live_ab --out folder.
"""

from __future__ import annotations

import glob
import json
import os
import sys


def _runs(d):
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    if isinstance(d, dict):
        return d.get("runs") if isinstance(d.get("runs"), list) else [d]
    return []


def _task_id(path: str) -> str:
    """The task identity shared across arms — the trajectory filename (same task config per arm)."""
    return os.path.basename(path)


def _dangling_fired(run: dict) -> int:
    """How many times the dangling re-surface fired in this run (from the conversation flow + stats)."""
    flow = run.get("conversation_flow") or []
    n = sum(1 for e in flow if isinstance(e, dict) and e.get("type") == "dos_dangling_warn")
    if n:
        return n
    stats = run.get("dos_arg_provenance") or {}
    return int(stats.get("dangling_warns", 0) or 0)


def _vpass(run: dict) -> float:
    vs = run.get("verification_summary") or {}
    return float(vs.get("pass_rate", 0.0) or 0.0)


def _load_arm(folder: str, arm: str) -> dict:
    """task_id -> the run dict, for one arm."""
    out = {}
    for f in glob.glob(os.path.join(folder, arm, "**", "*.json"), recursive=True):
        if "_summary" in f or "_sample" in f:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rs = _runs(d)
        if rs:
            out[_task_id(f)] = rs[0]
    return out


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "benchmark/enterpriseops/live_results/dangling_ab"
    none = _load_arm(folder, "none")
    resurf = _load_arm(folder, "resurface")
    shared = sorted(set(none) & set(resurf))

    n_fired = 0           # tasks where the warn fired in the resurface arm
    converted = 0         # ... where resurface vpass > none vpass (the FIX landed)
    unchanged = 0         # ... where resurface vpass == none vpass (fired, no conversion)
    regressed = 0         # ... where resurface vpass < none vpass (the backfire)
    fired_examples = []
    # whole-corpus aggregates
    none_v = resurf_v = 0.0
    none_pass = resurf_pass = 0
    total_fires = 0

    for tid in shared:
        nr, rr = none[tid], resurf[tid]
        nv, rv = _vpass(nr), _vpass(rr)
        none_v += nv; resurf_v += rv
        none_pass += 1 if nr.get("overall_success") else 0
        resurf_pass += 1 if rr.get("overall_success") else 0
        fires = _dangling_fired(rr)
        total_fires += fires
        if fires > 0:
            n_fired += 1
            if rv > nv:
                converted += 1
                if len(fired_examples) < 5:
                    fired_examples.append((tid[:40], f"vpass {nv:.2f}->{rv:.2f} CONVERTED"))
            elif rv == nv:
                unchanged += 1
            else:
                regressed += 1

    n = len(shared)
    print("=" * 82)
    print(f"  DANGLING-INTENT A/B — does the WARN CONVERT a premature stop? (docs/152 FIX half)")
    print(f"  folder: {folder}")
    print("=" * 82)
    print(f"  paired tasks (shared by id): {n}")
    if not n:
        print("  NO paired tasks found — check the folder / arm names (none, resurface).")
        print("=" * 82)
        return
    print(f"  whole-corpus verifier-pass: none {100*none_v/n:.1f}%  resurface {100*resurf_v/n:.1f}%  "
          f"(delta {100*(resurf_v-none_v)/n:+.1f}pp)")
    print(f"  whole-corpus task-success:  none {none_pass}/{n}  resurface {resurf_pass}/{n}")
    print(f"  total dangling fires (resurface arm): {total_fires}")
    print("-" * 82)
    print(f"  ON THE FIRED SUBSET (the tasks the warn actually fired on): {n_fired}")
    if n_fired:
        print(f"    CONVERTED (resurface vpass > none): {converted}/{n_fired} = {100*converted/n_fired:.0f}%  <- the FIX rate")
        print(f"    unchanged (fired, no conversion):   {unchanged}/{n_fired}  (can't-do-step-when-nudged)")
        print(f"    REGRESSED (resurface vpass < none): {regressed}/{n_fired}  (the backfire guard)")
    else:
        print("    the warn fired on 0 paired tasks in this slice — too few tasks / too few natural")
        print("    narrating-stops to measure conversion. Run more tasks (the DETECT rate is ~26%).")
    for tid, note in fired_examples:
        print(f"    + {tid}  {note}")
    print("-" * 82)
    print("  READING: CONVERSION is the FIX half docs/151 §1 flagged as the load-bearing unknown.")
    print("  A high fire-but-unchanged rate = the model couldn't do the step even when reminded")
    print("  (DETECT works, FIX doesn't). 0 regressions = the WARN-only floor held (no backfire).")
    print("  Trust per-verifier-pass over all-or-nothing success at small N (docs/143).")
    print("=" * 82)


if __name__ == "__main__":
    main()
