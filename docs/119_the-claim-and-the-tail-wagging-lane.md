# 119 — The claim, and the tail wagging the lane

> **Status:** design plan. Phase 0 (the `UNKNOWN_LANE` honesty fix) is SHIPPED
> (`bc83d94`). Phases 1–4 are unbuilt; this doc is the argument for them and the
> seam they share.
>
> **One line:** A *lane* is a named, pre-registered tree. The fleet jams when the
> work has a well-defined **region** but no pre-registered **name** — so the
> kernel should adjudicate the **claim** (the region + the intent) directly, and
> treat the lane name as an *optional handle*, not a precondition. The lane was a
> convenience that became a requirement; that inversion is the tail wagging the
> dog.

---

## 0. The field report that triggered this

A fleet operator, looking for a disjoint apply-adjacent lane to dispatch onto,
found there was no good answer:

| Apply plan | Lane | Pickable? | Why not |
|---|---|---|---|
| AFR (fill reliability) | `apply` | ❌ | collides with live ASI on `agents/apply_*.py` |
| ALO (observability) | `apply` | ❌ | same collision; also MAINTENANCE |
| SAS (synthetic shadow) | `apply` | ❌ | same collision |
| ANC/60 (apply-core) | `apply` | ❌ | this IS what ASI is running |
| PLA (priority-lane tick) | `orchestration` | ❌ | exclusive lane (the shared spine) |
| PMA (postmortem route) | — | ❌ | PARK |
| playbooks (ATS form-fill) | — | ❌ | **not a registered lane → degrades to a random non-apply lane (CID)** |

Two failures are braided here, and they live at *different levels of the stack*.
The operator's instruction — "don't shoehorn into lanes; go up and down the stack
for tail-wag issues" — is the correct diagnosis. This doc separates the levels.

### The two failures, by level

* **L0 — kernel honesty (a bug).** The `playbooks` row. An unregistered lane name
  with a resolvable-but-unregistered region was *silently substituted* for a
  different free lane (CID). The lease then described CID's tree while the agent
  intended `playbooks/**`, so disjointness guarded the **wrong region**. Fixed in
  Phase 0: an explicit keyword naming an unknown lane now `refuse`s
  (`UNKNOWN_LANE`) instead of guessing. This was the docs/103 disease turned
  inward — the kernel narrating an `acquire` for a region it was never asked
  about.

* **L1 — the abstraction (a design limit).** Even with `playbooks` correctly
  refused, *there is still no disjoint apply-adjacent lane*, because the disjoint
  region (`playbooks/`) **is not a lane at all**. The work has a perfectly
  well-defined, provably-disjoint blast radius — and the kernel cannot admit it,
  not because it collides, but because **nobody pre-registered a name for it.**
  That is the tail wagging the dog.

* **L2 — the host's shared file (a different mechanism entirely).** Raising the
  ceiling to 4 caused `execution-state.yaml` write-contention (6 consecutive
  `WinError 5` failed lease-releases). That is not the picker. It is a host-side
  shared mutable file taking concurrent writes *that nothing arbitrates* — the
  `[unbounded-growth]` shape (a shared surface with no region-lock on **itself**).
  Addressed separately in §5; it is a driver concern, not a kernel one.

The rest of this doc is mostly about **L1**, because L1 is where the abstraction
is wrong and where the durable fix lives.

---

## 1. What a "lane" actually is (read the type)

`arbiter.arbitrate()` already takes the region as a first-class argument,
*separate* from the name:

```python
def arbitrate(*, requested_lane: str, requested_kind: str,
              requested_tree: list[str], live_leases, ...): ...
```

The disjointness algebra (`_tree.lane_trees_disjoint`) operates **entirely on
`requested_tree`**. It never consults the lane name. The name is used for exactly
three things:

1. a display/journal handle (`lease.lane`),
2. a *lookup key* into the taxonomy to **resolve a tree** when the caller didn't
   supply one (`_cluster_tree`), and
