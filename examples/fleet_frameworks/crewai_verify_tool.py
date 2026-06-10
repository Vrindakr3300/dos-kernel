"""Recipe 2 — CrewAI: a verify tool + a post-kickoff gate.

The believe-the-agent point: `crew.kickoff()` returns when the agents decide
they're finished; the `CrewOutput` is their narration. The fix is two-layered:
give the agents the referee as a tool (a well-prompted agent can self-check
mid-run), and — because a tool the agent *may* call is advisory, not a gate —
verify the claims yourself after `kickoff()` returns. The second layer is the
one that holds: it reads zero bytes of crew output.

    python examples/fleet_frameworks/crewai_verify_tool.py

Needs `dos` + `crewai` (the cookbook's run used crewai 1.14.6). No LLM — the
tool and the gate are the demo; wire them into your real `Agent(...,
tools=[...])` / post-kickoff code.
"""

from __future__ import annotations

from crewai.tools import tool

from dos import oracle

from _fixture import make_demo_repo


def make_verify_tool(cfg):
    """The referee as a CrewAI tool — `Agent(..., tools=[make_verify_tool(cfg)])`."""

    @tool("verify_shipped")
    def verify_shipped(plan: str, phase: str) -> str:
        """Did (plan, phase) actually ship? Answered from git history, never from
        an agent's report. Returns SHIPPED or NOT_SHIPPED."""
        v = oracle.is_shipped(plan, phase, cfg=cfg)
        return f"SHIPPED via {v.source}" if v.shipped else "NOT_SHIPPED — no artifact backs this"

    return verify_shipped


def post_kickoff_gate(dispatched_units, cfg) -> list[tuple[str, str]]:
    """The gate — independent of anything any agent said in the crew's output.

    Returns the units whose "done" was NOT backed by git: redispatch these.
    """
    return [(plan, phase) for plan, phase in dispatched_units
            if not oracle.is_shipped(plan, phase, cfg=cfg).shipped]


def run_demo(repo=None) -> dict:
    cfg = make_demo_repo(repo)
    verify_shipped = make_verify_tool(cfg)
    return {
        "auth1": verify_shipped.run(plan="AUTH", phase="AUTH1"),
        "auth2": verify_shipped.run(plan="AUTH", phase="AUTH2"),
        "redispatch": post_kickoff_gate([("AUTH", "AUTH1"), ("AUTH", "AUTH2")], cfg),
    }


def main() -> int:
    r = run_demo()
    print(f"tool.run AUTH1 -> {r['auth1']}")
    print(f"tool.run AUTH2 -> {r['auth2']}")
    print(f"post-kickoff gate -> redispatch {r['redispatch']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
