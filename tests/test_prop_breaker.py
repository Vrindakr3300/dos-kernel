"""Property-based proof of the circuit-breaker state machine (docs/273, docs/223).

The breaker is the kernel's one *stateful* pure verdict: a two-counter machine
(`consecutive`, `total`) folded by `record_failure` / `record_success`, classified
by a pure `_classify`. Its docstring states explicit transition laws lifted from
CC's `denialTracking.ts`:

  * consecutive resets on a success; total NEVER resets (the flapping detector).
  * trips on EITHER rung (consecutive >= max OR total >= max).
  * a total-trip LATCHES — a success can heal a consecutive-trip but not a
    total-trip (a path that failed 20x is unreliable no matter how often it also
    succeeded).

A stateful machine with transition laws is the textbook Hypothesis
`RuleBasedStateMachine` target: drive a random sequence of record_failure /
record_success and assert the invariants hold at every step + against a shadow
oracle.

The properties:
  * `TestStateMachine`     — a random op sequence keeps the carried counts in lock-
    step with a hand-rolled oracle; total monotone; consecutive resets on success;
    total-trip latches OPEN.
  * `TestTripIff`          — OPEN ⟺ (consecutive >= max_c OR total >= max_t) over
    random count pairs (the EITHER-rung law as an iff).
  * `TestDeterminism`      — same start counts + policy ⟹ same transition (purity).
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    RuleBasedStateMachine,
    invariant,
    rule,
)

from dos.breaker import (  # noqa: E402
    BreakerCounts,
    BreakerPolicy,
    BreakerState,
    classify,
    record_failure,
    record_success,
)

_POLICY = BreakerPolicy(max_consecutive=3, max_total=20)


def _oracle_open(consecutive: int, total: int, policy: BreakerPolicy) -> bool:
    """Hand-rolled trip oracle: OPEN ⟺ either enabled rung is at/over its max."""
    c_trip = policy.max_consecutive > 0 and consecutive >= policy.max_consecutive
    t_trip = policy.max_total > 0 and total >= policy.max_total
    return c_trip or t_trip


class BreakerMachine(RuleBasedStateMachine):
    """Drive a random failure/success stream and keep a shadow oracle in lock-step.

    Each rule applies one breaker op AND the same op to a pair of plain integers,
    then `invariant`s assert the carried `BreakerCounts` match the integers and the
    classified state matches the oracle — so any drift between the real fold and the
    documented transition law is a falsifying trace Hypothesis will shrink."""

    def __init__(self):
        super().__init__()
        self.counts = BreakerCounts()
        self.policy = _POLICY
        # Shadow state: the law as plain ints.
        self.exp_consecutive = 0
        self.exp_total = 0
        self.total_ever_tripped = False  # has total >= max_total ever held?

    @rule()
    def fail(self):
        t = record_failure(self.counts, self.policy)
        self.counts = t.counts
        self.exp_consecutive += 1
        self.exp_total += 1
        if self.policy.max_total > 0 and self.exp_total >= self.policy.max_total:
            self.total_ever_tripped = True

    @rule()
    def succeed(self):
        t = record_success(self.counts, self.policy)
        self.counts = t.counts
        self.exp_consecutive = 0  # success zeroes consecutive
        # total is UNCHANGED on success (the flapping-detector invariant).

    @invariant()
    def counts_track_the_oracle(self):
        assert self.counts.consecutive == self.exp_consecutive
        assert self.counts.total == self.exp_total

    @invariant()
    def total_never_negative_and_consecutive_le_total(self):
        assert self.counts.total >= 0
        assert self.counts.consecutive >= 0
        # consecutive failures are a subset of total failures.
        assert self.counts.consecutive <= self.counts.total

    @invariant()
    def state_matches_oracle(self):
        v = classify(self.counts, self.policy)
        expect_open = _oracle_open(self.counts.consecutive, self.counts.total, self.policy)
        assert (v.state is BreakerState.OPEN) == expect_open

    @invariant()
    def total_trip_latches_open(self):
        """Once total has reached max_total, the breaker can never be CLOSED again —
        a success heals consecutive but cannot un-trip the cumulative rung."""
        if self.total_ever_tripped:
            v = classify(self.counts, self.policy)
            assert v.state is BreakerState.OPEN, (
                "total-trip did not latch: total reached the cap but the breaker "
                "returned to CLOSED"
            )


# Bind the machine as a pytest test case.
TestBreakerStateMachine = BreakerMachine.TestCase
TestBreakerStateMachine.settings = settings(max_examples=200, stateful_step_count=40, deadline=None)


class TestTripIff:
    """The EITHER-rung trip law as an iff over random count pairs (no sequencing —
    just `classify` on arbitrary already-counted state)."""

    @given(
        consecutive=st.integers(min_value=0, max_value=50),
        total=st.integers(min_value=0, max_value=50),
        max_c=st.integers(min_value=0, max_value=10),
        max_t=st.integers(min_value=0, max_value=30),
    )
    @settings(max_examples=600, deadline=None)
    def test_open_iff_either_rung_tripped(self, consecutive, total, max_c, max_t):
        # A policy needs at least one rung enabled (else __post_init__ refuses).
        if max_c == 0 and max_t == 0:
            return
        # consecutive can't exceed total in a real stream, but classify is a pure
        # peek that doesn't enforce that — still, keep the generated state coherent.
        total = max(total, consecutive)
        policy = BreakerPolicy(max_consecutive=max_c, max_total=max_t)
        v = classify(BreakerCounts(consecutive=consecutive, total=total), policy)
        expect_open = _oracle_open(consecutive, total, policy)
        assert (v.state is BreakerState.OPEN) == expect_open
        # An OPEN verdict always names which rung fired; a CLOSED one never does.
        if v.state is BreakerState.OPEN:
            assert v.tripped_on in ("consecutive", "total")
        else:
            assert v.tripped_on is None


class TestDeterminism:
    """record_failure / record_success are pure folds — same input, same output."""

    @given(
        consecutive=st.integers(min_value=0, max_value=50),
        total=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=300, deadline=None)
    def test_record_failure_is_deterministic(self, consecutive, total):
        total = max(total, consecutive)
        start = BreakerCounts(consecutive=consecutive, total=total)
        a = record_failure(start, _POLICY)
        b = record_failure(start, _POLICY)
        assert a.counts == b.counts
        assert a.verdict.state == b.verdict.state
        # The fold bumps BOTH counters by exactly one.
        assert a.counts.consecutive == consecutive + 1
        assert a.counts.total == total + 1

    @given(
        consecutive=st.integers(min_value=0, max_value=50),
        total=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=300, deadline=None)
    def test_record_success_zeroes_consecutive_keeps_total(self, consecutive, total):
        total = max(total, consecutive)
        start = BreakerCounts(consecutive=consecutive, total=total)
        t = record_success(start, _POLICY)
        assert t.counts.consecutive == 0
        assert t.counts.total == total  # total survives the success
