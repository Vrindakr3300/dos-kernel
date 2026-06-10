# docs/170 — Frontier lift: where it lives, where it doesn't, and the features that grow it

> **DOS does not make a frontier model smarter. It makes a *fleet* of fast,
> confidently-wrong frontier models safe and reviewable on shared state — value
> that grows with horizon × fanout, vanishes at N=1, and is *amplified* by
> frontier throughput, not by a model's mistakes.** This note settles the
> question "does DOS help frontier models?" against DOS's own data, names the one
> honest axis the frontier value lives on, and lays out a verified roadmap of new
> features that grow it.

*Status: design. Produced by a two-phase agent fan-out (understand → audit →
field-scan, then generate → adversarially-verify) that mined DOS usage across the
sibling repos (`job`, `rag-takehome`, `Benchmark`, this repo's own dogfood, the gym
benches), reconciled the bimodal detect-lift finding against the velocity finding,
cross-checked the 2026 literature, and verified every proposed feature against the
real `src/dos/` surface on disk. The contrarian verifier RAN the frozen corpus and
**falsified** one proposed instrument — recorded in §6 as the honesty proof, not
hidden.*

---

## 0. The question, stated precisely

The operator's framing: *"DOS was invented in a pure Opus 4.8 usage context, so it
for sure helps frontier models."* That intuition is **right about the conclusion
and wrong about the mechanism**, and the gap matters because we have a benchmark
line that, read naively, seems to contradict it.

There are **two distinct lift stories**, and only one of them is about model
strength:

1. **Defensive lift** — DOS DETECTs / INTERVENEs / FIXes a model's mistakes
   (the Toolathlon + gym benches). This is **regime-bound to weak models** and is
   ~zero on the frontier. Its boundary is honest and pinned.
2. **Coordination / velocity / self-supervision** — DOS keeps a *fleet* of agents
   on shared state honest, steerable, and fast. This is **orthogonal to per-model
   capability** and **amplified by frontier throughput.** This is where the
   frontier value actually lives, and it is exactly the regime a pure-Opus-4.8
   *fleet* dogfooding this repo runs in.

The benchmark line only ever stress-tested story #1. The frontier story is story
#2, and it must be re-grounded there — not on defensive lift.

---

## 1. The two ground truths

### 1a. Defensive lift is refuted on the frontier (and that is FINE)

This is not a weakness to hide; it is a *boundary* DOS's own SSOT discipline
established. The numbers, all from frozen in-repo artifacts:

- **Conversion ceiling** (`benchmark/toolathlon/conversion_ceiling.py`, run live)
  — the UPPER BOUND on pass-rate lift assuming *perfect* conversion of every
  caught failure — is **0.00pp** on the strongest models (gpt-5, gpt-5.1,
  gemini-3-pro-preview, claude-4.5-sonnet-0929, deepseek-3.2, claude-4.5-haiku) and
  only **0.31–0.34pp** on a few more (claude-4-sonnet, gpt-5-high, claude-4.5-opus).
  All real headroom is on WEAK models: minimax-m2 **16.67pp**, grok-4 **7.03pp**,
  gemini-2.5-flash **4.09pp**.
- **The regime split** (corpus partitioned by model pass-rate; folded in from the
  retired `_regime_split.txt` scratch so the finding is self-contained):

  | Regime | Models | Tasks | Detector fires | Recoverable | Ceiling |
  |---|---|---|---|---|---|
  | WEAK (<30% pass) | 14 | 4,360 | 328 | 162 | **3.72pp** |
  | STRONG (≥30% pass) | 8 | 2,502 | 21 | 3 | **0.12pp** |
  | **Corpus aggregate** | **22** | **6,862** | **349** | **165** | **2.4pp** |

  Realized estimated lift across the corpus is **0.72pp**. The split is the
  mechanism made quantitative: moving from WEAK to STRONG, detector fires drop ~15×
  and recoverable failures ~54×, so the available defensive headroom collapses from
  3.72pp to 0.12pp — the same monotone story the conversion-ceiling bullet tells,
  now with the per-regime denominators.
