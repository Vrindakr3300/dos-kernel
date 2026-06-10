"""Recipe 4 — OpenAI Agents SDK: an output guardrail with a git tripwire.

The believe-the-agent point: the run ends when the agent produces a final
output; handoffs and downstream code consume that output as the result. The
fix: an `output_guardrail` whose tripwire is the oracle — a final answer that
claims a ship git can't see trips the guardrail instead of landing
(`Runner.run(...)` raises `OutputGuardrailTripwireTriggered`; catch it and
re-dispatch instead of consuming the claim).

    python examples/fleet_frameworks/openai_agents_guardrail.py

Needs `dos` + `openai-agents` (the cookbook's run used 0.17.4). No LLM and no
API key — the guardrail is invoked directly both ways, because the tripwire
seam is the demo; attach it to your real `Agent(...,
output_guardrails=[...])`.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agents import (Agent, GuardrailFunctionOutput, RunContextWrapper,
                    output_guardrail)

from dos import oracle

from _fixture import make_demo_repo


def make_guardrail(cfg):
    """The git tripwire — `Agent(..., output_guardrails=[make_guardrail(cfg)])`.

    The run context carries which (plan, phase) this worker was dispatched on;
    the guardrail reads *that*, never the agent's output text.
    """

    @output_guardrail
    async def backed_by_git(ctx: RunContextWrapper, agent: Agent,
                            output) -> GuardrailFunctionOutput:
        v = oracle.is_shipped(ctx.context.plan, ctx.context.phase, cfg=cfg)
        return GuardrailFunctionOutput(
            output_info={"verdict": "SHIPPED" if v.shipped else "NOT_SHIPPED",
                         "via": v.source},
            tripwire_triggered=not v.shipped,   # "done" with no artifact → trip
        )

    return backed_by_git


async def demo(cfg) -> dict:
    """Invoke the guardrail directly on an unbacked and a backed claim."""
    guardrail = make_guardrail(cfg)
    worker = Agent(name="worker",
                   instructions="Ship the phase, then report.",
                   output_guardrails=[guardrail])

    async def invoke(phase: str) -> GuardrailFunctionOutput:
        ctx = RunContextWrapper(context=SimpleNamespace(plan="AUTH", phase=phase))
        result = await guardrail.run(agent=worker, agent_output="done!",
                                     context=ctx)
        return result.output

    return {"unbacked": await invoke("AUTH2"), "backed": await invoke("AUTH1")}


def run_demo(repo=None) -> dict:
    return asyncio.run(demo(make_demo_repo(repo)))


def main() -> int:
    r = run_demo()
    u, b = r["unbacked"], r["backed"]
    print(f"guardrail on unbacked 'done' -> tripwire: {u.tripwire_triggered}  "
          f"{u.output_info}")
    print(f"guardrail on backed 'done'   -> tripwire: {b.tripwire_triggered} "
          f"{b.output_info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
