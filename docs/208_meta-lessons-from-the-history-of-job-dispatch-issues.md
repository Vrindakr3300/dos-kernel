# 208 — Meta-lessons from the history of job-dispatch issues

> **Status:** RETROSPECTIVE (a synthesis note, not a plan). Written 2026-06-07.
> It introduces no mechanism — it reads the whole build journal back and names the
> recurring shapes of how agent/job dispatch goes wrong, each grounded in a doc, a
> commit, a test, or a `file:line`. Produced by a 7-modality corpus sweep →
> synthesis → adversarial grounding pass (`wf_0cd59739-e9c`); every lesson below
> was re-checked against live code, and the grounding pass corrected several stale
> citations (folded in). Companion to [`204`](204_the-four-walls-where-verification-runs-out.md)
> (where the witness runs out) and [`138`](138_what-is-truth-the-throughline.md)
> (what "truth" means here).

## The one root cause everything reduces to

> **The byte-author of the witness must not be the judged agent.**

An agent's "all work completed" is the cheapest possible lie, and it is
*grammatically indistinguishable from an honest flake*. So a verdict may only be
moved toward belief by bytes the judged agent did not author: git ancestry, an
environment-authored tool result, an OS exit code, a third-party receipt, another
effort's collision. **Every syscall is this one axiom re-applied to a different
surface** — `verify()` to finished claims, `liveness`/`tool_stream` to in-flight
progress, `resume_evidence` to recovery points, `believe_under_floor` to telemetry
— and **every "wall" is a place where non-agent-authored evidence runs out**
([`204 §0`](204_the-four-walls-where-verification-runs-out.md),
[`138`](138_what-is-truth-the-throughline.md),
[`141`](141_byte-inequality-and-the-derivative-problem.md)).

The deepest, most surprising consequence: this invariant does not only bound what
the kernel can **verify** — it bounds what it can **fix** (Lesson 2).

A note on reading this: the lessons are ranked by how load-bearing they are, not by
chronology. Each carries *why it matters* (the cost of ignoring it), *instances*
(the concrete incidents), and *how DOS encodes it* (baked into the kernel vs. left
as a discipline) — because a lesson that is only a discipline can still be violated.

---

## 1. Distrust the byte-author, not the words

A verdict may only be moved toward belief by bytes the judged agent did not author.
The kernel is one machine for enforcing this.

- **Why it matters.** "Done" with no commit is grammatically identical to a genuine
  flake; both bank a false "done" that downstream gates compound. Read the narration
  instead of the artifact and a fleet silently accumulates lies until an audit (or
  production) finds the rot. The same rule bounds the system *honestly*: where no
  non-agent-authored witness exists, the kernel must **abstain**, not guess.
- **Instances.**
  - `verify()` reads git ancestry / file footprint, never the "done" line — the
    cheap lie and the silent flake collapse to the same `NOT_SHIPPED`
    ([`108 §1+§2.2`](108_the-cheap-lie-and-the-narration-taxonomy.md); `src/dos/oracle.py`).
  - `believe_under_floor` grants belief **only** when a non-forgeable source
    (`OS_RECORDED`/`THIRD_PARTY`) attests; an `AGENT_AUTHORED` witness is
    structurally incapable of moving the verdict (`src/dos/evidence.py` — the
    non-forgeable branch sets `believe=True`; agent-authored attestations are
    recorded but filtered out of the decision).
  - A forged `--allow-empty` `STEP_VERIFIED` is re-adjudicated at *read* time
    against git ancestry + non-empty footprint + region overlap, never trusted from
    the agent-written ledger's `via` field
    (`src/dos/resume_evidence.py`; `test_intent_ledger.py::test_forged_step_verified_does_not_count_*`).
  - `tool_stream` judges the env-authored `result_digest` (the gym MCP server
    authored those bytes), never an agent-authored satisfaction predicate —
    `REPEATING` is provenance-of-repeated-output, not "is the agent succeeding?"
    (`src/dos/tool_stream.py`; [`145`](145_the-loop-economics-axis-and-the-stall-reader.md)).
