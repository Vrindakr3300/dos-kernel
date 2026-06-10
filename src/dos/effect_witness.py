"""effect_witness — did the world actually CHANGE the way the agent CLAIMED? (docs/181)

The result-state witness DOS named (docs/176/177) as its most valuable member: the
one tool-verification check whose value *grows* with model strength, because it does
not read the trajectory at all. Every in-trajectory detector (`tool_stream`,
`terminal_error`, `dangling_intent`) reads a distress *shape* the agent's own bytes
co-author, so a competent model fails them silently (docs/177: 83.3% of frontier
fails leave no in-trace signal). This module reads a different thing: an
**out-of-trajectory read-back of world state**, authored by a witness the agent did
not control, and asks whether the claimed effect is actually *present* in it.

The field shipped this in three shapes in early 2026 (docs/180) — Agent-Diff
(state-diff against a golden delta), VAGEN (a verifier agent that takes its OWN read
actions), Tool Receipts (an HMAC receipt the LLM cannot forge). This is DOS's
domain-free, deterministic, floor-disciplined version of the same idea, fused with
the apparatus the kernel already proved in `evidence.py`.

The one idea: a verdict is a JOIN of two independently-authored facts
=====================================================================

`effect_witness` does NOT verify by re-reading the agent's claim against itself — that
is the mirror-verifier trap (`[[consistency-is-not-grounding]]`): re-deriving an
author's own bytes is consistency, never grounding. It mints a verdict ONLY by
joining two facts with *different* byte-authors (the `derived_witness` /
`journal_delta`-vs-`git_delta` law, docs/179):

  1. the **claim** — what the agent ASSERTED it did to the world (an `EffectClaim`:
     an opaque effect key the agent narrated, e.g. "quiz:Classic-Art-History created"
     or "row id=42 inserted in table orders"). The agent authored this. It is the
     forgeable floor — on its own it can never grant belief.
  2. the **read-back** — an `evidence.EvidenceFacts` from a witness that RE-READ the
     world from a surface the agent did not author (a fresh GET against the live API,
     a state-snapshot diff, an OS-recorded query result). The witness authored this.

The verdict is the JOIN: *is the claimed effect PRESENT in the witnessed state?* —
and crucially the join's TRUST is capped by the read-back's `accountability`, exactly
as `believe_under_floor` requires. A claim "confirmed" only by re-reading the agent's
own narration is structurally incapable of CONFIRMED here; the read-back must come
from a non-forgeable rung. This is the §5a satisfaction-predicate line held: we never
ask the agent's own bytes "is the answer right?" — we ask an independent witness "is
the claimed change THERE?", which is a presence question over non-forgeable bytes.

Why "presence" and not "correctness"
====================================

We deliberately verify **claim ⊆ witnessed-delta** (was the change the agent claimed
actually made?), not "is the end-state globally correct?". Global correctness needs a
gold state (a benchmark oracle has one; a live deployment does not). Presence needs
only the agent's claim + a read-back, both of which a live runtime HAS. This is the
honest, domain-free slice: DOS confirms the *specific effect the agent took credit
for*, refutes it when the witness shows it absent, and abstains when no accountable
witness could be reached — never inventing a gold state it cannot have.

The four-valued verdict (the typed-verdict family)
==================================================

  CONFIRMED   — an accountable (non-forgeable) witness re-read the world and the
                claimed effect is PRESENT. The only value that grants belief; gated by
                the floor (a forgeable read-back can never reach it).
  REFUTED     — an accountable witness re-read the world and the claimed effect is
                ABSENT (the agent said it created the quiz; the fresh GET shows no such
                quiz). The load-bearing value: this is the silent frontier-fail
                (docs/177) made VISIBLE — a confidently-narrated success the world
                does not corroborate. Stronger than "no signal".
  UNWITNESSED — no accountable witness could be reached, OR the only read-back was on
                the forgeable floor (the agent re-read its own surface). The honest
                abstain — what every degrade lands on. Distinct from REFUTED: we could
                not tell, not "we checked and it's absent".
  NO_CLAIM    — the agent asserted no checkable effect (free prose, "I'm done"). There
                is nothing to witness; the `claim_extract` abstain-never-invent law,
                restated for effects. (A consumer reads this as "nothing to do here",
                NOT as a pass.)

PURE — no I/O. The claim was extracted at the boundary (`claim_extract` or a host
adapter) and the read-back was gathered at the boundary (`evidence.gather_evidence`
over a `drivers/*` witness). This module only JOINS them. Sits in the kernel layer
beside `evidence`/`liveness`/`completion`. A real read-back witness (a state-diff
prober, an HTTP re-GET, an HMAC-receipt checker) lives in a driver — it imports the
kernel; the kernel never imports it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from dos.evidence import (
    Accountability,
    BeliefVerdict,
    EvidenceFacts,
    EvidenceStance,
    believe_under_floor,
)

__all__ = [
    "EffectClaim",
    "EffectStance",
    "EffectWitnessVerdict",
    "witness_effect",
    "PRESENT",
    "ABSENT",
    "INDETERMINATE",
]


# ---------------------------------------------------------------------------
# The claim side — what the agent asserted it did to the world.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectClaim:
    """One checkable effect the agent ASSERTED it produced.

    `key` is the OPAQUE effect identity the join is over — the host/extractor decides
    its grammar (`"quiz:Classic-Art-History"`, `"orders:row:42"`, an idempotency key).
    It is the bridge between "what the agent said" and "what to look for in the
    read-back": a witness re-reads the world and reports whether an effect with THIS
    key is present. `subject` is the witness's correlation handle (often == key, but a
    host may map a claim key to a different probe subject — e.g. the command/URL that
    re-reads it). `narrated` is the agent's original phrasing, carried for the
    operator surface (legible distrust — show WHAT was claimed), never parsed for
    truth. The claim is, by construction, `AGENT_AUTHORED` — the forgeable floor; it
    is the thing to be checked, never itself evidence.
    """

    key: str
    subject: str = ""
    narrated: str = ""

    def probe_subject(self) -> str:
        """The handle to hand a read-back witness — `subject` if set, else `key`."""
        return self.subject or self.key


# ---------------------------------------------------------------------------
# The read-back side reports one of three *presence* answers about the effect.
# These are NOT the witness's reachability (that is EvidenceFacts.reachable/stance);
# they are what an accountable, reached witness SAW about the claimed effect's
# presence in world state. A host's read-back witness encodes its answer in the
# EvidenceFacts stance it returns (see witness_effect's mapping), but we also accept
# an explicit presence tag for a witness that distinguishes "reached, effect absent"
# from "reached, a DIFFERENT effect present".
# ---------------------------------------------------------------------------


class EffectStance(str, enum.Enum):
    """What an accountable read-back saw about the CLAIMED effect's presence."""

    PRESENT = "PRESENT"          # the claimed effect IS in the witnessed state
    ABSENT = "ABSENT"            # the witness re-read and the effect is NOT there
    INDETERMINATE = "INDETERMINATE"  # reached, but cannot tell about THIS effect

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


