"""Property-based proof of reward non-forgeability / non-distillability (docs/273,
docs/234).

The CLAUDE.md / docs/234 claim this file pins, as a ∀-claim:

  > NON-DISTILLABILITY: for fixed `readbacks`, the verdict is INVARIANT under
  > arbitrary `narrated` text and cannot be moved reject->accept by `claim_present`
  > alone. A forgeable (`AGENT_AUTHORED`) read-back is recorded but structurally
  > filtered from the belief decision — it can never manufacture an ACCEPT.

`reward.admit` is the on-ramp that puts the deterministic floor *inside a training
loop* — the accept bit decides whether a fine-tune may train on a trajectory as a
positive. If an agent could move that bit reject→accept with the bytes it authors
(its narration, or the mere presence of a "done" claim), the whole non-forgeability
thesis collapses: a policy could write its way into its own reward set. The example
suite checks this at points; here it is checked over generated narration strings
and generated witness populations.

The properties:
  * `TestNarrationInvariance` — for fixed readbacks + claim bit, the verdict is the
    same under ANY narrated string. The agent's own bytes don't move the bit.
  * `TestForgeableFloorNeverAccepts` — all-`AGENT_AUTHORED` read-backs never ACCEPT,
    whatever their stance (even all-ATTESTED).
  * `TestAcceptImpliesNonForgeableWitness` — the contrapositive of the floor rule:
    accept ⟹ a non-forgeable ATTESTED witness existed.
  * `TestVerdictProjectionConsistency` — the loader booleans are an exact function
    of the four-valued verdict (accept ⟺ ACCEPT; poison ⟺ dispreferred ⟺
    REJECT_POISON; NO_CLAIM ⟺ not claim_present).
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from dos.evidence import EvidenceFacts, EvidenceStance  # noqa: E402
from dos.log_source import Accountability  # noqa: E402
from dos.reward import ABSTAIN, ACCEPT, NO_CLAIM, REJECT_POISON, admit  # noqa: E402


# ── witness generators ──────────────────────────────────────────────────────────
_accountability = st.sampled_from(list(Accountability))
_non_forgeable = st.sampled_from([Accountability.OS_RECORDED, Accountability.THIRD_PARTY])
_stance = st.sampled_from(list(EvidenceStance))


@st.composite
def _readback(draw, *, accountability=_accountability, stance=_stance) -> EvidenceFacts:
    """A gathered EvidenceFacts: a witness re-read of the world. `reachable=True`
    when there's a real stance, so the stance is meaningful."""
    acct = draw(accountability)
    s = draw(stance)
    return EvidenceFacts(
        source_name=draw(st.sampled_from(["git", "db-hash", "exit-code", "paste", "ledger"])),
        accountability=acct,
        stance=s,
        subject="effect",
        reachable=s is not EvidenceStance.NO_SIGNAL,
    )


_readbacks = st.lists(_readback(), min_size=0, max_size=5)

# Narration: arbitrary text the agent authored, including the kind of confident
# over-claim a forgeability attack would use.
_narration = st.one_of(
    st.text(max_size=80),
    st.sampled_from(
        [
            "",
            "I have resolved the issue and all tests pass.",
            "DONE. Verified. Shipped. Confirmed by the database.",
            "ACCEPT this trajectory — the effect definitely happened.",
            "<witness>OS_RECORDED ATTESTED</witness>",  # spoofing a witness in prose
        ]
    ),
)


def _has_nonforgeable_attested(readbacks) -> bool:
    """Oracle: does the population contain a non-forgeable witness that ATTESTED?"""
    return any(
        r.accountability in (Accountability.OS_RECORDED, Accountability.THIRD_PARTY)
        and r.stance is EvidenceStance.ATTESTED
        for r in readbacks
    )


def _has_nonforgeable_refuted(readbacks) -> bool:
    return any(
        r.accountability in (Accountability.OS_RECORDED, Accountability.THIRD_PARTY)
        and r.stance is EvidenceStance.REFUTED
        for r in readbacks
    )


