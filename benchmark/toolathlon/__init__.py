"""Toolathlon replay study — DOS byte-clean detector PURCHASE on a third-party-scored benchmark.

This package is a CONSUMER of the `dos` kernel (it `import dos`, the one-way arrow), living
benchmark-side. Nothing under `src/dos/` imports it. See `HANDOFF.md` for the why + the next step.

The study replays the published `hkust-nlp/Toolathlon-Trajectories` dataset (17 models x 3 runs x
~108 tasks, CC-BY-4.0) — each record carries the full conversation, the dispatched tool calls/
results, AND the third-party `task_status.evaluation` pass/fail label. DOS's detectors are pure
`classify...(frozen-datum, policy)` functions, so the trajectory IS their input — no accounts, no
containers, no SDK edit, no inference spend.

We measure detector PURCHASE, not task LIFT: for `dangling_intent` and `tool_stream`, the fire-rate
and the **oracle-confirmed precision** (of flagged runs, the fraction the independent verifier
scored failed). Replay measures DETECT, not FIX — there was no intervention in a frozen trajectory,
so there is no lift number. That boundary is the honest deliverable (docs/157).
"""
