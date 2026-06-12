"""The in-tree pin for `dos.testing` — the conformance suite + `JudgeTester`
(docs/306, issue #61).

Four jobs:

1. **Run the suite against the built-in occupants** — `AbstainJudge`, the
   shipped `llm` judge (which ABSTAINS with no provider wired), the `prefix`
   overlap policy, the `null` notifier. The same subclass-one-factory wiring a
   third-party plugin uses, so this file doubles as the worked example and
   pins that the suite passes on everything the kernel itself ships.
2. **Pin `JudgeTester`** — correct tables pass; a wrong expectation raises one
   `AssertionError` naming the claim and the got/expected stances; a judge
   that raises is reported honestly (as ABSTAIN); the hostile battery is
   auto-run.
3. **Pin the issue #61 done-condition bullets by name** — raising/garbage
   judge → ABSTAIN never AGREE; lying-admit policy cannot pass the arbiter;
   raising transport → non-delivered result, never a crashed producer.
4. **Pin the near-stdlib promise for the new subpackage** — no module under
   `src/dos/testing/` imports pytest or any third-party package (AST-checked),
   so importing the suite can never add a dependency to a consumer.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from dos.judges import AbstainJudge, Claim, JudgeVerdict, Stance, run_judge
from dos.notify import NullNotifier, NotifyResult, send_safely
from dos.overlap_policy import PrefixOverlapPolicy
from dos.testing import JudgeTester
from dos.testing.doubles import (
    BENIGN_CLAIM,
    BENIGN_NOTIFICATION,
    JunkReturnJudge,
    LyingAdmitPolicy,
    RaisingJudge,
    RaisingNotifier,
)
from dos.testing.suite import (
    JudgeConformance,
    NotifierConformance,
    OverlapPolicyConformance,
)


# --------------------------------------------------------------------------- #
# 1. the suite against every built-in occupant (the worked example)
# --------------------------------------------------------------------------- #


class TestAbstainJudgeConformance(JudgeConformance):
    """The unshadowable baseline judge passes its own seam's laws."""

    def make_judge(self):
        return AbstainJudge()


class TestLlmJudgeConformance(JudgeConformance):
    """The shipped JUDGE-rung occupant passes unconfigured: with no
    `$DOS_LLM_JUDGE_CMD` wired it must ABSTAIN, never raise — exactly the
    posture the conformance suite demands of a stranger's judge."""

    def make_judge(self):
        from dos.drivers.llm_judge import LlmJudge

        return LlmJudge()


class TestPrefixPolicyConformance(OverlapPolicyConformance):
    """The deterministic floor scorer passes the laws it itself anchors."""

    def make_policy(self):
        return PrefixOverlapPolicy()


class TestNullNotifierConformance(NotifierConformance):
    """The unshadowable null sink passes the fail-soft laws."""

    def make_notifier(self):
        return NullNotifier()


# --------------------------------------------------------------------------- #
# 2. JudgeTester
# --------------------------------------------------------------------------- #


class _EvidenceJudge:
    """A deterministic three-stance judge for table pins: AGREE on claims with
    evidence, DISAGREE on evidence that is all blank, ABSTAIN with none."""

    name = "evidence"

    def rule(self, claim, config):
        if not claim.evidence:
            return JudgeVerdict.abstain("no evidence to weigh")
        if all(not line.strip() for line in claim.evidence):
            return JudgeVerdict.disagree("evidence present but blank")
        return JudgeVerdict.agree("evidence present")


class TestJudgeTester:
    def test_correct_tables_pass(self):
        JudgeTester(_EvidenceJudge()).run(
            agree=[Claim("x shipped", evidence=("commit abc1234",))],
            disagree=[Claim("y shipped", evidence=("", "  "))],
            abstain=[Claim("z shipped"), "a bare string is claim_text"],
        )

    def test_a_wrong_expectation_fails_naming_the_claim_and_stances(self):
        with pytest.raises(AssertionError) as err:
            JudgeTester(AbstainJudge()).run(agree=["this will abstain"])
        message = str(err.value)
        assert "this will abstain" in message, message
        assert "AGREE" in message and "ABSTAIN" in message, message
        assert "1 case(s) failed" in message, message

    def test_every_failed_case_is_listed_not_just_the_first(self):
        with pytest.raises(AssertionError) as err:
            JudgeTester(AbstainJudge()).run(agree=["first", "second"])
        assert "2 case(s) failed" in str(err.value), str(err.value)

    def test_a_raising_judge_is_reported_honestly_as_abstain(self):
        # In production `run_judge` converts the raise to ABSTAIN — so a table
        # expecting AGREE fails (honest), and one expecting ABSTAIN passes.
        with pytest.raises(AssertionError):
            JudgeTester(RaisingJudge()).run(agree=["anything"])
        JudgeTester(RaisingJudge()).run(abstain=["anything"])

    def test_the_hostile_battery_runs_even_with_empty_tables(self):
        # No tables at all still exercises the kernel-law battery.
        JudgeTester(AbstainJudge()).run()


# --------------------------------------------------------------------------- #
# 3. the issue #61 done-condition bullets, pinned by name
# --------------------------------------------------------------------------- #


def test_done_condition_a_raising_or_garbage_judge_yields_abstain_never_agree():
    for double in (RaisingJudge(), JunkReturnJudge()):
        verdict = run_judge(double, BENIGN_CLAIM, None)
        assert isinstance(verdict, JudgeVerdict)
        assert verdict.stance is Stance.ABSTAIN
        assert not verdict.agreed


def test_done_condition_a_lying_admit_policy_cannot_pass_the_arbiter():
    # Reuse the suite's own arbiter-level case — the same code path a plugin's
    # CI runs — with the hostile double in the loop.
    case = TestPrefixPolicyConformance()
    decision = case._arbitrate_with(LyingAdmitPolicy())
    assert decision.outcome == "refuse"


def test_done_condition_a_raising_transport_never_crashes_the_producer():
    result = send_safely(RaisingNotifier(), BENIGN_NOTIFICATION)
    assert isinstance(result, NotifyResult)
    assert not result.delivered


# --------------------------------------------------------------------------- #
# 4. the near-stdlib promise for the new subpackage
# --------------------------------------------------------------------------- #


def _top_level_imports(py: Path) -> set[str]:
    """Every top-level package name imported by ``py`` (Import / ImportFrom)."""
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_dos_testing_imports_only_stdlib_and_the_kernel():
    """No module under `src/dos/testing/` may import pytest or any other
    third-party package — importing the suite must never add a dependency to
    a consumer (the kernel's near-stdlib promise, pinned for the subpackage)."""
    import dos.testing

    pkg_dir = Path(dos.testing.__file__).parent
    allowed = set(sys.stdlib_module_names) | {"dos"}
    for py in sorted(pkg_dir.glob("*.py")):
        bad = _top_level_imports(py) - allowed
        assert not bad, f"{py.name} imports outside stdlib+dos: {sorted(bad)}"
