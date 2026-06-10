"""Tests for the judge-evaluation harness (`dos.judge_eval`) — the research instrument.

The pinned contract:

  `score` — the confusion grid + derived rates:
    * the six grid cells sum to n; the named cells land where the (stance × truth)
      crosstab says they should;
    * `false_clear_rate` = false-clears / agrees (the dangerous-cell precision);
    * `lie_leak_rate` = false-clears / all-false-claims (recall-of-lies);
    * `decisive_accuracy` excludes abstentions; `abstention_rate` = abstains / n;
    * a flaky judge (one that raises on a case) contributes an ABSTAIN, not a crash;
    * all rates guard divide-by-zero (empty / all-abstain sets) → 0.0.

  `compose_deterministic_first` — the trust-ladder / rung-occupancy report:
    * occupancy counts sum to n (det + judge + human);
    * the oracle's decisive verdicts resolve at the DET rung; the judge sees ONLY
      the residue; abstained residue escalates to HUMAN;
    * the judge is scored on the residue (its true workload), not the full set;
    * the judge runs exactly ONCE per residue claim (cost not double-counted).
"""

from __future__ import annotations

from dos import judge_eval as je
from dos.judges import Claim, JudgeVerdict, Stance


# A small, hand-checkable judge: DISAGREE if "lie" in the text, AGREE if evidence is
# present, else ABSTAIN. Reports cost 1.0 per ruling so cost math is checkable.
class _Heur:
    name = "heur"
    def rule(self, claim, config):
        if "lie" in claim.claim_text:
            return JudgeVerdict.disagree("smells false", cost=1.0)
        if claim.evidence:
            return JudgeVerdict.agree("has evidence", cost=1.0)
        return JudgeVerdict.abstain("no signal", cost=1.0)


# The canonical 5-case set, with each case's intended landing spot annotated:
#   A: agree,    truth True   -> correct_clear
#   B: disagree, truth False  -> correct_flag
#   C: agree,    truth False  -> FALSE CLEAR  (the dangerous cell)
#   D: abstain,  truth True   -> abstain_true
#   E: abstain,  truth False  -> abstain_false
_CASES = [
    (Claim("phase A shipped", evidence=("commit abc",)), True),
    (Claim("phase B shipped (lie)", evidence=("commit def",)), False),
    (Claim("phase C shipped", evidence=("commit ghi",)), False),
    (Claim("phase D unclear"), True),
    (Claim("phase E unclear"), False),
]


def test_score_grid_lands_in_the_right_cells():
    r = je.score(_Heur(), _CASES)
    assert r.n == 5
    assert (r.correct_clear, r.correct_flag, r.false_clear) == (1, 1, 1)
    assert (r.abstain_true, r.abstain_false, r.false_flag) == (1, 1, 0)


def test_score_grid_sums_to_n():
    r = je.score(_Heur(), _CASES)
    total = (r.correct_clear + r.false_clear + r.correct_flag
             + r.false_flag + r.abstain_true + r.abstain_false)
    assert total == r.n


def test_false_clear_rate_is_of_agrees():
    r = je.score(_Heur(), _CASES)
    # 1 false-clear out of 2 agrees (A correct, C false) → 0.5
    assert r.n_agree == 2
    assert r.false_clear_rate == 0.5


def test_lie_leak_rate_is_of_all_false_claims():
    r = je.score(_Heur(), _CASES)
    # 3 ground-truth-false claims (B, C, E); 1 was AGREE'd (C) → 1/3
    assert r.n_false_claims == 3
    assert round(r.lie_leak_rate, 4) == round(1 / 3, 4)


def test_decisive_accuracy_excludes_abstentions():
    r = je.score(_Heur(), _CASES)
    # decisive = 3 (A,B,C); right = 2 (A correct_clear, B correct_flag) → 2/3
    assert round(r.decisive_accuracy, 4) == round(2 / 3, 4)
    assert r.abstention_rate == 2 / 5
    assert r.cost_per_claim == 5.0 / 5  # 1.0 each


def test_rates_guard_divide_by_zero():
    r = je.score(_Heur(), [])
    assert r.n == 0
    assert (r.false_clear_rate, r.lie_leak_rate, r.decisive_accuracy,
            r.abstention_rate, r.cost_per_claim) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_flaky_judge_contributes_abstain_not_crash():
    class Flaky:
        name = "flaky"
        def rule(self, claim, config):
            raise RuntimeError("model timeout")
    r = je.score(Flaky(), _CASES)
    # every case abstained (fail-to-abstain), nothing cleared
    assert r.n_abstain == 5 and r.n_agree == 0 and r.false_clear == 0


# ---------------------------------------------------------------------------
# compose_deterministic_first — the rung-occupancy report.
# ---------------------------------------------------------------------------

def _oracle_clears_A(claim):
    """A deterministic oracle that can only rule on claim A (agrees), abstains else."""
    if claim.claim_text == "phase A shipped":
        return JudgeVerdict.agree("git confirms", cost=0.0)
    return None  # can't rule → residue


def test_rung_occupancy_sums_to_n():
    rr = je.compose_deterministic_first(_oracle_clears_A, _Heur(), _CASES)
    assert rr.det_resolved + rr.judge_resolved + rr.human_resolved == rr.n == 5


def test_deterministic_first_routing():
    rr = je.compose_deterministic_first(_oracle_clears_A, _Heur(), _CASES)
    # oracle ruled A (1); judge ruled B (disagree) + C (agree) = 2 decisive;
    # D, E abstained → human (2)
    assert rr.det_resolved == 1
    assert rr.judge_resolved == 2
    assert rr.human_resolved == 2


def test_judge_scored_on_residue_only():
    rr = je.compose_deterministic_first(_oracle_clears_A, _Heur(), _CASES)
    # the judge never saw A (the oracle settled it) → its report covers 4 cases
    assert rr.judge_report.n == 4
    # and on that residue it false-cleared exactly C
    assert rr.judge_false_clear == 1
    assert rr.judge_report.false_clear == 1


def test_judge_runs_once_per_residue_claim_cost_not_doubled():
    """The judge must run exactly once per residue claim — cost counted once, a
    nondeterministic judge not sampled twice. The residue here is 4 claims at cost
    1.0 each → 4.0, not 8.0 (which a re-run would produce)."""
    rr = je.compose_deterministic_first(_oracle_clears_A, _Heur(), _CASES)
    assert rr.judge_report.total_cost == 4.0


def test_human_occupancy_is_the_oversight_headline():
    """human_occupancy is the share of claims neither rung could clear — what a good
    judge SHRINKS. The abstain baseline (no real judge) leaves everything the oracle
    can't rule to a human; a ruling judge pulls it down."""
    from dos.judges import AbstainJudge
    base = je.compose_deterministic_first(_oracle_clears_A, AbstainJudge(), _CASES)
    better = je.compose_deterministic_first(_oracle_clears_A, _Heur(), _CASES)
    # baseline: oracle clears 1, abstain judge clears 0 → 4 to a human
    assert base.human_resolved == 4
    # the heuristic judge clears 2 of those → only 2 to a human
    assert better.human_resolved == 2
    assert better.human_occupancy < base.human_occupancy
