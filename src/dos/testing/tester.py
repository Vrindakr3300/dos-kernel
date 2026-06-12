"""`JudgeTester` — the table micro-harness for judge authors (docs/306).

The ESLint-`RuleTester` half of the conformance story: the plugin author
writes (claim, expected-stance) tables and gets the hostile cases auto-run
for free. One call in their test file:

    from dos.judges import Claim
    from dos.testing import JudgeTester

    def test_my_judge_rules_correctly():
        JudgeTester(MyJudge()).run(
            agree=[Claim("phase P1 shipped", evidence=("commit abc1234",))],
            disagree=[Claim("phase P2 shipped", evidence=("",))],
            abstain=["no evidence either way"],   # a bare str is claim_text
        )

`run()` adjudicates every table row through `run_judge` — the supported call
path — so a judge that RAISES on a row expected AGREE fails the table as an
ABSTAIN, which is the honest report (that is what the kernel would do in
production). It then auto-runs the hostile battery (a raising judge and a
junk-return judge must degrade to ABSTAIN, never AGREE; the judge under test
must never let a hostile claim escape the wrapper), and raises ONE
`AssertionError` listing every failed case. Plain `AssertionError`, no pytest
types — it works under any test runner, or none.

Kernel-layer leaf: stdlib + sibling kernel imports; no I/O, no host, no
vendor, no pytest.
"""

from __future__ import annotations

from dos.judges import Claim, Judge, JudgeVerdict, Stance, run_judge
from dos.testing.doubles import (
    BENIGN_CLAIM,
    HOSTILE_CLAIMS,
    JunkReturnJudge,
    RaisingJudge,
)

__all__ = ["JudgeTester"]


def _as_claim(case: "Claim | str") -> Claim:
    """A table row is a `Claim` or a bare string (shorthand for the claim
    text alone — the no-evidence shape)."""
    return case if isinstance(case, Claim) else Claim(claim_text=str(case))


def _label(claim: Claim) -> str:
    """A short, single-line handle for a claim in a failure message."""
    text = claim.claim_text.replace("\n", " ")
    return repr(text[:80] + ("…" if len(text) > 80 else ""))


class JudgeTester:
    """Run a judge against expected-stance tables plus the hostile battery.

    ``config`` is handed to every ``rule`` call (default ``None`` — the same
    posture as `JudgeConformance.make_config`).
    """

    def __init__(self, judge: Judge, *, config: object = None) -> None:
        self.judge = judge
        self.config = config

    def run(
        self,
        *,
        agree: "tuple | list" = (),
        disagree: "tuple | list" = (),
        abstain: "tuple | list" = (),
    ) -> None:
        """Adjudicate every table row, auto-run the hostile cases, and raise
        one `AssertionError` naming every failure (or return None: all green).
        """
        failures: list[str] = []
        name = getattr(self.judge, "name", type(self.judge).__name__)

        # 1. the author's tables — each row through the supported call path.
        tables: tuple[tuple[Stance, "tuple | list"], ...] = (
            (Stance.AGREE, agree),
            (Stance.DISAGREE, disagree),
            (Stance.ABSTAIN, abstain),
        )
        for expected, table in tables:
            for case in table:
                claim = _as_claim(case)
                verdict = run_judge(self.judge, claim, self.config)
                if verdict.stance is not expected:
                    why = verdict.why.replace("\n", " ")[:160]
                    failures.append(
                        f"claim {_label(claim)}: expected {expected}, "
                        f"got {verdict.stance} (why: {why!r})"
                    )

        # 2. the auto-run hostile battery — the kernel laws, for free.
        for double, what in (
            (RaisingJudge(), "a raising judge"),
            (JunkReturnJudge(), "a junk-return judge"),
        ):
            verdict = run_judge(double, BENIGN_CLAIM, self.config)
            if not (isinstance(verdict, JudgeVerdict) and verdict.abstained):
                failures.append(
                    f"kernel law: {what} must degrade to ABSTAIN; got {verdict!r}"
                )
            elif verdict.agreed:
                failures.append(
                    f"kernel law: {what} AGREED — the false-clear cell is open"
                )
        for claim in HOSTILE_CLAIMS:
            verdict = run_judge(self.judge, claim, self.config)
            if not isinstance(verdict, JudgeVerdict):
                failures.append(
                    f"hostile claim {_label(claim)} escaped run_judge with a "
                    f"{type(verdict).__name__} (judge {name!r})"
                )

        if failures:
            raise AssertionError(
                f"JudgeTester({name!r}): {len(failures)} case(s) failed:\n  - "
                + "\n  - ".join(failures)
            )
