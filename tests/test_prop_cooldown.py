"""Property-based proof of the cooldown anti-churn fold (docs/273, docs/207 §3b).

`cooldown_verdict(unit_id, attempt_history, now_ms, policy) -> Cooldown` is the
cross-run memory that breaks the re-pick storm: it folds a bag of `OP_ATTEMPT`
records into "is this unit in a cooldown window right now?". It is a PURE, fail-open
fold (a cooldown is a HINT — the safe direction is always re-pickable, so a garbled
record or empty history degrades to CLEAR, never a refusal). Its docstring states
several laws that example tests pin at points; this file pins them ∀.

The properties:
  * `TestUnitIsolation`     — only records for THIS unit_id affect the verdict;
    foreign-unit records are invisible.
  * `TestTimeWindowBoundary`— RECENTLY_ATTEMPTED ⟺ now_ms < wall; a far-past now is
    always CLEAR; the exact boundary (now == wall) is CLEAR (strict <).
  * `TestRecencyDetermines` — only the MOST RECENT attempt's wall matters; reordering
    the history doesn't change the verdict.
  * `TestShippedPrescreen`  — a SHIPPED most-recent attempt is always CLEAR (the unit
    moved; cooldown moot), regardless of timing.
  * `TestFailOpen`          — empty / all-garbage history → CLEAR; never raises.
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from dos.cooldown import (  # noqa: E402
    DEFAULT_COOLDOWN_POLICY,
    AttemptOutcome,
    CooldownState,
    cooldown_verdict,
)

_P = DEFAULT_COOLDOWN_POLICY
# Outcomes EXCLUDING SHIPPED — SHIPPED is the pre-screen carve-out tested separately
# (a SHIPPED most-recent attempt is CLEAR regardless of timing). The non-shipped
# outcomes are the ones whose timing window actually gates re-pick.
_holding_outcomes = st.sampled_from(
    [o for o in AttemptOutcome if o is not AttemptOutcome.SHIPPED]
)
_unit_ids = st.sampled_from(["u1", "u2", "docs/82-plan", "lane/x"])
# ms timestamps in a bounded window so `now` can straddle the wall.
_ms = st.integers(min_value=0, max_value=10**9)


@st.composite
def _attempt(draw, *, unit_id=None, outcome=None) -> dict:
    """One OP_ATTEMPT record, the shape `lane_journal.read_all` yields."""
    uid = unit_id if unit_id is not None else draw(_unit_ids)
    oc = outcome if outcome is not None else draw(_holding_outcomes)
    at = draw(_ms)
    return {
        "op": "ATTEMPT",
        "unit_id": uid,
        "outcome": oc.value,
        "attempted_at_ms": at,
        "ts": f"ts-{at}",
    }


class TestUnitIsolation:
    @given(
        target_attempts=st.lists(_attempt(unit_id="u1"), min_size=0, max_size=4),
        foreign_attempts=st.lists(_attempt(unit_id="u2"), min_size=0, max_size=6),
        now=_ms,
    )
    @settings(max_examples=400, deadline=None)
    def test_foreign_unit_records_are_invisible(self, target_attempts, foreign_attempts, now):
        """The verdict for 'u1' depends ONLY on u1's records. Adding any number of
        OTHER units' attempts to the history never changes it — the fold filters to
        this unit first (the cross-run memory is per-unit)."""
        only_mine = cooldown_verdict("u1", target_attempts, now_ms=now, policy=_P)
        with_noise = cooldown_verdict(
            "u1", [*target_attempts, *foreign_attempts], now_ms=now, policy=_P
        )
        assert only_mine.state is with_noise.state, (
            f"foreign-unit records changed u1's verdict: {only_mine.state.name} -> "
            f"{with_noise.state.name}"
        )


class TestTimeWindowBoundary:
    @given(unit=_unit_ids, outcome=_holding_outcomes, at=_ms, now=_ms)
    @settings(max_examples=600, deadline=None)
    def test_recently_attempted_iff_now_before_wall(self, unit, outcome, at, now):
        """RECENTLY_ATTEMPTED ⟺ now_ms < wall, where wall = at + window(outcome).
        The single-attempt case isolates the boundary exactly (strict <)."""
        rec = {
            "op": "ATTEMPT", "unit_id": unit, "outcome": outcome.value,
            "attempted_at_ms": at, "ts": f"ts-{at}",
        }
        wall = at + _P.window_for(outcome)
        v = cooldown_verdict(unit, [rec], now_ms=now, policy=_P)
        expect_holding = now < wall
        assert (v.state is CooldownState.RECENTLY_ATTEMPTED) == expect_holding, (
            f"at={at} outcome={outcome.value} wall={wall} now={now}: "
            f"state={v.state.name}, expected holding={expect_holding}"
        )
        if v.state is CooldownState.RECENTLY_ATTEMPTED:
            assert v.until_ms == wall  # the verdict reports the right wall

    @given(unit=_unit_ids, outcome=_holding_outcomes, at=_ms)
    @settings(max_examples=200, deadline=None)
    def test_far_future_now_is_always_clear(self, unit, outcome, at):
        """Once now is well past any possible wall, the window has elapsed → CLEAR."""
        rec = {
            "op": "ATTEMPT", "unit_id": unit, "outcome": outcome.value,
            "attempted_at_ms": at, "ts": f"ts-{at}",
        }
        far_future = at + _P.window_for(outcome) + 1  # strictly past the wall
        v = cooldown_verdict(unit, [rec], now_ms=far_future, policy=_P)
        assert v.state is CooldownState.CLEAR


class TestRecencyDetermines:
    @given(attempts=st.lists(_attempt(unit_id="u1"), min_size=1, max_size=6), now=_ms)
    @settings(max_examples=400, deadline=None)
    def test_verdict_is_invariant_under_history_order(self, attempts, now):
        """The fold sorts by time and reads only the MOST RECENT attempt's wall, so
        the verdict cannot depend on the order the records arrive in. Reversing the
        history must yield the same verdict."""
        forward = cooldown_verdict("u1", attempts, now_ms=now, policy=_P)
        reverse = cooldown_verdict("u1", list(reversed(attempts)), now_ms=now, policy=_P)
        assert forward.state is reverse.state, (
            f"history order changed the verdict: {forward.state.name} (fwd) vs "
            f"{reverse.state.name} (rev)"
        )


class TestShippedPrescreen:
    @given(
        older=st.lists(_attempt(unit_id="u1"), min_size=0, max_size=4),
        ship_at=_ms,
        now=_ms,
    )
    @settings(max_examples=300, deadline=None)
    def test_shipped_most_recent_is_always_clear(self, older, ship_at, now):
        """When the MOST RECENT attempt is SHIPPED, the unit moved — CLEAR regardless
        of timing (the picker's ship-detection excludes it anyway). We make the
        SHIPPED record the newest by giving it a timestamp past all the others."""
        max_older = max((r["attempted_at_ms"] for r in older), default=0)
        ship_ts = max(ship_at, max_older) + 1  # strictly the most recent
        ship_rec = {
            "op": "ATTEMPT", "unit_id": "u1", "outcome": AttemptOutcome.SHIPPED.value,
            "attempted_at_ms": ship_ts, "ts": f"ts-{ship_ts}",
        }
        v = cooldown_verdict("u1", [*older, ship_rec], now_ms=now, policy=_P)
        assert v.state is CooldownState.CLEAR, (
            f"a SHIPPED most-recent attempt was not CLEAR: {v.state.name}"
        )


class TestFailOpen:
    @given(now=_ms)
    @settings(max_examples=50, deadline=None)
    def test_empty_history_is_clear(self, now):
        v = cooldown_verdict("u1", [], now_ms=now, policy=_P)
        assert v.state is CooldownState.CLEAR

    @given(
        garbage=st.lists(
            st.one_of(
                st.none(),
                st.integers(),
                st.text(max_size=10),
                st.fixed_dictionaries({"op": st.just("NOT_ATTEMPT")}),
                st.fixed_dictionaries({"unit_id": st.just("u1")}),  # missing ts/outcome
            ),
            min_size=1,
            max_size=6,
        ),
        now=_ms,
    )
    @settings(max_examples=300, deadline=None)
    def test_garbage_history_degrades_to_clear_never_raises(self, garbage, now):
        """A cooldown is observability, not a correctness gate: an unreadable /
        wrong-family / non-mapping record is SKIPPED (the fail-open direction is
        re-pickable), and the fold never raises on garbage."""
        v = cooldown_verdict("u1", garbage, now_ms=now, policy=_P)
        # No real attempt for u1 survives the schema gate → CLEAR.
        assert v.state is CooldownState.CLEAR
