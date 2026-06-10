"""test_cause_locality.py — pin the docs/172 §0.3 cause-locality ablation (no gym, no LLM).

The ablation subdivides a natural thrash into A (recoverable-from-prefix → rewind-addressable),
B (upstream-omission/guessing → rewind livelocks), C (schema/not-in-transcript → model-capability
gap, unreachable by any transcript move). These tests pin the three classes on hand-built
tool_results, including the load-bearing FALSE-A guard: a coincidental digit-substring match must
NOT promote a guessing case (B) to recoverable (A).

Run: PYTHONPATH=...src:...benchmark/enterpriseops python -m pytest benchmark/enterpriseops/test_cause_locality.py -q
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, "..", "..", "src"), _HERE):
    if os.path.isdir(p):
        sys.path.insert(0, p)

import pytest  # noqa: E402

import cause_locality as CL  # noqa: E402


def _ok(tool, payload_text):
    """An OK (non-error) tool result whose env bytes carry `payload_text`."""
    return {"tool_name": tool, "arguments": {},
            "result": {"success": True, "error": None,
                       "result": {"content": [{"type": "text", "text": payload_text}]}}}


def _schema_err(tool, msg, args=None):
    """A class-C-shaped structured schema error (isError + an Invalid-Tool-Arguments message)."""
    return {"tool_name": tool, "arguments": args or {},
            "result": {"success": True, "error": None,
                       "result": {"content": [{"type": "text",
                                               "text": f"Invalid Tool Arguments: [{msg}]"}],
                                  "isError": True}}}


def _notfound_err(tool, entity_msg, args=None):
    """A class-A/B-shaped reference error ('X not found') in the REST envelope shape."""
    body = ('{"detail": {"error": true, "error_code": "RESOURCE_NOT_FOUND", '
            f'"message": "{entity_msg}"}}}}')
    return {"tool_name": tool, "arguments": args or {},
            "result": {"success": True, "error": None,
                       "result": {"content": [{"type": "text", "text": body}], "isError": True}}}


def test_class_C_schema_complaint_is_not_in_transcript():
    """A schema/required-field complaint repeated ≥2× = class C (model-capability gap). No tool
    result anywhere carries the fix, so it is unreachable by rewind/restart/append."""
    trs = [
        _ok("list_users", '[{"user_id": 7}]'),
        _schema_err("create_filter", "'criteria.from: is required'"),
        _schema_err("create_filter", "'criteria.from: is required'"),
    ]
    r = CL._classify_thrash(trs, "create_filter")
    assert r is not None
    assert r["class"] == "C_not_in_transcript", r["why"]


def test_class_B_guessing_is_upstream_omission_not_false_A():
    """The load-bearing FALSE-A guard: the agent GUESSES incident ids (INC-000001/044) that were
    never read. A coincidental digit-substring in an unrelated prefix result must NOT promote it to
    class A — it is class B (upstream omission, rewind livelocks)."""
    trs = [
        # an unrelated OK read that happens to contain the digits '44' and '1' somewhere
        _ok("create_knowledge_article", '{"knowledge_id": "KB_026", "version": 1, "views": 44}'),
        _notfound_err("link_knowledge_to_incident", "Incident 'INC-000001' not found",
                      args={"incident_id": "INC-000001", "knowledge_id": "KB_026"}),
        _notfound_err("link_knowledge_to_incident", "Incident 'INC-000044' not found",
                      args={"incident_id": "INC-000044", "knowledge_id": "KB_026"}),
    ]
    r = CL._classify_thrash(trs, "link_knowledge_to_incident")
    assert r is not None
    assert r["class"] == "B_upstream_omission", (
        f"a guessed id with no concrete prefix candidate must be B, got {r['class']}: {r['why']}")


def test_class_A_recoverable_when_correct_value_in_prefix():
    """When an OK prefix read RETURNED the correct entity id (a DIFFERENT value than the agent's
    failing one), the fix is in the surviving prefix → class A (rewind-addressable)."""
    trs = [
        # a real find that returned the correct incident_id INC_555
        _ok("find_incident", '{"incident_id": "INC_555", "number": "INC0000555"}'),
        # the agent then links using a WRONG incident_id (INC_999), not the one it just read
        _notfound_err("link_knowledge_to_incident", "Incident 'INC_999' not found",
                      args={"incident_id": "INC_999", "knowledge_id": "KB_1"}),
        _notfound_err("link_knowledge_to_incident", "Incident 'INC_999' not found",
                      args={"incident_id": "INC_999", "knowledge_id": "KB_1"}),
    ]
    r = CL._classify_thrash(trs, "link_knowledge_to_incident")
    assert r is not None
    assert r["class"] == "A_recoverable_from_prefix", (
        f"the correct INC_555 is in the prefix and differs from the bad INC_999 → A, "
        f"got {r['class']}: {r['why']}")


def test_single_failure_is_not_a_thrash():
    """One failure is not a thrash (needs ≥2 un-recovered)."""
    trs = [_ok("x", "{}"), _schema_err("create_filter", "'a: is required'")]
    assert CL._classify_thrash(trs, "create_filter") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
