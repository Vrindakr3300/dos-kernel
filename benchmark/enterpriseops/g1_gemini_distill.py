"""G1 — E1's non-distillability falsifier on LIVE GEMINI behavior, goal-witnessed (docs/206 §5b).

E1 ran the distillation on real Claude git-commit claims — but that label is W2
*presence* (did a commit land), not W3 *goal* (is the result correct). The
EnterpriseOps-Gym closes that gap: every task ships per-sub-goal **DB-state verifiers**
(`verification_results`) that read the world, not the agent's word — a non-agent-authored
GOAL witness. The gym has been run on `gemini-2.5-flash` many times; `live_results*/`
holds 1800+ real runs. This reads them with ZERO new API spend and asks E1's question on
that goal-witness:

    Can a cheap claim-side model distil the gym verifier's GOAL verdict, or is it
    irreducible — i.e. is a sub-goal the model ACTED on but silently failed
    shape-identical to one it really achieved?

THE STEP (the G1 unit) is a single VERIFIER (sub-goal) within a run:
  * LABEL `really_committed` := the DB verifier passed (goal achieved) — W3, world-read.
  * FEATURES (believer-visible only): did the model act at all (tools_used>0), how many
    tools it ran, how long its final narration was, how many tool-results it got back,
    whether its final narration asserts success. NONE of these is the verifier outcome —
    a believer folding the result sees exactly this much.

The expected result mirrors E1: claim-side shape recovers the gross structure (a run
that ran no tools achieves no goals) but hits a CEILING on the **silent-failure residue**
— a sub-goal the model worked on, narrated done, and still failed the DB check is
shape-identical to one it achieved. That residue is docs/177 frontier-silent failure,
and only the world-read verifier separates it from success. If the residue reproduces
here, E1's non-distillability is confirmed on a real frontier model AND on a goal
witness (past Wall 3).

Reuses `benchmark.fleet_horizon.verifier.score_feature_set` UNCHANGED via the shared
TrajectoryStep contract. Run:
    PYTHONPATH=src python -m benchmark.enterpriseops.g1_gemini_distill
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

# benchmark/ on path so we can reach fleet_horizon's scorer + TrajectoryStep.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from fleet_horizon.trajectory import TrajectoryStep  # noqa: E402
from fleet_horizon import verifier as _verifier      # noqa: E402


def _as_text(v) -> str:
    """model_response may be a str or a list of content blocks; flatten to text."""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        out = []
        for c in v:
            if isinstance(c, str):
                out.append(c)
            elif isinstance(c, dict):
                out.append(c.get("text", "") or c.get("content", "") or "")
        return " ".join(out)
    if isinstance(v, dict):
        return v.get("text", "") or ""
    return ""


def _assert_success(text_or_blocks) -> bool:
    """Does the model's final narration ASSERT success? (believer-visible claim tell)."""
    text = _as_text(text_or_blocks)
    if not text:
        return False
    low = text.lower()
    pos = ("success" in low or "completed" in low or "done" in low
           or "have created" in low or "successfully" in low or "all set" in low)
    neg = ("unable" in low or "could not" in low or "couldn't" in low
           or "failed" in low or "error" in low and "no error" not in low)
    return pos and not neg


def steps_from_run(run: dict, *, session: str, base_step: int) -> list[TrajectoryStep]:
    """One run -> one TrajectoryStep per DB verifier (sub-goal)."""
    vr = run.get("verification_results", {}) or {}
    tools_used = run.get("tools_used", []) or []
    tool_results = run.get("tool_results", []) or []
    narration = run.get("model_response", "") or ""
    acted = len(tools_used) > 0
    n_tools = len(tools_used)
    asserts = _assert_success(narration)

    steps: list[TrajectoryStep] = []
    for i, (vname, vres) in enumerate(sorted(vr.items())):
        if isinstance(vres, dict):
            passed = bool(vres.get("passed"))
            # some shapes store {'passed': 0/1, 'total': 1}; treat passed>=total as pass
            if "total" in vres and "passed" in vres:
                passed = vres["passed"] >= vres["total"] and vres["total"] > 0
        else:
            passed = bool(vres)
        steps.append(TrajectoryStep(
            step=base_step + i,
            effort=session,
            phase_id=f"{session}:{vname}",
            run_id=session,
            root_id=session,
            # FEATURES — believer-visible only. We MAP the gym signals onto the existing
            # feature names so verifier.score_feature_set runs unchanged:
            #   claimed_shipped   := the model asserted success in its narration
            #   n_files_written   := how many tools it ran (its claimed footprint)
            #   touches_shared    := did it get tool-results back (it really interacted)
            #   is_rework         := unused here (False)
            #   sha_looks_real    := did it ACT at all (the surface tell; ablated)
            claimed_shipped=asserts,
            claimed_sha=("acted" if acted else ""),
            n_files_written=n_tools,
            touches_shared=len(tool_results) > 0,
            is_rework=False,
            sha_looks_real=acted,
            # LABEL — the DB-state GOAL verifier (W3, world-read, non-agent-authored).
            really_committed=passed,
            real_sha=(vname if passed else ""),
            verdict_shipped=passed,
            verdict_source=("registry" if passed else "none"),
            is_caught_lie=bool(asserts and not passed),   # asserted done, goal failed
            arbiter_outcome="acquire",
            refusal_reason="",
        ))
    return steps


