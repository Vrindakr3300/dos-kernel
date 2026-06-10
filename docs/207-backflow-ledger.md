# 207 — The job→DOS back-flow ledger

> **The standing answer to "are recent `job` dispatch fixes reaching the kernel?"**
> Companion to [`207_…`](207_dispatch-workflow-extraction-and-the-pickable-substrate-completion.md)
> §"How well recent fixes are actually reaching DOS." This file is the *live*
> version of that section's snapshot — regenerable, not hand-asserted. Generated
> 2026-06-07; the LANDED half is machine-derived (see "Regenerate" below), the
> STRANDED half is the curated work-list this plan moves.

## The principle: provenance is the manifest

DOS records each lift **in the kernel's own code** — a module that descends from a
`job` fix cites that fix-id in its docstring/comment. So the back-flow manifest is
not a registry that can drift out of sync with reality; it is a `grep` over
committed source. "Did fix X land?" is answered by ground truth (the citation is
in the module that implements it), never by a claim in a doc. This is the
evidence-over-narrative rule applied to the extraction process itself.

```bash
# the whole LANDED half, reproducibly:
grep -rhoE 'FQ-[0-9]+|MQ3X' src/dos/*.py | sort -u        # which fixes landed
grep -rlE '\bFQ-491\b' src/dos/*.py                       # where a specific fix landed (empty = not yet)
python scripts/backflow_ledger.py                          # the full table, both halves
```

---

## LANDED — `job` fixes with a kernel home (auto-derived 2026-06-07)

Every id below is cited in the named DOS module(s) — the proof the lift happened.
**18 distinct** dispatch fix-ids have crossed; the lag from `job` ship to kernel
lift runs days-to-weeks for mechanism-shaped fixes.

> **This table is generated, not hand-kept.** `scripts/backflow_ledger.py` derives
> it from the grep, runs the OWED detector against the live `job` repo, and is
> pinned by `tests/test_backflow_ledger.py` (11 tests, green) — which guards both
> the derivation and the catch that the known picker/integrity cohort
> (FQ-420/449/452/493/MQ3X) stays cited (a refactor that drops a provenance comment
> fails the suite). As of 2026-06-07 the detector reports **OWED: none** — every
> recent `job` dispatch fix is LANDED, curated-STRANDED, or scope-out.

| `job` fix-id | Kernel module(s) it landed in |
|---|---|
| FQ-77 | `phase_shipped.py` |
| FQ-240 | `gate_classify.py`, `loop_decide.py` |
| FQ-301 | `timeline.py` *(the ship-oracle positional-token parse; the recent `5c364f3b` host-arbiter re-wiring is a host-policy refinement on this lifted primitive, not a new lift)* |
| FQ-326 | `phase_shipped.py` *(soak false-positive guard)* |
| FQ-336 | `preflight.py` *(touch-counts-as-ship demotion — the quiet-DRAIN root)* |
| FQ-348 | `picker_oracle.py` |
| FQ-375 / FQ-388 / FQ-390 | `oracle.py` *(plan-id-collision + footprint gates, ON by default)* |
| FQ-409 | `phase_shipped.py` |
| FQ-410 | `decisions.py`, `preflight.py`, `wedge_reason.py` |
| FQ-419 | `packet_sidecar.py`, `wedge_reason.py` *(sidecar write ownership)* |
| FQ-420 | `loop_decide.py`, `packet_sidecar.py`, `pickable.py`, `preflight.py`, `tokens.py`, `wedge_reason.py` *(the set-not-list serialization lesson, lifted as the kernel-owned serializer + the typed gate)* |
| FQ-449 | `arbiter.py`, `sibling_scan.py` *(sibling-disjoint bare auto-pick)* |
| FQ-452 | `loop_decide.py` *(stale-stamp spin breaker)* |
| FQ-467 | `scout.py` |
| FQ-475 / FQ-493 | `pickable.py`, `loop_decide.py` *(the `HoldReason` drain-trap gate + the honest-STOP rung — `8357ac0`)* |
| #529 | `loop_decide.py` *(false-OVERLOADED 0-pick cause)* |
| `claim_status` | `claim_ttl.py`, `oracle.py`, `preflight.py` *(retracted-claim freeing)* |
| dead-lease / stall reclaim | `lease_health.py`, `supervise.py` |
| MQ3X (P1) | `claim_ttl.py`, `gh4_coverage.py`, `lease_health.py`, `sibling_scan.py` *("pure kernels lifted from job fanout_state.py")* |