3. membership tests for exclusivity / known-ness (`exclusive_lanes`,
   `_known_lane_keys`).

So the operative truth is:

> **A lane is a named, pre-registered tree.** The *tree* (the region) is the
> substance the kernel actually adjudicates. The *name* is a convenience handle
> and a way to omit the tree.

The `playbooks` jam is now explicable in one sentence: **the substance was
present and disjoint (`playbooks/**`), but the handle was absent, and the kernel
made the handle a precondition for adjudicating the substance.** That is the
inversion. The kernel built to adjudicate *regions* refused a perfectly good
region because it lacked a *name* — a property that has nothing to do with
collision-safety.

### Why this matters beyond one fleet

Pre-registration is a **static-taxonomy assumption**: it presumes the set of
regions a fleet will contend over is known and enumerated ahead of time, in
`dos.toml`. But agent fleets are *dynamic*: a replan invents a new plan, a
postmortem proposes a new surface, a playbook touches a tree no one anticipated.
Every time the work outruns the taxonomy, the operator must stop, edit
`dos.toml`, and re-dispatch — or (worse, pre-Phase-0) the kernel silently
mis-adjudicated. The taxonomy is a cache of anticipated regions, and **the fleet
keeps missing the cache.**

---

## 2. The reframe: adjudicate the *claim*, not the lane

Define the thing the kernel should actually take as input:

> **A claim is `(region, intent, holder)` — a request to hold a leased region of
> the workspace for a stated purpose.** The region is a tree (globs). The intent
> is metadata (a plan id, a kind, a value hint). The holder is a run-id.

A **lane** is then just *a claim whose region was pre-named in the taxonomy.* It
is one constructor for a claim, not the only one. The kernel's job — the thing
it is uniquely good at — is **adjudicating whether a claim's region is admissible
against the live set** (disjoint under the floor, not self-modifying, under
budget). That job is *already* region-based and name-agnostic. We have been
forcing every claim through the one constructor (a pre-registered name) that
happens to have a static-taxonomy precondition.

The fix is to make the **ad-hoc claim** a first-class citizen alongside the
**named lane**:

| Constructor | Region comes from | Pre-registration | Today |
|---|---|---|---|
| Named lane (`--lane apply`) | taxonomy lookup | **required** | the only blessed path |
| Ad-hoc region (`--tree playbooks/**`) | the caller, directly | **none** | possible but second-class (empty-name handling is awkward; no journal identity; not in `dos doctor`) |

The kernel *already supports the second row mechanically* — and more completely
than "supports" suggests. Verified live (2026-06-03): a fully **unnamed** claim
(`requested_lane=''`, `requested_kind='keyword'`, `requested_tree=[…]`) is already
adjudicated end-to-end —

```
arbitrate(lane='', kind='keyword', tree=['agents/apply_obs.py'],  live=[asi:apply_fill.py]) -> acquire
arbitrate(lane='', kind='keyword', tree=['agents/apply_fill.py'], live=[asi:apply_fill.py]) -> refuse
        ("lane '' cannot share live lane 'asi': exact-glob overlap: identical glob claimed")
```

The disjoint unnamed claim acquires; the colliding one refuses with a precise
reason. So the *admission* of an ad-hoc region is not a gap at all — it works
today. What is missing is purely the **identity and ergonomics**: the lease comes
back with `lane=''`, so it cannot be journaled with a stable handle, shown in
`dos top`, or referenced by a later `dos resume`. **The region is adjudicated; the
claim is anonymous.** That — not admission — is the gap Phases 1–2 close.

---

## 3. Going UP the stack: the claim is the durable surface, the lane is a view

Up-stack from the arbiter sit the durable surfaces (the WAL, the intent ledger —
docs/107) and the operator projections (`dos top`, `dos decisions`, `dos plan`).
All of them key on the **lane name**. So an ad-hoc region, even when correctly
admitted, is a second-class citizen *everywhere up the stack*: it has no row in
`dos top`, no lease identity in the WAL beyond an empty string, no handle for
`dos resume`.

