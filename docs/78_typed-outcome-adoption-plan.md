# TOA — Typed-Outcome Adoption plan (the minimal on-ramp: reasons as a standalone type layer)

> **Status:** committed — **NOT STARTED** (proposed 2026-06-01). The
> SCV/WCR/RND/SKP/DOS-HOME/[ADM](73_admission-predicate-plan.md) genericization
> series has all shipped; TOA is the next open plan, landing on that green,
> generic base. This is an *adoption-surface* plan, not a new axis: it makes the
> already-shipped Axis-1 refusal vocabulary ([reasons.py](../src/dos/reasons.py),
> HACKING.md §1) usable **standalone** — without inheriting the dispatch machinery
> — so a host that wants only *typed outcomes* (the TypeScript/linter analogy) can
> adopt DOS in an afternoon and grow into lanes/arbiter later. Throughline-first,
> behavior-preserving for the existing dispatch host at every step. The
> behavior-preservation proof is the existing refusal-plane lockstep suite
> (`tests/test_refusal_and_tokens.py`) staying green; the new surfaces (the
> `CategorySet` lift, `[reason_categories]`, `dos check`, `init --minimal`) are
> pinned by a new `tests/test_typed_outcomes.py`.

## The thesis: DOS is a type system for outcomes, and reasons are its `tsconfig.json`

The closed-enums-as-data design (`project-dos-hackability-goal`) is, structurally,
**gradual typing for the runtime behavior of an agent fleet**:

| TypeScript / linter | DOS today | Where |
|---|---|---|
| A type | a `reason_class` — a typed "why this didn't happen" | `reasons.ReasonSpec` |
| The closed type universe (declared, immutable) | `ReasonRegistry` (`extend()` returns a NEW registry) | `reasons.py:124,201` |
| `tsconfig.json` / `.eslintrc` (config-as-data) | `dos.toml [reasons]` (additive) | `reasons.py:368` |
| `any` / `unknown` (untyped escape) | `UNCLASSIFIED` (undeclared-token fallthrough) | `reasons.py:78` |
| `noImplicitAny: true` (loosen knowingly) | `[stamp]` defaults **strict** (you opt into loose) | [SCV](70_stamp-convention-plan.md) |
| Custom rules / plugins | `entry_points` (`dos.predicates`/`dos.renderers`) | HACKING.md §"entry_points" |
| Rules compose, can only *add* errors | admission predicates are **conjunctive-only** | [ADM](73_admission-predicate-plan.md) |
| `tsc --noEmit` (prove no `any` leaked) | the `--check` completeness rail | HACKING.md §"`--check`" |

The one place DOS is **not** TypeScript is the load-bearing place: TS *trusts*
your annotation; DOS's `verify()` *distrusts* it and re-derives ground truth from
git ("the kernel is the part that doesn't believe the agents"). So the precise
analogy is a **gradual contract system with runtime verification** — refinement
types where the refinement is re-proven against artifacts. That distinction is
`project-dos-flexibility-geometry`: flexibility lives in *which signals* and
*provenance*, never in the adjudication.

This plan does **not** re-litigate any of that. It closes the three concrete gaps
between "reasons are a feature of the dispatch kernel" and "typed outcomes are a
thing you can adopt on their own."

## The three gaps this closes (each confirmed in code, not inferred)

**G1 — the category set is dispatch-coupled, so reasons are not yet standalone.**
Every `ReasonSpec.category` must be one of five values —
`{TRUE_DRAIN, OPERATOR_GATE, STALE_CLAIM, MISROUTE, UNCLASSIFIED}` — and those are
*picker* concepts. The coupling lives at **two** levels, and the plan is careful
to name which is which:

- *Declaration-time (the soft rung, what Phase 1 lifts).* `ReasonSpec.__post_init__`
  (`reasons.py:111`) validates `category` against the module-global frozenset
  `KNOWN_CATEGORIES` (`reasons.py:67`) — a **string** set, not the enum — and
  raises `ValueError` for anything outside the five. The error text even reads
  "not a known NoPickCause value": the *intent* is the round-trip, but the
  *enforcement* is a hardcoded string frozenset baked into the package. **That
  frozenset is the literal `extends DispatchBase` wart** — and being a plain
  module global, it is exactly the thing a per-workspace `CategorySet` replaces.
