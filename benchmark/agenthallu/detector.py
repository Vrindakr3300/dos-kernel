"""Byte-clean step-localizers for AgentHallu's Tool-Use slice (docs/166 §4b).

The DOS invariant (docs/138): adjudicate a witness the judged agent did NOT author. In an AgentHallu
trajectory step, `tool_calls` are AGENT-authored (the request) but `tool_responses` are ENV-authored
(what the tool actually returned). So a detector that fires on the *env-authored* response bytes is
byte-clean — it is reading the gym/tool's output, not the agent's narration about it. This is the
same provenance line as `terminal_error` (docs/158): the environment authored the error, not the
agent.

The task is STEP-LOCALIZATION: emit the 1-indexed step we believe is the first divergence, to be
scored against the gold `hallucination_step`. These detectors are deterministic and make zero LLM /
network calls.

HONEST SCOPE (the docs/162 false-reassurance scar, stated up front): an errored tool_response is a
SIGNAL, not the hallucination itself — errors are common and often recovered from. So
`first_errored_response` has real exact-hit lift over SOTA but a non-trivial false-alarm rate on
clean trajectories; the scorer (scoring.py) reports that false-alarm as a FLOOR, never hides it. We
do NOT claim to localize the silent semantic divergences (wrong-content-in-arg, missing-precondition)
that leave no errored byte — judging those would require re-deriving the agent's intent, which is
distrusting correctness (out of kernel mandate, the "consistency is not grounding" line).

THE FALSE-ALARM CUT (docs/166 §4b-ii, measured): the broad `first_errored_response` regex carries a
35.2% false-alarm floor on clean trajectories. A workflow over the corpus traced that floor to two
BREADTH bugs, both fixable WITHOUT a satisfaction predicate:

  1. The broad `_ERR` substring matches an error WORD appearing in legitimate env DATA (a file whose
     content says "error", a search result mentioning "permission"/"missing") — not the env's actual
     error CHANNEL. `_step_errored` fixes this: it fires only on a structured error KEY
     (`{"error": ...}`) or a raised-error PROSE prefix (`Error during execution:` / `Traceback`).
  2. The baseline fires on the FIRST error even when the agent demonstrably RECOVERED (a later clean
     env response from the same tool — a transient-then-retry). `first_unrecovered_error` gates on a
     BYTE-OBSERVABLE recovery signal: did a tool invoked at the errored step ever return a clean env
     response later? If so the error was transient, not the divergence.

The recovery filter is byte-clean — it reads only env-authored tool_responses + the env tool
IDENTITY (a provenance key for "did this same tool later emit clean env bytes"), never the agent's
content/reasoning, never the agent's args as a satisfaction judgment (the arg_provenance byte-author
line). It is NOT a corroboration ensemble (measured-false: the byte-clean detectors are complementary
not redundant, so requiring a second witness collapses recall — docs/166 §4b-ii). Two new localizers
ride the same `_step_errored` floor: `first_structural_error` (the channel fix alone, ~all recall at
3× lower false-alarm) and `first_unrecovered_error` (channel + recovery gate, the precision point —
29× lower false-alarm for 4 fewer exact-hits).
"""

from __future__ import annotations

import ast
import json
import re
from typing import Optional

from .dataset import Trajectory

# Error tokens an ENVIRONMENT emits in a tool response. Deliberately broad (recall-leaning); the
# scorer's precision + false-alarm columns keep us honest about the cost of that breadth.
_ERR = re.compile(
    r"error|exception|traceback|\bfail|not found|invalid|denied|cannot|unable|"
    r"no such|missing|unexpected|refused|forbidden|permission|timeout",
    re.I,
)


def _response_text(step: dict) -> str:
    tr = step.get("tool_responses")
    return json.dumps(tr) if tr else ""


def first_errored_response(traj: Trajectory) -> Optional[int]:
    """Predict the step whose ENV-authored tool_response first carries an error token.

    The broad RECALL FLOOR: a substring scan over the env response bytes. Returns the 1-indexed
    `step` value, or None if no env response erred (the detector abstains — it does not guess, the
    abstain-never-invent rule). Kept registered as the floor the scorer compares against; its 35.2%
    false-alarm is the breadth the two structural localizers below cut.
    """
    for step in traj.history:
        if _ERR.search(_response_text(step)):
            s = step.get("step")
            return int(s) if isinstance(s, int) else None
    return None


# ---------------------------------------------------------------------------------------------------
# The structural error-CHANNEL floor — the precision fix (docs/166 §4b-ii).
# ---------------------------------------------------------------------------------------------------

# The keys an ENV structures its error channel under. A truthy value under one of these is a real
# error the gym authored, not an error WORD sitting in legitimate response data.
_ERROR_KEYS = {"error", "errors", "error_type", "error_message", "exception"}

# The env's RAISED-error PROSE channel — a tool that THREW, prefixing its response. Anchored at the
# string start, so it matches a real tool-raise, NOT free text that merely contains the word "error"
# (that is the broad-regex false-alarm bug this whole tier exists to fix).
_PROSE_ERR = re.compile(r"^\s*(error during execution|traceback \(most recent)", re.I)


def _coerce(el: object) -> object:
    """Parse one env-response element to a Python object: json first, then a single-quote ast
    fallback (BFCL emits Python-repr responses like ``[{'error': ...}]`` that json.loads rejects).
    Returns None when the element is not parseable structured data. PURE."""
    if isinstance(el, (dict, list)):
        return el
    if not isinstance(el, str):
        return None
    s = el.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        if s[0] in "[{(":
            try:
                return ast.literal_eval(s)
            except Exception:
                return None
    return None


