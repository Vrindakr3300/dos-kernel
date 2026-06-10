# 168 — The picker substrate and quiet completion: the missing syscalls

> Status: **DESIGN / concept proposal.** No code here. Derived from a 2026-06-05
> ground-truth sweep of the `job` consumer repo's recurring wedges + a
> `/trajectory-audit` over its last 40 sessions. Companion to the existing
> `picker_oracle` module (the post-hoc picker-quality audit), `completion`
> (docs/117, the `residual = declared − verified` verdict), and docs/149–164
> (the quiet-failure detector line).

## The pattern that prompted this

The kernel's load-bearing stance is **"don't believe the agent — ask ground
truth."** It already owns four ground-truth questions as syscalls:

| Question | Syscall | Ground truth it reads |
|---|---|---|
| Did this unit ship? | `verify` / `oracle` | git ancestry + substantive commit footprint |
| Can this lane run now? | `arbitrate` | live leases vs requested region (disjointness) |
| Is this run alive / advancing? | `liveness` | heartbeat + commit/journal delta |
| Should I start / continue / what? | `scout` / `loop_decide` | scoreboard, decision queue, overlap, resource floor |

But a fleet's *throughput* this week was not lost to any of those. It was lost
**before a worker ever launched** — to the question the kernel does **not** yet
own as a syscall:

> **"Is there anything here a worker could actually pick up — and if not, *why
> not*, precisely enough to route?"**

The `job` repo answers this question today entirely in its own code
(`fanout_state._phase_universe_has_pickable_phase`, `next_up_context.
_attach_pick_gates`, `plan_phases.derive_phase_universe`, `plan_pickability.
_phase_gate_reason`). The kernel has the `picker_oracle` module — but that is a
**post-hoc audit** that reconstructs ground truth *after* a dispatch already
emitted a verdict, to *measure* picker precision/recall. It is not a
**pre-dispatch gate** the picker can call to decide what to offer. So the host
re-implements the gate, and every bug in that re-implementation is a fleet-wide
wedge.

The evidence (all from the `job` repo, dates 2026-06-04→06):

- **FQ-420** — the picker serialized a gate-set as a Python `set`, hit
  `TypeError: Object of type set is not JSON serializable` at the packet's JSON
  boundary, rendered a body-empty-but-LIVE packet, and **every** downstream
  `/fanout` refused it. One un-typed value in the picker's own bookkeeping
  dead-locked the entire dispatch fleet for ~36h. Fixed job-side
  (`3b0d08ae`).
- **FQ-336 / FQ-444** — the ship check counted a *touch* of a plan doc as a
  ship, so routing-stamp and release-bump commits read as "phase shipped." A
  bare loop saw "all shipped" on a lane with real remaining work → false DRAIN →
  `child_skipped_replan` storm (8 re-confirms). Fixed by moving the decision
  into `dos.oracle` with substantive-footprint demotion + default-on hooks
  (`a2427731`).
- **The drain-trap (FQ-493 / ASI #475 / RTN / FMP)** — the pick-count oracle
  counted a **DEFERRED / DRAFT / operator-gated** phase as *pickable*. A bare
  loop auto-picked the top-priority lane, found every phase gated, DRAINed,
  `/replan` could not un-gate it (it cannot make an operator decision or
  fast-forward a soak), and the loop re-DRAINed every iteration. **Three
  distinct lanes** hit this in 36h. Fixed at selection time job-side
  (`d2aaa9df`).
- **The picker-invisibility gap** — ~38 of 63 ACTIVE plans had no
  machine-readable phase list, so the picker silently **dropped them with no
  refusal reason**. The loop deterministically landed on the one lane that was
  both visible *and* gated, and stopped — while plans with real work never
  reached the picker. Fixed job-side by a gated migration + a phase **enumerator**
  (`72ee55e6`, PPG plan).

Four wedges, four job-side patches, **zero new kernel invariants.** The kernel
caught none of them, because the kernel does not yet own "what is pickable."
The host's `derive_phase_universe` is exactly the capability `picker_oracle`'s own module doc names as
missing: `phase_shipped` can check whether *a known phase id* shipped, but
**nothing in the kernel can list the phase ids from a plan in the first place.**

This doc proposes the three syscalls that close that class, in the kernel's own
idiom: **pure classifier, host supplies the bytes, verdict is typed and
falsifiable.**

---

## Concept 1 — `enumerate`: list the work units a source declares

**Invariant owned:** *the set of work-unit ids a plan/source declares, derived
from its own text, in document order — independent of whether any of them
shipped.*

This is the capability the kernel lacks today and the host owns in
`plan_phases.derive_phase_universe`. `phase_shipped(plan, phase)` answers "did
*this* id ship?" but presupposes you already have the id. `enumerate` is the
missing producer:

```
enumerate(source_bytes, *, grammar) -> Enumeration
    Enumeration = { units: [UnitId], by_unit: {UnitId: SourceSpan}, drift: [DriftNote] }
```

- **Pure over bytes.** Takes the plan's text + a declared grammar (the host's
  `[stamp].phase_labels` regex generalizes to a `[enumerate]` grammar:
  series-id-anchored headings, table first-cells, bare-`Phase N` fallback). No
  file I/O — same discipline as `gate_classify.classify_packet`.