- *Runtime (the hard rung, already exception-handled).* The enum round-trip itself
  is in `picker_oracle`: the base map does `NoPickCause[category.value]`
  (`picker_oracle.py:185`, a subscript that `KeyError`s on an unknown category) and
  `resolve_cause` falls through to `NoPickCause(cat)` (`picker_oracle.py:219`, a
  call that `ValueError`s) — but that call is wrapped in a `try/except Exception`
  that swallows the miss to `UNCLASSIFIED` (`picker_oracle.py:216-221`). So a
  category the picker has no rule for does **not** crash at runtime; it simply
  resolves as drift.

The two together are why a minimal adopter with no picker and no lanes is *still*
forced to roll every outcome up to a dispatch category: not because the picker
would crash (it won't — the runtime rung is caught), but because the **package
itself refuses to construct a `ReasonSpec` whose category is outside its hardcoded
five** (the declaration rung). Lifting *that* frozenset is the clean standalone
on-ramp — and it is behavior-preserving precisely because the runtime rung is
already drift-tolerant.

**G2 — `--check` is a *completeness* rail, but it does not yet check reasons.**
HACKING.md §"`--check`" promises: "a `reason_class` **emitted** in a verdict
envelope but **not** in the active registry → **fail**." But the shipped
`dos doctor --check` (`cmd_doctor`, `cli.py:626`; the flag at `cli.py:1134`)
computes findings from only `_stamp_coverage_finding` + `_treeless_lane_findings`
(`cli.py:636-639`) — **stamp grammar** and **lane/tree** completeness. It never
scans a verdict envelope for an undeclared `reason_class`. The reason-drift rail
is *documented but unbuilt*. `dos man wedge <UNKNOWN>` does print an
`UNCLASSIFIED … this is drift` message (`cli.py:439`), but that is a per-token
lookup, not a CI-grade scan of *emitted* verdicts for undeclared reasons — the
exact `tsc --noEmit` move the analogy promises.

**G3 — the on-ramp is not framed or defaulted as one.** HACKING.md lists all five
axes as peers; nothing tells a newcomer "Axis 1 is the front door, adopt it
alone." And there is no strict posture for reasons to match `[stamp]`'s: a
workspace that *wants* `UNCLASSIFIED` to be a hard error (the `noImplicitAny`
stance) cannot declare it.

> **Out of this plan's scope, by design (the sibling, not the body):** the
> *outcome-verdict* half — `GateVerdict`/`OutcomeVerdict` (`tokens.py:88,122`),
> still closed built-in `str`-enums (immutable by construction, not yet
> registry-as-data) — is **Axis 2** (HACKING.md §2, 🔜 *design*). "Typed
> outcomes" splits into *why-not* (refusals, shipped + hackable — this plan's
> subject) and *what-happened* (verdicts, Axis 2). TOA makes the *refusal* surface
> adoptable standalone; making the *verdict* surface hackable is Axis 2's own
> plan. They are siblings; folding them would violate the series' one-axis-per-plan
> discipline. TOA *references* Axis 2 as the thing that completes the picture.

## Design laws this plan must honor

- **The dispatch host's behavior is byte-identical at every phase.** `job` and
  the default config keep `KNOWN_CATEGORIES`-as-the-five and the existing
  `picker_oracle` round-trip. G1's fix makes the category set *declarable*, never
  *changes the default*. The `picker_oracle`/`wedge_reason` lockstep suite
  (`tests/test_refusal_and_tokens.py` — its docstring states it "pins the lockstep
  property"; `test_oracle_recognizes_every_wedge_reason` /
  `test_reason_class_map_categories_agree_with_wedge_reason` are the round-trip
  pins) stays green unchanged — that is the proof.
- **Strict is the safe default for the dangerous direction** ([SCV](70_stamp-convention-plan.md),
  the `project-dos-genericization-plan-series` strict-default call). A *standalone*
  reason layer with no oracle to verify against is the permissive direction, so
  the standalone category set is opt-in, exactly as loose stamp grammar is.
- **Openness is only safe with a completeness rail** (HACKING.md §"`--check`").
  G2 is not optional polish — it is the invariant that lets an *open* reason
  vocabulary stay verifiable. Shipping a standalone adoption path (G1) without the
  drift rail (G2) would re-open the `UNCLASSIFIED` prose-drift the kernel exists
  to kill.
- **A reason declaration must light up every surface it already lights up**
  (emit / verify / refuse / `man` / `learn` — HACKING.md §"state home"). A
  standalone-category reason must still be `man`-projectable and `learn`-
  aggregable; only its *verification against a picker* is what a no-picker host
  forgoes.