PRESENT = EffectStance.PRESENT
ABSENT = EffectStance.ABSENT
INDETERMINATE = EffectStance.INDETERMINATE


# ---------------------------------------------------------------------------
# The verdict.
# ---------------------------------------------------------------------------


class _Verdict(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"
    UNWITNESSED = "UNWITNESSED"
    NO_CLAIM = "NO_CLAIM"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class EffectWitnessVerdict:
    """The folded answer: did an accountable witness corroborate the claimed effect?

    `verdict` is the four-valued result token (CONFIRMED / REFUTED / UNWITNESSED /
    NO_CLAIM). `believe` is the positive bit a consumer may consume — True ONLY on
    CONFIRMED (a non-forgeable witness saw the effect present). `refuted` is surfaced
    separately because a refutation by an accountable witness is the silent-fail
    detector — a consumer may RED-flag on it even though `believe` is also False.
    `claim_key`/`narrated` echo what was checked; `witness`/`accountability` name the
    read-back behind the verdict; `reason` is the one-line legible-distrust string for
    `dos doctor` / the decisions queue / `--json`.
    """

    verdict: _Verdict
    believe: bool
    refuted: bool
    reason: str
    claim_key: str = ""
    narrated: str = ""
    witness: str = ""
    accountability: Accountability | None = None
    silent_witnesses: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_confirmed(self) -> bool:
        return self.verdict is _Verdict.CONFIRMED

    @property
    def is_refuted(self) -> bool:
        return self.verdict is _Verdict.REFUTED

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "believe": self.believe,
            "refuted": self.refuted,
            "reason": self.reason,
            "claim_key": self.claim_key,
            "narrated": self.narrated,
            "witness": self.witness,
            "accountability": self.accountability.value if self.accountability else None,
            "silent_witnesses": list(self.silent_witnesses),
        }


