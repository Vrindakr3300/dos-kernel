# 137 — The trace spine & the cross-surface join (`dos trace <run_id>`)

> **Status:** PLAN + BUILD (this doc lands with the code). The load-bearing claim
> — "a lease/refusal carries no `run_id`, so you cannot walk from a denied lane
> back to the run that wanted it" — is the gap [`118`](118_the-fleet-postmortem-and-the-attribution-join.md)
> *measured* against the live binary on 2026-06-03 (ACQUIREs with both `loop_ts`
> AND `lease.run_id` = **0**), and `journal_delta`'s module docstring names in
> prose ("THE HARD PROBLEM: a journal entry carries **no run-id**"). This plan
> finishes the write-side docs/118 specced (Size S) and adds the **reader** that
> makes the now-connected spine traversable end-to-end.

## Problem (one line)

DOS has a correlation **spine** (`run_id` + `parent_id`/`root_id`, sortable,
lineage-carrying) and three durable surfaces that should compose — the WAL
(`lane_journal`), the intent ledger (`intent.jsonl`), and git — but **there is no
verb to walk from one part of DOS to the others**, and the one structural break
that would block such a walk (the WAL's ACQUIRE not carrying `run_id`) is still
open. So "show me everything this run touched — its lineage, the lanes it took,
the refusals it hit, the steps it claimed vs the kernel verified, the commits it
landed" is a manual, multi-file, multi-key eyeball pass.

## What already joins, and the one break (the inventory)

| Surface | Keyed by | Carries `run_id`? | Joinable to the spine? |
|---|---|---|---|
| Spine (`run.json`) | `run_id` | — (it IS the id) | ✅ root of the join |
| Intent ledger (`intent.jsonl`) | `run_id` (run-dir name) | ✅ by construction (docs/107 §3.1) | ✅ direct |
| WAL — `OP_REFUSE` / `OP_HALT` | `(loop_ts, lane)` | ✅ already (`refuse_entry`/`halt_entry` take `run_id`) | ✅ when the writer passed it |
| WAL — `OP_ACQUIRE` / `RELEASE` / `HEARTBEAT` | `(loop_ts, lane)` | ❌ **the break** — `acquire_entry` has no `run_id` param | ❌ time-window guess only |
| git | SHA | — | ✅ via the ledger's `start_sha` + `STEP_VERIFIED.sha` |

The asymmetry is the whole bug: the **refusal** side of the WAL is run-id-ready,
but the **grant** side is not. So you can already trace a *denied* lane to its run,
but not a *held* one — and a held lane is exactly what a postmortem ("the agent
burned tokens while holding lane X") needs. Closing it is a one-field additive
change docs/118 already designed; this doc lands it and then reads across it.

## The two builds

### Build 1 — stamp `run_id` on the acquire (docs/118 Size S, the load-bearing field)

- `lane_journal.acquire_entry(lease, *, run_id="")` — a new OPTIONAL kwarg,
  mirroring `refuse_entry`/`halt_entry`. When given, it nests `run_id` onto the
  emitted `lease` (so `replay` reconstructs it and any reader — `decisions`,
  `trajectory_audit._lease_run_id`, the new `trace`) reads it off the live lease).
  **Purely additive**: an ACQUIRE with no `run_id` replays byte-identically (the
  lane-journal forward-compat contract — the same posture `env_digest`/`children`
  already ride).
- `lane_lease.acquire(..., run_id="")` threads the caller's run-id into both the
  ACQUIRE **and** the genuine-collision REFUSE it already writes (so a refused
  acquire also carries the id, completing the refusal side for the live writer).
- `dos lease-lane acquire --run-id RID-…` resolves the id at the **CLI boundary**
  (explicit flag › `CID_RUN_ID` env › `DISPATCH_RUN_ID` env › none) and passes it
  in — never inside a pure verdict (the `active_predicates` rule). The minter
  already exists (`run_id.mint`); the lease just carries the id the loop already
  runs under.
- **Exit gate:** a `dos lease-lane acquire --run-id RID-…` on a scratch workspace
  writes an ACQUIRE whose `lease.run_id` is a parseable `RID-…` AND a non-null
  `loop_ts` — the join-ready shape docs/118 measured at `0`. Pinned in
  `tests/test_lane_journal.py` (round-trip) + `tests/test_trace.py`.

This stays strictly inside the **non-goal** docs/118 fixed: stamping `run_id` on
the lease does **not** fabricate a transcript↔lease key. It makes the *journal
side* of a join carry a stable identity, so a reader keyed on `run_id` resolves a
lease to a *named* run instead of an anonymous `(loop_ts, lane)`.

### Build 2 — `dos trace <run_id>` (the reader; a layer-3 projection, no new verdict)

A thin, read-only projection — the same posture as `dos decisions` / `dos top` /
`dos plan` (a reader over kernel state, stores nothing, takes no lease, adjudicates
nothing). It assembles one **TraceFrame** for a `run_id` by joining, in order:

1. **Spine** — `run_id.read_run_json(run_dir)` → the id + lineage
   (`parent_id`/`root_id`/`process_id`/`ts_ms`). Ancestors/descendants are a
   `root_id` scan over sibling run-dirs (cheap, optional).
2. **Intent** — `intent_ledger.read_all(run_id)` → `replay` → the `LedgerState`:
   the declared goal/plan/phase, `start_sha`, `declared_steps`, and crucially the
   **claimed-vs-verified** split (the residual = declared − verified, the same
   epistemic surface `resume` reads).
3. **WAL** — `lane_journal.read_all` filtered to THIS run: every lease event
   (ACQUIRE/RELEASE/HEARTBEAT/SCAVENGE — now joinable via Build 1's
   `lease.run_id`), plus every `OP_REFUSE`/`OP_HALT` carrying this `run_id`. The
   lease identities (`(loop_ts, lane)`) this run held/was-refused.
4. **git** — the commits since `start_sha` (`git_delta.commits_since`, the same
   reader `liveness`/`timeline` use) + which `STEP_VERIFIED.sha`s are in ancestry.

The frame renders **provenance-first**: who the run is (lineage), what it tried
(intent), what it touched (lanes), what it actually shipped (verified steps +
commits) — with the believed column (claimed) beside the adjudicated column
(verified), the divergence visible. `--json` emits the whole join for tooling;
the plain text is the operator floor.

- **The honesty discipline is inherited verbatim (docs/103 / docs/118):** the
  *adjudicated* columns (verified steps, commits, refusals) come from git ancestry
  + the WAL, never the agent's self-report. `claimed` is shown as believed and
  labelled as such. A lease event that does NOT carry a `run_id` (a pre-Build-1
  ACQUIRE, or a writer that didn't pass one) is shown under a **`(unattributed)`**
  bucket with an honest note — never silently dropped and never guessed onto this
  run by a time window (the docs/118 "fail toward no-match" rule).

## Non-goals (the line that keeps this a projection, not a syscall)

- **No new verdict, no new vocabulary.** `dos trace` adjudicates nothing — it
  reads existing verdicts/effects and joins them. The exit code is `0` (found) /
  `1` (no such run). It is not a `verify`/`arbitrate`/`liveness` and does not move
  any of them (the docs/100 native-spine freeze line is untouched — `trace.py` is
  pure periphery, the code docs/100 says is free to churn).
- **No fabricated join key.** The only join keys are the ones that already exist:
  `run_id` (spine ↔ ledger ↔ now-WAL), `(loop_ts, lane)` (within the WAL), and
  SHA (ledger ↔ git). No transcript↔lease key is invented; a lease with no
  `run_id` stays `(unattributed)`.
- **No write.** `trace` reads; it never appends to the WAL or the ledger, never
  takes a lane, never proposes an effect. (Contrast `resume`, which MINTS a
  `RESUME_PROPOSED` — `trace` is the pure read of the same surfaces.)
- **It is not a `correlation_id`/`trace_id`/UUID retrofit.** DOS already has the
  right id (`run_id` — sortable, lineage-carrying). The fix is to make every
  surface *carry the existing id* and to *read across it*, not to mint a second
  parallel id. (A new opaque UUID would be a second spine to keep in sync — the
  exact `[[project-dos-memory-is-an-unverified-agent]]` failure mode at the
  identity layer.)

## Why this is correct, not just expedient

- **It finishes a write-side the kernel already declared.** `refuse_entry`'s
  docstring already names the trajectory audit as a consumer and itself "the
  missing PRODUCER"; LJ shipped the REFUSE/HEARTBEAT/CHECKPOINT producers. The
  `run_id`-on-acquire is the *next* missing producer in that same closure (docs/118
  Size S), not a new concept.
- **It keeps I/O at the boundary.** The run-id is resolved + the surfaces are read
  at the CLI/driver boundary; the join + render stay pure over materialized data —
  the `git_delta`/`journal_delta` → pure-fold rule, applied to a third reader.
- **It is the operator-facing payoff of the spine.** docs/64 minted the id and
  carried lineage "so the dispatch → next-up → fanout tree is a *join*, not a
  timestamp-grep." `dos trace` is that join, finally performed by a verb.

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Concurrent agent editing `lane_journal.py` / `cli.py` (the tree is dirty this session) | high | med | Build 1 is a small additive kwarg on `acquire_entry`; stage only the hunks this change touches, never `git add -A`. If a concurrent change already added `run_id` to acquire, Build 1 collapses to "verify it round-trips" — check first. |
| A reader mis-attributes a `(unattributed)` lease onto the run by time-window | med | high | Explicit `(unattributed)` bucket + the docs/118 "no widened window, fail toward no-match" rule, pinned by a test: a lease with a blank `run_id` never appears under a named run's lanes. |
| Volatile journal (compaction truncates mid-read) makes a trace non-reproducible | low | low | `trace` reads once (no tailing), the `read_all` torn-tail contract; the frame is a snapshot of the bytes it read. |
| `trace` re-implements a join `trajectory_audit`/`decisions` already have | med | low | Reuse the existing readers verbatim (`lane_journal.read_all`, `intent_ledger.replay`, `git_delta.commits_since`); `trace.py` only assembles + renders, it defines no new read. |

## Exit criteria

1. **Break closed:** an ACQUIRE on the real path carries both `loop_ts` and a
   parseable `lease.run_id`; `lane_journal.replay` reconstructs it onto the lease.
   (docs/118 Size S exit gate.)
2. **Traversal works:** `dos trace <run_id>` over a scratch run prints its lineage,
   intent (claimed-vs-verified), the lanes it held/was-refused, and its commits —
   joining all three surfaces by `run_id`, with `(unattributed)` shown honestly.
3. **No regression / no verdict moved:** the Python suite stays green; no
   `arbitrate`/`is_shipped`/`liveness`/`resume` logic changed; `trace` is a pure
   projection (`--json` round-trips; the readers degrade to empty on a missing
   surface).

## See also

- [`118`](118_the-fleet-postmortem-and-the-attribution-join.md) — the measured gap
  + Size S this plan lands (its postmortem reader is the sibling consumer of the
  same now-stamped lease).
- [`64`](64_correlation-id-spine-plan.md) (`run_id.py` header) — the spine this
  verb finally traverses ("a join, not a timestamp-grep").
- [`107`](107_resumable-work-and-the-intent-ledger.md) — the intent ledger +
  claimed-vs-verified split `trace` reads (and `journal_delta`'s "HARD PROBLEM"
  note, sidestepped by the ledger's `run_id` key).
- [`120`](120_the-status-digest-a-folded-fact-for-a-fleet.md) — the status digest
  (`status.py`): a *folded fact* over the same surfaces; `trace` is the *expanded
  walk* of one run where `status` is the fleet summary.
- `decisions.py` / `dispatch_top.py` — the projection posture `trace.py` mirrors
  (read-only, stores nothing, degrades on a missing source).