- **How DOS encodes it.** **Baked, not a discipline.** The accountability tag
  (`AGENT_AUTHORED`/`OS_RECORDED`/`THIRD_PARTY`) is *data fixed by the source*, so a
  buggy or hostile source can only **withhold** an attestation, never **manufacture**
  one — the dual of the judge seam's fail-to-`ABSTAIN` and the overlap seam's
  conjunctive floor.

## 2. Detection and remediation are orthogonal — and every *positive* fix washes to net-negative by structure; only *withholding* survives

This is the hardest-won, most counter-intuitive result in the whole record, and it
reverses the obvious "detect → fix" instinct.

- **Why it matters.** A sound detector that fires correctly can still have *every*
  actuation be wrong or harmful. A positive (steering) intervention must change the
  trajectory — which means authoring bytes into the loop — which perturbs runs that
  were already on track. A negative intervention (withholding spend) authors nothing,
  so it inherits detection's groundedness.
- **Instances.**
  - The byte-clean `schema_refresh` cure **ran live** (176 runs): converted **+2**
    where aimed, but was **net −5** because the *fire itself* perturbed
    baseline-passing runs (**−7**, sign-p=0.016); all 9 flips were cure-caused. The
    harm is the intervention's *existence in the loop*, not its content
    ([`205 §6.2`](205_growing-the-fix-story-the-curable-conversion-arm.md), `0cac947`; wired live by `d89a8ee`+`29fd70c`).
  - Rewind/subtract **refuted** on live A/B: 44.9% vs none 49.2%, fired-run flip net
    **−3**; 18 rewinds, **0/4** success, re-thrashing the same invented id
    ([`172`](172_the-rewindable-fix-loop-experiment.md), `805822d`).
  - WARN's celebrated **+6.2pp was injection-only**; re-scored on the **natural**
    stream it is **+0.20pp flat**, with task success trending *down* 16.7%→10.0%
    ([`202 §1`](202_intervention-ladder-refresh-natural-regime.md), `6648baa`).
  - The lone survivor — **give-up-correctly**: halts **0 winners** at K≥3 across two
    benchmarks (EnterpriseOps 45 winners / 0 FA; Toolathlon 1,634 winners / 0 FA),
    ~13% token save, *because withholding spend authors nothing*
    ([`201 §4c`](201_the-full-corpus-rescore-and-the-give-up-correctly-arm.md), `e8083f3`/`f9d282f`; `benchmark/enterpriseops/giveup_arm.py`).
- **How DOS encodes it.** As the **PDP-not-PEP / advisory-only** posture (Lesson 10):
  the kernel reports a typed verdict and PROPOSES, never acts. The one
  structurally-safe actuator (give-up / early-halt) ships as an advisory floor in a
  benchmark arm, needing no kernel change. Positive cures remain a discipline gated
  by **pre-registered kill conditions** (d≥6, n≥30, witness-gated curable slice,
  additive-only), not baked in.

> ⚠ **Open question (do not over-read Lesson 2).** "Give-up is the only survivor" was
> measured against **agent-side** consumers only. The out-of-loop half-plane —
> routing the verdict to a *gate*, a *commons*, or a *training label* instead of back
> into the agent's own loop — is **unmeasured, not refuted**
> ([`206`](206_proving-the-out-of-loop-verdict-the-frontier-lab-rigor-program.md), `880fd5f`).
> The perturbation harm is specific to authoring bytes *into the loop under judgement*.

## 3. Capability redistributes failure down the witness ladder; it does not remove it

Stronger models fail more *competently* — no loop, no give-up, no error envelope — so
failure migrates from trajectory-legible cells to world-state cells a byte-clean
trajectory reader cannot reach by design.

