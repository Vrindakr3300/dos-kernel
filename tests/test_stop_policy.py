"""Tests for the pluggable loop-STOP policy seam (`dos.stop_policy`) + its scout rung.

The seam lets a host turn a pending-decision class into a real loop STOP, while the
kernel default stays evidence-only. These pin the load-bearing guarantees:

  * **fail-to-DEFER** — a policy that raises or returns the wrong type degrades to
    DEFER, never STOP (a buggy/hostile policy can't manufacture a halt);
  * **the resource floor** — `resource_blocked` STOPs regardless of the policy, and
    a policy can only ADD a halt on top of the floor, never suppress it;
  * **`NeverStopPolicy`** — the unshadowable built-in defers on everything;
  * **the resolver** — built-in first, unknown fails loud;
  * **scout default unchanged** — `ScoutState.stop_policy=None` reproduces today's
    decision, and a wired STOP policy adds a `rule_id=1` STOP only off the floor.
"""

from __future__ import annotations

import pytest

from dos import scout as S
from dos import stop_policy as SP


# ---------------------------------------------------------------------------
# Test doubles.
# ---------------------------------------------------------------------------


class _AlwaysStop:
    name = "always-stop"

    def decide(self, state, config):
        return SP.StopVerdict.stop("halt", cause_key="always", evidence=("e",))


class _AlwaysDefer:
    name = "always-defer"

    def decide(self, state, config):
        return SP.StopVerdict.defer("no opinion")


class _Veto:
    name = "veto"

    def decide(self, state, config):
        return SP.StopVerdict.never("I veto every halt")


class _Raises:
    name = "raises"

    def decide(self, state, config):
        raise RuntimeError("boom")


class _BadReturn:
    name = "bad"

    def decide(self, state, config):
        return "not a StopVerdict"


class _FakeState:
    """The minimal scout-state shape the floor reads (resource_blocked + reason)."""

    def __init__(self, resource_blocked=False, reason=""):
        self.resource_blocked = resource_blocked
        self.resource_block_reason = reason


# ---------------------------------------------------------------------------
# StopVerdict — the three-valued ruling.
# ---------------------------------------------------------------------------


class TestStopVerdict:
    def test_stop_should_stop(self):
        v = SP.StopVerdict.stop("x", cause_key="k")
        assert v.should_stop is True
        assert v.stance is SP.StopStance.STOP
        assert v.cause_key == "k"

    def test_defer_and_never_are_both_go(self):
        assert SP.StopVerdict.defer("x").should_stop is False
        assert SP.StopVerdict.never("x").should_stop is False
        assert SP.StopVerdict.defer("x").deferred is True
        assert SP.StopVerdict.never("x").deferred is False


# ---------------------------------------------------------------------------
# run_stop_policy — fail-to-DEFER.
# ---------------------------------------------------------------------------


class TestFailToDefer:
    def test_raising_policy_defers(self):
        v = SP.run_stop_policy(_Raises(), _FakeState(), None)
        assert v.stance is SP.StopStance.DEFER
        assert "raised" in v.reason

    def test_bad_return_type_defers(self):
        v = SP.run_stop_policy(_BadReturn(), _FakeState(), None)
        assert v.stance is SP.StopStance.DEFER
        assert "not a StopVerdict" in v.reason

    def test_a_failure_can_never_become_a_stop(self):
        # The whole point: no failure path yields should_stop=True.
        for bad in (_Raises(), _BadReturn()):
            assert SP.run_stop_policy(bad, _FakeState(), None).should_stop is False

    def test_a_well_behaved_stop_passes_through(self):
        assert SP.run_stop_policy(_AlwaysStop(), _FakeState(), None).should_stop is True


# ---------------------------------------------------------------------------
# stop_under_resource_floor — the AND-floor guarantee.
# ---------------------------------------------------------------------------


