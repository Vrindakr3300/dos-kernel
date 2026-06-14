# 330 — isolated merging: the joint-merge floor (the stale-witness catch)

> **Status:** Design plan + a runnable spike (§7). Proposes ONE new kernel leaf
> (`dos.jointmerge` — *may this SET of branches merge, and in what ORDER?*) that
> sits one level above the shipped per-branch `dos merge-gate` (docs/327 Phase 1).
> Re-grounded against `src/dos/mergegate.py` + `src/dos/drivers/merge_gate.py` at
> HEAD (2026-06-13). Two axes: the **trust** side (re-witness the combined tree,
> §0–§3) and the **data** side (a held verdict carries the resolution packet that
> makes the downstream agent good at the merge, §4). The spike is ~40 lines, no
> I/O, and settles the load-bearing claim before any build.
>
> **One line:** `merge-gate` proves each branch is clean *against the tree it was
> born on*. The instant a sibling lands, that proof is a **self-report about a
> tree that no longer exists** — and believing a stale witness is the exact thing
> the kernel exists not to do. The joint-merge floor is the kernel re-deriving the
> merge-bit on the **combined** tree, in a **witnessed order**.

---

## 0. The angle — "isolated merging" is an unguarded surface, and it is trust-shaped

The operator's framing: make **multi-agent isolated merging safe** — a different
angle of attack to win the space. Take it literally. The shipped story closes two
surfaces and leaves the one *between* them open:

| Surface | Owned by | Question it answers |
|---|---|---|
| **Spawn** — two agents, same region, now | `arbiter` / `_tree` (docs/211) | *may these two AGENTS work concurrently?* |
| **One branch's merge** | `merge-gate` (docs/327) | *may THIS branch merge — on its own tree?* |
| **The joint merge** ← **unguarded** | *nothing* | *may these N green branches BECOME one trunk — and in what order?* |

The third surface is where "isolated" turns dangerous. Isolation is what makes
each branch's witness **local**: `merge-gate` runs the suite on the *candidate
worktree* — `trunk@spawn + branch` — never on `trunk@now + branch` (read
`src/dos/drivers/merge_gate.py:131-133`: `gather_suite()` is called once, on the
one candidate context; there is no "already-merged-ahead-of-you" input). So:

> **N branches each pass `merge-gate`. Each green checkmark was earned on a
> different tree. The merged trunk was witnessed by no one.**

This is not a textual-conflict problem — git's three-way merge can succeed with
zero conflict markers and still produce a broken trunk. It is a **witness-
staleness** problem, and that is precisely the kernel's department: a green result
from a branch's pre-merge run is a *self-report about a superseded tree*. The
industry answer (merge queues — GitHub merge queue, Mergify, Zuul, Bors) solves
the mechanics by re-running CI in sequence, but frames it as *CI orchestration*,
not as *distrust of a stale witness*. DOS reframes the merge queue as an instance
of its one thesis — **the kernel is the part that doesn't believe the agents** —
and inherits the worktree-as-evidence-substrate (docs/327) for free. That reframe
is the win: not a better CI runner, a *soundness floor* the CI runner lacks.

---

## 1. The three failure modes a per-branch gate cannot see

All three pass `merge-gate` on every individual branch and still break the trunk.
Each is a distinct refuse cause the joint floor must name.

1. **STALE_BASE** — A and B both green on `trunk@spawn`. A merges. B's suite was
   never run on `trunk + A`. B merges textually clean; the combined suite is red.
   *The witness B carried certifies a tree that no longer exists.* This is the
   STORM/DeLM "defers conflict resolution to a post-hoc merge step" the
   [FAQ](FAQ.md) already cites — but at the **witness** level, one layer below
   the textual level everyone means by it.

2. **DISJOINT_BUT_DEPENDENT** — A renames `helper()`; B (different files, so the
   arbiter ruled the regions *disjoint* and admitted both — correctly, for
   *spawn*) adds a new caller of `helper()`. Zero textual conflict. Broken trunk.
   *Spawn-disjointness is necessary but NOT sufficient for joint mergeability* —
   the arbiter's tree-disjointness (`_tree.lane_trees_disjoint`) is a statement
   about **edit locations**, never about **semantic dependence**. The joint floor
   is where that gap is closed, by re-witnessing — never by trying to *predict*
   the dependence (which would be unsound; see §4).

