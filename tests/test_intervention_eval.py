"""Tests for dos.intervention_eval — the net-task-delta harness (docs/143 §13.2).

PURE: every test builds `InterventionCase`s with frozen verdicts + ground-truth labels and
reads a `InterventionReport` back. The contract:

  * `_case_delta` implements the §13.2-generalized ledger: a prevented relevant corruption is
    +(1−cost), disruption (cost, read from the ladder) is paid whenever the action ACTUATES,
    a dispatching action has ~0 prevention value;
  * the report's rates all guard divide-by-zero (an empty score → all 0.0, not a crash —
    pins that `sum_disruption_cost` is a real field);
  * the count invariants hold (n_actuated == relevant+irrelevant+false-flag actuated);
  * an all-DEFER policy on a corpus with irrelevant catches is NET-HARMFUL (reproduces the
    live −9pp as a number); a confidence-gated BLOCK/WARN policy beats it on net delta AND
    dangerous-cell rate (the §13.2 #3 win);
  * confidence is DERIVED from the stored verdict in score(), never a hand label (no drift);
  * a flaky policy degrades to the ladder default (fail-to-least-disruptive), not a crash.
"""
from __future__ import annotations

from pathlib import Path

from dos.arg_provenance import (
    ArgProvenance,
    ProvenanceStance,
    ProvenanceVerdict,
)
from dos.intervention import (
    BASE_INTERVENTIONS as L,
    Intervention,
    InterventionPolicy,
)
from dos import intervention_eval as ie
from dos.intervention_eval import InterventionCase, score


# ── verdict helpers ────────────────────────────────────────────────────────────
def _high_verdict():
    a = ArgProvenance("parent", "INC9999999", ProvenanceStance.UNSUPPORTED, True, True,
                      (), ("9999999",), ("9999999",), "")
    return ProvenanceVerdict(believe=False, args=(a,), unsupported=("parent",), reason="")


def _low_verdict():
    a = ArgProvenance("ref", "x@acme", ProvenanceStance.UNSUPPORTED, True, True,
                      (), ("0010023", "acme"), ("acme",), "")
    return ProvenanceVerdict(believe=False, args=(a,), unsupported=("ref",), reason="")


def _clean_verdict():
    return ProvenanceVerdict(believe=True, args=(), unsupported=(), reason="")


def _case(verdict, minted, mattered, rec_block, rec_defer, label=""):
    return InterventionCase(verdict=verdict, truly_minted=minted, mattered_to_score=mattered,
                            recovered_if_blocked=rec_block, recovered_if_deferred=rec_defer,
                            label=label)


# ── the per-case delta ─────────────────────────────────────────────────────────
def test_case_delta_block_recovered_relevant():
    c = _case(_high_verdict(), True, True, True, True)
    d = ie._case_delta(c, Intervention.BLOCK, L)
    assert d == (1.0 - L.disruption_cost("BLOCK")) > 0.0


def test_case_delta_defer_irrelevant_is_negative():
    """DEFER on a true-but-irrelevant catch → −cost (the −9pp dangerous cell)."""
    c = _case(_high_verdict(), True, False, False, False)
    d = ie._case_delta(c, Intervention.DEFER, L)
    assert d == -L.disruption_cost("DEFER") < 0.0


def test_case_delta_warn_dispatches_no_prevention():
    """WARN on a relevant mint: the write LANDS on the irreversible DB → 0 prevention value
    (a dispatched mint cannot be un-committed), strictly worse than the withholding BLOCK."""
    c = _case(_high_verdict(), True, True, True, True)
    d = ie._case_delta(c, Intervention.WARN, L)
    assert d == 0.0
    assert d < (1.0 - L.disruption_cost("BLOCK"))   # strictly worse than the withholding BLOCK


def test_case_delta_false_flag_defer_costs():
    c = _case(_low_verdict(), False, False, False, False)
    d = ie._case_delta(c, Intervention.DEFER, L)
    assert d == -L.disruption_cost("DEFER")


def test_case_delta_observe_clean_is_zero():
    c = _case(_clean_verdict(), False, False, False, False)
    assert ie._case_delta(c, Intervention.OBSERVE, L) == 0.0


# ── the report rates + guards ───────────────────────────────────────────────────
def test_report_div_by_zero_guards():
    r = score(InterventionPolicy(), [])
    assert r.n == 0
    assert r.net_task_delta == 0.0
    assert r.wasted_disruption_rate == 0.0
    assert r.dangerous_cell_rate == 0.0
    assert r.disruption_efficiency == 0.0
    assert r.coverage == 0.0
    assert r.net_harmful is False
    assert r.sum_disruption_cost == 0.0   # the field exists (was an undefined-name bug)
    assert isinstance(r.to_dict(), dict)