The durable fix is to **make the claim the journaled unit and the lane a derived
view over it.** Concretely:

* The WAL records a **claim**, whose identity is `(run_id, region-digest)` — a
  stable hash of the normalized tree prefixes (`_tree.norm_tree_prefix` folded and
  sorted). A named lane's claim additionally carries `lane=<name>`; an ad-hoc
  claim carries `lane=""` but is *still fully identified* by its region-digest. No
  claim is anonymous.
* `dos top` / `dos decisions` group by region-digest, displaying the lane name
  when present and a short region summary (`playbooks/… +2`) when not. An ad-hoc
  claim is visible, leased, and attributable — it just shows its region instead of
  a name.
* `dos resume` (docs/107) can re-aim an ad-hoc claim because the region-digest is
  the durable key, independent of whether a name was ever assigned.

This is the **inversion undone**: the region (the substance) becomes the durable
identity; the name (the handle) becomes optional decoration. The taxonomy stops
being a *gate* and becomes what it always should have been — *a dictionary of
convenient names for common regions.*

> **Design law (proposed, joins `project-dos-lane-is-a-region-lock`):** *The
> durable identity of a lease is its region, not its name.* A name is a cache key
> for a region, never a precondition for adjudicating one. The kernel adjudicates
> regions; names are an operator convenience layered on top.

---

## 4. Going DOWN the stack: the region is *declared* too coarse (verified)

Down-stack from the arbiter sits `_tree` — the prefix algebra. Here is the second
half of the `apply` jam, and it is **not** a naming problem. But the precise
mechanism is subtler than "the prefix rule is imprecise," and it was worth
*executing* rather than asserting — the first draft of this section got it wrong.
Run against the live algebra (`PYTHONPATH=src python -c …`, 2026-06-03):

```
norm_tree_prefix('agents/apply_*.py')   -> 'agents/apply_'
norm_tree_prefix('agents/apply_fill.py')-> 'agents/apply_fill.py'
norm_tree_prefix('agents/apply_obs.py') -> 'agents/apply_obs.py'

lane_trees_disjoint(['agents/apply_fill.py'], ['agents/apply_obs.py']) -> True   # DISJOINT
lane_trees_disjoint(['agents/apply_*.py'],    ['agents/apply_fill.py']) -> False  # COLLIDE
```

So the correction: **two sibling apply-family *files* do NOT collide today.**
`apply_fill.py` and `apply_obs.py` are already adjudicated disjoint — they would
run concurrently *right now* if each claim declared its actual file. What collides
is the **coarse glob**: the moment one claimant declares `agents/apply_*.py`, it
truncates to the prefix `agents/apply_`, which is a prefix of *every* apply-family
file, so it collides with all of them.

That reframes the apply jam entirely. It is **not** that the prefix rule is too
blunt to separate sibling files (it separates them fine). It is that **the
claimants declare a region far broader than the files they touch.** AFR says "I
take `agents/apply_*.py`" when it actually edits `agents/apply_fill.py`. The
over-claim *is* the collision. The fix is not a new predicate — it is **claiming
the precise region**, which is exactly the §2 thesis (adjudicate the region the
work actually touches) pointed downward. A fleet that declares narrow trees
unjams itself with zero kernel changes.

Two refinements remain genuinely useful, but their scope is now narrower:

* **Phase 3a — precise overlap for the GLOB-vs-files case only (docs/92, opt-in).**
  Precise file-set comparison is *not* needed for file-vs-file (already disjoint).
  It is needed only when one side is an irreducible glob that must be compared
  against the other side's finite expansion — e.g. a tool that genuinely globs
  `apply_*.py` for codegen but only writes a known subset. Narrower than the first
  draft claimed, still floor-safe (fires only when it can enumerate; a real shared
  file is still caught). For the common apply case, *declaring narrow trees
  obviates it.*

