"""test_stall_trigger.py — the DOMAIN-FREE prune trigger classify_stream→STALLED (docs/176 §7 #1).

Pins the stall trigger's behavior with no gym, no LLM: it fires the SUBTRACT-eligible signal
ONLY on STALLED (the kernel verdict over byte-identical env-result triples), never on
REPEATING (a legitimate eventual-consistency poll must not be pruned — the safe-signal
discipline) or ADVANCING. The trigger reuses dos.posttool_sensor.step_from_event, so these
tests also confirm the IN-FLIGHT loop signal is byte-identical to the live PostToolUse hook's.

Run: PYTHONPATH=...src python -m pytest benchmark/enterpriseops/test_stall_trigger.py -q
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, "..", "..", "src"), os.path.join(_HERE, ".."),
          os.path.join(_HERE, "enterpriseops-gym")):
    if os.path.isdir(p):
        sys.path.insert(0, p)

import pytest  # noqa: E402

from stall_trigger import (  # noqa: E402
    stall_thrash_gate,
    stream_from_tool_results,
    _event_from_tool_result,
    _latest_result_excerpt,
)
from dos.tool_stream import StreamPolicy, StreamState, classify_stream  # noqa: E402


def _tr(tool, args, result):
    """A tool_results entry in the gym's shape: {tool_name, arguments, result, gym_server}."""
    return {"tool_name": tool, "arguments": args, "result": result, "gym_server": None}


def _identical(tool="read_row", n=5, payload=None):
    """n byte-identical results for one tool (a true spin)."""
    res = {"success": True, "result": payload if payload is not None else {"rows": []}}
    return [_tr(tool, {"id": "A"}, res) for _ in range(n)]


# ==========================================================================
# The three-state gate: STALLED fires, REPEATING + ADVANCING do not.
# ==========================================================================
def test_stalled_fires_the_prune_signal():
    """5 byte-identical env results (>= stall_n default 5) → STALLED → the gate fires with the
    kernel's measured run length."""
    trs = _identical(n=5)
    gate = stall_thrash_gate(trs, "read_row")
    assert gate is not None
    repeat_run, excerpt, anchor_idx = gate
    assert repeat_run == 5
    assert isinstance(excerpt, str) and excerpt
    assert anchor_idx == -1  # the stall starts at turn 0 (no verified prefix in this run)
    # confirm it really is the kernel STALLED verdict driving it
    assert classify_stream(stream_from_tool_results(trs)).state is StreamState.STALLED


def test_repeating_does_not_fire_the_prune_signal():
    """3-4 byte-identical results → REPEATING (>= repeat_n 3, < stall_n 5) → the gate returns
    None. REPEATING is WARN-only: a legitimate eventual-consistency poll must NOT be pruned."""
    for n in (3, 4):
        trs = _identical(n=n)
        assert classify_stream(stream_from_tool_results(trs)).state is StreamState.REPEATING
        assert stall_thrash_gate(trs, "read_row") is None  # the safe-signal discipline


def test_advancing_does_not_fire():
    """5 DIFFERENT env results → ADVANCING → None (new bytes are entering the loop)."""
    trs = [_tr("read_row", {"id": "A"}, {"success": True, "result": {"n": i}}) for i in range(5)]
    assert classify_stream(stream_from_tool_results(trs)).state is StreamState.ADVANCING
    assert stall_thrash_gate(trs, "read_row") is None


def test_too_short_does_not_fire():
    """Fewer than repeat_n steps → ADVANCING (too young to judge) → None."""
    assert stall_thrash_gate(_identical(n=2), "read_row") is None
    assert stall_thrash_gate([], "read_row") is None


# ==========================================================================
# The in-the-hole-now guard: the stall must be on the queried tool.
# ==========================================================================
def test_does_not_fire_for_a_different_tool():
    """A stall on read_row must not fire when the caller asks about another tool (the gate is
    for the tool in the hole right now — the natural_thrash_gate posture)."""
    trs = _identical(tool="read_row", n=6)
    assert stall_thrash_gate(trs, "create_incident") is None


