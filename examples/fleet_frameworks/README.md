# `fleet_frameworks` — the cookbook's recipes, runnable

The executable form of the
[fleet-framework cookbook](../playbooks/cookbook-fleet-frameworks.md): each
file is that cookbook's recipe lifted out of markdown so the DOS-bearing seam
is **executed and pinned by the suite**
(`tests/test_fleet_framework_examples.py`) instead of living only as pasted
output. The recipes find each framework's **believe-the-agent point** — where a
worker's "done" is folded into control flow as a fact — and route it through a
kernel verdict instead. Read the cookbook for the full argument; run these for
the proof.

| File | Recipe | Needs |
|---|---|---|
| `universal.py` | 0 — the two-function adapter (`verify` at the "done" seam, `arbitrate` at the dispatch seam) | `dos` only |
| `langgraph_referee.py` | 1 — a referee node + a verdict-routed edge | `langgraph` |
| `crewai_verify_tool.py` | 2 — a verify tool + a post-kickoff gate | `crewai` |
| `autogen_termination.py` | 3 — a termination condition only git can satisfy | `autogen-agentchat` |
| `openai_agents_guardrail.py` | 4 — an output guardrail with a git tripwire | `openai-agents` |

Recipe 5 (Claude Code / Claude Agent SDK) has no file here because it needs no
adapter — use the shipped surfaces (`dos init --hooks claude-code`, `dos-mcp`,
the [plugin](../../claude-plugin/README.md)). The swarm-runtime worked example
is [`../hermes_integration/`](../hermes_integration/).

```bash
# from the repo root, with dos installed (pip install -e .):
python examples/fleet_frameworks/universal.py

# each framework recipe runs the moment its framework is installed, e.g.:
pip install langgraph
python examples/fleet_frameworks/langgraph_referee.py
```

Every demo builds its own throwaway git repo (`_fixture.make_demo_repo`) with
one real `AUTH1: implement login` commit, so AUTH1 is verifiably shipped and
AUTH2 verifiably is not — no recipe touches the repo you run it from. The
workers are scripted liars, no LLM behind them, because the *control flow* is
what's being demonstrated: swap in your real agents; the referee doesn't care
who's lying to it.

The matching tests skip cleanly when a framework isn't installed — CI without
the frameworks still pins Recipe 0 (the kernel seam itself); a checkout with
any of them installed pins that framework's seam too.
