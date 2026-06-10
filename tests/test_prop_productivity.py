"""Property-based proof of the productivity verdict's laws (docs/273, docs/218).

`productivity.classify(WorkHistory, policy) -> ProductivityVerdict` is a pure,
timeless, no-I/O TREND verdict over per-step work deltas. Its docstring lifts CC's
`isDiminishing`: DIMINISHING ⟺ (>= min_steps steps) AND (the last two deltas are
BOTH under the floor). The example suite pins the named points; this file pins the
laws over generated delta sequences.

The properties:
  * `TestYoungGuard`        — fewer than min_steps deltas ⟹ PRODUCTIVE, ∀ values.
  * `TestDiminishingNeedsBothLow` — if either of the last two deltas clears the
    floor, the verdict is NOT DIMINISHING.
  * `TestTailDetermines`    — the verdict depends only on step_count >= min_steps
    and the last two deltas; the prefix doesn't matter.
  * `TestTotalAndClosed`    — always one of three members; never raises in-domain.
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from dos.productivity import (  # noqa: E402
    Productivity,
    ProductivityPolicy,
    WorkHistory,
    classify,
)

_delta = st.integers(min_value=0, max_value=10_000)
_deltas = st.lists(_delta, min_size=0, max_size=12)
_policy = ProductivityPolicy()  # defaults: min_steps=3, floor=500
_FLOOR = _policy.floor
_MIN = _policy.min_steps


class TestYoungGuard:
    @given(deltas=st.lists(_delta, min_size=0, max_size=_MIN - 1))
    @settings(max_examples=300, deadline=None)
    def test_too_few_steps_is_always_productive(self, deltas):
        """Fewer than min_steps deltas ⟹ PRODUCTIVE for ANY delta values — there is
        not enough of a trend to accuse a run of fading (the young-and-alive guard).
        Even all-zero deltas below the step floor are PRODUCTIVE."""
        v = classify(WorkHistory.of(deltas), _policy)
        assert v.verdict is Productivity.PRODUCTIVE, (
            f"{len(deltas)} deltas (< min {_MIN}) was not PRODUCTIVE: {v.verdict.value}"
        )


class TestDiminishingNeedsBothLow:
    @given(
        prefix=st.lists(_delta, min_size=_MIN - 1, max_size=8),
        last=_delta,
        prior=_delta,
    )
    @settings(max_examples=500, deadline=None)
    def test_one_high_recent_step_is_not_diminishing(self, prefix, last, prior):
        """With enough steps, DIMINISHING needs BOTH the last two deltas under the
        floor (CC's lastDelta AND priorDelta). If EITHER clears the floor, the run
        is not DIMINISHING — it just did real work recently."""
        deltas = [*prefix, prior, last]
        v = classify(WorkHistory.of(deltas), _policy)
        either_clears = prior >= _FLOOR or last >= _FLOOR
        if either_clears:
            assert v.verdict is not Productivity.DIMINISHING, (
                f"last two ({prior},{last}) — one clears floor {_FLOOR} but verdict "
                f"was DIMINISHING"
            )

    @given(
        prefix=st.lists(_delta, min_size=_MIN - 1, max_size=8),
        prior=st.integers(min_value=1, max_value=_FLOOR - 1),
        last=st.integers(min_value=1, max_value=_FLOOR - 1),
    )
    @settings(max_examples=400, deadline=None)
    def test_both_recent_low_nonzero_with_enough_steps_is_diminishing(self, prefix, prior, last):
        """The positive direction: enough steps + both last two deltas in the
        NONZERO-but-under-floor band ⟹ DIMINISHING (the sustained-fading signal).

        The last delta must be nonzero: an exact 0 is caught one rung earlier as
        STALLED (the flat-line / give-up rung), which is a DIFFERENT verdict — that
        carve-out is pinned in `test_zero_last_delta_is_stalled` below. Property
        testing surfaced this distinction that a naive `[...,0,0]` example missed."""
        deltas = [*prefix, prior, last]  # both in (0, floor) → sustained fading
        v = classify(WorkHistory.of(deltas), _policy)
        assert v.verdict is Productivity.DIMINISHING

    @given(
        prefix=st.lists(_delta, min_size=_MIN - 1, max_size=8),
        prior=_delta,
    )
    @settings(max_examples=300, deadline=None)
    def test_zero_last_delta_is_stalled_not_diminishing(self, prefix, prior):
        """An exact-zero most-recent step is STALLED, checked BEFORE DIMINISHING —
        the flat-line rung is named precisely even when the prior step was also low.
        This is the carve-out the positive-direction test excludes."""
        deltas = [*prefix, prior, 0]  # last delta exactly 0
        v = classify(WorkHistory.of(deltas), _policy)
        assert v.verdict is Productivity.STALLED


class TestTailDetermines:
    @given(
        a=st.lists(_delta, min_size=_MIN, max_size=6),
        b=st.lists(_delta, min_size=_MIN, max_size=10),
        prior=_delta,
        last=_delta,
    )
    @settings(max_examples=400, deadline=None)
    def test_verdict_depends_only_on_tail_past_the_step_gate(self, a, b, prior, last):
        """Two histories that both clear min_steps and share the same final two
        deltas get the same verdict — the verdict reads only deltas[-1]/deltas[-2]
        past the length gate. Catches a regression that starts reading the whole
        list (e.g. summing or averaging it)."""
        va = classify(WorkHistory.of([*a, prior, last]), _policy)
        vb = classify(WorkHistory.of([*b, prior, last]), _policy)
        assert va.verdict == vb.verdict, (
            f"same tail ({prior},{last}) gave different verdicts: "
            f"{va.verdict.value} vs {vb.verdict.value}"
        )


class TestTotalAndClosed:
    @given(deltas=_deltas, min_steps=st.integers(0, 6), floor=st.integers(0, 5000))
    @settings(max_examples=400, deadline=None)
    def test_always_returns_a_valid_verdict(self, deltas, min_steps, floor):
        """classify never raises on any in-domain (non-negative) delta sequence and
        always returns one of the three members, for any sane policy."""
        policy = ProductivityPolicy(min_steps=min_steps, floor=floor)
        v = classify(WorkHistory.of(deltas), policy)
        assert v.verdict in (
            Productivity.PRODUCTIVE,
            Productivity.DIMINISHING,
            Productivity.STALLED,
        )
        assert v.history.step_count == len(deltas)
