"""tau2coord — the docs/233 coordination payoff, PORTED across tau2-bench domains.

Ports the airline-only coordination A/B (benchmark/agentprocessbench/writeadmit/
coord_loop.py, docs/233 J=6/8) onto tau2-bench's deterministic-DB-state domains
(airline + retail), and adds a headless-`claude -p` live-agent confirmation arm.

The thesis (unchanged from docs/233): tau2-bench already grades with a sound
DETERMINISTIC DB-state check, so DOS adds nothing on SINGLE-agent verification —
we concede that. The value is the FLEET case the re-run wrapper cannot reach: two
agents on ONE shared tau2 DB, where a check reads true when agent A looks and
false when A writes because B changed the state in between (TOCTOU lifted onto
world state). The arbiter serializes the contended region; a re-run wrapper
prevents ~0 (each agent's own check already passed).

J = lost-update clobbers PREVENTED, off the DB-hash neither agent authors —
NOT tasks-won.
"""
