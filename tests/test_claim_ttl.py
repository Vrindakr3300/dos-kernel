"""Claim TTL / kind / status math — pure branch logic (MQ3X P1).

Pins the OS7 per-status TTL resolution table, the legacy-row kind/status
inference, the expected-wallclock defaults, and the ``now``-injected
``expires_at_from`` core — all on frozen scalars (no clock, no fs). The defaults
must reproduce the job's historical constants exactly so a ``DEFAULT_POLICY``
caller is byte-identical to the pre-lift code.
"""
from __future__ import annotations

import datetime as dt

import pytest

from dos.claim_ttl import (
    DEFAULT_POLICY,
    VALID_CLAIM_KINDS,
    VALID_CLAIM_STATUSES,
    TtlPolicy,
    expected_wallclock,
    expires_at_from,
    infer_kind,
    infer_status,
    resolve_ttl_minutes,
)


class TestDefaultPolicyMatchesHistoricalConstants:
    def test_default_values(self):
        assert DEFAULT_POLICY.awaiting_commit_minutes == 24 * 60   # 1440
        assert DEFAULT_POLICY.agent_in_session_minutes == 6 * 60   # 360
        assert DEFAULT_POLICY.default_working_wallclock_minutes == 30
        assert DEFAULT_POLICY.working_ttl_multiplier == 3

    def test_negative_policy_rejected(self):
        with pytest.raises(ValueError):
            TtlPolicy(awaiting_commit_minutes=-1)


class TestInferKind:
    def test_explicit_kind_wins(self):
        for k in VALID_CLAIM_KINDS:
            assert infer_kind({"claim_kind": k}) == k

    def test_expires_at_implies_soft(self):
        assert infer_kind({"claim_expires_at": "2026-06-04T01:00Z"}) == "soft"

    # The host supplies its own (dispatched_by-prefix, kind) map; the kernel
    # hardcodes no host dispatcher SKILL name (userland-coupling audit 2026-06-08).
    _HOST_MAP = (("fanout-", "hard"), ("next-up-", "soft"))

    def test_dispatched_by_fanout_is_hard(self):
        assert infer_kind({"dispatched_by": "fanout-20260604T010203Z"},
                          self._HOST_MAP) == "hard"

    def test_dispatched_by_nextup_is_soft(self):
        assert infer_kind({"dispatched_by": "next-up-2026-06-04-1"},
                          self._HOST_MAP) == "soft"

    def test_host_prefix_without_map_is_unknown(self):
        # the kernel default (no map) names no host prefix: a host-dispatched row
        # is `unknown` until the host passes its own dispatcher_kinds.
        assert infer_kind({"dispatched_by": "fanout-20260604T010203Z"}) == "unknown"
        assert infer_kind({"dispatched_by": "next-up-2026-06-04-1"}) == "unknown"

    def test_unknown_fallback(self):
        assert infer_kind({}) == "unknown"
        assert infer_kind({}, self._HOST_MAP) == "unknown"


class TestInferStatus:
    def test_explicit_status_wins(self):
        for s in VALID_CLAIM_STATUSES:
            assert infer_status({"claim_status": s}) == s

    def test_in_progress_implies_working(self):
        assert infer_status({"status": "in_progress"}) == "working"

    def test_falls_back_to_status_field(self):
        assert infer_status({"status": "expired"}) == "expired"
        assert infer_status({}) == "unknown"


class TestExpectedWallclock:
    def test_explicit_ttl_wins(self):
        assert expected_wallclock("hard", 120) == 120

    def test_soft_default(self):
        assert expected_wallclock("soft", None) == 90

    def test_agent_in_session_default(self):
        assert expected_wallclock("agent_in_session", None) == 60

    def test_hard_default(self):
        assert expected_wallclock("hard", None) == 360


class TestResolveTtlMinutes:
    def test_agent_in_session_overrides_status(self):
        assert resolve_ttl_minutes("working", "agent_in_session", 30) == 360
        assert resolve_ttl_minutes("awaiting_commit", "agent_in_session", None) == 360

    def test_working_is_wallclock_times_multiplier(self):
        assert resolve_ttl_minutes("working", "hard", 30) == 90
        assert resolve_ttl_minutes("working", "hard", 120) == 360

    def test_working_uses_default_wallclock_when_absent(self):
        # matches pre-OS7 legacy --ttl-minutes 90 (30 default * 3)
        assert resolve_ttl_minutes("working", "hard", None) == 90

    def test_awaiting_commit_is_24h(self):
        assert resolve_ttl_minutes("awaiting_commit", "hard", None) == 1440

    def test_awaiting_decision_and_stale_are_infinite(self):
        assert resolve_ttl_minutes("awaiting_decision", "hard", 30) is None
        assert resolve_ttl_minutes("stale", "hard", 30) is None

    def test_custom_policy_injection(self):
        pol = TtlPolicy(working_ttl_multiplier=5, default_working_wallclock_minutes=10)
        assert resolve_ttl_minutes("working", "hard", None, pol) == 50


class TestExpiresAtFrom:
    def test_none_ttl_is_none(self):
        now = dt.datetime(2026, 6, 4, 1, 0, tzinfo=dt.timezone.utc)
        assert expires_at_from(now, None) is None

    def test_iso_minute_format(self):
        now = dt.datetime(2026, 6, 4, 1, 0, tzinfo=dt.timezone.utc)
        assert expires_at_from(now, 90) == "2026-06-04T02:30Z"

    def test_injected_now_is_pure(self):
        # same now + ttl -> same answer, no clock dependency
        now = dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
        assert expires_at_from(now, 60) == expires_at_from(now, 60) == "2026-01-01T01:00Z"
