# 207 — Dispatch-workflow extraction: completing the pickable substrate + the operator-facing skill tier

> **Status:** SHIPPED (2026-06-07). Phases 0–8 landed: the seam ledger
> ([207-seam-ledger.md](207-seam-ledger.md)); `enumerate`/`reconcile`/`cooldown`/
> `lifecycle` kernel modules + the `[enumerate]`/`[cooldown]`/`[lifecycle]` config
> tables; the `dos pickable`/`enumerate`/`cooldown`/`reconcile` verbs; the
> `OP_ATTEMPT` WAL event + the `PICK_COOLDOWN` `loop_decide` rung; the three
> operator skills (`dos-unstick`/`dos-promote`/`dos-class-cycle`); the loop wiring;
> `dos init --skills`; and the friction log ([207-friction-log.md](207-friction-log.md)).
> Three offline-replay gates PASSED: `enumerate` byte-parity over the `job` repo
> (17/17 doc-resolvable plans, universe + partition), the `cooldown` re-pick-storm
> backtest, and `reconcile` on the toolathlon corpus (precision 1.0, full recall).
> Two plan premises were CORRECTED at build time (see the seam ledger §4): Phase 2c's
> "remove a host callback" was a non-task (`completion` reads the intent ledger, not
> a callback), and the toolathlon corpus is ~7,116 trajectories, not the cited 751.
> Eighth in the genericization series, and
> the second to address *workflow* after [SKP](74_skill-pack-plan.md)
> (SCV→WCR→RND→ADM→SKP→DOS-HOME→[overlap](113_the-overlap-policy-seam-and-eval-per-axis.md)→**this**).
> Closes the three [docs/168](168_picker-substrate-and-quiet-completion-the-missing-syscalls.md)
> concepts (`enumerate`/`pickable`/`reconcile`) — of which `pickable` already shipped
> (`8357ac0`) — and ships the operator-facing skill tier (`dos-class-cycle`,
> `dos-promote`, `dos-unstick`) the reference userland app proved out as
> `class-cycle` / `promote` / `unstick`. Derived from a 2026-06-07 ground-truth
> sweep of the `job` consumer repo's dispatch family + the SKP friction log's
> still-open seams (F1/F2/F6).

## The one-paragraph thesis

