"""NOS — the no-op-streak verdict + the audit→budget proposal helper (docs/259 §Follow-ups).

`noop_streak.classify` is the GENERALIZATION of `loop_decide.wait_marker_budget` off
its one special case ("markers emitted") onto the general one ("no-op turns since the
last forward delta"). These tests pin (1) the LIVE/EXHAUSTED ladder on frozen counts
(timeless — no clock, no I/O, the `productivity` discipline), (2) the load-bearing
EQUIVALENCE with the shipped `wait_marker_budget` arithmetic (the generalization must
not drift from the marker case it subsumes), (3) the `dos.toml [noop_streak]` on-ramp,
and (4) `loop_decide.propose_tighter_budget` — the pure arithmetic of the audit→budget
loop (the post-hoc detector tuning the pre-hoc lever).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dos import loop_decide
from dos import noop_streak
from dos.noop_streak import (
    DEFAULT_POLICY,
    NoOpHistory,
    NoOpStreak,
    NoOpStreakPolicy,
    classify,
    load_from_toml,
    policy_from_table,
)


# ---------------------------------------------------------------------------
# 1. The pure-classifier ladder, on frozen no-op-turn counts.
# ---------------------------------------------------------------------------


def test_fresh_streak_is_live():
    """0 no-op turns → LIVE, carry 1 (a fresh wait phase has spent nothing)."""
    v = classify(NoOpHistory(0), NoOpStreakPolicy(4))
    assert v.verdict is NoOpStreak.LIVE
    assert v.allow is True
    assert v.noop_turns == 1


def test_under_cap_is_live_and_increments():
    """A streak under the cap → LIVE, carrying count+1 into the next decision."""
    v = classify(NoOpHistory(3), NoOpStreakPolicy(4))
    assert v.verdict is NoOpStreak.LIVE
    assert v.allow is True
    assert v.noop_turns == 4  # 3 + 1


def test_at_cap_is_exhausted_and_holds_count():
    """A streak that REACHES the cap (>=, the cost-guard direction) → EXHAUSTED, count held."""
    v = classify(NoOpHistory(4), NoOpStreakPolicy(4))
    assert v.verdict is NoOpStreak.EXHAUSTED
    assert v.allow is False
    assert v.noop_turns == 4  # a refused turn did not happen → not incremented


def test_over_cap_is_exhausted():
    v = classify(NoOpHistory(7), NoOpStreakPolicy(4))
    assert v.verdict is NoOpStreak.EXHAUSTED
    assert v.allow is False


def test_zero_cap_refuses_the_first_turn():
    """A budget of 0 refuses the FIRST no-op turn (0 >= 0) — the degenerate, honest."""
    v = classify(NoOpHistory(0), NoOpStreakPolicy(0))
    assert v.verdict is NoOpStreak.EXHAUSTED
    assert v.allow is False


def test_default_policy_cap_is_four():
    """The generic default equals wait_marker_budget's (4) — the marker case must not drift."""
    assert DEFAULT_POLICY.max_streak == 4
    assert classify(NoOpHistory(3)).allow is True   # under default
    assert classify(NoOpHistory(4)).allow is False  # at default


# ---------------------------------------------------------------------------
# 2. The EQUIVALENCE pin — noop_streak.classify subsumes wait_marker_budget.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("noop_turns", range(0, 8))
@pytest.mark.parametrize("max_streak", range(0, 8))
def test_equivalent_to_wait_marker_budget(noop_turns: int, max_streak: int):
    """The generalization agrees with the shipped marker arithmetic on the allow bit
    AND the carried count, across the whole grid — proof it did not drift from the
    special case it subsumes (`wait_marker_budget(n, m)` is `classify(NoOpHistory(n),
    NoOpStreakPolicy(m))` on the count-vs-cap question)."""
    nv = classify(NoOpHistory(noop_turns), NoOpStreakPolicy(max_streak))
    wv = loop_decide.wait_marker_budget(noop_turns, max_streak)
    assert nv.allow == wv.allow
    assert nv.noop_turns == wv.markers_emitted


# ---------------------------------------------------------------------------
# 3. Policy / history validation + the json shape.
# ---------------------------------------------------------------------------


def test_negative_cap_rejected():
    with pytest.raises(ValueError):
        NoOpStreakPolicy(-1)


def test_negative_count_rejected():
    with pytest.raises(ValueError):
        NoOpHistory(-1)


def test_history_of_helper():
    assert NoOpHistory.of(3).noop_turns == 3


def test_to_dict_shape():
    d = classify(NoOpHistory(4), NoOpStreakPolicy(4)).to_dict()
    assert d["verdict"] == "EXHAUSTED"
    assert d["allow"] is False
    assert d["noop_turns"] == 4
    assert "reason" in d


# ---------------------------------------------------------------------------
# 4. The dos.toml [noop_streak] on-ramp (mirror tool_stream/productivity).
# ---------------------------------------------------------------------------


def test_policy_from_table_reads_the_cap():
    assert policy_from_table({"max_streak": 2}).max_streak == 2


def test_policy_from_table_empty_is_default():
    assert policy_from_table({}) is DEFAULT_POLICY


def test_policy_from_table_raises_on_bad_value():
    """A malformed declaration fails loudly at load (via NoOpStreakPolicy.__post_init__)."""
    with pytest.raises(ValueError):
        policy_from_table({"max_streak": -3})


def test_load_from_toml_absent_file_is_base(tmp_path: Path):
    assert load_from_toml(tmp_path / "nope.toml") is DEFAULT_POLICY


def test_load_from_toml_no_table_is_base(tmp_path: Path):
    p = tmp_path / "dos.toml"
    p.write_text("[other]\nx = 1\n", encoding="utf-8")
    assert load_from_toml(p) is DEFAULT_POLICY


def test_load_from_toml_reads_the_table(tmp_path: Path):
    p = tmp_path / "dos.toml"
    p.write_text("[noop_streak]\nmax_streak = 6\n", encoding="utf-8")
    assert load_from_toml(p).max_streak == 6


def test_load_from_toml_tolerates_a_powershell_bom(tmp_path: Path):
    """A PowerShell-written UTF-8 BOM must not break the read (the utf-8-sig fix)."""
    p = tmp_path / "dos.toml"
    p.write_text("[noop_streak]\nmax_streak = 2\n", encoding="utf-8-sig")
    assert load_from_toml(p).max_streak == 2


# ---------------------------------------------------------------------------
# 5. propose_tighter_budget — the audit→budget loop's pure arithmetic (docs/259 §FU3).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "observed,current,expected",
    [
        (252, 4, 4),   # a HUGE burst proves non-enforcement → monotone-down clamp → no tightening
        (5, 8, 4),     # a burst WITHIN a generous cap → genuine tighten to observed-1
        (3, 4, 2),     # observed-1, under the cap
        (1, 4, 1),     # floored at 1 (a 0 budget would refuse the first legit wait)
        (0, 4, 1),     # floored at 1
        (2, 4, 1),     # observed-1 = 1
        (9, 4, 4),     # observed > current → clamp to current
    ],
)
def test_propose_tighter_budget_grid(observed: int, current: int, expected: int):
    assert loop_decide.propose_tighter_budget(observed, current) == expected


def test_propose_tighter_budget_never_loosens():
    """For any observed/current, the proposal is <= current (monotone-down) and >= 1."""
    for observed in range(0, 300, 7):
        for current in range(1, 12):
            p = loop_decide.propose_tighter_budget(observed, current)
            assert 1 <= p <= current
