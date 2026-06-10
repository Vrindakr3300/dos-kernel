"""Tests for the /replan §1.5 no-op-skip decision (`dos.gate_classify`).

`replan_skip_decision(new_findings, substantive_ships) -> ReplanSkip` is the
PRODUCER-side twin of the consumer-side `classify_replan_productivity`: it is the
pure boolean /replan's §1.5 gate makes BEFORE it sweeps. Pure given two injected
integer counters — no git/file/clock — so it is replay-testable away from a live
$2-4 sweep, exactly like `classify_packet` / `classify_replan_productivity`.
"""

from __future__ import annotations

from dos.gate_classify import ReplanSkip, replan_skip_decision


class TestReplanSkipDecision:
    def test_no_evidence_skips(self):
        # The §1.5 gate verbatim: 0 new findings AND 0 substantive ships → SKIP.
        assert replan_skip_decision(0, 0) is ReplanSkip.SKIP

    def test_a_new_finding_proceeds(self):
        assert replan_skip_decision(1, 0) is ReplanSkip.PROCEED

    def test_a_substantive_ship_proceeds(self):
        assert replan_skip_decision(0, 1) is ReplanSkip.PROCEED

    def test_both_signals_proceed(self):
        assert replan_skip_decision(3, 5) is ReplanSkip.PROCEED

    def test_negative_counts_are_treated_as_zero(self):
        # A malformed count must NEVER suppress a real sweep — but two negatives
        # (no real signal) still skip, since max(0, n) clamps both to 0.
        assert replan_skip_decision(-1, -1) is ReplanSkip.SKIP
        # A negative paired with a real positive still proceeds.
        assert replan_skip_decision(-1, 2) is ReplanSkip.PROCEED

    def test_enum_is_str_valued(self):
        # str-valued so it round-trips through the context bundler's JSON.
        assert ReplanSkip.SKIP == "SKIP"
        assert ReplanSkip.PROCEED == "PROCEED"
        assert str(replan_skip_decision(0, 0)) == "SKIP"
