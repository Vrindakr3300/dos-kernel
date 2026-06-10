# 260 — Writing loops vs. prompting: the loop-authoring proof

> **Status:** design + proof plan (2026-06-09). The forcing question (operator
> `/goal`): *prove how DOS helps people "write loops" for agents vs. prompting.*
> This doc isolates that claim — distinct from the trust/payoff line (docs/228+)
> and the closed-loop synthesis (docs/136) — states it as something **measurable**,
> names the trap that makes the easy version of the proof worthless, and specifies
> the one experiment whose result the operator can read off ground truth. The
> mechanism already shipped (`dos.loop_decide`, the `dos-dispatch-loop` skill); what
> is missing is the **head-to-head** that turns the docstring's asserted "mechanical
> contract over prose" into a number.

---

## 1. What the claim is — and what it is NOT

There are two ways to make an agent run *unattended* — to keep acting across many
iterations without a human in the seat between them:

- **Prompting.** You write a long natural-language instruction — "keep dispatching
  work; stop when the backlog is drained twice, or you've hit 10 iterations, or
  the subprocess keeps failing, or a rate-limit window is exhausted; when a lane
  drains, switch to replan; don't re-pick a unit you just tried…" — and you trust
  the **model** to apply that prose, *identically*, on every iteration. The loop's
  control flow lives in the model's head. The model both *does the work* and
  *decides whether to keep going.*

- **Writing a loop (DOS).** The control flow — continue / stop / which-mode-next —
  is a **pure, typed function the loop calls** (`loop_decide.decide`). The model
  gathers evidence and narrates; the **kernel** decides the transition. The thing
  that *does the work* and the thing that *decides whether to keep going* are
  split, and the deciding half is deterministic, replayable, and authored by
  someone other than the worker.

This is the same byte-author≠judged-agent invariant the whole kernel rides
(docs/138), aimed at a new target: not "did the work ship?" but **"should the loop
take another step?"** In the prompting world that decision is generation #2
narrating generation #1 (the model judging its own loop). In the DOS world it is a
function the model cannot talk its way past.

**What this claim is NOT.** It is *not* the payoff line. docs/228/232/237 measure
"does adjudicating a worker's claim beat believing it" (ΔB) and the answer there
is nuanced (≈0 at the easy single-hop, real for coordination/multi-hop/non-LLM
consumers — memory `project-dos-recovery-is-a-confound`). This doc is upstream of
that: it is about the **authoring experience and the loop's own control flow**,
not about trusting a work-claim. A prose loop can be perfectly honest about each
unit of work and *still* mis-decide whether to continue — because the stop logic
itself is the thing it is failing to apply. Keep the two apart.

---

## 2. The trap (why the obvious proof is worthless)

The tempting experiment: "ask a model the loop's stop question 100 times in prose,
count how often it gets the answer right." This is the **consistency-is-not-
grounding** trap (memory `feedback-consistency-is-not-grounding`) wearing a loop
costume. If the grader is *another model* (or the same model) reading the same
prose, you are measuring whether a model agrees with a model — re-deriving the
author's own bytes. That number is noise dressed as evidence.

It is *also* the **static-replay** trap (memory
`project-dos-out-of-loop-live-payoff`): a frozen transcript of "here is the loop
state, what's the decision?" measures a **rate** in a vacuum, not a **payoff** in a
live loop. An authoring advantage that only shows up on a corpus you hand-built is
an artifact of how you built the corpus.

So the proof must satisfy three conditions, the same three every honest DOS
experiment must (docs/206):

1. **The grader is not a model reading prose.** The correct stop-decision for any
   loop state is computable *deterministically* — `loop_decide.decide` IS that
   ground truth (it is pure, and pinned by 101 cases in
   `tests/test_oracle_and_loop.py`). So the oracle for "what should the loop have
   done here?" is a function, not an opinion. The prose loop's answer is scored
   against **the function**, never against another narration.

2. **The thing measured is a divergence from an un-forgeable reference**, not an
   agreement. We count the iterations where the prose-applied decision *differs*
   from the kernel decision on the *same state* — and, critically, the
   **cost of each divergence** (a burned launch, a missed stop, a wrong mode).

