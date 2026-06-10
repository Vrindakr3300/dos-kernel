# 207 — the seam ledger (Phase 0 deliverable)

> **Status:** committed Phase-0 artifact for
> [docs/207](207_dispatch-workflow-extraction-and-the-pickable-substrate-completion.md).
> Built from a 2026-06-07 ground-truth sweep of (a) the `job` consumer repo's
> dispatch family (`scripts/{plan_phases,plan_pickability,audit_plan_pickability,
> class_cycle,unstick_audit}.py`) and (b) the live DOS kernel substrate the new
> modules build on. This is the "dissection map" SKP Phase 0 produced for the
> first five skills — every POLICY line of the three operator skills with its
> data/hook destination, plus the verified substrate state, plus the
> false-premise corrections the sweep surfaced.

The plan's Design Law 0 ("probe target + verify reuse before building"): the
repo's own memory warns that plans here *rest on false premises and unbuildable
reuse*. This ledger is the probe. Six load-bearing premises were checked against
the actual code; **two were wrong and the plan adapts** (recorded in §4 below).

---

## 1. Verified substrate state (what this plan builds ON)

| Concept | Module / surface | State | What Phase N must still build |
|---|---|---|---|
| `pickable` gate | `dos.pickable` (`8357ac0`) — `classify(unit_state, *, now_ms, policy)` → `Pickability`; `HoldReason` (10 members); `is_redispatch_invariant` (4 members) | **shipped + tested** (`test_pickable.py`) | **no `dos pickable` CLI verb** → Phase 1 |
| honest-STOP rung | `loop_decide.PICK_HELD_INVARIANT` (rung 4b, `loop_decide.py:776`) | **shipped + tested** | a sibling `PICK_COOLDOWN` rung → Phase 3 |
| `completion` | `dos.completion.classify(state, ancestry, …)` → `CompletionVerdict`; `declared = state.declared_steps` (intent ledger), `verified = resume.resume_plan(...).verified` | **shipped** (`dos complete`) | `enumerate` as an *alternative* `declared` producer (NOT callback-removal — see §4.5) → Phase 2c |
| `recurring_wedge` | `dos.recurring_wedge.classify_recurring_wedge(*, this_run_id, this_run_cause_keys, prior_hits, min_recurrence)` → `RecurringWedgeVerdict`; `cause_key` is an **opaque** string | **shipped + tested** | **no `dos wedge-sweep`/`dos unstick` verb** → Phase 5a decides verb-vs-compose |
| lane-journal WAL | `dos.lane_journal` — `append`/`replay`/`read_all`; entry builders; `OP_*` vocabulary (no `OP_ATTEMPT`) | **shipped** | an `OP_ATTEMPT` forensic event + `attempt_entry` builder → Phase 3a |
| `durable_schema` | `dos.durable_schema.tag(family, version)` / `classify(record, family=, understands=)` | **shipped** | the ATTEMPT event rides `tag("lane-journal", …)` → Phase 3a |
| `dos.judges` seam | `Judge` protocol, `AbstainJudge`, `run_judge` (fail-to-abstain), `resolve_judge`, `dos judge`/`judge-eval` verbs; drivers `llm_judge`/`operator_judge`/`similarity_judge` | **shipped + tested** | the JUDGE *content* for class-cycle is a host driver; the *cycle mechanism* + `[lifecycle]` table → Phase 5c |
| `[stamp]` config seam | `dos.stamp.StampConvention` + `convention_from_table` + `SubstrateConfig.stamp`; loaded from `dos.toml [stamp]` | **shipped** (the data-attachment template) | three new tables `[enumerate]`/`[cooldown]`/`[lifecycle]` modelled on it → Phases 2b/3b/5c |
| `dos init` | `cli.cmd_init` — scaffolds `dos.toml` only (lanes auto-derived from top-level dirs) | **shipped** | `--skills` to copy SKILL.md package-data → Phase 7 |
| skill pack | 7 generic skills under `src/dos/skills/`; `test_skill_pack_*` litmus | **shipped** (`docs/74`) | three operator skills → Phase 5; the count assert moves 7→8 (see note) |
| `enumerate` / `reconcile` | — | **NOT built** | Phases 2 / 4 |
| cooldown ledger | — | **NOT built, no kernel home** | Phase 3 |

