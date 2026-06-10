# 257 — Open-plans survey: what's specced but not finished

> **Status:** survey / index (2026-06-08). Not itself a build plan — a
> point-in-time inventory of every `docs/NN_*.md` plan that is **unbuilt or
> partially built**, with the concrete *remaining* work pulled out of each, so the
> next builder picks from a ranked menu instead of re-reading 197 docs. Read
> [`README.md`](README.md) for the full plan index; this doc is the *open subset*
> with the residual deltas extracted.
>
> **How it was derived:** the first `> **Status:**` line of all 76 status-bearing
> docs was harvested and filtered to drop everything marked SHIPPED / COMPLETE /
> EXECUTED / RETROSPECTIVE; each survivor was then read for its own "what remains"
> / phase table / out-of-scope section. The statuses below are **self-reported
> prose** — the forgeable rung (CLAUDE.md). They are an *index*, not a ground-truth
> verdict; confirm any single item with `dos verify` / `dos commit-audit` before
> trusting "done." (`dos plan --once` reports "no plans declared" on this repo by
> design — these are prose docs, not phase-table plans; see CLAUDE.md step 5.)
>
> **Scope note:** four docs that the README still tags `📋 planned` are actually
> **shipped** — [`207`](207_dispatch-workflow-extraction-and-the-pickable-substrate-completion.md)
> (picker substrate, SHIPPED 2026-06-07) most notably. They are excluded here; the
> README table is the drifted artifact, not this survey. (A README-vs-doc status
> reconciliation is itself a small open task — see §4.)

---

## 1. Unbuilt design plans (nothing shipped yet)

The clearest "open": each argues for a capability that does not exist in the tree.
Ordered roughly by value-per-effort (cheap + high-leverage first).

### Admission-predicate family (cheap — a new *payload* on shipped machinery)

These three are all "one more built-in `AdmissionPredicate` over one more declared
axis," riding the already-shipped `dos.predicates` conjunction + `SubstrateConfig`
seam + `reasons.BASE_REASONS`. Each is a *days* build because the machinery exists;
the predicate is new data on it, the `SelfModifyPredicate` sibling. All three are
**detection-only** until [`126`](126_the-mediated-write-and-the-apply-gate-pep.md)
gives them teeth (their shared Phase 4).

- **[`125`](125_the-trifecta-color-and-the-capability-conjunction.md) — the lethal-trifecta color.**
  A predicate that refuses when an agent's capability-color union reaches
  cardinality 3 (`private-data` ∩ `untrusted-content` ∩ `exfiltration`). The
  single most-cited agentic-security defense, restated as a set-union refusal — the
  exact shape `arbitrate` already is. **Remaining:** the whole thing (new predicate
  + typed refuse + capability-color axis as declared data). The cheapest Phase-1
  payload of the security-PEP program.

- **[`247`](247_the-clearance-lattice-a-sensitivity-class-as-an-arbiter-color.md) — the clearance lattice.**
  The docs/125 pattern re-aimed at a *sensitivity lattice*: refuse a write whose
  region-level is below the level of everything the lease reads (or that straddles
  incompatible compartments). A pure order-check; template is the shipped
  `data_class.py` four-class path classifier. **Remaining:** the whole predicate +
  its lattice axis. Sibling to 125, not a duplicate (LEVEL, not COLOR).

- **[`248`](248_instruction-provenance-rejecting-the-injected-directive.md) — instruction provenance.**
  The "sibling axiom to `verify()`": reject an effect whose *triggering
  instruction* traces to untrusted/unknown input, even when the effect is
  well-formed (the clean-artifact injection `verify()` passes cleanly). Generalizes
  the shipped `arg_provenance.py` (docs/143) using `log_source.py`'s (docs/117)
  accountability labels. **Remaining:** the generalized directive-grain verdict +
  the trust-label trace. This is the trifecta's "untrusted-content" leg as a *trace
  on a directive* rather than a color on a capability.

### Verify / plan surface (medium)

