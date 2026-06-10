# Garbage collection — reachability is a verdict, not a reference count

> **DOS has no managed heap, but it has the GC *problem* in two shapes the operator
> already feels: a *recurrent drain* (the append-only lane journal grows without
> bound, and every liveness poll re-reads and re-folds the whole of it — per held
> lease, per tick) and *noisy scratch pads* (per-project `.dos/runs/`, `.dos/verdicts/`,
> and the `~/.dos/*.jsonl` projections accumulate forever; only an operator verb ever
> trims any of them). The instinct is to reach for reference counting or a TTL. This
> note argues that instinct is *wrong in the DOS-specific way*, and that being wrong
> about it is the whole point: a garbage lease is a stale self-report, so **what is
> reachable is decided by an adjudicator (`liveness`), not by whether a reference
> (an `ACQUIRE` line) still exists.** Refcounting trusts the reference; the kernel
> doesn't believe references. GC in DOS is `verify()`/`liveness()` aimed at the
> kernel's own substrate — the same move [`103`](103_memory-is-an-unverified-agent.md)
> made for memory. It then specifies the cheap, sound collector the journal already
> half-implements: a generational split (beats die young, never reach the old
> generation), an auto-compaction *trigger* on the snapshot the kernel already
> computes, and a declared `[retention]` seam — answering the retention open question
> [`94 §7`](94_checkpoints-and-recovery-from-slop.md) left on the table.**

