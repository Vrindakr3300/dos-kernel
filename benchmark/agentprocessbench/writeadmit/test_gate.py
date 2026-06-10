"""Tests for the E-TAU2-WRITEADMIT pure gate (docs/216 §6) — $0, no model, no network.

Pins the kernel join BEFORE any spend: the gate BLOCKs a confident write-claim the witness
refutes, ADMITs an honest success, ADMITs a non-write answer, and — the load-bearing floor
test — can NEVER be talked into a BLOCK *or* an admit-of-a-real-refutation by a FORGEABLE
(agent-authored) read-back. The corpus-backed tests skip cleanly without the cache.
"""
from __future__ import annotations

import pytest

from dos.effect_witness import Accountability, EffectClaim, EvidenceFacts, witness_effect
from .gate import admit, db_witness


# --- pure unit tests (no corpus) -------------------------------------------------------

def test_blocks_confident_write_when_db_refutes():
    """A confident write-claim + db_match==False (env says the write did not land) -> BLOCK."""
    d = admit("Your reservation has been successfully cancelled.", db_match=False)
    assert d.confident_write
    assert d.admit is False
    assert d.verdict == "REFUTED"


def test_admits_confident_write_when_db_attests():
    """A confident write-claim + db_match==True (env confirms) -> ADMIT."""
    d = admit("Your reservation has been successfully cancelled.", db_match=True)
    assert d.confident_write
    assert d.admit is True
    assert d.verdict == "CONFIRMED"


def test_admits_non_write_answer():
    """No write claimed -> nothing to gate -> ADMIT regardless of witness."""
    d = admit("I checked your reservation; here are the available flights.", db_match=False)
    assert d.confident_write is False
    assert d.admit is True
    assert d.verdict == "NO_CLAIM"


def test_no_witness_admits():
    """db_match is None (no env DB check) -> UNWITNESSED -> nothing to refute on -> ADMIT.

    The gate only BLOCKs on a POSITIVE refutation from an accountable witness; absence of a
    witness is not a refusal (fail-open on the publish, fail-closed only on a real refute)."""
    d = admit("Your reservation has been successfully updated.", db_match=None)
    assert d.confident_write
    assert d.admit is True


def test_forgeable_readback_can_never_block():
    """THE FLOOR (docs/216): a read-back the AGENT authored cannot set the refuted bit.

    Even a refute-stance read-back on the AGENT_AUTHORED rung yields UNWITNESSED, not
    REFUTED — so a policy pasting a fake 'verification failed' string into its own answer
    cannot trick the gate into anything, and (the dual) cannot launder a real failure into
    an admit either: only an OS_RECORDED/THIRD_PARTY witness moves the bit."""
    claim = EffectClaim(key="cancel_reservation", subject="effect",
                        narrated="has been successfully cancelled")
    forgeable_refute = [EvidenceFacts.refute(
        "agent_self_report", Accountability.AGENT_AUTHORED, "effect",
        detail="the agent's own claim that verification failed")]
    v = witness_effect(claim, forgeable_refute)
    assert v.refuted is False
    assert v.verdict.value == "UNWITNESSED"


def test_only_os_recorded_witness_refutes():
    """The dual of the floor test: the SAME refute stance on OS_RECORDED DOES refute."""
    claim = EffectClaim(key="cancel_reservation", subject="effect", narrated="cancelled")
    os_refute = db_witness(db_match=False)
    assert os_refute and os_refute[0].accountability == Accountability.OS_RECORDED
    v = witness_effect(claim, os_refute)
    assert v.refuted is True
    assert v.verdict.value == "REFUTED"


# --- corpus-backed: the frozen A/B fold + J arithmetic ---------------------------------

def _corpus_or_skip():
    from benchmark.agentprocessbench.dataset import corpus_root
    try:
        corpus_root()
    except FileNotFoundError:
        pytest.skip("AgentProcessBench cache not on disk (external sibling clone)")


def test_frozen_ab_adjudicate_blocks_every_refuted_write():
    """On the consensus over-claim slice (frozen stand-in: final_label==-1 -> db_match==False),
    the adjudicate arm BLOCKs every confident write the witness refutes, and the believe arm
    lets a peer inherit every one. J (adjudicate) == inherited_phantom (believe)."""
    _corpus_or_skip()
    from .live_loop import frozen_ab
    believe = frozen_ab("believe")
    adjud = frozen_ab("adjudicate")
    # every confident write on the consensus slice is gold-diverged -> refuted -> blocked.
    assert adjud.n_blocked == adjud.n_confident_write
    assert adjud.j_blocked_before_inherit == adjud.n_confident_write
    assert adjud.inherited_phantom == 0
    # the believe arm inherits exactly what the adjudicate arm blocked.
    assert believe.inherited_phantom == adjud.j_blocked_before_inherit
    assert believe.j_blocked_before_inherit == 0
    # the slice is the confident-write subset of the 34-index consensus (>=30 by construction).
    assert adjud.n_confident_write >= 30


def test_gated_live_entry_is_zero_cost_without_key(monkeypatch):
    """run_writeadmit returns 0 (the opt-in message) when GEMINI_API_KEY is absent — no
    tau2-bench import, no spend."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from .live_loop import run_writeadmit
    assert run_writeadmit() == 0
