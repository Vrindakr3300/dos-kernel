"""The docs/143 §13 intervention A/B on the faithful simulator — WARN vs BLOCK vs DEFER.

The companion to `run_ab.py`. Where `run_ab.py` proves the `arg_provenance` *detector*
(does the nudge lift the Integrity slice?), this proves the §13 *intervention* thesis (given
a sound detector, which ACTUATION maximizes net task delta?). It is the mechanism behind the
live "⚑ KEY DATA POINT": a sound verdict (0 % false-nudge, 83 % recall) was net-HARMFUL
(−9 pp) because the SKIP-and-re-prompt intervention (DEFER) derailed the model — even on a
true-positive catch, and worst on the catches the verifier never checked.

It builds labelled `dos.intervention_eval.InterventionCase`s from the SAME generative model
the simulator uses (the real `classify_call` produces each verdict; the generative model
holds the ground-truth `truly_minted` / `mattered_to_score` / recovery), then scores three
policies through the REAL `dos.intervention_eval.score`:

  * DEFER  — skip + re-prompt (the −9 pp posture). Withholds the turn.
  * WARN   — inform + still dispatch (the advisory default). Never withholds.
  * BLOCK  — refuse + synthetic corrective result (the §13.4 non-disruptive PEP). Withholds
             the turn but PRESERVES it (the agent recovers without losing the iteration).

The headline is `net_task_delta` per policy, directly comparable to the live −9 pp. The
result the §13 double-down predicts: DEFER is net-harmful on a corpus with irrelevant
catches; BLOCK turns that around (same catches, lower disruption, turn preserved); WARN sits
near zero (safe but no prevention on an irreversible DB).

Run:
    python -m benchmark.enterpriseops.intervention_ab
    python -m benchmark.enterpriseops.intervention_ab --tasks 2000 --seeds 5
"""

from __future__ import annotations

import argparse
import random
import statistics

from dos.arg_provenance import (
    CorpusSource,
    EnvBlob,
    PriorResults,
    ProvenancePolicy,
    ToolArg,
    ToolCall,
    classify_call,
)
from dos.intervention import Confidence, InterventionPolicy, assess_confidence
from dos.intervention_eval import InterventionCase, score

from .simulator import SimParams, _agent_choose_fk, generate_task


def _build_cases(seed: int, n_tasks: int, params: SimParams,
                 prov_policy: ProvenancePolicy | None = None,
                 *, mattered_rate: float = 0.65, q_recover_block: float = 0.85,
                 q_recover_defer: float = 0.75) -> list[InterventionCase]:
    """Generate labelled intervention cases from the simulator's generative model.

    For each MUTATE step the cheap agent makes an FK choice (`_agent_choose_fk` — the real
    policy), the REAL `classify_call` produces the verdict over the accumulated env corpus,
    and the generative model supplies the GROUND-TRUTH labels the eval needs:

      * truly_minted          — the generative model's `is_minted` flag (a coincidental mint
                                that traces is truly_minted=True but the detector won't fire,
                                so it never becomes a case — only FIRED verdicts are cases).
      * mattered_to_score     — drawn at `mattered_rate` (a fraction of FKs feed a verifier;
                                the rest are the −9 pp "true catch the verifier ignored" cell).
                                A false-flag (legit derived id) has mattered=False.
      * recovered_if_blocked  — at `q_recover_block` (turn-PRESERVING → higher recovery).
      * recovered_if_deferred — at `q_recover_defer` (turn-SPENDING → the measured ~75 %).

    Only verdicts that FIRED (`not believe`) become cases — an un-fired verdict triggers no
    intervention, so it is not part of the actuation eval (the consumer dispatches it
    untouched). This is the honest denominator: the eval scores the intervention on exactly
    the calls the detector flagged.
    """
    prov_policy = prov_policy or ProvenancePolicy()
    gen = random.Random(seed)
    cases: list[InterventionCase] = []
    for _ in range(n_tasks):
        task = generate_task(gen, params, feasible=True)
        agent = random.Random(gen.randint(0, 2**31))
        env_blobs = [EnvBlob(text=task.task_text, source=CorpusSource.TASK_TEXT)]
        emitted_by_kind: dict[str, list[str]] = {}
        depth = 0
        for step in task.steps:
            if step.kind == "read":
                emitted_by_kind.setdefault(step.id_kind, []).append(step.gold)
                env_blobs.append(EnvBlob(
                    text=f'{{"id": "{step.gold}", "number": "{step.gold}"}}',
                    source=CorpusSource.TOOL_RESULT,
                ))
                continue
            depth += 1
            pool = emitted_by_kind.get(step.id_kind, [])
            val, correct, minted, derived = _agent_choose_fk(agent, step, params, depth, pool)
            call = ToolCall(
                tool_name="update_record",
                args=(ToolArg(name=step.fk_arg, value=val, is_reference=True),),
                is_mutating=True,
            )
            verdict = classify_call(call, PriorResults(blobs=tuple(env_blobs)), prov_policy)
            if verdict.believe:
                continue  # the detector did not fire → no intervention → not a case
            # a fired verdict — label it from the generative ground truth.
            mattered = (not derived) and (agent.random() < mattered_rate)
            cases.append(InterventionCase(
                verdict=verdict,
                truly_minted=bool(minted),       # False ⟺ a false-flag (legit derived id)
                mattered_to_score=mattered,
                recovered_if_blocked=(agent.random() < q_recover_block),
                recovered_if_deferred=(agent.random() < q_recover_defer),
                label=f"{assess_confidence(verdict).value}/{'minted' if minted else 'derived'}",
            ))
    return cases


