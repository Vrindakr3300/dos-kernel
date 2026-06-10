# The lane is a region-lock — name the primitive after its mechanism

> **A "lane" is not a track a worker runs in. It is a *leased predicate-claim
> over a region of the workspace*, admitted by predicate-disjointness. The
> swim-lane metaphor breaks at exactly the point the kernel's real work begins —
> and the cleaner name (a range/predicate lock, the database-locking primitive)
> reframes the one piece of `arbitrate` that looks like a fudge into the most
> defensible thing in it.**

A theory note in the family of [`79`](79_primitives-not-features.md) (the syscalls
are small so a buildable space opens above them) and
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) (every syscall is a kind of "no").
Where those zoom out to all four syscalls, this one zooms *all the way in* on a
single noun — `lane` — and asks what it actually is in well-understood systems.
The answer tightens the direction of every future `arbitrate`/lane change: it
tells you which properties a "lane feature" must have (those of a region-lock) and
which are category errors imported from a metaphor the code already outgrew.

It carries no litmus and is not in the `next-stage-plan` table. It is a *naming
correction*, not new mechanism — the mechanism it describes already ships
(`src/dos/arbiter.py`, `src/dos/lane_overlap.py`, `src/dos/_tree.py`,
`src/dos/lane_journal.py`).

---

## 1. The instinct: "lane" is *ever so slightly* off

The word feels wrong, and the wrongness is load-bearing — it points at what the
thing actually is. A traffic lane or a swim lane has two defining properties:

1. **Lanes are predefined and fixed in number.** A pool has eight. The set is
   closed and known before anyone swims.
2. **Lanes never overlap — by construction.** That non-overlap *is* the
   abstraction; it is why you can run eight swimmers at once without a referee.

The kernel's "lanes" have *neither* property:

- The contended objects are **open**, not fixed. A `keyword` lane's tree is
  computed from a `--scope` at request time; a `derived` lane is minted per-plan
  (`arbiter.py` legacy path). The `autopick` list is a fixed *menu of named
  tracks*, but the actual things being contended — the **trees** — are an open
  set the kernel never enumerates in advance.
- Lanes **can** overlap. The entire `lane_overlap.py` module exists *because they
  overlap* and a binary "any overlap = refuse" rule was provably too tight for
  narrow keyword lanes (`lane_overlap.py:6`). The module ships a **ratio
  threshold** (admit when ≤⅓ of the requested tree shares prefixes with a lease,
  `OVERLAP_RATIO_MAX = 1/3`).

The moment you write *a tolerated-overlap ratio for lanes*, the swim-lane metaphor
is dead. A swim lane with "30% overlap allowed" is not a lane. So the offness is
real, and it is precisely this: **"lane" promises a fixed set of non-overlapping
tracks; the kernel implements an open set of regions that contend on overlap.**

---

## 2. What a lane actually is, mechanically

Strip `arbitrate` to its bones. A lane is a tuple of:

| Field | What it is | Where |
|---|---|---|
| a **name** | identity for refusal messages + the journal (`apply`, `global`) | `config.py` `LaneTaxonomy` |
| a **`tree`** | a set of repo-relative path globs — *the real payload* | `arbiter.py:160`, `_tree.py:12` |
| a **concurrency class** | `concurrent` / `exclusive` / `autopick` | `config.py:79` |

And the one operation that matters does exactly one thing: **`arbitrate` admits a
new claimant iff its requested `tree` is provably disjoint from — or ≤⅓
overlapping with — every `tree` currently held** (`lane_overlap.py`, `_tree.py:60`).
Auto-pick, the priority ladder, the self-modify guard, the exclusive-lane
short-circuit — all of it is sugar on that single disjointness test.

Two consequences fall straight out, and both are the source of the felt wrongness:

- **A lane is not a process.** A process *holds* a lane (the lease carries a `pid`,
  `lane_journal.py:301`), but the lane outlives any process and is *scavenged* when
  the holder dies. The lane is the thing **being contended for**, not the thing
  doing the contending. "Lane" reads as an execution context (a track you run *in*);
  the kernel's lane is a **territory you claim**.
- **The `tree` is the lane.** The name is a label; the concurrency class is a
  policy bit; the `tree` is the resource. Everything `arbitrate` decides, it
  decides from trees.

---

## 3. The primitive's true name: a **leased predicate-lock over a region**

The closest match in well-understood systems is not lanes at all — it is the
**database locking** literature. A lane is a **named, leased lock whose
granularity is a *set of resources* (a region of the path namespace) rather than a
single row**, admitted by a **lock-compatibility test**. The correspondences are
exact:

