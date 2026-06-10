"""test_rewind_arm.py — verify the docs/171 rewind arm's SUBTRACT logic in isolation (no gym, no LLM).

The live A/B (live_ab.py --arms rewind) is expensive; this pins the message-truncation + byte-clean
no-good-note behavior of `DosReactOrchestrator._maybe_rewind` on a hand-built message/tool stream, so
the wiring is proven before any real Gemini spend. Pure: builds langchain message objects + a fake
verdict, calls the real method, asserts the transcript was SUBTRACTED to the last-verified anchor and
the re-entry note carries ONLY un-forged bytes.

Run: PYTHONPATH=...src:...benchmark:...gym python -m pytest benchmark/enterpriseops/test_rewind_arm.py -q
"""
from __future__ import annotations

import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, "..", "..", "src"), os.path.join(_HERE, ".."),
          os.path.join(_HERE, "enterpriseops-gym")):
    if os.path.isdir(p):
        sys.path.insert(0, p)

import pytest  # noqa: E402
from langchain_core.messages import (  # noqa: E402
    SystemMessage, HumanMessage, AIMessage, ToolMessage,
)


def _extract_symbols(*names):
    """Pull named FUNCTIONS (orchestrator methods + module-level helpers) off dos.react WITHOUT
    importing the gym base.

    The orchestrator class is defined inside `make_dos_react_orchestrator`, which imports the
    gym's ReactOrchestrator (needs `benchmark.mcp_client` — a path-shadow we avoid). But the rewind
    methods + the byte-clean helpers are self-contained: they only read attributes we set on a
    stand-in (or other extracted symbols). So we compile dos_react.py, locate each named def at ANY
    nesting depth, and exec them into ONE shared namespace — so `_maybe_rewind`/`_maybe_rewind_natural`
    can call the co-extracted `_enact_rewind`, and `natural_thrash_gate` can call the co-extracted
    `_is_struct_error`/`_result_text`/`_is_blocked_result`. (If the gym base is ever importable, the
    real bound methods are byte-identical, so this exercises production code.)
    """
    import ast
    import textwrap
    import re as _re
    src = open(os.path.join(_HERE, "dos_react.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {"json": __import__("json"), "re": _re, "Optional": __import__("typing").Optional,
          "Tuple": __import__("typing").Tuple, "List": list, "Dict": dict, "Any": object,
          "Sequence": __import__("typing").Sequence}
    # The module-level compiled regexes (`_STRUCT_ERR`, `_REFLECTED_INPUT`) are closed over by
    # the helpers; exec their assignments into the shared namespace so the helpers resolve them.
    _MODULE_CONSTS = {"_STRUCT_ERR", "_REFLECTED_INPUT"}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in _MODULE_CONSTS):
            exec(textwrap.dedent(ast.get_source_segment(src, node)), ns)
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            found[node.name] = ast.get_source_segment(src, node)
    for name in names:
        assert name in found, f"could not find {name} in dos_react.py"
        exec(textwrap.dedent(found[name]), ns)
    return ns


_REWIND_METHODS = ("_maybe_rewind", "_maybe_rewind_natural", "_enact_rewind",
                   "_post_dispatch_rewinds")
_HELPERS = ("natural_thrash_gate", "_is_struct_error", "_result_text", "_is_blocked_result",
            "_redact_reflected_input")


class _StubOrch:
    """A stand-in carrying only the state the rewind methods touch."""
    def __init__(self):
        self._rewind_on = True
        self._rewind_natural_on = True
        self._stall_rewind_on = False        # the stall path imports stall_trigger; off by default
        self._schema_refresh_on = False      # the curable-conversion re-surface (docs/205); off here
        self._block_counts = {}
        self._natural_thrash_done = set()
        self._stall_done = set()
        self._schema_refresh_done = set()
        self._rewinds_done = 0
        self._read_tools = {"find_user", "query_account"}
        self._dos_stats = {"rewinds": 0, "blocks": 0}