**Read:** the integrity + picker cohort (FQ-326/336/390/419/420/449/452/475/493)
has crossed. The kernel is current with the consumer on everything mechanism-shaped
up to ~early June. docs/127 (the DOS↔Bench/Job integration audit) is the standing
process that keeps it so.

---

## STRANDED — open high-value items with NO kernel home (the work-list)

These are the `job` dispatch fixes that shipped 2026-06-06/07 and return
`module: none` on a `grep src/dos/`. Each carries a **disposition** so its lift is
*decided*, not silently deferred. This is the list the plan moves.

> **A note on the OWED detector's first run.** It initially flagged 8 commits;
> auditing them found 5 were already LANDED but carried a subject the
> citation-grep can't match (a bare `529`, a `claim_status` keyword, an FQ-id-less
> root like `3b0d08ae`'s set-not-list → `packet_sidecar`), and 3 were HOST-ONLY
> refactors (dir renames, an apply cycle-break). Those are recorded in the script's
> `_RESOLVED_BY_COMMIT` map so they stay resolved across runs — the detector now
> reports OWED: none. This is the ledger catching a gap in *its own tracking*,
> which is the point: an unmatchable-but-landed fix is invisible to a naive grep,
> and the resolution map makes it visible.

| # | `job` fix (commit) | Shipped | Value | Disposition | Owner phase |
|---|---|---|---|---|---|
| **S1** | FQ-491/493 pickability gap — `phase_prefix` deriver + stale-% classifier (`72082eca`) | 06-07 | **HIGH** — the phase-list *producer*; its absence = the 38-invisible-plans wedge | **LIFT** → `enumerate` (the exact producer) | **Phase 2** |
| **S2** | FQ-494 deterministic cooldown reset in `replan_autoclose` (`4eea0690`) | 06-06 | **HIGH** — the anti-churn reset; without a kernel cooldown it has no home, only `scout`-adjacent code | **LIFT** → the cooldown primitive (`ATTEMPT` WAL event + `PICK_COOLDOWN` rung) | **Phase 3** |
| **S3** | child2 `/fanout` launched DETACHED to survive parent `-p` exit (`4c7672cb`) | 06-07 | MED — fanout *lifecycle*, not a verdict | **SCOPE-OUT** — heavy tier (SKP F3); a process-survival fix is host-orchestration, not kernel mechanism. Friction-log it. | Phase 8c |
| **S4** | FQ-367 release orphaned soft-claims from dead `/fanout` children (`d2b8a897`) | 06-07 | MED — soft-claim *core* | **SCOPE-OUT** — the per-pick soft-claim core is the parked heavy tier (SKP F3). The pure *lease-health* slice already crossed (MQ3X); the soft-claim GC is host-side until demand pulls a full port. | Phase 8c |
| **S5** | FQ-498 lease scavenged mid-iteration — TTL vs wall-time (`47a6e11a`) | 06-07 | MED — lease-TTL *tuning* | **SCOPE-OUT** — a host lease-lifecycle *value* (the TTL window), not a kernel rule. The arbiter owns admission; the host owns its lease TTL. Note in `[concurrency_class]`/docs/110 if a second consumer wants it tunable. | docs/110 (existing) |
| — | FQ-472 force terminal JSON on gemini_cdp final turn (`070198f0`) | 06-07 | n/a | **N/A** — apply-backend, not dispatch. Out of this plan's lane entirely. | — |

**The shape of the open work:** exactly **two HIGH-value items (S1, S2) are owed a
lift**, and both already have an owner phase in the plan. The three MED items
(S3–S5) are correctly host-side (the heavy soft-claim/fanout-lifecycle tier the
layer contract parks) — their disposition is "scope-out, friction-log," not "owed."
So the back-flow is **not behind by much**: the kernel is current except for the
two mechanism-shaped producers this plan exists to lift.

