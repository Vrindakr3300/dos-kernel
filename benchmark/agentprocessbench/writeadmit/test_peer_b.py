"""$0 unit tests for the peer-B handoff/arm constructor (docs/229).

Proves the testable core (`handoff_text`, the CONTROL INVARIANT) with hand-built A-rows and
NO model, NO tau2 clone, NO network — the same discipline as test_gate.py. The live tau2
`InitialState` builder (`handoff`) is exercised by a guarded test that skips when tau2 is
absent, so this file is green on a bare checkout.
"""

from __future__ import annotations

import pytest

from benchmark.agentprocessbench.writeadmit.peer_b import (
    AHandoff,
    BELIEVE,
    ADJUDICATE,
    handoff_text,
    control_invariant_holds,
    _GATE_BLOCK_CORRECTION,
    _BELIEVE_HANDOFF_PREFIX,
)


def _row(*, domain="airline", task_id="1", answer="", confident_write=False,
         admit=True, db_match=None, claim_key=""):
    return {
        "domain": domain, "task_id": task_id, "answer_excerpt": answer,
        "confident_write": confident_write, "admit": admit, "db_match": db_match,
        "claim_key": claim_key,
    }


# --- AHandoff.from_row + is_overclaim -------------------------------------------------

def test_from_row_maps_fields():
    a = AHandoff.from_row(_row(answer="Your reservation has been cancelled.",
                               confident_write=True, admit=False, db_match=False,
                               claim_key="cancel_reservation"))
    assert a.domain == "airline" and a.task_id == "1"
    assert a.claim_text == "Your reservation has been cancelled."
    assert a.confident_write is True and a.admit is False
    assert a.db_match is False and a.claim_key == "cancel_reservation"


def test_is_overclaim_only_when_confident_write_and_refuted():
    # the slice ΔB is measured on
    assert AHandoff.from_row(_row(confident_write=True, db_match=False)).is_overclaim is True
    # honest confirmed write -> not an over-claim
    assert AHandoff.from_row(_row(confident_write=True, db_match=True)).is_overclaim is False
    # no confident write -> never an over-claim, even on a False witness
    assert AHandoff.from_row(_row(confident_write=False, db_match=False)).is_overclaim is False
    # no witness -> not an over-claim (the floor abstains)
    assert AHandoff.from_row(_row(confident_write=True, db_match=None)).is_overclaim is False


# --- handoff_text: the believe arm ----------------------------------------------------

def test_believe_carries_As_raw_claim():
    a = AHandoff.from_row(_row(answer="Your reservation M05KNL has been successfully updated.",
                               confident_write=True, admit=True, db_match=True))
    t = handoff_text(a, BELIEVE)
    assert t.startswith(_BELIEVE_HANDOFF_PREFIX)
    assert "M05KNL has been successfully updated" in t


def test_believe_handles_empty_claim():
    a = AHandoff.from_row(_row(answer="", confident_write=False))
    t = handoff_text(a, BELIEVE)
    assert _BELIEVE_HANDOFF_PREFIX in t and "left no summary" in t


# --- handoff_text: the adjudicate arm + the control invariant -------------------------

def test_adjudicate_on_blocked_row_is_the_correction():
    # BLOCKED row (confident write, witness refuted) -> adjudicate hands B the env correction
    a = AHandoff.from_row(_row(answer="Your reservation has been cancelled.",
                               confident_write=True, admit=False, db_match=False,
                               claim_key="cancel_reservation"))
    t = handoff_text(a, ADJUDICATE)
    assert t == _GATE_BLOCK_CORRECTION
    assert "did NOT take effect" in t
    # and it DIFFERS from believe (the flipped inheritance)
    assert handoff_text(a, BELIEVE) != t


def test_adjudicate_on_admitted_row_equals_believe_CONTROL_INVARIANT():
    # the heart of it: when the gate ADMITTED (honest write, or no witness), the adjudicate
    # handoff must be byte-identical to believe -> ΔB control arm is ≈0 by construction.
    for db in (True, None):
        a = AHandoff.from_row(_row(answer="Your reservation has been successfully updated.",
                                   confident_write=True, admit=True, db_match=db))
        assert handoff_text(a, ADJUDICATE) == handoff_text(a, BELIEVE), f"db_match={db}"