def _has_error_key(obj: object) -> bool:
    """Recursively: does any dict in this env structure carry a TRUTHY error-CHANNEL key? PURE.

    Recurses into nested lists/dicts so an error reported one level down (``{"result": {"error":
    ...}}``) is still seen. A falsy value (``{"error": null}`` / ``{"error": ""}``) is NOT an error —
    the channel is present but empty."""
    if isinstance(obj, dict):
        if any(isinstance(k, str) and k.lower() in _ERROR_KEYS and v for k, v in obj.items()):
            return True
        return any(_has_error_key(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_has_error_key(v) for v in obj)
    return False


def _step_errored(step: dict) -> bool:
    """True iff this step's ENV-authored tool_response used the env's error CHANNEL — a structured
    error key OR a raised-error prose prefix — never a mere error-WORD in legitimate response data.
    This is the structural replacement for the broad `_ERR` substring scan. PURE."""
    tr = step.get("tool_responses")
    if not tr:
        return False
    for el in tr:
        if isinstance(el, str) and _PROSE_ERR.match(el.strip()):
            return True
        obj = _coerce(el)
        if obj is not None and _has_error_key(obj):
            return True
    return False


def _step_tools(step: dict) -> set:
    """The env tool identities invoked at this step. Used as PROVENANCE KEYS for the recovery test
    ("did this same tool later emit clean env bytes?"), never as agent reasoning. PURE."""
    tc = step.get("tool_calls")
    return (
        {c["name"] for c in tc if isinstance(c, dict) and c.get("name")}
        if isinstance(tc, list)
        else set()
    )


def first_structural_error(traj: Trajectory) -> Optional[int]:
    """RUNNER-UP localizer (docs/166 §4b-ii variant A): the first step whose ENV tool_response used
    the error CHANNEL (a structured key or a raised-error prose prefix), not merely an error WORD in
    response data. The structural replacement for the broad-regex breadth bug. Abstains (None) when
    no env error channel fired.

    MEASURED on the 103 Tool-Use slice: exact 34/103 (33.0%), within±1 36, fired 69, precision 49.3%,
    false-alarm 28/250 (11.2%) — vs the broad-regex baseline's 34.0% / 48.6% / 35.2% (a ~3× false-
    alarm cut for one exact-hit). The recall-preserving point: keep ~all hits, shed the worst breadth.
    """
    for step in traj.history:
        if _step_errored(step):
            s = step.get("step")
            return int(s) if isinstance(s, int) else None
    return None


def first_unrecovered_error(traj: Trajectory) -> Optional[int]:
    """RECOMMENDED localizer (docs/166 §4b-ii variant B): the first env-errored step whose error was
    NOT later recovered — no tool invoked at that step ever returns a CLEAN env response later in the
    trajectory (a byte-observable "this error was terminal, not a transient-then-retry").

    Byte-clean: reads only env-authored tool_responses (via `_step_errored`) + the env tool IDENTITY
    (a provenance key for "did this same tool later emit clean env bytes"), never the agent's
    content/reasoning, never the agent's args as a satisfaction judgment. Same byte-author line as
    `arg_provenance`. Abstains (None) when no env error channel fired.

    MEASURED on the 103 Tool-Use slice: exact 31/103 (30.1%), within±1 32, fired 37, precision 83.8%,
    false-alarm 3/250 (1.2%) — vs the broad-regex baseline's 34.0% / 48.6% / 35.2% (a 29× false-alarm
    cut for four exact-hits, +35pp precision). At 30.1% exact it still beats the SOTA Tool-Use ceiling
    (Gemini-2.5-Pro 11.6%) by ~2.6×. The recovery filter SELF-SELECTS to the strong subcategories
    (Missing-Required-Call 18/19 fired, Parallel-Conflict 6/6) and suppresses the weak ones
    (Incorrect-Args, Unnecessary-Call) without ever reading the gold subcategory label — which is why
    its precision reaches 83.8%. The recommended point for an advisory WARN surface (the docs/144
    intervention ladder): a 35% false-resurface rate trains operators to ignore the signal; 1.2% stays
    credible.

    The irreducible floor: the 3 surviving clean false-alarms are genuine TERMINAL env errors with no
    later same-tool retry, on truncated trajectories that simply end — distinguishing those from a
    real divergence needs re-deriving agent intent, which the byte-author invariant forbids. 1.2% is
    the floor for a byte-clean detector on this corpus.
    """
    steps = traj.history
    for i, step in enumerate(steps):
        if not _step_errored(step):
            continue
        tools = _step_tools(step)
        recovered = bool(tools) and any(
            (not _step_errored(later)) and (_step_tools(later) & tools)
            for later in steps[i + 1:]
        )
        if not recovered:
            s = step.get("step")
            return int(s) if isinstance(s, int) else None
    return None


# A registry so scoring.py can sweep multiple localizers and the SSOT can grow without edits here.
# Kept FLAT (no ensemble policy): a union raises false-alarm to 46%, routing's perfect-oracle ceiling
# (33) is below the plain baseline (35), and corroboration collapses recall to 6 hits — the single
# gated `first_unrecovered_error` dominates every ensemble on the Pareto frontier (docs/166 §4b-ii).
# A flat registry also keeps each localizer's false-alarm floor independently visible (never OR-hidden).
LOCALIZERS = {
    "first_errored_response": first_errored_response,    # broad recall floor: 34.0% exact / 35.2% FA
    "first_structural_error": first_structural_error,    # runner-up: 33.0% / 11.2% FA (~all recall)
    "first_unrecovered_error": first_unrecovered_error,  # RECOMMENDED: 30.1% / 1.2% FA / 83.8% prec
}
