"""Did the catch MATTER? — per-task verifier-flip join vs the none baseline.

The Tier-0 sweep said the load-bearing quantity is the mattered_rate: of the mints the
detector caught, how many fed a verifier the task was scored on? A catch on an FK no
verifier checks buys nothing (and the disruption can still hurt a different step — the
docs/143 -9pp). This measures it EMPIRICALLY from the live results, without guessing:

  For each task an intervention arm shares with the `none` baseline, and where that arm
  CAUGHT >=1 mint, compare the per-verifier pass/fail between the two arms:
    * a verifier that flipped FALSE->TRUE  = the intervention HELPED (a checked FK fixed)
    * a verifier that flipped TRUE->FALSE  = the intervention HURT (disruption broke a step)
    * no flip                              = the catch did not matter to the score

This is the honest decomposition behind the headline integrity delta: net help = helped -
hurt, and the ratio of help-flips to caught-mint tasks is the live mattered-rate proxy.

NOTE the caveat (stated in the output): arms are NOT verifier-paired at the model level —
each re-seeds a fresh DB and the model is stochastic — so a single flip can be noise. The
signal is the AGGREGATE help-vs-hurt count across many caught-mint tasks, not any one flip.

    python mattered_join.py                       # all intervention arms vs none
    python mattered_join.py --arms warn block
"""

from __future__ import annotations

import argparse
import glob
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _tid(path: str) -> str:
    return os.path.basename(path).replace("results_oracle__", "").replace(".json", "")


def _load(arm_dir: str) -> dict:
    return {_tid(f): f for f in glob.glob(os.path.join(arm_dir, "results_*.json"))}


def _run0(path: str) -> dict:
    try:
        d = json.load(open(path, encoding="utf-8"))
        return (d.get("runs") or [{}])[0]
    except Exception:
        return {}


def _caught(run: dict) -> int:
    return int((run.get("dos_arg_provenance") or {}).get("nudges_injected", 0) or 0)


def _verifiers(run: dict) -> dict:
    vr = run.get("verification_results") or {}
    return {k: bool(v.get("passed")) for k, v in vr.items() if isinstance(v, dict)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results"))
    ap.add_argument("--arms", nargs="+", default=["defer", "warn", "block"])
    args = ap.parse_args(argv)

    none = _load(os.path.join(args.out, "none"))
    print("=" * 80)
    print("  DID THE CATCH MATTER? — per-task verifier flips vs the none baseline")
    print("=" * 80)
    print(f"  {'arm':<8}{'caught-mint tasks':>18}{'help-flips':>12}{'hurt-flips':>12}"
          f"{'net':>7}{'mattered%':>11}")
    print("-" * 80)
    for arm in args.arms:
        adir = os.path.join(args.out, arm)
        if not os.path.isdir(adir):
            continue
        other = _load(adir)
        common = sorted(set(none) & set(other))
        caught_tasks = help_flips = hurt_flips = mattered_tasks = 0
        for t in common:
            r_arm = _run0(other[t])
            if _caught(r_arm) == 0:
                continue
            caught_tasks += 1
            vn = _verifiers(_run0(none[t]))
            va = _verifiers(r_arm)
            task_helped = False
            for k in set(vn) & set(va):
                if not vn[k] and va[k]:
                    help_flips += 1
                    task_helped = True
                elif vn[k] and not va[k]:
                    hurt_flips += 1
            if task_helped:
                mattered_tasks += 1
        net = help_flips - hurt_flips
        mrate = (100.0 * mattered_tasks / caught_tasks) if caught_tasks else 0.0
        print(f"  {arm:<8}{caught_tasks:>18}{help_flips:>12}{hurt_flips:>12}"
              f"{net:>+7}{mrate:>10.1f}%")
    print("-" * 80)
    print("  help-flips: a verifier the baseline FAILED that this arm PASSED (catch fixed a")
    print("  checked FK). hurt-flips: the reverse (disruption broke a step). net = help - hurt.")
    print("  mattered% = caught-mint tasks with >=1 help-flip (the live mattered-rate proxy).")
    print("  CAVEAT: arms are not verifier-paired (fresh DB + stochastic model), so a single")
    print("  flip can be noise — trust the AGGREGATE net across many tasks.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
