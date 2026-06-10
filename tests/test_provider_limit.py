"""Tests for `dos.provider_limit` — the canonical provider-limit category, its
policy table, and the three mappers from the upstream taxonomies.

This module is the PI5 collapse target: it does not classify, it standardizes
the OUTPUT vocabulary the dispatch family shares. The tests pin three contracts:

  1. `policy_for` is TOTAL over `ProviderLimit` (no category ships without a
     policy) and its retry semantics match the kernel's decide() expectations.
  2. The mapper tables are correct for every known upstream token, and defensive
     (unknown → NONE, never a spurious limit).
  3. The canonical overload backoff ladder equals `loop_decide._OVERLOADED_BACKOFF`
     — the two copies (shared source of truth here, hot-path copy there) must not
     drift, or a transient overload would back off differently depending on which
     module the caller read.
"""
from __future__ import annotations

import pytest

from dos.provider_limit import (
    LimitPolicy,
    ProviderLimit,
    from_apply_outcome_token,
    from_quota_error_class,
    from_rate_limit_kind,
    policy_for,
)


# --- 1. policy_for is total + retry semantics are coherent -------------------

def test_policy_for_total_over_enum():
    """Every ProviderLimit member has a policy (exhaustiveness lock — a new
    category cannot be added without giving it a handling policy)."""
    for cat in ProviderLimit:
        pol = policy_for(cat)
        assert isinstance(pol, LimitPolicy)
        assert pol.category is cat


def test_only_transient_overload_is_retryable():
    """The load-bearing split: TRANSIENT_OVERLOAD retries; everything else stops."""
    assert policy_for(ProviderLimit.TRANSIENT_OVERLOAD).retryable_same_iter is True
    for cat in (ProviderLimit.USAGE_WINDOW, ProviderLimit.HARD_QUOTA, ProviderLimit.NONE):
        assert policy_for(cat).retryable_same_iter is False


def test_retryable_iff_has_backoff_ladder():
    """A non-empty backoff ladder is present exactly when the category is
    retryable — an empty ladder on a 'retryable' category (or vice-versa) would
    be an incoherent policy a caller could not act on."""
    for cat in ProviderLimit:
        pol = policy_for(cat)
        assert bool(pol.backoff_seconds) == pol.retryable_same_iter


def test_only_hard_quota_needs_operator_and_no_timer():
    """HARD_QUOTA is the one category a timer cannot clear — it requires an
    operator and does not reset on its own."""
    hq = policy_for(ProviderLimit.HARD_QUOTA)
    assert hq.operator_action_required is True
    assert hq.resets_on_timer is False
    # The two timer-reset categories do reset on their own.
    assert policy_for(ProviderLimit.TRANSIENT_OVERLOAD).resets_on_timer is True
    assert policy_for(ProviderLimit.USAGE_WINDOW).resets_on_timer is True
    # ...and none of the others demand operator action.
    for cat in (ProviderLimit.TRANSIENT_OVERLOAD, ProviderLimit.USAGE_WINDOW, ProviderLimit.NONE):
        assert policy_for(cat).operator_action_required is False


def test_overload_escalates_after_three_others_after_one():
    assert policy_for(ProviderLimit.TRANSIENT_OVERLOAD).escalate_after == 3
    for cat in (ProviderLimit.USAGE_WINDOW, ProviderLimit.HARD_QUOTA, ProviderLimit.NONE):
        assert policy_for(cat).escalate_after == 1


# --- 2. mapper tables --------------------------------------------------------

@pytest.mark.parametrize("kind, expected", [
    ("OVERLOADED", ProviderLimit.TRANSIENT_OVERLOAD),
    ("RATE_LIMITED", ProviderLimit.USAGE_WINDOW),
    ("CREDIT_LOW", ProviderLimit.HARD_QUOTA),
    ("NONE", ProviderLimit.NONE),
    ("something-unknown", ProviderLimit.NONE),  # defensive
])
def test_from_rate_limit_kind(kind, expected):
    assert from_rate_limit_kind(kind) is expected


def test_from_rate_limit_kind_accepts_enum_value_object():
    """The mapper accepts the str-valued enum member directly (str(Kind.X) == 'X')."""
    class _FakeKind(str):
        pass
    assert from_rate_limit_kind(_FakeKind("OVERLOADED")) is ProviderLimit.TRANSIENT_OVERLOAD


@pytest.mark.parametrize("qec, expected", [
    ("rpm_throttled", ProviderLimit.TRANSIENT_OVERLOAD),
    ("transient_429", ProviderLimit.TRANSIENT_OVERLOAD),
    ("daily_quota_exhausted", ProviderLimit.USAGE_WINDOW),
    ("subscription_blackout", ProviderLimit.USAGE_WINDOW),
    ("unknown_class", ProviderLimit.NONE),  # defensive
])
def test_from_quota_error_class(qec, expected):
    assert from_quota_error_class(qec) is expected


@pytest.mark.parametrize("token, expected", [
    ("LLM-QUOTA-EXHAUSTED", ProviderLimit.USAGE_WINDOW),
    ("LLM-QUOTA-EXHAUSTED-DURABLE", ProviderLimit.USAGE_WINDOW),
    ("CORRELATED-OUTAGE", ProviderLimit.NONE),          # an outage, not a limit
    ("BROWSER-SERVICE-UNAVAILABLE", ProviderLimit.NONE),  # an outage, not a limit
    ("SHIPPED", ProviderLimit.NONE),                    # not a limit token at all
])
def test_from_apply_outcome_token(token, expected):
    assert from_apply_outcome_token(token) is expected


# --- 3. cross-module backoff-ladder agreement --------------------------------

def test_overload_backoff_ladder_matches_loop_decide():
    """The canonical ladder here MUST equal loop_decide's hot-path copy, or a
    transient overload would back off differently depending on which module a
    caller read. This is the drift-lock between the two intentional copies."""
    from dos.loop_decide import _OVERLOADED_BACKOFF

    assert policy_for(ProviderLimit.TRANSIENT_OVERLOAD).backoff_seconds == _OVERLOADED_BACKOFF


def test_overload_escalate_matches_loop_decide_default():
    """escalate_after for an overload must equal loop_decide's default
    max_overloaded (the 'stop on the Kth consecutive 529' constant)."""
    from dos.loop_decide import LoopState

    assert policy_for(ProviderLimit.TRANSIENT_OVERLOAD).escalate_after == LoopState().max_overloaded


def test_enum_is_str_valued_round_trip():
    """ProviderLimit round-trips as its str value (token convention)."""
    assert ProviderLimit.USAGE_WINDOW == "usage_window"
    assert str(ProviderLimit.TRANSIENT_OVERLOAD) == "transient_overload"
