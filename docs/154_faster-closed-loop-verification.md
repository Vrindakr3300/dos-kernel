# Faster closed-loop verification — loop latency as the next axis after "is the loop closed"

> **An open loop integrates error: every interval a disturbance goes un-sensed,
> its damage compounds against the remaining horizon. A *closed* loop rejects that
> disturbance — but only as fast as it can SENSE it. The correction bandwidth of a
> control loop is hard-bounded by its sensing latency: you cannot drive a
> disturbance to zero faster than you can sample its effect. So the axis docs/136
> named ("is there a feedback path from the un-forgeable effect back to the next
> decision?") has a second coordinate it never developed — *how fast does that path
> close?* — and that coordinate is the lever this note is about. "Faster
> closed-loop verification" is raising the loop GAIN by shortening the path from an
> un-forgeable effect to the next decision: in-flight instead of post-hoc,
> incremental instead of batch, push instead of pull, parallel instead of serial.
> And the load-bearing claim is an inversion: the kernel's purity discipline — the
> pure `classify()` with I/O at the boundary, adopted to make verdicts *testable* —
> is the same property, read as latency, that makes the loop *fast*. The constraint
> is the feature. The one caveat, stated up front because it is fatal if dropped:
> "faster" must mean a higher sampling rate on an UN-FORGEABLE effect, never a
> faster belief in the plant's self-report. A fast verdict on a forgeable predicate
> is the mirror-verifier (docs/141/143 §5a) and is *strictly worse* than a slow
> honest one.**

A synthesis note in the docs/136 tradition. It introduces no new primitive; it
argues that **loop latency** is the organizing dimension *after* "is the loop
closed," names the concrete latency mechanisms that already partly ship, and shows
each is checkable in-tree rather than a slogan. It expands
[`136`](136_the-closed-loop-as-the-organizing-principle.md) (the four loops) along
the time axis it left flat, and ties together
[`82`](82_liveness-oracle-plan.md) / [`145`](145_the-loop-economics-axis-and-the-stall-reader.md)
(the in-flight sensors), [`134`](134_the-integration-surface-binding-the-verdict-to-the-agent-runtime.md)
(the verdict bound to a runtime event — the fastest loop DOS already has),
[`101`](101_watchdog-driver-and-the-poll-cadence.md) (the bounded-latency poller done right),
[`148`](148_running-tests-and-sims-concurrently.md) (purity = parallelism), and the
`*_eval` / `replay_*.py` harnesses (the slow loop made fast & cheap). The
control-theory framing is the operator's own (memory:
`project-dos-closed-loop-control`); this note keeps it literal and applies the
*time constant* to it.

---

## 1. The definition, kept literal — verification latency *is* loop gain

