"""The plugin's own CI: conformance + behavior tables + discovery.

This file is the whole point of `dos.testing` — the kernel's seam safety
laws, proven HERE, in the plugin's checkout, against the installed
`dos-kernel` version. The kernel repo never sees this code.
"""

from dos.judges import Claim
from dos.testing import JudgeTester
from dos.testing.suite import JudgeConformance

from example_judge import EvidenceCountJudge


class TestEvidenceCountJudgeConformance(JudgeConformance):
    """One factory override — pytest runs every seam law."""

    def make_judge(self):
        return EvidenceCountJudge()


def test_ruling_tables():
    """The JudgeTester half: expected-stance tables, hostile cases auto-run."""
    JudgeTester(EvidenceCountJudge()).run(
        agree=[Claim("phase P1 shipped", evidence=("commit abc1234",))],
        disagree=[Claim("phase P2 shipped", evidence=("", "  "))],
        abstain=["no evidence either way"],
    )


def test_registered_under_the_entry_point_group():
    """The pyproject entry point took: the kernel resolves this judge by name.
    (Needs the `pip install -e .` — discovery reads installed metadata.)"""
    from dos.judges import resolve_judge

    assert resolve_judge("evidence-count").name == "evidence-count"
