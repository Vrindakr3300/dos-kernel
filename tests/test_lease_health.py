"""lease_health — pure lease + child-stall verdicts (MQ3X P2).

Pins the two ``classify`` ladders on frozen evidence (injected clock, precomputed
activity_state / sha facts) and the minute-OR-second ISO parser. Defaults must
reproduce the job's historical windows (TTL 50m / stall 8m / quiet 600s).
"""
from __future__ import annotations

import datetime as dt

import pytest

from dos.lease_health import (
    CHILD_ALIVE,
    CHILD_CHURNING,
    CHILD_DEAD,
    CHILD_DOUBLE_ARCHIVE,
    DEFAULT_POLICY,
    LEASE_DEAD,
    LEASE_LIVE,
    LEASE_ORPHANED_WORKING,
    LEASE_STALLED,
    ChildStallResult,
    LeaseHealthPolicy,
    classify_child_stall,
    classify_lease_health,
    parse_iso,
)

_NOW = dt.datetime(2026, 6, 4, 12, 0, tzinfo=dt.timezone.utc)


def _hb(minutes_ago: float) -> str:
    return (_NOW - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%MZ")


class TestParseIso:
    def test_minute_resolution(self):
        assert parse_iso("2026-06-04T12:00Z") == _NOW

    def test_second_resolution(self):
        assert parse_iso("2026-06-04T12:00:30Z") == _NOW.replace(second=30)

    def test_malformed_is_none(self):
        assert parse_iso("not-a-date") is None
        assert parse_iso("") is None
        assert parse_iso(None) is None


class TestLeaseHealthPolicy:
    def test_defaults_match_historical(self):
        assert DEFAULT_POLICY.ttl_minutes == 50.0
        assert DEFAULT_POLICY.stall_threshold_minutes == 8.0

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            LeaseHealthPolicy(ttl_minutes=-1)


class TestClassifyLeaseHealth:
    def test_fresh_heartbeat_is_live(self):
        assert classify_lease_health(
            {"heartbeat_at": _hb(2)}, now=_NOW, activity_state="QUIET") == LEASE_LIVE

    def test_past_ttl_is_dead(self):
        assert classify_lease_health(
            {"heartbeat_at": _hb(60)}, now=_NOW, activity_state="LIVE_DOWNSTREAM") == LEASE_DEAD

    def test_missing_heartbeat_is_dead(self):
        # no timestamp -> age inf -> > ttl -> DEAD
        assert classify_lease_health({}, now=_NOW, activity_state="LIVE_DOWNSTREAM") == LEASE_DEAD

    def test_stale_but_active_is_orphaned_working(self):
        assert classify_lease_health(
            {"heartbeat_at": _hb(20)}, now=_NOW, activity_state="LIVE_DOWNSTREAM") == LEASE_ORPHANED_WORKING

    def test_stale_unknown_is_orphaned_working(self):
        # never reclaim on missing evidence
        assert classify_lease_health(
            {"heartbeat_at": _hb(20)}, now=_NOW, activity_state="UNKNOWN") == LEASE_ORPHANED_WORKING

    def test_stale_and_quiet_is_stalled(self):
        assert classify_lease_health(
            {"heartbeat_at": _hb(20)}, now=_NOW, activity_state="QUIET") == LEASE_STALLED

    def test_falls_back_to_acquired_at(self):
        assert classify_lease_health(
            {"acquired_at": _hb(2)}, now=_NOW, activity_state="QUIET") == LEASE_LIVE

    def test_custom_policy(self):
        pol = LeaseHealthPolicy(ttl_minutes=10, stall_threshold_minutes=2)
        assert classify_lease_health(
            {"heartbeat_at": _hb(15)}, now=_NOW, activity_state="QUIET", policy=pol) == LEASE_DEAD


class TestClassifyChildStall:
    def test_double_archive_wins_first(self):
        r = classify_child_stall(
            log_age_seconds=10, last_commit_sha="a", current_head_sha="b",
            archive_shas=["sha1", "sha2"])
        assert r.verdict == CHILD_DOUBLE_ARCHIVE
        assert r.archive_count == 2

    def test_log_grew_is_alive(self):
        r = classify_child_stall(
            log_age_seconds=100, last_commit_sha="a", current_head_sha="a",
            quiet_window_s=600)
        assert r.verdict == CHILD_ALIVE
        assert r.log_grew is True

    def test_new_commit_is_alive(self):
        r = classify_child_stall(
            log_age_seconds=900, last_commit_sha="aaaa1111", current_head_sha="bbbb2222",
            quiet_window_s=600)
        assert r.verdict == CHILD_ALIVE
        assert r.new_commit is True

    def test_quiet_and_no_commit_is_dead(self):
        r = classify_child_stall(
            log_age_seconds=900, last_commit_sha="a", current_head_sha="a",
            quiet_window_s=600)
        assert r.verdict == CHILD_DEAD

    def test_absent_log_no_commit_is_dead(self):
        r = classify_child_stall(
            log_age_seconds=None, last_commit_sha=None, current_head_sha="a")
        assert r.verdict == CHILD_DEAD

    def test_to_dict_roundtrip(self):
        r = ChildStallResult(CHILD_ALIVE, log_age_seconds=5.0, log_grew=True)
        d = r.to_dict()
        assert d["verdict"] == CHILD_ALIVE and d["log_grew"] is True
        assert d["archive_shas"] == []
        # the ancestry fields default to 0 and round-trip
        assert d["shipped_pick_count"] == 0 and d["registered_pick_count"] == 0


class TestClassifyChildStallChurn:
    """The CHILD_CHURNING verdict: alive-but-wasteful (every registered pick is
    already an ancestor of HEAD). Killing a churner is only safe because the
    caller's shipped count is never-over-counted — so the foreground guard here
    is that shipped < registered NEVER yields CHURNING (a still-producing child
    must fall through to alive)."""

    def test_log_grew_all_shipped_is_churning(self):
        # log still growing (would be ALIVE) but all 3 picks shipped → CHURNING.
        r = classify_child_stall(
            log_age_seconds=30, last_commit_sha="a", current_head_sha="a",
            quiet_window_s=600, registered_pick_count=3, shipped_pick_count=3)
        assert r.verdict == CHILD_CHURNING
        assert r.log_grew is True
        assert r.shipped_pick_count == 3 and r.registered_pick_count == 3

    def test_new_commit_all_shipped_is_churning(self):
        # quiet log but HEAD advanced (would be ALIVE) + all shipped → CHURNING.
        r = classify_child_stall(
            log_age_seconds=900, last_commit_sha="aaaa1111",
            current_head_sha="bbbb2222", quiet_window_s=600,
            registered_pick_count=2, shipped_pick_count=2)
        assert r.verdict == CHILD_CHURNING
        assert r.new_commit is True

    def test_shipped_over_registered_is_churning(self):
        # ancestry count can meet-or-exceed (>=) the registered count.
        r = classify_child_stall(
            log_age_seconds=30, last_commit_sha="a", current_head_sha="a",
            registered_pick_count=2, shipped_pick_count=2)
        assert r.verdict == CHILD_CHURNING

    def test_partial_ship_is_NOT_churning_still_alive(self):
        # KILL-SAFETY: a still-producing child (1 of 3 shipped) must stay ALIVE —
        # never killed mid-work. This is the never-over-count contract's payoff.
        r = classify_child_stall(
            log_age_seconds=30, last_commit_sha="a", current_head_sha="a",
            quiet_window_s=600, registered_pick_count=3, shipped_pick_count=1)
        assert r.verdict == CHILD_ALIVE

    def test_zero_registered_is_never_churning(self):
        # a drain / a /replan registers no picks → can never be "all shipped".
        # (also guards the back-compat path: no counts supplied → ALIVE.)
        r = classify_child_stall(
            log_age_seconds=30, last_commit_sha="a", current_head_sha="a",
            quiet_window_s=600, registered_pick_count=0, shipped_pick_count=0)
        assert r.verdict == CHILD_ALIVE

    def test_all_shipped_but_quiet_and_no_commit_is_dead_not_churning(self):
        # churn requires LIVENESS (log grew or new commit). A genuinely-stopped
        # child whose picks shipped is DEAD (takeover/reconcile), not CHURNING
        # (nothing to TaskStop) — the double-archive/dead paths own that.
        r = classify_child_stall(
            log_age_seconds=900, last_commit_sha="a", current_head_sha="a",
            quiet_window_s=600, registered_pick_count=2, shipped_pick_count=2)
        assert r.verdict == CHILD_DEAD

    def test_double_archive_still_wins_over_churn(self):
        # a self-shipped archive moots the TaskStop regardless of liveness.
        r = classify_child_stall(
            log_age_seconds=30, last_commit_sha="a", current_head_sha="b",
            archive_shas=["s1", "s2"],
            registered_pick_count=2, shipped_pick_count=2)
        assert r.verdict == CHILD_DOUBLE_ARCHIVE

    def test_back_compat_default_args_unchanged(self):
        # the old call signature (no count kwargs) is byte-identical: a growing
        # log is still ALIVE, not CHURNING.
        r = classify_child_stall(
            log_age_seconds=100, last_commit_sha="a", current_head_sha="a",
            quiet_window_s=600)
        assert r.verdict == CHILD_ALIVE
