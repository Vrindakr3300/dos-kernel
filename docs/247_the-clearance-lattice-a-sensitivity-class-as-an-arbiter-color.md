# 247 — The clearance lattice: a sensitivity class as an arbiter color

> **Status:** design plan. Unbuilt. This doc is the argument for a SECOND
> request-axis built-in admission predicate — a *clearance / sensitivity* guard —
> beside the docs/125 trifecta color, plus the seam it rides (the already-shipped
> `dos.predicates` conjunction + the `data_class.py`-shaped config registry). Like
> docs/125 it is a *days* build: every piece of machinery it needs
> (`admission.run_predicates`, `reasons.BASE_REASONS`, the `SubstrateConfig` seam,
> and a closed-token-policy-as-data with a `load_from_toml`) already ships. This
> predicate is a new *payload* on those rails, the SELF_MODIFY / trifecta sibling.
>
> **One line:** An autonomous agent must not move data across a sensitivity
> boundary it is not cleared for — read SECRET context and write it into an
> UNCLASSIFIED region, or hold a lease whose region-union spans two incompatible
> compartments. Stated generically, that prohibition is a **lattice comparison**
> (is the write-region's level ≥ the level of everything the lease reads, and are
> the compartments compatible?), and a lattice comparison is the *same shape* as
> the trifecta cardinality check: a refusal that fires when a **set/order relation
> over what one agent holds** reaches a forbidden value. So it is not a new
> subsystem — it is one more built-in `AdmissionPredicate` over one more
> host-declared axis, a pure order-check inside the `arbitrate()` the kernel
> already wrote, replay-tests, and trusts. No model call.
>
> **Lineage.** The WHY is the data-handling / cross-domain frame of the
> national-security strategy: `../dos-strategy/dispatch-os-national-security.md`
> (**§3.3** — the boundary DOS does *not* cross, the container/VM/cross-domain
> guard's job; **§4** — the threat-model table, where data-segregation across a
> sensitivity boundary sits next to the lethal-trifecta row; the §5 sovereignty
> framing of why a vendor-neutral such control matters). **Do not restate that
> argument here** — it is the market/threat case and lives there; this doc is the
> HOW. The sibling AXIS is docs/125 (`125_the-trifecta-color-and-the-capability-conjunction.md`):
> this plan is *the docs/125 pattern re-aimed at a sensitivity lattice* (a separate
> predicate over a separate declared axis — sensitivity LEVEL, not capability
> COLOR), NOT a re-invention and NOT a duplication of the trifecta. The TEMPLATE
> for "declared closed tokens as data, generic default, pure `classify`,
> `load_from_toml` at the boundary" is `src/dos/data_class.py` (the four-class path
> classifier on `SubstrateConfig`). The SEAM is `src/dos/admission.py` (the
> conjunctive-only predicate Protocol) + `src/dos/self_modify.py` (the worked
> request-absolute built-in + its `reasons.BASE_REASONS` row). The PDP→PEP
> boundary (making the refuse *bind* at a mediated write) is docs/126
> (`126_the-mediated-write-and-the-apply-gate-pep.md`) and is explicitly out of
> scope (Phase 4). The "this is not an accreditation control" companion is
> [docs/249](https://github.com/anthony-chaudhary/dos-strategy/blob/master/249_the-accreditation-surface-mapping-the-verdicts-to-controls.md) (the real-classification-system / accreditation-vs-mechanism
> companion, now in the `dos-strategy` repo; named here to mark the boundary, the same way docs/125 forward-named
> docs/126 before it was written).

---

## 0. The requirement, and why it is already an arbiter shape

The reference data-handling hazard in a sovereignty-conscious or regulated fleet
is **cross-domain spillage**: a single autonomous agent reads data labeled at one
sensitivity level and writes it — directly, or by laundering it through its own
working state — into a region labeled at a *lower* level, or it straddles two
*compartments* (need-to-know partitions) that policy says must not mix in one
actor. No single read and no single write looks dangerous in isolation; the
hazard is the *combination one agent holds at once*. (This is the classic
Bell-LaPadula confidentiality shape — **no read-up, no write-down** — but we will
state it generically below and the kernel will name no real classification level.)

