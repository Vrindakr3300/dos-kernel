# Checkpoints, restore points, and recovering a repo that is sliding into slop

> **Recovery is not a new subsystem. It is the kernel minting *verified-known-good
> markers* from evidence it already gathers, and folding the same evidence over time
> into a typed, neutrally-named verdict — while the *restore* (the `git revert` / `reset`
> / `checkout`) stays a human or driver act the kernel reports toward but never performs.
> The advisory-only soundness floor of [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) /
> [`90`](90_open-research-areas.md), extended to the temporal axis.**

A repo run by a fleet of self-narrating agents can degrade: the same files re-touched
five times with different bugs, scope creeping across lanes, leases refused and re-taken,
runs spinning without advancing. The industry now has a name for the symptom ("AI slop",
"code rot") and a small product category for the cure ("agent rewind", snapshot-and-restore).
This note asks the DOS-shaped version of the question: **how does the kernel expose the
*history* it already owns so that a damaged repo can be localized and walked back — and
what, precisely, are a "checkpoint" and a "restore point" in a trust kernel that is
*forbidden from believing the agents and forbidden from acting on its own conclusions*?**

It is a theory + spec note in the family of [`79`](79_primitives-not-features.md),
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md), [`84`](183_how-much-does-this-lean-on-git.md),
[`85`](85_extending-the-verifiable-surface.md), [`86`](86_the-typed-verdict-surface.md). It
carries no litmus and is not in the `next-stage-plan` table. §3–§6 are a buildable spec, not
yet built. The answers it earns:

1. **The checkpoint / restore-point split is the kernel / host split restated (§2).** A
   *checkpoint* is a belief about ground-truth state the kernel may MINT; a *restore point*
   is an EFFECT (mutating git) the kernel may only PROPOSE.
2. **Almost all of it is composition, not new machinery (§3).** DOS already ships a
   write-ahead log (`lane_journal`), a correlation spine (`run_id`), the per-commit
   predicates (`verify` / `scope` / `liveness`), and the open verdict registry
   (`verdicts.py`). Recovery is folds over those — git bisect is composition with *zero*
   new code.
3. **Exactly two new verbs are warranted (§4),** both passing the four-gate test, both
   strictly *state observations* with neutral names — never a code-quality opinion.
4. **A concrete, critique-hardened build order (§5)** that goes deeper before broader, and
   six non-goals (§6) that keep the kernel from drifting into an actuator or a judge.

---

## 1. What DOS already exposes (the history surface that is already there)

Recovery does not start from zero. The kernel already records, assembles, and adjudicates
history through five surfaces — this is the substrate every mechanism below composes:

| Surface | Module | What history it holds | How queried |
|---|---|---|---|
| **The WAL** | [`lane_journal.py`](../src/dos/lane_journal.py) | the durable, `fsync`'d, append-only record of every lane DECISION in mutation order — closed op vocab `ACQUIRE / RELEASE / HEARTBEAT / SCAVENGE / REFUSE / RECONCILE`; torn-tail tolerant; a mid-file corrupt line becomes a `{op:"_CORRUPT"}` sentinel rather than silently mutating state | `read_all` / `tail` / `next_seq`; `replay(entries)` — a **pure** fold to the authoritative live-lease set; `dos journal tail|replay|seq` |
| **The spine** | [`run_id.py`](../src/dos/run_id.py) | sortable, collision-safe `RID-…` tokens carrying lineage (`run_id` / `parent_id` / `root_id` / `ts_ms`); `run.json` per run-dir | `mint` / `mint_child_from_env` / `ts_ms_of` / `read_run_json`; `dos run-id mint` |
| **The git delta** | [`git_delta.py`](../src/dos/git_delta.py) | commits since a run's start SHA, as `[{sha, subject}, …]`, fail-safe to `[]` | `commits_since` / `count_commits_since` (root passed explicitly) |
| **The verdict ladder** | [`oracle.py`](../src/dos/oracle.py), [`scope.py`](../src/dos/scope.py), [`liveness.py`](../src/dos/liveness.py) | the per-commit / per-run distrust verdicts: `verify` (shipped?), `scope` (in its lane?), `liveness` (advancing?) | `dos verify` / `dos scope` / `dos liveness` |
| **The operator queue** | [`decisions.py`](../src/dos/decisions.py) | a **read-only projection** (stores nothing) over four decision feeds — arbiter `OP_REFUSE`, gate/WEDGE envelopes, preflight refusals, open soaks — each normalized with a resolver-kind (`ORACLE`/`JUDGE`/`HUMAN`) and an emit-and-exit action bar | `collect_decisions` / `next_steps`; `dos decisions` |

