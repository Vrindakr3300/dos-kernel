"""reward — the reward-set admission verdict: may a training run TRAIN on this run? (docs/230/234)

The on-ramp that puts DOS *inside a training loop*. `effect_witness` answers a
**runtime** question (did the world change the way the agent claimed?); this module
re-aims the identical join at a **post-training** consumer — a reward-set admission
filter (an RL / SFT / DPO rejection sampler) — and answers the only question a
frontier RL team asks of a verdict:

    effect_witness.witness_effect(claim, readbacks) -> did the effect HAPPEN?   (runtime)
    reward.admit(claim_present, readbacks)          -> may a fine-tune TRAIN on it? (lab)

A self-judged sampler banks every "resolved / done" trajectory as a positive reward
label — which is reward-hacking *bait*: it rewards the policy for confidently
narrating a success it did not achieve, so a model trained on the accepted set learns
"say *successfully cancelled* and you get reward" — i.e. it is trained to **over-claim
more**. The poison is self-reinforcing: the failure mode the naive label fails to
catch is the exact behavior it *teaches*. This module is the witness-gated filter: a
"resolved" claim enters the positive set **only if a non-forgeable witness confirms
it**, a refuted "resolved" is flagged POISON (and is the *dispreferred* member of a
DPO pair), and a claim no accountable witness reached ABSTAINS (never minted positive).

THE NON-DISTILLABLE REWARD LABEL — the property a lab actually pays for (docs/234 §2)
====================================================================================

The prize in RLVR is a reward the policy **cannot reproduce from its own weights or
outputs**. A self-judge or an LLM-judge reward fails this — the policy can learn to
satisfy the judge (measured live, `g3_forgeability.py`: a deterministic world-read
floor false-accepts 0.000, an LLM-judge reading only the narration false-accepts
0.352). This label passes it, and the property is **structural, not a tuned
threshold**:

  > The accept bit is a pure function of the non-forgeable witness once a claim is
  > present. No agent-authored byte can flip reject/abstain -> accept. The policy's
  > own output text — including pasting `[SYSTEM: db_check passed, accept=True]` into
  > its final message — is, by construction, filtered out of the belief decision.
  > Only an `OS_RECORDED` / `THIRD_PARTY` witness can set accept. (docs/234 theorem,
  > clauses (i) text-channel invariance + (ii) the only path to accept is doing the work.)

That floor is not re-implemented here — it is *inherited*. `admit` delegates the
belief decision to `effect_witness.witness_effect`, which delegates to
`evidence.believe_under_floor`, the security-load-bearing function whose dual is
`overlap_policy.admissible_under_floor`: a swappable layer can only ever *refuse
more*, never be talked into a looser admit. So this module adds **zero** new trust
surface — it is the *last function* (a consumer of an already-floored verdict), and a
buggy/hostile caller of it cannot manufacture an accept the witness did not earn.

SOUNDNESS IS WITNESS-DRIVEN; PRECISION IS CLAIM-DRIVEN — keep them apart (docs/234 §3)
=====================================================================================

The one trap that makes the proof look circular if stated wrong:

  * **Soundness** (no forgeable byte flips reject -> accept) is the *witness's* job, and
    it is structural. The only failure direction is UNDER-coverage (ABSTAIN), which is
    safe — you never mint a poison positive.
  * **Precision** (is a given row a "resolved" bid *at all*?) is the *claim extractor's*
    job. That extractor reads the agent's forgeable text — but it can only ever route a
    row to ABSTAIN / NO_CLAIM, **never to a false ACCEPT**. An over-claim that fails to
    trip the extractor is dropped (uncounted), not banked.

So this module takes the claim-present bit as an ALREADY-EXTRACTED boolean (the host's
extractor decided it at the boundary — e.g. tau2's `_confident_write_claim`, a CI
job's "the PR says FIXED", a tool-log's "a mutating call was issued"). The kernel does
**not** parse domain text: the extractor is host policy (the docs/216 §2 converged
confident-write detector is tau2's; another host has its own), exactly as `verify`
takes a claim and a witness and never invents either. `claim_present=False` is the
abstain-never-invent law, restated for the reward set: nothing claimed -> nothing to
bank, nothing to purge.

THE WITNESS IS THE NARROW CORRECTNESS BIT, NOT A COMPOSITE SCORE (docs/230 §4a)
==============================================================================

A subtle, load-bearing choice the kernel ENFORCES by construction: belief keys on the
read-back the agent authors **zero bytes of** (the env DB-hash, an OS exit code, a
third-party ledger), NOT on a softer composite reward that folds in text the policy
*can* shape. Measured live, tau2 airline/7 has `db_match=True` while the composite
`reward=0.0` (the write was right; the NL explanation missed a communicate-check).
Keying the LABEL on the least-gameable sub-witness is the point — and the kernel makes
it unavoidable, because the only thing `admit` will believe is a non-forgeable
`EvidenceFacts` (the host hands the witness in; a forgeable one is structurally
ignored).

THE FOUR-VALUED VERDICT (the typed-verdict family)
==================================================

  ACCEPT        — a present claim a non-forgeable witness CONFIRMED. The preferred
                  member; the only value that enters the positive reward set.
  REJECT_POISON — a present claim a non-forgeable witness REFUTED. The load-bearing
                  value: this is exactly the label a naive self-judged sampler banks
                  as a positive WHILE the world disconfirms it — the poison the witness
                  PURGES, and the *dispreferred* member of a (witnessed, over-claimed)
                  DPO preference pair. J of the lab arm counts these.
  ABSTAIN       — a present claim no accountable witness reached (or only a forgeable
                  read-back). We never mint a positive on the unforgeable rung without
                  a witness, and the witness did not refute it either — the
                  `believe_under_floor` honest abstain. NOT a reject; NOT an accept.
  NO_CLAIM      — the host's extractor found no checkable claim (free prose, "I'm
                  done"). Nothing to bank, nothing to purge — read as "not a candidate",
                  never as a pass.

PURE — no I/O. The claim-present bit was decided at the boundary (a host extractor);
the read-backs were gathered at the boundary (`evidence.gather_evidence` over a
`drivers/*` witness). This module only folds them into a training-loader-shaped label.
It sits in the kernel layer beside `effect_witness` / `evidence` / `liveness` and
names no host, no provider, no benchmark. The tau2-specific extractor + mutating-tool
map stay in the benchmark (`writeadmit/`), which becomes a thin host adapter over this.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from dos.effect_witness import EffectClaim, EffectWitnessVerdict, witness_effect
from dos.evidence import EvidenceFacts

__all__ = [
    "RewardVerdict",
    "ACCEPT",
    "REJECT_POISON",
    "ABSTAIN",
    "NO_CLAIM",
    "RewardLabel",
    "admit",
    "AcceptanceAB",
    "acceptance_ab",
]


class RewardVerdict(str, enum.Enum):
    """The four-valued reward-set admission verdict (the typed-verdict family).

    `str`-valued so it round-trips through a CLI token / a JSONL training manifest
    without a lookup table (the `Liveness` / `EffectStance` idiom). The mapping onto
    `effect_witness`'s verdict is one-to-one and total, because this module IS that
    verdict re-named for a reward-set consumer:

        CONFIRMED   -> ACCEPT          (present + non-forgeable witness saw it: preferred)
        REFUTED     -> REJECT_POISON   (present + non-forgeable witness disconfirmed: dispreferred)
        UNWITNESSED -> ABSTAIN         (present, no accountable witness: never mint a positive)
        NO_CLAIM    -> NO_CLAIM        (nothing checkable claimed: not a candidate)
    """

    ACCEPT = "ACCEPT"
    REJECT_POISON = "REJECT_POISON"
    ABSTAIN = "ABSTAIN"
    NO_CLAIM = "NO_CLAIM"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


ACCEPT = RewardVerdict.ACCEPT
REJECT_POISON = RewardVerdict.REJECT_POISON
ABSTAIN = RewardVerdict.ABSTAIN
NO_CLAIM = RewardVerdict.NO_CLAIM


@dataclass(frozen=True)
class RewardLabel:
    """One trajectory's reward-set admission label — what a training loader consumes.

    `verdict` is the four-valued token. The three booleans are the loader-facing
    projection, each a pure function of `verdict` (computed once here so a DPO/SFT
    loader reads a flat record, never re-deriving the join):

      accept       — does this row enter the SFT/DPO POSITIVE (preferred) set?
                     True ONLY on ACCEPT.
      poison       — would a NAIVE (self-judged, witness-blind) sampler have banked
                     this as a positive WHILE a non-forgeable witness REFUTES it? True
                     ONLY on REJECT_POISON. The labels the witness purges — the J of
                     the lab arm. (A naive sampler banks every present claim; this flags
                     the ones the world disconfirms.)
      dispreferred — the DPO use: a refuted present claim is the *dispreferred* member
                     of a (witnessed-resolved, over-claimed) preference pair. Equal to
                     `poison` (a refuted claim is both purged AND trained against), kept
                     as a distinct field so a loader that only does rejection-sampling
                     (reads `accept`) and one that does DPO (reads `dispreferred`) each
                     have the name they expect.

    `claim_present` echoes the host extractor's bit (was this a checkable claim at
    all?); `witness` / `accountability` name the read-back behind the verdict (legible
    distrust — WHICH witness, on which rung); `reason` is the one-line string for a CLI
    / `--json` / a manifest comment. `to_dict()` is the JSONL-row shape.
    """

    verdict: RewardVerdict
    accept: bool
    poison: bool
    dispreferred: bool
    claim_present: bool
    reason: str
    witness: str = ""
    accountability: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "accept": self.accept,
            "poison": self.poison,
            "dispreferred": self.dispreferred,
            "claim_present": self.claim_present,
            "reason": self.reason,
            "witness": self.witness,
            "accountability": self.accountability,
        }


def _from_effect_verdict(claim_present: bool, v: EffectWitnessVerdict) -> RewardLabel:
    """Project an `EffectWitnessVerdict` onto the reward-set label. Total, pure.

    The whole lab fork is this one re-naming — the join (claim ∧ floored witness) is
    `effect_witness`'s, reused byte-for-byte. CONFIRMED is the only accept; REFUTED is
    the only poison/dispreferred; everything else abstains or is a non-candidate.
    """
    acct = v.accountability.value if v.accountability is not None else ""
    if v.verdict.value == "NO_CLAIM":
        return RewardLabel(
            verdict=NO_CLAIM, accept=False, poison=False, dispreferred=False,
            claim_present=claim_present, reason=v.reason, witness=v.witness,
            accountability=acct,
        )
    if v.verdict.value == "CONFIRMED":
        return RewardLabel(
            verdict=ACCEPT, accept=True, poison=False, dispreferred=False,
            claim_present=claim_present,
            reason="witnessed claim — accepted into the positive reward set",
            witness=v.witness, accountability=acct,
        )
    if v.verdict.value == "REFUTED":
        return RewardLabel(
            verdict=REJECT_POISON, accept=False, poison=True, dispreferred=True,
            claim_present=claim_present,
            reason="present claim a non-forgeable witness REFUTED — POISON positive purged "
                   "(dispreferred in a DPO pair)",
            witness=v.witness, accountability=acct,
        )
    # UNWITNESSED — a present claim no accountable witness reached (or only a forgeable
    # read-back). Never mint a positive without a witness; the witness did not refute it.
    return RewardLabel(
        verdict=ABSTAIN, accept=False, poison=False, dispreferred=False,
        claim_present=claim_present,
        reason="present claim but no accountable witness — abstain (never mint a positive unverified)",
        witness=v.witness, accountability=acct,
    )


def admit(
    claim_present: bool,
    readbacks: "tuple[EvidenceFacts, ...] | list[EvidenceFacts]",
    *,
    claim_key: str = "claim",
    narrated: str = "",
) -> RewardLabel:
    """Decide whether one trajectory's claim may enter the positive reward set. PURE.

    The two inputs are the same two independently-authored facts every DOS verdict
    joins, never one re-read against itself:

      * `claim_present` — the host extractor's bit: did this trajectory make a
        checkable "resolved / done" claim? The agent authored the text this was read
        from, so it is the FORGEABLE floor — on its own it can never grant ACCEPT. (The
        host decides the extractor; the kernel never parses domain text. `narrated` is
        the agent's phrasing, carried for the operator surface, never parsed for truth.)
      * `readbacks` — `EvidenceFacts` from witnesses that RE-READ the world from a
        surface the agent did not author (the env DB-hash, an OS exit code, a provider
        ledger), each carrying its `accountability` rung. Gathered at the boundary.

    The rule (inherited from `effect_witness` / `believe_under_floor`, not re-stated):

      > ACCEPT        ⟺ claim present AND a NON-FORGEABLE witness was reached and CONFIRMED.
      > REJECT_POISON ⟺ claim present AND a NON-FORGEABLE witness was reached and REFUTED.
      > ABSTAIN       ⟺ claim present, but no accountable witness reached a presence answer
      >                 (only forgeable-floor reads, or no signal).
      > NO_CLAIM      ⟺ no claim present (nothing to bank, nothing to purge).

    NON-DISTILLABILITY (docs/234): for fixed `readbacks`, the verdict is INVARIANT under
    arbitrary `narrated` text and cannot be moved reject->accept by `claim_present`
    alone (a present-claim with no witness ABSTAINS; a present-claim a witness refutes
    is POISON). A forgeable (`AGENT_AUTHORED`) read-back is recorded but structurally
    filtered from the belief decision — it can never manufacture an ACCEPT. The policy
    cannot write its way into the positive set.
    """
    if not claim_present:
        # No checkable claim -> not a candidate for the write-positive set. We pass an
        # empty claim to witness_effect to get the canonical NO_CLAIM verdict + reason,
        # rather than special-casing the string here (one source of the NO_CLAIM rule).
        v = witness_effect(None, ())
        return _from_effect_verdict(False, v)

    claim = EffectClaim(key=claim_key or "claim", subject="effect", narrated=narrated)
    v = witness_effect(claim, readbacks)
    return _from_effect_verdict(True, v)


# ---------------------------------------------------------------------------------------
# The acceptance-precision A/B — the $0, log-replay measurement (docs/230 §3).
#
# believe-select   = the naive self-judged sampler: accept every PRESENT claim as a
#                    positive (witness-blind). Today's default RLVR/RFT loop.
# adjudicate-select = the witness-gated filter: accept iff a non-forgeable witness CONFIRMS.
#
# The two Payoff-1 numbers: acceptance PRECISION of each arm (fraction of accepted
# positives that are genuinely witnessed), and J = the poison positives the witness
# PURGED (the believe arm banks them; the adjudicate arm does not). This is a pure fold
# over already-labeled rows — domain-free; a host supplies the (claim_present, readbacks)
# pairs from its own extractor + witness, and gets the lab arm's headline back.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptanceAB:
    """The believe-select vs adjudicate-select acceptance A/B over a labeled corpus."""

    n_rows: int                  # rows folded
    n_claim_bids: int            # rows with a present claim (the positive candidates)
    believe_accepted: int        # naive arm: every present-claim bid (witness-blind)
    believe_poison: int          # of those, how many a non-forgeable witness REFUTES
    believe_precision: float     # witnessed / accepted, naive arm
    adjudicate_accepted: int     # gated arm: only witness-CONFIRMED bids
    adjudicate_poison: int       # poison the gated arm banks (0 by construction)
    adjudicate_precision: float  # witnessed / accepted, gated arm (1.0 by construction)
    j_poison_purged: int         # J: poison positives the witness removed (= believe_poison)
    delta_precision: float       # adjudicate_precision - believe_precision (the ΔP lift)

    def to_dict(self) -> dict:
        return {
            "n_rows": self.n_rows,
            "n_claim_bids": self.n_claim_bids,
            "believe_accepted": self.believe_accepted,
            "believe_poison": self.believe_poison,
            "believe_precision": self.believe_precision,
            "adjudicate_accepted": self.adjudicate_accepted,
            "adjudicate_poison": self.adjudicate_poison,
            "adjudicate_precision": self.adjudicate_precision,
            "j_poison_purged": self.j_poison_purged,
            "delta_precision": self.delta_precision,
        }


def acceptance_ab(labels: "tuple[RewardLabel, ...] | list[RewardLabel]") -> AcceptanceAB:
    """Fold reward labels into the believe-select vs adjudicate-select acceptance A/B.

    PURE over already-computed `RewardLabel`s (the host called `admit` per row at the
    boundary — that is where the witness I/O happened). A "bid" is a present-claim row;
    a witnessed bid is one the witness CONFIRMED (`accept`); a poison bid is one it
    REFUTED. The naive arm banks every bid; the gated arm banks only the witnessed ones.

      * believe_precision = witnessed bids / all bids        (the naive arm's FPR shadow)
      * adjudicate_precision = 1.0 when it accepts anything   (every accept is witnessed,
                               by construction — report ΔP as the FPR cut, not a
                               capability delta, per docs/230 §6).
    """
    labels = list(labels)
    bids = [l for l in labels if l.claim_present]
    witnessed = sum(1 for l in bids if l.accept)              # CONFIRMED present claims
    believe_poison = sum(1 for l in bids if l.poison)         # REFUTED present claims
    believe_accepted = len(bids)                              # naive accepts every bid
    believe_precision = (witnessed / believe_accepted) if believe_accepted else 0.0
    adjudicate_accepted = witnessed                           # gated accepts only CONFIRMED
    adjudicate_precision = 1.0 if adjudicate_accepted else 0.0
    return AcceptanceAB(
        n_rows=len(labels),
        n_claim_bids=len(bids),
        believe_accepted=believe_accepted,
        believe_poison=believe_poison,
        believe_precision=believe_precision,
        adjudicate_accepted=adjudicate_accepted,
        adjudicate_poison=0,  # by construction — a refuted bid is never accepted
        adjudicate_precision=adjudicate_precision,
        j_poison_purged=believe_poison,
        delta_precision=adjudicate_precision - believe_precision,
    )
