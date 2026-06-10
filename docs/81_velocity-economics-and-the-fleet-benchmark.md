# Velocity economics — the second axis of fleet effectiveness, and the benchmark category it defines

> **Catching the lie is integrity. Not paying for the lie downstream is velocity.
> They are different measurements, and DOS moves both.**

[`benchmark/fleet_horizon/`](../benchmark/fleet_horizon/README.md) already measures
the **integrity** axis: run a fleet of long-horizon agents on one shared repo
*believing* their self-reports (open loop) vs *adjudicating* them with the real
kernel (closed loop), and report the delta in **lie-rate**, **silent-overwrites**,
**wasted spend**, and **verified-shipped-per-dollar**.

This note adds — and the harness now implements (§4) — the axis that benchmark could
not see before, the one an operator actually feels: **the economics of collaborative
development velocity.** The claim under it:

> The expensive part of a fleet is not that an agent occasionally lies. It is that
> a believed lie, a silent clobber, and a "done" that has to wait in a human
> review queue each **detonate downstream** as merge-conflict resolution, re-review,
> and blocked dependents — and *that* cost, not the catch itself, is what a
> non-believing, work-adjudicating kernel removes.

There are four data points here, each with a theory anchor, each a measurable
metric, and together they define a benchmark **category** distinct from
SWE-bench-style single-patch scoring — the "harness benchmark" the agentic-coding
field is converging toward (Harness-Bench, arXiv:2605.27922) but has not pinned to a
verified-velocity headline.

**The real-world anchor this whole note exists to explain.** One striking signal in
the field right now is a *paradox*: a production telemetry study of 10,000+
developers (Faros AI, *The AI Productivity Paradox*, 2026 — vendor telemetry, large N,
not peer-reviewed) found that high-AI-adoption teams **merged +98% more PRs and
completed +21% more tasks, while PR review time rose +91%, PR size grew +154%, and
company-level throughput did not move.** Generation got cheap; the human review step
did not — so the gains were *absorbed at review*. That is the velocity problem in one
data point: a fleet that writes twice as fast delivers the same amount, because
everything it writes still has to clear a human queue that did not get faster. The
four data points below are the mechanism behind that paradox, and DOS's lever against
each.

This is a **design note + a benchmark spec**, not a phased plan; it carries no
litmus and is not in the `next-stage-plan` table. It says what the velocity axis is and
why; §4 records the FleetHorizon extension that implements it (shipped 2026-06-01) and
the measured result (§4.6).

---

## 1. The gap in today's instrument (why a second axis is needed)

Run the current harness at a realistic fleet:

```
PYTHONPATH=src python -m benchmark.fleet_horizon.harness --efforts 8 --phases 30
```

The integrity columns separate cleanly — the open loop banks ~17% lies, the closed
loop banks 0% — **but on `verified-shipped-per-dollar` the closed loop looks
*worse*: ~0.56 vs the open loop's ~0.78** (measured, this cell). That is not a bug in
the benchmark; it is an honest — and damning — consequence of its cost model.
`metrics.py` prices `verified_per_$` as `real_ships / total_cost`, and `total_cost`
counts only **worker actions** (attempt, rework, thrash, the collision-retry). In that
model the closed loop pays for every verify and every collision-split, while the open
loop's corruption is *free*: a banked lie costs nothing, a silent overwrite costs
nothing, a "done" that a human still has to review costs nothing. So today's
instrument actively makes the non-believing kernel look like **pure overhead** on the
per-dollar headline — which is exactly backwards from what an operator experiences,
and exactly the distortion the velocity axis exists to correct.

In a real fleet none of those three is free. Each is a deferred bill:

- a **banked lie** is paid when something built on the missing phase breaks, or when
  a reviewer has to discover by hand that "shipped" wasn't;
- a **silent overwrite** is paid as a merge conflict or a regression weeks later;
- a **"done" awaiting review** is paid as queue time — the dependent effort idles,
  and the reviewer is the scarce resource the whole fleet bottlenecks on.

So the raw instrument proves DOS keeps the fleet **honest** but, on the un-loaded
per-dollar number, makes it *read as a tax*. The velocity axis is the missing half:
price the downstream bill, add a wall-clock dimension, and the misleading
`verified_per_$` becomes an honest A/B delta that flips the right way —
**verified-velocity-per-dollar.** That axis has since been **built** (the extension in
§4, shipped 2026-06-01): with the downstream bill priced, the same 8×30 cell that read
0.56 < 0.78 against DOS on the raw number reads **0.500 > 0.379 for DOS** fully loaded —
a **1.32×** edge (§4.6). The rest of this note is the *why* behind each term of that flip.

---

## 2. The four data points

Each is stated as: the operator's intuition → the formal anchor → the DOS lever →
the metric that captures it.