- **Two surfaces, one authority.** Plans carry the same phase set in two places
  (a prose table/headers and a cached `remaining:[]` list). The job repo's hard
  lesson (PPG): **the table/headers are authority, the list is a cache.**
  `enumerate` reads the authority and emits any list↔table **drift** as a typed
  `DriftNote` — it does not silently trust the cache. This is the structural
  cure for FQ-256/FQ-419 (the list and the table disagreed; the picker trusted
  the stale list).
- **Degrade, never crash.** A heading shape the grammar doesn't recognize
  yields a `DriftNote(unparseable, span)`, never an exception and never a
  silently-empty universe. The picker-invisibility gap was *silent* drop; the
  cure is a **typed "I could not parse this"** the picker can surface as a
  refusal reason, exactly as `picker_oracle` argues the NO-PICK-fake case must become visible.

**Why it belongs in the kernel:** enumeration + shipped-check + the residual
between them (`declared − verified`, docs/117 `completion`) is one closed
concept. The kernel already owns two-thirds of it (`oracle`, `completion`) and
the host owns the producer. Pulling `enumerate` in lets `completion` compute
the residual end-to-end without a host callback, and makes the **drift note** a
kernel-typed verdict instead of a job-side audit (`audit_plan_pickability
--drift`). The grammar stays policy (in `dos.toml`); only the parser is
mechanism. This is the dos-contribution the `job` repo already flagged as a
candidate ("the ENUMERATOR is the capability the kernel lacks").

---

## Concept 2 — `pickable`: a pre-dispatch gate, not a post-hoc audit

**Invariant owned:** *given a unit's declared state, is it offerable to a worker
right now — and if not, the single typed reason it is held.*

Today `gate_classify.classify_packet` types a packet's verdict (LIVE / DRAIN /
STALE-STAMP / BLOCKED) — but it consumes a **disposition list the host already
computed**. The host computes that list with `_attach_pick_gates` +
`_phase_gate_reason` (DRAFT? deferred-noted? soak-gated? dependency-unmet?).
That gate logic is the part that mis-fired in the drain-trap (it counted gated
phases as pickable) and the part that was un-typed in FQ-420 (the gate-set
serialization). Lift the gate itself into the kernel:

```
pickable(unit_state, *, now_ms, policy) -> Pickability
    Pickability = OFFERABLE
                | HELD(reason: HoldReason, evidence)
    HoldReason ∈ { SHIPPED, IN_FLIGHT, SOFT_CLAIMED_ELSEWHERE,
                   DRAFT_CLASS, OPERATOR_GATED, SOAK_OPEN,
                   DEPENDENCY_UNMET, COOLDOWN, UNPARSEABLE }
```

- **One closed enum of hold reasons.** This is the keystone. The drain-trap
  existed because "gated" and "shipped" were collapsed into a single boolean
  ("has a pickable phase: y/n") with no reason. The fix the host shipped
  (`d2aaa9df`) was exactly *"skip deferred/operator-gated/DRAFT lanes at
  selection"* — i.e. it added the reasons, in job code. As a kernel enum the
  reasons become **the contract every picker shares**, and the
  *consequence-routing* (a `DRAFT_CLASS` hold → `/promote`; an `OPERATOR_GATED`
  hold → escalate a decision; a `SOAK_OPEN` hold → wait, never `/replan`) is
  derivable from the reason instead of re-discovered per incident.
