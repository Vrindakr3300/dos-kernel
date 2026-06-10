# From plan-lanes to concurrency-classes — a worked lesson in finding the generic concept

> **For someone new to DOS lane arbitration.** This note is not a spec — it is the
> *story* of how a single live failure exposed a confused abstraction, and how
> pulling on that thread led to the generic concept underneath. Read it to
> understand **why** the lane model is shaped the way it is (and where it is
> going), before you read the mechanism in [`89`](89_the-lane-is-a-region-lock.md)
> or the build plan in [`97`](97_concurrency-class-model-plan.md).

This is a companion to [`89`](89_the-lane-is-a-region-lock.md). Where 89 states
the *answer* ("a lane is a leased predicate-lock over a region"), this note shows
the *journey* to it from a concrete bug — because the value of the abstraction is
invisible until you have felt the pain it removes.

---

## 1. The incident (2026-06-01)

A `/dispatch-loop` was launched with no scope — "just work the next highest open
priority." It auto-picked a lane the arbiter called **`TM`** and spent **~$9 and
~40 minutes** launching a full dispatch child. The child shipped **nothing**, and
the post-mortem found *two* problems, both knowable at second zero:

1. **`TM` overlapped a live sibling.** Another loop already held the `tailor`
   cluster. `TM` is a *tailor plan* — its files live inside the tailor cluster's
   tree. The two loops were editing the same files; one of them was guaranteed to
   wedge. (It did.)
2. **The lane had been failing the same way for 8 runs.** A renderer bug was
   dropping a required artifact every single run; the loop had no way to know
   "this lane is sick, don't even start" — so it kept paying to re-discover it.

The first instinct was to fix the overlap math (the arbiter had *soft-admitted* a
25%-overlap that should have refused). That fix was real and shipped. But it only
raised the next question:

> **Why was a lane called `TM` competing with a lane called `tailor` for the same
> files in the first place?**

---

## 2. Pulling the thread: where does a lane named `TM` even come from?

The arbiter walks a **priority ladder** to auto-pick a lane for a bare request:

```
slot:P1  →  clusters  →  named  →  by_slot_then_status
```

The first three rungs are curated, designed regions: `apply`/`tailor`/`discovery`
(clusters), `recruiter`/`fleet`/`ui`/`auth` (named). Fixed, disjoint, sensible.

The **last rung is the surprise.** `by_slot_then_status` takes *every live plan in
the portfolio* — ~200 of them — and **mints one ad-hoc lane per plan**, named
after the plan's ID, with a file tree auto-derived from the plan doc. `TM`, `EV`,
`FRV`, … are not lanes anyone designed. They are *plans wearing a lane costume*
for the duration of one acquire.

And that is the whole bug, stated generically:

> **A "lane" was being used to mean two completely different things — a *designed
> disjoint region* (a cluster) and *an arbitrary plan that happens to have files*
> (a plan-lane) — and the second kind overlaps the first by construction.**

The lease system's entire correctness rests on lanes being disjoint. The
`by_slot_then_status` rung manufactures lanes that *violate that invariant*. Every
bug in the incident is downstream of that one conflation.

---

## 3. The confusion, measured

When you actually count, the shape of the problem is stark:

| Lane "kind" | What it really is | How many | Disjoint? |
|---|---|---|---|
| `cluster` | a designed region | 3 | yes (asserted) |
| `named` | a curated region | ~4 | yes |
| `slot` / `priority` / `derived` | **a plan with a tree** | **~125** | **no — 33 overlap a cluster** |

So the operator-facing question "what lanes exist right now?" had **no fixed
answer** — it was "three real ones, plus up to ~125 ghosts recomputed on every
acquire, a third of which collide with the real ones." That is not a model anyone
can hold in their head, and it is why the same class of overlap bug kept coming
back under a dozen different plan names.

---

## 4. The realization: separate the *label* from the two things that matter

Strip away every name — `cluster`, `named`, `priority`, `TM`. Ask what the
dispatch system actually *needs* from the thing it calls a lane. Exactly two
properties (this is the core insight of [`89`](89_the-lane-is-a-region-lock.md),
arrived at from the bug instead of from first principles):

1. **A disjoint region** to work in — so concurrent workers don't clobber each
   other's files and git index.
2. **A concurrency budget** — how many workers may hold a region of this *kind* at
   once.

Everything else is a *label on top of those two primitives.* The plan-lane
explosion happened because the code **conflated the label with the region**: a
cluster *is* its tree; a plan-lane *is* its plan. Untangle that, and the generic
concept appears:

> **A lane is a `(region, concurrency-class)` pair. Acquiring one is: "give me a
> free disjoint region from class X." The plan a worker drains is *payload* on the
> lease, not the lane's identity.**

This is exactly the region-lock framing of 89 — `region` is 89's leased
predicate-lock; `concurrency-class` is 89's "concurrency class" field — but now
with the missing piece the incident forced into view: **the class carries a
budget** (a max number of concurrent holders), and "priority work" is *one such
class*, not 125 one-off lanes.