### 2.1 Shared work & state can *speed* development — the coordination dividend

**Intuition (the operator's #1).** When efforts share state through one adjudicated
substrate instead of each working blind on a private branch, a dependent effort can
start the *moment* its predecessor is **verified** — not when a human gets around to
confirming it, and not on faith that the predecessor's "done" was true.

**Formal anchor.** This is the *positive* reading of Little's Law,
**WIP = Throughput × Cycle Time** (Little 1961). Unmerged branches are WIP; the
longer work sits unintegrated, the more WIP the fleet carries and the longer every
item's cycle time. Coordinating through shared, continuously-adjudicated state keeps
WIP low *without* lowering throughput — the regime *Accelerate*/DORA associates with
elite delivery (small batches, merge-to-trunk-daily, ≤3 active branches). The classic
CS framing is the **blackboard / shared-workspace** model (Hayes-Roth, *A Blackboard
Architecture for Control*, 1985) and tuple-space coordination (Gelernter's Linda, ACM
TOPLAS 1985): agents coordinating through a shared, structured medium scale better than
agents coordinating by point-to-point message-passing, whose communication cost is the
O(n²) channel growth of **Brooks's Law** (*Mythical Man-Month*, 1975 — n(n−1)/2
channels). And the *form* the coordination should take is settled CS: under **high
write contention**, **pessimistic** concurrency control (locks/leases) beats
**optimistic** (write-freely-then-reconcile), because optimism forces repeated
rollback/retry that wastes work (Kung & Robinson, *On Optimistic Methods for
Concurrency Control*, ACM TODS 1981). CodeCRDT (arXiv:2510.18893) is the agent-era
empirical echo: lock-free parallel agents hit **up to −39.4% slowdown** on some tasks
from code-volume inflation and coordination overhead, with optimistic convergence
guaranteeing *no merge failure* but **not correctness** (5–10% semantic-conflict rate).
Optimism converges; it does not make the convergence true — which is the whole reason a
*non-believing* arbiter, not a CRDT, is the right primitive here.

**The DOS lever.** `arbitrate()` lets disjoint efforts proceed truly in parallel
(no false serialization), while `verify()` turns "predecessor done" from a believed
claim into an adjudicated fact a dependent can build on immediately. The dividend is
*earned parallelism*: concurrency that is safe because writes are serialized on
contention and completeness is checked, not assumed.

**Metric — `dependency-unblock latency`:** for each phase that depends on a prior
phase, the wall-clock from "predecessor really shipped" to "dependent allowed to
start." Open loop: either it blocks on human review (slow) or it starts on an
unverified predecessor (fast but corruption-prone — and it pays §2.2/§2.4 when the
predecessor was a lie). Closed loop: starts at the verify, which is machine-fast.

### 2.2 Merge-conflict resolution is the expensive tax — the detonation cost

