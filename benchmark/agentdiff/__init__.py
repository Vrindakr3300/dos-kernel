"""E-AGENTDIFF-WRITEADMIT — the docs/216→228 write-admission gate, ported onto Agent-Diff.

Agent-Diff (`agent-diff`, on `localhost:8000`) is a write-heavy enterprise-API
state-diff benchmark: 224 tasks over slack/linear/box/calendar, each carrying a GOLD
assertion spec the env's own diff engine adjudicates an agent's run against. It satisfies
the docs/228 5-property out-of-loop-payoff recipe (forgeable agent claim · agent-unforgeable
correctness witness · live via API · out-of-loop consumer · write-heavy distribution), and
its witness is RICHER than tau2's single `db_match` bool: a structured
`{passed, failures, score, diff}` — the assertion engine's verdict over the observed diff vs
the gold spec, of which the agent authors zero bytes.

This package is the gate (`gate.py`), the believe-vs-adjudicate A/B (`peer_b.py`), and the
dataset reader (`dataset.py`) — the same shape as `benchmark/agentprocessbench/writeadmit/`,
re-aimed at the richer witness.
"""
