# 117 — Completion as a verdict: the end of working in passes

> **A "pass" is what you run when you have no completion oracle. The agent stops
> on *budget* — tokens, rounds, "the model stopped emitting tool calls" — and
> narrates "done," because it has no external account of the work's total extent
> nor of what is verifiably closed against it. DOS already built the oracle that
> closes this gap; it is just labelled *crash recovery*. This plan lifts
> `residual = declared − verified` out of the resume path and makes it the
> dispatch loop's *termination condition*, hardens `declared` so the extent is not
> self-reported, and adds a *convergence* verdict for the residual that will not
> shrink. Then a fleet stops working in passes and starts working toward a fixpoint
> it cannot fake.**

Status: **Phases 1–3 SHIPPED (kernel half)** (`src/dos/completion.py` + `dos complete`
CLI + `tests/test_completion.py`, 18 tests; the Phase-3 `decide()` gate in
`src/dos/loop_decide.py` + `TestCompletionSelfStop` in `tests/test_oracle_and_loop.py`,
15 tests; suite green at 1822). The pure live completion verdict (`classify` →
`COMPLETE`/`INCOMPLETE`/`INDETERMINATE`, reusing `resume`'s residual arithmetic
verbatim per §5.1) and the convergence verdict (`convergence` →
`CONVERGING`/`THRASHING`/`STARVED` over a residual-size history) are built and
replay-tested on frozen fixtures.

**Phase 3 (the loop-stop wiring) is shipped in the kernel as far as a pure kernel
can take it.** Two new `StopReason`s — `COMPLETE` ("finished," the first
non-give-up terminal, the anti-`ITERATION_CAP`) and `THRASHING` (no fixpoint /
scope in doubt → surface) — and a completion gate in `decide()` that reads the
in-flight `CompletionVerdict`/`ConvergenceVerdict` off `LoopState` (two new opt-in
fields) and stops on them, checked AFTER the not-a-fault stops and BEFORE the
SPINNING rung (an explicit operator-decided precedence: a provably-finished run
beats a zero-delta SPINNING read — the resumed-already-done case). It is the exact
mirror of the docs/99 `SPINNING` rung: the kernel READS a verdict value, never
computes one; `None` verdicts are byte-identical to the pre-Phase-3 loop (pinned by
`test_no_completion_verdict_is_byte_identical` over every `OutcomeKind`). **What is
deliberately NOT in the kernel** is the *caller's* half of §5.4 — gathering
`AncestryFacts` from git each turn, running `completion.classify`, and re-dispatching
the `.residual` as the next iteration's work-list. That is I/O + host workflow (the
kernel is pure and may not read git inside `decide()`), so it lives in the host
dispatch loop, exactly as `liveness`'s evidence-gather does (the verdict shipped
before its `loop_decide` consumer). The kernel now provides the gate; the host loop
supplies the evidence and performs the re-dispatch.

**Phase 4 (the `ScopeSource` extent rung) is SHIPPED** (`src/dos/scope_source.py`
+ the reference driver `src/dos/drivers/plan_scope.py` + `tests/test_scope_source.py`,
27 tests; the Gate-7 wiring in `completion.classify` + `tests/test_completion.py`,
4 tests; suite green at 1877). `UNDERDECLARED` — unreachable in Phase 3 (the gate
routed it, but nothing emitted it) — is now reachable: the seam is the exact
`overlap_policy` apparatus re-aimed at *extent* (a `ScopeSource` Protocol + a
`ScopeVerdict` + the null `AllDeclaredScope` baseline + `run_scope` fail-to-strict +
the `honest_under_floor` conjunction + a by-name resolver + the `dos.scope_sources`
entry-point group), and `completion.classify` now takes `scope_verdicts` and grants
`COMPLETE` only as `residual_empty AND honest_under_floor(scope_verdicts)` — so a
source can only ever WITHHOLD completion (flip `COMPLETE`→`UNDERDECLARED`), never
grant it. The structural guarantee is the inverse of overlap's and simpler: the
dangerous direction (false-`COMPLETE`) is the one a source cannot reach, so the
conjunction + fail-to-strict ALONE are the proof — no competing deterministic floor
is needed (`test_scope_source.py::TestSoundnessProof` pins it end-to-end: a lying
`extent_honest=True` source cannot manufacture a `COMPLETE` an honest auditor
withholds). With no `scope_verdicts` supplied (the default), `classify` is
byte-for-byte the Phase-1 floor. **What is deliberately NOT in the kernel**: the
`dos complete --scope-source` CLI flag + the `dos.toml [completion] scope_sources`
config seam that *populates* `scope_verdicts` from a workspace declaration (today a
caller passes the verdicts in explicitly; `scope_source.active_scope_sources` is the
call-boundary resolver ready for the CLI to use), and a `dos doctor` listing of the
active scope sources — the operator-surface wiring, deferred the same way Phase 3's
host evidence-gather was. A richer set of real driver sources (changed-files,
acceptance-criteria) is also future; the kernel ships the seam + one reference driver.

