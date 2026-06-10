# docs/179 — the detector self-labeling harness (turning each run into a batch of calibration labels)

> **Status: Phase 0 + Phase 1 + the offline corpus harvester SHIPPED this session,
> with NET LIFT measured on a real third-party-scored corpus.** The Phase-0 firing
> record (`run_id`/`step_index`/`verdict_state` on the `posttool_sensor` stream
> record, additive — schema NOT bumped) and the pure `firing_label` fold are built,
> tested, exported (`dos.firing_label`, `dos.DetectorFiring`/`label_firings`/…). The
> `fleet_roll` honest aggregator (#3 below) is built (`dos.fleet_roll`). The
> **corpus harvester** (`benchmark/toolathlon/firing_corpus.py`) runs the kernel
> fold over the frozen 6,862-row Toolathlon corpus and (a) **reproduces the
> `additivity.py` SSOT confusion grid byte-for-byte** — proving the kernel
> instrument is correct — and (b) **shows net lift: +173 net-new oracle-failures the
> 3-detector union catches that the best single detector (tool_stream) misses,
> recall 2.87% → 6.18% (+3.31pp), at a bounded 1.59% union false-alarm** (§7). The
> CLI surfaces (`dos label-firings`, `dos roll`) remain Phase 3 (named, not built).

## 0. The seed and the reframe

The seed was two design ideas: (1) verify the claims of an entire **chain or tree**,
and (2) track **trajectory-level** data ("5/10 turns × dos something"). A follow-up
sharpened the goal into the load-bearing frame:

> *think of it as a way to get **more data** to make **more signal more useful**.*

That reframe is the whole point of this doc. A point-verdict (`oracle.is_shipped`)
mints **one git-authored label per phase**. The detector line — `tool_stream`
(docs/145), `terminal_error` (docs/158), `dangling_intent` (docs/150), the
precursor gate (docs/146) — is scored not by recall (recall is meaningless on a
76%-fail bench, docs/159) but by **lift + false-alarm rate**, and *those two numbers
are starved for labeled firings*: every detector audit in the repo (docs/158-163,
174, 177) hand-curates a tiny, static, expensive labeled set. The bottleneck on
"making the signal more useful" is **labeled data**, and the kernel already holds
the labels — it just never joins them to the firings.

## 1. The design law this doc establishes (read this first)

A workflow designed four "fold across a structure the kernel records" concepts —
the chain/tree verify, a per-turn ratio, this self-labeling harness, and a fleet
roll-up — and an adversarial pass refuted three of them on the **same** ground. The
refutation crystallizes into a law that governs every future "compose existing
verdicts into more data" proposal:

> **A fold mints new ground truth ONLY when it joins two independently-authored
> facts that were never compared before. A fold that re-projects one
> already-adjudicated set at a different grain mints ZERO new labels — counting
> those derived rows as data is the consistency-not-grounding sin (docs/138; the
> "re-counting one git fact as N labels" failure).**

By that law:

- **Tree-verify** folds `oracle.batch_is_shipped` over N phases keyed by a run's
  lineage. But `batch_is_shipped` *already* mints those N labels in one call — the
  tree aggregate adds a convenience verdict, **0 new labels**.
- **Per-turn ratio** is 20 cumulative prefix re-counts of one final `verified` set —
  correlated rows that inflate *n* without information and bias calibration
  *downward*. **~0 new labels** (and the load-bearing `turn_index` input does not
  even exist in the ledger). `completion.convergence(residual_history)` already folds
  the closure trend, with a *fixed declared* denominator that — unlike a forgeable
  `claimed_cum` — cannot be gamed by spamming `STEP_CLAIMED`. **Dropped.** (The one
  honest salvage is a kernel-authored `ts_ms` on `STEP_VERIFIED` → verification
  *latency* per step, an orthogonal scalar — a separate, optional future build.)
- **Fleet roll-up** folds N already-computed `StatusDigest`s into one call —
  **0 new labels**, an honest *aggregator* (built below as #3, with that framing).
- **Detector self-labeling** joins a detector **firing** (env/agent-authored) to the
  run's **git-minted outcome** (a fact the judged agent did not author) — two
  independently-authored facts never compared before. **This is the one that mints
  new data.** It is the build.

### 1.1 The lineage corollary

The same trap has a structural half. `RunId.parent_id`/`root_id` is the run that
**spawned** this one — a *process-spawn* edge, not a *depends-on* edge. A parent
commonly depends on the child it spawned (the reverse of what a dependency check
assumes). So:

> **Spawn-lineage is display-ordering, never a dependency verdict. Never let a
> parent→child spawn edge gate a refusal (a `BROKEN_LINK`) or deprioritize a lane.
> A real dependency fold needs a non-agent-authored depends-on edge, which does not
> exist in the spine today.**

This is why tree-verify's headline `BROKEN_LINK` and fleet-roll's
arbiter-deprioritization were cut: both leaned on spawn-lineage as if it were a
dependency.

## 2. The harness — `dos.firing_label`

### 2.1 The join

A `DetectorFiring` is *"detector D fired signal S at step N of run R."* Its label is
the run's **git-minted** outcome read off `trace.TraceFrame` — the verified-step
count, the residual, the commits since `start_sha`. The agent's `claimed_sha`
column is shown by `trace` but is **never read here** (the docs/138 byte-author
invariant: a `CLAIMED`-but-unverified step is the agent saying it made progress;
git says it did not — so it is still residual, never counts as a false-alarm).

The fold emits one `LabeledPoint` with a **closed** outcome vocabulary — a label,
never an optimism:

| `LabelOutcome` | Fires when | Provenance |
|---|---|---|
| `TRUE_POSITIVE` | detector fired AND the run verified 0 declared steps AND landed 0 commits (residual remains) | the no-progress the detector accused is confirmed by git |
| `FALSE_ALARM` | detector fired BUT the run verified ≥1 step OR landed ≥1 commit | the loop was not terminally stuck — git shows it advanced |
| `UNVERIFIABLE` | firing joined a run with NO git-minted ground truth (no intent, no commits) | refuse-don't-guess: nothing to judge against, decline to call it |
| `BROKEN_LINK` | the firing carries no `run_id`, or the run left no surface | cannot join — counted, never time-guessed onto a run (docs/118/137) |

`UNVERIFIABLE`/`BROKEN_LINK` are first-class refusals — the §5a optimism trap,
inverted: we will not call an unjudgeable firing a catch.

### 2.2 Why the multiplier is honest (1–3×, not 5–15×)

A single REPEATING→STALLED run on the **same** stuck step is **one** firing, not
many. Two guards enforce this:

1. **At the sensor (Phase 0):** `verdict_state` is stamped on a stream record only
   when the detector fired, and the run of identical steps shares one
   `(tool, args, result)` identity.
2. **In the fold:** `dedupe_firings` collapses firings that share
   `(run_id, detector, signal, repeat-identity)` to one.

So the real audited `8bd8c736` read-loop (22 byte-identical reads → STALLED) mints
**EXACTLY ONE** `LabeledPoint`, not 22 — pinned by
`tests/test_firing_label.py::test_audited_read_loop_mints_exactly_one_point`. That
single assertion proves three things at once: the join works end-to-end, the dedup
keeps the multiplier honest, and the byte-author invariant holds. Re-counting one
env stall as 22 labels would be the consistency-not-grounding sin in miniature.

The honest yield is **~1 label per distinct detector-fired step that has a verified
side — typically 1–3 per run**. The ground-truth rule is deliberately run-terminal,
and its selection bias (a still-in-flight run reads as `UNVERIFIABLE` until it
declares/verifies/commits) is **reported** via `LabelSummary.coverage`, not buried
(the docs/159 "no silent caps" discipline). Still a real, free gain over the
1-label/phase baseline, every point with clean provenance.

### 2.3 The shape (Layer-1 pure leaf)

```
DetectorFiring{run_id, detector, signal, step_index, identity}      # the INPUT (what the detector said)
LabeledPoint{firing, outcome: LabelOutcome, reason, ground_truth}   # the OUTPUT (the git-minted label)
LabelSummary{points}  -> true_positives / false_alarms / unverifiable / broken_links
                         / judgeable / false_alarm_rate / coverage   # the confusion grid

label_one(firing, trace: TraceFrame|None) -> LabeledPoint            # the per-firing ladder
label_firings(firings, frame_for, *, dedupe=True) -> tuple[LabeledPoint]   # the batch fold
dedupe_firings(firings) -> tuple[DetectorFiring]                     # the honest-multiplier guard
```

`label_firings` takes a `frame_for: run_id -> TraceFrame|None` callable — the I/O
(`trace.build_trace`) stays at the caller boundary, exactly as `liveness.classify`
takes a pre-read `ProgressEvidence`. The fold is state-in / frozen-verdict-out, zero
I/O. `false_alarm_rate` is over the **judgeable** points only (TP+FP) and is `None`
on a 0/0 denominator (refuse the number, don't print 0.0).

## 3. Phase 0 — the gating boundary stamp (the firing must EXIST as a fact)

The fold's evidence source — the shipped `posttool_sensor` — recorded neither a
`run_id` nor the fact that a detector *fired*: `_step_entry` carried only
`{schema, op, tool_name, args_digest, result_digest}`. So Phase 0 (the gate the
review flagged) makes a firing a **durable fact**:

- `posttool_sensor._step_entry` / `append_step` gained three **additive optional**
  fields — `run_id`, `step_index`, `verdict_state` — written ONLY when known. A
  record without them is byte-for-byte the old v1 record, so `TOOL_STREAM_SCHEMA`
  stays `1` (the `durable_schema` additive contract: a new optional field is
  forward/backward compatible and does not bump the version). The whole shipped
  `tool_stream` suite stays green.
- `cmd_hook_posttool` now reads the prior stream, classifies the would-be stream
  (prior + this step) to learn THIS step's verdict, then appends **once** —
  stamping `verdict_state` (and `run_id` from `CID_RUN_ID` when in a spine, and
  `step_index`) only when it fired. Classifying over (prior + step) is identical to
  classifying the re-read stream, so the verdict the agent sees is unchanged; this
  only makes the firing durable, not re-derived. The advisory fail-safe (any I/O
  error → emit nothing, exit 0) is preserved on both the read and the write.

The presence of `verdict_state` IS the firing — ADVANCING never stamps it.

## 4. The fleet roll-up — `dos.fleet_roll` (#3, the honest aggregator)

The cross-run fold docs/120 Phase 2-4 named but never built: fold a whole `root_id`
tree of `StatusDigest`s into one fleet headline + a per-branch breakdown
("9 COMPLETE, 2 SPINNING, 1 DIVERGED; the failing branch is X under Y"). Built with
its honesty stated up front: **it mints 0 new labels** — every digest it folds was
already computable by `dos status <run_id>`; it batches them into one operator call.

Two design constraints the review pinned, both obeyed:

1. **Two disjoint enums collapse to one `FleetState` first.** A digest carries a
   `liveness` (ADVANCING/SPINNING/STALLED) AND a `resume` (RESUMABLE/COMPLETE/
   DIVERGED/UNRESUMABLE, None while live). `verdict_rollup` ranks one vocabulary, so
   `fleet_state_of` collapses each digest to a single string FIRST — a stopped run
   governed by its terminal `resume` verdict, a live run by its `liveness`. The
   worst-first order makes a single DIVERGED branch dominate a sea of COMPLETE
   (`UNKNOWN` is severe, never "clean"). `verdict_rollup` then contributes only the
   `min` + counts; it interprets no semantics.
2. **The per-branch grouping is spawn-lineage DISPLAY only** (§1.1) — it attributes
   "which subtree is failing," never condemns a parent or gates a lane.

The I/O is the caller's (the corrected cost model): gathering N digests is N+1
`build_trace`-class reads + N liveness/resume evidence gathers at the CLI boundary
(`trace.build_trace(root).descendants` returns run_id **strings**, not digests).
`fleet_roll` itself is pure.

## 5. What is NOT built (Phase 3+, named not silent)

- **`dos label-firings`** — the CLI that harvests firing records from a session's
  `.dos/streams/*.jsonl` + `dos trace` frames and prints the `LabelSummary` / writes
  a labeled-point JSONL. The pure fold is done; this is the boundary that gathers.
- **`dos roll <root_id>`** — the CLI that gathers a tree's digests and prints the
  `FleetRoll`. The pure fold is done; this is the N-fold boundary gather.
- **Other detectors' firing records** — `terminal_error`/`dangling`/`precursor`
  need the same Phase-0 stamp (their own durable `DetectorFiring`) to feed the same
  live fold. `tool_stream` is the live proof; the corpus harvester (§7) already folds
  ALL THREE offline. The pattern generalizes.
- **The `ts_ms` latency salvage** from the dropped per-turn concept — a
  kernel-authored timestamp on `STEP_VERIFIED` → verification latency per step
  (the over-claim precursor), if/when the detector line wants a timing signal.

## 6. The throughline

The kernel mints point-verdicts. This doc's harness turns each run into a **batch of
labeled points** by joining a firing to its git-minted outcome — the one fold that
mints new ground truth, governed by the law in §1. The fleet roll-up and the
(cut) tree-verify / per-turn ratio are honest aggregators or re-counts; naming which
is which is the contribution as much as the code. More labels → a better-calibrated
detector line → the signal made more useful, which was the ask.

## 7. The measured result — NET LIFT on the real corpus

`benchmark/toolathlon/firing_corpus.py` runs the kernel `firing_label` fold over the
frozen Toolathlon corpus (`_results/replay_all_rows.csv`, 6,862 labeled rows, 22
models × 3 runs — the same durable join `additivity.py` reads), zero network/LLM:

```
python -m benchmark.toolathlon.firing_corpus --check
```

### 7.1 The join is real, not circular

On a live run the label is git; on this offline replay there is no git, so the
ground-truth stand-in is the third-party `passed` column — **the Toolathlon task
evaluator's verdict, authored by the benchmark harness, not by the detector and not
by the agent.** The detector firing (env bytes) and the oracle label (task checker)
are computed from disjoint inputs — two independently-authored facts, the §1 law's
condition. The fiction would be synthesizing the oracle FROM the firing; we do the
opposite (both columns pre-exist). `test_oracle_label_is_independent_of_the_firing`
pins it: the SAME firing labels TRUE_POSITIVE against a FAIL frame and FALSE_ALARM
against a PASS frame — the label comes from the oracle, never the detector.

### 7.2 The kernel instrument is correct (cross-validation)

The kernel fold's per-detector confusion grid reproduces the validated SSOT
(`additivity.py`) **byte-for-byte** — `cross_validate` asserts it and is pinned by
`test_kernel_fold_reproduces_additivity_ssot_exactly`:

| detector | kernel TP / FP | precision |
|---|---|---|
| dangling | 100 / 2 | 98.0% |
| tool_stream | 150 / 20 | 88.2% |
| terminal_error | 76 / 4 | 95.0% |

So the net-lift number below is the SSOT metric computed through the kernel, not a
parallel possibly-buggy path.

### 7.3 NET LIFT — the "more signal" number

| | TP (deduped by run) | recall | false-alarm |
|---|---|---|---|
| best single detector (tool_stream) | 150 | 2.87% | — |
| **union of 3 (the kernel fold)** | **323** | **6.18%** | 1.59% |

> **+173 net-new oracle-failures the union catches that the best single detector
> misses — recall 2.87% → 6.18% (+3.31pp), at a bounded 1.59% union false-alarm.**

That is the docs/179 thesis, measured: pooling the detector labels (the "more data"
the self-labeling fold mints) yields strictly more caught failures (the "more
signal"), on real third-party-scored labels, at a small false-alarm cost. The build
"works and shows net lift." Pinned by `test_net_lift_is_positive_on_real_labels`.

The kernel mints point-verdicts. This doc's harness turns each run into a **batch of
labeled points** by joining a firing to its git-minted outcome — the one fold that
mints new ground truth, governed by the law in §1. The fleet roll-up and the
(cut) tree-verify / per-turn ratio are honest aggregators or re-counts; naming which
is which is the contribution as much as the code. More labels → a better-calibrated
detector line → the signal made more useful, which was the ask.