Define the two terms this plan turns on, in plain words:

  * A **sensitivity level** is a point on a host-declared **total order** of
    protection — "the higher the level, the more protected the data." DOS ships no
    real level names; a host declares its own ordered tokens (see §2.1).
  * A **compartment** (optional) is a host-declared **label that does not order** —
    two compartments are either the same or *incompatible*; an agent cleared for
    one is not thereby cleared for the other. (The "need-to-know" / caveat axis,
    orthogonal to level.)

Read that requirement next to the arbiter and the shape is exact. `arbitrate()`
already refuses when a *requested region* plus *the live leases* would put two
agents on the same files — a refusal keyed on a **predicate over a union of what
is held**. docs/125 taught the same arbiter a sibling refusal: cardinality-3 over
a union of capability *colors*. This plan teaches it a *third* refusal on a
*fourth* sibling axis: an **order/compatibility relation** over the sensitivity
LEVELS (and compartments) of the regions one agent holds. The arbiter is already
a set-union conflict detector; docs/125 added one set to union over; this adds one
*lattice* to compare over.

> **A national-security data-segregation rule maps onto an order-comparison inside
> a pure function the kernel already wrote, trusts, and replay-tests.** That is why
> this is a cheap, high-leverage payload and not a research project — exactly the
> docs/125 argument, on the sensitivity axis instead of the capability axis.

---

## 1. Why this slots onto the shipped seams with no new machinery

Two families of *current* kernel fact make this a payload, not a subsystem. The
first is the predicate seam (shared with docs/125); the second is the
declared-token-policy-as-data pattern (shared with `data_class`).

**The predicate seam is conjunctive-only and open** (`admission.py`):

1. An `AdmissionPredicate` is a pure `(request, live_lease, config) ->
   AdmissionVerdict`, and `AdmissionVerdict` has only `.admit()` / `.refuse(reason,
   reason_class=…)` — **there is no force-admit constructor** (`admission.py:69-110`).
   So a clearance predicate is *structurally* incapable of loosening admission; the
   worst a bug can do is refuse too much (the safe direction). A clearance refuse
   inherits the docs/125 guarantee for free — adding it can only make the arbiter
   *stricter*.
2. `run_predicates` runs the conjunction against a **synthetic empty lease** when
   nothing is live (`admission.py:258`), so a **request-absolute** clearance rule —
   one that answers from the request's own read-set vs write-region, exactly like
   `SelfModifyPredicate` — fires on *every* admit path, idle or busy. (The
   cross-agent compartment case is request-relative-to-held, the docs/125 §3 shape;
   see §3.)
3. `run_predicates` is **fail-closed**: a predicate that raises, or returns a
   non-`AdmissionVerdict`, is converted to a refuse naming the predicate
   (`admission.py:264-281`). A clearance guard that cannot answer refuses — the
   correct direction for a data-segregation control.
4. The typed-refuse vocabulary is **data** (`reasons.py`): SELF_MODIFY,
   SCHEMA_UNREADABLE, UNKNOWN_LANE are `ReasonSpec` rows in `BASE_REASONS`
   (`reasons.py:302-366`), each rolling up to a `KNOWN_CATEGORIES` value
   (`reasons.py:67-73`) that must be a `picker_oracle.NoPickCause` (the lockstep).
   A clearance refuse is one more row on the same completeness rail.

**The declared-token-policy-as-data pattern already ships** (`data_class.py`):

5. `data_class.py` is a **frozen `DataClassPolicy`** carrying per-class glob
   patterns, a fixed priority order, a `default_class` that **defaults to the SAFE
   direction** (unknown ⇒ `PRODUCT`, the most-protected / never-reaped class —
   `data_class.py:212`), a pure `classify(path) -> str` (`data_class.py:233`),
   `with_overrides(...)`, a `policy_from_table` that validates keys + raises on a
   typo, and a `load_from_toml` that opens the toml **at the call boundary** exactly
   as `stamp.load_from_toml` / `retention.load_from_toml` do (`data_class.py:368`).
   It rides `SubstrateConfig` next to `.reasons` / `.stamp` / `.retention`
   (`config.py:613`), is declarable in `dos.toml [data_class]`, and ships a
   **generic default keyed only off `.dos/`-relative shapes** so the kernel stays
   domain-free (`GENERIC_DATA_CLASS`, `data_class.py:258`). This is the EXACT
   template for a clearance policy: a closed/ordered token set as data, a generic
   default, a pure classifier, file I/O only at the boundary.

