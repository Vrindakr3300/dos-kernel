# docs/262 — the verdict journal: observability as a first-class kernel surface

> **Status:** Phase 1 (the recorder + reader + pure fold + `dos observe` projection)
> SHIPPED. Phases 2–4 (sensor auto-emit, `trace` join, retention/compaction) staged
> below.

## The gap (why this is the cheapest 10x in the kernel)

DOS already has a **correlation spine** (`run_id` + lineage), a **lease WAL**
(`lane_journal`), an **intent ledger** (claimed-vs-verified steps), and a
**read-only join verb** (`trace`) that walks all three. What it does *not* have is
a durable record of **the verdicts themselves**.

Walk the syscall ABI and count what persists. `verify()` answers SHIPPED /
NOT_SHIPPED — printed to stdout, gone. `liveness()` answers ADVANCING / SPINNING /
STALLED — printed, gone. `productivity()`, `efficiency()`, `breaker()`,
`hook_exit()`, `reward()`, every `pretool`/`posttool`/`stop` hook decision — each
is a PURE `classify(evidence, policy)` computed at the CLI boundary, rendered, and
**evaporated**. The *only* verdict that lands anywhere durable is `arbitrate()`,
and only because the lease WAL records the ACQUIRE/REFUSE it produces as a
side effect of needing the live-lease set across processes.

So the observability story today is: a firehose of adjudications, of which we keep
the one (leases) that the arbiter happened to need for its own state, and discard
the rest. Every existing read-only projection inherits that hole:

- `dos trace <run_id>` can show lease events + claimed-vs-verified steps + commits
  — because those three persist — but it **cannot** show "every liveness verdict
  this run emitted over its life," or "when did efficiency cross into WASTEFUL,"
  because those bytes were never written.
- `dos decisions` projects the four *refusal* sources; it cannot project the
  *advisory* verdicts (liveness/productivity/efficiency) because there is no store.
- `dos top` recomputes liveness live from the git/journal delta each tick — correct
  for "what's running NOW," but it has no history, so "was this run STALLED an hour
  ago and recovered?" is unanswerable.
- The `trajectory-audit` skill reaches *outside* the kernel to scrape Claude Code's
  own `.jsonl` session logs for pathologies — precisely because the kernel keeps no
  durable trace of its own verdict stream to audit instead.

**The 10x is not a dashboard. It is the missing substrate under every dashboard.**
Add one durable, append-only, run-id-correlated **verdict journal** and every
projection above gets richer for free, the `trajectory-audit` gets a kernel-native
data source, and "what did this fleet actually decide, across all surfaces, over
time" becomes a cheap fold instead of an impossibility.

## The design — `verdict_journal.py`, the lane journal's lateral sibling

The lane journal is a *proven* WAL: append-only JSONL, `fsync` under the decision
lock, torn-tail tolerance (a half-written final line is "didn't happen"), a
non-trailing corrupt line kept as a `_CORRUPT` sentinel so an audit still sees the
breach, and `replay()` as a pure fold (entries in, state out, no disk). The verdict
journal is **the same WAL discipline re-aimed from leases onto verdicts** — the
exact relationship `efficiency` has to `productivity`, or `resume` to `liveness`.

### The record — one `VerdictEvent` per adjudication

```
VerdictEvent
  schema_family = "verdict-journal"   # durable-schema tagged from line 1 (docs/207)
  schema_version
  ts            second-resolution UTC (journal_now_iso, the lane-journal stamp)
  seq           monotonic per-file tiebreak (the lane-journal seq idiom)
  syscall       "verify" | "liveness" | "productivity" | "efficiency"
                | "arbitrate" | "reward" | "breaker" | "hook_exit" | ...  (closed-ish)
  verdict       the typed token the syscall returned ("SHIPPED", "STALLED", "WASTEFUL"…)
  run_id        the correlation spine key (may be "" — see "honest unattributed")
  lane          optional region this verdict was about
  subject       optional free identifier (a (plan,phase), a command, a step id)
  detail        a small dict of the evidence counts that produced the verdict
                (tokens spent, work units, ages) — NEVER the agent's narration
  source        "kernel" (a syscall emitted it) | "sensor" (a hook did)
```

The honesty discipline is **inherited verbatim** from `trace`/`lane_journal`: the
`detail` carries the *environment-authored counts* the verdict was computed from
(the same byte-clean inputs `efficiency`/`liveness` already trust), never a
self-report. A verdict event records *what the kernel decided and the ground-truth
evidence it decided from* — it is structurally incapable of recording "the agent
says it's done," because the recorder is called with a verdict object the syscall
already minted, downstream of the classify.

### The API — record at the boundary, fold in pure code

Mirrors `lane_journal` one-for-one:

- `record(event, *, path=None)` — append one `VerdictEvent` as JSONL, `fsync`'d.
  The ONLY I/O. Fail-soft: a record that cannot be written is logged-and-dropped,
  never crashes the syscall that emitted it (observability must never take down the
  thing it observes — the `notify.send_safely` posture).