## North-star acceptance (the whole plan is done when)

```bash
# A host that wants ONLY typed outcomes, no dispatch:
pip install dos-kernel               # dist name is dos-kernel (NOT `dos` — that PyPI name is unrelated)
dos init ./svc                       # scaffolds dos.toml
```
```toml
# svc/dos.toml — declare your OWN outcome categories, no dispatch concepts
[reason_categories]
categories = ["RETRYABLE", "TERMINAL", "NEEDS_HUMAN"]
strict     = true                    # UNCLASSIFIED is a hard error (noImplicitAny)

[reasons.UPSTREAM_5XX]
category = "RETRYABLE"               # validated against MY set, not TRUE_DRAIN/…
[reasons.BAD_CREDENTIALS]
category = "NEEDS_HUMAN"
```
```bash
dos man wedge                        # lists UPSTREAM_5XX, BAD_CREDENTIALS — emittable + documented
dos man wedge UPSTREAM_5XX           # full man page, projected from MY fields
dos check ./svc/verdicts/*.json      # FAIL if any emitted reason_class isn't declared (tsc --noEmit)
```

…while `dos doctor`/`dos verify`/`dos arbitrate` in the **dispatch** host (`job`,
default config) behave byte-for-byte as today, the `picker_oracle` lockstep test
stays green, and a workspace that declares no `[reason_categories]` table inherits
the five built-in dispatch categories unchanged.

---

## Phase 1 — categories-as-data (the G1 unblock, behavior-preserving)

The smallest end-to-end slice that makes reasons standalone: lift the hardcoded
five-category frozenset into config data, defaulting to exactly today's five, and
prove nothing in the dispatch host moved.

- **1a.** Add a `CategorySet` value to `dos.reasons`: a frozen, ordered, closed
  set of category tokens with membership + `is_known`. Define
  `DISPATCH_CATEGORIES = CategorySet({"TRUE_DRAIN", "OPERATOR_GATE",
  "STALE_CLAIM", "MISROUTE", "UNCLASSIFIED"})` — the literal five from
  `KNOWN_CATEGORIES`, reproduced verbatim. `UNCLASSIFIED` is a permanent member of
  *every* category set (it is the drift sentinel, not a domain category).
- **1b.** Make `ReasonSpec.__post_init__` (`reasons.py:111` — the
  `category not in KNOWN_CATEGORIES` raise) validate `category` against an injected
  `CategorySet` rather than the module-global `KNOWN_CATEGORIES` frozenset. The
  default remains `DISPATCH_CATEGORIES`, so a `ReasonSpec(...)` built with no
  custom set validates exactly as today. `ReasonRegistry` carries its `CategorySet`
  so the registry knows its own universe.
- **1c.** Thread the `CategorySet` onto `SubstrateConfig` (a new field defaulting
  to `DISPATCH_CATEGORIES`), the way `reasons` already rides the config. The
  generic `default_config` and `job_config` both keep the five.
- **1d.** Make `picker_oracle.resolve_cause` robust to a category that is **not** a
  `NoPickCause` member: today `NoPickCause(cat)` (`picker_oracle.py:219`) raises
  for an unknown string and is swallowed to `UNCLASSIFIED` by the bare `except`.
  Make that explicit and intentional — a category outside `NoPickCause` means
  "this reason is not a dispatch-verifiable cause," which correctly resolves to
  `UNCLASSIFIED` *from the picker's point of view* (the picker can't cross-check a
  category it has no rule for). Document that a standalone host simply never calls
  the picker, so the resolution is moot for it. **No behavior change for the
  dispatch host** — its categories are all `NoPickCause` members, so the existing
  branch is taken unchanged.

**Litmus (Phase 1):**
- The **existing refusal-plane lockstep suite (`tests/test_refusal_and_tokens.py`)
  stays green** routed through the injected default `CategorySet` — the proof the
  lift was behavior-preserving (the single most important litmus). What we loosen
  is the *declaration-time* frozenset (`reasons.py:67`); the *runtime* oracle
  round-trip (`picker_oracle.py:219`) is left exactly as-is, already drift-tolerant
  — so the dispatch host's every-category-is-a-`NoPickCause`-member path is
  untouched.
- `tests/test_typed_outcomes.py::test_default_categories_are_the_dispatch_five` —
  a `ReasonSpec` built with no custom set still rejects a non-dispatch category.
