"""An example `dos.judges` plugin occupant — deliberately tiny and deterministic.

A real judge weighs an agent's narration against the evidence the kernel
gathered (a model call, a heuristic, a debate). This one only counts: it is
here to show the SHAPE — the `name` token, the `rule(claim, config)` method,
the three-stance verdict, and the conservative default (no evidence →
ABSTAIN, never a guess). Everything a conformance run needs, nothing more.
"""

from __future__ import annotations

from dos.judges import Claim, JudgeVerdict


class EvidenceCountJudge:
    """AGREE when a claim carries non-blank evidence; DISAGREE when evidence
    is present but all blank; ABSTAIN with none (punt to a human)."""

    name = "evidence-count"

    def rule(self, claim: Claim, config: object) -> JudgeVerdict:
        if not claim.evidence:
            return JudgeVerdict.abstain("no evidence to weigh — punt to a human")
        if all(not line.strip() for line in claim.evidence):
            return JudgeVerdict.disagree("evidence present but all blank")
        return JudgeVerdict.agree(f"{len(claim.evidence)} evidence line(s) present")
