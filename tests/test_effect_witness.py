"""Tests for the effect-witness verdict (`dos.effect_witness`) — docs/181.

The result-state witness DOS named (docs/176/177) as its key member: did the world
actually change the way the agent CLAIMED? This is the join of two independently-
authored facts (the agent's claim + a non-forgeable read-back), folded under the
SAME floor discipline `evidence.believe_under_floor` enforces. The pins here are:

  * the four-valued verdict (CONFIRMED / REFUTED / UNWITNESSED / NO_CLAIM) maps to
    the right read-back shapes;
  * the SECURITY-LOAD-BEARING floor: a read-back on the forgeable floor
    (AGENT_AUTHORED — the agent re-reading its OWN surface) can NEVER reach CONFIRMED
    or REFUTE on its own. The whole soundness rests on this — it is the docs/177
    "silent fail is a verify() problem" made structural: only an out-of-trajectory,
    non-forgeable read-back can corroborate or disconfirm.
  * REFUTED is the silent-frontier-fail detector: an accountable witness re-read the
    world and the claimed effect is ABSENT (a narrated success the world denies).
  * the abstain-never-invent law for effects (NO_CLAIM on an empty claim).
  * PURE — no I/O; we hand it already-gathered EvidenceFacts.
"""
from __future__ import annotations

import pytest

from dos.evidence import Accountability, EvidenceFacts, EvidenceStance
from dos.effect_witness import (
    EffectClaim,
    EffectStance,
    EffectWitnessVerdict,
    witness_effect,
)


# --- helpers: build read-backs at each accountability rung --------------------

def _attest(rung: Accountability, name: str = "probe", subject: str = "e") -> EvidenceFacts:
    return EvidenceFacts.attest(name, rung, subject, detail="re-read: effect present")


def _refute(rung: Accountability, name: str = "probe", subject: str = "e") -> EvidenceFacts:
    return EvidenceFacts.refute(name, rung, subject, detail="re-read: effect absent")


def _no_signal(rung: Accountability, name: str = "probe", subject: str = "e") -> EvidenceFacts:
    return EvidenceFacts.no_signal(name, rung, subject, detail="could not reach")


CLAIM = EffectClaim(key="quiz:Classic-Art-History", narrated="I successfully created the quiz")


# --- CONFIRMED: a non-forgeable read-back saw the effect present --------------

@pytest.mark.parametrize("rung", [Accountability.OS_RECORDED, Accountability.THIRD_PARTY])
def test_confirmed_on_nonforgeable_present(rung):
    v = witness_effect(CLAIM, [_attest(rung)])
    assert v.is_confirmed
    assert v.believe is True
    assert v.refuted is False
    assert v.claim_key == CLAIM.key
    assert v.accountability is rung
    assert "PRESENT" in v.reason


# --- REFUTED: a non-forgeable read-back saw the effect ABSENT (silent fail!) ---

@pytest.mark.parametrize("rung", [Accountability.OS_RECORDED, Accountability.THIRD_PARTY])
def test_refuted_on_nonforgeable_absent(rung):
    """The load-bearing case: the agent claimed success, an accountable witness
    re-read the world and the effect is NOT there. docs/177's silent frontier-fail
    made visible."""
    v = witness_effect(CLAIM, [_refute(rung)])
    assert v.is_refuted
    assert v.believe is False
    assert v.refuted is True
    assert "ABSENT" in v.reason


# --- THE FLOOR: a forgeable read-back can NEVER confirm or refute on its own ----

def test_forgeable_present_cannot_confirm():
    """The agent re-reading its OWN surface (AGENT_AUTHORED) attesting 'present' is
    structurally incapable of CONFIRMED — the whole soundness of the witness."""
    v = witness_effect(CLAIM, [_attest(Accountability.AGENT_AUTHORED)])
    assert not v.is_confirmed
    assert v.believe is False
    assert v.verdict.value == "UNWITNESSED"
    # and it must SAY why the present-looking read-back was ignored
    assert "forgeable floor" in v.reason.lower()


