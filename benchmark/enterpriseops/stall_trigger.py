"""stall_trigger — the DOMAIN-FREE prune trigger: classify_stream → STALLED (docs/176 §7 item #1).

The frontier-#1 gap docs/176 names: the live rewind/restart trigger today is either the
MINT-specific `block_counts >= 2` or the gym-specific `natural_thrash_gate` (which keys on a
recognized STRUCTURED-ERROR grammar, `_is_struct_error`). Both are domain-coupled. The kernel
already ships the DOMAIN-FREE, ENV-AUTHORED, MODEL-DURABLE version of "is this loop stuck?" —
`tool_stream.classify_stream` — and this module wires it as a prune trigger, so the SUBTRACT
actuation can fire on ANY stalled tool loop, not just the gym's error envelopes.

WHY STALLED, NOT REPEATING (the safe-signal discipline, from tool_stream's own docstring +
docs/176 §5). `classify_stream` returns three states over the trailing run of
byte-identical `(tool, args, result_digest)` triples:
  * ADVANCING — new env bytes are entering the loop (or too short to judge) → NO action.
  * REPEATING (run >= repeat_n, default 3) — the same env bytes recurred → WARN/re-surface
    ONLY. A legitimate eventual-consistency poll produces identical reads until the async
    write lands; cutting it would FAIL a correct wait. So REPEATING is never a prune.
  * STALLED (run >= stall_n, default 5) — the run is long enough to be near-certainly doomed
    → the PRUNE-eligible rung. This module fires the SUBTRACT trigger ONLY here.

WHY IT IS BYTE-CLEAN (the §5a survival argument, inherited from tool_stream). The trigger's
only question is "did the ENV return byte-identical `result_digest` N times in a row?" — a
pure byte fact about ENV-AUTHORED output (the gym/MCP server produced the result bytes; the
agent did not author the IDENTITY of its own repeated results). It NEVER asks the forgeable
satisfaction predicate "is the agent making progress / has it done the right thing." Same
clean provenance as `arg_provenance`'s mint detector, re-aimed from "is this id minted?" to
"did this exact env output repeat?".

THE HONEST RELATIONSHIP TO natural_thrash_gate (docs/175 §4 — NOT a replacement). The two
catch DIFFERENT failure classes, and keeping them apart is load-bearing:
  * STALLED (this module) = the byte-identical-REPEAT class — re-issue the SAME call, get the
    SAME bytes back N times (a true spin: re-reading an unchanged row, polling a stuck result).
    Domain-free: needs no error grammar.
  * natural_thrash_gate = the error-dominated-BRANCH class — the SAME tool errors >=2× with
    POSSIBLY-DIFFERENT error bytes (parent A → 404, parent B → 404). docs/175 measured that
    `tool_stream` MISSES 12 of 20 such branches because the differing errors never form a
    consecutive identical run. So STALLED is the domain-free LOOP trigger; natural_thrash is
    the BRANCH trigger. This module ADDS the former; it does not supersede the latter. A host
    can run both (a tool can stall on one input and branch on another).

⚓ This is benchmark-side (it imports `dos` — the one-way arrow, never kernel) and STANDALONE
(zero edits to the concurrently-held dos_react.py — the disjoint-lane discipline). The pure
gate is AST-extractable / directly importable for a no-gym unit test (the restart_arm pattern).
It reuses `dos.posttool_sensor.step_from_event` to compute the digests, so the IN-FLIGHT loop
trigger is BYTE-IDENTICAL to the live PostToolUse hook's signal — the same verdict, not a
look-alike (the dos_solves_output_poll "same signal" discipline).

Wire (one-line swap/augment at the natural-thrash call site, when the concurrent benchmark
edits land):
    if self._stall_rewind_on and tool_name not in self._stall_done:
        gate = stall_thrash_gate(tool_results, tool_name, self._stream_policy)
        if gate is not None:
            n_repeat, env_excerpt = gate
            self._stall_done.add(tool_name)
            rewound = self._maybe_rewind_natural(messages, tool_results,
                                                 conversation_flow, tool_name,
                                                 n_repeat, env_excerpt)
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence, Tuple

from dos.posttool_sensor import step_from_event
from dos.tool_stream import (
    DEFAULT_POLICY,
    StreamPolicy,
    StreamState,
    StreamStep,
    ToolStream,
    classify_stream,
)
from dos.rewind import (
    EnvExcerpt,
    FireVerdict,
    SuspendCheckpoint,
    TurnRef,
    digest_turn,
    rewind_plan,
)


def _event_from_tool_result(tr: Dict[str, Any]) -> dict:
    """Map one `tool_results` entry → the hook-shaped event `step_from_event` reads. PURE.

    A `tool_results` entry is `{tool_name, arguments, result, gym_server}`. The live
    PostToolUse hook event is `{tool_name, tool_input, tool_response}`. We map
    arguments→tool_input and result→tool_response so the SAME `step_from_event` computes
    BYTE-IDENTICAL digests in-flight as it does at the hook — the in-flight trigger really is
    the same signal as the hook, not a parallel implementation that could drift.

    The result we hand in is the FULL `tr["result"]` object (the gym's
    `{"success": bool, "result": <payload>, ...}` wrapper), so two calls digest-equal iff the
    env returned byte-identical wrapped results — which is exactly the spin we want to catch
    (an unchanged success-or-error reply hammered N times). A `dos_blocked` synthetic is left
    in as-is: it carries a distinct `dos_blocked` marker so a block's bytes differ from a real
    result's, and the BLOCK path has its own (mint) trigger; the stall trigger keys on the env
    stream and a synthetic simply doesn't form an env-identical run with a real result.
    """
    return {
        "tool_name": str(tr.get("tool_name", "")),
        "tool_input": tr.get("arguments", {}) or {},
        "tool_response": tr.get("result"),
    }


def stream_from_tool_results(
    tool_results: Sequence[Dict[str, Any]], policy: StreamPolicy = DEFAULT_POLICY
) -> ToolStream:
    """Fold a run's `tool_results` into a `ToolStream`. PURE — the boundary the kernel verdict reads.

    Each entry becomes a `StreamStep` via the SHARED `step_from_event` adapter (so the digest
    bytes match the live hook exactly). An entry that yields no step (no tool_name) is dropped —
    it cannot participate in a repeat run. The stream is kept WHOLE and in order so
    `classify_stream` measures the run ENDING at the latest step (the live "is it stuck right
    now?" question, not a whole-history histogram).
    """
    steps: list[StreamStep] = []
    for tr in tool_results:
        step = step_from_event(_event_from_tool_result(tr), policy=policy)
        if step is not None:
            steps.append(step)
    return ToolStream(tuple(steps))


def _latest_result_excerpt(
    tool_results: Sequence[Dict[str, Any]], tool_name: str, *, excerpt_chars: int = 200
) -> str:
    """The ENV's own latest result bytes for `tool_name`, for the byte-clean no-good note. PURE.

    The no-good note re-entered after a stall carries the env-authored bytes the agent kept
    receiving (THIRD_PARTY — the env wrote them). This pulls the latest such result as a short
    excerpt. It is descriptive, not a generated critique: it is the env's own repeated output,
    the same provenance the rewind arm's note requires. Falls back to a generic env-authored
    line if no textual result is available (still THIRD_PARTY in spirit — a statement about the
    env's behavior, never an agent-authored fix)."""
    import json as _json

    own = [tr for tr in tool_results if str(tr.get("tool_name", "")) == tool_name]
    if own:
        latest = own[-1]
        try:
            text = _json.dumps(latest.get("result"), sort_keys=True, default=str)[:excerpt_chars]
        except (TypeError, ValueError):
            text = str(latest.get("result"))[:excerpt_chars]
        if text and text not in ("null", "{}"):
            return text
    return (
        f"`{tool_name}` returned byte-identical results repeatedly — the env is not "
        f"producing new information for this call."
    )


def stall_anchor_index(
    tool_results: Sequence[Dict[str, Any]], repeat_run: int
) -> int:
    """The rewind anchor for a STALLED run: the index of the last turn BEFORE the stall began.

    THE INTEGRATION FINDING (docs/176 §7, surfaced by test_stall_to_rewind_integration). The
    natural-error rewind's anchor-finder (`_maybe_rewind_natural._is_verified`) rejects a turn
    that is a STRUCTURED ERROR — correct for the error-dominated stall, where the stalled turns
    ARE errors. But a `classify_stream`-STALLED loop can be a BYTE-IDENTICAL **success-looking**
    repeat (e.g. re-reading a row that returns `{"rows": []}` with outer `success: True` five
    times). Those stalled turns pass `_is_verified` (they look successful), so that anchor-finder
    walks BACKWARD into the stall and anchors INSIDE it — subtracting nothing. So the STALLED
    path must compute its OWN anchor: the turn immediately before the consecutive stalled run.

    `repeat_run` is the kernel's measured run length (the count of trailing byte-identical
    triples). The stalled run occupies the LAST `repeat_run` steps; the anchor is the step
    before them: `len(tool_results) - repeat_run - 1`. Returns -1 when the stall starts at the
    very first turn (no good prefix to anchor to → the kernel maps this to the System+Human-only
    re-entry, the honest "nothing verified to keep" floor). PURE.
    """
    return len(tool_results) - repeat_run - 1


def stall_thrash_gate(
    tool_results: Sequence[Dict[str, Any]],
    tool_name: str,
    policy: StreamPolicy = DEFAULT_POLICY,
    *,
    excerpt_chars: int = 200,
) -> Optional[Tuple[int, str, int]]:
    """PURE — has the tool loop STALLED (the domain-free prune signal)? Returns None, or
    ``(repeat_run, env_excerpt, anchor_index)``.

    Folds the whole run's `tool_results` into a `ToolStream` and asks the KERNEL verdict
    `classify_stream`. Fires (returns the tuple) ONLY on:

      * `verdict.state is STALLED` — the trailing run of byte-identical `(tool, args, result)`
        triples has reached `policy.stall_n` (default 5): near-certainly doomed, the
        PRUNE-eligible rung. AND
      * the repeating step is `tool_name` — the stall is on the tool the caller just dispatched
        (so the gate fires for the tool in the hole right now, the natural_thrash_gate posture).

    Returns None on ADVANCING or REPEATING (REPEATING is WARN-only — a legitimate
    eventual-consistency poll must not be pruned; the safe-signal discipline). On a fire it
    returns:
      * `repeat_run`    — the kernel's measured trailing-run length;
      * `env_excerpt`   — the env's own latest bytes for the byte-clean no-good note;
      * `anchor_index`  — the turn BEFORE the stall (the correct rewind target — see
                          `stall_anchor_index` for why the error-path's anchor-finder is wrong
                          for a success-looking stall). The consumer rewinds to THIS index, not
                          to whatever a re-used error-anchor-finder would pick.

    Domain-free: no error grammar, no mint, no agent narration — only env-authored
    result-byte identity.
    """
    stream = stream_from_tool_results(tool_results, policy)
    verdict = classify_stream(stream, policy)
    if verdict.state is not StreamState.STALLED:
        return None
    # The stall must be on the tool the caller is asking about (the one in the hole now). The
    # repeating step's tool_name is casefolded inside the verdict; compare casefolded.
    rs = verdict.repeated_step
    if rs is None or rs.tool_name.casefold() != tool_name.casefold():
        return None
    excerpt = _latest_result_excerpt(tool_results, tool_name, excerpt_chars=excerpt_chars)
    return verdict.repeat_run, excerpt, stall_anchor_index(tool_results, verdict.repeat_run)


def enact_stall_rewind(
    messages: list,
    tool_results: Sequence[Dict[str, Any]],
    conversation_flow: list,
    tool_name: str,
    repeat_run: int,
    env_excerpt: str,
    anchor_index: int,
    *,
    human_factory,
) -> bool:
    """SUBTRACT a STALLED loop: rewind to the correct (pre-stall) anchor + re-enter byte-clean.

    The self-contained STALLED enactment (NOT `_maybe_rewind_natural`, whose error-specific
    anchor-finder mis-anchors a success-looking stall — the integration finding above). Mirrors
    `_enact_rewind`'s shape but anchors at `anchor_index` (the turn before the stall), which the
    gate computed correctly. Uses the REAL kernel `rewind_plan` for the verdict + the byte-clean
    no-good note (a VERIFY_NOT_SHIPPED token over the stalled tool + the env's own repeated
    bytes, THIRD_PARTY) — the wrapper authors NO correction (the docs/164 ONE-FIX rule).

    Returns True iff the rewind was enacted (truncation done + note re-entered). False on
    UNANCHORED / NO_REWIND (no actionable plan) — fail-safe: never truncate to a turn the kernel
    did not stamp. `human_factory` builds the note message (langchain HumanMessage in production;
    a stand-in in the test) so this stays gym-free.
    """
    from dos.completion import Convergence
    from dos.log_source import Accountability
    from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED

    # map the env stream → kernel TurnRefs (the _enact_rewind digest shape)
    turns = tuple(
        TurnRef(i, digest_turn(json.dumps(
            {"t": tr.get("tool_name"), "s": str(tr.get("result"))[:64]}, sort_keys=True)))
        for i, tr in enumerate(tool_results)
    )
    if anchor_index >= 0:
        cp = SuspendCheckpoint(turn_index=anchor_index,
                               transcript_digest=turns[anchor_index].digest, present=True)
    else:
        cp = SuspendCheckpoint.absent()

    tokens = (VerdictToken(KIND_VERIFY_NOT_SHIPPED,
                           {"sha": f"{tool_name}=stalled-{repeat_run}x-identical"}),)
    plan = rewind_plan(
        turns, cp, FireVerdict.from_convergence(Convergence.THRASHING),
        verdict_tokens=tokens,
        env_excerpt=EnvExcerpt(env_excerpt, Accountability.THIRD_PARTY),
    )
    if not plan.is_actionable:  # UNANCHORED / NO_REWIND → fall back
        return False

    # SUBTRACT — truncate the message history back to the anchor's ToolMessage. messages is
    # [System, Human, (AI, Tool)*]; keep ToolMessages [0..anchor_index], drop the stalled tail.
    from langchain_core.messages import ToolMessage as _TM  # type: ignore  # noqa
    keep_tool_msgs = anchor_index + 1
    seen_tool = 0
    cut = len(messages)
    for mi, m in enumerate(messages):
        if isinstance(m, _TM):
            seen_tool += 1
            if seen_tool == keep_tool_msgs:
                cut = mi + 1
                break
    if anchor_index < 0:
        cut = 2  # no verified prefix → keep only System+Human
    del messages[cut:]

    note_text = "[DOS rewind] " + " | ".join(plan.no_good_note.render_lines())
    messages.append(human_factory(note_text))
    conversation_flow.append({
        "type": "dos_rewind",
        "kind": "stall",
        "tool_name": tool_name,
        "repeat_run": repeat_run,
        "rewind_to_turn": plan.rewind_to_turn,
        "dropped_turns": list(plan.dropped_turns),
        "no_good_note": list(plan.no_good_note.render_lines()),
    })
    return True