def test_control_invariant_holds_helper():
    # admitted -> believe==adjudicate -> invariant holds
    admitted = AHandoff.from_row(_row(confident_write=True, admit=True, db_match=True,
                                      answer="done"))
    assert control_invariant_holds(admitted) is True
    # blocked -> believe!=adjudicate -> the helper's "they must differ" branch holds
    blocked = AHandoff.from_row(_row(confident_write=True, admit=False, db_match=False,
                                     answer="done", claim_key="cancel_reservation"))
    assert control_invariant_holds(blocked) is True


def test_unknown_arm_raises():
    a = AHandoff.from_row(_row())
    with pytest.raises(ValueError):
        handoff_text(a, "trust-me")


# --- trust_handoff posture (docs/230 localization experiment) -------------------------

def test_trust_handoff_prepends_directive_both_arms():
    from benchmark.agentprocessbench.writeadmit.peer_b import _TRUST_DIRECTIVE
    a = AHandoff.from_row(_row(answer="Your reservation has been cancelled.",
                               confident_write=True, admit=False, db_match=False,
                               claim_key="cancel_reservation"))
    for arm in (BELIEVE, ADJUDICATE):
        t = handoff_text(a, arm, trust_handoff=True)
        assert t.startswith(_TRUST_DIRECTIVE)
        # the underlying arm content is still present after the directive
        assert handoff_text(a, arm, trust_handoff=False) in t


def test_trust_handoff_preserves_control_invariant():
    # the directive is added to BOTH arms, so on an admitted row believe==adjudicate STILL
    # holds (we change B's posture, not the handoff's truth — the cross-arm contrast is intact)
    admitted = AHandoff.from_row(_row(answer="done", confident_write=True, admit=True,
                                      db_match=True))
    assert (handoff_text(admitted, BELIEVE, trust_handoff=True)
            == handoff_text(admitted, ADJUDICATE, trust_handoff=True))
    # and on a blocked row they still DIFFER (the flip survives the directive)
    blocked = AHandoff.from_row(_row(answer="cancelled", confident_write=True, admit=False,
                                     db_match=False, claim_key="cancel_reservation"))
    assert (handoff_text(blocked, BELIEVE, trust_handoff=True)
            != handoff_text(blocked, ADJUDICATE, trust_handoff=True))


# --- the NON-LLM consumer (docs/236 §5 H3, the keystone) ------------------------------

def test_decide_nonllm_is_arm_blind_and_reads_done_vs_redo():
    from benchmark.agentprocessbench.writeadmit.peer_b import (
        decide_nonllm, PROCEED_AS_DONE, REDO_WORK, _GATE_BLOCK_CORRECTION,
    )
    # a believe-style "done" claim -> a trusting consumer PROCEEDS
    assert decide_nonllm("[handoff from prior agent] Your reservation has been cancelled.") == PROCEED_AS_DONE
    # the gate correction carries explicit re-verify signals -> REDO
    assert decide_nonllm(_GATE_BLOCK_CORRECTION) == REDO_WORK


def test_decide_nonllm_hedged_claim_is_not_a_strawman():
    # a believe-claim whose OWN prose is hedged reads as REDO too -> no poison to propagate.
    # this is why a deflection is computed per-row from the real text, never assigned by arm.
    from benchmark.agentprocessbench.writeadmit.peer_b import decide_nonllm, REDO_WORK
    assert decide_nonllm("[handoff from prior agent] I could not complete the cancellation.") == REDO_WORK
    assert decide_nonllm("[handoff from prior agent] The update was not applied.") == REDO_WORK


