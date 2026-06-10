# 155 — Coordinating parallel research-on-DOS: why it felt off, and the fix

> **Status:** ruling + the first concrete artifact seeded (2026-06-05). Produced by an adversarial
> 3-angle workflow (dogfood-the-lanes / question-the-decomposition / lightweight-convention →
> synthesize), motivated by the operator's repeated "divide and conquer still feels slightly off"
> while multiple agents built the EnterpriseOps arc (docs/143–154) in parallel.
>
> **One line.** The numbered `docs/NN` was secretly doing **three jobs at once** — an *identifier*
> (which collides: two agents took `151`), a *unit of immutability* (which forces supersede-don't-edit:
> 149's wrong claim got a new immutable doc 150 with a hand-maintained `⚠ Update` banner instead of an
> edit), and a *unit of finding* (one measurement = one whole document: the same dangling recall got
> re-measured 13% vs 26% in two docs and reconciled after the fact). **Split those three apart and all
> four observed failures dissolve.** The deepest irony, named: the agents *building* docs/116 ("read
> each other's adjudicated EFFECTS, never their claims") coordinated through **claims** — prose docs
> that re-argue numbers — instead of **effects** — measured rows that accrete. Applying the kernel's
> own thesis to the research is the fix.

---

## 0. The four observed failures (concrete, from the git log)

1. **Doc-number collision** — two `docs/151_*.md` (intervention-live-study + weak-model), committed
   minutes apart, neither agent knew. Refs to "docs/151" went ambiguous. (Resolved: weak-model → 153.)
2. **Hot shared files** — `live_ab.py` (~6 commits) and `RESULTS.md` (~10) accreted near-duplicate
   fixes across agents (chdir, key-names, env-vars, the dangling arm, an encoding fix).
3. **No arc index** — no map of designed-vs-measured-vs-shipped; `docs/README.md` stopped at doc 84.
4. **Semantic drift** — the same `dangling_intent` recall measured 13% (full corpus) vs 26% (paired
   set), reconciled across two docs after the fact, not at measurement time.

---

## 1. The ruling on decomposition: HYBRID (the root fix)

**Not 10 numbered docs. Not one mega-doc. A living lab-notebook + an append-only measurements
registry for the *empirical arc*; numbered `docs/NN` reserved strictly for a *shipped kernel
mechanism*.**

The one-line test (already in CLAUDE.md's mechanism-vs-strategy spirit): **if a sentence reports a
measured number, it belongs in the registry/notebook; if it specifies how a kernel module behaves, it
is a `docs/NN`.** Half of 143–152 is the former wearing the latter's clothes.

Why hybrid, not the extremes:

- **Not 10 numbered docs.** A numbered design-note is *immutable, ordered, singular* — right for
  docs/82 (liveness) or docs/107 (resume): one author, one design, ships or doesn't. The EnterpriseOps
  work is the **opposite shape** — one living question (*does DOS help a real model?* → no → partly →
  measure it two ways) under *concurrent measurement where later evidence revises earlier
  conclusions*. Forcing that into immutable docs produced every pathology: a finding can't be *edited*
  when new data revises it (149's claim was wrong), so it gets *superseded* by a new immutable doc
  (150) with a hand-faked `⚠ Update` banner — mutability the format denied, faked by hand. And two
  agents measuring the same live question each need a *number* with no allocator → 151a/151b.
- **Not one mega-doc.** A shippable mechanism that comes *out of* the research (docs/144 the
  intervention ladder; the `arg_provenance`/`dangling_intent` modules) is a real design contract — one
  author, immutable, ordered. Keep those numbered; demoting them to notebook sections loses what the
  numbered-doc is *good* at.
- **So: hybrid.** Split the three conflated jobs: the **identifier** goes to a broker (no collision);
  the **immutability** unit becomes the notebook's body-immutable/head-editable profile (the mutability
  the work actually needed); the **finding** unit becomes a keyed registry row (one measurement = one
  row, not one document).

---

## 2. The prevention mechanisms (lightweight, reuse what ships)

The four failures split cleanly by **whether a path-glob can name the contested thing** — which
decides whether to dogfood DOS's lock or use a convention:

| Failure | Contested thing | A glob-region? | Fix |
|---|---|---|---|
| Hot file | a concrete path | **Yes** | `dos lease-lane acquire --lane benchmark` — *works today, was unused* |
| Doc number | the next free *integer* | **No** (not a path until it exists) | `dos doc-claim` over `archive_lock` CAS — the one genuine race |
| Arc index | a read-model projection | No | generate it (`docs/REGISTRY.md` / this doc's siblings) |
| Semantic drift | the *meaning* of a finding | **No** (overlaps by meaning, not path) | a measurements registry with a **mandatory `denominator`** |

**Hot files — dogfood the lane (build nothing).** `live_ab.py` is under the `benchmark` lane already.
An agent about to edit it runs `dos lease-lane acquire --lane benchmark --run-id <rid>`; a second
agent is **refused** and reads the holder's `run_id` from the WAL (docs/116, applied to the builders).
Optionally narrow the hot files into their own lanes so disjoint edits run concurrently:
```toml
[lanes.trees]
bench-live-ab = ["benchmark/enterpriseops/live_ab.py"]
bench-results = ["benchmark/enterpriseops/RESULTS.md"]
```
(Add to `concurrent`, **never** `autopick` — never auto-hand-out a hot file.)

**Doc number — the one genuine race, and a convention loses it.** The proof: the `151→153` manual
renumber, run under "check the max, take the next," briefly *re-collided* with another agent's
in-flight 153 before settling at 154. "Read max+1" loses the race exactly like `git add -A` does when
two agents run it in the same window. Only an *atomic reserve* closes it — and DOS already ships the
primitive: `src/dos/archive_lock.py` is a value-keyed compare-and-swap (`O_CREAT|O_EXCL` + TTL-steal
via atomic rename). `dos doc-claim` is a thin **driver/helper** (not a syscall) over it:
```bash
dos doc-claim --slug <slug> --status DESIGNED   # → reserved docs/NNN, appends the registry row under a mutex
# ... write docs/NNN_<slug>.md ...
dos doc-claim --update NNN --status SHIPPED
```
The mutex makes "read-max → append → release" a critical section; the second agent **blocks on
acquire** until the first appends, then gets the next integer. The CAS-on-a-counter the situation
demands *falls out of* read-max-under-mutex — reusing the shipped TOCTOU-safe steal, inventing
nothing. **Recommendation: ship the verb only if the collision recurs; until then, the cheaper
convention is "reserve the number with an empty stub commit *before* the work" — the stub IS the
lease, a git fact every other agent sees on the next fetch** (the root cause was both agents holding
the number *privately* for the whole session).

---

## 3. The dogfood-honesty split (real indictment vs category error)

- **Hot files + doc number → REAL INDICTMENT, dogfood it.** These are region/identity problems DOS
  exists to referee. The hot file *is* the glob region the agents didn't lease; the doc number *is* the
  CAS target they didn't reuse.
- **Arc index + semantic drift → CATEGORY ERROR, don't force the lock.** An index is a *projection*,
  not a lock. And 149↔150 "crack" / 13%-vs-26% is **semantic overlap, not path overlap** — `lane_overlap`
  is a glob-prefix test; it would call 149 and 150 disjoint, admit both, and they'd *still* contradict.
  No region-lock catches "you divided by a different N than I did." Claiming the arbiter fixes this
  would be the laundering trap docs/143 itself warns against.

**The prerequisite for any of it — use the spine that already exists.** Every one of the ~41 arc
commits is authored "Claude" — the correlation spine cannot tell the agents apart. So the cheapest
dogfood of all: **each research agent takes a `run_id` at task start and stamps it in the registry
`claimed_by`, the measurement `agent` field, and its commit trailer.** Same hole docs/137 `trace`
closed for leases — the id existed, the join didn't.

---

## 4. What was actually done now (the seeded artifacts)

This doc's commit ships the two lowest-cost, highest-value pieces (the verb is deferred until the
collision recurs, per §2):

1. **`docs/ENTERPRISEOPS_ARC.md`** (the arc index, already created): the designed/measured/shipped
   table + the crack/supersede graph + a measured-results table. Linked from `docs/README.md`.
2. **`benchmark/enterpriseops/measurements.jsonl`** (seeded here): the append-only measurements
   registry with a **mandatory `denominator`**. The 13%-vs-26% drift is now two keyed rows that
   *visibly* differ on `denominator` — and had it existed, the second value would have collided at
   append time on `metric=dangling_recall + denominator`, caught once instead of reconciled across two
   docs. From now on, `RESULTS.md` and docs *cite a row id*; they never restate a number.

The deeper hybrid move (a single `LAB.md` notebook replacing future numbered findings, + the
`dos doc-claim` verb) is recommended but deferred — it is a process change best adopted at the *start*
of the next research arc, not retrofitted onto a finished one. This doc + the two artifacts make the
existing arc coherent and the next one cheaper.

---

## 5. The one-paragraph rule (the quotable start-of-task rule)

> **Parallel research-on-DOS, at task START:** take a `run_id` and stamp it in every commit trailer
> and every row you write. Measurements are **effects, not prose** — append one keyed row per measured
> number to `benchmark/enterpriseops/measurements.jsonl` (**mandatory `denominator`, `n`, `corpus`,
> `commit`, `agent`**); do **not** open a numbered `docs/NN` for a finding. Reserve a `docs/NN` **only**
> for a shippable kernel mechanism, and reserve it atomically — `dos doc-claim`, or at minimum an empty
> stub commit *before* the work (the stub is the lease) — never by eyeballing the highest number (that
> races). Before editing a hot shared file (`live_ab.py`, `RESULTS.md`), `dos lease-lane acquire` its
> lane; a refusal means someone holds it — read their `run_id` and wait, don't collide. **Numbers are
> reserved by a broker, findings accrete as keyed rows, narrative appends to one notebook — you race on
> nothing.**

---

## 6. Proving the theory on a benchmark (measured, 2026-06-05)

The operator asked: *can this coordination theory be proven on a benchmark, not just argued from our
own friction?* It can — but **not on EnterpriseOps-Gym, and the right benchmark already exists.**

### 6.1 EnterpriseOps-Gym is the wrong benchmark (don't force it)

EnterpriseOps-Gym is **single-agent by design**: fresh DB per run, independent pass@1 — docs/143 §5.4
already ruled "a single-task gym run is ONE process; there is nothing to double-book across; the
`arbitrate()` half is theater." A benchmark engineered to *exclude* the multi-agent collision is the
wrong place to measure a collision-prevention theory. Forcing it would be the exact laundering trap
docs/143 warns against. (The pass@1-over-3-runs is a tiny 3-agent fleet, but the runs are
*independent* — no shared state to collide on — so even that is not a coordination testbed.)

### 6.2 FleetHorizon already proves the MECHANISM half (measured)

`benchmark/fleet_horizon/` is the believed-vs-adjudicated A/B that *was* built for this: a fleet with
a lie-rate **and a collision-rate**, run `open_loop` (believe each agent) vs `closed_loop`
(`arbitrate` before each write + `run_id` lineage + `verify` the effect), same seed/workload — the
only difference is believe-vs-adjudicate. Run on a realistic long-horizon fleet (8 efforts × 30
phases, lie 0.12, shared 0.25):

| metric | open-loop (believe) | closed-loop (adjudicate) |
|---|---|---|
| banked LIES (undetected) | **35** (14.6 %) | **0** — all 35 refused |
| **silent overwrites on shared state** | **7** | **0** |
| **collisions refused** | 0 | **104** |
| banked integrity | 85.4 % | **100 %** |
| true cost (spend + downstream defect debt) | **966** | **359** |
| human-review fraction | 100 % | **17.1 %** |
| verified-velocity / $ | 0.387 | **0.520** |

**This is the docs/155 theory, measured.** Same agents, same seed — adjudication *refuses the
collisions a believing fleet silently banks* (104 of them) and the lies it can't detect (35), at the
cost of +40 % raw actions, netting a **1.34× verified-velocity/$ edge** and cutting human review 6×.
The sweep shows the edge is **2.2× at fleet 4, plateauing ~1.9× by fleet 12** — and the harness's own
falsifier is that the gap **→ 0 as fleet/horizon → 1** (at N=1, DOS is pure overhead). The mechanism
half of the theory is **proven**, not argued.

### 6.3 The real incident anchors it at the LOW end (measured)

Our docs/155 arc *is* a real fleet, and mining its git log (the `arc_coordination_rework_rate` /
`arc_hot_file_contention` rows in `measurements.jsonl`) gives the anchor:

- **Coordination-rework ≈ 10 %** (5 / 48 arc commits a lease/doc-claim would have prevented). **The
  honest split that matters:** the *naive* rework rate is 22 %, but most of it is **honesty-rework**
  (re-grounding overclaims — "the A/B REFUTES the BLOCK prize", "magnitude is a guess") which is
  *good science* DOS's lanes can't and **shouldn't** prevent. Only the coordination subset counts.
- **Hot-file contention:** `RESULTS.md` touched 10× across agents, `dos_react.py` 6×, `cli.py` 4× —
  the shared region the closed-loop arm would `lease-lane`.

**Running FleetHorizon AT the arc's real coordinates** (the most honest result — wide-but-SHORT, low-lie:
`efforts=12, phases=4, shared=0.15, lie=0.05`):

```
fleet=1  horizon=4: prevented= 0   edge=1.00x   (the falsifier: no one to collide with)
fleet=4  horizon=4: prevented= 6   edge=0.73x
fleet=8  horizon=4: prevented=13   edge=0.72x
fleet=12 horizon=4: prevented=24   edge=0.68x
```

Two findings, and the second is the load-bearing honesty:

1. **The collision-prevention mechanism FIRES at the real coordinates.** At the arc's fleet width
   (~12), FleetHorizon prevents **24 collisions** a believing fleet would discover after the fact —
   the same *kind* of friction we felt (the 151-collision, the ~6 `live_ab.py` re-fixes). Prevention
   scales cleanly with fleet width (0→6→13→24) and the falsifier holds (fleet=1 → 0). The simulated
   ~24 over the 48-commit arc is the same *order of magnitude* as the real ~7 observed — the model is
   in the right regime, not rigged.
2. **But the dollar-edge is BELOW 1.0× at the arc's coordinates (0.68–0.79×).** This is the punchline,
   and it is *more* credible than a forced win: docs/155's arc was **wide-but-SHORT**, and at a short
   horizon the defect-debt compounding that makes adjudication pay for itself (sweep [A]: edge climbs
   1.00× → 3.07× as horizon grows 1 → 40) **hasn't kicked in** — so on raw verified-velocity/$, DOS is
   net overhead *for an arc of exactly this shape*. **The benchmark, anchored, refuses to over-claim:**
   it says our friction was the *prevent-able kind but not yet the expensive kind* — a handful of
   re-fixes and one renumber, real but cheap, sitting *below* the horizon where adjudication pays off.
   That is a stronger result than "DOS would have 3×-ed the arc," because it is what the model actually
   reports at the real coordinates instead of the favorable cell.

### 6.4 The honest ceiling — what is and is NOT proven

- **PROVEN (mechanism):** *given* a fleet that lies at rate L and collides at rate C, adjudication
  recovers what a believing fleet loses — measured in FleetHorizon, and the direction is confirmed by
  the real arc's 10 %/hot-file data sitting where the model says it should (low-fleet, small gap).
- **NOT proven (live magnitude):** *would real parallel LLM agents on a real shared repo actually
  collide measurably less WITH the dogfood than without?* FleetHorizon's agents are **simulated**
  (deterministic lie/collide draws — by design, so the A/B is falsifiable; a live LLM makes the rates
  unrepeatable). So FleetHorizon proves the mechanism, **not the live magnitude** (the docs/145
  sim-vs-real wall). The real-incident anchor is **n=1** — it anchors C with a real number, it is not a
  statistical result.
- **The live experiment** (K real agents, a shared overlapping task, dogfood-arm vs ad-hoc-arm,
  measure collisions/rework/net-velocity) *would* prove the live half — but **defer it**, for three
  reasons: (a) the anchored run says the win at our scale is below 1.0× on velocity (short horizon), so
  the expected sign is *uncertain*, not clearly positive; (b) docs/143 already showed a *sound* verdict
  can be net-harmful if the intervention derails the agent, so it must measure *net arc velocity*, not
  just "fewer collisions" — a real paired campaign, not a demo; and (c, decisively) **the instrument
  does not exist yet** — all 57 arc commits are authored by one identity ("Claude"), so the live
  collision *rate* is unmeasurable until research agents stamp a `run_id` (commit trailer +
  measurements row). **So the live experiment's own prerequisite is the cheapest dogfood (the run_id
  stamp), which then lets the *next* real arc accrete attributed collision data for free** — run the
  live A/B only if that passive rate, plugged into FleetHorizon, predicts a materially large gap.