| DOS | Locking world | Note |
|---|---|---|
| `tree` (path globs) | the **lock's coverage** | the set of objects it claims |
| disjoint-trees-admit (`lane_overlap`) | the **lock-compatibility matrix** | two locks coexist iff non-conflicting |
| empty tree ⇒ "unknown blast radius, refuse" (`_tree.py:63`) | the **coarsest lock** / `X` on the whole table | unknown scope ⇒ assume maximal |
| `exclusive` lane refuses everything (`arbiter.py:256`) | a **table-level exclusive lock** | `global` ≈ `LOCK TABLE … EXCLUSIVE` |
| `concurrent` lanes, disjoint trees | **range locks that don't intersect** | the normal parallel case |
| the lease (`pid`, `ttl`, `heartbeat`) | the **lock holder + lease/expiry** | a dead holder's lock is reclaimable |
| the journal (`lane_journal.py`) | the **lock manager's WAL** | stated outright at `lane_journal.py:13` |

But plain row-locking is not quite it, because the keys are not a fixed set of
rows — they are **globs over a namespace the kernel never enumerates**. That is
precisely **predicate locking** (System R) and its practical approximation,
**key-range / range locking** (the modern decidable form). A predicate lock claims
"every object matching this predicate"; two predicate locks conflict iff their
predicates can be *simultaneously satisfied by some object*.

`prefixes_collide` (`_tree.py:41`) **is** a predicate-intersection test: two
path-prefix predicates conflict iff one prefixes the other. General predicate
satisfiability is undecidable, so real systems conservatively over-approximate with
prefixes/ranges — which is *exactly* what the kernel did. The `**/*` → universal
(empty) prefix handling (`_tree.py:52`, `lane_overlap.py:64`) is the kernel patching
that over-approximation's one sharp corner: the broadest possible predicate must
read as "collides with everything," not "matches nothing."

So the honest one-line definition, the one this note exists to install:

> **A lane is a named, leased predicate-lock over a region of the workspace,
> admitted by predicate-disjointness. `arbitrate` is a lock manager whose lock
> granularity is a glob-set.**

---

## 4. Why this reframe *tightens direction* (the payoff)

A naming correction earns its keep only if it changes decisions. This one changes
four.

### 4.1 The ⅓ overlap threshold stops being a fudge

Under the swim-lane metaphor, `OVERLAP_RATIO_MAX = 1/3` reads as an embarrassing
hack — "lanes shouldn't overlap, but we allow a little." Under the lock metaphor it
is a **deliberately loosened lock-compatibility test**: the kernel admits two
*nearly*-disjoint region-locks because strict disjointness was empirically too
conservative for narrow keyword lanes (`lane_overlap.py:27`). That is a normal,
defensible thing a lock manager does (intention locks, soft-conflict tolerance) —
not a metaphor violation. **Direction:** the threshold is a *policy knob on a lock
compatibility function*, the right place to tune admission strictness; reason about
it as "how much predicate intersection do we tolerate," never as "how much may
swim-lanes touch."

### 4.2 The capability-lattice generalization is *the same primitive*

`arbiter.py:18` flags a future "capability-lattice generalization (every touchable
resource a lattice node; admit iff the requested capability set is *provably
disjoint*)" as a separate redesign sitting on top of the pure arbiter. The lock
framing says what that redesign actually **is**: it is **predicate-locking over a
richer lattice than path-prefixes** — swap the path-prefix predicate algebra
(`_tree.py`) for an arbitrary resource-lattice predicate algebra; `arbitrate`'s
admission logic is unchanged. **Direction:** do not design the lattice as a new
arbiter. Design it as a new **predicate algebra** plugged into the *existing*
disjointness gate — the same way a hardware `place()` verb would be "the pure
arbiter pointed at GPUs," not a second arbiter. The arbiter is already
the lattice lock manager; the lattice just needs its `prefixes_collide`.

### 4.3 The naming guidance: keep `lane` at the UX boundary, name the primitive in the kernel

`lane` is a *fine operator-facing word* — "which track do I take?" is exactly the
question a dispatcher asks, and the `autopick` ladder (walk a fixed, ordered menu
of named tracks to find a free one) **is** genuinely lane-like (pick an open
checkout lane). The offness lives entirely in the **kernel mechanism**, where the
primitive is a region-lock, not a track. So:

- **Do not churn-rename `lane` → `claim`/`lock` across the codebase.** The cost is
  high, the operator UX word is correct, and the lease vocabulary (`lease` = the
  *holding* of a lane) is already distinct and right.
- **Do name the primitive correctly where it is *defined and reasoned about*** —
  the kernel docstrings and the design law (done: `arbiter.py`, `_tree.py`,
  `lane_overlap.py` now point here; [[project-dos-kernel-design-laws]] carries the
  law). One word, two honest jobs: the **named track** (lane-ish, UX) and the
  **leased region-lock** (the kernel primitive). Naming the second one stops the
  two meanings from rubbing.

### 4.4 A forward litmus for "lane features"

Before adding anything to `arbitrate` or the lane taxonomy, ask the **region-lock
question, not the swim-lane question**:

> *Is the property I'm adding a property of a leased predicate-lock over a region?*

- **Yes** → it belongs, and the lock literature probably already names it (lock
  upgrade, intention locks, deadlock/wait-for, lease renewal, fair queuing on a
  contended region). Borrow the proven shape.
