"""Tests for `dos.cooldown` — the anti-churn primitive (docs/207 Phase 3).

Groups:
  * the pure fold — CLEAR vs RECENTLY_ATTEMPTED, outcome-awareness (SHIPPED
    pre-screened, DRAINED/BLOCKED full window, ERROR short window), the window
    boundary, the fail-open degrade (garbled/too-new rows skipped, never refused);
  * the `attempt_entry` builder + replay-ignores-it (forensic, not state);
  * the schema-constant pin (cooldown's inlined family/version == lane_journal's);
  * the `[cooldown]` config seam (policy_from_table / load_from_toml);
  * `TestRepickStormBacktest` — the re-pick-storm backtest docs/207 §3 names: a
    unit attempted-then-DRAINed inside the window cools; 7h later it clears.
"""
from __future__ import annotations

import pytest

from dos import cooldown as _cooldown
from dos.cooldown import (
    AttemptOutcome,
    Cooldown,
    CooldownPolicy,
    CooldownState,
    cooldown_verdict,
)
from dos import lane_journal as lj
from dos import durable_schema as _schema


HOUR = 60 * 60 * 1000
NOW = 100 * HOUR  # fixed clock (ms)


def _attempt(unit, outcome, at_ms, *, tagged=True):
    rec = {"op": "ATTEMPT", "unit_id": unit, "outcome": outcome, "attempted_at_ms": at_ms,
           "ts": "2026-06-07T00:00:00Z"}
    if tagged:
        rec.update(_schema.tag("lane-journal", 1))
    return rec


# ---------------------------------------------------------------------------
# The pure fold.
# ---------------------------------------------------------------------------


class TestCooldownFold:
    def test_no_attempts_is_clear(self):
        v = cooldown_verdict("U1", [], now_ms=NOW)
        assert v.state is CooldownState.CLEAR
        assert not v.held

    def test_recent_drain_holds(self):
        # attempted 1h ago, 6h default window → still cooling.
        v = cooldown_verdict("U1", [_attempt("U1", "drained", NOW - 1 * HOUR)], now_ms=NOW)
        assert v.state is CooldownState.RECENTLY_ATTEMPTED
        assert v.held
        assert v.until_ms == (NOW - 1 * HOUR) + 6 * HOUR

    def test_old_drain_clears(self):
        # attempted 7h ago, 6h window → elapsed.
        v = cooldown_verdict("U1", [_attempt("U1", "drained", NOW - 7 * HOUR)], now_ms=NOW)
        assert v.state is CooldownState.CLEAR

    def test_shipped_is_prescreened_moot(self):
        # A SHIPPED most-recent attempt is moot even if "recent".
        v = cooldown_verdict("U1", [_attempt("U1", "shipped", NOW - 1 * HOUR)], now_ms=NOW)
        assert v.state is CooldownState.CLEAR
        assert "moot" in v.reason

    def test_blocked_holds_like_drained(self):
        v = cooldown_verdict("U1", [_attempt("U1", "blocked", NOW - 1 * HOUR)], now_ms=NOW)
        assert v.held

    def test_error_uses_short_window(self):
        # ERROR earns the 30m window; 1h ago → already elapsed (unlike DRAINED).
        v = cooldown_verdict("U1", [_attempt("U1", "error", NOW - 1 * HOUR)], now_ms=NOW)
        assert v.state is CooldownState.CLEAR
        # but 10m ago → still cooling under the 30m window.
        v2 = cooldown_verdict("U1", [_attempt("U1", "error", NOW - 10 * 60 * 1000)], now_ms=NOW)
        assert v2.held

    def test_most_recent_attempt_decides(self):
        # An old SHIPPED then a recent DRAINED → the recent DRAINED holds.
        history = [
            _attempt("U1", "shipped", NOW - 20 * HOUR),
            _attempt("U1", "drained", NOW - 1 * HOUR),
        ]
        v = cooldown_verdict("U1", history, now_ms=NOW)
        assert v.held
        assert v.count == 2

    def test_other_units_ignored(self):
        v = cooldown_verdict("U1", [_attempt("U2", "drained", NOW - 1 * HOUR)], now_ms=NOW)
        assert v.state is CooldownState.CLEAR

    def test_garbled_row_is_skipped_fail_open(self):
        # A row missing attempted_at_ms is skipped (fail-open → re-pickable), never raises.
        v = cooldown_verdict("U1", [{"op": "ATTEMPT", "unit_id": "U1", "outcome": "drained"}], now_ms=NOW)
        assert v.state is CooldownState.CLEAR

    def test_too_new_schema_row_skipped_not_refused(self):
        # A too-new schema row degrades to "no attempt" (re-pickable), NOT a refusal
        # — the cooldown is a hint, the OPPOSITE direction from the correctness-read floor.
        rec = {"op": "ATTEMPT", "unit_id": "U1", "outcome": "drained",
               "attempted_at_ms": NOW - 1 * HOUR, **_schema.tag("lane-journal", 99)}
        v = cooldown_verdict("U1", [rec], now_ms=NOW)
        assert v.state is CooldownState.CLEAR  # skipped, not held

    def test_untagged_legacy_row_is_accepted(self):
        # An untagged (pre-tag) ATTEMPT row is still folded (the tolerant legacy floor).
        v = cooldown_verdict("U1", [_attempt("U1", "drained", NOW - 1 * HOUR, tagged=False)], now_ms=NOW)
        assert v.held


