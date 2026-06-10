"""Tests for dos.precursor_gate_eval — the per-axis grammar eval (docs/147 §9.2).

PURE: hands in labelled `PrecursorCase`s + a `PrecursorGrammar` and checks the recall/false-fire
ledger. The labels are researcher ground truth (precursor_required / precursor_actually_fired),
NEVER derived from the grammar under test — the `tool_stream_eval` / `intervention_eval`
honesty discipline.
"""
from __future__ import annotations

from dos.precursor_gate import (
    CallStream,
    MutatingCall,
    PriorCall,
    grammar_from_table,
)
from dos.precursor_gate_eval import PrecursorCase, score


def _g(**requires):
    return grammar_from_table({"requires": dict(requires)})


def _case(mutating, prior_tools, *, required, fired, mattered=False):
    return PrecursorCase(
        call=MutatingCall(tool_name=mutating, is_mutating=True),
        stream=CallStream(calls=tuple(PriorCall(tool_name=t) for t in prior_tools)),
        precursor_required=required,
        precursor_actually_fired=fired,
        mattered_to_score=mattered,
    )


def test_perfect_grammar_catches_every_skip():
    """A grammar covering the mutating tool catches a real skip and is silent on a sequenced call."""
    g = _g(create_change="check_change_authorization")
    cases = [
        _case("create_change", ["get_change"], required=True, fired=False, mattered=True),  # real skip
        _case("create_change", ["check_change_authorization"], required=True, fired=True),  # sequenced
    ]
    r = score(g, cases)
    assert r.n == 2
    assert r.n_real_skip == 1 and r.n_correctly_sequenced == 1
    assert r.n_refuted == 1 and r.n_refuted_skip == 1 and r.n_refuted_fired == 0
    assert r.missed_precursor_recall == 1.0
    assert r.false_refute_rate == 0.0
    assert r.mattered_recall == 1.0
    assert r.net_positive is True


def test_uncovered_tool_misses_the_skip_recall_drops():
    """A real skip on a tool the grammar does NOT cover → NO_SIGNAL, not caught → recall 0."""
    g = _g(create_change="check_change_authorization")  # does NOT cover delete_record
    cases = [_case("delete_record", ["get_record"], required=True, fired=False)]
    r = score(g, cases)
    assert r.n_real_skip == 1
    assert r.n_refuted == 0  # NO_SIGNAL, never fired
    assert r.missed_precursor_recall == 0.0  # the grammar-coverage bound, made measurable
    assert r.net_positive is False


def test_unlisted_alias_causes_false_refute():
    """A precursor fired under a synonym the grammar did not list → false REFUTED on a sequenced call."""
    g = _g(create_change="check_change_authorization")  # no alias for check_access
    cases = [
        # ground truth: the precursor DID fire (under check_access), so this is correctly sequenced
        _case("create_change", ["check_access"], required=True, fired=True),
    ]
    r = score(g, cases)
    assert r.n_correctly_sequenced == 1
    assert r.n_refuted == 1 and r.n_refuted_fired == 1
    assert r.false_refute_rate == 1.0  # the alias gap, surfaced — grow aliases (R3 calibration)
    assert r.net_positive is False


def test_alias_closes_the_false_refute_gap():
    """Adding the alias makes the same case ATTESTED → false_refute_rate drops to 0 (R3 payoff)."""
    g = grammar_from_table({
        "requires": {"create_change": ["check_change_authorization"]},
        "aliases": {"check_change_authorization": ["check_access"]},
    })
    cases = [_case("create_change", ["check_access"], required=True, fired=True)]
    r = score(g, cases)
    assert r.n_refuted == 0
    assert r.false_refute_rate == 0.0


def test_ledger_invariant_holds():
    """n_refuted_skip + n_refuted_fired never exceeds n_refuted; mattered <= skip."""
    g = _g(create_change="check_change_authorization", assign_incident="get_assignment_group")
    cases = [
        _case("create_change", ["x"], required=True, fired=False, mattered=True),
        _case("assign_incident", ["y"], required=True, fired=False),
        _case("create_change", ["check_change_authorization"], required=True, fired=True),
    ]
    r = score(g, cases)
    assert r.n_refuted_skip + r.n_refuted_fired <= r.n_refuted
    assert r.n_refuted_skip_mattered <= r.n_refuted_skip


def test_empty_cases_safe():
    r = score(_g(create_change="check_change_authorization"), [])
    assert r.n == 0
    assert r.missed_precursor_recall == 0.0
    assert r.false_refute_rate == 0.0
    assert r.net_positive is False


def test_to_dict_shape():
    g = _g(create_change="check_change_authorization")
    r = score(g, [_case("create_change", ["x"], required=True, fired=False)])
    d = r.to_dict()
    assert set(d) == {"n", "grid", "firing", "rates", "net_positive"}
    assert set(d["rates"]) == {
        "missed_precursor_recall", "false_refute_rate", "fire_precision", "mattered_recall"
    }
