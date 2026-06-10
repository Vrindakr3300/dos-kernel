# docs/188 — The frontier loop-rate, measured: the rank-1 kill-criterion fired

> **One-line result:** across **1,795 real frontier-model (Opus-4.x) Claude Code
> sessions / 40,820 tool calls**, the live `tool_stream` verdict fires
> REPEATING/STALLED on **3 sessions (0.2%)**, and **0 of them are substantive
> reasoning loops** — all 3 are background-task `.output` polls. The strong-model
> null (`p_stuck≈0%`) generalizes off the gym onto the real harness. The
> agent-side WARN re-surface bet is **recall-bounded to ~0 on the frontier.**

## Why this measurement

The conversion-gap synthesis (`wf_6647ad3c-913`, docs/170 cluster) ranked
**WARN re-surface via `dos hook posttool`** the #1 value-capture bet, with one
pre-registered **kill criterion**:

> *If across ~30 real frontier sessions ZERO receive a REPEATING/STALLED
> re-surface (the `p_stuck=0.0%` null generalizing), the agent-side budget-reclaim
> value is recall-bounded to near zero on the frontier; the story collapses to
> "correctly silent / harmless," not a banked win.*

The cheapest way to "fully understand" the bet is to **measure the loop-rate**, not
argue it. We have the corpus: the operator's own Claude Code transcripts are
frontier-model trajectories, not a weak gym model.

## Method (byte-clean, $0, real kernel logic)

`benchmark/toolathlon/measure_frontier_loop_rate.py` replays every transcript
through the **exact live-hook code path** — no re-implementation:

- parse `*.jsonl` into ordered `(tool_name, tool_input, tool_result)` triples
  joined by `tool_use_id` (CC format: `assistant.message.content[]` `tool_use` →
  `user.message.content[]` `tool_result`);
- shape each into the **same PostToolUse event dict** the live hook receives
  (`{tool_name, tool_input, tool_response}`);
- feed it through `posttool_sensor.step_from_event` (the real adapter:
  agent-authored `args_digest` + ENV-authored `result_digest`) and
  `tool_stream.classify_stream` (the real pure verdict), accumulating per session.

So the offline fire is **byte-identical** to what `dos hook posttool` would have
emitted live. It is byte-clean for the same reason the detector is: the only
question asked is "did the **env-authored** `result_digest` repeat N times in a
row?" — never a satisfaction predicate (docs/138 §5a).

**Parse health (verified, not assumed):** 16,723 top-level tool pairs, **100%
carry a digestable result** (only the 3.4% `is_error` calls correctly carry none —
the fail-safe break). The fire-rate is not a dropped-result artifact.

## Results

| Scope | Sessions w/ tools | Tool calls | Fired (REPEAT/STALL) | STALLED | **Substantive** |
|---|---|---|---|---|---|
| Top-level only | 180 | 16,723 | 2 (1.1%) | 1 (0.6%) | **0 (0.0%)** |
| **Full fleet (+sub-agents)** | **1,795** | **40,820** | **3 (0.2%)** | 2 (0.1%) | **0 (0.0%)** |

Median 76 calls/session top-level (13 across the sub-agent-heavy fleet), **max
404** — a genuinely long-horizon corpus, not toy sessions.

**The `peak_run` distribution is the clincher (top-level, n=180):**

```
peak_run -> n_sessions:  {1: 174, 2: 5, 3: 1, 5: 1}
```

**174 of 180 sessions never repeated a triple even ONCE.** A frontier model on a
real coding task almost never re-issues an identical `(tool, args, result)` call.

**All 3 fires are POLL-class** (a background-task `.output` read returning the same
"still empty" bytes):
- `2cd77e93` — the documented `.output` poll-loop catch-of-record (STALLED@5).
- `18983ffb` — same shape (REPEATING@3).
- `agent-ad6750f08124` (a sub-agent) — read a `tasks/…/*.output` **18×**, each
  returning `the file exists but is shorter than the provided offset` (STALLED@6).

## Robustness (the steelmen, all answered)

1. **More sensitive threshold** (`repeat_n=2`): fire-rate rises to 3.9%, **still
   0% substantive** — all `Read` polls.
2. **Sub-agent blind spot**: including ~1,600 sub-agent/workflow transcripts (the
   full fleet) *lowered* the rate to 0.2% and added one more POLL fire — no hidden
   looping sub-agent population.
3. **Non-consecutive repeats** (the strongest steelman — "maybe they loop, just
   not back-to-back"): counting *any* identical triple recurring ≥3× **anywhere**
   in a session yields **13/1,794 (0.7%)** vs 0.2% consecutive — and the worst
   offenders are the same poll-class sessions. No masked reasoning-loop population.

## What this settles

- **The kill criterion FIRED.** The agent-side WARN re-surface value on the
  frontier is recall-bounded to ~0. `dos hook posttool` is **correct to be silent**
  here — it is HARMLESS, not lift. That is the honest frontier verdict, consistent
  with the 0.00pp defensive-lift ceiling (docs/170) and the gym `p_stuck=0.0%` null
  (docs/173). The detector is *sound*; the frontier simply does not produce its
  target failure mode.
- **The one real value of the live hook is operator/harness ergonomics**: the
  eventual-consistency `.output` poll (the 2cd77e93 / ad6750f0 class). Real, but it
  plausibly plateaus — a hill that does **not** grow with capability. Worth wiring
  (it is one config line, the sensor is shipped and green) for the ergonomic win and
  to bank the live datum, but **not** as a frontier-quality lift.
- **Value-capture must move OFF the per-task agent-action denominator.** This is the
  empirical confirmation of the synthesis headline: detection is solved; the
  remaining frontier value is **coordination** (bet #2, F8 — measure it) and the
  **gated write** (bet #3, F3/PEP — the unbuilt step-function), neither of which
  routes through the agent's next action.

## Reproduce

```bash
python benchmark/toolathlon/measure_frontier_loop_rate.py            # top-level sessions
python benchmark/toolathlon/measure_frontier_loop_rate.py --recursive --show-fires  # full fleet
python benchmark/toolathlon/measure_frontier_loop_rate.py --repeat-n 2 --stall-n 3  # sensitivity
```

Related: docs/170 (frontier-lift axis), docs/173 (the four detectors), docs/145
(`tool_stream`), docs/144/151 (the WARN-wins intervention ladder). Memory:
`project-dos-conversion-gap-value-capture`.