- **No, it's a swim-lane property** (a fixed lane count; lanes that can't overlap
  *by fiat*; a worker "assigned to" a lane as its execution home) → it is a
  category error; you are modeling the metaphor, not the mechanism. Stop.

This is the same move [`76`](76_flexible-goals-and-verification.md) makes for
goal/verify flexibility (it lives in provenance and which-signals, never the
adjudication): name where the give lives so future work stops trying to put it
where it doesn't belong.

---

## 5. Other systems that landed on the same shape (so the kernel is in good company)

The region-lock shape is not exotic — it is what every system that has to let
independent workers touch a shared namespace without a global lock converges on:

- **POSIX `fcntl`/`flock` byte-range locks** — a lock claims `[start, len)` of a
  file; two are compatible iff the ranges don't overlap. The kernel's tree is the
  multi-file generalization: byte-ranges → path-globs.
- **Deterministic databases (Calvin / Spanner-style sequencers)** — the sequencer
  decides a serial order *before* execution by inspecting each transaction's
  read/write **set**. `arbitrate` is a sequencer for file-write-sets: it serializes
  effects on shared state by refusing concurrent claims to intersecting write-sets,
  decided purely from declared sets — which is why `arbiter.py:6` can claim "almost
  no production OS scheduler has this property." It is the deterministic-DB
  admission trick applied to a fleet of agents.
- **Software Transactional Memory** — a commit succeeds iff its write-set doesn't
  intersect a concurrently-committed write-set. The same disjointness gate, at
  commit time instead of admission time.
- **k8s leader-election / resource leases** — named leases with holder + TTL +
  renewal. The kernel's lease *envelope* is this exactly — but a k8s lease is
  mutual-exclusion on a *single named thing* (one leader), whereas a lane is
  mutual-exclusion on an *overlap relation between sets*. Strictly more general.
- **cgroups / namespaces** — the near-miss worth stating to sharpen the contrast.
  A cgroup is "a named subtree of resources a set of processes is confined to" —
  nearly the taxonomy — but it is a *containment* boundary (you cannot escape it),
  while a lane is a *contention* boundary (you are *refused* if someone is there).
  **Containment vs. arbitration.** The kernel is arbitration; that is why a lane is
  a lock and not a cage.

---

## 6. The one-paragraph version

A lane *reads* like a track a worker runs in. It *is* a leased predicate-lock over
a region of the workspace: a name, a glob-set (`tree`) that is the real resource,
and a concurrency class — admitted by a conservative predicate-intersection test
(`prefixes_collide`) that over-approximates the undecidable general case exactly as
range-locking does. Keep `lane` as the operator's word for "which track," because
the `autopick` menu genuinely is one; but reason about the kernel mechanism as a
**lock manager whose granularity is a glob-set**, because that reframing turns the
⅓-overlap threshold from a fudge into a tuned compatibility function, turns the
capability-lattice from a new arbiter into a new predicate algebra on the old one,
and hands you the entire lock literature as the design vocabulary for whatever you
add next.

---

## See also

- [`96_from-plan-lanes-to-concurrency-classes.md`](96_from-plan-lanes-to-concurrency-classes.md)
  — the **worked lesson** that arrives at this note's primitive *from a live
  failure* (the 2026-06-01 plan-lane wedge). Read it for the "why this matters"
  story; it is the motivating example for §4.2's "richer concurrency model".
- [`97_concurrency-class-model-plan.md`](97_concurrency-class-model-plan.md) — the
  **buildable plan** that realizes §4.2/§4.4 here: collapse the three hard-coded
  concurrency-kinds into a class registry with per-class `max_concurrent`, so
  "N priority slots" is `class=priority, max_concurrent=N` (a lock-manager
  concurrency budget) rather than a fixed lane count (the §4.4 swim-lane error).
- [`CLAUDE.md`](../CLAUDE.md) — the architecture contract; `arbitrate` is "the pure
  admission kernel." This note names the *primitive* that admission kernel locks.
- [`79_primitives-not-features.md`](79_primitives-not-features.md) — why the
  syscalls are small; `arbitrate` is the row whose "what it makes buildable" is
  "every lease scheme, fairness policy, capability lattice."
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
  — `arbitrate` as a *no* ("no, you may not touch this"); this note says *what* the
  "this" is.
- [`102_when-to-trust-an-agent.md`](102_when-to-trust-an-agent.md) §5 — the audit
  finding this note's §5 (the Calvin/OLLP gap) sets up: the arbiter trusts the
  agent's *declared* tree at contention but only checks conformance post-hoc, so for
  an irreversible clobber it does collision-*detection* where the trust law demands
  collision-*prevention*. The principled fix (a binding pre-effect scope gate).
- `src/dos/arbiter.py`, `src/dos/lane_overlap.py`, `src/dos/_tree.py` — the
  region-lock mechanism; their docstrings now point here.