def test_report_count_invariants():
    cases = [
        _case(_high_verdict(), True, True, True, True),    # relevant, recovers
        _case(_high_verdict(), True, False, False, False),  # irrelevant (dangerous cell)
        _case(_low_verdict(), False, False, False, False),  # false flag → WARN (dispatches)
        _case(_clean_verdict(), False, False, False, False),  # clean → OBSERVE
    ]
    r = score(InterventionPolicy(), cases)   # default: HIGH→BLOCK, LOW→WARN
    assert r.n == 4
    assert r.n_actuated == r.actuated_irrelevant + r.actuated_false_flag + r.n_actuated_relevant
    assert r.n_actuated + r.n_informed_only == r.n
    assert r.n_true_relevant + r.n_true_irrelevant + r.n_false_flag == r.n


# ── the live −9pp reproduced + the confidence-gating win ────────────────────────
def _mixed_corpus():
    """A corpus where ~1/3 of true catches are IRRELEVANT (the verifier never checks them) —
    the shape that produced the live −9pp under a blanket disruptive intervention."""
    cases = []
    # 6 true-relevant HIGH mints that recover when the turn is preserved (BLOCK) better than
    # when it is spent (DEFER): recovered_if_blocked True, recovered_if_deferred only ~half.
    for i in range(6):
        cases.append(_case(_high_verdict(), True, True, True, i % 2 == 0))
    # 3 true-IRRELEVANT HIGH catches — disrupting on these is pure cost (the −9pp cell)
    for _ in range(3):
        cases.append(_case(_high_verdict(), True, False, False, False))
    # 3 clean calls
    for _ in range(3):
        cases.append(_case(_clean_verdict(), False, False, False, False))
    return cases


def test_all_defer_policy_is_net_harmful():
    cases = _mixed_corpus()
    defer = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="DEFER",
                               ceiling="DEFER")
    r = score(defer, cases)
    assert r.net_harmful is True and r.net_task_delta < 0.0


def test_confidence_gated_block_beats_all_defer():
    cases = _mixed_corpus()
    defer = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="DEFER",
                               ceiling="DEFER")
    block = InterventionPolicy()   # default: HIGH→BLOCK (turn-preserving), LOW→WARN
    rd = score(defer, cases)
    rb = score(block, cases)
    # the non-disruptive BLOCK policy wins net delta and is no worse on the dangerous cell
    assert rb.net_task_delta > rd.net_task_delta
    assert rb.dangerous_cell_rate <= rd.dangerous_cell_rate


def test_confidence_gating_helps_when_irrelevant_are_low_confidence():
    """Confidence-gating's SPECIFIC value: when the irrelevant catches are LOW-confidence
    composites and the relevant ones are HIGH-confidence whole-value mints, gating BLOCKs the
    relevant (winning prevention) while only WARNing the irrelevant (paying no disruption) —
    strictly beating a blanket-BLOCK that would BLOCK both. This is the §13.3 mechanism, and
    it works ONLY under this correlation (confidence is not relevance — see the module note)."""
    cases = []
    for _ in range(6):  # relevant + HIGH confidence + recovers under BLOCK
        cases.append(_case(_high_verdict(), True, True, True, False))
    for _ in range(4):  # irrelevant + LOW confidence (the dangerous cell, but low-conf)
        cases.append(_case(_low_verdict(), True, False, False, False))
    gated = InterventionPolicy()  # HIGH→BLOCK, LOW→WARN
    blanket = InterventionPolicy(on_high_confidence="BLOCK", on_low_confidence="BLOCK")
    rg = score(gated, cases)
    rb = score(blanket, cases)
    assert rg.net_task_delta > rb.net_task_delta
    # gating never BLOCKs the low-confidence irrelevant catches → no wasted disruption on them
    assert rg.actuated_irrelevant == 0
    assert rb.actuated_irrelevant == 4


def test_block_policy_can_go_net_positive():
    """On a corpus dominated by recoverable RELEVANT mints, the turn-preserving BLOCK policy
    is net-POSITIVE — the +pp the §13 double-down is built to win."""
    cases = [_case(_high_verdict(), True, True, True, True) for _ in range(20)]
    cases += [_case(_clean_verdict(), False, False, False, False) for _ in range(5)]
    r = score(InterventionPolicy(), cases)
    assert r.net_task_delta > 0.0 and r.net_harmful is False