- **[`109`](109_non-git-evidence-in-the-verify-verdict.md) — a non-git rung above the git ladder.**
  Give `ShipVerdict` a top rung (`source="ci-green"`) minted only when a host wired
  a non-git oracle and its evidence is agent-unforgeable — **conjunctive** (sharpens
  or withholds a ship, never fabricates one). The occupant already ships
  (`drivers/ci_status.py`) but sits *outside* `verify()`, consulted only by the
  stable-release script. **Remaining:** the seam in `oracle.py` that consults a
  by-name driver at the boundary; fold the `[ci]`/`[verify]` `dos.toml` table into
  `SubstrateConfig` (today it folds only `[lanes]`/`[paths]`/`[stamp]`/`[reasons]`).

- **[`111`](111_plan-scaffolding-and-automatic-plan-vs-oracle-checking.md) — plan scaffold + auto plan-vs-oracle check.**
  `dos plan` exists (the read-only fan-out); two gaps remain. (a) A **scaffold** —
  `dos init --with-example-plan` / `dos plan scaffold` writes a starter plan into
  `plans_glob` + a `dos doctor --check` harvest-finding proving it parses under the
  active grammar. (b) An **automatic rung** — the watchdog driver periodically fans
  `oracle.is_shipped` over the active plan and records each `⚠over-claim` as a new
  `dos decisions` source (record + propose, never auto-correct). **Remaining:** both;
  the scaffold writes a file the kernel already reads, the auto-check lives in the
  watchdog *driver*, never a new kernel verb.

- **[`112`](112_the-dynamic-verified-by-dos-badge.md) — the dynamic "Verified by DOS" badge.**
  The static badge ships (asserts *adoption*, always green). The dynamic one is a
  `dos badge` / `dos verify --shields-endpoint` output mode emitting shields.io
  endpoint JSON from a real verdict, with a **three-state honesty rule** (real ship
  → green, `via none` → NEUTRAL never red, evidenced `NOT_SHIPPED` → red).
  **Remaining:** Phase 1 the local JSON output mode (no service); the hosting/trust
  model is gated behind it + behind PyPI publish.

### Concurrency-class operator surface (medium — kernel half already landed)

- **[`110`](110_the-concurrency-class-operator-surface.md) — make the class budget reachable + declarable.**
  The docs/97 Phase-1 claim-budget **admission step already landed in the pure
  arbiter** (`arbitrate(..., class_budgets={"priority": 3})`, pinned by
  `tests/test_arbiter.py`). But it is reachable *only as a Python parameter* —
  nothing in `cli.py` or `config.py`. **Remaining:** (1) `dos arbitrate
  --class-budget K=N` flag; (2) a `[[concurrency_class]]` `dos.toml` table read as
  the default budget set; (3) re-express host "priority work" as a declared class
  with a `TopPickablePlan` region source (pool stays host-side). Every step is
  byte-identical when its surface is absent.

- **[`97`](97_concurrency-class-model-plan.md) — the full concurrency-class model (parent of 110).**
  Replace the three hard-coded lane-kinds (`concurrent`/`exclusive`/`autopick`)
  with one `ConcurrencyClass` registry `{name, region_source, max_concurrent,
  rank}`; clusters / exclusive / named / priority all collapse to instances.
  **Remaining:** the registry + `RegionSource` model + the lease `class`/`payload`
  fields + folding host soft-claim into the class registry. 110 is the thin
  operator slice of this; 97 is the structural whole. **Do 110 first** — it banks
  the already-built kernel work; 97 is the larger refactor above it.

### Enforcement & forensics (larger lifts)

- **[`126`](126_the-mediated-write-and-the-apply-gate-pep.md) — the mediated write / apply-gate PEP.**
  DOS's first **enforcement point**: a `dos`-mediated write (commit / lease grant /
  spawn) that runs the already-computed verdicts *at the moment the effect would
  land* and refuses the effect itself. Turns "detected, not prevented" into
  "prevented" for a narrow, effect-typed chokepoint. The largest of the security
  family — it is the *teeth* that 125/247/248 (detectors) depend on for binding.
  **Remaining:** all of it; the discipline (§3 of the doc) that keeps it from
  becoming a sandbox is the whole design.

