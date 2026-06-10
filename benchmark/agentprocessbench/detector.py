"""Byte-clean first-error localizers for AgentProcessBench (docs/174).

The DOS invariant (docs/138): adjudicate a witness the judged agent did NOT author. In an
AgentProcessBench step, the agent authored its `tool_calls` (the request), but the env executor
authored `tool_metrics[name][k].status` and the `tool` message RESULT bytes (what the tool actually
returned). A detector that fires on the env-authored STATUS channel is byte-clean — the same
provenance line as `terminal_error` (Toolathlon) and `first_unrecovered_error` (AgentHallu).

THE TASK is FirstErrAcc: predict the message index of the FIRST diverging step, scored against the
human gold `first_negative_step`. These detectors are deterministic and make zero LLM / network calls.

THE HONEST CEILING (docs/174 K2, measured): the gold rates task EFFECTIVENESS, not tool errors —
~73-89% of gold first-divergences are SEMANTIC (wrong logic on a `status:success` call) and leave no
error byte. A byte-clean detector is blind to those BY DESIGN, so its FirstErrAcc ceiling is the
error-caused fraction (~11% bfcl / 27% tau2), far below the LLM-judge's 65.8%. These detectors are
therefore a deterministic FLOOR on the error-caused slice + a boundary instrument, NOT a judge rival.
We read ONLY the env status channel; we never re-derive the agent's intent (that is the satisfaction
predicate the kernel mandate forbids — the "consistency is not grounding" line).
"""

from __future__ import annotations

from typing import Optional

from .dataset import Trajectory


def first_env_error(traj: Trajectory) -> Optional[int]:
    """Predict the first ASSISTANT step whose tool call returned a non-success env status.

    Reads the authoritative env-authored `tool_metrics.status` channel (via
    `Trajectory.step_tool_status`), NOT a text scan — so a success that prints "None" is not a false
    fire and an error flagged only in status (tau2) is not missed. Returns the 1... message index of
    the first errored assistant step, or None if no env error fired (abstain — never guesses).
    """
    status = traj.step_tool_status()
    for idx in sorted(status):
        if status[idx] == "error":
            return idx
    return None


def first_unrecovered_env_error(traj: Trajectory) -> Optional[int]:
    """Predict the first errored step whose error was NOT later recovered — no LATER assistant step
    invoking one of the SAME tools returned a clean (success) env status.

    The AgentHallu recovery gate, re-aimed onto the status channel: an errored env response the agent
    recovered from (a later same-tool success) is a transient, not the divergence. Byte-clean: reads
    only env-authored status + the env tool IDENTITY (a provenance key), never agent reasoning.
    Returns the message index, or None (abstain). NB on tau2 this rarely differs from `first_env_error`
    (tau2 has ~0 error->clean same-tool recoveries; docs/174); on bfcl it suppresses transients.
    """
    status = traj.step_tool_status()
    errored = [i for i in sorted(status) if status[i] == "error"]
    if not errored:
        return None
    # Map each assistant step index -> the set of tools it called (for the recovery test).
    msgs = traj.messages
    tm = traj.tool_metrics

    def tools_at(i: int) -> set:
        m = msgs[i] if 0 <= i < len(msgs) else {}
        return {
            ((tc.get("function", {}) or {}).get("name") or tc.get("name"))
            for tc in (m.get("tool_calls") or [])
            if ((tc.get("function", {}) or {}).get("name") or tc.get("name")) in tm
        }

    for i in errored:
        my_tools = tools_at(i)
        recovered = bool(my_tools) and any(
            status.get(j) == "success" and (tools_at(j) & my_tools)
            for j in sorted(status)
            if j > i
        )
        if not recovered:
            return i
    return None


# A registry so scoring.py can sweep multiple localizers and the SSOT can grow without edits here.
LOCALIZERS = {
    "first_env_error": first_env_error,                      # the status-channel floor
    "first_unrecovered_env_error": first_unrecovered_env_error,  # + recovery gate (bfcl-relevant)
}