---

## 5. Why this is the *generic* concept (and how the special cases collapse)

Once a lane is `(region, class)` and a class is `{name, region-source,
max_concurrent}`, the three hardcoded lane-kinds become three **instances of one
mechanism**:

| Today (special-cased) | Generic concurrency-class |
|---|---|
| `concurrent` clusters (3 fixed disjoint trees) | class `clusters`: region-source = the 3 curated trees, `max_concurrent = 3` |
| `exclusive` (`global`/`orchestration`) | class `exclusive`: `max_concurrent = 1`, region = whole workspace |
| `by_slot_then_status` (mint 125 plan-lanes) | class `priority`: region-source = "top pickable plan's tree, disjoint-checked", `max_concurrent = N` |

The thing you asked for — **"allow e.g. 3 priority lanes, the point is
concurrency"** — is not a new special case. It is just `class=priority,
max_concurrent=3`. "Match the cluster count" is `max_concurrent = len(clusters)`.
Adding a fourth class later (say `maintenance`) is **config, not code**. One
mechanism, expressed as data.

And critically, the concurrency is *preserved*, which the naive "collapse to a
single priority lane" idea would have thrown away: three priority workers can run
at once, each binding a *different* top-priority plan whose tree is disjoint from
the others — enforced at grab time by the same overlap test that fixed the
original bug. They **cannot** collide, because disjointness is checked when the
region is bound, not assumed from a name.

---

## 6. The litmus that keeps this honest (from 89 §4.4)

[`89`](89_the-lane-is-a-region-lock.md) §4.4 already gave the test for any "lane
feature," and it judges this exact design:

> *Is the property I'm adding a property of a leased predicate-lock over a region?*

- **"N concurrent holders of a contended class"** → **yes.** That is a lock
  manager's *concurrency budget on a contended resource* (intention locks, fair
  queuing). Borrow the proven shape.
- **"3 fixed lanes called priority-1/2/3"** → **no — that is the swim-lane error
  89 warns against** (a fixed lane count, lanes-can't-overlap-by-fiat). It would
  replace one special case (plan-lanes) with another (hardcoded slots).

So the design is "a `priority` **class** with `max_concurrent = 3`," and the slots
are *anonymous holders of that class*, bound to a disjoint region at grab time —
**not** three pre-named lanes. That distinction is the whole difference between
modeling the mechanism and modeling the metaphor, and it is why we planned the
generic model ([`97`](97_concurrency-class-model-plan.md)) instead of hardcoding
the slots.

---

## 7. The lesson, generalized

This is a reusable move, not a one-off:

1. **A live failure is the cheapest spec.** The $9 wedge told us more about the
   lane model than any amount of upfront design review — it pointed straight at
   the conflation.
2. **When the same bug recurs under many names, suspect a conflated abstraction.**
   "TM overlaps tailor", "EV overlaps tailor", "FRV overlaps apply" are not 125
   bugs; they are one bug — a lane-kind that violates the disjointness invariant
   the system depends on.
3. **Find the generic concept by deleting the labels.** Ask what the machine
   *needs*, not what the things are *called*. Here: a region + a concurrency
   budget. Everything else was a name.
4. **Preserve the property the mess was protecting.** The plan-lane explosion's
   one virtue was concurrency. The fix had to keep N-way parallelism while making
   the regions genuinely disjoint — not collapse to a single serialized lane.
5. **Check the new design against the existing law.** 89's litmus caught that
   "3 fixed priority lanes" would be a category error; the generic class-with-a-
   budget is the lock-legitimate shape. The law you already wrote is the guardrail
   for the next change.

---

## See also

- [`89_the-lane-is-a-region-lock.md`](89_the-lane-is-a-region-lock.md) — the
  primitive this builds on; a lane is a leased predicate-lock over a region. This
  note is the *worked example* that motivates 89 §4.2's "richer concurrency model"
  forward-pointer.
- [`97_concurrency-class-model-plan.md`](97_concurrency-class-model-plan.md) — the
  buildable plan: collapse `concurrent`/`exclusive`/`autopick` into a class
  registry with per-class `max_concurrent`; `priority` becomes one class.
- [`79_primitives-not-features.md`](79_primitives-not-features.md) — why the
  syscalls stay small so a buildable space (like a class registry) opens above
  them.
- `src/dos/lane_overlap.py` — the `REFUSE_EXACT_GLOB` floor (2026-06-01) that
  fixed the *immediate* overlap math; the generic class model is the *structural*
  fix above it.
- Job-side: `scripts/fanout_state.py` `_walk_priority_ladder` (the
  `by_slot_then_status` rung + the cluster-member defocus that stopped the
  bleeding) and `scripts/dispatch_lane_health.py` (the pre-dispatch gate the same
  incident produced).
