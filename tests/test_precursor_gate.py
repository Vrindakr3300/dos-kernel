"""Tests for dos.precursor_gate — the pure precursor-presence fold (docs/147).

PURE: every test hands in a `MutatingCall` + a `CallStream` of `PriorCall`s + a
`PrecursorGrammar` directly (no LLM, no MCP, no DB), so the did-the-mandated-lookup-fire
decision is exercised in isolation — the "testable with zero benchmark access" keystone.

The case families mirror the design's ladder (docs/147 §2) and its safe-direction biases:
  * MUST FIRE     — a mutating call with a declared precursor that NEVER fired → REFUTED → WARN.
  * MUST NOT FIRE — the precursor fired (ATTESTED), an undeclared tool (NO_SIGNAL = the
                    grammar-coverage bound), a read call, the first call, an alias hit.
  * DEAD-LINE     — the verdict NEVER carries a resource/clause/ordering relation; the
                    intervention map emits ONLY WARN (BLOCK structurally absent from the output).
"""
from __future__ import annotations

import pytest

from dos.evidence import EvidenceStance
from dos.intervention import Confidence, Intervention
from dos.precursor_gate import (
    CallStream,
    EMPTY_GRAMMAR,
    MutatingCall,
    PrecursorGrammar,
    PrecursorPolicy,
    PrecursorVerdict,
    classify_call,
    grammar_from_table,
    precursor_intervention,
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _grammar(**requires) -> PrecursorGrammar:
    """A grammar from {mutating_tool: precursor | [precursors]} kwargs (canonicalized)."""
    return grammar_from_table({"requires": {k: v for k, v in requires.items()}})


def _stream(*tool_names: str) -> CallStream:
    from dos.precursor_gate import PriorCall
    return CallStream(calls=tuple(PriorCall(tool_name=t, result_text="{}") for t in tool_names))


def _mut(tool: str = "create_change") -> MutatingCall:
    return MutatingCall(tool_name=tool, is_mutating=True)


# ── MUST FIRE: a declared precursor that never fired → REFUTED ────────────────

def test_missing_precursor_is_refuted():
    """A mutating call whose mandated precursor never appears in the stream → REFUTED."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(_mut("create_change"), _stream("get_change", "list_users"), g)
    assert v.stance is EvidenceStance.REFUTED
    assert v.fired is True
    assert v.present == ()
    assert "check_change_authorization" in v.required


def test_refuted_when_only_other_tools_fired():
    """Other reads fired, but not THE mandated precursor → still REFUTED."""
    g = _grammar(assign_incident=["get_assignment_group", "check_assignment_permission"])
    v = classify_call(_mut("assign_incident"), _stream("get_incident", "get_user"), g)
    assert v.stance is EvidenceStance.REFUTED
    assert set(v.required) == {"get_assignment_group", "check_assignment_permission"}


# ── MUST NOT FIRE: ATTESTED when the precursor is present ─────────────────────

def test_precursor_present_is_attested():
    """The mandated precursor fired earlier in the stream → ATTESTED, no intervention."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(
        _mut("create_change"),
        _stream("get_change", "check_change_authorization", "list_users"),
        g,
    )
    assert v.stance is EvidenceStance.ATTESTED
    assert v.fired is False
    assert v.present == ("check_change_authorization",)


def test_any_one_of_several_precursors_attests():
    """The floor is 'at least one mandated precursor fired', never 'all' — one present → ATTESTED."""
    g = _grammar(assign_incident=["get_assignment_group", "check_assignment_permission"])
    v = classify_call(
        _mut("assign_incident"),
        _stream("get_incident", "check_assignment_permission"),
        g,
    )
    assert v.stance is EvidenceStance.ATTESTED
    assert v.present == ("check_assignment_permission",)


# ── MUST NOT FIRE: NO_SIGNAL — the fail-safe zeros ───────────────────────────

def test_undeclared_mutating_tool_is_no_signal():
    """A mutating tool with NO declared precursor → NO_SIGNAL (the grammar-coverage bound)."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(_mut("delete_record"), _stream("get_record"), g)
    assert v.stance is EvidenceStance.NO_SIGNAL
    assert v.required == ()


def test_read_call_is_no_signal():
    """A read / non-mutating call is never gated — reads source the stream."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(
        MutatingCall(tool_name="get_change", is_mutating=False), _stream("list_users"), g
    )
    assert v.stance is EvidenceStance.NO_SIGNAL