def test_fires_for_the_stalling_tool_amid_other_calls():
    """The trailing run is what matters: a stall on the LATEST tool fires even if other tools
    ran earlier (the run ends at the latest step)."""
    trs = [_tr("list_users", {"q": "x"}, {"success": True, "result": {"u": 1}})]
    trs += _identical(tool="read_row", n=5)
    gate = stall_thrash_gate(trs, "read_row")
    assert gate is not None and gate[0] == 5
    assert gate[2] == 0  # anchor = the list_users prefix (index 0), the turn before the stall


def test_tool_name_match_is_casefold():
    """The repeating step's tool_name is casefolded inside the verdict; the guard compares
    casefolded so a case-different query still matches its own stall."""
    trs = _identical(tool="Read_Row", n=5)
    assert stall_thrash_gate(trs, "read_row") is not None


# ==========================================================================
# Custom policy: stall_n is tunable (the StreamPolicy seam).
# ==========================================================================
def test_custom_stall_n_lowers_the_bar():
    """A host that declares stall_n=3 fires at 3 identical results (the [tool_stream] config
    seam flows through)."""
    pol = StreamPolicy(repeat_n=2, stall_n=3)
    trs = _identical(n=3)
    assert classify_stream(stream_from_tool_results(trs, pol), pol).state is StreamState.STALLED
    assert stall_thrash_gate(trs, "read_row", pol) is not None
    # and with the DEFAULT policy the same 3 results are only REPEATING → None
    assert stall_thrash_gate(trs, "read_row") is None


# ==========================================================================
# Byte-cleanliness: the digest is over ENV-authored result bytes, and the
# in-flight mapping is byte-identical to the live hook's step_from_event.
# ==========================================================================
def test_same_signal_as_the_posttool_hook():
    """The in-flight trigger reuses step_from_event, so a tool_result maps to the SAME digests
    the live PostToolUse hook computes for the equivalent event (the 'same signal, not a
    look-alike' discipline)."""
    from dos.posttool_sensor import step_from_event

    tr = _tr("read_row", {"id": "A"}, {"success": True, "result": {"rows": []}})
    # the trigger's mapping
    via_trigger = step_from_event(_event_from_tool_result(tr))
    # the hook's own event for the same call/result
    hook_event = {"tool_name": "read_row", "tool_input": {"id": "A"},
                  "tool_response": {"success": True, "result": {"rows": []}}}
    via_hook = step_from_event(hook_event)
    assert via_trigger.args_digest == via_hook.args_digest
    assert via_trigger.result_digest == via_hook.result_digest


def test_different_env_bytes_break_the_run_agent_cannot_forge():
    """The break is decided by ENV-authored result bytes, not the agent's call. Same args, one
    different env result mid-run → the run does not reach stall_n (the byte-clean break the
    agent cannot forge — docs/138 invariant)."""
    trs = _identical(n=4)
    trs.append(_tr("read_row", {"id": "A"}, {"success": True, "result": {"rows": [1]}}))  # break
    trs += _identical(n=2)  # only 2 identical after the break → not STALLED
    assert stall_thrash_gate(trs, "read_row") is None


def test_excerpt_is_env_authored_bytes():
    """The no-good-note excerpt carries the env's own latest result bytes (THIRD_PARTY), never
    an agent-authored fix."""
    trs = _identical(n=5, payload={"error": "row not found", "code": 404})
    gate = stall_thrash_gate(trs, "read_row")
    assert gate is not None
    _, excerpt, _ = gate
    assert "404" in excerpt or "row not found" in excerpt  # the env's own bytes


def test_excerpt_fallback_when_no_textual_result():
    """A stall with an un-stringifiable / empty result still yields a descriptive
    env-behavior line (a statement about the env, not an agent fix)."""
    text = _latest_result_excerpt([], "read_row")
    assert "read_row" in text and "byte-identical" in text
