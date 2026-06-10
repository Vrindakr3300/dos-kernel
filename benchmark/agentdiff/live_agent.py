"""The live A-run ReAct harness for Agent-Diff — drives a Gemini agent through the real
backend, returns the A-row (claim + env witness). PAID (one Gemini key + the backend on :8000).

THE SEAM (verified live, 2026-06-08)
------------------------------------
This ports the Agent-Diff example notebook's `run_react_agent` onto two DOS realities:

  1. **PythonExecutorProxy, not BashExecutorProxy.** The example uses bash+curl; on Windows
     the bash proxy invokes WSL and the CRLF script dies (`$'\r': command not found`). The
     Python proxy runs natively and routes `requests` to slack.com/box/linear/calendar →
     the sandbox. So the agent writes PYTHON (`requests.*`), not curl. (standup trap #2.)
  2. **Native Gemini, not OpenRouter.** Driven by `benchmark.agentdiff._gemini.chat` (the AQ
     key rejects the OpenAI-compat endpoint; see that module).

THE FLOW per task:
  init_env(templateService, templateName=seed_template, impersonateUserId)
    → start_run(envId)
    → ReAct loop: Gemini emits <action>python</action> (executed) | <done>summary</done>
    → evaluate_run(runId, expectedOutput=gold_spec)  +  get_results_for_run(runId)
    → delete_env(envId)

The returned A-row carries BOTH halves of the docs/228 join, kept separate:
  * the FORGEABLE claim   — `answer_excerpt` (the <done> summary) + `completed`,
  * the NON-FORGEABLE     — `passed` / `score` / `failures` (the env AssertionEngine verdict
    over the diff the agent authored zero bytes of).
The gate (`gate.admit`) does the join; this module only PRODUCES the row.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ._gemini import chat


# Per-service API surface hints handed to the agent (lifted from the example's SERVICE_CONFIG).
_SERVICE_CONFIG = {
    "slack": {"name": "Slack", "base_url": "https://slack.com/api", "extra": ""},
    "box": {"name": "Box", "base_url": "https://api.box.com/2.0", "extra": ""},
    "calendar": {
        "name": "Google Calendar",
        "base_url": "https://www.googleapis.com/calendar/v3",
        "extra": "- The current date/time is Sunday, June 17, 2018 at 00:01, timezone America/Los_Angeles.\n",
    },
    "linear": {"name": "Linear", "base_url": "https://api.linear.app/graphql", "extra": ""},
}

# The ReAct system prompt — Python flavor (the agent writes `requests` code, not curl). The
# proxy intercepts requests to the real API hosts and routes them to the sandbox, so the agent
# uses the REAL public URLs with a placeholder token.
_REACT_SYSTEM_PROMPT = """You are an AI assistant that completes tasks by calling REST APIs from Python.

## Current Session
- Service: {service_name}
- Base URL: {base_url}
{extra_context}

## Environment
- Authentication is handled automatically by a proxy. Use a placeholder token (e.g. "Bearer x") where credentials would go.
- You run Python code (using the `requests` library) to call the API. Requests to the real API host are transparently routed to a sandbox.
- If unsure how the API works, explore endpoints and parameters first by reading before writing.

## Response Format
Respond using XML tags. Exactly ONE block per turn:

<thinking>your reasoning</thinking>
<action>a single self-contained Python snippet that prints what you need</action>

When the task is fully complete:

<thinking>your reasoning</thinking>
<done>a brief summary of what you changed</done>

