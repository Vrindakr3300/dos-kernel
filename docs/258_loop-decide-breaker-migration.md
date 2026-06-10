# 258 — the `loop_decide` → `breaker` migration (closing job-queue #506)

> **Status:** plan + build (2026-06-08). The forcing function is the host
> reference app's routed queue item **#506** ("consecutive-unproductive-replan
> breaker, via `dos.breaker`"). #506 asked for ONE new rung expressed through the
> shipped breaker primitive "NOT a 6th hand-written inline counter"; the operator
> widened the scope to *also* migrate the existing five inline counters onto
> `dos.breaker` in the same pass — realizing the goal `breaker.py`'s own docstring
> states ("DOS already has this pattern six times over … lift the mechanism into
> one pure leaf"). This doc is the mechanism-preserving mapping + the one new rung.

## Why this is safe to do now

#506 was **routed, not landed**, explicitly "to avoid colliding with the kernel
migration" — the `loop_decide`→`breaker` work that was in-flight in this repo. As
of 2026-06-08 that work has settled: `src/dos/breaker.py` is committed (`44bd8c8`),
the `dos breaker` CLI verb ships (`cli.py:cmd_breaker`), `dos.toml`'s `[breaker]`
seam exists, and the working tree is clean (no dirty `breaker.py` / `decisions.py`
/ `loop_decide.py` / `docs/223`). The blocker has cleared; #506 is unblocked.

## The invariant: BYTE-IDENTICAL for every existing path

`loop_decide.decide()` is a PURE function pinned by a large green suite
(`tests/test_oracle_and_loop.py`). The migration is **mechanism-preserving**: it
replaces hand-written `streak = x + 1; if streak >= max: stop` arithmetic with a
call to `breaker.record_failure` / `record_success`, which does *exactly* that
(bump both counts, then `_classify` trips on `>=`). No existing test may change.

Two facts make this clean:

1. **No code outside `loop_decide.py` reads the `LoopState` counter fields.** A
   grep over `src/` finds only docstring *mentions* in `breaker`/`completion`/
   `liveness`. So the internal counting representation is free to change.
2. **But the field SURFACE must stay backward-compatible.** Tests and the host
   driver construct `LoopState(consecutive_stale_stamp=…, max_unclear=…, …)` and
   read `next_state.consecutive_unproductive_replan_drains`. Those public int
   fields STAY. What changes is that `decide()` derives a `BreakerCounts` /
   `BreakerPolicy` from them, calls the primitive, and writes the result back into
   the SAME int field. The mechanism is lifted; the surface is untouched.

This is the "I/O at the boundary, data to the pure core" rule applied to state: the
loop's int counters are the boundary representation; the breaker fold is the core.

## The six breakers, mapped

Each existing inline breaker is **consecutive-only** (no cumulative/flapping rung),
so each maps to `BreakerPolicy(max_consecutive=<the max field>, max_total=0)`. The
trip is `>=` in both the inline code and `breaker._classify` → identical.

| Rung (StopReason) | counts field | max field | reset rule | trip → |
|---|---|---|---|---|
| `CONSECUTIVE_UNCLEAR` | `consecutive_unclear` | `max_unclear` | any non-UNCLEAR non-fault outcome | stop |
| `CONSECUTIVE_OVERLOADED` | `consecutive_overloaded` | `max_overloaded` | any non-OVERLOADED outcome | stop (else `retry-same-iter` w/ backoff) |
| `CONSECUTIVE_DIRTY_ZERO` | `consecutive_dirty_zero` | `max_dirty_zero` | any healthy SHIPPED / REPLAN_DONE / GATE | stop (else continue) |
| `STALE_STAMP_UNRECONCILED` | `consecutive_stale_stamp` | `max_stale_stamp` | SHIPPED, or a non-stale-stamp gate (LIVE/DRAIN/RACE); SURVIVES REPLAN_DONE | stop |
| `BENIGN_DRAIN` | `consecutive_unproductive_replan_drains` | `max_unproductive_replan_drains` | productive replan, ship, non-DRAIN gate | stop (checked on the next DRAIN) |
| **`REPLAN_STALLED` (NEW, #506)** | `consecutive_unproductive_replan` | `max_unproductive_replan` | any PRODUCTIVE replan, any SHIPPED, any non-stale gate | stop on the Kth unproductive REPLAN_DONE itself |

The migration keeps the *idiosyncratic reset rules* exactly — those are POLICY
encoded at each call site (which outcome resets which counter), and `breaker` only
owns the bump/compare/trip MECHANISM. `record_success` (resets consecutive, keeps
total) is the right primitive for "a clean outcome heals this breaker"; for the
counters whose reset is conditional/positional (stale-stamp surviving REPLAN_DONE),
the call site decides whether to call `record_failure` / `record_success` /
neither, just as today it decides whether to `+1` / set-0 / leave-be.

### The `max == 0` degenerate case (preserved)

Inline today, `max_unclear=0` means "trip on the first" (`streak = 0+1 = 1 >= 0`).
But `BreakerPolicy(max_consecutive=0, max_total=0)` RAISES (a breaker that can never
trip is a config error). To stay byte-identical for a caller that passes `max=0`,
the migration routes through a thin local helper `_breaker_fail(consecutive, max)`
that returns `(new_consecutive, is_open)`: when `max == 0` it reproduces the inline
"trip on first" (`new = consecutive+1`, `is_open = new >= 0` → always True); when
`max > 0` it calls `breaker.record_failure(BreakerCounts(consecutive), BreakerPolicy(max_consecutive=max, max_total=0))`.
In practice every default max is ≥ 2, so the breaker path is the one that runs; the
guard exists only so the migration changes NO behavior at the degenerate boundary.

## The new rung: `REPLAN_STALLED` (#506)

**Why it is not already covered by `BENIGN_DRAIN`.** `BENIGN_DRAIN` counts only
unproductive replans **bracketed by a DRAIN gate** (`last_gate_was_drain`), and
`tests/test_oracle_and_loop.py::test_benign_drain_unproductive_replan_without_prior_drain_no_count`
PINS that an unproductive replan NOT preceded by a DRAIN must not increment it.
That is exactly #506's measured STALL: loop `20260607T173259Z/iter-2` ran a 53-turn
`/replan` that logged *"skip gate says PROCEED (new_findings=0 but
git_substantive_count>0)"* — commits HAD landed (so the gate was not a DRAIN) yet
the replan refilled nothing. The lane is **not empty** (the `BENIGN_DRAIN` case);
`/replan` is just **expensive and unproductive** (16-22 min / ~$5 / 0 refill),
twice in a row. `BENIGN_DRAIN` = "lane drained"; `REPLAN_STALLED` = "replan keeps
doing costly nothing regardless of why." Complementary, not duplicate.

**Semantics.** A new `consecutive_unproductive_replan` count + `max_unproductive_replan`
threshold (default 2 — #506: "trip on the 2nd unproductive `REPLAN_DONE`"). In the
`REPLAN_DONE` branch (5b): an UNPRODUCTIVE replan does `record_failure`; a PRODUCTIVE
replan does `record_success` (the sweep refilled — the stall cleared). A SHIPPED
iteration and a non-stale gate also reset it (the lane moved). On OPEN, stop with
`StopReason.REPLAN_STALLED` + surface. **Opt-in / byte-identical:**
`max_unproductive_replan` defaults to 2 but the count starts 0 and only an
UNPRODUCTIVE `REPLAN_DONE` (`outcome.replan_productivity == UNPRODUCTIVE`) ever
bumps it — a caller that never classifies replan productivity (the conservative
`PRODUCTIVE`-when-None default, FQ-240) never trips it, so un-migrated callers are
unaffected. This is the same opt-in discipline as `BENIGN_DRAIN`.

**Placement.** Inside the `REPLAN_DONE` branch (5b), checked AFTER the productivity
classification (it needs it) and as a STOP that pre-empts the continue. It is
mutually compatible with `BENIGN_DRAIN`: `REPLAN_STALLED` trips on the Kth
unproductive replan *itself* (K=2), so on a pure benign-drain spin
(DRAIN→unprod→DRAIN→unprod→DRAIN) it would fire on the 2nd unprod replan — one step
*before* `BENIGN_DRAIN`'s 3rd-DRAIN stop. To keep the existing `BENIGN_DRAIN`
trajectory test green, `REPLAN_STALLED` is checked with the SAME default threshold
the operator's measurement gives (2) but ONLY when the new counter is *fed* — and
the existing benign-drain tests construct state with the OLD field
(`consecutive_unproductive_replan_drains`), never the new one, so they do not feed
`consecutive_unproductive_replan` and stay on the `BENIGN_DRAIN` path exactly. A
caller that feeds BOTH gets `REPLAN_STALLED` first (the broader, earlier stop),
which is the correct #506 behavior.

## Host side (the job repo — NOT this commit)

#506's other half is `scripts/dispatch_loop_iter_driver.py` in the host repo:
classify each `/replan`'s productivity (already done — `ReplanProductivity` is fed
for the FQ-240 drained-twice rung) and pass it through so the new counter is fed.
That is a host shim edit, lands in the reference userland app, and is out of the kernel lane.
This doc + the kernel change unblock it; the queue row stays open until the driver
feeds the counter.

## Test plan

- All existing `tests/test_oracle_and_loop.py` + `tests/test_breaker.py` stay green
  (the byte-identical proof).
- New tests for `REPLAN_STALLED`: trips on the 2nd consecutive UNPRODUCTIVE
  REPLAN_DONE; a PRODUCTIVE replan resets; a SHIPPED resets; opt-in default state
  (no productivity fed) is byte-identical; a single unproductive replan does not
  trip; it fires independently of a prior DRAIN (the gap `BENIGN_DRAIN` leaves).
- A migration-fidelity test or two asserting the breaker-backed counters still hit
  their existing StopReasons at the same thresholds (covered by the existing suite).