def test_warn_floor_is_near_zero_not_harmful():
    """A WARN-everywhere policy (cap escalation at WARN) informs without withholding any turn
    → net delta >= the all-DEFER policy and never deeply negative (the WARN-only arm)."""
    cases = _mixed_corpus()
    warn = InterventionPolicy(on_high_confidence="WARN", on_low_confidence="WARN",
                              ceiling="WARN")
    defer = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="DEFER",
                               ceiling="DEFER")
    rw = score(warn, cases)
    rd = score(defer, cases)
    assert rw.net_task_delta > rd.net_task_delta
    assert rw.n_actuated == 0   # WARN dispatches → never withholds a turn


def test_dangerous_cell_rate_is_the_minus9pp_cell():
    cases = _mixed_corpus()
    r = score(InterventionPolicy(), cases)   # HIGH irrelevant catches → BLOCK (actuates)
    assert r.n_true_irrelevant == 3
    assert r.dangerous_cell_rate == r.actuated_irrelevant / r.n_true_irrelevant


# ── honesty: confidence derived, fail-safe ──────────────────────────────────────
def test_confidence_derived_not_stored():
    """Two cases with the SAME verdict always score the same action — confidence is derived
    in score() from the verdict, never a stored label that could drift."""
    c1 = _case(_high_verdict(), True, True, True, True, label="a")
    c2 = _case(_high_verdict(), True, False, False, False, label="b")
    r = score(InterventionPolicy(), [c1, c2])
    # both HIGH verdicts → BLOCK (actuates) → both actuated, regardless of the other labels
    assert r.n_actuated == 2


def test_score_fail_safe_degrades_to_default(monkeypatch):
    """A policy whose choose_intervention raises degrades to the ladder default (WARN), and
    the eval does not crash — fail-to-least-disruptive."""
    import dos.intervention_eval as mod

    def _boom(verdict, policy, ladder):
        raise RuntimeError("policy blew up")

    monkeypatch.setattr(mod, "choose_intervention", _boom)
    cases = [_case(_high_verdict(), True, True, True, True)]
    r = score(InterventionPolicy(), cases)   # must not raise
    # WARN dispatches → not actuated; the case is booked as informed-only
    assert r.n == 1 and r.n_actuated == 0 and r.n_informed_only == 1


# ── the ground-truth grid is action-INDEPENDENT ─────────────────────────────────
class TestGridIsActionIndependent:
    """The crosstab (`n_true_relevant`/`n_true_irrelevant`/`n_false_flag`) is computed from the
    case LABELS alone — it must be byte-identical under two policies that act differently. The
    `overlap_eval` "the grid counts the ground truth, the policy is scored separately"
    discipline: the crosstab counts what the cases ARE, not what the policy DID."""

    _CASES = [
        _case(_high_verdict(), True, True, True, True),     # true-relevant
        _case(_high_verdict(), True, True, True, False),    # true-relevant
        _case(_high_verdict(), True, False, True, True),    # true-IRRELEVANT
        _case(_low_verdict(), False, False, False, False),  # false-flag
    ]

    def test_grid_identical_under_default_and_all_defer(self):
        # DEFAULT maps HIGH→BLOCK + LOW→WARN; all-DEFER forces every fired verdict to DEFER —
        # the ACTUATION ledgers differ, yet the ground-truth grid is the same crosstab.
        default = score(InterventionPolicy(), self._CASES)
        deferring = score(InterventionPolicy(on_high_confidence="DEFER",
                                             on_low_confidence="DEFER", ceiling="DEFER"),
                          self._CASES)
        # the actions genuinely differ (LOW→WARN dispatches under default, →DEFER actuates).
        assert default.n_actuated != deferring.n_actuated
        for got in (default, deferring):
            assert (got.n_true_relevant, got.n_true_irrelevant, got.n_false_flag) == (2, 1, 1)

    def test_grid_identical_under_all_warn_which_never_actuates(self):
        warn = score(InterventionPolicy(on_high_confidence="WARN",
                                        on_low_confidence="WARN", ceiling="WARN"), self._CASES)
        assert warn.n_actuated == 0   # WARN dispatches → empty actuation ledger
        assert (warn.n_true_relevant, warn.n_true_irrelevant, warn.n_false_flag) == (2, 1, 1)


