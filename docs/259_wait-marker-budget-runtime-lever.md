# 259 — Wiring the wait-marker budget to a live Stop hook

> **Status:** SHIPPED (2026-06-09). The pure `loop_decide.wait_marker_budget`
> verdict (2026-05-19) gains its runtime PEP: a `Stop`-hook binding
> (`dos hook marker`) backed by a per-session durable tally
> (`dos.marker_sensor`). Closes the gap named in
> [[project-dos-poll-loop-antipattern]] and the `wait_marker_budget` docstring —
> "the budget could refuse a marker, but nothing was wired to *consult* it on a
> live hook." Confirm with `dos verify` / `dos commit-audit`; this doc is the
> *why*, the code is the *what*.

## The harness issue this closes

A `/loop`-style dispatch loop (one agent or a fleet) holds its turn open by
**polling** — emitting `claude -p` keep-alive markers, or re-reading a `.output`
file in a tight tick — while waiting on background work whose completion it cannot
directly observe. **Each poll is a full assistant turn that replays the entire
system+skill+context out of prompt cache and produces nothing but "not done
yet."** The damage is measured, not hypothetical: session `4b4ff97c` burned **252
markers / ~26M cache-read tokens / ~$7.80** in one run (91% of that run's total
`cache_read`). It is invisible per-turn — every marker "succeeds" — and screams
only in aggregate, which is why it needs a cross-session audit to *see* and a
runtime lever to *stop*.