class TestResourceFloor:
    def test_resource_blocked_stops_regardless_of_policy(self):
        # Even a vetoing policy cannot keep the loop alive past a measured wall.
        st = _FakeState(resource_blocked=True, reason="RAM exhausted")
        v = SP.stop_under_resource_floor(_Veto(), st, None)
        assert v.should_stop is True
        assert v.cause_key == "resource_blocked"
        assert "RAM exhausted" in v.reason

    def test_resource_blocked_stops_even_with_a_raising_policy(self):
        st = _FakeState(resource_blocked=True, reason="slot pool")
        # The floor short-circuits BEFORE the policy is consulted, so a raising
        # policy never even runs — the floor STOP stands.
        assert SP.stop_under_resource_floor(_Raises(), st, None).should_stop is True

    def test_floor_go_plus_policy_stop_adds_a_halt(self):
        v = SP.stop_under_resource_floor(_AlwaysStop(), _FakeState(), None)
        assert v.should_stop is True
        assert v.cause_key == "always"

    def test_floor_go_plus_policy_defer_is_go(self):
        assert SP.stop_under_resource_floor(_AlwaysDefer(), _FakeState(), None).should_stop is False

    def test_a_failing_policy_off_the_floor_does_not_halt(self):
        assert SP.stop_under_resource_floor(_Raises(), _FakeState(), None).should_stop is False


# ---------------------------------------------------------------------------
# NeverStopPolicy + the resolver.
# ---------------------------------------------------------------------------


class TestBuiltInAndResolver:
    def test_never_policy_always_defers(self):
        assert SP.NeverStopPolicy().decide(_FakeState(), None).stance is SP.StopStance.DEFER

    def test_resolve_built_in_never(self):
        p = SP.resolve_stop_policy("never")
        assert isinstance(p, SP.NeverStopPolicy)

    def test_resolve_unknown_fails_loud(self):
        with pytest.raises(ValueError) as ei:
            SP.resolve_stop_policy("does-not-exist")
        assert "unknown stop policy" in str(ei.value)
        assert "never" in str(ei.value)  # lists the known set

    def test_active_default_is_never_no_discovery(self):
        # No config → the built-in never, no entry-point discovery (hot path I/O-free).
        assert isinstance(SP.active_stop_policy(config=None), SP.NeverStopPolicy)


# ---------------------------------------------------------------------------
# The scout rung — default unchanged + a policy adds a STOP.
# ---------------------------------------------------------------------------


class TestScoutRung:
    def test_no_policy_reproduces_default_dispatch(self):
        # With no stop_policy and no blocker, the scout DISPATCHes (rule 9) exactly
        # as before the seam — the byte-identical-default guarantee.
        d = S.choose(S.ScoutState(scope="apply"))
        assert d.activity is S.ScoutActivity.DISPATCH
        assert d.rule_id == 9

    def test_no_policy_with_open_decisions_still_dispatches(self):
        # An open decision is evidence-only when no policy is wired (the kernel
        # default the operator directive froze).
        d = S.choose(S.ScoutState(scope="apply",
                                  open_escalated_decisions=("362", "LIVENESS:api")))
        assert d.activity is S.ScoutActivity.DISPATCH

    def test_wired_stop_policy_adds_a_rule1_stop(self):
        d = S.choose(S.ScoutState(scope="apply", stop_policy=_AlwaysStop()))
        assert d.activity is S.ScoutActivity.STOP
        assert d.rule_id == 1
        assert d.cause_key == "always"

    def test_wired_defer_policy_falls_through_to_dispatch(self):
        d = S.choose(S.ScoutState(scope="apply", stop_policy=_AlwaysDefer()))
        assert d.activity is S.ScoutActivity.DISPATCH
        assert d.rule_id == 9

    def test_resource_blocked_still_wins_as_rule0_over_a_policy(self):
        # rule 0 returns BEFORE the policy rung, so a measured wall is rule_id=0,
        # not the policy's rule_id=1 — the floor is the kernel's, above the seam.
        d = S.choose(S.ScoutState(scope="apply", resource_blocked=True,
                                  resource_block_reason="RAM",
                                  stop_policy=_AlwaysDefer()))
        assert d.activity is S.ScoutActivity.STOP
        assert d.rule_id == 0


# ---------------------------------------------------------------------------
# The reference driver (DecisionClassStopPolicy) — pure mapping.
# ---------------------------------------------------------------------------


class TestDecisionClassDriver:
    def test_default_stop_class_is_liveness(self):
        from dos.drivers.decision_stop import DecisionClassStopPolicy
        p = DecisionClassStopPolicy()
        assert "LIVENESS" in p.stop_classes

    def test_queue_read_fault_degrades_to_defer(self, monkeypatch):
        # A torn/absent queue → DEFER (no spurious halt), with a clear reason.
        from dos.drivers import decision_stop as ds
        import dos.decisions as D
        monkeypatch.setattr(D, "collect_decisions",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("torn")))
        v = ds.DecisionClassStopPolicy().decide(_FakeState(), None)
        assert v.stance is SP.StopStance.DEFER
        assert "could not read the queue" in v.reason