3. **The payoff is read in a live loop, not asserted from the rate.** The rate
   (condition 2) is the *detector*; the payoff is what those divergences *cost*
   when a real multi-iteration run acts on them — extra `claude -p` launches at
   \$10–40 each, or keep-alive markers at \$0.03–0.10 each (the docstring's own
   session `4b4ff97c` burned **252 markers / ~\$7.80** from *one* mis-applied
   keep-alive condition — `loop_decide.py:1645`).

---

## 3. Why prose loses — the mechanism, before the measurement

Before building anything, be precise about *where* a prose loop diverges, because
that is where the experiment must aim. `loop_decide.decide` is not "stop after N" —
it is ~7 interacting conditions with invariants a prose reader predictably drops:

| Stop/route condition | The invariant prose forgets | Failure if applied loosely |
|---|---|---|
| **DRAINED_TWICE** | a DRAIN counts as "twice" only if the *intervening* /replan was **PRODUCTIVE** (FQ-240) — an empty replan does not arm it | stops one drain too early (gives up on a refillable backlog) **or** loops forever on an unproductive replan |
| **CONSECUTIVE_UNCLEAR** | resets to 0 on any non-UNCLEAR; a parked-but-**committing** descendant (FQ-509 `ADVANCING`) is *not* a fault and must adopt-wait, not charge the breaker | self-stops over a healthy child **and** re-launches a fresh \$10–40 child each iteration |
| **SHIPPED-DIRTY-0** | a SHIPPED iter that shipped *zero* picks with a DIRTY tree is the degraded signal; any other SHIPPED resets | misreads "it said SHIPPED" as progress (the over-claim the whole kernel exists to catch) |
| **RATE_LIMITED / OVERLOADED** | rate-limit = don't retry till the window resets; 529 = retry *with backoff* — different handling | burns the remaining slots hammering a closed window |
| **wait_marker_budget** | a keep-alive marker that won't earn its cache-read cost must be **refused before it is emitted** | the 252-marker / \$7.80 bleed — a pure-overhead cost a prose instruction *cannot* enforce because it has no pre-emission hook |

The pattern: every one of these is a place where the **honest, well-meaning model
still gets it wrong**, not because it lies, but because **prose state-machines do
not compose in a context window.** The model is holding the work, the evidence, the
history, *and* a 7-condition interacting rulebook — and the rulebook is what slips.
The docstring says it plainly: "~80 steps of prose a downstream model is trusted to
apply consistently" (`loop_decide.py:52`). DOS's move is to make the rulebook a
function so the model only has to hold the work.

This is also the **fleet** point (memory
`feedback-fleet-angle-is-the-irreducible-pitch`), and it is where the claim gets
its teeth. A single prose loop that miscounts once is cheap to shrug off. But:

- **Concede the single-loop case up front.** For *one* loop, a careful prompt with
  a good model applies the stop logic correctly most of the time, and the
  divergences are recoverable. The honest expected single-loop authoring win is
  *real but modest* — fewer wrong stops, a bounded marker bill — not a knockout.
  (State this; do not oversell it. The single-agent ΔB lesson —
  `project-dos-valueadd-single-agent-deltaB-negative` — is that overselling the
  single case gets caught.)

- **Lead with the fleet.** Run **K loops at once** (the actual use — several
  `dos-dispatch-loop`s on disjoint lanes, `SKILL.md` §0). Now the per-loop
  divergence rate `d` compounds: the chance that *all K* loops decide correctly on
  a given tick is `(1−d)^K`, and a fleet is only as steerable as its worst member.
  A 5% per-loop wrong-stop rate is one-in-twenty for a single loop but
  **1 − 0.95²⁰ ≈ 64%** chance *some* loop in a fleet of 20 mis-decides each round.
  The prompting approach degrades super-linearly in fleet size; the function does
  not degrade at all (it is the same pure call K times). **That** is the
  irreducible "DOS helps you write loops" claim — not that the function is smarter
  than the model on one tick, but that it is the only approach whose correctness is
  *invariant under fan-out*. (This is the docs/245 F1/F3 compounding shape — memory
  `project-dos-fleet-scale-proof-plan` — applied to the *loop-control* decision
  instead of the work-claim.)

