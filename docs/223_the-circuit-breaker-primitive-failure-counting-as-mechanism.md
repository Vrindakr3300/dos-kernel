# 223 — The circuit-breaker primitive: failure-counting as mechanism

> **Status:** ✅ **Shipped** (2026-06-07). `src/dos/breaker.py` (the pure state
> machine), `dos breaker` (the CLI peek), `tests/test_breaker.py` (25 tests), the
> `dos doctor --json` exit-contract row. This is the build of idea **H2** (with
> **H3** folded in) from the Claude Code source audit (docs/189). It is the second
> loop-economics lift, after the productivity verdict (docs/218).

## What this is, in one sentence

Count failures of one kind; when too many pile up, **open the circuit** — stop
hammering the broken path — and say *where to escalate*.

## The repetition it removes

A circuit breaker is the oldest idea in reliability: don't keep calling a thing
that keeps failing. DOS already has this idea — **six times**, hand-written inline
in `loop_decide`:

- `consecutive_unclear` — N crashed iterations in a row → stop.
- `consecutive_overloaded` — N server-overload (529) hits in a row → stop.
- `consecutive_dirty_zero` — N degraded-ship iterations in a row → stop.
- `consecutive_stale_stamp` — N unreconciled gate iterations in a row → stop.

Each one is the same shape, about fifteen lines:

```python
streak = state.consecutive_X + 1          # bump the counter
bumped = replace(state, consecutive_X=streak)
if streak >= state.max_X:                 # trip test
    return STOP(reason=...)               # tripped
return continue(...)                      # not tripped
# ...and elsewhere, on a clean outcome:
state = replace(state, consecutive_X=0)   # reset
```

The control logic — bump, compare, stop-or-continue, reset — is **identical** in
all four. What differs is only three things: *which* counter, *what* the threshold
is, and *what to do* when it trips. That split is the whole signal. The identical
part is **mechanism**; the three differing things are **policy**. The repetition is
the smell that says: lift the mechanism into one place, and make the policy data.

## Why it belongs in the kernel — the mechanism/policy test

This is the same `malloc` argument as the productivity verdict (docs/218), and it
is worth restating because the breaker is an even cleaner example.

`malloc` is in every C program because it is mechanism (hand out bytes) with policy
(what you allocate) pushed entirely out. A breaker hard-wired to "stop the dispatch
loop after 3 UNCLEAR iterations" can never be a shared cog: the `3`, the `UNCLEAR`,
and the `dispatch loop` are all someone's policy welded into the mechanism. But a
breaker that knows *only* "this failure class has now failed N times in a row (or M
times total), and the policy says that is too many" **can** be universal — because
the caller names the class, the thresholds, and the response.

The proof that the cog is universal is structural: `breaker` is handed **counts**,
never the failure's **identity**. No `UNCLEAR` token, no `OVERLOADED` enum, no host
vocabulary reaches it — just two integers. It is impossible for the module to
smuggle in a host assumption, because it never learns what failed. That is the
sharpest form of the kernel-imports-no-host litmus: the kernel cannot name a host
concept it is never told.

## Two counters, lifted from Claude Code

The audit found this same pattern already generalized in CC — not in the loop, but
in the permission system: `src/utils/permissions/denialTracking.ts`. And CC's
version is *richer* than DOS's inline breakers, in a way that matters. It tracks
**two** counters and trips on **either**:

```ts
export function shouldFallbackToPrompting(state) {
  return (
    state.consecutiveDenials >= DENIAL_LIMITS.maxConsecutive ||  // 3
    state.totalDenials >= DENIAL_LIMITS.maxTotal                 // 20
  )
}
// recordSuccess resets consecutive — but NOT total.
```

The two counters catch two different failures, and you genuinely need both:

- **consecutive** catches a **sustained** failure — N in a row, a path that is
  simply broken right now. It resets the moment anything succeeds: the incident
  cleared, start over.
- **total** catches a **flapping** failure — fail, succeed, fail, succeed, fail…
  — a path that is *unreliable* but not consistently down. A consecutive-only
  breaker never trips on this (the streak keeps resetting to 1), yet it is exactly
  the kind of intermittent fault you want to give up on. The cumulative count,
  which **never resets**, is the only thing that sees it.

DOS's six inline breakers are all consecutive-only. So they are all **blind to
flapping** — a `/dispatch` that fails every other iteration forever would never
trip `consecutive_unclear`. Lifting CC's two-counter shape fixes that bug for free,
the moment a breaker re-expresses on `dos.breaker`.

The reset asymmetry is load-bearing and easy to get wrong: a success resets
`consecutive` (the outage cleared) but **not** `total` (a path that has failed
twenty times is unreliable no matter how many times it also succeeded). So a
success can *close* a consecutive-tripped breaker, but it cannot *un-trip* a
total-tripped one. That is the correct behavior, and the tests pin it.

## The DOS addition: the trip escalates a rung

CC's breaker, when it trips, does one thing: fall back to **prompting the human**.
That is a single fixed fallback. DOS already has a richer answer to "who decides
when the cheap mechanism is stuck" — the **trust ladder**, ORACLE → JUDGE → HUMAN
(docs/86, `dos.judges`). A deterministic oracle rules first; a non-deterministic
*advisory* judge rules only on the residue the oracle abstained on; a human rules
only at the irreducible seed.

