"""Tests for the enforcement-handler seam (`dos.enforce`) — docs/189 §A1.

The seam that consumes an `intervention.InterventionDecision` and proposes the
effect a host PEP should materialize. The pinned contract:

  The proposal type (advisory-only by shape):
    * `EffectProposal` is frozen and carries nothing mutable; a handler's whole
      expressible output is "dispatch / withhold (+ synthetic) / note".
    * a synthetic_result implies the call is WITHHELD (dispatch_call False) —
      a proposal that both dispatches AND substitutes is rejected at construction.

  The fail-to-OBSERVE guarantee (the load-bearing safety property):
    * `run_handler` converts a RAISE into the zero-disruption OBSERVE proposal,
      never a spurious BLOCK/DEFER;
    * `run_handler` converts a non-`EffectProposal` return into OBSERVE;
    * the asymmetry vs judges is deliberate: a handler fails to "do nothing"
      (actuation), a judge fails to "I don't know" (adjudication) — neither to
      the dangerous outcome for its role.

  The no-escalation guarantee:
    * a handler may DE-escalate (propose a no-more-disruptive rung) but a proposal
      MORE disruptive than the kernel's recommendation is clamped down to OBSERVE.

  The built-in baseline + resolution:
    * `ObserveHandler` ("observe") is built-in, always resolvable, observes on all;
    * a plugin CANNOT shadow the built-in `observe` (built-ins resolve first);
    * an unknown handler name fails LOUD with the known list (no silent fallback);
    * discovery faults degrade to the built-in, never crash a call.
"""

from __future__ import annotations

import pytest

from dos import enforce
from dos.enforce import (
    EffectProposal,
    EnforcementHandler,
    ObserveHandler,
    active_handler_names,
    active_handlers,
    resolve_handler,
    run_handler,
)
from dos.intervention import (
    BASE_INTERVENTIONS,
    Confidence,
    Intervention,
    InterventionDecision,
    InterventionSpec,
    choose_intervention,
)
from dos.arg_provenance import (
    ArgProvenance,
    ProvenanceStance,
    ProvenanceVerdict,
)


# ---------------------------------------------------------------------------
# Decision builders — small fixtures so a test names its confidence rung clearly.
# ---------------------------------------------------------------------------
def _decision(intervention: Intervention) -> InterventionDecision:
    """A minimal InterventionDecision pinned to a given rung (for handler tests)."""
    return InterventionDecision(
        intervention=intervention,
        confidence=Confidence.HIGH if intervention is Intervention.BLOCK else Confidence.NONE,
        rung=BASE_INTERVENTIONS.get(intervention.value),
        disruption_cost=BASE_INTERVENTIONS.disruption_cost(intervention.value),
        unsupported=("INC9999999",) if intervention is not Intervention.OBSERVE else (),
        reason=f"test decision pinned to {intervention.value}",
    )


def _clean_decision() -> InterventionDecision:
    """A real NONE→OBSERVE decision from a believe=True verdict (end-to-end thread)."""
    v = ProvenanceVerdict(believe=True, args=(), unsupported=(), reason="clean")
    return choose_intervention(v)


def _mint_arg(arg_name: str = "incident_id") -> ArgProvenance:
    """A whole-value-absent scalar mint ArgProvenance (the HIGH-confidence shape)."""
    return ArgProvenance(
        arg_name=arg_name,
        value_repr="INC9999999",
        stance=ProvenanceStance.UNSUPPORTED,
        id_shaped=True,
        is_reference=True,
        matched_in=(),
        components_checked=("9999999",),
        components_unmatched=("9999999",),
        reason="value never appeared in any prior tool result",
    )


def _high_mint_decision() -> InterventionDecision:
    """A real HIGH→BLOCK decision from a whole-value-absent scalar mint."""
    v = ProvenanceVerdict(
        believe=False, args=(_mint_arg(),), unsupported=("incident_id",),
        reason="minted id",
    )
    return choose_intervention(v)


# ---------------------------------------------------------------------------
# EffectProposal — frozen, advisory, the coherence invariant.
# ---------------------------------------------------------------------------
def test_effect_proposal_is_frozen():
    p = EffectProposal(intervention=Intervention.OBSERVE, dispatch_call=True)
    with pytest.raises(Exception):
        p.dispatch_call = False  # type: ignore[misc]


def test_synthetic_result_implies_withheld_call():
    # a BLOCK proposal substitutes a synthetic result and withholds the call — ok
    ok = EffectProposal(
        intervention=Intervention.BLOCK, dispatch_call=False,
        synthetic_result={"status": "blocked"},
    )
    assert ok.withholds_call is True
    # a proposal that BOTH dispatches the real call AND substitutes is incoherent
    with pytest.raises(ValueError):
        EffectProposal(
            intervention=Intervention.WARN, dispatch_call=True,
            synthetic_result={"status": "blocked"},
        )


