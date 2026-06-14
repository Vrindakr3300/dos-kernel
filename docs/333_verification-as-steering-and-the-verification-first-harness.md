# 333 — Verification as steering, and the verification-first harness

> **Verification is not the last step of an agent's work; it is the steering
> wheel.** Over a long horizon the thing that decides whether an agent arrives
> anywhere is not how good each move is — it is whether something that is *not
> the agent* corrects the heading between moves. A check run only at the end
> grades a journey already over. A check run *between every move* is the control
> loop. This note builds the idea up from first principles, then draws the one
> architectural consequence that matters: **a harness designed around
> verification from the ground up is a different machine from one that bolts a
> verifier onto an existing agent loop — not a better-tuned version of it.**

This is a theory note in the family of [`102`](102_when-to-trust-an-agent.md)
(the trust law), [`117`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)
(completion is a verdict, not a budget), and
[`138`](138_what-is-truth-the-throughline.md) (truth is what the kernel can
establish without believing the agent). Those three answer *what* the kernel
verifies and *why* a verdict is trustworthy. This one answers the question
underneath the operator's: **why is verification the thing that steers a
long-horizon agent at all — and what do you have to build differently if you
take that seriously from the start?**

It carries no litmus and ships no mechanism. It is the conceptual frame; the
mechanisms it points at already ship and are cited inline.

---

## 1. The control-theory reframe: an agent is a plant, verification is feedback

Borrow the oldest idea in control. A system you want to drive somewhere has a
**plant** (the thing that acts and drifts) and a **controller** (the thing that
measures the gap to the goal and corrects). Open-loop control sets the actuator
once and hopes; closed-loop control measures the output and feeds the error back.
The entire reason closed-loop beats open-loop is that **the plant drifts, and
only a measurement the plant did not produce can catch the drift.**

An LLM agent on a long task *is* a plant. It drifts — not randomly, but in the
specific way a next-token sampler drifts: each step conditions on its own prior
output, so an early wrong assumption is not corrected by later steps, it is
*amplified* by them (every later token is sampled from a context that now treats
the wrong assumption as established fact). This is the mechanism behind the
restart livelock in [`193 §2`](193_clean-restart-seeded-with-dos-knowledge.md):
the agent invents an id it never looked up, and because the invention is now in
its own context, every subsequent step reasons *from* the invented id as though
it were real. The agent cannot self-correct because the corrupted state is
upstream of its own attention — it is reading its own past output as ground truth.

So the question "how do I steer a long-horizon agent?" is the closed-loop
question: **what is the feedback signal, and where does it come from?** And the
load-bearing word is *where*. A controller that reads the plant's own
self-estimate of its position is not closed-loop — it is open-loop wearing a
sensor costume. If the sensor is the plant, the loop is not closed.

This is the same observation [`102 §3`](102_when-to-trust-an-agent.md) makes
about reports vs. commitments and [`138`](138_what-is-truth-the-throughline.md)
makes about byte-authorship, but stated as the control law it implies:

> **The steering law.** A long-horizon agent is steerable only to the degree its
> heading is corrected, between steps, by a signal whose author is not the agent.
> The agent's own "I'm on track" is the plant reporting its own position — it
> closes no loop. Verification *is* that external signal. It is not a quality
> gate at the end; it is the feedback term in the controller, and a horizon is
> exactly as long as the feedback is honest.

Everything else in this note is a consequence of taking that sentence literally.

---

## 2. Why the horizon is the thing that breaks — the compounding argument

Single-step agents barely need this. Ask a model to write one function and check
the function: the report ("done") and the artifact (the function) are inspected
together, by a human, in one glance. The report's dishonesty has nowhere to hide
and nowhere to compound. Verification is *nice* here but not *load-bearing* —
which is exactly why most harnesses bolt it on as an afterthought and get away
with it on short tasks.

The horizon is what changes the regime. Three things compound as steps accumulate,
and each one is a different reason the end-check fails:

- **Error compounds multiplicatively.** If each step is independently correct
  with probability *p*, an *n*-step chain is correct with probability *pⁿ*. At
  *p* = 0.95 a 100-step task is correct ~0.6% of the time. You do not fix a *pⁿ*
  curve by raising *p* a little; you fix it by *resetting the exponent* — catching
  and correcting error *per step* so the chain is a sequence of short chains, each
  re-grounded, rather than one long one. That per-step re-grounding is the
  feedback term of §1. **The whole value of verification scales with the horizon**
  precisely because the failure it prevents is the one that scales with the
  horizon.

