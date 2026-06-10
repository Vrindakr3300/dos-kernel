"""Tests for the byte-clean schema-refresh corrective extractor (docs/198 §7).

These pin the corrective-KIND classification on the EXACT env-authored error grammars observed in the
EnterpriseOps corpus, so the "76% schema-convertible" ceiling is reproducible and the recursive
category-error guard holds: a NOT_FOUND / already-exists error is NEVER classified SCHEMA (folding
those into the schema cell would over-claim the mechanism's reach one level down).

Run from benchmark/enterpriseops/ (the module imports dos_react for the struct-error grammar):
    python -m pytest test_schema_refresh.py -q
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from schema_refresh import (  # noqa: E402
    extract_corrective, refresh_directive,
    KIND_SCHEMA, KIND_REFERENCE, KIND_STATE, KIND_OPAQUE,
)


def _wrap(text):
    """The gym's {"result":{"content":[{"text":...}]}, "isError":true} wrapper around a message."""
    import json
    return json.dumps({"success": True,
                       "result": {"content": [{"type": "text", "text": text}], "isError": True},
                       "error": None})


# --------------------------------------------------------------------------- SCHEMA kind
def test_missing_required_list_is_schema():
    c = extract_corrective(_wrap(
        "❌ Invalid Tool Arguments: ['responseBodyHtml: is required', "
        "'restrictToContacts: is required', 'restrictToDomain: is required']"))
    assert c.kind == KIND_SCHEMA
    assert c.schema_convertible
    assert "responseBodyHtml" in c.missing_required
    assert "restrictToDomain" in c.missing_required


def test_constraint_sentence_is_schema():
    c = extract_corrective(_wrap("❌ start_time must be a valid epoch millisecond timestamp"))
    assert c.kind == KIND_SCHEMA
    assert c.schema_convertible
    assert any("epoch millisecond" in s for s in c.constraints)


def test_type_mismatch_is_schema():
    c = extract_corrective(_wrap("❌ Invalid Tool Arguments: [\"message: expected type "
                                 "'object', got 'string'\"]"))
    assert c.kind == KIND_SCHEMA
    assert c.schema_convertible
    assert any("expected type" in s for s in c.constraints)


def test_pydantic_value_error_is_schema():
    import json
    detail = json.dumps({"detail": [{"type": "value_error", "loc": ["body", "phone"],
                                     "msg": "Invalid phone format provided: '+91-98101-00011'"}]})
    c = extract_corrective(_wrap(detail))
    assert c.kind == KIND_SCHEMA
    assert any("Invalid phone format" in s for s in c.constraints)


# --------------------------------------------------------------------------- the guard rails
def test_not_found_is_reference_not_schema():
    """The recursive category-error guard: a NOT_FOUND is curable but needs a LOOKUP, not a schema —
    classifying it SCHEMA would over-claim the schema-refresh ceiling."""
    c = extract_corrective(_wrap("Change not found with identifier 'CHG_001'"))
    assert c.kind == KIND_REFERENCE
    assert not c.schema_convertible


def test_already_exists_is_state_not_schema():
    c = extract_corrective(_wrap("❌ Message already has label: ['1c78...']"))
    assert c.kind == KIND_STATE
    assert not c.schema_convertible


def test_opaque_error_is_not_actionable():
    c = extract_corrective(_wrap("❌ Internal error"))
    assert c.kind == KIND_OPAQUE
    assert not c.actionable
    assert not c.schema_convertible


def test_empty_error_is_opaque():
    c = extract_corrective("")
    assert c.kind == KIND_OPAQUE
    assert not c.actionable