def build_corpus(results_glob: str) -> list[TrajectoryStep]:
    files = sorted(glob.glob(results_glob, recursive=True))
    steps: list[TrajectoryStep] = []
    n = 0
    for f in files:
        try:
            r = json.load(open(f, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        model = (r.get("benchmark_config", {}) or {}).get("model", "")
        if "gemini" not in model.lower():
            continue
        stem = Path(f).stem
        for ri, run in enumerate(r.get("runs", []) or []):
            steps.extend(steps_from_run(run, session=f"{stem}#{ri}", base_step=n))
            n += 1
    return steps


def summary(steps: list[TrajectoryStep]) -> dict:
    n = len(steps)
    achieved = sum(1 for s in steps if s.really_committed)
    # silent failure = the model ASSERTED success but the goal verifier failed
    silent = sum(1 for s in steps if s.claimed_shipped and not s.really_committed)
    return {
        "verifier_steps": n,
        "runs": len({s.run_id for s in steps}),
        "goal_achieved": achieved,
        "goal_failed": n - achieved,
        "silent_failures": silent,
        "base_rate": round(max(achieved, n - achieved) / n, 3) if n else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="G1 — distil the gym GOAL verdict from live Gemini behavior (docs/206 §5b)")
    ap.add_argument("--glob", default=os.path.join(_HERE, "live_results*", "**", "results_*.json"))
    ap.add_argument("--seed", type=int, default=1729)
    args = ap.parse_args(argv)

    steps = build_corpus(args.glob)
    s = summary(steps)
    if s["verifier_steps"] < 30:
        print(f"too few verifier-steps ({s['verifier_steps']}); need >=30.")
        return 1

    full = _verifier.score_feature_set(steps, seed=args.seed)
    ablated_names = [n for n in _verifier.FEATURE_ORDER if n != _verifier.ARTIFACT_FEATURE]
    ablated = _verifier.score_feature_set(steps, seed=args.seed, feature_names=ablated_names)

    print("=" * 78)
    print("G1 — distil the gym GOAL verdict from LIVE GEMINI behavior (docs/206 §5b)")
    print("=" * 78)
    print(f"\nCorpus: {s['verifier_steps']} DB-verifier sub-goals across {s['runs']} "
          f"real gemini-2.5-flash runs")
    print(f"  goal achieved (label 1) {s['goal_achieved']} / failed {s['goal_failed']} "
          f"(base rate {s['base_rate']})")
    print(f"  SILENT failures (model asserted success, DB goal failed): {s['silent_failures']}")
    print(f"  train/test: {full.n_train}/{full.n_test} "
          f"(label = gym DB-state verifier passed -- W3 goal, world-read)\n")

    print("Can claim-side shape predict the GOAL verdict better than guessing?")
    print(f"  {full.headline()}")
    print(f"  {ablated.headline()}")
    print(f"  weights (ablated): {ablated.weights}")

    a = ablated
    print("\nThe irreducible residue (the goal-witness git/DB CANNOT be distilled out of):")
    print(f"  asserted-success-but-goal-failed in test set : {a.lies_total}")
    print(f"    +- gross misses (no real action) flagged    : "
          f"{a.pure_lies_caught}/{a.lies_total - a.flakes_total}  <- learnable from shape")
    print(f"    +- SILENT failures (acted+narrated, goal failed) : "
          f"caught {a.flakes_caught}/{a.flakes_total}  "
          f"<- shape-identical to success; only the DB verifier separates them")

    print("\nReading (docs/206 §5b G1), ON LIVE GEMINI + A GOAL WITNESS:")
    if a.flakes_total > 0 and a.flakes_caught < a.flakes_total:
        print("  -> CONFIRMED on a real frontier model AND on W3 goal-witnessing: claim-side")
        print("     shape catches the gross misses but CANNOT separate a silently-failed")
        print("     sub-goal from an achieved one -- only the world-read DB verifier can.")
        print("     E1's non-distillability holds past Wall 3. This is the strongest form.")
    elif a.accuracy <= a.base_rate + 1e-6:
        print("  -> NO distillation: claim-side shape carries no signal beyond base rate.")
    else:
        print("  -> NULL: the verifier beats base rate AND clears the silent-failure residue")
        print("     -> the GOAL verdict is distillable on this corpus; report honestly.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
