"""Tests for `dos.pick_priority` — the freshness sort-key producer (docs/254).

Groups:
  * the pure fold — NEVER_ATTEMPTED vs ATTEMPTED, the last-attempt stamp, the
    fail-open degrade (no summary / garbled stamp → never-attempted, never raises);
  * the load-bearing `sort_key` — (0,0) for fresh, (1, last_attempt_ms) for attempted;
  * `TestOrderingContract` — the keystone: fresh-first, then LRU among attempted;
  * `TestCrossTierSafety` — freshness is a TIE-BREAKER: appended to (priority,
    status, …) it never reorders across tiers (a P1 attempted unit still beats a P2
    never-attempted one) — the safety invariant the whole change rests on;
  * `TestCli` — the `dos pick-priority` verb maps the verdict to the exit code and
    derives the per-unit summary from the attempt list.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from dos import pick_priority as _pp
from dos.pick_priority import (
    AttemptSummary,
    Freshness,
    PickPriority,
    classify,
)


HOUR = 60 * 60 * 1000
NOW = 100 * HOUR  # a fixed clock (ms), for legible relative stamps


# ---------------------------------------------------------------------------
# The pure fold.
# ---------------------------------------------------------------------------


class TestFold:
    def test_no_summary_is_never_attempted(self):
        v = classify("U1", None)
        assert v.freshness is Freshness.NEVER_ATTEMPTED
        assert v.is_fresh
        assert v.sort_key == (0, 0)

    def test_explicit_never_summary(self):
        v = classify("U1", AttemptSummary.never())
        assert v.freshness is Freshness.NEVER_ATTEMPTED
        assert v.sort_key == (0, 0)

    def test_attempted_carries_stamp(self):
        v = classify("U1", AttemptSummary.at(NOW - 3 * HOUR))
        assert v.freshness is Freshness.ATTEMPTED
        assert not v.is_fresh
        assert v.last_attempt_ms == NOW - 3 * HOUR
        assert v.sort_key == (1, NOW - 3 * HOUR)

    def test_attempted_with_no_stamp_is_most_stale(self):
        # A present-but-unstamped attempt still sorts as ATTEMPTED, earliest among
        # them (stamp coerces to 0) — degrade-never-crash.
        v = classify("U1", AttemptSummary(attempted=True, last_attempt_ms=None))
        assert v.freshness is Freshness.ATTEMPTED
        assert v.sort_key == (1, 0)

    def test_garbled_stamp_coerces_to_zero(self):
        v = classify("U1", AttemptSummary(attempted=True, last_attempt_ms="not-an-int"))  # type: ignore[arg-type]
        assert v.freshness is Freshness.ATTEMPTED
        assert v.sort_key == (1, 0)

    def test_never_raises_on_bad_input(self):
        # A non-AttemptSummary object → fail-open to never-attempted, never a raise.
        v = classify("U1", object())  # type: ignore[arg-type]
        assert v.freshness is Freshness.NEVER_ATTEMPTED

    def test_to_dict_round_trips(self):
        d = classify("U1", AttemptSummary.at(5000)).to_dict()
        assert d["freshness"] == "ATTEMPTED"
        assert d["last_attempt_ms"] == 5000
        assert d["sort_key"] == [1, 5000]
        assert d["unit_id"] == "U1"


# ---------------------------------------------------------------------------
# The keystone: the ordering contract. Fresh first, then LRU among attempted.
# ---------------------------------------------------------------------------


class TestOrderingContract:
    def test_fresh_then_lru(self):
        # never-attempted, tried 1h ago, tried 18h ago → [never, 18h-ago, 1h-ago].
        never = classify("NEVER", AttemptSummary.never())
        recent = classify("RECENT", AttemptSummary.at(NOW - 1 * HOUR))
        stale = classify("STALE", AttemptSummary.at(NOW - 18 * HOUR))
        order = sorted([recent, never, stale], key=lambda v: v.sort_key)
        assert [v.unit_id for v in order] == ["NEVER", "STALE", "RECENT"]

    def test_all_fresh_keep_tie(self):
        # Two never-attempted units tie on the freshness key (a later key breaks it).
        a = classify("A", AttemptSummary.never())
        b = classify("B", AttemptSummary.never())
        assert a.sort_key == b.sort_key == (0, 0)

    def test_fresh_always_before_any_attempted(self):
        never = classify("N", AttemptSummary.never())
        # Even an attempt at ms=0 (the most-stale possible) sorts after fresh.
        ancient = classify("A", AttemptSummary.at(0))
        assert never.sort_key < ancient.sort_key


# ---------------------------------------------------------------------------
# The safety invariant: freshness is a within-tier tie-breaker only.
# ---------------------------------------------------------------------------


class TestCrossTierSafety:
    """Freshness is APPENDED to the host's (priority, status, …) key, so it can only
    reorder within a tier — never across one, never in/out of the candidate set."""

    @staticmethod
    def _host_key(priority: int, status_rank: int, pp: PickPriority, unit_id: str):
        # The exact shape the host builds: (priority, status, *freshness, id).
        return (priority, status_rank, *pp.sort_key, unit_id)

    def test_priority_beats_freshness(self):
        # A P1 ATTEMPTED unit must still outrank a P2 NEVER_ATTEMPTED unit — freshness
        # never overrides operator priority.
        p1_attempted = self._host_key(
            1, 0, classify("P1U", AttemptSummary.at(NOW - 1 * HOUR)), "P1U")
        p2_fresh = self._host_key(
            2, 0, classify("P2U", AttemptSummary.never()), "P2U")
        assert p1_attempted < p2_fresh

    def test_freshness_breaks_within_tier(self):
        # SAME priority + status → freshness decides: the fresh one wins.
        same_fresh = self._host_key(1, 0, classify("F", AttemptSummary.never()), "F")
        same_attempted = self._host_key(
            1, 0, classify("A", AttemptSummary.at(NOW - 1 * HOUR)), "A")
        assert same_fresh < same_attempted

    def test_id_tiebreaker_is_last(self):
        # Two units identical on (priority, status, freshness) fall back to id —
        # replay determinism is preserved.
        a = self._host_key(1, 0, classify("AAA", AttemptSummary.never()), "AAA")
        b = self._host_key(1, 0, classify("BBB", AttemptSummary.never()), "BBB")
        assert a < b  # AAA before BBB, purely on the id tiebreaker


# ---------------------------------------------------------------------------
# The CLI verb — verdict-is-the-exit-code + per-unit summary derivation.
# ---------------------------------------------------------------------------


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "pick-priority", *args],
        capture_output=True, text=True,
    )


class TestCli:
    def test_empty_attempts_is_never_attempted_exit_0(self):
        r = _run("AUTH3", "--attempts", "[]", "--json")
        assert r.returncode == 0
        d = json.loads(r.stdout)
        assert d["freshness"] == "NEVER_ATTEMPTED"
        assert d["sort_key"] == [0, 0]

    def test_attempted_takes_newest_stamp_exit_3(self):
        attempts = json.dumps([
            {"op": "ATTEMPT", "unit_id": "AUTH3", "attempted_at_ms": 5000},
            {"op": "ATTEMPT", "unit_id": "AUTH3", "attempted_at_ms": 9000},
        ])
        r = _run("AUTH3", "--attempts", attempts, "--json")
        assert r.returncode == 3
        d = json.loads(r.stdout)
        assert d["freshness"] == "ATTEMPTED"
        assert d["last_attempt_ms"] == 9000  # the NEWEST of the two

    def test_other_unit_ignored(self):
        # Only AUTH3 was attempted; querying OTHER → never-attempted.
        attempts = json.dumps([{"op": "ATTEMPT", "unit_id": "AUTH3", "attempted_at_ms": 5000}])
        r = _run("OTHER", "--attempts", attempts)
        assert r.returncode == 0
        assert "NEVER_ATTEMPTED" in r.stdout

    def test_bad_attempts_json_is_contract_error(self):
        r = _run("AUTH3", "--attempts", "{not json")
        assert r.returncode == _pp_contract_error()


def _pp_contract_error() -> int:
    # The contract-error code the CLI returns for malformed --attempts (ExitMap
    # default unknown=5 → contract_error). Imported indirectly to avoid coupling the
    # test to the literal.
    from dos import cli
    return cli._PICK_PRIORITY_EXIT_CONTRACT_ERROR
