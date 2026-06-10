# Deferred obligations — the mid-flight transition the intent ledger can't see

> **DOS can recover a run that *crashed* mid-flight ([`107`](107_resumable-work-and-the-intent-ledger.md):
> the intent ledger replays declared intent against the fossils and proposes a
> continuation). It cannot see a transition that was *deliberately left half-done* —
> a multi-step change where a later step was parked ("migrate the rest in a quiet
> window," "flip the flag later") with no run holding it, no deadline, and no
> detector. That is not a crash: no process died, no `run_id` owns the residual, and
> `liveness` never fires because the half-done state looks perfectly healthy. It is a
> *deferred obligation* that decays into a *forgotten* one. This note names that class,
> shows it is a real recurring failure (three instances found in one audit), and
> specifies the missing primitive: an append-only, kernel-adjudicated **obligation
> ledger** — the forward dual of the intent ledger, keyed by a *transition* instead of
> a *run*, carrying a **completion predicate as data** that the kernel re-checks at a
> boundary and surfaces (never performs). The intent ledger asks "a run died — how far
> did the fossils say it got?"; the obligation ledger asks "a transition stopped
> halfway by design — does its completion predicate hold yet, and if not, who still
> owes it?"**

A theory-plus-spec note in the family of [`107`](107_resumable-work-and-the-intent-ledger.md)
(the run-scoped resumption surface this is the dual of), [`106`](106_garbage-collection-and-the-reachability-verdict.md)
(reachability-is-a-verdict — extended here from "is this collectible" to "is this
transition finished"), [`94`](94_checkpoints-and-recovery-from-slop.md) (the
checkpoint/belief-vs-effect split the obligation verdict reuses), [`99`](99_runtime-validation-and-the-actuation-boundary.md)
(the advisory-only actuation boundary the obligation surfacer respects — it surfaces, a
human/driver acts), and the [`retention`](../src/dos/retention.py) seam (the
`should_compact` monotone-threshold posture the bloat half borrows).

**Status: the size half is SHIPPED, the obligation half is a buildable spec.** A pure
[`state_health.py`](../src/dos/state_health.py) leaf + `dos doctor --check` wiring (this
note's §4) already ships the *bloat* rung and the *pure obligation verdict*
(`classify_obligation`, `StateHealthVerdict`); what remains is the *durable obligation
ledger* + the writers + the `dos obligations` verb (§5 build order, Phases 2–4). The
prototype proves the verdict logic on frozen evidence (`tests/test_state_health.py`),
the [`82`](82_liveness-oracle-plan.md)/`liveness.classify` test posture.

---

## 1. The gap, named from a real incident (not hypothesized)

On 2026-06-04 a job-repo audit asked a blunt question: *why is `execution-state.yaml`
still 280 KB / 8,160 lines, full of legacy state, after months of cleanup work?* The
machinery to keep it lean exists and is sophisticated. The answer was not a bug in any
of it. It was that **three separate fixes had each been started and then deferred to
"later," and "later" had no owner, no deadline, and no detector** — so all three
silently became permanent:

| Deferred transition | Step that was parked | Why it never resumed |
|---|---|---|
| **SQLite history migration** (move the cold logs out of the hot YAML) | the bulk drain + the flag flip + the YAML-bucket drop were deferred to "a quiet window" | the dual-write intermediate state is *stable and healthy-looking* — nothing flagged that steps 2–3 were still owed; the store held 44/6 rows while the YAML held 227/207 |
| **The prune lever** (trim the cold buckets) | "run `prune --keep-recent` periodically" | the lever exists but has no scheduled hand; the default `prune --days 30` is a no-op on a self-windowing section, so the file never shrinks |
| **The plan-field migration** (`slot:`→`priority:`, retire `status: KEEP`) | "apply the rename to the data" | the code was renamed; the data was not; 9 plans on a retired enum and 27 on the old field name, 14 days past the cutover |

The shape is identical across all three: **a transition was intentionally split across
time, a later step was parked, and nothing in the system holds the residual or checks
whether it ever completed.** This is a *class*, not three coincidences.

### Why none of DOS's existing primitives catches it

| Primitive | What it keys on | Why it misses a deferred obligation |
|---|---|---|
| **Intent ledger** ([`107`](107_resumable-work-and-the-intent-ledger.md)) | a `run_id` + a `liveness`→STALLED trigger | there is **no run** — the residual was never owned by a process that *died*; it was set down on purpose. No crash, no `run_id`, no STALLED, no trigger. |
| **Reachability verdict** ([`106`](106_garbage-collection-and-the-reachability-verdict.md)) | "is this state still referenced / making progress" | a dual-write state is *fully reachable* **and** *fully incomplete* — reachability says "keep it," which is correct and useless; it does not ask "is the transition that produced this state finished?" |
| **`should_compact`** ([`retention`](../src/dos/retention.py)) | the lane journal's size/age | it is a pure threshold the kernel *exposes* but, like `prune`, has **no wired trigger** for an *external* state file — and size is only one of the three debts (the migration and the rename are not size problems). |
| **`verify` / the ship oracle** | a commit landed for a phase | a deferred obligation often has *no remaining commit to make right now* — its next step is "flip a flag in a quiet window," which `verify` has no notion of. |

The intent ledger (107) is the closest, and the contrast is exact and instructive.
107's whole framing is *"the kernel records what a run **decided** and what it
**committed**, but never what it was **trying to do**."* This note adds the missing
fourth quadrant: **the kernel also never records what a *transition* still **owes**.**

> 107: a crashed run is a stale self-report about *unfinished work it was doing*.
> 133: a deferred obligation is a standing promise about *unfinished work nobody is doing* —
> and the danger is precisely that nobody is doing it, so nothing ever looks wrong.

---

## 2. The reframe: an obligation is a reachability claim pointed forward in time

The load-bearing idea borrows 106's deepest move — *reachability is a verdict, not a
refcount or a clock* — and points it at *completeness* instead of *collectibility*:

> **A transition is "done" when an oracle says its completion predicate holds — not when
> a timer fires, not when someone remembers, not because the intermediate state looks
> healthy.** Until the oracle says so, the transition is *owed*, and being owed is a
> first-class, durable, surfaced fact.

This splits along the kernel's existing belief/effect line exactly as 94's
checkpoint/restore and 107's resume-point/resume did:

- **An obligation's *status* is a BELIEF the kernel may MINT.** "Transition T declared it
  is not complete until predicate P holds; P does not hold (the store is not yet a
  superset of the YAML); T is therefore `PENDING`, and it was declared 40 days ago past a
  30-day horizon, so it is `STALE`." This is an epistemic claim over caller-gathered
  ground truth (the [`86 §1`](86_the-typed-verdict-surface.md) boundary) — the kernel is
  *allowed* to produce it, the same way it mints a `liveness` or a `resume` verdict.
- **Discharging an obligation is an EFFECT the kernel may only PROPOSE.** Running the
  drain, flipping the flag, applying the rename — those mutate the world. They live where
  DOS puts effects: behind a human (a `dos decisions` emit-and-exit row that prints the
  command and exits) or a driver. **The kernel never performs the completion** — it marks
  the obligation owed and surfaces it until ground truth says it's satisfied. This is the
  [`99`](99_runtime-validation-and-the-actuation-boundary.md) advisory floor on the
  obligation axis, identical to 107's "the kernel proposes a resume; a driver enacts it."

The industry analogue is the *reconciliation loop* (Kubernetes controllers, Terraform
plan/apply, any desired-state system): declare the desired end state, observe the actual
state, surface the diff, and converge. DOS's twist is the one it always has — it does
**not** auto-converge (it is advisory, not an actuator: the [`99`](99_runtime-validation-and-the-actuation-boundary.md)
line), and it does **not** trust a self-report that the transition finished (it
re-evaluates the predicate against ground truth at read time, the [`103`](103_memory-is-an-unverified-agent.md)
move). *Declare the end state as a predicate; re-check the predicate against the fossils;
surface — never perform — the residual.*

---

## 3. The obligation ledger — a durable surface, reachability-shaped, keyed by a transition

The missing piece is a small, append-only, replay-foldable record of **declared
deferred transitions** and their **completion predicates**. It is the intent ledger's
sibling: same ARIES discipline (log-before-defer, torn-tail tolerant, pure replay fold),
different subject (*a transition's completion*, not *a run's progress*), different key
(a stable `obligation_key`, not a `run_id`).

### 3.1 Where it lives

It rides the workspace's `.dos/` home the same way the central projections do
(`home.py`): `.dos/obligations.jsonl`, an append-only ledger folded by a pure replay
into the live obligation set. Unlike the intent ledger (per-run-dir, GC'd with the run),
an obligation **outlives any single run** — it is a property of the *workspace's
transitions*, so it lives at the workspace root, not under a run-dir. (This is the one
place the dual is not symmetric: a run's intent dies with the run; a transition's
obligation persists until its predicate holds.)

### 3.2 The record vocabulary (closed, additive, schema-tagged)

Every record carries the [`durable_schema`](../src/dos/durable_schema.py) `schema:` tag
([`107 §6`](107_resumable-work-and-the-intent-ledger.md)) and the `obligation_key` it
belongs to:

| Op | Written when | Carries | Believed at read? |
|---|---|---|---|
| `DECLARE` | a transition is *deliberately* left partial | `obligation_key`; the human description; the **completion predicate** (as a named, re-evaluable check + its summary text); the declared horizon; the `declared_at` | **As a claim** — it is the operator's statement of what is owed and how to know it's done. The predicate is re-evaluated, never trusted as "already true." |
| `BLOCK` | a precondition is found unmet (the completion can't even be attempted) | `obligation_key`; the blocking reason | **As a hint** — re-checked at read; a stale BLOCK doesn't keep an obligation blocked if the precondition cleared. |
| `DISCHARGE` | a human/driver records that they completed it | `obligation_key`; the SHA / evidence | **Never on its own** — like 107's `STEP_CLAIMED`, a self-report. The obligation is only treated as satisfied when the *predicate re-evaluation* says so, not because a DISCHARGE was written. |
| `_CORRUPT` | replay hits an unparseable non-trailing line | the raw bytes | Never — the `lane_journal`/`intent_ledger` torn-tail sentinel. |

The asymmetry between `DISCHARGE` (the self-report) and the **predicate re-evaluation**
(the ground-truth check) is the epistemic spine, identical to 107's
`STEP_CLAIMED`/`STEP_VERIFIED` split: a `DISCHARGE` record is a *pointer to re-check the
predicate*, not proof the obligation is done. A buggy/forgetful driver that writes
`DISCHARGE` for a migration it didn't finish does **not** clear the obligation — the next
`dos doctor` re-evaluates `store ⊇ yaml ∧ flag_flipped ∧ yaml_buckets_empty`, finds it
false, and keeps surfacing it. *You cannot lie an obligation closed; you can only make
its predicate true.*

### 3.3 The completion predicate — data the caller evaluates, the kernel adjudicates

This is the crux, and the one genuinely new shape over 107. A completion predicate is
**not** code in the kernel (the kernel can't know a host's migration semantics). It is a
**named check** the host registers (the [`HACKING.md`](HACKING.md) closed-enum-as-data
discipline, the same way `[reasons]`/`[judges]`/`[overlap]` are data), evaluated at the
I/O boundary, with the *result* handed to the pure verdict:

```
# the pure leaf — already shipped (src/dos/state_health.py)
classify_obligation(Obligation(satisfied=<bool|None>, blocked=…, declared_at_ms=…,
                               horizon_days=…), now_ms=…) -> ObligationStatus
```

The boundary evaluates the predicate (it touches disk: counts rows, reads the flag,
diffs the store vs the YAML) and fills `satisfied`. The leaf stays pure. `satisfied=None`
(the boundary *could not* evaluate the predicate) is fail-closed to `PENDING` — the
direction every DOS verdict takes when evidence is missing (degrade toward "still owed,"
never toward "assume done"). The verdict:

- `SATISFIED` — the predicate holds; the obligation is discharged; drop it from the live set.
- `PENDING` — not satisfied, still inside its declared horizon: owed, surfaced as a finding.
- `BLOCKED` — a precondition is unmet: a human must clear it before completion is possible.
- `STALE` — `PENDING` past its horizon: **escalate** — this is the "we left a migration
  half-done 30 days ago" rung, the one thing that was structurally missing in the incident.

The whole thing is testable on frozen obligation records + frozen predicate results,
exactly like `liveness.classify` — no live half-done migration needed to prove the
adjudication (the [`107`](107_resumable-work-and-the-intent-ledger.md) design value,
restated for the obligation axis). It is shipped and pinned (`tests/test_state_health.py`).

---

## 4. What already ships (the size half + the pure obligation verdict)

The [`state_health.py`](../src/dos/state_health.py) leaf + the `dos doctor --check`
wiring (this note's first increment) already close the *bloat* half of the incident and
ship the *pure obligation verdict*:

- **`classify_state_file(evidence, policy, *, now_ms) -> StateHealthVerdict`** — a pure
  fold over caller-gathered evidence (total bytes, cold-section row counts, retired-token
  findings, **and** declared obligations), returning a typed verdict whose `findings()`
  renders the `dos doctor --check` lines (the `_treeless_lane_findings` shape). The size
  rung is `should_compact`'s monotone-threshold posture pointed at an external file; the
  legacy rung surfaces retired schema tokens; the obligation rung re-states each
  pre-evaluated obligation via `classify_obligation`.
- **`dos doctor --check`** now gathers the workspace's `execution_state` file (size +
  best-effort top-level section row counts, at the I/O boundary) and surfaces a bloat
  finding + a non-zero exit. The gap where doctor reported the *path* but never its
  *health* is closed. Live-verified against the job repo: it flags the 285 KB file and
  the two oversized cold sections, exit 1.

What this increment deliberately does **not** ship (it is the §5 build order): the
*durable* obligation ledger (`.dos/obligations.jsonl` + the `DECLARE`/`DISCHARGE`
writers), the host-registered named predicates, and the `dos obligations` verb. The pure
verdict is ready for them; they are host wiring + one new durable surface.

---

## 5. Build order (deepest leverage first; each step independently shippable + green)

- **Phase 1 — the pure verdict + the size rung in `dos doctor`.** ✅ **SHIPPED**
  ([`src/dos/state_health.py`](../src/dos/state_health.py),
  [`tests/test_state_health.py`](../tests/test_state_health.py),
  [`tests/test_state_health_doctor.py`](../tests/test_state_health_doctor.py)). The
  `ObligationStatus`/`Obligation`/`classify_obligation` + `StateFilePolicy`/
  `classify_state_file`/`StateHealthVerdict` leaf, and the `dos doctor --check`
  state-file health rail. Pinned: the four-way fail-closed obligation adjudication
  (incl. `satisfied=None`→PENDING and the horizon→STALE escalation), the size +
  legacy rungs, and the CLI-boundary wiring (bloated file → finding + exit 1; healthy/
  absent file → quiet).
- **Phase 2 — the durable obligation ledger (the new surface, §3).** The
  `.dos/obligations.jsonl` append/read_all/replay trio (byte-mirroring
  `intent_ledger`'s ARIES discipline: `fsync`, torn-tail tolerant, `_CORRUPT`
  sentinel, the §3.2 schema gate at read) + the pure `live_obligations(ledger) ->
  list[Obligation]` fold. The recovery *bookkeeping*, testable without a live
  half-done transition.
- **Phase 3 — host-registered predicates + the evidence boundary.** The named-check
  registry (the `[obligations]` / entry-point seam, the `[judges]`/`[reasons]`
  closed-enum-as-data shape) + the boundary that evaluates each declared predicate
  against ground truth and fills `Obligation.satisfied`. This is where "the migration
  is done iff `store ⊇ yaml ∧ flag_flipped ∧ yaml_buckets_empty`" becomes a registered,
  re-evaluable check rather than prose in an audit doc.
- **Phase 4 — the `dos obligations` verb (advisory actuator).** `dos obligations list`
  (replay + adjudicate + render), `dos obligations declare <key> --predicate <name>
  --horizon <days>` (append a `DECLARE`), and the `dos decisions` route for a `STALE`
  obligation (emit-and-exit: print the discharge command + exit). The
  [`99`](99_runtime-validation-and-the-actuation-boundary.md) advisory floor — it
  surfaces and proposes; a human/driver discharges.
- **Phase 5 — bench proof (the honesty discipline).** Inject deferred transitions into
  FleetHorizon the way [`107 §7`](107_resumable-work-and-the-intent-ledger.md) Phase 6
  injects crashes, and count "obligations-surfaced-before-they-rot vs
  obligations-found-only-by-a-manual-audit" — the falsifiable claim: a workspace with
  the obligation ledger surfaces a stalled migration *at the next boundary*, where a
  workspace without it finds it only when a human goes looking (months later, the
  incident).

Phase 1 is the leverage (the verdict + the bloat catch); 2–4 are the durable surface, the
predicate seam, and the actuator; 5 is the proof.

---

## 6. Non-goals (the lines that keep obligations a kernel concern, not an actuator)

1. **The kernel never discharges an obligation.** It mints the status and surfaces the
   residual; the act of completing is a human emit-and-exit decision or a driver — the
   [`99`](99_runtime-validation-and-the-actuation-boundary.md) advisory floor. There is no
   `dos obligations discharge` that *runs the migration*; there is one that *records you
   did* (and even that doesn't clear the obligation — the predicate re-check does).
2. **The kernel never believes a `DISCHARGE` self-report.** "Satisfied" is always
   re-derived from the predicate against ground truth (§3.2), never from the fact that a
   `DISCHARGE` record exists — the [`103`](103_memory-is-an-unverified-agent.md) posture.
3. **A predicate is host data, not kernel code.** The kernel adjudicates a
   *pre-evaluated boolean*; it does not know any host's migration/rename/prune semantics.
   The named-predicate registry is the [`HACKING.md`](HACKING.md) closed-enum-as-data seam,
   not a plugin that runs inside the verdict.
4. **No auto-reconciliation.** DOS is not a Kubernetes controller: it does not converge
   the world to the desired state on its own. It surfaces the diff and proposes; the
   convergence is an actuator's. (The whole point of the advisory floor is that an
   *untrusted* driver's actuation is gated on a human — [`132`](132_what-the-operator-may-resolve.md).)
5. **No silent schema reinterpretation.** An obligation record whose schema the reader
   can't soundly parse yields a typed refusal, never a best-effort guess
   ([`107 §6`](107_resumable-work-and-the-intent-ledger.md)).
6. **An obligation is not a plan, a task, or a TODO.** It is specifically a *deferred
   transition with a machine-checkable completion predicate*. "Write more tests someday"
   is not an obligation (no predicate); "the history migration is incomplete until
   `store ⊇ yaml`" is (a predicate ground truth can answer). The discipline that keeps the
   ledger from becoming a junk drawer is: **no predicate, no obligation.**

---

## 7. What this note claims, and what it does not

- **Does claim:** the mid-flight failure has *two* shapes, and DOS only had the first —
  a run that *crashed* with work in flight (107, covered) and a transition *deliberately
  left half-done* with the residual owned by nobody (uncovered until now); the second is a
  real recurring class (three instances in one audit); it is the forward dual of the
  intent ledger — keyed by a *transition* not a *run*, triggered by a *boundary re-check*
  not a *STALLED verdict*, carrying a *completion predicate as data* the kernel
  re-evaluates against ground truth and surfaces (never performs); and the
  reachability-is-a-verdict law (106) extends cleanly from "is this collectible" to "is
  this transition finished." The pure verdict + the bloat catch ship today.
- **Does not claim:** that the kernel should ever *perform* a discharge (it surfaces; a
  driver/human acts), that a `DISCHARGE` self-report can be trusted (the predicate
  re-check is the only thing that clears an obligation), that the kernel knows any host's
  completion semantics (the predicate is host data), that DOS becomes a reconciliation
  controller (it is advisory, not an actuator), or that the horizon defaults are
  calibrated (the Phase 5 bench is the eventual evidence source, like 94's REWORK and
  106's retention defaults).

The meta-answer, in one line: **a deferred obligation is a promise the system made to
itself and then forgot — so the fix is the distrust primitive pointed at the system's own
intentions: record the transition's completion as a machine-checkable predicate at the
moment you defer it, re-evaluate that predicate against ground truth at every boundary,
escalate it the moment it rots past its horizon, and *surface* — never silently perform —
the residual; the half-done migration that hid for months becomes a `dos doctor` finding
the next time anyone looks.**

---

## References

*The dual and the substrate this composes:*
- [`107_resumable-work-and-the-intent-ledger.md`](107_resumable-work-and-the-intent-ledger.md)
  — the run-scoped twin: declared intent re-verified against the fossils, the
  `STEP_CLAIMED`/`STEP_VERIFIED` self-report/ground-truth split the `DISCHARGE`/predicate
  split mirrors, the schema-tag durability floor (§6) this reuses.
- [`106_garbage-collection-and-the-reachability-verdict.md`](106_garbage-collection-and-the-reachability-verdict.md)
  — reachability-is-a-verdict, extended from collectibility to completeness.
- [`94_checkpoints-and-recovery-from-slop.md`](94_checkpoints-and-recovery-from-slop.md)
  — the belief-vs-effect (mint-vs-propose) split the obligation status/discharge split reuses.
- [`src/dos/state_health.py`](../src/dos/state_health.py) /
  [`src/dos/retention.py`](../src/dos/retention.py) — the shipped pure verdict + the
  `should_compact` monotone-threshold posture the bloat rung borrows.
- [`src/dos/durable_schema.py`](../src/dos/durable_schema.py) — the `schema:`-tag-per-record
  refuse-don't-guess gate every durable obligation record carries.

*The boundary and the posture:*
- [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md)
  — the advisory-only floor: the kernel surfaces an obligation, a driver/human discharges it.
- [`103_memory-is-an-unverified-agent.md`](103_memory-is-an-unverified-agent.md) — a prior
  commitment re-verified against ground truth at read time: the exact posture toward a `DISCHARGE`.
- [`132_what-the-operator-may-resolve.md`](132_what-the-operator-may-resolve.md) — why a
  `STALE` obligation's discharge is gated on a human, not auto-run by an untrusted driver.
- [`HACKING.md`](HACKING.md) — the closed-enum-as-data seam the named-predicate registry follows.

*Industry art (motivation, not load-bearing):*
- Desired-state reconciliation (Kubernetes controllers, Terraform plan/apply) — observe,
  diff, converge — with DOS's twist that it is advisory (surfaces the diff, does not
  auto-converge) and distrustful (re-checks the predicate, doesn't trust a "done" report).
- Database schema-migration trackers (Flyway/Alembic version tables) — a durable record of
  which migrations have/haven't been applied — generalized from "schema version N" to "an
  arbitrary completion predicate over ground truth."
