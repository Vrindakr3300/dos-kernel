"""The LIVE WARN arm: a DOS `tool_stream` re-surface, bound to the Toolathlon agent runtime.

This is the in-flight sibling of `live_adapter.py`. `live_adapter` reads a COMPLETED on-disk
`traj_log.json` and scores it POST-HOC (DETECT after the run is over). This module wires the SAME
pure DOS verdict (`tool_stream.classify_stream`, the docs/145 stall verdict) into the agent loop
WHILE it runs, so on a REPEATING/STALLED loop it can re-surface the env value the agent already
holds — the turn-preserving WARN (docs/144), the first DOS lever on this benchmark that can move a
doomed re-read loop UP to a finished task on the same budget.

WHY IT IS A SEPARATE MODULE IN THE DOS REPO (not an edit to Toolathlon)
=======================================================================
The A/B arm is selected by IMPORT, gated by an env flag:
  * OBSERVE arm — do NOT import this (or import it with `DOS_WARN` unset): the SDK runs untouched.
  * WARN    arm — import it and call `apply_warn_patch()` (or set `DOS_WARN=1`): the patch installs.
The SAME code runs both arms; the only delta is the flag. Nothing under `Toolathlon` is
edited — this is an importable monkey-patch the harness opts into, exactly the mechanism
`custom_run_impl.py` already uses (`RunImpl.process_model_response = ...`).

THE SEAM (verified 2026-06-05 against openai-agents==0.0.15, openai==1.76.0)
===========================================================================
`RunImpl.execute_tools_and_side_effects` (agents/_run_impl.py:188) is the ONE method that receives
the FULL prior turn history as `RunItem` objects: `pre_step_items` ("everything since the original
input, before the current step") + the `new_step_items` it assembles this step (the just-executed
tool calls + results). `my_execute_function_tool_calls` is the WRONG seam — it only sees the calls
ABOUT to dispatch this step (`tool_runs`), no cross-step history, so it cannot build a ToolStream.

THE BYTE-FAITHFULNESS CONTRACT (so live == offline replay — the parity test is the gate)
========================================================================================
The whole point is that the LIVE verdict is byte-identical to the OFFLINE replay verdict on the
same loop. We achieve that by REUSING the offline reader unchanged: we convert the SDK `RunItem`
history into the EXACT chat-dict shape `trajectory.to_tool_stream` already walks, build a
`Trajectory`, and call `to_tool_stream(normalize=True)` + `classify_stream`. The shared normalizer
(`normalize_result_bytes` / `_normalize_args`) is never re-implemented here — `tests/
test_toolathlon_replay.py::test_live_warn_adapter_parity_*` PROVES the two paths agree.

THE §5a PROVENANCE LINE, PRESERVED
==================================
`result_digest` is ENV-authored — the MCP gateway produced the `ToolCallOutputItem.output` bytes,
exactly as the dataset's `role:'tool'` content was env-authored. `tool_stream` asks only "did the
env return the same bytes N times?" — a fact about env-authored output, never an "is the agent
succeeding?" satisfaction predicate. The WARN re-surfaces the agent's OWN already-held env value;
it authors no directive and no step (the docs/143 −9 pp derailment channel is unreachable by
construction — we only PREPEND a message, never substitute a tool call or skip a dispatch).

ADVISORY + STRUCTURAL SAFETY (a patch bug must never break the run)
==================================================================
The entire injection is wrapped in try/except → fail-toward-normal-dispatch. We ONLY ever PREPEND a
synthetic user message to the next turn's items; we NEVER touch `processed_response.functions`,
never skip/substitute a tool call, and only act at a TURN BOUNDARY (after results are assembled,
before the next model call) — never between a tool_call and its result. A raise inside the verdict
or the adapter degrades to the un-patched SDK behavior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dos.tool_stream import StreamPolicy, StreamState, classify_stream

from .trajectory import Trajectory, to_tool_stream

# The live WARN policy: the docs/145 generic floor (repeat_n=3, stall_n=5). A live consumer acts at
# REPEATING (re-surface the held value); STALLED is the harder rung (still a WARN by default here).
LIVE_STREAM_POLICY = StreamPolicy(repeat_n=3, stall_n=5)


# ---------------------------------------------------------------------------
# The PURE I/O-at-edge adapter: SDK RunItem history -> the chat-dict shape the
# offline reader (trajectory.to_tool_stream / to_stop_evidence) already walks.
# ---------------------------------------------------------------------------
def _sdk_items_to_chat_messages(history_items: list) -> list[dict]:
    """SDK `RunItem` history (Responses API) -> the chat-dict list `to_tool_stream`/`to_stop_evidence`
    read. PURE; the I/O-at-edge reader. Preserves order. Each function call becomes its OWN assistant
    message carrying exactly one tool_call, immediately followed by its tool-result message — so
    `_tool_msg_name`'s 'assistant precedes its result' assumption holds and call_id linkage is 1:1.

    The shape contract (verified against openai-agents==0.0.15):
      * a ToolCallItem (type=='tool_call_item') whose raw_item is a ResponseFunctionToolCall carries
        `.call_id` (the linkage key — NOT `.id`), `.name`, `.arguments` (a JSON string).
      * a ToolCallOutputItem (type=='tool_call_output_item') carries `.output` (the raw result) and a
        `.raw_item` dict {"call_id","output","type":"function_call_output"}.
      * a MessageOutputItem (type=='message_output_item') carries assistant text in
        `.raw_item.content[*].text` where `.type=='output_text'` (for the dangling terminal-narration).
    """
    out: list[dict] = []
    for it in history_items:
        t = getattr(it, "type", None)

        # (A) a function tool CALL — ToolCallItem whose raw_item is a ResponseFunctionToolCall.
        if t == "tool_call_item":
            raw = getattr(it, "raw_item", None)
            # only function calls have .name/.arguments/.call_id; skip computer/web/file-search calls
            if getattr(raw, "type", None) != "function_call":
                continue
            out.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": raw.call_id,  # NOT raw.id — call_id is the linkage key
                            "type": "function",
                            "function": {
                                "name": raw.name,
                                "arguments": raw.arguments or "",
                            },
                        }
                    ],
                }
            )

        # (B) a tool RESULT — ToolCallOutputItem; raw_item is a FunctionCallOutput dict.
        elif t == "tool_call_output_item":
            raw = getattr(it, "raw_item", None)
            if isinstance(raw, dict):
                call_id = raw.get("call_id")
                # computer_call_output etc. — not part of the function tool stream
                if raw.get("type") != "function_call_output":
                    continue
            else:
                call_id = getattr(raw, "call_id", None)
            if call_id is None:
                continue
            # prefer .output (the raw result); coerce to str to match str(m["content"]) the offline
            # walker applies (trajectory.py:289). raw_item["output"] is already str(result).
            content = getattr(it, "output", None)
            if content is None and isinstance(raw, dict):
                content = raw.get("output", "")
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": content if isinstance(content, str) else str(content),
                }
            )

        # (C) assistant TEXT (for the dangling_intent terminal narration) — cheap to include.
        elif t == "message_output_item":
            raw = getattr(it, "raw_item", None)
            txt = "".join(
                getattr(c, "text", "")
                for c in getattr(raw, "content", []) or []
                if getattr(c, "type", None) == "output_text"
            )
            out.append({"role": "assistant", "content": txt})
        # else: reasoning_item / handoff_* — irrelevant to the tool stream; skip.
    return out


def stream_verdict_from_items(history_items: list, policy: StreamPolicy = LIVE_STREAM_POLICY):
    """Build the live `StreamVerdict` from the SDK history. PURE given the items.

    Converts the SDK RunItems to the chat shape, assembles a `Trajectory`, and runs the SAME
    `to_tool_stream(normalize=True)` + `classify_stream` the offline replay uses — so the live
    verdict is byte-identical to the offline replay verdict on the same loop (the parity test gate).
    """
    msgs = _sdk_items_to_chat_messages(history_items)
    traj = Trajectory(model_run="", task_name="", passed=None, messages=tuple(msgs))
    stream = to_tool_stream(traj, normalize=True)
    return classify_stream(stream, policy)


# ---------------------------------------------------------------------------
# The synthetic WARN message — a turn-boundary re-surface, never a directive.
# ---------------------------------------------------------------------------
@dataclass
class _WarnMessageItem:
    """A minimal RunItem-shaped carrier for a synthetic user WARN message.

    `new_step_items` is iterated only for `.to_input_item()` (run.py:758) and the typed `.type`
    discriminators elsewhere; this duck-types both. `to_input_item()` returns a plain Responses
    input dict {"role":"user","content":<warn>} — the SDK feeds it to the next model call verbatim
    (items.py:60, the dict branch). We deliberately do NOT use a real `MessageOutputItem` (its
    raw_item is typed `ResponseOutputMessage`, an ASSISTANT pydantic model) — a re-surface is a
    USER-channel nudge, not a forged assistant turn.
    """

    raw_item: dict
    agent: Any = None
    type: str = "dos_warn_item"

    def to_input_item(self) -> dict:
        return self.raw_item


def _warn_message(warn_text: str, agent: Any = None) -> _WarnMessageItem:
    return _WarnMessageItem(raw_item={"role": "user", "content": warn_text}, agent=agent)


def build_warn_text(verdict) -> str:
    """Compose the turn-preserving WARN string for a REPEATING/STALLED verdict. PURE.

    Re-surfaces the env value the agent ALREADY received (its own `result_digest`/step), never a
    fabricated value and never a directive about which tool to call (the docs/143 derailment channel
    is unreachable). The text names the repeat count and the looping tool, and tells the agent to
    USE the value it already holds or take a DIFFERENT action.
    """
    rs = verdict.repeated_step
    tool = rs.tool_name if rs is not None else "a tool"
    n = verdict.repeat_run
    return (
        f"[DOS tool-stream WARN] You have already received the exact same result from "
        f"`{tool}` {n} times in a row — no new information is entering the loop. Use the value "
        f"you already have, or take a DIFFERENT action. Do not re-issue the same call again."
    )


# ---------------------------------------------------------------------------
# The patch: classify the live stream after results are assembled, prepend a
# WARN to the next turn on REPEATING/STALLED. Advisory, structural, fail-safe.
# ---------------------------------------------------------------------------
_FIRE_STATES = (StreamState.REPEATING, StreamState.STALLED)


def install(policy: StreamPolicy = LIVE_STREAM_POLICY) -> None:
    """Install the WARN patch onto `RunImpl.execute_tools_and_side_effects`.

    Wraps the SDK's own method: it runs the un-patched body to get the `SingleStepResult` (so all
    tool dispatch + side effects happen EXACTLY as before — we never touch dispatch), then — ONLY if
    the run continues (NextStepRunAgain, i.e. the model will be called again) — classifies the live
    tool stream and, on REPEATING/STALLED, PREPENDS a synthetic user WARN to `new_step_items` so the
    next model call sees it. Idempotent: a second install is a no-op.
    """
    from agents._run_impl import RunImpl  # local import: only the WARN arm needs the SDK present
    from agents._run_impl import NextStepRunAgain, SingleStepResult

    if getattr(RunImpl.execute_tools_and_side_effects, "_dos_warn_wrapped", False):
        return  # already installed — idempotent

    original = RunImpl.execute_tools_and_side_effects

    async def patched(cls, *args, **kwargs):  # noqa: ANN001 - matches the classmethod shape
        # 1. Run the un-patched body FIRST — all dispatch + side effects are untouched.
        result: SingleStepResult = await original.__func__(cls, *args, **kwargs)
        # 2. ADVISORY + STRUCTURAL + FAIL-SAFE: only ever prepend a message, only at a turn boundary
        #    (the run continues), wrapped so a patch bug degrades to normal dispatch.
        try:
            if os.environ.get("DOS_WARN") in (None, "", "0"):
                return result  # the env flag gates the actuation; same code, the flag is the delta
            # Only act when the model will be called again — never on a final-output / handoff step
            # (no "next turn" to inform). This is the turn-boundary discipline.
            if not isinstance(result.next_step, NextStepRunAgain):
                return result
            agent = kwargs.get("agent") or (args[0] if args else None)
            history = list(result.pre_step_items) + list(result.new_step_items)
            verdict = stream_verdict_from_items(history, policy)
            if verdict.state in _FIRE_STATES:
                warn = _warn_message(build_warn_text(verdict), agent=agent)
                # PREPEND so the WARN leads the next turn's appended items (the model reads it as the
                # most recent user turn). We never modify processed_response / functions / any result.
                result.new_step_items = [warn] + list(result.new_step_items)
        except Exception:
            # A patch bug must NEVER break the run — fail toward un-patched dispatch.
            return result
        return result

    patched._dos_warn_wrapped = True  # type: ignore[attr-defined]
    patched._dos_warn_original = original  # type: ignore[attr-defined]
    RunImpl.execute_tools_and_side_effects = classmethod(patched)  # type: ignore[assignment]


def uninstall() -> None:
    """Restore the original `execute_tools_and_side_effects` (test hygiene / arm reset)."""
    try:
        from agents._run_impl import RunImpl
    except Exception:
        return
    wrapped = RunImpl.execute_tools_and_side_effects
    original = getattr(wrapped, "_dos_warn_original", None)
    if original is not None:
        RunImpl.execute_tools_and_side_effects = original


def apply_warn_patch(policy: StreamPolicy = LIVE_STREAM_POLICY) -> bool:
    """The A/B entry point. Installs the WARN patch IFF `DOS_WARN` is truthy; returns whether the
    actuation arm is active.

    The OBSERVE arm leaves `DOS_WARN` unset → this is a no-op (the patch is not installed; even if a
    caller installs unconditionally, the patched body's flag check short-circuits). The WARN arm sets
    `DOS_WARN=1` → the patch installs and re-surfaces on REPEATING/STALLED. The SAME harness code
    runs both arms; the env flag is the only difference (the docs/144 OBSERVE-vs-WARN ladder)."""
    active = os.environ.get("DOS_WARN") not in (None, "", "0")
    if active:
        install(policy)
    return active
