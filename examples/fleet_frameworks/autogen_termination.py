"""Recipe 3 — AutoGen: a termination condition only git can satisfy.

The believe-the-agent point: AgentChat teams stop on conditions like
`TextMentionTermination("TERMINATE")` — the run ends because an agent said the
magic word, which is exactly how an agent ends a run it's stuck on. The fix: a
`TerminationCondition` that treats the magic word as a *claim* and only stops
the team when the oracle backs it. Compose it with a budget stop
(`ShippedTermination(...) | MaxMessageTermination(50)`) so an honestly-stuck
run still ends — refusing to *believe* "done" is not the same as running
forever.

    python examples/fleet_frameworks/autogen_termination.py

Needs `dos` + `autogen-agentchat` (the cookbook's run used 0.7.5). No LLM —
the condition is called with scripted messages, because the stop seam is the
demo; hand it to your real `RoundRobinGroupChat(...,
termination_condition=...)`.
"""

from __future__ import annotations

import asyncio

from autogen_agentchat.base import TerminatedException, TerminationCondition
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.messages import StopMessage, TextMessage

from dos import oracle

from _fixture import make_demo_repo


class ShippedTermination(TerminationCondition):
    """Stop only when (plan, phase) verifiably shipped — an agent saying
    'TERMINATE' is a claim, not a stop."""

    def __init__(self, plan: str, phase: str, cfg):
        self._plan, self._phase, self._cfg, self._done = plan, phase, cfg, False

    @property
    def terminated(self) -> bool:
        return self._done

    async def __call__(self, messages) -> StopMessage | None:
        if self._done:
            raise TerminatedException("already terminated")
        claims_done = any("TERMINATE" in str(getattr(m, "content", ""))
                          for m in messages)
        if claims_done and oracle.is_shipped(self._plan, self._phase,
                                             cfg=self._cfg).shipped:
            self._done = True
            return StopMessage(content="verified: shipped per git ancestry",
                               source="dos")
        return None        # claim unbacked (or no claim) — the run keeps going

    async def reset(self) -> None:
        self._done = False


async def demo(cfg) -> dict:
    """Both verdicts + the `|` composition, against scripted messages."""
    claim = [TextMessage(content="all done — TERMINATE", source="worker")]
    lying = await ShippedTermination("AUTH", "AUTH2", cfg)(claim)
    honest = await ShippedTermination("AUTH", "AUTH1", cfg)(claim)
    budgeted = ShippedTermination("AUTH", "AUTH2", cfg) | MaxMessageTermination(50)
    return {"lying": lying, "honest": honest, "budgeted": budgeted}


def run_demo(repo=None) -> dict:
    return asyncio.run(demo(make_demo_repo(repo)))


def main() -> int:
    r = run_demo()
    print(f"lying TERMINATE on AUTH2  -> {r['lying']} (run keeps going)")
    h = r["honest"]
    print(f"honest TERMINATE on AUTH1 -> StopMessage(content={h.content!r}, "
          f"source={h.source!r})")
    print(f"composes with MaxMessageTermination via `|` "
          f"({type(r['budgeted']).__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