**Intuition (the operator's #2).** A silent overwrite is not a neutral event that a
kernel happens to catch. It is a *latent conflict* that, left undetected, surfaces
later as the single most expensive routine event in collaborative development:
resolving a merge conflict by hand.

**Formal anchor.** Three measured facts stack here. (a) **Conflicts are common even
among coordinating humans:** ~**10–20% of merge attempts** produce a textual conflict
(Ghiotto et al., *On the Nature of Merge Conflicts*, IEEE TSE 2018, 2,731 Java
projects) — and resolution difficulty is driven by *complexity, not size*, with
deferral stalling the whole team (Nelson et al., EMSE 2019). (b) **Agent fleets exceed
that floor:** **AgenticFlict** (arXiv:2604.03551, AIware'26) found **27.67% conflict**
across 142,652 agentic PRs / 336K+ conflict regions, mean ~540 conflict lines/PR — and,
tellingly, the rate **climbs with agent autonomy** (Copilot 15.2% < Cursor 19.8% <
Devin 22.9% < Claude Code 25.9% < Codex ~31.9%). (c) Resolution cost rises **super-
linearly in divergence** — the "merge debt" DORA's trunk-based-development capability
argues against, Reinertsen's holding-cost curve. The nastier subclass is the
**semantic / silent** conflict: a merge clean *textually* that still breaks build or
behavior (Brun et al., *Proactive Detection of Collaboration Conflicts*, ESEC/FSE 2011,
across 9 systems / 3.4M LOC) — exactly what "last-write-wins" produces when two efforts
both touch a shared file, nothing is lost on disk, but the *meaning* is.

*Honesty grading:* the 10–20% human floor is well-replicated, large-scale mining; the
27.67% agentic figure is **preprint-only, single-source, merge-*simulation* based, with
no within-study human control arm** — so "agents conflict more than humans" is a
defensible cross-study inference, not one study's measured comparison. And do not
conflate AgenticFlict's 142K filtered PRs with the 932K-PR AIDev parent dataset they're
drawn from; they are different layers.

**The DOS lever.** `arbitrate()` over live leases refuses the colliding write *at
the moment of contention*, when the divergence is zero and the fix is "split the
change / take the lane next," not later when the divergence is large and the fix is a
hand-merge. A conflict prevented at t=0 is paid at the cheap end of the super-linear
curve; a conflict discovered at merge time is paid at the expensive end.

**Metric — `conflict-resolution cost`:** every silent overwrite the open loop banks
is charged a **conflict multiplier** `κ > 1` of a normal action (the hand-merge tax),
applied at the downstream point where it would surface. The closed loop pays the
*prevention* cost instead: one refused-write + one split-retry (a small constant). The
A/B is `κ · overwrites_open` vs `prevention_cost_closed`. Sweep `κ` — the benchmark
reports the **break-even κ** above which DOS pays for itself purely on conflict cost,
and notes that the empirical literature puts real κ well above it.

### 2.3 PR review / wait is a real roadblock — the review-queue bottleneck

**Intuition (the operator's #3).** The time to *craft a review*, and the time a PR
*waits* for a human reviewer, is often the dominant component of lead time — and it
gets worse, not better, as agents make code cheap to generate. Generation scales;
human review does not.

**Formal anchor.** This is **Kingman's formula** / the M/M/1 result: queue wait grows
as **ρ/(1−ρ)** in utilization ρ. A review queue fed by a fleet that generates faster
than humans review runs ρ → 1, and wait time **explodes super-linearly** — the
formal statement of "review is the new bottleneck." It is also Little's Law again
(§2.1) read as a *failure* mode: if arrival rate into the review queue exceeds the
reviewer's service rate, the queue is non-stationary and average time-to-merge grows
**without bound**. The empirics back the model with three measured findings: (a)
**latency is dominated by *waiting*, not reviewing** — across 111,094 PRs in 10 OSS
projects, human first-response is slow and project-variable (Odoo median ~23.6 h) while
**bots respond in <10 min** (Kudrjavets et al., *Time to First Response in GitHub PRs*,
MSR 2023); the causal decomposition finds reviewer first-response time the single
largest determinant of total latency (Zhang et al., *Pull Request Latency Explained*,
EMSE 2022). (b) **PRs sit idle most of their life** — roughly half idle >50% of their
lifespan, pickup the largest bucket (LinearB, 8.1M PRs — vendor analytics). (c) **Bigger
PRs get slower, worse review** — defect detection collapses above ~400 LOC
(SmartBear/Cisco, 2,500 reviews / 3.2M LOC; corroborated by *Do Small Code Changes
Merge Faster?*, arXiv:2203.05045) — and agent PRs trend *larger* (+154% under high AI
adoption, Faros), pushing them out of the reviewable band exactly as volume rises.

**The DOS lever — this is where "planned out and adjudicated for completeness"
earns its keep (the operator's #4 fused into #3).** DOS does not *replace* the human
reviewer; it changes *what reaches the queue*. Work is planned into phases, and each
phase's completeness is adjudicated **deterministically** by `verify()` + the `gate`
verb against machine-checkable criteria. So the human review queue shrinks from
*everything the fleet emits* to *the exceptions the kernel surfaces* — caught lies,
refusals, genuine judgement calls (the `dos decisions` queue is exactly this
projection). Lowering the arrival rate into the human queue is the one move that
pulls ρ back from 1, and by Kingman that is **super-linearly** valuable — a small
drop in arrival rate near saturation is a large drop in wait.

**Metric — `review-wait time` and `human-review fraction`:** model a single-server
human review queue with service rate μ. Open loop: *every* banked "done" enters it
(arrival rate λ_open = full fleet output), so wait ≈ ρ/(1−ρ)·(1/μ) with ρ_open
near 1. Closed loop: only kernel-surfaced exceptions enter it (λ_closed = lie/refusal
rate × fleet output ≪ λ_open), so ρ_closed is far from 1 and wait collapses. Report
both the **review-wait time** delta and the **human-review fraction** (share of fleet
output that needed a human) — the second is the cleaner headline because it is a
property of the kernel's adjudication, not of any assumed μ.

### 2.4 Plan-then-adjudicate-completeness — the mechanism beneath 2.1 and 2.3

This is less a fourth independent metric than the **mechanism** that makes the first
three real, called out because it is the operator's framing and because it is the part
that is genuinely DOS-shaped rather than generic queueing theory.

A plain orchestrator's unit of work is "a PR an agent opened." Its completeness is a
*self-report* (`{shipped: true}`), so the only authority that can confirm it is a
human, and the only place that confirmation can happen is the review queue. DOS's
unit of work is **a planned phase with a machine-checkable completion predicate**.
Completeness is adjudicated by `verify()` (registry-first, ancestry-checked, answered
from git — never from the agent's log line) and gated by `gate`. That single change —
*completeness is an adjudicated property, not a narrated one* — is what:

- lets a dependent start at the verify instead of the review (§2.1),
- lets the conflict be refused at contention instead of merge (§2.2),
- and lets the human queue carry exceptions instead of everything (§2.3).

The honest boundary (from [`79_primitives-not-features.md`](79_primitives-not-features.md)
and [`76_*`](76_flexible-goals-and-verification.md)): DOS adjudicates *completeness
against a declared predicate*; it does **not** adjudicate *correctness* or *taste*.
"Is this the right design?" stays a human review. So the claim is **not** "DOS
eliminates review" — it is "DOS removes the *mechanical completeness check* from the
human's plate so the human reviews *judgement*, and shrinks the queue to the rate at
which real judgement is actually needed." Overclaiming this is the one way to make the
velocity story dishonest, so the metric headlines **human-review fraction** (what the
kernel can take off the human) rather than a fabricated "review eliminated" number.

*A second honesty grade, the most important in this note.* The empirical evidence that
*pre-verified/machine-gated PRs actually reduce human review time* is **the weakest
link in the literature** — it is mechanism plus one corroborated fact (bots already own
the sub-10-min first-response lane; CI is a first-order latency factor), **not** a
controlled before/after study. We know review is the bottleneck (well measured, §2.3);
we know completeness *can* be adjudicated by machine (DOS does it). The *bridge* — "so
human review shrinks" — is a sound mechanism we should claim **as a mechanism**, and the
benchmark exists precisely to *measure* what is today only argued. The note must not
present the bridge as already-measured; the §4 instrument and the §6 live A/B are how it
becomes measured.

There is also a textual-vs-semantic caveat that bounds even the completeness claim: a
clean `verify()` (a real commit closing the phase) is *ground-truth shipped*, but ship
≠ correct, the same way a clean textual merge ≠ a working build (§2.2's silent-conflict
finding). DOS's completeness verdict rests on git + a declared predicate; wiring the
predicate to *build/test* oracles (not just commit-existence) is what makes "complete"
approach "correct," and that is a host's predicate to declare, not the kernel's to
assume.

---

## 3. The honesty discipline (carried over and extended)

The integrity benchmark's §6 rebuttals all still bind, plus three new ones the
velocity axis introduces:

- **The downstream multiplier `κ` is swept, not picked.** The headline is the
  **break-even κ** (where DOS pays for itself on conflict cost alone) plus a curve;
  the empirical anchor (AgenticFlict conflict rate, the super-linear merge literature)
  is cited as *context for where real κ sits*, never plugged in as a magic number that
  wins the A/B.
- **The review-queue service rate μ is the consumer's, not ours.** Because absolute
  wait depends on an assumed μ, the load-bearing headline is **human-review fraction**
  — a model-free property of the kernel's adjudication (what share of output the
  kernel could confirm without a human). Wait-time is reported as a *function of* μ, so
  a skeptic plugs in their own μ.
- **Same agent, same seed — DOS still gets no better worker.** The velocity metrics
  are computed over the *same* event logs as the integrity metrics. DOS does not write
  faster code or fewer conflicts at the source; it changes *when and where the bill for
  a given fleet's behavior is paid*. The delta is a property of believe-vs-adjudicate,
  identical-agent — the same invariant the integrity arm honors.
- **The gap → 0 as horizon → 1 still holds, and now for velocity too.** At one effort,
  one phase, there is no dependent to unblock, no concurrent writer to conflict with,
  and a review queue of depth ~1 — so the velocity delta vanishes exactly where the
  integrity delta does. The benchmark proves its own "DOS is pure overhead at small
  scale" clause on *both* axes.

The steelman to pre-empt (the §6.2 analogue): *"you priced the open loop's lies with a
multiplier you chose, so of course DOS wins."* The rebuttal is the break-even framing:
we do not assert κ; we report the κ at which the arms cross and let the reader compare
it to the published merge-cost and conflict-rate literature. The A/B's *sign* (which
arm is cheaper) is reported as a function of κ and μ, not as a single rigged scalar. And
the measured answer disarms the steelman directly: the sweep reports **break-even κ = 0
at every fleet ≥ 2** (§4.6) — DOS wins *even with the conflict multiplier set to zero*,
on the model-free human-review-fraction term alone (100% → 20% in the headline cell).
There is no chosen multiplier doing the work; the conflict cost is margin on top of an
already-winning position.

**A determinism note, because "same seed → same result" is load-bearing here.** The
whole A/B rests on the two arms running the *identical* seeded workload, so the numbers
above must be a pure function of `(seed, workload)` — reproducible across machines and
runs. A first cut of the shipped extension was **not**: the per-effort RNG was seeded
from Python's built-in `hash(effort)`, which CPython salts per process
(`PYTHONHASHSEED`), so the headline metrics quietly drifted between separate CLI
invocations (three observers logged 0.50, 0.484, and 0.447 for the same cell) while the
in-process determinism test stayed green. That is exactly the failure the README warns
against ("a benchmark whose result changes run-to-run proves nothing"), so it was fixed:
the seed now derives from `zlib.crc32` (stdlib, unsalted, stable across processes), and a
`test_determinism_is_hash_salt_independent` subprocess test pins the contract by running
an arm under two different `PYTHONHASHSEED` values and asserting byte-identical metrics.
The figures in §4.6 are the post-fix, reproducible canon.

---

## 4. The FleetHorizon velocity extension — built, and what it shows

> **Status: shipped 2026-06-01.** This section specified the extension; it has since
> been implemented in `benchmark/fleet_horizon/` (the new velocity event kinds, the
> derived metrics, `--velocity-sweep`, and the pinned honesty tests all exist and pass).
> The component breakdown below doubles as the design record; the measured result is in
> §4.6. No kernel change — the harness consumes the kernel from outside, the same
> boundary as `examples/`.

The build, component by component:

1. **`metrics.py` — two new costed event kinds + derived velocity metrics.**
   Add `conflict-detonation` (a banked silent-overwrite's downstream hand-merge,
   charged `κ · COST_PER_ACTION`) and `human-review` (a banked "done" that entered the
   human queue, charged a review-service cost). Derive `verified_velocity_per_dollar`
   (real ships ÷ *fully-loaded* cost, downstream bill included), `human_review_fraction`,
   and `mean_review_wait(μ)`. Keep `score()` a pure function over the event log so the
   *same* scorer runs both arms (no per-arm tilt — the existing invariant).

2. **`open_loop.py` — emit the deferred bills it was silently ignoring.** When the open
   loop banks a silent overwrite, it later emits a `conflict-detonation`; when it banks
   any "done," it emits a `human-review` (everything must be reviewed by a human because
   nothing adjudicated completeness). This is not *penalizing* the open loop — it is
   *recording costs its own output already incurred*, the same honesty stance as the
   lie metric (the open loop *produced* the clobber and the unverified "done"; the
   velocity scorer merely prices them).

3. **`closed_loop.py` — emit the prevention + exception bills.** A refused write emits
   the small split-retry cost (already partly modeled as the deferred-drain actions); a
   caught lie or refusal emits one `human-review` (the exception genuinely reaches a
   human via the decisions queue); a verify-confirmed clean ship emits **no**
   `human-review` (the kernel confirmed completeness). The closed loop's human-review
   fraction is therefore ~ the lie+refusal rate, not 100%.

4. **`harness.py` — sweep `κ` and `μ`, report the velocity A/B + break-even.** Add
   `--kappa` and `--review-mu` plus a `--velocity-sweep` that prints
   `verified-velocity-per-$` for both arms across (horizon × fleet × κ), the
   **break-even κ**, and the **human-review-fraction** delta. The existing
   integrity table stays; this is a second table beneath it.

5. **`test_fleet_horizon.py` — pin the new honesty properties.** Add cases:
   velocity gap → 0 at `efforts=1, phases=1`; `human_review_fraction(open) == 1.0`
   exactly and `closed < open` strictly at any fleet > 1; `verified_velocity_per_$`
   ordering flips at the reported break-even κ and not before; same-seed determinism.

The deliverable is a second headline beside `verified-shipped-per-$`:
**`verified-velocity-per-$`** — oracle-confirmed ships per *fully-loaded* dollar
(generation + verification + the downstream conflict-and-review bill). That single
number is what an operator deciding whether to put a kernel under their fleet actually
wants, and it is the number no published benchmark reports today (§5).

### 4.6 The measured result (headline cell: 8 efforts × 30 phases, κ=5, μ=0.33)

Running `--velocity-sweep` on the shipped extension confirms the thesis — and, on one
point, *exceeds* what §3 claimed. These are the **canonical, reproducible** figures
(regenerate any time with `python -m benchmark.fleet_horizon.harness --velocity-sweep`;
the checked-in `RESULTS.txt` is a snapshot and is rebuilt by that command — see the
determinism note at the end of §3):

| metric | open-loop | closed-loop | |
|---|---|---|---|
| `verified/$` **(raw — actions only)** | **0.78** | **0.56** | ← the distortion §1 names: raw, DOS looks like a tax |
| `verified/$` (defect-adjusted) | 0.24 | 0.56 | ← price the integrity debt and it flips |
| **human-review FRACTION** | **100%** | **20%** | ← the open loop must human-confirm *everything* |
| review-queue wait (M/M/1) | **∞** | 1.54 | ← ρ→1 saturates the open loop's queue (Kingman) |
| conflict detonations | 6 | 0 | |
| **VERIFIED-VELOCITY / $** (fully loaded) | **0.379** | **0.500** | ← **1.32× for DOS** — the honest headline |

Three things to read off it:

1. **The raw-vs-loaded contrast is shown both ways, not hidden.** The raw row still
   reproduces §1's distortion (open 0.78 > closed 0.56 — DOS as overhead); the
   fully-loaded row flips it (closed 0.500 > open 0.379, **1.32×**). The benchmark reports
   both, so a skeptic sees exactly which costs drive the flip.

2. **The review-fraction win alone carries it — stronger than the break-even-κ framing
   predicted.** The sweep reports **break-even κ = 0 at every fleet ≥ 2**: DOS is ahead
   *even with the conflict multiplier set to zero*, because shrinking the human-review
   queue from 100% to 20% already wins on its own. The conflict-detonation cost (§2.2)
   is then pure additional margin, not the load-bearing term. So §3's "we report the
   break-even κ" honesty stance survives — and the answer happens to be 0, which is the
   most conservative-to-DOS result possible.

3. **The monotonicity falsifier holds on the velocity axis too.** The integrity
   `--sweep`'s `verified/$ edge` is `<1.0` (DOS *more* expensive) at short horizon and
   only climbs past 1.0 as the horizon grows — the benchmark proves its own "DOS is
   overhead at small scale" clause rather than hiding it (exact per-horizon multipliers
   in `RESULTS.txt`).

Reproduce: `PYTHONPATH=src python -m benchmark.fleet_horizon.harness --velocity-sweep`.

---

## 5. The benchmark *category* — why this is a new leaderboard, not a new row

The agentic-coding field measures **single-patch correctness**: SWE-bench, SWE-bench
Verified, SWE-Lancer, Multi-SWE-bench — *one* agent, *one* patch, scored in isolation
against hidden tests. That axis is mature and saturating. The field is now reaching for
a **harness** axis: score not the model in a vacuum but the *whole apparatus* — the
scaffolding, the coordination, the orchestration — because at the frontier the harness,
not the raw model, sets the ceiling. **Harness-Bench** (arXiv:2605.27922, 2026; site
harness-bench.ai — *not* a `.com`) makes this concrete with a full factorial of 106
tasks × 6 harnesses × 8 models (5,194 runs): aggregate scores span **52.4% → 76.2%
across harnesses on the *same* models** — a 23.8-point gap — so its own conclusion is
"report capability at the *model-harness* level, not the model alone." (Preprint,
unreplicated — cite as reported.) But Harness-Bench, like SWE-bench, still scores a
**single agent's** harness; it does not put a *fleet* on shared state.

FleetHorizon's contribution is to give that harness axis a **headline the others
lack**: not "what fraction of isolated tasks pass" but **"how much verified work does a
fleet on shared state deliver per fully-loaded dollar, believed vs adjudicated."** The
category-defining move is the **A/B that no single-patch benchmark can run** — the same
fleet, same seed, once trusting self-reports and once adjudicated — with a *velocity*
headline, not just an integrity one.

Position against the nearest neighbors (the prior-art map in
[`benchmark/fleet_horizon/README.md`](../benchmark/fleet_horizon/README.md) and the
References above):

| Benchmark | Unit scored | Fleet on shared state? | Believed-vs-adjudicated A/B? | Velocity / $ headline? |
|---|---|---|---|---|
| **SWE-bench (+Verified/Lancer/Multi)** | one patch, isolated | no | no | no (pass-rate; Lancer maps to $ but single-task) |
| **STORM** (2605.20563) | task success under a *manager-agent* mediator | yes | no (no *believed* arm; mediator is an LLM) | no (task-success %) |
| **CodeCRDT** (2510.18893) | parallel-agent throughput w/ CRDT convergence | yes | no | partial (speedup/slowdown, no $, no verify) |
| **SCHEME** (2605.29178) | monitored-vs-unmonitored on shared codebase | yes | adversarial-sabotage framing; OS-pre-partitioned perms | no |
| **FleetHorizon (this)** | **fleet of long-horizon efforts, shared repo** | **yes** | **yes — deterministic, model-free kernel** | **yes — verified-velocity-per-$** |

The honest novelty claim stays narrow (per the prior-art memo): **first to measure the
adjudication delta — on both integrity *and* velocity — for an honest fleet, with a
model-free kernel and a per-dollar headline.** Not "first to notice fleets conflict"
(AgenticFlict), not "first to mediate concurrent agents" (STORM), not "first to measure
parallel-agent throughput" (CodeCRDT). The empty quadrant is the *believed-vs-adjudicated
velocity A/B with a model-free referee*, and it is an absence from targeted search — a
moderate-high-confidence negative, not a proof.

> **A harness benchmark scores the apparatus around the model. DOS's apparatus is a
> referee that doesn't believe the workers — so the natural headline for a DOS-flavored
> harness benchmark is the one quantity that only a non-believing referee can even
> compute: how much of the fleet's "done" was *true*, and what the true part cost,
> believed vs adjudicated.**

---

## 6. Demos on existing projects — showing the delta where it bites

The benchmark proves the delta *in simulation* (deterministic, hand-checkable). The
demos show it *on real repos*, each tied to one data point. Ordered by build cost:

1. **The `dos decisions` queue as the §2.3 demo (lowest cost — already shipped).**
   Point `dos decisions` at any workspace with refusals/caught-lies. The TUI *is* the
   "human queue carries exceptions, not everything" story made concrete: it renders the
   handful of items a human must actually adjudicate and emits the shell command to act,
   while everything the kernel could confirm never appears. Demo script: run a fleet, show
   that N "done"s collapsed to k≪N items in the operator queue. Hooks §2.3/§2.4 directly.

2. **A foreign OSS repo with known agentic-PR conflicts as the §2.2 demo.** `verify`
   already points DOS at a repo it does not own. Pick an OSS repo from the
   AgenticFlict-style population (high agentic-PR conflict rate), replay two overlapping
   PRs through `arbitrate()`, and show the conflict refused at contention vs the actual
   hand-merge that landed. The headline: "this real conflict cost a human a hand-merge;
   the arbiter would have refused it at t=0." Ties to the prior-art conflict anchor.

3. **The reference userland app's own dispatch history as the §2.1 demo (dogfood).** The
   reference userland app runs a real multi-lane fleet under DOS today. Mine its
   lane-journal + git history for a case
   where a dependent phase started right after a predecessor *verified* (not after a human
   confirmed) — the coordination dividend in the wild — and contrast with a hypothetical
   review-gated timeline. This is the "we already live this" proof; it is the strongest
   because it is not simulated.

4. **A small live A/B on a scratch repo (the headline demo) — the Faros-paradox
   falsifier.** Two real Claude-Code fleets on the same seeded set of issues in a throwaway
   repo: one plain orchestrator (believe `{shipped:true}`), one under DOS
   (`verify`+`arbitrate`+`gate`). Measure the real `verified-velocity-per-$` *and the
   human-review fraction*. This is the live test of the §1 paradox: the production
   telemetry (Faros) shows AI fleets merge +98% but stall at +91% review and flat
   throughput — the prediction here is that the DOS arm converts more of its raw output
   into *human-confirmed* throughput by shrinking the review fraction, while the plain arm
   reproduces the paradox. It is the most expensive demo (real models, real nondeterminism,
   real cost) and the most persuasive — the live counterpart the simulation is built to
   make safe to reason about first. Budget-gated; the deterministic simulation is the cheap
   stand-in that de-risks the design before any model spend.

---

## References (theory + empirical prior art)

Graded by strength of evidence, because the velocity story is only as honest as its
weakest cited number. **Theorem** = proved (holds under stated assumptions a fleet can
violate); **measured** = peer-reviewed empirical study; **industry** = large-N vendor
telemetry/analytics, not peer-reviewed; **preprint** = un-peer-reviewed, often
single-source; **model** = an economic/management model, not a dataset.

*Flow & queueing economics (§2.1, §2.3):*
- Little, *A Proof for the Queuing Formula L = λW*, Operations Research 1961 — **theorem**
  (WIP = throughput × cycle time; needs steady state). [`en.wikipedia.org/wiki/Little%27s_law`]
- Kingman 1961 / M/M/1 — **theorem** (wait ∝ ρ/(1−ρ); the super-linear review-queue
  blow-up).
- Reinertsen, *The Principles of Product Development Flow*, 2009 — **model** (batch-size
  U-curve, cost-of-delay, holding cost of unmerged work).
- Forsgren, Humble, Kim, *Accelerate* + DORA *State of DevOps* reports — **industry /
  survey correlation** (four key metrics; small-batch & trunk-based ↔ elite delivery).
  *Caution:* correlational, not causal; the popular "2.3×" trunk-based figure is a
  secondary-blog attribution, not on DORA's primary page. [`dora.dev/guides/dora-metrics`]

*Code-review latency (§2.3):*
- Kudrjavets et al., *Understanding Time to First Response in GitHub PRs*, MSR 2023
  (arXiv:2304.08426) — **measured** (111K PRs; bots <10 min, humans far slower).
- Zhang et al., *Pull Request Latency Explained: An Empirical Overview*, EMSE 2022
  (arXiv:2108.09946) — **measured** (reviewer first-response time dominates latency).
- Sadowski et al., *Modern Code Review: A Case Study at Google*, ICSE-SEIP 2018 — **measured**
  (~9M changes). *Caution:* the oft-quoted "~4 h turnaround" is industry-secondary.
- SmartBear/Cisco code-review study (~2006) — **industry** (defect detection collapses
  >400 LOC); corroborated by *Do Small Code Changes Merge Faster?* (arXiv:2203.05045, **measured**).
- LinearB *Engineering Benchmarks* (8.1M PRs) — **industry** (½ of PRs idle >50% of life).
  *Caution:* the derived "$24K/dev/yr" is a vendor estimate; don't cite as measured.

*Merge-conflict cost (§2.2):*
- Ghiotto et al., *On the Nature of Merge Conflicts*, IEEE TSE 2018 (2,731 projects) —
  **measured** (10–20% of merges conflict among humans).
- Nelson et al., *The Life-cycle of Merge Conflicts*, EMSE 2019 — **measured** (difficulty
  ∝ complexity not size; deferral stalls the team).
- AgenticFlict (arXiv:2604.03551, AIware'26) — **preprint** (27.67% of 142,652 agentic
  PRs conflict; rate climbs with autonomy). *Cautions:* simulation-based, **no human
  control arm**; do **not** conflate its 142K filtered PRs with the 932K-PR AIDev parent
  dataset (arXiv:2602.09185).
- Brun et al., *Proactive Detection of Collaboration Conflicts*, ESEC/FSE 2011 (9 systems,
  3.4M LOC) — **measured** (silent/semantic conflicts: clean textual merge still breaks
  build/test). The basis for "textual non-conflict ≠ correctness."

*Concurrency control & shared-state coordination (§2.1):*
- Kung & Robinson, *On Optimistic Methods for Concurrency Control*, ACM TODS 1981 —
  **established CS** (under high write contention, pessimistic locking beats optimistic).
- Gelernter, *Generative Communication in Linda*, ACM TOPLAS 1985 — **foundational**
  (tuple-space / shared-associative-memory coordination).
- Hayes-Roth, *A Blackboard Architecture for Control*, Artif. Intell. 1985 — **foundational**.
- Brooks, *The Mythical Man-Month*, 1975 — **heuristic** (communication cost n(n−1)/2; the
  brake on naive parallelism).

*The AI-fleet smoking gun & benchmark landscape (§1, §5):*
- Faros AI, *The AI Productivity Paradox* (10,000+ devs) — **industry telemetry**
  (+98% PRs merged, +91% review time, +154% PR size, flat company throughput). The headline
  real-world anchor; large N but vendor-published, not peer-reviewed. *Do not* cite the
  unsourced "4.3 vs 1.2 min to review AI vs human code" figure — it is unverifiable.
- Harness-Bench (arXiv:2605.27922, 2026; harness-bench.ai) — **preprint** (52.4%→76.2%
  across harnesses; "report capability at model-harness level"). Single-agent harnesses.
- SWE-bench / Verified / Multimodal / Multi-SWE-bench / SWE-Lancer — **measured/adopted**
  (single patch, isolated; the quadrant FleetHorizon is *not* in).
- STORM (arXiv:2605.20563) — **preprint** (manager-agent mediates concurrent agents;
  Commit0-Lite 82.5% vs 63.8% worktree vs 66.4% single — *reported*, no *believed* arm).
- CodeCRDT (arXiv:2510.18893) — **preprint** (parallel agents w/ CRDTs; +21.1%/−39.4%
  speedup/slowdown; convergence ≠ correctness). The empirical echo of Kung & Robinson.
- SCHEME (arXiv:2605.29178) — **preprint**, and **not a velocity benchmark** — it measures
  coordinated *sabotage*; cited only to disqualify it as a velocity comparator.

> **The "empty quadrant" claim, stated honestly:** across targeted search we located **no
> public benchmark** that runs a *fleet on shared state*, *believed-vs-adjudicated*, with
> a *model-free referee* and a *verified-velocity-per-dollar* headline. That is an absence
> from search — a moderate-to-high-confidence negative, not a proof a private one doesn't
> exist. One adjacent production signal (a throughput-stagnation analysis echoing the Faros
> paradox) exists as commentary, not a benchmark.

## See also

- [`benchmark/fleet_horizon/README.md`](../benchmark/fleet_horizon/README.md) — the
  integrity-axis instrument this note adds a velocity axis to.
- [`79_primitives-not-features.md`](79_primitives-not-features.md) — why `verify`/`refuse`
  are primitives the velocity story builds *on* without changing them (completeness is
  adjudicated; remediation is host concern).
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) — the
  verdict-vs-source split; why "completeness" is adjudicable but "correctness/taste" stays
  a human review (the boundary §2.4 must not overclaim).
- `CLAUDE.md` — the layering contract; the benchmark and demos consume the kernel from
  outside it, never edit it.
</content>
</invoke>