# ── the rates on a hand-built mix (coverage / efficiency / wasted, all hand-computed) ──
class TestRatesOnHandBuiltMix:
    """A fixed mix scored under DEFAULT (HIGH→BLOCK actuates, LOW→WARN does not), with every
    rate hand-computed in the assertion so a regression in the arithmetic is caught."""

    def _cases(self):
        return [
            # 2 true-relevant HIGH mints → BLOCK (actuates); recovered_if_blocked T then F.
            _case(_high_verdict(), True, True, True, True),
            _case(_high_verdict(), True, True, False, True),
            # 2 true-IRRELEVANT HIGH mints → BLOCK (actuates) → the dangerous cell.
            _case(_high_verdict(), True, False, True, True),
            _case(_high_verdict(), True, False, True, True),
            # 1 false-flag HIGH mint → BLOCK (actuates) → wasted.
            _case(_high_verdict(), False, False, False, False),
            # 1 LOW true-irrelevant mint → WARN (dispatches) → informed-only, NOT actuated.
            _case(_low_verdict(), True, False, True, True),
        ]

    def test_actuation_ledger(self):
        r = score(InterventionPolicy(), self._cases())
        assert (r.n_actuated, r.n_informed_only) == (5, 1)
        assert (r.n_actuated_relevant, r.actuated_irrelevant, r.actuated_false_flag) == (2, 2, 1)

    def test_wasted_disruption_rate(self):
        r = score(InterventionPolicy(), self._cases())
        assert r.wasted_disruption_rate == 3 / 5   # (2 irrelevant + 1 false-flag) / 5 actuated

    def test_dangerous_cell_rate(self):
        r = score(InterventionPolicy(), self._cases())
        # 3 true-irrelevant cases (2 HIGH + 1 LOW), only the 2 HIGH actuated → 2/3.
        assert r.n_true_irrelevant == 3
        assert r.dangerous_cell_rate == 2 / 3

    def test_coverage_rewards_actuating_on_true_relevant(self):
        r = score(InterventionPolicy(), self._cases())
        assert r.n_true_relevant == 2 and r.coverage == 1.0   # both relevant mints actuated

    def test_disruption_efficiency(self):
        r = score(InterventionPolicy(), self._cases())
        # recovered = actuated-relevant that recovered under BLOCK: case0 True, case1 False → 1.
        assert r.recovered == 1
        assert r.disruption_efficiency == 1 / 5   # 1 recovered / 5 actuated

    def test_to_dict_round_trips_headline_numbers(self):
        r = score(InterventionPolicy(), self._cases())
        d = r.to_dict()
        assert d["n"] == 6
        assert d["net_task_delta"] == round(r.net_task_delta, 4)
        assert d["net_harmful"] == r.net_harmful
        assert d["grid"] == {"true_relevant": 2, "true_irrelevant": 3, "false_flag": 1}
        assert d["actuation"]["actuated"] == 5
        assert d["rates"]["wasted_disruption_rate"] == round(r.wasted_disruption_rate, 4)


