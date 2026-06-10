# docs/243 — The fleet-trajectory benchmark: turning our own corpus into the hard dataset the field doesn't have

> **Status:** design note (2026-06-08). Written from a direct measurement of this
> project's own Claude Code trajectory corpus (`benchmark/_probe_concurrency.py`)
> against the four-walls / witness-ladder framing
> ([[project-dos-the-four-walls-witness-runs-out]], docs/192/204) and the
> external out-of-loop benchmark survey
> ([[project-dos-other-benchmarks-for-out-of-loop-payoff]]). Numbers are from the
> probe, dated, and re-runnable — not memory.

## The one sentence

Every public agent benchmark scores **one agent, on one task, in one isolated
environment, against a witness the benchmark author hand-built** — which is
exactly the regime where DOS adds the *least*; the trajectory corpus this project
already generated is, by contrast, a **natively concurrent multi-session fleet
hammering one shared git tree**, which is the regime where DOS adds the *most*, and
so it is the hard benchmark the field is missing — we just have to label it.

## 1. What we actually have (measured, not assumed)

`~/.claude/projects/<project>/` holds the Claude Code session logs (`.jsonl`,
one record per turn/event) for every session that has touched this repo. As of
2026-06-08:

| Fact | Value | Source |
|---|---|---|
| Total session files | **718** | `_probe_concurrency.py` |
| Total size | **~1.0 GB** | `du -sh` |
| Sessions > 1 MB (substantial) | **123** | size bucket |
| "Real" dos-repo sessions (≥3 assistant turns, not a sidechain) | **285** | probe |
| **Peak concurrent sessions at one instant** | **19** | sweep-line over start/end |
| Sessions that temporally overlap ≥1 other | **280 / 285** | interval overlap |
| Corpus span | **2026-05-31 → 2026-06-08 (7 days)** | min/max timestamp |
| Total tool calls in substantial sessions | **26,409** | tool_use count |
| …of which mutations (`Edit`+`Write`) | **5,457** | tool dist |

Each record is richly structured. The fields that make this labelable as a
benchmark (confirmed by schema dump):

- `sessionId`, `uuid`, `parentUuid` — **causal chain** within and the identity
  across sessions.
- `gitBranch`, `cwd`, `timestamp` — **where and when**, so concurrency and
  shared-region contention are reconstructable.
- `isSidechain` — marks sub-agent (Task/Agent) work vs the main loop.
- `message.content[].type == "tool_use"` — the **act** (name + input), separable
  from the surrounding narration.
- `type == "system"` with `hookAdditionalContext`, `preventedContinuation`,
  `stopReason`, `toolUseID` — the **hook/PEP moments** (where a guard fired or
  could have).
- `permissionMode` / `mode` — the operator's trust posture at each step.

The single most important number is **19**. Nineteen agents were editing this one
repository at the same instant, and 280 of 285 substantial sessions overlapped at
least one sibling. **This is not an isolated-agent corpus that happens to be
large. It is a concurrent-fleet corpus**, which is a different *kind* of object
from anything in the public benchmark literature.

## 2. How existing benchmarks are oversimplified

The survey memory ([[project-dos-other-benchmarks-for-out-of-loop-payoff]])
already inventories the strongest external candidates — Agent-Diff,
WebArena-Verified, OSWorld, BIRD/Spider, τ²-bench, TheAgentCompany. They are good
benchmarks. But they share a set of simplifying assumptions, and **each
assumption is precisely a place DOS's value lives**. The pattern: a benchmark is
built to make grading *tractable*, and tractability is bought by removing the
exact conditions that make a trust substrate necessary.

The four walls (docs/204) say DOS's value shows up only when four conditions
hold. Read the same four conditions as a critique of benchmarks: a benchmark is
"oversimplified, from DOS's standpoint" exactly insofar as it *designs the
condition away*.

