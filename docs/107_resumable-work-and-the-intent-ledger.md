# Resumable work — the intent ledger, and recovering a run that crashed mid-flight

> **DOS can already detect that a run died (`liveness` → STALLED) and reclaim its
> lane (`SCAVENGE`). What it cannot do is *continue the dead run's unfinished
> work* — because the kernel records what a run **decided** (the WAL: leases taken,
> dropped, evicted) and what it **committed** (git ancestry), but never what it was
> **trying to do** and **how far it got** on the part that isn't a commit yet. The
> WAL is a log of *adjudicated effects*; resumption needs a log of *declared intent
> and adjudicated progress against it*. This note specifies that missing ledger as a
> third durable surface alongside the journal and the spine — and, crucially, keeps
> the kernel on the right side of its own line: the kernel **mints a resume point**
> (a belief about how far a run verifiably got) and **proposes a continuation**
> (data: the residual work + the safe re-entry SHA); it never *performs* the resume,
> never re-runs an effect, and never believes the dead run's self-report about its
> own progress. Resume is the forward dual of [`94`](94_checkpoints-and-recovery-from-slop.md)'s
> walk-back: 94 localizes and proposes *undo*; this localizes and proposes
> *continue-from*.**

A theory-plus-spec note in the family of [`82_liveness`](82_liveness-oracle-plan.md)
(the verdict that decides a run is dead, which is resumption's *trigger*),
[`94`](94_checkpoints-and-recovery-from-slop.md) (which built `compact()`, named the
checkpoint/restore split, and **deferred the ARIES-UNDO and `(loop_ts,lane)→run_id`
correlation questions to its §7** — this note answers the forward half of both),
[`99`](99_runtime-validation-and-the-actuation-boundary.md) (the during-the-interval
moment + the advisory-only actuation boundary resume must respect),
[`103`](103_memory-is-an-unverified-agent.md) (a prior commitment re-verified against
ground truth at read time — the exact move resume makes on a dead run's *claimed*
progress), and [`106`](106_garbage-collection-and-the-reachability-verdict.md)
(reachability-is-a-verdict, which governs *when a resumable run is instead garbage*).

It carries no litmus and is not yet in the `next-stage-plan` table. §3–§6 were a
buildable spec; **Phases 1–5 are now SHIPPED** (the durability floor, the intent
ledger + the pure `resume_plan` fold, the `STEP_VERIFIED` mint on the non-forgeable
rung, pause/resume + the SUSPENDED reachability clause, and the advisory `dos resume`
actuator — see §7). Phases 0 (the manual-recipe note) and 6 (the FleetHorizon bench)
remain. The answers it earns:

1. **Resume is composition over a surface the kernel is one field short of having
   (§2–§3).** The WAL + spine + verdict ladder already reconstruct *what happened*;
   what is missing is a durable, append-only **intent ledger** keyed by `run_id` —
   the same ARIES discipline as `lane_journal`, aimed at *plan/progress* instead of
   *leases*. With it, resume is `replay(ledger) → residual` + a re-entry SHA the
   verdict ladder certifies, then a *proposed* re-dispatch.
2. **The pause/resume split is the crash/scavenge split made voluntary (§4).** A
   crash is an *involuntary* STALLED that `SCAVENGE` reclaims; a pause is a
   *voluntary* SUSPENDED that yields the lane while preserving the intent ledger and
   the resume claim. They share one mechanism (the ledger) and differ only in who
   wrote the last entry and whether liveness was ever consulted.
3. **"Safely" is the semantic-rollback-attack dual, and it has a precise answer
   (§5).** A naive resume re-runs the tail of a dead run and double-applies any
   effect that already committed (the duplicate-side-effect hazard [`94 §6.4`](94_checkpoints-and-recovery-from-slop.md)
   names for restore). The kernel forecloses it the same way it forecloses a forged
   ship: **the resume point stands on the most-accountable fossil (git ancestry),
   not the ledger's self-reported "I finished step 3."** You resume *from the last
   committed, verified SHA*, never from the last *claimed* step — so re-execution
   re-does at most the uncommitted tail, which is idempotent by construction (it
   produced no durable effect, or it would be a commit).
4. **"…or DOS changes" is a first-class durability axis the prior notes omit
   (§6).** A checkpoint, a journal, a run-record, an intent ledger written by DOS
   `v0.6` must remain *readable and resumable* by `v0.9`. This note specifies the
   schema-evolution discipline (a `schema:` tag on every durable record, forward-
   compatible additive evolution, a refuse-don't-guess floor on unreadable records)
   that makes the durable substrate survive the kernel changing under it — the
   property the whole "durable substrate" framing in `CLAUDE.md` quietly assumes but
   nothing yet enforces.

---

## 1. The gap, named from the code (not hypothesized)

Take the concrete failure the operator feels. A worker holds the `src` lane, is
three edits into a five-edit change, has committed the first two, and its process is
killed (OOM, machine reboot, `dos loop` restart, a crash). What does the kernel know,
and what can a successor do with it?

**What the kernel knows today** (all real, all shipped):

| Surface | What it holds about the dead run | Module |
|---|---|---|
| **The WAL** | `ACQUIRE src` at `loop_ts=T`; possibly some `HEARTBEAT`s; **no** `RELEASE` (it crashed) | [`lane_journal.py`](../src/dos/lane_journal.py) |
| **The spine** | `run.json` with `RID-…`, `parent_id`, `root_id`, `ts_ms` — the run's *identity and lineage* | [`run_id.py`](../src/dos/run_id.py) |
| **Git ancestry** | the two commits it landed (its *durable, unforgeable* output) | `git_delta` / `oracle` |
| **The liveness verdict** | STALLED — no fresh beat, and (correctly) it can be reaped | [`liveness.py`](../src/dos/liveness.py) |

**What a successor needs to resume, and the kernel does NOT have:**

1. **What was the run *trying to do*?** The WAL says it held `src`; it does not say
   "implementing the five-edit change described in plan P phase φ." `run.json` carries
   identity, not intent. There is **no durable record of the run's declared goal**.
2. **How far did it verifiably get?** Git says two commits landed; nothing connects
   those commits to "steps 1–2 of the five-step intent." There is no per-run
   **progress ledger** mapping intent → adjudicated completion.
3. **What is the *residual* — the work still to do?** This is (1) minus (2), and
   neither operand exists in a durable form. The successor would have to *re-derive
   the whole plan and re-discover what's done* — which is exactly the expensive,
   error-prone re-orientation the operator means by "can't resume properly."
4. **Which `run_id` did all of this?** Even reconstructing "everything the dead run
   touched" is blocked: journal entries are keyed by `(loop_ts, lane)`, **not**
   `run_id` ([`journal_delta`](../src/dos/journal_delta.py)'s "THE HARD PROBLEM",
   restated as [`94 §7`](94_checkpoints-and-recovery-from-slop.md)'s open
   correlation gap). The spine and the WAL do not join.

The shape of the gap: **DOS records *adjudicated effects* (leases in the WAL,
commits in git) but not *declared intent and progress against it*.** Effects are
what the kernel is *allowed* to believe (they happened, unforgeably). Intent is a
*self-report* — and the kernel's reflex is to not store self-reports. That reflex is
right for *trusting* the intent; it is wrong for *resuming* from it. The resolution
(§3) is the [`103`](103_memory-is-an-unverified-agent.md) move: **store the intent as
a declared prior commitment, and re-verify its progress claims against ground truth
at resume time** — never believe "I finished step 3," always check "did step 3's
commit land in ancestry."

> **The WAL answers "what was decided about leases." The intent ledger answers "what
> was the run trying to accomplish, and how far did the *evidence* say it got." The
> first is the kernel believing only effects; the second is the kernel storing a
> self-report so it can later distrust it against the fossils.**

---

## 2. The reframe: resume is replay-to-the-last-verified-point, then re-dispatch

The whole design is the ARIES recovery triad, completed. [`94 §3.2`](94_checkpoints-and-recovery-from-slop.md)
observed that `lane_journal.replay` is the ARIES **redo** fold and that DOS
deliberately does not own **undo** (rolling back a live lease's effects). Resume is
the *third* phase the WAL framing implies and neither 94 nor 106 builds: **redo the
intent ledger forward to the last point ground truth confirms, then continue from
there** — analysis → redo → *continue*, not analysis → redo → undo.

This splits cleanly along the kernel's existing belief/effect line, exactly as
[`94 §2`](94_checkpoints-and-recovery-from-slop.md)'s checkpoint/restore split did:

- **A resume point is a BELIEF the kernel may MINT.** "Run R got verifiably as far as
  commit `abc123`, which `verify`/`scope` certify as steps 1–2 of intent I; the
  residual is steps 3–5" is an epistemic claim over unforgeable git artifacts +ledger
  data. The kernel is *allowed* to produce it (the [`86 §1`](86_the-typed-verdict-surface.md)
  boundary), and it is the forward twin of [`94 §4.1`](94_checkpoints-and-recovery-from-slop.md)'s
  CHECKPOINT marker — a checkpoint says "this is a good place to *return to*"; a
  resume point says "this is the good place to *continue from*." (In the common case
  they are the **same SHA** — the last verified-good commit is both the safe rollback
  target and the safe re-entry target. A resume point is a checkpoint read forward.)
- **A resume is an EFFECT the kernel may only PROPOSE.** Re-spawning a worker,
  re-acquiring the lane, handing it the residual — those mutate the world (a process,
  a lease, a working tree). They live where DOS puts effects: behind a human (a
  `dos decisions` emit-and-exit action that prints the re-dispatch command and exits)
  or a host/driver. **The kernel never re-spawns and never re-runs the work.** This is
  the [`99`](99_runtime-validation-and-the-actuation-boundary.md) actuation boundary
  on the resume axis: the kernel's job is to *mark the safe re-entry point and compute
  the residual*; the act of re-entering is a driver's.

The industry analogue is durable-execution / workflow replay (Temporal, AWS Step
Functions, Restate, and — closest to home — this repo's own harness `Workflow`
`resumeFromRunId`, where "the longest unchanged prefix of agent() calls returns
cached results instantly; the first edited/new call and everything after runs live").
Those systems resume by **replaying a durable event history and re-executing only the
suffix past the last recorded checkpoint.** DOS's twist is the one it always has: it
**does not believe the history's claim that a step completed** — it re-verifies each
claimed completion against git ancestry before treating it as done (§5). Temporal
trusts its event log because Temporal *owns* every effect through its SDK; DOS cannot,
because the effect is an autonomous agent's commit, so DOS adjudicates the log against
the fossil. *Replay the ledger; trust git, not the ledger, about what finished.*

---

## 3. The intent ledger — a third durable surface, ARIES-shaped, keyed by `run_id`

The missing piece is one append-only, `fsync`'d, replay-foldable log per run,
recording **declared intent** and **progress beats against it**. It is `lane_journal`'s
sibling: same ARIES discipline (log-before-act, torn-tail tolerant, pure replay fold),
different subject (plan/progress, not leases), different key (`run_id`, not
`(loop_ts,lane)` — which *also closes the §1.4 correlation gap as a side effect*).

### 3.1 Where it lives, and why next to the spine

It rides the run-dir the spine already creates: `.dos/runs/<run_id>/intent.jsonl`
alongside the existing `run.json`. This is deliberate — the run-dir is *already* keyed
by `run_id`, so an intent ledger placed there is correlated-by-construction with the
spine. The `(loop_ts,lane)→run_id` join [`94 §7`](94_checkpoints-and-recovery-from-slop.md)
flagged as a prerequisite is sidestepped, not solved: rather than stamp `run_id` onto
every *lane-journal* entry (a kernel-spine schema change 94 rightly wanted justified on
spine merits, not driven by a recovery goal), we put the *resumption* data in a log
that is keyed by `run_id` from birth. The WAL stays exactly what it is (lease
correctness, keyed by lease identity); the intent ledger carries the run-scoped
progress the WAL was never meant to hold. Two logs, two keys, two jobs — the same
separation `journal_delta` keeps between "is this lease alive" and "what is the live
set."

### 3.2 The record vocabulary (closed, additive, ARIES-shaped)

A small closed op set, every record carrying the `schema:` tag §6 requires and the
`run_id` it belongs to:

| Op | Written when | Carries | Believed at resume? |
|---|---|---|---|
| `INTENT` | a run declares its goal (at spawn / first dispatch) | the plan+phase or a free-form goal string; the *declared* step list if one exists; the start SHA | **As a claim** — it is the run's self-report of what it meant to do. The residual is computed from it but every "done" is re-verified. |
| `STEP_CLAIMED` | the agent says it finished a unit of work | a step id + the SHA it *claims* landed the step | **Never on its own** — this is the forgeable self-report. It is a *pointer to a commit to check*, not proof the step is done. |
| `STEP_VERIFIED` | the kernel (at a CLI boundary) confirms a claimed step's SHA is in ancestry and passes the configured verdict conjunction | the step id + the verified SHA + which verdicts backed it + their rungs | **Yes** — this is a minted belief over unforgeable artifacts (a [`94 §4.1`](94_checkpoints-and-recovery-from-slop.md)-grade marker, scoped to a step). |
| `SUSPEND` | a run voluntarily yields (pause; §4) | reason; the resume point SHA; the residual at suspend time | **Yes** — it is a recorded decision, not a progress claim. |
| `RESUME_PROPOSED` | a successor/driver mints a resume point and proposes continuation | the resume-point SHA; the computed residual; the predecessor `run_id` | It is the *output*, not an input — recorded for forensics + idempotence (§5). |
| `_CORRUPT` | replay hits an unparseable non-trailing line | the raw bytes | Never — same torn-tail/sentinel discipline as `lane_journal`. |

The asymmetry between `STEP_CLAIMED` and `STEP_VERIFIED` is the entire epistemic
spine of the design, and it is [`102`](102_when-to-trust-an-agent.md)'s structure/
content line exactly: `STEP_CLAIMED` is **content** (the agent's say-so, distrusted);
`STEP_VERIFIED` is **structure** (git ancestry, which cannot misreport that a commit
happened). Resume reads `STEP_VERIFIED`s as done and treats every `STEP_CLAIMED`
without a matching `STEP_VERIFIED` as **not done** — fail-closed, the [`82`](82_liveness-oracle-plan.md)/ADM
direction (an unverified claim degrades toward "redo it," never toward "skip it").

### 3.3 Resume = a pure fold + a verdict, then a proposal

The resume computation mirrors `liveness.classify` field-for-field — pure verdict over
caller-gathered evidence (the [`94 §4.2`](94_checkpoints-and-recovery-from-slop.md)
template):

```
resume_plan(ledger_entries, ancestry_facts, policy) -> ResumePlan
```

- **Evidence (gathered at the boundary, pure to the core):** the `intent.jsonl`
  entries (`read_all`, torn-tail tolerant) + which claimed SHAs are actually in
  ancestry (`git_delta` / `oracle` at the CLI boundary) + the configured verdict
  conjunction's results per claimed step.
- **The fold (pure):** replay the ledger → the declared intent + the set of
  `STEP_VERIFIED` steps; subtract → the **residual** (declared-minus-verified); pick
  the **resume-point SHA** = the newest commit that backs a contiguous prefix of
  verified steps (the last point past which nothing is confirmed). Fail-closed: a
  `STEP_CLAIMED` whose SHA is *not* in ancestry contributes nothing (the agent claimed
  a step it never actually landed — the resume must redo it).
- **The verdict (`ResumePlan`, a closed-enum-carrying typed verdict):**
  - `RESUMABLE` — there is a clean resume-point SHA and a non-empty residual: continue
    from here, do this remaining work.
  - `COMPLETE` — residual is empty (every declared step is verified): nothing to
    resume; the run finished, it just never wrote a clean terminal record.
  - `DIVERGED` — the working tree / ancestry has moved on past the resume point in a
    way the residual can't be cleanly grafted onto (someone else advanced the lane):
    **refuse to auto-resume; raise a decision.** This is the analogue of a merge
    conflict, surfaced as a verdict rather than silently overwritten.
  - `UNRESUMABLE` — no `INTENT` record, or the ledger is `_CORRUPT` past the point of
    a sound fold: the honest floor (the [`94 §4.2`](94_checkpoints-and-recovery-from-slop.md)
    `INSUFFICIENT_DATA` twin) — *don't guess a residual you can't ground.*
- **The proposal (effect — NOT the kernel's):** on `RESUMABLE`, the resume point and
  residual become a `dos decisions` emit-and-exit row whose action bar prints the
  re-dispatch command (`dos loop dispatch --lane … --resume <run_id>` or a host's
  spawn verb) and exits. A driver may enact it; the kernel prints and stops — the
  [`99`](99_runtime-validation-and-the-actuation-boundary.md) advisory-only floor.

The whole thing is testable on frozen ledger + frozen ancestry lists, exactly like
`liveness.classify` and `lane_journal.replay` — no live multi-minute crashed run
needed to prove the recovery logic (the `loop_decide`/`journal_delta` design value,
restated for the resume axis).

---

## 4. Pause/resume is crash/scavenge made voluntary — one mechanism, two entry doors

The operator asked for *both* crash-recovery and deliberate pause/resume. The
insight that keeps this from being two subsystems: **they are the same ledger and the
same fold; they differ only in how the run stopped and therefore which final record
exists.**

| | Crash | Pause (voluntary suspend) |
|---|---|---|
| **How it stops** | process dies; no final record | run appends `SUSPEND` then exits cleanly |
| **Lease disposition** | no `RELEASE`; reclaimed by `SCAVENGE` after `liveness`→STALLED ([`106 §2`](106_garbage-collection-and-the-reachability-verdict.md)) | run appends `RELEASE` **and** `SUSPEND` — the lane is yielded politely, no scavenge needed |
| **Liveness verdict** | STALLED (the trigger to even look for resumable work) | not consulted — the run *declared* it was stopping; a SUSPENDED run is not "dead," it is "parked" |
| **Resume input** | replay ledger + re-verify every claimed step against ancestry (trust nothing) | replay ledger; the `SUSPEND` record already carries a *recorded* (not claimed) resume point — cheaper, but still re-verified at resume (a suspend an hour ago may be stale) |
| **What it shares** | the intent ledger, `resume_plan`, the `ResumePlan` verdict, the emit-and-exit proposal | identical |

The one new lease state this implies is **SUSPENDED**, distinct from both
*held-and-advancing* and *dead-and-scavengeable*. It matters because [`106`](106_garbage-collection-and-the-reachability-verdict.md)'s
reachability rule must not reap a *parked* run's resume data as garbage: a SUSPENDED
run released its lane but its `intent.jsonl` is **reachable** (resumable), not
collectible. So the GC reachability verdict gains one clause — *a run-dir is garbage
only if its run is terminal-COMPLETE or its resume plan is UNRESUMABLE; a SUSPENDED-
with-RESUMABLE run-dir is retained regardless of age.* Pause is, precisely, "make this
run scavenge-immune and lane-free until I come back," and resume is "re-adjudicate the
parked intent against current ground truth and propose the continuation." This is the
[`106`](106_garbage-collection-and-the-reachability-verdict.md) reachability law
extended from leases to *unfinished work*: **what is reachable is what an adjudicator
says can still make progress, not what holds a reference or beat a clock.**

A subtle but important consequence: pause/resume gives the operator a *safe
preemption primitive*. Today, stopping a worker to free a lane means either killing it
(losing its in-flight orientation) or waiting it out. With a `SUSPEND` op, a driver
(or `dos halt` — [`99`](99_runtime-validation-and-the-actuation-boundary.md)) can ask
a SPINNING run to *checkpoint its intent and yield* rather than be hard-killed — the
recoverable analogue of the halt the watchdog already proposes. The halt verb stops
being only "stop this" and can become "stop this *resumably*."

---

## 5. "Safely" — the resume point stands on git, never on the ledger's progress claim

This is the load-bearing safety property and the direct answer to the user's
"*safely* recover." A resume that re-executes the dead run's tail risks the
duplicate-side-effect hazard [`94 §6.4`](94_checkpoints-and-recovery-from-slop.md)
names (the 2026 "semantic rollback attack": re-running after a restore re-applies
committed effects). DOS forecloses it the same way it forecloses a forged ship — **by
refusing to let a self-report be the trusted input**:

1. **Resume from the last *verified* SHA, never the last *claimed* step.** The resume
   point is the newest commit in ancestry that a `STEP_VERIFIED` (a minted belief over
   unforgeable git) backs — *not* the newest `STEP_CLAIMED` (the forgeable self-
   report). A step the agent *said* it finished but never committed simply isn't in the
   resume point, so the successor redoes it. By construction the re-executed residual
   produced **no durable committed effect** (if it had, it would be a commit, and the
   resume point would include it) — so re-doing it cannot double-apply a committed
   effect. The idempotence is *structural*, inherited from "git is the only thing that
   proves an effect happened," exactly the [`84`](183_how-much-does-this-lean-on-git.md)
   most-accountable-fossil rule.
2. **The verify leg must stand on the non-forgeable rung.** Same hard requirement as
   [`94 §4.1`](94_checkpoints-and-recovery-from-slop.md)'s checkpoint: a `STEP_VERIFIED`
   may not be minted on `verify`'s forgeable no-plan subject-grep rung (defeated by
   `git commit --allow-empty`); it must stand on the diff-content / ≥N-distinctive-
   files rung, or the kernel refuses to mark the step verified (it stays in the
   residual). A resume point built on a forgeable verdict is *worse than no resume
   point* — it would skip work that never really happened.

   > **IMPLEMENTATION SHARPENING (from an adversarial review of the build).** The
   > intent ledger is written BY the distrusted run, so a stored `STEP_VERIFIED`
   > record is *itself a self-report* — a malicious/buggy run can append its own
   > `STEP_VERIFIED {via: "file-path", sha: <real ancestry commit>}` for a step it
   > never did. Trusting the stored record at read time would be the [`103`](103_memory-is-an-unverified-agent.md)
   > disease wearing a recovery hat. So the kernel **RE-ADJUDICATES every step at
   > READ time** (`resume_evidence.adjudicate_verified_steps`): the stored record is
   > an *unauthenticated hint* naming a `(step, SHA)` to re-check, and the pure verdict
   > (`resume.resume_plan`) trusts ONLY the boundary's fresh re-check
   > (`AncestryFacts.steps_verified_at_read`), never the agent-written `via`. And the
   > footprint check has two teeth, not one: (a) the commit must be a non-empty,
   > in-ancestry artefact (defeats `--allow-empty`); and (b) when the step declared a
   > **file region** (`step_regions` on its `INTENT`), the commit's footprint must
   > *intersect that region* — a forged record pointing at a real-but-*unrelated*
   > commit (one that touched only files outside the step's work) is rejected. Overlap
   > reuses the kernel's one collision algebra (`_tree.lane_trees_disjoint`), so there
   > is no second match definition. Pinned by `tests/test_resume_evidence.py` +
   > `test_intent_ledger.py::test_forged_step_verified_does_not_count_the_core_section5_fix`.
3. **`DIVERGED` refuses rather than overwrites.** If ground truth advanced past the
   resume point on the same lane (a successor already did some of the residual, or a
   human committed there), the fold returns `DIVERGED` and raises a decision instead of
   grafting stale residual over fresh work. This is the resume analogue of the
   arbiter's disjointness refusal — *don't write into a region that moved under you.*
4. **Resume is idempotent at the proposal layer.** A `RESUME_PROPOSED` record on the
   spine means a re-dispatch was already proposed for this predecessor; a second
   resume attempt sees it and does not double-propose (the watchdog's one-halt-per-
   window idempotence, [`101 §`](101_watchdog-driver-and-the-poll-cadence.md), applied
   to resume). Two supervisors racing to resume the same dead run converge on one
   proposal.

The meta-property: **resume never trusts the dead run about what it accomplished.** It
trusts git about what committed, the ledger only about what was *intended*, and re-
derives "done" by checking intent against ancestry. The dead run's `STEP_CLAIMED`
records are treated exactly as [`103`](103_memory-is-an-unverified-agent.md) treats a
recalled memory: a *prior commitment*, re-verified against ground truth at read time,
surfaced with a freshness verdict — never replayed as present fact.

---

## 6. "…or DOS changes" — the durable substrate must survive the kernel evolving

The user named a third hazard the prior notes omit: resume must hold *"even while …
DOS changes."* This is the **schema-evolution** axis of durability — the property the
`CLAUDE.md` "durable substrate" framing assumes but nothing yet enforces. A journal, a
run-record, a checkpoint marker, an intent ledger written by DOS `v0.6` must remain
readable and resumable by `v0.9`. Three disciplines make the durable surface
forward-survivable; all are policy/format, none is a new syscall:

1. **Every durable record carries a `schema:` tag.** `run.json` already does
   (`home.py`'s `project.json` has `schema`); generalize it to *every* persisted
   record — WAL entries, checkpoint payloads, intent-ledger lines. The tag is the
   version the *writer* used. A reader keys its parse on the record's own tag, never on
   "what version am I." (This is the closed-enum-as-data discipline of
   [`HACKING.md`](HACKING.md) applied to the *time* axis: the format is data the record
   declares, not a constant the code assumes.)
2. **Evolution is additive and forward-compatible by default.** New fields are
   *optional with a default* (the dataclass-default discipline already pervasive —
   `ProgressEvidence`'s `journal_events_since: int = 0`, etc.), so a `v0.9` reader sees
   a `v0.6` record's *absence* of a new field as that field's default, and a `v0.6`
   reader sees a `v0.9` record's *extra* field as ignorable. The replay folds already
   ignore unknown ops (`lane_journal.replay` only acts on `_STATE_MUTATING_OPS`,
   passing everything else through) — so an op added in `v0.9` is *safely skipped* by a
   `v0.6` replay rather than crashing it. **Additive op vocabulary is already
   forward-safe; this note only names it as a contract and extends it to record
   fields.**
3. **A breaking change is refuse-don't-guess, with a one-way migration fold.** If a
   record's `schema:` is *newer* than the reader understands in a non-additive way, the
   reader must **refuse to interpret it** (a typed `UNRESUMABLE`/`INDETERMINATE`
   verdict, surfaced — never a silent best-effort parse that resumes from a
   misread intent). This is the kernel's whole reflex — *when you can't verify, refuse;
   don't fabricate* — applied to its own persisted past. A genuine breaking migration
   ships as an explicit, operator-run fold (a `dos journal migrate` / `dos runs
   migrate` that rewrites old records to the new schema under the same `fsync`/torn-
   tail discipline as `compact`), the same shape as `compact()` (a pure
   old-entries→new-entries transform), never an implicit in-place reinterpretation.

The four-gate framing extends cleanly: a durable record's *readability across versions*
is a claim about *structure* (the bytes and their declared schema), not *content* (what
the agent meant), so it sits on the trustworthy side of [`102`](102_when-to-trust-an-agent.md)'s
line — the kernel can mechanically decide "can I parse this record's schema" without
believing anything the agent said. **The substrate survives the kernel changing because
each record declares its own format and the reader refuses what it cannot soundly
read — the same distrust posture the kernel takes toward agents, turned on its own
history.**

This axis also constrains the *journal* and *checkpoint* work of [`94`](94_checkpoints-and-recovery-from-slop.md)/[`106`](106_garbage-collection-and-the-reachability-verdict.md):
a `compact()` that rewrites the WAL, or an auto-compaction trigger, **must preserve or
upgrade the `schema:` tag**, never silently drop it — or a compaction performed by
`v0.9` would orphan records a `v0.8` reader (a concurrent `dos top`) could no longer
interpret. Schema-tag preservation is a new clause on the differential-equivalence
invariant: `replay(compact(E))` must equal `replay(E)` *and* every surviving record's
`schema:` must be readable by the same reader set that could read `E`.

---

## 7. Build order (deepest leverage first; each step independently shippable + green-able)

- **Phase 0 — the resume story that ships today, near-zero new code.** ◑ **SUPERSEDED
  by Phases 1–5.** The manual recipe (`dos verify` the last claimed phase to find the
  high-water mark, read `run.json` for lineage, hand a fresh worker the residual by
  hand) proved the *evidence* for resume already existed — and the shipped ledger +
  `dos resume` now make it cheap, so the clumsy hand-recipe is the thing the
  automation replaced rather than a standing deliverable. The runnable example is the
  DOGFOOD in this repo's working notes: mint a run-id, write an `INTENT` + a real
  `STEP_VERIFIED` + a forged `STEP_CLAIMED`, then `dos resume --run-id RID` returns
  `RESUMABLE` with the forged step back in the residual.
- **Phase 1 — the schema-tag floor (§6), because everything durable rides on it.** ✅
  **SHIPPED** ([`src/dos/durable_schema.py`](../src/dos/durable_schema.py),
  [`tests/test_durable_schema.py`](../tests/test_durable_schema.py)). The `schema:`
  tag contract (`tag(family, version)` write-side; `classify(record, family, understands)`
  read-side) + the typed `Readability` verdict that REFUSES an unreadable-newer record.
  Pinned: a `v99` record read by a `v1` reader yields `UNREADABLE_NEWER` (surfaced,
  never a silent misparse); an additive extra field is ignored; an UNTAGGED legacy
  record is the explicit caller-decides floor; the legacy bare-int `home.SCHEMA` tag
  bridges to a named reader. `intent_ledger.read_all`'s schema gate consumes it.
- **Phase 2 — the intent ledger as a pure surface (§3).** ✅ **SHIPPED**
  ([`src/dos/intent_ledger.py`](../src/dos/intent_ledger.py) +
  [`src/dos/resume.py`](../src/dos/resume.py),
  [`tests/test_intent_ledger.py`](../tests/test_intent_ledger.py)). `intent.jsonl` in
  the run-dir (`.dos/runs/<run_id>/`, keyed by `run_id` — closing the §1.4 correlation
  gap by construction) with the closed op vocabulary, the `append`/`read_all`/`replay`
  trio (byte-mirroring `lane_journal`'s ARIES discipline: `fsync`, torn-tail tolerant,
  `_CORRUPT` sentinel) PLUS the §6 schema gate at read, and the pure
  `resume_plan(LedgerState, AncestryFacts, policy) -> ResumePlan` fold. Pinned on
  frozen fixtures: `RESUMABLE`/`COMPLETE`/`DIVERGED`/`UNRESUMABLE`, the contiguous-
  verified-prefix anchor, the non-contiguous hole case, and the fail-closed
  "claimed-but-not-in-ancestry → residual" case. The recovery *logic*, testable
  without a live crash.
- **Phase 3 — the writers + the `STEP_VERIFIED` mint (§3.2, §5).** ✅ **SHIPPED**
  ([`src/dos/intent_ledger.py`](../src/dos/intent_ledger.py) entry builders +
  [`src/dos/resume_evidence.py`](../src/dos/resume_evidence.py),
  [`tests/test_resume_evidence.py`](../tests/test_resume_evidence.py)). The
  `intent_entry`/`step_claimed_entry`/`step_verified_entry`/`suspend_entry`/
  `resume_proposed_entry` builders + the CLI-boundary `verify_step` mint that
  re-checks a claimed SHA against ancestry on the **non-forgeable rung**
  (`step_stands_on_nonforgeable_rung`: in ancestry via `git merge-base --is-ancestor`
  AND a non-empty footprint via `git show --name-only`). Pinned, incl. an end-to-end
  REAL git repo: a forged `--allow-empty` step (in ancestry, touches nothing) never
  reaches `STEP_VERIFIED`; the resume point only ever includes ancestry-backed steps.
  (Teaching the host's dispatch loop to call these at spawn/done is host wiring.)
- **Phase 4 — pause/resume + the SUSPENDED state (§4).** ✅ **SHIPPED** (`SUSPEND`
  op + `suspend_entry` in [`intent_ledger`](../src/dos/intent_ledger.py); the pure
  `classify_run_dir_reachability` → `Reachability` verdict in
  [`resume.py`](../src/dos/resume.py); `dos halt --resumable` in
  [`cli.py`](../src/dos/cli.py); [`tests/test_resume_reachability.py`](../tests/test_resume_reachability.py)).
  The [`106`](106_garbage-collection-and-the-reachability-verdict.md) reachability
  clause, extended from leases to unfinished work: a run-dir is COLLECTIBLE only when
  COMPLETE or UNRESUMABLE; a SUSPENDED-RESUMABLE (or DIVERGED) run-dir is REACHABLE
  *regardless of age* — reachability is ADJUDICATED, never refcounted/clocked.
  `dos halt --resumable --run-id RID` appends a SUSPEND (parked & scavenge-immune)
  on top of the WAL HALT. Pinned: a SUSPENDED run's intent ledger is never GC'd while
  `resume_plan` returns `RESUMABLE`.
- **Phase 5 — the human actuator (still advisory).** ✅ **SHIPPED** (`dos resume` in
  [`cli.py`](../src/dos/cli.py) `cmd_resume`; the boundary evidence-gather
  `gather_ancestry` in [`resume_evidence.py`](../src/dos/resume_evidence.py);
  [`tests/test_resume_cli.py`](../tests/test_resume_cli.py)). `dos resume --run-id RID`
  replays the ledger, re-verifies progress against ancestry, and PROPOSES the
  continuation: it prints the residual + the non-forgeable re-entry SHA + the
  re-dispatch command (`dos loop dispatch --resume RID …`) and exits — it NEVER
  executes (the §8 non-goal / docs/99 advisory floor; the verdict IS the exit code:
  RESUMABLE/COMPLETE=0, DIVERGED=3, UNRESUMABLE=4, surfaced in `dos doctor --json`'s
  `exit_codes`). On RESUMABLE it idempotently records `RESUME_PROPOSED` (§5 req 4):
  two supervisors racing to resume one dead run converge on a single proposal.
  (Routing the same row through `decisions.collect_decisions` as a `RESUME` decision
  kind is a small follow-up; the actuator + the idempotent record are shipped.)
- **Phase 6 — bench proof (the honesty discipline).** Wire resume into FleetHorizon
  the way [`86 §3`](86_the-typed-verdict-surface.md) wired scope/liveness: inject
  crashes mid-run and count "work-recovered-vs-redone-from-scratch" as a measured
  dimension on the *same simulated fleet* — believed-resume (trust the agent's "I got
  to step 3") vs adjudicated-resume (re-verify against ancestry), with the gap closing
  as the ledger+verification engages. The claim to falsify: adjudicated resume redoes
  *less* total work than from-scratch **and** never double-applies a committed effect,
  where believed-resume occasionally does both.

Phases 1–2 are the leverage (the durability floor + the recovery logic); 3–6 are the
writers, the voluntary-pause surface, the actuator, and the proof.

---

## 8. Non-goals (the lines that keep resume a kernel concern, not an actuator)

1. **The kernel never re-spawns, re-acquires, or re-runs the work.** It mints the
   resume point and computes the residual; the act of continuing is a human emit-and-
   exit decision or a host/driver — the [`99`](99_runtime-validation-and-the-actuation-boundary.md)/[`94 §6.1`](94_checkpoints-and-recovery-from-slop.md)
   advisory-only floor on the resume axis. There is no `dos resume` that *executes*;
   there is a `dos resume --plan` that *prints the residual + the re-entry SHA*.
2. **The kernel never believes the dead run about its own progress.** `STEP_CLAIMED` is
   a pointer to a commit to check, never proof; "done" is always re-derived from
   ancestry (§5). A resume that trusted the self-report would be the [`103`](103_memory-is-an-unverified-agent.md)
   disease (a stale self-report replayed as fact) wearing a recovery hat.
3. **The kernel never resumes across a `DIVERGED` boundary.** If ground truth moved
   past the resume point, it refuses and raises a decision — it does not graft stale
   residual over fresh work (the merge-conflict-as-verdict rule, §5 req 3).
4. **No new state store beyond the run-dir the spine already owns.** The intent ledger
   is a `.jsonl` next to `run.json`, reconstructed by a pure replay fold — the same
   "no new store" discipline [`94 §6.3`](94_checkpoints-and-recovery-from-slop.md)/[`106 §5`](106_garbage-collection-and-the-reachability-verdict.md)
   hold. It is not a filesystem/conversation snapshot; git + the WAL + this ledger are
   the substrate.
5. **No silent schema reinterpretation.** A durable record whose schema the reader
   cannot soundly parse yields a typed refusal, never a best-effort guess (§6). A
   breaking migration is an explicit operator-run fold, never an implicit in-place
   reinterpretation.
6. **No cross-host resume / distributed handoff.** The run-dir and the WAL are
   host-local ([`94 §6.5`](94_checkpoints-and-recovery-from-slop.md)/[`106 §5`](106_garbage-collection-and-the-reachability-verdict.md)'s
   DLO non-goal); resuming a run that died on machine A from machine B is out of scope
   — the intent ledger correlates a run with *its* successor on the *same* host.
7. **No durable-execution framework ambitions.** DOS does not become Temporal: it does
   not own the effects, intercept the I/O, or guarantee exactly-once via a runtime
   harness. It adjudicates an *autonomous* agent's commits after the fact and *proposes*
   a continuation. The exactly-once property it offers is the weak, honest one git
   already provides (a committed effect is in ancestry once), not the strong one a
   side-effect-mediating SDK provides.

---

## 9. What this note claims, and what it does not

- **Does claim:** resumption is the forward dual of [`94`](94_checkpoints-and-recovery-from-slop.md)'s
  walk-back and the third ARIES phase the WAL framing implies (analysis → redo →
  *continue*); it needs exactly one new durable surface — an append-only, `run_id`-keyed
  **intent ledger** that stores *declared intent* (a distrusted self-report) and
  *adjudicated progress against it* (a minted belief over git), the missing complement
  to the WAL's *adjudicated effects*; the pause/resume split is the crash/scavenge split
  made voluntary (one ledger, one fold, a SUSPENDED state and a [`106`](106_garbage-collection-and-the-reachability-verdict.md)
  reachability clause); "safely" is the semantic-rollback-attack dual, foreclosed by
  resuming from the last *verified* (ancestry-backed, non-forgeable-rung) SHA rather
  than the last *claimed* step; and "DOS changes" is a first-class durability axis met
  by a `schema:`-tag-per-record + additive-forward-compatible + refuse-don't-guess
  discipline that makes the durable substrate survive the kernel evolving under it.
- **Does not claim:** that the kernel should ever *perform* a resume (it proposes; a
  driver/human acts), that an agent's progress self-report can be trusted (it is re-
  verified against the fossil at resume time), that the intent ledger is a new *store*
  (it is a `.jsonl` in the run-dir the spine already creates, folded by pure replay),
  that DOS becomes a durable-execution framework (it adjudicates autonomous commits
  after the fact, it does not mediate effects), or that the resume thresholds/policy are
  calibrated (the Phase 6 bench is the eventual evidence source, like the [`94`](94_checkpoints-and-recovery-from-slop.md)
  REWORK and [`106`](106_garbage-collection-and-the-reachability-verdict.md) retention
  defaults).

The meta-answer, in one line: **a crashed or paused run is a stale self-report about
unfinished work, so resuming it is the distrust primitive pointed at the run's own
intent — record what it *meant* to do (distrusted), re-verify how far the *fossils*
say it got, fold the difference into a residual and a non-forgeable re-entry SHA, and
*propose* — never perform — the continuation; and the ledger that carries all this
declares its own schema so it stays readable when the kernel that wrote it has moved
on.**

---

## References

*The recovery substrate this composes (§1, §3):*
- [`src/dos/lane_journal.py`](../src/dos/lane_journal.py) — the WAL the intent ledger is
  modeled on: `append`/`fsync`, `read_all` (torn-tail tolerant, `_CORRUPT` sentinel),
  `replay` (pure redo fold), `compact` (mark-and-copy), the closed op vocabulary and the
  `_STATE_MUTATING_OPS`/skip-unknown forward-compat property (§6).
- [`src/dos/run_id.py`](../src/dos/run_id.py) — the spine the ledger rides (`run.json`
  per run-dir, `run_id`/`parent_id`/`root_id`/`ts_ms`, the `schema`-tagged record §6
  generalizes).
- [`src/dos/journal_delta.py`](../src/dos/journal_delta.py) — the `(loop_ts,lane)→run_id`
  "HARD PROBLEM" the `run_id`-keyed ledger sidesteps; the boundary/pure-fold split the
  `resume_plan` fold mirrors.
- [`src/dos/liveness.py`](../src/dos/liveness.py) — STALLED, the trigger that says a run
  is dead enough to look for resumable work; the `classify(Evidence,Policy)->Verdict`
  shape `resume_plan` follows.
- [`src/dos/git_delta.py`](../src/dos/git_delta.py) / [`src/dos/oracle.py`](../src/dos/oracle.py)
  — the ancestry reader + the non-forgeable verify rung the resume point must stand on (§5).
- [`src/dos/decisions.py`](../src/dos/decisions.py) — the emit-and-exit action bar the
  `RESUMABLE` proposal routes through (the human actuator).

*The frame and the boundary (§2, §4, §5, §6, §8):*
- [`94_checkpoints-and-recovery-from-slop.md`](94_checkpoints-and-recovery-from-slop.md)
  — the backward dual; the checkpoint/restore belief/effect split; the ARIES-UNDO and
  `(loop_ts,lane)→run_id` open questions this answers forward; the forgeable-floor
  requirement; the semantic-rollback-attack non-goal.
- [`106_garbage-collection-and-the-reachability-verdict.md`](106_garbage-collection-and-the-reachability-verdict.md)
  — reachability-is-a-verdict, extended from leases to unfinished work; the run-dir
  reaper the SUSPENDED-RESUMABLE clause constrains.
- [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md)
  — the advisory-only actuation boundary; `halt` as the precedent for `halt --resumable`.
- [`103_memory-is-an-unverified-agent.md`](103_memory-is-an-unverified-agent.md) — a
  prior commitment re-verified against ground truth at read time: the exact posture
  resume takes on a dead run's `STEP_CLAIMED` records.
- [`102_when-to-trust-an-agent.md`](102_when-to-trust-an-agent.md) — the structure
  (git ancestry, trusted) vs content (the agent's say-so, distrusted) line that makes
  `STEP_VERIFIED` ≠ `STEP_CLAIMED`.
- [`82_liveness-oracle-plan.md`](82_liveness-oracle-plan.md) / [`86_the-typed-verdict-surface.md`](86_the-typed-verdict-surface.md)
  — the verdict template, the registry, "generalize last," and the fail-closed direction.
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md) — the
  most-accountable-fossil rule the structural-idempotence safety property (§5) inherits.

*Industry art the design builds on (motivation, not load-bearing):*
- ARIES write-ahead-log recovery (Analysis → Redo → Undo) — resume is the third phase
  the WAL framing implies, recast as analysis → redo → *continue*.
- Durable-execution / workflow replay (Temporal, AWS Step Functions, Restate) and this
  repo's own harness `Workflow resumeFromRunId` (longest-unchanged-prefix cached,
  suffix re-run) — replay-a-history-and-re-execute-the-suffix, with DOS's twist that it
  *re-verifies* the history against ancestry rather than trusting it.
- The 2026 "semantic rollback attack" line (re-execution after restore → duplicate
  side-effects) — the safety hazard §5's resume-from-verified-SHA forecloses.
- Schema-on-read / additive-forward-compatible record evolution (Avro/Protobuf evolution
  rules, event-sourcing upcasting) — the §6 discipline that lets the durable substrate
  survive the kernel changing.
