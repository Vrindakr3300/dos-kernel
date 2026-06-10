"""dos.drivers.operator_judge — the operator-decision adjudicator (a JUDGE occupant).

A host's *operator-decision queue* (the reference userland app's "judge-operator"
JO machine) is a JUDGE-rung adjudicator: for each open operator decision it rules
**accept-recommended** (the recommended option is clearly correct and reversible),
**escalate** (genuinely ambiguous / value-laden / irreversible — a human must
decide), or **defer** (evidence is stale; re-propose later). That is exactly the
three-valued ruling `dos.judges` is the seam for — so the JO machine should be a
registered occupant of the JUDGE rung, scored by the same `dos.judge_eval`
instrument as any other judge, rather than a wholly-separate parallel machine.

This driver is the **thin binding**, not a rewrite. The host keeps ALL of its
machinery — the LLM adjudication that PRODUCES the accept/escalate/defer string,
the decisions-pending stamps, the findings-queue rows, the reversibility
(`JO_AUTO_ACCEPT`) gate, the cap/cooldown/veto failsafes. This module adds two
things, both pure and additive:

  * `OperatorDecisionJudge` — a `dos.judges.Judge` occupant whose `rule()` reads a
    host decision-string off the `Claim` and returns the canonical `JudgeVerdict`.
    Registered under the `dos.judges` entry-point group so `dos doctor` lists it
    and `resolve_judge("operator-decision")` returns it.
  * `stance_for_decision` / `verdict_for_decision` — the pure mapping the host
    adapter calls to translate its own accept/escalate/defer into the canonical
    `Stance` / `JudgeVerdict`, so it can then feed `(Claim, verdict, truth)` triples
    to `dos.judge_eval.false_clear_rate` and re-ground its ≤5%-false-accept gate on
    the kernel instrument instead of a hand-rolled number.

THE MAPPING (the only non-trivial part — it encodes WHICH host string clears a claim):

  accept-recommended → AGREE     — the judge believes the recommended option is
                                   correct AND reversible; this is the one verdict
                                   that can let the lane proceed automatically. It
                                   is the false-clear surface `judge_eval` measures.
  escalate           → DISAGREE  — the judge flags the decision as one it should
                                   NOT auto-clear; a human must rule (the safe,
                                   non-clearing direction).
  defer              → ABSTAIN   — the judge cannot rule yet (stale/unverifiable);
                                   punt to the next cycle / a human.

Why this is the honest split: the kernel never holds the host's stamp formats,
findings schema, or reversibility gate — only the three-valued mapping and the
discipline (`run_judge` still fail-to-abstains; the occupant mutates nothing). A
grep of this driver for a host directory / lane / commit prefix returns nothing —
it names only the three domain-neutral decision strings, which are this judge's
*vocabulary*, the way a build/test judge would name "pass"/"fail".
"""
from __future__ import annotations

from dos.judges import Claim, JudgeVerdict, Stance

# The judge's name — the token `resolve_judge(...)` selects and `dos doctor` lists.
JUDGE_NAME = "operator-decision"

# The three host decision strings this judge rules in, mapped to the canonical
# three-valued Stance. `accept-recommended` is the ONLY one that clears (AGREE) —
# the false-clear surface the eval harness measures.
_DECISION_TO_STANCE: dict[str, Stance] = {
    "accept-recommended": Stance.AGREE,
    "escalate": Stance.DISAGREE,
    "defer": Stance.ABSTAIN,
}


def stance_for_decision(decision: str) -> Stance:
    """Map a host accept/escalate/defer string to the canonical Stance.

    An unknown / unparseable decision maps to ABSTAIN — the conservative default
    (an adjudicator that produced something the seam doesn't recognise has not
    cleared the claim). PURE.
    """
    return _DECISION_TO_STANCE.get((decision or "").strip().lower(), Stance.ABSTAIN)


def verdict_for_decision(
    decision: str, *, reason: str = "", evidence: tuple[str, ...] = (),
    cost: float = 0.0,
) -> JudgeVerdict:
    """Build the canonical `JudgeVerdict` for a host decision string. PURE.

    The host adapter calls this to translate its own already-produced
    accept/escalate/defer ruling into the kernel verdict type, so the ruling can be
    scored by `dos.judge_eval` alongside any other judge's.
    """
    stance = stance_for_decision(decision)
    if stance is Stance.AGREE:
        return JudgeVerdict.agree(reason, evidence=evidence, cost=cost)
    if stance is Stance.DISAGREE:
        return JudgeVerdict.disagree(reason, evidence=evidence, cost=cost)
    return JudgeVerdict.abstain(reason, evidence=evidence, cost=cost)


class OperatorDecisionJudge:
    """A `dos.judges.Judge` occupant for the operator-decision queue.

    `rule()` reads the host's already-produced decision off the `Claim` — the
    accept/escalate/defer string is carried in `claim_text` (with the human reason
    in `stated_reason`) — and returns the canonical `JudgeVerdict`. It does NO I/O
    and NO model call itself: the host's LLM adjudication runs upstream and writes
    its decision into the `Claim`; this occupant is the registered, eval-scorable
    seam that ruling plugs into. Mutates nothing (advisory-only by shape).

    A `Claim` whose `claim_text` is not one of the three known decision strings
    maps to ABSTAIN (and `run_judge` would also catch any raise), so this judge can
    never auto-clear a claim it does not understand.
    """

    name = JUDGE_NAME

    def rule(self, claim: Claim, config: object) -> JudgeVerdict:
        return verdict_for_decision(
            claim.claim_text,
            reason=claim.stated_reason,
            evidence=claim.evidence,
        )
