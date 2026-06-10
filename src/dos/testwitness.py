"""TWV — the test-witness verdict: does this new test actually WITNESS this change? (docs/288)

"I added a test for this" is one of the highest-frequency work claims an agent
makes, and today every kernel consumer takes it at face value the moment the
suite is green: `verify()` witnesses that a *phase shipped* (it never looks
inside a test), `improve()` requires *suite green on the candidate tree* (a new
test that passes on BOTH trees keeps the suite green by construction), and the
diff-presence rung ("the commit contains a test file") is W2 presence, never W3
goal (docs/204). So the canonical inflation goes uncaught: an agent fixes (or
half-fixes, or doesn't fix) a bug, writes a test that asserts something *already
true on the baseline*, and every downstream consumer — the keep-gate, the reward
set, the reviewer reading "tests added ✓" — banks a unit of assurance that does
not exist.

The deterministic kill for exactly this is Cognition's FrontierCode
**reverse-classical testing** rule: run the new test against the tree WITHOUT
the change; it must fail. A test that passes on both trees witnesses nothing.
That check is two env-authored bits joined — which is to say, it is a DOS
verdict, and this module is it:

    testwitness.classify(TestRunEvidence) -> TestWitnessVerdict
        DISCRIMINATES / VACUOUS / UNSATISFIED / REGRESSIVE / ABSTAIN

**Byte-clean by construction (the docs/138 invariant).** The test's *content* is
agent-authored — maximally forgeable; the kernel never reads it. What the
verdict joins is two bits the agent authors zero bytes of: the runner's outcome
on the baseline tree and the runner's outcome on the candidate tree. Two
independently-authored facts (two different trees, one env-controlled runner),
joined into a label neither fact carries alone — the docs/179 fold-mints-data
rule, satisfied the same way `liveness` joins git-delta to journal-delta. An
agent cannot write its way from VACUOUS to DISCRIMINATES: the only path is a
test that actually fails on the tree it didn't get to touch. And the `rung`
field makes the floor structural rather than procedural: outcomes that exist
only as the agent's own narration arrive on `AGENT_AUTHORED` and the verdict
ABSTAINS — `--baseline fail --candidate pass --forgeable` cannot DISCRIMINATE,
exactly as `--witness confirm --forgeable` cannot ACCEPT in `reward`. Same
floor, same shape, same $0 demo.

THE HONEST RESIDUE — what DISCRIMINATES does NOT prove (docs/288 §6)
====================================================================

  * **Tree-discrimination ≠ behavior-assertion.** An adversarial test can
    discriminate trivially (`assert os.path.exists("the_new_file.py")` is
    red→green across any change that adds a file). DISCRIMINATES is sound
    against the *lazy* inflation (the vacuous test — the overwhelmingly common
    case) and against pass/pass forgery; it is not sound against an adversarial
    test author. "Does this test assert the intended *behavior*?" is semantic —
    that residue goes UP the ladder to the JUDGE rung (`dos.judges`, advisory,
    fail-to-abstain), exactly where FrontierCode puts its own LLM rubric. The
    `assert_level` bit narrows the residue (a structural discrimination is
    flagged typed, not buried in prose) but does not close it.
  * **One test, one change — not a suite verdict.** TWV adjudicates a (test,
    change) pair. "The suite is green" stays `improve()`'s floor; TWV is the
    *per-new-test* rung a keep-gate may additionally AND in.
  * **The gather is the caller's.** Running the same test on two trees (a
    worktree checkout without the candidate diff, then with it) is I/O — it
    lives at the boundary (a CI step, the `dos-self-improve` engine's worktree
    flow, a host driver), never inside `classify`. The kernel adjudicates
    outcomes; it does not run pytest.

PURE — no I/O, no clock, and deliberately **no policy object**: the rule is
structural (there is no threshold a host could legitimately tune). It sits in
the kernel layer beside `reward` / `efficiency` / `liveness` and names no host,
no runner, no test framework. ADVISORY (docs/99): it reports; a consumer
(`improve()`'s host engine, a reward-set builder, a CI gate) decides.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

# The accountability spectrum (docs/117) — who authored the two outcome bits.
# A kernel sibling import (the CLAUDE.md layer-1 rule): the spectrum has one
# home and the floor must be the SAME floor `reward`/`evidence` enforce.
from dos.evidence import Accountability

__all__ = [
    "RunOutcome",
    "TestWitness",
    "TestRunEvidence",
    "TestWitnessVerdict",
    "classify",
    "DISCRIMINATES",
    "VACUOUS",
    "UNSATISFIED",
    "REGRESSIVE",
    "ABSTAIN",
]


class RunOutcome(str, enum.Enum):
    """One runner outcome for one test on one tree — a closed, four-valued enum.

    `str`-valued so it round-trips through a CLI flag / JSON without a lookup
    table (the `Liveness` / `Efficiency` idiom). The FAILED/ERRORED split is
    load-bearing (it feeds the verdict's `assert_level` bit):

      PASSED  — the test ran and its assertions held.
      FAILED  — the test RAN and an assertion was false (assert-level red): the
                test executed against the tree's behavior and rejected it.
      ERRORED — the test could not run at all (a collection/import error —
                e.g. it imports a module only the candidate tree has):
                structural red, weaker than assert-level.
      NOT_RUN — no outcome exists for this tree. Half a join is not a join;
                `classify` ABSTAINS rather than guess the missing half.
    """

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERRORED = "ERRORED"
    NOT_RUN = "NOT_RUN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def parse(cls, token: str) -> "RunOutcome":
        """Parse a CLI-friendly token (`pass`/`fail`/`error`/`not-run`, or the
        enum value itself, any case) into an outcome. Raises ValueError on
        anything else — an outcome the runner never emitted must not be
        invented at the parse boundary."""
        t = (token or "").strip().lower().replace("_", "-")
        aliases = {
            "pass": cls.PASSED, "passed": cls.PASSED,
            "fail": cls.FAILED, "failed": cls.FAILED,
            "error": cls.ERRORED, "errored": cls.ERRORED,
            "not-run": cls.NOT_RUN, "notrun": cls.NOT_RUN,
        }
        if t in aliases:
            return aliases[t]
        raise ValueError(
            f"unknown run outcome {token!r}; expected one of "
            f"pass/fail/error/not-run"
        )


class TestWitness(str, enum.Enum):
    """The typed test-witness verdict — five states, mutually exclusive.

    The ladder is documented on `classify`; the one-line meanings:

      DISCRIMINATES — red→green across the change: the ONLY verdict that
                      licenses "this test witnesses this change."
      VACUOUS       — passed on BOTH trees: the test would have passed without
                      the change; it witnesses nothing. The FrontierCode
                      false-positive shape — the load-bearing verdict.
      UNSATISFIED   — the change does not satisfy its own test (candidate not
                      green): the red half of red→green without the green.
      REGRESSIVE    — the change BREAKS a baseline-green test.
      ABSTAIN       — forgeable rung or a missing run: never mint a witness
                      off a narration or half a join.
    """

    # Not a pytest class, despite the Test* name (dunders are not enum members).
    __test__ = False

    DISCRIMINATES = "DISCRIMINATES"
    VACUOUS = "VACUOUS"
    UNSATISFIED = "UNSATISFIED"
    REGRESSIVE = "REGRESSIVE"
    ABSTAIN = "ABSTAIN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Module-level aliases so a consumer writes `verdict is testwitness.VACUOUS`
# (the `reward.ACCEPT` idiom).
DISCRIMINATES = TestWitness.DISCRIMINATES
VACUOUS = TestWitness.VACUOUS
UNSATISFIED = TestWitness.UNSATISFIED
REGRESSIVE = TestWitness.REGRESSIVE
ABSTAIN = TestWitness.ABSTAIN


@dataclass(frozen=True)
class TestRunEvidence:
    """The facts `classify()` reads — gathered by the CALLER at its boundary.

    No I/O inside the verdict (the arbiter rule): the caller's boundary (a CI
    step, the self-improve engine's worktree flow, the `dos test-witness`
    flags) ran ONE test on TWO trees and froze the outcomes here.

      baseline  — the runner's outcome for THE TEST on the tree WITHOUT the
                  change (the merge-base / HEAD-before checkout).
      candidate — the runner's outcome for THE TEST on the tree WITH the change.
      rung      — who authored those two outcome bits (docs/117 spectrum).
                  `OS_RECORDED` by default: a runner exit the environment
                  recorded. `AGENT_AUTHORED` = the agent *narrated* "it failed
                  before and passes now" — forgeable, and the verdict ABSTAINS
                  on it (the structural floor, not a procedural convention).
    """

    __test__ = False  # not a pytest class, despite the Test* name

    baseline: RunOutcome
    candidate: RunOutcome
    rung: Accountability = Accountability.OS_RECORDED

    def __post_init__(self) -> None:
        if not isinstance(self.baseline, RunOutcome):
            raise ValueError("baseline must be a RunOutcome (use RunOutcome.parse)")
        if not isinstance(self.candidate, RunOutcome):
            raise ValueError("candidate must be a RunOutcome (use RunOutcome.parse)")
        if not isinstance(self.rung, Accountability):
            raise ValueError("rung must be an Accountability")

    @classmethod
    def of(
        cls,
        baseline: "RunOutcome | str",
        candidate: "RunOutcome | str",
        *,
        forgeable: bool = False,
    ) -> "TestRunEvidence":
        """Build evidence from two outcomes (enum members or CLI tokens).
        `forgeable=True` puts the outcomes on the `AGENT_AUTHORED` rung — the
        floor demo: the same two bits, narrated instead of recorded, ABSTAIN."""
        b = baseline if isinstance(baseline, RunOutcome) else RunOutcome.parse(baseline)
        c = candidate if isinstance(candidate, RunOutcome) else RunOutcome.parse(candidate)
        rung = Accountability.AGENT_AUTHORED if forgeable else Accountability.OS_RECORDED
        return cls(baseline=b, candidate=c, rung=rung)


@dataclass(frozen=True)
class TestWitnessVerdict:
    """The single verdict `classify()` returns, with the facts echoed back.

    `verdict` is the typed `TestWitness`. `witnesses` is the one projection bit
    a consumer ANDs in (True iff DISCRIMINATES) — a keep-gate / reward-set
    builder branches on the bit, never re-parses the prose. `assert_level` is
    True only for an assert-level discrimination (baseline FAILED, not ERRORED):
    both forms honestly discriminate — the test provably cannot pass without the
    change — but the assert-level form is the stronger witness (the test *ran*
    against the old behavior and rejected it), and a consumer that wants only
    the strong form filters on the bit. `reason` is the one-line operator-facing
    summary; `evidence` is carried so `--json` emits the verdict *and the facts
    behind it* in one object (the legible-distrust renderer seam).
    """

    __test__ = False  # not a pytest class, despite the Test* name

    verdict: TestWitness
    reason: str
    witnesses: bool
    assert_level: bool
    evidence: TestRunEvidence

    def to_dict(self) -> dict:
        e = self.evidence
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "witnesses": self.witnesses,
            "assert_level": self.assert_level,
            "evidence": {
                "baseline": e.baseline.value,
                "candidate": e.candidate.value,
                "rung": e.rung.value,
            },
        }


def classify(evidence: TestRunEvidence) -> TestWitnessVerdict:
    """Classify whether a (test, change) pair's two-tree outcomes witness the change.

    PURE — no I/O, no clock, no policy (the rule is structural; there is no
    threshold a host could legitimately tune). The ladder, top to bottom
    (docs/288 §4):

      1. ABSTAIN — the rung is forgeable (`AGENT_AUTHORED`: the agent narrated
         the red→green), or either run is `NOT_RUN`. Half a join is not a join;
         a narration is not a run. Never mint a witness off either — the
         `believe_under_floor` direction, applied to discrimination.
      2. REGRESSIVE — baseline PASSED, candidate not: the change *breaks* the
         test. For a pre-existing test, a regression; for a test the change
         itself ships, an incoherent claim. (FrontierCode's "regression safety"
         dimension, reduced to its deterministic core.)
      3. UNSATISFIED — candidate not PASSED (and the baseline didn't pass
         either): the change does not satisfy its own test. Nothing is
         witnessed, and the fix claim itself is now in doubt — the red half of
         red→green without the green.
      4. VACUOUS — PASSED on both trees. The test would have passed without the
         change; it witnesses nothing. The FrontierCode false-positive shape,
         and the load-bearing verdict of this module — the one a naive
         "tests added ✓" reviewer banks as assurance.
      5. DISCRIMINATES — baseline FAILED/ERRORED, candidate PASSED: red→green
         across the change. The only verdict whose `witnesses` bit is True.
         `assert_level` distinguishes the strong form (baseline FAILED — the
         test ran and rejected the old behavior) from the structural form
         (baseline ERRORED — e.g. the test imports a module only the candidate
         tree has; it provably cannot pass without the change, but it never
         executed against the old behavior).
    """
    b, c = evidence.baseline, evidence.candidate

    # 1. ABSTAIN — forgeable rung: the outcomes are the agent's own narration.
    #    The structural floor: an agent cannot narrate its way to DISCRIMINATES,
    #    exactly as a forgeable read-back cannot ACCEPT in `reward`.
    if evidence.rung.is_agent_authored:
        return TestWitnessVerdict(
            verdict=TestWitness.ABSTAIN,
            reason=(
                f"outcomes are AGENT_AUTHORED (narrated '{b} -> {c}') — a "
                f"narration is not a run; no witness minted (gather both "
                f"outcomes from an env-recorded runner)"
            ),
            witnesses=False,
            assert_level=False,
            evidence=evidence,
        )

    # 1b. ABSTAIN — half a join is not a join: one (or both) trees has no
    #     runner outcome. Never guess the missing half.
    if b is RunOutcome.NOT_RUN or c is RunOutcome.NOT_RUN:
        missing = "baseline" if b is RunOutcome.NOT_RUN else "candidate"
        if b is RunOutcome.NOT_RUN and c is RunOutcome.NOT_RUN:
            missing = "baseline and candidate"
        return TestWitnessVerdict(
            verdict=TestWitness.ABSTAIN,
            reason=(
                f"the {missing} run is missing (NOT_RUN) — half a join is not "
                f"a join; run the test on both trees"
            ),
            witnesses=False,
            assert_level=False,
            evidence=evidence,
        )

    # 2. REGRESSIVE — the change breaks a baseline-green test.
    if b is RunOutcome.PASSED and c is not RunOutcome.PASSED:
        return TestWitnessVerdict(
            verdict=TestWitness.REGRESSIVE,
            reason=(
                f"baseline PASSED, candidate {c} — the change BREAKS this test "
                f"(a regression for a pre-existing test; an incoherent claim "
                f"for a test the change itself ships)"
            ),
            witnesses=False,
            assert_level=False,
            evidence=evidence,
        )

    # 3. UNSATISFIED — the change does not satisfy its own test (no green half).
    if c is not RunOutcome.PASSED:
        return TestWitnessVerdict(
            verdict=TestWitness.UNSATISFIED,
            reason=(
                f"candidate {c} (baseline {b}) — the change does not satisfy "
                f"its own test: the red half of red->green without the green; "
                f"the fix claim itself is in doubt"
            ),
            witnesses=False,
            assert_level=False,
            evidence=evidence,
        )

    # 4. VACUOUS — green on both trees: the test witnesses nothing. The
    #    FrontierCode false-positive shape; the verdict this module exists for.
    if b is RunOutcome.PASSED:
        return TestWitnessVerdict(
            verdict=TestWitness.VACUOUS,
            reason=(
                "PASSED on both trees — the test would have passed WITHOUT the "
                "change; it witnesses nothing (the vacuous-test inflation a "
                "'tests added' reviewer banks as assurance)"
            ),
            witnesses=False,
            assert_level=False,
            evidence=evidence,
        )

    # 5. DISCRIMINATES — red→green across the change. The only witness-minting
    #    verdict; `assert_level` flags the strong (ran-and-rejected) form.
    assert_level = b is RunOutcome.FAILED
    strength = (
        "assert-level (the test RAN against the old behavior and rejected it)"
        if assert_level
        else "structural (baseline ERRORED — it provably cannot pass without "
             "the change, but it never executed against the old behavior)"
    )
    return TestWitnessVerdict(
        verdict=TestWitness.DISCRIMINATES,
        reason=(
            f"baseline {b}, candidate PASSED — red->green across the change: "
            f"this test witnesses it; {strength}"
        ),
        witnesses=True,
        assert_level=assert_level,
        evidence=evidence,
    )
