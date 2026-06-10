# Runtime validation, the self-stop seam, and where the kernel may act

> **DOS adjudicates two of the three moments of a run today — *before* work
> starts (`arbitrate`: is the lane free?) and *after* a claim is made (`verify`:
> did it ship?). The expensive failures live in the third: the *interval while
> the agent is running*. `liveness()` already mints the in-flight verdict
> (ADVANCING / SPINNING / STALLED); nothing consumes it. This note closes that
> loop — and answers the question the closing forces: *may the kernel ever act on
> its own verdict, or only report it?* The answer reframes the advisory-only law
> from a flat prohibition into a precise one: the kernel must not act because
> **acting requires knowing what a "process" is**, and that knowledge is a
> driver's, not a domain-free kernel's. Self-stopping a loop's own control flow is
> in-bounds; signalling a foreign process is not.**

A theory + spec note in the family of [`79`](79_primitives-not-features.md),
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md),
[`94`](94_checkpoints-and-recovery-from-slop.md). It is grounded in historical
failure data (the reference userland app's apply/dispatch postmortems), it draws
the actuation boundary that [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) and
[`94`](94_checkpoints-and-recovery-from-slop.md) assert but under-argue, and it
specifies two builds: a **pure** loop self-stop seam (the
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) Phase-3a wiring) and one
**effectful** `reap`-family boundary verb (`halt`). §1–§3 are the argument;
§4–§6 are the buildable spec.

---

## 1. The three moments of a run — and which one the kernel still misses

Every syscall DOS ships adjudicates a *moment* in a run's life:

| Moment | Question | Syscall | Evidence |
|---|---|---|---|
| **Before** work starts | Is this lane free to take? | `arbitrate()` | the live-lease set |
| **During** — the interval | Is the run *moving*, or spinning? | `liveness()` | git delta + journal fold |
| **After** a claim | Did `(plan, phase)` actually ship? | `verify()` | the registry + git ancestry |

