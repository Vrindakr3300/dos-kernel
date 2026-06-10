"""test_restart_arm.py — verify the docs/176 §6 RESTART arm in isolation (no gym, no LLM).

The live A/B (restart vs rewind vs block) is expensive; this pins the window-discard + the
optional byte-clean seed + the token ledger of the restart arm on a hand-built message stream,
so the wiring is proven before any real Gemini spend. Two layers, the test_rewind_arm pattern:

  1. The PURE mechanism functions (`build_fresh_window`, `restart_decision`,
     `restart_ledger_delta`, `estimate_window_tokens`) import WITHOUT the gym — exercised
     directly.
  2. `_maybe_restart` (a method defined inside the factory's class) is AST-extracted and exec'd
     into a shared namespace, then driven against a stand-in orchestrator carrying only the
     state it touches — so the real method body is exercised without importing the gym base.

Run: PYTHONPATH=...src:...benchmark:...gym python -m pytest benchmark/enterpriseops/test_restart_arm.py -q
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


# ---------------------------------------------------------------------------
# A minimal langchain-free message stand-in (the pure helpers + the extracted
# method only read `.content`, so a tiny object suffices — no langchain needed).
# ---------------------------------------------------------------------------
class _Msg:
    def __init__(self, content):
        self.content = content

    def __repr__(self):  # nicer assert output
        return f"_Msg({self.content!r})"


def _window(n_dead=4):
    """[System, Human, <n_dead dead-branch turns>] — a thrashed window."""
    msgs = [_Msg("SYSTEM PROMPT"), _Msg("USER TASK: do the thing")]
    for i in range(n_dead):
        msgs.append(_Msg(f"dead-branch turn {i} " * 10))
    return msgs


# ===========================================================================
# Layer 1 — the PURE mechanism (imports without the gym).
# ===========================================================================
from restart_arm import (  # noqa: E402
    build_fresh_window,
    estimate_window_tokens,
    restart_decision,
    restart_ledger_delta,
)


def test_fresh_window_unseeded_keeps_only_system_and_human():
    msgs = _window(n_dead=5)
    fresh = build_fresh_window(msgs[0], msgs[1])
    assert fresh == [msgs[0], msgs[1]]
    # the lesson is LOST (no note) and the warm prefix is LOST (no dead turns) — the naive restart
    assert len(fresh) == 2


def test_fresh_window_seeded_appends_the_note_only():
    msgs = _window(n_dead=5)
    fresh = build_fresh_window(
        msgs[0], msgs[1],
        no_good_note_text="[DOS restart] VERIFY_NOT_SHIPPED: id=never-appeared",
        human_factory=_Msg,
    )
    assert len(fresh) == 3
    assert fresh[0] is msgs[0] and fresh[1] is msgs[1]
    # the lesson is KEPT (the note) but the warm prefix is still LOST (no dead turns)
    assert "never-appeared" in fresh[2].content


def test_fresh_window_seed_without_factory_raises():
    msgs = _window()
    with pytest.raises(ValueError):
        build_fresh_window(msgs[0], msgs[1], no_good_note_text="x", human_factory=None)


def test_restart_decision_fires_only_on_thrash_once_per_tool():
    done: set = set()
    # 1st block — not a thrash yet
    assert restart_decision(restart_on=True, block_count=1,
                            already_restarted_tools=done, tool_name="t") is False
    # 2nd block — THRASHING → fire
    assert restart_decision(restart_on=True, block_count=2,
                            already_restarted_tools=done, tool_name="t") is True
    # after restarting t, a 3rd block on t does NOT re-fire (one-shot cap)
    done.add("t")
    assert restart_decision(restart_on=True, block_count=3,
                            already_restarted_tools=done, tool_name="t") is False
    # a DIFFERENT tool still fires
    assert restart_decision(restart_on=True, block_count=2,
                            already_restarted_tools=done, tool_name="u") is True


def test_restart_decision_off_never_fires():
    assert restart_decision(restart_on=False, block_count=9,
                            already_restarted_tools=set(), tool_name="t") is False


def test_ledger_delta_counts_discarded_turns_and_tokens():
    msgs = _window(n_dead=4)
    discarded = msgs[2:]              # what a restart throws away (past System+Human)
    delta = restart_ledger_delta(discarded)
    assert delta["restart_events"] == 1
    assert delta["turns_discarded"] == 4
    # the re-paid prefix tokens are > 0 and equal the estimate of the discarded turns
    assert delta["prefix_tokens_repaid"] == estimate_window_tokens(discarded)
    assert delta["prefix_tokens_repaid"] > 0


def test_token_estimate_monotone_in_content():
    small = [_Msg("hi")]
    big = [_Msg("x" * 4000)]
    assert estimate_window_tokens(big) > estimate_window_tokens(small)


# ===========================================================================
# Layer 2 — the AST-extracted `_maybe_restart` method, driven on a stand-in.
# (The test_rewind_arm pattern: pull the method body off the factory's class
# WITHOUT importing the gym base.)
# ===========================================================================
def _extract_maybe_restart():
    """Locate `_maybe_restart` (nested inside make_restart_orchestrator's class) and exec it
    into a namespace wired with the helpers + imports it closes over."""
    import ast
    import textwrap

    src = open(os.path.join(_HERE, "restart_arm.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {
        "os": os, "json": __import__("json"),
        "Optional": __import__("typing").Optional,
        "Dict": dict, "List": list, "Any": object,
        "restart_decision": restart_decision,
        "restart_ledger_delta": restart_ledger_delta,
        "build_fresh_window": build_fresh_window,
        # the langchain HumanMessage the method builds via a lambda → the stand-in
        "HumanMessage": _Msg,
    }
    found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_maybe_restart":
            found = ast.get_source_segment(src, node)
            break
    assert found is not None, "could not find _maybe_restart in restart_arm.py"
    exec(textwrap.dedent(found), ns)
    return ns["_maybe_restart"]


class _StubVerdict:
    def __init__(self, unsupported):
        self.unsupported = unsupported


class _StubOrch:
    """Carries only the state `_maybe_restart` touches."""
    def __init__(self, *, restart_on=True, seed=False):
        self._restart_on = restart_on
        self._restart_seed = seed
        self._restarted_tools = set()
        self._restarts_done = 0
        self._restart_ledger = {
            "restart_events": 0, "turns_discarded": 0, "prefix_tokens_repaid": 0,
        }
        self._block_counts = {}

    def _restart_env_excerpt(self, tool_results, tool_name, unresolved):
        """Stand-in for the real method: with no tool_results the structural fallback fires,
        naming the WALL (id never appeared) but never a corrective directive — the provenance fix."""
        for tr in reversed(tool_results or []):
            if str(tr.get("tool_name")) == tool_name:
                import json as _j
                txt = _j.dumps(tr.get("result", tr), default=str)
                if "blocked_unresolved_id" in txt or "isError" in txt or "Error" in txt:
                    return txt[:400]
        return (f"`{tool_name}` references id(s) ({unresolved}) that never appeared in any "
                f"prior tool result.")


_maybe_restart = _extract_maybe_restart()


def test_maybe_restart_unseeded_discards_to_system_human_and_ledgers():
    orch = _StubOrch(restart_on=True, seed=False)
    orch._block_counts["create_x"] = 2          # THRASHING
    messages = _window(n_dead=4)
    flow = []
    fired = _maybe_restart(
        orch, messages, [], flow,
        _StubVerdict(["acct_999"]), "create_x", {"acct_id": "acct_999"},
    )
    assert fired is True
    # window reset to [System, Human] in place (no note when unseeded)
    assert len(messages) == 2
    assert messages[0].content == "SYSTEM PROMPT"
    assert messages[1].content.startswith("USER TASK")
    # ledger recorded the discard of the 4 dead turns + the re-paid tokens
    assert orch._restarts_done == 1
    assert orch._restart_ledger["restart_events"] == 1
    assert orch._restart_ledger["turns_discarded"] == 4
    assert orch._restart_ledger["prefix_tokens_repaid"] > 0
    assert "create_x" in orch._restarted_tools
    assert flow and flow[-1]["type"] == "dos_restart" and flow[-1]["seeded"] is False


def test_maybe_restart_seeded_carries_the_byte_clean_note():
    orch = _StubOrch(restart_on=True, seed=True)
    orch._block_counts["create_x"] = 2
    messages = _window(n_dead=3)
    flow = []
    fired = _maybe_restart(
        orch, messages, [], flow,
        _StubVerdict(["acct_999"]), "create_x", {"acct_id": "acct_999"},
    )
    assert fired is True
    # [System, Human, no-good note] — the lesson kept, the warm prefix dropped
    assert len(messages) == 3
    note = messages[2].content
    assert note.startswith("[DOS restart]")
    # byte-clean: it names the unresolved id fact, NOT a generated fix / advice
    assert "acct_999" in note
    assert "never-appeared" in note or "never appeared" in note.lower()
    assert flow[-1]["seeded"] is True


def test_seeded_note_carries_no_fabricated_directive():
    """The provenance fix (the audit): the seed names the WALL (id never appeared) but NEVER an
    authored corrective ACTION. The old note fabricated 'Look the id up with a read/query tool,
    then retry' and self-tagged it THIRD_PARTY — wrapper-authored advice wearing an env tag. The
    fixed note must not contain that directive (no 'retry', no 'look ... up' instruction)."""
    orch = _StubOrch(restart_on=True, seed=True)
    orch._block_counts["create_x"] = 2
    messages = _window(n_dead=3)
    flow = []
    _maybe_restart(orch, messages, [], flow,
                   _StubVerdict(["acct_999"]), "create_x", {})
    note = messages[2].content.lower()
    assert "then retry" not in note
    assert "look the id up" not in note
    assert "read/query tool" not in note


def test_maybe_restart_not_thrash_does_not_fire():
    orch = _StubOrch(restart_on=True, seed=False)
    orch._block_counts["create_x"] = 1          # first block, not a thrash
    messages = _window(n_dead=4)
    fired = _maybe_restart(
        orch, messages, [], [],
        _StubVerdict(["acct_999"]), "create_x", {},
    )
    assert fired is False
    assert len(messages) == 6                    # window untouched
    assert orch._restarts_done == 0


def test_maybe_restart_one_shot_per_tool():
    orch = _StubOrch(restart_on=True, seed=False)
    orch._block_counts["create_x"] = 2
    messages = _window(n_dead=4)
    assert _maybe_restart(orch, messages, [], [],
                          _StubVerdict(["a"]), "create_x", {}) is True
    # a later thrash on the SAME tool does not re-restart (no cold-start livelock)
    orch._block_counts["create_x"] = 3
    messages2 = _window(n_dead=5)
    assert _maybe_restart(orch, messages2, [], [],
                          _StubVerdict(["a"]), "create_x", {}) is False
    assert orch._restarts_done == 1


def test_byte_clean_note_uses_real_kernel_builder():
    """The seeded note must come through dos.rewind.build_no_good_note — the SAME un-forgeable
    path the rewind arm uses — so a seeded restart can carry the lesson without authoring a fix.
    Proven by: the note renders the kernel's VERIFY_NOT_SHIPPED token and carries NO free-form
    advice slot (the docs/164 §6 lock)."""
    from dos.rewind import build_no_good_note, EnvExcerpt
    from dos.log_source import Accountability
    from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED

    note = build_no_good_note(
        (VerdictToken(KIND_VERIFY_NOT_SHIPPED, {"sha": "acct_999=never-appeared"}),),
        EnvExcerpt("references id(s) that never appeared", Accountability.THIRD_PARTY),
    )
    lines = note.render_lines()
    assert any("acct_999" in ln for ln in lines)
    # the THIRD_PARTY excerpt attaches (non-AGENT_AUTHORED); an AGENT_AUTHORED one would not
    agent_note = build_no_good_note(
        (VerdictToken(KIND_VERIFY_NOT_SHIPPED, {"sha": "x=never-appeared"}),),
        EnvExcerpt("a generated critique", Accountability.AGENT_AUTHORED),
    )
    assert all("generated critique" not in ln for ln in agent_note.render_lines())