**Phase 5 remains** (the `dos complete-eval` instrument — over a labelled corpus of
runs, a confusion grid + a false-`COMPLETE` rate, the `overlap-eval` / `judge-eval`
friendliness pattern). The §7 litmus tests are the acceptance gates — the
Phase-1/2/3/4 ones are now pinned in `test_completion.py` +
`test_oracle_and_loop.py` + `test_scope_source.py` (including the lying-`ScopeSource`
proof: a source can only withhold `COMPLETE`, never grant it); the Phase-5 one (the
false-`COMPLETE` rate over a labelled corpus) awaits that phase. Phases 0–1 were a
re-aiming of shipped code (`resume.COMPLETE` already existed); Phase 2 is the one
genuinely new pure verdict; Phase 3 is the `SPINNING`-rung pattern applied a second
time; Phase 4 is the `overlap_policy` seam pattern applied a third.

---

## 1. The problem: every agentic loop terminates on budget, not on done

No matter how much orchestration sits on top — more agents, more rounds, a
supervisor, a workflow DAG — every agentic system today runs **a pass**: a bounded
sweep that terminates when it runs out of *budget*, never when the *work is
closed*. The budget is tokens, wall-clock, a max-round counter, or simply "the
model stopped emitting tool calls." None of those is a statement about the work.

The symptom the operator sees is that the job never *completes fully*. Two
distinct failures hide under that one observation, and **they compound** — the
agent cannot tell which one it is in, because it has no external ground truth for
either:

- **It can't stop (no static fixpoint).** Each review pass surfaces new findings;
  each cleanup pass dirties new code. The loop asymptotes but never converges,
  because nothing tests whether the *residual is empty*.
- **It stops too early and says it's done (false completion).** A pass terminates
  on budget, the model narrates "✅ complete," and orchestration stacks *more
  passes* — but each pass is still self-certified, so N passes never sum to a
  *completion*. You get motion, not closure.

The deep cause is identical for both: **the agent has no durable, external account
of two numbers — the work's total extent (*declared*) and what is verifiably done
against it (*verified*).** Without them, "am I finished?" is unanswerable, so the
agent substitutes the only thing it *can* measure — "did this pass run?" — and that
substitution **is** working-in-passes.

### 1.1 This is the DOS disease, pointed at a new noun

An agent saying "I'm done" is a self-report. A pass declaring success is a
self-report. The kernel's entire thesis — *the kernel is the part that doesn't
believe the agents* — is exactly the right hammer. It has simply never been
pointed at **completion** as a first-class verdict. The other distrust primitives
already ship; completion is the next one.

**The self-report → distrust-verdict ladder** (the spine of this plan — each row is
a thing the agent *says*, paired with the DOS verdict that refuses to take it on
faith and adjudicates it against the fossils instead):

| The self-report the agent makes | The DOS verdict that distrusts it | Module | Status |
|---|---|---|---|
| "this step shipped" | `verify()` → `SHIPPED` / `NOT_SHIPPED`, from git ancestry | `oracle`, `phase_shipped` | ✅ shipped |
| "I'm making progress" | `liveness()` → `ADVANCING` / `SPINNING` / `STALLED`, from the git/journal delta | `liveness` | ✅ shipped |
| "I may take this region" | `arbitrate()` → `ACQUIRE` / refuse, from the live lease set | `arbiter` | ✅ shipped |
| "I crashed here; resume from X" | `resume_plan()` → `RESUMABLE` / `COMPLETE` / `DIVERGED`, residual vs ancestry | `resume` | ✅ shipped (recovery-only) |
| **"I'm done with the whole job"** | **a *live* `COMPLETE` verdict, looped on as the stop condition** | **`completion` (new) + `loop_decide`** | ⚠️ exists, wired only for recovery |
| **"the job was only this big"** | **a distrusted-`declared_steps` check against external scope** | **`ScopeSource` rung (new)** | ❌ gap |
| **"I keep finding more, but I'm progressing"** | **`CONVERGING` / `THRASHING`, from |residual| across rounds** | **`completion` (new)** | ❌ gap |