* **Phase 3b — region as lock-mode, not just extent (docs/114).** The genuinely
  hard apply case is ALO (observability) needing to *read* `agents/apply_*.py`
  while ASI *writes* it — here the regions really do overlap and narrowing won't
  help, because ALO legitimately reads the whole family. A reader/writer lock
  (`mode: read|write`, R/R compatible, R/W and W/W not) admits ALO alongside ASI
  **soundly**. This is the one apply sub-case that needs a *region enrichment*
  rather than a *region narrowing*, and it is the highest-leverage unlock for the
  read-only apply-adjacent work (ALO, SAS-shadow) specifically.

The point of §4 in a doc about naming: **the apply jam's causes are
region-shaped, not name-shaped — but mostly they are OVER-CLAIM, not
imprecision.** Adding a `playbooks` lane would not help; neither would a cleverer
prefix rule for the common case. *Claiming the files you touch* helps immediately
(§2, verified above); lock-modes help the read-vs-write residue (§3b). The
operator's instinct — "don't just add another lane" — is exactly right.

---

## 5. The L2 footnote: `execution-state.yaml` is a region nothing locks

The `WinError 5` contention at ceiling-4 is a host concern, but it rhymes with the
whole doc, so it is worth one paragraph. `execution-state.yaml` is a **shared
mutable surface that the lane arbiter does not arbitrate** — every loop writes its
soft-claims there, and at high concurrency the writes collide at the *filesystem*
level (Windows mandatory locking → `EACCES`). FQ-451's ceiling-of-3 is a crude
global proxy for "how many concurrent writers can this one file tolerate." The
durable answer is the same answer as the rest of DOS: **treat the file as a region
and arbitrate it.** Either (a) give `execution-state.yaml` its own
single-writer lease (serialize writes through one holder, the WAL-append
discipline the lane journal already uses), or (b) shard it per-run (each run
writes `execution-state.<run_id>.yaml`, a projection folds them — the
"projection-not-sync" pattern from `project-dos-state-home-layout`). Either way the
ceiling-of-3 becomes unnecessary, because the contention it works around is gone.
This is host (reference-userland) work — noted here only so the connection is on
the record: *a shared surface with no region-lock on itself is the same bug class
as a region with no name, one level down in the I/O substrate.*

---

## 6. The shared seam (so this is one design, not four patches)

All of the above is one move applied at four levels:

> **Adjudicate the region; let the name, the granularity, and the mode be
> refinements of the region — never preconditions for adjudicating it.**

* **§1/L0 (shipped):** don't substitute a region the caller didn't claim
  (`UNKNOWN_LANE`).
* **§2–3/L1:** make the **ad-hoc claim** first-class and the **region-digest** the
  durable identity; the lane name becomes an optional view.
* **§4/down:** sharpen the region (precise files, opt-in) and enrich it (lock
  modes) so coarse prefixes stop over-serializing.
* **§5/L2:** lock the shared host file like any other region.

The seam they share is the **claim** type: `(region, intent, holder)` with the
region carrying *optionally* a name, *optionally* a mode, and adjudicated by the
existing pure conjunction. Nothing here weakens a floor: every refinement
(precise-overlap, lock-modes, ad-hoc claims) is gated so it can only **refuse-more
or admit-a-provably-disjoint-region**, never admit a real collision — the docs/113
`admissible_under_floor` discipline, generalized from the overlap scorer to the
whole claim.

---

## 7. Phasing