- `tests/test_typed_outcomes.py::test_custom_category_set_accepts_own_tokens` — a
  `ReasonSpec` built against `CategorySet({"RETRYABLE", "TERMINAL"})` accepts
  `RETRYABLE` and rejects `TRUE_DRAIN`.
- `tests/test_typed_outcomes.py::test_non_dispatch_category_resolves_unclassified`
  — a reason whose category is not a `NoPickCause` member resolves to
  `UNCLASSIFIED` via `resolve_cause` **without raising** (the swallow made an
  explicit branch).

---

## Phase 2 — `[reason_categories]` in `dos.toml` + the standalone init scaffold

Make the standalone path declarative — no code, just data — and give `dos init` a
scaffold that doesn't presuppose dispatch.

- **2a.** Teach the `dos.toml` loader a `[reason_categories]` table:
  `categories = [...]` (the closed set) and `strict = bool` (G3, wired in Phase 3).
  Folds onto the base the SCV/WCR way: **declaring `categories` REPLACES** the
  default set wholesale (the same replace-not-extend semantics as `[lanes]`/
  `[stamp]`, and for the same reason — your universe is yours), while a missing
  table inherits `DISPATCH_CATEGORIES`. `UNCLASSIFIED` is always implicitly
  included even if omitted. A `[reasons.X]` whose `category` is not in the
  declared set fails loud at load (the existing `ReasonSpec` constructor error,
  now keyed on the workspace's set) — a typo is surfaced, never silently drifted.
- **2b.** Reuse `utf-8-sig` BOM-stripping on the read (the
  `project-dos-genericization-verified-state` fix — PowerShell writes a BOM;
  raw `tomllib` chokes). Pin it; this is the foreign-repo defect WCR's review
  caught and it will recur on any new table.
- **2c.** Add an `--minimal` (or `--no-dispatch`) flag to `dos init` that scaffolds
  a `dos.toml` with a `[reason_categories]` + example `[reasons.*]` block and
  **omits** `[lanes]`/`[paths]`/`[stamp]` (the dispatch tables). The default
  `dos init` is unchanged (full dispatch scaffold). This is the literal "minimal
  surface" front door the adoption question asks for.

**Litmus (Phase 2):**
- `tests/test_typed_outcomes.py::test_toml_categories_replace_default` — a
  `[reason_categories] categories = ["RETRYABLE","TERMINAL"]` table yields a
  registry that accepts `RETRYABLE`, rejects `TRUE_DRAIN`, and still accepts
  `UNCLASSIFIED`.
- `tests/test_typed_outcomes.py::test_toml_reason_bad_category_fails_loud` — a
  `[reasons.X]` citing a category absent from the declared set raises at load.
- `tests/test_typed_outcomes.py::test_toml_categories_bom_tolerant` — a UTF-8-BOM
  `dos.toml` parses (the PowerShell-default-encoding defect; the existing
  `utf-8-sig` read in `reasons.load_from_toml`, `reasons.py:391`, already does this
  — the test pins it for the new table).
- `tests/test_typed_outcomes.py::test_init_minimal_omits_dispatch_tables` —
  `dos init --minimal` writes `[reason_categories]`/`[reasons]` and no
  `[lanes]`/`[paths]`/`[stamp]`.

---

## Phase 3 — the reason-drift rail (`dos check`) + the strict posture (the G2/G3 close)

Ship the completeness rail HACKING.md already promises, and the `noImplicitAny`
stance — the two things that make an *open, standalone* reason vocabulary safe.

- **3a.** Add a `dos check [GLOB...]` verb (or fold into `dos doctor --check`; pick
  at design — a standalone host has no "doctor" workspace ceremony, so a free-
  standing `dos check` reads better for the minimal surface). It scans verdict/
  outcome envelopes (JSON files carrying a `reason_class`) and reports any token
  **not** in the active `ReasonRegistry` — the documented "emitted but undeclared
  → fail" rail (HACKING.md §"`--check`"), the `tsc --noEmit` of outcomes. The
  verdict IS the exit code (clean=0, drift-found=1, contract error=2), so CI
  branches on it directly — the same exit-code-as-verdict discipline as
  `dos gate` ([SKP](74_skill-pack-plan.md)).
- **3b.** Honor `[reason_categories] strict = true`: in strict mode an
  `UNCLASSIFIED` resolution is a **hard error wherever it surfaces** (the check
  fails, and a strict-host library call may raise rather than silently classify) —
  `noImplicitAny` for outcomes. Default `strict = false` preserves today's
  forward-compatible "unknown classifies as drift but doesn't crash" behavior
  (`reasons.py:167` `category_for`), so the dispatch host is unaffected.
- **3c.** *(framing — the G3 close)* Add a **"Start here — gradual adoption"**
  section to HACKING.md that presents reasons as the minimal core and the ladder
  above it (reasons-only → wire `dos check` into CI → add `[reason_categories]` →
  grow into lanes when you actually have concurrency), with the TypeScript table
  from this plan's thesis. Restate the one asymmetry: the standalone category set
  defaults *generic-but-replace* while strict defaults *off* (loosen-knowingly is
  the safe direction here because there is no oracle to falsely satisfy). Flip
  nothing in the axis statuses — TOA is an adoption surface over Axis 1, not a new
  axis.

**Litmus (Phase 3):**
- `tests/test_typed_outcomes.py::test_check_flags_undeclared_reason` — an envelope
  carrying a `reason_class` absent from the registry makes `dos check` exit 1 and
  name the token.
- `tests/test_typed_outcomes.py::test_check_clean_when_all_declared` — every
  emitted reason declared ⇒ exit 0.
- `tests/test_typed_outcomes.py::test_strict_unclassified_is_hard_error` — under
  `strict = true`, an `UNCLASSIFIED` resolution fails the check (and the strict
  library path raises); under default, it classifies as drift without raising
  (today's behavior, the `reasons.py:167` `category_for` path, pinned unchanged).
- A dispatch-host repo (`job`/default config, no `[reason_categories]`) runs
  `dos check` over its own verdict envelopes with exit 0 — the existing
  vocabulary is complete, so the new rail is silent for it.

---

## Out of scope (explicitly)

- **The outcome-verdict vocabulary (`GateVerdict`/`OutcomeVerdict`).** That is
  Axis 2 (HACKING.md §2), its own 🔜-*design* plan. TOA is the *refusal* half only.
  The two are siblings; see the scope note above.
- **Behavioral lint rules (the lying-verdict detector as a generic verb).**
  `dos check` here is a *completeness* rail (every used reason is declared), the
  `tsc` analogue. The linter's other move — "you claimed BLOCKED but the commit
  set is non-empty, that's a lie" — already exists host-side (the four
  claimed-cause-vs-on-disk-state cross-checks `picker_oracle.py:346-431` defines,
  dispatched inside `classify` at `picker_oracle.py:523-538`; `tokens.py:179`
  `KNOWN_VERDICT_TOKENS` `claims-X` hints) and is *exactly `verify()` generalized*.
  Promoting it to a generic kernel `dos lint`/`dos audit` verb is the natural
  follow-on, but it is a separate plan (it needs a host-agnostic "claimed vs
  re-derived" contract, which is real design beyond this adoption surface).
- **Changing the dispatch host's default categories.** The five stay the five for
  `job`/default config. G1 makes the set *declarable*; it never *moves the
  default*. Re-litigating the five would break the `picker_oracle` lockstep this
  plan is careful to preserve.
- **TOML-declared *computed* reasons.** Data reasons go in `[reasons]`; reasons
  whose category/refusal must be *computed* stay code (`entry_points`/`extend()`),
  the same data-vs-behavior split HACKING.md draws for every axis.

## Why this plan, and why now

The adoption question — *"for users who want a more minimal surface, is this an
adoption path to start?"* — is correct, and the answer is **yes, reasons are
DOS's `tsconfig.json`**: pure stdlib, zero deps, no plan/lease/arbiter ceremony,
solving a problem every codebase already has badly (stringly-typed outcomes).
TOA is small and lands cleanly on the SCV/WCR/RND-generic, SKP-green,
ADM-shipped base. Its risk is the lowest in the series — Phase 1 is a
behavior-preserving lift proven by the existing lockstep suite; the only genuinely
new surface (`dos check`) is additive and silent for the dispatch host. It is the
natural complement to the just-shipped ADM: ADM opened the *safety* seam (the
admission-predicate axis), TOA opens the *adoption* seam (the standalone-reasons
on-ramp), and neither touches the other's core. Shipping the standalone path
**without** the drift rail would be the one unsafe move — so G1 and G2 ship
together, openness and verifiability reconciled by the registry-as-data design
exactly as they are for the dispatch reasons today.