> **Skill-count note.** The litmus `test_skill_pack_litmus.py::test_pack_ships_the_generic_skills`
> asserts **exactly 7** skills and names them. The plan's headline ("eight skills")
> counts the three operator skills as +3 = 10, not 8 — the plan's §8a "eight" is a
> stale figure from before two loops (`supervise-loop`, `witness-claim`) were added.
> Phase 5/8 update the assert to the real post-Phase-5 count (**10**) and the named
> set. Recorded so the prose says the true number.

---

## 2. The dissection — MECHANISM vs POLICY, per skill

### 2a. `unstick` (job `scripts/unstick_audit.py`, ~52 KB) — read-only, lightest slice

| Line in the host script | Kind | Destination |
|---|---|---|
| Cluster recurring blockers by `cause_key`; rank by recurrence × stall-cost | **MECHANISM** | `dos.recurring_wedge` (shipped) |
| The cause TAXONOMY (`_HALT_CUES`, the `Cause` cue table, the canonical cause keys, the proposed structural fix per cause) | **POLICY** | `dos.toml [reasons]` (Axis 1 `ReasonRegistry`) — a host adds a cause by declaring a reason, NOT editing the skill. The job script already unifies its key set with `dispatch_tokens.BlockedReason` — the same kernel-catalog↔host-cue split |
| `DISPATCH_LOOPS_DIR` / `FANOUT_RUNS_DIR` (host run-archive paths) | **POLICY** | `dos doctor --json` `paths.runs` (WCR) |
| The dispatch-loop README iter-row regex (`_ITER_ROW`), the Outcome-cell mining | **POLICY** (a host evidence reader) | a `dos.evidence_sources` driver hook (optional); the skill `log`s when no host evidence reader is wired — no silent gap |
| `--with-trajectories` session `.jsonl` HALT mining | **POLICY** (host telemetry) | a driver hook; out of the generic floor |

→ `dos-unstick` is the lightest skill: it shells a cause-clustering verb over `recurring_wedge`, reads `[reasons]` for the taxonomy, surfaces via `dos decisions`. Phase 5a decides: add a thin `dos wedge-sweep` verb, or compose existing verbs in the screenplay.

### 2b. `promote` (job `scripts/audit_plan_pickability.py` + `plan_pickability.py`) — visibility-inverse of demote

| Host behavior | Kind | Destination |
|---|---|---|
| For each unit, decide offerable / why-not | **MECHANISM** | `dos.pickable.classify` (shipped) — surfaced by Phase 1 `dos pickable` |
| `HoldReason → unblock action` routing (`DRAFT_CLASS`→promote, `UNPARSEABLE`→inspect-deriver, `OPERATOR_GATED`→raise-decision, `SOAK_OPEN`→wait) | **POLICY (data)** | a `dos.toml`-declarable reason→action map; default routing is derivable from `HoldReason` (the enum already documents it) |
| `HIGH_PRIORITY_BAND = 8` (which priorities must be visible) | **POLICY** | host knob; the generic skill ranks by `enumerate` order, not a band |
| The list↔table drift detector (`--drift`, the "table is authority / cached list is cache" rule) | **MECHANISM** | Phase 2c typed `DriftNote` from `enumerate` |
| The auto-applied mechanical reclassify (DRAFT→ACTIVE, one commit) | **POLICY** (the one gated mutation) | the skill applies it gated; everything else surfaces for a human |

### 2c. `class-cycle` (job `scripts/class_cycle.py`, ~78 KB) — heaviest, judge-gated

| Host behavior | Kind | Destination |
|---|---|---|
| The cycle: evaluate triggers → build candidates (deterministic order) → judge → apply gated transitions → log | **MECHANISM** | the domain-free cycle Phase 5c ships |
| The class taxonomy (`ACTIVE/MAINTENANCE/PARK/TOMB/DRAFT`) + the 9 named triggers (`T1..T9`) | **POLICY (data)** | `dos.toml [lifecycle]` — a repo declares its own class set + trigger list; a 2-class repo declares `active`/`done` |
| Trigger thresholds (`_T5_STUCK_DAYS=14`, `_T7_IDLE_DAYS=180`, `_T9_AUTOPICK_MIN=2` …) | **POLICY (data)** | `[lifecycle]` knobs |
| Failsafes (`_DAILY_TRANSITION_CAP=5`, `_COOLDOWN_HOURS=72`, P0-veto) | **POLICY (data)** | `[lifecycle]` knobs |
| `_JUDGE_PROMPT_TEMPLATE` (the LLM-judge prompt) | **POLICY (host content)** | a host `dos.judges` driver — the *content* stays host-side by design (forcing it generic re-couples the kernel); the skill spawns the judge via the seam, fail-to-abstain |
| `agents.plan_meta` parse + `plans.yaml` re-render | **POLICY** (host plan store) | the skill edits plan-meta + commits; the store shape is host config (WCR `paths`) |