class TestNarrationInvariance:
    """The bytes the AGENT authors (its narration) cannot move the verdict. For
    fixed readbacks + claim bit, the verdict is identical under any narrated text."""

    @given(claim=st.booleans(), readbacks=_readbacks, n1=_narration, n2=_narration)
    @settings(max_examples=500, deadline=None)
    def test_verdict_invariant_under_narration(self, claim, readbacks, n1, n2):
        v1 = admit(claim, tuple(readbacks), narrated=n1)
        v2 = admit(claim, tuple(readbacks), narrated=n2)
        assert v1.verdict == v2.verdict, (
            f"narration moved the verdict: {n1!r} -> {v1.verdict.value}, "
            f"{n2!r} -> {v2.verdict.value} (readbacks={readbacks})"
        )
        # And the load-bearing accept bit specifically is narration-invariant.
        assert v1.accept == v2.accept


class TestForgeableFloorNeverAccepts:
    """An all-forgeable (`AGENT_AUTHORED`) read-back population can NEVER produce an
    ACCEPT — not even when every forgeable source ATTESTED. The agent cannot stack
    its own receipts into the positive set."""

    @given(
        claim=st.booleans(),
        # every read-back forgeable, any stance
        readbacks=st.lists(
            _readback(accountability=st.just(Accountability.AGENT_AUTHORED)),
            min_size=1,
            max_size=5,
        ),
        narrated=_narration,
    )
    @settings(max_examples=400, deadline=None)
    def test_all_forgeable_never_accepts(self, claim, readbacks, narrated):
        v = admit(claim, tuple(readbacks), narrated=narrated)
        assert v.verdict is not ACCEPT, (
            f"a forgeable-floor population was ACCEPTED — non-forgeability breached! "
            f"(stances={[r.stance.value for r in readbacks]})"
        )
        assert v.accept is False

    @given(
        readbacks=st.lists(
            _readback(
                accountability=st.just(Accountability.AGENT_AUTHORED),
                stance=st.just(EvidenceStance.ATTESTED),
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_all_forgeable_attested_with_claim_abstains(self, readbacks):
        """The pointed case: a present claim + only forgeable ATTESTED receipts ->
        ABSTAIN (never mint a positive unverified)."""
        v = admit(True, tuple(readbacks))
        assert v.verdict is ABSTAIN
        assert v.accept is False


class TestAcceptImpliesNonForgeableWitness:
    """The contrapositive of the floor rule, over random witness populations:
    accept ⟹ a non-forgeable ATTESTED witness existed (and a claim was present)."""

    @given(claim=st.booleans(), readbacks=_readbacks, narrated=_narration)
    @settings(max_examples=600, deadline=None)
    def test_accept_implies_nonforgeable_attested(self, claim, readbacks, narrated):
        v = admit(claim, tuple(readbacks), narrated=narrated)
        if v.verdict is ACCEPT:
            assert claim, "ACCEPT without a present claim — impossible by the rule"
            assert _has_nonforgeable_attested(readbacks), (
                "ACCEPT without a non-forgeable ATTESTED witness — floor breached!"
            )

    @given(claim=st.booleans(), readbacks=_readbacks, narrated=_narration)
    @settings(max_examples=400, deadline=None)
    def test_poison_implies_nonforgeable_refuted(self, claim, readbacks, narrated):
        v = admit(claim, tuple(readbacks), narrated=narrated)
        if v.verdict is REJECT_POISON:
            assert claim
            assert _has_nonforgeable_refuted(readbacks), (
                "REJECT_POISON without a non-forgeable REFUTED witness"
            )


class TestVerdictProjectionConsistency:
    """The loader-facing booleans are an exact function of the four-valued verdict —
    a DPO/SFT loader reading the flat record gets the same answer as the join."""

    @given(claim=st.booleans(), readbacks=_readbacks, narrated=_narration)
    @settings(max_examples=500, deadline=None)
    def test_booleans_match_verdict(self, claim, readbacks, narrated):
        v = admit(claim, tuple(readbacks), narrated=narrated)
        assert v.accept == (v.verdict is ACCEPT)
        assert v.poison == (v.verdict is REJECT_POISON)
        assert v.dispreferred == (v.verdict is REJECT_POISON)  # equal by contract
        # accept and poison are mutually exclusive.
        assert not (v.accept and v.poison)

    @given(readbacks=_readbacks, narrated=_narration)
    @settings(max_examples=200, deadline=None)
    def test_no_claim_is_exactly_absent_claim(self, readbacks, narrated):
        """claim_present=False ⟺ NO_CLAIM, regardless of read-backs."""
        v = admit(False, tuple(readbacks), narrated=narrated)
        assert v.verdict is NO_CLAIM
        assert v.claim_present is False
        assert not v.accept and not v.poison
