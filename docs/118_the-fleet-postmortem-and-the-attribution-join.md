# 118 — The fleet postmortem & the attribution join (closing the WAL `run_id` gap)

> **Status:** PLAN (not yet built). Re-derived 2026-06-03 against the *live* binary
> by running `scripts/trajectory_audit.py` on this repo and probing the journal
> writers directly — not from a memory note (the memory's "18 AMBIGUOUS_JOIN /
> benchmark-only" figure was already stale; see §1). The plan's load-bearing claim
> is a measured gap, not an assumed one.
>
> Sibling to the strategy essay it makes true —
> `dos-strategy/dispatch-os-trajectory-audit-and-the-attribution-substrate.md` §6.4
> ("a wedge dressed as a moat until the dispatch-path WAL writer lands"). That essay
> argues *why* DOS is the attribution substrate the postmortem literature lacks; this
> plan is the *one build* that converts the argument's flagship artifact from a shape
> demo into a recorded receipt. It is also the consumer-side complement to
> [`117`](185_native-log-adapters-and-the-actor-witness-split.md) (which adds *new
> evidence sources*) and [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) /
> [`LJ`](#) (the lane-journal WAL this plan finishes the write-side of).

## Problem (one line)

DOS's most defensible audit artifact — *"the agent burned tokens while the kernel was
refusing its lane"* — cannot fire on real data, because **no producer writes a lane
lease that carries BOTH the run-id and the loop-ts the join needs to confidently tie a
session's wasted-token window to the lane that was refused under it.**

## What was actually measured (2026-06-03, this repo, live binary)

Run `scripts/trajectory_audit.py --workspace . --last 15 --format json` and read the
`journal` / `join` blocks; then read `.dos/lane-journal.jsonl` directly through
`lane_journal.read_all` + `trajectory_audit.fold_journal`. The findings — each a fact,
not a recollection:

1. **The journal is volatile and mixed, not statically "benchmark-only."** Within one
   session it held, in order: **real `dos lease-lane` ACQUIREs** (`loop_ts` set, e.g.
   `2026-06-01T21:48:18Z`; holders `wf-1`/`wf-3`; lanes `lane-a`/`lane-c`; real glob
   trees) at the head; **synthetic FleetHorizon exhaust** (`run_id: RID-…` set, `loop_ts`
   null, lanes `lane-NN`, `_expires_at` integer counters) at the tail; and — after a
   concurrent `dos journal compact` / fresh run truncated it mid-session — **zero
   entries**. The audit's `_journal_is_benchmark_only` correctly reported `false` on the
   mixed file (a real-looking entry flips it off, by design).
2. **The window floor silently empties the join.** `--last 15` (≈ the last two days of
   sessions) produced `journal.total_entries: 0` and **every session as
   `trajectory_only`** — because the real lease-lane entries were dated 2026-06-01,
   outside the derived floor. So today's *default* audit shows neither benchmark-only
   nor triples; it shows an empty journal-in-window and attributes nothing. (This is the
   honest current state, and it is *not* what the strategy essay's stale §6.4 figure
   claimed — corrected there in lockstep with this plan.)
3. **The precise producer gap, confirmed at the writer surface** (`lane_journal.py`):
   - `acquire_entry(lease, *, reason, prev_holder)` has **no `run_id` parameter.** It
     emits a `run_id` only if the *caller* pre-nested one into the `lease` dict.
   - The real effectful writer behind `dos lease-lane` stamps a genuine `loop_ts` and
     `holder` (`wf-1`) but **no `run_id`** on the lease.
   - The benchmark writer (`closed_loop.py`) stamps a `run_id` but **null `loop_ts`** and
     `lane-NN` lanes.
   - **Net: `ACQUIRE entries with BOTH loop_ts AND a lease.run_id = 0`.** Neither
     producer emits the join-ready shape.
   - By contrast `refuse_entry` / `halt_entry` **already carry `run_id`** — the refusal
     side is run-id-ready; only the *acquire* side is not. (`refuse_entry`'s own
     docstring already names the trajectory audit as a consumer.)

The join logic is **not** the gap. `trajectory_audit.fold_journal` already reads
`lease.run_id` (`_lease_run_id`), already recovers refusals both ways
(`op==REFUSE` OR `op==ACQUIRE` w/ `REFUSED:` reason), already detects benchmark-only,
and already reports `AMBIGUOUS_JOIN` rather than guessing. The consumer is built and
tested. **The single missing piece is a producer that stamps `run_id` onto the
lease at acquire time on the real dispatch path.**

## Goal

Make the contention-vs-waste join produce **confident `(session, run_id, lane)`
triples on recorded data from a real multi-agent run**, with `AMBIGUOUS_JOIN` shown
honestly wherever the time-overlap is not 1:1 — and package the result as a named
operator artifact (`dos postmortem`, a thin projection, no new kernel verdict).

Two payoffs, ranked:

1. **Truth/receipt (the deeper win).** Convert the strategy essay's strongest claim
   from *asserted* to *demonstrated*: a report that reads "here is what the agent said
   (the trajectory), here is what the kernel adjudicated (the lease + the refusal),
   here is the divergence — **recorded, not estimated**." That is the artifact to put
   in front of an AI-SRE / agent-observability buyer, and the thing that distinguishes
   DOS from a better-organized transcript.
2. **The decisive-error timestamp for free.** With `liveness` already shipped (docs/82,
   99) and the journal carrying real beats, the report can stamp the
   ADVANCING→SPINNING/STALLED transition — the literature's "decisive error" (AgenTracer)
   — from counting commits/beats, where the external state of the art spends a trained
   8B model + fault injection.

## Non-goals (the line that keeps this a thin projection, not a new verdict)

- **No new kernel syscall, no new verdict vocabulary.** `dos postmortem` is a *helper*
  (layer 3), a projection over `lane_journal.replay` + the verdict envelopes +
  `liveness.classify` + the trajectory fold — the same posture as `dos decisions` /
  `dos top`. It adjudicates nothing new.
- **No fabricated join key.** There is still no shared field between a transcript
  (`sessionId/cwd/gitBranch/timestamp`) and a lease (`run_id/lane/loop_ts`). The join
  stays **time-window + workspace overlap**, and a non-1:1 overlap stays
  `AMBIGUOUS_JOIN`. Stamping `run_id` on the lease does **not** create a transcript↔lease
  key — it makes the *journal side* of a confident overlap carry a stable identity, so a
  1:1 time match resolves to a *named* `(session, run_id, lane)` triple instead of an
  anonymous `(session, lane)` one. The honesty discipline (docs/103, the audit's own
  rules) is preserved verbatim.
- **No trust in the agent's self-narration.** The report's ground-truth columns come
  from git ancestry (`verify`), the WAL (`arbitrate`/refusals), and the commit/beat
  delta (`liveness`) — never from the trajectory's own "I did X." The trajectory is the
  *believed* column; the kernel artifacts are the *adjudicated* column; the headline is
  their divergence.
- **Do not widen `--slack-ms` to manufacture matches.** Loosening the overlap tolerance
  to turn AMBIGUOUS into triples is the exact anti-pattern the audit exists to refuse
  (fail toward no-match). The fix is a stable identity on the lease, not a sloppier
  window.

## The fix, in three sizes (smallest that is honest first)

### Size S — stamp `run_id` on the acquire (the load-bearing one-liner cluster)
Thread a `run_id` through the acquire write so a real `dos lease-lane` (and the
supervisor/dispatch driver) records it:

- Add an optional `run_id` to `acquire_entry` (mirroring `refuse_entry`/`halt_entry`),
  nesting it into the emitted `lease` so `replay` reconstructs it and
  `_lease_run_id` reads it. Pure constructor change, no behavior shift when `run_id` is
  absent (backward-compatible — existing entries without it still replay).
- Pass the caller's run-id at the `dos lease-lane acquire` boundary. The minter already
  exists (`run_id.mint`); the lease just needs to carry the id the loop is already
  running under (`DISPATCH_RUN_ID` env / the spine id, resolved at the CLI boundary,
  never inside a pure verdict — the `active_predicates` rule).
- **Exit gate:** a `dos lease-lane acquire` on a scratch workspace writes an ACQUIRE
  whose `lease.run_id` is a parseable `RID-…`; `fold_journal` over it yields a lease
  with non-null `run_id` AND non-null `loop_ts` (the join-ready shape that measured `0`
  today). One new test in `tests/test_lane_journal.py` asserting the round-trip.

### Size M — `dos postmortem` projection + a real-run fixture
- A thin `dos postmortem [--since …] [--start-sha …]` verb (helper layer) that runs the
  trajectory fold + the journal join + (with `--start-sha`) the liveness column, and
  renders the **divergence-first** report: per confident triple, the believed column
  (trajectory flags, tokens) beside the adjudicated column (lease taken? refused?
  liveness verdict?), with the contention-vs-waste hits at the top.
- A **recorded real-run fixture** for the test suite: a small captured journal +
  transcript pair exhibiting one genuine contention-vs-waste hit (a session with a
  waste flag whose joined lane shows a refusal in-window) and one honest
  `AMBIGUOUS_JOIN`. This is the regression anchor that proves the headline fires — and
  proves it *doesn't* over-attribute.
- **Exit gate:** `dos postmortem` over the fixture prints ≥1 confident triple with a
  contention-vs-waste hit and ≥1 `AMBIGUOUS_JOIN`, and the suite pins both.

### Size L — the settling experiment (the receipt the strategy doc points at)
Run the real loop end-to-end and capture the artifact:
1. Land Size S so the journal carries `(loop_ts, lane, run_id)` leases.
2. Run a genuine N-agent dispatch loop (or the FleetHorizon harness wired to the *real*
   writer, not the synthetic one) that produces both contention (refused lanes) and
   waste (looping sessions).
3. `dos postmortem` over it; confirm the headline flips: confident triples, refusals
   joined to wasteful sessions, the `liveness` decisive-error timestamp matching the
   wasted-token window — **on recorded data, AMBIGUOUS_JOIN shown wherever overlap isn't
   1:1.**
- **Exit gate:** a dated report under `.dos/audits/` that a buyer can read as
  "believed vs adjudicated, recorded not estimated." Cite it back into the strategy
  essay's §7, retiring the §6.4 hedge.

## Why this is correct, not just expedient (the discipline check)

- **It finishes a write-side the kernel already declared.** `refuse_entry`'s docstring
  calls the trajectory audit a consumer and itself "the missing PRODUCER"; LJ shipped
  the REFUSE/HEARTBEAT/CHECKPOINT producers (see memory: LJ write-side closure). The
  `run_id`-on-acquire is the *next* missing producer in that same closure, not a new
  concept.
- **It keeps the I/O at the boundary.** The run-id is resolved and the journal is read
  at the CLI/driver boundary; the fold and the join stay pure over materialized data —
  the `git_delta`/`journal_delta` → `liveness.classify` rule, unchanged.
- **It does not move a verdict.** No `arbitrate`/`is_shipped`/`liveness.classify` logic
  changes, so the docs/100 native-spine freeze line is untouched — `dos postmortem` is
  pure periphery (a renderer over existing verdicts), exactly the code docs/100 says is
  *free to churn*.
- **It preserves the honesty that is the whole point.** No fabricated key, no widened
  slack, no promoting AMBIGUOUS to a name. The plan's own §"what was measured" is
  written the way the audit reports the journal: state the stale figure, correct it
  against the live binary, attribute nothing the evidence doesn't support.

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Concurrent agent is editing `lane_journal.py` right now (it is — file is unstaged-dirty this session) | high | med | Size S is a small additive change to `acquire_entry`; coordinate/stage only that hunk; do not `git add -A`. If the concurrent work already adds `run_id` to acquire, this plan's S collapses to "verify it round-trips" — check first. |
| The real-run fixture bakes in a synthetic shape and masks the gap (the FleetHorizon trap) | med | high | The fixture MUST come from the *real* writer post-Size-S, or be hand-authored to the real shape (`loop_ts` AND `run_id` both set, real lane names) — never from `closed_loop.py`'s synthetic exhaust. |
| `run_id` on the lease is read as a transcript↔lease key (it isn't) | med | med | The non-goal is explicit and the join code stays time-window-only; add a test that two sessions overlapping one run_id-bearing lease still produce `AMBIGUOUS_JOIN`, not a guessed pick. |
| Volatile journal (compaction truncates it mid-audit, as observed) makes the report non-reproducible | med | low | The audit already injects the clock and reads once (no tailing); for the receipt, snapshot the journal into the dated `.dos/audits/` artifact so the report is pinned to the bytes it read. |

## Exit criteria (whole plan)

1. **Measured gap closed:** an ACQUIRE on the real path carries both `loop_ts` and a
   parseable `lease.run_id`; `fold_journal` yields the join-ready shape that measured
   `0` on 2026-06-03.
2. **Headline fires honestly:** `dos postmortem` over a real (or real-shaped) run prints
   confident `(session, run_id, lane)` triples with ≥1 contention-vs-waste hit AND ≥1
   `AMBIGUOUS_JOIN`, pinned by a fixture test.
3. **No regression / no verdict moved:** the Python suite stays green; no
   `arbitrate`/`is_shipped`/`liveness` logic changed; `dos postmortem` is a pure
   projection.
4. **Strategy receipt:** a dated report exists that backs
   `dispatch-os-trajectory-audit-and-the-attribution-substrate.md` §7, and that doc's
   §6.4 hedge is updated to point at it.

## See also

- `dos-strategy/dispatch-os-trajectory-audit-and-the-attribution-substrate.md` — the
  positioning this plan makes true (§6.4 is the hedge it retires).
- [`117`](185_native-log-adapters-and-the-actor-witness-split.md) — the evidence-source
  axis `dos postmortem` would *consume* (the actor-witness test for which columns count
  as adjudicated vs believed).
- [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) / [`99`](99_runtime-validation-and-the-actuation-boundary.md)
  — `liveness` + `refuse`, the adjudicated columns of the report.
- [`100`](100_native-spine-port-plan.md) — the freeze line this plan stays on the
  *periphery* side of (a renderer, not a verdict).