- **The pass@1-over-3-runs reframe is killed (not salvage).** "3 runs = a 3-agent fleet, pick the run
  whose effects are real" is **not** coordination — the runs share no mutable state, so there is no
  collision to prevent. "Pick the real-effects run" is just `verify()` applied 3× (the truth syscall,
  already proven) wearing a coordination costume; running it would measure the lane theory at ~0 and
  invite the exact mirror-verifier critique docs/143 warns against. The gym is the *subject*; the
  docs/143–155 arc that built it is the *fleet*.

**Verdict:** FleetHorizon (mechanism, proven + green) + the arc-mine anchored at the real coordinates
(prevention fires, dollar-edge < 1.0× because the arc was short — an honest, non-over-claimed magnitude)
+ the registry-as-prevented-error (the 13/26 drift would have collided at append time) is **sufficient
proof for the claim as scoped**: the mechanism is real and pays *at scale and long horizon*; at our
scale (wide-but-short) the lightweight convention is enough — which is *why* docs/155 ships the
convention and defers the `dos doc-claim` verb. The one cheap dogfood worth doing *now* is the `run_id`
stamp, because it is the live experiment's missing instrument and costs nothing.

**The one defensible sentence:** the coordination theory's **mechanism is proven on FleetHorizon**
(adjudication refuses the collisions + lies a believing fleet silently banks — 104 + 35 at long
horizon for a 1.34× verified-velocity edge — gap growing with fleet × horizon and → 0 at N=1); run
**at our arc's real coordinates** (wide-but-short) the prevention mechanism still fires (24 collisions
prevented) **but the dollar-edge is below 1.0× because the arc was too short for defect-debt to
compound** — so the honest reading is *our friction was the prevent-able kind, not yet the expensive
kind*; the only unproven half is the **live LLM magnitude**, whose missing instrument is the `run_id`
stamp, and which the model says is not worth an expensive run until a longer-horizon arc makes the gap
material.

**Cross-refs (proof):** the mechanism benchmark = `benchmark/fleet_horizon/` (+ docs/81 velocity,
docs/118 fleet-postmortem, docs/130 savings); the real-incident anchor rows = `measurements.jsonl`
(`arc_coordination_rework_rate`, `arc_hot_file_contention`); the sim-vs-magnitude wall = docs/145; the
single-agent-by-design ruling that excludes EnterpriseOps = docs/143 §5.4.

---

**Cross-refs:** the arc this came from = `docs/ENTERPRISEOPS_ARC.md`; the CAS primitive to reuse =
`src/dos/archive_lock.py`; the lane/lease the hot-file fix uses = `dos lease-lane` + docs/89; the
read-adjudicated-effects-not-claims thesis this applies to the builders = docs/116; the run_id join
that's already shipped = docs/137 (`dos trace`); the mechanism-vs-strategy split the decomposition
test echoes = CLAUDE.md.
