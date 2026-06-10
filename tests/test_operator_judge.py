"""Tests for dos.drivers.operator_judge — the operator-decision JUDGE occupant.

The occupant is a thin, pure binding: it maps a host's already-produced
accept/escalate/defer decision onto the canonical three-valued JudgeVerdict, and
registers under the `dos.judges` entry-point group so the host's open-decision
queue is scored by `dos.judge_eval` like any other judge. These tests pin the
mapping (which string clears a claim), the fail-to-abstain discipline through
`run_judge`, the entry-point resolution, and the eval-scorability.
"""
from __future__ import annotations

from dos.drivers.operator_judge import (
    JUDGE_NAME,
    OperatorDecisionJudge,
    stance_for_decision,
    verdict_for_decision,
)
from dos.judges import Claim, Stance, resolve_judge, run_judge


def test_decision_to_stance_mapping():
    assert stance_for_decision("accept-recommended") is Stance.AGREE
    assert stance_for_decision("escalate") is Stance.DISAGREE
    assert stance_for_decision("defer") is Stance.ABSTAIN


def test_unknown_decision_abstains():
    """An unrecognised / unparseable decision is the conservative ABSTAIN — an
    adjudicator that produced something the seam does not recognise has NOT
    cleared the claim."""
    assert stance_for_decision("") is Stance.ABSTAIN
    assert stance_for_decision("yolo") is Stance.ABSTAIN
    assert stance_for_decision(None) is Stance.ABSTAIN  # type: ignore[arg-type]


def test_decision_string_is_case_and_space_insensitive():
    assert stance_for_decision("  ACCEPT-RECOMMENDED ") is Stance.AGREE


def test_verdict_for_decision_carries_reason_and_evidence():
    v = verdict_for_decision(
        "accept-recommended", reason="reversible flag flip",
        evidence=("data/jo_decisions.jsonl",))
    assert v.agreed
    assert v.why == "reversible flag flip"
    assert v.evidence == ("data/jo_decisions.jsonl",)


def test_only_accept_recommended_clears():
    """AGREE is the only verdict that can let a lane proceed automatically — the
    false-clear surface. escalate/defer never clear."""
    assert verdict_for_decision("accept-recommended").agreed
    assert verdict_for_decision("escalate").disagreed
    assert verdict_for_decision("defer").abstained


def test_occupant_rule_reads_decision_off_claim():
    j = OperatorDecisionJudge()
    v = j.rule(Claim(claim_text="escalate", stated_reason="value-laden fork"), None)
    assert v.disagreed
    assert v.why == "value-laden fork"


def test_occupant_satisfies_protocol_and_fails_to_abstain():
    """An unknown claim string maps to ABSTAIN; run_judge would also catch a raise."""
    j = OperatorDecisionJudge()
    assert run_judge(j, Claim(claim_text="???"), None).abstained
    # A genuinely-clearing claim still clears (the mapping is not blanket-abstain).
    assert run_judge(j, Claim(claim_text="accept-recommended"), None).agreed


def test_occupant_resolves_via_entry_point():
    """Registered under dos.judges so resolve_judge finds it by name."""
    j = resolve_judge(JUDGE_NAME)
    assert j.name == JUDGE_NAME
    assert run_judge(j, Claim(claim_text="defer"), None).abstained


def test_occupant_is_eval_scorable():
    """The occupant feeds dos.judge_eval.score — the host re-grounds its
    false-accept gate on the kernel instrument (`JudgeReport.false_clear_rate`)
    instead of a hand-rolled number. A `Case` is (Claim, was-it-actually-true)."""
    from dos.judge_eval import score

    cases = [
        # accept-recommended (AGREE) on a claim that WAS clear-worthy -> correct_clear
        (Claim(claim_text="accept-recommended", subject="d1"), True),
        # accept-recommended (AGREE) on a claim that was NOT -> false_clear (the lie)
        (Claim(claim_text="accept-recommended", subject="d2"), False),
        # escalate (DISAGREE) on a not-clear-worthy claim -> correct_flag
        (Claim(claim_text="escalate", subject="d3"), False),
    ]
    report = score(OperatorDecisionJudge(), cases)
    assert report.correct_clear == 1
    assert report.false_clear == 1
    # 1 false-clear out of 2 AGREE verdicts = 0.5 (the dangerous-cell precision).
    assert report.false_clear_rate == 0.5