- **Composes with `loop_decide`.** The single most expensive recurring mistake
  was a loop that kept re-dispatching a lane whose *only* hold reason was one a
  re-dispatch cannot change (`DRAFT_CLASS`, `OPERATOR_GATED`, `SOAK_OPEN`). The
  loop's `decide()` models continue→dispatch on a DRAIN, so the host had to
  *override* with an "honest STOP" every time (documented across a dozen run
  READMEs and as many memory entries). With `pickable` typing the hold reason,
  `loop_decide` gains a clean rung: **a lane held only by re-dispatch-invariant
  reasons is STOP-now, not continue** — the honest-STOP becomes a kernel rule
  instead of a per-run human judgment. This is the same move docs/145 made for
  the stall reader: turn a thing the operator kept doing by hand into a typed
  signal the loop can branch on.
- **Pure; host gathers state.** Identical seam to `scout` (docs on
  `dos.scout.choose` reading a sibling `HealthVerdict`): `pickable` is
  `pure(state)`, all the I/O (read the plan class, the soak index, the live
  claims) on the host adapter side. The host's `_phase_universe_has_pickable_
  phase` becomes a thin `all(pickable(u).held for u in units)` instead of
  bespoke gate logic.

**Relationship to the `picker_oracle` module:** `pickable` is the **pre-flight
gate** (decide what to offer); `picker_oracle` is the **post-flight audit**
(was the gate right?). They share the `HoldReason` vocabulary — the oracle's
job becomes checking that a `HELD(OPERATOR_GATED)` really had an open decision,
a `HELD(SOAK_OPEN)` really had an open deadline, etc. One enum, two
consumers — exactly the `gate_classify` → `dispatch-loop` shape that already
worked.

---

## Concept 3 — `reconcile`: the quiet-completion gate at the picker boundary

**Invariant owned:** *a unit a worker called "done" but whose declared
end-state is not present is NOT removed from the residual — it stays pickable,
flagged.*

docs/149–164 established the kernel's quiet-failure line on the **execution**
side: an agent stops with required rows unwritten, and the detectors
(`dangling_intent`, `tool_stream`, `terminal_error → WARN`) raise recall on
that. The `job` repo's `/trajectory-audit` this session and its
`toolathlon-dos-phase0` study (memory: **65.6% of failures are QUIET** —
clean-looking, no error distress, `eval=False`) both point at the same shape
from the **portfolio** side: a phase marked shipped that wasn't, a "completed"
pick whose deliverable never landed. The kernel already has the two halves —
`oracle` (did it ship?) and `enumerate`/`completion` (what was declared?) — but
nothing wires them at the **picker boundary** so a quiet non-completion
*re-enters the pickable set* instead of vanishing.

```
reconcile(unit, claim, *, oracle_verdict) -> Reconciliation
    Reconciliation = VERIFIED          # claim done ∧ oracle SHIPPED → drop from residual
                   | QUIET_INCOMPLETE  # claim done ∧ oracle NOT_SHIPPED → KEEP in residual, flag
                   | HONEST_OPEN        # claim not-done → keep, no flag