| Phase | What | Level | Floor-safe? | Status |
|---|---|---|---|---|
| 0 | `UNKNOWN_LANE` refuse (no silent substitute) | L0 | yes (strictly refuses more) | **SHIPPED `bc83d94`** |
| 1 | First-class **ad-hoc claim** ergonomics + identity: `dos arbitrate --tree …` with no `--lane` already *admits* correctly (verified §2); give it a `acquire (ad-hoc region)` reason and a non-empty lease handle | L1 | yes (admission already exists; this is ergonomics + identity) | unbuilt |
| 2 | **Region-digest identity**: WAL/journal record a claim keyed by region-digest; `dos top`/`decisions`/`resume` group by it and display a region summary when unnamed | L1/up | yes (additive identity) | unbuilt |
| — | **Operator guidance: declare narrow trees.** The biggest apply unlock needs *no code* — claimants declaring `agents/apply_fill.py` instead of `agents/apply_*.py` are already disjoint (verified §4). A `dos doctor`/lint warning when a claim's tree is broader than its likely footprint would surface over-claims | down | yes (no mechanism change) | unbuilt |
| 3a | **Precise-overlap** predicate (opt-in): exact file-set comparison for the GLOB-vs-finite-expansion case only (file-vs-file already disjoint) | down | yes (under the floor — only fires when it can enumerate; real shared file still caught) | unbuilt (docs/92) |
| 3b | **Lock modes** (`read`/`write`) on a claim + the compatibility matrix; admits a read-claim (ALO observability) alongside a write-claim (ASI) on a genuinely-overlapping region | down | yes (R/W matrix is the classic sound rule; default `write` = today's behavior) | unbuilt (docs/114) |
| 4 | **Lane = derived view**: taxonomy becomes a dictionary of named regions over the claim type, not a gate; `dos.toml` lanes are sugar for common claims | L1/up | yes (refactor; named path stays byte-identical) | unbuilt |
| — | (host) lock `execution-state.yaml` as a region / shard per-run; retire FQ-451 ceiling-of-3 | L2 | n/a (host) | reference-userland work |

The cheapest real unlock needs **no kernel code at all**: claimants declaring the
*files they touch* instead of the coarse `apply_*.py` glob are already adjudicated
disjoint (verified §4) — so a lint/`doctor` warning on over-broad claims is the
highest value-per-effort move. Phase 1 (ad-hoc identity) is the next build: the
admission already works (verified §2), only the handle is missing. Phase 3b is the
unlock for the genuinely-overlapping read-vs-write apply residue. Phases 2 and 4
are the durable-identity payoff that makes ad-hoc claims first-class up the stack.

---

## 8. What this is NOT

* **Not** "add more lanes." The whole argument is that the *name* is the wrong
  axis; adding `playbooks` to `dos.toml` (a legitimate, separate band-aid — do it
  to unblock today) does not address the static-taxonomy assumption that will miss
  the *next* unanticipated region.
* **Not** a weakening of disjointness. Every phase is floor-safe; the prefix
  disjointness verdict remains the unforgeable floor under any refinement
  (docs/113).
* **Not** a host-policy change masquerading as kernel work. The claim type, the
  region-digest, the lock modes, and the precise-overlap predicate are all
  *mechanism* (they adjudicate regions without knowing what any region means). The
  taxonomy-as-dictionary (Phase 4) keeps the host's *named* regions in `dos.toml`
  where they belong — it just stops them being a precondition.

---

## 9. Open questions

1. **Region-digest stability across glob rewrites.** `agents/apply_*.py` and
   `agents/apply_fill.py` + `agents/apply_obs.py` may denote the same file set but
   produce different digests. Does the digest key on the *declared* tree or the
   *expanded* file set? (Leaning declared, with precise-overlap as a separate
   compatibility check — keep identity and admission orthogonal.)
2. **Lock-mode honesty.** A claim that declares `read` but then writes is a
   self-report the kernel cannot verify at admission time. Is there a cheap
   post-hoc check (the footprint∩region re-verification docs/107 already does for
   `STEP_VERIFIED`) that catches a read-claim that wrote? If not, lock modes are
   advisory in the same way liveness is — which is acceptable, but should be
   *stated*, not assumed.
3. **Does the ad-hoc claim need exclusivity guards?** A `--tree **/*` ad-hoc claim
   is the whole-repo blast radius (`_tree` already treats the empty prefix as
   universal). It should route to the same exclusive-lane treatment as `global`.
   Confirm the empty-prefix path already does this for an unnamed claim (it does
   for a named one).
