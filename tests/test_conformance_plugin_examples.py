"""The `examples/conformance_plugins/` trio stays conformant (docs/306 P2).

The three plugin packages under `examples/conformance_plugins/` are the
worked out-of-tree examples for `dos.testing` — a real author copies one and
swaps in their occupant. They are NOT installed in this repo's environment
(they are examples, not dependencies), so this pin imports each occupant
module by file path and runs the SAME conformance classes the plugin's own
`tests/test_conformance.py` runs — everything except the entry-point
discovery checks, which need the plugin's `pip install -e .` and are proven
by the out-of-tree run recorded on issue #61.

If a seam law or a conformance signature changes, this file is what turns
the silent example-rot into a red build.

Source-tree-only: an installed wheel ships no `examples/`, so the module
skips when the directory is absent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from dos.testing.suite import (
    JudgeConformance,
    NotifierConformance,
    OverlapPolicyConformance,
)

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "conformance_plugins"

pytestmark = pytest.mark.skipif(
    not _EXAMPLES.is_dir(),
    reason="the conformance-plugin examples only exist in the source tree",
)


def _load(subdir: str, module: str):
    """Import an example plugin's occupant module by file path (the examples
    are not installed packages)."""
    path = _EXAMPLES / subdir / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"_example_{module}", path)
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestExampleJudgeConformance(JudgeConformance):
    """The judge example passes the same laws its own checkout proves."""

    def make_judge(self):
        return _load("judge_plugin", "example_judge").EvidenceCountJudge()


class TestExampleOverlapPolicyConformance(OverlapPolicyConformance):
    """The overlap-policy example passes the same laws, arbiter case included."""

    def make_policy(self):
        return _load(
            "overlap_policy_plugin", "example_overlap_policy"
        ).BasenameOverlapPolicy()


class TestExampleNotifierConformance(NotifierConformance):
    """The notifier example passes the same fail-soft laws."""

    def make_notifier(self):
        return _load("notifier_plugin", "example_notifier").CollectingNotifier()


def test_the_judge_example_tables_still_rule_as_documented():
    """The behavior its README/tests advertise: evidence → AGREE, blank
    evidence → DISAGREE, none → ABSTAIN."""
    from dos.judges import Claim
    from dos.testing import JudgeTester

    judge = _load("judge_plugin", "example_judge").EvidenceCountJudge()
    JudgeTester(judge).run(
        agree=[Claim("phase P1 shipped", evidence=("commit abc1234",))],
        disagree=[Claim("phase P2 shipped", evidence=("", "  "))],
        abstain=["no evidence either way"],
    )
