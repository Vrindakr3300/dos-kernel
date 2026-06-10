# ADM — Admission-predicate plan (Axis 3: pluggable safety hooks)

> **Status:** ✅ **SHIPPED** (all three phases, 2026-06-01). `src/dos/admission.py`
> carries `AdmissionVerdict` (admit/refuse only — no force-admit), the
> `AdmissionPredicate` Protocol, `DisjointnessPredicate`, the conjunctive
> `run_predicates` (first-refusal-wins, raise⇒fail-closed), and the
> `dos.predicates` entry-point discovery. `src/dos/self_modify.py` ships the
> `SelfModifyPredicate` over `_DISPATCH_RUNTIME_FILES`; `SELF_MODIFY` is a
> `reasons.BASE_REASONS` member (category `MISROUTE`) so it is emittable /
> verifiable / refusable / `dos man wedge SELF_MODIFY`-documented. The arbiter
> routes EVERY admit path through the conjunction (the keyword, cluster, and
> exclusive-lane fast-paths all gate on it — see the review note below), with
> built-ins by default (pure, no discovery I/O) and the CLI resolving discovered
> plugins at the boundary and passing them in, like `pick_oracle`. `dos doctor`
> lists the active predicates; HACKING.md Axis 3 is flipped to shipped. Pinned by
> `tests/test_admission.py` (44 cases) + the unchanged `tests/test_arbiter.py`
> (the behavior-preservation proof) — full kernel suite 311 green; a 8000-case
> property sweep confirms the built-in default is byte-identical to
> disjointness-only for every non-runtime tree.
>
> **A 5-lens adversarial review (45 agents) caught 3 real defects, all fixed +
> regression-pinned:** (1) the **cluster** and **exclusive-lane** fast-paths
> returned `acquire` WITHOUT running the conjunction — SELF_MODIFY (and
> disjointness, for clusters) was bypassed on those paths; now every direct-acquire
> fast-path gates through `_admission_verdict`. (2) the **idle-repo gap** —
> `run_predicates` was a vacuous admit on empty `live_leases`, so a request-absolute
> predicate (SELF_MODIFY) never fired on an idle repo; now the conjunction runs once
> against an empty-lease sentinel so request-absolute predicates fire regardless of
> liveness, while lease-relative ones (disjointness) still admit on the empty lease.
> (3) the **double-oracle-call** — the auto-pick path called `pick_oracle` twice
> (once to admit, once to report `pick_count`), so a non-deterministic oracle could
> report a count that disagreed with the admission decision; now the admission-driving
> count is cached and reported. A fourth, lower-severity find (a buggy predicate
> returning a non-`AdmissionVerdict` crashed the runner instead of failing closed)
> was caught + fixed during self-review before the workflow. It was the last open
> plan of the series; SCV/WCR/RND/SKP/DOS-HOME all shipped earlier. It deliberately
> landed last because it touches the **safety core** — the highest leverage **and**
> highest risk. Throughline-first.

## The gap this closes

HACKING.md Axis 3 is 🔜 *design*: the arbiter's admission logic — `_lease_blocks`
(`arbiter.py:72`) + `overlap_verdict` (the ≤30% soft-overlap tree-disjointness
rule, `lane_overlap.py:79`) — is the kernel's *safety element*: it's what stops
two agents editing the same files concurrently. Today that logic is fixed. A
workspace can't add its own admission rule (e.g. "refuse a new lease when over
the monthly token budget," "refuse a lease that would touch the orchestrator's
own running code" — the `SELF-MODIFY` hazard in
`project-dos-self-modification-hazard`) without forking the arbiter.

The hackable form (HACKING.md §3): a list of pure **admission predicates**, each
`(request, live_lease, config) -> AdmissionVerdict`, resolved from a
`dos.predicates` entry-point group. The arbiter runs the built-in disjointness
predicate **plus** any registered ones.

## The one invariant that makes this safe: **conjunctive-only**

This is the highest-risk axis — a buggy predicate that *loosens* admission could
let two agents collide, the exact failure the arbiter exists to prevent. The
guardrail is structural, not careful coding:

> **A predicate may only REFUSE. It can never force-admit over a built-in
> refusal.** Predicates compose conjunctively: admission requires the built-in
> disjointness check **and** every registered predicate to admit. Adding a
> predicate can only make admission *stricter*, never looser.

So the worst a buggy/malicious predicate can do is refuse too much (a visible,
safe-direction failure an operator notices immediately), never admit a collision.
The `--force` operator override stays the *only* thing that can overrule a
refusal — exactly as today (`arbiter.py:127`, `force=True` skips the
disjointness/overlap refuses but still respects a live exclusive lane). A
predicate refusal is overridable by `--force` the same way; a predicate cannot
itself force anything.

