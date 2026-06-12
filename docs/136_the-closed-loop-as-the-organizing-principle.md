# The closed loop — why "close the loop" is the one principle under all of DOS

> **An open loop fires an action and never reads back what the action did. A
> closed loop reads the result and lets it change the next action. Every failure
> mode DOS exists to catch is an *open loop somewhere* — a claim banked without
> reading git, a fleet launched without a way to see which member is stuck, a
> recurring fix fed back into a prompt instead of into a deterministic rung, a
> transition parked "for later" with nothing watching whether "later" came. And
> every DOS primitive is the *closing* of one of those loops: the syscalls are the
> feedback path that turns a fire-and-pray fleet into a system you can actually
> steer. This note argues that "close the loop" is not one feature among many —
> it is the single organizing principle the whole kernel is an instance of, names
> the **four loops** DOS closes (control, trust, improvement, completion), and
> shows each is already partly built so the claim is checkable, not slogan.**

A synthesis note. It does not introduce a new primitive; it argues that the
primitives already shipped are all the *same shape* — and that naming the shape
is what makes the next pickups obvious. It ties together
[`82`](82_liveness-oracle-plan.md) (the in-flight sensor),
[`98`](98_the-orchestrator-is-a-driver.md) (the open-vs-closed benchmark),
[`99`](99_runtime-validation-and-the-actuation-boundary.md) (the advisory
actuation boundary — DOS supplies the signal, a host closes on it),
[`107`](107_resumable-work-and-the-intent-ledger.md) /
[`117`](117_completion-as-a-verdict-the-end-of-working-in-passes.md) /
[`133`](133_deferred-obligations-and-the-mid-flight-gap.md) (the completion
loop), and the live `scout.ClosedLoopSignal` rung (the improvement loop). The
control-theory framing is the operator's own (memory:
`project-dos-closed-loop-control`); this note generalizes it from "a positioning
axis" to "the architecture's keystone."

---

## 1. The definition, kept literal

Borrow the control-systems meaning exactly, because it is load-bearing and the
loose metaphor ("close the loop = follow up") loses the whole point.

- **Open loop:** `command → plant → (output is never measured)`. The controller
  commits to its action and never observes the effect. It works only when the
  plant is perfectly predictable and nothing perturbs it. Add *any* disturbance —
  a worker that lies, a write that collides, a step that silently fails — and the
  error accumulates undetected because **there is no path from the output back to
  the next command.**
- **Closed loop:** `command → plant → output → sensor → compare to reference →
  error → next command`. The controller *reads back the result* and the error
  drives the correction. Disturbances are rejected because the loop sees them.

Now translate the plant. **In a fleet of autonomous agents, the "plant" is the
agents acting on shared state, and the "output" is what they actually did — not
what they said they did.** An agent's self-report (`{shipped: true}`) is *not* a
sensor reading; it is part of the command path talking about itself. (This is the
docs/116 §2.5 point: a self-report is generation #2 narrating generation #1 — the
only true sensor reading is the un-authored effect, the commit in git, the email
the counterparty received.) So the question "is this fleet open-loop or
closed-loop?" reduces to: **is there a feedback path from the un-forgeable effect
back to the next decision, or does the system act on narration?**

That single question is the whole of DOS. Every syscall is a wire on the feedback
path; every refusal is the error signal driving a correction.

---

## 2. "Just run N agents" is the open-loop plant — stated precisely

The operator's recurring framing (memory `project-dos-closed-loop-control`): today
you *can* spin up N ultracode/Workflow sessions on N plans. What you cannot do is
**read back, mid-run, which of the N is spinning, which is drifting out of its
lane, which is lying about being done — and redirect the right one.** You fire N
bets and read N walls of output later and hope. That is the *definition* of open
loop: parallelism with no feedback path.

The honest steelman is "but the agent reads its own output and self-corrects —
isn't that a closed loop already?" No, and the reason is the same one the whole
kernel rests on: **a loop where the controller and the sensor are the same
untrusted generator is not closed — it is open with extra steps.** The agent
grading its own work is the plant reporting its own output; a disturbance that
corrupts the action (a confabulated success) corrupts the measurement identically,
so the error signal is zero exactly when it should be largest. A closed loop needs
a sensor *the plant cannot author.* That is why the sensor has to be git ancestry,
an OS exit code, a counterparty's receipt — evidence whose byte-author is not the
judged agent (docs/117 the log-source seam; docs/123 the independence coordinate).
**The feedback path must cross a trust boundary or it is not feedback.**