"Working in passes" is **precisely the three rows that are not shipped.** The job of
this plan is to ship them — and two-thirds of the hard part is already sitting in
`resume.py`, written for a different occasion.

---

## 2. What already exists (and why it is 80 % of the answer)

Three pieces are already in the kernel and point straight at completion. None of
them was built *for* the live-completion problem, which is why the problem persists
despite them.

**(a) `verify()` is a per-unit completion oracle.** "Did (plan, phase) *actually*
ship?" — answered from git ancestry on a non-forgeable rung, never from "I'm done"
(`oracle.is_shipped`, `phase_shipped`). This is the atom: it adjudicates *one*
unit's completion against ground truth. What it lacks is any notion of *the set of
all units that must be closed* — it answers about a unit you *name*. It is a
spot-check, not a convergence test.

**(b) The intent ledger already stores `declared` vs `verified`, deliberately
apart.** `intent_ledger.LedgerState` (`intent_ledger.py:235`) carries
`declared_steps` — the total extent the run committed to — and `verified` — the
steps confirmed-done on the non-forgeable rung — and keeps them as separate fields
**because the whole epistemic point (§3.2 of docs/107) is that they are not
equal.** These are exactly the two numbers the completion question needs, and they
are already durable, already replay-foldable, already distrust-shaped (`claimed` is
held apart from `verified` too).

**(c) `resume_plan` already computes the residual and emits `COMPLETE`.**
`resume.resume_plan` (`resume.py:265`) computes
`residual = declared_steps − contiguous-verified-prefix` and returns
`Resume.COMPLETE` precisely when **the residual is empty: every declared step
verified against ancestry** (`resume.py:409`). That is a static fixpoint verdict.
It already distinguishes the three states the operator conflates:

- `RESUMABLE` (non-empty residual) — "there is verifiably more to do,"
- `COMPLETE` (empty residual) — "the declared work is verifiably closed,"
- `DIVERGED` (residual exists but ground truth moved past it) — "stopped, and the
  world changed underneath."

And it is already false-completion-proof at the unit level: `resume.py:282` keeps a
`STEP_CLAIMED` the agent *narrated* but never landed **in the residual**. That one
line is the entire answer to per-step false completion — *a claimed-done step that
git cannot confirm is still on the to-do list.*

> **The completion oracle is already written. It is trapped inside the
> crash-recovery framing.** `resume_plan` is documented and built as "the third
> ARIES phase: a run died/paused — how far did the fossils say it got?"
> (`resume.py:1`). The `residual == ∅` test only runs when you are *resuming a dead
> run*. The "passes" problem is not about crashes — it is about a **live, healthy,
> actively-orchestrated** fleet that never asks "is the residual empty *now*?",
> because nothing in the *normal* loop computes it.

---

## 3. The three gaps

### Gap A — completion is computed on resume, not on the live loop

Nothing in the running dispatch loop asks `resume_plan` "is the residual empty
now?" after a round. The loop terminates on its **own** budget, and the proof is in
the kernel's own stop vocabulary. `loop_decide.StopReason` (`loop_decide.py:304`)
enumerates *eleven* ways the loop can stop:

```
ITERATION_CAP, DRAINED_TWICE, DRAIN, BLOCKED, CONSECUTIVE_UNCLEAR,
CONSECUTIVE_DIRTY_ZERO, CONSECUTIVE_OVERLOADED, RATE_LIMITED, LAUNCH_FAILED,
UNMEASURED_SHIPPED, SPINNING
```

**Not one of them is "the work is done."** Every terminal path is a give-up
(`ITERATION_CAP`), a circuit-break (`CONSECUTIVE_*`), an outage (`RATE_LIMITED`,
`LAUNCH_FAILED`), or a stall (`SPINNING`). `ITERATION_CAP` — "reached
max_iterations" — **is the pass, encoded directly in the kernel's loop verdict.**
The loop stops because it ran its rounds, then a *human* might run `dos resume`
later and discover it was `RESUMABLE` the whole time. The fixpoint test exists but
is **not wired as the loop's termination condition.** The loop should not stop
because it ran out of rounds; it should stop because the residual is empty — and
**keep re-dispatching the residual** while it is not.