The crucial observation: **`lane_journal` is, structurally, an ARIES / event-sourcing
write-ahead log.** It does log-before-apply (the append happens inside the same state lock
that serializes the registry write, so journal order = mutation order), it `fsync`s before
the function returns, it tolerates a torn final record, and `replay()` is the pure
forward-fold that reconstructs state from the log — i.e. the ARIES *redo* phase, restated.
The pieces recovery theory is built on are already in the kernel; what is missing is the
*naming* of a checkpoint and the *reading* of the log's own soundness.

What is **NOT** there (the gaps, confirmed by grep — `checkpoint`/`bisect`/`restore-point`
appear nowhere in `src/dos`):

- **No checkpoint concept.** Nothing mints or records a "last point I can trust." The spine
  names a run's *start*, never a verified-good baseline.
- **No "which slice is the rot" query.** `commits_since` returns a flat list with no
  per-commit verdict; `verify` adjudicates a `(plan, phase)` claim, not "is commit X rot."
- **No bisect driver, no health-over-time verdict, no journal-integrity verdict, no
  identity/duplication verdict.** ([`85`](85_extending-the-verifiable-surface.md) already
  named journal-integrity and identity as candidate verbs — §4 builds the first as a blessed
  candidate, not a novelty.)
- **`run_id` ↔ `lane_journal` correlation is partial.** Journal entries are keyed by
  `(loop_ts, lane)`, not `run_id` ([`journal_delta`](../src/dos/journal_delta.py) calls this
  "THE HARD PROBLEM"), so "reconstruct everything run R did, then walk it back" is not cleanly
  answerable today.

---

## 2. The reframe: a checkpoint is a *belief*; a restore point is an *effect*

The whole design turns on one distinction, which is the kernel / host line restated on the
time axis:

- **A checkpoint is a belief about ground-truth state the kernel may MINT.** "This commit
  passed `verify` *and* `scope` *and* `liveness` cleanly" is an epistemic claim over
  unforgeable git artifacts — exactly the kind of thing [`86 §1`](86_the-typed-verdict-surface.md)
  says the kernel is *allowed* to produce. So the kernel can name a known-good point and
  record it.
- **A restore point is the ACT of returning to a checkpoint** — `git revert`, `git reset`,
  `git checkout <sha>`, a branch cut. That is an EFFECT, and every effect lives where DOS
  puts effects: behind a human (a `dos decisions` emit-and-exit action that *prints* the
  command and exits) or a host/driver. The kernel **never runs it.**

This is the same boundary `arbitrate()` and `spawn/reap` sit just outside of: they share the
pure `classify`-shape but produce an effect/identity, not a belief, so they are "cousins, not
members" of the [`verdict.py`](../src/dos/verdict.py) contract. *Mint the marker (epistemic) —
propose the undo (effect) — never perform it.*

The industry's "agent rewind" category (Rubrik's Agent Rewind, announced Aug 2025; Cohesity /
Cisco entrants reported early 2026) is the pattern **snapshot → detect → restore**. DOS
splits that triad exactly along its own line: it already *detects* (the verdicts) and already
keeps the *audit trail* (the journal + spine); it deliberately stops before *restore* and
proposes the command instead. The auto-restore half is also where the danger lives — the
2026 "semantic rollback attack" line of work (re-executing after a restore causes duplicate
side-effects) is a direct argument *against* a kernel that reverts on its own (non-goal §6.4).

And "which slice is the rot" is answered the way [`76`](76_flexible-goals-and-verification.md) /
[`85`](85_extending-the-verifiable-surface.md) demand: **never as a quality opinion, only as a
deterministic fold over unforgeable signals**, each carrying its provenance rung. The kernel
can say *these bytes were re-touched four times and two leases here were refused*; it can never
say *this code is bad* — that is a JUDGE's call, in a driver.

---

## 3. The composition layer — most of recovery needs no new kernel code