> The job script confirms the judge is **spawned by the skill, not the script** —
> "the LLM judge is **not** called from this script — the `/class-cycle` skill
> spawns it via the Agent tool with the prompt this script emits." This matches the
> plan: the cycle mechanism is kernel/skill; the judge content is a driver.

---

## 3. The reference deriver to relocate (Phase 2 `enumerate`)

The job `scripts/plan_phases.py::derive_phase_universe` is the gold-standard
battle-scarred deriver. **Design Law 6 (relocate, don't relax)** — the following
correctness, hard-won against a 38-invisible-plan corpus, moves into the generic
`enumerate` byte-for-byte, with the *grammar* lifted to `[enumerate]` data:

- **Series-anchored phase-id token regex** (`_phase_token_re`) — the anti-brittleness core that rejects every data-table trap (`| Class | Count |`, sibling-plan rows). The series prefix is the ONE rule. → grammar: `series` from plan-meta `id` / `phase_prefix`.
- **Three id shapes**: numeric/sub-phase (`TF0`, `MAS2.5`, `SVP-2`), word-suffix satellites (`AFR-FQ282`, `WD-CREATE-ACCT`), with range guards (`IFR4-IFR5` is not one phase).
- **Code-fence stripping** (`_strip_code_fences`) — a phase id inside a ``` sample must not enumerate.
- **Heading + table + generic-`Phase N` families**, UNION'd (the TF/AR hybrid).
- **Sibling-clause masking** (`_mask_sibling_clauses`) — the CD9 `(CD8 shipped this slot)` trap.
- **Structural-stamp gate** (`_STRUCTURAL_STAMP_RE`) — a prose "all-SHIPPED" must not read as a ship.
- **Parent/child rollup** to a fixpoint, with the MC2/MC2.1 not-done guard.
- **Degrade-never-crash**: a malformed body → empty derivation + a typed `DriftNote`, never a raise (the picker-invisibility cure: a typed refusal, never a silent empty universe).

The generic grammar default (a repo that declares nothing): markdown `### N. NAME`
headings + `| Phase |` table first-cells + bare `Phase N`. The reference grammar
(series-anchored) is opt-in via `[enumerate]`.

> **Note** — the job deriver READ-ONLY-reuses `dos.phase_shipped`'s
> `_section_says_shipped` + `_phase_variants`. The generic `enumerate` reuses the
> same kernel internals (they live HERE), so the shipped-state decision stays one
> implementation, not a second heuristic.

---

## 4. False-premise corrections (the probe's findings)

The sweep verified the plan's six load-bearing premises. **Two were wrong;** the
plan adapts here rather than coding against a false assumption.

1. **`enumerate.py` naming is a HAZARD (plan silent on it).** The builtin
   `enumerate()` is used at 20+ kernel call sites. A module `dos/enumerate.py` is
   importable safely (the builtin resolves via the builtins namespace, not the
   import system), BUT `from dos import enumerate` inside any module would shadow
   the builtin locally. **Resolution:** name the module `enumerate.py` (so the CLI
   verb `dos enumerate` reads naturally), but (a) the public function is
   `enumerate_units(...)`, NOT `enumerate(...)`; (b) every consumer imports it as
   `from dos import enumerate as _enumerate` or `import dos.enumerate` — **never**
   the bare `from dos import enumerate`. Verified 2026-06-07: no existing module
   does the bare form, so the convention starts clean. Pinned by a litmus test.

2. **Cooldown — PARTIAL (consumer done, producer unbuilt).** `pickable.COOLDOWN`
   + the `cooldown_until_ms` READ are shipped and tested; **nothing WRITES**
   `cooldown_until_ms`, there is no `OP_ATTEMPT`, no `cooldown.py`. Phase 3 builds
   the entire producer chain (ATTEMPT event → fold → `cooldown_until_ms` → the
   `PICK_COOLDOWN` rung). The consumer's existence is a HELP, not a conflict: the
   cooldown verdict feeds the same `cooldown_until_ms` key `pickable` already reads.

3. **Job byte-parity corpus — BUILDABLE.** `job/docs/_plans/plans.yaml`
   has exactly **63 `classification: ACTIVE`** entries and 36 `.md` plan files. The
   Phase 2 `test_enumerate_byte_parity_job` gate is buildable here, offline, $0.

4. **Toolathlon corpus — size CORRECTION.** The corpus exists at
   `benchmark/toolathlon/_data/` but holds **~7,116 trajectories across 66 JSONL
   files**, NOT the "751" the plan cites (a stale figure). **Resolution:** Phase 4
   scores over the available corpus and cites the *real* count; the "phase0" label
   is a design path, not a directory — the test reads `_data/*.jsonl` with the
   ground-truth `eval` field, no held-out 751 subset required.

5. **Phase 2c "remove a host callback" — FALSE; it is a non-task as stated.**
   `completion.classify` reads `declared = tuple(state.declared_steps)` directly
   from the intent-ledger `LedgerState` — there is NO host callback to remove (the
   signature has none; commit `a5c1939` was the same). **Resolution:** Phase 2c is
   re-scoped to its honest form: `enumerate` is an *alternative producer* of the
   `declared` extent for a workspace that declares phases in **plan docs** rather
   than minting **intent-ledger** steps. The two are different sources of
   "declared" (doc-enumeration vs ledger-fossils); Phase 2c wires `enumerate` as
   the doc-side producer and emits the list↔table `DriftNote`, it does not delete a
   callback. The test `test_completion_uses_enumerate_no_callback` is renamed to
   `test_enumerate_feeds_declared_extent` to match the real task.

6. **Phase 5c judges seam — READY; `[lifecycle]` + skill unbuilt (as planned).**
   `dos.judges` (`AbstainJudge`, `run_judge` fail-to-abstain, `resolve_judge`, the
   `dos judge`/`judge-eval` verbs) is production-ready. The `[lifecycle]` table and
   `dos-class-cycle` skill are correctly NOT built — Phase 5c ships them.

---

## 5. Layer-contract homes (Phase 0c confirmation)

Every new piece slots into an existing layer — **no new layer, no new top-level
package** (the plan's modularity claim, verified against `CLAUDE.md`'s table):

- `src/dos/enumerate.py`, `src/dos/reconcile.py`, `src/dos/cooldown.py` → **Layer 1** (kernel), pure verdicts, no host, no I/O. Sibling imports allowed (the litmus is "no host, no I/O policy", not "no sibling import").
- `OP_ATTEMPT` + `attempt_entry` → the **WAL tier** in `lane_journal` (a forensic op, NOT in `_STATE_MUTATING_OPS` — an attempt grants/removes no lease; the cooldown fold reads it via `read_all`, never `replay`).
- `dos pickable`/`dos enumerate`/`dos reconcile`/`dos cooldown` verbs → **Layer 3** (`cli.py`), exit-code-is-verdict, modelled on `dos gate`.
- `[enumerate]`/`[cooldown]`/`[lifecycle]` → **Seam-data (2a/2b)**, `SubstrateConfig` fields modelled on `[stamp]`.
- `dos-unstick`/`dos-promote`/`dos-class-cycle` → **Axis-5 package-data** under `src/dos/skills/`, grep-clean, no `__init__.py`, pinned by `test_skill_pack_*`.

**No `src/dos/` module imports a host** (`job`/`apply`/`tailor`/`discovery`), the
release scripts, the MCP server, or a judge implementation — the new modules
inherit those litmuses by construction (they import only stdlib + sibling kernel +
`dos.config`).

---

## 6. The build order (dependency-sorted)

The plan numbers phases 1→8 but the true dependency order front-loads Phase 2
(`enumerate` is a dependency of Phase 1's `dos enumerate` verb and Phase 2c):

1. **Phase 2** — `enumerate.py` + `[enumerate]` + the byte-parity gate (the foundation).
2. **Phase 1** — `dos pickable` + `dos enumerate` verbs (now `enumerate` exists).
3. **Phase 3** — `OP_ATTEMPT` + `cooldown.py` + `[cooldown]` + `PICK_COOLDOWN` rung + `dos cooldown`.
4. **Phase 4** — `reconcile.py` + the toolathlon scoring gate.
5. **Phase 5** — the three operator skills (need Phases 1/2/5c-table).
6. **Phase 6** — wire the generic dispatch-loop to the new substrate.
7. **Phase 7** — `dos init --skills`.
8. **Phase 8** — HACKING.md / CLAUDE.md / README / friction log.

Each phase: minimal diff, prove against the corpus + the foreign-repo rig, keep
the existing 2615-test suite green, commit the lane.