- **[`118`](118_the-fleet-postmortem-and-the-attribution-join.md) — close the WAL `run_id` gap.**
  DOS's flagship audit artifact — *"the agent burned tokens while the kernel was
  refusing its lane"* — **cannot fire on real data** because no producer writes a
  lane lease carrying *both* `run_id` and `loop_ts`. The join logic, consumer, and
  refusal side are all built and tested; the *acquire* side is the single gap
  (`acquire_entry` has no `run_id` parameter). **Remaining:** one producer change —
  stamp `run_id` onto the lease at acquire time on the real dispatch path. (A
  measured gap, re-derived live 2026-06-03, not assumed.)

- **[`100`](100_native-spine-port-plan.md) — the native-spine (Python → Go) port.**
  Reimplement *only* the pure verdict cores as one Go binary behind
  `DOS_SPINE_NATIVE=1`, Python staying the fallback + differential oracle. Two
  payoffs: a quality ratchet (the core becomes a frozen dual-implemented contract)
  and CI-storm cold-start elimination (~1.5s → ~150-400ms per `verify`).
  **Remaining:** everything; greenfield, no Go scaffolding exists. The biggest lift
  in this list and the most speculative — gated on whether the CI-storm regime is
  real for an actual consumer.

### On-ramp (small, low-priority)