def test_withholds_call_is_the_complement_of_dispatch():
    assert EffectProposal(Intervention.OBSERVE, True).withholds_call is False
    assert EffectProposal(Intervention.DEFER, False).withholds_call is True


def test_to_dict_round_trips_the_fields():
    p = EffectProposal(
        intervention=Intervention.BLOCK, dispatch_call=False,
        synthetic_result={"k": 1}, note="n", handler="h", reason="r",
    )
    d = p.to_dict()
    assert d == {
        "intervention": "BLOCK", "dispatch_call": False,
        "synthetic_result": {"k": 1}, "note": "n", "handler": "h", "reason": "r",
    }


# ---------------------------------------------------------------------------
# ObserveHandler — the built-in, observe-only floor.
# ---------------------------------------------------------------------------
def test_observe_handler_is_built_in_and_observes_only():
    h = ObserveHandler()
    # even a BLOCK decision is actuated as a non-disruptive OBSERVE by the built-in
    p = run_handler(h, _decision(Intervention.BLOCK), object())
    assert p.intervention is Intervention.OBSERVE
    assert p.dispatch_call is True       # the call ALWAYS fires under the built-in
    assert p.withholds_call is False
    assert p.synthetic_result is None
    assert p.handler == "observe"


def test_observe_handler_satisfies_the_protocol():
    assert isinstance(ObserveHandler(), EnforcementHandler)


# ---------------------------------------------------------------------------
# run_handler — fail-to-OBSERVE (the load-bearing safety property).
# ---------------------------------------------------------------------------
class _Raises:
    name = "boom"

    def handle(self, decision, config):
        raise RuntimeError("kaboom")


class _BadReturn:
    name = "badret"

    def handle(self, decision, config):
        return {"not": "a proposal"}  # wrong type — must not be trusted


class _ReturnsNone:
    name = "none"

    def handle(self, decision, config):
        return None


@pytest.mark.parametrize("handler", [_Raises(), _BadReturn(), _ReturnsNone()])
def test_run_handler_fails_to_observe_never_blocks(handler):
    # a faulting handler on a BLOCK decision must NOT withhold the call — the safe
    # failure for actuation is "do nothing", never a spurious block (the -9pp lesson).
    p = run_handler(handler, _decision(Intervention.BLOCK), object())
    assert p.intervention is Intervention.OBSERVE
    assert p.dispatch_call is True
    assert p.withholds_call is False
    assert p.synthetic_result is None
    # the failure is named in the reason for the audit log
    assert handler.name in p.reason


def test_run_handler_failure_is_asymmetric_with_judges():
    # judges fail-to-ABSTAIN (never auto-CLEAR); handlers fail-to-OBSERVE (never
    # auto-DISRUPT). Both refuse the dangerous outcome for their role; they differ
    # in which outcome is dangerous. Pin that a handler failure dispatches the call.
    p = run_handler(_Raises(), _decision(Intervention.DEFER), object())
    assert p.dispatch_call is True  # call goes through — the opposite of a block


def test_run_handler_passes_through_a_well_typed_proposal():
    class _Good:
        name = "good"

        def handle(self, decision, config):
            return EffectProposal(
                intervention=Intervention.WARN, dispatch_call=True, note="seen it"
            )

    p = run_handler(_Good(), _decision(Intervention.WARN), object())
    assert p.intervention is Intervention.WARN
    assert p.note == "seen it"
    assert p.handler == "good"  # run_handler stamps the name if the handler left it blank


# ---------------------------------------------------------------------------
# run_handler — no-escalation (a handler can de-escalate, never escalate).
# ---------------------------------------------------------------------------
def test_run_handler_clamps_an_escalating_proposal():
    # handler tries to BLOCK on a decision the kernel only rated OBSERVE → clamped down
    class _Overreach:
        name = "over"

        def handle(self, decision, config):
            return EffectProposal(
                intervention=Intervention.BLOCK, dispatch_call=False,
                synthetic_result={"x": 1},
            )

    p = run_handler(_Overreach(), _decision(Intervention.OBSERVE), object())
    assert p.intervention is Intervention.OBSERVE  # clamped back down
    assert p.dispatch_call is True                  # and the call is NOT withheld
    assert "more disruptive" in p.reason


def test_run_handler_allows_a_de_escalating_proposal():
    # handler proposes WARN on a decision the kernel rated BLOCK — LESS disruptive, ok
    class _DeEscalate:
        name = "down"

        def handle(self, decision, config):
            return EffectProposal(
                intervention=Intervention.WARN, dispatch_call=True, note="just warn"
            )

    p = run_handler(_DeEscalate(), _decision(Intervention.BLOCK), object())
    assert p.intervention is Intervention.WARN  # honored — de-escalation is allowed
    assert p.dispatch_call is True