- **Detectors fire ~0 on the absolute frontier**: `terminal_error` adds 0 net-new on
  claude-4.5-opus (0/174), gpt-5.1 (0/216), gpt-5 (0/212), claude-4-sonnet (0/222)
  (`additivity_claims.md`). `arg_provenance` correctly fires **0 times** on a capable
  model that behaves (live: 0 natural mints across 406 mutating calls, gemini-2.5-flash
  A/B baseline).
- **Intervention lift is weak-model-only**: the live 4-arm gym A/B (docs/144) —
  **WARN +6.2pp integrity, BLOCK +0.0pp (13 hurt-flips), DEFER +2.0pp** — is on a
  WEAK model in a mint-prone regime. On a capable model 0 mints fire, so the
  intervention lift is structurally 0.

**The mechanism is monotone and unavoidable: a stronger model fails LESS and mints
LESS, so anything that profits from a model's mistakes shrinks toward zero by
construction.** Reporting union-recall gains (4.74% → 6.18%) or "WARN +6.2pp"
without the per-model frontier cut would *launder* a weak-model result into a
frontier claim — which is exactly the laundering DOS's SSOT tooling
(`additivity.py --check`, `conversion_ceiling.py`) exists to prevent. **Recall is
the wrong scoreboard** on a 76%-fail bench (an always-fire null posts 100% recall
at 0 skill); score by lift(precision−base) + false-alarm.

So: on the defensive axis, the honest claim about a frontier model is that **DOS is
HARMLESS — it correctly stays silent** — not that it lifts the score. That harmless-
ness is itself proven on frontier data, and it is a real product property (a
referee that does not interfere with a competent player). But it is not the lift.

### 1b. Coordination / velocity is real, model-independent, and throughput-amplified

The value that does NOT decay with capability:

- **The closed loop is the organizing principle** (docs/136). DOS closes four
  loops — CONTROL, TRUST, IMPROVEMENT, COMPLETION — each comparing a reference
  against an *un-forgeable* output (git ancestry, the lease WAL, an OS exit code,
  a counterparty receipt), never the agent's self-report. *"Parallelism is easy;
  control of a running fleet is the hard part."* None of these four loops is about
  catching a weak generator — they are about steering a *plant* (the fleet acting on
  shared state).
- **FleetHorizon measures it** (docs/81 §4.6, `benchmark/fleet_horizon/`). Same
  agents, same seed, open loop (believe) vs closed loop (adjudicate), 8 efforts ×
  30 phases: **35/35 banked lies caught, 7/7 silent overwrites prevented,
  human-review fraction 100% → 17.1%, verified-velocity-per-$ 0.379 → 0.500 fully
  loaded (1.32×).** Break-even κ = **0 at every fleet ≥ 2** — DOS wins *even with the
  conflict multiplier set to zero*, on the model-free review-fraction term alone.
- **It is monotone in horizon × fanout and → 0 at N=1** (its own falsifier).
  Defect-debt grows 0 → 2 → 13 → 147 → 779 across horizon 1 → 3 → 8 → 20 → 40;
  collisions-prevented grows 0 at fleet=1 → 104 at fleet=8.
- **Throughput amplifies it super-linearly.** Faster generation pushes more "done"
  reports into the human review queue per unit time; Kingman's M/M/1 wait
  `ρ/(1−ρ)·(1/μ)` blows up super-linearly as ρ → 1. Shrinking the review fraction
  (100% → 17%) is worth *more*, not less, the faster the fleet generates — this is
  the **Faros productivity paradox** (high-AI teams merged +98% more PRs while PR
  review time rose +91% and throughput did not move) and DOS's lever against it.

This is why DOS emerged in a pure-Opus-4.8 context: a *fleet* of strong agents on
shared state is exactly the high-throughput, long-horizon, high-contention regime
where the closed loop earns its keep — and a stronger generator makes the
*open-loop* problem **worse**, not better.

### 1c. The linchpin — and the correction the data forced

