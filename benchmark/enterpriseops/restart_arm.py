"""restart_arm — the missing comparand: RE-ORCHESTRATE a fresh context window on a thrash.

docs/176 §6. The rewind experiment (docs/172/175) compared rewind / none / block — but
the rival the *concept* names ("pruning a known-bad path beats orchestrating a whole new
context window") was never built: there was no RESTART arm. So "subtract ≻ re-orchestrate"
had zero measured comparand on the re-orchestrate side. This module adds it, as a STANDALONE
arm (zero edits to the concurrently-held dos_react.py / live_ab.py — the disjoint-lane
discipline, CLAUDE.md "commit only the lane you actually worked").

It is a thin subclass of `DosReactOrchestrator` that, on the SAME thrash trigger the rewind
arm uses (the same tool BLOCKED a 2nd time = convergence.THRASHING), does the naive recovery:
**discard the in-flight window and re-orchestrate from a fresh context** — the "kill it and
start over" baseline — with one knob that separates prune's two claimed advantages:

  * `seed_no_good=False` (the pure restart)  — fresh window = [System, Human]. Keeps the warm
    prefix? NO. Keeps the lesson "path P is dead"? NO. A fresh window can re-walk straight
    back into P. This is the literal "orchestrate a whole new context window" the framing names.
  * `seed_no_good=True`  (restart, seeded)    — fresh window = [System, Human, <no-good note>].
    Keeps the warm prefix? NO. Keeps the lesson? YES (the same BYTE-CLEAN no-good note the
    rewind arm re-enters with — a kernel VerdictToken + the env's own error bytes, NEVER a
    generated critique). Isolates "the lesson is what mattered, not the warm prefix."

Held against {none, block, rewind}, the four/five-way isolates exactly the §4 decomposition:
append-vs-subtract-vs-restart, and warm-prefix-vs-lesson. The whole point of building the
losing-on-paper restart is that the live rewind REFUTATION (docs/172 §8: rewind livelocked
when the dead end's cause was UPSTREAM of the anchor — backjumping handed back the same
poisoned prefix and the agent re-emitted the invented id) PREDICTS restart should win on the
upstream-cause slice: re-reasoning the whole prefix is the only move in this set that can
escape an upstream omission. This arm is how that prediction gets measured.

THE TOKEN LEDGER (the cost half of docs/176 §4, asserted there, never instrumented). Every
restart records prefix-tokens-re-paid + turns-discarded + a restart-event count, so the
"prune keeps the warm prefix, restart re-pays it" arithmetic finally has numbers — the exact
quantity the rewind replay (turns only) could not produce.

THE BYTE-CONTRACT (inherited from rewind, the docs/164 ONE-FIX rule). When seeding, the
no-good note is built by the REAL kernel `rewind.build_no_good_note` (a VerdictToken over the
unresolved id + the gym's THIRD_PARTY error excerpt), so a seeded restart can carry the
lesson WITHOUT the wrapper ever authoring a correction — same un-forgeable bytes as the
rewind arm, just prepended to a fresh window instead of a truncated one.

Run (when the concurrent benchmark edits land, add to live_ab.py _ARM_ENV):
    "restart":        {"DOS_CONSULT": "1", "DOS_INTERVENTION": "BLOCK", "DOS_RESTART": "1"},
    "restart_seeded": {"DOS_CONSULT": "1", "DOS_INTERVENTION": "BLOCK", "DOS_RESTART": "1",
                       "DOS_RESTART_SEED": "1"},

This module imports `dos` (the one-way arrow — benchmark-side, never kernel), and the pure
mechanism functions are AST-extractable for the no-gym unit test (test_restart_arm.py),
exactly the test_rewind_arm.py pattern, so the wiring is proven before any Gemini spend.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple


# ===========================================================================
# PURE mechanism — a window in, a FRESH window + a ledger delta out (no I/O, no LLM).
# These are the AST-extractable core the no-gym test exercises (the test_rewind_arm
# pattern): they read only their arguments, so a stand-in can drive them without the
# gym base class.
# ===========================================================================
def estimate_window_tokens(messages: List[Any]) -> int:
    """A cheap, deterministic proxy for the tokens a window costs to re-establish. PURE.

    NOT a real tokenizer (the live arm reads the LLM's usage_metadata for the true count) —
    a transport-stable estimate so the no-gym test can assert the ledger arithmetic without a
    model. ~4 chars/token over the stringified content of each message, the standard rough
    rule. The point of the ledger is the RELATIVE quantity (restart re-pays this; rewind keeps
    it warm), and a char/4 proxy preserves the ordering the experiment needs.
    """
    total_chars = 0
    for m in messages:
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content", "")
        total_chars += len(str(content if content is not None else ""))
    return total_chars // 4


def build_fresh_window(
    system_message: Any,
    human_message: Any,
    *,
    no_good_note_text: Optional[str] = None,
    human_factory=None,
) -> List[Any]:
    """The fresh context window a RESTART re-orchestrates from. PURE.

    The naive recovery: throw away everything after the original task framing and start the
    loop over from [System, Human]. This is the literal "orchestrate a whole new context
    window" the docs/176 framing names — it keeps NO warm prefix and (unseeded) NO lesson.

    `no_good_note_text` (the seeded variant) prepends the BYTE-CLEAN lesson as one extra
    HumanMessage so a fresh window keeps "path P is dead" without the wrapper authoring a
    correction — the same un-forgeable bytes the rewind arm re-enters with, just on a fresh
    window. `human_factory` builds the note message (the langchain HumanMessage in production;
    a stand-in in the test) so this stays gym-free.

    The fresh window is ALWAYS [System, Human, (note?)] — never anything from the dead branch.
    That is the whole contrast with rewind: rewind keeps [System, Human, …good prefix…, note];
    restart keeps only [System, Human, (note?)]. If the dead end's cause is UPSTREAM (in the
    good prefix rewind preserves), only restart drops it — the docs/172 §8 prediction.
    """
    window: List[Any] = [system_message, human_message]
    if no_good_note_text:
        if human_factory is None:
            raise ValueError("seeding a no-good note needs a human_factory to build it")
        window.append(human_factory(no_good_note_text))
    return window


def restart_decision(
    *,
    restart_on: bool,
    block_count: int,
    already_restarted_tools: set,
    tool_name: str,
    thrash_threshold: int = 2,
) -> bool:
    """Should THIS block trigger a restart? PURE — the same THRASHING gate the rewind arm uses.

    A restart fires iff: the arm is on, this is the >= thrash_threshold-th block on `tool_name`
    in this run (convergence.THRASHING — the agent re-entered the same hole), AND we have NOT
    already restarted on this tool this run. The one-restart-per-tool cap mirrors the rewind
    arm's `_natural_thrash_done` guard: without it, a tool that keeps thrashing after a restart
    would re-restart every block and livelock the loop in cold-starts (the failure mode the
    rewind refutation found in its OWN mechanism — a per-block re-fire that dropped nothing).
    Holding the trigger identical to the rewind arm's is what keeps the A/B clean: any delta is
    attributable to subtract-vs-restart, not to a different fire condition.
    """
    if not restart_on:
        return False
    if block_count < thrash_threshold:
        return False
    if tool_name in already_restarted_tools:
        return False
    return True


def restart_ledger_delta(discarded_messages: List[Any]) -> Dict[str, int]:
    """The token ledger delta one restart records. PURE.

    The cost half of docs/176 §4, made concrete: a restart DISCARDS `discarded_messages` (the
    whole dead window past [System, Human]) and will RE-PAY their token cost on the fresh
    re-orchestration. `prefix_tokens_repaid` is the estimate of what a rewind would have kept
    warm and a restart throws away — the exact quantity the rewind replay (which counted turns,
    never tokens) could not produce. Summed across a run, these are the per-arm numbers that
    settle "rewind keeps the warm prefix, restart re-pays it."
    """
    return {
        "restart_events": 1,
        "turns_discarded": len(discarded_messages),
        "prefix_tokens_repaid": estimate_window_tokens(discarded_messages),
    }


# ===========================================================================
# The factory — subclass DosReactOrchestrator, override the thrash handling.
# Deferred gym imports (the make_dos_react_orchestrator idiom) so the pure
# helpers above stay importable without the gym.
# ===========================================================================
def make_restart_orchestrator():
    """Build `RestartOrchestrator` against the live gym base — the restart arm's class.

    Subclasses the real `DosReactOrchestrator` and changes exactly the THRASH handling: where
    the rewind arm SUBTRACTS (truncate to the anchor + re-enter), this DISCARDS the window and
    re-orchestrates fresh (optionally seeded with the same byte-clean no-good note). Everything
    else — the arg_provenance consult, the intervention ladder, the BLOCK synthetic, the mint
    injection — is inherited UNCHANGED, so the detector is byte-identical to the rewind/block
    arms and the only between-arm difference is the recovery move. Register the returned class
    in the gym's ORCHESTRATOR_MAP under "restart" (the gym_orchestrator_shim does this).
    """
    from dos_react import make_dos_react_orchestrator, _load_base  # benchmark-side

    DosReactOrchestrator = make_dos_react_orchestrator()
    _ReactOrchestrator, SystemMessage, HumanMessage, ToolMessage = _load_base()

    class RestartOrchestrator(DosReactOrchestrator):
        """ReAct + arg_provenance + intervention ladder, but a THRASH RE-ORCHESTRATES fresh.

        The naive rival to rewind: on the 2nd block of a tool, instead of subtracting the
        dead-end turns back to the last-verified anchor, throw the whole window away and start
        the loop over from [System, Human] (+ the byte-clean no-good note when seeded). Holds
        the detector identical to block/rewind; records a token ledger so the cost half of the
        prune-vs-restart question is finally measured.
        """

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._restart_on = os.environ.get("DOS_RESTART", "0") not in ("0", "false", "")
            self._restart_seed = os.environ.get("DOS_RESTART_SEED", "0") not in ("0", "false", "")
            self._restarted_tools: set = set()         # tool_names already restarted (one-shot)
            self._restarts_done = 0
            self._restart_ledger = {
                "restart_events": 0, "turns_discarded": 0, "prefix_tokens_repaid": 0,
            }

        def get_result_metadata(self) -> Dict[str, Any]:
            md = dict(super().get_result_metadata())
            md["dos_restart"] = {
                "restarts_done": self._restarts_done,
                "seeded": self._restart_seed,
                **self._restart_ledger,
            }
            return md

        def _restart_env_excerpt(self, tool_results, tool_name, unresolved) -> str:
            """The gym's OWN latest block-error bytes for `tool_name` — NOT a fabricated directive.

            The provenance fix: read the env's REAL recorded error text (the gym's
            blocked_unresolved_id payload the BLOCK branch fed back) so the THIRD_PARTY tag is HONEST.
            Falls back to a STRUCTURAL fact that names the WALL (the id never appeared), never the
            corrective ACTION — so the note carries no authored 'do X' instruction either way."""
            for tr in reversed(tool_results or []):
                if str(tr.get("tool_name")) == tool_name:
                    r = tr.get("result", tr)
                    txt = r if isinstance(r, str) else __import__("json").dumps(r, default=str)
                    if "blocked_unresolved_id" in txt or "isError" in txt or "Error" in txt:
                        return txt[:400]
            return (f"`{tool_name}` references id(s) ({unresolved}) that never appeared in any "
                    f"prior tool result.")

        def _maybe_restart(self, messages, tool_results, conversation_flow,
                           verdict, tool_name, tool_args) -> bool:
            """RE-ORCHESTRATE a fresh window instead of subtracting (the restart move).

            Called on a THRASH (2nd block on the same tool). DISCARDS the in-flight window back
            to [System, Human] (+ the byte-clean no-good note when seeded), records the token
            ledger delta, and returns True so the caller `continue`s — the outer loop re-invokes
            the LLM on the fresh window next iteration. Returns False (caller falls through to
            the ordinary BLOCK append) only if the trigger is not met — fail-safe: never restart
            a window we should not.

            The seeded note is built by the REAL kernel `rewind.build_no_good_note` over the
            unresolved id + a synthetic env excerpt, so a seeded restart carries the lesson with
            the SAME un-forgeable bytes the rewind arm uses — the wrapper authors nothing.
            """
            from dos.rewind import build_no_good_note, EnvExcerpt
            from dos.log_source import Accountability
            from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED

            if not restart_decision(
                restart_on=self._restart_on,
                block_count=self._block_counts.get(tool_name, 0),
                already_restarted_tools=self._restarted_tools,
                tool_name=tool_name,
            ):
                return False

            # the window past [System, Human] is what a restart discards + re-pays
            discarded = messages[2:]
            delta = restart_ledger_delta(discarded)

            note_text: Optional[str] = None
            if self._restart_seed:
                # The BYTE-CLEAN lesson (the audit's provenance fix): a typed VERIFY_NOT_SHIPPED
                # token over the unresolved id (a structured field the kernel computed) + the gym's
                # REAL recorded block-error bytes (THIRD_PARTY), NOT a fabricated 'Look the id up…
                # then retry' DIRECTIVE. The old version authored a corrective ACTION and self-tagged
                # it THIRD_PARTY — the exact mislabel the kernel floor forbids (rewind.py:243-247).
                # We now read the env's own error text off tool_results; absent one, a STRUCTURAL fact
                # that names the WALL (id never appeared) but never the corrective action.
                unresolved = ",".join(getattr(verdict, "unsupported", []) or []) or "id"
                env_err = self._restart_env_excerpt(tool_results, tool_name, unresolved)
                tokens = (VerdictToken(KIND_VERIFY_NOT_SHIPPED,
                                       {"sha": f"{unresolved}=never-appeared"}),)
                note = build_no_good_note(
                    tokens,
                    EnvExcerpt(env_err, Accountability.THIRD_PARTY),
                )
                note_text = "[DOS restart] " + " | ".join(note.render_lines())

            fresh = build_fresh_window(
                messages[0], messages[1],
                no_good_note_text=note_text,
                human_factory=lambda t: HumanMessage(content=t),
            )
            messages[:] = fresh  # in-place replace so the caller's reference stays valid

            self._restarted_tools.add(tool_name)
            self._restarts_done += 1
            for k, v in delta.items():
                self._restart_ledger[k] += v
            conversation_flow.append({
                "type": "dos_restart",
                "tool_name": tool_name,
                "seeded": self._restart_seed,
                **delta,
            })
            return True

    return RestartOrchestrator