# ── THE SEED FIXTURE — the headline result (docs/143 KEY DATA POINT, re-scored) ──
class TestSeedFixture:
    """Re-score the docs/143 live A/B as the seed fixture (docs/144 Phase 2). The corpus
    encodes the "⚑ KEY DATA POINT" shape: a MAJORITY of caught mints are true-but-IRRELEVANT
    (the −9 pp source), a minority are true-relevant, and a couple are false-flags.
    `recovered_if_deferred` is set near the live ~75 %; `recovered_if_blocked` is HIGHER
    (BLOCK preserves the turn). Scored under THREE policies, this is the in-repo, reproducible
    demonstration that the confidence-gated DEFAULT beats the disruptive all-DEFER baseline —
    the operator's 'baseline to beat'. The measured, hand-checkable ordering:

        all-DEFER  net = -0.7857   (worst — every catch spends a turn, the −9 pp posture)
        DEFAULT    net = -0.1905   (better — BLOCK is turn-preserving; LOW mints only WARN)
        all-WARN   net =  0.0000   (non-negative — never actuates, never wastes a turn; under
                                    the irreversibility premise a dispatched mint scores 0)
    """

    def _corpus(self):
        cases = []
        # 6 true-but-IRRELEVANT HIGH mints — the dominant −9 pp cell. HIGH, so even the
        # cautious DEFAULT actuates (→ BLOCK) and pays the cost for nothing.
        for i in range(6):
            cases.append(_case(_high_verdict(), True, False, True, True, label=f"irr-high-{i}"))
        # 2 true-but-IRRELEVANT LOW mints — under DEFAULT (LOW→WARN) these DON'T actuate, so
        # DEFAULT wastes less than all-DEFER (which forces them to DEFER). The confidence gate.
        for i in range(2):
            cases.append(_case(_low_verdict(), True, False, True, True, label=f"irr-low-{i}"))
        # 4 true-RELEVANT HIGH mints — the catches that matter. Deferred recovery ~75 % (3 of
        # 4 recover under DEFER); blocked recovery higher (all 4 recover under BLOCK).
        cases.append(_case(_high_verdict(), True, True, True, True, label="rel-0"))
        cases.append(_case(_high_verdict(), True, True, True, True, label="rel-1"))
        cases.append(_case(_high_verdict(), True, True, True, True, label="rel-2"))
        cases.append(_case(_high_verdict(), True, True, True, False, label="rel-3-defer-fails"))
        # 2 false-flags LOW — DEFAULT (LOW→WARN) doesn't waste a turn; all-DEFER does.
        cases.append(_case(_low_verdict(), False, False, False, False, label="ff-0"))
        cases.append(_case(_low_verdict(), False, False, False, False, label="ff-1"))
        return cases

    # the three policies — each verified constructible under InterventionPolicy.__post_init__.
    _ALL_DEFER = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="DEFER",
                                    on_none="OBSERVE", floor="DEFER", ceiling="DEFER")
    _DEFAULT = InterventionPolicy()
    _ALL_WARN = InterventionPolicy(on_high_confidence="WARN", on_low_confidence="WARN",
                                   on_none="OBSERVE", floor="WARN", ceiling="WARN")

    def test_corpus_shape_is_majority_irrelevant(self):
        r = score(self._DEFAULT, self._corpus())
        assert r.n == 14
        assert r.n_true_irrelevant == 8     # 6 HIGH + 2 LOW — the dominant cell
        assert r.n_true_relevant == 4
        assert r.n_false_flag == 2
        # the −9 pp shape: irrelevant catches are the strict majority of all caught mints.
        assert r.n_true_irrelevant > r.n_true_relevant + r.n_false_flag

    def test_all_defer_is_worst_and_net_harmful(self):
        r = score(self._ALL_DEFER, self._corpus())
        assert r.net_harmful is True
        assert round(r.net_task_delta, 4) == -0.7857   # the SKIP/−9 pp arm

    def test_default_net_delta_is_pinned(self):
        r = score(self._DEFAULT, self._corpus())
        assert round(r.net_task_delta, 4) == -0.1905

    def test_all_warn_net_delta_is_pinned_and_non_negative(self):
        # Under the IRREVERSIBILITY premise (`_case_delta`: a dispatched relevant mint already
        # corrupted the scored DB → 0 prevention value), all-WARN withholds nothing, so every
        # cell contributes 0 → net 0.0. The point stands: it NEVER goes negative (it spends no
        # turn), so it strictly beats the deeply-negative all-DEFER baseline.
        r = score(self._ALL_WARN, self._corpus())
        assert r.n_actuated == 0   # WARN dispatches → never withholds a turn
        assert round(r.net_task_delta, 4) == 0.0
        assert r.net_task_delta >= 0.0

    def test_full_ordering_all_defer_lt_default_lt_all_warn(self):
        # The single headline the whole fixture exists to make: the confidence-gated DEFAULT
        # BEATS the disruptive all-DEFER baseline, and never-actuating all-WARN is best here.
        d_defer = score(self._ALL_DEFER, self._corpus()).net_task_delta
        d_default = score(self._DEFAULT, self._corpus()).net_task_delta
        d_warn = score(self._ALL_WARN, self._corpus()).net_task_delta
        assert d_defer < d_default, "DEFAULT must beat the disruptive all-DEFER baseline"
        assert d_defer < d_warn, "all-WARN must beat the disruptive all-DEFER baseline"
        assert d_defer < d_default < d_warn

    def test_all_defer_wastes_more_disruption_than_default(self):
        # The mechanism BEHIND the ordering: all-DEFER actuates on the LOW irrelevant + LOW
        # false-flag cases DEFAULT leaves as WARN, so it spends more turns for nothing.
        d_defer = score(self._ALL_DEFER, self._corpus())
        d_default = score(self._DEFAULT, self._corpus())
        assert d_defer.wasted_disruption_rate > d_default.wasted_disruption_rate
        assert d_defer.n_actuated > d_default.n_actuated


# ── the layering litmus ─────────────────────────────────────────────────────────
def test_layer_litmus_eval_imports_no_host():
    """Import-line check only (prose may name the consumer; an import may not)."""
    src = Path(__file__).resolve().parents[1] / "src" / "dos" / "intervention_eval.py"
    import_lines = [
        ln for ln in src.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith(("import ", "from ")) and "import" in ln
    ]
    blob = "\n".join(import_lines)
    for forbidden in ("dos.drivers", "drivers", "job", "dos_react", "dos_mcp",
                      "scripts", "enterpriseops"):
        assert forbidden not in blob, f"intervention_eval.py imports must not name {forbidden!r}"
    assert "from dos.intervention import" in blob