| Simplifying assumption (what makes the benchmark tractable) | DOS value it removes | Wall (docs/204) | This corpus instead |
|---|---|---|---|
| **One agent per task.** The unit of evaluation is a solo run. | Plurality — overwrite-prevention, lease arbitration, the whole `arbitrate()` kernel — is **structurally 0 at fleet=1** ([[project-dos-wall-fleet-of-one]]). | §1 fleet-of-one | **19-way concurrency**; 280/285 overlap. The contention is *native*, not injected. |
| **Isolated, reset environment.** Each task gets a clean container; no other writer exists. | Shared-state serialization, the region-lock ([[project-dos-lane-is-a-region-lock]]), TOCTOU/CAS hazards — nothing to serialize in a sandbox-of-one. | §1 | One **shared git tree**, 5,457 mutations, branches worked in parallel — last-writer-wins is a *live* hazard here. |
| **A clean, env-enforced witness the author built.** Pass/fail comes from a unit test, a backend-state checker, a gold diff. | DOS *copies* good graders, it doesn't beat them; where a sound witness already exists, DOS adds little (docs/169 "best graders = `verify()` in the wild"). The value is where the witness is **W2-presence, not W3-goal** ([[project-dos-world-state-witness-ladder]]) — ~38% of goals reach **no** sound witness. | §3 presence-not-goal | git is a **W2/partial** witness *by construction* here (the same collapse docs/192 found inside DOS) — so the corpus exercises the regime where the witness genuinely runs out. |
| **Failure is visible in the trace.** The benchmark is built around detectable failure modes (a wrong SQL row, a 500). | A *strong* model hides its failure in world-state, not in env-authored bytes — frontier detectors fire **0/321** ([[project-dos-wall-frontier-detector-silence]]). | §2 frontier silence | Real frontier-model sessions (Opus/Sonnet), real silent failures — the failure distribution is **natural**, not curated to be catchable. |
| **Detection is the deliverable.** Score = did you flag the bad run. Acting on it is out of scope. | The hard, unsolved half is DETECT→**FIX** in-loop; the only regime-independent fix is the *negative* one (give up correctly) ([[project-dos-wall-detect-not-fix]]). | §4 detect-not-fix | The corpus contains the **downstream consequence** of each (un)intervention — a later session inheriting a forged "shipped" — so a fix's payoff is *observable*, not hypothetical. |
| **The claim is fused to the work.** There is no separable self-report to distrust; the artifact *is* the answer. | DOS's whole invariant is byte-author ≠ judged agent ([[project-dos-what-is-truth-throughline]]); it needs a **forgeable claim** to sit beside an **unforgeable witness**. Agent-Diff's one weakness is exactly this — code, not a separable NL claim (survey, property #1). | (cross-cutting) | Every session has **explicit narration** ("I verified X", "this is done") *and* a git ground truth — the claim/witness split is **native and abundant**. |

Put plainly: the public benchmarks are oversimplified along **six axes at once**
— solo, isolated, clean-witness, catchable-failure, detect-only, fused-claim —
and DOS's distinctive value is defined by the *complement* of all six. No single
external benchmark relaxes more than one or two. **This corpus relaxes all six
simultaneously, because it was generated by a real fleet doing real work, not
designed to be gradeable.**

That is the headline finding: **the thing that makes a corpus a good DOS
benchmark — un-designed concurrent reality with a partial witness — is the same
thing that makes it a *bad* conventional benchmark (hard to score cleanly). The
field avoids this regime because it is inconvenient; DOS exists *for* this
regime.** We have a GB of it sitting on disk.

## 3. The benchmark design — five tracks, hardest-witness-first

The discipline is the kernel's own: **only label what a byte the agent did not
author can witness; abstain elsewhere; report the rung that answered.** Each track
below is a labeling function over the corpus whose *gold* is authored by something
other than the session being judged. Ordered by witness soundness (sound → JUDGE
→ human), mirroring docs/192's ladder.

### Track A — Concurrent over-write detection (the fleet-of-one wall, inverted)

**Question:** when two sessions held overlapping file regions in the same time
window, did one silently clobber the other's uncommitted work?

**Why it's hard + novel:** *no public benchmark can pose this question* — they
have no second writer. Here it is the dominant condition (280/285 overlap).

**Gold (unforgeable):** the git history + working-tree-snapshot records
(`file-history-snapshot`) + the interval overlap. A clobber is two sessions whose
edited path-sets intersect, with the later edit not built on the earlier (no
common ancestor in the snapshot chain). The agent authors none of: the timestamps,
the snapshot hashes, the path-sets.

**The benchmark instance:** `(session_i, session_j, region, t_window) →
{CLOBBER, DISJOINT, SERIALIZED}`. DOS's `arbitrate()` + `lane_overlap` is scored
on whether it *would have refused* the colliding lease — this is the docs/233
coordination payoff (`J=6/8 off DB-hash` in the synthetic case) but on a **real**
collision distribution instead of a constructed one.

### Track B — Mid-trajectory over-claim (the claim/witness split, in-trace)

**Question:** at the moment a session asserted "I verified / this is done / tests
pass," did a byte the session did not author agree?

**Why it's hard + novel:** existing benchmarks grade the *final* state. They never
ask whether the agent's *running narration* was honest at the step it was emitted
— the signal a live out-of-loop consumer (a peer agent, a reward labeler) actually
sees. This is the docs/228/232 write-admission payoff, but the claims here are
**natural and abundant** (every session narrates), not a curated over-claim slice
that evaporates under a capable policy (the Run-A J=0 wall).

**Gold:** for a commit claim → `commit-audit` (subject vs its own diff; drift
machinery already shipped, measured 0% on the curated HEAD~30 range but that is
the *honest* tail — the hard instances are mid-session, pre-commit). For a "tests
pass" claim → the *next* tool result that ran the tests. For a "shipped" claim →
`dos verify` git-ancestry at that SHA. The witness is always downstream bytes the
claimant had not yet authored when it made the claim.

**The benchmark instance:** `(session, turn, claim_span) → {WITNESSED_TRUE,
WITNESSED_FALSE, UNWITNESSABLE}`. The `UNWITNESSABLE` bin is the deliverable the
field never reports — docs/192's ~38%.

### Track C — Recovery-vs-collapse after a detected error (detect→fix, with the confound named)

**Question:** after a terminal error / failed tool call, did the session recover,
give up correctly, or thrash?

**Why it's hard + novel:** the detect→fix wall (§4) is unsolved, and docs/236
found that **self-recovery is a confound** (believe-B self-recovers 3/5, so ΔB≈0
at the easy hop). A real corpus lets us *measure the base recovery rate* instead
of assuming it — the feasible-tail `P(never recover)=0.44` (docs/236 §5 H1) came
from exactly this kind of survival analysis. The label is the *trajectory shape*,
not a single verdict.

**Gold:** the subsequent git delta + tool-result stream (`liveness` /
`productivity` evidence: was the run ADVANCING or SPINNING?). A "give up" is
unforgeable when the session ends with no further mutation and an explicit stop;
a "thrash" is a repeated identical failing call (the read-loop / phantom-key
signatures, [[project-dos-phantom-key-detector]]).

**The benchmark instance:** `(session, error_event) → {RECOVERED, GAVE_UP_CORRECTLY,
THRASHED, GAVE_UP_WRONGLY}`. Scoring DOS = does `liveness`/`breaker`/`productivity`
call the shape *before* the human would. This is the only track where the
positive-fix value is real, so it is also where DOS's honest ceiling shows.

### Track D — The peer-B handoff (causal, cross-session)

**Question:** when session B inherited a claim from session A's narration ("docs/NN
is shipped") and acted on it, was A's claim true — and did B's trust of it cause a
divergent outcome?

**Why it's hard + novel:** this is the docs/229/235 ΔB experiment, and the corpus
is *full of natural instances of it* — a new session reading the prior session's
summary off a forgeable `> **Status:**` sentence or commit subject. External
benchmarks have no notion of a *second session inheriting the first's
self-report*, because they have no second session. The causal A/B (does an
unforgeable witness at the handoff change B's outcome?) is the whole point of the
out-of-loop value, and here it is *observable in the wild* rather than constructed.

**Gold:** the `parentUuid`/`sessionId` lineage joins A→B; git ancestry says
whether A's claim was true; B's subsequent diff says what B did. The handoff
witness (`dos verify` at the boundary) is the treatment.

### Track E — Token-waste / loop pathology (the cheap, already-tooled track)

**Question:** which sessions burned tokens on read-loops, shell-polls, glob-storms?

**Why it's here:** it is the *easiest* track (the `trajectory-audit` skill already
sweeps for exactly these — read-loops, shell-poll, keepalive-poll, cache-miss,
glob-storms) and it grounds the corpus's *cost* axis. Not the headline (it doesn't
exercise the trust substrate), but it makes the corpus a complete benchmark: a
fleet's *efficiency* alongside its *integrity*. The `tool_stream`/`productivity`
verdicts are scored against the audited ground truth (docs/171 already PROVED
`tool_stream` catches a real audited 22×→STALLED read-loop).