---

## 4. The experiment

**Name:** `loop_authoring` (proposed `benchmark/loop_authoring/`).

**Subject under test:** the loop-control decision — continue / stop(reason) /
next-mode — *not* the work.

**The two arms, on identical inputs:**

- **Arm P (prompt).** A model is given (a) the loop's rules as prose — the same
  ~80-step English a hand-written prompt-loop would carry, lifted from
  `dos-dispatch-loop/SKILL.md` + the `loop_decide` docstring — and (b) one
  iteration's evidence (the outcome kind, the gate verdict, the carried counters),
  rendered as the text a prose loop would actually see. It must answer: continue or
  stop? if continue, which mode? It carries its *own* running counters across the
  sequence in prose (as a real prompt-loop does — the state lives in context).

- **Arm D (DOS).** The same evidence is fed to `loop_decide.decide(state,
  outcome)`. The counters are carried in the typed `LoopState` the function returns.

**The reference (ground truth):** Arm D *is* the reference. `decide` is pure and
test-pinned; there is no separate oracle to disagree with it. This is the crux that
escapes the trap of §2: **we are not asking a model to grade a model.** We are
asking whether a prose-applied state machine reproduces a deterministic one — a
question with a computable answer.

**The input distribution (this is where rigor lives).** Garbage in = garbage proof.
The sequences fed to both arms must be **realistic loop trajectories**, not
hand-picked gotchas. Three sources, in order of trustworthiness:

1. **Real captured loops.** The host reference app's `dispatch-loop` runs leave
   journals; replay the actual `(state, outcome)` sequences a live loop produced.
   This is the only fully honest distribution. (Availability: the lane journals +
   headless telemetry under the `job` consumer repo; the 252-marker session
   `4b4ff97c` is one such trace.)
2. **Property-generated sequences.** Enumerate reachable `(LoopState,
   IterationOutcome)` transitions from the state machine itself and walk random
   paths — guarantees coverage of the *interacting* conditions (the DRAINED_TWICE ×
   productive-replan cross-term), which a captured log may under-sample. Honest
   because the generator is the kernel's own transition relation, not a prompt
   author's intuition about what's hard.
3. **NOT hand-authored gotchas.** Explicitly excluded as a *scoring* set (they may
   illustrate, never score). A distribution built to make prose look bad proves
   only that its author can build such a distribution (the docs/235 slice-must-
   have-power lesson — memory `project-dos-keystone-deltaB-needs-validation`).

**What is measured (the detector — a divergence, per §2.2):**

- **`d` = per-iteration divergence rate** — fraction of ticks where Arm P's
  decision ≠ Arm D's decision (wrong continue/stop, or right stop but wrong
  reason, or wrong next-mode). Broken down *by condition* (which rung prose drops
  most — the §3 table predicts DRAINED_TWICE and the marker budget).
- **Counter drift** — how far Arm P's prose-carried counters diverge from the typed
  `LoopState` over a sequence (does the miscount compound or self-correct?).

**What is measured (the payoff — a cost, per §2.3):** each divergence is priced by
its loop consequence, so the headline is dollars/launches, not a bare rate:
- a **missed stop** (P continues where D stops) → +1 wasted `claude -p` launch
  (\$10–40) and possibly a re-launched child;
- a **wrong mode** (P replans where D dispatches or vice-versa) → +1 wasted
  iteration;
- a **marker over-budget** (the condition with *no prose hook at all*) → the marker
  bill the budget would have refused (priced from the real session: \$0.03–0.10
  each; 252 → \$7.80).

**The fleet multiplier (the headline, per §3):** report `d` for a single loop, then
the compounded fleet wrong-decision probability `1−(1−d)^K` and the **expected
wasted spend** across a fleet of K loops over an H-iteration horizon —
`E[waste] ≈ K·H·d·(mean cost per divergence)`. This is the number that answers the
goal: *at fleet scale, writing the loop (calling the function) versus prompting it
(trusting the prose) saves `E[waste]`, and the saving grows with K.* Cross-check
the `(1−d)^K` shape against any available real multi-loop run, exactly as docs/256
(memory `project-dos-fleet-scale-proof-plan`) cross-checked `F^D` — a clean formula
that no live run corroborates is a model, not a measurement.