This is not a correctness bug. It is a **billing-and-attention** pathology, and it
is the canonical DOS use-case: an agent narrating "still working" N times while
doing nothing is a **self-report the kernel refuses to believe**, replaced by a
ground-truth signal (the real Bash `<task-notification>`, which fires on the
child's true exit regardless of how many markers the loop emitted).

## The two halves — detector and lever (the PDP doctrine, both directions)

The kernel already had the *post-hoc detector*; this lands the *pre-hoc lever*, so
the same verdict now aims both backward (audit) and forward (gate) — the
`verify()` / `commit-audit` duality applied to loop economics:

| | Where | What it does | Trust property |
|---|---|---|---|
| **Post-hoc detector** | `headless_telemetry.py` `keepalive_poll` flag (≥5 markers); the `trajectory-audit` skill | *Names* the waste after the fact, across sessions | Reads bytes the agent did not author (the trajectory `.jsonl`, the cache-read counts) |
| **Pre-hoc lever** (this doc) | `loop_decide.wait_marker_budget` (pure) + `marker_sensor` (boundary I/O) + `dos hook marker` (CLI) | *Refuses* the marker before it is emitted | Pure `classify(count, policy)`; the count is durable ground-truth state, not a flag the model threads through |

The default `max_markers=4` is tuned to fire **one marker before** the post-hoc
flag (≥5) would — the runtime refusal lands just ahead of the telemetry alarm.

## Why the count is durable state, not a CLI flag

The pure `wait_marker_budget(markers_emitted, max_markers)` needs the running
count. Threading it through a flag (`--emitted N`) the loop carries forward is
exactly *"the prose the model must remember"* the budget docstring criticizes — a
loop that forgets to increment it defeats the guard. So the count is made
**ground-truth durable state the model cannot forget**: `dos.marker_sensor`
appends one `fsync`'d, schema-tagged record per emitted marker under
`.dos/markers/<session_id>.jsonl`, and the count is the number of valid records
replayed back. This is the **exact sibling of `posttool_sensor`** (the
`tool_stream` boundary): same accumulator idiom (append/replay, schema-gated +
torn-tail-tolerant, byte-mirroring `intent_ledger`'s ARIES discipline), but the
fold is the simplest possible one — a count.

The conservative direction for a cost guard is to **under-count** (a torn/corrupt
line is "didn't happen"), never over-count — a guard must never refuse a marker
the loop was genuinely entitled to.

## ⚠ The polarity — the INVERSE of `cmd_hook_stop` (the load-bearing fact)

This binds to a **Stop** hook, and its polarity is the **opposite** of the
existing `dos hook stop`. A keep-alive marker is the loop *choosing not to stop* —
blocking its own Stop to keep waiting. So:

- **budget REMAINS** (`wait_marker_budget(...).allow` is `True`) → the loop may emit
  another marker → **block the Stop** (`{"decision": "block", "reason": …}`),
  holding the turn open one more marker, and record the marker.
- **budget EXHAUSTED** (`.allow` is `False`) → stop polling → **allow the Stop**
  (emit *nothing* — an empty Stop output is Claude Code's "allow stop") → the loop
  ends its turn and waits on the real `<task-notification>`. The refused marker is
  **not** recorded (it was not emitted).

`cmd_hook_stop` blocks a **false done** (the agent claimed a phase shipped, git
disagrees). `cmd_hook_marker` blocks a **premature stop, but only while the marker
budget is unspent**, then gets out of the way. **Two Stop hooks, opposite
triggers — do not conflate them.** They *compose*: a host can wire both (stop
first to refuse a false done, then marker to bound the keep-alive polling of a true
wait).

This polarity is also why the emitted bytes matter: like every other DOS hook, a
Stop block MUST be the top-level `{"decision": "block", "reason": …}` Claude Code
honors — never an `{"ok": …}` / `hookSpecificOutput` shape (which CC *silently
ignores* at a Stop hook, the docs/165 §2 no-op lesson). Pinned by
`tests/test_marker_sensor.py::test_cli_block_dialect_is_exactly_what_cc_honors`.

## Advisory, fail-safe, kernel-clean

- **Advisory (PDP, not PEP — docs/99):** the block is a *proposal* the runtime
  consumes; the kernel computes, the runtime acts.
- **Fail-safe direction = "let it stop":** every failure mode (no stdin,
  unparseable JSON, an unusable `session_id`, an accumulator I/O error) degrades to
  *emit nothing, exit 0*. The hook can refuse to keep a loop polling past its
  budget; it never traps a loop open on its own inability to read or write.
- **Kernel litmus:** `marker_sensor` is a pure verdict-adapter — imports only
  sibling kernel modules (`loop_decide`, `config`, `durable_schema`), names no host
  or vendor, resolves every path via `SubstrateConfig.paths` (never `__file__`),
  and carries no policy of its own (the threshold is `wait_marker_budget`'s
  `max_markers`, handed in at the CLI). Passes `test_vendor_agnostic_kernel.py`.

## What landed

- `src/dos/marker_sensor.py` — the per-session marker tally (boundary I/O).
- `src/dos/cli.py` — `cmd_hook_marker` + the `dos hook marker` subparser.
- `tests/test_marker_sensor.py` — accumulator round-trip / schema-gate /
  torn-tail; CLI polarity (block-while-budget-remains → allow-stop-when-spent),
  the anti-no-op dialect assertion, the refused-marker-doesn't-advance-count
  invariant, the `--json` surface, and the fail-safe paths. 19 tests.

Wire it via `.claude/settings.json` Stop hooks (alongside or instead of
`dos hook stop`).

## The fleet angle (why this is a kernel concern, not a skill's prose)

For **one** agent, "stop polling" is a trivial self-discipline. Under
**concurrency** the verdict changes: a fleet of *K* loops each polling
independently contends for the same rate-limit window, so one loop's wasted markers
*delay every other loop's real work* — poll-waste becomes a shared-resource
externality, not a private cost. You cannot trust *K* independently-narrating
agents to each remember a 4-marker cap; you need one deterministic referee they all
consult. That is why the budget lives in the kernel and the count is durable state,
not a line in each skill's screenplay.

## Follow-ups

All three follow-ups below LANDED (2026-06-09). Confirm with `dos verify` /
`dos commit-audit`; the code is the *what*, this section is the *why* and the
where-it-went.

1. **Generalize the counter** from "markers emitted" to "**no-op turns since last
   forward delta**," folded into the `liveness`/`productivity`/`efficiency` family
   — so a `ScheduleWakeup`-poll loop and a marker-storm become the *same* verdict
   (both are "a turn that replayed context and produced zero ground-truth delta").
   **LANDED** as `src/dos/noop_streak.py` — the pure `classify(NoOpHistory, policy)
   -> NoOpStreakVerdict` (LIVE/EXHAUSTED) verdict, a count-vs-cap sibling of
   `wait_marker_budget` (NOT a trend like `productivity`, NOT a ratio like
   `efficiency`). `wait_marker_budget(n, m)` is byte-equivalent to
   `noop_streak.classify(NoOpHistory(n), NoOpStreakPolicy(m))` on the allow bit and
   carried count (pinned by a grid test), so the marker case is the special case
   the generalization subsumes without drift. The accumulator (`marker_sensor`) now
   records the general no-op turn; the marker hook is its first consumer.
2. **A session-boundary reset** (`op:"RESET"`, or a forward-progress signal that
   zeroes the tally — the `tool_stream` ADVANCING analogue), so a long-lived
   session that legitimately re-enters a wait phase starts fresh. **LANDED** as
   `marker_sensor.record_reset` (an `op:"RESET"` record) + the reset-relative
   `marker_count` ("MARKER records *after* the last RESET record," a single forward
   pass where RESET zeroes and MARKER increments) + the `dos hook marker --reset`
   CLI path (a host wires it on a forward-progress hook —
   SessionStart/UserPromptSubmit, or after a commit). The conservative direction is
   preserved and SHARPENED: a torn/too-new/foreign RESET is skipped, so the reset
   "didn't happen" and the count stays *higher* (EXHAUSTED sooner → refuse one MORE
   no-op turn, never one fewer) — a torn RESET can never erase a real marker count.
   With **no** RESET in a tally (every host today), the count is byte-identical to
   the old "all MARKERs," so the shipped lever's behavior is unchanged. What is
   still explicit (not auto-derived) is the reset *trigger*: deriving a RESET from a
   live git/journal delta (pulling `git_delta` into the marker boundary, the
   `liveness` evidence reader) is the one remaining future step.
3. **Close the audit→budget loop:** let `trajectory-audit`'s `keepalive_poll`
   finding emit a decision proposing a tighter `max_markers`, so the post-hoc
   detector tunes the pre-hoc lever. **LANDED** as the pure
   `loop_decide.propose_tighter_budget(observed, current_max) -> int` (the
   arithmetic is kernel-side, tested, reusable — `max(1, min(current_max,
   observed-1))`, monotone-down and floored at 1) + the `trajectory_audit.py`
   wiring: the `keepalive_poll` finding now carries the raw `observed` marker count
   through the rollup (R5 — it was otherwise lost to a prose string), and a routed
   decision row carries `observed_markers` / `current_max_markers` /
   `proposed_max_markers`. It stays ADVISORY (`resolver_kind:"HUMAN"`, never
   auto-applied — the PDP/PEP line). The load-bearing honesty: when the observed
   burst *exceeds* the current cap (e.g. 252 under a 4-cap), the clamp yields *no*
   tightening — because that proves the lever was never enforced, so the fix is to
   *wire the hook*, not lower a number that was never consulted; the row carries a
   `lever_not_wired` flag to say exactly that.