3. **ORDER_DEPENDENT** — `{A then B}` is clean but `{B then A}` refuses (B's
   migration assumes A's column). A merge queue that integrates in arrival order
   merges the broken order half the time. *Order is a free variable the fleet
   currently resolves by accident.*

The unifying observation: **a branch's merge-bit is only valid relative to a
specific base, and isolation guarantees that base is stale by merge time.** The
fix is not to make the branch's witness smarter — it is to **re-derive the
witness on the actual combined tree**, which is exactly what the kernel already
does for a single branch, lifted to a serialized set.

---

## 2. The leaf — `jointmerge.plan`: serialize a SET into a witnessed order

A new pure kernel leaf, sibling to `mergegate` (not a wrapper — same reason
`mergegate` is not `improve` re-aimed: the verdict shape differs). It does **not**
run anything. It is the pure adjudicator that, given the per-step re-witnessed
results the driver gathers, decides the **admission order** and which branches are
**held back**.

```
jointmerge.plan(
    candidates: list[BranchId],          # the green-per-branch set, declared regions attached
    rewitness: Callable                  # injected: (already_merged, next_branch) -> JointEvidence
) -> JointPlan
```

The shape mirrors the layering exactly:

- **Kernel leaf (`dos.jointmerge`)** — PURE. Owns the *serialization policy* and
  the *fold*: given the sequence of per-step `MergeEvidence` (each produced on the
  real combined tree), it emits an ADMITTED order + a HELD set with typed causes.
  No I/O, no git, no clock — `classify`-shaped like every leaf.
- **Driver (`dos.drivers.joint_merge`)** — gathers. For each candidate the leaf
  asks to test-next, it **materializes `trunk + already-merged + candidate` in a
  worktree** (the docs/327 evidence substrate — the combined tree is *real*, not
  predicted) and runs the same `run_gate` witness bundle on it. This is the only
  layer that touches git.

The decisive property carries up from `merge-gate` unchanged: **the joint merge-
bit is a function of env-authored witnesses on the real combined tree, never of
any branch's claim.** A branch cannot narrate its way into the trunk, and now it
cannot *ride a stale green checkmark* into the trunk either.

### The serialization rule (the policy the leaf owns)

Greedy, witnessed, abstention-first:

```
admitted = []                  # the trunk-in-progress
held     = []                  # branches that refused at their turn
pool     = candidates
while pool:
    progressed = False
    for b in pool:             # try each remaining branch against the CURRENT trunk
        ev = rewitness(admitted, b)        # re-run the floor on trunk+admitted+b — REAL tree
        if mergegate.classify(ev).is_clean:
            admitted.append(b); pool.remove(b); progressed = True
            break              # commit it, re-test the rest against the new trunk
    if not progressed:         # no remaining branch is clean on the current trunk
        held += pool; break    # hold them ALL back with their refuse causes
return JointPlan(order=admitted, held=held)
```

Why greedy-with-restart and not "find the optimal order": optimality over N
branches is the topological-sort-with-conflicts problem (NP-hard in the
adversarial case). The kernel does not need optimal — it needs **sound**: every
branch in `order` was *witnessed clean on the exact trunk it will land on*, and
every branch in `held` *demonstrably could not be made clean against the trunk the
admitted set produced*. A held branch is not "rejected forever" — it is **refused
with a re-derivation tax owed** (docs/324): rebase onto the new trunk and re-enter.
That is the honest verdict; promising an optimal global order would be the
metaphor outrunning the mechanism (docs/114).

---

## 3. The typed refuse causes (the closed vocabulary this leaf adds)

The per-step verdict is the *existing* `mergegate.RefuseCause` (SUITE_RED,
TRUTH_DIRTY, AUDIT_UNWITNESSED, TEST_NOT_WITNESSED) — re-witnessing on the combined
tree reuses the same floor, so no new *rung* is invented. What the joint leaf adds
is the **set-level** outcome for a held branch, which the per-branch gate has no
vocabulary for:

The two are distinguished by a **witnessed probe**, not an assumption — when a
branch is held, the fold re-witnesses it against the *empty* trunk to learn which
it is (the §7 spike forced this; an earlier draft assumed it and was wrong):

- **`STALE_BASE`** — the held branch is clean on the empty/early trunk but red on
  `trunk+admitted`. Its green checkmark *expired* as a sibling landed. The honest,
  un-alarming name: a sibling moved under it. Routes to: rebase + re-enter (the
  cheapest recovery, paid at the right moment). **This is also the verdict for a
  2-cycle** — when A and B each refuse on the other, the greedy fold admits one and
  the other becomes STALE_BASE, *not* a deadlock: one simply lands first and the
  other rebases onto it. (The §7 spike pins exactly this — a 2-cycle is *not*
  mutually exclusive; it is a one-lands-one-rebases.)
- **`MUTUALLY_EXCLUSIVE`** — the held branch is red **even on the empty trunk**: it
  is broken on its own, or genuinely cannot land without human reconciliation (its
  green never existed — no rebase fixes it). This is the *narrow* case the name was
  meant for. Routes to: `dos decisions` (an operator gate — the kernel refuses to
  *guess* a fix it cannot witness).

Keeping these distinct matters: most "held" branches are `STALE_BASE` (a cheap
rebase), and only the rare genuinely-broken branch is `MUTUALLY_EXCLUSIVE` (a human
gate). Collapsing them — the easy mistake — would route every stale branch to a
human and make the floor look far more blocking than it is.

These are **set-level refuse reasons**, candidates for the closed `[reasons]`
vocabulary (`dos_refuse_reasons`), so a held branch refuses *structurally* — an
A2A peer reads `STALE_BASE` and knows the exact unblock, instead of parsing prose.
This is the docs/120 fail-closed digest applied to the merge surface.

---

## 4. The data side — a held verdict is a RESOLUTION PACKET, not a dead end

> **Operator point (2026-06-13): agents are good at handling merges *iff they
> have the right data*. So solve it from the data side as well as the
> trust/witness side — and wire their relation.**

This is the half that turns the floor from a *gate* into a *substrate an agent can
act on*. The two sides are not separate features — they are **the same artifact
read twice**:

> **The witness that REFUSES a branch IS the data that RESOLVES it.** When
> `rewitness(admitted, B)` returns SUITE_RED on the combined tree, that one
> env-authored run already contains everything the resolving agent needs. The
> kernel's job is to *not throw it away* — to hand the held branch the packet
> instead of a bare "refused."

### Why this is load-bearing, not a nicety

A bare "merge refused" forces the resolving agent to **re-derive the whole
context from scratch**: re-clone, guess the base, re-run the suite, bisect to find
which sibling broke it, diff to find the symbol. That is the docs/324
re-derivation tax — and isolation makes it *worse*, because the agent's own
worktree no longer reflects the trunk it must merge onto. The kernel already paid
that cost *once* when it re-witnessed (§2). Discarding the result and making every
held agent re-pay it is the waste the data side removes. **An agent with the
packet does the merge in one shot; an agent with "refused" does archaeology.**

### What the packet carries (each field is the by-product of a witness already run)

The held verdict (`HeldBranch`) carries a `ResolutionPacket` — every field
authored by the *same re-witness run* that produced the refuse cause, so it costs
nothing extra to emit:

| Field | What it is | Which witness authored it | What the agent does with it |
|---|---|---|---|
| `landing_base` | the real `trunk + admitted` SHA the branch must rebase onto | the serialization fold (§2) — the trunk-in-progress | **rebase onto the base it never had** (the missing datum that caused STALE_BASE) |
| `failing_witness` | which test failed + its output, on the combined tree | `gather_suite` on `trunk+admitted+b` | go straight to the broken behavior — no bisect |
| `culprit_delta` | the diff of `admitted` *since the branch's spawn base* | `git_delta` over the two known SHAs | **see exactly what changed under its feet** — the DISJOINT_BUT_DEPENDENT rename, the migrated column |
| `conflict_locus` | the file(s)/symbol(s) the branch and `admitted` both touch | `_tree` intersection of declared regions ∩ the failing diff | scope the fix to the real collision, not the whole tree |
| `refuse_cause` | the typed `STALE_BASE` / `MUTUALLY_EXCLUSIVE` (§3) | the floor | route the work (rebase-and-re-enter vs escalate-to-human) |

Every one of these is a **fact the kernel already computed to reach its verdict**.
The data side is not new gathering — it is *retaining and shaping* the gather the
trust side already did. That is the relation the operator named: trust and data
are dual readings of one re-witness.

### Provenance is part of the data (the trust side guards the data side)

The packet is *data handed to an agent*, so it inherits the kernel's discipline:
every field is **env-authored and carries its source** (the SHA, the test name,
the diff are git/runner artifacts, not narrated). An agent acting on the packet is
acting on witnessed facts, never on a sibling branch's *claim* about what it did.
This closes the loop both ways:

- **Trust → data:** the re-witness that *refuses* the stale branch is what
  *produces* the resolution facts. No refusal, no packet.
- **Data → trust:** an agent that resolves using the packet produces a *new*
  branch, which re-enters the floor and is **re-witnessed from scratch** — the
  packet bought it a head start, not a free pass. The resolved branch earns its
  merge-bit the same way every branch does. The data side accelerates the agent;
  it never lets the agent *skip* the witness.

So the two sides compose into a sound loop: **witness → refuse-with-packet →
agent-resolves-fast → re-witness → admit.** The kernel is the part that doesn't
believe the agent *and* the part that hands the agent exactly the data it needs to
become believable. (Honest boundary: the kernel *assembles* the packet from
witnessed facts; it does not *resolve* the merge — resolution is the agent's work,
and the resolved branch is re-adjudicated, never trusted. PDP-no-PEP holds.)

### `[jointmerge]` policy: how much packet to assemble

Assembling `culprit_delta` / `conflict_locus` is cheap (diffs over known SHAs) but
not free at scale, so the *depth* of the packet is config-as-data, not mechanism:
a host arms `resolution_packet = full | base_only | none` in `dos.toml
[jointmerge]`. `base_only` (just `landing_base` + `refuse_cause`) is the floor that
makes rebase-and-re-enter possible; `full` adds the culprit diff + locus for an
agent that resolves autonomously. The floor's *soundness* never depends on the
packet depth — the packet only changes how fast the held agent recovers, never
whether a branch is admitted.

---

## 5. The mechanism-vs-metaphor line (docs/211 discipline)

Mark it honestly, per the rule that keeps this repo's claims behind its mechanism:

**What is real mechanism:**
- The combined tree `trunk + admitted + b` is **materialized and witnessed**, not
  modeled. The merge-bit is env-authored on the actual bytes that will land. This
  is sound — it is just `merge-gate` run on a different (real) base.
- The serialization is **deterministic** given the rewitness callback: same
  candidates + same trees → same order + same held set. Replayable, auditable.
- HELD is **abstention-first**: a branch is held on *witnessed* failure or on
  *no clean order existing*, never on a guess.

**What is explicitly NOT claimed (the metaphor we refuse):**
- The leaf does **not predict** semantic conflicts. DISJOINT_BUT_DEPENDENT (§1.2)
  is caught **only because the re-witness runs the suite on the combined tree** —
  not because the kernel understood the rename. Any "we detect semantic conflicts"
  claim would be the branding outrunning the mechanism (docs/114). The kernel
  detects them the only sound way: by *running the combined result and reading the
  exit code*.
- It does **not** find the optimal order (§2) — only a sound one, or an honest
  "no clean order exists."
- It is **advisory** (PDP-no-PEP, like every verdict leaf): `plan` REPORTS the
  order + held set; the driver actuates the merges. The kernel never runs
  `git merge`.
- Cost is real and stated: re-witnessing is **O(N²) suite runs worst case** (each
  of N admissions re-tests the remaining pool). The mitigation is policy, not
  mechanism — `[jointmerge]` config can cap the pool size that triggers full
  re-witness, or arm a cheap **pre-filter** (textual-disjoint AND import-graph-
  disjoint ⇒ skip re-witness for that pair) that can only *skip a known-safe
  re-run*, never *admit* a branch (refuse-more-only, the docs/211 overlap-policy
  floor). The floor stays sound; the optimization only removes provably-redundant
  work.

---

## 6. Why this is the winning angle, not just another verb

Three reasons it is positioning, not feature-creep:

1. **It closes the one surface the shipped story leaves open.** docs/327's own
   table ends at "merge as an admission gate" *for one branch*. The joint surface
   is the natural completion — and it is the surface the operator named.

2. **It reframes a known category as a trust problem.** Merge queues exist
   (GitHub, Mergify, Zuul, Bors) and are *infrastructure* — they assume a CI farm
   and frame the job as orchestration. DOS reframes it: a pre-merge green check is
   a **stale self-report**, the merged trunk is the **unwitnessed artifact**, and
   the kernel's identity is re-deriving the bit from the environment. No merge
   queue ships with "the part that doesn't believe the branch" as its thesis. That
   reframe travels to audiences a CI tool cannot reach (the docs/answers GEO
   surface, the AEO thread).

3. **It is ~all re-aim.** The per-step witness IS `run_gate` (docs/327, shipped).
   The combined-tree materialization IS the worktree evidence substrate (docs/327,
   shipped). The disjointness pre-filter IS `_tree.lane_trees_disjoint` (shipped).
   The only genuinely new code is the **pure serialization fold** (`jointmerge.plan`,
   ~40 lines) + its driver. The kernel earns a new surface for one small sound leaf.

---

## 7. The spike — RUN, green, and it corrected this doc once

The claim the whole doc rests on: **a greedy witnessed serialization is sound
(every admitted branch was clean on its real landing tree) and order-aware (it
finds a clean order when one exists, holds the rest with the *right* typed cause,
and admits a correct no-op set)** — provable as a pure fold over a *fake*
rewitness oracle, before any git.

**Status: written and run.** `.dos/scratch/jointmerge_spike.py` embeds the
candidate `jointmerge.plan` fold verbatim (prove-then-place, the docs/92 / docs/327
§6 discipline) and drives it with a fake `rewitness(frozenset(admitted), branch) ->
clean?`. All five cases are green:

- **STALE_BASE replay** — A,B both clean on `{}`, B red on `{A}` → admits `[A]`,
  holds `[B:STALE_BASE]`. The per-branch gate would have merged *both*; the joint
  floor catches what it structurally cannot.
- **ORDER_DEPENDENT replay** — B clean only on `{A}` → finds `[A, B]` for *both*
  input orders `[A,B]` and `[B,A]`. Proves order-discovery is input-order-blind.
- **2-cycle** — A red on `{B}`, B red on `{A}`, both clean on `{}` → admits `[A]`,
  holds `[B:STALE_BASE]`. **Not** a deadlock: one lands, the other rebases.
- **TRULY_UNMERGEABLE** — X red on *every* base → admits the rest, holds
  `[X:MUTUALLY_EXCLUSIVE]`. The narrow human-gate case, kept distinct.
- **ALL_DISJOINT no-op** — all clean on every subset → admits all 4, holds none.
  The `mergegate`-vs-`improve` no-op-merges property, carried to the set.

**What the spike corrected (the doc followed the witness, not the reverse):** the
first draft of §3 called the 2-cycle `MUTUALLY_EXCLUSIVE` ("no order clears the
pool → send to a human"). Running the fold showed that is wrong and *needlessly
alarming* — the greedy fold admits one arm and the other is a cheap `STALE_BASE`
rebase. The honest distinction — `STALE_BASE` (clean on empty, a sibling expired
it) vs `MUTUALLY_EXCLUSIVE` (red on empty, broken on its own) — is a **witnessed
probe against the empty trunk**, which the fold now runs when classifying a held
branch. §3 was rewritten to match. This is the docs/327 §6 result repeated: the
cheap no-I/O spike paid for itself by catching a wrong verdict before any driver
code existed.

---

## 8. Buildables ranked

1. **`jointmerge.plan` leaf + spike** (this doc §2/§7) — the pure fold + the
   no-I/O proof. Highest payoff: it is the whole soundness claim, ~40 lines, and
   it is the surface the operator named. **Build first.**
2. **`dos.drivers.joint_merge` engine** — the gather: materialize `trunk+admitted+b`
   in a worktree, run `run_gate` on it, feed the leaf. Re-aim of `merge_gate.run_gate`.
3. **`dos join-merge` CLI verb + `[jointmerge]` config** — exit 0 if a clean full
   order exists, 3 if any branch held; `--json` emits order + held-with-causes.
   The pre-filter knob lives here (refuse-more-only).
4. **`STALE_BASE` / `MUTUALLY_EXCLUSIVE` in the `[reasons]` vocabulary** — make the
   held verdict a structured A2A refusal (`dos_refuse_reasons`), not prose.
5. **`ResolutionPacket` on the held verdict** (§4, the data side) — retain the
   `landing_base` / `failing_witness` / `culprit_delta` / `conflict_locus` the
   re-witness already produced, gated by `[jointmerge] resolution_packet`. Build
   #5 because it rides on #1–#3's witnesses (no new gather); it is what makes the
   held agent *fast*, the operator's data-side ask. The `base_only` floor lands
   with #2 (the engine already knows `landing_base`); `full` follows.

§1–§7 stand on their own as the position even if only build #1 ships; the leaf is
the part that makes "isolated merging" *sound*, build #5 is what makes resolving a
held branch *fast*, and the rest is actuation.