def test_empty_stream_is_no_signal():
    """The first call of an episode — nothing could have fired yet, so we never accuse."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(_mut("create_change"), CallStream(), g)
    assert v.stance is EvidenceStance.NO_SIGNAL
    assert "empty" in v.reason.lower()


def test_empty_grammar_no_signals_everything():
    """No grammar declared → the gate is silent on every call (today's behavior)."""
    v = classify_call(_mut("create_change"), _stream("anything"), EMPTY_GRAMMAR)
    assert v.stance is EvidenceStance.NO_SIGNAL


# ── ALIASES: the synonym allow-list (the false-REFUTED safety valve) ──────────

def test_alias_satisfies_the_mandate():
    """A precursor fired under a declared ALIAS name → ATTESTED (no false-REFUTED)."""
    g = grammar_from_table({
        "requires": {"create_change": ["check_change_authorization"]},
        "aliases": {"check_change_authorization": ["check_access"]},
    })
    v = classify_call(_mut("create_change"), _stream("check_access"), g)
    assert v.stance is EvidenceStance.ATTESTED
    assert "check_access" in v.present


# ── NORMALIZATION: casefold + delimiter canon (the fewest-false-fires bias) ───

def test_casefold_and_delimiter_normalized_by_default():
    """`Check-Change-Authorization` (called) matches `check_change_authorization` (declared)."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(_mut("Create.Change"), _stream("Check-Change-Authorization"), g)
    assert v.stance is EvidenceStance.ATTESTED


def test_case_sensitive_policy_distinguishes_case():
    """Under case_sensitive, a re-cased precursor no longer matches → REFUTED."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(
        _mut("create_change"),
        _stream("Check_Change_Authorization"),
        g,
        PrecursorPolicy(case_sensitive=True),
    )
    assert v.stance is EvidenceStance.REFUTED


def test_case_sensitive_exact_match_attests():
    """Under case_sensitive, an EXACT-case precursor still matches → ATTESTED."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(
        _mut("create_change"),
        _stream("check_change_authorization"),
        g,
        PrecursorPolicy(case_sensitive=True),
    )
    assert v.stance is EvidenceStance.ATTESTED


# ── THE INTERVENTION MAP: REFUTED→WARN only, BLOCK structurally absent ────────

def test_refuted_maps_to_warn():
    """REFUTED → an Intervention.WARN decision (the only fired rung)."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(_mut("create_change"), _stream("get_change"), g)
    decision = precursor_intervention(v)
    assert decision is not None
    assert decision.intervention is Intervention.WARN
    assert decision.rung.dispatches is True  # the call STILL fires (turn preserved)
    assert decision.confidence is Confidence.NONE  # no mint-confidence for a precursor verdict
    assert "create_change" in decision.unsupported


def test_attested_and_no_signal_map_to_no_intervention():
    """ATTESTED / NO_SIGNAL → None (no intervention; dispatch unchanged)."""
    g = _grammar(create_change="check_change_authorization")
    attested = classify_call(_mut("create_change"), _stream("check_change_authorization"), g)
    no_sig = classify_call(_mut("delete_record"), _stream("x"), g)
    assert precursor_intervention(attested) is None
    assert precursor_intervention(no_sig) is None


def test_intervention_is_warn_only_no_harder_rung():
    """The map's ONLY non-None output is WARN — BLOCK/DEFER are unreachable by construction
    (docs/147 §4: WARN-only-by-output-type, the over-enforcement lesson made structural)."""
    g = _grammar(create_change="check_change_authorization")
    # Across every fired case, the rung is always exactly WARN — there is no escalation path.
    for stream in (_stream("get_change"), _stream("a", "b", "c")):
        v = classify_call(_mut("create_change"), stream, g)
        if v.fired:
            d = precursor_intervention(v)
            assert d.intervention is Intervention.WARN
            assert d.intervention not in (Intervention.BLOCK, Intervention.DEFER)


# ── DEAD-LINE: the verdict carries no resource/clause/ordering relation ───────

def test_verdict_carries_no_relation_only_presence():
    """The verdict exposes ONLY tool/required/present (a presence fact) — no resource id, no
    clause-satisfaction, no ordering claim (the §3 dead-line, enforced by the type's shape)."""
    g = _grammar(create_change="check_change_authorization")
    v = classify_call(_mut("create_change"), _stream("get_change"), g)
    d = v.to_dict()
    assert set(d) == {"stance", "mutating_tool", "required", "present", "reason"}
    # nothing resource-bound or authorization-shaped leaks into the verdict
    assert "resource" not in d and "authorized" not in d and "clause" not in d


# ── DETERMINISM / PURITY ──────────────────────────────────────────────────────

def test_classify_is_deterministic():
    g = _grammar(create_change="check_change_authorization")
    s = _stream("get_change", "list_users")
    a = classify_call(_mut("create_change"), s, g)
    b = classify_call(_mut("create_change"), s, g)
    assert a == b


def test_grammar_from_table_canonicalizes():
    """The grammar keys/values are canonicalized at load (no per-call normalization needed)."""
    g = grammar_from_table({"requires": {"Create-Change": "Check.Access"}})
    assert g.required_set("create_change") == frozenset({"check_access"})
    # a scalar precursor is accepted in place of a one-element list
    assert g.required_set("CREATE.CHANGE") == frozenset({"check_access"})


def test_only_prior_calls_count_not_the_call_itself():
    """A self-named precursor in the SAME call does not count — only PRIOR stream calls do.
    (The stream is the calls BEFORE this one; the mutating call is not in it.)"""
    g = _grammar(create_change="create_change")  # degenerate: requires itself
    v = classify_call(_mut("create_change"), CallStream(), g)
    assert v.stance is EvidenceStance.NO_SIGNAL  # empty stream → never fired