## 4. Why this is worth doing (and the honest caveats)

**The payoff.** Every recent value experiment (docs/228/232/233/235/236) had to
*construct* its hard instance — a synthetic collision, a curated over-claim slice,
a hand-built peer-B — and then fight the objection that the construction
manufactured the result (Run-A J=0; the recovery confound; the infeasibility
denominator, [[project-dos-feasibility-witness-and-category-error]]). **A natural
corpus dissolves that objection class**: the concurrency is real (19-way), the
over-claims are real (natural narration), the recoveries are real (measured base
rate), the handoffs are real (lineage in the data). It is the corpus the external
survey is hunting for — and it is the *only* candidate that is natively
concurrent, which is DOS's first and most structural wall.

**It is the four-walls memo, made falsifiable.** docs/204 is currently an
*argument* that DOS's value lives in a regime benchmarks avoid. This benchmark
*tests* that argument: if DOS's verdicts don't lift any track here, the four-walls
thesis is wrong. That is the kernel discipline applied to our own strategy — a
witness we did not author (the corpus) judging a claim we made (DOS matters in the
concurrent-fleet regime).

**The honest caveats (do not skip these):**

1. **Self-witnessing risk — the corpus is partly DOS-on-DOS.** Many sessions were
   *building DOS*, some while running the kernel on themselves. A track must not
   grade a session against a verdict that same session produced. The fix is the
   same byte-author≠judge rule: gold for session S must come from git / a *later*
   session / a *different* session — never S's own emitted verdict. Track this as a
   hard exclusion in the labeler, pinned by a test.