# ---------------------------------------------------------------------------
# The attempt_entry builder + replay-ignores-it.
# ---------------------------------------------------------------------------


class TestAttemptEvent:
    def test_attempt_entry_shape(self):
        e = lj.attempt_entry("U1", outcome="drained", run_id="r1", lane="auth")
        assert e["op"] == "ATTEMPT"
        assert e["unit_id"] == "U1"
        assert e["outcome"] == "drained"
        assert e["run_id"] == "r1"
        assert e["schema"] == {"family": "lane-journal", "version": 1}

    def test_replay_ignores_attempt_for_state(self):
        # An ATTEMPT grants/removes no lease — replay must reconstruct no lease from it.
        e = lj.attempt_entry("U1", outcome="drained")
        assert lj.replay([e]) == []

    def test_schema_constants_match_lane_journal(self):
        # cooldown.py inlines the family/version (to break a config import cycle);
        # this pins them equal to lane_journal's source of truth — no silent drift.
        assert _cooldown._LJ_FAMILY == lj.SCHEMA_FAMILY
        assert _cooldown._LJ_SCHEMA == lj.LANE_JOURNAL_SCHEMA


# ---------------------------------------------------------------------------
# The [cooldown] config seam.
# ---------------------------------------------------------------------------


class TestCooldownTable:
    def test_unknown_key_raises(self):
        with pytest.raises(ValueError):
            _cooldown.policy_from_table({"bogus": 1})

    def test_window_hours_override(self):
        p = _cooldown.policy_from_table({"window_hours": 2})
        assert p.window_ms == 2 * HOUR

    def test_window_ms_override(self):
        p = _cooldown.policy_from_table({"window_ms": 12345})
        assert p.window_ms == 12345

    def test_error_window_minutes(self):
        p = _cooldown.policy_from_table({"error_window_minutes": 15})
        assert p.error_window_ms == 15 * 60 * 1000

    def test_load_from_toml(self, tmp_path):
        p = tmp_path / "dos.toml"
        p.write_text("[cooldown]\nwindow_hours = 3\n", encoding="utf-8")
        pol = _cooldown.load_from_toml(p)
        assert pol.window_ms == 3 * HOUR

    def test_load_from_toml_absent_is_base(self, tmp_path):
        assert _cooldown.load_from_toml(tmp_path / "nope.toml") is _cooldown.DEFAULT_COOLDOWN_POLICY

    def test_config_carries_cooldown(self):
        import dos.config as c
        cfg = c.default_config()
        assert isinstance(cfg.cooldown, CooldownPolicy)


# ---------------------------------------------------------------------------
# The re-pick-storm backtest (docs/207 §3).
# ---------------------------------------------------------------------------


class TestRepickStormBacktest:
    """The measure-then-change gate: a unit attempted-then-DRAINed inside the
    window must cool (the storm broken); the same unit 7h later must clear (a
    genuinely-unblocked unit returns the same session). If a recent DRAIN does NOT
    cool, the storm-breaker is wrong and this fails."""

    def test_recently_drained_unit_cools(self):
        v = cooldown_verdict("AUTH3", [_attempt("AUTH3", "drained", NOW - 1 * HOUR)], now_ms=NOW)
        assert v.held, "a unit drained 1h ago must cool — else the re-pick storm recurs"

    def test_same_unit_after_window_clears(self):
        v = cooldown_verdict("AUTH3", [_attempt("AUTH3", "drained", NOW - 7 * HOUR)], now_ms=NOW)
        assert not v.held, "a unit drained 7h ago must clear — an unblocked unit returns"
