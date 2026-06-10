"""FleetForge — the live-magnitude, skill-as-treatment coordination A/B.

This benchmark closes the ONE gap every prior DOS benchmark left open: the LIVE
MAGNITUDE of the coordination/velocity win, measured with REAL LLM agents, scored
on the CONSUMER's denominator (collisions averted, review-hours skipped,
double-spawns avoided, verified-ships-per-$), with the SHIPPED operator-facing
SKILL.md workflow (dos-dispatch / dos-dispatch-loop / dos-supervise-loop) as the
treatment arm — NOT a hand-coded Python loop, and NOT the agent's task pass-rate.

It is built ON FleetHorizon's proven honesty machinery (the real kernel, real git
ground truth, the model-free consumer-denominator battery in
`benchmark.fleet_horizon.metrics`, and the gap->0-at-N=1 falsifiers) and consumes
the kernel from outside — the same boundary as `examples/`. It is NOT in the
kernel release gate (`testpaths=["tests"]`).

The keystone is `skill_adherence.py`: the attribution instrument the live A/B was
always missing — a PURE join over the lane-journal WAL + git that reconstructs, per
effort, whether the skill's mandated verb sequence (ACQUIRE-before-write /
HEARTBEAT / verify-before-bank / RELEASE) actually fired, read from byte-clean
fossils, NEVER from the agent's self-report. Without it, a live coordination delta
cannot be credited to the skill verbs rather than to model luck — which is exactly
why FleetHorizon stayed simulated.
"""