2. **W2-not-W3 ceiling is inherited.** git witnesses *changed*, not *right*
   (docs/192). So Tracks A/B/D top out at presence-soundness; goal-correctness on
   this repo bottoms out at HUMAN (the ~38%). That is a *feature* — it means the
   benchmark honestly contains the wall — but the leaderboard must label each
   instance's witness rung, never silently score a W2 instance as if it were W3.
3. **Single-repo, single-operator, 7-day window.** It is one team's fleet, not a
   population. Generalization claims need a second corpus (another DOS workspace,
   or a consenting third party). State the n and the scope on every number (the
   [[feedback-date-observations-for-staleness]] discipline).
4. **Privacy / provenance.** These are real session logs with real prompts. Any
   release is a redaction + consent problem, not a `cp`. Likely the *labels +
   derived features* ship, not the raw narration — the same split the survey notes
   for releasing a benchmark.
5. **Distribution skew toward honesty.** This team commits honestly (commit-audit
   drift 0% on the curated range). The *hard* instances are mid-session and
   pre-commit, and they are rarer than a constructed slice — the benchmark's value
   density is lower than a designed adversarial set. That is the price of being
   natural; report the base rate, don't inflate it.

## 5. The smallest first step

Don't build all five tracks. Build **Track A** (concurrent over-write detection)
first, because it is the one *no other benchmark can pose* and the one that
exercises DOS's most structural wall (fleet-of-one). Concretely:

1. Extend `_probe_concurrency.py` into a labeler that, for each overlapping
   session pair, extracts the edited path-sets (from `tool_use` Edit/Write inputs)
   and the snapshot lineage, and emits `(i, j, region, t) → {CLOBBER, DISJOINT,
   SERIALIZED}` with git as gold.
2. Score `dos arbitrate` / `lane_overlap.overlap_verdict` on whether it refuses
   the colliding lease — the docs/233 coordination metric on a **real** collision
   distribution.
3. Report: collisions found, fraction DOS would have prevented, fraction that
   *actually caused* a lost edit (the payoff, not the rate — the
   [[project-dos-intervention-bench-must-be-live-reactive]] law: rate ≠ payoff).

If Track A shows DOS prevents real, consequential clobbers in this corpus, the
four-walls §1 claim is no longer an argument — it is a measured number off bytes
we did not author. That is the whole thesis of the project, turned on the project
itself.

**Dovetail with docs/244.** docs/244 (the fleet-scale proof plan) marries the
`fleet_horizon` harness to live agents + a real DB-hash witness to attack the
*compounding* objection (a rate is not a cascade). It currently feeds that harness
a **simulated** collision/witness distribution. Track A here produces the missing
piece: a **real** collision distribution mined from this corpus. So docs/243 is the
natural *input source* for docs/244's F-series — this note supplies the natural
data; that note supplies the scaling argument. Keep them joined, not merged: they
answer different questions (is the corpus a benchmark? vs. does the payoff
compound?).

## 6. Built — all five tracks + the dovetail (2026-06-08)

