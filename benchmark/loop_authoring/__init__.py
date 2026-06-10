"""loop_authoring — the head-to-head: a prose-applied loop state-machine vs. the
kernel's pure `loop_decide.decide`, on realistic trajectories, priced in wasted
launches/markers, with the fleet-scale multiplier as the headline.

This is the docs/260 proof. The claim under test: *DOS helps you WRITE a loop
(call a function) vs. PROMPT one (trust prose to apply the stop logic).*

The crux that escapes the consistency-is-not-grounding trap (docs/260 §2): the
reference is NOT another model's opinion — it is `loop_decide.decide`, a pure
function pinned by 101 cases in `tests/test_oracle_and_loop.py`. We measure
whether a prose-applied state machine *reproduces* a deterministic one, a question
with a computable answer.

Modules:
  generate   — property-based trajectory generator (walks the kernel's own
               transition relation; the honest distribution per docs/260 §4).
  prose_arm  — Arm P: the prose-applied decision. A pluggable `ProseDecider`
               protocol so a LIVE model drops in for Step 2; ships a faithful-but-
               lossy SIMULATED decider for Step 1 (free, no spend) that models the
               documented prose-drop on the interacting invariants.
  score      — the divergence detector + the per-divergence cost pricing + the
               1-(1-d)^K fleet roll-up (docs/260 §4 headline).
  run        — the CLI: `python -m benchmark.loop_authoring.run`.
"""