## Rules
1. Run ONE Python snippet at a time, then wait for its printed output.
2. Each <action> snippet is independent — re-import `requests` and re-derive any IDs you need every time (no variables persist between snippets).
3. Parse JSON responses carefully; extract IDs needed for subsequent calls.
4. If a call fails, read the error and try a different approach.
5. Only use <done> when the task is genuinely finished and the write has been made.
"""


@dataclass
class ARow:
    """One live A-run outcome — the docs/228 join's two halves, kept separate.

    `answer_excerpt`/`completed` are the FORGEABLE claim; `passed`/`score`/`failures` are the
    NON-FORGEABLE env witness. `confident_write`/`admit` are filled by the gate downstream
    (left None here so this module stays witness-only). Serializable to the cached A-row dict
    `peer_b.AHandoff.from_row` reads.
    """
    test_id: str
    service: str
    operation_type: str = ""
    completed: bool = False
    answer_excerpt: str = ""        # the <done> summary — A's forgeable self-report
    iterations: int = 0
    passed: Optional[bool] = None   # env AssertionEngine verdict (True/False/None)
    score: dict[str, Any] = field(default_factory=dict)
    failures: tuple[str, ...] = ()
    error: str = ""                 # set if the run crashed (never silently dropped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id, "service": self.service,
            "operation_type": self.operation_type, "completed": self.completed,
            "answer_excerpt": self.answer_excerpt, "iterations": self.iterations,
            "passed": self.passed, "score": self.score,
            "failures": list(self.failures), "error": self.error,
        }


_THINK_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
_ACTION_RE = re.compile(r"<action>(.*?)</action>", re.DOTALL)
_DONE_RE = re.compile(r"<done>(.*?)</done>", re.DOTALL)


def _parse_react(text: str) -> tuple[Optional[str], Optional[str]]:
    """Return (action_code, done_summary) — at most one is non-None for a well-formed turn."""
    action = _ACTION_RE.search(text)
    done = _DONE_RE.search(text)
    return (
        action.group(1).strip() if action else None,
        done.group(1).strip() if done else None,
    )


def run_react_agent(
    question: str,
    executor: Any,
    system_prompt: str,
    *,
    model: str = "gemini-2.5-flash",
    max_iterations: int = 30,
    max_output_tokens: int = 2048,
) -> tuple[bool, str, int]:
    """Drive the ReAct loop. Returns (completed, done_summary, iterations).

    `executor` is a `PythonExecutorProxy` (has `.execute(code) -> {status, stdout, stderr, ...}`).
    A model turn that yields neither <action> nor <done> is nudged once and counted.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    last_text = ""
    for i in range(max_iterations):
        res = chat(messages, model=model, max_output_tokens=max_output_tokens)
        if not res.ok:
            # transport/API failure — stop the loop, surface as not-completed with the reason.
            return False, f"[agent LLM error: {res.error}]", i + 1
        text = res.text
        last_text = text
        action, done = _parse_react(text)
        if done is not None:
            return True, done, i + 1
        if action:
            out = executor.execute(action)
            stdout = out.get("stdout", "") if isinstance(out, dict) else str(out)
            stderr = out.get("stderr", "") if isinstance(out, dict) else ""
            obs = stdout.strip() or "(empty output)"
            if isinstance(out, dict) and out.get("exit_code", 0) != 0:
                obs = f"{stdout}\n[stderr]: {stderr}".strip()
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"<observation>\n{obs[:4000]}\n</observation>"})
        else:
            # neither action nor done (or an empty/blocked turn): nudge once.
            messages.append({"role": "assistant", "content": text or "(empty response)"})
            messages.append({"role": "user", "content": "Please respond with a single <action>...</action> or <done>...</done> block."})
    # ran out of iterations without <done> — not completed (an honest non-claim).
    return False, last_text[:300], max_iterations


def run_a_task(
    client: Any,
    task: Any,
    *,
    model: str = "gemini-2.5-flash",
    max_iterations: int = 30,
    inherited_context: Optional[str] = None,
) -> ARow:
    """Run agent A (or peer B) live on one `BenchTask`; return the witnessed `ARow`.

    `inherited_context` (used by the live ΔB loop for peer B) is prepended to the task prompt
    as an inherited-handoff note; None for a fresh A-run. The env is always seeded fresh from
    the task's gold template, so both arms of the ΔB measurement face the SAME starting state
    and only the narrated context differs (peer_b.py Design A).
    """
    from agent_diff import PythonExecutorProxy  # lazy: needs the SDK on path

    info = task.info or {}
    service = task.service
    cfg = _SERVICE_CONFIG.get(service, {"name": service, "base_url": "", "extra": ""})
    system_prompt = _REACT_SYSTEM_PROMPT.format(
        service_name=cfg["name"], base_url=cfg["base_url"], extra_context=cfg["extra"]
    )
    prompt = task.question
    if inherited_context:
        prompt = f"{inherited_context}\n\n---\n\nYour task:\n{task.question}"

    row = ARow(test_id=task.test_id, service=service, operation_type=task.operation_type)
    env = None
    try:
        env = client.init_env(
            templateService=service,
            templateName=info.get("seed_template"),
            impersonateUserId=info.get("impersonate_user_id"),
        )
        run = client.start_run(envId=env.environmentId)
        executor = PythonExecutorProxy(env.environmentId, base_url=client.base_url, api_key=client.api_key)

        completed, summary, iters = run_react_agent(
            prompt, executor, system_prompt, model=model, max_iterations=max_iterations
        )
        row.completed = completed
        row.answer_excerpt = summary
        row.iterations = iters

        # The ENV-AUTHORED witness: evaluate the run against the gold spec, read the result.
        client.evaluate_run(runId=run.runId, expectedOutput=task.gold_spec)
        result = client.get_results_for_run(runId=run.runId)
        row.passed = bool(result.passed) if isinstance(result.passed, bool) else None
        row.score = dict(result.score) if isinstance(result.score, dict) else {"raw": result.score}
        row.failures = tuple(result.failures or ())
    except Exception as e:  # noqa: BLE001 — surface as an error row, never a silent drop
        row.error = f"{type(e).__name__}: {e}"
    finally:
        if env is not None:
            try:
                client.delete_env(envId=env.environmentId)
            except Exception:
                pass
    return row