## Design laws this plan must honor

- **The arbiter stays PURE** (`CLAUDE.md`, `arbiter.py:107` "No I/O —
  `live_leases` is passed in, the decision is returned"). A predicate is also
  pure: any I/O it needs (reading a token-budget file) happens *before* the call,
  with the result passed in via `config` or a pre-computed input — never inside
  the predicate during arbitration. This mirrors how `pick_oracle`
  (`arbiter.py:131`) already does its I/O outside the arbiter.
- **Oracle/predicate failure can only ADD refusals, never remove them**
  (the `pick_oracle` rule, `arbiter.py:131-137`, and design-law: "oracle failure
  can only add skips, never remove a viable fallback"). A predicate that *raises*
  is treated as a refuse (fail-closed), not a skip — the safe direction for a
  safety hook. This is the inverse of the renderer rule and is deliberate.
- **Self-modification is a kernel concern** (`project-dos-self-modification-hazard`,
  mechanism (a)): the `SELF-MODIFY` refuse — intersect the requested tree with a
  `_DISPATCH_RUNTIME_FILES` set — is "the natural DOS-kernel realization" of a new
  typed refuse. ADM's predicate seam is the *vehicle* for it: ship `SELF-MODIFY`
  as a **built-in predicate** (always-on, like disjointness), and the same seam
  lets workspaces add their own. This plan delivers the seam; the
  `_DISPATCH_RUNTIME_FILES` enumeration is its first built-in predicate.

## North-star acceptance (the whole plan is done when)

```python
# A workspace ships a budget guard as a dos.predicates entry_point…
def budget_guard(request, lease, config):
    if over_budget(config):                       # I/O done before the call, cached on config
        return AdmissionVerdict.refuse("monthly token budget exhausted")
    return AdmissionVerdict.admit()
```

```bash
pip install -e my_budget_plugin                   # registers the predicate
dos arbitrate --lane api --kind cluster --leases '[]'        # REFUSED: monthly token budget exhausted
dos arbitrate --lane api --kind cluster --leases '[]' --force # ADMIT (operator override)
```

…and a built-in `SELF-MODIFY` predicate refuses a lease whose tree includes
`src/dos/arbiter.py` (the orchestrator's own running code), with `--force` the
only escape — while the full existing arbiter suite stays green (every predicate
admits by default, so today's behavior is unchanged).

---

## Phase 1 — `AdmissionVerdict` + the conjunctive runner, built-ins only (throughline)

The smallest end-to-end slice: refactor today's fixed disjointness check into the
*first registered predicate*, run it through a conjunctive runner, change nothing.

- **1a.** Add `dos/admission.py`: a frozen `AdmissionVerdict` (`admit: bool`,
  `reason: str`) with `.admit()` / `.refuse(reason)` constructors, and the
  `AdmissionPredicate` `Protocol` (`name: str`,
  `__call__(request, live_lease, config) -> AdmissionVerdict`).
- **1b.** Wrap the existing disjointness/overlap logic as the built-in
  `DisjointnessPredicate` (delegates to `lane_overlap.overlap_verdict` /
  `_lease_blocks` unchanged). Add a `run_predicates(predicates, request,
  live_leases, config) -> AdmissionVerdict` that calls each predicate against
  each live lease and returns the **first refusal** (conjunctive: first refuse
  wins; all-admit ⇒ admit). A predicate that *raises* is caught and converted to
  a refuse naming the predicate (fail-closed).
- **1c.** Route `arbitrate()`'s collision check through `run_predicates` with a
  `built_in_predicates=[DisjointnessPredicate()]` list. **Behavior identical** —
  the same overlaps refuse, the same disjoint trees admit, `--force` still skips
  exactly what it skips today.

**Litmus (Phase 1):**
- The **entire existing arbiter/overlap suite stays green** routed through
  `run_predicates` — this is the proof the refactor was behavior-preserving
  (the single most important litmus in the series; the arbiter is the safety
  core).
- `tests/test_admission.py::test_raising_predicate_fails_closed` — a predicate
  that raises yields a REFUSE, not an admit and not a crash.
- `test_first_refusal_wins` — two refusing predicates surface the first; the
  conjunction short-circuits.

---

## Phase 2 — the `SELF-MODIFY` built-in predicate (the first new safety rule)

Deliver a real second built-in predicate — the self-modification guard — proving
the seam carries genuine safety logic, not just a refactor.

- **2a.** Enumerate `_DISPATCH_RUNTIME_FILES`: the kernel modules that sit in a
  running orchestrator's own execution path (`arbiter.py`, `gate_classify.py`,
  `loop_decide.py`, `wedge_reason.py`, `tokens.py`, the lane taxonomy source).
  This is the T1 set from `project-dos-self-modification-hazard`; pin it as data
  with a comment tying each entry to *why* it's runtime-critical.
- **2b.** Ship `SelfModifyPredicate`: refuse a lease whose requested tree
  intersects `_DISPATCH_RUNTIME_FILES`, with a new typed `WedgeReason`
  (`SELF_MODIFY`, category `MISROUTE` or a new dedicated category — decide at
  design, declare it in `reasons.py` `BASE_REASONS` so it's emittable / verifiable
  / refusable / `dos man`-documented, per the Axis-1 mechanism). Always-on, like
  disjointness.
- **2c.** Make it overridable only by `--force` (the operator's explicit "yes, I
  am editing the kernel between loop runs" — the safe, human-in-loop path the
  hazard memo calls for), never by another predicate.

**Litmus (Phase 2):**
- `test_self_modify_refuses_kernel_tree` — a lease tree including
  `src/dos/arbiter.py` is REFUSED with `reason_class == SELF_MODIFY`.
- `test_self_modify_force_override` — the same lease with `--force` ADMITs.
- `test_self_modify_reason_is_documented` — `dos man wedge SELF_MODIFY` renders
  (the new reason is in the registry — the Axis-1 completeness rail).
- A lease on a non-runtime tree (`src/api/**`) is unaffected.

---

## Phase 3 — entry_point discovery for workspace predicates + the rail

Open the seam to workspace-supplied predicates, with the conjunctive-only
guarantee enforced at the boundary.

- **3a.** Resolve the `dos.predicates` entry-point group (like RND's renderers)
  and append discovered predicates **after** the built-ins in the conjunction.
  Because the runner only honors *refusals*, a discovered predicate is
  structurally incapable of loosening admission — there is no "admit harder"
  return value to misuse. Document this as the safety contract.
- **3b.** Make `examples/dos_ext` register a sample predicate (e.g. the
  `budget_guard` skeleton from HACKING.md §3) so the copy-me example exercises
  both behavior axes (renderer + predicate).
- **3c.** *(completeness rail)* `dos doctor` lists the active admission predicates
  (built-in + discovered) so an operator can see exactly what gates their
  arbiter — the predicate analogue of "see the active reason set." Flip
  HACKING.md §3 from 🔜 *design* to ✅ *shipped*, restating the conjunctive-only
  invariant prominently.

**Litmus (Phase 3):**
- `test_discovered_predicate_can_refuse` — a registered predicate's refusal
  blocks admission.
- `test_discovered_predicate_cannot_admit_over_builtin` — a discovered predicate
  returning `admit()` does **not** override a built-in disjointness refusal (the
  conjunction still refuses). This is the load-bearing safety test of the whole
  plan.
- `dos doctor` names the active predicates.

---

## Out of scope (explicitly)

- **Predicates doing I/O during arbitration.** All I/O is pre-computed and passed
  in (via `config` or a cached field), keeping the arbiter pure. A predicate that
  wants live data gets it from a value the caller resolved before `arbitrate()`,
  exactly as `pick_oracle` does.
- **Force-admit predicates.** There is deliberately no return value that forces
  admission. `--force` (operator) remains the sole override. Re-litigating this
  would break the one invariant that makes the open seam safe.
- **TOML-declared predicates.** Predicates are code → `entry_points`. (HACKING.md
  floats that a *simple* always-refuse-on-flag predicate could be data; defer —
  the safety-criticality argues for keeping predicates in reviewed code, not a
  config file, until there's a concrete demand.)
- **The heavier self-modification mechanisms** (snapshot-pinning the orchestrator,
  cold-dispatch for T2 hooks, verdict-version stamping) from the hazard memo —
  ADM ships mechanism (a), the arbiter-refuse, only. The others are separate
  plans if mechanism (a) proves insufficient.

## Why this is last

It touches the **safety core** — the one part of the kernel where a bug doesn't
produce ugly output or a wrong path but lets two agents *collide on shared
state*. It ships last so it lands on a base already made generic and green by
SCV/WCR/RND, with the most conservative slicing (Phase 1 is a pure behavior-
preserving refactor proven by the existing suite; new safety logic only arrives
in Phase 2 once the runner is trusted). The conjunctive-only invariant is what
lets an *open* predicate set coexist with a safety guarantee — openness and
safety are not in tension here, exactly as the registry-as-data design reconciles
openness and verifiability for reasons.
