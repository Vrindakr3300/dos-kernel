"""Pins for the loop_authoring harness (docs/260 Step 1).

The load-bearing guarantee: the scorer never MANUFACTURES a divergence. If the
prose arm reproduces the kernel exactly (the `faithful` drop-rates), `d` MUST be
0 — every divergence the scorer reports is a real disagreement injected by the
drop model, not an artifact of the comparison. This is the identity test that
keeps the headline honest.
"""

from __future__ import annotations

from benchmark.loop_authoring.generate import OutcomeMix, generate_corpus, generate_trajectory
from benchmark.loop_authoring.prose_arm import DropRates, SimulatedProseDecider
from benchmark.loop_authoring.score import Pricing, score_corpus


def test_faithful_prose_gives_zero_divergence():
    """A perfect prose applier reproduces the kernel → d == 0 (no manufactured div)."""
    corpus = generate_corpus(200, base_seed=0, mix=OutcomeMix.stress())
    decider = SimulatedProseDecider(drops=DropRates.faithful(), seed=1)
    score = score_corpus(corpus, decider, Pricing())
    assert score.total_ticks > 1000  # the corpus is non-trivial
    assert score.total_divergences == 0
    assert score.d == 0.0
    assert score.net_usd == 0.0


def test_lossy_prose_diverges_only_on_hard_rungs():
    """With the default (lossy) drop-rates, divergences land on the interacting
    invariants — never on the easy caps the model gets right."""
    corpus = generate_corpus(500, base_seed=0, mix=OutcomeMix.stress())
    decider = SimulatedProseDecider(drops=DropRates(), seed=7)
    score = score_corpus(corpus, decider, Pricing())
    assert score.total_divergences > 0
    # The easy rungs (iteration-cap, a clean first DRAIN, SHIPPED-CLEAN) must NOT
    # appear in the by-rung breakdown — their drop-rate is 0.
    assert "iteration-cap" not in score.divergence_by_rung
    # The hard rungs the §3 table predicts SHOULD dominate.
    hard = {"drained-twice", "replan-stalled", "stale-stamp-unreconciled", "overloaded_backoff"}
    assert hard & set(score.divergence_by_rung), score.divergence_by_rung


def test_fleet_multiplier_is_monotone_increasing():
    """The headline: P(some loop wrong) and E[waste] grow with fleet size K."""
    corpus = generate_corpus(800, base_seed=0, mix=OutcomeMix.stress())
    decider = SimulatedProseDecider(drops=DropRates(), seed=7)
    score = score_corpus(corpus, decider, Pricing())
    rows = score.fleet([1, 4, 16, 32], horizon=40)
    ps = [r["p_some_loop_wrong_per_round"] for r in rows]
    es = [r["expected_wasted_usd_over_horizon"] for r in rows]
    assert ps == sorted(ps) and ps[0] < ps[-1]
    assert es == sorted(es) and es[0] < es[-1]
    # The compounding is super-linear in K vs. the single-loop rate.
    assert ps[-1] > 32 * ps[0] * 0.5  # not merely linear scaling of a tiny d


def test_trajectory_terminates_at_kernel_stop():
    """A generated trajectory ends exactly when the kernel STOPs (or horizon)."""
    ticks = generate_trajectory(seed=3, mix=OutcomeMix.stress(), horizon=40)
    assert len(ticks) >= 1
    last = ticks[-1].kernel_decision
    # Either the kernel stopped on the last tick, or we hit the horizon cap.
    assert last.action == "stop" or len(ticks) == 40