---

## 5. The honest failure modes (state them before running)

Pre-registering where this could come back ≈0, so a null result is the method
working (the `project-dos-valueadd-single-agent-deltaB-negative` discipline):

- **`d` may be small on the easy conditions.** A good model *will* get
  ITERATION_CAP and a clean DRAIN right almost always. If `d` is dominated by the
  trivial conditions, the single-loop win is genuinely modest — report it as such.
  The claim survives *only* if `d` concentrates on the interacting invariants
  (DRAINED_TWICE×productive-replan, FQ-509 adopt-wait) and on the marker budget,
  AND the fleet multiplier makes even a small `d` expensive at scale.
- **The marker budget is the cleanest, least arguable win** and may carry the
  result alone: it is a cost a prose instruction *structurally cannot* enforce
  (there is no "before you emit a keep-alive" hook in prose — the model has already
  spent the turn by the time it could "decide"). If every other condition washes
  out, "DOS lets you refuse spend prose can't even see" still stands, and it is
  backed by a real \$7.80 receipt.
- **Recovery is a confound here too** (memory `project-dos-recovery-is-a-confound`).
  A prose loop that mis-decides on tick *t* may self-correct on *t+1* (the same
  lurking variable that drove the payoff line to ≈0). So the payoff must be
  measured on the **net** waste across a full sequence, not summed per-tick
  divergences — a divergence the next tick erases costs nothing. Price the *trace*,
  not the events.
- **Distribution risk is the dominant risk.** If the captured-log source is thin
  and the result leans on property-generated sequences, say so loudly — a
  generated distribution proves the *mechanism* (prose drops these conditions) but
  understates or overstates the *rate* a real workload hits them. The strongest
  version waits for enough real journals.

---

## 6. Why this is the right artifact (and what it is not)

It is **not** a new syscall — `loop_decide` already exists and is the reference. It
is **not** strategy — it argues *how a kernel module beats the prompting
alternative and how to measure that*, which is an engineering design plan (→
`dos/docs/`, per CLAUDE.md's litmus), not a why-DOS-matters essay (→ `dos-private`).
It is the **missing head-to-head**: the docstring asserts "mechanical contract over
prose," 101 tests prove the function is *correct in isolation*, and nothing yet
shows it *beats prompting the same logic* — which is precisely the "write loops vs.
prompting" question.

The deliverable, in one line: **a benchmark that scores a prose-applied loop
state-machine against the kernel's pure `decide`, on realistic trajectories, priced
in wasted launches/markers, with the fleet-scale multiplier as the headline — graded
by a function, not a model.**

---

## 7. Build order (smallest honest first)

1. **The scorer, against generated sequences (cheap, no spend).** Implement Arm D
   (call `decide`) + the divergence/cost accounting + the `1−(1−d)^K` fleet roll-up
   over property-generated trajectories (source 2). This is pure-Python and free;
   it pins the *machinery* and the formula. Ship this first — it is the analogue of
   docs/256 building the headline figure with no live spend.
2. **Arm P on a real model, smallest slice (bounded spend).** Render the prose
   rulebook + evidence, ask a live model the decision across a short sequence,
   score against Arm D. Start at one model, one short horizon; this is where `d`
   becomes real instead of assumed. (Gate any paid batch on the operator, per the
   repo's spend discipline.)
3. **Captured-log distribution (the honest rate).** Pull real `(state, outcome)`
   sequences from the host journals (source 1) and re-run Arm P/D — this replaces
   the assumed rate with the measured one and is what lets the dollar figure be
   quoted without an asterisk.
4. **Fleet cross-check.** Marry the per-loop `d` to a real multi-loop run's
   observed wrong-decision rate, the docs/245 F-series move, to confirm the
   compounding formula is a measurement and not just algebra.

Steps 1 is buildable now and entirely free; 2–4 escalate cost and rigor in that
order. The proof is *staged*: even step 1 alone produces the headline formula and
the marker-budget argument (the structurally-unenforceable-in-prose win); each later
step removes one asterisk.