Three of the five mechanisms are pure composition over what §1 lists. They ship with little
or no kernel change and are the highest-leverage, lowest-risk moves (the [`85`](85_extending-the-verifiable-surface.md)
"go deeper before broader" discipline).

### 3.1 Bisect = `verify` / `scope` as the deterministic oracle git bisect was built for

`git bisect run <script>` is the canonical, decades-old tool for binary-searching commit
history for the change that broke something; the script's exit code is the good/bad signal.
DOS's truth syscall is *oracle-grade by construction* — deterministic, registry-free, works
with no plan present — so it drops straight in:

```bash
git bisect start <known-bad> <known-good>
git bisect run dos verify PLAN PHASE     # exit 0 = shipped/good, 1 = not → git localizes the break
# or, for footprint regressions:
git bisect run dos scope --lane LANE --base BISECT_HEAD~1 --head BISECT_HEAD
```

This is **zero new kernel code**: it composes the standard tool with verdict exit codes that
already exist. Be precise about *where* those exit codes live, because they are not unified
under one dispatcher today:

- `dos verify` exits **0 / 1** (`cli.py: cmd_verify` — `return 0 if verdict.shipped else 1`).
- `dos scope` exits **0 / 5 / 6** (`IN_SCOPE` / `SCOPE_CREEP` / `WRONG_TARGET`) — wired through
  the generic [`verdict_cli.py`](../src/dos/verdict_cli.py) dispatcher (`_SCOPE_EXIT`).
- `dos liveness` exits **0 / 3 / 4** (`ADVANCING` / `SPINNING` / `STALLED`) — still a *bespoke*
  `cmd_liveness` in `cli.py`, **not** migrated onto `verdict_cli` (the module says so itself).

`git bisect run` consumes whichever single verb's exit code you point it at; there is no
single `verdict_cli.run` map that surfaces all three (the migration is a separate follow-up).
For a linear (non-bisect) scan, `git_delta.commits_since` supplies the range. The composition
is the standard; DOS supplies the oracle. This mirrors the CI shift from merge-time gating to
per-commit behavioral-regression detection.

### 3.2 The lane-journal IS the recovery log (and `replay` is the redo fold)

No new store is needed to reconstruct dispatch state at a point in time. `lane_journal.replay`
is the pure WAL-recovery fold; a **bounded** replay (up to a `seq` or `ts`) is the
event-sourcing "snapshot + replay-after" optimization, and it is a trivial slice of the same
fold. The ARIES analogues line up cleanly: `seq` is the LSN; `replay` is redo; a future
`SNAPSHOT`/`CHECKPOINT` op (§4.1) is the checkpoint; the one phase DOS deliberately does *not*
own is UNDO — rolling back a live lease's *effects* — because that is an effect (§6.1, open
question §7).

### 3.3 The spine is the "who touched what" lineage — actuator stays human

The `run_id` lineage (`parent_id` / `root_id`, `ts_ms_of`) is the join for "everything run R
did," and `decisions.collect_decisions` + `next_steps` is the existing emit-and-exit action
bar that *prints* a shell command and exits without mutating substrate. A "rework detected"
row (§4.2) routes here: its action bar prints a **copyable** `git revert <range>` /
`git checkout <checkpoint-sha>` and stops. To flag whether a slice touched the kernel's own
adjudication path, reuse the **workspace-aware** `self_modify.existing_runtime_files(workspace)`
(the subset of `_DISPATCH_RUNTIME_FILES` that actually exists under the served root) — *not*
the raw static set, which would mislabel the damage radius in any repo that isn't DOS itself.
The `(loop_ts, lane) → run_id` correlation gap (§1) is the prerequisite for a clean
"walk back everything run R did" — see open question §7.

---

## 4. The two new verbs (each passes the four-gate test; each is state-only)

Run every candidate through the [`85 §2`](85_extending-the-verifiable-surface.md) four-gate
test — (1) claim about ground-truth state? (2) evidence unforgeable? (3) domain-free? (4)
mechanical closed enum? — and the honest sort is: **a checkpoint is a recorded *marker*, not a
verdict; a degradation fold and a journal-integrity check are real verbs; restore and bisect
are not verbs at all.**

### 4.1 CHECKPOINT — a minted verified-good marker (a fold + a vocabulary op, not a verdict)

