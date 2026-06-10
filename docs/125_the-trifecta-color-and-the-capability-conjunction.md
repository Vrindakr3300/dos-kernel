# 125 — The trifecta color, and the capability conjunction

> **Status:** design plan. Unbuilt. This doc is the argument for a new built-in
> admission predicate + its typed refuse, and the seam it rides (the already-shipped
> `dos.predicates` conjunction). Phase 1 is a *days* build because the machinery
> (`admission.run_predicates`, `reasons.BASE_REASONS`, the `SubstrateConfig` seam)
> already exists; this predicate is a new *payload* on it, the SELF_MODIFY sibling.
>
> **One line:** The single most-cited agentic-security defense — *never let one
> agent simultaneously hold **private-data + untrusted-content + exfiltration**; if
> it needs all three, force a human / isolate* (Willison's "lethal trifecta") — is
> **structurally identical to lane arbitration**: it is a refusal that fires when a
> set-union reaches a forbidden cardinality. So it is not a new subsystem; it is a
> third built-in `AdmissionPredicate` beside `DisjointnessPredicate` and
> `SelfModifyPredicate`, a set-membership check inside the pure `arbitrate()` the
> kernel already wrote, replay-tests, and trusts. No model call.
>
> **Lineage.** This is the cheapest Phase-1 payload of the security-PEP program in
> `dos-strategy/dispatch-os-security-10x-100x.md` (§4.1, §5). It is the *detection*
> half (a typed refuse over a capability conjunction); the *enforcement* half — making
> that refuse **bind** by gating the capability grant at a mediated write moment — is
> docs/126 (the apply-gate / mediated-write PEP) and is explicitly out of scope here.
> A trifecta refuse that only *prints* is a detector (today's advisory arbiter); the
> same refuse withholding the exfiltration *capability* is enforcement (docs/126).
> This doc ships the verdict; docs/126 gives it teeth.

---

## 0. The defense, and why it is already an arbiter shape

The 2026 reference hazard is the **lethal trifecta** (Willison, June 2025; the
OWASP ASI working group; Oso; Airia; the *provable* version is Google's **CaMeL**,
control/data-flow isolation at ~77% task completion): a single agent that
simultaneously holds

  * **`private-data`** — read access to sensitive context (secrets, a customer's
    files, internal data),
  * **`untrusted-content`** — exposure to attacker-controllable input (a fetched
    web page, a recalled memory, an inbound email, a peer agent's message), and
  * **`exfiltration`** — a channel that can move bytes off-box (network egress, a
    public write, an outbound API),

is exploitable *by construction*: untrusted content can carry an injected
instruction that reads the private data and ships it out, and no individual
capability looks dangerous in isolation. The field's converged defense is not "make
each capability safe" — it is **"never let the three co-occur in one agent; if the
task genuinely needs all three, force human-in-the-loop or session-isolate."**

Read that defense next to the arbiter and the shape is exact. `arbitrate()` already
refuses when a *requested region* + *the live leases* would put two agents on the
same files — a refusal keyed on a **predicate over a union of what is already
held**. The trifecta defense is the *same predicate on a sibling axis*: a refusal
keyed on whether the *requested capability color* + *the colors the agent already
holds* would reach **cardinality 3**. The arbiter is already a set-union conflict
detector; this teaches it one more set to union over.

> **A widely-cited agentic attack pattern maps onto a set-membership check inside a
> pure function we already wrote, trust, and replay-test** (for the capabilities a
> lease actually grants — §3/§5 bound the scope, and it stays advisory). That is the
> reason this is a cheap, high-leverage build and not a research project.

---

## 1. Why this slots onto the shipped seam with no new machinery

Three facts about the *current* kernel make this a payload, not a subsystem:

1. **The predicate seam is conjunctive-only and open** (`admission.py`). An
   `AdmissionPredicate` is a pure `(request, live_lease, config) -> AdmissionVerdict`,
   and `AdmissionVerdict` has only `.admit()` / `.refuse(reason)` — **there is no
   "force-admit"**. So a new predicate is *structurally incapable* of loosening
   admission; the worst a bug can do is refuse too much (the safe direction). A
   trifecta predicate inherits that guarantee for free: adding it can only make the
   arbiter *stricter*.

2. **`run_predicates` already runs the conjunction against a synthetic empty lease
   when nothing is live** (`admission.py`, the idle-repo fix). So a
   **request-absolute** predicate — one that answers from the request alone, exactly
   like `SelfModifyPredicate` — fires on *every* admit path, idle or busy. The
   trifecta check is request-relative-to-the-agent's-own-held-colors, not
   relative-to-another-lease, so it follows the SELF_MODIFY pattern precisely (more
   on the "held colors" subtlety in §3).

3. **The typed-refuse vocabulary is data** (`reasons.py`). SELF_MODIFY,
   SCHEMA_UNREADABLE, UNKNOWN_LANE were all added as `ReasonSpec` rows in
   `BASE_REASONS` so an arbiter-emitted refusal is simultaneously *emittable*,
   *verifiable* (`category_for`), *refusable* (`is_refusal`), and `dos man wedge`-
   documented. The trifecta refuse is one more row — the same completeness rail.

So Phase 1 is: a new predicate module + one `ReasonSpec` + wiring it into
`built_in_predicates` + tests. The diff touches the same files the SELF_MODIFY guard
touched, and the SELF_MODIFY guard is the worked precedent for every line of it.

---

## 2. The one genuine design decision: where do the colors come from, and what category does the refuse roll up to

Two things this plan must decide before code, because they are not mechanical.

### 2.1 Colors are declared data on the lease request, not inferred

A capability color is **policy**, not mechanism — DOS must not *guess* that "this
lane can exfiltrate." So the colors a request carries are **declared by the host**,
exactly as the lane taxonomy and the reason vocabulary are:

  * A new optional field on the admission request: `colors: tuple[str, ...]` (a
    subset of the closed set `{private-data, untrusted-content, exfiltration}`).
    Absent / empty ⇒ the predicate admits (no color declared = nothing to conflict;
    the safe default that keeps every existing call site byte-unchanged).
  * The mapping *lane → colors* (or *capability → colors*) is **`SubstrateConfig`
    data**, declared in `dos.toml`, the same shape as the lane taxonomy. A host that
    never declares colors gets today's behavior exactly; a host that declares them
    opts into the check. This is the docs/76 flexibility law held: the *which-color*
    is provenance/policy (hackable, host-declared); the *adjudication* (cardinality-3
    ⇒ refuse) is fixed kernel mechanism.

This is the honest reading of "colors are declared, not sniffed": the kernel never
decides what is sensitive — it only enforces the conjunction over what the operator
*labeled* sensitive. (A future driver could *propose* colors via a JUDGE — "this
tool description looks like egress" — but that is advisory and out of the kernel,
the `judges` pattern. The kernel only ever consumes a declared color.)

### 2.2 The refuse needs a category — and this surfaces a `NoPickCause` gap

`ReasonSpec.category` must be one of `KNOWN_CATEGORIES` = {`TRUE_DRAIN`,
`OPERATOR_GATE`, `STALE_CLAIM`, `MISROUTE`, `UNCLASSIFIED`} (these must be
`picker_oracle.NoPickCause` values — the lockstep). SELF_MODIFY chose `MISROUTE`
("work aimed at the wrong place"). The trifecta refuse is semantically different:
the field's prescribed remedy is *"force human-in-the-loop / isolate"* — which is an
**`OPERATOR_GATE`** ("a human must decide"), not a misroute. So:

  * **Decision A (preferred): roll `TRIFECTA_THIRD_COLOR` up to `OPERATOR_GATE`.**
    The remedy is "an operator must approve this agent holding all three colors, or
    split the work" — exactly the gate semantics. No new category; no `NoPickCause`
    change. This is the low-friction path and is recommended for Phase 1.
  * **Decision B (deferred): mint a new category `CAPABILITY_CONFLICT`.** Cleaner
    taxonomically (a trifecta refuse is neither a stale claim nor a soak gate nor a
    misroute), but it touches `picker_oracle.NoPickCause` + the lockstep test + the
    man surface — a wider blast radius. Defer unless the `OPERATOR_GATE` rollup
    proves to conflate two genuinely different operator actions in practice.

Phase 1 takes Decision A. The plan flags B so the choice is explicit, not silent.

---

## 3. The held-colors subtlety — what "the agent already holds" means without a model

`DisjointnessPredicate` compares a request against *one live lease at a time*.
SELF_MODIFY ignores the live lease and answers from the request alone. The trifecta
check is a *third* shape: it must union the requested color with **the colors this
same agent already holds across its live leases**. That needs an *identity* to group
by — and DOS already has one: the lease holder / `run_id` on the spine.

So the check is:

> For the requesting agent's identity, let `held = ⋃ colors(lease)` over that
> agent's currently-live leases (read from the WAL at the call boundary, exactly as
> live leases are already gathered for `arbitrate`). If `requested_color ∉ held` and
> `|held ∪ {requested_color}| == 3`, refuse `TRIFECTA_THIRD_COLOR`.

Two honesty notes this forces, both of which are *features* (they keep the kernel
from pretending):

  * **The held set is read at the boundary, handed to the pure predicate** — the
    `liveness`/`arbitrate` "I/O at the boundary, data to the pure core" rule. The
    predicate itself stays pure; the WAL read that assembles `held` happens in the
    CLI/`arbitrate` caller, the same place live leases are already loaded.
  * **This binds the trifecta to lease-granted capabilities only.** A color the
    agent exercises *without* taking a lease (it just makes a network call) is
    invisible to this check — which is precisely the §5 limitation that makes the
    detector advisory until docs/126 routes capabilities through a mediated grant.
    The plan states this plainly rather than implying coverage it does not have.

---

## 4. Phase plan

**Phase 1 — the predicate + the typed refuse (the cheap, in-lane core).**
- `src/dos/trifecta.py` (the SELF_MODIFY-shaped module): the closed color set, a
  `TrifectaColorPredicate` implementing `AdmissionPredicate`, request-relative-to-
  held-colors, refusing on cardinality 3. Pure; `held` passed in.
- One `ReasonSpec(token="TRIFECTA_THIRD_COLOR", category="OPERATOR_GATE", …)` row in
  `reasons.BASE_REASONS`, with `fix`/`see_also` (the SELF_MODIFY precedent).
- Wire into `admission.built_in_predicates` *after* disjointness + self-modify (a
  refuse-only voice appended; cannot displace the safety guards).
- The optional `colors` field on the admission request + the `held` parameter
  threaded from the boundary; absent ⇒ admit (byte-unchanged default).
- `tests/test_trifecta.py`: cardinality 0/1/2 admit, 3 refuse, idempotent re-request
  of a held color admits, `--force` overrides (the SELF_MODIFY override contract),
  empty-colors admits, the conjunctive-only proof (a trifecta refuse cannot be
  forced by another predicate's admit).

**Phase 2 — the config seam (host-declared color mapping).**
- `dos.toml` `[colors]` (or `[lane.<name>].colors`) → `SubstrateConfig` data; a
  loader mirroring `reasons.load_from_toml`. `dos doctor` lists the active color
  mapping (the "see what gates your arbiter" rail).
- The CLI `dos arbitrate --color private-data` flag (and the MCP `arbitrate` tool
  field) so an operator/host can pass a requested color explicitly.

**Phase 3 — the eval harness (friendliness instrument, the per-axis pattern).**
- A `dos trifecta-eval` confusion grid over a labeled corpus (false-ADMIT rate =
  the dangerous direction; the `overlap-eval`/`judge-eval` shape), so a host can
  measure whether its declared color mapping actually catches the trifecta on its
  own history. Optional; mirrors docs/113 §2.

**Phase 4 (DEFERRED to docs/126) — make the refuse bind.** Route the exfiltration
capability through a mediated grant so a `TRIFECTA_THIRD_COLOR` refuse *withholds the
capability* instead of printing. This is the PDP→PEP step and is the docs/126 apply-
gate's job; named here only to mark the boundary.

---

## 5. What this is NOT (the litmus, so the build stays in its lane)

- **NOT a content classifier.** The kernel never decides what is sensitive or what
  is untrusted — it enforces the conjunction over *declared* colors only. Sniffing
  content for colors is a JUDGE/driver concern (advisory, out of kernel), never the
  predicate.
- **NOT enforcement (yet).** Phase 1–3 ship a *typed verdict* — the detector half.
  It refuses in the advisory arbiter exactly as SELF_MODIFY does; it does not stop a
  process from exfiltrating. Binding it is docs/126. This doc deliberately ships only
  the half that needs no new actuation boundary.
- **NOT a new override path.** `--force` is the sole override, identical to every
  other predicate refusal — the operator's explicit "yes, this agent may hold all
  three, I accept it." A predicate cannot force itself.
- **NOT host-coupled.** No lane name, no host directory, the color set is generic and
  the mapping is config data — the `kernel imports no host` litmus holds, pinned the
  same way `test_self_modify_*` pins SELF_MODIFY.

The whole plan is one sentence made buildable: *the lethal trifecta is an arbiter
color, and the arbiter is already a set-union conflict detector — so teach it one
more set, refuse on cardinality 3, and let `--force` be the human-in-the-loop the
field already prescribed.*