So Phase 1 is: a new predicate module (`clearance.py`) carrying the
`data_class`-shaped sensitivity policy + the pure violation check, one `ReasonSpec`
row, and wiring into `built_in_predicates`. The diff touches the union of the files
SELF_MODIFY touched (`admission.py` wiring, `reasons.py` row, a new module + test)
and the files `data_class` touched (the policy dataclass + its toml loader) — both
are worked precedents for every line.

---

## 2. The genuine design decisions

Four things this plan must decide before code, because they are policy, not
mechanism. Decisions A–C are Phase-1; the held-set discipline (§3) is shared with
docs/125 verbatim in spirit.

### 2.1 The sensitivity tokens AND their order are host-declared (the kernel names no real level)

A sensitivity level is **policy**, not mechanism — DOS must not ship the word
`SECRET` or decide that one token outranks another. So, exactly as the lane
taxonomy, the reason vocabulary, and the `data_class` patterns are declared data:

  * A `ClearancePolicy` (frozen, the `DataClassPolicy` sibling) carries an
    **ordered tuple of level tokens** `levels: tuple[str, ...]` — *the tuple order
    IS the lattice order* (index 0 = least protected … index n−1 = most protected).
    The host writes its own tokens; the kernel attaches no meaning to the strings
    beyond their position.
  * It carries the **region → level** mapping as glob patterns per level (the
    `data_class` per-class-patterns shape) and an optional **region →
    compartment** mapping, so a path classifies to a `(level, compartment)` pair by
    the same priority-ordered first-match-wins walk `DataClassPolicy.classify`
    already implements.
  * It carries a `default_level` that **defaults to the SAFE direction —
    `default_level = levels[-1]`, the MOST-protected level** (the `data_class`
    "unknown ⇒ PRODUCT" choice, re-grounded: an unclassified region is treated as
    maximally sensitive, so the guard can never under-protect an unlabeled path).
    This is the single most important default in the plan and the inverse of a
    "fail-open" classifier.
  * The kernel ships TWO named constants mirroring `data_class.py`'s pair:
    `GENERIC_CLEARANCE` — a generic two-level lattice over `.dos/`-relative shapes
    only (names no host tree, no real level), the domain-free starting point; and
    `NONE_CLEARANCE` — a single-level lattice where every region is the same level
    so the predicate always admits (the byte-faithful "no clearance seam" opt-out,
    the `NONE_DATA_CLASS` analogue). A host that declares nothing gets `NONE`-shaped
    behavior: every existing call site is byte-unchanged.

This is the docs/76 flexibility law and the docs/125 §2.1 line, held on the new
axis: the *which-level* (the tokens, their order, the region map) is
provenance/policy — hackable, host-declared, `dos.toml` data; the *adjudication*
(write-region level ≥ read-set level, compatible compartments, else refuse) is
fixed kernel mechanism. **The kernel never decides what is secret; it enforces the
lattice over what the operator LABELED.**

### 2.2 The violation rule, stated generically (the Bell-LaPadula shape, expressed as an order check)

Given a lease request resolved to a region tree, the predicate computes, over
every path in the union it is judging (see §3 for the cross-agent case):

  * `read_levels` = the set of levels of the regions the lease **reads** (a lease's
    tree is its blast radius; a host that distinguishes read-grants from
    write-grants declares them — see §2.4),
  * `write_region_level` = the level of the region the lease **writes**, and
  * the compartment set the lease's regions fall into.