> **Status:** all five labeling tracks and the docs/244 dovetail are IMPLEMENTED,
> RUN, and pinned, in `benchmark/fleet_trajectory/` (`corpus.py` loader + `track_a`
> … `track_e` + `test_fleet_trajectory.py`, 28 deterministic tests). Numbers below
> are from the frozen snapshot `--before 2026-06-08T17:00Z`, self-witness-excluded
> (caveat #1), n≈237–287 sessions. The corpus is NON-STATIONARY — it grew from 285
> sessions / peak-19 (the design measurement) to 287 / peak-21 *during the build*,
> because the analyzing sessions joined the fleet they were analyzing — so `--before`
> freezes a reproducible snapshot and the count moves between runs by design.

| Track | What it measured | Headline (frozen) |
|---|---|---|
| **A** concurrent over-write | classify every overlapping session pair CLOBBER/SERIALIZED/DISJOINT off CC edit-windows + git serialization; score `overlap_verdict` | 1157 concurrent editing pairs; **946 disjoint → kernel ADMITS 100%** (specificity 1.0, zero false-refuse), **211 share a region → refuses 100%** (sensitivity 1.0); **50 consequential CLOBBERs** (interleaved, no commit between) all refused |
| **B** mid-trajectory over-claim | bin each agentive claim WITNESSED_TRUE/FALSE/UNWITNESSABLE off a downstream byte | 1162 agentive claims (after killing 2939 PROSE phantoms); **713 UNWITNESSABLE (61%)** — the bare-assertion bin no benchmark reports; **exactly 1 sound WITNESSED_FALSE** ("519 tests pass" → next test FAILED). A sound 1 beats an inflated 19 |
| **C** recovery-vs-collapse | label each error RECOVERED/THRASHED/GAVE_UP; score `productivity`+`breaker` | **base recovery rate 98.45%** (the docs/236 confound, MEASURED) — only 2 thrash + 12 give-ups in 903 errors; **breaker (max-consec-3) OPENS on 24 runs that ALL recovered** (2.7% false-escalation) — the precision cost of in-loop intervention, off real bytes |
| **D** peer-B handoff | join A-claims-docs/NN → later-B-edits-docs/NN; git ancestry is the witness | 47 docs/NN claims; **12 real cross-session handoffs, all WITNESSED_TRUE**; one docs/229 near-miss with a **7.5-second forgeable window** — the honesty-skew caveat quantified |
| **E** token-waste | `tool_stream.classify_stream` as a sliding retrospective audit over result digests | kernel **agrees with 100% of read-loop signatures** (the docs/171 22×→STALLED proof at scale) AND surfaces real no-progress runs they miss (8× identical idempotent Edits) |

**The four-walls memo is now falsifiable and not falsified on §1.** Track A turned the
fleet-of-one wall from an argument into a measured number: the kernel admits 100% of
safe concurrency and refuses 100% of real collisions, including 50 consequential
clobbers, off bytes (CC timestamps, git ancestry) the agents did not author. The
honest counterweight is Tracks B/C/D: on a DISCIPLINED corpus the over-claims are
rare (1 sound), recovery is near-total (98%), and handoffs are witness-backed (12/12)
— the honesty-skew caveat (§4.5) is real, and the value DENSITY is lower than a
constructed adversarial set, exactly as predicted. The benchmark honestly contains
the wall.

**Two methodological laws fell out** (now memory `project-dos-243-track-witness-soundness`):
(1) a tool's EXIT CODE is an unsound witness — it scores shell artifacts (a truncating
pipe, a malformed `git commit`, a permission denial) as over-claims; read the RESULT
TEXT or abstain. (2) a loose word-match mines PROSE — require agentive completed-action
framing or harvest phantom claims. Both are the project's own byte-author≠judge
discipline, turned on the benchmark itself.

**The dovetail is built** (`benchmark/fleet_horizon/real_collisions_from_track_a.py`):
Track A's measured collision distribution now feeds the docs/244/245 fleet-scale
harness, replacing the simulated `workload.generate` `shared_ratio=0.25` with the
**measured 0.188** (18.8% of concurrent pairs share a region) + a 0.230 clobber
fraction. Projected to the corpus's observed peak (fleet=20): ~36 colliding pairs,
~8 consequential clobbers, every one serializable (sensitivity 1.0) — a RATE
projection, the honest predecessor to FleetHorizon's payoff A/B. The same fix
un-broke the sibling `measure_real_collisions.py` (it had resolved a `<project>`
placeholder and reported 0 collisions; it now finds 351 cross-session collisions
across the operator's repos, `prefixes_collide` agreeing with the arbiter).

---

*Provenance: corpus measurement in `benchmark/_probe_concurrency.py` (scratch,
gitignored-class); the built benchmark in `benchmark/fleet_trajectory/`. Framing from
docs/192 (witness ladder), docs/204 (four walls), docs/228/232/233/235/236 (the
out-of-loop payoff arc), and the external survey memory. Companion to — not a
replacement for — the external benchmark registry in
`benchmark/_experiments/out_of_loop_registry.md`.*
