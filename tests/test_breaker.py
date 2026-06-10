"""BRK — the circuit-breaker primitive + the pure transitions (docs/219).

`breaker` is the generic facility extracted from `loop_decide`'s six hand-coded
breakers (idea H2 from the docs/189 CC audit). These tests pin the two-counter
state machine (consecutive + total, CC `denialTracking.ts`), the trip on EITHER
rung, the reset semantics (success resets consecutive, NOT total), the escalation
rung (the DOS H3 addition), purity, and the CLI verb.

The whole point of the two counters:
  - consecutive catches a SUSTAINED outage (N in a row), resets on success.
  - total catches a FLAPPING failure (fail/succeed/fail…) a consecutive count misses.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import breaker
from dos.breaker import (
    BreakerCounts,
    BreakerPolicy,
    BreakerState,
    Escalation,
    classify,
    record_failure,
    record_success,
)

# A readable policy: trip at 3 in a row OR 5 total, escalate to HUMAN on trip.
_POLICY = BreakerPolicy(max_consecutive=3, max_total=5, on_trip=Escalation.HUMAN)


# ---------------------------------------------------------------------------
# The consecutive rung — a sustained run of failures.
# ---------------------------------------------------------------------------


def test_under_consecutive_limit_is_closed():
    """Two failures in a row, limit 3 → CLOSED (still usable)."""
    t1 = record_failure(BreakerCounts(), _POLICY)
    assert t1.verdict.state is BreakerState.CLOSED
    assert t1.counts == BreakerCounts(consecutive=1, total=1)
    t2 = record_failure(t1.counts, _POLICY)
    assert t2.verdict.state is BreakerState.CLOSED
    assert t2.counts == BreakerCounts(consecutive=2, total=2)


def test_reaching_consecutive_limit_opens():
    """Three failures in a row → OPEN, tripped on the consecutive rung."""
    counts = BreakerCounts()
    for _ in range(3):
        t = record_failure(counts, _POLICY)
        counts = t.counts
    assert t.verdict.state is BreakerState.OPEN
    assert t.verdict.tripped_on == "consecutive"
    assert "sustained" in t.verdict.reason


def test_success_resets_the_consecutive_streak():
    """A success zeroes the consecutive counter — the sustained-outage signal cleared."""
    # Two failures, then a success.
    counts = record_failure(BreakerCounts(), _POLICY).counts
    counts = record_failure(counts, _POLICY).counts
    assert counts.consecutive == 2
    healed = record_success(counts, _POLICY)
    assert healed.counts.consecutive == 0
    assert healed.verdict.state is BreakerState.CLOSED
    # But the total survives the success (load-bearing for flapping; see below).
    assert healed.counts.total == 2


# ---------------------------------------------------------------------------
# The total rung — a flapping failure a consecutive count misses.
# ---------------------------------------------------------------------------


def test_flapping_trips_total_rung_when_consecutive_never_would():
    """fail/succeed/fail/succeed… never trips consecutive but DOES trip total.

    This is the whole reason CC carries two counters and the bug a consecutive-only
    breaker (today's loop_decide shape) has.
    """
    counts = BreakerCounts()
    verdict = None
    # 5 failures, each immediately followed by a success → consecutive never exceeds 1.
    for _ in range(5):
        t = record_failure(counts, _POLICY)
        counts = t.counts
        verdict = t.verdict
        # consecutive is always 1 here (a failure right after a success).
        assert counts.consecutive == 1
        counts = record_success(counts, _POLICY).counts
    # By the 5th failure the TOTAL rung (max_total=5) has tripped.
    assert verdict.state is BreakerState.OPEN
    assert verdict.tripped_on == "total"
    assert "flapping" in verdict.reason


def test_success_does_not_reset_total():
    """A total-tripped breaker stays OPEN through a success (total never resets).

    Correct: a path that failed `max_total` times is unreliable no matter how often
    it also succeeded.
    """
    # Drive the total to its limit via flapping.
    counts = BreakerCounts(consecutive=0, total=5)  # already at the total limit
    assert classify(counts, _POLICY).state is BreakerState.OPEN
    # A success resets consecutive but not total → still OPEN.
    healed = record_success(counts, _POLICY)
    assert healed.counts.total == 5
    assert healed.verdict.state is BreakerState.OPEN
    assert healed.verdict.tripped_on == "total"


# ---------------------------------------------------------------------------
# Escalation — the DOS addition (H3): the trip names a rung.
# ---------------------------------------------------------------------------


def test_open_verdict_carries_the_escalation_rung():
    """An OPEN breaker names where to escalate (the policy's on_trip)."""
    counts = BreakerCounts(consecutive=3)
    v = classify(counts, _POLICY)
    assert v.state is BreakerState.OPEN
    assert v.escalation is Escalation.HUMAN
    assert "escalate to HUMAN" in v.reason


def test_closed_verdict_never_escalates():
    """A CLOSED breaker always reports NONE — there is nothing to escalate."""
    v = classify(BreakerCounts(consecutive=1, total=1), _POLICY)
    assert v.state is BreakerState.CLOSED
    assert v.escalation is Escalation.NONE


def test_default_escalation_is_none_advisory_floor():
    """The default policy escalates to NONE — the kernel's safe advisory floor."""
    p = BreakerPolicy(max_consecutive=2, max_total=10)  # on_trip defaults to NONE
    v = classify(BreakerCounts(consecutive=2), p)
    assert v.state is BreakerState.OPEN
    assert v.escalation is Escalation.NONE
    # No escalation clause in the reason when NONE.
    assert "escalate" not in v.reason


def test_judge_escalation_rung():
    """A policy can escalate to JUDGE (the ORACLE→JUDGE→HUMAN ladder)."""
    p = BreakerPolicy(max_consecutive=2, max_total=10, on_trip=Escalation.JUDGE)
    v = classify(BreakerCounts(consecutive=2), p)
    assert v.escalation is Escalation.JUDGE
    assert "escalate to JUDGE" in v.reason


# ---------------------------------------------------------------------------
# Rung selection + disabling.
# ---------------------------------------------------------------------------


def test_consecutive_reason_wins_when_both_rungs_would_fire():
    """When both rungs are at their limit, the (more urgent) consecutive reason wins."""
    # consecutive 3 (>=3) AND total 5 (>=5) — both would trip.
    v = classify(BreakerCounts(consecutive=3, total=5), _POLICY)
    assert v.state is BreakerState.OPEN
    assert v.tripped_on == "consecutive"  # the first-checked, more-specific rung


def test_disabled_consecutive_rung_only_total_trips():
    """max_consecutive=0 disables that rung — only the total rung can open."""
    p = BreakerPolicy(max_consecutive=0, max_total=4)
    # 10 in a row would never trip a disabled consecutive rung on its own...
    assert classify(BreakerCounts(consecutive=10, total=3), p).state is BreakerState.CLOSED
    # ...but the total rung trips at 4.
    assert classify(BreakerCounts(consecutive=10, total=4), p).state is BreakerState.OPEN


def test_disabled_total_rung_only_consecutive_trips():
    """max_total=0 disables that rung — only the consecutive rung can open."""
    p = BreakerPolicy(max_consecutive=3, max_total=0)
    assert classify(BreakerCounts(consecutive=2, total=100), p).state is BreakerState.CLOSED
    assert classify(BreakerCounts(consecutive=3, total=100), p).state is BreakerState.OPEN


# ---------------------------------------------------------------------------
# Structural guarantees.
# ---------------------------------------------------------------------------


def test_recording_past_a_trip_stays_open_idempotently():
    """An already-OPEN breaker stays OPEN on further failures (counts only grow)."""
    counts = BreakerCounts(consecutive=3, total=3)
    t = record_failure(counts, _POLICY)
    assert t.verdict.state is BreakerState.OPEN
    assert t.counts == BreakerCounts(consecutive=4, total=4)


def test_transitions_are_pure(monkeypatch):
    """record_failure/record_success/classify make NO I/O."""
    import builtins
    import time as _time

    def _boom(*a, **k):  # pragma: no cover - only fires on a violation
        raise AssertionError("breaker transitions must not perform I/O")

    monkeypatch.setattr(_time, "time", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    counts = BreakerCounts(consecutive=2, total=2)
    assert record_failure(counts, _POLICY).verdict.state is BreakerState.OPEN
    assert record_success(counts, _POLICY).verdict.state is BreakerState.CLOSED
    assert classify(counts, _POLICY).state is BreakerState.CLOSED


def test_verdict_to_dict_round_trips():
    v = classify(BreakerCounts(consecutive=3, total=4), _POLICY)
    d = v.to_dict()
    assert d == {
        "state": "OPEN",
        "escalation": "HUMAN",
        "reason": v.reason,
        "tripped_on": "consecutive",
    }
    assert json.loads(json.dumps(d, sort_keys=True)) == d


def test_is_open_helper():
    assert classify(BreakerCounts(consecutive=3), _POLICY).is_open is True
    assert classify(BreakerCounts(consecutive=1), _POLICY).is_open is False


def test_policy_rejects_negative_thresholds():
    with pytest.raises(ValueError):
        BreakerPolicy(max_consecutive=-1)
    with pytest.raises(ValueError):
        BreakerPolicy(max_total=-1)


def test_policy_rejects_both_rungs_disabled():
    """A breaker that can never trip is a config mistake — refuse it."""
    with pytest.raises(ValueError):
        BreakerPolicy(max_consecutive=0, max_total=0)


def test_counts_reject_negatives():
    with pytest.raises(ValueError):
        BreakerCounts(consecutive=-1)
    with pytest.raises(ValueError):
        BreakerCounts(total=-1)


def test_default_policy_matches_cc_constants():
    """The generic defaults are the CC `denialTracking.ts` values (3 / 20)."""
    p = BreakerPolicy()
    assert p.max_consecutive == 3
    assert p.max_total == 20
    assert p.on_trip is Escalation.NONE


# ---------------------------------------------------------------------------
# The CLI verb (`dos breaker`) — the verdict-is-exit-code.
# ---------------------------------------------------------------------------


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_breaker_cli_closed_exit_zero(tmp_path: Path):
    """Under the limits → CLOSED is exit 0 (the success-is-0 idiom)."""
    r = _run_cli(
        "breaker", "--consecutive", "1", "--total", "1",
        "--max-consecutive", "3", "--max-total", "5",
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "CLOSED" in r.stdout


def test_breaker_cli_open_exit_code(tmp_path: Path):
    """Tripped → OPEN is exit 3 (disjoint from argparse's usage code 2)."""
    r = _run_cli(
        "breaker", "--consecutive", "3", "--max-consecutive", "3", "--max-total", "20",
        cwd=tmp_path,
    )
    assert r.returncode == 3, r.stderr
    assert "OPEN" in r.stdout


def test_breaker_cli_json_carries_escalation(tmp_path: Path):
    """`--json` emits the verdict object with the escalation rung."""
    r = _run_cli(
        "breaker", "--consecutive", "3", "--max-consecutive", "3",
        "--on-trip", "human", "--json",
        cwd=tmp_path,
    )
    assert r.returncode == 3, r.stderr
    obj = json.loads(r.stdout)
    assert obj["state"] == "OPEN"
    assert obj["escalation"] == "HUMAN"
    assert obj["tripped_on"] == "consecutive"


def test_breaker_cli_no_plan(tmp_path: Path):
    """The no-plan rail: runs in a bare dir with NO git, NO plan, NO journal."""
    r = _run_cli("breaker", "--total", "20", cwd=tmp_path)  # default max-total=20
    assert r.returncode == 3, r.stderr
    assert "OPEN" in r.stdout
    assert not (tmp_path / ".dos").exists()


def test_breaker_cli_rejects_both_rungs_disabled(tmp_path: Path):
    """A can-never-trip policy is a contract error (exit 2)."""
    r = _run_cli(
        "breaker", "--consecutive", "5", "--max-consecutive", "0", "--max-total", "0",
        cwd=tmp_path,
    )
    assert r.returncode == 2
    assert "error" in r.stderr.lower()