The refuse fires (`reason_class = CLEARANCE_VIOLATION`) iff EITHER:

  * **write-down** — `write_region_level < max(read_levels)` (the agent would move
    data from a higher level into a region declared lower — the "no write-down"
    half), OR
  * **compartment straddle** — the lease's regions fall into two or more
    compartments declared incompatible (an actor crossing a need-to-know partition).

Two notes that keep this honest:

  * The order comparison is **purely positional**: `level_a < level_b` iff
    `levels.index(a) < levels.index(b)`. A token not in `levels` is impossible
    because every region classifies (unknowns fall to `default_level`), so the
    comparison is always defined — no "unknown level" ambiguity.
  * The "no read-UP" dual (an agent reading data above its *own* clearance) is a
    statement about the AGENT'S clearance, not about two regions; DOS has no agent
    identity carrying a clearance level today, so the Phase-1 predicate scopes to
    the **region-to-region** relation (write-down + compartment straddle), which is
    decidable from the lease alone. Read-up against a declared *agent clearance* is
    named as Phase-3+ once a clearance attribute exists on the request — flagged,
    not silently claimed (the docs/125 §3 honesty discipline).

### 2.3 The category the refuse rolls up to: OPERATOR_GATE (docs/125 Decision A)

`ReasonSpec.category` must be one of `KNOWN_CATEGORIES` = {`TRUE_DRAIN`,
`OPERATOR_GATE`, `STALE_CLAIM`, `MISROUTE`, `UNCLASSIFIED`} and each must be a
`picker_oracle.NoPickCause` value (the lockstep — `reasons.py:67-73`). SELF_MODIFY
chose `MISROUTE` ("work aimed at the wrong place"). A clearance violation is
semantically the docs/125 case, not the SELF_MODIFY case: the prescribed remedy is
*"a human with the authority must approve this data movement, or the work must be
split so no one agent spans the boundary"* — an **`OPERATOR_GATE`** ("a human must
decide"), not a misroute and not a stale claim.

  * **Decision A (Phase 1, preferred):** roll `CLEARANCE_VIOLATION` up to
    `OPERATOR_GATE` — identical to docs/125 Decision A. No new category, no
    `NoPickCause` change, no lockstep-test churn.
  * **Decision B (deferred, shared with docs/125):** if `OPERATOR_GATE` proves to
    conflate two genuinely different operator actions (the trifecta "approve all
    three colors" vs the clearance "approve this cross-level movement"), mint a
    single new `CAPABILITY_CONFLICT` (or `BOUNDARY_GATE`) category that BOTH
    predicates share — a wider blast radius (`picker_oracle.NoPickCause` + the
    lockstep test + the man surface). Defer; do not pre-build it. Whether docs/125
    and docs/247 share one new category is itself the decision to make then.

Phase 1 takes Decision A. The plan flags B so the choice is explicit, not silent.

### 2.4 How a region's level is known WITHOUT a content sniff

The level of a region comes from the **same place `data_class` gets a path's
class**: the host's declared `[clearance]` glob patterns, matched against the
POSIX-normalized repo-relative path by `ClearancePolicy.classify(path) -> (level,
compartment)`. The kernel **never opens the file** — it does not decide a path is
SECRET by reading it; it reads the *label the operator declared for that path
shape*. This is the §5 litmus made structural: the classifier sees only paths and
the declared map, never bytes. (A future driver could *propose* a level via a JUDGE
— "this directory name looks like PII" — but that is advisory and out of the
kernel, the `judges` pattern; the kernel only ever consumes a declared level, the
docs/125 §2.1 closing note.)

---

## 3. The held-set subtlety — what "the agent already holds" means without a model

(This is the docs/125 §3 discipline, reused verbatim in spirit on the sensitivity
axis — read docs/125 §3 for the full argument; the deltas are noted.)

The **write-down** half of the rule (§2.2) is **request-absolute**: it compares the
lease's OWN write-region against the lease's OWN read-set, so it answers from the
request alone, ignores `live_lease`, and follows the SELF_MODIFY pattern precisely
— firing on every admit path including an idle repo (`run_predicates`' synthetic
empty lease, `admission.py:258`).

The **compartment-straddle** half can be either request-absolute (the single lease
already spans two compartments) OR cross-agent (this lease is in compartment X and
the same agent already holds a lease in incompatible compartment Y). The
cross-agent case is the docs/125 §3 shape exactly: it must union the requested
region's compartment with **the compartments this same agent already holds across
its live leases**, grouped by the lease holder / `run_id` on the spine. So:

> For the requesting agent's identity, let `held = ⋃ compartment(lease)` over that
> agent's currently-live leases (read from the WAL **at the call boundary**, the
> same place live leases are already gathered for `arbitrate`). If the requested
> region's compartment is incompatible with any compartment in `held`, refuse
> `CLEARANCE_VIOLATION`.