---

## Moving the open items — the sequenced path

Ordered by dependency + value. S1 and S2 are independent of each other, so they can
proceed in parallel; both gate on a cheap replay before any kernel code.

### S1 → `enumerate` (the phase-list producer) — Phase 1b + 2

1. **Replay-gate first (zero cost).** Run `job`'s `plan_phases.derive_phase_universe`
   over its ~63 ACTIVE plans, capture the unit sets, and assert a fresh
   `enumerate(source_bytes, grammar)` reproduces them byte-for-byte (or emits a
   typed `DriftNote` where the host silently returned `[]`). This is the
   `test_enumerate_byte_parity_job` litmus — it must pass before the module's prose
   is final. *Borrow the recent `72082eca` `phase_prefix` deriver as the reference
   grammar; it is the most-evolved version of the producer.*
2. **Build `src/dos/enumerate.py`** (pure over bytes) + the `[enumerate]` `dos.toml`
   grammar table + `dos enumerate <plan-doc>` verb.
3. **Wire `completion` to use it** so the residual computes with no host callback —
   the modularity payoff that closes the `oracle`+`completion` concept.
4. **Cite the origin:** the module docstring names `FQ-491`/`FQ-493` (the back-flow
   rule). After this lands, `grep -rlE '\bFQ-491\b' src/dos/` is non-empty and S1
   moves LANDED.

### S2 → the cooldown primitive (anti-churn) — Phase 3

1. **Replay-gate first.** Take a `job` bare-loop re-pick storm (the run READMEs where
   a drained lane was re-picked every iteration) and assert a
   `cooldown_verdict(unit, history, now_ms, policy)` classifies the re-picked unit
   `RECENTLY_ATTEMPTED` inside the window — the `test_cooldown_skips_recently_drained`
   + `test_loop_decide_pick_cooldown_rung` litmus.
2. **Add the `ATTEMPT` event to `lane_journal`** (beside `HEARTBEAT`/lease events,
   `durable_schema`-tagged) — one WAL event genre, not a new state-file.
3. **Build the pure fold** (`src/dos/cooldown.py` or fold into `loop_decide`) +
   `[cooldown]` `dos.toml` window/backoff data (default 6h, the value the operator
   tuned in `job`) + `dos cooldown <unit>` read verb.
4. **Wire the `PICK_COOLDOWN` rung into `loop_decide.decide`** (sibling of the
   shipped `PICK_HELD_INVARIANT`) so the unattended loop skips cooled units.
5. **Cite the origin:** docstring names `FQ-494`. S2 moves LANDED.

### S3–S5 → friction-log, do not lift (the decided non-work)

Add one entry each to `74-friction-log.md` (or `207-friction-log.md`) recording
*why* it stays host-side — the SKP F3 heavy-tier line, restated per item — so the
"scope-out" is a written decision the next iteration inherits, not an omission. If a
**second consumer** ever needs the fanout-lifecycle survival (S3/S4) or a tunable
lease TTL (S5), that is a *new* plan (a full soft-claim-core port), not a fold into
this one.

---

## Keeping the ledger live (so it never silently rots)

1. **The review rule (Phase 8d):** a kernel module that lifts a `job` behavior
   **must** cite its `job` fix-id, or it fails review. This keeps the LANDED half
   a pure grep — self-maintaining.
2. **The regeneration command:** `python scripts/backflow_ledger.py` re-derives the
   LANDED table from the grep and diffs the STRANDED list against the current `job`
   fix stream, so a new high-value `job` fix that lands without a disposition shows
   up as an **`owed`** row. Run it in the docs/127 audit cadence.
3. **The success test:** when Phases 2–3 land, re-running the generator must show
   S1 and S2 move from STRANDED to LANDED — the plan's measure-then-change
   discipline applied to its own back-flow.

## Regenerate

```bash
# LANDED half (reproducible, the source of truth is the code citations):
grep -rhoE 'FQ-[0-9]+|MQ3X' src/dos/*.py | sort -u

# the full ledger (both halves + the owed-detector):
python scripts/backflow_ledger.py            # text
python scripts/backflow_ledger.py --json     # machine-readable for the docs/127 audit
```