```

- **Fail-closed on the claim.** This is docs/107's intent-ledger rule
  (`STEP_CLAIMED` stays in residual, `STEP_VERIFIED` is removed) generalized to
  the picker: a claim of completion that the oracle cannot confirm leaves the
  unit pickable. The agent's word never removes work; only ground truth does.
- **It's the missing closure of the throughline.** The verification substrate
  (docs/157–164) detects quiet failure *in a trajectory*. `reconcile` is what
  *does something with it across runs*: the quietly-incomplete unit shows back
  up as pickable next cycle, with a `QUIET_INCOMPLETE` flag the host can route
  (to a verifier pass, to `/replan`, to a finding). Without this, a quiet
  failure detected in run N is forgotten by run N+1 — the exact "forgetting
  plans" gap the host hit (38 invisible plans), but on the *completion* axis
  instead of the *enumeration* axis.
- **Cheap and structural.** No new sensor — it's a join over two verdicts the
  kernel already produces. It belongs at the boundary precisely because the
  job repo's CLAUDE.md rule applies: *wire the contract into the step that runs
  the write* (here, the step that drops a unit from the residual), not into a
  passive index.

---

## What these three share (and why they're kernel, not host)

1. **They are the producers/gates the host already re-implements.** `enumerate`
   = `plan_phases`; `pickable` = `_phase_universe_has_pickable_phase` +
   `_phase_gate_reason`; `reconcile` = the residual logic split across
   `next_up_render` + `ship_oracle`. Every one of this week's wedges was a bug
   in one of these host re-implementations. The kernel caught none because it
   owns none.
2. **They turn a recurring human override into a typed rule.** The "honest
   STOP" on a re-dispatch-invariant hold, the "route DRAFT→/promote not
   /replan," the "keep a quietly-incomplete pick alive" — all are currently
   *per-incident operator judgment* recorded in run READMEs and memory. Typing
   the `HoldReason` / `Reconciliation` enums lets `loop_decide` and the host
   router branch on them deterministically. This is the same lever docs/145
   (stall reader) and docs/150 (`dangling_intent`) pulled: **a thing the
   operator keeps deciding by hand becomes a signal the loop reads.**
3. **They stay mechanism-not-policy.** The grammar (`enumerate`), the
   hold-reason→action routing (`pickable`), and the residual-keep policy
   (`reconcile`) are all declared by the consuming repo in `dos.toml`. The
   kernel carries only the parser, the gate, and the join. Same split as every
   existing syscall.

## Falsifiable, before any code

The kernel's discipline is measure-then-change. The cheap pre-build tests:

- **`enumerate`** — replay the host's `plan_phases.derive_phase_universe` over
  the `job` repo's ~63 ACTIVE plans; `enumerate` must produce the identical
  unit sets (or a typed `DriftNote` where the host's deriver silently returned
  `[]`). Byte-parity gate, zero cost (offline replay over committed docs).
- **`pickable`** — replay the dozen drain-trap run READMEs: every lane that
  DRAINed-then-STOPped must classify as `HELD` with a re-dispatch-invariant
  reason (`DRAFT_CLASS` / `OPERATOR_GATED` / `SOAK_OPEN`). If any classifies
  `OFFERABLE`, the gate is wrong. This is the same backtest-invariant shape as
  `tests/test_dispatch_scout.py::TestBacktestInvariant`.
- **`reconcile`** — over the `toolathlon-dos-phase0` corpus (751 trajectories
  with ground-truth `eval`): a claim-done + `eval=False` row must classify
  `QUIET_INCOMPLETE`. Precision/recall measured against the held-out label, the
  same scoreboard docs/157–161 already use. **This is the natural extension of
  the quiet-failure study from DETECT-in-trajectory to KEEP-in-residual.**

None of these spends a live run; all three are offline replays over artifacts
that already exist. That is the bar docs/157 set ("the first DOS study scored by
an oracle it didn't author") and the one these proposals should clear before a
line of kernel code is written.

---

## Out of scope / deferred

- **The lock-thrash cost axis is real but separate.** The `/trajectory-audit`
  flagged a `read_loop` (HIGH, 4 sessions) — `next_up_render.py` read 22×,
  `fanout_state.py` 14× in single sessions, the heaviest session 178M
  cache-read tokens / 630 turns — and the host independently measured Step-0
  `acquire` re-parsing `execution-state.yaml` 4–5× under one lock (36–61s
  lock-wait). That is a **host telemetry/caching** problem ([docs/128](https://github.com/anthony-chaudhary/dos-private/blob/master/128_the-ultracode-economics-and-how-the-kernel-saves-spend.md), in `dos-private`, names the
  context-re-payment lever; there is no kernel re-read sensor and this doc does
  not propose one — it would need a finer telemetry seam than the kernel owns).
  Noted here only so it is not conflated with the picker substrate above.
- **`reconcile` does not FIX.** Per docs/164, the kernel keeps a worker's claim
  and re-offers the work; it does not author a correction. `QUIET_INCOMPLETE`
  is a DETECT-and-KEEP verdict, not a mutation.