**What it exposes.** A named, queryable answer to "what is the last point I can trust?": a
commit SHA the kernel marks *good* only when a declared set of verdicts all held cleanly there.
Agents read it as JSON (the SHA + which verdicts backed it + each one's provenance rung);
humans see a chip/row. It is **data pointing at a commit git already stores immutably** — never
a captured filesystem/conversation snapshot (non-goal §6.3).

**Four-gate sort.** The *marker* is a SHA + recorded verdict values — data, not a new verdict
enum, so it does **not** enter the verdict registry. It PASSES as a recorded marker and
(correctly) FAILS as a standalone verdict. Mechanically it is:

- a **cli-helper FOLD** over already-shipped verbs (`oracle.is_shipped` + `scope.classify` +
  `liveness.classify`), composed at the CLI boundary; plus
- a new **closed lane-journal op** `CHECKPOINT` — *vocabulary* expansion, the
  [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) "expand by vocabulary, not machinery"
  move — recorded on the spine via `run_id`, reusing the `fsync`-before-mutate WAL discipline;
  optionally surfaced out-of-band as a git note / `refs/meta/*` ref (§4.4).

**Two hard constraints the critiques surfaced — both adopted as requirements, not options:**

1. **The conjunction is configurable, not hardcoded.** Which verdicts must pass to call a
   commit "verified-good" is a *policy* — a host may want verify-only, verify+scope, or a
   fourth driver verdict. The kernel mechanism is: *record a marker at SHA, stamping which
   named verdicts backed it and their values.* The conjunction is composed at the boundary,
   the same conjunctive-seam discipline the arbiter uses for admission predicates. This keeps
   CHECKPOINT a fold, never a built-in definition of "good."
2. **Never mint on the forgeable floor.** `verify`'s no-plan subject-grep rung is defeated by
   `git commit --allow-empty -m "<stamp>"` ([`85 §3.1`](85_extending-the-verifiable-surface.md)).
   A checkpoint built on a forgeable verdict is *worse than no checkpoint*. So the `verify` leg
   of a checkpoint MUST stand on the diff-content / ≥N-distinctive-files rung — or the kernel
   refuses to mint. (This is the [`85`](85_extending-the-verifiable-surface.md) "harden the
   weakest rung" move, here a *precondition* on minting.)

**Industry anchor.** The format prior art is **git-meta** (`refs/meta/*` typed metadata on git
objects, 2025) and plain **git notes** — an out-of-band, queryable, history-non-polluting
marker layer, the same shape the *Assisted-by* trailer / SLSA+in-toto attestation convergence
points at. DOS's twist vs the IDE/shadow-git checkpointers (Hermes, Gemini CLI, Kilo, Cursor,
Claude Code's own checkpointing) is two-fold: (a) those snapshot *everything* into a separate
shadow repo and trigger *before every edit unconditionally* — DOS mints *after* a typed verdict
gate, so a checkpoint is a known-**good** point, not merely a return point; (b) DOS records a
*marker pointing at the real commit*, not a parallel snapshot store (non-goal §6.3). Cite the
shadow-git tools only for the trigger-timing contrast; anchor the marker *format* on
git-meta / git-notes.

### 4.2 The degradation fold — a typed verdict, neutrally named (the `classify(history) → trend` instance)

This is the one place the design walks up to the cliff edge, and the critiques were right to
push hard. The mechanical fold is sound; the *naming* is where a quality opinion can sneak in.

**What it exposes.** A per-window answer to "how much measured rework / refusal / spin happened
here?" as a CLOSED enum — and the enum is **deliberately neutral**, never "HEALTH"/"ROT"/"SLOP".
Those are value judgments about the workspace dressed as state reports; the kernel's existing
verbs are neutrally named (`ADVANCING`/`SPINNING`/`STALLED`, `IN_SCOPE`/`SCOPE_CREEP`/
`WRONG_TARGET`) *precisely* so a verdict cannot be read as "this is good/bad code." So the verb
is named for the **measurement**, e.g.:

```
REWORK_NOMINAL  — measured re-touch / revert / refuse / spin counts within the window's policy band
REWORK_RISING   — counts above the nominal band but below the high cutoff
REWORK_HIGH     — counts above the high cutoff
INSUFFICIENT_DATA — too few commits/events in the window to classify (the honest floor)
```

"Rework" means *measured re-touch + revert + scope-creep + REFUSE + SPINNING counts* — bytes
moved or leases refused — and the `reason` names the counts, never quality. The instant a
threshold means "good code looks like X," the verb has become a driver JUDGE and must demote
out of the kernel (gate 1).

**Four-gate sort.** (1) YES — "this window's counts exceed a band" is a claim about observed
history. (2) YES — every input is a deterministic count over git + the journal; none is the
agent's self-report. (3) YES — domain-free counts. (4) YES — closed enum + reason + echoed
evidence + `to_dict`, conforming to `verdict.TypedVerdict`. PASSES all four → a legitimate
kernel verb.

**Two requirements the critiques surfaced — adopted:**

1. **Thresholds live in a frozen `Policy` with a `dos.toml [<verb>]` seam**, exactly like
   `LivenessPolicy`'s windows. `classify` reads cutoffs from `Policy` only — *no hardcoded
   cutoff in the kernel.* The GENERIC defaults are explicitly **provisional** and are *not*
   grounded on the industry numbers below (open question §7). If a generic threshold can't be
   defended domain-free, the verb emits the raw counts + `INSUFFICIENT_DATA` and lets a host
   policy bucket them. The counts are kernel-grade evidence; the count→verdict cutoff is the
   policy knob.
2. **Re-touch is not assumed-bad.** Same-file re-touch correlates with *both* refactoring
   (good) and thrash (bad), and the kernel cannot mechanically tell them apart — so the verdict
   echoes re-touch as a *count in evidence* and lets the band (in `Policy`) do the bucketing;
   it never encodes "high churn = degrading" as kernel mechanism (that is the GitClear/CodeScene
   *opinion*, and opinions live in drivers).

**Composition.** Mirror `liveness.classify` field-for-field (Enum + frozen `Policy` + frozen
caller-gathered `Evidence` + `to_dict` + pure `classify`). Evidence readers reuse what already
exists: `git_delta.commits_since` for the range, `oracle._git_touched_files` (the kernel's
existing "read what a commit actually did" primitive) for re-touch/churn counts, per-commit
`scope.classify` for the creep fraction, and a `lane_journal.read_all` fold for `REFUSE` /
`SCAVENGE` density and `SPINNING`-streak length. Register it in the **existing**
[`verdicts.py`](../src/dos/verdicts.py) registry with `reviewed=True`, exactly like `scope`
and `liveness`, and surface it through `verdict_cli.attach` — but **generalize last**
([`86 §4`](86_the-typed-verdict-surface.md)): build it only once it has ≥2 real consumers (the
decisions-queue row + the FleetHorizon trajectory column).

**Industry anchor (grounding, with the precision the critiques demanded).** The degradation
*literature* motivates the signals but does **not** ground a generic cutoff:

- GitClear's 2025 analysis (211M lines) — code **churn** rose **3.1% → 5.7%** (2020→2024,
  exact) and **refactoring** fell **24.1% → 9.5%** (exact). Duplication grew too (duplicated
  *blocks* ~8×; copy-paste *lines* 8.3% → 12.3%) — use the churn/refactoring figures as the
  load-bearing ones and qualify the duplication multiplier by metric.
- The MSR-2026 *Source Code Hotspots* paper (arXiv 2602.13170) — a 15-pattern taxonomy with
  **74% of hotspot edits automated (bot-driven)**; cite it for the taxonomy + the bot-driven
  fact. (μ+3σ outlier analysis is the *standard* hotspot method DOS would reuse, **not** a
  headline finding of that paper — don't attribute it as such.)
- CodeScene behavioral code-health and the DORA-2025 change-failure-rate framing as the
  general direction.

DOS's contribution over all of these is the framing they lack: a **typed verdict carrying its
provenance** (a closed enum + *which signal fired*), not a 0–100 composite score whose
internals are an opaque opinion. And the citations are *motivation*, not a falsifiable basis
for the cutoff — which is itself the argument for keeping the threshold→verdict step in the
`Policy` seam, never in kernel mechanism.

### 4.3 JOURNAL-INTEGRITY — the soundness floor (build it first; it is a blessed candidate)

**What it exposes.** A verdict that the WAL being replayed is `SOUND` or `CORRUPT` (with an
`INDETERMINATE` middle if you prefer three states). [`85 §2`](85_extending-the-verifiable-surface.md)
already named journal-integrity an explicit candidate verb (flagged low-glamour) — this builds
the blessed candidate, it is not a novelty.

**Four-gate sort.** (1) YES — "the WAL is uncorrupted." (2) YES — `_CORRUPT` sentinels are a
mechanical read of the log itself. (3) YES. (4) YES — a 2–3 state closed enum. PASSES; it is
the *cheapest real verb* — a pure fold over `lane_journal.read_all`, which **already** preserves
a `{op:"_CORRUPT"}` sentinel for any non-trailing bad line, and `journal_delta` **already**
carries `saw_corrupt` (just unsurfaced). It is the ARIES *Analysis*-phase integrity read,
restated as a typed verdict.

**Why first.** Every later recovery flow trusts `replay()`, and `replay()` must not be trusted
on an unverified log. The soundness floor comes before the things that stand on it.

### 4.4 What is *not* a verb (the honest negatives)

- **RESTORE / REVERT** (perform the undo) — not a claim, an EFFECT (mutating git). HARD FAIL at
  the [`86 §1`](86_the-typed-verdict-surface.md) epistemic boundary, same reason `arbitrate` /
  `spawn` are cousins. It is a human emit-and-exit decisions action or a host/driver. The kernel
  proposes; it never runs (the `--force` / advisory-only litmus).
- **BISECT** — not a verdict; a SEARCH that *calls* a verdict per step (§3.1). Proposing a
  `dos bisect` verb would re-import machinery `git bisect run` already ships (the
  over-abstraction trap [`86 §4`](86_the-typed-verdict-surface.md) warns against).
- **CHECKPOINT** as a verdict — no; it is a recorded marker + a vocabulary op (§4.1).

---

## 5. Build order (deepest leverage first, every critique fix folded in)

- **Phase 0 — the recovery story that ships today, zero new code.** Document and pin the
  `git bisect run dos verify` / `dos scope` rot-localization recipe (§3.1), with the *correct*
  per-verb exit codes (verify 0/1; scope 0/5/6; liveness 0/3/4 — not a unified map). Highest
  value / lowest risk.
- **Phase 1 — the soundness floor.** Ship JOURNAL-INTEGRITY (§4.3): a pure fold counting
  `read_all`'s `_CORRUPT` sentinels into a closed enum, registered `reviewed=True` in the
  **existing** [`verdicts.py`](../src/dos/verdicts.py). Cheapest real verb; everything later
  trusts `replay`.
- **Phase 2 — mint the marker.** Add the `CHECKPOINT` lane-journal op (vocabulary) + a
  cli-helper that mints a checkpoint when a **configurable** verdict conjunction passes — with
  the `verify` leg required to stand on the diff-content rung (§4.1), recorded as a git
  note / `refs/meta/*` marker on the spine. JSON for agents, a chip for humans.
- **Phase 3 — the degradation fold (generalize last).** Build the neutrally-named REWORK verb
  (§4.2) mirroring `liveness`/`scope`, thresholds in a `dos.toml [<verb>]` `Policy` with
  provisional generic defaults + an `INSUFFICIENT_DATA` escape. Register only once it has ≥2
  instances behind it; wire through `verdict_cli.attach`.
- **Phase 4 — the human actuator + lineage (still advisory).** Emit a "rework detected" row into
  `decisions.collect_decisions` whose `next_steps` prints a proposed `git revert <range>` /
  `git checkout <checkpoint-sha>` and exits. Join via the spine for "who touched what"; flag
  kernel-damage radius via the **workspace-aware** `self_modify.existing_runtime_files(cfg.root)`,
  not the static set. *Prerequisite:* the `(loop_ts, lane) → run_id` correlation (§7) — and
  justify any "stamp `run_id` on every journal entry" change on *spine* merits, not as a
  recovery goal driving a kernel-spine schema change.
- **Phase 5 — bench proof (the honesty discipline).** Wire the REWORK and CHECKPOINT signals
  into FleetHorizon's `TrajectoryStep` the way [`86 §3`](86_the-typed-verdict-surface.md) wired
  scope/liveness, so the believed-vs-adjudicated A/B counts "recovered-from-degradation" as a
  measured dimension (gap → 0 as horizon → 1) on the *same simulated run* — no better worker,
  just more dimensions adjudicated.

---

## 6. Non-goals (the lines that keep the kernel a kernel)

1. **The kernel never restores, reverts, resets, or cuts a branch.** It mints markers and
   reports verdicts; the actuator is a human emit-and-exit action or a host/driver — the
   advisory-only floor ([`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) /
   [`90`](90_open-research-areas.md)) on the recovery axis.
2. **The kernel never judges code QUALITY or correctness.** Every degradation verb counts
   re-touch / revert / creep / refuse / spin — state that bytes moved or leases were refused,
   never that code is good or bad. A threshold that encodes "good code looks like X" has become
   a driver JUDGE (the distrust-state vs distrust-judgment line).
3. **No new state store.** A checkpoint is a marker pointing at a commit git already stores +
   a journal entry; recovery state is reconstructed by `lane_journal.replay` (a bounded fold).
   DOS does **not** capture conversation / memory / filesystem snapshots the way IDE
   checkpointers do — git + the WAL are the substrate.
4. **No automatic rollback on a bad verdict.** A failing `verify` / `SPINNING` / `SCOPE_CREEP`
   *raises a decision*; it does not trigger an undo. Auto-revert would couple the kernel to an
   effect and is exposed to the 2026 "semantic rollback attack" (re-execution after restore →
   duplicate side-effects).
5. **No cross-host recovery / distributed consensus.** The lane-journal is host-local by design;
   correlating journals across machines to find a bad decision is out of scope (the DLO non-goal).
6. **No bespoke `dos bisect` / `dos rollback` verb where composition suffices** — that would
   re-import machinery `git bisect run` / `git revert` already ship (the over-abstraction trap).

---

## 7. Open questions

- **The `(loop_ts, lane) → run_id` correlation gap** ([`journal_delta`](../src/dos/journal_delta.py)'s
  "THE HARD PROBLEM"): journal entries are keyed by lease identity, not `run_id`, so "reconstruct
  everything run R did, then walk it back" is not cleanly answerable. Stamp `run_id` on every
  entry (a spine change to justify on spine merits), or accept a time-window join (AMBIGUOUS when
  concurrent)?
- **Detection latency.** The kernel runs verdicts only at dispatch/CLI boundaries, so a bad slice
  may go unflagged for hours. Consult the degradation fold continuously (cost) or only at
  boundaries (latency)? The advisory-only model leans toward the latter; the agent-rewind product
  model assumes the former.
- **Checkpoint cadence + retention.** Mint on every passing commit, or only at lane-release /
  phase-ship? What prunes the git-note / `refs/meta/*` markers — does it reuse the journal's
  size-rotation? (IDE checkpointers persist ~30 days; DOS needs its own policy.)
- **The REWORK thresholds are a calibration open problem** (the [`90 §2`](90_open-research-areas.md)
  soft-threshold family): what counts actually separate the bands *generically*, without becoming
  host policy? The `Policy` seam makes them data, but the GENERIC defaults need a falsifiable basis
  — the Phase 5 bench is the intended evidence source. Until then, the verb should not claim its
  defaults are grounded.
- **ARIES UNDO is unbuilt.** `replay()` is the redo fold; DOS has no notion of rolling back a live
  lease's *effects* if a process crashed mid-decision. Is the kernel's job only to *mark* a lease
  revoked (a possible `OP_REVOKE` op), leaving the git/state undo to the human — i.e. is UNDO
  permanently a host concern?
- **The forgeable-floor interaction** (§4.1 requirement #2): a checkpoint trusts `verify`, but the
  no-plan grep rung is forgeable. Requiring the diff-content rung for the `verify` leg of a
  checkpoint is adopted as a hard requirement here — but it shifts work onto hardening that rung
  ([`85 §3.1`](85_extending-the-verifiable-surface.md)), which is itself only partly built.

---

## 8. What this note claims, and what it does not

- **Does claim:** recovery from slop is *composition over history the kernel already owns* (the
  WAL, the spine, the verdict ladder, the registry) plus exactly two new state-only verbs and one
  recorded marker; the checkpoint/restore-point split is the belief/effect (kernel/host) line on
  the time axis; the kernel may *mint a verified-good marker* and *report a measured-rework
  verdict* and *propose an undo*, but may never *restore*, *judge quality*, or *auto-act*.
- **Does not claim:** that the kernel should snapshot filesystems/conversations (those are IDE/
  driver concerns), that a degradation verdict measures code quality (it counts state, neutrally
  named), that the REWORK thresholds are grounded (they are provisional), or that any single
  cited product feature is load-bearing for the design (the architecture stands on the DOS code
  and a few durable mechanisms — ARIES WAL recovery, `git bisect run` with a deterministic
  oracle, git-meta/notes markers, snapshot-detect-restore as a category — not on whether a given
  CLI shipped a flag in a given month).

The meta-answer: **DOS already has the recovery substrate — a write-ahead log with a pure replay
fold, a lineage spine, and per-commit distrust verdicts. "Recovery" is naming a known-good marker,
reading the log's own soundness, folding the unforgeable signals into a neutral trend, and
*proposing* — never performing — the walk-back. The kernel's contribution stays what
[`84`](183_how-much-does-this-lean-on-git.md) named it: consult the most accountable fossil, report
which rung it stood on, and leave the acting to a human.**

---

## References

*The history surface the design composes (§1, §3):*
- [`src/dos/lane_journal.py`](../src/dos/lane_journal.py) — the WAL: `append`/`fsync`,
  `read_all` (preserves `_CORRUPT`), `replay` (the pure redo fold), the closed op vocabulary.
- [`src/dos/run_id.py`](../src/dos/run_id.py) — the lineage spine (`run_id`/`parent_id`/`root_id`,
  `ts_ms_of`, `run.json`).
- [`src/dos/git_delta.py`](../src/dos/git_delta.py) — the boundary-I/O range reader.
- [`src/dos/journal_delta.py`](../src/dos/journal_delta.py) — the pure journal fold (`saw_corrupt`),
  and the `(loop_ts, lane) → run_id` "HARD PROBLEM".
- [`src/dos/decisions.py`](../src/dos/decisions.py) — the read-only projection + emit-and-exit
  action bar (the human actuator surface).
- [`src/dos/self_modify.py`](../src/dos/self_modify.py) — `existing_runtime_files(workspace)`,
  the workspace-aware kernel-damage radius.

*The verb template, contract, and registry (§4):*
- [`src/dos/liveness.py`](../src/dos/liveness.py) — the pure-verdict shape REWORK mirrors.
- [`src/dos/scope.py`](../src/dos/scope.py) — the footprint verdict + `_tree` reuse pattern.
- [`src/dos/verdict.py`](../src/dos/verdict.py) — the `TypedVerdict` / `Classifier` contract +
  `conforms`.
- [`src/dos/verdicts.py`](../src/dos/verdicts.py) — the **shipped** open registry (`register`,
  `VerdictSpec(reviewed=…)`, seed-registered `liveness`+`scope`).
- [`src/dos/verdict_cli.py`](../src/dos/verdict_cli.py) — the generic dispatcher (`attach`/`run`);
  note it wires **only** `scope` today.

*The frame and the boundary (§2, §6):*
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md) — necessary-not-
  sufficient; the typed-verdict-with-provenance resolution.
- [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) — the four-gate
  test; the forgeable-floor rung; journal-integrity as a named candidate.
- [`86_the-typed-verdict-surface.md`](86_the-typed-verdict-surface.md) — the verdict contract +
  registry + "generalize last".
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md),
  [`90_open-research-areas.md`](90_open-research-areas.md) — expand by vocabulary; the advisory-only
  soundness floor.

*Industry art the design builds on (motivation, not load-bearing):*
- ARIES write-ahead-log recovery (Analysis-Redo-Undo, LSN, checkpoints) + event-sourcing with
  snapshotting — the theory the lane-journal already realizes.
- `git bisect run` with a deterministic oracle — the canonical "find the bad commit" composition.
- git-meta (`refs/meta/*`) / git notes / *Assisted-by* trailer / SLSA+in-toto attestations — the
  out-of-band, history-non-polluting marker format.
- Rubrik Agent Rewind (Aug 2025) / the agentic snapshot-detect-restore product category — the triad
  DOS splits along its belief/effect line; the 2026 semantic-rollback-attack line is the auto-revert
  non-goal's rationale.
- GitClear 2025 (churn 3.1%→5.7%, refactoring 24.1%→9.5%) / MSR-2026 hotspots (15 patterns,
  74% bot-driven) / CodeScene / DORA-2025 — the measured-degradation signals the REWORK verb folds,
  with thresholds left to policy.