---

## 3. The four loops DOS closes

"Close the loop" is not a single mechanism — DOS closes **four** distinct loops,
each a different reference signal compared against a different un-forgeable output.
Naming all four is the doubling-down: they look like separate features (liveness,
verify, scout, resume) but they are one principle instantiated four times.

### 3.1 The CONTROL loop — *is the running fleet steerable?*

- **Reference:** "every member is advancing within its lane."
- **Sensor:** `liveness()` (ADVANCING/SPINNING/STALLED, from the git/journal delta,
  not the "making progress" self-report — docs/82); `scope.classify` (is it
  drifting out of its declared tree?); `verify()` (did this one actually ship?).
- **Comparator + error:** the `dos decisions` queue + `dos top` — the *operator
  console* where the divergence between intended and actual becomes visible and
  actionable.
- **Actuator:** `refuse()` / `arbitrate()` — deny the colliding effect, hold the
  lane. (Advisory by design, docs/99: the kernel emits the error signal; a host
  watchdog or a human closes the final actuation — the docs/101 watchdog driver is
  exactly that closing built once, as a driver.)

This is the operator's original axis: **parallelism is easy; control of a running
fleet is the hard part, and the distrust syscalls are what make a fleet
closed-loop instead of fire-and-pray.** Shipped sensors: `liveness` Phases 1–2,
`scope`, `verify`. Shipped console: `dos top`, `dos decisions`. Shipped actuator:
`arbitrate`/`refuse`. The loop is wired end to end today; what a host adds on top
is the *automatic* closing (kill-the-spinner), which the kernel deliberately
leaves as buildable space.

### 3.2 The TRUST loop — *is what we banked actually true?*

- **Reference:** "banked = shipped" (the ledger of done work equals ground truth).
- **Sensor:** `oracle.is_shipped` against real git ancestry — never the worker's
  `{shipped: true}`.
- **Error:** a claim with no commit closing it → `shipped=False` → a caught lie,
  refused and never banked.

This is the loop the **FleetHorizon benchmark** measures literally:
[`open_loop.py`](../benchmark/fleet_horizon/open_loop.py) *believes* the
self-report and banks it verbatim; [`closed_loop.py`](../benchmark/fleet_horizon/closed_loop.py)
runs the **same** workload, **same** seed, **same** failure model under the real
kernel and *adjudicates* every claim against a real git repo. The only difference
between the two files is the feedback path: one reads the output, one does not.
The measured gap (headline cell, 8 efforts × 30 phases, kernel 0.6.0):

| | open loop (believe) | closed loop (adjudicate) |
|---|---|---|
| banked as shipped | 240 | 205 |
| └ of those, LIES banked | **35** | **0** |
| silent overwrites on shared state | **7** | **0** |
| human-review fraction | **100%** | **17.1%** |
| verified-velocity / $ (κ=5) | 0.387 | **0.520** |

The open loop banked 35 false "shipped" claims (14.6% of its ledger) it *could not
detect* — not because its agents were worse (they were identical) but because it
had no wire from the output back to the decision. The closed loop caught all 35
and prevented every silent overwrite, at a cost of +40.8% actions. And critically:
**the value is monotone in horizon × fanout and → 0 at fleet/horizon = 1** (its own
falsifier). One agent on one PR rarely lies, rarely collides — the open loop looks
fine, because with no disturbance an open loop *is* fine. The loop only earns its
keep when the plant is being perturbed, which is exactly the regime a *fleet* on
*shared state over a long horizon* lives in. **The benchmark is evidence — from a
single deterministic simulation with an injected failure model — that closed-loop
scales where open-loop does not; field data would test it harder.**

### 3.3 The IMPROVEMENT loop — *does a fix stop the failure, or just survive this run?*