The bridge from §1a to §1b: **strong models fail LESS often, but when they fail
they fail SILENTLY and CONFIDENTLY.** docs/158: ~92% of silent failures carry a
substantial confident final narration — the model "fails while asserting success."
A *believing* fleet of strong agents banks those confident lies, which compound
across a long horizon. DOS's `verify` + `arbitrate` + `run_id` spine refuses
without believing the claimant.

**The honesty correction (forced by the contrarian verifier running the corpus, §6):**
the linchpin is NOT "strong models fail *more* silently than weak ones." That is
**false** in the data — Pearson(pass%, silent-fail-rate) = **+0.584**, and BOTH
strong and weak models fail silently at 80–100% rates; `final_text_len` does not
separate them. The correct, defensible statement is narrower and still sufficient:

> A strong model fails *less often*, but its failures are silent + confident, and a
> believing fleet banks them at whatever rate they occur. The compounding lives in
> **horizon × fanout**, not in capability. So the fleet needs an external,
> un-authorable sensor on every "done" — and that need does not shrink as the model
> gets stronger, because the model's own confidence in a silent failure does not
> shrink.

### 1d. The honest weaknesses (state them out loud)

The coordination story is the right axis, but its live frontier *magnitude* is not
yet proven, and three things must be said every time it is cited:

1. **The strongest evidence is SIMULATED.** FleetHorizon's failure model hardcodes
   `lie_rate = 0.12` (`agent.py`). It proves the kernel MECHANISM under an assumed
   rate, not real frontier-agent behavior. If real strong agents lie/collide at a
   materially lower rate, the simulated 1.32× edge shrinks.
2. **The one real arc measured a NET LOSS.** The EnterpriseOps dogfood arc
   (docs/155) measured **0.68–0.79× verified-velocity-per-$** at its real
   coordinates (fleet=12, horizon=4) — because it was *wide but SHORT*: enough
   agents to see 104 real collisions, not enough horizon for defect-debt to make
   adjudication pay. The mechanism is real; the dollar payoff is deferred to long
   horizons. And the live collision *rate* is currently **unmeasurable** — all 294
   arc commits are one "Claude" identity with no `run_id` stamps.
3. **"Invented in Opus context → helps frontier" is a NON-SEQUITUR.**
   Throughput-amplification is not frontier-exclusive — a fast *weak* fleet would
   get the same coordination value. The lift is a fleet/horizon property, not a
   capability-tier property. The inventor's tier is not evidence of lift on the
   inventor's tier.

---

## 2. How the sibling repos actually consume DOS (the usage evidence)

Mined directly from the repos. The pattern confirms §1: where DOS touches a
frontier-model workflow, it delivers **structure + ground truth for a fleet**, not
a capability boost.

- **`job`** (the reference userland app, 48 dispatch files) uses DOS for
  **DISPATCH DECISIONS** — `scout.choose` (9-rule activity routing), `health.check`
  (lane-health gate), `arbiter.arbitrate` (predicate-lock admission),
  `loop_decide.decide` (the stop-condition state machine — *the crown jewel: pure,
  one place to read*), `liveness.classify` (the ground-truth anti-spin veto),
  `lane_journal` (the WAL). The honest gap (docs/140): job uses DOS for dispatch but
  NOT for **truth** — it hand-rolls `git merge-base --is-ancestor` instead of
  `dos.verify`, and hand-writes residual branching in SKILL prose instead of
  `dos.resume`. The frontier value job *gets today* is **structured decisions over
  prose choice** — a strong model verifies the routing against the evidence tuple
  instead of re-deriving it from a 1400-line SKILL. (Several of these read
  "weak-model-only" under a strict lens — saving a strong model from re-implementing
  a state machine is convenience; the *load-bearing* frontier value is the
  fleet-coordination set: `arbitrate` + `verify` + `liveness` + `lane_journal`.)
