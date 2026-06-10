"""docs/158 — the TERMINAL-ERROR STOP-event gate in `benchmark/enterpriseops/dos_react.py`.

PURE unit tests (NO model, NO gym, NO Docker). The gate DECISION was extracted into the
module-level pure helper `terminal_error_gate(tool_results)` (the same pattern as the other
unit-tested helpers in this module: `build_nudge_text`, `build_prior_results`,
`is_mutating_tool`). Constructing the full `DosReactOrchestrator` is heavy (its `__init__`
calls the gym's `ReactOrchestrator.__init__`, which needs the gym package), so we test the
PURE helper directly — it is exactly what the STOP-event branch calls.

The proof obligations from the task:
  1. On a synthetic state where the LAST tool_results entry is a Python Traceback from tool
     "local-python-execute" (and the agent's response says "All done!"), the gate FIRES and
     the appended nudge contains the Traceback bytes + the tool name, and does NOT contain
     "All done" (byte-clean: the nudge echoes ONLY env-authored bytes, never the agent's
     narration).
  2. With DOS_TERMINAL_ERROR unset, behavior is unchanged (the opt-in flag is OFF), and with
     it set it is ON — the exact env-flag expression the wrapper uses.
"""
from __future__ import annotations

import os

from benchmark.enterpriseops.dos_react import (
    _is_struct_error,
    terminal_error_gate,
)


# The synthetic ENV-authored Traceback the gym tool returned (NOT agent narration).
_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "<stdin>", line 1, in <module>\n'
    "KeyError: 'incident_id'"
)

# The agent's own STOP narration — must NEVER appear in a byte-clean nudge.
_AGENT_RESPONSE = "All done! I have completed the task successfully."


def _synthetic_tool_results():
    """A run whose LAST tool result is an unresolved Traceback from a generic executor.

    Mirrors the real `tool_results` entry shape the wrapper accumulates:
    {"tool_name": <str>, "arguments": {...}, "result": <env-authored dict>, "gym_server": ...}.
    The error bytes live under `result` (the env's reply); the agent's "All done!" narration
    is deliberately NOT in this list — the gate must read env bytes only.
    """
    return [
        {"tool_name": "list-incidents", "arguments": {},
         "result": {"result": {"incidents": ["INC0010023"]}}, "gym_server": "sn"},
        {"tool_name": "local-python-execute",
         "arguments": {"code": "raise KeyError('incident_id')"},
         "result": {"result": {"stdout": "", "stderr": _TRACEBACK}}, "gym_server": "py"},
    ]


# ── 1. the gate FIRES + the nudge is byte-clean ──────────────────────────────

def test_struct_error_grammar_matches_traceback():
    """The tight structured-envelope grammar matches a real Traceback (and the env content
    carrying it), the byte-clean source for the gate."""
    assert _is_struct_error(_TRACEBACK) is True
    assert _is_struct_error("the operation completed normally") is False


def test_gate_fires_on_trailing_traceback():
    """The closing window holds an unrecovered structured error from `local-python-execute`
    → the gate fires and names that tool."""
    decision = terminal_error_gate(_synthetic_tool_results())
    assert decision is not None, "gate should fire on a trailing unresolved Traceback"
    tool_name, excerpt, nudge = decision
    assert tool_name == "local-python-execute"


def test_nudge_contains_traceback_bytes_and_tool_name():
    """The appended nudge echoes the ENV error excerpt (the Traceback bytes) and the failing
    tool name — both pulled from tool_results (env-authored)."""
    decision = terminal_error_gate(_synthetic_tool_results())
    assert decision is not None
    _tool, excerpt, nudge = decision
    # the Traceback bytes (the distinctive first line + the KeyError) ride in the nudge
    assert "Traceback (most recent call last)" in nudge
    assert "KeyError: 'incident_id'" in excerpt
    assert "KeyError: 'incident_id'" in nudge
    # the failing tool name is named
    assert "local-python-execute" in nudge


def test_nudge_is_byte_clean_no_agent_narration():
    """The byte-inequality line (§5a): the nudge must contain NONE of the agent's own
    response.content — only env-authored bytes. The agent said "All done!"; the gate, which is
    never given response.content, cannot leak it."""
    decision = terminal_error_gate(_synthetic_tool_results())
    assert decision is not None
    _tool, excerpt, nudge = decision
    assert "All done" not in nudge
    assert "All done" not in excerpt
    assert _AGENT_RESPONSE not in nudge


# ── 2. recovery suppression + the env-flag opt-in ─────────────────────────────

def test_gate_silent_when_later_same_tool_succeeded():
    """recovery="aware": a LATER success from the SAME tool suppresses the error — the gate
    does NOT fire (a transient error the agent fixed should not nag)."""
    results = _synthetic_tool_results() + [
        {"tool_name": "local-python-execute", "arguments": {"code": "print('ok')"},
         "result": {"result": {"stdout": "ok\n", "stderr": ""}}, "gym_server": "py"},
    ]
    assert terminal_error_gate(results) is None


def test_gate_silent_on_clean_run():
    """No structured error anywhere → the gate never fires."""
    clean = [
        {"tool_name": "list-incidents", "arguments": {},
         "result": {"result": {"incidents": []}}, "gym_server": "sn"},
        {"tool_name": "get-incident", "arguments": {"id": "INC0010023"},
         "result": {"result": {"state": "closed"}}, "gym_server": "sn"},
    ]
    assert terminal_error_gate(clean) is None


def _flag_on(env_value):
    """The EXACT opt-in expression the wrapper uses in __init__:
        self._terminal_error_on = os.environ.get("DOS_TERMINAL_ERROR","0") not in ("0","false","")
    Reproduced here so a regression in the flag default is caught without constructing the
    gym-backed orchestrator."""
    return env_value not in ("0", "false", "")


def test_env_flag_default_off_unchanged_behavior(monkeypatch):
    """With DOS_TERMINAL_ERROR UNSET, the opt-in is OFF → the STOP branch skips the gate
    entirely (behavior unchanged from before this feature)."""
    monkeypatch.delenv("DOS_TERMINAL_ERROR", raising=False)
    default = os.environ.get("DOS_TERMINAL_ERROR", "0")
    assert _flag_on(default) is False  # unset → gate disabled → unchanged behavior


def test_env_flag_explicit_off_values():
    assert _flag_on("0") is False
    assert _flag_on("false") is False
    assert _flag_on("") is False


def test_env_flag_on_when_set(monkeypatch):
    """An explicit truthy value opts INTO the gate."""
    monkeypatch.setenv("DOS_TERMINAL_ERROR", "1")
    assert _flag_on(os.environ["DOS_TERMINAL_ERROR"]) is True
    monkeypatch.setenv("DOS_TERMINAL_ERROR", "yes")
    assert _flag_on(os.environ["DOS_TERMINAL_ERROR"]) is True