- `read_all(path=None)` — every event in append order; torn-tail-tolerant; a
  non-trailing corrupt line kept as a `_CORRUPT` sentinel (the lane-journal reader,
  verbatim).
- `tail(n, path=None)` — the last N.
- `rollup(events, *, by="syscall")` — the **pure fold**: entries in, a
  `VerdictRollup` out, no disk. Counts verdicts per (dimension, verdict-token), so
  "47 liveness verdicts: 40 ADVANCING, 5 SPINNING, 2 STALLED" is one call. The
  unit-test surface (mirrors `lane_journal.replay`, `decisions.collect_decisions`).
- `for_run(events, run_id)` — the per-run slice (the `trace` join key).

### Where it lives — pure kernel leaf, path on the config seam

`verdict_journal.py` is a **Layer-1 kernel module**: pure stdlib + `dos.config` +
`dos.durable_schema`, exactly like `lane_journal`. It names no host, makes no
adjudication of its own (it records verdicts other syscalls minted — it is a
*recorder and reader*, not a *judge*), and resolves its path against the active
workspace, never `__file__`.

The path is a new `PathLayout.verdict_journal` field, parallel to `lane_journal`:
`.dos/verdict-journal.jsonl` under the generic layout, `docs/_plans/
verdict-journal.jsonl` under the reference layout. Added as a defaulted
keyword-only field (the back-compatible widening rule already documented on
`PathLayout`), with a `DISPATCH_VERDICT_JOURNAL_PATH` env override.

### The projection — `dos observe`

A new read-only helper (Layer-3, the `decisions`/`trace`/`dispatch_top` posture):

```
dos observe                       # fleet-wide rollup over the whole journal
dos observe --run <run_id>        # one run's verdict history (joins to trace)
dos observe --syscall liveness    # filter to one dimension
dos observe --tail N              # the last N events, raw
dos observe --json                # machine-readable for the trajectory-audit
```

It reads the verdict journal only — takes no lease, mints no belief, adjudicates
nothing new. Delete it and you lose the reader, not the data (the `trace` contract).

## Why this is mechanism, not policy (it belongs in the kernel)

The thing being recorded — *which verdict a syscall returned, and the evidence* —
is mechanism: it is the kernel's own output, in the kernel's own closed
vocabulary. WHICH verdicts an operator cares to surface, how long to keep them, and
how to alert on them are policy — and they ride the existing seams (`dos observe`
filters; the `[retention]` caps already govern journal size; `notify` already pipes
a projection to a transport). The recorder records everything the kernel decides;
policy reads selectively. That is the same mechanism/policy split as
`lane_journal` (records every lease op) vs `decisions` (projects selectively) vs
`retention` (declares how much to keep).

The litmus tests hold by construction: it imports no host (pure stdlib + config +
durable_schema); `verify`/`liveness` still need no plan to *emit* a verdict event
(the recorder takes an already-minted verdict — it adds no precondition); the path
resolves against `SubstrateConfig.root`; nothing in the kernel imports a driver to
use it. A new durable-schema family (`verdict-journal`, version 1) tags every
record from line 1, so a future shape change migrates cleanly.

## Staging

- **Phase 1 — the substrate + the reader (THIS commit).** `verdict_journal.py`
  (record/read_all/tail/rollup/for_run + the `VerdictEvent`/`VerdictRollup` value
  objects), the `PathLayout.verdict_journal` field, the `dos observe` projection,
  and the test suite (`test_verdict_journal.py`). Nothing auto-emits yet — the
  substrate is proven in isolation first (the lane-journal was built the same way:
  the WAL before the writers).
- **Phase 2 — sensor auto-emit.** Wire the CLI verdict verbs
  (`verify`/`liveness`/`productivity`/`efficiency`/`breaker`/`reward`) and the hook
  sensors (`pretool`/`posttool`/`stop`) to `record()` a `VerdictEvent` as they emit
  — opt-in behind a `--observe` flag / `DISPATCH_OBSERVE=1` so a bare `dos verify`
  stays side-effect-free by default (a truth syscall must not silently start
  writing a log). The fleet's `/loop` sets the env once and every verdict lands.
- **Phase 3 — the `trace` join.** Add a `verdicts` column to `TraceFrame`: the
  per-run verdict history beside the lease events and claimed-vs-verified steps, so
  `dos trace <run_id>` shows the *full* adjudication record, not just the three
  surfaces that incidentally persisted.
- **Phase 4 — retention + compaction.** The verdict journal grows unbounded like
  the lane journal; fold the `[retention]` caps + a `dos observe compact` (or a
  shared journal-compaction verb) over it. Until then it is `read_all`-O(file),
  the documented lane-journal posture.

## The one-line thesis

DOS is the kernel that doesn't believe the agents — but until now it kept no
durable record of *its own disbelief*. The verdict journal is that record: every
adjudication, correlated and queryable, on the same WAL discipline the lease log
already proves. It makes observability a first-class kernel surface instead of a
firehose we watched go by.