Two honesty notes this forces, both features (they keep the kernel from
pretending), identical to docs/125 §3:

  * **The held set is read at the boundary, handed to the pure predicate** — the
    `liveness` / `arbitrate` "I/O at the boundary, data to the pure core" rule
    (`admission.py:344-401` resolves workspace facts at the boundary and threads
    them in; the clearance held-set rides the same channel). The predicate stays
    pure; the WAL read happens in the CLI / `arbitrate` caller.
  * **This binds the guard to lease-granted regions only.** Data an agent moves
    *without* taking a lease (it just makes a network call, or reads a path outside
    any leased tree) is invisible to this check — which is precisely the limitation
    that keeps the detector ADVISORY until docs/126 routes the write through a
    mediated grant (§ Phase 4). The plan states this plainly rather than implying
    coverage it does not have.

---

## 4. Phase plan

**Phase 1 — the predicate + the policy-as-data + the typed refuse (the cheap, in-lane core).**
- `src/dos/clearance.py`: the frozen `ClearancePolicy` (the `DataClassPolicy`
  sibling — ordered `levels`, per-level + per-compartment glob patterns,
  `default_level = levels[-1]` safe default, `classify(path) -> (level,
  compartment)`, `with_overrides`, `policy_from_table`, `load_from_toml` at the
  boundary), the `GENERIC_CLEARANCE` / `NONE_CLEARANCE` constants, and a
  `ClearancePredicate` implementing `AdmissionPredicate` — pure, request-absolute
  for write-down, request-relative-to-`held` for compartment straddle, refusing on
  a lattice violation. The held compartment set is passed in (not gathered inside).
- One `ReasonSpec(token="CLEARANCE_VIOLATION", category="OPERATOR_GATE", …)` row in
  `reasons.BASE_REASONS`, with `summary` / `fix` / `see_also` (the SELF_MODIFY +
  trifecta precedent; `see_also` points at `dos man lane` / `dos arbitrate`, never a
  host lane name — the `config_lint.REASON_SEE_ALSO_DANGLES` discipline,
  `reasons.py:311-317`).
- Wire into `admission.built_in_predicates` **after** disjointness + self-modify
  (`admission.py:401`) — a refuse-only voice appended; it cannot displace the safety
  guards, only add stricture.
- The optional read/write region distinction on the admission request (if the host
  separates read-grants from the write-region; absent ⇒ the whole tree is treated as
  both read and write, the conservative default) + the `held` compartment parameter
  threaded from the boundary; a `NONE_CLEARANCE` / no-`[clearance]` config ⇒ admit
  (byte-unchanged default, the `NONE_DATA_CLASS` analogue).
- `tests/test_clearance.py` (the `test_self_modify_*` + `test_trifecta` shape):
  same-level admits; write-up admits (more-protected write of less-protected reads
  is allowed — only write-DOWN refuses); write-down refuses; single-compartment
  admits; incompatible-compartment straddle refuses; idle-repo (empty `live_leases`)
  still fires the write-down half (the synthetic-empty-lease path); `--force`
  overrides (the SELF_MODIFY override contract); the conjunctive-only proof (a
  clearance refuse cannot be forced to admit by another predicate); the
  unknown-region-⇒-most-protected-level default; a raising/ill-typed policy
  degrades to a fail-closed refuse, never an admit.

