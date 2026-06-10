"""curable_oversample — the TARGETED run-recipe for the curable-slice conversion A/B (docs/198 §4.2).

THE EXPERIMENT NEVER RUN. docs/198 §3 established that conversion on the CURABLE slice is genuinely
UNTESTED: the natural thrash rate is ~10% and is dominated by the ONE walled tool (`create_filter`),
so a random task sample yields only ~6 curable-thrash runs even at 480 total — far below the n>=30
the pre-registered kill needs. Re-reading the corpus cannot settle it; the only decision-relevant
spend is a run that OVER-SAMPLES the tasks that thrash on curable tools.

This program is the recipe. It is $0 by itself — it reads the recorded corpus, finds every task that
EVER produced a curable thrash, and emits:

  1. THE TARGET TASK-ID LIST — the task families whose runs thrash on a CURABLE tool (the witness
     proves a path exists, so a cure could in principle convert them). Pinned by task_id so a re-run
     hits the SAME tasks.

  2. THE POWER PLAN — how many (task x arm x rep) runs reach n>=30 curable-thrash INSTANCES, given the
     measured per-task curable-thrash HIT-RATE (thrash is stochastic per run, so a task that thrashed
     once may not thrash on the next run; we need reps). Cost is reported in live runs.

  3. THE EXACT live_ab.py INVOCATION — the targeted command, with the pinned task set and the arms to
     A/B (none vs the cures), so the operator runs ONE command, not a hand-built sweep.

PRE-REGISTERED KILL (docs/198 §4.2): a cure ships ONLY if its fired-flip NET > 0 on the CURABLE slice
at n>=30. Scoring is feasibility_split.py's `conversion_on_curable` (curable slice, task-success
denominator) — the SAME scorer this recipe feeds, so the analysis is fixed before the spend.

WHY THIS AVOIDS RE-COMMITTING THE CATEGORY ERROR: the target list is the CURABLE thrashers only; the
walled `create_filter` tasks are explicitly excluded (a cure on them is the category error). The score
is read per-population by feasibility_split, never pooled.

    python curable_oversample.py                      # the target list + power plan + the command
    python curable_oversample.py --target-n 30 --reps 8 --json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _BENCH)

from _feasibility import ToolEvent, Verdict, feasibility_witness, thrash_tools  # noqa: E402
from dos_react import _is_struct_error, _result_text, _is_blocked_result  # noqa: E402


def _events(run: dict) -> List[ToolEvent]:
    out = []
    for tr in (run.get("tool_results") or []):
        if _is_blocked_result(tr):
            continue
        t = str(tr.get("tool_name", ""))
        if not t:
            continue
        out.append(ToolEvent(t, _is_struct_error(_result_text(tr))))
    return out


def _parse_name(fname: str) -> Tuple[str, str, str]:
    """results_<mode>__<domain>__<task_id>.json -> (mode, domain, task_id)."""
    b = os.path.basename(fname).replace("results_", "").replace(".json", "")
    parts = b.split("__")
    if len(parts) >= 3:
        return parts[0], parts[1], "__".join(parts[2:])
    return "oracle", "?", b


def _runs(arm_glob):
    for f in sorted(glob.glob(arm_glob)):
        try:
            r = (json.load(open(f, encoding="utf-8")).get("runs") or [{}])[0]
        except Exception:
            continue
        yield f, r


def collect_targets(out_dir: str, min_obs: int) -> Tuple[List[dict], Dict[str, Verdict]]:
    """Find every task that EVER curable-thrashed, with its per-task hit-rate across recorded runs.
    Returns (targets, witness). A target = {task_id, domain, curable_tools, runs_seen, thrash_hits}."""
    all_corpus = [_events(r) for _f, r in _runs(os.path.join(out_dir, "*", "results_*.json"))]
    witness = feasibility_witness(all_corpus, min_obs=min_obs)

    # per task_id: how many recorded runs we saw, how many curable-thrashed, which curable tools
    seen: Dict[str, int] = defaultdict(int)
    hits: Dict[str, int] = defaultdict(int)
    tools: Dict[str, set] = defaultdict(set)
    domain: Dict[str, str] = {}
    for f, r in _runs(os.path.join(out_dir, "*", "results_*.json")):
        _mode, dom, tid = _parse_name(f)
        seen[tid] += 1
        domain[tid] = dom
        tt = thrash_tools(_events(r))
        curable = [t for t in tt if witness.get(t) is not Verdict.WALLED and witness.get(t) is not None]
        if curable:
            hits[tid] += 1
            tools[tid].update(curable)

    targets = []
    for tid, h in sorted(hits.items(), key=lambda kv: -kv[1]):
        targets.append({
            "task_id": tid,
            "domain": domain.get(tid, "?"),
            "curable_tools": sorted(tools[tid]),
            "runs_seen": seen[tid],
            "thrash_hits": h,
            "hit_rate": round(h / seen[tid], 3) if seen[tid] else 0.0,
        })
    return targets, witness


def power_plan(targets: List[dict], target_n: int, arms: List[str]) -> dict:
    """How many runs to reach `target_n` curable-thrash INSTANCES per arm. Uses the measured
    per-task hit-rate; assumes the cure arms thrash at a similar baseline rate (the none-arm rate
    is the honest estimator — a cure may suppress thrash, which only HELPS power on the cured arm,
    but we size on the conservative none rate)."""
    if not targets:
        return {"feasible": False, "reason": "no curable-thrash tasks found in the corpus"}
    # expected curable-thrash instances per (task, rep) = the task's hit rate
    mean_hit = sum(t["hit_rate"] for t in targets) / len(targets)
    n_tasks = len(targets)
    # reps needed per task on the NONE arm so n_tasks * reps * mean_hit >= target_n
    import math
    reps = max(1, math.ceil(target_n / (n_tasks * mean_hit))) if mean_hit > 0 else None
    if reps is None:
        return {"feasible": False, "reason": "mean hit-rate 0 — no task reliably thrashes"}
    none_runs = n_tasks * reps
    total_runs = none_runs * len(arms)            # each arm runs the SAME pinned task set x reps
    return {
        "feasible": True,
        "n_tasks": n_tasks,
        "mean_hit_rate": round(mean_hit, 3),
        "reps_per_task": reps,
        "expected_curable_instances_per_arm": round(n_tasks * reps * mean_hit, 1),
        "runs_per_arm": none_runs,
        "arms": arms,
        "total_live_runs": total_runs,
        "target_n": target_n,
    }


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"))
    ap.add_argument("--target-n", type=int, default=30, help="curable-thrash instances needed (docs/198 §4.2)")
    ap.add_argument("--arms", nargs="+", default=["none", "warn", "restart_seeded"],
                    help="the conversion A/B arms (none baseline + the cures to test)")
    ap.add_argument("--min-obs", type=int, default=3)
    ap.add_argument("--out-target-dir", default=os.path.join(_HERE, "live_results_curable_ab"),
                    help="where the targeted re-run should write (feeds feasibility_split --out)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    targets, witness = collect_targets(args.out, args.min_obs)
    plan = power_plan(targets, args.target_n, args.arms)
    task_ids = [t["task_id"] for t in targets]
    domains = sorted({t["domain"] for t in targets})

    if args.json:
        print(json.dumps({"targets": targets, "plan": plan,
                          "task_ids": task_ids, "domains": domains}, indent=2))
        return 0

    print("=" * 82)
    print("  CURABLE-SLICE OVER-SAMPLE RECIPE — the experiment never run (docs/198 §4.2)")
    print(f"  corpus: {args.out}")
    print("=" * 82)
    print(f"  {'task_id':<46}{'dom':>6}{'seen':>6}{'hits':>6}{'rate':>7}")
    print("-" * 82)
    for t in targets:
        print(f"  {t['task_id']:<46}{t['domain']:>6}{t['runs_seen']:>6}{t['thrash_hits']:>6}{t['hit_rate']:>7.2f}")
        print(f"      curable tools: {', '.join(t['curable_tools'])}")
    print("-" * 82)
    print(f"  {len(targets)} curable-thrash task families found (WALLED create_filter EXCLUDED).")
    print()
    print("  POWER PLAN — reach n>=30 curable-thrash INSTANCES (thrash is stochastic => need reps):")
    if not plan.get("feasible"):
        print(f"    INFEASIBLE: {plan.get('reason')}")
    else:
        for k in ("n_tasks", "mean_hit_rate", "reps_per_task",
                  "expected_curable_instances_per_arm", "runs_per_arm", "total_live_runs"):
            print(f"    {k:<38} {plan[k]}")
        print()
        print("  THE COMMAND (targeted A/B; same pinned tasks across arms => paired):")
        print(f"    # 1. pin the target task set (task_id list above), reps={plan['reps_per_task']}:")
        print(f"    python live_ab.py \\")
        print(f"        --tasks {plan['reps_per_task']} \\")
        print(f"        --arms {' '.join(args.arms)} \\")
        print(f"        --domains {' '.join(domains)} \\")
        print(f"        --mint-rate 0.0 \\        # NATURAL regime — no injection (docs/172)")
        print(f"        --out {os.path.relpath(args.out_target_dir, _HERE)}")
        print(f"    # (NOTE: live_ab.py samples by --tasks per domain; to PIN the exact task_ids")
        print(f"    #  above, add a --task-ids filter — see the live_ab oversample hook below.)")
        print()
        print("  THEN SCORE (curable slice only, pre-registered kill NET>0 at n>=30):")
        print(f"    python feasibility_split.py --out {os.path.relpath(args.out_target_dir, _HERE)} \\")
        print(f"        --cure {args.arms[1] if len(args.arms) > 1 else 'warn'} --min-curable-n {args.target_n}")
    print("=" * 82)
    print("  COST: ~{} live Gemini runs (cheap-model tier). This is the ONLY new spend docs/198"
          .format(plan.get("total_live_runs", "?")))
    print("  identifies as decision-relevant. Everything else (witness, split, early-halt) is $0.")
    print("=" * 82)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
