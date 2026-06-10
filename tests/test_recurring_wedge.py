"""Tests for dos.recurring_wedge — the pure recurring-blocker fold.

PURE: every test passes prior BlockerHits in directly (no disk, no mining), so
the recurring-vs-one-off decision is exercised in isolation. The cause_key is an
opaque grouping string here — the kernel never interprets it (a host's taxonomy
owns what each key means). These cases are the kernel half of the host's
`tests/test_dispatch_loop_recurring_wedge.py`, lifted to the frozen-fold layer.
"""
from __future__ import annotations

from dos.recurring_wedge import (
    BlockerHit,
    build_clusters,
    classify_recurring_wedge,
)


def _hit(run: str, cause_key: str, *, example: str = "x") -> BlockerHit:
    return BlockerHit(
        run=run, iter_n=1, cause_key=cause_key, cost_usd=1.0, wall_min=5.0,
        example=example, source="dispatch-loop",
    )


def test_one_off_wedge_not_routed():
    """A cause that appears only in THIS run (no prior occurrences) is a one-off
    — not recurring (the host routes a sweep only when recurrence makes it useful)."""
    v = classify_recurring_wedge(
        this_run_id="RUN_NOW", this_run_cause_keys=["stale_claim_false_block"],
        prior_hits=[],
    )
    assert v.recurring is False
    assert v.runs_affected == 1


def test_recurring_structural_wedge():
    """Same cause across this run + >=1 prior run → recurring; the winning
    cluster names the cause + cross-run count for the host to re-attach taxonomy."""
    prior = [
        _hit("RUN_A", "stale_claim_false_block"),
        _hit("RUN_B", "stale_claim_false_block"),
    ]
    v = classify_recurring_wedge(
        this_run_id="RUN_NOW",
        this_run_cause_keys=["stale_claim_false_block"], prior_hits=prior,
    )
    assert v.recurring is True
    assert v.runs_affected == 3
    assert v.cause_key == "stale_claim_false_block"


def test_min_recurrence_threshold_respected():
    """The recurrence threshold is configurable; at min_recurrence=3 a 2-run
    cause is below the bar — the same inputs at the default (2) DO recur."""
    prior = [_hit("RUN_A", "ship_oracle_false_positive")]
    v3 = classify_recurring_wedge(
        this_run_id="RUN_NOW",
        this_run_cause_keys=["ship_oracle_false_positive"], prior_hits=prior,
        min_recurrence=3,
    )
    assert v3.runs_affected == 2
    assert v3.recurring is False
    v_default = classify_recurring_wedge(
        this_run_id="RUN_NOW",
        this_run_cause_keys=["ship_oracle_false_positive"], prior_hits=prior,
    )
    assert v_default.recurring is True


def test_most_recurring_cause_wins():
    """If this run wedged on two distinct causes, the one with the higher
    cross-run recurrence is the reported cluster (recurrence dominates)."""
    prior = [
        _hit("RUN_A", "ship_oracle_false_positive"),
        _hit("RUN_B", "ship_oracle_false_positive"),
        _hit("RUN_C", "stale_claim_false_block"),
    ]
    v = classify_recurring_wedge(
        this_run_id="RUN_NOW",
        this_run_cause_keys=["ship_oracle_false_positive", "stale_claim_false_block"],
        prior_hits=prior,
    )
    # ship_oracle spans RUN_A+RUN_B+RUN_NOW = 3; stale spans RUN_C+RUN_NOW = 2.
    assert v.cause_key == "ship_oracle_false_positive"
    assert v.runs_affected == 3


def test_prior_only_cause_not_reported():
    """A cause that recurs in prior runs but did NOT wedge THIS run must not be
    reported — only a cause the current run actually hit is eligible."""
    prior = [
        _hit("RUN_A", "ship_oracle_false_positive"),
        _hit("RUN_B", "ship_oracle_false_positive"),
        _hit("RUN_C", "ship_oracle_false_positive"),
    ]
    v = classify_recurring_wedge(
        this_run_id="RUN_NOW",
        this_run_cause_keys=["stale_claim_false_block"], prior_hits=prior,
    )
    assert v.cause_key == "stale_claim_false_block"
    assert v.runs_affected == 1
    assert v.recurring is False


def test_empty_cause_keys_is_safe():
    """Defensive: called with no wedge cause returns a benign non-recurring
    verdict with an empty cause."""
    v = classify_recurring_wedge(
        this_run_id="RUN_NOW", this_run_cause_keys=[], prior_hits=[],
    )
    assert v.recurring is False
    assert v.cause_key == ""


def test_blank_cause_keys_filtered():
    """Whitespace-only keys are dropped before the fold (treated as no cause)."""
    v = classify_recurring_wedge(
        this_run_id="RUN_NOW", this_run_cause_keys=["", "   "], prior_hits=[],
    )
    assert v.recurring is False
    assert v.cause_key == ""


def test_uncategorized_cause_can_recur():
    """An opaque novel key still clusters — a recurring NEW shape is surfaced
    rather than vanishing."""
    prior = [_hit("RUN_A", "uncategorized_nonship", example="weird new wedge")]
    v = classify_recurring_wedge(
        this_run_id="RUN_NOW",
        this_run_cause_keys=["uncategorized_nonship"], prior_hits=prior,
    )
    assert v.cause_key == "uncategorized_nonship"
    assert v.runs_affected == 2
    assert v.recurring is True


def test_build_clusters_sorted_by_stall_score():
    """build_clusters returns clusters recurrence-first; cost/wall break ties."""
    hits = [
        _hit("R1", "low"),
        _hit("R1", "high"), _hit("R2", "high"), _hit("R3", "high"),
    ]
    clusters = build_clusters(hits)
    assert clusters[0].cause_key == "high"
    assert clusters[0].runs_affected == 3
    assert clusters[-1].cause_key == "low"


def test_cluster_carries_no_taxonomy_object():
    """Boundary guard: a WedgeCluster carries only the cause_key STRING, never a
    host taxonomy object — that is what keeps the fold domain-free."""
    (cluster,) = build_clusters([_hit("R1", "anything")])
    assert isinstance(cluster.cause_key, str)
    assert not hasattr(cluster, "cause")
