# docs/254 — The freshness sort-key: prefer new work over churn

> **Status:** SHIPPED. `dos.pick_priority` + `dos pick-priority` + tests
> (`tests/test_pick_priority.py`, 17 green). Host wiring (the job repo's
> `fanout_state.py` plan-sort) is a separate, follow-on change in that repo.

## The problem — the picker churns

A dispatch loop drives a fleet by repeatedly asking "what should a worker pick up
next?" The job repo measured what that loop actually did over a 24-hour window:

- **19 dispatch runs; only 1 shipped a pick (5.3%).** 18 of 19 DRAINED or BLOCKED.
- The loop kept re-attempting units it had *already tried* — ones that did not move —
  instead of picking up new, not-started work. It burned ~$80/24h to ship one pick.
  (Session `0030756a`, scoreboard shape `0:18 1:1 2:0 3+:0`.)

That is **churn**: re-confirming a known drain every iteration while fresh plans sit
un-picked.

## The root cause — the sort key is blind to churn

The picker has two separate jobs:

1. **Gate** — *may* this unit be picked at all? (`pickable`, `cooldown`, `reconcile`.)
2. **Order** — among the units that *may* be picked, *which one first?*

The gate side was already built. The **order** side was the gap. The host's
plan-sort key was:

```
(priority, status, id)
```

There is no *freshness* term in it. So:

- A never-attempted plan and a plan the loop drained 18× in a row **sort
  identically** — the key cannot tell them apart.
- Ties break on **alphabetical `id`** — whatever sorts first by name gets re-picked
  every iteration, forever, regardless of how many times it already failed.

`cooldown` *does* know a unit was tried — but it only **gates**: it skips a
`RECENTLY_ATTEMPTED` unit for a 6-hour window. The moment that window lapses, the
churned unit sorts right back to the top next to fresh work, because the **sort
itself never learned it was a repeat offender.** A gate can also *starve* a ready
plan (hold it out entirely); it never actively *prefers* new work.

## The fix — a freshness tie-breaker

Add a small **pure kernel primitive**, `dos.pick_priority`, that folds the attempt
history the host **already records** (the `cooldown` ledger) into a freshness rank,
and produces a `sort_key` the picker appends to its own key:

```
(priority, status, *freshness, id)
```

Two signals (both chosen deliberately; see "Out of scope"):

1. **Never-attempted first** — a unit with zero recorded attempts outranks any
   attempted unit. This is the direct "pick up new not-started work" signal.
2. **Staler last-attempt first (LRU)** — among attempted units, the
   least-recently-tried sorts first, so attention rotates across the residual and
   nothing is permanently starved.

The `sort_key` is `(0, 0)` for a never-attempted unit and `(1, last_attempt_ms)` for
an attempted one. Lower wins (matching the host's lower-wins tuple sort): fresh work
sorts before all attempted work, then attempted work sorts oldest-attempt-first.

## Why this is safe — the tie-breaker invariant

> **Freshness is appended AFTER `(priority, status)`, so it can only reorder WITHIN a
> priority/status tier — it never gates a unit in or out, and never reorders across
> tiers.**

Each consequence is load-bearing:

- **Priority is never overridden.** A P1 unit always outranks a P2 unit, attempted or
  not. Freshness only decides between two units that were *already* tied on priority
  and status. (Contrast strengthening the cooldown gate, which *could* starve a ready
  high-priority unit by holding it out.)
- **Order changes, admissibility does not.** Freshness cannot keep work out and
  cannot let held work in — it is not a gate. A bug here produces "wrong order,"
  never "starved work" or "double-booked lane." This is the same shape as the
  overlap-policy floor ("a swappable scorer can only refuse-MORE, never admit"): here
  the primitive can only *reorder-within-tier*, never *gate*.
- **Fail-open to fresh.** A missing or garbled attempt record degrades a unit to
  `NEVER_ATTEMPTED` (sorts first) — the pre-fix behaviour, never a refusal. This
  matches the `cooldown` ledger's own observability-grade posture: an unreadable row
  can only DELAY a re-pick, never wedge a clean unit. The safe direction for an
  *ordering hint* is "treat it as fresh," the opposite of the correctness-read
  refuse-don't-guess floor.

## Why a kernel primitive, not a host tweak

The attempt ledger and the fold that collapses it to "latest attempt per unit"
already live in the kernel's orbit (`cooldown`; the job repo's `pick_cooldown.py`
exposes `latest_attempts`). Re-implementing the freshness logic inline in the host's
`fanout_state.py` would duplicate that fold — and docs/168 records that *every*
re-implementation of a picker concept in host code became a fleet-wide wedge (the
drain-trap, the picker-invisibility gap). So the mechanism goes in the kernel, the
host keeps only the I/O:

- The kernel exposes `classify(unit_id, AttemptSummary) -> PickPriority`.
- The host reads the ledger (it already does, for the gate), reduces it to an
  `AttemptSummary` per unit, and appends `PickPriority.sort_key` to its sort key.

No new disk reads: the data the freshness signal needs is the data the cooldown gate
already gathers.

## What ships

- **`src/dos/pick_priority.py`** — `AttemptSummary` (the per-unit fact), `Freshness`
  (NEVER_ATTEMPTED / ATTEMPTED), `PickPriority` (the verdict + `sort_key`), and the
  pure `classify`. No I/O, never raises, no config table.
- **`dos pick-priority UNIT`** — the read surface, shaped exactly like `dos cooldown`
  (gather `OP_ATTEMPT` from the lane journal at the boundary, or `--attempts <json>`
  for replay). The verdict IS the exit code: NEVER_ATTEMPTED=0, ATTEMPTED=3 — so
  `dos pick-priority U && pick U` reads naturally.
- **`tests/test_pick_priority.py`** — the pure fold, the **ordering contract**
  (`[never, stale, recent]`), the **cross-tier safety** assertion (a P1 attempted
  unit beats a P2 fresh one), fail-open, and the CLI smoke test.

## Host wiring (follow-on, in the job repo)

In `fanout_state.py`'s `_rung_candidates` (`by_slot_then_status` rung), build the
latest-attempt map once, then append the kernel sort_key to the existing `key()`:

```python
from dos import pick_priority as _pp
# ...
return (slot_r, stat_r, *_pp.classify(pid, summary).sort_key, str(p.get("id") or ""))
```

A plan is "attempted" iff any of its phases has an attempt row; its `last_attempt_ms`
is the max over its phases (most-recent attempt on the plan). The `id` tiebreaker
stays last, so replay determinism is preserved. The same one-line append goes in
`next_up_render.py`'s sort so the rendered board agrees with what the loop picks.
This is a separate commit in the job repo (a different repository), picked up via the
editable `dos-kernel` install.

## Out of scope (explicitly)

Two further freshness signals were considered and **not** built — they add policy
and were not requested:

- **Attempt-count backoff** — rank attempted units by *how many times* they were
  tried (18× sorts below 1×). A natural extension; would add a tunable and so a
  `[pick_priority]` config table. Not built.
- **Quiet-incomplete demotion** — sort a `reconcile`-flagged QUIET_INCOMPLETE unit
  (claimed-done but the oracle says not-shipped) below honest-open work, since
  re-picking it just re-confirms the same false claim until a verifier/replan
  intervenes. A clean follow-on that joins `pick_priority` to `reconcile`. Not built.

Also unchanged: `cooldown` itself, the cooldown windows, the gate behaviour, and the
arbiter. This adds an *ordering* layer above the existing gates; it touches nothing
about *admissibility*.