_POLICIES = {
    "DEFER (skip+re-prompt, the -9pp posture)":
        InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="DEFER", ceiling="DEFER"),
    "WARN (inform+dispatch, advisory default)":
        InterventionPolicy(on_high_confidence="WARN", on_low_confidence="WARN", ceiling="WARN"),
    "BLOCK confidence-gated (the s13 PEP)":
        InterventionPolicy(),   # HIGH->BLOCK, LOW->WARN, ceiling=BLOCK
}


def headline(n_tasks: int, seeds: list[int], params: SimParams) -> dict:
    print("=" * 86)
    print(f"  EnterpriseOps-Gym INTERVENTION A/B - {n_tasks} tasks x {len(seeds)} seeds")
    print("  (the SAME dos.intervention_eval the kernel ships scores each policy)")
    print("=" * 86)
    print(f"{'Policy':<44}{'net delta':>12}{'wasted':>9}{'danger':>9}{'cov':>7}")
    print("-" * 86)
    results: dict[str, float] = {}
    # build one shared corpus per seed so all policies are scored on the SAME cases (paired).
    corpora = [_build_cases(s, n_tasks, params) for s in seeds]
    for name, policy in _POLICIES.items():
        nets, wasted, danger, cov = [], [], [], []
        for cases in corpora:
            r = score(policy, cases)
            nets.append(r.net_task_delta)
            wasted.append(r.wasted_disruption_rate)
            danger.append(r.dangerous_cell_rate)
            cov.append(r.coverage)
        nm = statistics.mean(nets)
        results[name] = nm
        print(f"{name:<44}{nm:>+12.4f}{statistics.mean(wasted):>9.2f}"
              f"{statistics.mean(danger):>9.2f}{statistics.mean(cov):>7.2f}")
    print("-" * 86)
    n_cases = statistics.mean(len(c) for c in corpora)
    print(f"  fired verdicts (cases) / seed: {n_cases:.0f}")
    defer = results["DEFER (skip+re-prompt, the -9pp posture)"]
    warn = results["WARN (inform+dispatch, advisory default)"]
    block = results["BLOCK confidence-gated (the s13 PEP)"]
    # BLOCK vs DEFER: the turn-preserving rung beats the turn-spending one (the s13.4 claim).
    print(f"  BLOCK - DEFER swing: {block - defer:+.4f}  "
          f"({'BLOCK beats DEFER' if block > defer else 'no win'})")
    # BLOCK vs WARN: the HONEST baseline (WARN was the docs/143 LIVE winner, not DEFER). At
    # this fixed point BLOCK may NOT beat WARN — that depends on mattered_rate (see
    # intervention_theories sweep 2: BLOCK overtakes WARN only when mattered_rate >~ 0.80).
    print(f"  BLOCK - WARN swing:  {block - warn:+.4f}  "
          f"({'BLOCK beats WARN' if block > warn else 'WARN still wins (low mattered-rate regime)'})")
    gate = "PASS" if block > defer else "CHECK"
    print(f"  s13.4 GATE (BLOCK > DEFER - turn-preserving beats turn-spending): {gate}")
    print(f"  NOTE: the REAL baseline is WARN; run `intervention_theories` for the BLOCK>WARN region.")
    print("=" * 86)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tasks", type=int, default=690,
                    help="tasks per seed (default 690 = the public-split size)")
    ap.add_argument("--seeds", type=int, default=3, help="number of seeds (default 3)")
    args = ap.parse_args(argv)
    headline(args.tasks, list(range(1, args.seeds + 1)), SimParams())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