DOS extracted the **mechanism** (`verify`/`arbitrate`/`liveness`/`refuse`) and a
**baseline workflow** (SKP's five generic skills). But the `job` repo's dispatch
family kept *evolving* after SKP froze — it grew a whole **second tier** of
operator-facing workflow (lifecycle gardening, picker-unblock, recurring-wedge
sweep) and a **third missing-syscall set** (`enumerate` the phase-list producer,
`reconcile` the quiet-completion gate) that SKP did not cover because they did not
exist yet. Every one of those is the same shape SKP already validated: *the
producer/gate the host re-implements, the recurring human override that wants to
become a typed rule, mechanism-not-policy with the grammar in `dos.toml`.* This
plan pulls that tier in — **two kernel modules, one anti-churn primitive, four thin
CLI verbs, three generic skills, and a `dos init --skills` scaffold** — so a
stranger who `dos init`s a repo gets not just honest syscalls and a plan-and-ship
loop, but the **full unattended portfolio loop** that keeps a fleet moving without
a human re-triggering it: it can see what's pickable and *why-not*, garden its own
plan lifecycle, and break out of the re-pick churn that is the single most
expensive recurring failure.

## Why now — the evidence the gap is real

The `job` repo hit these as **fleet-wide wedges**, each patched host-side with zero
new kernel invariants (the docs/168 §"The pattern" table, extended with the
2026-06-06→07 incidents this sweep added):

| Wedge (job-side) | Root | What it cost | The missing kernel concept |
|---|---|---|---|
| FQ-420 (`3b0d08ae`) | picker serialized a gate-set as a `set` → JSON `TypeError` → body-empty-but-LIVE packet | ~36h fleet deadlock | `pickable` typed gate (un-typed bookkeeping) — **shipped** |
| Drain-trap ×3 (ASI #475 / FMP #493 / RTN) | pick-oracle counted DEFERRED/DRAFT/operator-gated phases as pickable → loop re-DRAINed every iter | 3 lanes × many iters × ~$3/iter | `pickable` `HoldReason` + `loop_decide` honest-STOP — **shipped** |
| Picker-invisibility (`72ee55e6`, PPG) | ~38/63 ACTIVE plans had no machine-readable phase list → silently dropped, no refusal reason | whole lanes never reached the picker | `enumerate` (phase-list producer) — **NOT built** |
| `ladder read slot not priority` (`reference_ladder_read_slot_not_priority_fix`) | the auto-pick ladder read an obsolete field with a prose-digit regex → ranked a done plan TOP | every bare loop auto-picked the wrong lane | `enumerate` + `pickable` (the ladder is host re-impl) — **partial** |
| FQ-336 quiet-DRAIN storm (`a2427731`) | a *touch* of a plan doc counted as a ship → false "all shipped" | `child_skipped_replan` ×8 re-confirms | `reconcile` (quiet-incomplete keep) — **NOT built** |
| Per-pick re-pick churn | a bare loop re-picked the same drained item every iter once the 90-min claim TTL lapsed | measured 1/21 runs shipping (~5%) | a **cooldown / anti-churn** primitive — **NOT built, no kernel home** |

The throughline: **the kernel owns "did it ship / can this lane run / is it
alive," but not "is there anything pickable, why-not, and have I tried this
already."** docs/168 named the producers; this plan builds the two unbuilt ones,
generalizes the anti-churn ledger the `job` repo learned the hard way, and ships
the operator skills that turn the typed verdicts into a workflow a stranger can run.

## How well recent fixes are actually reaching DOS (the back-flow audit)

This plan is the *forward* extraction; this section is the *measurement* that
justifies it — **are the dispatch fixes the `job` repo ships continuously landing
in the kernel, or stranding host-side?** The honest answer from a 2026-06-07 git
sweep of both repos: **the mechanism-shaped fixes flow, with a bounded lag of
roughly weeks; the newest cohort is still stranded; and there is no live ledger
tracking which is which.** That last gap is what lets a fix sit host-only
indefinitely — and is the thing this plan must not reproduce.

### What the flow looks like (it IS happening, selectively)

DOS records the back-flow *in the kernel's own provenance* — the code cites the
`job` finding it descends from, the strongest possible evidence a lift actually
landed (not just a doc claiming intent). A `grep` of `src/dos/*.py` for fix-ids
returns **explicit lift markers**: `FQ-420` (×16), `FQ-390` (×10), `FQ-240` (×10),
`FQ-452` (×6), `FQ-449` (×4), `FQ-326` (×2), `FQ-419` (×2), `MQ3X` (×4),
`job finding #476` (×2), and more. The matching landings, by commit:

| `job` fix | Reached DOS as | Lag |
|---|---|---|
| `fanout_state.py` pure kernels (MQ3X) | `gh4_coverage` + `claim_ttl` — "pure kernels lifted from job fanout_state.py" (`054bc33`) | ~weeks |
| FQ-326 soak false-positive / FQ-452 stale-stamp spin | `phase_shipped` + `loop_decide` guard (`fc2fe9e`) | ~weeks |
| FQ-419 / FQ-420 sidecar serialization | `packet_sidecar` owns the write + producer-side verify (`87af613`) | ~weeks |
| FQ-449 single-pick-ceiling | `arbiter` prefers a sibling-disjoint lane on bare auto-pick (`959528c`) | ~weeks |
| FQ-390 plan-id-collision | `oracle` gate ON by default (`bff0d25`) | ~weeks |
| #399 grep_touched_files / footprint demotion | `oracle` + `phase_shipped` shared predicate (`7d87552`) | ~weeks |
| job lane taxonomy | relocated to `dos._job_policy` + `job_config` reads `dos.toml [lanes]` (`daf369d` / `d46b075`) | ~weeks |
| `dos top` fleet TUI | "ported from job — works in a random new repo" (`618da00`) | ~weeks |
| job finding #476 (decision recency) | `decisions` recency-filter (`c8b8b2e`) | days |

And the flow is *audited*, not ad-hoc: **docs/127 is a standing "DOS ↔ Bench/Job
integration audit"** (`127_dos-bench-job-integration-audit-2026-06-03.md`) that
catches live seam regressions. So the pipeline exists and works — the kernel is
not drifting away from the consumer; recent integrity/velocity fixes (FQ-326/449/
390/419/452) demonstrably crossed.

### Where it lags (the stranded cohort — measured, not asserted)

The **most recent** high-value `job` dispatch fixes have **no kernel home yet** — a
`grep` of `src/dos/` for each returns `module: none`:

| `job` fix (commit) | Date | Kernel home today | This plan's disposition |
|---|---|---|---|
| child2 `/fanout` launched DETACHED so it survives parent `-p` exit (`4c7672cb`) | 2026-06-07 | **none** | fanout-lifecycle — **scope-out** (heavy tier, SKP F3); named in Phase 8 friction log |
| FQ-367 release orphaned soft-claims from dead `/fanout` children (`d2b8a897`) | 2026-06-07 | **none** | same heavy-tier family — **scope-out**, friction-logged |
| FQ-491/493 pickability gap: `phase_prefix` deriver + stale-% classifier (`72082eca`) | 2026-06-07 | **none** | **THIS PLAN** — `enumerate` (Phase 2) is exactly this producer |
| FQ-494 deterministic cooldown reset in `replan_autoclose` (`4eea0690`) | 2026-06-06 | `scout` (adjacent only) | **THIS PLAN** — the cooldown primitive (Phase 3) gives it a kernel home |
| FQ-498 lease scavenged mid-iteration (TTL vs wall-time) (`47a6e11a`) | 2026-06-07 | `dispatch_top` (adjacent only) | lease-lifecycle tuning — **scope-out** (host lease core, SKP F3) |

So the lag is **real and bounded**: a fix lands in `job`, runs as host policy for
days-to-weeks, and *then* — if it is mechanism-shaped — gets lifted. The danger is
not that lifts fail; it is that **nothing decides per-fix whether a lift is owed**,
so a mechanism-shaped fix (FQ-491/493's deriver, FQ-494's cooldown) can sit
host-only past the point where a *second* consumer would have benefited. docs/168
stated this exactly for an earlier cohort — *"four wedges, four job-side patches,
**zero new kernel invariants** … the kernel caught none."* The same sentence is
true today of the 2026-06-06/07 cohort; this plan is the response (it lifts the two
mechanism-shaped ones and explicitly scopes-out the three heavy-tier ones, so each
has a *decided* disposition rather than a silent one).

### The fix: a live back-flow ledger, not a one-time table (BUILT)

The table above is a snapshot; the structural cure is to **keep it live**, so the
lag is visible instead of discovered. **This is now built, not just planned:**
[`207-backflow-ledger.md`](207-backflow-ledger.md) is the standing ledger,
`scripts/backflow_ledger.py` regenerates it (`--check` exits non-zero on any OWED
row, for the docs/127 audit cadence), and `tests/test_backflow_ledger.py` (11
tests, green) pins it. The detector caught 8 unmatchable commits on first run, all
since reconciled (OWED: none today). The two in-idiom moves it rests on:

1. **Provenance stays in the code (already the norm — make it a rule).** Every lift
   cites its `job` fix-id in the module docstring/comment, exactly as `claim_ttl` /
   `arbiter` / `oracle` already do. A `grep src/dos -e 'FQ-[0-9]'` is then the
   back-flow manifest — no separate registry to drift. The litmus: a kernel module
   that lifts a `job` behavior **without** citing its origin fails review.
2. **A `job`-side dispositions column the audit reads.** The `job` repo already
   tags dispatch fixes with FQ-ids and routes them through findings; docs/127's
   audit gains a **per-fix disposition** (lifted `<sha>` / scope-out `<reason>` /
   owed) so "is this fix's lift owed?" is a column, not a per-incident rediscovery.
   This is the same evidence-over-narrative move the kernel makes everywhere: the
   *answer* (did it land?) is a grep over committed provenance, never a claim.

The bar this section sets for the plan: when Phase 2–3 land `enumerate` + the
cooldown primitive, the **stranded cohort above must shrink by exactly those rows**,
and the new modules must cite `FQ-491`/`FQ-493`/`FQ-494` in their provenance — so
this very table, re-grepped, shows the lift. That is the plan's own
measure-then-change discipline applied to itself.

## Design laws (inherited from SKP + the layer contract — non-negotiable)

These are the litmus every phase below is checked against. They are SKP's laws,
re-stated because this plan is bound by the same contract:

1. **A generic skill names no host path, lane, or commit convention.** Every
   literal comes from `dos doctor --json` / `dos.toml`. A `grep` of a shipped skill
   for `docs/_plans`, `apply`/`tailor`/`discovery`, `docs/dispatch:`, or a `job`
   plan-class name returns nothing. Pinned per-skill (`test_skill_pack_*`).
2. **The skill shells `dos`, never a host's fat scripts.** Where `class_cycle.py`
   (78 KB) or `unstick_audit.py` (52 KB) runs in `job`, the generic skill runs a
   `dos` subcommand over the *pure* kernel module. The screenplay carries no Python.
3. **Mechanism is the kernel; policy is data; the grammar is `dos.toml`.** The new
   modules (`enumerate`, `reconcile`) are pure classifiers over bytes the host
   gathers; the *grammar* (which heading shape declares a unit, which class is
   "DRAFT") is declared, never hardcoded. Same split as every existing syscall.
4. **Kernel imports no host; a verdict does no I/O.** `enumerate(source_bytes,…)`
   and `reconcile(unit, claim, oracle_verdict)` are pure — the file read, the soak
   index, the live-claims read all happen at the CLI/adapter boundary (the
   `git_delta`→`liveness.classify` rule). Pinned by the no-host import litmus.
5. **A typed verdict replaces a per-incident human override — it does not act.**
   `pickable`'s `HoldReason`, `reconcile`'s `QUIET_INCOMPLETE`, the cooldown's
   `RECENTLY_ATTEMPTED` all *report and route*; the kernel stays a PDP, never a PEP.
   The honest-STOP becomes a `loop_decide` rung (already shipped for `pickable`),
   not a human judgment re-made every run.
6. **Battle-scarred correctness is relocated, not relaxed.** The `job` fixes
   (substantive-footprint demotion, the table-is-authority/list-is-cache rule, the
   DRAFT-gate skip) move into the kernel/config; each phase proves byte-parity
   against the `job` behavior (offline replay) **before** its prose is touched.
7. **Minimal diff, prove-then-move, record friction.** One seam per step, validate
   against a foreign repo + the `job` replay corpus, and write any genericization
   insight that has no home yet into the friction log (Phase 8) rather than coding
   ahead of proof.

## How this stays MODULAR relative to the rest of DOS (the user's explicit ask)

The plan is shaped so each piece slots into an **existing** DOS seam rather than
inventing a parallel structure — this is what keeps it from becoming "another tier
bolted on the side":

- **`enumerate` is the missing third of an existing closed concept.** The kernel
  already owns `oracle` (did *this id* ship?) and `completion` (`residual =
  declared − verified`). `enumerate` is the **producer** of the `declared` set —
  it composes *into* `completion`, it does not stand beside it. After this,
  `completion` computes the residual end-to-end with no host callback. (docs/168 §1.)
- **`pickable` (shipped) is the pre-flight twin of the post-flight `picker_oracle`.**
  They share the `HoldReason` vocabulary: `pickable` *decides what to offer*,
  `picker_oracle` *audits whether the gate was right*. One enum, two consumers —
  the exact `gate_classify` → `dispatch-loop` shape that already worked. This plan
  only adds the **CLI surface** (`dos pickable`) and the **skill** that reads it; the
  module is done.
- **`reconcile` is the picker-boundary closure of the quiet-failure line
  (docs/149–164).** Those docs DETECT quiet failure *in a trajectory*; `reconcile`
  is what KEEPS a quietly-incomplete unit in the residual *across runs*. It is a
  **join over two verdicts the kernel already produces** (`oracle` + `enumerate`),
  not a new sensor. It reuses the intent-ledger rule (docs/107: `STEP_CLAIMED` stays,
  `STEP_VERIFIED` is removed) generalized to the picker.
- **The cooldown primitive is the anti-churn sibling of `liveness`/`loop_decide`,
  not a new subsystem.** `liveness` asks "is this run *moving*?"; the cooldown
  ledger asks "have I *already tried* this unit and it didn't move?" — the
  cross-run memory `loop_decide` needs to stop re-picking a drained item. It rides
  the **lane-journal WAL** that already exists (an `ATTEMPT` event beside the
  `HEARTBEAT`/lease events), so it is one fold over a durable surface DOS already
  writes — not a new state file genre. It composes with `loop_decide.decide` as a
  new rung (`PICK_COOLDOWN`), the same way `PICK_HELD_INVARIANT` did.
- **The three new skills are Axis-5 occupants, full stop.** They are `SKILL.md`
  package-data under `src/dos/skills/`, driven by `dos.toml` + `dos` verbs, held to
  the same grep-clean litmus and `test_skill_pack_*` pins as the existing five.
  They do not get a new directory, a new loader, or a new contract — they *are* the
  workflow axis, extended.
- **The grammar each new module reads is a `dos.toml` table, mirroring `[stamp]`.**
  `[enumerate]` (heading/table/bare-`Phase N` grammar as data) generalizes
  `[stamp].phase_labels`; the `HoldReason→action` routing and the
  `reconcile`-keep policy are `dos.toml` data. **The kernel carries the parser, the
  gate, and the join; the consuming repo declares the policy.** Same attachment
  model as Axis 1 (reasons) and the WCR `[lanes]`/`[paths]` readback.

The net effect: a reader of `CLAUDE.md`'s layer table sees **no new layer** — two
kernel modules join the layer-1 syscall set, one primitive joins the WAL tier,
four verbs join the layer-3 CLI helper, three skills join the Axis-5 pack. Nothing
crosses a layer line that the existing seven plans did not already cross.

## How this becomes LESS house-style (the user's second explicit ask)

The `job` versions encode three kinds of house specificity that the extraction
**strips into config or drops**:

1. **Named lane trees → derived/declared lanes.** `job`'s skills name `apply` /
   `tailor` / `discovery` and a curated `docs/_plans/` tree. The generic skills
   read `lanes`/`paths` from `dos doctor --json` (WCR), so the *same screenplay*
   runs on a repo whose lanes are `api`/`worker`/`web`. (Already true for the SKP
   five; the new three inherit it.)
2. **Plan-class taxonomy → declared classes.** `job`'s `class-cycle` hardcodes
   ACTIVE/MAINTENANCE/PARK/TOMB/DRAFT and 8 named triggers (PCL). The generic
   `dos-class-cycle` reads a **`[lifecycle]` class set + trigger list as data** —
   a repo that only wants ACTIVE/DONE declares two classes; a repo with a richer
   taxonomy declares more. The *mechanism* (evaluate triggers → judge-as-operator
   → apply gated transitions → log) is domain-free; the *taxonomy* is policy.
3. **Curated evidence streams → a driver hook (or dropped).** `job`'s `replan` /
   `unstick` read a hand-ranked next-hits file, a postmortem stream, an INDEX of
   past runs (SKP friction F2). The generic skills rank by the **domain-free
   signal** (`enumerate` order + `verify` status + the cooldown ledger) and surface
   via `dos decisions`; the curated streams become an optional `dos.evidence_sources`
   driver hook the host wires, never a literal. The skill `log`s when it is not
   consulting host evidence — no silent gap.

What deliberately does **not** get genericized (and why that is correct): the
*content* of a host's judge prompt (a `dos.judges` driver), the *exact* commit
subject template (`[stamp]` data), and the heavy `fanout_state.py` soft-claim core
(SKP F3, parked by the layer contract). Those are policy by nature; forcing them
generic would re-couple the kernel. The friction log (Phase 8) records each.

---

## Phase 0 — the gap audit + the seam ledger extension (no code)

The dissection map, as SKP Phase 0 did for the first five skills. Pin which lines
of `class-cycle` / `promote` / `unstick` are mechanism vs policy, and which
docs/168 concepts each leans on.

- **0a.** For `unstick` (the lightest, the first slice — it is read-only and needs
  no new kernel module, only `recurring_wedge` which exists): table every shelled
  command, every hardcoded cause-key, every host path. Classify MECHANISM vs POLICY
  with a destination (`[reasons]` for the cause taxonomy? a `dos.toml [unstick]`
  table? a driver hook?). Repeat lighter passes for `promote` (leans on the unbuilt
  `dos pickable` verb) and `class-cycle` (leans on a new `[lifecycle]` table).
- **0b.** Record the verified substrate state this plan builds on:
  - `pickable.py` + `HoldReason` + `loop_decide.PICK_HELD_INVARIANT` — **shipped**
    (`8357ac0`), but **no `dos pickable` CLI verb** (Phase 1 adds it).
  - `recurring_wedge.py` — **shipped** (the "is this recurring?" fold); **no `dos
    unstick`/`dos wedge-sweep` verb** (Phase 5 decides whether to add one or have
    the skill compose existing verbs).
  - `enumerate` / `reconcile` — **NOT built** (Phases 2, 4).
  - cooldown / attempt-ledger — **NOT built, no kernel home** (Phase 3).
  - `dos init` scaffolds `dos.toml` only, **not skills** (Phase 7 adds `--skills`).
- **0c.** Confirm the skill-pack home + module homes match the layer contract:
  new modules under `src/dos/` (layer 1), the cooldown ledger event in
  `lane_journal` (the WAL tier), verbs in `cli.py` (layer 3), skills under
  `src/dos/skills/` (Axis-5 package-data). No new top-level package; no host name
  anywhere in `src/dos/` (except `drivers/`).

**Litmus (Phase 0):** a committed `docs/207-seam-ledger.md` listing every POLICY
line of the three skills with its data/hook destination, and naming the
no-destination-yet items as the genuine kernel gaps this plan fills.

---

## Phase 1 — `dos pickable` + `dos enumerate` CLI surface (expose the shipped/near gate)

Two thin verbs over kernel machinery. `pickable` exists; `enumerate` is built in
Phase 2 but its verb shape is designed here so Phase 2 ships the module *and* its
surface together.

- **1a.** Add `dos pickable` over `pickable.classify`: given a unit's declared
  state (read at the boundary — plan class, soak index, live claims), emit the
  `Pickability` verdict (`OFFERABLE` | `HELD(reason, evidence)`). `--json` emits the
  typed object; **the exit code is the verdict** (`OFFERABLE`=0, `HELD`=nonzero with
  a per-`HoldReason` code so a skill branches on *which* hold). Mirrors `dos gate`.
- **1b.** Design `dos enumerate <plan-doc>`: emit the `Enumeration` (`units`,
  `by_unit` spans, `drift` notes) the host's `derive_phase_universe` produces. The
  grammar comes from `dos.toml [enumerate]` (Phase 2). `--json` is the machine
  surface; a `DriftNote` is reported, never an exception (degrade-never-crash).
- **1c.** Verify `dos pickable` against the SCV/WCR foreign-repo rig: a unit whose
  declared class is the workspace's "draft" class returns `HELD(DRAFT_CLASS)`; an
  in-flight unit returns `HELD(IN_FLIGHT)`; a clean unit returns `OFFERABLE`.

**Litmus (Phase 1):**
- `test_cli_pickable_held_draft` — a draft-class unit → `HELD(DRAFT_CLASS)`, exit
  code per the hold, through the CLI.
- `test_cli_pickable_exit_code_per_hold` — each `HoldReason` maps to a distinct,
  documented exit code (the verdict IS the code).
- default-text output is byte-stable; `--json` round-trips the typed verdict.

---

## Phase 2 — `enumerate`: the phase-list producer (the unbuilt docs/168 §1)

The kernel's missing producer. Pure over bytes; the grammar is data. This is the
structural cure for the picker-invisibility gap (38 invisible plans) and the
`ladder read slot not priority` class.

- **2a.** Build `src/dos/enumerate.py`: `enumerate(source_bytes, *, grammar) ->
  Enumeration`. Pure — no file I/O (the CLI reads the file). The grammar
  (series-id-anchored headings, table first-cells, bare-`Phase N` fallback, the
  code-fence skip, the sibling-mention mask for the "(CD8 shipped)" trap) generalizes
  the `job` `plan_phases.py` deriver and `[stamp].phase_labels`.
- **2b.** Add the `[enumerate]` `dos.toml` table (heading regex, table-column index,
  bare-`Phase N` toggle) — the WCR data attachment, mirroring `[stamp]`. A repo that
  declares nothing gets a sensible generic grammar (markdown `### N. NAME` +
  `| Phase |` tables); a repo with a bespoke shape declares it.
- **2c.** Wire `completion` to use `enumerate` for the `declared` set so the
  residual computes end-to-end with no host callback (the modularity payoff — close
  the closed concept). Emit list↔table **drift** as a typed `DriftNote`
  (table/headers = authority, cached list = cache — the PPG lesson), the kernel-typed
  replacement for `job`'s `audit_plan_pickability --drift`.

**Litmus (Phase 2):**
- `test_enumerate_byte_parity_job` — replay over the `job` repo's ~63 ACTIVE plans
  (committed docs, offline, zero cost): `enumerate` produces the identical unit sets
  the host's `derive_phase_universe` did, OR a typed `DriftNote` where the host
  silently returned `[]`. **The byte-parity gate docs/168 names.**
- `test_enumerate_degrades_on_unparseable` — an unrecognized heading yields a
  `DriftNote(unparseable, span)`, never an exception, never a silently-empty universe.
- `test_completion_uses_enumerate_no_callback` — `completion` computes the residual
  from `enumerate` alone on a foreign repo.

---

## Phase 3 — the cooldown / anti-churn primitive (generalize the host's hardest lesson)

The single highest-leverage anti-churn mechanism, and the most house-style-coupled
concept in the `job` repo (`pick_attempts.jsonl` + `pick_cooldown.py`). Generalize
it into the WAL tier as a pure fold + a `loop_decide` rung — **not** a new state
file genre.

- **3a.** Add an `ATTEMPT` event to the lane journal (`lane_journal`), beside the
  `HEARTBEAT`/lease events: `{unit_id, outcome, ts, run_id}` written when a pick is
  *attempted* (claimed), carrying its outcome when known. It rides the durable WAL
  DOS already writes — one event genre, not a new file. Carries a `durable_schema`
  tag (refuse-don't-guess across kernel versions).
- **3b.** Build `src/dos/cooldown.py` (or fold into `loop_decide`): a pure
  `cooldown_verdict(unit_id, attempt_history, *, now_ms, policy) -> Cooldown`
  (`CLEAR` | `RECENTLY_ATTEMPTED(last_ts, count, until_ms)`). **Outcome-aware**: a
  unit already verified-shipped is pre-screened out (never re-offered), a unit
  attempted-and-drained within the window is `RECENTLY_ATTEMPTED`. The window +
  the outcome→backoff policy are `dos.toml [cooldown]` data (default e.g. 6h,
  matching the `job` value the operator tuned).
- **3c.** Wire it into `loop_decide.decide` as a new rung (`PICK_COOLDOWN`), the
  same way `PICK_HELD_INVARIANT` was: a loop whose only offerable next-unit is one
  it attempted-and-drained inside the window **does not re-dispatch** — it skips to
  the next unit, or honest-STOPs if all are cooled. This is the cross-run memory the
  bare loop lacked (the 1/21-runs-shipping measurement). Add `dos cooldown <unit>`
  as the read surface (CLEAR / RECENTLY_ATTEMPTED, exit-code verdict).

**Litmus (Phase 3):**
- `test_cooldown_skips_recently_drained` — a unit attempted-then-DRAINed 1h ago, a
  1h-default window → `RECENTLY_ATTEMPTED`; the same unit 7h ago → `CLEAR`.
- `test_cooldown_outcome_aware_shipped_prescreened` — a verified-shipped unit is
  never `RECENTLY_ATTEMPTED` (it is out of the residual entirely).
- `test_loop_decide_pick_cooldown_rung` — replay a bare-loop re-pick storm: the
  loop STOPs/skips on the cooled unit instead of re-dispatching. Backtest-invariant
  shape (`test_dispatch_scout.py::TestBacktestInvariant`).

---

## Phase 4 — `reconcile`: the quiet-completion gate (the unbuilt docs/168 §3)

The picker-boundary closure of the quiet-failure line. A join over two verdicts the
kernel already produces; no new sensor.

- **4a.** Build `src/dos/reconcile.py`: `reconcile(unit, claim, *, oracle_verdict)
  -> Reconciliation` (`VERIFIED` | `QUIET_INCOMPLETE` | `HONEST_OPEN`).
  **Fail-closed on the claim** (docs/107 generalized): claim-done ∧ oracle
  NOT_SHIPPED → `QUIET_INCOMPLETE`, **kept in the residual, flagged**. The agent's
  word never removes work; only ground truth does.
- **4b.** Wire `reconcile` at the residual boundary so a quietly-incomplete unit
  **re-enters the pickable set** next cycle with its `QUIET_INCOMPLETE` flag (the
  host routes it — to a verifier pass, to `/replan`, to a finding). This is the
  cross-run KEEP the `job` repo's FQ-336 storm needed (a touch-counts-as-ship false
  DRAIN would have been caught as `QUIET_INCOMPLETE`, not believed).
- **4c.** `reconcile` does NOT fix (docs/164): it is DETECT-and-KEEP, never a
  mutation. The host owns the correction; the kernel keeps the work alive.

**Litmus (Phase 4):**
- `test_reconcile_quiet_incomplete_kept` — claim-done + oracle NOT_SHIPPED →
  `QUIET_INCOMPLETE`, unit stays in residual.
- `test_reconcile_toolathlon_corpus` — over the `toolathlon-dos-phase0` corpus
  (751 trajectories, ground-truth `eval`): a claim-done + `eval=False` row →
  `QUIET_INCOMPLETE`. Precision/recall scored against the held-out label — **the
  natural extension of the quiet-failure study from DETECT-in-trajectory to
  KEEP-in-residual** (docs/157's bar: scored by an oracle it didn't author).

---

## Phase 5 — the operator-facing skill tier (`dos-unstick`, `dos-promote`, `dos-class-cycle`)

Three generic Axis-5 skills, ordered lightest→heaviest by what they depend on. Each
is grep-clean, shells `dos`, reads `dos.toml`, and is pinned by `test_skill_pack_*`.

- **5a. `dos-unstick`** (read-only, depends only on shipped `recurring_wedge`): sweep
  the run-archive trail of BLOCKED/DRAIN verdicts, normalize each to a canonical
  cause via `recurring_wedge`, cluster by recurrence × stall-cost, and propose **one
  structural fix per recurring cause** (a contract/oracle/preflight change), not a
  one-off unblock. The cause taxonomy is `[reasons]` (Axis 1) — a host adds a cause
  by declaring a reason, not editing the skill. Surfaces via `dos decisions`; writes
  no code (routing-only).
- **5b. `dos-promote`** (depends on Phase 1 `dos pickable`): the visibility-inverse
  of lifecycle-demote. Run `dos pickable` over every unit; for each `HELD`, surface
  the unit + its typed `HoldReason` + the **derived unblock action** (the
  reason→action routing is data: `DRAFT_CLASS`→promote-to-active, `UNPARSEABLE`→
  inspect-deriver/backfill, `OPERATOR_GATED`→raise-a-decision, `SOAK_OPEN`→wait).
  The only auto-applied action is a safe mechanical reclassify (gated, one commit);
  everything else is surfaced for a human. This is the operator-facing half of the
  shipped `pickable` primitive — the skill `promote` proved out in `job`.
- **5c. `dos-class-cycle`** (depends on a new `[lifecycle]` `dos.toml` table): the
  automatic plan-class transition cycle. Reads the **declared** class set + trigger
  list from `[lifecycle]` (not a hardcoded PCL taxonomy), evaluates each trigger,
  spawns a read-only JUDGE-rung adjudicator (the `dos.judges` seam — advisory,
  fail-to-abstain) to approve/defer each candidate transition, applies gated
  transitions as plan-meta edits + one commit per cycle, and logs to the run
  archive. Failsafes (per-cycle cap, per-plan cooldown, operator veto) are
  `[lifecycle]` data. The judge *content* is a host `dos.judges` driver; the
  *cycle mechanism* is domain-free.

**Litmus (Phase 5):**
- `test_dos_unstick_clusters_recurring` — a trail with one cause appearing 3× is
  clustered and ranked above a one-off; the proposed fix is structural.
- `test_dos_promote_surfaces_held_with_action` — a `HELD(DRAFT_CLASS)` unit is
  surfaced with the promote-to-active action; an `OFFERABLE` unit is not surfaced.
- `test_dos_class_cycle_reads_declared_classes` — a workspace declaring only
  `[lifecycle]` classes `active`/`done` runs the cycle with those two; no `job`
  class name appears.
- The grep-clean litmus per skill (full token absence of host literals).

---

## Phase 6 — extend the generic loop to use the new substrate (close the throughline)

The existing `dos-dispatch-loop` (SKP) gains the cooldown rung and the
pickable/reconcile gates so the **unattended loop** actually stops re-picking
drained work and keeps quiet-incomplete units alive — the throughline payoff.

- **6a.** `dos-dispatch-loop` Step (pick-selection) consults `dos pickable` before
  offering a unit, and `dos cooldown` to skip recently-drained units — so the loop's
  continue/stop is driven by `loop_decide` rungs (`PICK_HELD_INVARIANT` +
  `PICK_COOLDOWN`), not a per-run human override. The honest-STOP is now a kernel
  rule end-to-end.
- **6b.** `dos-dispatch-loop` archive step runs `dos reconcile` over each claimed
  pick so a quietly-incomplete pick re-enters the pickable set next iteration with
  its flag — the cross-run KEEP wired at the boundary that runs the write (the
  `CLAUDE.md` "wire the contract into the step that runs the write" rule).
- **6c.** `log` every gap the loop still has (no host evidence source, no per-pick
  soft-claim core — SKP F2/F3) so the capability boundary stays visible at runtime.

**Litmus (Phase 6):**
- `test_dos_loop_skips_cooled_unit` — a loop scripted over a cooled unit skips it,
  does not re-dispatch.
- `test_dos_loop_reconciles_quiet_incomplete` — a claimed-done-but-NOT_SHIPPED pick
  is kept pickable with `QUIET_INCOMPLETE` next iteration.

---

## Phase 7 — `dos init --skills` (the "worked on directly" on-ramp)

The user's explicit ask — *"so it can be used with `dos init` and then worked on
directly."* Today `dos init` scaffolds `dos.toml` only; the skills must be copied by
hand. Close that.

- **7a.** Add `dos init --skills [names…]` (or `dos skills install`): copy the
  selected generic `SKILL.md` screenplays from the wheel's package-data into the
  workspace's `.claude/skills/` (or a `--dest`), so a stranger runs `dos init
  --skills` and immediately has `/dos-next-up`/`/dos-dispatch`/… as **editable
  local skills** to work on directly, not package-buried prose. Default copies the
  core set; `--all` copies the full pack.
- **7b.** The copied skills are ordinary editable files (the package-data is the
  *seed*, not a runtime binding — exactly the folders→lanes one-time-scaffold
  pattern). A `dos doctor --check` rail (or `dos skills --check`) optionally reports
  drift between a copied skill and the shipped version, so a host knows when it has
  diverged — advisory, never blocking.
- **7c.** Update QUICKSTART + the SKP "how to use it" block: the adoption path is
  `pip install dos-kernel` → `dos init --skills` → edit/run. One command, not a
  manual copy.

**Litmus (Phase 7):**
- `test_init_skills_copies_editable` — `dos init --skills` writes the selected
  `SKILL.md` files into the dest as plain editable files; re-running is idempotent
  (no clobber of a diverged local copy without `--force`).
- `test_init_skills_grep_clean` — a copied skill still names no host literal (the
  seed is the shipped generic, which already passed the grep litmus).

---

## Phase 8 — the workflow-axis docs + the friction-log extension

Make the new tier first-class in the hackability story and record what resisted.

- **8a.** Update `HACKING.md` Axis 5: the pack now ships **eight** skills (the five
  SKP + the three operator-tier), and the `[enumerate]`/`[cooldown]`/`[lifecycle]`
  data tables join the four existing ones. Add the `dos pickable`/`dos
  enumerate`/`dos reconcile`/`dos cooldown` verbs to the syscall-ABI surface in
  `CLAUDE.md` + README.
- **8b.** Update `CLAUDE.md`: `enumerate`/`reconcile`/`cooldown` join the layer-1
  module list (with the import-litmus note); the cooldown `ATTEMPT` event joins the
  WAL tier; the three skills join the Axis-5 pack. **No new layer** — the table
  grows rows, not columns.
- **8c.** Extend `74-friction-log.md` (or a `207-friction-log.md`): record every
  place a `job` skill behavior could NOT be made generic — the curated-evidence
  streams (still F2, now also feeding `unstick`/`class-cycle`), the judge *content*
  (host `dos.judges` driver), the heavy soft-claim core (still F3). Mark F1 (packet
  template) and F6 (`dos decisions add`) as **resolved-or-still-open** given this
  plan touches the same surfaces. Each open item is a named target for the next
  iteration, written down instead of coded ahead of proof.
- **8d. Keep the back-flow ledger live (the §"How well recent fixes reach DOS"
  commitment).** Make the provenance-citation a **review rule**: a kernel module
  that lifts a `job` behavior must cite its `job` fix-id in its docstring/comment
  (as `claim_ttl`/`arbiter`/`oracle` already do), so `grep src/dos -e 'FQ-[0-9]'`
  is the standing back-flow manifest. Add the **per-fix disposition column** to
  docs/127's integration audit (lifted `<sha>` / scope-out `<reason>` / owed) so
  the stranded-cohort table is regenerable, not a one-time snapshot. The two
  modules this plan lands (`enumerate`, the cooldown primitive) must cite
  `FQ-491`/`FQ-493`/`FQ-494` so the audit shows the stranded cohort shrink by
  exactly those rows.

**Litmus (Phase 8):** `HACKING.md` lists the eight skills + the seven data tables;
`CLAUDE.md`'s syscall-ABI table includes the four new verbs; the friction log names
every still-open seam; and `grep src/dos -e 'FQ-49[134]'` returns the new modules'
provenance (the back-flow ledger proves these specific lifts landed — the plan's
own measure-then-change discipline, applied to itself).

---

## North-star acceptance (the whole plan is done when)

```bash
pip install -e .                          # the eight-skill pack + new modules ship
dos init --skills /tmp/svc && cd /tmp/svc # scaffold dos.toml AND copy the skills
# ... a repo with a couple of planning/*.md plans, some shipped, some drafty ...

dos enumerate planning/auth-plan.md       # lists the declared phases, in doc order,
                                          #   with a typed DriftNote if list↔table disagree
dos pickable AUTH AUTH3                    # OFFERABLE | HELD(DRAFT_CLASS) — exit code is the verdict
/dos-promote                               # surfaces every HELD unit + its unblock action
/dos-class-cycle                           # gardens the declared plan lifecycle (judge-gated)
/dos-dispatch-loop                         # the unattended loop now SKIPS cooled units,
                                          #   KEEPS quiet-incomplete picks, honest-STOPs on
                                          #   a re-dispatch-invariant hold — all kernel rules
```

…with the SKP five still working byte-for-byte, the existing kernel suite green, the
`job` repo's own driver-backed skills untouched (it keeps its battle-scarred tuning),
and three offline-replay gates passed before any prose was finalized:
**`enumerate` byte-parity over `job`'s 63 plans**, **`cooldown` re-pick-storm
backtest**, **`reconcile` scored on the toolathlon corpus.**

## Out of scope (explicitly)

- **Migrating `job` off its skills.** `job` keeps its five+ driver-backed skills
  (computed policy, battle-scarred tuning). This plan adds the generic *operator*
  tier for new hosts; it does not force `job` onto it (mirrors SKP/WCR).
- **Porting the heavy soft-claim leasing core.** `fanout_state.py`'s per-pick
  soft-claim core, `next_up_focus.py`'s value-greedy scheduler, the rate-limit
  resume machinery — SKP F3, parked by the layer contract. The cooldown primitive
  (Phase 3) is the *anti-churn* slice that is genuinely kernel-shaped; the full
  soft-claim core is not, and stays host-side. A full port is a separate plan if
  demand pulls it.
- **The lock-thrash / context-re-payment cost axis.** docs/168's deferred item —
  a host telemetry/caching problem (the `next_up_render.py` read-loop), needing a
  finer telemetry seam than the kernel owns. Named so it is not conflated with the
  picker substrate; not built here.
- **A skill runtime.** The pack ships *screenplays* driven by the Claude Code skill
  mechanism + the `dos` CLI; no new execution engine.
- **TOML-declared behavior.** Where a skill or module needs *code* (a computed
  judge, a bespoke evidence reader), that is a driver hook / `entry_point`, never
  `dos.toml` — the HACKING.md data/behavior split holds.

## Why this is eighth (and what it depends on)

SCV/WCR/RND/ADM made the *syscalls* honest and open; SKP made the *baseline
workflow* portable; overlap made the disjointness scorer swappable. This plan is
the first to extract the **operator-facing second tier** of workflow and the
**last two missing producers/gates** of the picker substrate — and it can only
stand on the substrate those seven plans built: it reads lanes/paths from WCR,
gates with `dos gate`, rides the `pickable`/`HoldReason`/`loop_decide` honest-STOP
rung SKP's successor (`8357ac0`) already shipped, and scaffolds skills the SKP pack
ships. It is eighth because it composes every prior plan: the workflow tier on top
of the syscalls, and the syscalls completed underneath it.
