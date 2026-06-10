"""dos_react — a 4th EnterpriseOps-Gym orchestrator that consults `dos.arg_provenance`.

docs/143 §3/§7 — the consumer-side fork. This is NOT kernel code (it imports `dos`, the
one-way arrow); it lives benchmark-side. It subclasses the gym's `ReactOrchestrator` and
changes exactly ONE thing: **before dispatching a mutating tool call, it folds
`dos.arg_provenance.classify_call` over the env-authored bytes the agent has already seen
(prior tool RESULTS + the task text). On UNSUPPORTED — an id/FK arg the model minted
rather than resolved — it injects ONE advisory nudge ToolMessage ("resolve `<value>` via
a read tool first") instead of dispatching.** Same model, same 512 tools, same hidden SQL
scorer — only the loop changes (the clean A/B the audit calls for).

The legitimacy line (docs/143 §3): the wrapper reads ONLY what a fair agent could — its
own prior tool-result history and the system/user prompt. It NEVER reads the hidden SQL
verifiers, the oracle plan, or held-out final state. The provenance corpus is built only
of `EnvBlob`s tagged `TOOL_RESULT` / `TASK_TEXT` — there is no enum to tag a model turn
with, so the agent's own narration can never enter the corpus (the structural
non-self-authorship guarantee).

The nudge is advisory and bounded:
  * it fires only on a MUTATING call with ≥1 UNSUPPORTED id/FK arg;
  * it is capped at ONE re-injection per (tool, arg-value) pair (the docs/143 §4 cap), so
    a stubborn model that re-mints the same id is dispatched the second time — the wrapper
    nudges, it does not livelock;
  * on the second attempt for the same arg-value, or on SUPPORTED/ABSTAIN, the call is
    dispatched normally. The verdict's only power is to nudge-MORE; it can never force a
    call through (refuse-MORE-only by the shape of `dos.arg_provenance`).

Per-flag switches (docs/143 §8): `enforce` toggles nudge (R1, default) vs hard-block (R2);
both off reproduces `react` exactly. Mechanisms are flags so the ladder rungs differ by
one config line.

The write-verb classifier is deliberately **fail-open** (when unsure whether a tool
mutates, treat it as a read → do not gate): under-gating degrades to baseline (safe),
over-gating risks a feasible-task regression (the §8 kill-signal). A host that ships
explicit tool schemas can pass `mutating_tools` for precision.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dos.arg_provenance import (
    CorpusSource,
    EnvBlob,
    PriorResults,
    ProvenancePolicy,
    ToolArg,
    ToolCall,
    classify_call,
)

logger = logging.getLogger(__name__)

# A small, conservative set of verb stems that mark a tool as MUTATING. The classifier is
# fail-open: a tool whose name matches none of these is treated as a read and never gated.
# Substring-on-a-normalized-name (lower, '-'/'.'→'_'), so `create_incident`,
# `incident.create`, `update-user`, `delete_record`, `send_email`, `add_member` all hit.
_MUTATING_STEMS: tuple[str, ...] = (
    "create", "update", "delete", "remove", "add", "send", "set", "assign",
    "insert", "patch", "put", "post", "modify", "edit", "submit", "close",
    "resolve", "cancel", "approve", "reject", "schedule", "move", "rename",
    "upload", "share", "grant", "revoke", "transfer", "merge", "link", "attach",
)


def _normalize_tool_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(".", "_")


def is_mutating_tool(
    tool_name: str,
    *,
    mutating_tools: Optional[set[str]] = None,
    read_tools: Optional[set[str]] = None,
) -> bool:
    """Fail-open write-verb classifier. Explicit `mutating_tools`/`read_tools` (from the
    tool schema) win; otherwise a verb-stem heuristic over the normalized name, biased to
    NOT gate when unsure."""
    n = _normalize_tool_name(tool_name)
    if read_tools and n in {_normalize_tool_name(t) for t in read_tools}:
        return False
    if mutating_tools is not None:
        return n in {_normalize_tool_name(t) for t in mutating_tools}
    stems = n.split("_")
    return any(stem in _MUTATING_STEMS for stem in stems) or any(
        n.startswith(s) for s in _MUTATING_STEMS
    )


def build_prior_results(
    task_text: str,
    prior_tool_results: Sequence[Dict[str, Any]],
) -> PriorResults:
    """Flatten the env-authored bytes the agent has seen into a `PriorResults` corpus.

    `task_text` (the system+user prompt) is one `TASK_TEXT` blob; each prior tool RESULT is
    one `TOOL_RESULT` blob, rendered to a string with `json.dumps` (the kernel never parses
    JSON — it gets flat text). This is the boundary I/O the audit places at the call site;
    `classify_call` is pure over the result.
    """
    blobs: list[EnvBlob] = []
    if task_text:
        blobs.append(EnvBlob(text=str(task_text), source=CorpusSource.TASK_TEXT))
    for tr in prior_tool_results:
        # docs/143 §13.4 anti-laundering: a BLOCK's SYNTHETIC corrective result echoes the
        # unresolved id (by component) — it must NEVER re-enter the provenance corpus, or it
        # would teach `classify_arg`'s whole-value-direct-match to TRUST the very id it
        # blocked (the re-mint would substring the corrective text and read SUPPORTED). The
        # kernel stamps `dos_blocked: True` on the synthetic payload; the consumer drops it.
        if _is_blocked_result(tr):
            continue
        try:
            payload = tr.get("result", tr)
            text = json.dumps(payload, default=str)
        except Exception:
            text = str(tr)
        blobs.append(EnvBlob(text=text, source=CorpusSource.TOOL_RESULT))
    return PriorResults(blobs=tuple(blobs))


def _is_blocked_result(tr: object) -> bool:
    """True iff `tr` is a DOS BLOCK synthetic corrective result (carries `dos_blocked: True`
    at any of the nested result levels the harness wraps it in). Such a record is excluded
    from the provenance corpus — the docs/143 §13.4 self-laundering guard."""
    if not isinstance(tr, dict):
        return False
    if tr.get("dos_blocked"):
        return True
    r = tr.get("result")
    if isinstance(r, dict):
        if r.get("dos_blocked"):
            return True
        rr = r.get("result")
        if isinstance(rr, dict) and rr.get("dos_blocked"):
            return True
    return False


def evaluate_tool_call(
    tool_name: str,
    tool_args: Dict[str, Any],
    task_text: str,
    prior_tool_results: Sequence[Dict[str, Any]],
    *,
    policy: ProvenancePolicy = ProvenancePolicy(),
    mutating_tools: Optional[set[str]] = None,
    read_tools: Optional[set[str]] = None,
    new_key_args: Optional[set[str]] = None,
):
    """The full per-call provenance evaluation — pure given the inputs.

    Returns the `dos.arg_provenance.ProvenanceVerdict`. `new_key_args` names the arg(s)
    holding the NEW object's own identity (a create's own primary key) so they are tagged
    `is_reference=False` and never nudged (you cannot resolve an id you are minting). When
    unknown, omit it — the default treats every arg as a reference (the gating direction);
    a host with tool schemas should pass the create's own-key slot.
    """
    is_mut = is_mutating_tool(tool_name, mutating_tools=mutating_tools, read_tools=read_tools)
    nk = {a.lower() for a in (new_key_args or set())}
    args = tuple(
        ToolArg(name=k, value=v, is_reference=(k.lower() not in nk))
        for k, v in (tool_args or {}).items()
    )
    call = ToolCall(tool_name=tool_name, args=args, is_mutating=is_mut)
    prior = build_prior_results(task_text, prior_tool_results)
    return classify_call(call, prior, policy)


def build_nudge_text(verdict, tool_name: str) -> str:
    """The advisory ToolMessage injected in place of an UNSUPPORTED mutating dispatch.

    Names the precise minted components (from `components_unmatched`) so the model knows
    which id to resolve, and instructs it to issue the prerequisite read first — directly
    targeting the 'Missing Prerequisite Lookup' / 'Incorrect ID Resolution' failure modes.
    """
    parts: list[str] = []
    for a in verdict.args:
        if a.stance.value == "UNSUPPORTED":
            missing = ", ".join(a.components_unmatched) or a.value_repr
            parts.append(f"`{a.arg_name}={a.value_repr}` (unresolved: {missing})")
    joined = "; ".join(parts) if parts else "an id argument"
    return (
        f"[DOS arg-provenance] The call to `{tool_name}` references {joined}, which did "
        f"not appear in any prior tool result or the task description — it looks invented "
        f"rather than resolved. Before this mutating call, issue a READ/QUERY tool call to "
        f"look up the correct id from the database, then retry `{tool_name}` with the "
        f"resolved value. Do NOT fabricate ids."
    )


# ---------------------------------------------------------------------------
# docs/158 — the TERMINAL-ERROR gate (the STOP-event sibling of the DANGLING gate).
#
# byte-clean terminal_error predicate; canonical copy in benchmark/toolathlon/trajectory.py
# (docs/158). The grammar is anchored TIGHTLY to STRUCTURED error-envelope shapes only — a
# loose substring ('error'/'failed'/'not found') would match env-authored PAYLOAD that
# legitimately contains those words. The bytes it reads are the ENV-authored tool RESULT, never
# the agent's response.content (its own narration) — the §5a byte-inequality line: the judged
# agent did not author the identity of the env's error envelope, so this is provenance-of-an-
# env-authored-error, never a forgeable satisfaction predicate.
_STRUCT_ERR = re.compile(
    r"MCP error -3\d{4}"              # JSON-RPC / MCP gateway error code (e.g. -32603, -32004)
    r"|\"isError\"\s*:\s*true"        # the MCP tool-result error flag
    r"|^\s*Error:"                    # a leading 'Error:' text node (env error envelope)
    r"|Traceback \(most recent"       # a Python traceback in a tool/terminal result
    r"|exited with code [1-9]"        # a non-zero process exit (terminal/k8s tools)
    r"|permission denied",            # an access failure
    re.IGNORECASE | re.MULTILINE,
)


def _is_struct_error(content: str) -> bool:
    """True iff the env result content matches a STRUCTURED error envelope (not a loose
    substring). PURE; the byte-clean grammar (canonical copy in trajectory.py, docs/158)."""
    return bool(_STRUCT_ERR.search(content or ""))


def _result_text(tr: Dict[str, Any]) -> str:
    """Serialize the ENV-authored result payload of a `tool_results` entry to text — exactly the
    bytes `build_prior_results` feeds the provenance corpus. Reads `tr['result']` (the env's
    reply), never any agent-authored narration."""
    try:
        return json.dumps(tr.get("result", tr), default=str)
    except Exception:
        return str(tr)


def terminal_error_gate(
    tool_results: Sequence[Dict[str, Any]], *, window: int = 3, excerpt_chars: int = 200,
) -> Optional[Tuple[str, str, str]]:
    """PURE decision for the STOP-event TERMINAL-ERROR gate (docs/158). Returns None if the gate
    does NOT fire, else ``(tool_name, excerpt, nudge_text)`` where every byte is ENV-authored.

    FIRES iff a STRUCTURED error envelope sits in the LAST ``window`` (K=3) tool_results AND no
    later result from the SAME tool recovered to a success — the agent walked away from an
    unresolved environment failure. The nudge echoes ONLY the env error excerpt (truncated) +
    the failing tool name, both pulled from ``tool_results``; it NEVER interpolates the agent's
    response.content. Mirrors ``trajectory.terminal_error_fired`` (recovery="aware")."""
    steps: List[Tuple[str, bool, str]] = []
    for tr in tool_results:
        name = str(tr.get("tool_name", "") or "")
        text = _result_text(tr)
        steps.append((name, _is_struct_error(text), text))
    n = len(steps)
    start = max(0, n - window)
    for idx in range(start, n):
        name, is_err, text = steps[idx]
        if not is_err:
            continue
        # recovery="aware": a LATER result from the same tool that succeeded recovers this error.
        later_ok = any(
            steps[j][0] == name and not steps[j][1] for j in range(idx + 1, n)
        )
        if later_ok:
            continue
        excerpt = text[:excerpt_chars]
        nudge = (
            f"[DOS] The environment reported an unresolved error from `{name}`:\n"
            f"{excerpt}\n"
            f"No later call to that tool succeeded. Fix or retry it before finishing, or "
            f"confirm completion."
        )
        return name, excerpt, nudge
    return None


# The gym's Pydantic validator REFLECTS the agent's OWN submitted argument values verbatim
# back into the error envelope (an `input`/`"input":` field on each validation-error entry).
# Those reflected bytes are AGENT-AUTHORED — so an env-error excerpt that contains them is NOT
# purely THIRD_PARTY (the verify-wf byte-leak finding, docs/172). This pure helper STRIPS the
# reflected-input echo so the excerpt carries only the gym's own validation MESSAGE (`type`/
# `loc`/`msg`/the `❌ ... is required` text) — the bytes the env authored — before the consumer
# mints Accountability.THIRD_PARTY. Conservative: it redacts every `'input': <value>` /
# `"input": <value>` span (the only place the validator echoes the agent's value); if the shape
# is unrecognized it leaves the text unchanged and a separate caller-side cap still bounds length.
_REFLECTED_INPUT = re.compile(
    r"(['\"]input['\"]\s*:\s*)"          # the reflected-value key
    r"(?:'(?:[^'\\]|\\.)*'"              # a single-quoted value
    r"|\"(?:[^\"\\]|\\.)*\""            # or a double-quoted value
    r"|[^,}\]]*)",                      # or a bare scalar up to the next delimiter
)


def _redact_reflected_input(text: str) -> str:
    """Replace every reflected `input` echo with `input: <redacted: agent-authored>`. PURE.

    Keeps the env's own validation message (the byte the gym authored) and removes the agent's
    echoed argument value (the byte the agent authored), so the surviving excerpt is honestly
    THIRD_PARTY. The verify-wf must-fix: the kernel floor trusts the accountability TAG and never
    inspects bytes, so this boundary-side redaction is what KEEPS the tag honest."""
    if not text:
        return text
    return _REFLECTED_INPUT.sub(r"\1<redacted: agent-authored>", text)


# ---------------------------------------------------------------------------
# docs/172 — the NATURAL fail-thrash gate (the mint-free trigger for the rewind arm).
#
# The mint regime (docs/143) manufactures the invented-FK-ID failure mode by injecting
# corrupted ids; on a capable model the natural mint rate is ~0, so it is moot. But the
# NATURAL failure regime (no injection) shows agents thrash on their OWN errors ~9-12% of
# runs (the same tool failing >=2x), where the failures are real env errors (wrong filter
# logic, wrong field values, a state conflict) the agent re-issues. This gate fires the
# rewind SUBTRACT off THAT stream instead of the mint stream — the SOTA-relevant question
# ("agents naturally dead-end ~10% of the time; back them out soundly") rather than the
# artificial one. It is byte-clean for the SAME reason terminal_error is: it reads only the
# ENV-authored `tr['result']` error envelope (`_is_struct_error`), never response.content;
# the judged agent did not author the identity of the env's repeated error. The excerpt is
# REDACTED of the gym's reflected-input echo (the agent's own value bytes) so the THIRD_PARTY
# tag the consumer mints is honest (the verify-wf byte-leak fix).
def natural_thrash_gate(
    tool_results: Sequence[Dict[str, Any]], tool_name: str, *,
    min_failures: int = 2, excerpt_chars: int = 200,
) -> Optional[Tuple[int, str]]:
    """PURE — has `tool_name` just NATURALLY thrashed? Returns None if not, else
    ``(n_failures, env_error_excerpt)`` where the excerpt is the ENV's own latest error bytes.

    THRASH = the SAME tool produced a STRUCTURED error envelope (`_is_struct_error`) on
    `min_failures` (K=2) or more of its calls in this run AND its LATEST result is one of
    those errors (the agent is in the hole right now, not recovered). This is
    `completion.Convergence.THRASHING` computed off the env-authored failure stream — no
    mint, no arg_provenance, no agent narration. Counts failures of `tool_name` across the
    whole run (not just a window) because a natural re-thrash can be interleaved with other
    tools; the recovery check is on the LATEST result, so a tool that failed then succeeded
    does not fire (later success recovered it)."""
    own = [tr for tr in tool_results if str(tr.get("tool_name", "")) == tool_name
           and not _is_blocked_result(tr)]
    if len(own) < min_failures:
        return None
    # The latest call to this tool must itself be a structured error (still in the hole).
    latest = own[-1]
    latest_text = _result_text(latest)
    if not _is_struct_error(latest_text):
        return None
    n_fail = sum(1 for tr in own if _is_struct_error(_result_text(tr)))
    if n_fail < min_failures:
        return None
    # Redact the gym's reflected-input echo (agent-authored value bytes) BEFORE truncating, so
    # the THIRD_PARTY excerpt the consumer mints carries only the env's own validation message.
    return n_fail, _redact_reflected_input(latest_text)[:excerpt_chars]


# ---------------------------------------------------------------------------
# The orchestrator subclass. Imports the gym lazily so this module is importable (and the
# nudge logic above is unit-testable) without EnterpriseOps-Gym installed.
# ---------------------------------------------------------------------------
def _load_base():
    from orchestrators.react import ReactOrchestrator  # type: ignore
    from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage  # type: ignore

    return ReactOrchestrator, SystemMessage, HumanMessage, ToolMessage


def make_dos_react_orchestrator():
    """Build the `DosReactOrchestrator` class against the live gym base classes.

    Done as a factory so the gym imports are deferred to call time (a fair A/B requires the
    gym installed; the pure nudge helpers above do not). Register the returned class in the
    gym's `ORCHESTRATOR_MAP` under `"dos_react"`.
    """
    ReactOrchestrator, SystemMessage, HumanMessage, ToolMessage = _load_base()

    class DosReactOrchestrator(ReactOrchestrator):
        """ReAct + the `dos.arg_provenance` advisory verdict, actuated by a typed intervention.

        The actuation is the docs/143 §13 typed `dos.intervention` ladder
        (OBSERVE<WARN<BLOCK<DEFER), confidence-gated: before each mutating call the wrapper
        folds `arg_provenance.classify_call`, then maps the verdict to an `Intervention` via
        `intervention.choose_intervention` under an `InterventionPolicy`. The chosen rung
        decides what the wrapper DOES — the actuation the kernel only recommends:
          OBSERVE — dispatch unchanged; record only.
          WARN    — attach the advisory nudge as a ToolMessage AND still dispatch (the model
                    is informed without losing the turn — the prior −1.8pp default).
          BLOCK   — do NOT dispatch; return the kernel's SYNTHETIC corrective result in place
                    of the mutation (the agent gets "id unresolved; use a read tool" on the
                    SAME turn — the docs/143 §13.4 non-disruptive PEP, the candidate to turn
                    −9pp positive). Stamped `dos_blocked` so it never re-enters the corpus.
          DEFER   — do NOT dispatch; re-prompt (the agent retries, the turn is SPENT — the
                    original −9pp posture, opt-in only).

        Flags (set via orchestrator_kwargs / env):
          intervention  — the actuation mode: OBSERVE|WARN|BLOCK|DEFER (default WARN; env
                          DOS_INTERVENTION). Confidence-gated: a HIGH-confidence whole-value-
                          absent mint escalates to this mode's strength, a LOW-confidence
                          composite stays at WARN.
          enforce       — back-compat (R2): True maps to intervention=DEFER (skip+re-prompt).
          DOS_WARN_ONLY — back-compat env: "1" forces intervention=WARN (it was the default).
          max_nudges_per_value — cap on re-injections per (tool, arg-value) (default 1).
        """

        def __init__(self, *args, enforce: bool = False, max_nudges_per_value: int = 1,
                     mutating_tools: Optional[set[str]] = None,
                     read_tools: Optional[set[str]] = None,
                     mint_inject_rate: float = 0.0, mint_seed: int = 0,
                     consult: bool = True, intervention: str = "WARN", **kwargs):
            super().__init__(*args, **kwargs)
            import os as _os
            self.enforce = enforce
            self.max_nudges_per_value = max_nudges_per_value
            self._mutating_tools = mutating_tools
            self._read_tools = read_tools
            # Env overrides so the gym (which doesn't pass these kwargs) can drive the live
            # A/B without editing evaluate.py: DOS_MINT_RATE, DOS_MINT_SEED, DOS_CONSULT(0/1).
            mint_inject_rate = float(_os.environ.get("DOS_MINT_RATE", mint_inject_rate))
            mint_seed = int(_os.environ.get("DOS_MINT_SEED", mint_seed))
            if "DOS_CONSULT" in _os.environ:
                consult = _os.environ["DOS_CONSULT"] not in ("0", "false", "False", "")
            # WARN-ONLY remains the DEFAULT (docs/143 live finding): the skip-the-dispatch
            # nudge DERAILS the model mid-plan — on a true-positive catch it still cost −9pp on
            # the real harness, while warn-but-still-dispatch recovered that to −1.8pp and
            # flipped verifier-pass positive. Set DOS_WARN_ONLY=0 to opt INTO the disruptive
            # skip behavior (the old default), e.g. to reproduce the −9pp regression.
            self._warn_only = _os.environ.get("DOS_WARN_ONLY", "1") not in ("0", "false", "")
            # docs/143 §13 — the TYPED INTERVENTION LADDER, the primary actuation control. The
            # mode (OBSERVE/WARN/BLOCK/DEFER) is resolved with back-compat precedence:
            #   1. DOS_INTERVENTION env (explicit) wins;
            #   2. else DOS_WARN_ONLY=0 (the opt-in disruptive flag) OR enforce=True → DEFER
            #      (the old skip+re-prompt posture — back-compat for the R2 arm);
            #   3. else the `intervention` kwarg (default WARN).
            from dos.intervention import Intervention, InterventionPolicy
            _mode_env = _os.environ.get("DOS_INTERVENTION", "").strip().upper()
            if _mode_env:
                _mode = _mode_env
            elif (not self._warn_only) or enforce:
                _mode = "DEFER"
            else:
                _mode = (intervention or "WARN").strip().upper()
            try:
                self._intervention_mode = Intervention(_mode)
            except ValueError:
                self._intervention_mode = Intervention.WARN
            # The confidence-gating policy: a HIGH-confidence whole-value-absent mint escalates
            # to the chosen mode (capped by it as the ceiling), a LOW-confidence composite stays
            # at WARN (the §13.3 coupling). floor=WARN keeps a fired verdict at least informing.
            # OBSERVE mode means "never escalate past observe" → the whole ladder collapses to
            # OBSERVE for fired verdicts too, so floor/ceiling both ride the mode there.
            _m = self._intervention_mode.value
            if _m == "OBSERVE":
                self._int_policy = InterventionPolicy(
                    on_high_confidence="OBSERVE", on_low_confidence="OBSERVE",
                    on_none="OBSERVE", floor="OBSERVE", ceiling="OBSERVE")
            else:
                self._int_policy = InterventionPolicy(
                    on_high_confidence=_m,
                    on_low_confidence=("WARN" if _m in ("BLOCK", "DEFER") else _m),
                    on_none="OBSERVE", floor="WARN", ceiling=_m)
            # CONTROLLED MINT INJECTION (docs/143 live demonstration only — NOT a default).
            # With rate>0, a fraction of resolved id args are perturbed into a right-shape/
            # wrong-content mint BEFORE the provenance check, simulating a weaker model's
            # ID-error rate on the otherwise-REAL harness. R0 (consult=False) and R1
            # (consult=True) seeded IDENTICALLY inject the SAME mints, so the only difference
            # is whether the nudge catches+recovers them — a clean live A/B of the mechanism.
            self._mint_rate = mint_inject_rate
            self._consult = consult
            import random as _random
            import hashlib as _hashlib
            # per-task seed mixed with the user_prompt so each task injects deterministically
            # and identically across arms (the paired A/B), but tasks differ. Uses a STABLE
            # hash (md5, not the salted builtin hash()) so R0 and R1 — separate processes —
            # inject the SAME mints. The seed must be an int (a tuple raises).
            _task_h = int(_hashlib.md5(
                str(self.config.user_prompt).encode("utf-8")).hexdigest()[:8], 16)
            self._rng = _random.Random((int(mint_seed) << 32) ^ _task_h)
            self._nudge_counts: Dict[str, int] = {}
            # docs/147 — the PRECURSOR-PRESENCE consult (opt-in, additive beside arg_provenance).
            # On a mutating call whose mandated precursor (declared in the grammar, hand-authored
            # from the task prose) never fired earlier in the stream, attach a WARN re-surfacing
            # the requirement — the call STILL dispatches (turn preserved). Grammar loaded from
            # DOS_PRECURSOR_GRAMMAR (a dos.toml-shaped file) or the active SubstrateConfig.
            self._precursor_on = _os.environ.get("DOS_PRECURSOR", "0") not in ("0", "false", "")
            self._precursor_grammar = None
            if self._precursor_on:
                from dos.precursor_gate import EMPTY_GRAMMAR, load_from_toml
                gpath = _os.environ.get("DOS_PRECURSOR_GRAMMAR", "")
                try:
                    if gpath:
                        self._precursor_grammar = load_from_toml(gpath, base=EMPTY_GRAMMAR)
                    else:
                        from dos import config as _config
                        self._precursor_grammar = _config.active().precursors
                except Exception:  # fail-open: a bad grammar path degrades to no consult
                    self._precursor_grammar = EMPTY_GRAMMAR
            # docs/150/152 — the DANGLING-INTENT consult (opt-in, the third advisory gate). At the
            # agent's STOP event (a turn with no tool calls), did its last narration admit an open
            # obligation ("I still need to…") with no tool result after? On DANGLING_INTENT, re-surface
            # the agent's OWN abandoned sentence ONCE as a HumanMessage and let the loop run one more
            # iteration — DETECT-not-FIX, WARN-only, natural (no injection needed). The first byte-clean
            # axis whose value is on NATURAL premature-completion failures (the docs/149 92% head).
            self._dangling_on = _os.environ.get("DOS_DANGLING", "0") not in ("0", "false", "")
            self._dangled = False  # one-shot: re-surface at most once per run (never a livelock)
            # docs/158 — the TERMINAL-ERROR consult (opt-in, the STOP-event sibling of dangling).
            # At the agent's STOP event, did the env-authored bytes of the LAST few tool results
            # carry a STRUCTURED error envelope that no later same-tool success recovered? If so,
            # re-surface ONLY the env error excerpt + the failing tool name ONCE and run one more
            # turn — DETECT-not-FIX, WARN-only, byte-clean (the error bytes are the gym's, not the
            # agent's). The error envelope is read from tool_results, NEVER from response.content.
            self._terminal_error_on = _os.environ.get("DOS_TERMINAL_ERROR", "0") not in ("0", "false", "")
            self._terminal_errored = False  # one-shot
            # docs/171 — the REWINDABLE FIX LOOP arm (the conversation-rewind axis, F1.5).
            # When ON, a THRASH (the SAME tool blocked a 2nd time in a run = convergence.THRASHING)
            # does NOT append another synthetic correction (BLOCK's −4/task accretion). Instead the
            # wrapper SUBTRACTS: it calls dos.rewind.rewind_plan to place the rewind anchor at the
            # last VERIFIED tool result, truncates the live message history back to that anchor, and
            # re-enters with the kernel's byte-clean no-good note (a typed VERIFY_NOT_SHIPPED token +
            # the gym's OWN blocked_unresolved_id error excerpt — never a generated critique). The
            # 1st block on a tool still acts as the BLOCK re-surface; only the re-block (the thrash)
            # triggers the subtract. This is the live half of the rewind_counterfactual.py replay.
            self._rewind_on = _os.environ.get("DOS_REWIND", "0") not in ("0", "false", "")
            # docs/172 — the NATURAL fail-thrash rewind. The mint-free trigger: a real dispatch
            # whose ENV result is a structured error, for the SAME tool >=2× un-recovered, drives
            # the SUBTRACT off the env's OWN error bytes (no injection, no arg_provenance). This is
            # the SOTA-relevant arm — it fires on the agent's natural dead-ending (~10% of runs),
            # independent of CONSULT/INTERVENTION (it reads the post-dispatch failure stream).
            self._rewind_natural_on = _os.environ.get("DOS_REWIND_NATURAL", "0") not in ("0", "false", "")
            self._natural_thrash_done: set = set()      # tool_names already rewound (one-shot/tool)
            # docs/200/205 — the curable-CONVERSION arm. On the SAME natural fail-thrash trigger
            # (natural_thrash_gate), instead of SUBTRACTING (rewind), re-surface the env's OWN
            # corrective as an ADDITIVE forcing function (schema_refresh.refresh_directive over the
            # env-authored error bytes). Byte-clean: DOS authors only the framing; every corrective
            # byte is the gym's (the docs/164 one-rule). Additive (returns False, never breaks/subtracts)
            # so it is NOT the rewind livelock and NOT the BLOCK substitution (-4/task). One-shot/tool.
            self._schema_refresh_on = _os.environ.get("DOS_SCHEMA_REFRESH", "0") not in ("0", "false", "")
            self._schema_refresh_done: set = set()      # tool_names already re-surfaced (one-shot/tool)
            # docs/176 §6.1 — the DOMAIN-FREE STALLED rewind. The mint-free / error-grammar-free
            # trigger: the SAME tool returns BYTE-IDENTICAL env results stall_n× (the kernel
            # `tool_stream.classify_stream → STALLED` verdict, not a recognized-error shape), drives
            # the SUBTRACT off the env's OWN repeated bytes. Catches the byte-identical LOOP class
            # (re-reading an unchanged row / polling a stuck result) that natural_thrash_gate's
            # error grammar misses (docs/175 §4 loop-vs-branch). Independent of CONSULT/INTERVENTION
            # and of DOS_REWIND_NATURAL — a host may run both (a tool can loop on one input, branch
            # on another). REPEATING stays WARN; only STALLED prunes (the safe-signal line).
            self._stall_rewind_on = _os.environ.get("DOS_STALL", "0") not in ("0", "false", "")
            self._stall_done: set = set()               # tool_names already stall-rewound (one-shot/tool)
            # docs/176 §6 — the RESTART arm: on a THRASH, RE-ORCHESTRATE a fresh window instead of
            # SUBTRACTING to an anchor. rewind keeps [System, Human, …good prefix…, note]; restart keeps
            # ONLY [System, Human, (note?)] — the one move that DROPS the prefix, so the only one that can
            # escape an UPSTREAM omission (the cause that livelocked rewind: none 49.2 / rewind 44.9). The
            # seed (DOS_RESTART_SEED) prepends the SAME byte-clean no-good note rewind re-enters with —
            # built from the gym's OWN block error bytes (THIRD_PARTY), the wrapper authors no correction.
            # Mutually exclusive with DOS_REWIND (both read _block_counts>=2): a clean A/B runs one or the
            # other, never both. Env-gated like every other arm — NOT a subclass (the audit's fix).
            self._restart_on = _os.environ.get("DOS_RESTART", "0") not in ("0", "false", "")
            self._restart_seed = _os.environ.get("DOS_RESTART_SEED", "0") not in ("0", "false", "")
            self._restarted_tools: set = set()          # tool_names already restarted (one-shot/tool)
            self._restarts_done = 0
            self._restart_ledger = {"restart_events": 0, "turns_discarded": 0,
                                    "prefix_tokens_repaid": 0}
            self._block_counts: Dict[str, int] = {}   # tool_name -> times blocked this run (thrash)
            self._rewinds_done = 0                      # how many subtracts this run
            self._dos_stats = {"calls_seen": 0, "nudges_injected": 0, "blocks": 0,
                               "defers": 0, "observes": 0, "mints_injected": 0,
                               "precursor_warns": 0, "dangling_warns": 0,
                               "terminal_error_warns": 0, "rewinds": 0,
                               "schema_refresh_warns": 0,
                               "intervention_mode": self._intervention_mode.value}

        def get_result_metadata(self) -> Dict[str, Any]:
            md = dict(super().get_result_metadata())
            md["dos_arg_provenance"] = dict(self._dos_stats)
            if self._restart_on:
                md["dos_restart"] = {"restarts_done": self._restarts_done,
                                     "seeded": self._restart_seed, **self._restart_ledger}
            return md

        def _maybe_inject_mint(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
            """Controlled mint injection (the docs/143 live demonstration). With prob
            `mint_rate`, perturb ONE id-shaped FK arg into a right-shape / wrong-content
            value — simulating a weaker model's 'Incorrect ID Resolution' on the real
            harness. Deterministic per (seed, task), so the paired R0/R1 arms inject the
            SAME mints and the only difference is the nudge. Never touches a value the
            detector wouldn't see as an id (so it is a genuine FK error, not noise)."""
            for k, v in args.items():
                if not isinstance(v, (str, int)):
                    continue
                s = str(v)
                if len(s) < 3 or not any(c.isdigit() for c in s) or " " in s:
                    continue
                if "_id" not in k.lower() and "id" != k.lower() and not any(
                    c.isalpha() for c in s
                ):
                    # bias to FK-ish slots / prefixed ids — avoid perturbing a quantity
                    continue
                if self._rng.random() < self._mint_rate:
                    minted = "".join(
                        str(self._rng.randint(0, 9)) if c.isdigit() else c for c in s
                    )
                    if minted != s:
                        args[k] = minted if isinstance(v, str) else (
                            int(minted) if minted.isdigit() else minted
                        )
                        self._dos_stats["mints_injected"] += 1
                        return args  # one mint per call (matches the simulator)
            return args

        def _maybe_rewind(self, messages, tool_results, conversation_flow,
                          verdict, tool_name, tool_args) -> bool:
            """docs/171 — SUBTRACT the dead-end turns instead of APPENDING a synthetic correction.

            Called on a THRASH (2nd block on the same tool = convergence.THRASHING). Uses the REAL
            kernel verdict `dos.rewind.rewind_plan` to place the rewind anchor at the last VERIFIED
            tool result, then truncates the live message history back to that anchor and re-enters
            with the kernel's byte-clean no-good note. Returns True iff a rewind was enacted (the
            caller then `continue`s without appending the synthetic). On UNANCHORED / NO_REWIND
            (no verified state to rewind to) it returns False so the caller falls through to the
            ordinary BLOCK append — fail-safe: never rewind to a turn the kernel did not stamp.

            The no-good note carries ONLY un-forged bytes (the §6 contract): a VERIFY_NOT_SHIPPED
            token over the unresolved id (a structured field the kernel computed) + the gym's OWN
            blocked-unresolved-id error excerpt (THIRD_PARTY — the env authored it). Never prose.
            """
            from dos.rewind import TurnRef, digest_turn
            from dos.intent_ledger import SuspendCheckpoint
            from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED

            # 1) Map the live tool stream → rewind.py TurnRefs (index, digest). A "turn" is a
            #    real tool_result; a synthetic (dos_blocked) result is a dead end, never an anchor.
            def _is_verified(tr):
                # A real (non-synthetic, non-error) tool result that succeeded. The gym wraps every
                # result as tr["result"] = {"success": bool, "result": <payload>} — so the success
                # flag is at the OUTER level, NOT inside the payload (an earlier version read the
                # payload and never saw success=True → every anchor UNANCHORED → no rewind fired).
                # The struct-error guard is the docs/172 anchor-bug fix, PORTED here from the natural
                # path (verify wf): the gym sets outer success=True even on isError:true failures
                # (measured 211/211), so a real env-error turn (e.g. a 409 conflict interleaved
                # before the 2nd mint-block) must be REJECTED as an anchor or the rewind would
                # truncate back to a FAILED turn (the last-known-good purpose defeated).
                if tr.get("dos_blocked"):
                    return False
                if _is_struct_error(_result_text(tr)):
                    return False
                r = tr.get("result", {})
                if not isinstance(r, dict):
                    return False
                if r.get("success") is True:
                    return True
                inner = r.get("result", {})
                if isinstance(inner, dict):
                    if inner.get("success") is True:
                        return True
                    st = str(inner.get("status", "")).lower()
                    if st and "error" not in st and "blocked" not in st:
                        return True
                return False

            turns = tuple(
                TurnRef(i, digest_turn(json.dumps(
                    {"t": tr.get("tool_name"), "s": str(tr.get("result"))[:64]}, sort_keys=True)))
                for i, tr in enumerate(tool_results)
            )
            # anchor = last VERIFIED tool result (last-known-good). None → UNANCHORED.
            anchor_idx = -1
            for i in range(len(tool_results) - 1, -1, -1):
                if _is_verified(tool_results[i]):
                    anchor_idx = i
                    break
            if anchor_idx >= 0:
                cp = SuspendCheckpoint(turn_index=anchor_idx,
                                       transcript_digest=turns[anchor_idx].digest, present=True)
            else:
                cp = SuspendCheckpoint.absent()

            # 2) FIRE = THRASHING (a tool blocked ≥2× = the agent re-entered the same hole). The
            #    no-good note: a typed token over the unresolved id + the env's own error bytes.
            unresolved = ",".join(verdict.unsupported) or "id"
            env_err = (
                f"`{tool_name}` was NOT executed: it references id(s) ({unresolved}) that never "
                f"appeared in any prior tool result — they look invented, not resolved. Look the "
                f"id up with a read/query tool, then retry."
            )
            tokens = (VerdictToken(KIND_VERIFY_NOT_SHIPPED,
                                   {"sha": f"{unresolved}=never-appeared"}),)
            return self._enact_rewind(
                messages, tool_results, conversation_flow, tool_name,
                turns, cp, tokens, env_err, anchor_idx, kind="mint",
            )

        def _restart_env_excerpt(self, tool_results, tool_name) -> str:
            """The gym's OWN latest block-error bytes for `tool_name` — NOT a fabricated directive.

            The audit's provenance fix: the rewind mint-path builds a 'Look the id up… then retry'
            sentence in-line and tags it THIRD_PARTY (dos_react.py:659-663) — wrapper-authored advice
            wearing an env tag, the exact mislabel the kernel floor forbids. The restart seed instead
            reads the env's REAL recorded error text (the gym's `blocked_unresolved_id` payload, which
            the BLOCK branch already fed back as the synthetic result), so the THIRD_PARTY tag is HONEST
            — the same source `_enact_rewind` reads. Falls back to a STRUCTURAL fact (no directive prose)
            if no recorded error is found, so the note never carries an authored corrective ACTION."""
            for tr in reversed(tool_results):
                if str(tr.get("tool_name")) == tool_name:
                    txt = _result_text(tr)
                    if _is_struct_error(txt) or tr.get("dos_blocked"):
                        return txt[:400]
            # structural fallback — names the WALL (id never appeared), never the corrective action
            return f"`{tool_name}` references id(s) that never appeared in any prior tool result."

        def _maybe_restart(self, messages, tool_results, conversation_flow,
                           verdict, tool_name, tool_args) -> bool:
            """docs/176 §6 — RE-ORCHESTRATE a fresh window instead of SUBTRACTING to an anchor.

            Called on a THRASH (2nd block on the same tool). DISCARDS the in-flight window back to
            [System, Human] (+ the byte-clean no-good note when seeded) and returns True so the caller
            `continue`s — the outer loop re-invokes the LLM on the FRESH window next iteration. Returns
            False only when the trigger is not met (fail-safe: never restart a window we should not).
            One-shot per tool (the `_restarted_tools` cap), exactly like the rewind one-shot guard —
            without it a tool that keeps thrashing post-restart would re-restart every block and
            livelock the loop in cold-starts.

            The seeded note rides the REAL kernel `rewind.build_no_good_note`: a VERIFY_NOT_SHIPPED
            token over the unresolved id (a structured field the kernel computed) + the gym's OWN block
            error bytes (THIRD_PARTY, redacted of reflected input at the same mint point as the rewind
            path). The wrapper authors NO correction and NO directive — the audit's provenance fix."""
            from restart_arm import (build_fresh_window, restart_decision,
                                     restart_ledger_delta)
            if not restart_decision(
                restart_on=self._restart_on,
                block_count=self._block_counts.get(tool_name, 0),
                already_restarted_tools=self._restarted_tools,
                tool_name=tool_name,
            ):
                return False

            note_text = None
            if self._restart_seed:
                from dos.rewind import build_no_good_note, EnvExcerpt
                from dos.log_source import Accountability
                from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED
                unresolved = ",".join(verdict.unsupported) or "id"
                tokens = (VerdictToken(KIND_VERIFY_NOT_SHIPPED,
                                       {"sha": f"{unresolved}=never-appeared"}),)
                env_err = _redact_reflected_input(
                    self._restart_env_excerpt(tool_results, tool_name))
                note = build_no_good_note(
                    tokens, EnvExcerpt(env_err, Accountability.THIRD_PARTY))
                note_text = "[DOS restart] " + " | ".join(note.render_lines())

            from langchain_core.messages import HumanMessage  # type: ignore
            discarded = messages[2:]
            delta = restart_ledger_delta(discarded)
            fresh = build_fresh_window(
                messages[0], messages[1],
                no_good_note_text=note_text,
                human_factory=lambda t: HumanMessage(content=t),
            )
            messages[:] = fresh  # in-place replace so the loop's reference stays valid

            self._restarted_tools.add(tool_name)
            self._restarts_done += 1
            for k, v in delta.items():
                self._restart_ledger[k] += v
            conversation_flow.append({
                "type": "dos_restart", "tool_name": tool_name,
                "seeded": self._restart_seed, **delta,
            })
            return True

        def _maybe_rewind_natural(self, messages, tool_results, conversation_flow,
                                  tool_name, n_failures, env_excerpt) -> bool:
            """docs/172 — SUBTRACT a NATURAL fail-thrash (no mint, no arg_provenance).

            The mint-free sibling of `_maybe_rewind`. Called when `natural_thrash_gate` fired:
            the SAME tool produced a STRUCTURED env error >=2× and is in the hole right now.
            Drives the SAME `rewind.rewind_plan` to the last-VERIFIED anchor and truncates the
            transcript, but the no-good note carries the ENV's OWN latest error bytes
            (THIRD_PARTY — the gym authored them, `_is_struct_error`-matched) rather than an
            arg-provenance token. This is the SOTA-relevant trigger: it fires on the agent's
            natural dead-ending (~10% of runs), not an injected FK error (~0% naturally)."""
            from dos.rewind import TurnRef, digest_turn
            from dos.intent_ledger import SuspendCheckpoint
            from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED

            def _is_verified(tr):
                # A real (non-synthetic, non-error) tool result = a last-known-good anchor. The
                # gym sets outer `success: True` on EVERY result — INCLUDING `isError: true`
                # failures (measured: 46/46 natural errors carry outer success=True). So the
                # outer flag alone is NOT trustworthy: a struct-error result must be REJECTED as
                # an anchor, or the natural rewind would anchor to a FAILED turn (defeating the
                # last-known-good purpose). Read the env error envelope (`_is_struct_error`), the
                # same byte-clean grammar the gate fires on, before trusting the success flag.
                if tr.get("dos_blocked"):
                    return False
                if _is_struct_error(_result_text(tr)):
                    return False
                r = tr.get("result", {})
                if not isinstance(r, dict):
                    return False
                if r.get("success") is True:
                    return True
                inner = r.get("result", {})
                if isinstance(inner, dict):
                    if inner.get("success") is True:
                        return True
                    st = str(inner.get("status", "")).lower()
                    if st and "error" not in st and "blocked" not in st:
                        return True
                return False

            turns = tuple(
                TurnRef(i, digest_turn(json.dumps(
                    {"t": tr.get("tool_name"), "s": str(tr.get("result"))[:64]}, sort_keys=True)))
                for i, tr in enumerate(tool_results)
            )
            anchor_idx = -1
            for i in range(len(tool_results) - 1, -1, -1):
                if _is_verified(tool_results[i]):
                    anchor_idx = i
                    break
            if anchor_idx >= 0:
                cp = SuspendCheckpoint(turn_index=anchor_idx,
                                       transcript_digest=turns[anchor_idx].digest, present=True)
            else:
                cp = SuspendCheckpoint.absent()
            # The typed token names the natural-thrash fact (the tool failed N× un-recovered) —
            # a structured field the kernel computed, never prose. The env excerpt is the gym's
            # OWN latest error bytes (already `_is_struct_error`-matched at the gate).
            tokens = (VerdictToken(KIND_VERIFY_NOT_SHIPPED,
                                   {"sha": f"{tool_name}=failed-{n_failures}x-unrecovered"}),)
            return self._enact_rewind(
                messages, tool_results, conversation_flow, tool_name,
                turns, cp, tokens, env_excerpt, anchor_idx, kind="natural",
            )

        def _enact_rewind(self, messages, tool_results, conversation_flow, tool_name,
                          turns, cp, tokens, env_err, anchor_idx, *, kind: str) -> bool:
            """The shared SUBTRACT core for both rewind triggers (mint + natural).

            Builds the kernel rewind plan, and on REWIND truncates the live message history to
            the last-verified anchor + re-enters with the byte-clean no-good note. Returns True
            iff a rewind was enacted (UNANCHORED/NO_REWIND → False, caller falls back). The
            byte-contract lives HERE in one place: the note is the kernel's typed tokens + the
            floor-gated env excerpt (THIRD_PARTY) only — never a generated critique. The env
            excerpt is REDACTED of the gym's reflected-input echo at this single mint point, so
            the THIRD_PARTY tag is honest by construction for EVERY caller (the verify-wf
            byte-leak fix — the kernel floor trusts the tag and never inspects bytes, so the
            boundary must guarantee no agent-authored value rides a THIRD_PARTY tag)."""
            from dos.rewind import rewind_plan, FireVerdict, EnvExcerpt
            from dos.completion import Convergence
            from dos.log_source import Accountability
            from langchain_core.messages import HumanMessage, ToolMessage as _TM  # type: ignore

            plan = rewind_plan(
                turns, cp, FireVerdict.from_convergence(Convergence.THRASHING),
                verdict_tokens=tokens,
                env_excerpt=EnvExcerpt(_redact_reflected_input(env_err), Accountability.THIRD_PARTY),
            )
            if not plan.is_actionable:  # UNANCHORED / NO_REWIND → fall back
                return False

            # SUBTRACT — truncate the live message history back to the anchor tool result. The
            # messages list is [System, Human, AI, Tool, AI, Tool, ...]; keep everything up to and
            # including the ToolMessage for the anchor tool_result, drop the dead-end turns after.
            keep_tool_msgs = anchor_idx + 1  # keep ToolMessages [0..anchor_idx]
            seen_tool = 0
            cut = len(messages)
            for mi, m in enumerate(messages):
                if isinstance(m, _TM):
                    seen_tool += 1
                    if seen_tool == keep_tool_msgs:
                        cut = mi + 1
                        break
            if anchor_idx < 0:
                cut = 2  # no aligned ToolMessage yet → keep only the System+Human preamble
            del messages[cut:]

            note_text = "[DOS rewind] " + " | ".join(plan.no_good_note.render_lines())
            messages.append(HumanMessage(content=note_text))
            conversation_flow.append({
                "type": "dos_rewind",
                "kind": kind,
                "tool_name": tool_name,
                "rewind_to_turn": plan.rewind_to_turn,
                "dropped_turns": list(plan.dropped_turns),
                "no_good_note": list(plan.no_good_note.render_lines()),
            })
            self._rewinds_done += 1
            return True

        def _post_dispatch_rewinds(self, messages, tool_results, conversation_flow,
                                   tool_name) -> bool:
            """The POST-dispatch SUBTRACT triggers (natural fail-thrash + STALLED loop). Returns
            True iff a rewind fired (the caller then breaks the tool-call loop).

            CRITICAL (the CONSULT=0 firing bug, found 2026-06-06): these triggers are INDEPENDENT
            of arg_provenance / CONSULT — they read the post-dispatch ENV failure stream, not a
            mint verdict. But the `rewind_natural`/`stall` arms set DOS_CONSULT=0, which takes the
            early `if not self._consult:` dispatch branch and `continue`s BEFORE the normal-branch
            gate ran — so the gate was dead code for exactly the arms that use it (0 live fires
            despite 11/43 runs where the gate would fire). Calling this helper from BOTH branches
            is the fix: the natural/stall SUBTRACT now fires in the un-consulted (mint-free) regime
            it was built for. Mirrors the original mint-arm `_is_verified` live-smoke bug class."""
            # docs/200/205 — the curable-CONVERSION re-surface (ADDITIVE, error-BRANCH class). Same
            # natural_thrash_gate trigger as the rewind, but instead of SUBTRACTING it APPENDS the
            # env's OWN schema/reference/state corrective as a forcing function (docs/172 found append
            # > subtract live; the subtract livelocked on upstream omission). Placed BEFORE the rewind
            # block so a clean A/B runs one arm or the other (both read the same gate; a host would not
            # enable both). Byte-clean: schema_refresh.refresh_directive authors only the framing, every
            # corrective byte is the gym's (extract_corrective parses ENV bytes, raw is redacted of the
            # agent's reflected input). One-shot/tool. Returns False (advisory) — the loop continues so
            # the agent retries with the requirement surfaced; nothing is broken or substituted.
            if self._schema_refresh_on and tool_name not in self._schema_refresh_done:
                gate = natural_thrash_gate(tool_results, tool_name)
                if gate is not None:
                    self._schema_refresh_done.add(tool_name)
                    # Read the corrective from the LATEST full error result (not the gate's 200-char
                    # excerpt — the docs/200 §5 conservative-read: a long missing-field list is clipped
                    # in the excerpt). Mirrors natural_thrash_gate's own `own[-1]` latest-error pick.
                    own_errs = [tr for tr in tool_results
                                if str(tr.get("tool_name", "")) == tool_name
                                and not _is_blocked_result(tr)
                                and _is_struct_error(_result_text(tr))]
                    if own_errs:
                        from schema_refresh import extract_corrective, refresh_directive
                        corr = extract_corrective(_result_text(own_errs[-1]))
                        directive = refresh_directive(corr, tool_name)
                        if directive:
                            messages.append(HumanMessage(content=f"[DOS] {directive}"))
                            conversation_flow.append({
                                "type": "dos_schema_refresh",
                                "tool_name": tool_name,
                                "kind": corr.kind,
                                "n_fail": gate[0],
                            })
                            self._dos_stats["schema_refresh_warns"] += 1
                            # additive — do NOT return True (that would short-circuit a subtract); the
                            # directive rides into the next turn alongside the unchanged history.

            # docs/172 — the NATURAL fail-thrash rewind (error-BRANCH class). Reads tr['result']
            # (env-authored), never response.content. One rewind per tool per run.
            if self._rewind_natural_on and tool_name not in self._natural_thrash_done:
                gate = natural_thrash_gate(tool_results, tool_name)
                if gate is not None:
                    n_fail, env_excerpt = gate
                    self._natural_thrash_done.add(tool_name)
                    if self._maybe_rewind_natural(messages, tool_results, conversation_flow,
                                                  tool_name, n_fail, env_excerpt):
                        self._dos_stats["rewinds"] += 1
                        return True

            # docs/176 §6.1 — the DOMAIN-FREE STALLED rewind (byte-identical LOOP class). The kernel
            # tool_stream.classify_stream → STALLED verdict; its own pre-stall anchor + enact.
            if self._stall_rewind_on and tool_name not in self._stall_done:
                from stall_trigger import stall_thrash_gate, enact_stall_rewind
                sgate = stall_thrash_gate(tool_results, tool_name)
                if sgate is not None:
                    s_run, s_excerpt, s_anchor = sgate
                    self._stall_done.add(tool_name)
                    if enact_stall_rewind(messages, tool_results, conversation_flow,
                                          tool_name, s_run, s_excerpt, s_anchor,
                                          human_factory=lambda t: HumanMessage(content=t)):
                        self._dos_stats["rewinds"] += 1
                        return True
            return False

        async def execute(self) -> Dict[str, Any]:
            messages = [
                SystemMessage(content=self.config.system_prompt),
                HumanMessage(content=self.config.user_prompt),
            ]
            task_text = f"{self.config.system_prompt}\n{self.config.user_prompt}"
            conversation_flow = [
                {"type": "system_message", "content": self.config.system_prompt},
                {"type": "user_message", "content": self.config.user_prompt},
            ]
            tools_used: List[str] = []
            tool_results: List[Dict[str, Any]] = []

            for iteration in range(self.max_iterations):
                response = await self.llm_client.invoke_with_tools(
                    messages, self.available_tools
                )
                messages.append(response)
                usage_metadata = getattr(response, "usage_metadata", {}) or {}
                response_metadata = getattr(response, "response_metadata", {}) or {}
                conversation_flow.append({
                    "type": "ai_message",
                    "content": response.content,
                    "usage_metadata": usage_metadata,
                    "response_metadata": response_metadata,
                    "tool_calls": [
                        {"name": tc["name"], "args": tc["args"]}
                        for tc in (response.tool_calls or [])
                    ],
                })

                if not response.tool_calls or len(response.tool_calls) == 0:
                    # --- docs/150/152: the DANGLING-INTENT consult at the STOP event -----------
                    # The agent emitted NO tool call this turn — it is stopping. Did its last
                    # narration admit an open obligation with nothing executed after? If so, and we
                    # have not already done this once, re-surface the agent's OWN abandoned sentence
                    # (a HumanMessage — there is no tool_call_id to anchor a ToolMessage at a
                    # no-tool-call stop) and DO NOT break: run one more iteration so it can finish or
                    # confirm. `results_after_turn=0` is structural here (the loop only reaches this
                    # branch when the terminal turn produced no calls → nothing ran after it).
                    if self._dangling_on and not self._dangled:
                        from dos.dangling_intent import (
                            DEFAULT_POLICY as _DI_POLICY, StopEvidence, classify_stop,
                        )
                        di = classify_stop(
                            StopEvidence(
                                final_turn_text=str(response.content or ""),
                                results_after_turn=0,
                            ),
                            _DI_POLICY,
                        )
                        if di.is_dangling:
                            self._dangled = True
                            self._dos_stats["dangling_warns"] += 1
                            messages.append(HumanMessage(content=(
                                f"[DOS] Your final message says: \"…{di.matched_cue}…\" — and no "
                                f"tool ran after it. It looks like you stopped with work still "
                                f"intended. Continue and finish that step now if it is not done, "
                                f"or confirm explicitly that the task is complete."
                            )))
                            conversation_flow.append({
                                "type": "dos_dangling_warn",
                                "matched_cue": di.matched_cue,
                                "reason": di.reason,
                            })
                            continue  # one more turn — the re-surface (DETECT, not a plan)
                    # --- docs/158: the TERMINAL-ERROR consult at the STOP event ----------------
                    # Did the env-authored bytes of the last few tool results carry a STRUCTURED
                    # error envelope that no later same-tool success recovered? If so, re-surface
                    # ONLY the env error excerpt + the failing tool name ONCE (a HumanMessage —
                    # byte-clean: the error bytes are the gym's, the agent did not author them) and
                    # DO NOT break: run one more iteration so it can fix/retry or confirm.
                    if self._terminal_error_on and not self._terminal_errored:
                        gate = terminal_error_gate(tool_results)
                        if gate is not None:
                            _te_tool, _te_excerpt, _te_nudge = gate
                            self._terminal_errored = True
                            self._dos_stats["terminal_error_warns"] += 1
                            messages.append(HumanMessage(content=_te_nudge))
                            conversation_flow.append({
                                "type": "dos_terminal_error_warn",
                                "tool_name": _te_tool,
                                "excerpt": _te_excerpt,
                            })
                            continue  # one more turn — the re-surface (DETECT, not a plan)
                    break

                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]

                    # --- controlled mint injection (live A/B only; rate=0 by default) ----
                    if self._mint_rate > 0 and is_mutating_tool(
                        tool_name, mutating_tools=self._mutating_tools,
                        read_tools=self._read_tools,
                    ):
                        tool_args = self._maybe_inject_mint(tool_name, dict(tool_args))

                    # --- the DOS arg-provenance consult (the one change vs react) -------
                    self._dos_stats["calls_seen"] += 1
                    if not self._consult:
                        # R0-equivalent arm under injection: dispatch as-is (no nudge), so
                        # the injected mints corrupt the DB exactly as a weaker model's would.
                        exec_result = await self._execute_tool_call(tool_name, tool_args)
                        tool_result = exec_result["result"]
                        if tool_name not in tools_used:
                            tools_used.append(tool_name)
                        tool_results.append({
                            "tool_name": tool_name, "arguments": tool_args,
                            "result": tool_result, "gym_server": exec_result["gym_server"],
                        })
                        messages.append(ToolMessage(
                            content=json.dumps(tool_result.get("result", {}), default=str),
                            tool_call_id=tool_call.get("id", ""),
                        ))
                        conversation_flow.append({
                            "type": "tool_result", "tool_name": tool_name,
                            "result": tool_result, "gym_server": exec_result["gym_server"],
                        })
                        # docs/172 §0.6 FIX — the mint-free SUBTRACT triggers (natural + stall) MUST
                        # run here too: the rewind_natural/stall arms set CONSULT=0 and take THIS
                        # branch, so without this call the gate was dead code for exactly the arms
                        # that use it (the CONSULT=0 firing bug). These triggers are independent of
                        # arg_provenance — they read the post-dispatch ENV failure stream.
                        if self._post_dispatch_rewinds(messages, tool_results,
                                                       conversation_flow, tool_name):
                            break  # transcript SUBTRACTED; outer loop re-invokes on the rewound transcript
                        continue
                    verdict = evaluate_tool_call(
                        tool_name, tool_args, task_text, tool_results,
                        mutating_tools=self._mutating_tools, read_tools=self._read_tools,
                    )
                    # --- docs/143 §13: the typed, confidence-gated intervention -----------
                    # The kernel RECOMMENDS a rung (choose_intervention); the wrapper ACTS on
                    # it (the actuation the kernel only proposes — the PDP/PEP split). A fired
                    # verdict is capped at <=1 re-injection per (tool, arg-values): a stubborn
                    # re-mint falls through to OBSERVE the second time (nudge, don't livelock).
                    from dos.intervention import (
                        Intervention, choose_intervention, synthetic_corrective_result,
                    )
                    decision = choose_intervention(verdict, self._int_policy)
                    fired = bool(verdict.unsupported)
                    capped = False
                    if fired:
                        key = tool_name + "|" + "|".join(
                            str(tool_args.get(a, "")) for a in verdict.unsupported
                        )
                        capped = self._nudge_counts.get(key, 0) >= self.max_nudges_per_value
                        if not capped:
                            self._nudge_counts[key] = self._nudge_counts.get(key, 0) + 1
                    action = (
                        Intervention.OBSERVE if (not fired or capped)
                        else decision.intervention
                    )

                    if action is Intervention.DEFER:
                        # SKIP + re-prompt — the agent spends its turn re-resolving (the
                        # original −9pp posture; opt-in only). DISRUPTIVE.
                        messages.append(ToolMessage(
                            content=build_nudge_text(verdict, tool_name),
                            tool_call_id=tool_call.get("id", ""),
                        ))
                        conversation_flow.append({
                            "type": "dos_defer", "tool_name": tool_name,
                            "unsupported": list(verdict.unsupported),
                        })
                        self._dos_stats["nudges_injected"] += 1
                        self._dos_stats["defers"] += 1
                        continue  # turn SPENT, no DB effect

                    if action is Intervention.BLOCK:
                        # NON-DISRUPTIVE PEP (docs/143 §13.4): refuse the minted call but feed
                        # back the kernel's SYNTHETIC corrective result in place of the
                        # mutation — the agent gets "id unresolved; use a read tool" on the
                        # SAME turn, the real call never fires, the DB is untouched, and the
                        # turn is NOT lost. Stamped dos_blocked so build_prior_results excludes
                        # it from the corpus (the anti-laundering guard).
                        self._block_counts[tool_name] = self._block_counts.get(tool_name, 0) + 1

                        # docs/171 — THE REWINDABLE FIX LOOP. A 2nd block on the SAME tool is a
                        # THRASH (convergence.THRASHING): the agent re-entered the same hole, and
                        # appending ANOTHER synthetic correction is exactly the −4/task accretion
                        # BLOCK lost on. Instead SUBTRACT: place the rewind anchor at the last
                        # VERIFIED tool result, truncate the message history back to it, and
                        # re-enter with the kernel's BYTE-CLEAN no-good note. No content authored.
                        if self._rewind_on and self._block_counts[tool_name] >= 2:
                            rewound = self._maybe_rewind(
                                messages, tool_results, conversation_flow,
                                verdict, tool_name, tool_args,
                            )
                            if rewound:
                                self._dos_stats["rewinds"] += 1
                                self._dos_stats["blocks"] += 1
                                continue  # transcript SUBTRACTED, re-entered with the no-good note

                        # docs/176 §6 — the RESTART sibling of the rewind hook: on the SAME thrash,
                        # RE-ORCHESTRATE a fresh window instead of subtracting (drops the whole prefix
                        # → the only move that escapes an UPSTREAM omission). Mutually exclusive with
                        # rewind above (a clean arm sets one flag, never both). One-shot per tool.
                        if self._restart_on and self._block_counts[tool_name] >= 2:
                            restarted = self._maybe_restart(
                                messages, tool_results, conversation_flow,
                                verdict, tool_name, tool_args,
                            )
                            if restarted:
                                self._dos_stats["blocks"] += 1
                                continue  # window DISCARDED, re-orchestrated from [System, Human, (note)]

                        hint = ", ".join(sorted(self._read_tools)[:3]) if self._read_tools else ""
                        synthetic = synthetic_corrective_result(
                            verdict, tool_name, read_tool_hint=hint)
                        if tool_name not in tools_used:
                            tools_used.append(tool_name)
                        tool_results.append({
                            "tool_name": tool_name, "arguments": tool_args,
                            "result": {"result": synthetic}, "gym_server": None,
                            "dos_blocked": True,
                        })
                        messages.append(ToolMessage(
                            content=json.dumps(synthetic, default=str),
                            tool_call_id=tool_call.get("id", ""),
                        ))
                        conversation_flow.append({
                            "type": "dos_block", "tool_name": tool_name,
                            "unsupported": list(verdict.unsupported),
                        })
                        self._dos_stats["nudges_injected"] += 1
                        self._dos_stats["blocks"] += 1
                        continue  # turn PRESERVED (synthetic result fed), no DB effect

                    if action is Intervention.WARN:
                        # INFORM + still dispatch — the model sees the nudge (and may self-
                        # correct NEXT turn) without losing this one. The advisory-only default.
                        messages.append(ToolMessage(
                            content=build_nudge_text(verdict, tool_name),
                            tool_call_id=tool_call.get("id", ""),
                        ))
                        conversation_flow.append({
                            "type": "dos_nudge", "tool_name": tool_name,
                            "unsupported": list(verdict.unsupported),
                        })
                        self._dos_stats["nudges_injected"] += 1
                    elif fired and action is Intervention.OBSERVE:
                        # a fired verdict that capped / OBSERVE-mode — record, dispatch silently.
                        self._dos_stats["observes"] += 1
                    # OBSERVE + WARN fall through to the real dispatch (unchanged below):

                    # --- docs/147: the PRECURSOR-PRESENCE consult (additive, WARN-only) --------
                    # Did a tool whose name is on the hand-authored mandated-precursor set produce
                    # a result earlier in the stream? On REFUTED (a Missing-Prerequisite-Lookup),
                    # attach a WARN re-surfacing the requirement — the call STILL dispatches (turn
                    # preserved, the only rung this gate can emit). Independent of arg_provenance:
                    # a call can be both a mint AND a prereq-skip; both floor to WARN, so the union
                    # is two reminders, never an escalation (docs/147 §5).
                    if self._precursor_on and self._precursor_grammar is not None:
                        from dos.precursor_gate import (
                            CallStream, MutatingCall, PriorCall, classify_call as pc_classify,
                            precursor_intervention,
                        )
                        is_mut = is_mutating_tool(
                            tool_name, mutating_tools=self._mutating_tools,
                            read_tools=self._read_tools,
                        )
                        pstream = CallStream(calls=tuple(
                            PriorCall(tool_name=str(tr.get("tool_name", "")))
                            for tr in tool_results
                        ))
                        pverdict = pc_classify(
                            MutatingCall(tool_name=tool_name, is_mutating=is_mut),
                            pstream, self._precursor_grammar,
                        )
                        pdecision = precursor_intervention(pverdict)
                        if pdecision is not None:  # REFUTED → WARN (the only fired rung)
                            messages.append(ToolMessage(
                                content=(
                                    f"[DOS precursor] `{tool_name}` is about to mutate, but its "
                                    f"mandated precursor(s) {list(pverdict.required)} produced no "
                                    f"result yet. The policy requires that lookup first — issue "
                                    f"it, then retry. (The call still proceeds.)"
                                ),
                                tool_call_id=tool_call.get("id", ""),
                            ))
                            conversation_flow.append({
                                "type": "dos_precursor_warn", "tool_name": tool_name,
                                "required": list(pverdict.required),
                            })
                            self._dos_stats["precursor_warns"] += 1

                    exec_result = await self._execute_tool_call(tool_name, tool_args)
                    tool_result = exec_result["result"]
                    target_gym = exec_result["gym_server"]
                    if tool_name not in tools_used:
                        tools_used.append(tool_name)
                    tool_results.append({
                        "tool_name": tool_name, "arguments": tool_args,
                        "result": tool_result, "gym_server": target_gym,
                    })
                    messages.append(ToolMessage(
                        content=json.dumps(tool_result.get("result", {}), default=str),
                        tool_call_id=tool_call.get("id", ""),
                    ))
                    conversation_flow.append({
                        "type": "tool_result", "tool_name": tool_name,
                        "result": tool_result, "gym_server": target_gym,
                    })

                    # --- docs/172/176: the POST-dispatch mint-free SUBTRACT triggers ----------
                    # natural fail-thrash (error-BRANCH) + STALLED (byte-identical LOOP). Factored
                    # into _post_dispatch_rewinds so it runs identically here AND in the CONSULT=0
                    # branch above (the docs/172 §0.6 firing-bug fix). On a fire the transcript was
                    # truncated under this response's remaining tool_calls → break and re-invoke.
                    if self._post_dispatch_rewinds(messages, tool_results,
                                                   conversation_flow, tool_name):
                        break

            return {
                "final_response": messages[-1].content if messages else "",
                "conversation_flow": conversation_flow,
                "tools_used": tools_used,
                "tool_results": tool_results,
                "messages": messages,
            }

    return DosReactOrchestrator