- **This repo (dogfood)** coordinates concurrent Opus 4.8 agents editing the kernel
  via `arbitrate` (lane region-locks), `verify` (one agent trusts another's ship
  claim via git, never via narration), `liveness`, the **SELF_MODIFY** predicate
  (an agent cannot rewrite the kernel adjudicating it mid-flight), and the
  lease-journal WAL. The frontier-specific ritual (CLAUDE.md): *stage by path glob,
  never `git add -A`* — because the working tree carries another agent's in-flight
  edits. That is the disjoint-lane discipline applied to staging, a norm a fleet of
  strong agents follows because the substrate makes the contention legible.
- **a third-party RAG take-home** (first real third-party adoption) imported
  `evidence.believe_under_floor`, the `Accountability` witness ladder
  (THIRD_PARTY / OS_RECORDED / AGENT_AUTHORED), `judges.run_judge` (fail-to-abstain),
  `reasons`, `derived_witness`. The reframe (docs/156): the *concepts* propagated
  even where kernel *code* was inert — a frontier model BUILDING a system gets
  forced to reify "grounded" into an auditable witness ladder. These are
  correctness-architecture primitives, model-independent.
- **`Benchmark` / FleetHorizon** is the velocity instrument itself (§1b).

---

## 3. The field has converged on DOS's axis (2026 literature)

Independent validation that the coordination/self-supervision axis is *the* axis —
and that DOS's specific design choices are the ones the field is reaching for:

- **The Self-Correction Illusion** (arXiv 2606.05976) + **CRITIC**
  (2305.11738 / 2604 follow-ups): self-correction *reliably degrades* reasoning
  accuracy without external feedback; what's called "self-correction" is mostly
  external-feedback-driven refinement; an LLM's willingness to correct a claim tracks
  the **chat-template role label**, not the claim's content. **This is docs/136 §2
  published as an empirical 2026 result**: a frontier model structurally cannot be
  its own sensor — it needs feedback it cannot author. DOS's whole evidence ladder
  is that sensor.
- **CAID — Centralized Asynchronous Isolated Delegation** (arXiv 2603.21489):
  frontier multi-agent SWE gets **+26.7% (PaperBench) / +14.3% (Commit0)** via
  *isolated workspaces + executable test-based verification*, and **worktree
  isolation becomes necessary for long-horizon tasks.** This is *empirical frontier
  lift from coordination + ground-truth verification* — DOS's lane region-lock +
  `verify`, from an independent lab. The strongest external evidence the operator's
  intuition is right.
- **CodeCRDT** (arXiv 2510.18893) + the "17× error trap of the bag of agents":
  concurrent modification / merge conflicts are the *primary* multi-agent failure;
  the field reaches for CRDTs (optimistic) and notes a "practical team size of 3–4
  agents due to coordination overhead." DOS argues **pessimistic region-locks are
  correct under high write contention** (docs/81 §2.1) — the lane is exactly the
  coordination-overhead-folded-into-one-verdict that lifts that 3–4 ceiling.
- **Beyond pass@1: A Reliability Science Framework for Long-Horizon Agents**
  (arXiv 2603.29231): reliability is a function of task *duration* (the Reliability
  Decay Curve). That is DOS's horizon axis, named.
- **Trust Fabric / A Protocol for Verifiable Multi-Agent Systems / Separation of
  Power** (2507.07901, 2507.22077, 2603.25100): the field is naming "Kubernetes for
  agents," tamper-resistant ledgers, and a separate **Adjudication branch** of the
  agent lifecycle — DOS's "the referee cannot report to a contestant" inversion,
  arriving in the literature.

---

## 4. The frontier-feature roadmap (verified against the real kernel)

Sixteen candidates were generated across four lenses (coordination,
self-supervision, velocity/long-horizon, contrarian-instruments) and each was
adversarially verified against the source on disk. **One was cut by the verifier
running the data (§6).** The survivors deduplicate to the roadmap below. Every
entry: a pure kernel verdict (state in, verdict out, I/O at the boundary),
advisory-only, reusing shipped modules, with its forgeable hole named.

Ordering is by **cheapest-first** (the discipline docs/160 §4 / docs/159 prescribe):
$0 offline proofs before any spend.

### Tier 0 — the keystone, $0, unblocks everything (KEEP-STRONG ×3, buildable=yes)