**Phase 2 — the config seam (host-declared lattice).**
- `dos.toml [clearance]` → `SubstrateConfig.clearance: ClearancePolicy`, a loader
  mirroring `data_class.load_from_toml` (`data_class.py:368`) and wired in
  `config.py`'s layering exactly as `[data_class]` is (`config.py:1184-1192`):
  `levels = ["public", "internal", "restricted"]`, per-level + per-compartment
  pattern lists, optional `default_level`. `dos doctor` lists the **active lattice**
  (the ordered levels + the region map) — the docs/125 §2 "see what gates your
  arbiter" rail, the `dos doctor` data-class line's sibling.
- The CLI `dos arbitrate --read-level / --write-level / --compartment …` flags (and
  the MCP `arbitrate` tool fields) so an operator/host can pass the resolved
  sensitivity explicitly when the path-glob classify is not enough.

**Phase 3 — the eval harness (friendliness instrument, the per-axis pattern).**
- A `dos clearance-eval` confusion grid over a labeled corpus (**false-ADMIT rate =
  the dangerous direction**), the `overlap-eval` / `judge-eval` / docs/125 §Phase-3
  shape, so a host can measure whether its declared lattice actually catches the
  cross-level / cross-compartment cases on its own history.
- Read-up against a declared **agent clearance** attribute (§2.2) lands here if/when
  the request carries an agent-level token — the dual of write-down, named in
  Phase 1 and built only once the identity exists.

**Phase 4 (DEFERRED to docs/126) — make the refuse BIND at the mediated write.**
Route the write through the mediated grant so a `CLEARANCE_VIOLATION` refuse
*withholds the cross-boundary write* instead of printing. This is the PDP→PEP step
and is the docs/126 apply-gate's job (`126_the-mediated-write-and-the-apply-gate-pep.md`);
named here only to mark the boundary, identical to docs/125 Phase 4.

---

## 5. What this is NOT (the litmus, so the build stays in its lane)

- **NOT a content / data classifier.** The kernel never opens a file to decide
  whether it IS secret — it enforces the lattice over *declared* sensitivity only
  (the region → level map). Sniffing content for a level is a JUDGE / driver concern
  (advisory, out of kernel), never the predicate. This is the docs/125 §5 line, on
  the sensitivity axis: DOS adjudicates the LABEL, not the bytes.
- **NOT a real classification system, and not an accreditation control by itself.**
  The kernel ships no real level name and makes no accreditation claim; it is a
  generic order-comparison mechanism a host points at its own labels. The
  accreditation-vs-mechanism boundary — what a sanctioned classified-system control
  actually requires, and why this predicate is one *ingredient* and not the system —
  is docs/249. The strategy doc is explicit (§3.3, §4): the
  cross-domain-guard / VM / accreditor's job is NOT DOS's job, and DOS must not
  pretend to it.
- **NOT enforcement (yet).** Phase 1–3 ship a *typed verdict* — the detector half.
  It refuses in the advisory arbiter exactly as SELF_MODIFY and the trifecta color
  do; it does not stop a process from writing across the boundary. Binding it is
  docs/126.
- **NOT a duplicate of the trifecta, and NOT a new override path.** The trifecta is
  a cardinality check over capability COLORS; this is an order/compatibility check
  over sensitivity LEVELS — separate predicate, separate declared axis, separate
  reason token, composed in the same conjunction (both refuse-only; either can fire
  first). `--force` remains the SOLE override, identical to every other predicate
  refusal — the operator's explicit "yes, I accept this agent moving data across
  this boundary." A predicate cannot force itself.
- **NOT host-coupled.** No lane name, no host directory, no real classification
  level: the level tokens, their order, and the region map are all generic config
  data, the `GENERIC_CLEARANCE` default keyed only off `.dos/`-relative shapes. The
  `kernel imports no host` litmus holds, pinned the same way `test_self_modify_*` and
  `test_data_class_*` pin their seams.

The whole plan is one sentence made buildable: *a sensitivity boundary is a lattice,
the arbiter is already a set-union/order conflict detector, and a clearance is just
one more declared axis like the data-class — so classify each region's declared
level off `data_class`-shaped config, refuse when a lease would write data down a
level or straddle an incompatible compartment, and let `--force` be the cleared
human the policy already requires.*