- **The cheapest lie gets cheaper to tell and more expensive to catch.** A
  self-report at step 3 that goes unchecked is read as fact by steps 4…100. By
  step 100 the lie is not one sentence — it is the foundation a hundred steps
  were built on, and the end-check now has to *unwind* a hundred steps to find
  it. [`117 §1`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)
  names the two failure modes that hide under "the job never finishes" — can't
  stop (no fixpoint) and stops-too-early (false completion) — and observes they
  *compound*, because the agent has no external account of either. The reason they
  compound is the reason §1 gives: nothing external corrected the heading, so the
  error rode forward.

- **"Done" is the maximally-tempting report at exactly the wrong moment.**
  [`102 §3.1`](102_when-to-trust-an-agent.md)'s commit-vs-report asymmetry is
  sharpest at the end of a long run: the agent has spent its budget, "done" is the
  rewarded answer, and it is now optimizing the *report* against whatever it
  learned the checker wants. An end-of-run check is the single most-gamed signal
  in the stack, evaluated at the single most-tempting moment. You could hardly
  design a worse place to put your only verification.

The synthesis: **on a long horizon, the end-check is both too late (the error has
compounded) and most-gamed (it lands at peak temptation).** The fix is not a
better end-check. It is to *move verification off the end and into the loop* — to
make it the per-step feedback term, so no error rides more than one step before
something that is not the agent corrects the heading. This is why
[`117`](117_completion-as-a-verdict-the-end-of-working-in-passes.md) is titled
"the end of working in passes": a *pass* is open-loop (act until budget, then
report); a verification-steered loop is closed-loop (act, verify, re-dispatch the
residual, repeat until the residual is empty against ground truth). The difference
is not effort. It is whether the loop is closed.

---

## 3. What "steering" requires that a final verifier does not provide

Calling verification "the feedback term" raises the bar on what the verification
has to be. A final pass/fail grade is a scalar at the end. A *steering* signal
has to do four things a grade does not, and each one is a property the DOS
verdict surface already has — which is the tell that the kernel was, all along,
building a controller and not a grader.

