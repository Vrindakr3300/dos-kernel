#!/usr/bin/env python3
"""Generate the GHF posttool differential parity corpus (docs/125 GHF3).

posttool is STREAM-STATEFUL: the verdict at step N depends on the prior N-1 steps.
So a corpus case is a SEQUENCE — a list of `{event, expected_stdout}` where each
expected_stdout is the EXACT bytes the Python posttool decider emits at that step,
computed by folding the events through `tool_stream.classify_stream` +
`posttool_sensor.warn_payload` (the same path cli.cmd_hook_posttool runs). The Go
`parity_posttool_test.go` replays each sequence through the native decider and
asserts byte-equality at every step.

This is the in-memory twin of the live 5-step parity check: it exercises the
ADVANCING -> REPEATING -> STALLED progression, a run broken by new bytes, and a
run broken by an absent result — all hermetic (no disk, no live hook).

Run: python gen_corpus_posttool.py > corpus_posttool.jsonl
"""
from __future__ import annotations

import json
import sys

from dos import posttool_sensor as pts
from dos.tool_stream import ToolStream, classify_stream, DEFAULT_POLICY


def _render(dialect):
    if dialect is None:
        return ""
    return json.dumps(dialect, sort_keys=True)


def _ev(tool, result=None, tool_input=None):
    e = {"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": tool,
         "tool_input": tool_input if tool_input is not None else {}}
    if result is not None:
        e["tool_response"] = result
    return e


def sequence(name: str, events: list[dict]) -> dict:
    """Fold the events through the SAME path the live hook runs, capturing the
    expected dialect at each step."""
    steps = []
    out_steps = []
    for ev in events:
        step = pts.step_from_event(ev, policy=DEFAULT_POLICY)
        # step may be None (no tool_name) — the live hook records nothing + emits
        # nothing; mirror that as an empty expected with the event still present.
        if step is None:
            out_steps.append({"event": ev, "expected_stdout": ""})
            continue
        steps.append(step)
        verdict = classify_stream(ToolStream(tuple(steps)), DEFAULT_POLICY)
        out_steps.append({"event": ev, "expected_stdout": _render(pts.warn_payload(verdict))})
    return {"name": name, "steps": out_steps}


def build() -> list[dict]:
    cases = []
    # 5 identical reads: ADVANCING, ADVANCING, REPEATING, REPEATING, STALLED.
    cases.append(sequence("five-identical-reads",
                          [_ev("Read", "SAME") for _ in range(5)]))
    # A run broken by new bytes mid-way.
    cases.append(sequence("run-broken-by-new-bytes",
                          [_ev("Read", "A"), _ev("Read", "A"), _ev("Read", "A"),
                           _ev("Read", "B"), _ev("Read", "B")]))
    # A run broken by an errored call (no result -> breaks the run).
    cases.append(sequence("run-broken-by-absent-result",
                          [_ev("Read", "A"), _ev("Read", "A"), _ev("Read", None),
                           _ev("Read", "A"), _ev("Read", "A")]))
    # Different tools never share a repeat run.
    cases.append(sequence("different-tools-never-repeat",
                          [_ev("Read", "X"), _ev("Grep", "X"), _ev("Read", "X")]))
    # A structured (dict) result repeated — digest over canonical JSON.
    cases.append(sequence("structured-result-repeat",
                          [_ev("Bash", {"stdout": "ok", "code": 0}) for _ in range(4)]))
    # An event with no tool_name records nothing + emits nothing.
    cases.append(sequence("no-tool-name",
                          [{"hook_event_name": "PostToolUse", "session_id": "s"},
                           _ev("Read", "Z")]))
    return cases


def main() -> int:
    for c in build():
        sys.stdout.write(json.dumps(c, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