def _make_orch():
    # Extract the rewind methods AND the byte-clean helpers into ONE namespace, so
    # `_maybe_rewind_natural`'s `_is_verified` can resolve the module-level `_is_struct_error`
    # / `_result_text` it now reads (the gym sets outer success=True on isError results, so a
    # struct-error turn must be rejected as an anchor — see dos_react.py).
    ns = _extract_symbols(*_REWIND_METHODS, *_HELPERS)
    obj = _StubOrch()
    for m in _REWIND_METHODS:
        setattr(obj, m, types.MethodType(ns[m], obj))
    return obj


class _Verdict:
    """A minimal stand-in for the arg-provenance verdict the method reads (.unsupported)."""
    def __init__(self, unsupported):
        self.unsupported = tuple(unsupported)


def _tool_result(name, status=None, success=None, blocked=False):
    """A tool_result in the gym's REAL wrapper shape: tr["result"] = {"success": bool, "result":...}.

    The success flag lives at the OUTER level (the bug the live smoke caught: an earlier reader
    looked inside the payload and never saw it, so every anchor was UNANCHORED). `status` (when
    given) goes on the inner payload, matching a blocked_unresolved_id correction."""
    inner = {"status": status} if status else {}
    outer = {"result": inner}
    if success is not None:
        outer["success"] = success   # OUTER success flag (the gym's real shape)
    tr = {"tool_name": name, "arguments": {}, "result": outer}
    if blocked:
        tr["dos_blocked"] = True
    return tr


def test_rewind_truncates_to_last_verified_and_note_is_byte_clean():
    """A thrash (2nd block on a tool) SUBTRACTS the dead-end turns to the last-verified anchor and
    re-enters with a byte-clean note. The dead-end AI/Tool turns are gone; the note carries only the
    typed verdict token + the env's own error bytes (no generated prose)."""
    obj = _make_orch()

    # tool_results: [0 verified create_account, 1 verified create_contact, 2 BLOCKED create_case,
    #                3 BLOCKED create_case (the thrash)] — anchor must be index 1 (last verified).
    tool_results = [
        _tool_result("create_account", success=True),
        _tool_result("create_contact", success=True),
        _tool_result("create_case", status="blocked_unresolved_id", blocked=True),
    ]
    # the live message history mirrors it: System, Human, then AI/Tool pairs per tool_result.
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="task"),
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="account ok", tool_call_id="t0"),   # verified turn 0
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="contact ok", tool_call_id="t1"),   # verified turn 1  <-- anchor
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="blocked once", tool_call_id="t2"),  # dead-end (1st block, appended)
        AIMessage(content="", tool_calls=[]),                    # the re-block turn (thrash)
    ]
    conversation_flow = []
    verdict = _Verdict(["contact_id"])

    n_before = len(messages)
    rewound = obj._maybe_rewind(messages, tool_results, conversation_flow,
                                verdict, "create_case", {"contact_id": 70})

    assert rewound is True, "a thrash with a verified anchor must enact a rewind"
    # The transcript was SUBTRACTED: messages shrank, and the last message is the no-good note.
    assert len(messages) < n_before
    assert isinstance(messages[-1], HumanMessage)
    note = messages[-1].content
    # byte-clean: the note carries the typed token + the env error bytes, NEVER a generated critique.
    assert "[DOS rewind]" in note
    assert "NOT_SHIPPED" in note           # the typed VERIFY_NOT_SHIPPED token
    assert "contact_id" in note            # the structured unresolved field
    assert "never appeared" in note        # the env's own error bytes (THIRD_PARTY)
    assert "try/except" not in note        # no generated advice
    assert "you should" not in note
    # the dead-end blocked ToolMessage ("blocked once") was excised.
    surviving = "\n".join(m.content for m in messages if isinstance(m, ToolMessage))
    assert "blocked once" not in surviving
    assert "contact ok" in surviving       # the anchor turn is retained
    # the conversation_flow recorded a dos_rewind event with the dropped turns.
    assert conversation_flow and conversation_flow[-1]["type"] == "dos_rewind"
    assert conversation_flow[-1]["dropped_turns"]
    assert obj._dos_stats["rewinds"] == 0  # the CALLER increments this, not the method
    assert obj._rewinds_done == 1


