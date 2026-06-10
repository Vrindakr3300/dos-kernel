"""Tests for `dos.testwitness` — the test-witness verdict (docs/288, TWV), at $0.

Pins, with no model, no network, and no test actually run twice:
  * the five-valued ladder `classify` — DISCRIMINATES red->green, VACUOUS pass/pass
    (the FrontierCode false-positive shape), UNSATISFIED no-green, REGRESSIVE
    breaks-baseline, ABSTAIN on a missing run;
  * THE NON-FORGEABILITY FLOOR: the SAME two outcome bits on the `AGENT_AUTHORED`
    rung (the agent narrated "it failed before and passes now") ABSTAIN — an agent
    cannot narrate its way to DISCRIMINATES, exactly as a forgeable read-back
    cannot ACCEPT in `reward` (the docs/138 invariant at the test-claim seam);
  * the `witnesses` projection bit is True for DISCRIMINATES and ONLY there
    (proved over the exhaustive outcome matrix, not by spot checks);
  * the `assert_level` bit splits the strong (baseline FAILED — ran-and-rejected)
    from the structural (baseline ERRORED — import-level) discrimination;
  * the CLI verb `dos test-witness` — the verdict IS the exit code
    (DISCRIMINATES 0 / VACUOUS 3 / UNSATISFIED 4 / REGRESSIVE 5 / ABSTAIN 6),
    published through `dos exit-codes` like every other verdict verb.
"""
from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos.evidence import Accountability
from dos.testwitness import (
    ABSTAIN,
    DISCRIMINATES,
    REGRESSIVE,
    UNSATISFIED,
    VACUOUS,
    RunOutcome,
    TestRunEvidence,
    TestWitness,
    classify,
)


# --- the ladder, rung by rung -----------------------------------------------------------

def test_red_to_green_discriminates():
    """baseline FAILED, candidate PASSED — the only witness-minting verdict, and the
    assert-level (strong) form: the test RAN against the old behavior and rejected it."""
    v = classify(TestRunEvidence.of("fail", "pass"))
    assert v.verdict is DISCRIMINATES
    assert v.witnesses is True
    assert v.assert_level is True


def test_structural_red_to_green_discriminates_but_not_assert_level():
    """baseline ERRORED (e.g. the test imports a module only the candidate tree has) —
    honestly DISCRIMINATES (it provably cannot pass without the change), but the
    `assert_level` bit is False: it never executed against the old behavior. A consumer
    that wants only the strong form filters on the bit, never re-parses prose."""
    v = classify(TestRunEvidence.of("error", "pass"))
    assert v.verdict is DISCRIMINATES
    assert v.witnesses is True
    assert v.assert_level is False


def test_pass_on_both_trees_is_vacuous():
    """The load-bearing verdict — the FrontierCode false-positive shape: a test that
    passes on the tree WITHOUT the change witnesses nothing, however green the suite."""
    v = classify(TestRunEvidence.of("pass", "pass"))
    assert v.verdict is VACUOUS
    assert v.witnesses is False
    assert v.assert_level is False


def test_candidate_not_green_is_unsatisfied():
    """Red on the candidate tree (and the baseline didn't pass either): the change does
    not satisfy its own test — the red half of red->green without the green."""
    for b, c in (("fail", "fail"), ("fail", "error"), ("error", "fail"), ("error", "error")):
        v = classify(TestRunEvidence.of(b, c))
        assert v.verdict is UNSATISFIED, (b, c)
        assert v.witnesses is False


def test_breaking_a_baseline_green_test_is_regressive():
    """baseline PASSED, candidate not — the change BREAKS the test (FrontierCode's
    regression-safety dimension, reduced to its deterministic core)."""
    for c in ("fail", "error"):
        v = classify(TestRunEvidence.of("pass", c))
        assert v.verdict is REGRESSIVE, c
        assert v.witnesses is False


def test_missing_run_abstains():
    """Half a join is not a join: either tree lacking a runner outcome ABSTAINS —
    never guess the missing half."""
    assert classify(TestRunEvidence.of("not-run", "pass")).verdict is ABSTAIN
    assert classify(TestRunEvidence.of("fail", "not-run")).verdict is ABSTAIN
    assert classify(TestRunEvidence.of("not-run", "not-run")).verdict is ABSTAIN


# --- the non-forgeability floor (the docs/138 invariant, the $0 demo) -------------------

def test_narrated_red_to_green_cannot_discriminate():
    """THE FLOOR: the same red->green bits on the AGENT_AUTHORED rung (the agent
    narrated 'it failed before and passes now') ABSTAIN. An agent cannot write its way
    to DISCRIMINATES — the only path is a test that actually fails on the tree it
    didn't get to touch. The `reward --witness confirm --forgeable` proof, restated."""
    v = classify(TestRunEvidence.of("fail", "pass", forgeable=True))
    assert v.verdict is ABSTAIN
    assert v.witnesses is False
    assert "AGENT_AUTHORED" in v.reason


def test_forgeable_rung_abstains_whatever_the_outcomes_say():
    """The floor is structural, not outcome-shaped: EVERY outcome pair on the forgeable
    rung abstains — there is no narration that reaches any other verdict."""
    for b, c in itertools.product(RunOutcome, RunOutcome):
        v = classify(TestRunEvidence(baseline=b, candidate=c,
                                     rung=Accountability.AGENT_AUTHORED))
        assert v.verdict is ABSTAIN, (b, c)
        assert v.witnesses is False