- **Why it matters.** Mis-reading frontier silence as "detection is solved" leads to
  declaring victory; the temptation to "read the narration harder" violates Lesson 1
  (the satisfaction-predicate trap). It also kills the "just wait for a better model"
  hope: the four walls are not refutable by more capability.
- **Instances.**
  - In-trace detectors sweet-spot at gemini-2.5-pro (**+12pp**, 100% precision) then
    fire **0/321** on gemini-3-pro; frontier failures populate `CLAIM_SUCCESS×WROTE`
    (95, 47%) and `ABANDONED×WROTE` (52, 26%) — loud in world-state, silent in
    trajectory ([`177`](177_the-frontier-silent-failure-and-why-detection-is-not-solved.md)).
  - `verify()`'s file-path rung is **W2-PRESENCE** (witnesses *a file changed*,
    git-log-only, never content-diff) not **W3-GOAL** (*it is right*); ~38% of
    frontier goals reach **no sound witness**
    ([`192`](192_the-world-state-witness-ladder-and-the-w2-w3-gap.md); `phase_shipped.py` git-log rung).
  - The four walls are ordered cheap→fundamental and all reduce to one cause: DOS is
    bounded by what it can witness non-agent-authored; capability redistributes,
    never removes (re-run live, `--raw-digest` byte-identical 0/321,
    [`204 §0`](204_the-four-walls-where-verification-runs-out.md)).
- **How DOS encodes it.** As **scope honesty**: each detector is correctly scoped to
  the legible failure class and returns **0** (not a fabricated verdict) outside it,
  pinned by the fleet-of-one structural-zero test pattern. The frontier cell is
  explicitly punted to the *result-state* witness (`effect_witness`, `verify-result`)
  and to JUDGE/HUMAN — never faked.

## 4. Irreversible effects must be PREVENTED at the pre-effect boundary, not DETECTED post-hoc

You cannot un-clobber an atomic commit. For shared state under concurrency that means
a binding admission gate keyed on **region** (a leased range-lock), and a stale-lock
steal must be a value-keyed **compare-and-swap**, never a bare TOCTOU
unlink-and-recreate.

- **Why it matters.** A collision detected after both agents committed is unfixable.
  A non-atomic "observe orphan → unlink → recreate" lets two concurrent stealers both
  win, both read a stale pre-other-admission world, and both ACQUIRE colliding lanes —
  the worst-class double-admit. The cost of a *missed* prevention is irreversible; the
  cost of an *over-strict* prevention is a cheap retry.
- **Instances.**
  - `lane_lease._Mutex` stole stale locks with bare `unlink()`+recreate — two
    concurrent stealers could both win and double-admit; fixed by routing the steal
    through the shared value-keyed CAS (`cd86e53`;
    `tests/test_lane_lease_mutex.py` two-stealer regression).
  - `dos arbitrate` CLI defaulted `--leases` to `[]` so it arbitrated against an
    **empty world** and re-granted a durably-held lane — the *pure* arbiter was
    correct, the *boundary* read the wrong state; fixed by loading the live WAL set
    (`b3befa0`).
  - **The live proof — the git-index-race incident (`f14cde1`).** Concurrent loops on
    *this* repo were `git commit`-ing into the shared `.git` index; one loop's staged
    files (the C4 enforcement-journal work) got absorbed into a *sibling* loop's commit
    (`809e313`) under the wrong subject. The note's own words: *"the exact
    cross-process index hazard DOS's lane arbitration exists to prevent — a live
    demonstration of the problem on the repo itself."* (The repo wasn't running its own
    lane arbitration over the `.git` region.)