`refuse()` cross-cuts all three (a structured "no" at any moment), and
`spawn/reap` bracket the run (mint identity, end it). But the *load-bearing*
adjudication is the before/after pair — and that is exactly where the kernel was
strong first, because both moments produce a discrete artifact to check (a
contended lane; a commit). The **interval** is harder: it has no single artifact,
only a *trend*, and an agent narrating that trend ("almost there, refining the
approach") is least trustworthy precisely there. `liveness()` was built to close
it ([`82`](182_the-kernel-is-a-taxonomy-of-refusal.md)) — Phases 1–2 ship the
verdict — but the verdict is a *sensor with no wire to an actuator*. A spinning
run is detected and nothing happens.

That gap is not academic. It is the single most expensive failure class in the
historical record.

## 2. What the historical data says the runtime pain actually is

Mined from the reference userland app's `_apply_postmortems/` + `_dispatch_loops/`
+ `apply-lessons-learned.md` (the fleet that DOS was lifted out of), ranked by
frequency and cost — the runtime failures, the ones a before/after referee could
not catch:

1. **Hung run / budget didn't fire (the most expensive single incident).** Eight
   jobs hung ~4.4 h *each* — ~35 agent-hours — because the wall-clock budget
   (2000 s) fired **2.2 h late**: the orchestrator loop stalled inside a long
   poll, so the timer that should have killed the run never got a turn. This is a
   *supervisor* failure, not an agent failure: the layer meant to stop the stuck
   thing was itself asleep. *Detectable from ground truth:* 0 commits + a stale
   heartbeat over hours is `STALLED`, the orphan-sweep's input.
2. **Loop exhaustion without progress (the most *recurring*).** Six-plus
   postmortems: an agent burning its retry/turn ceiling while re-editing the same
   fields, re-running the same failing step, landing nothing. *This is the
   textbook `SPINNING` shape* — alive, narrating motion, zero forward delta — and
   it is the rung the self-report breakers in `loop_decide` (`consecutive_unclear`
   et al.) **cannot reach**, because they read the caller's `IterationOutcome`
   token, not git.
3. **Mid-step self-deception (the gap with no home at all).** An agent logs
   `still_broken=[]` for form fields the page still renders empty — it *claims* a
   sub-step succeeded without re-reading ground truth. This is below commit
   granularity: `verify()` fires too late (at the commit), `liveness()` too coarse
   (it sees minutes, not keystrokes). Noted here as the open frontier (§6); it is
   not what this note builds, but it is where "runtime validation" ultimately
   points.
4. **Mid-run collision.** Two workers `git add -A`'d each other's in-flight edits;
   one's plan-row write clobbered the other's (the repo failed *silent* — a bad
   partition is a clobbered file you don't see). `arbitrate()` is built for exactly
   this, but it adjudicates *at admission* and never re-checks while both hold —
   prevention degraded to after-the-fact detection.

The shape is unmistakable: **the expensive runtime failures are
"alive-but-not-moving" (1, 2) plus one sub-commit blind spot (3).** DOS already
*detects* (1) and (2) — `STALLED` and `SPINNING` are exactly those verdicts. The
deficiency is purely that **the loop does not consult its own liveness and stop.**
Closing that is most of the value, and it is mostly assembly.

## 3. The actuation boundary — the real reason the kernel doesn't kill

Closing the loop forces the question the advisory-only law has always asserted but
never fully argued: *if the kernel can see the run is stuck, why may it not stop
it?* [`82 §6`](182_the-kernel-is-a-taxonomy-of-refusal.md) ("Killing a run … LVN
never terminates a process") and [`94 §6.1`](94_checkpoints-and-recovery-from-slop.md)
("the kernel never restores, reverts, resets") state the prohibition flat. A flat
prohibition invites the reasonable objection: *handing a SPINNING verdict back to
the very agent that can't see its own loop, and trusting it to stop, is trusting
the broken component.* So the law deserves a real argument, not an assertion.

There are three candidate justifications. Two are weaker than they look; the third
is the load-bearing one.

- **Purity / replay-testability** ("`classify()` does no I/O, killing is I/O").
  Real, but it is an argument about *where the effect lives* (the boundary, not the
  pure verdict), **not** about whether an effect may exist. Every syscall already
  has a pure core and an I/O boundary (the CLI). An effect could live at the
  boundary without touching the pure core. This justification scopes the design; it
  does not forbid it.
- **The semantic-rollback hazard** ([`94 §6.4`](94_checkpoints-and-recovery-from-slop.md):
  re-execution after an auto-restore causes duplicate side-effects). This argues
  against **auto-revert**, and decisively — but **halt ≠ rollback.** Stopping a
  process is idempotent and side-effect-free in a way that mutating state back is
  not: a second SIGTERM to a dead pid does nothing; a second `git revert` does not.
  So this objection, which is fatal for auto-restore, is weak for auto-halt.
- **Domain-freedom — the load-bearing one.** To *stop a run* the actor must know
  **what the run is**: a local pid? a pid in a container? a remote agent behind an
  API? a harness `Workflow` task id? Killing each is a different, platform- and
  host-specific act (`SIGTERM` vs `docker kill` vs an HTTP cancel vs `TaskStop`).
  That knowledge is precisely what a **domain-free kernel must not carry** — it is
  a driver's. The kernel that learns "a run is a pid on this host" has stopped
  being a substrate and become one host's harness. *This* is why the kernel doesn't
  kill: not because acting is forbidden in principle, but because **the knowledge
  required to act safely is domain knowledge the kernel is defined not to have.**

The reframe is productive, because it sorts the design instead of blocking it.
Three layers, three different answers to "may it act?":

| Layer | May it act? | Why |
|---|---|---|
| **The pure verdict** (`liveness.classify`, `loop_decide.decide`) | No — it returns a typed *decision* | Purity. `decide()` returning `action="stop"` *names* a decision; it does not perform one. (The shape already shipped.) |
| **The kernel boundary** (the CLI, a `reap`-family verb) | It may **record** the decision on the WAL and **propose** the command — never deliver the signal | Recording that a decision was made is epistemic-adjacent (identical to logging an `OP_REFUSE`). Proposing a command is emit-and-exit ([`94 §3.3`](94_checkpoints-and-recovery-from-slop.md)). Delivering the signal needs the domain knowledge it lacks. |
| **The driver / host harness** (`drivers/supervisor.py`, the run's launcher) | **Yes** — it performs the kill | It knows what the handle *is*. This is where `Popen`/`SIGTERM`/`TaskStop` already live. |

Two consequences fall straight out, and both are already half-built in the tree:

**(a) A loop stopping its *own* control flow on SPINNING is NOT a line-crossing.**
A loop that declines to launch its next iteration is exercising control flow, not
killing a foreign process — it needs no knowledge of "what a process is," because
the only thing it stops is *itself deciding to continue*. This is byte-for-byte
the move `loop_decide` **already makes** with `UNMEASURED_SHIPPED`: the kernel
distrusts a SHIPPED self-report and stops the loop on ground-truth evidence
(`loop_decide.py`, the FQ-420 stall). Self-stop on SPINNING is the same move one
rung lower. **This is Piece 1 (§4), and it is in-bounds.**

**(b) The one effect the kernel already sanctions has a name: `spawn`/`reap`.**
And the precedent is *live on master*, not theoretical: `supervise()` + its driver
`drivers/supervisor.py` already implement "kernel proposes REAP → the driver
performs it by journaling a `SCAVENGE` under the lock; the kernel never `Popen`s."
A `halt` verb is `reap`'s sibling — *stop a run that is **not** done* — and
`lane_lease.release()` is its line-for-line template. **This is Piece 2 (§5).**

### 3.1 FLAG-a-neighbor vs stop-yourself — keep the two spins apart

`supervise()` already meets SPINNING and deliberately does **nothing**: its
disposition for a spinning worker is `FLAG` — "advisory only … it never auto-reaps
it … the kernel ships the signal, a driver/operator decides the act" (`supervise.py`).
That is **not** in tension with Piece 1, because the two are different subjects:

- `supervise()` FLAGs a **neighbor's** spin — a *population*-level observation
  about some *other* worker's lane. The supervisor has no standing to halt a peer's
  control flow, and (per §3) no domain knowledge to kill its process. So it reports
  and stops. Correct.
- Piece 1 is a loop reacting to its **own** spin — *self*-control-flow. A loop
  always has standing to stop itself, and needs no process knowledge to do so. So
  it may act on the verdict. Also correct.

The line is *whose control flow*. Stop-yourself is in-bounds; stop-a-neighbor is a
`FLAG` plus, at most, a *proposed* `halt` the driver/operator may enact. The `halt`
verb (§5) is the surface [`82` LVN-3a](182_the-kernel-is-a-taxonomy-of-refusal.md)
and [`90 §5`](90_open-research-areas.md) flagged as the open "acting on a spin"
question — built as a *proposal*, never an autonomous kill.

## 4. Piece 1 — the self-stop seam (`StopReason.SPINNING`, pure)

Extend `loop_decide` so a caller may pass the in-flight `Liveness` verdict it
already gathered (via `dos liveness`) into the loop state; `decide()` stops the
loop when that verdict is `SPINNING`. This is the
[`82` Phase-3a](182_the-kernel-is-a-taxonomy-of-refusal.md) wiring, and it mirrors
the `UNMEASURED_SHIPPED` precedent exactly.

- **A new `StopReason.SPINNING`.** The named terminal condition, joining the enum
  that *is* the answer to "under what exact conditions does this loop stop?"
- **An optional `LoopState.liveness: Liveness | None`** (default `None`). It lives
  on `LoopState`, not `IterationOutcome`, because liveness is a property of *the
  run across the interval* (the caller's evidence-gather), the same carried-context
  status as `gate_mode` — not a property of one iteration's exit token. `loop_decide`
  importing `Liveness` is a **sibling** kernel import, explicitly blessed
  (`CLAUDE.md`: "`liveness` is `loop_decide`'s sibling"); the litmus is "no host, no
  I/O", not "no sibling import". `loop_decide` stays pure — it *reads* a verdict
  value, never computes one.
- **Opt-in, byte-identical.** A caller that passes no verdict (`liveness=None`)
  gets today's behavior *byte-for-byte* — the same conservative-default discipline
  that `measurement_expected=False` and `replan_productivity or PRODUCTIVE` already
  encode in the file. This is pinned by a behavior-preservation test parametrized
  over **every** `OutcomeKind`.
- **Decision-order placement (load-bearing).** The new order is:
  `LAUNCH_FAILED → RATE_LIMITED → OVERLOADED → [SPINNING] → UNCLEAR → SHIPPED/REPLAN/GATE → cap-last`.
  The SPINNING check goes **after** the upstream/transient breakers and **before**
  the outcome block, inserted right after the line that resets the OVERLOADED
  streak on a clean iteration:
  - *After RATE_LIMITED / OVERLOADED*: a run idle only because the API is 529-ing
    is correctly backing off, not spinning. Firing SPINNING there would mislabel an
    outage as a spin and rob the caller of the retry ladder — the same precedence
    the file already gives those not-a-fault conditions over the UNCLEAR breaker.
  - *Before SHIPPED*: SPINNING reads ground truth, and the whole
    [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) thesis is that ground truth
    overrides the self-report. A loop reporting `SHIPPED` every iteration while
    landing zero commits is the canonical spin; if SHIPPED's healthy path ran first
    it would `_continue_or_cap` and the ground-truth signal would never fire.
    Placing SPINNING ahead of the outcome block is the structural statement "the
    kernel distrusts the token when liveness says nothing moved" — exactly parallel
    to `UNMEASURED_SHIPPED` being checked *first* inside the SHIPPED branch.
  - *Above UNCLEAR*: a confirmed ground-truth spin wins over "increment the streak
    and retry", stopping on hard evidence rather than waiting two more UNCLEARs.
- **`STALLED` is NOT mapped to a self-stop.** `STALLED` means "dead or hung — the
  orphan-sweep's input, not a spin" (`liveness.py`). A loop that is *making
  decisions* is by construction alive, so a STALLED verdict reaching `decide()` is
  degenerate; STALLED is the **supervisor's** REAP input (`supervise.py`), already
  handled there. Folding it into the loop's self-stop would duplicate the
  supervisor's reap responsibility and blur the alive-vs-dead line the whole of
  [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) draws. (A host that wants
  belt-and-suspenders can add a distinct `StopReason.STALLED`; the kernel default
  is SPINNING-only.)

**Litmus (Piece 1):**
- `test_loop_stops_on_spinning` — `LoopState(liveness=SPINNING)` + any benign
  outcome → `action="stop", stop_reason=SPINNING`.
- `test_no_liveness_verdict_is_byte_identical` — **the behavior-preservation
  proof**: over every `OutcomeKind`, `decide()` returns an identical `LoopDecision`
  whether `liveness` is absent or `None`.
- `test_advancing_verdict_does_not_stop` — `ADVANCING` continues exactly as
  no-verdict.
- `test_spinning_does_not_preempt_rate_limited` / `…_launch_failed` — pin the
  ordering: those fault/transient stops still win over SPINNING.

No new policy is needed for Piece 1: `decide()` consumes a *verdict*, not a
`LivenessPolicy`. The `dos.toml [liveness]` block
([`82` Phase-3c](182_the-kernel-is-a-taxonomy-of-refusal.md)) governs only whoever
*produces* the verdict (the `dos liveness` CLI, which has its own default policy).
**3c is independent of 3a and not a prerequisite.**

## 5. Piece 2 — `halt`, a `reap`-family boundary verb (effectful, the deliberate crossing)

Self-stop covers a loop reacting to its *own* spin. The harder case — an operator
or a supervisor driver wanting to stop a *foreign* run (the hung-for-4-hours job of
§2.1) — needs a verb that crosses from report to effect. Per §3, the kernel may go
exactly two steps and no further: **record the stop decision on the WAL, and
propose the command.** It must not deliver the signal.

### 5.1 The four-gate sort (it is not a verdict)

Run `halt` through the [`85 §2`](85_extending-the-verifiable-surface.md) four-gate
test, the same way [`94 §4.4`](94_checkpoints-and-recovery-from-slop.md) sorted
RESTORE:

- **Gate 1 — a claim about ground-truth state? → DELIBERATELY FAILS.** `halt` does
  not *answer* a question about the world; it *changes* it (or proposes to). It
  produces no belief that can be true or false the way `SPINNING` or `IN_SCOPE`
  can. **Failing Gate 1 is the signal that `halt` is not a verdict** — it belongs
  with `arbitrate`/`spawn`/`reap`, the "cousins, not members" of the
  [`verdict.py`](../src/dos/verdict.py) contract, and is **not** registered in
  [`verdicts.py`](../src/dos/verdicts.py). Identical to how `SuperviseVerdict` is a
  cousin (`supervise.py`).
- **Gate 2 — evidence unforgeable? → vacuous → PASSES.** `halt` consumes no
  agent-authored evidence. Its *trigger* (the SPINNING/STALLED verdict) already
  passed Gate 2 — it reads git/journal, never the self-report. `halt` introduces no
  new forgeability surface.
- **Gate 3 — domain-free? → PASSES, by contract.** This is the gate that *defines*
  the verb. The host supplies an **opaque handle** (a pid, a container id, a remote
  task token — a string), and the kernel records it and, optionally, echoes a
  **host-supplied** stop command. The kernel branches on **nothing** about the
  handle and interprets none of it — the same split as `supervise()` emitting a
  REAP that names only a *lane* while the driver owns the platform-specific
  eviction. A grep of the verb for `kill` / `docker` / `taskkill` / pid-as-integer
  semantics returns nothing.
- **Gate 4 — mechanical closed-enum verdict? → N/A.** `halt` has no verdict enum
  because it is not a verdict; its output is a `HaltResult` record (recorded? /
  handle / proposed-command), pure data — consistent with `supervise`'s `LanePlan`
  being data, not a `TypedVerdict`.

**Sort:** fails Gate 1, passes Gate 3 → a `spawn/reap`-family **boundary verb**,
recorded on the WAL, never a registered classifier. Exactly the placement
[`94 §4.4`](94_checkpoints-and-recovery-from-slop.md) gives the effect verbs.

### 5.2 The two design calls (recommendations, with the tradeoff)

1. **Signal vs propose → PROPOSE (record + echo a command).**
   - *(A) Kernel-sends-signal* — `halt()` calls `os.kill(pid, SIGTERM)`. Immediate,
     one call; but it (i) forces the kernel to read the handle as *a pid on this
     host*, breaking Gate 3 the instant the handle is a container/remote task; (ii)
     crosses the [`94 §6.1`](94_checkpoints-and-recovery-from-slop.md) hard non-goal;
     (iii) exposes the kernel to "acted on an unconfirmed effect" — a half-landed
     signal leaves the WAL disagreeing with reality.
   - *(B) Kernel-records + proposes* **(recommended)** — `halt()` appends an
     `OP_HALT` to the WAL (recording *that the stop decision was made* — the
     legitimate epistemic-adjacent act, identical to logging an `OP_REFUSE`) and
     returns a copyable, host-supplied command for a driver/operator to run. Keeps
     the kernel domain-free (Gate 3) and inside the advisory-only floor; matches the
     shipped supervisor (journal the decision, let the driver `Popen`/signal). The
     `dos decisions` emit-and-exit action bar is the natural home for the proposed
     command. A host that *wants* auto-kill writes a driver that consumes the
     `OP_HALT` record and signals — precisely as `drivers/supervisor.py` consumes
     the REAP plan.

2. **A distinct `OP_HALT` op, NOT a mode of `reap`.** `reap` = "this run is *done*,
   clean it up"; `halt` = "stop this run that is **not** done." Those are different
   *reasons a lease is ending*, and recording *why* is the whole forensic point of
   the closed op vocabulary — an auditor replaying the journal must distinguish a
   *kill* from a *natural death*. So `halt` is its own op, and it is **non-mutating
   in replay** (excluded from `_STATE_MUTATING_OPS`, REFUSE-like): it records the
   stop *intent*, decoupled from the eventual `RELEASE`/`SCAVENGE` that confirms the
   lease actually ended. This decoupling is also why it cannot be a `reap` mode —
   `reap`/`SCAVENGE` *evict*; `halt` *records intent* and lets a later confirmed
   eviction fold the state. (Conflating intent with confirmed effect is the
   [`94 §6.4`](94_checkpoints-and-recovery-from-slop.md) acted-without-confirmation
   hazard.)

### 5.3 Shape and home

- `OP_HALT` + a pure `halt_entry(handle, *, reason, lane="", loop_ts="", run_id=None)`
  builder in [`lane_journal.py`](../src/dos/lane_journal.py), beside
  `scavenge_entry`; excluded from `_STATE_MUTATING_OPS`.
- An effectful `halt(config, *, handle, lane="", owner="", reason="", command=None) -> HaltResult`
  in [`lane_lease.py`](../src/dos/lane_lease.py), modeled line-for-line on
  `release()`: under the `_Mutex`, journal path via `_journal_path(config)` (never
  `__file__`), append `halt_entry(...)`, return `HaltResult(handle, recorded, command)`.
  It **never** calls `os.kill`/`subprocess`. (A new `lane_halt.py` is a defensible
  alternative if a host wants the effect verb visibly fenced from the acquire
  surface; the recommendation is `lane_lease.py` for cohesion.)
- `cmd_halt` + a `dos halt` subparser in [`cli.py`](../src/dos/cli.py), modeled on
  `cmd_lease_lane`: `--handle` (required, opaque), `--lane`/`--owner`/`--reason`/`--run-id`,
  optional `--command` to echo. Output through the `--output json` seam. Exit **0
  on recorded** (it is an effect record, not a verdict — *not* verdict-as-exit-code;
  mirror `cmd_loop`, not `cmd_liveness`).

**Litmus (Piece 2):**
- `test_halt_entry_op_and_keys` — `OP_HALT` + the opaque handle + reason (mirrors
  `test_scavenge_entry_op_and_keys`).
- `test_halt_does_not_mutate_replay_state` — `ACQUIRE` then `HALT` folds to the
  lease **still live** (intent, not eviction).
- `test_halt_then_scavenge_evicts` — `ACQUIRE → HALT → SCAVENGE` folds to empty
  (the driver confirmed the kill, then journaled the eviction).
- `test_halt_records_on_spine` — after `halt()`, `read_all` shows one `OP_HALT`
  carrying the handle.
- `test_halt_resolves_via_config_not_file` — the HALT lands at the configured
  journal path; nothing is written under the package tree (the layering litmus).
- `test_halt_is_domain_free` — pid / container-id / opaque-token handles are
  recorded identically and interpreted none.
- `test_halt_proposes_does_not_signal` — monkeypatch `os.kill`/`Popen` to **raise**;
  `halt()` still succeeds (proving the kernel never calls them — the four-gate
  "deliberately fails the effect-performance gate" proof).

## 6. Non-goals and the open frontier

- **The kernel never delivers the kill.** It self-stops a loop's *own* control flow
  (Piece 1) and *records + proposes* a foreign stop (Piece 2). The signal is always
  a driver's hands — the [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) /
  [`94`](94_checkpoints-and-recovery-from-slop.md) advisory-only floor, here given
  its real justification (§3: domain-freedom, not principle).
- **No watchdog daemon in the kernel.** A push-model supervisor that *polls*
  `liveness`/`verify` on a cadence and routes spinning/hung runs to the decisions
  queue or fires `halt` is the literal "ongoing agent supervisor" — and it is a
  **driver** (the `dos loop` / `drivers/supervisor.py` line), not a kernel change.
  The kernel ships the question-answerer and the stop-recorder; the scheduler that
  asks on a timer is a host's. (This is the build that directly answers the §2.1
  budget-didn't-fire incident; it is sequenced *after* Piece 1, deliberately, to
  keep the kernel change small.)
- **No judging the *quality* of progress.** `liveness` says bytes moved, never that
  they moved *well*; `halt` stops a run, never because the work was *bad*. Quality
  is an advisory judge's call (`drivers/llm_judge`), forever driver-layer — the
  distrust-state / distrust-judgment line.
- **The sub-commit blind spot (§2.3) is the real frontier, and it is left open.**
  The mid-step self-deception failure ("I filled the field" while the DOM shows it
  empty) lives below the granularity of both `verify` (fires at the commit) and
  `liveness` (sees minutes). The kernel-pure shape of catching it is *still a
  verdict, not an actuator*: a **mid-run assertion** the agent's harness pauses at —
  "field X is filled now" — adjudicated against ground truth (re-read the DOM,
  re-run a predicate) before the agent proceeds, with the harness halting on a
  refuse. It is the `dos.predicates` conjunctive seam pointed at the *time axis*
  mid-run. It needs real design (what is the evidence source below a commit? how is
  it kept domain-free and unforgeable?) and is **not** built here. This note closes
  the interval verdict's loop; the sub-interval is the next question.

## 7. What this note claims, and what it does not

- **Does claim:** the kernel already adjudicates before/after and already *detects*
  the in-flight failures (1, 2 in §2); the only deficiency is that the loop does not
  consult its own liveness and stop. Closing that is the
  [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) Phase-3a wiring (Piece 1) and is
  in-bounds because self-stop is control flow, not killing. A foreign stop is
  legitimate only as *record + propose* (Piece 2), a `reap`-family boundary verb
  that passes the four-gate test exactly where the effect verbs pass it. The
  advisory-only law is right, and its real basis is **domain-freedom** — the kernel
  must not learn what a process is.
- **Does not claim:** that the kernel should ever deliver a signal, run a watchdog
  thread, judge progress quality, or that the sub-commit assertion (§6) is solved.
  The architecture stands on the DOS code already on master (`liveness`,
  `loop_decide`'s `UNMEASURED_SHIPPED` precedent, `supervise`/`drivers/supervisor`,
  `lane_lease.release`) and a few durable lines — not on any single product feature.

The meta-answer: **DOS already mints the interval verdict; "runtime validation" is
mostly wiring that verdict into the loop's own stop decision, plus a thin
`reap`-family verb that records a stop and proposes the command — and the reason
the kernel goes no further than *propose* is not a rule handed down but a property
of what a domain-free kernel is: it adjudicates what a run *is doing*, and leaves
*what a run is* — and therefore how to stop it — to the host that knows.**

---

## References

*The in-flight verdict and its consumers (§1, §4):*
- [`src/dos/liveness.py`](../src/dos/liveness.py) — the pure ADVANCING/SPINNING/STALLED classifier (the sensor).
- [`src/dos/loop_decide.py`](../src/dos/loop_decide.py) — the loop-control verdict; the `UNMEASURED_SHIPPED` stop + `consecutive_dirty_zero` breaker are the self-stop precedent.
- [`src/dos/supervise.py`](../src/dos/supervise.py) + [`src/dos/drivers/supervisor.py`](../src/dos/drivers/supervisor.py) — the population verdict + its driver: "propose REAP → driver journals SCAVENGE", the FLAG-a-neighbor discipline, "the kernel never `Popen`s".

*The effect-verb template and the boundary (§3, §5):*
- [`src/dos/lane_lease.py`](../src/dos/lane_lease.py) — `release()`, the effectful-WAL-write template; `_journal_path(config)` path discipline.
- [`src/dos/lane_journal.py`](../src/dos/lane_journal.py) — the closed op vocabulary, `_STATE_MUTATING_OPS`, the entry builders; `OP_REFUSE` ("recorded, does not mutate") is the `OP_HALT` semantics template.
- [`src/dos/verdict.py`](../src/dos/verdict.py) — the `TypedVerdict` contract + the "cousins, not members" clause that holds effect-emitters out of the registry.
- [`src/dos/decisions.py`](../src/dos/decisions.py) — the emit-and-exit action bar (the proposed-command home).

*The frame this extends (§1–§3, §6):*
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md) + [`82_liveness-oracle-plan.md`](82_liveness-oracle-plan.md) — refusal as the primitive; the liveness plan whose Phase 3a this builds; "killing a run" as a stated non-goal.
- [`94_checkpoints-and-recovery-from-slop.md`](94_checkpoints-and-recovery-from-slop.md) — the belief-vs-effect (mint-vs-perform) line; the four-gate sort of RESTORE; the semantic-rollback non-goal.
- [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) — the four-gate test applied to `halt`.
- [`90_open-research-areas.md`](90_open-research-areas.md) §5 — "acting on a spin" as the open question `halt` (as a proposal) answers.