def test_forgeable_absent_cannot_refute():
    """Symmetric: a forgeable-floor 'absent' read-back is too weak to REFUTE on its
    own (the floor cuts both ways — it cannot redden verify either)."""
    v = witness_effect(CLAIM, [_refute(Accountability.AGENT_AUTHORED)])
    assert not v.is_refuted
    assert v.refuted is False
    assert v.verdict.value == "UNWITNESSED"


def test_forgeable_present_plus_accountable_absent_is_refuted():
    """A lying same-surface 'present' cannot override an accountable 'absent'. The
    forgeable attest is IGNORED for belief; the accountable refute stands."""
    v = witness_effect(
        CLAIM,
        [_attest(Accountability.AGENT_AUTHORED, name="self"), _refute(Accountability.OS_RECORDED, name="probe")],
    )
    assert v.is_refuted
    assert v.refuted is True
    assert v.believe is False


# --- UNWITNESSED: no accountable witness reached a presence answer --------------

def test_unwitnessed_on_no_signal():
    v = witness_effect(CLAIM, [_no_signal(Accountability.THIRD_PARTY)])
    assert v.verdict.value == "UNWITNESSED"
    assert v.believe is False
    assert v.refuted is False
    assert "no signal" in v.reason.lower() or "could not tell" in v.reason.lower()


def test_unwitnessed_on_empty_readbacks():
    v = witness_effect(CLAIM, [])
    assert v.verdict.value == "UNWITNESSED"
    assert v.believe is False


# --- NO_CLAIM: abstain, never invent -------------------------------------------

def test_no_claim_when_claim_none():
    v = witness_effect(None, [_attest(Accountability.THIRD_PARTY)])
    assert v.verdict.value == "NO_CLAIM"
    assert v.believe is False
    assert v.refuted is False


def test_no_claim_when_key_blank():
    v = witness_effect(EffectClaim(key="   "), [_attest(Accountability.THIRD_PARTY)])
    assert v.verdict.value == "NO_CLAIM"
    # an empty claim is NOT a pass — believe stays False
    assert v.believe is False


# --- CONFLICT: accountable witnesses disagree → conservative REFUTED + route ----

def test_conflict_accountable_disagree_is_not_believed():
    v = witness_effect(
        CLAIM,
        [_attest(Accountability.THIRD_PARTY, name="api"), _refute(Accountability.OS_RECORDED, name="db")],
    )
    # a contested effect is NOT cleanly confirmed
    assert v.believe is False
    assert v.refuted is True
    assert "CONFLICT" in v.reason


# --- multi-witness: one accountable present is enough to CONFIRM ---------------

def test_one_accountable_present_among_silent_confirms():
    v = witness_effect(
        CLAIM,
        [
            _no_signal(Accountability.THIRD_PARTY, name="api"),
            _attest(Accountability.OS_RECORDED, name="db"),
        ],
    )
    assert v.is_confirmed
    assert v.believe is True
    assert "db" in v.reason
    # the unreachable witness is named as silent
    assert "api" in v.silent_witnesses


# --- the probe_subject bridge --------------------------------------------------

def test_probe_subject_prefers_subject_over_key():
    c = EffectClaim(key="orders:row:42", subject="curl -fsS https://api/orders/42")
    assert c.probe_subject() == "curl -fsS https://api/orders/42"
    assert EffectClaim(key="k").probe_subject() == "k"


# --- to_dict shape (the --json / decisions-queue consumer) ---------------------

def test_to_dict_shape():
    v = witness_effect(CLAIM, [_attest(Accountability.THIRD_PARTY, name="api")])
    d = v.to_dict()
    assert d["verdict"] == "CONFIRMED"
    assert d["believe"] is True
    assert d["claim_key"] == CLAIM.key
    assert d["accountability"] == "THIRD_PARTY"
    assert d["witness"] == "api"
    assert isinstance(d["silent_witnesses"], list)


# --- the effect-stance helper mapping (defensive: stance preserved, never upgraded)

def test_effect_stance_mapping():
    from dos.effect_witness import _effect_stance_of
    assert _effect_stance_of(_attest(Accountability.THIRD_PARTY)) is EffectStance.PRESENT
    assert _effect_stance_of(_refute(Accountability.THIRD_PARTY)) is EffectStance.ABSENT
    assert _effect_stance_of(_no_signal(Accountability.THIRD_PARTY)) is EffectStance.INDETERMINATE