- **How DOS encodes it.** **Baked.** A lane is a leased region-lock adjudicated by the
  PURE arbiter (state-in / decision-out, no I/O); the `lane_journal` is an append-only
  WAL where every ACQUIRE/RELEASE is logged *before* believed; the steal goes through
  one shared value-keyed CAS module. Pinned by `test_arbiter.py`,
  `test_lane_lease_mutex.py`. (The *working* corollary is the
  [commit-with-a-pathspec discipline](#) — never `git add -A` on a shared tree, which
  is the human-grain version of the same index hazard.)

## 5. On high-base-rate detection, recall is a broken scoreboard — and the same reflexive discipline applies to prose

Score by **lift** (precision − base rate) plus a first-class **false-alarm ceiling**,
with an **always-fail / always-refuse control**.

- **Why it matters.** On a 76.2%-fail benchmark, "always-fail" posts 100% recall and
  ranks first. Recall confuses *how often you speak* with *whether you should be
  believed when you do*. A team optimizing recall ships the worthless control. The same
  trap at the docs layer: an unhedged "proven" on an N=1 corpus silently misleads the
  next reader — the kernel's evidence-carries-provenance rule applied reflexively to
  the writing.
- **Instances.**
  - Naive-loose posts **+4.9pp** lift at **25.6%** false-alarm and "beats"
    `terminal_error` (**+18.8pp** lift at **0.2%** false-alarm) *only on recall*;
    defaults now mandate the always-fail control + lift + a false-alarm ceiling
    ([`159 §2–3,§5`](159_naive-baselines-and-what-a-detector-default-should-be.md)).
  - `claims_lint` (advisory, exit 0, edits nothing) flags unhedged proof words +
    marketing superlatives on empirical claims — the byte-author-cannot-self-certify
    rule applied to prose (`4fe5c57`; CONTRIBUTING.md "Claims discipline").
  - A Table 8 token column was per-arm but **mislabeled pooled** (`giveup_arm.py`
    *prints* per-arm; the caption said pooled) — copying the printout overstated 13.0%
    vs the real pooled 11.4% @K=3 (`fd1f1f0`).
  - **Date-stamp every observation** as the cheapest staleness witness — without it a
    doc's prose silently reads as current after it has rotted.
- **How DOS encodes it.** Partly baked, partly discipline. Detector defaults (control +
  lift + ceiling) are documented norms. The prose discipline ships as an **advisory**
  tool (`claims_lint`, PDP-only, never blocks) — deliberately the same advisory-floor
  posture as the kernel.

## 6. Instrument BOTH sides of a paired decision, and join honestly

When the only available join key is not 1:1, report **AMBIGUOUS plus the candidate
set** rather than fabricating a name. Asymmetric wiring (one side stamped, the other
not) silently zeroes the join; widening a window to force a match is the cheap-lie at
the audit layer.

- **Why it matters.** The flagship audit — *"the agent burned tokens while the kernel
  refused its lane"* — could never fire on real data because `REFUSE`/`HALT` carried
  `run_id` but `ACQUIRE` did not. The join measured exactly **0** join-ready ACQUIREs;
  the *consumer* was fully built — only the *producer* was missing. Promoting an
  ambiguous time-overlap to a named triple is the same self-certifying lie the kernel
  exists to refuse.
- **Instances.**
  - `acquire_entry` had no `run_id` parameter while `refuse_entry`/`halt_entry` did →
    `ACQUIRE` entries with BOTH `loop_ts` AND `lease.run_id` = **0**
    ([`118 §measured-3`](118_the-fleet-postmortem-and-the-attribution-join.md); producer fix planned in [`139`](139_phase1-wire-run-id-onto-the-acquire.md)).
  - `AMBIGUOUS_JOIN` *by design*: when one session window overlaps multiple leases,
    the audit checks 1:1 and reports `AMBIGUOUS_JOIN` + candidates rather than guessing
    — no fabricated key, no widened slack (`scripts/trajectory_audit.py`).
  - The durable deeper fix (designed, not yet lifted into the WAL): make the
    normalized-tree-prefix **region-digest** the lease identity, so unnamed ad-hoc
    claims stay attributable ([`119 §3`](119_the-claim-and-the-tail-wagging-lane.md)).
- **How DOS encodes it.** Partly baked: the kernel *receiver* was ready (`acquire_entry`
  accepts `run_id`, `replay` reconstructs it, readers read it back) — the gap was
  *producer* wiring, with a producer-side assertion as the exit gate. `AMBIGUOUS_JOIN`
  is implemented honesty in the audit; the region-digest identity is designed.

## 7. Occupancy is a one-sided lower bound, never confirmation

file-exists, schema-validates, exit-code-0, mtime-fresh all prove *"at least one byte
occupies the slot"* — never that the content is correct, current, or even present.

- **Why it matters.** The most insidious failures don't error — they return **green
  with an empty frame**: telemetry that collected no metrics but validated its schema
  and exited 0; a span collection that returns 0 frames; a verdict cache keyed on a
  stale digest never recomputed. If "the structure exists" reads as "the work
  happened," coverage is silently undercounted and decisions ride on absent data that
  *looks* present.
- **Instances.**
  - Telemetry shows `available_layers {DGX2: []}` / "No metrics snapshots collected"
    yet schema-valid and exit 0 — every archived cache verdict lands `UNWITNESSED`
    because the source is null (occupancy=true, belief=false)
    ([`156`](156_grounded-rag-adoption-and-the-claim-ledger-seam.md) — telemetry-as-self-report; was drafted as docs/187 before re-indexing).
  - occupancy ≠ flow: file-exists / mtime / JSON-schema / stdout-grep are all
    non-starters for grounding ([`167 §2`](167_the-eval-and-naive-verifier-comparison.md); [`141`](141_byte-inequality-and-the-derivative-problem.md)).
  - **The working-discipline twin:** a workflow whose `agent({schema})` calls fail en
    masse returns `null`, gets filtered, and reads as **clean coverage** — reconcile
    `failed = unique − (real + misattr + unver + irrel)` so the absence is visible.
- **How DOS encodes it.** **Baked** as the `UNWITNESSED` verdict — a named outcome
  distinct from `ABSTAIN`/`REFUTED`/`PASS` (`effect_witness` returns
  `CONFIRMED`/`REFUTED`/`UNWITNESSED`; `evidence.py` falls to a weaker witness rather
  than believing). Making stale frames *detectable* via a kernel-authored timestamp on
  `STEP_VERIFIED` is named future work ([`179 §5`](179_detector-self-labeling-harness.md)), not yet built.

## 8. Ablate by causal SHAPE, and match the actuation verb to where the cause lives

Subtraction (rewind) only helps when the problem is downstream-accreted context. When
the cause is an upstream **omission**, re-entering at a clean prefix faithfully
reproduces the omission and the agent re-thrashes. Feasibility is necessary but not
sufficient: a failure can be technically curable yet not be the **binding** constraint.

- **Why it matters.** A detector can be 100% sound while every actuation is wrong,
  because the intervention's hidden assumption about the *cause* doesn't hold. And
  curing the bound symptom on a multi-failure task leaves the run failing for other
  reasons — so conversion is **event-rate-bounded, not sample-size-bounded**: more
  reps cannot raise a discordant-pair count when the flips structurally don't happen.
- **Instances.**
  - Cause-locality ablation: **0/12** natural thrashes were rewind-fixable (class A);
    the rest were class B (upstream omission) or class C (capability gap) — rewind
    subtracts a symptom it cannot supply the cause for ([`172 §0.3`](172_the-rewindable-fix-loop-experiment.md)).
  - Curable-slice conversion null: base success on curable-thrash tasks is **~5%**
    (3/55) because they are MULTI-FAILURE — the thrash is a symptom, not the binding
    constraint ([`199 §3.3`](199_the-curable-slice-conversion-experiment-the-data-never-collected.md), `5f07713`).
  - The right verb per cause: route *away* from SUBTRACT — schema-injection for class
    C, precursor-gate for class B, restart/re-orchestrate for upstream omission; the
    restart arm was built as the missing comparand ([`193`](193_clean-restart-seeded-with-dos-knowledge.md); `restart_arm.py`).
- **How DOS encodes it.** Mostly discipline, partly tooled. The cause-locality classes
  (A downstream / B upstream-omission / C capability) are an analysis frame, not a
  kernel type. The restart-vs-rewind comparand is a benchmark arm. Pre-registered kill
  conditions encode "binding, not merely feasible" as *experiment design*, not code.

## 9. Generic correctness is a default, not an afterthought — and a too-permissive recognizer is worse than a strict one

A default chosen to keep the *first* consumer byte-identical silently breaks every
*new* consumer. "What keeps the reference app unchanged" and "what a stranger's repo
needs on day one" point in opposite directions.

- **Why it matters.** A *false all-clear* is more dangerous than a hard error: a loose
  heuristic that matches the wrong commits returns exit 0 while concrete `verify` fails
  for every phase, so the operator's safety net is asleep.
- **Instances.**
  - `default_config` inherited the strict `JOB_STAMP_CONVENTION` (requires a dir
    prefix), so a brand-new repo committing the *canonical* ship shape verified
    `NOT_SHIPPED via none` — the first friction every adopter hit; fixed by
    `GENERIC_STAMP_CONVENTION` as the default, user-approved (friction-log **F9**, `6511f81`).
  - `doctor --check` false all-clear: the recognizer matched release anchors
    (`vX.Y.Z:`) and `chore:` commits as ship-shaped → `finding=None`, exit 0, while
    `verify` failed for every phase; fixed by requiring a digit in the phase token +
    excluding release-cuts (friction-log **F8**; `tests/test_stamp_doctor.py`).
  - The batch grep protocol split on whitespace, truncating multi-word phases
    (`"hybrid-cache-type Phase 4"` → key mismatch → `source=none`); the green suite
    missed it because no test ever passed a phase with a space; fixed by tab-delimiting
    (friction-log **F7**; `phase_shipped._parse_batch_line`).
- **How DOS encodes it.** **Baked** as the closed-enums-as-data seam: stamp convention,
  reason vocabulary, lane taxonomy, and overlap policy are all *declared* per-workspace
  in `dos.toml`, so genericity is a config value, not a code fork — and the kernel ships
  a generic `main`/`global` default. Remaining gaps are open seams (plan-body ship
  grammar **F10** has no knob) and pragmatic tunings (the scan window is cadence-sized,
  not durable).

## 10. Adjudication belongs to the kernel; ACTUATION belongs to the host (PDP-not-PEP)

To **stop** a run you must know *what a run is* — a pid? a container? a remote API? a
task id? — and that platform knowledge is exactly what a domain-free substrate must not
carry. The kernel goes exactly two steps: **RECORD** (epistemic) and **PROPOSE**
(emit-and-exit), no further.

- **Why it matters.** The tempting objection is "if the kernel can see the run is
  stuck, why may it not kill it?" — but a kernel that learns "a run is a pid on this
  host" has stopped being a substrate and become one host's harness. The real boundary
  is *whose control flow is stopped*: a loop stopping its **own** decision-to-continue
  needs no domain knowledge; signalling a **foreign** process does.
- **Instances.**
  - `loop_decide` self-stop: a loop stopping its own control flow on `SPINNING` is
    in-bounds — byte-identical to the precedent where a loop distrusts its own
    `SHIPPED` self-report (`src/dos/loop_decide.py`; [`99 §3.1`](99_runtime-validation-and-the-actuation-boundary.md)).
  - `halt`: for a foreign-run stop the kernel journals `OP_HALT` and **proposes** a
    host-supplied command, never calls `os.kill`/`Popen`
    (`test_halt_proposes_does_not_signal` monkeypatches `os.kill`/`Popen` to raise,
    then asserts `halt()` succeeds with the command echoed, not executed).
  - `resume` **proposes** the residual + re-dispatch command and prints it, never
    executes ([`107`](107_resumable-work-and-the-intent-ledger.md) Phase 5).
- **How DOS encodes it.** **Baked** as the layering law (mechanism=kernel,
  policy=driver, one-directional imports). Every in-flight verdict is a pure
  `classify()` with I/O gathered at the boundary; the only effectful kernel moves are
  journal-a-record and propose-a-command. The actuator lives in a driver the kernel
  never imports — pinned by the "kernel imports no driver" litmus.

## 11. Terminology debt at trust boundaries is a real defect class

When one word spans three trust tiers, readers conflate them and propose merging things
that must stay apart. Keep version/identity metadata coherent for the same reason.

- **Why it matters.** "Claim" meant three different things — a kernel-granted lease
  *region-claim*, a forgeable intent-ledger `STEP_CLAIMED`, and a host TTL *soft-claim*
  — and without disambiguation people proposed lifting host soft-claim budgets *into the
  kernel*, which would pollute the trust floor. Version incoherence is the same disease
  in metadata: a durable adjudication record that stamps one version next to another's
  SHA is self-contradictory.
- **Instances.**
  - Three "claims" that must not be conflated: lease region-claim (adjudicated,
    `lane_journal`), intent `STEP_CLAIMED` (forgeable, `intent_ledger`), host soft-claim
    (TTL policy, `gate_classify`) — disambiguated by the [`110`](110_the-concurrency-class-operator-surface.md) tier table; soft-claim explicitly **not** lifted into the kernel.
  - 4-way version drift across `pyproject`/tag, `__version__`, the prod pin, and a
    vestigial dist-info; `doctor` stamped one version next to a newer SHA — internally
    self-contradictory in durable records ([`127`](127_dos-bench-job-integration-audit-2026-06-03.md)).
  - `UNKNOWN_LANE`: the arbiter auto-picked a substitute for an *explicit* unknown lane,
    masking the caller's region intent — fixed by splitting explicit-keyword
    (refuse-don't-guess) from soft-hint (redirect-with-reason) (`bc83d94`; `src/dos/arbiter.py`).
- **How DOS encodes it.** Mostly discipline (the full-phrase naming rule, the tier
  table), partly baked: the three "claim" concepts *are* cleanly separated into
  different modules at different trust tiers. The version-coherence fix (a `doctor`
  self-check asserting `importlib.metadata.version == fallback literal`) is designed,
  not yet a hard gate. `UNKNOWN_LANE`'s refuse-don't-guess is baked into the arbiter and
  registered in `BASE_REASONS`.

---

## If you take three things away

1. **The narration is never evidence.** Build the gate to read the artifact (git, env
   bytes, exit code), and make "I can't witness this" (`UNWITNESSED` / `ABSTAIN`) a
   first-class verdict, not a pass.
2. **Detecting a problem does not license fixing it.** On capable models, *steering*
   interventions wash to net-negative by *structure*; the safe actuator is the one that
   authors nothing (give up, withhold spend) — though the *out-of-loop* consumer remains
   unmeasured (Lesson 2's caveat, [`206`](206_proving-the-out-of-loop-verdict-the-frontier-lab-rigor-program.md)).
3. **Prevent irreversible effects at the boundary, and keep actuation out of the
   kernel.** The repo demonstrated its own thesis the hard way — `f14cde1` is the
   index-race DOS exists to prevent, happening to DOS itself.

## Provenance

7-modality corpus sweep (origin pathologies · extraction friction · WAL/coordination ·
refuted experiments · measurement discipline · liveness/resume · the condensed memory
record) → synthesis → adversarial grounding (`wf_0cd59739-e9c`, 19 agents, 2026-06-07).
58 raw findings → 11 lessons, all confirmed grounded against live code; the grounding
pass corrected stale commit hashes and one re-indexed doc number (187→156), folded in
above. Numbers (n, pp, p-values) are quoted from the cited docs; re-verify against the
named `file:line` / commit before treating any single-corpus figure as universal
(Lesson 5).
