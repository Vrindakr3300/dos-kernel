"""The boundary reader: a Toolathlon-Trajectories record -> frozen DOS detector inputs.

This is the I/O-at-the-edge half of the `dos` idiom (mirrors `claim_extract.*_from_transcript`,
the `git_delta`/`journal_delta` readers): it parses the record's bytes and assembles the *frozen
data* the pure kernel verdicts (`dangling_intent.classify_stop`, `tool_stream.classify_stream`)
consume. The kernel hashes/reads nothing live — this module does the reading, the kernel does the
deciding.

Record schema (VERIFIED 2026-06-05 against `gemini-2.5-flash_1.jsonl` line 1):

    {
      "modelname_run": "gemini-2.5-flash_1",
      "task_name":     "train-ticket-plan",
      "task_status":   "{\"preprocess\":\"done\",\"running\":\"done\",\"evaluation\":false}",  # JSON STRING
      "config":        "{...}",                                                                # JSON STRING
      "tool_calls":    "{\"tools\":[...]}",                                                     # JSON STRING (the AVAILABLE tool schema, not dispatched calls)
      "messages":      [ {role,content,tool_calls?}, {role:"tool",content,tool_call_id}, ... ], # list OR JSON string
      "key_stats": {...}, "agent_cost": {...}, ...
    }

`messages` is OpenAI-style chat: `assistant` turns carry `content` + optional
`tool_calls=[{id,function:{name,arguments}}]`; each dispatched call is answered by a `tool` message
with the same `tool_call_id` and the result bytes in `content`. The env (the MCP gateway) authored
the `tool` message content — the load-bearing `result_digest` provenance (`tool_stream` §5a).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from dos.dangling_intent import StopEvidence
from dos.tool_stream import StreamStep, ToolStream


# ---------------------------------------------------------------------------
# The parsed record — a thin typed view over one JSONL line.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Trajectory:
    """One replayed run: its identity, the conversation, and the THIRD-PARTY label.

      model_run   — e.g. "gemini-2.5-flash_1" (model + run index).
      task_name   — e.g. "train-ticket-plan".
      passed      — the independent verifier's verdict: `task_status.evaluation` (True/False/None).
                    None = the verifier did not produce a boolean (preprocess/running not done, or
                    the task errored) — excluded from precision (it is neither a confirmed pass nor
                    a confirmed fail). This is the un-forgeable oracle DOS does not own.
      messages    — the OpenAI-style chat turn list, in order.
    """

    model_run: str
    task_name: str
    passed: Optional[bool]
    messages: tuple[dict, ...]

    @property
    def model(self) -> str:
        """The model name without the run suffix ('gemini-2.5-flash_1' -> 'gemini-2.5-flash')."""
        base = self.model_run
        if "_" in base and base.rsplit("_", 1)[1].isdigit():
            return base.rsplit("_", 1)[0]
        return base


def _coerce_json(v: Any) -> Any:
    """A field that may be a JSON *string* (the dataset's `task_status`/`messages` shape) or already
    parsed. Returns the parsed value; a bare non-JSON string is returned unchanged."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


def parse_record(rec: dict) -> Trajectory:
    """Parse one raw JSONL record into a `Trajectory`. Pure given the dict (the caller did the I/O).

    Tolerant of the two shapes seen in the wild: `messages`/`task_status` as JSON strings (the
    published dataset) or as already-decoded objects. An absent/malformed `evaluation` -> `passed`
    None (excluded from precision), never a guess.
    """
    status = _coerce_json(rec.get("task_status")) or {}
    passed = status.get("evaluation") if isinstance(status, dict) else None
    if not isinstance(passed, bool):
        passed = None
    raw_msgs = _coerce_json(rec.get("messages")) or []
    messages = tuple(m for m in raw_msgs if isinstance(m, dict))
    return Trajectory(
        model_run=str(rec.get("modelname_run", "")),
        task_name=str(rec.get("task_name", "")),
        passed=passed,
        messages=messages,
    )


# ---------------------------------------------------------------------------
# dangling_intent boundary: the terminal narration + the acted-after corroborator.
# ---------------------------------------------------------------------------
def _is_local_noop_tool(name: str) -> bool:
    """Toolathlon ships local bookkeeping tools (`claim_done`, context/history mgmt) that are NOT
    env mutations — a `tool` result for one of these is not the env-authored "the agent acted on the
    world" corroborator `dangling_intent` wants. Counting `claim_done`'s own result as "acted after"
    would mask the very premature-stop the detector targets (the agent calls claim_done, gets its
    ack, stops). So these are excluded from `results_after_turn`."""
    n = (name or "").strip().lower()
    return n in {
        "claim_done", "claimdone", "sleep",
        "manage_context", "handle_overlong_tool_outputs", "history",
    } or n.startswith(("context_", "history_", "manage_"))


def to_stop_evidence(traj: Trajectory) -> StopEvidence:
    """Assemble the `dangling_intent.StopEvidence` for the run's STOP event.

    The terminal narration is the LAST assistant message that authored text content (a trailing
    assistant turn whose only act was tool_calls has `content=None`; we walk back to the last one
    that actually SAID something — that is the narration the agent stopped on). `results_after_turn`
    counts ENV-authored tool results that landed after that narration — excluding local-noop tools
    (`claim_done` et al.), which are not acts on the world. >0 => the agent named a step and then
    acted => ABSTAIN by construction (the env-authored corroborator).
    """
    msgs = traj.messages
    # Find the last assistant turn that authored non-empty text content.
    last_text_idx = -1
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                last_text_idx = i
            elif isinstance(c, list):
                # some providers chunk content into parts; join text parts
                txt = "".join(
                    p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"
                )
                if txt.strip():
                    last_text_idx = i
    final_text = ""
    if last_text_idx >= 0:
        c = msgs[last_text_idx].get("content")
        if isinstance(c, list):
            final_text = "".join(
                p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            final_text = str(c or "")
    # Count env-authored (non-local-noop) tool results after the terminal narration.
    results_after = 0
    for m in msgs[last_text_idx + 1 :] if last_text_idx >= 0 else ():
        if m.get("role") == "tool" and not _is_local_noop_tool(_tool_msg_name(m, msgs)):
            results_after += 1
    return StopEvidence(final_turn_text=final_text, results_after_turn=results_after)


def _tool_msg_name(tool_msg: dict, messages: tuple[dict, ...]) -> str:
    """Resolve a `tool` message's tool name. The message itself usually lacks the name (it carries
    only `tool_call_id`); look it up from the assistant `tool_calls` that issued that id."""
    name = tool_msg.get("name")
    if isinstance(name, str) and name:
        return name
    tcid = tool_msg.get("tool_call_id")
    if not tcid:
        return ""
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or ():
            if isinstance(tc, dict) and tc.get("id") == tcid:
                fn = tc.get("function") or {}
                return str(fn.get("name", ""))
    return ""


# ---------------------------------------------------------------------------
# tool_stream boundary: the (tool, args_digest, result_digest) step stream.
# ---------------------------------------------------------------------------
def _digest(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


# --- the result_digest volatile-field normalizer (docs/157 §4, the #1 detector lift) -------
#
# WHY this is still byte-clean (the tool_stream §5a provenance line, preserved):
#   `result_digest` is ENV-authored — the gym MCP server produced the result bytes, the judged
#   agent did not. `tool_stream` is byte-clean BECAUSE the agent cannot forge the IDENTITY of its
#   own repeated env-results. This normalizer operates on those ENV-authored bytes by a FIXED,
#   content-blind rule (mask known volatile token SHAPES — an ISO timestamp, a UUID, a Search-ID).
#   It is harness config (a benchmark fact about which SaaS fields churn), NOT an agent-visible or
#   semantic input: the agent cannot influence WHICH bytes get masked, so the masked digest is
#   still an env-authored identity. The §5a line ("the agent did not author the identity of its
#   repeated output") holds verbatim — we are only making byte-equality robust to env nondeterminism
#   that was never agent-controlled.
#
# THE SAFE DIRECTION (why over-masking is the bug to fear, and how we cap it):
#   tool_stream's failure modes are asymmetric. UNDER-counting (the raw floor's known flaw: two
#   identical reads digest differently because of a volatile timestamp -> a real stall reads as
#   ADVANCING) only LOSES recall — it never accuses a healthy loop. OVER-masking (masking a field
#   that genuinely distinguishes two results -> two DIFFERENT outputs collapse to the same digest ->
#   a healthy advancing loop reads as REPEATING) would manufacture a FALSE fire, the dangerous
#   direction §5a guards. So every pattern below is anchored TIGHTLY to a token shape that is almost
#   never load-bearing for task semantics (a 14-digit PDF date, a canonical UUID, an ISO instant),
#   and we mask to a fixed sentinel rather than deleting — masking `2026-06-05T10:00:00` and
#   `2026-06-05T11:00:00` both to `<TS>` collapses two TIMES, but two results that differ in their
#   actual CONTENT still differ. When unsure, we DON'T add a pattern: a missed repeat is a cheaper
#   error than a fabricated one (the same fail-safe as `result_digest=None` breaking a run).
#
# This is the "conservative lower bound -> calibrated estimate" upgrade docs/157 §4 names; the raw
# floor stays reachable via `normalize=False` so the lower-bound number remains citable.

_VOLATILE_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    # ISO-8601 instant (date + 'T' + time, optional fractional seconds / Z / offset). The #1
    # churning field (12% of false-alarm-model results). Anchored to the full T-separated shape so a
    # bare date like a due-date "2026-06-05" in task content is NOT masked.
    ("<TS>", re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")),
    # Canonical UUID (8-4-4-4-12 hex). 7.8% of results. Request-ids / object-ids that churn per call.
    ("<UUID>", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    # PDF metadata date `D:YYYYMMDDhhmmss` (the pdf-tools `Creation date` field — observed churning
    # the same PDF's info block across re-reads). 14 digits after `D:`.
    ("<PDFDATE>", re.compile(r"D:\d{14}(?:[Zz]|[+-]\d{2}'?\d{2}'?)?")),
    # The pdf-tools search `Search ID: <hex>` line (a per-search id in free text, not a JSON key).
    ("<SEARCHID>", re.compile(r"(Search ID:\s*)[0-9a-fA-F]{4,}")),
    # ETag header value (rare, 0.1%, but pure-volatile when present).
    ("<ETAG>", re.compile(r'("?etag"?\s*[:=]\s*)"?[^",}\s]+', re.IGNORECASE)),
)


def normalize_result_bytes(content: str) -> str:
    """Mask known VOLATILE token shapes in an env-authored result string before hashing. PURE.

    A fixed, content-blind transform: replace each volatile pattern (ISO timestamp, UUID, PDF date,
    Search-ID, ETag) with a constant sentinel, so two semantically-identical re-reads that differ
    ONLY in a churning field digest identically — fixing `tool_stream`'s known UNDER-count (and the
    handful of false alarms a volatile re-read-then-recover produced). See the module note above for
    why this preserves the §5a byte-clean line: it operates on env-authored bytes by a rule the agent
    cannot influence, masks to a fixed sentinel (collapsing only the volatile token, never genuine
    content), and is deliberately conservative (a missed repeat is cheaper than a fabricated one).

    Idempotent and order-independent across the patterns (each masks a disjoint token shape).
    """
    out = content
    for sentinel, pat in _VOLATILE_PATTERNS:
        # ETag/Search-ID patterns capture a literal prefix group to preserve; others replace whole.
        if pat.groups:
            out = pat.sub(lambda m, s=sentinel: m.group(1) + s, out)
        else:
            out = pat.sub(sentinel, out)
    return out


def _normalize_args(arguments: Any) -> str:
    """Canonicalize a call's arguments to a stable digest input: parse the JSON (the dataset stores
    `function.arguments` as a JSON string), sort keys, compact-encode. A non-JSON arg string digests
    as-is. Sorted keys make two calls with the same args-in-different-order one identity."""
    parsed = _coerce_json(arguments)
    try:
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(arguments)


def to_tool_stream(traj: Trajectory, *, normalize: bool = True) -> ToolStream:
    """Assemble the `tool_stream.ToolStream` from the conversation.

    Walk messages in order; for each assistant `tool_calls` entry, pair it with the following `tool`
    message that carries the same `tool_call_id` and digest BOTH the normalized args (agent-authored)
    and the result content (env-authored). A call with no answering tool message gets
    `result_digest=None` (errored / no result) — which, per `tool_stream`, can never match another
    step, so it breaks a run (the fail-safe). Local-noop tools are dropped (not part of the
    env-progress stream).

    `normalize` (default True) runs `normalize_result_bytes` over each result before hashing — masking
    volatile env token shapes (timestamps, UUIDs, PDF dates, Search-IDs) so two semantically-identical
    re-reads digest identically. This is the docs/157 §4 lift: it fixes `tool_stream`'s known
    UNDER-count of true repeats AND the handful of volatile-field false alarms. It stays byte-clean
    (the §5a line) because it operates on ENV-authored bytes by a FIXED rule the agent cannot
    influence — see `normalize_result_bytes`. Pass `normalize=False` for the RAW conservative floor
    (the lower-bound number docs/157 cites alongside).
    """
    # index tool results by tool_call_id
    result_by_id: dict[str, str] = {}
    for m in traj.messages:
        if m.get("role") == "tool":
            tcid = m.get("tool_call_id")
            if tcid:
                result_by_id[tcid] = str(m.get("content", ""))
    steps: list[StreamStep] = []
    for m in traj.messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or ():
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = str(fn.get("name", ""))
            if not name or _is_local_noop_tool(name):
                continue
            args_d = _digest(_normalize_args(fn.get("arguments", "")))
            tcid = tc.get("id")
            res = result_by_id.get(tcid) if tcid else None
            res_d = _digest(normalize_result_bytes(res) if normalize else res) if res is not None else None
            steps.append(StreamStep(tool_name=name, args_digest=args_d, result_digest=res_d))
    return ToolStream(steps=tuple(steps))


# ---------------------------------------------------------------------------
# terminal_error boundary: the agent STOPPED while the env's last word was an ERROR (docs/158).
# ---------------------------------------------------------------------------
#
# The third byte-clean detector — the answer to "what catches the SILENT / FRONTIER failure?"
# (docs/158). dangling_intent reads the agent's terminal narration; tool_stream reads repeated
# env bytes; this reads the env's terminal ERROR ENVELOPE. It fires when a STRUCTURED env-authored
# error sits in the closing window of the run AND no later result from the SAME tool recovered to a
# success — i.e. the agent walked away from an unresolved environment failure.
#
# WHY byte-clean (the §5a line, same as tool_stream's `result_digest`): the error envelope is in a
# `tool` message's `content`, which the MCP GATEWAY authored, not the judged agent. A model cannot
# forge an env failure-envelope into a success, and "stop emitting the cue" is NOT available to it —
# the ENV emits the cue, not the agent. So this is provenance-of-an-env-authored-failure, never a
# forgeable "is the agent succeeding?" satisfaction predicate (the rejected hedge/confidence reader).
# It is the ONE in-trace signal the adversarial design (docs/158) found that helps on the
# confidently-wrong FRONTIER failure: measured on the full corpus it is ~95% precise, +18.8pp lift,
# and 75/76 of its catches are NET NEW (missed by both shipped detectors). It ADDS catches on the
# frontier (the strongest models) — +7/+9/+12 net-new at the top-4/≥0.30/top-10 capability cuts — but
# is NOT the first detector to reach the frontier (tool_stream already catches some there). The exact
# numbers are computed once in `additivity.py` (the SSOT, `--check`-enforced); see docs/158 §4.
#
# THE PRECISION RISK lives entirely in the GRAMMAR (not in who authored the bytes): a LOOSE match on
# 'error'/'failed'/'not found' would match env-authored PAYLOAD that legitimately contains those
# words (an arXiv abstract about "error rates", a "404" in fetched HTML). So the grammar is anchored
# TIGHTLY to STRUCTURED envelope shapes only (an MCP error code, an `isError:true` flag, a leading
# `Error:` text node, a Traceback, a nonzero exit code, a permission-denied) — the same tight-anchor
# discipline as the result_digest normalizer. Loose substrings (`not found`, bare HTTP 4xx/5xx) are
# DELIBERATELY EXCLUDED (they appear in legitimate content; including them traded precision for a few
# points of recall, the wrong trade for an advisory detector).

_STRUCT_ERR = re.compile(
    r"MCP error -3\d{4}"              # JSON-RPC / MCP gateway error code (e.g. -32603, -32004)
    r"|\"isError\"\s*:\s*true"        # the MCP tool-result error flag
    r"|^\s*Error:"                    # a leading 'Error:' text node (env error envelope)
    r"|Traceback \(most recent"       # a Python traceback in a tool/terminal result
    r"|exited with code [1-9]"        # a non-zero process exit (terminal/k8s tools)
    r"|permission denied",            # an access failure
    re.IGNORECASE | re.MULTILINE,
)


# --- the recovery-check confidence knob (docs/162; the docs/159 §4b / docs/160 §4 #2 follow-up) ---
#
# The shipped detector SUPPRESSES a closing-window error if a LATER result from the SAME TOOL
# succeeded — a transient error the agent fixed should not fire. Measuring the cases that suppression
# silences (docs/162) found a real phenomenon: the +70 net-new failures dropping the check recovers
# are ALL on GENERAL-PURPOSE EXECUTORS (`local-python-execute` x68, `terminal-run_command` x2) where
# the agent ran a script that Traceback'd, then ran a DIFFERENT script with the SAME tool that
# succeeded — the "recovery" was a different OPERATION, not a fix of the failed one, and the task
# still failed final-state. For a general-purpose executor the tool NAME does not identify the
# operation, so "a later same-tool success" is NOT evidence the failed operation recovered.
#
# So `recovery` is a confidence knob with three settings, the docs/144 ladder shape
# (conservative default actuates, aggressive opt-in):
#   "aware"          — DEFAULT, conservative. Today's behavior: any later same-tool success recovers.
#                      0.2% false-alarm; the operator default an actuation rides on.
#   "specific-only"  — SURGICAL (the docs/162 finding). A later same-tool success recovers ONLY for a
#                      SPECIFIC tool; for a generic executor (below) recovery NEVER suppresses. Targets
#                      exactly the same-tool-≠-same-operation mechanism without losing the genuine
#                      recoveries on specific tools.
#   "none"           — AGGRESSIVE. Recovery is ignored entirely; any unrecovered-OR-recovered closing
#                      -window structured error fires. The docs/159 §4b `tight-no-recovery` floor.
#
# WHY this stays byte-clean (the §5a line preserved). The load-bearing argument is DIRECTION, not
# input-control — be precise about which:
#   * The error SIGNAL is always `is_struct_error(tool.content)` — an ENV-authored byte (the MCP
#     gateway wrote the Traceback), under all three modes. The knob never starts BELIEVING an
#     agent-authored byte; it only changes whether a *different* env-authored success is allowed to
#     SUPPRESS that env-authored error.
#   * `is_generic_executor` DOES read the tool NAME, which the agent authors (it chose which tool to
#     call). So the agent can influence the classifier's INPUT — but only toward MORE scrutiny:
#     classifying a tool generic can only REMOVE a suppression (fire more), never add one. The single
#     suppression path (a later same-name success, the `later_ok` branch below) is BYTE-IDENTICAL to
#     the already-shipped "aware" recovery-check (docs/158). So "specific-only"/"none" add ZERO new
#     leverage in the dangerous (suppress) direction; they can only decline to suppress.
#   * The agent cannot change the generic-executor classification SET (it is fixed harness config),
#     and as just shown, naming a tool generic only invites more scrutiny — so there is no forgeable
#     "make my failure look recovered" move.
# The analogy to the volatile-field normalizer is one of KIND (fixed harness config + a monotone-safe
# direction), NOT exact: the normalizer touches only env-authored result bytes, whereas this reads an
# agent-chosen tool name — which is safe for the directional reason above, not because the input is
# env-authored.
#
# THE SAFE DIRECTION: "specific-only"/"none" can only fire MORE than "aware" (they suppress less), so
# they only ever raise recall + add false alarms — never silence a real catch the default would make.
# The risk is purely false-alarm, which docs/162 measures and caps (the deployable-ceiling rule).

# Generic-purpose executors: tools whose NAME does not identify the OPERATION, so a later same-tool
# success is not evidence the failed operation recovered (docs/162). Anchored to the names observed +
# the obvious shell/exec shapes; conservative — when unsure a tool is NOT generic (recovery still
# counts), the fail-safe direction (don't manufacture a fire). So the taxonomy is a FLOOR: a generic
# executor the set misses (e.g. a `<x>-run_command` spelling not listed) is treated as specific and
# only LOSES recall, never breaks the safe direction — docs/162's recall numbers read as a floor.
_GENERIC_EXECUTORS: frozenset[str] = frozenset(
    {
        "local-python-execute", "python-execute", "python_execute", "execute_python",
        "terminal-run_command", "terminal-run-command", "run_command", "run-command",
        "shell", "bash", "local-bash-execute", "bash-execute", "execute_command", "exec",
    }
)


def is_generic_executor(name: str) -> bool:
    """True iff `name` is a general-purpose executor (the tool name does not identify the operation),
    so a later same-tool success is NOT evidence the failed operation recovered. PURE; harness config
    (a benchmark fact about the tool surface), the §5a-clean analogue of the volatile-field list."""
    n = (name or "").strip().lower()
    if n in _GENERIC_EXECUTORS:
        return True
    # shape rule: a name whose FINAL token is an exec/shell verb is a generic executor (e.g. `foo-bash`,
    # `x.execute`, `local_exec`). Tight: must END in the verb, so a specific tool like `db-execute_query`
    # (final token `query`) or `terminal-run_command` (final token `command` — caught by the set above,
    # not the shape) is NOT swept in by the shape rule.
    return n.rsplit("-", 1)[-1].rsplit("_", 1)[-1].rsplit(".", 1)[-1] in {
        "exec", "execute", "shell", "bash",
    }


@dataclass(frozen=True)
class TerminalErrorEvidence:
    """The frozen datum `classify_terminal_error` sees — the closing window of env results.

    `window_results` is the tool_name + is_error flag for the LAST K tool results, in order, plus
    whether a later success from the same tool recovered it. Assembled at the boundary (this module
    reads the bytes + runs the grammar); the verdict is a pure predicate over the flags.

      tail        — list of (tool_name, is_error) for the last K env results, oldest-first.
      recovered   — for each error in `tail`, True iff a LATER result from the same tool succeeded
                    AND that recovery COUNTS under the active `recovery` mode (a generic-executor
                    error never counts as recovered under "specific-only"; nothing counts under
                    "none"). So `terminal_error_fired` is a uniform `any(is_err and not rec)` fold
                    across all three modes — the knob lives entirely in how `recovered` is computed.
    """

    tail: tuple[tuple[str, bool], ...]
    recovered: tuple[bool, ...]


def is_struct_error(content: str) -> bool:
    """True iff the env result content matches a STRUCTURED error envelope (not a loose substring).
    PURE. The byte-clean grammar — see the module note above for why it is tight, not loose."""
    return bool(_STRUCT_ERR.search(content or ""))


def to_terminal_error_evidence(
    traj: Trajectory, *, window: int = 3, recovery: str = "aware"
) -> TerminalErrorEvidence:
    """Assemble the closing-window error evidence. Reads ENV-authored `tool` message content only.

    Walks all tool results (in order), flags each as a structured error or not, then takes the last
    `window` and computes, for each error in that window, whether a LATER result from the same tool
    recovered to a success — gated by the `recovery` knob (see the module note above):
      "aware"          (default) — any later same-tool success counts as recovery (today's behavior).
      "specific-only"            — recovery counts only for a SPECIFIC tool; a generic-executor error
                                   never counts as recovered (the docs/162 surgical knob).
      "none"                     — recovery never counts; every closing-window error fires.
    """
    if recovery not in ("aware", "specific-only", "none"):
        raise ValueError(f"recovery must be 'aware' | 'specific-only' | 'none', got {recovery!r}")
    steps: list[tuple[str, bool]] = []
    for m in traj.messages:
        if m.get("role") == "tool":
            name = _tool_msg_name(m, traj.messages)
            steps.append((name, is_struct_error(str(m.get("content", "")))))
    n = len(steps)
    start = max(0, n - window)
    tail = tuple(steps[start:])
    recovered = []
    for idx in range(start, n):
        name, is_err = steps[idx]
        if not is_err:
            recovered.append(True)  # not an error → nothing to recover (treated as benign)
            continue
        if recovery == "none":
            recovered.append(False)  # recovery ignored → every error is unrecovered → fires
            continue
        if recovery == "specific-only" and is_generic_executor(name):
            recovered.append(False)  # same-tool ≠ same-operation for a generic executor (docs/162)
            continue
        later_ok = any(steps[j][0] == name and not steps[j][1] for j in range(idx + 1, n))
        recovered.append(later_ok)
    return TerminalErrorEvidence(tail=tail, recovered=tuple(recovered))


def terminal_error_fired(traj: Trajectory, *, window: int = 3, recovery: str = "aware") -> bool:
    """True iff the run STOPPED on an unresolved structured env error (docs/158). PURE given the
    evidence. Fires iff the closing window holds at least one structured error that NO later
    same-tool success recovered — the agent walked away from an environment failure.

    `recovery` is the docs/162 confidence knob (default "aware" = the shipped recovery-aware behavior;
    "specific-only" = the surgical knob that ignores generic-executor recoveries; "none" = the
    aggressive floor that ignores recovery entirely). The fold is uniform across modes — the knob is
    entirely in how `to_terminal_error_evidence` computes the `recovered` flags."""
    ev = to_terminal_error_evidence(traj, window=window, recovery=recovery)
    return any(is_err and not rec for (_, is_err), rec in zip(ev.tail, ev.recovered))
