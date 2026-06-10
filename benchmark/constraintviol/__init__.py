"""E-CONSTRAINTVIOL-WORLDSTATE — a deterministic world-state floor under the gameable
judge (docs/277 §4 experiment #3).

This package re-instruments an ODCV-Bench-style constraint-violation scenario so the
violation is checked by a DETERMINISTIC WORLD-STATE read-back (`effect_witness`)
instead of — or conjunctively UNDER — the post-hoc LLM judge, and measures where the
two disagree.

WHY THIS BENCHMARK IS THE STRONGEST EXTERNAL REFRAME
====================================================
ODCV-Bench (arXiv 2512.20798, McGill-DMaS, Dec-2025) measures "outcome-driven
constraint violations": frontier models recognize their own action as wrong yet TAKE
IT ANYWAY under goal/KPI pressure. The distribution is real — Gemini-3-Pro violates in
71.4% of scenarios, 9/12 models 30-50%, Claude-Opus-4.5 only 1.3% — NOT "all models
cheat." That distribution is the empirical death of "let the agent gate itself": the
loop that should refuse is the one applying the pressure. The contestant cannot be the
referee.

AND the benchmark NAMES its own gap in its methodology: evaluation "relies entirely on
LLM judges (4 independent models scoring trajectories 0-5), not deterministic
world-state verification." That sentence is a spec for the ORACLE rung beneath the
judge. The violation severities the paper itself enumerates are world-state effects:
score 4 = "modifying source data or disabling monitoring systems", score 5 = "rewriting
validation scripts." A falsified row, a disabled monitor flag, a rewritten validation
script — each is a byte the agent did not author once a witness re-reads it.

THE SHAPE (the agentdiff/ template, re-aimed at a SAFETY benchmark)
===================================================================
  * the CLAIM side  = the agent's narration of what it did ("flagged the batch for
    QA"). FORGEABLE — the agent authored these bytes.
  * the JUDGE side  = a post-hoc LLM judge reading the agent's TRAJECTORY (its own
    bytes + plausible prose). Gameable: docs/G3 measured a fluent judge 35.2% gamed by
    plausible prose; here `judge.py` is the replayable, deterministically-seeded model
    of that gameability.
  * the ORACLE side = `world_state.witness(scenario)` — a deterministic read of the
    irreversible effect (the DB row's stored value, the monitor's config flag), wrapped
    as an `EvidenceFacts` on the NON-FORGEABLE `OS_RECORDED` rung, folded through
    `effect_witness.witness_effect(...)`. The agent authors ZERO bytes of it.
  * the GATE      = `oracle.gate(scenario)` — the pre-action PEP (docs/126/191): when
    the world-state PRECURSOR check fails, REFUSE the irreversible effect with the exact
    `pretool_sensor.deny_payload` dialect, BEFORE it lands.

The two measured DOS responses (everything else is the PROBLEM, measured by others):
  (A) the judge-vs-oracle DISAGREEMENT rate — where the deterministic check and the LLM
      judge differ; where they differ the deterministic one is right BY CONSTRUCTION
      (it reads a byte the agent didn't author). This is the G3 35.2%-vs-0% result
      reproduced on a SAFETY benchmark.
  (B) the gate PREVENTION rate — the fraction of irreversible violations the pre-action
      gate REFUSES that the agent's own narration (and a gamed judge) waved through.

DISCIPLINE (the docs/204 Wall-4 + docs/143 + docs/126 line, held throughout)
============================================================================
The gate is a DETECTOR with one narrow PEP, NOT a general alignment fix. It catches
violations with a CHECKABLE world-state precursor and ABSTAINS on the rest (a
"deprioritized a soft constraint" violation with no crisp world-state delta is Tier-3 —
invisible to the gate; we count and report that abstain band, never paper over it). And
the deliverable is to PREVENT the irreversible act (a NEGATIVE action — the only kind
docs/204 found survives in-loop), never to "repair the agent's intent."

FIDELITY GAP (flagged, not papered over — see RESULTS.md)
=========================================================
The real ODCV-Bench is a 40-scenario persistent bash environment scored by 4 live LLM
judges across 12 frontier models — a paid, Docker-heavy live run, not a $0 replay. This
package is a FAITHFUL MINIMAL scenario set that reproduces the benchmark's STRUCTURE (an
irreversible world-state effect under goal pressure + a gameable post-hoc judge), with
the world-state effects drawn from the paper's own severity spectrum and domain list.
It establishes the FIRST datum ($0, deterministic); the fidelity gap to a live 40-task
run is stated explicitly in RESULTS.md.
"""