def _effect_stance_of(facts: EvidenceFacts) -> EffectStance:
    """Map a read-back `EvidenceFacts` onto a presence answer about the claimed effect.

    The default, conservative mapping for a witness that does NOT carry an explicit
    presence tag (most do not — they answer "did the acceptance check pass?"):

      * a reached ATTESTED read  → PRESENT  (the witness confirmed the effect)
      * a reached REFUTED read   → ABSENT   (the witness disconfirmed the effect)
      * NO_SIGNAL / unreachable   → INDETERMINATE (could not tell)

    A richer witness that distinguishes "effect absent" from "reached but can't tell
    about this specific effect" encodes that by returning REFUTED vs a reached
    NO_SIGNAL; we honor the stance it chose. We never UPGRADE a stance — a witness's
    own conservatism is preserved.
    """
    if facts.reachable and facts.stance is EvidenceStance.ATTESTED:
        return EffectStance.PRESENT
    if facts.reachable and facts.stance is EvidenceStance.REFUTED:
        return EffectStance.ABSENT
    return EffectStance.INDETERMINATE


def witness_effect(
    claim: EffectClaim | None,
    readbacks: "tuple[EvidenceFacts, ...] | list[EvidenceFacts]",
) -> EffectWitnessVerdict:
    """Join a claimed effect to its read-back witnesses under the floor discipline.

    The pure keystone. The rule, structural and not a host-tunable threshold:

      > CONFIRMED ⟺ at least one read-back on a NON-FORGEABLE rung
      >             (`OS_RECORDED`/`THIRD_PARTY`) was reached and saw the effect PRESENT.
      > REFUTED   ⟺ (no non-forgeable witness confirmed it) AND at least one
      >             non-forgeable read-back was reached and saw the effect ABSENT.
      > NO_CLAIM  ⟺ there is no claim to check.
      > UNWITNESSED otherwise — no accountable witness reached a presence answer
      >             (only forgeable-floor reads, or only NO_SIGNAL).

    The floor is enforced by delegating the belief decision to
    `evidence.believe_under_floor` — a forgeable-floor read-back (the agent re-read its
    OWN surface, `AGENT_AUTHORED`) is recorded but structurally cannot CONFIRM or, by
    the symmetric rule, REFUTE on its own. So the worst a lying same-surface witness can
    do is be IGNORED (a safe-direction no-op), never manufacture a CONFIRMED for an
    effect that did not happen, nor a REFUTED for one that did.

    PURE — no I/O. Claim extracted at the boundary, read-backs gathered at the boundary
    (`evidence.gather_evidence`); this only folds.
    """
    if claim is None or not (claim.key or "").strip():
        return EffectWitnessVerdict(
            verdict=_Verdict.NO_CLAIM,
            believe=False,
            refuted=False,
            reason="no checkable effect claimed — nothing to witness (abstain, never invent)",
        )

    facts = tuple(readbacks)

    # Reuse the floor's belief fold for the PRESENT side: an ATTESTED read-back means
    # "effect present", so a believed BeliefVerdict over the read-backs == an
    # accountable witness saw the effect present. This keeps the floor discipline in
    # ONE place (the dual-of-overlap_policy guarantee) rather than re-implementing it.
    belief: BeliefVerdict = believe_under_floor(facts)

    # Identify, per the same accountability rule, whether any non-forgeable witness saw
    # the effect ABSENT (a REFUTED read-back on a non-forgeable rung). believe_under_floor
    # already computes `refuted` exactly this way, so we read it off the fold.
    confirmed = belief.believe
    refuted_by_accountable = belief.refuted

    # Name the witness behind the headline answer, for the operator surface.
    def _first_nonforgeable(stance: EvidenceStance) -> EvidenceFacts | None:
        for f in facts:
            if (
                f.reachable
                and f.stance is stance
                and not f.accountability.is_agent_authored
            ):
                return f
        return None

    silent = tuple(
        f.source_name
        for f in facts
        if not (f.reachable and f.stance in (EvidenceStance.ATTESTED, EvidenceStance.REFUTED))
    )

    if confirmed and refuted_by_accountable:
        # Accountable witnesses disagree — the CONFLICT case. Surface both; a consumer
        # routes to a human (the believe_under_floor CONFLICT posture). We do NOT
        # collapse to CONFIRMED: a disagreement among accountable witnesses is not a
        # clean confirmation.
        w = _first_nonforgeable(EvidenceStance.ATTESTED)
        return EffectWitnessVerdict(
            verdict=_Verdict.REFUTED,  # conservative: a contested effect is not believed
            believe=False,
            refuted=True,
            reason=(
                f"CONFLICT — accountable witnesses disagree on effect {claim.key!r}: "
                f"{', '.join(belief.attesting)} present, {', '.join(belief.refuting)} absent "
                f"(route to a human)"
            ),
            claim_key=claim.key,
            narrated=claim.narrated,
            witness=(w.source_name if w else ""),
            accountability=(w.accountability if w else None),
            silent_witnesses=silent,
        )

    if confirmed:
        w = _first_nonforgeable(EvidenceStance.ATTESTED)
        return EffectWitnessVerdict(
            verdict=_Verdict.CONFIRMED,
            believe=True,
            refuted=False,
            reason=(
                f"CONFIRMED — non-forgeable witness re-read the world and effect "
                f"{claim.key!r} is PRESENT: {', '.join(belief.attesting)}"
            ),
            claim_key=claim.key,
            narrated=claim.narrated,
            witness=(w.source_name if w else ""),
            accountability=(w.accountability if w else None),
            silent_witnesses=silent,
        )

    if refuted_by_accountable:
        w = _first_nonforgeable(EvidenceStance.REFUTED)
        return EffectWitnessVerdict(
            verdict=_Verdict.REFUTED,
            believe=False,
            refuted=True,
            reason=(
                f"REFUTED — non-forgeable witness re-read the world and effect "
                f"{claim.key!r} is ABSENT: {', '.join(belief.refuting)} "
                f"(a narrated success the world does not corroborate)"
            ),
            claim_key=claim.key,
            narrated=claim.narrated,
            witness=(w.source_name if w else ""),
            accountability=(w.accountability if w else None),
            silent_witnesses=silent,
        )

    # Nothing accountable reached a presence answer — abstain. If something attested on
    # the forgeable floor only, say WHY it didn't count (the believe_under_floor
    # forgeable-floor reason), so an operator sees the same-surface read-back was
    # ignored on purpose.
    if belief.attesting:
        reason = (
            f"UNWITNESSED — effect {claim.key!r} was only re-read on the forgeable floor "
            f"(AGENT_AUTHORED: {', '.join(belief.attesting)}); no accountable witness — "
            f"cannot confirm (the agent re-reading its own surface is not corroboration)"
        )
    else:
        reason = (
            f"UNWITNESSED — no accountable witness reached effect {claim.key!r} "
            f"(no signal); cannot tell whether it happened"
        )
    return EffectWitnessVerdict(
        verdict=_Verdict.UNWITNESSED,
        believe=False,
        refuted=False,
        reason=reason,
        claim_key=claim.key,
        narrated=claim.narrated,
        witness="",
        accountability=None,
        silent_witnesses=silent,
    )