def test_third_party_rung_is_non_forgeable_and_classifies():
    """THIRD_PARTY (e.g. a CI provider's recorded runner outcome) sits above the floor
    exactly as OS_RECORDED does — the spectrum, not a special case."""
    v = classify(TestRunEvidence(baseline=RunOutcome.FAILED,
                                 candidate=RunOutcome.PASSED,
                                 rung=Accountability.THIRD_PARTY))
    assert v.verdict is DISCRIMINATES


# --- the exhaustive matrix: every pair gets exactly one verdict; the bit is honest ------

def test_every_outcome_pair_classifies_and_witnesses_only_on_discriminates():
    """Over the full 4x4 outcome matrix on the non-forgeable rung: classify never
    raises, the verdict is total, `witnesses` is True iff DISCRIMINATES, and
    DISCRIMINATES happens iff (baseline red, candidate PASSED)."""
    for b, c in itertools.product(RunOutcome, RunOutcome):
        v = classify(TestRunEvidence(baseline=b, candidate=c))
        assert isinstance(v.verdict, TestWitness), (b, c)
        expected_discriminates = (
            b in (RunOutcome.FAILED, RunOutcome.ERRORED) and c is RunOutcome.PASSED
        )
        assert v.witnesses is expected_discriminates, (b, c, v.verdict)
        assert (v.verdict is DISCRIMINATES) is expected_discriminates, (b, c, v.verdict)
        # assert_level implies witnesses (the strong form is a form of the witness).
        assert not (v.assert_level and not v.witnesses), (b, c)


# --- evidence construction & the JSON shape ---------------------------------------------

def test_parse_aliases_and_unknown_token_raises():
    assert RunOutcome.parse("PASSED") is RunOutcome.PASSED
    assert RunOutcome.parse("Fail") is RunOutcome.FAILED
    assert RunOutcome.parse("errored") is RunOutcome.ERRORED
    assert RunOutcome.parse("not_run") is RunOutcome.NOT_RUN
    with pytest.raises(ValueError):
        RunOutcome.parse("flaky")


def test_evidence_rejects_non_outcome_inputs():
    with pytest.raises(ValueError):
        TestRunEvidence(baseline="fail", candidate=RunOutcome.PASSED)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TestRunEvidence(baseline=RunOutcome.FAILED, candidate=None)  # type: ignore[arg-type]


def test_to_dict_carries_verdict_bits_and_facts():
    """`--json` emits the verdict AND the facts behind it in one object (legible
    distrust): the consumer sees not just DISCRIMINATES but the two runs and the rung."""
    d = classify(TestRunEvidence.of("fail", "pass")).to_dict()
    assert d["verdict"] == "DISCRIMINATES"
    assert d["witnesses"] is True
    assert d["assert_level"] is True
    assert d["evidence"] == {"baseline": "FAILED", "candidate": "PASSED",
                             "rung": "OS_RECORDED"}
    assert isinstance(d["reason"], str) and d["reason"]


# --- the CLI verb: the verdict IS the exit code -----------------------------------------

def _env() -> dict:
    import os
    return {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
    }


def _cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "from dos.cli import main; raise SystemExit(main())",
         *argv],
        capture_output=True, text=True, encoding="utf-8", env=_env())


def test_cli_exit_codes_are_the_verdict():
    """DISCRIMINATES 0 / VACUOUS 3 / UNSATISFIED 4 / REGRESSIVE 5 / ABSTAIN 6 — a CI
    step branches on `$?` with no JSON glue (the verdict-IS-the-exit-code contract)."""
    assert _cli("test-witness", "--baseline", "fail", "--candidate", "pass").returncode == 0
    assert _cli("test-witness", "--baseline", "pass", "--candidate", "pass").returncode == 3
    assert _cli("test-witness", "--baseline", "fail", "--candidate", "fail").returncode == 4
    assert _cli("test-witness", "--baseline", "pass", "--candidate", "fail").returncode == 5
    assert _cli("test-witness", "--baseline", "not-run", "--candidate", "pass").returncode == 6


def test_cli_bare_invocation_abstains():
    """No outcomes supplied -> both default NOT_RUN -> ABSTAIN (exit 6): the honest
    zero, the `dos reward` default-witness-none posture."""
    assert _cli("test-witness").returncode == 6


def test_cli_forgeable_floor_demo():
    """The $0 floor demo: `--baseline fail --candidate pass --forgeable` ABSTAINS
    (exit 6) — a narrated red->green is structurally ignored."""
    cp = _cli("test-witness", "--baseline", "fail", "--candidate", "pass", "--forgeable")
    assert cp.returncode == 6, (cp.stdout, cp.stderr)
    assert "ABSTAIN" in cp.stdout


def test_cli_json_shape():
    cp = _cli("test-witness", "--baseline", "error", "--candidate", "pass", "--json")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    d = json.loads(cp.stdout)
    assert d["verdict"] == "DISCRIMINATES"
    assert d["assert_level"] is False
    assert d["evidence"]["rung"] == "OS_RECORDED"


def test_cli_publishes_exit_code_contract():
    """`dos exit-codes test-witness --json` publishes the map (one source with the
    handler's own ExitMap, so the table and the behaviour cannot drift)."""
    cp = _cli("exit-codes", "test-witness", "--json")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    row = json.loads(cp.stdout)["test-witness"]
    assert row == {"DISCRIMINATES": 0, "VACUOUS": 3, "UNSATISFIED": 4,
                   "REGRESSIVE": 5, "ABSTAIN": 6, "contract_error": 2, "unknown": 7}