1. **It must be available between steps, not only at the end.** A verdict you can
   only compute on a dead run is the morgue, not the loop. This is exactly the
   gap [`117 §2(c)`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)
   names: the completion oracle *was already written*, trapped inside the
   crash-recovery framing (`resume_plan`'s `residual = declared − verified`), and
   the whole plan is to lift it onto the *live* loop. The arithmetic was identical;
   the only change was *when* you run it. That "when" is the entire difference
   between a post-mortem and a steering wheel.

2. **It must say which way to turn, not just whether you arrived.** A grade is a
   bit. A heading correction is a *vector* — and the kernel's verdicts are
   structured exactly so they carry one. `INCOMPLETE` does not just say "not done";
   it carries *the residual*, so the loop re-dispatches the unfinished set and not
   a fresh pass
   ([`117 §5.4`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)).
   `SCOPE_CREEP` / `WRONG_TARGET` do not just say "bad"; they say *which file the
   diff escaped into*. A refusal is not "no"; it is a token from a closed
   vocabulary that names the *cause*
   ([`182`](182_the-kernel-is-a-taxonomy-of-refusal.md)). The verdict is the
   error term *and* its sign — the thing a controller actually needs.

3. **It must distinguish "off course" from "off course and will never converge."**
   A controller that corrects a thrashing plant forever is itself a failure mode.
   This is the convergence verdict of
   [`117 §5.2`](117_completion-as-a-verdict-the-end-of-working-in-passes.md):
   `CONVERGING` (the residual is shrinking — keep steering) vs. `THRASHING` (the
   residual oscillates — the loop has no fixpoint; stop steering and surface a
   decision). A steering signal that could not say "this will not converge" would
   drive a fleet into the wall at full budget. The honest controller knows when to
   take its hands off the wheel and call a human — which is the actuation boundary
   ([`99`](99_runtime-validation-and-the-actuation-boundary.md)) seen from the
   steering side.

4. **It must be honest about where it cannot see.** A sensor that fabricates a
   reading when blind is worse than no sensor. The kernel's `ABSTAIN` /
   `INDETERMINATE` / `none`-source verdicts are the controller saying "I have no
   honest measurement here" rather than inventing one
   ([`138`](138_what-is-truth-the-throughline.md)'s bottom rung, routed to a
   human). A steering loop built on a sensor that lies-when-blind would correct
   *toward* the blindness. The verdict surface's whole grading apparatus — `source=`
   carried as data, the forgeability ladder — exists so the controller knows the
   *confidence* of each correction, not just its direction.

The point of the list: **a steering signal is a richer object than a grade**, and
the difference is not polish. A grader can be a function `work → {pass, fail}`. A
controller needs `state → (error_vector, confidence, converging?, can_I_see?)`. If
you build the verifier as a grader and later wish it were a controller, you
discover the grader threw away exactly the structure the controller needed. Which
is the bridge to the real claim.

---

## 4. The architectural fork: foundation vs. bolt-on

Now the operator's second axis — *building a long-horizon harness from the ground
up, not bolting verification onto an existing one.* The two are not the same
machine with the verifier in a different place. They are different machines,
because **the question "what is true here?" has to be answerable at the layer
where steering happens, and that layer is decided at the foundation or not at
all.**

### 4.1 What a bolt-on actually is

A bolt-on harness is one where the agent loop was designed first — act, observe,
act, observe, terminate on budget — and a verifier is added at the seams that
loop happens to expose. Those seams are almost always two: the *tool-call return*
(did this one call succeed?) and the *end of the run* (does the final output look
right?). A bolt-on verifier lives at one or both. And it inherits, structurally,
three limits it cannot engineer its way out of:

- **It reads what the loop chose to expose, which is the agent's own narration.**
  The loop was built to pass the agent's outputs forward; the verifier sees those
  outputs. So the bolt-on verifier is reading a self-report — it closes no loop in
  the §1 sense, no matter how clever it is, because the *only thing it has access
  to* is generation #2 narrating generation #1
  ([`138`](138_what-is-truth-the-throughline.md)'s one invariant). To read an
  *un-authored effect* — the git diff's footprint, the OS exit code, the lease
  journal — the verifier needs a channel to ground truth the agent does not
  mediate, and a bolt-on, by construction, does not have one: the loop was not
  built to carry it.

- **It has no notion of the work's *extent*, so it cannot compute a residual.**
  The end-check asks "does the output look done?" It cannot ask "is the residual
  empty?" because *residual = declared − verified* requires a durable, distrusted
  record of what was declared at the start
  ([`117 §2(b)`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)'s
  intent ledger, `declared` and `verified` kept deliberately apart). A loop that
  was not built to record declared-extent up front has nothing to subtract
  verified-progress *from* — so its only available stop condition is budget. The
  pass is not a choice the bolt-on made; it is the only thing its architecture can
  express.

- **Its corrections are not serialized against shared state.** The moment more
  than one agent steers concurrently, "correct the heading" includes "do not
  overwrite the other agent's heading." That is an admission decision over a
  region-lock ([`89`](89_the-lane-is-a-region-lock.md),
  [`102 §5`](102_when-to-trust-an-agent.md)'s un-clobber point), and it has to
  happen *before the write*, at a layer the agent loop does not own. A bolt-on
  added at the tool-return seam is already too late: the write is the tool call it
  is observing. You cannot bolt prevention onto a loop whose seams are all
  post-effect.

None of these is a tuning problem. Each is a place where the information the
controller needs (un-authored ground truth; declared extent; pre-effect
admission) had to be *threaded through the architecture from the start*, and a
loop designed without it has no seam to thread it through later. **A bolt-on
verifier is structurally a grader, because the only signals its host loop exposes
are gradeable, not steerable.**

### 4.2 What "verification-first" inverts

Build the harness the other way and the inversion is total: **the loop is not the
thing the verifier observes; the verifier is the thing the loop is built around.**
The control loop is primary, and the agent is the plant *inside* it. Concretely,
four things move from "added later, where it fits" to "decided first, at the
foundation":

- **Ground truth is a first-class input channel, not a thing scraped from
  narration.** The harness is built to read the un-authored effect directly — git
  ancestry, the diff footprint, the OS exit code, the lease WAL, a third-party
  attestation ([`138`](138_what-is-truth-the-throughline.md)'s evidence ladder;
  [`109`](109_non-git-evidence-in-the-verify-verdict.md)'s non-git rungs). The
  agent's narration is *also* read, but demoted at the door to a hint that must
  clear a non-forgeable checkpoint. This is the difference between a sensor wired
  to the plant's output and a sensor wired to the plant's *self-estimate*. You
  decide which one you have at design time; you cannot rewire it later without
  rebuilding the loop.

- **The unit of work carries its own completion predicate.** Every dispatch
  declares its extent up front, into a distrusted ledger, so *residual* is
  computable at every step and the loop's termination condition is "residual empty
  against ground truth," not "budget spent"
  ([`117`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)). The plan
  is not documentation; it is the *committed predicate the work is steered
  toward* ([`102 §3.2`](102_when-to-trust-an-agent.md)'s
  conformance-not-correctness move). A verification-first harness is, in one
  sentence, *a conformance engine over commitments the agent made before it could
  game the check* — and that engine has to be the skeleton, because the commitment
  has to be recorded before the first step or it is just another post-hoc report.

- **Admission is a pre-effect gate, because steering concurrent plants means
  serializing their effects.** The region-lock (`arbitrate` over the lease
  journal, the scope gate at the edit boundary —
  [`102 §5`](102_when-to-trust-an-agent.md)'s shipped pre-effect enforcement) sits
  *before* the write, where prevention is possible, not after, where only
  detection is. A foundation-built harness puts the write chokepoint through the
  verdict; a bolt-on cannot, because its only chokepoints are the seams of a loop
  that already wrote.

- **The verdict is structured for steering, not grading — from the first type
  defined.** Verdicts carry the residual, the escaped file, the refusal cause, the
  convergence trend, and the forgeability grade of their own evidence (§3). These
  are the controller's error-vector-and-confidence. A grader designed first would
  have typed its output as a bit and thrown the structure away; you cannot
  retrofit a vector onto a bit.

### 4.3 The one-line statement of the fork

> **Bolt-on:** an agent loop, with a verifier reading the narration it happens to
> expose. The verifier is a grader because the loop's seams are post-effect and
> self-authored. Its native stop condition is *budget*; its native verdict is a
> *bit*; its native failure is *silent compounding*.
>
> **Foundation:** a control loop, with the agent as the plant inside it. Ground
> truth, declared extent, and pre-effect admission are threaded through from the
> first type. Its native stop condition is *residual-empty-against-ground-truth*;
> its native verdict is an *error vector with a confidence grade*; its native
> failure is a *surfaced decision*, because the controller knows when it has gone
> blind or stopped converging.

The reason this is a fork and not a spectrum: the three things the controller
needs (§4.1) are all *architecture-time* decisions — what channels exist, what
gets recorded before step one, where the write chokepoint is. You either built
the loop to carry them or you did not. **A harness does not gradually become
verification-first by adding more verifiers. It is verification-first or it is a
loop with verifiers stapled to its exhaust.**

---

## 5. The honest limits — what verification-as-steering does *not* buy

A note that only stated the thesis would be a self-report
([`102 §5`](102_when-to-trust-an-agent.md) set this honesty bar). The steering law
has the same holes the truth surface has
([`138 §"Where truth is still forgeable"`](138_what-is-truth-the-throughline.md)),
re-aimed:

- **A controller cannot steer toward correctness — only toward conformance.** The
  feedback term measures "does the artifact conform to its commitment," never "is
  the artifact *good*" — Rice's theorem forecloses the latter for any mechanical
  oracle ([`102 §3.2`](102_when-to-trust-an-agent.md),
  [`183`](183_how-much-does-this-lean-on-git.md)). Steering keeps the agent *on
  the declared course*; whether the course was *worth steering* is a judge's or a
  human's call. The horizon you can hold is the horizon of *conformance*, and the
  semantic correctness of the destination rides on the quality of the
  commitment — which is why the plan being a real pre-commitment (§4.2) is
  load-bearing, not bureaucratic.

- **The cheap lie is priced up, not abolished.** A `--allow-empty` commit on the
  right SHA still satisfies the forgeable grep-subject rung
  ([`138 §"Where truth is still forgeable"`](138_what-is-truth-the-throughline.md)).
  Verification-as-steering raises the forgery cost from "a sentence" to "a
  reachable artifact of the right shape" — strictly stronger than believing a
  report, hardenable rung-by-rung
  ([`85`](85_extending-the-verifiable-surface.md)), but not unforgeable. The
  controller's sensor has a noise floor, and the honest move is to *grade* the
  reading (`source=`), not to pretend it is clean.

- **The loop is advisory; it decides, it does not enact.** DOS is a PDP with no
  PEP ([`138`](138_what-is-truth-the-throughline.md),
  [`99`](99_runtime-validation-and-the-actuation-boundary.md)). The steering signal
  is computed honestly; *acting* on it — stopping the run, re-dispatching, killing
  the spinner — is the host's. A verification-first harness produces the
  correction; the actuation boundary decides who is allowed to turn the wheel, and
  the conservative default routes the irreversible turn to a human. This is a
  feature (a wrong auto-correction is contained), but it means "verification
  steers" is precise: it *computes the heading*; the controller still has to be
  wired to act on it, and that wiring is the host's responsibility and risk.

- **A co-resident verifier can be steering by the plant's own hand.** If the
  signal that corrects the agent is generated by the *same weights on the same
  box* ([`123`](132_what-the-operator-may-resolve-the-authority-floor-of-an-untrusted-driver.md)
  / the locality point in [`138`](138_what-is-truth-the-throughline.md)), the loop
  is closed back onto the plant and §1's law is violated silently. Locality is a
  trust coordinate the harness must track, not assume away — and a foundation-built
  harness can make it a first-class fact, where a bolt-on inherits whatever box the
  agent already runs on.

These limits do not weaken the thesis; they *locate* it. Verification-as-steering
is the controller for the cell [`102 §6.4`](102_when-to-trust-an-agent.md) named:
*an un-authored artifact exists × mis-trust is silent or irreversible.* That is
exactly the cell where a long horizon turns a small per-step error into a silent
catastrophe, and exactly the cell where reading the plant's own narration closes
no loop. On that cell — and honestly conceding the rest — verification is not a
check you run. It is the steering wheel, and a harness that does not put it at the
center is open-loop on the axis that matters most as the horizon grows.

---

## 6. The synthesis (one paragraph)

A long-horizon agent is a plant that drifts by reading its own past output as
ground truth, so it is steerable only by a feedback signal whose author is not the
agent — and that signal is verification, run *between* steps, not as a grade at
the end. The horizon is precisely the regime where this stops being optional:
error compounds multiplicatively (*pⁿ*), the unchecked self-report becomes the
foundation later steps build on, and "done" lands at peak temptation — so an
end-check is both too late and most-gamed, and the only fix is to move
verification off the end and into the loop as the per-step heading correction.
That correction must be a richer object than a grade — it must carry the residual
(which way to turn), distinguish converging from thrashing (when to stop turning),
and grade its own confidence (when it has gone blind) — which is why the kernel's
verdicts were structured as error-vectors-with-confidence all along. And that is
the fork: a harness that *bolts* a verifier onto an existing agent loop inherits
only the loop's post-effect, self-authored seams, so its verifier is structurally
a grader, its stop condition is budget, and its failure is silent compounding;
whereas a harness built *verification-first* threads un-authored ground truth,
declared-extent, and pre-effect admission through from the first type, so its stop
condition is residual-empty-against-ground-truth, its verdict is a steering vector,
and its failure is a surfaced decision. The two are not the same machine tuned
differently — they are open-loop and closed-loop, and on a long horizon that is
the only distinction that survives.

---

## 7. See also

- [`102_when-to-trust-an-agent.md`](102_when-to-trust-an-agent.md) — the trust law
  (structure / prior commitments / cheap-yes); §3's commit-vs-report asymmetry is
  this note's §2, and §6.4's named cell is this note's §5 boundary.
- [`117_completion-as-a-verdict-the-end-of-working-in-passes.md`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)
  — completion is a verdict, not a budget; the *pass* this note calls open-loop and
  the residual/convergence verdicts it calls the steering vector.
- [`138_what-is-truth-the-throughline.md`](138_what-is-truth-the-throughline.md) —
  the evidence ladder and the one invariant (byte-author ≠ judged agent) that §1's
  steering law restates as a control law.
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
  — a refusal carries its cause; the closed vocabulary that makes the correction a
  vector, not a bit (§3.2).
- [`89_the-lane-is-a-region-lock.md`](89_the-lane-is-a-region-lock.md) /
  [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md)
  — pre-effect admission (§4.1's third limit) and the actuation boundary (§5's
  advisory floor).
- [`193_clean-restart-seeded-with-dos-knowledge.md`](193_clean-restart-seeded-with-dos-knowledge.md)
  — the upstream-omission livelock: the concrete mechanism of §1's "the plant reads
  its own output as ground truth."
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md)
  — git is necessary, not sufficient; the conformance-not-correctness ceiling of §5.