A theory-plus-spec note in the family of [`82_liveness`](82_liveness-oracle-plan.md)
(the verdict whose evidence-gather is the drain), [`94`](94_checkpoints-and-recovery-from-slop.md)
(which built `compact()` as an operator verb and explicitly **deferred** the
retention policy — "DOS needs its own policy"), [`101`](101_watchdog-driver-and-the-poll-cadence.md)
(the poller that pays the drain on a timer), and especially
[`103`](103_memory-is-an-unverified-agent.md) (a DOS substrate re-adjudicated by the
kernel's own distrust). Like 103 it points an existing syscall *inward*; unlike 103
the inward subject is not the memory store but the kernel's own write-ahead log and
scratch state. It proposes **no new syscall** — a *trigger*, a *generational tag*, a
*config seam*, and a *driver*, all assembly over `replay`/`compact`/`liveness`
already on master.

It exists because the drain is not hypothetical. §1 measures it from the code.

---

## 1. The two problems, named from the code (not hypothesized)

### 1.1 The recurrent drain — O(L × J) per tick, J unbounded

The lane journal ([`lane_journal.py`](../src/dos/lane_journal.py)) is the load-bearing
state: the arbiter's live-lease set, the liveness oracle's beat/event evidence, and
the forensic record all fold out of it. It is **append-only and not auto-rotated**
(`lane_journal.py:37-44`, `:202-207`: *"on a long-lived fleet it grows unbounded …
this is O(file)"*). Three reads all walk the **entire** file:

- `read_all` (`lane_journal.py:162`) — reads + JSON-parses every line, every call.
- `replay` — folds all entries to the live-lease set (O(J)).
- `journal_delta.fold_since` (`journal_delta.py:182`) — folds all entries to
  `(events-since-start, newest-beat-age)` for **one** lease (O(J)), scoped by lease
  identity, so it must be called **once per held lease**.

Compose those at the callers and the per-tick cost is super-linear in fleet size
*and* grows with runtime:

| Caller | Cadence | Per-tick journal cost |
|---|---|---|
| `dos top` (`dispatch_top.snapshot`) | **5 s** | one `read_all` + one `replay` (O(J)) |
| `dos watch` (`drivers/watchdog.tick`) | 300 s | per tracked run: `read_all` + `fold_since` → **O(N × J)** |
| `dos loop` (`cli._supervise_evidence`) | 300 s | `read_all` + `replay`, then `fold_since` **per held lease** → **O(L × J)** |

J = journal length = `ACQUIRE/RELEASE/SCAVENGE` (state ops) **plus every `HEARTBEAT`**.
A fleet of N leases beating every M seconds appends `N × (runtime / M)` lines. So J
climbs with wall-clock even at constant fleet size and constant beat rate, and `dos top`
re-reads-and-re-folds all of it twelve times a minute. **The per-tick cost of asking
"is anything stuck?" grows with how long the fleet has been running** — the precise
shape of a drain.

### 1.2 The noisy scratch pads — append-only projections nobody auto-reaps

Three categories accumulate, and the reaper coverage is partial-to-absent:

| Scratch | Where | Grows per | Reaper | Automatic? |
|---|---|---|---|---|
| **Heartbeat lines** | the WAL | beat | bundled into `compact()` | **no** — operator `dos journal compact` |
| **Run-dirs / `run.json`** | `.dos/runs/…` (`run_id.py`) | run | **none** | **no** |
| **Verdict sidecars** | `.dos/…/.verdict-*.json` | verify | **none** | **no** |
| **Central projections** | `~/.dos/{projects/index.jsonl, decisions.jsonl, roots.log}` (`home.py`) | persist | `dos reindex --prune` | **no**, and it only drops stale **projects** — never old decisions or run records |

The heartbeat is the noise *generator*. It is a keepalive, **not** a state transition
— `journal_delta` deliberately excludes it from the EVENT count and keeps only
`newest_beat_ms`, discarding every superseded beat (`journal_delta.py:295-301`). Yet
each beat lands as a permanent WAL line that every future `replay`/`fold` must read
and skip. The signal in a beat has a half-life of one tick; its cost in the log is
forever. **That is textbook short-lived garbage written into the old generation.**

---

## 2. Why reference counting is the wrong primitive here (the angle, taken seriously)

The request named reference counting specifically. It is worth taking seriously and
then rejecting *for a reason that is the kernel's whole thesis*, not for a hand-wave.

### 2.1 A lease has a "reference" (its ACQUIRE line) long after it is garbage

Refcounting collects an object when its inbound reference count hits zero. Model a
lease's `ACQUIRE` line as the reference and its `RELEASE` as the decrement, and the
scheme *appears* to work — `replay` already does exactly this fold (an unreleased
ACQUIRE is "live"). But it is **unsound for the case the kernel exists to handle**:
a worker that **crashed** never appended its `RELEASE`. Its refcount stays at one
forever. A pure refcounter would keep that lease live indefinitely and the arbiter
would refuse the lane against a dead holder — a leak that is also a deadlock.

This is the GC analogue of the cycle/leaked-owner problem that *forces* tracing
collectors to exist: **you cannot refcount your way to detecting that the thing
holding the reference is itself dead.** You need an independent reachability test.

DOS already has that test, and it is not a counter: it is `liveness.classify`
(`liveness.py:214`) plus the supervisor's `SCAVENGE` (`drivers/supervisor.py:122`).
A lease is *reachable* (live) not because its ACQUIRE line exists but because the
run behind it is **ADVANCING or freshly beating** — adjudicated from git delta +
journal beat, never from the lease's own say-so. Restated in the kernel's own law:

> **Reachability is not "a reference exists." Reachability is adjudicated liveness.**

A garbage lease is a *stale self-report* — the lease line says "I am held," the
process behind it is gone, and at scavenge time that claim is checked against ground
truth (the absence of forward delta / a fresh beat) rather than believed. That is
[`103`](103_memory-is-an-unverified-agent.md)'s pattern exactly — *"a prior commitment,
not a present fact; re-verify its content against ground truth, surface the verdict"*
— with the lease's ACQUIRE line in the role 103 gives the memory file's "FIXED in
cli.py:1000." **The collector that decides what is garbage must be an adjudicator,
not a refcount.** The kernel must not believe a lease is alive because its line
exists, exactly as it must not believe an agent shipped because it said so. GC is the
distrust primitive turned on the kernel's own heap.

(The refcount lens is not *useless* — it is the right model for the **ship-stamp /
verify** rung, where a commit's existence in ancestry IS the durable reference and
cannot lie about having happened. The distinction is the doc-102 line: refcount the
*structure that cannot misreport* — git ancestry — and adjudicate the *content that
can* — "is this holder still alive." Heartbeat = content; commit = structure.)

### 2.2 TTL is the same mistake wearing a clock

A per-lease TTL ("expire after T seconds") fails the same way from the other side. A
legitimately long-running, *actively committing* worker is not garbage, but a TTL
reaps it the instant the clock runs out — a false SCAVENGE, the exact false-positive
the liveness ladder's `grace_ms`/`spin_ms` policy and the lease-birth exclusion
(`journal_delta.py:257-270`) were built to avoid (the docs/82 false-clear fix). A
clock cannot tell a slow-but-advancing run from a hung one; only the *delta* can.
The archive-lock's 300 s TTL (`archive_lock.py:61`) is sound precisely because an
archive ceremony is bounded and uniform — a lease is neither, which is why leases are
reaped by liveness, not age. **TTL is reachability-by-stopwatch; it inherits every
weakness of believing the clock instead of the evidence.**

### 2.3 What DOS already is: a mark-and-copy collector missing a trigger

The good news the refcount detour surfaces: **`compact()` is already a copying
collector.** `replay` *marks* the live set (the reachable objects); `checkpoint_entry`
*copies* the survivors into a snapshot (the to-space); the old history is *abandoned*
(`lane_journal.py:555-603`). The differential-equivalence invariant
`replay(compact(E)) == replay(E)` is the copying collector's correctness property: the
mutator (the arbiter) cannot tell collection happened. DOS is not missing a collector.
It is missing three things a real collector has and this one doesn't:

1. a **trigger** (today `compact` only runs when an operator types it);
2. a **generational split** (beats and state ops share one space, so the collector
   must walk the whole history to drop the beats);
3. a **safe-point story** (compaction drops the `ts` beat anchor, so a live run reads
   STALLED until its next beat — `lane_journal.py:571-577` — which is *why* it can't
   run mid-flight today).

The rest of this note specifies those three, smallest-leverage-first.

### 2.4 "Make the WAL an index of per-run folders" is the same mistake wearing a directory tree

This one recurs whenever the live WAL crosses a few MB and a read feels slow: the
instinct is "split it into per-run folders and put an index in front." It is worth
interrogating, because it sounds like the obvious database move — and it is the wrong
move here, for the same reason refcount and TTL are. The single append-only WAL +
`compact` is the correct shape; the size pain is a **missing trigger** (§3.2), not a
wrong structure.

- **The single ordered log is load-bearing, not incidental.** The WAL's whole job is
  to impose a *total order* over lease events so `replay` can answer "who held lane X
  at instant T" and the arbiter can never double-book a region (docs/89). Splitting
  into per-run folders replaces "fold one ordered log" with "merge N independently-
  ordered logs and reconstruct a global order" — trading a solved problem (snapshot the
  live set) for an unsolved one (distributed-log merge with a consistent cross-segment
  clock). It shatters the invariant §2.3 just identified as the collector's correctness
  property.
- **An index doesn't help the symptom.** The 18 MB was ~34.7k ACQUIRE against ~1
  RELEASE (test fixtures polluting the real WAL + no auto-compaction firing), not the
  WAL outgrowing its shape. An index lets you *seek*, but the kernel never seeks —
  every consumer (`replay`, `journal_delta.fold_since`, the audit join) **folds** the
  whole relevant span. The fix for "too big" is to make the file smaller (`compact` on
  a trigger), not to index a file that should not be that big.
- **Index-of-folders is the §2.1 mistake re-spelled.** An index-of-runs is a
  locating/counting scheme; §2.1's finding is that a *reference* (the ACQUIRE line) is
  unsound as a liveness signal — a dead holder keeps its line. Reachability must be
  *adjudicated* by liveness, never counted or indexed. The collector stays
  mark-and-copy, not mark-and-index.
- **The one storage split that IS right is not folders — it's §3.1's generational
  split.** Segregate the *young generation* (HEARTBEAT beats, die by supersession,
  never in the arbiter's live set) from the *old* (ACQUIRE/RELEASE state ops). That
  splits by **event lifetime**, which preserves the total order within each generation;
  per-run foldering splits by **run identity**, which destroys it. §2.3 named exactly
  this as one of the three missing pieces, and §3.1 builds it.

The decision, in one line: keep one append-only WAL + `compact`; the answer to "it's
too big" is the unbuilt auto-trigger (§3.2) + the `[retention]` seam (§3.3) + the
generational beats split (§3.1) + test-WAL isolation — never an index of per-run
folders, which solves a query DOS never runs by breaking the order DOS depends on.

---

## 3. The design — generational tag, auto-trigger, retention seam

The collector stays exactly what it is (mark-the-live-set, copy-to-checkpoint,
operator-auditable). Three additions, each a property of *data* the kernel already
holds, none a new syscall.

### 3.1 Generational split — beats die young, by construction

The beat is short-lived garbage; treat it as a young generation that is collected
without touching the old. Two equivalent shapes, in build-cost order:

- **(a) Beat coalescing at the write boundary — SHIPPED (beat *elision*, not rewrite).**
  A lease needs exactly **one** *fresh* beat — `fold_since` keeps only `newest_beat_ms`,
  and the liveness ladder has no lower bound that distinguishes a 5 s-old beat from a
  290 s-old one (both are "alive ≤ `spin_ms`"). The first instinct — *rewrite* the WAL
  to replace the prior beat line — is rejected: it turns an O(1) atomic append into an
  O(J) rewrite-under-lock per beat (the opposite of a drain fix) and reintroduces the
  torn-rewrite hazard the append-only WAL exists to avoid. The shipped mechanism is
  strictly better and keeps the WAL append-only: **`lane_lease.heartbeat` takes a
  `coalesce_within_s` floor and *elides* the append entirely when the lease's current
  beat is younger than that floor** (it returns `True` — the lease is live and recently
  beaten — having written nothing). A beat that would not move the verdict simply is
  not written. This is verdict-preserving **by construction and only in the safe
  direction**: eliding can only let an existing beat *age*, never fabricate a fresher
  one, so it can never cause a false ADVANCING/SPINNING — the same one-way safety
  `compact` relies on. Default floor `0.0` elides nothing (byte-identical to the prior
  writer), so it is pure opt-in; a worker beating every 5 s under a 900 s `spin_ms`
  passing `coalesce_within_s=300` collapses the heartbeat contribution to J from
  `N × (runtime/5 s)` to `N × (runtime/300 s)` — a ~60× cut in this example, **measured
  at 12× (24 beats → 2 lines) in the test**, while the lease never reads older than the
  floor. The floor is the **caller's** concern, bounded by the policy it runs under,
  never a kernel constant silently coupled to `spin_ms`. Shipped in `lane_lease.heartbeat`
  + `dos lease-lane heartbeat --coalesce-within-s`, pinned by four tests incl. the
  verdict-preservation property (a coalesced and a full-beat journal classify identically).
- **(b) A young-generation segment.** Segregate beats into a sidecar `beats` region
  (or a `gen:young` tag) that compaction sweeps on a fast cadence while never
  rewriting the state-op log. Strictly more machinery than (a) for the same J
  reduction; deferred unless (a)'s last-write-wins-per-lease proves too coarse (e.g.
  if a future rung wants beat *history*, not just the newest).

Either way the principle is the generational hypothesis applied to DOS: **the WAL's
old generation is state transitions (ACQUIRE/RELEASE/SCAVENGE — rare, load-bearing,
keep); its young generation is beats (frequent, superseded-on-next-tick, collect
eagerly).** (a) alone removes the dominant unbounded term.

### 3.2 Auto-compaction trigger — on a threshold over the snapshot the kernel already computes

`compact` is pure and already correct; it only lacks a *when*. Add a size/age trigger
behind the existing `[journal]`-shaped seam, fired at a **safe point**, never per-append:

- **Threshold:** compact when `len(entries) > retention.max_entries` **or** the
  oldest non-checkpoint entry is older than `retention.max_age`. Both are read off the
  list `read_all` already materializes — no extra I/O to decide.
- **Safe point — this is the load-bearing constraint.** Compaction drops the beat
  anchor, so a naive mid-flight trigger would flicker live runs to STALLED. Fire it
  **only when the collector can prove it won't lie**: either (i) after rebeating —
  the trigger runs in the same `dos loop`/supervisor tick that just folded liveness,
  so it can compact *and* let the next beat re-anchor within one interval, or (ii)
  preserve the newest beat's `ts` **into the checkpoint payload** so `fold_since` can
  read a beat anchor out of the snapshot. (ii) is the better fix and is a small change
  to `checkpoint_entry` (carry `{lane: newest_beat_ms}`) + `fold_since`'s CHECKPOINT
  handling — it makes compaction *liveness-fold-preserving*, removing the "quiet
  window only" caveat that blocks auto-running today (`lane_journal.py:571-577`). With
  (ii), the differential-equivalence invariant strengthens from "arbiter-equivalent"
  to "arbiter-**and**-liveness-equivalent," and auto-compaction becomes unconditionally
  safe. **Build (ii); it is the unlock.**
- **Who fires it.** A **driver**, not a kernel module — the same line `94` and `101`
  draw. The natural home is the supervisor/watchdog tick (it already holds the journal
  write-lock and has just done the read), or a dedicated `drivers/gc.py` resolved by
  name like `dos watch` resolves the watchdog. The kernel ships `compact` (pure) and
  the threshold *predicate* (pure, `should_compact(entries, policy) -> bool`); the
  driver supplies the cadence and the write-back, exactly as `liveness.classify` is
  kernel and `dos watch` is the driver that puts it on a timer.

### 3.3 The retention seam — `[retention]` in `dos.toml`, closed-set-as-data

This is the direct answer to [`94 §7`](94_checkpoints-and-recovery-from-slop.md)'s
open question. Retention is **policy**, so it is declared per-workspace and carried on
the config seam as data, the `docs/HACKING.md` closed-enum→declared-data pattern that
already governs `[reasons]` and `[stamp]`:

```toml
[retention]
journal_max_entries = 5000     # compact the WAL past this many lines
journal_max_age_days = 30      # …or older than this (IDE checkpointers persist ~30d; 94 §7)
runs_keep_last = 200           # reap .dos/runs/ beyond the newest N run-dirs
verdicts_keep_last = 500       # reap .dos/.verdict-*.json beyond the newest N
projections_compact = true     # let `dos reindex` rewrite, not just append
```

It rides `SubstrateConfig` next to `.reasons`/`.stamp`, ships a **generic default**
(generous caps, never zero — the floor is "never reap a live lease," which the
collector enforces independently of these numbers), and is read by the driver, never
by a pure verdict. A host that wants infinite retention sets the caps high; a host on
a tiny disk sets them low; **the kernel's behavior is unchanged either way** — it only
ever computes *the live set* and *the threshold predicate*.

### 3.4 The scratch-pad reapers — composition, bounded, and they announce what they drop

The run-dir / verdict / projection garbage (§1.2) is collected by the **same driver**,
by the **same reachability rule**, never by age alone:

- **Run-dirs (`.dos/runs/`).** A run-dir is garbage when its run is **terminal** — its
  lease is RELEASE'd/SCAVENGE'd in the journal *and* it is older than the newest
  `runs_keep_last`. Reachability first (don't reap a run whose lease is still live,
  even if it's old), recency second (keep a forensic tail). This needs the
  `(loop_ts, lane) → run_id` join `94 §7` flags as the correlation gap; until that
  lands, fall back to keep-last-N by mtime, and **`log()` the cutoff** (see below).
- **Verdict sidecars.** Pure keep-last-N by mtime under `verdicts_keep_last` — a
  verdict is a point-in-time artifact with no liveness, so recency is the honest rule.
- **Central projections.** Extend `dos reindex` to *compact* (rewrite to the live
  digest), not only `--prune` stale projects: fold `decisions.jsonl` to its deduped
  identity set (`home.py:_decision_identity`) and rewrite. The projection is *already*
  declared rebuildable-not-authoritative (`home.py:20-22`), so compaction is sound by
  the same argument as `compact()`.

**No silent caps.** Every reap that bounds coverage (keep-last-N, the run-dir mtime
fallback) must `log()` what it dropped and why — the `docs/90`/workflow discipline that
a truncation read as "cleaned everything" when it didn't is itself a stale self-report.
A GC that quietly eats a run-dir an operator needed is the disease, not the cure.

---

## 4. Build order (smallest leverage-unlock first)

1. **§3.1(a) beat coalescing — ✅ SHIPPED.** Beat *elision* (not rewrite) per
   `(loop_ts, lane)` in `lane_lease.heartbeat`, via an opt-in `coalesce_within_s` floor
   + `dos lease-lane heartbeat --coalesce-within-s`. Removes the dominant unbounded term
   in J while the WAL stays append-only and O(1)-atomic. Pinned by four tests: the
   default writes every beat (byte-identical to before); a fresh redundant beat is
   elided (writes nothing, returns True); an unparseable stamp never elides (safe
   direction); and the verdict-preservation property — a coalesced journal and a
   full-beat journal classify identically (24 beats → 2 lines, both SPINNING).
2. **§3.2(ii) beat-anchor-preserving checkpoint** — carry newest-beat `ts` into the
   CHECKPOINT payload; teach `fold_since` to read it. Strengthens the compaction
   invariant to liveness-preserving and **unblocks auto-compaction**. Pins:
   `fold_since` over a freshly-compacted journal returns a live run's true beat age,
   not STALLED.
3. **§3.3 `[retention]` seam + `should_compact` predicate** — config data + one pure
   threshold function. Pins: a workspace with no `[retention]` gets the generic
   default; the predicate reads only the materialized list.
4. **§3.2 driver trigger** — fire `should_compact → compact → write-back` from the
   supervisor/watchdog tick (or `drivers/gc.py`). Pins: the journal self-bounds under
   a long-running `dos loop` with no operator action; the arbiter's live set is
   identical across the auto-compaction (differential equivalence holds live).
5. **§3.4 scratch reapers** — run-dir / verdict / projection collection behind the
   same seam, recency-floored, liveness-gated where the join exists, logging every
   drop. Pins: a reaper never removes a run-dir whose lease is live; every cap is
   announced.

Steps 1–2 are the value; 3–5 are the policy surface and the housekeeping. Each step is
independently shippable and independently green-able.

---

## 5. Non-goals (the lines GC must not cross)

- **No new syscall.** GC is `compact` + `liveness` + a trigger + a config seam. The
  collector is a driver; the reachability test is the syscall that already exists.
  Adding a `gc()` syscall would re-import machinery the kernel already ships (the
  over-abstraction trap `94 §6` names).
- **No reaping a live lease, ever.** The floor is reachability, not the retention
  numbers. A misconfigured `[retention]` may keep *too much* (waste disk) but must
  never collect a lease the liveness verdict calls reachable. False-keep is tolerable;
  false-collect is the lost-live-lease catastrophe `compact`'s fold-to-snapshot exists
  to foreclose (`lane_journal.py:563-565`).
- **No TTL on leases.** §2.2 — a clock cannot distinguish slow-advancing from hung.
  Leases are reaped by `liveness`/`SCAVENGE`, full stop. (The archive-lock TTL stays;
  a bounded uniform ceremony is the one place a clock is sound.)
- **No filesystem/conversation snapshots.** Same line as `94 §6.3`: git + the WAL are
  the substrate; GC reaps *DOS's own* scratch, not the host's working tree.
- **No auto-delete of forensic history the operator hasn't budgeted to lose.** The
  keep-last-N tail and the `log()`-every-drop rule exist so collection is auditable,
  not a silent shredder. Compaction *folds* (preserving the live set + corrupt
  sentinels); it does not *erase*.
- **No cross-host GC.** The WAL is host-local (`94 §6.5`, the DLO non-goal); collecting
  across machines is out of scope.

---

## 6. What this note claims, and what it does not

- **Does claim:** the DOS "GC problem" is real and measurable from the code today (an
  O(L × J) per-tick drain with J unbounded, plus three un-reaped scratch categories);
  reference counting and TTL are *unsound* for leases for a reason that is the kernel's
  own thesis (a dead holder still holds its reference / outlasts no clock — reachability
  must be **adjudicated**, not counted); DOS already contains a correct mark-and-copy
  collector (`replay`+`compact`) missing only a trigger, a generational split, and a
  safe-point; and those three are buildable as a generational beat-tag, an auto-trigger
  over a beat-anchor-preserving checkpoint, and a declared `[retention]` seam — all
  assembly over master, the retention question `94 §7` left open now answered.
- **Does not claim:** that GC needs a new syscall (it is a driver + a seam), that the
  retention defaults are calibrated (they are generous-and-provisional, floored on
  "never collect a live lease," with the bench as the eventual evidence source like the
  `94` REWORK thresholds), that beats should be collected by age (they are collected by
  supersession — last-write-wins per lease — which is exactly the fold's existing
  semantics), or that the kernel should ever delete a host's working tree (it reaps only
  its own `.dos/` scratch and its own WAL).

The meta-answer, in one line: **garbage in DOS is a stale self-report, so the collector
is the distrust primitive pointed at the kernel's own heap — reachability is a
`liveness` verdict, the collector is the `compact` the kernel already runs, and the
only thing missing is the trigger that fires it before the drain is felt.**
