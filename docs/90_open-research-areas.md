# Open research areas — where the kernel's mechanism is a deliberate stand-in

> **Most of the kernel is *done* in the sense that matters: the verdicts are
> sound, the ABI is small, the tests are green. But several syscalls ship a
> deliberately *thin* mechanism — a greedy walk, an empirically-picked threshold,
> a conservative over-approximation — that stands in for a harder problem whose
> right answer is genuinely not known. Those thin spots are not bugs and not
> roadmap items. They are *open research areas*, and naming them sharply is how a
> contributor (or a paper) finds the unclaimed ground.**

This is a sequel to [`89_the-lane-is-a-region-lock.md`](89_the-lane-is-a-region-lock.md)
(which named the *primitive* under the lane) and a companion to
[`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md)
(which named where to *extend verification*). It carries no litmus and is not in
the [`next-stage-plan`](next-stage-plan.md) table.

**The distinction this note turns on — research area ≠ roadmap item:**

> A **roadmap item** is work whose answer is known; only the doing remains (port
> DTOP, ship ADM, add a second driver). The [next-stage-plan](next-stage-plan.md)
> tracks those.
>
> A **research area** is a place where the *current mechanism is a known
> simplification of a problem whose optimum is open* — where you could write a
> measurably-better one but nobody knows the best shape yet, and the kernel
> deliberately shipped the simple correct version first.

Each area below names: **what the kernel does now** (with the file), **the open
question**, **the shape an answer takes**, and — the non-negotiable — **the
soundness floor a better answer may not break**. The soundness floor is the point:
these are all *precision/optimality* problems sitting on top of an already-correct
*soundness* guarantee. You may make the kernel smarter; you may not make it lie.

---

## 1. The predicate-conflict test — precision of an over-approximation

> **Scoping note (2026-06-03):** [`102 §5`](102_when-to-trust-an-agent.md)'s
> *enforcement* half — the binding pre-effect scope gate that refuses an
> out-of-tree write *before* it lands — shipped as `dos.scope.gate` / `dos
> scope-gate`. That gate enforces the **already-declared** tree; the open research
> below (§1 precision + §2 threshold) is the *prediction* half — deciding what the
> tree *should* be and how tightly to compare two of them. The gate made the
> declared tree binding; this section is still "make the declared tree *precise*."

**Now.** Two claims conflict iff their path-prefixes nest (`_tree.prefixes_collide`,
`_tree.py:41`). This is a *conservative over-approximation* of the real question
("can these two work-units touch the same byte?"): the normalizer truncates a glob
at its first `*` (`norm_tree_prefix`), so it discards both the post-`*` suffix and
the fact that a `*` does not cross a `/`. The concrete false conflict (verified
against the live code): a claim on `agents/apply_*.py` — files *directly* in
`agents/` — is refused against a lease on `agents/apply_steps/helper.py`, because
both truncate to the prefix `agents/apply_`, even though the glob `apply_*.py` does
not match the nested path. The over-approximation refuses a genuinely-disjoint
pair. It is conservative on purpose, because general predicate-satisfiability is
undecidable and prefix-nesting is the cheap decidable lower bound
([`89`](89_the-lane-is-a-region-lock.md) §3, and [`92`](92_predicate-precision-plan.md)
which specs the fix). (Note: a pair of *literal* paths like `src/foo.py` vs
`src/foo_helpers.py` is already correctly disjoint — they don't truncate, so they
don't nest; the imprecision is specifically a *glob-truncation* artifact.)

**Open question.** *What is the precision/cost frontier of a decidable
claim-conflict predicate?* Path-prefix is the cheapest point on it. Richer points:
true glob-set intersection (not prefix approximation); directory-vs-file
granularity; **symbol-level** conflict (two claims that edit the same file but
disjoint functions/AST nodes are arguably non-conflicting — the unit of contention
may be finer than a file); or a *learned* conflict predictor trained on historical
merge outcomes (did these two trees, when run concurrently, actually produce a
merge conflict?). The capability-lattice generalization
is this question over a
*non-path* resource algebra — same primitive, new predicate.

**Answer shape.** A new `prefixes_collide`-grade pure function (drop-in at the one
seam every collision check routes through), benchmarked on a corpus of real
concurrent-edit pairs by two numbers: **false-conflict rate** (safe pairs refused)
and **cost** (it must stay cheap enough to run in the admission hot path).

**Soundness floor.** *Never admit a true conflict.* A more precise predicate may
only *remove* false refusals; if it ever admits a pair that can corrupt shared
state, it has broken the arbiter. Precision is the open axis; soundness is fixed.

---

## 2. The soft-overlap threshold — a calibrated elbow, not a derivation

**Now.** When two trees *partially* overlap, admit iff the shared fraction is
≤ ⅓ (`OVERLAP_RATIO_MAX = 1/3`, `lane_overlap.py`). That constant was read off
**two observed data points** — a narrow keyword lane that should admit (31%) and a
code-sharing lane that should refuse (40%) — and picked as a clean fraction
between them (`lane_overlap.py:27`). It is honest engineering, not a theory.

**Open question.** *Is a fixed ratio even the right functional form for a
lock-compatibility tolerance?* Candidates: size-weighted (overlapping a 2-file
claim is not the same as overlapping a 200-file one); **risk-weighted** by
`P(conflict) × detonation-cost` (the [`85`](85_extending-the-verifiable-surface.md)
§ "risk-weight by P×detonation" idea, applied to admission rather than
verification); or a threshold *learned and recalibrated* from whether past
soft-admits actually detonated. The ⅓ is a scalar where the right object may be a
function of (overlap, blast-radius, historical-conflict-rate).

**Answer shape.** Replace the scalar compare in `overlap_verdict` with a policy
object (the same "mechanism is kernel, thresholds are config" split `liveness`
already uses for its windows) — and a study that backtests candidate compatibility
functions against a labeled corpus of concurrent runs, scored on detonations
*missed* vs safe concurrency *forgone*.

**Soundness floor.** This one has no hard soundness floor (soft-overlap is already
a deliberate loosening), but it has an **economic** one: a looser threshold that
raises throughput must be paid for at the *loaded* merge-conflict cost
([`81`](81_velocity-economics-and-the-fleet-benchmark.md)), not the raw one — the
right metric is verified-velocity-per-$, never admit-rate.

---

## 3. Auto-pick — greedy first-fit vs an online-scheduling optimum

**Now.** A bare (lane-less) request walks a fixed priority ladder and takes the
**first** lane whose tree is disjoint from every live lease (`arbiter.py:386`).
First-fit, order-dependent, no lookahead, no fairness: it can hand out a lane that
blocks two *future* high-value lanes, and a low-priority lane can starve
indefinitely behind busier siblings.

**Open question.** *Auto-pick is an online scheduling / interval-packing problem —
what is its competitive ratio, and what is the right objective?* The classic
theory (online interval scheduling, list scheduling, makespan minimization) gives
the frame, but the *objective* is the novel part: not throughput but
**verified-throughput-per-$** ([`81`](81_velocity-economics-and-the-fleet-benchmark.md)).
Sub-questions with known-theory anchors: starvation/fairness bounds (does any
free-with-work lane wait unboundedly?); lookahead value (does picking the
*lower-conflict* lane now raise total verified yield?); the gap between this online
greedy and an offline optimum that saw the whole plan queue.

**Answer shape.** The picker is *already* a pluggable boundary — `pick_oracle` is
injected, resolved by the caller, never inside the pure arbiter
(`arbiter.py:223`). A value-aware picker is a richer oracle (rank free lanes by
expected verified-yield, not first-disjoint-wins), measured in
`benchmark/fleet_horizon` against the greedy baseline on the per-$ headline.

**Soundness floor.** A smarter picker may reorder or rank *only among lanes the
disjointness gate already admits*. It may never admit a conflicting lane to chase
yield — optimization rides on top of the safety verdict, never around it (the same
rule as §1).

---

## 4. Lease theory — the kernel's stateless arbiter vs the lifecycle it doesn't own

**Now.** The arbiter is *pure and stateless*: it decides admission from the leases
passed in and returns; it owns no expiry, no scavenge, no queue (`arbiter.py`).
The **lifecycle** lives elsewhere and is deliberately *split*: TTL + heartbeat +
scavenge-as-a-journal-op in `lane_journal.py`, but the *heavy lease core* (when to
scavenge, how renewal races, the live registry mutation) is **not yet ported** and
still lives host-side in `job`'s `fanout_state.py` (`CLAUDE.md`: "What is NOT yet
ported"). A refused request simply *leaves* — `arbitrate` returns `refuse`; there
is no "wait in line."

**Open questions — three, and the first is a boundary question, not just a
theory one:**

- **What should the kernel own?** Is the lease *lifecycle* (expiry/scavenge/renew)
  kernel mechanism or host policy? Today it is split for historical reasons, not
  principled ones. Drawing that line cleanly is itself the research.
- **Should refusal queue?** Right now refusal is terminal. If refused requests
  *queued*, admission becomes a fairness/priority problem (FIFO? priority? priority
  *inheritance* so a high-value lane blocked behind a cheap one can lift it?) — the
  whole lock-manager literature opens up, because [`89`](89_the-lane-is-a-region-lock.md)
  says the arbiter *is* a lock manager and lock managers have wait queues.
- **Deadlock / wait-for.** With queues + multi-resource claims (the capability
  lattice, §1), classic deadlock (A holds x waits y, B holds y waits x) becomes
  reachable. A wait-for graph + detection/avoidance is unbuilt because the current
  no-queue arbiter can't deadlock — but the lattice will need it.
- **Cross-host.** The journal is host-local by design (`lane_journal.py:34`,
  cross-host is a stated non-goal). A fleet spanning machines has no shared lease
  truth. *Whether* and *how* to make leases cross-host (a merge protocol over the
  per-host journals; a consensus layer) is open and explicitly unclaimed.

**Answer shape.** Likely a new pure verdict in the `classify(Evidence, Policy)`
family ([`86`](86_the-typed-verdict-surface.md)) — a lease-lifecycle verdict
("expire / renew / scavenge / hold") gathered-at-the-boundary like `liveness`, plus
a queue policy object. The cross-host piece is a separate protocol question, not a
verdict.

**Soundness floor.** *At most one holder of any conflicting region at any time* —
the mutual-exclusion invariant. Queues, renewal, scavenge, and cross-host merge may
reorder and reclaim, but two live leases on overlapping trees is the one thing none
of them may ever produce.

---

## 5. Liveness thresholds + the act-on-SPINNING control problem

**Now.** SPINNING/STALLED/ADVANCING is decided by two windows — 15-minute
heartbeat-freshness, 30-minute grace-before-accusation (`liveness.py:116`) — that
are **generic guesses**, and the verdict is strictly **advisory**: it reports,
never kills a process or refuses a lease (`liveness.py:53`). Phase 3 (loop
self-stop + a `[liveness]` policy) is unbuilt.

**Open question.** *What is the ROC curve of "stuck" detection, and what is the
cost of acting on it?* The windows are a detection threshold; the
[trajectory/distillation work](84_ground-truth-trajectories-for-training.md) already
found a hard floor here — pure lies are learnable from trajectory shape but FLAKES
are not, only git separates them, an *irreducibility boundary*. The control
question is the unbuilt half: if a consumer **acts** on SPINNING (kills/replans a
run), what is the false-positive cost of stopping an agent that was slow-but-
actually-thinking? That is a detection-threshold / control-theory problem with a
real asymmetric loss (a killed-good-run vs a tolerated-spin), and the right window
is the one that minimizes *loaded* loss, not raw misclassification.

**Answer shape.** Per-workspace `[liveness]` windows (the config seam is already
designed, `liveness.py:96`) tuned against a labeled trajectory corpus; and an
opt-in `LivenessPredicate` over ADM's conjunctive seam (floated at `liveness.py:56`)
for hosts that *do* want to act, kept a separate driver policy from the verdict.

**Soundness floor.** Liveness stays in the **distrust-state, never
distrust-judgment** lane (`liveness.py:40`): it may report that bytes did/didn't
*move*, never whether they moved *well*. Acting-on-spin is a host policy bolted
*above* the verdict; the kernel verb may never become a quality judgment.

---

## 6. The unifying one — value-aware admission, or: the objective function is unclaimed

**Now.** Every mechanism above is safety-only or first-fit: the arbiter admits *if
disjoint*, the picker takes the *first* free lane, the thresholds are *static*.
Nothing in the kernel optimizes against a value signal. Yet the value signal exists
and is defined — **verified-velocity-per-$** ([`81`](81_velocity-economics-and-the-fleet-benchmark.md)),
risk-weighted by `P × detonation` ([`85`](85_extending-the-verifiable-surface.md)).

**Open question.** *Should admission be value-aware at all — and if so, where does
the value live without corrupting the kernel's domain-freedom?* §1–§5 are facets of
one question: rank-by-expected-verified-yield instead of pick-first / admit-if-safe.
The hard part is the layering: a value-ranking that names a *domain's* notion of
value would violate [`76`](76_flexible-goals-and-verification.md) (flexibility lives
in provenance and which-signals, *never* the adjudication). So the research is as
much *where the objective may live* (a driver-supplied yield oracle? a config-
declared cost model?) as *what the objective is*.

**Answer shape.** Almost certainly: the *mechanism* stays value-blind (admit-if-
disjoint is forever the kernel's floor), and value enters only through the existing
injected boundaries — a richer `pick_oracle`, a `[liveness]`/`[admission]` policy, a
driver yield-estimator — measured end-to-end in `benchmark/fleet_horizon`. If the
objective ever needs to live *inside* a verdict, that is the signal it has become a
new typed verdict on the registry ([`86`](86_the-typed-verdict-surface.md)), not a
change to `arbitrate`.

**Soundness floor.** The kernel's verdicts stay domain-free and safety-first; value
is *always* a driver/config/oracle concern layered on top. The day the arbiter
hard-codes someone's notion of "valuable," it has stopped being a substrate
([`79`](79_primitives-not-features.md)).

---

## Priority — where the leverage is

Ordered by *leverage per unit of research risk*, not by difficulty:

1. **§3 auto-pick (value-aware picker).** Highest leverage, lowest risk: the
   `pick_oracle` boundary already exists, the benchmark already measures the
   headline, and the soundness floor is automatic (it only ranks already-admitted
   lanes). A better picker is shippable *without touching the safety core*.
2. **§1 predicate precision.** Deepest and most reusable (it is also the
   capability-lattice): one better pure function lifts every collision check.
   Higher risk (the soundness floor is sharp), so it wants the adversarial
   treatment.
3. **§5 liveness act-on-spin.** The config seam and the verdict already ship; the
   open part is the control threshold and the opt-in predicate — a contained study.
4. **§2 threshold calibration.** Tractable and self-contained, but lower leverage
   until there is a labeled detonation corpus to calibrate against.
5. **§4 lease theory** and **§6 value-aware admission** are the *deep* ones — they
   reshape the arbiter's contract and want a design note of their own before code.
   Name them now; build them last (the ADM-ships-last instinct, applied to
   research).

The through-line, and the one rule that makes all six safe to pursue: **every one
is a precision/optimality problem layered on a soundness guarantee that does not
move.** That is the same discipline as the rest of the kernel — make the *no* legible
and correct first, then let everything cleverer get built in the layer above it.

---

## See also

- [`89_the-lane-is-a-region-lock.md`](89_the-lane-is-a-region-lock.md) — names the
  primitive (§1, §3, §4 are all "the region-lock, done better").
- [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md)
  — the verification-side companion (deeper-rung / new-oracle / new-verb; risk-
  weighting feeds §2 and §6).
- [`81_velocity-economics-and-the-fleet-benchmark.md`](81_velocity-economics-and-the-fleet-benchmark.md)
  — the objective function (`verified-velocity-per-$`) §3 and §6 optimize toward,
  and the harness that measures it.
- [`84_ground-truth-trajectories-for-training.md`](84_ground-truth-trajectories-for-training.md)
  — the irreducibility boundary behind §5 (lies vs flakes).
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) —
  the law that constrains where §6's objective may live (never the adjudication).
- [`102_when-to-trust-an-agent.md`](102_when-to-trust-an-agent.md) — the trust frame
  that *ranks* these areas: §5 here (liveness ROC/threshold) is its §6.3 (tiered
  actuation); §1–§2 here (predicate precision + the ⅓ threshold) are the build behind
  its §5 (make the declared scope a *binding* pre-commitment). Read 102 for *why* each
  thin spot is where it is on the detectable×reversible map.