So an open breaker in DOS does not merely say STOP — it names *where to escalate*,
on that ladder (idea H3 from the audit, "don't keep refusing identically; escalate
the rung"):

- **NONE** — advisory only. Report OPEN and let the caller decide. The safe
  default floor (the same advisory posture `liveness`/`productivity` hold).
- **JUDGE** — kick the stuck decision up to a non-deterministic adjudicator. "The
  deterministic path tripped four times; ask a model."
- **HUMAN** — surface to an operator (the `dos decisions` queue). The irreducible
  seed.

The rung is **monotonic in trust-cost**: a policy escalates *up* the ladder, never
down — you do not answer a stuck human with a deterministic re-check. The kernel
computes *which* rung the policy declared and whether the breaker is open; the host
decides what *acting on* an escalation means (re-dispatch under a judge, queue an
operator decision). This keeps the kernel a pure decision point: it reports the
trip and the rung; it never performs the escalation. Advisory, like every verdict
in this family.

## The shape

Three pieces, the `liveness`/`productivity` mould:

```
BreakerCounts(consecutive, total)        # the carried state — two integers
BreakerPolicy(max_consecutive, max_total, on_trip)   # thresholds + escalation rung
record_failure(counts, policy) -> BreakerTransition  # bump both, classify
record_success(counts, policy) -> BreakerTransition  # reset consecutive only, classify
classify(counts, policy)       -> BreakerVerdict      # read-only peek
```

`record_failure`/`record_success` are the **write path** — pure folds that return
the next `BreakerCounts` to carry plus the `BreakerVerdict` to act on, so a loop
threads them through its own state exactly as `loop_decide.decide` returns
`next_state` + the action. `classify` is the **read-only peek** — "given these
counts, is the circuit open?" — without mutating the stream. The CLI verb is the
peek; the write path is the library API a host loop uses.

There is deliberately **no HALF_OPEN state.** The classic breaker has a third state
("let one request through to test if the path recovered"). That is a *recovery
actuation* — a host's decision to retry — not a kernel verdict. BRK reports the
trip; whether and when to probe for recovery is the host's call, the same advisory
line that keeps every DOS verdict from acting.

## The CLI

The verdict IS the exit code, so a shell loop branches without parsing:

```bash
dos breaker --consecutive 3 --max-consecutive 3 --on-trip human
#   OPEN  3 consecutive failures (>= max 3) — a sustained failure, open the
#         circuit; escalate to HUMAN
#   exit 3

dos breaker --consecutive 1 --total 1 --max-consecutive 3 --max-total 5
#   CLOSED  1 consecutive / 1 total failures — under the limits; circuit closed
#   exit 0
```

CLOSED 0, OPEN 3, contract-error 2. A policy with both thresholds at 0 can never
trip — almost certainly a config mistake — so the kernel refuses it rather than
silently building a breaker that does nothing (the refuse-don't-guess discipline,
docs/117). Defaults are the CC constants: 3 consecutive / 20 total, escalation
NONE.

## What it makes buildable (the open right column)

Shipped as a primitive, not yet wired into `loop_decide` — the docs/79 restraint.
The space it opens:

1. **Re-express `loop_decide`'s six breakers on `dos.breaker`.** The direct
   payoff: replace `consecutive_unclear` / `consecutive_overloaded` /
   `consecutive_dirty_zero` / `consecutive_stale_stamp` (four near-identical inline
   blocks, ~60 lines) with four `BreakerPolicy` values and one call each. The host
   keeps its own *response* (a stop reason, a surface), but the bump/trip/reset
   mechanism stops being copy-pasted. **And every one of them gains the flapping
   (total) rung it lacks today, for free.** This is a host-side refactor (the
   reference app's loop), not a kernel change — the proof the cog is reusable.
2. **A flapping-failure breaker the loop cannot currently express.** Even before
   the refactor, a host can add a breaker for an intermittent fault (a tool that
   fails every third call) that no consecutive-only counter would catch.
3. **Escalate-on-repeat for any verdict.** The H3 use: if `liveness → STALLED` (or
   the same `refuse` reason) recurs N times for a lane, feed it to a breaker whose
   `on_trip` is JUDGE or HUMAN — turning "the same verdict, re-emitted forever"
   into "escalate the rung." The breaker is the mechanism; *which* verdict feeds
   it is the host's wiring.
4. **A `dos top` health chip.** An open breaker on a lane is a different color of
   trouble than a stalled run — the live TUI can read `classify` over a lane's
   recent failure counts.

## How it relates to the productivity verdict (docs/218)

These two are the loop-economics cluster from the audit, and they are
complementary, not overlapping:

- `productivity` watches a **success trend** — is the run doing less and less *good*
  work per step? (a fading rate)
- `breaker` watches a **failure count** — has one kind of thing gone *wrong* too
  many times? (a tripped limit)

A healthy run is PRODUCTIVE with all breakers CLOSED. A grinding run is DIMINISHING.
A run hitting a broken dependency is PRODUCTIVE-but-OPEN (it is doing real work,
except this one path keeps failing). Different axes, different verdicts, both
domain-free — exactly the small-primitives-that-compose design (docs/79).

---

*Provenance: idea H2 (with H3 folded in) from docs/189 (the Claude Code v2.1.88
source audit). Source shapes: `loop_decide.py`'s six inline breakers (the
repetition) and `denialTracking.ts` (the two-counter generalization). Built
2026-06-07 as `src/dos/breaker.py` + `dos breaker` + 25 tests.*