def test_run_handler_honors_an_equal_rung_proposal():
    # a handler that proposes exactly the kernel's rung is honored (not clamped)
    class _Equal:
        name = "eq"

        def handle(self, decision, config):
            return EffectProposal(
                intervention=Intervention.BLOCK, dispatch_call=False,
                synthetic_result={"status": "blocked"},
            )

    p = run_handler(_Equal(), _decision(Intervention.BLOCK), object())
    assert p.intervention is Intervention.BLOCK
    assert p.withholds_call is True
    assert p.synthetic_result == {"status": "blocked"}


# ---------------------------------------------------------------------------
# Resolution — built-in first, unshadowable, loud-unknown, fault-tolerant.
# ---------------------------------------------------------------------------
def test_resolve_built_in_observe():
    assert resolve_handler("observe").name == "observe"


def test_unknown_handler_fails_loud_with_known_list():
    with pytest.raises(ValueError) as ei:
        resolve_handler("nope")
    assert "unknown enforce handler 'nope'" in str(ei.value)
    assert "observe" in str(ei.value)  # the known list is shown


def test_active_handlers_lists_builtin_then_discovered(monkeypatch):
    # with no plugins, exactly the built-in is active
    monkeypatch.setattr(enforce, "_discover_entry_point_handlers", lambda *, _stderr=None: [])
    assert active_handler_names() == ["observe"]
    names = [n for n, _h in active_handlers()]
    assert names == ["observe"]


def test_plugin_cannot_shadow_builtin_observe(monkeypatch):
    # a plugin registering the name "observe" must NOT displace the built-in floor
    class _FakeObserve:
        name = "observe"

        def handle(self, decision, config):
            # a hostile shadow that tries to BLOCK everything
            return EffectProposal(
                intervention=Intervention.BLOCK, dispatch_call=False,
                synthetic_result={"hijacked": True},
            )

    monkeypatch.setattr(
        enforce, "_discover_entry_point_handlers",
        lambda *, _stderr=None: [("observe", _FakeObserve())],
    )
    resolved = resolve_handler("observe")
    # built-ins resolve FIRST → we get the real ObserveHandler, not the shadow
    assert isinstance(resolved, ObserveHandler)
    p = run_handler(resolved, _decision(Intervention.BLOCK), object())
    assert p.dispatch_call is True  # the floor still observes, the shadow is ignored


def test_discovery_fault_degrades_to_builtin(monkeypatch):
    def _boom(*, _stderr=None):
        raise RuntimeError("discovery exploded")

    # active_handlers must not crash if discovery itself raises... but our discovery
    # helper is what swallows plugin faults; simulate a hard discovery failure and
    # confirm resolve of the built-in still works (built-in path never touches discovery).
    monkeypatch.setattr(enforce, "_discover_entry_point_handlers", _boom)
    assert resolve_handler("observe").name == "observe"  # built-in path is discovery-free


# ---------------------------------------------------------------------------
# End-to-end — the intervention → enforce thread the consumer will run.
# ---------------------------------------------------------------------------
def test_end_to_end_clean_call_dispatches():
    # a clean (believe=True) call → NONE → OBSERVE → the built-in dispatches it.
    decision = _clean_decision()
    assert decision.intervention is Intervention.OBSERVE
    p = run_handler(resolve_handler("observe"), decision, object())
    assert p.dispatch_call is True
    assert p.withholds_call is False


def test_end_to_end_high_mint_under_builtin_still_observes():
    # a HIGH mint → BLOCK decision, but under the OBSERVE built-in it is NOT withheld:
    # escalation past OBSERVE is opt-in (requires a ruling driver). This pins that the
    # kernel default never disrupts even on a strong catch.
    decision = _high_mint_decision()
    assert decision.intervention is Intervention.BLOCK  # the kernel RECOMMENDS block
    p = run_handler(resolve_handler("observe"), decision, object())
    assert p.intervention is Intervention.OBSERVE       # the built-in does not act on it
    assert p.dispatch_call is True


def test_end_to_end_ruling_handler_actuates_a_block():
    # a driver-style ruling handler that honors the kernel's BLOCK and substitutes the
    # synthetic corrective result — the actuation the built-in declines to perform.
    from dos.intervention import synthetic_corrective_result

    class _BlockingHandler:
        name = "blocker"

        def handle(self, decision, config):
            if decision.intervention is Intervention.BLOCK:
                # build the corrective payload from the decision's unsupported args
                v = ProvenanceVerdict(
                    believe=False, args=(_mint_arg(decision.unsupported[0]),),
                    unsupported=decision.unsupported, reason="minted",
                )
                synth = synthetic_corrective_result(v, "create_incident")
                return EffectProposal(
                    intervention=Intervention.BLOCK, dispatch_call=False,
                    synthetic_result=synth, note=decision.reason,
                )
            return EffectProposal(intervention=Intervention.OBSERVE, dispatch_call=True)

    decision = _high_mint_decision()
    p = run_handler(_BlockingHandler(), decision, object())
    assert p.intervention is Intervention.BLOCK
    assert p.withholds_call is True
    assert p.synthetic_result is not None
    assert p.synthetic_result.get("dos_blocked") is True  # the anti-laundering stamp
    assert p.handler == "blocker"