**F1. verify-on-stop, wired to the REAL Claude Code Stop contract.** Fix the
docs/165 keystone no-op: `dos hook stop` today emits `{"ok":false}` + exit-0, which
real Claude Code **honors none of** (it acts only on `decision:block` /
`additionalContext` / exit-2). The verdict logic is already correct (`claim_extract`
3-rung extractor → `oracle.is_shipped` per claim); the bug is purely the output
*dialect*. The ~5-line fix: emit `additionalContext` (WARN-by-default — the live-A/B
winner) so the agent gets the un-authored verdict re-surfaced before it stops;
`decision:block` only under explicit opt-in; restrict any BLOCK to the
**file-path/registry non-forgeable rung** (never `grep-subject` — the agent authors
its own commit subjects, forgeable, fired live on docs/120); strike-cap so a block
degrades to context after N identical re-prompts.
  - *Why it's the keystone:* this is the **only place "helps a frontier runtime"
    becomes literally true** — currently it's a proven silent no-op. The Stop event
    is the instant an agent converts "I'm done" into a terminal fact; it is the
    lowest-latency sensor in the docs/154 latency axis. The whole Stop family
    (SubagentStop, PreCompact, the plugin verifier) inherits the broken output
    byte-for-byte and is DEAD until this lands.
  - *Reuses:* `claim_extract`, `oracle`, `intervention` (WARN mapping), `guard`.
  - *$0 proof:* a **mirror-vs-real conformance test** — feed a real CC Stop-event
    JSON through the fixed hook, assert the emitted bytes are in CC's accepted-action
    set (the test `test_hook_stop` *should* have been; today it pins the dead
    dialect). Plus a dogfood replay: a Stop claiming an un-committed `docs/NN` phase
    must surface the residual via `additionalContext`.
  - *Honest boundary:* proves the binding is HONORED, not a task-score lift. WARN
    buys ~+4.2pp on a WEAK model; on the frontier the catch-rate is low *because
    strong models mint fewer false "done"s*. The value is **reviewability** (a
    confident-stop-lie surfaced to the operator), never pass@1. **Probe live CC
    before enabling any BLOCK.** Ship WARN-by-default.
  - *Convergence signal:* this feature surfaced **independently from three lenses**
    (self-supervision, velocity, contrarian) and scored keep-strong / buildable=yes
    each time — the strongest possible vote that it is the right pickup.

### Tier 1 — the external sensor a fleet calls (KEEP-STRONG, buildable=yes)