This is the deeper, less-obvious loop, and it is already live in the kernel as
[`scout.ClosedLoopSignal`](../src/dos/scout.py) (the rule-9 "closed-loop focus
bias," operator directive 2026-06-04). It is worth stating in full because it is
the one that compounds:

> **Open-loop work bleeds at a constant rate; closed-loop work pays down the rate.**

The worked example from the scout docstring: an apply learning engine extracted a
screening-answer fix at confidence 1.0 roughly fifty times — but only ever fed it
back into the *LLM prompt* (an open loop: the model is asked again each run and may
or may not use it), so the field failed ~50 times. *Closing* the loop (FQ-467:
promote the lesson to a **config write the deterministic path reads**) removes the
failure class outright. The difference is precisely open vs closed: feeding a
correction into a generator that may ignore it is open loop; feeding it into a
deterministic rung that *must* honor it is closed loop.

So scout, when a lane is otherwise clean to dispatch, **biases `focus` toward the
loop-closing work** — the work that converts a recurring observation into a durable
mechanism (an oracle, a preflight, a gate, a learned-answer promoter). Given two
pickable items of equal urgency, the one that *pays down a failure rate* beats the
one that *does a task once*, because the first one shrinks all future runs and the
second does not. This is closed-loop control applied to the **engineering
backlog itself**: the reference is "recurring failures should become impossible,
not re-corrected," the sensor is "how often did this class recur," and the error
drives prioritization toward mechanization.

This loop is why DOS is a *self-improving substrate* and not just a referee: the
referee's own findings (a lie caught, a collision refused, a wedge that recurs) are
the sensor readings that tell the fleet which mechanism to build next — and scout
routes attention there. A fleet that only does open-loop work runs forever at its
ambient failure rate; a fleet that preferentially closes loops drives that rate
down over time.

### 3.4 The COMPLETION loop — *did the work actually finish, or just stop?*

The fourth loop is the one DOS is still mostly *opening the spec on*, and it is the
subtlest: an open loop can fail not only by acting on a lie, but by **never reading
back whether it is done** — stopping on budget instead of on completion, or parking
a transition "for later" with nothing watching.

- [`117`](117_completion-as-a-verdict-the-end-of-working-in-passes.md): agents stop working when they hit an
  iteration cap or a token budget, *not* when the work is actually complete —
  `loop_decide.StopReason` has eleven reasons and **none of them means "done."**
  The loop closes on exhaustion, not on a completion signal. The fix reframes
  completion as the next distrust verdict: a residual (declared − verified) folded
  over the live loop, so the loop can stop *because the work is done* (a
  ground-truth `COMPLETE`), not because it ran out of road.
- [`133`](133_deferred-obligations-and-the-mid-flight-gap.md): a multi-step change
  whose later step was deliberately parked ("migrate the rest in a quiet window,"
  "flip the flag later") is an open loop with *no controller at all* — no run holds
  the residual, no deadline, no detector, and `liveness` never fires because the
  half-done state looks perfectly healthy. Three such deferred obligations decayed
  into permanent ones in a single audit. The fix is an obligation ledger carrying a
  **completion predicate as data** that the kernel re-checks at a boundary — closing
  the loop on a transition the same way `resume` (docs/107) closes it on a crashed
  run.

Both are the completion loop: the reference is "the obligation's completion
predicate holds," the sensor is the kernel re-checking that predicate against
ground truth, and the error is "who still owes this?" Without it, "I'll finish
later" is an open command with no feedback — and the field measures that loops left
open this way do not close themselves.

---

## 4. The unifying table — one shape, four instances

| Loop | Reference (what "good" is) | Sensor (un-forgeable output) | Error signal | Actuator / who closes it | Status |
|---|---|---|---|---|---|
| **Control** (§3.1) | every member advancing in-lane | `liveness` / `scope` / `verify` over git+journal delta | SPINNING / out-of-scope / not-shipped | `arbitrate`/`refuse` + `dos decisions`/`dos top`; host watchdog auto-acts | sensors+console+actuator shipped; auto-close = buildable |
| **Trust** (§3.2) | banked = ground truth | `oracle.is_shipped` vs git ancestry | a claim with no commit = caught lie | refuse-to-bank; route the exception to a human | shipped + benchmarked (FleetHorizon) |
| **Improvement** (§3.3) | recurring failures become impossible | recurrence count of a failure class | a fix that re-corrects instead of mechanizing | `scout` biases focus to loop-closing work | live rung (`ClosedLoopSignal`); host measures which items close loops |
| **Completion** (§3.4) | the completion predicate holds | kernel re-checks predicate vs effect | residual > 0 / obligation unmet | surface "who owes this"; host/human finishes | size-half shipped; ledger+verb = spec (117/133) |

The columns are identical because the loops are the same control loop with
different reference/sensor pairs. **That is the doubling-down: DOS is not a bag of
distrust features — it is a feedback-control system for fleets, and each syscall is
one wire on the loop.** Read the kernel this way and the design laws fall out for
free:

- *Why advisory-only (docs/99)?* Because a controller that **actuates** must know
  what the plant *is*, and the kernel is deliberately domain-free — it must not know
  whether a process is a build, a deploy, or a payment. So DOS supplies the **error
  signal** (the sensor + comparator) and leaves the **actuation** to a host that
  knows the plant. The loop is closed *across* the kernel boundary, not inside it.
- *Why the sensor must cross a trust boundary (docs/116/117/123)?* Because feedback
  authored by the plant is not feedback — a loop whose sensor is the agent's
  self-report is open with extra steps (§2).
- *Why monotone in horizon × fanout (FleetHorizon)?* Because a closed loop only
  earns its cost when the plant is disturbed; the value is the disturbance-rejection
  the open loop cannot do, and disturbances compound with scale.
- *Why "primitives not features" (docs/79)?* Because the kernel ships the *wires*
  (small syscalls) and the *closing* (watchdog, auto-redirect, obligation-finisher)
  is the buildable space above — a host composes the loop from the parts.

---

## 5. Why this is critical to agent success — the one-paragraph version

A single agent on a single task can sometimes get away with an open loop: short
horizon, low disturbance, a human reading every output. A **fleet** cannot. The
moment you have N agents on shared state over a long horizon, the disturbances —
confabulated completions, silent collisions, recurring wedges, parked obligations —
compound faster than any human can read N walls of output, and an open-loop
orchestrator banks every one of them undetected (FleetHorizon: 35 lies, 7
overwrites, 100% of output dumped on a human, all invisible to the loop that
produced them). The only thing that scales is a **feedback path the agents cannot
author**: read the un-forgeable effect, compare it to the reference, let the error
drive the next decision. That path is what DOS *is* — `verify` closes the trust
loop, `liveness`+`scope`+the console close the control loop, `scout` closes the
improvement loop, `resume`+the obligation ledger close the completion loop. The
agents stay exactly as unreliable as they were; the *fleet* becomes reliable
because the loop around it is closed. **Parallelism is the easy half. The closed
loop is the half that makes a fleet a system instead of a gamble — and it is the
half the rest of the agent stack has largely left unbuilt.**

---

## 6. What this reframing makes obvious (the next pickups)

Naming the principle is only useful if it changes what to build next. It does:

1. **Control loop — auto-close the in-flight sensor.** The sensors (`liveness`
   Phase 2, `scope`) and the console (`dos top`) are shipped; the *automatic*
   actuation (`loop_decide.StopReason.SPINNING` consumer that self-stops a spinner;
   the docs/101 watchdog generalized) is where the control loop currently relies on
   a human standing at the console. That is the highest-leverage closing left.
2. **Completion loop — ship the obligation ledger (docs/133 Phases 2–4) and lift
   the residual into the live loop (docs/117).** These are the two open loops with
   *no controller at all* — the failure mode is silent permanence, the worst kind.
3. **Improvement loop — measure the rate.** Scout *biases* toward loop-closing work
   but nothing yet *quantifies* the payed-down rate (failures-of-class-K over time,
   before vs after a mechanism landed). A `dos` instrument that scores "did closing
   this loop actually drop the recurrence" turns §3.3 from a heuristic into a
   measured control law — the eval-harness-per-axis posture (docs/113/90) applied to
   the improvement loop.
4. **Positioning — lead with the loop, not the list.** Against "why not just run N
   agents?", the answer is not "DOS has verify and arbitrate and liveness" (a
   feature list invites a feature comparison). It is: *"those N agents are an open
   loop — you can't see or steer them mid-run; DOS is the feedback path that closes
   the loop, and a closed loop is the only thing that scales past one agent."* The
   FleetHorizon numbers are the proof, and the gap → 0 at N = 1 is the honesty.

The loop is the product. Everything else is a wire on it.
