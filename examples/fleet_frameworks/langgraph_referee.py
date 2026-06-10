"""Recipe 1 — LangGraph: a referee node + a verdict-routed edge.

The believe-the-agent point: a conditional edge that routes on the worker
node's own output ("if the agent says done, go to END"). The fix: a `referee`
node between the worker and the routing decision, and a conditional edge that
reads the *verdict* field — which only the referee writes, from git — never
the worker's `report`.

    python examples/fleet_frameworks/langgraph_referee.py

Needs `dos` + `langgraph` (the cookbook's run used langgraph 1.2.4). No LLM —
the worker is scripted to lie on purpose, because the control flow is the demo.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from dos import oracle

from _fixture import make_demo_repo


class FleetState(TypedDict):
    plan: str
    phase: str
    report: str      # what the agent SAYS (never trusted)
    verdict: str     # what git says (the only thing routed on)
    attempts: int


def build_app(cfg, *, max_attempts: int = 2):
    """The cookbook graph: START -> worker -> referee -> {worker | END}."""

    def worker(state: FleetState) -> dict:
        # your real agent node goes here — this one lies on purpose:
        return {"report": f"{state['phase']} is done — all work completed!",
                "attempts": state["attempts"] + 1}

    def referee(state: FleetState) -> dict:
        v = oracle.is_shipped(state["plan"], state["phase"], cfg=cfg)
        return {"verdict": "SHIPPED" if v.shipped else "NOT_SHIPPED"}

    def route(state: FleetState) -> str:
        if state["verdict"] == "SHIPPED":
            return "land"
        return "redispatch" if state["attempts"] < max_attempts else "give_up"

    g = StateGraph(FleetState)
    g.add_node("worker", worker)
    g.add_node("referee", referee)
    g.add_edge(START, "worker")
    g.add_edge("worker", "referee")           # every "done" goes through the referee
    g.add_conditional_edges("referee", route,
                            {"redispatch": "worker", "land": END, "give_up": END})
    return g.compile()


def _dispatch(app, plan: str, phase: str) -> dict:
    return app.invoke({"plan": plan, "phase": phase,
                       "report": "", "verdict": "", "attempts": 0})


def run_demo(repo=None) -> dict:
    cfg = make_demo_repo(repo)
    app = build_app(cfg)
    return {
        "lying": _dispatch(app, "AUTH", "AUTH2"),    # nothing ever landed
        "honest": _dispatch(app, "AUTH", "AUTH1"),   # a real commit backs it
    }


def main() -> int:
    r = run_demo()
    lying, honest = r["lying"], r["honest"]
    print("dispatch on AUTH2 (nothing ever landed):")
    print(f"  worker said: {lying['report']!r}")
    print(f"  -> final: {lying['verdict']} after {lying['attempts']} attempt(s)"
          " — the lie never routed as done")
    print("dispatch on AUTH1 (a real commit backs it):")
    print(f"  worker said: {honest['report']!r}")
    print(f"  -> final: {honest['verdict']} after {honest['attempts']} attempt(s)"
          " — landed on git's word, not the agent's")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