def test_nonllm_outcome_only_on_slice_and_directional():
    from benchmark.agentprocessbench.writeadmit.peer_b import nonllm_outcome
    # off-slice (not an over-claim) -> None
    honest = AHandoff.from_row(_row(answer="done", confident_write=True, admit=True, db_match=True))
    assert nonllm_outcome(honest, BELIEVE) is None
    # a blocked over-claim with a "done" claim: believe FAILS (proceeds), adjudicate SUCCEEDS (redo)
    oc = AHandoff.from_row(_row(answer="Your reservation has been cancelled.",
                                confident_write=True, admit=False, db_match=False,
                                claim_key="cancel_reservation"))
    assert nonllm_outcome(oc, BELIEVE) is False
    assert nonllm_outcome(oc, ADJUDICATE) is True


def test_nonllm_deflected_requires_block_and_a_done_claim():
    from benchmark.agentprocessbench.writeadmit.peer_b import nonllm_deflected
    # blocked over-claim, "done" prose -> the poison propagates under believe, prevented under adjudicate
    deflects = AHandoff.from_row(_row(answer="Your reservation has been cancelled.",
                                      confident_write=True, admit=False, db_match=False,
                                      claim_key="cancel_reservation"))
    assert nonllm_deflected(deflects) is True
    # hedged prose -> believe already REDOes -> no deflection
    hedged = AHandoff.from_row(_row(answer="I was not able to cancel the reservation.",
                                    confident_write=True, admit=False, db_match=False,
                                    claim_key="cancel_reservation"))
    assert nonllm_deflected(hedged) is False
    # an over-claim the gate MISSED (admit=True, false-negative) -> adjudicate==believe -> no flip
    missed = AHandoff.from_row(_row(answer="Your reservation has been cancelled.",
                                    confident_write=True, admit=True, db_match=False,
                                    claim_key="cancel_reservation"))
    assert nonllm_deflected(missed) is False


def test_delta_b_of_r_pins_both_endpoints_and_the_llm_case():
    from benchmark.agentprocessbench.writeadmit.peer_b import delta_b_of_r
    # r=0 (non-LLM, no re-verify): ΔB = deflection·feasibility = 1.0  (the §5 H3 endpoint)
    assert delta_b_of_r(0.0, deflection=1.0, feasibility=1.0) == 1.0
    # r=1 (always self-recovers): ΔB = 0
    assert delta_b_of_r(1.0) == 0.0
    # monotone DECREASING in r (more self-recovery -> less payoff for the verdict)
    assert delta_b_of_r(0.25) > delta_b_of_r(0.75)
    # the capable-LLM case: r≈0.6 but residual INFEASIBLE -> ΔB≈0 (docs/235), NOT (1−r)
    assert delta_b_of_r(0.6, deflection=1.0, feasibility=0.0) == 0.0
    # inputs clamp to [0,1]
    assert delta_b_of_r(2.0) == 0.0 and delta_b_of_r(-1.0, feasibility=0.5) == 0.5


def test_blast_radius_curve_is_linear_and_clamped():
    from benchmark.agentprocessbench.writeadmit.peer_b import blast_radius_curve
    assert blast_radius_curve(0.5, max_hops=4) == [0.5, 1.0, 1.5, 2.0]
    assert blast_radius_curve(0.0, max_hops=3) == [0.0, 0.0, 0.0]
    # out-of-range rate is clamped to [0,1]
    assert blast_radius_curve(2.0, max_hops=2) == [1.0, 2.0]
    assert blast_radius_curve(-1.0, max_hops=2) == [0.0, 0.0]


# --- the live tau2 InitialState builder (guarded) -------------------------------------

def test_handoff_builds_valid_initialstate_if_tau2_present():
    pytest.importorskip("tau2.data_model.tasks")
    from benchmark.agentprocessbench.writeadmit.peer_b import handoff
    a = AHandoff.from_row(_row(answer="Your reservation has been cancelled.",
                               confident_write=True, admit=False, db_match=False,
                               claim_key="cancel_reservation"))
    st = handoff(a, ADJUDICATE)
    # a single prior assistant turn carrying the correction
    assert st.message_history is not None and len(st.message_history) == 1
    msg = st.message_history[0]
    assert getattr(msg, "role", None) == "assistant"
    assert "did NOT take effect" in (msg.content or "")