**F2. `dos_attested` — `verify` / `believe_under_floor` as a mid-task MCP tool.**
Expose, as an MCP tool a frontier agent calls *mid-task on its own prior steps*, a
`dos_attested(subject, workspace)` that gathers `EvidenceFacts` via
`active_evidence_sources` and folds them through `evidence.believe_under_floor`,
returning the `BeliefVerdict`. The agent asks "is the thing I just did real?" and
gets back `believe=True` **only when a non-forgeable witness (OS_RECORDED exit code /
THIRD_PARTY) attested** — its own stdout (AGENT_AUTHORED) is structurally filtered
out of the belief decision by the floor.
  - *Why frontier:* this is **CRITIC's missing piece made a syscall.** The
    Self-Correction Illusion is *structural, not capability-bound* — a stronger
    model still cannot subtract its own house style with the pen that wrote it.
    Value grows with autonomy × horizon (more unattended steps → more "is my own
    prior claim real?" moments) and throughput; → 0 at a one-shot task with a human
    watching every step.
  - *Reuses:* `evidence.believe_under_floor`, `evidence.active_evidence_sources`,
    `evidence.BeliefVerdict`, `oracle.is_shipped`, the `dos_mcp.server` tool pattern.
    *(The MCP server already ships `dos_verify`; this is a new sibling tool.)*
  - *$0 proof:* the floor-discipline tests already pin it — an AGENT_AUTHORED
    self-report cannot launder belief; add a witness → `believe=True`. No model call.
  - *Honest boundary:* it verifies only effects that HAVE an accountable witness
    wired (git, an OS exit code, a provider receipt). It cannot grade open-ended
    reasoning or correctness. It does NOT prove the agent will *call* it (MCP is
    decline-able). It is "an external sensor for the narrow class of effects with an
    accountable witness," NOT "the model now self-corrects."

**F3. `derived_witness` for agent-selected computation, surfaced as a tool.**
`evidence.derived_witness` already exists (mints a non-forgeable rung IFF the op is
*declared* — never reverse-searched to fit the answer — AND every operand was itself
non-forgeably attested AND the recomputation matches, capping at the minimum operand
rung). Wire it into the verify path / an MCP tool so a frontier agent reporting a
NUMBER (a metric, an aggregate, a score) must supply witnessed operands + a declared
op; a fabricated operand degrades the result to AGENT_AUTHORED — advisory,
structurally incapable of granting belief. Closes the exact laundering docs/156
committed (tagging agent-selected arithmetic THIRD_PARTY).
  - *Reuses:* `evidence.derived_witness` (+ its 8 shipped tests), `believe_under_floor`.
  - *Honest boundary:* covers only values reducible to a declared arithmetic op over
    witnessable operands; ABSTAINS on non-deterministic transforms; degrades to
    advisory when operands lack witnesses (most real cases today — a visible,
    safe-direction loss). It is a **ceiling on laundering, not a floor on accuracy.**

### Tier 2 — the fleet console (KEEP-STRONG fleet_digest; KEEP-WITH-CAVEAT the rest)

**F4. `fleet_digest` — the fleet-wide "who is banking the most unverified work right
now" board.** A pure `fleet_digest(tuple[StatusDigest, ...], policy) → FleetBoard`
that folds the existing per-run `status.status_digest` across the whole roster,
ranking runs by `exposure = declared − verified` × liveness-confidence. It inherits
`status`'s load-bearing invariant: **no `claimed` slot** — a consumer cannot read a
self-report, only the adjudicated residual.
  - *Why frontier:* the docs/158 linchpin operationalized as a live console — total
    banked-exposure grows with fleet size × horizon × throughput (the Kingman
    blowup). At N=1 it degrades to today's `dos status`; the value is the
    **cross-agent ranking** — which of N to review first.
  - *Reuses:* `status`, `intent_ledger`, `liveness`, `completion`, `run_id`,
    `lane_journal`. **All six confirmed with usable surface; buildable=yes.**
  - *$0 proof:* replay a frozen FleetHorizon closed-loop run into per-run
    `LedgerState`s → `StatusDigest`s → `fleet_digest`; assert the top-ranked run is
    the one the harness labeled with the most banked lies; assert by dict-keys that
    `FleetBoard.to_dict` carries no `claimed` key.
  - *Honest boundary:* **exposure ≠ lying** — a healthy agent legitimately runs
    ahead of verification mid-phase. The board ranks RISK for triage; it does not
    adjudicate dishonesty. Blind to a run that declared no intent
    (forgeable-by-suppression — the `dangling_intent` hole at fleet scale).

**F5. `release_gate` — the dependent-unblock primitive.** A pure verdict that AND-s
two existing kernel verdicts: a dependent effort may spawn the instant its
predecessor is **kernel-VERIFIED** (`completion.classify == COMPLETE`, residual
empty, every declared step on the non-forgeable rung) AND its lane is free
(`arbiter.arbitrate == acquire`). Turns the human review desk from a serial gate on
the critical path into an async exception lane — the direct Faros-paradox lever.
  - *Reuses:* `completion`, `resume`, `intent_ledger`, `arbiter`, `lane_journal`.
    **Buildable=yes.**
  - *$0 proof:* replay the frozen `fleet_horizon/.dos/lane-journal.jsonl` over a
    synthetic dependency DAG; report edges released on VERIFY vs edges that would
    idle at the review desk, and wall-clock idle collapsed via `metrics.py`'s
    Kingman estimator.
  - *Honest boundary (must be in the verdict string, not a footnote):* it is a
    **START-permission, not a quality verdict** — a completed task can still be
    wrong; it removes review from the *critical path between efforts*, NOT the final
    deliverable review. Value → 0 at N=1.

**F6. `review_triage` — route only genuine exceptions to humans.** A pure classifier
mapping already-computed verdicts to a closed escalation set (AUTO_RELEASE /
HUMAN_DIVERGENCE / HUMAN_NOFIXPOINT / HUMAN_INDETERMINATE / HUMAN_OVERCLAIM) — the
arrival-rate filter the velocity axis already prices (100% → ~lie-rate human-review
fraction → lower Kingman ρ). Rides the shipped `intervention` ladder for the action.
  - *Caveat from the verifier:* AUTO_RELEASE is safe only in a *replay* harness;
    in a live harness liveness must be re-checked at release time. The false-release
    rate is the honest metric and must be reported alongside saved-reviews; driving
    reviews to zero is a red flag, not a win.

**F7. `collision_attribution` / `lease_horizon` — coordination visibility (KEEP-WITH-CAVEAT).**
- `collision_attribution`: a pure verdict over the WAL naming, for each contending
  `(run_id, run_id, region)` pair, the **PREVENTED** disposition (a REFUSE that
  collided with a live ACQUIRE, both sides attributed by `run_id`). **Critical
  correction from the verifier:** the WAL records arbiter *verdicts*, not
  collisions-that-occurred — so it can attribute **PREVENT** events soundly, but
  **silent overwrites are NOT WAL-observable** (they require host-side data-flow
  tracking, out of kernel scope per the PDP-not-PEP line). Ship as PREVENT-attribution
  only; do not claim it counts realized overwrites.
- `lease_horizon`: a pre-dispatch `CONTENTION_AHEAD` WARN naming which sibling's
  *declared future scope* a requester would collide with — a fleet self-coordinates
  by reading each other's adjudicated intent (docs/116), never each other's chat. It
  can only refuse-MORE than the arbiter (`overlap_policy.admissible_under_floor`).
  **Caveat:** declared scope is agent-authored and forgeable (the docs/117 Phase-4
  scope-source hole) — it is a WARN forecast that reduces *detection latency*, never
  a BLOCK guarantee; the unforgeable floor stays the acquire-time arbiter over real
  leases.

### Tier 3 — the instruments that close the simulation gap ($0, KEEP-STRONG/CAVEAT)

These are the disciplined path docs/155 §6 itself prescribes: convert the
coordination thesis from SIMULATED to MEASURED, cheapest-first, before any spend.

**F8. `passive_collision_replay` (KEEP-STRONG, buildable=yes).** Deterministically
replay the frozen multi-effort workload (or this repo's own `lane_journal`) through
`arbitrate()` / `overlap_verdict()` at increasing fanout, counting the double-books a
*believing* orchestrator would commit vs the zero the arbiter refuses. **At N=1 the
count is exactly 0 — the thesis "value → 0 at N=1" made an EQUATION** — and it grows
super-linearly in N; `generate_disjoint()` is the boundary falsifier (0 avoided
collisions when footprints are truly disjoint → proves WHEN DOS is moot). *Honest
boundary:* collisions-avoided is an UPPER BOUND on harm, not realized dollar harm.

**F9. `passive_collision_dataset` — the dogfood arc as a labeled corpus
(KEEP-WITH-CAVEAT).** The single cheapest path to killing the hardcoded
`lie_rate=0.12`: fold this repo's own WAL + intent ledgers + git ancestry into
per-event ground-truth records where the agent's claim-side features are kept rigidly
apart from the kernel-adjudicated label (the docs/84 trajectory tuple, re-aimed from
a simulator onto REAL concurrent-agent runs). **Prerequisite (docs/155 §6.4 names it):
stamp `run_id` in every research-agent commit trailer + a `measurements.jsonl` row** —
today all arc commits are one "Claude" identity, so the live collision rate is
unmeasurable. One cheap convention turns the next real Opus-fleet arc into a passive,
attributed dataset for free. *Honest boundary:* it supplies the labels to MEASURE the
net-loss-vs-payoff question, it does NOT prove the fleet pays off; forgeable-by-
suppression at the claim side (a run that stops narrating goes dark).

**F10. `horizon_compounding_replay` (KEEP-WITH-CAVEAT).** Replace FleetHorizon's
hardcoded `lie_rate` with the per-model *measured* silent-failure rate from the
frozen corpus, re-run the open-vs-closed arc per model. *Honest boundary:* it
de-hardcodes the RATE with a real number but the compounding MECHANISM stays a
simulation — label it "simulated arc, measured rate," show the **crossover horizon**
where the believing arm becomes worse (NOT just the asymptote), and keep the real
short-horizon NET LOSS plotted as the falsifier.

---

## 5. The honest one-paragraph thesis (for reuse)

> DOS does not lift a single frontier model's task score — its detect/intervene/fix
> value is regime-bound to weak, mistake-prone models and is ~0 on the strongest
> tier by construction (a better model fails less and mints less). What DOS lifts is
> a **fleet** of fast, confidently-wrong frontier agents working a shared, long-lived
> codebase: it keeps them honest (`verify` against git, never self-report), steerable
> (`liveness`/`scout`/`arbitrate` close the control loop), non-colliding (the lane
> region-lock), and reviewable (shrink the human queue to the exceptions). That value
> is orthogonal to per-model capability, monotone in horizon × fanout, → 0 at N=1,
> and *amplified* by frontier throughput (faster generation → heavier review-queue
> load → super-linear Kingman blowup) — which is exactly why it emerged in a
> pure-Opus-4.8 *fleet* context. The boundary, stated every time: this is proven as a
> MECHANISM on a simulated fleet and anchored n=1 on a real arc at a short-horizon
> NET LOSS; the axis is right, its live frontier dollar magnitude is the next thing
> to measure — cheapest-first, on frozen data, before any spend.

---

## 6. The falsification (why this note is trustworthy)

The contrarian verifier did not rubber-stamp the proposals. It **ran the frozen
corpus** and killed one:

- **CUT: `capability_orthogonality_recut`.** The proposal claimed an *inversion* —
  detect-lift falling to 0 with capability while silent-confident-failure RISES with
  capability — and would have plotted it as the headline. The data refutes it:
  Pearson(pass%, silent-fail-rate) = **+0.584**, both strong and weak models fail
  silently at 80–100%, and `final_text_len` (the proposed "confidence" proxy) does
  not separate tiers (weak gemini-2.5-flash produces 3000–6000-char failures too).
  Verbosity ≠ confidence ≠ correctness. The instrument was cut and the linchpin in
  §1c was rewritten to the narrower, defensible claim.

That cut is the proof the rest of the note survived the same scrutiny: every kept
feature's reuse was checked against the file on disk, every over-claim was named,
and the simulation/net-loss/non-sequitur caveats are carried into every tier — not
buried.

---

## 7. Relationship to existing docs

- **docs/81** (velocity economics) — the FleetHorizon harness + the 1.32× / κ=0
  result this note's §1b rests on.
- **docs/136** (the closed loop) — the four-loops keystone; §1c's "a loop whose
  sensor is the plant is open with extra steps" is its §2.
- **docs/154** (the latency axis) — why the Stop event (F1) is the lowest-latency
  sensor and why purity makes the loop fast.
- **docs/155** (coordinating parallel research) — the real dogfood arc, the net-loss
  measurement, and the `run_id`-stamp prerequisite F9 depends on.
- **docs/156 / evidence.py** (`believe_under_floor`, `derived_witness`) — the floor
  F2/F3 expose as tools.
- **docs/158** (silent + confident frontier failures) — the linchpin, as corrected.
- **docs/164** (the FIX loop) — the author-and-believe line every feature here
  respects (DETECT-and-surface, never author-and-believe a correction).
- **docs/165** (DOS into Claude Code) — F1 is the keystone fix this note promotes
  from "found bug" to "ranked roadmap pickup."

*Strategy framing (why this matters / who buys it) belongs in `dos-strategy`, not
here — see the companion note.*