- **[`78`](78_typed-outcome-adoption-plan.md) — typed outcomes as a standalone layer.**
  Marked "committed — **NOT STARTED**." Make the shipped reason vocabulary usable
  *without* the dispatch machinery (the "DOS is a type system for outcomes, reasons
  are its `tsconfig.json`" framing) so a host can adopt typed outcomes in an
  afternoon. **Remaining:** lift `ReasonSpec.category` off the five picker-coupled
  values (`CategorySet`), a `[reason_categories]` table, `dos check`, `dos init
  --minimal`. Behavior-preserving; pinned by a new `tests/test_typed_outcomes.py`.

---

## 2. Partially shipped (phases remain)

- **[`82`](82_liveness-oracle-plan.md) — liveness oracle. Phases 1–2 shipped; Phase 3 open.**
  The verdict + git-rung + journal/heartbeat rungs ship and are green. **Remaining
  (Phase 3):** **3a** the first real consumer — `loop_decide` gains a
  `StopReason.SPINNING` so a loop self-stops on ground-truth spin (opt-in,
  byte-identical without it); **3b** the *queue-row* form — a SPINNING/STALLED run
  as a `dos decisions` entry with a kill/let-it-ride action (note: the
  *dashboard* half already shipped — `dos top`'s status chips ARE
  `liveness.classify`); **3c** policy/rails — `[liveness]` `dos.toml` block,
  `--output json`, `dos doctor` naming the active windows. The highest-value entry
  in the distrust-primitive map; 3a is the payoff.

- **[`99`](99_runtime-validation-and-the-actuation-boundary.md) — the self-stop seam + the actuation boundary.**
  The theory companion to 82 Phase 3 + the `reap`-family `halt` verb. Closes the
  loop on the most expensive historical failure class (hung run / budget didn't
  fire — eight jobs × ~4.4h). Draws the actuation line: self-stopping a loop's own
  control flow is in-bounds; signalling a *foreign* process is record+propose only.
  **Remaining:** the pure loop self-stop seam (= 82's 3a wiring) + the one effectful
  `halt` boundary verb. Tightly coupled to 82 — build them together.

- **[`120`](120_the-status-digest-a-folded-fact-for-a-fleet.md) — the status digest. Phase 1 shipped; 2-4 open.**
  `dos status <run_id>` folds the four shipped reads (liveness / ledger-*verified* /
  held lease / resume) into one fail-closed A2A fact that *structurally cannot
  expose a self-report*. `status.py` + 8 tests ship (Phase 1). **Remaining:**
  Phase 2 the CLI verb, Phase 3 the MCP `dos_status` tool, Phase 4 the follow-up
  tier. No new mechanism — the contribution is the fold + its fail-closed
  construction. The "hand-run CLI → platform-team dashboard" threshold surface.

- **[`184`](184_the-supervisor-loop-plan.md) — the supervisor loop. Phases 1-2 shipped; Phase 3 open.**
  `supervise()` (liveness's *population*-axis sibling) + emit-only `dos loop` +
  watchdog driver + skill all ship. **Remaining (Phase 3):** value-aware spawn
  ranking, *acting* on spin (vs only flagging), and a `[supervise]` policy seam.

- **[`119`](119_the-claim-and-the-tail-wagging-lane.md) — claim-not-lane. Phase 0 shipped; 1-4 open.**
  The `UNKNOWN_LANE` honesty fix ships (`bc83d94`). **Remaining (the phase table):**
  **1** ad-hoc claim identity (admission already works; only the lease *handle* is
  missing — the next build, highest value-per-effort); **2** region-digest identity
  in WAL/journal so `top`/`decisions`/`resume` group unnamed claims; **3a**
  precise-overlap predicate for the glob-vs-files case (opt-in, under the floor);
  **3b** read/write lock-modes + compatibility matrix; **4** lane-as-derived-view
  (taxonomy becomes sugar over the claim type). Plus a no-code operator-guidance
  win: a `dos doctor`/lint warning when a claim's tree is broader than its footprint.

---

## 3. Design-only / live research threads (open, but not "unbuilt code")

These carry no pending implementation in the kernel sense — they are positioning
notes, or live experiments whose *next step* is a run, not a merge.

- **[`225`](225_the-ci-gate-consumer-the-verdict-at-the-pr-boundary.md)** — 🟡 Design.
  The *mechanism* (`hook_exit`/`exec_capability`) already ships; this is the wiring
  of the verdict at the PR boundary as a consumer. Pairs with 112 (badge) and 109
  (CI rung).
- **[`219`](219_the-capability-routing-floor-why-model-agnostic-is-the-point.md)** — DESIGN / positioning, no kernel change.
- **[`250`](250_payoff-2-the-trained-behavior-delta-rlvr-admit.md)** — *in progress*:
  pipeline + $0 proxy done, real Vertex tuning **running** (see the
  `project-dos-rlvr-payoff2-vertex-run` memory — resume via `rlvr_run --await-jobs
  --eval`). The active experiment; its "remaining" is a job completion, not a build.
- **[`245`](245_proving-the-referee-at-fleet-scale-the-plan.md)** — plan, mostly
  executed. F1/F1-super-linear/F2/F4 all ran/built; **only F3 remains** (the
  second-witness Agent-Diff port — does the headline figure reproduce under an
  independent witness?). Agent-Diff is standing locally (see
  `project-dos-agent-diff-standup`).
- **[`66`](66_dispatch-os-issue-solve-plan.md)** — ACTIVE · 0% · research. The
  foreign-repo "solve" path (the WRITE sequel to the read-only research); first real
  consumer of the worktree-isolation series. Long-horizon, not queued.

---

## 4. Housekeeping deltas this survey surfaced

Small, concrete, found while compiling — worth doing regardless of the big plans:

1. **README plan-index status drift.** `docs/README.md`'s "Plan records" table tags
   [`207`](207_dispatch-workflow-extraction-and-the-pickable-substrate-completion.md)
   and a few siblings `📋 planned` when their own `> **Status:**` line says SHIPPED.
   Reconcile the table against the docs (or generate it from them).
2. **The 119 no-code operator-guidance win** (a `dos doctor`/lint over-broad-claim
   warning) needs no mechanism change and would unblock the biggest apply-side
   concurrency gain — cheap and orthogonal to the rest of 119.

---

## 5. The shortlist (if you want one next thing)

- **Cheapest high-leverage:** [`125`](125_the-trifecta-color-and-the-capability-conjunction.md)
  (trifecta predicate) — days, on shipped machinery, the most-cited security defense.
- **Banks already-built kernel work:** [`110`](110_the-concurrency-class-operator-surface.md)
  (class-budget CLI/config surface) — the arbiter half is done and pinned.
- **Closes the most expensive failure class:** [`82`](82_liveness-oracle-plan.md)
  Phase 3a + [`99`](99_runtime-validation-and-the-actuation-boundary.md) self-stop —
  the spinning-loop sensor finally wired to an actuator.
- **Makes the flagship audit real:** [`118`](118_the-fleet-postmortem-and-the-attribution-join.md)
  — one producer change (`run_id` on the acquire lease) lights up the whole
  trajectory-audit join.