### Gap B — `declared_steps` is the agent's own list (the load-bearing gap)

`intent_entry` (`intent_ledger.py:433`) lets the run declare its *own*
`declared_steps`. So false-completion re-enters through the back door: not "I lied
that I did it," but **"I lied about how much there was."** Declare 3 steps, finish
3, earn `COMPLETE` — while the real work needed 8. The *extent* is as self-reported
as the *progress*, and the kernel currently distrusts the second but not the first.
This is the same shape docs/103 named for memory ("a frozen self-report recalled as
fact"): **declared extent is just another self-report**, and a completion oracle
that trusts it is checking the agent's homework against the agent's own answer key.

**Operator decision (settled): floor + opt-in rung.** Ship the narrow version as
the kernel floor (`COMPLETE` ⟺ everything *declared* is verified), AND add an
**optional, pluggable `ScopeSource` rung** that a host can wire to cross-check
`declared_steps` against an external scope (the plan registry's phase list, a PR's
changed-files, an issue's acceptance criteria). Like the `overlap_policy` floor,
the rung can only make completion **harder** (refuse-more), never easier — see §5.3.

### Gap C — no convergence / oscillation verdict

`COMPLETE` is a *static* fixpoint (residual empty). But the "can't stop" failure is
usually *dynamic*: the residual never empties because each pass adds as much as it
closes (the reviewer-finds-new-findings loop). There is no verdict for "the
residual is **not shrinking** across rounds." That is a *different* "no" from the
two we already have:

- `liveness.SPINNING` = *not committing* (zero forward git delta) — temporal, about
  whether anything lands at all.
- `resume.RESUMABLE` = *work remains* (residual non-empty) — static, a single
  snapshot.
- **The missing verdict** = *commits are landing, the residual is changing, but
  |residual| is not monotonically decreasing* — the agent is busy and productive
  and **will run forever**. Call it `THRASHING` (its converging twin is
  `CONVERGING`).

This is the honest verdict for "this loop has no fixpoint," and it is the one that
turns an infinite review loop into a *surfaced decision* ("the residual has
oscillated for K rounds — a human must cut scope or accept") instead of silent
budget-exhaustion.

---

## 4. The reframe, in one line

> Lift `residual = declared − verified` out of the resume path and make it the
> dispatch loop's **termination condition**; harden `declared` with an optional
> external-scope rung so it is not self-reported; and add a **convergence verdict**
> over |residual| across rounds. Completion becomes the **next distrust primitive**
> — and two-thirds of it is already in `resume.py`, waiting to be pointed at the
> live loop instead of the morgue.

---

## 5. The design

A new pure module `dos.completion`, a sibling of `resume`/`liveness` in the kernel
layer (it imports `intent_ledger`, never a host, never I/O). It holds the **live**
completion verdict and the **convergence** verdict; it reuses `resume`'s residual
arithmetic verbatim rather than reimplementing it.

### 5.1 The live completion verdict (Gap A)

```
completion.classify(LedgerState, AncestryFacts, [ScopeVerdict], policy) -> CompletionVerdict
```

Field-for-field a sibling of the existing pure verdicts:

```
arbiter.arbitrate      (request, live_leases, config)              -> decision
liveness.classify      (ProgressEvidence, policy)                  -> LivenessVerdict
resume.resume_plan     (LedgerState, AncestryFacts, policy)        -> ResumePlan
completion.classify    (LedgerState, AncestryFacts, scope, policy) -> CompletionVerdict   ← THIS
```

`CompletionVerdict.state` is a typed enum:

- `COMPLETE` — residual empty **and** (no `ScopeSource` wired, or every wired one
  agrees the declared extent was real). The only verdict that authorises the loop
  to stop-on-done.
- `INCOMPLETE` — residual non-empty. Carries the residual so the loop re-dispatches
  *it*, not a fresh pass.
- `UNDERDECLARED` — residual empty **but** a `ScopeSource` says the declared extent
  was smaller than the real scope (the Gap-B refusal). NOT complete; surfaces a
  decision.
- `INDETERMINATE` — the ledger fold is unsound (`unreadable_newer`, corrupt past) —
  the `resume.UNRESUMABLE` floor, restated: refuse to *call it done*, don't guess.

The residual and the contiguous-verified prefix are computed by **calling
`resume`'s existing logic**, not duplicating it — `resume_plan` already does the
ancestry re-adjudication, the contiguous-prefix rule, and the fail-closed
treatment of `claimed`-but-unverified. `completion.classify` is a thin re-framing:
it takes the same residual and answers a *forward* question ("is it empty, and was
the extent honest?") rather than a *backward* one ("where do I re-enter?").

The verdict is **advisory** — it reports; it does not kill the loop. The loop reads
it (§5.4) and decides to stop. Same actuation-boundary floor as everything else
(docs/99): the kernel mints the belief "the declared work is verifiably closed";
the act of stopping is the loop's/driver's.

### 5.2 The convergence verdict (Gap C)

```
completion.convergence(residual_history: tuple[int, ...], policy) -> ConvergenceVerdict
```

Pure over a **history of residual sizes**, one int per completed round (the loop
appends |residual| each iteration; the history is cheap and lives in `LoopState`).
Verdict:

- `CONVERGING` — |residual| is (weakly) monotonically decreasing over the window
  and trending to 0. Keep going; the fixpoint is reachable.
- `THRASHING` — |residual| has failed to decrease for `max_nonconverging` rounds
  (default 3, the existing circuit-breaker idiom — cf. `max_unclear`,
  `max_dirty_zero`): work lands but the residual oscillates or grows. The loop has
  no fixpoint; **surface a decision**, do not burn budget.
- `STARVED` — |residual| is non-empty and *unchanged* across the window with zero
  verified progress — distinct from `THRASHING` (which churns) and deferred to
  `liveness.SPINNING` when the cause is "nothing committing." Included for
  completeness; may collapse into `THRASHING` in Phase 2 if it earns no distinct
  action.

This is the verdict that makes "it never completes" *legible*: the operator-decisions
queue can now show "run R: THRASHING — residual oscillated 4,3,4,3 over 4 rounds;
the loop will not converge; cut scope or accept partial."

### 5.3 The `ScopeSource` extent rung (Gap B) — floor + opt-in, refuse-more-only

The exact `overlap_policy` / `judges` pattern, re-aimed at *extent*:

```python
class ScopeSource(Protocol):
    """Cross-checks a run's DECLARED extent against an EXTERNAL account of scope.
    Returns a ScopeVerdict: did the run declare the WHOLE job, or under-declare?"""
    def scope_verdict(self, state: LedgerState, cfg) -> ScopeVerdict: ...
```

- **The floor is structural and unforgeable.** `completion.classify` computes
  `COMPLETE` only as `residual_empty AND all(sv.extent_honest for sv in scope_verdicts)`.
  A `ScopeSource` returns a verdict that includes "extent OK," so — exactly like
  `overlap_policy.admissible_under_floor` AND-ing a scorer under the prefix floor
  (`admit ⟺ floor.admissible AND policy.admissible`) — a buggy/lying/raising
  `ScopeSource` can only **withhold** `COMPLETE`, never grant it. The safe
  direction is guaranteed by construction: with no source wired, completion is
  exactly today's "all declared verified" floor; each wired source can only make it
  *stricter*.
- **`run_scope` fails to the strict side.** A `ScopeSource` that raises or returns
  a malformed verdict is converted to `extent_honest = False` →
  `UNDERDECLARED` is surfaced rather than `COMPLETE` granted — the judge
  fail-to-ABSTAIN analogue, but biased toward *refusing completion* (the
  conservative direction for "are we done").
- **The rung lives in a driver; the seam lives in the kernel.** The kernel ships
  the `ScopeSource` Protocol + `ScopeVerdict` + `run_scope` + a by-name resolver
  over a `dos.scope_sources` entry-point group + a built-in **null** source
  (`AllDeclaredScope`, always `extent_honest=True` — the unshadowable floor that
  reproduces today's behaviour). Every *real* source — "diff the declared steps
  against the plan registry's phase list," "compare against the PR's changed-files,"
  "check issue acceptance-criteria" — is a **driver** (`drivers/…`), discovered by
  name at the call boundary, never imported by a kernel module. The `dos.drivers`
  litmus (no `src/dos/*` except `drivers/` imports `dos.drivers`) covers it.

This is the part that makes "done means done against the *real* scope, not the
scope the agent chose to admit" a kernel-enforceable property — without baking any
host's notion of scope into the kernel.

### 5.4 Wiring the loop to stop-on-done (Gap A, the actuation)

Two new `StopReason`s and the decide-loop change:

- `StopReason.COMPLETE = "complete"` — the loop stops because
  `completion.classify` returned `COMPLETE`. **This is the first stop reason that
  means "finished," not "gave up."** It is the anti-`ITERATION_CAP`.
- `StopReason.THRASHING = "thrashing"` — the loop stops (and **surfaces**) because
  `completion.convergence` returned `THRASHING`: no fixpoint, do not burn the cap
  silently.

`loop_decide.decide()` gains, ahead of the existing cap/circuit checks, a
completion gate:

1. After each iteration, the loop already knows the run's `LedgerState` (it owns the
   intent ledger). Gather `AncestryFacts` at the boundary (the same git read
   `resume`'s evidence-gather does), run `completion.classify`.
2. `COMPLETE` → stop with `StopReason.COMPLETE` (no surface — a clean finish).
3. `INCOMPLETE` → **continue, re-dispatching the residual** (the residual becomes
   the next iteration's work list), *subject to* the convergence gate:
4. Append |residual| to history; run `completion.convergence`. `THRASHING` → stop
   with `StopReason.THRASHING` (surface). `CONVERGING` → continue.
5. `UNDERDECLARED` → stop and surface (the run thinks it's done; an external scope
   says it under-declared — a human must reconcile).
6. `INDETERMINATE` → fall through to the existing logic (don't *assert* completion
   on an unsound fold).

The critical inversion: **`ITERATION_CAP` stops being the *primary* terminal and
becomes the *backstop*.** A healthy loop now terminates on `COMPLETE` (it
converged) or `THRASHING` (it provably won't); the cap only fires when neither
verdict resolved in `max_iterations` — a genuinely pathological run, which is
exactly when a hard cap *should* be the thing that stops you.

### 5.5 CLI + MCP surface

- `dos complete --workspace . <run_id>` — print the `CompletionVerdict` (state +
  residual + which `ScopeSource`s weighed in). The read-only "is this run actually
  done?" probe, runnable by a human *outside* the loop (the `dos plan`
  check-outside-the-loop discipline, applied to completion). `--json` for the
  decisions queue.
- A `COMPLETION` source in `dos.decisions` (the projection), so `UNDERDECLARED` and
  `THRASHING` show up in the operator queue with their resolver kind, exactly as
  `LIVENESS` did (docs/101 Phase-3b).
- An MCP tool `dos_complete` exposing the verdict to any MCP host (the adoption
  surface; same one-way arrow as the rest of `dos_mcp`).

---

## 6. Phasing

- **Phase 0 — the doc + the chart (this file).** The self-report ladder (§1.1) and
  the `StopReason`-has-no-"done" finding (§3 Gap A) are the load-bearing framing;
  they belong in the design record regardless of build order.
- **Phase 1 — `dos.completion` pure module, floor only.** `classify` (reusing
  `resume`'s residual), `CompletionVerdict`, `COMPLETE`/`INCOMPLETE`/`INDETERMINATE`
  (no `UNDERDECLARED` yet — no scope rung), + `dos complete` CLI read-out. Pure,
  fully replay-testable on frozen `LedgerState` + `AncestryFacts` fixtures (no live
  loop). This alone gives a human the "is it *really* done?" probe and is the
  cheapest dogfood win.
- **Phase 2 — the convergence verdict.** `completion.convergence` +
  `CONVERGING`/`THRASHING` over a residual-size history. Pure; tested on synthetic
  histories. No loop wiring yet.
- **Phase 3 — loop-stop wiring.** `StopReason.COMPLETE` + `StopReason.THRASHING`,
  the `decide()` completion gate (§5.4), residual re-dispatch, |residual| history in
  `LoopState`. This is where the fleet stops working in passes — the behavioural
  change.
- **Phase 4 — the `ScopeSource` extent rung (Gap B).** Protocol + `ScopeVerdict` +
  `run_scope` + resolver + null floor in the kernel; `UNDERDECLARED` state;
  `admissible-under-floor`-style conjunction. A reference driver (`drivers/…`)
  cross-checking `declared_steps` against the plan registry's phase list. The
  `dos.scope_sources` entry-point group.
- **Phase 5 — the eval harness (the per-axis instrument).** `dos complete-eval`:
  over a labelled corpus of runs (truly-done / under-declared / thrashing), a
  confusion grid + a **false-COMPLETE rate** (the friendliness instrument, the
  `overlap-eval` / `judge-eval` pattern — the number that says "how often does this
  call a job done when it wasn't"). This is the metric that makes the whole thing
  falsifiable.

Phases 0–2 touch no running loop and ship pure, testable verdicts; Phase 3 is the
first behavioural change and should land behind the existing `dos.toml` policy
seam so a host opts in; Phase 4–5 are the distrust-the-extent and measure-it tiers.

---

## 7. The litmus tests (acceptance gates)

- **A loop can stop because it finished.** `StopReason.COMPLETE` exists and
  `decide()` emits it when `completion.classify` returns `COMPLETE`. Pinned by a
  test that runs a loop to an empty residual and asserts the stop reason is
  `COMPLETE`, not `ITERATION_CAP`. *(Today there is no such stop reason — this is
  the headline gate.)*
- **A claimed-but-unverified step blocks completion.** A run that declares 5 steps,
  `STEP_CLAIMED`s all 5, but only lands 3 in ancestry → `INCOMPLETE` with a 2-step
  residual, NEVER `COMPLETE`. (Inherits `resume.py:282`; re-pinned at the
  completion surface.)
- **A swappable `ScopeSource` can only refuse completion, never grant it.** A
  hostile source returning `extent_honest=True` for a run that closed its declared
  residual cannot upgrade anything (residual-empty already → `COMPLETE` under the
  floor); a source returning `extent_honest=False` *downgrades* `COMPLETE` →
  `UNDERDECLARED`. A *raising* source → `UNDERDECLARED` (fail-strict). Pinned the
  way `test_overlap_policy` pins the lying-admit policy.
- **The convergence verdict catches a non-shrinking residual.** A residual history
  `(4,3,4,3)` → `THRASHING`; `(8,5,3,1)` → `CONVERGING`. Pinned on synthetic
  histories.
- **Completion needs no plan (the `verify`-no-plan invariant, extended).** A run
  with a free-form goal and no `ScopeSource` wired still gets a sound
  `COMPLETE`/`INCOMPLETE` from the floor — the kernel does not *require* external
  scope to answer, it only *tightens* when scope is supplied.
- **The kernel imports no scope driver.** No module under `src/dos/` (except
  `drivers/`) imports a `ScopeSource` implementation; the seam holds only the
  Protocol + null floor. Grep-checkable, the `dos.drivers` litmus.
- **`completion` is pure.** `classify` / `convergence` make no subprocess, file, or
  clock call; all evidence (`AncestryFacts`, residual history) is a field handed in
  at the boundary — replay-tested on frozen fixtures, the `liveness`/`resume` rule.

---

## 8. Non-goals

- **The kernel never re-runs the work.** `completion` mints the belief "done / not
  done / under-declared / won't-converge" and the loop *decides* to stop; the
  kernel does not itself spawn, re-dispatch, or kill (docs/99 advisory floor, §8 of
  docs/107 restated for the forward axis).
- **No semantic correctness claim.** `COMPLETE` means *every declared unit is
  verifiably closed against ground truth, and the declared extent survived any
  external scope check* — NOT "the work is good." Correctness stays the JUDGE/HUMAN
  rung (docs/84–86); completion is the ORACLE rung answering *extent*, not
  *quality*. This is the docs/79 primitives-not-features discipline: a small, hard,
  honest "is it all closed?" — with the open space above it left for judgment.
- **The kernel does not invent scope.** Where there is no external account of the
  job's extent, the floor answers from the declared steps alone and says so; it
  does not fabricate a "real" scope. Distrusting the extent is *opt-in evidence*
  (a wired `ScopeSource`), never a kernel guess.

---

## 9. Provenance

This plan re-aims shipped machinery. The residual arithmetic, the contiguous-prefix
rule, the ancestry re-adjudication, and the `COMPLETE`/`RESUMABLE`/`DIVERGED`
trichotomy are `dos.resume` (docs/107), lifted from the crash-recovery framing to
the live loop. The floor-plus-opt-in-rung-that-can-only-refuse-more shape is
`dos.overlap_policy` (docs/113) and `dos.judges` (docs/86). The advisory /
actuation-boundary floor is docs/99. The "declared extent is a self-report" insight
is docs/103 ("memory is an unverified agent") pointed at the *size* of the job
rather than its *progress*. The new surface is small: one pure verdict module, two
stop reasons, one optional rung, and the loop-gate that finally lets a fleet stop
because it is **done** rather than because it is **out of budget**.