def test_rewind_falls_back_when_no_verified_anchor():
    """If there is NO verified tool result to rewind to, the method REFUSES (returns False) so the
    caller falls through to the ordinary BLOCK append — never rewind to a turn the kernel didn't
    stamp (the §6 UNANCHORED floor, live)."""
    obj = _make_orch()
    # every tool_result is blocked — no last-known-good state.
    tool_results = [
        _tool_result("create_case", status="blocked_unresolved_id", blocked=True),
        _tool_result("create_case", status="blocked_unresolved_id", blocked=True),
    ]
    messages = [SystemMessage(content="sys"), HumanMessage(content="task"),
                AIMessage(content="", tool_calls=[])]
    rewound = obj._maybe_rewind(messages, tool_results, [], _Verdict(["case_id"]),
                                "create_case", {"case_id": 99})
    assert rewound is False, "no verified anchor → UNANCHORED → fall back to BLOCK append"


# ---------------------------------------------------------------------------
# docs/172 — the NATURAL fail-thrash gate + the mint-free rewind. No mint, no arg_provenance:
# the trigger is the agent's OWN repeated env error, the note is the gym's OWN error bytes.
# ---------------------------------------------------------------------------
def _err_result(name, error_text):
    """A tool_result whose ENV payload is a STRUCTURED error envelope (`_is_struct_error`-matched).

    Mirrors the gym's REAL natural-error shape (measured from live_results_natural): the MCP
    content carries `"isError": true` (the tight grammar's hook) with the validation message as
    a text node — `{"result": {"content": [{"type":"text","text":"❌ <error_text>"}], "isError": true}}`.
    Note the gym sets outer `success: true` even on an isError result, so the gate must read the
    `isError` envelope, NOT the success flag. NOT a dos_blocked synthetic (that is the mint path)."""
    return {"tool_name": name, "arguments": {},
            "result": {"success": True, "error": None,
                       "result": {"content": [{"type": "text", "text": error_text}],
                                  "isError": True}}}


def test_natural_thrash_gate_fires_on_repeated_env_error():
    """natural_thrash_gate fires iff the SAME tool produced a structured env error >=2× AND its
    LATEST result is still an error (in the hole now). A single failure, or a failure later
    recovered by a success, does NOT fire — that is convergence, not thrash."""
    ns = _extract_symbols(*_HELPERS)
    gate = ns["natural_thrash_gate"]
    # one failure → no fire (a single dead-end is not yet a thrash)
    one = [_err_result("update_case", "state conflict 409")]
    assert gate(one, "update_case") is None
    # two failures, latest still an error → FIRE, excerpt is the env's own latest error bytes
    two = [_err_result("update_case", "state conflict 409"),
           _tool_result("get_user", success=True),
           _err_result("update_case", "state conflict 409 again")]
    res = gate(two, "update_case")
    assert res is not None, "same tool failing 2× un-recovered must fire (natural THRASHING)"
    n_fail, excerpt = res
    assert n_fail == 2
    assert "state conflict" in excerpt          # the env's own error bytes (THIRD_PARTY)
    # two failures but a LATER success on the same tool → recovered → no fire
    recovered = [_err_result("update_case", "x"), _err_result("update_case", "y"),
                 _tool_result("update_case", success=True)]
    assert gate(recovered, "update_case") is None, "a later same-tool success recovers the thrash"


