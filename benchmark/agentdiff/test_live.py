"""$0 tests for the live ΔB harness's PURE seams — no SDK, no key, no backend.

The network-touching paths (`_gemini.chat`, `live_agent.run_a_task`, `delta_b.run_delta_b`)
are exercised by the paid live run; here we pin the pure logic those paths rest on:
  * `_gemini._to_gemini_payload` — message→Gemini mapping + model-aware thinking budget,
  * `live_agent._parse_react` + `ARow.to_dict` — the ReAct tag parse + the cached-row shape,
  * `delta_b` cache + slice helpers — resumability + the difficulty-sorted task selection.
These have no import-time dependency on the Agent-Diff clone, so they run in the kernel suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# benchmark/ on path (mirrors how the suite is run as `python -m pytest` from repo root)
_BENCH = str(Path(__file__).resolve().parents[1])
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from agentdiff._gemini import _to_gemini_payload, _extract_text, ChatResult, _FLASH_THINKING_BUDGET
from agentdiff.live_agent import _parse_react, ARow
from agentdiff import delta_b as db


# --------------------------------------------------------------------------------------------
# _gemini: the message→Gemini payload mapping
# --------------------------------------------------------------------------------------------

def test_payload_splits_system_into_systemInstruction():
    msgs = [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "<observation>x</observation>"},
    ]
    body = _to_gemini_payload(msgs, model="gemini-2.5-flash", max_output_tokens=128)
    # system goes to systemInstruction, NOT into contents
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    roles = [c["role"] for c in body["contents"]]
    assert roles == ["user", "model", "user"]  # assistant maps to Gemini's "model"
    assert body["generationConfig"]["temperature"] == 0.0
    assert body["generationConfig"]["maxOutputTokens"] == 128


def test_flash_gets_bounded_thinking_budget():
    body = _to_gemini_payload([{"role": "user", "content": "x"}],
                              model="gemini-2.5-flash", max_output_tokens=64)
    assert body["generationConfig"]["thinkingConfig"]["thinkingBudget"] == _FLASH_THINKING_BUDGET


def test_pro_omits_thinking_budget():
    # pro/gemini-3 REJECT a 0 budget; we must NOT send thinkingConfig at all (API default).
    for model in ("gemini-2.5-pro", "gemini-3-pro-preview", "gemini/gemini-2.5-pro"):
        body = _to_gemini_payload([{"role": "user", "content": "x"}],
                                  model=model, max_output_tokens=64)
        assert "thinkingConfig" not in body["generationConfig"], model


def test_gemini3_flash_still_takes_flash_path():
    # the -pro discriminator must not catch a future gemini-3-flash.
    body = _to_gemini_payload([{"role": "user", "content": "x"}],
                              model="gemini-3-flash-preview", max_output_tokens=64)
    assert "thinkingConfig" in body["generationConfig"]


def test_extract_text_concatenates_parts_and_finish():
    data = {"candidates": [{"finishReason": "STOP",
                            "content": {"parts": [{"text": "foo"}, {"text": "bar"}]}}]}
    text, finish = _extract_text(data)
    assert text == "foobar"
    assert finish == "STOP"


def test_extract_text_handles_no_candidates():
    text, finish = _extract_text({"promptFeedback": {"blockReason": "SAFETY"}})
    assert text == ""
    assert finish == "SAFETY"


# --------------------------------------------------------------------------------------------
# live_agent: the ReAct tag parse + cached-row shape
# --------------------------------------------------------------------------------------------

def test_parse_react_action():
    action, done = _parse_react("<thinking>plan</thinking>\n<action>print(1)</action>")
    assert action == "print(1)"
    assert done is None


def test_parse_react_done():
    action, done = _parse_react("<thinking>ok</thinking>\n<done>renamed the file</done>")
    assert action is None
    assert done == "renamed the file"


def test_parse_react_neither():
    action, done = _parse_react("I am confused")
    assert action is None and done is None


def test_arow_to_dict_roundtrips_handoff_fields():
    row = ARow(test_id="box_1", service="box", operation_type="search+U",
               completed=True, answer_excerpt="done", passed=False,
               score={"total": 1}, failures=("nope",))
    d = row.to_dict()
    # the cached-row keys AHandoff.from_row reads must be present
    for k in ("test_id", "service", "answer_excerpt", "passed", "completed"):
        assert k in d
    assert d["passed"] is False
    assert d["failures"] == ["nope"]
    # and the dict re-hydrates into an ARow (the resume path)
    rt = ARow(**{k: v for k, v in d.items() if k in ARow.__dataclass_fields__})
    assert rt.test_id == "box_1" and rt.passed is False


# --------------------------------------------------------------------------------------------
# delta_b: cache + difficulty-sorted selection
# --------------------------------------------------------------------------------------------

def test_load_jsonl_keys_by_test_id_last_wins(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"test_id":"a","passed":false}\n'
                 '{"test_id":"b","passed":true}\n'
                 '{"test_id":"a","passed":true}\n', encoding="utf-8")
    rows = db._load_jsonl(p)
    assert set(rows) == {"a", "b"}
    assert rows["a"]["passed"] is True  # last write wins (a resumed re-run overwrites)


def test_load_jsonl_missing_file_is_empty(tmp_path):
    assert db._load_jsonl(tmp_path / "nope.jsonl") == {}


def test_load_jsonl_tolerates_blank_and_bad_lines(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('\n{"test_id":"a"}\nNOT JSON\n  \n', encoding="utf-8")
    rows = db._load_jsonl(p)
    assert set(rows) == {"a"}


def test_append_jsonl_creates_and_appends(tmp_path):
    p = tmp_path / "sub" / "b.jsonl"
    db._append_jsonl(p, {"test_id": "x"})
    db._append_jsonl(p, {"test_id": "y"})
    rows = db._load_jsonl(p)
    assert set(rows) == {"x", "y"}


def test_no_key_result_is_zero_cost():
    import os
    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        res = db.run_delta_b(sample=1)
        assert res.delta_b == 0 and res.n_tasks == 0
        assert "GEMINI_API_KEY" in res.notes
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved


# the difficulty-sort selection needs the clone (load_tasks reads the JSONL); skip if absent.
def test_select_tasks_sorts_by_difficulty_desc():
    try:
        tasks = db._select_tasks("test", sample=10, services=None)
    except FileNotFoundError:
        pytest.skip("Agent-Diff clone not present")
    if len(tasks) < 2:
        pytest.skip("not enough write tasks")
    # non-increasing (n_assertions, horizon) — the hard tail first, where over-claims live
    keys = [(t.n_assertions, t.task_horizon or 0) for t in tasks]
    assert keys == sorted(keys, reverse=True)
    assert all(t.is_write_task for t in tasks)