# --------------------------------------------------------------------------- the directive (framing only)
def test_directive_surfaces_env_corrective_not_a_dos_invention():
    """DOS authors only the FRAMING; every corrective byte must be the env's. The directive must
    contain the env's field names verbatim and never invent a value."""
    c = extract_corrective(_wrap("❌ Invalid Tool Arguments: ['responseBodyHtml: is required']"))
    d = refresh_directive(c, "update_vacation_settings")
    assert "responseBodyHtml" in d                  # the env's own field name, surfaced
    assert "update_vacation_settings" in d          # the tool it applies to
    assert "environment's" in d.lower()             # framed as the env's reply, not advice
    # it must NOT fabricate a value for the field (no '= <value>' minting)
    assert "responseBodyHtml =" not in d
    assert "responseBodyHtml:" not in d.replace("responseBodyHtml: is required", "")


def test_directive_emits_refetch_when_introspection_available():
    """The GENERAL form: where a tools/list schema-introspection exists, route the agent to RE-FETCH
    the authoritative schema (100% env-authored) before retry."""
    c = extract_corrective(_wrap("❌ some opaque error"))
    d = refresh_directive(c, "create_filter", has_introspection=True)
    assert "RE-FETCH" in d or "re-fetch" in d.lower()
    assert "create_filter" in d


def test_directive_empty_when_nothing_actionable_and_no_introspection():
    c = extract_corrective(_wrap("❌ Internal error"))
    assert refresh_directive(c, "t", has_introspection=False) == ""


# --------------------- the REFERENCE / STATE branches (docs/205: the degenerate-frame fix) ----------
# Before docs/205 these kinds fell through to the generic SCHEMA frame with NO env body (actionable is
# True so they did not early-return "", but missing_required/constraints are empty so every body
# branch was skipped). The fix renders a kind-specific lever carrying the env's verbatim corrective.
def test_reference_directive_routes_a_lookup_and_carries_env_text():
    """A NOT_FOUND corrective must produce a re-fetch forcing function that (a) names a LOOKUP, (b)
    carries the env's verbatim NOT_FOUND message, and (c) invents NO replacement identifier."""
    c = extract_corrective(_wrap("Change not found with identifier 'CHG_001'"))
    d = refresh_directive(c, "update_change")
    assert d != ""                                    # not the degenerate empty/generic frame
    assert c.kind == KIND_REFERENCE
    assert "not found" in d.lower()                   # the env's own message rides through
    assert "update_change" in d                       # the tool it applies to
    assert "resolve" in d.lower() or "LIST" in d or "QUERY" in d  # routes a lookup
    assert "environment" in d.lower()                 # framed as the env's reply, not advice
    # DOS must NOT author a replacement id — it does not know the correct one.
    assert "CHG_002" not in d and "the correct identifier is" not in d.lower()


def test_state_directive_routes_a_replan_and_carries_env_text():
    """An already-exists corrective must produce a re-plan forcing function that (a) says re-plan/
    re-read, (b) carries the env's verbatim conflict message, and (c) authors NO corrected plan."""
    c = extract_corrective(_wrap("❌ Message already has label: applied"))
    d = refresh_directive(c, "modify_message")
    assert d != ""
    assert c.kind == KIND_STATE
    assert "already" in d.lower()                     # the env's own conflict phrase rides through
    assert "modify_message" in d
    assert "plan" in d.lower() or "re-read" in d.lower()  # routes a re-plan
    assert "do not retry the identical call" in d.lower()


def test_reference_state_directives_carry_no_agent_reflected_value():
    """The redacted-raw discipline: if the env error echoes the agent's own input value, that value
    must be stripped from the directive (only the env's structural message is THIRD_PARTY)."""
    # the gym's reflected-input shape: a quoted `'input'` key echoing the agent's value (the exact
    # grammar dos_react._REFLECTED_INPUT strips, the same redaction natural_thrash_gate applies).
    c = extract_corrective(_wrap("Change not found. {'input': 'CHG_DELETED_42'}"))
    d = refresh_directive(c, "update_change")
    assert "CHG_DELETED_42" not in d                  # the agent's reflected value is redacted out
    assert "redacted" in d.lower()                    # replaced by the redaction marker