def test_natural_rewind_subtracts_and_note_is_env_bytes_only():
    """A natural fail-thrash SUBTRACTS to the last-verified anchor and re-enters with a note that
    carries ONLY the kernel's typed token + the gym's OWN error bytes — never a generated critique.
    The mint-free sibling of the §6 byte-clean contract."""
    obj = _make_orch()
    # [0 verified find_incident, 1 verified get_user, 2 FAILED update_case, 3 FAILED update_case]
    tool_results = [
        _tool_result("find_incident", success=True),
        _tool_result("get_user", success=True),
        _err_result("update_case", "state conflict 409"),
        _err_result("update_case", "state conflict 409 again"),
    ]
    messages = [
        SystemMessage(content="sys"), HumanMessage(content="task"),
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="incident ok", tool_call_id="t0"),   # verified turn 0
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="user ok", tool_call_id="t1"),       # verified turn 1  <-- anchor
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="err 409", tool_call_id="t2"),       # dead-end (1st fail)
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="err 409 again", tool_call_id="t3"),  # dead-end (2nd fail = thrash)
    ]
    conversation_flow = []
    n_before = len(messages)
    rewound = obj._maybe_rewind_natural(
        messages, tool_results, conversation_flow, "update_case", 2,
        "Error: state conflict 409 again",
    )
    assert rewound is True, "a natural 2× fail-thrash with a verified anchor must rewind"
    assert len(messages) < n_before
    note = messages[-1].content
    assert "[DOS rewind]" in note
    assert "NOT_SHIPPED" in note                    # the typed token (kernel-computed)
    assert "update_case=failed-2x" in note          # the structured natural-thrash field
    assert "state conflict" in note                 # the gym's OWN error bytes (THIRD_PARTY)
    assert "you should" not in note and "try/except" not in note  # no generated advice
    surviving = "\n".join(m.content for m in messages if isinstance(m, ToolMessage))
    assert "err 409 again" not in surviving         # the dead-end turns excised
    assert "user ok" in surviving                   # the anchor retained
    assert conversation_flow[-1]["type"] == "dos_rewind"
    assert conversation_flow[-1]["kind"] == "natural"
    assert obj._rewinds_done == 1


def test_natural_rewind_falls_back_when_no_verified_anchor():
    """No verified state to rewind to → UNANCHORED → returns False (the caller leaves the failed
    turn in place). The §6 floor holds on the natural axis too — never rewind to an un-stamped turn."""
    obj = _make_orch()
    tool_results = [
        _err_result("update_case", "x"), _err_result("update_case", "y"),
    ]
    messages = [SystemMessage(content="sys"), HumanMessage(content="task"),
                AIMessage(content="", tool_calls=[])]
    rewound = obj._maybe_rewind_natural(messages, tool_results, [], "update_case", 2, "Error: y")
    assert rewound is False, "no verified anchor → UNANCHORED → no truncation"


# ---------------------------------------------------------------------------
# docs/172 — the verify-wf MUST-FIX coverage: (1) the reflected-input echo redaction (the
# gym mirrors the agent's OWN argument value into the error envelope's `input` field — those
# agent-authored bytes must NOT ride a THIRD_PARTY note), and (2) the mint-path anchor guard
# (the original _maybe_rewind must also reject struct-error turns as anchors).
# ---------------------------------------------------------------------------
def test_reflected_input_echo_is_redacted_from_note():
    """An env error whose envelope echoes the agent's OWN submitted value (the gym's `input`
    field reflection) must have that value REDACTED before it reaches the no-good note — the
    note carries the gym's validation MESSAGE, never the agent's echoed argument bytes."""
    ns = _extract_symbols(*_HELPERS, "_redact_reflected_input")
    redact = ns["_redact_reflected_input"]
    # the real corpus shape: API Error with a reflected agent body string in 'input'
    agent_value = "This kind of issues are tackled by Assignment Group X, Steps to resolve: do Y"
    env_err = ("API Error [create_knowledge]: [{'type': 'string_too_long', 'loc': ['body', 'body'], "
               f"'msg': 'String should have at most 100 characters', 'input': '{agent_value}'}}]")
    red = redact(env_err)
    assert agent_value not in red, "the agent's echoed argument value must be redacted"
    assert "<redacted: agent-authored>" in red
    assert "string_too_long" in red and "String should have at most" in red  # the gym's msg survives

    # and end-to-end: the redaction is applied where the note is built (the gym gate)
    gate = ns["natural_thrash_gate"]
    err_tr = {"tool_name": "create_knowledge", "arguments": {},
              "result": {"success": True, "error": None,
                         "result": {"content": [{"type": "text", "text": (
                             '{"isError": true, "detail": [{"type":"string_too_long",'
                             f'"input":"{agent_value}"}}]}}')}], "isError": True}}}
    res = gate([err_tr, err_tr], "create_knowledge")
    assert res is not None
    _, excerpt = res
    assert agent_value not in excerpt, "the gate's excerpt must not carry the agent's echoed value"