Borrow the control-systems meaning exactly, because the loose reading ("faster =
nicer") loses the whole point.

A sampled feedback loop has a hard upper bound on its correction bandwidth: you
cannot reject a disturbance faster than you sample its effect (the Nyquist-style
limit). Map the parts onto DOS with no metaphor:

- **Plant:** the fleet acting on shared state — git, the lane WAL, the gym DB.
- **Disturbance:** a confabulated completion, a silent lane collision, a re-read
  loop, a dangling premature-stop.
- **Sensor:** a *pure verdict over an un-forgeable effect* — `liveness.classify`
  over commits-since-start + journal delta; `tool_stream.classify_stream` over
  env-authored `result_digest`s; `oracle.is_shipped` over git ancestry;
  `arbiter.arbitrate` over the live-lease set.
- **Comparator / controller:** `loop_decide.decide` / `scout.choose` /
  `intervention.choose_intervention`.
- **Actuator:** the **host** (PDP-not-PEP: the kernel emits the error signal and
  refuses-to-act, never acts — §5).

The loop's correction rate — its **gain** — is the fraction of disturbances driven
to zero before they propagate, and that fraction is upper-bounded by the
**sampling rate** of the sensor: the mean time between a disturbance landing and
the verdict firing. Lower that latency and you raise the achievable gain.

**Why faster raises gain — the integral of un-rejected error.** The quantity that
makes this literal is already measured in the tree, not borrowed: FleetHorizon's
harness defines defect **debt = count × remaining horizon** — the integral of
un-rejected error over the horizon. That is exactly the control-theory cost a slow
loop pays: a disturbance sampled *late* is integrated against the whole remaining
horizon before correction lands. Halving the mean-time-to-error-signal halves the
horizon over which an undetected lie compounds. This is why docs/136 §4's
monotonicity ("value monotone in horizon × fanout, → 0 at fleet = 1") is not just
a scale law — it is a *latency* law in disguise: more horizon = more interval over
which a slow sample integrates un-rejected error, and at horizon = 1 there is no
interval to integrate, so faster (like closed) buys nothing.

A caution the corpus earns the right to state: this is a **directional bound, not a
transfer function.** No DOS sensor has a measured sampling-period or
mean-time-to-error-signal in milliseconds; do not claim a Nyquist number. The claim
is qualitative — faster verification raises the *achievable* gain of the
sensing+comparator path the kernel owns — and it is bounded above by §2's soundness
constraint and below by §6's measured nulls.

---

## 2. The central caveat — faster ≠ faster self-certification

This is the load-bearing line, placed before the mechanisms so nothing below can be
read without it.

A faster loop is worthless — worse, *dangerous* — if the signal it samples is
authored by the plant it judges. A fast *wrong* verdict is strictly worse than a
slow *right* one, and DOS has the doctrine and the measured proof to say so. The
**mirror-verifier trap** (docs/143 §5a, docs/141 §2) is precisely
speed-without-soundness: a DB read-probe through the agent's own tool is fast, but
the predicate it answers ("is this the row the task required?") is *agent-authored*
from agent-visible prose. A feedback path authored by the plant being judged is
open-loop with extra steps **regardless of how fast it samples** — raising the
sample rate on a forgeable signal raises only the *apparent* gain while breaking
the trust boundary that makes the sample feedback at all.

The bound that governs how a sensor may be made faster is the **byte-inequality
axiom** (docs/141 §1): the bytes used to confirm a claim must not be the bytes the
judged agent emitted. So latency may be lowered *only* by sampling an un-forgeable
effect more often — never by substituting a cheaper, agent-visible signal to hit a
latency target. The §5a refinement is sharper still: even *env-authored bytes* are
insufficient if the *predicate* over them is agent-authored. `tool_stream` is the
worked example of fast **and** sound: it samples the in-process stream every step
(fast), but only asks "is this env-authored `result_digest` byte-identical to one
the env already returned N times?" — provenance-of-repeated-output, never a
satisfaction predicate (`tool_stream.py`, the "byte-clean" rationale). The gym MCP
server authored those bytes; the agent did not author the *identity* of its own
repeated results. That is why a higher sample rate on it is real gain, not a phantom.

Therefore the thesis is stated precisely: **faster reading of the un-forgeable
effect**, never faster believing the plant. Every proposed mechanism in §3 inherits
this as a hard invariant, and §6 names where a future implementer could let the
slogan rot.

---

## 3. The three latency levers — each grounded, each tagged shipped/proposed

Three independent ways to shorten the path from effect to decision. Each is already
*partly* built, which is what makes "faster" checkable and not aspirational.

### 3a. INCREMENTAL — verify the delta, not the world

DOS already computes its in-flight verdicts as pure **folds over a delta**, not
re-scans of the world. This is not a new mechanism to invent; it is an existing
idiom to *name and standardize as a standing reducer*.

- **[shipped]** `liveness.classify` folds a per-run delta: `journal_delta.fold_since`
  is scoped to one run's `(loop_ts, lane)` lease (not the world), and the git rung
  is `git_delta.count_commits_since(start_sha)` (a delta from a start SHA, not a
  full-history scan).
- **[shipped]** `tool_stream._trailing_run` walks *backward* from the latest step
  over the trailing identical-run only, stopping at the first break — morally
  O(run-length), the canonical incremental reduction.
- **[shipped]** `churn.decide_coalesce` maintains its verdict as `prev_state +
  this_event`: `recurrence = max(1, prior.coalesce_count) + 1` — a carried-forward
  run-length over git history.
- **[partial]** `lane_journal.replay` is *internally* an O(1)-per-op fold (a `live`
  dict + an `order` list; ACQUIRE adds, RELEASE forgets, HEARTBEAT updates one
  field, CHECKPOINT re-bases) **with the algebraic invariant `replay(compact(E)) ==
  replay(E)`** — but the public entry point re-folds the *whole* entries list on
  every call, and `dispatch_top.snapshot` calls `read_all` + `replay(entries)` on
  **every frame**. That is the latency wedge: the console re-reads and re-folds an
  append-only journal per pull.
- **[proposed]** Promote `replay`'s internal loop to a **standing reducer**: start
  from the last checkpoint/offset and apply only the newly-appended entry's O(1)
  transition, re-firing the verdict for the affected lease/run, so `dos top` updates
  *push-on-append* instead of *poll-on-pull*. This changes **where** the fold starts,
  not **what** it computes — and the already-shipped `replay(compact(E)) == replay(E)`
  invariant is exactly the property that makes the incremental restart sound.
- **[proposed]** A **streaming truth oracle**: maintain `oracle.is_shipped` as an
  online fold keyed to each newly-appended *commit* (check git ancestry *during* the
  run) instead of re-grepping whole ancestry after it. **Stays byte-clean** because
  `is_shipped` greps git ancestry — bytes the plant authored — and incrementalizing
  the *schedule* of an ancestry fold does not move the input toward the agent's pen.
- **[proposed]** An **incremental completion residual**: maintain `completion.classify`'s
  residual instead of re-deriving it via `resume_plan` over the *whole* `LedgerState`
  each call. **This is the sharp edge.** `resume.resume_plan` re-adjudicates
  `STEP_VERIFIED` against git ancestry at every read and treats the ledger record as
  an unauthenticated *hint*, never trusted. An incremental residual is safe **only**
  if the standing fold keys its re-fire to the appended un-forgeable *commit* and
  re-adjudicates ancestry on each one — never caching the re-adjudicated verdict and
  skipping the ancestry re-check. A memoized `STEP_VERIFIED` banked as cached truth
  would be the mirror-verifier disease at speed (docs/141 §8 caching rule). Hold the
  fold to the non-forgeable rung or do not build it.

Doctrine note: incrementalizing changes only the **schedule** of the fold, not its
**inputs** — every increment still consumes a plant-authored un-forgeable byte
(journal ts, env `result_digest`, git commit), so byte-inequality is preserved for
free, and the verdict stays advisory.

### 3b. PUSH not PULL — fire the verdict at the runtime event, not at the operator's next glance

The dominant trigger today is **pull**: an operator runs `dos verify` / `dos top` /
`dos decisions` and reads the verdict. `dos.decisions` is explicitly a read-only
projection with "no push/heartbeat" — a sampled loop whose interval is a human's
attention span, *unbounded*. Per docs/101 §2.1 the single most expensive failure in
the historical record was exactly a sampling failure: runs hung for hours because
the timer meant to stop them was asleep *inside the same stuck loop*.

The fastest closed loop DOS has is not a faster poll — it is the **elimination of
the poll**, and it already ships:

- **[shipped]** `dos hook stop` (`cli.py:cmd_hook_stop`, docs/134 §2.2). It is
  event-driven, not poll-driven: the host fires it structurally at the agent's
  Stop/SubagentStop boundary; it reads the hook event on stdin, runs
  `claim_extract` to lift the `(plan,phase)` the agent **claimed**, calls
  `oracle.is_shipped` against git, and on a confident `NOT_SHIPPED` returns
  `{"ok": false, "reason": …}` so the agent cannot stop on a lie. This is the
  textbook closed loop at **zero human latency and zero idle cost** — push-by-binding,
  not push-by-busy-poll (the distinction the "don't poll background tasks" memory
  rule enforces). The sensor is `oracle` over git ancestry (an un-authored effect,
  byte-author ≠ judged agent); the verdict gates the agent's *own* turn-end. The one
  verdict→control-flow line is marked host-side ("the HOST declines to stop; DOS only
  computed"), so the PDP/PEP line holds, and the asymmetry is fail-closed: the hook
  can refuse a *false* done, never *force* a stop — refuse-more-not-less re-expressed
  as a runtime asymmetry. Every failure mode degrades to exit-0/let-it-stop.
- **[shipped]** `dos guard` (`guard.build_guard_plan`, pure) — the headless-launch
  wrapper that injects `--settings` (carrying the Stop hook) + `--mcp-config`
  (mounting `dos-mcp`). The framing that wires the push binding into a launch.
- **[shipped]** the MCP tool call (`dos_verify` via `dos-mcp`) — push *initiated by
  the agent's own tool use* mid-run, zero Python coupling; the guard mounts it by
  default (it only *adds* a callable tool, the safe default vs the stop-changing hook).
- **[proposed]** Bind `dangling_intent.classify_stop` to the **same** Stop hook. It
  is *already* a pure Stop-boundary verdict — at turn-end, fold the against-interest
  verdict (the agent admitted "I still need X" then stopped, with no tool result
  after) alongside `oracle.is_shipped`, and re-surface the agent's own sentence as an
  advisory WARN. It composes with **no new trigger machinery**, and it is byte-clean:
  it checks an env-authored corroborator (`results_after_turn`) *first* and only fires
  on an admission *against interest* (forgeable-toward-false, never in-favor).
- **[proposed]** Bind `tool_stream.classify_stream` to **PostToolUse** (the host
  event docs/134 §1 confirms exists). Fold the `(tool, args_digest, result_digest)`
  triple at each tool result and fire a turn-preserving re-surface WARN the moment
  the same triple recurs N times — catching a looping agent *at the repeat*, not on a
  later pull.
- **[shipped, honest form]** the **watchdog cadence** (`drivers/watchdog.py`). Liveness
  has no single in-process event to bind to (git/journal advance asynchronously), so
  its push form is a *bounded-latency poller* living **outside** the supervised
  process — which is the actual fix for the docs/101 §2.1 timer-asleep-inside-the-loop
  failure. It classifies each tracked run via `liveness.classify` on a cadence and
  records OP_HALT + proposes a stop on SPINNING (propose-not-signal, pinned by
  `test_watchdog_proposes_does_not_signal`). This is bounded latency, not zero-idle
  event binding — and a hard upper bound on dead time versus the unbounded human pull.

### 3c. PARALLEL + OFFLINE REPLAY — make the SLOW loop fast & cheap

A controller has two loops with different time constants. The fast inner loop steers
a single run (§3a/§3b). The **slow outer loop** is the *adaptation* loop: it re-tunes
the controller itself — threshold calibration (what `repeat_n`/`stall_n` fires?),
gain-scheduling (how hard should the intervention ladder push?), and the
system-identification question "did landing this mechanism actually drop
failure-class-K?" In classical control, the adaptation loop's latency bounds how fast
the system can track a changing plant; if it takes a quarter to learn whether a fix
helped, you are trimming a plane once per season.

DOS's purity discipline collapses that loop's sample period from human-time to
CI-time, and it is **measured and shipped**:

- **[shipped]** `replay_stall.py` / `replay_recall.py` / `replay_dangling.py` fold a
  shipped pure verdict (`tool_stream.classify_stream` / `arg_provenance.classify_call`
  / `dangling_intent.classify_stop`) over a *frozen recorded corpus* of trajectories
  with "no new model calls, no DB mutation, no Docker — pure replay of recorded bytes
  (the L1-safe path, docs/148)." The boundary does the hashing; the kernel core
  compares pre-computed digests and never touches disk. Fast feedback (< 1 s/replay)
  on production data; gates CI for threshold calibration.
- **[shipped]** the pure simulator (`run_ab.py` over `simulator.run_split`) runs the
  **real** `classify_call` with no I/O/DB/model — embarrassingly parallel, zero shared
  state per seed (docs/148 Level 1). And `pytest -n auto` across the kernel suite is
  measured at **2129 passed in 26.15 s** (≈ 5× serial) precisely because pure
  `classify` functions isolate per worker (docs/148 Level 2) — *the isolation written
  for correctness doubles as parallel-safety.*
- **[shipped]** the five per-axis evals (`judge_eval`, `tool_stream_eval`,
  `overlap_eval`, `intervention_eval`, `precursor_gate_eval`) **recompute the verdict
  inside `score()`** rather than storing it, so the harness can never drift from its
  label — the same pure classify run as a backtest.
- **[shipped, as method]** replay-as-method has already *corrected a live conclusion*:
  docs/152's refutation phase scored the committed natural data and ran the replay,
  which rewrote the opening framing to the honest −8.3 pp wash *before the doc
  shipped* — the adaptation loop closing inside a single authoring session. And
  docs/149 used the same path to **measure** `p_stuck = 0` on 757 real runs instead of
  *assuming* `tool_stream` helps (measure-don't-assume operationalized).
- **[proposed]** A **standard**: *a verdict is not done until its replay harness can
  score it over a recorded corpus in seconds.* Partially realized (3 replay harnesses
  + 5 evals); worth generalizing so every new distrust verdict ships with an offline
  replay harness gating CI for calibration.
- **[proposed]** A **system-identification harness** for the IMPROVEMENT loop (the one
  docs/136/149 name but never build): fold the shipped verdict over a corpus split by
  *mechanism-landed SHA* and report the recurrence-rate delta for failure-class-K —
  "did this fix measurably drop the rate?" Labelled-unbuilt; would need measurement to
  validate.

The hard invariant for this lever (state it, do not footnote it): **speed here comes
only from pure-classify-with-I/O-at-the-boundary.** Never tempt I/O *into* `classify()`
to shave in-flight latency — that breaks the purity that makes replay free and risks a
faster verdict on a less-grounded read.

---

## 4. The inversion — the purity discipline IS what makes the loop fast

Foreground this, because it is the doc's best idea: the kernel constraint adopted to
make verdicts *testable* is the very property that makes the loop *fast*. Every
distrust verdict is a pure `classify(frozen_evidence, policy) -> verdict` with **zero
I/O inside** the core (`liveness.py`: "`classify()` makes no subprocess, file, or
clock call"; `tool_stream.py`: PURE, the caller hashes at the boundary). Now read each
testability property as a *latency* property — they are the same fact:

- **In-flight** — because the evidence is gathered at the boundary and the verdict is
  a pure function, it can run the instant the next evidence arrives, not after the run
  finishes. (Moving a check from `oracle`'s terminal post-hoc sample to `liveness`/
  `tool_stream`'s mid-run sample *is* raising the sampling rate.)
- **Incremental** — a pure classify over frozen evidence can be re-run over just the
  new delta; the marginal cost per sample is one function call, not a DB round-trip
  (§3a).
- **Replayable** — the verdict is identical on frozen data, so the *same* classify that
  runs in-flight runs offline as a backtest with no behavioral drift; this collapses
  the calibration loop from "ship a threshold, watch production, adjust next quarter"
  to "fold the pure verdict over the recorded corpus, sweep the threshold in seconds"
  (§3c).
- **Parallel** — purity means no shared state per sample, so the sample rate scales
  horizontally across the fleet for free (docs/148's `pytest -n auto` 5×, the
  embarrassingly-parallel simulators).

**The constraint is the feature.** The thing that made the kernel testable is the
thing that makes the loop fast — and crucially, none of these speedups touch a
verdict's *logic* or its *trust boundary*. Latency is reducible exactly as far as the
byte-inequality axiom permits and no further; that bound is what separates real loop
gain from the mirror-verifier's faster self-certification (§2).

---

## 5. The unifying table — the four docs/136 loops, read by their latency

| Loop (docs/136) | Current latency character | Faster-target | Status of the faster-target |
|---|---|---|---|
| **Control** (§3.1) | PULL liveness via `dos top`/`dos decisions`; in-flight sensor pure but human-sampled | bind to the runtime boundary — watchdog cadence (bounded) + `tool_stream`→PostToolUse + `dangling_intent`→Stop (event-driven) | watchdog **shipped** (propose-not-signal); the two in-flight bindings **proposed** |
| **Trust** (§3.2) | POST-HOC `oracle.is_shipped` (verifies retroactively after the run) | fire at the **stop hook** (already the fastest loop DOS has) + a streaming truth oracle (incremental git-ancestry fold *during* the run) | `dos hook stop` **shipped**; streaming oracle **proposed** (git-ancestry rung only) |
| **Improvement** (§3.3) | BATCH/offline; scout *biases* toward loop-closing work but no per-loop measurement | parallel replay in CI-time + the system-identification before/after-SHA harness | replay harnesses + evals **shipped**; the recurrence-delta instrument **proposed** |
| **Completion** (§3.4) | POST-HOC residual re-derived via `resume_plan` over the whole ledger each call | incremental fold keyed to each appended un-forgeable commit (re-adjudicate ancestry, never cache the verdict) | residual **shipped** (post-hoc); incremental fold **proposed**, gated on the non-forgeable-rung discipline |

The columns are about *time*, not about a new feature in any cell. Reading the loops
this way makes the doctrine fall out again: actuation stays host-side (faster makes
the **sensor** faster; the kernel still does not act — §5 below is the boundary, not a
gap to close), and the speedup never crosses the trust boundary because every
faster-target samples an un-forgeable effect more *often*, never a forgeable one at all.

---

## 6. The honest boundary — the falsifier and the floor

Two bounds, both non-negotiable, both already measured.

**Faster only rejects a disturbance that EXISTS.** Gain is the *product* of
disturbance-rate and rejection-fraction; a faster loop multiplies only the second
factor. On a capable model the loop-level disturbances DOS samples are near-null:
`p_stuck = 0` measured on 757 real gemini-3-flash runs (longest byte-identical run =
1; `replay_stall` fired on 0), `mints ~ 0%`, narrating-premature-stop **13% recall**
(docs/149–151). And the dominant real failure is **92% MISSING ROW** — the model stops
silent after ~5 calls vs ~9 required — which is **upstream PLANNING**, off-limits to
DOS by doctrine (no-planner; domain-free). docs/151's arithmetic is the honest bound:
`0.75 × ~0.12 × 0.25 ≈ 2.3%` of tasks recovered (≈ +0.5–1.5 pp, credible floor of
**zero**). So "faster" is **monotone in horizon × fanout and → 0 at N = 1**, exactly
like "closed" — load-bearing where FleetHorizon shows the value is real and compounding
(35 lies banked open-loop vs 0 closed; 7 silent overwrites vs 0; 100% → 17.1%
human-review; 0.387 → 0.520 verified-velocity/$, κ = 5 — and note these are *simulator*
numbers that prove the loop *emerges* and is monotone, **not** a deployment magnitude,
the docs/145 sim-proves-emergence-not-magnitude rule), and **honestly empty** on a
capable single agent. The in-flight push extensions deliver their zero-latency win on
the *cheap-looping-model* regime where the pathology fires (+3–4 pp ceiling, docs/145),
and ~0 incremental catch on the capable-model default. *Faster delivery of a verdict
that fires rarely is still architecturally correct; the operator must not read "faster"
as "more catches." Latency reduction catches the same disturbances **sooner**, never
**more**.*

**The mirror-verifier floor.** A faster verdict *never* licenses believing a forgeable
predicate. The two highest-risk proposed items both live on this line and must be
gated: (1) the **streaming truth oracle** is safe *only* on the git-ancestry rung —
faster git-read is fine; faster belief of a ledger `STEP_CLAIMED` is the mirror and is
fatal (`resume` re-adjudicating `STEP_VERIFIED` at every read is the correct precedent,
docs/107/141). (2) the **incremental completion residual** must re-adjudicate ancestry
on every appended commit and never cache the residual as state (docs/141 §8). Any
implementation that pulls I/O *into* `classify()` to hit a latency target has traded
the soundness that makes the sample feedback at all (§4). The discipline holds only
while sensing+comparator (kernel) stays separate from actuation (host).

---

## 7. What this reframing makes obvious (the next pickups)

Naming the latency axis changes what to build next:

1. **The incremental standing-verdict.** Promote `lane_journal.replay`'s internal
   O(1)-per-op fold to a standing reducer (start-from-last-offset, apply only the
   appended entry), so `dos top` updates push-on-append instead of poll-on-pull. The
   `replay(compact(E)) == replay(E)` invariant already guarantees soundness; this is an
   operator-console-latency/CPU win that touches no kernel input and stays advisory.
   Buildable today (§3a).
2. **The push-bound in-flight sensors.** Bind `tool_stream.classify_stream` to
   PostToolUse and `dangling_intent.classify_stop` to the existing Stop hook —
   both are *already* pure boundary verdicts, so they compose into the shipped
   `dos hook stop` / `dos_react` surfaces with no new trigger machinery, firing the
   verdict at the effect instead of at the next pull (§3b). (This is also the pending
   `dos_react` wiring docs/145 §6 names.)
3. **The replay-harness-per-verdict standard + the latency instrument.** Adopt "a
   verdict is not done until its replay harness can score it over a recorded corpus in
   seconds," and build the system-identification before/after-SHA recurrence-delta
   harness (§3c) — the IMPROVEMENT-loop instrument docs/136/149 name but never build.
   Then make *time-to-error-signal* itself an eval metric: measure the dead time
   between a disturbance landing and the verdict firing, per sensor, so "faster" stops
   being a directional bound and becomes a measured one.

The loop is the product; how fast it closes is the next thing to measure.

---

*Cross-refs:* [`136`](136_the-closed-loop-as-the-organizing-principle.md) (the four
loops — this note's parent), [`82`](82_liveness-oracle-plan.md) /
[`145`](145_the-loop-economics-axis-and-the-stall-reader.md) (in-flight sensors),
[`134`](134_the-integration-surface-binding-the-verdict-to-the-agent-runtime.md) (the
stop-hook — the fastest loop DOS has), [`101`](101_watchdog-driver-and-the-poll-cadence.md) (the
bounded-latency poller), [`148`](148_running-tests-and-sims-concurrently.md) (purity =
parallelism, the measured 5×), [`141`](141_byte-inequality-and-the-derivative-problem.md)
/ [`143`](143_enterpriseops-gym-dos-delta-audit.md) (§5a, the mirror-verifier floor that
bounds "faster"), [`149`](149_the-real-failure-distribution-sorts-the-priorities.md) /
[`151`](151_intervention-ladder-live-study.md) /
[`152`](152_the-first-natural-lift-experiment-dangling-intent-conversion.md) (the
measured nulls — the falsifier). The positioning angle (faster as the gen-2→gen-3
trajectory) is mechanism-grounded here but argued for adoption in **dos-strategy** →
the "faster closed loop" essay; nothing under `src/dos/` depends on it.