def test_post_dispatch_rewinds_fires_on_natural_thrash():
    """The docs/172 §0.6 firing-bug regression guard. `_post_dispatch_rewinds` is the helper called
    from BOTH the normal branch AND the CONSULT=0 branch (the bug: the natural/stall gate was dead
    code for the CONSULT=0 arms that use it). This pins that the helper fires the natural SUBTRACT on
    a natural fail-thrash and returns True (so the caller breaks) — independent of any consult state."""
    obj = _make_orch()
    obj._post_dispatch_rewinds = types.MethodType(
        _extract_symbols(*_REWIND_METHODS, *_HELPERS)["_post_dispatch_rewinds"], obj)
    # [0 verified, 1 verified anchor, 2 FAILED update_case, 3 FAILED update_case (thrash)]
    tool_results = [
        _tool_result("find_incident", success=True),
        _tool_result("get_user", success=True),
        _err_result("update_case", "state conflict 409"),
        _err_result("update_case", "state conflict 409 again"),
    ]
    messages = [
        SystemMessage(content="sys"), HumanMessage(content="task"),
        AIMessage(content="", tool_calls=[]), ToolMessage(content="inc ok", tool_call_id="t0"),
        AIMessage(content="", tool_calls=[]), ToolMessage(content="user ok", tool_call_id="t1"),
        AIMessage(content="", tool_calls=[]), ToolMessage(content="err", tool_call_id="t2"),
        AIMessage(content="", tool_calls=[]), ToolMessage(content="err again", tool_call_id="t3"),
    ]
    conversation_flow = []
    fired = obj._post_dispatch_rewinds(messages, tool_results, conversation_flow, "update_case")
    assert fired is True, "the post-dispatch helper must fire the natural SUBTRACT on a thrash"
    assert obj._dos_stats["rewinds"] == 1
    assert conversation_flow[-1]["type"] == "dos_rewind"
    assert "update_case" in obj._natural_thrash_done  # one-shot per tool


def test_mint_path_rejects_struct_error_anchor():
    """The MINT-path _maybe_rewind's _is_verified must ALSO reject a struct-error turn as an
    anchor (the verify-wf must-fix #2). A real env error interleaved before the 2nd block must
    NOT become the last-known-good anchor (the gym sets outer success=True even on isError)."""
    obj = _make_orch()
    # [0 verified create_account, 1 NATURAL env error (success:True+isError), 2 BLOCKED, 3 BLOCKED]
    tool_results = [
        _tool_result("create_account", success=True),                 # turn 0: the ONLY good anchor
        _err_result("update_case", "423 record locked conflict"),     # turn 1: env error (success:True!)
        _tool_result("create_case", status="blocked_unresolved_id", blocked=True),
    ]
    messages = [
        SystemMessage(content="sys"), HumanMessage(content="task"),
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="account ok", tool_call_id="t0"),   # verified turn 0  <-- the true anchor
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="err 423", tool_call_id="t1"),      # the struct-error turn (NOT an anchor)
        AIMessage(content="", tool_calls=[]),
        ToolMessage(content="blocked", tool_call_id="t2"),
        AIMessage(content="", tool_calls=[]),
    ]
    conversation_flow = []
    rewound = obj._maybe_rewind(messages, tool_results, conversation_flow,
                               _Verdict(["case_id"]), "create_case", {"case_id": 99})
    assert rewound is True
    # the anchor must be turn 0 (create_account), NOT turn 1 (the env error) — verify the
    # error turn was dropped and the account turn retained.
    surviving = "\n".join(m.content for m in messages if isinstance(m, ToolMessage))
    assert "account ok" in surviving, "the true verified anchor (turn 0) must be retained"
    assert "err 423" not in surviving, "the struct-error turn must NOT be the anchor (must-fix #2)"
    assert conversation_flow[-1]["rewind_to_turn"] == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
