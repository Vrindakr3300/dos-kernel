# docs/143 — DOS as a key delta on EnterpriseOps-Gym (vs the cheapest LLM)

> **Status: SHIPPED + RUN. 2026-06-04.** The R1 keystone (`dos.arg_provenance`) is
> built, unit-tested, wired into a 4th gym orchestrator (`dos_react`), and run
> **end-to-end on the real `ServiceNow/enterpriseops-gym` harness** with a live
> Gemini model (Docker MCP servers, hidden SQL verifiers untouched). The audit
> below (the original design analysis) stands; the measured companion is
> **`benchmark/enterpriseops/RESULTS.md`** and the code is `src/dos/arg_provenance.py`
> + `benchmark/enterpriseops/`. **Headline of the real run:** the detector is
> deployment-safe and high-recall — **0.00 % false-nudge on 249 real resolved calls,
> ~83 % recall on genuine injected mints** (measured deterministically over real
> gemini-3-flash trajectories) — and on a *strong* model it correctly stays silent
> because that model resolves its FK ids (0 real mints), **confirming the audit's own
> "Integrity is agents' strongest class" prediction**. The value appears on a *cheap
> minting* agent (the faithful simulator, running the same `classify_call`, shows
> +11 pp on the Integrity slice with the recover loop). See §12 + RESULTS.md.
>
> *Original framing (still the design contract):* An honest audit of where the DOS
> distrust substrate would and would not move a published agentic benchmark, run
> as directly as the public record allows: drop DOS into the *same* harness with
> the *same* cheap model and read the difference. This is the map + the experiment
> + the honest ceiling.

## 0. The question

Operator ask: *audit DOS's ability as a key delta vs the most affordable runnable
LLM on [EnterpriseOps-Gym](https://enterpriseops-gym.github.io/) — comparable as
directly as possible, "just add DOS and see the difference."* Plus two refinements:
(1) can we run DOS on top of the ServiceNow harness as another sweep option? and
(2) what's obvious to add to DOS to make it more effective here — used in **multiple
places** across a trajectory, not just bolted on at the end.

## 1. The benchmark (primary source: arXiv 2603.13594, ServiceNow Research)

EnterpriseOps-Gym measures **stateful, multi-step enterprise operations against
live databases** — direct mutation of a shared relational DB where **every action
is permanent and irreversible** (no within-run rollback or checkpoint). Standard
**ReAct** loop; an action is a tool call against a containerized **MCP** server.

- **Scale:** 1,150 expert-curated tasks · 8 domains (Teams, CSM, Email, ITSM,
  Calendar, HR, Drive, Hybrid) · 512 tools · 164 DB tables · avg 9.15 steps,
  **up to 34** · avg ~5.3 verifiers/task (max 44).
- **Verification (load-bearing):** hidden expert-authored **SQL on the FINAL DB
  state**, all-must-pass, `pass@1` over 3 runs. **Not** LLM-as-judge (an LLM only
  *tags* verifiers post-hoc), **not** action-sequence matching.
- **Verifier categories (Table 7):** Task Completion · Integrity Constraints
  (FK validity) · **Permission & Process Compliance**.
- **Headline:** best = **Claude Opus 4.5 = 37.4%** avg (oracle-tool mode, full
  benchmark; the HF "34.1%" is the same model on the ~60% public split). Nothing
  reaches 40%.
- **Refusal subset:** 30 infeasible tasks; correct refusal = decline **AND leave
  zero side effects** (~10 checks each). Best = **53.9%** (GPT-5.2 Low); best
  *overall* model (Opus 4.5) only 50.0%.
- **The dominant finding:** **strategic planning is the bottleneck** — oracle human
  plans add **+14–35pp**; adding 5/10/15 distractor tools moves success only
  **+1.0pp** ("the bottleneck is not tool discovery"). Performance decays
  monotonically with horizon (~35% @ 4 steps → <20% @ 16 steps).

### 1a. The two tables that decide the audit

**Cheap models are the paper's own headline** (Pareto frontier, Figure 1):

| Model | Success | $/task |
|---|---|---|
| Claude Opus 4.5 | 37.4% | $0.36 |
| **Gemini-3-Flash** | **31.9%** | **$0.03** ← best cost/perf |
| GPT-5 | 29.8% | $0.16 |
| Claude Sonnet 4.5 | 30.9% | $0.26 |
| DeepSeek-V3.2 (High) | 24.5% | $0.014 |
| Qwen3-235B (Inst.) | 16.1% | $0.007 ← cheapest |

**Table 7 — verifier pass rates by category** (averaged across models):

| Domain | Task Completion | Integrity Constraints | **Policy Compliance** |
|---|---|---|---|
| Teams | 82.3 | 90.0 | 81.3 |
| CSM | 58.3 | 70.0 | **45.5** |
| Email | 70.9 | 76.5 | 79.2 |
| ITSM | 53.7 | 50.6 | **30.0** ← worst cell |
| Calendar | 71.5 | 62.5 | 76.1 |
| HR | 63.2 | 56.0 | **50.4** |
| Drive | 75.1 | 87.8 | 66.7 |
| Hybrid | 60.0 | 72.5 | 61.1 |

> **Two facts from Table 7 that steer everything below.** (a) **Policy Compliance
> is the weakest verifier class everywhere**, and *collapses* in the policy-heavy
> domains (ITSM 30%, CSM 45.5%, HR 50.4%). (b) **Integrity Constraints is agents'
> *strongest* class** (50.6–90) — so there is *less* headroom on the FK-corruption
> slice than intuition suggests.

### 1b. Named failure modes (verbatim from §4.4)

- **Missing Prerequisite Lookup** — create an object without querying prereqs →
  dangling/orphaned FK records.
- **Cascading State Propagation** — fail to trigger the policy-mandated **follow-up**
  action a state transition requires.
- **Incorrect ID Resolution** — pass **unverified IDs minted by the model** instead
  of resolving the correct IDs through **prior tool interactions**.
- **Premature Completion Hallucination** — declare completion **before all required
  steps have been executed**.

### 1c. The policy doc is a structured grammar, not prose (Appendix C system prompts)

The per-domain system prompt embeds a *parseable* policy contract, e.g. Drive:

- *"**Policy Enforcement:** Do not act on any request that violates a restriction
  within this document. **Refuse the command and state the specific policy reason.**"*
- *"**Atomic Operations:** Perform one distinct, validated operation at a time. Do
  not chain dependent actions if the failure of a single step risks data corruption."*
- *"**Permission Verification:** All operations must **first call a permission check**.
  Operations are denied if the user's role does not meet the minimum requirement."*
- *"**Destructive Actions:** For irreversible operations … you must explicitly confirm
  the consequence before proceeding."*

This matters: refusal/policy-compliance here is **not** open-ended feasibility
*reasoning* — it is a **declared precondition + a named-reason refusal**, which is
`dos.refuse` mechanism, not planner reasoning.

## 2. The cheap comparator — Gemini Flash-Lite

- `gemini-3.1-flash-lite` (GA id; the `-preview` id 404s on stable v1). **$0.25 /
  $1.50** per 1M in/out; **1M ctx**; full `google-genai` function-calling incl. a
  proven multi-turn `run_tool_loop` (`job_search/gemini_client.py`). Runnable key
  path: `GEMINI_API_KEY` (`job/.env.example:13`), accepted via
  `conf/llm/<name>.json` + `evaluate.py --llm_config`.
- **~20× cheaper per task than the Opus 4.5 leader** (robust — fixed by the price
  gap). ESTIMATE per-task ~$0.22; public-split run (~690 tasks) ~$150 vs ~$3,000.
- **Expected absolute success: ~5–18% (ESTIMATE, reasoned not measured)** — below
  the 37.4% ceiling, because the named bottleneck (multi-step strategic reasoning)
  is exactly where a Lite tier is weakest.

## 3. Yes — DOS slots in as a 4th `--orchestrator` (`dos_react`)

The harness is built for this. `orchestrators/base.py` defines `AgentOrchestrator`
(`__init__(llm_client, mcp_clients, tool_to_server_mapping, available_tools, config,
max_iterations=50)`, async `execute() -> {final_response, conversation_flow,
tools_used, tool_results, messages}`, helper `_execute_tool_call`). `react` /
`planner_react` / `decomposing` are subclasses selected by `--orchestrator`. A
**`dos_react` subclass** is a clean A/B: **same model, same 512 tools, same hidden
SQL scorer — only the loop changes.** The wrapper *owns* the loop, so it can make an
advisory DOS verdict **enforcing in the wrapper** (block a call, block the stop)
without changing the kernel's advisory doctrine.

> **The legitimacy line you may not cross.** The wrapper may read ONLY what a fair
> agent could (its own read tools / MCP read calls / tool-result history / the
> system-prompt policy doc). It may **never** read the hidden SQL verifiers, the
> oracle plan, or held-out final state. Cross it and you've built a cheater. Note
> the ReAct terminate condition (`if not response.tool_calls: break`) **is** the
> "agent self-declared DONE" seam — the natural place the stop-gate hooks, but also
> the *weakest* one (see §5).

## 4. DOS is a control loop AROUND every step — not a stop-gate

A 34-step episode is a **stream of distrust moments**. The placements, mapped to
`execute()`:

| # | When in the loop | Syscall | Evidence (env-authored?) | Target failure / verifier |
|---|---|---|---|---|
| **P0** | episode start | `refuse` (+ scope) | task text + policy doc | feasibility (30-task subset) + declare obligations |
| **P1** | **before each mutating call** | `believe_under_floor` on **args** | prior tool **results** ✅ | **Incorrect ID Resolution / Missing Prereq** → Integrity |
| P1b | before each mutating call | `believe_under_floor` (presence) ⚠ | ids in prior results + task text | dangling-FK writes (prereq-row present?) |
| **P2** | **after each tool result** | `liveness`-shape fold | tool_result delta ✅ | horizon decay (spin/stall) |
| P3 | at a state transition | `intent_ledger` + `believe_under_floor` | result status + policy doc | **Cascading State Propagation** (mandated follow-ups) |
| **P4** | at a sub-goal boundary | `believe_under_floor` (read-probe) | a read-tool SELECT ✅ | silently-failed write, caught early |
| P5 | intercept the `break` | `completion` (refutation-guard) | the P4 ledger + probes | **Premature Completion Hallucination** |
| P6 | on max_iterations/error | `resume` | read-confirmed fossils | re-enter residual vs return half-done |
| P7 | across episodes | `judges` + `reasons.extend` | violated policy clauses | learned refusals (only if sweep allows carryover) |

> **⚠ P1b syscall correction (source-verified).** `arbiter.arbitrate` admits on
> tree-**disjointness** — grant iff a region is *free* of collision with live
> leases. The prereq gate needs the **inverse**: admit iff a prereq row is
> *present/attested*. The conjunctive floor `arbitrate` cites refuses-more on
> *collision*, not *absence*. The correct primitive is **`evidence.believe_under_floor`**
> (presence-attestation), which still gives the refuse-MORE-only floor. Sound gate,
> wrong kernel name — re-aim it onto the evidence seam, not the arbiter.

**The leverage is early + mid, not the end.** P1 (arg-provenance) and P2 (liveness)
read **env-authored** bytes — the gym MCP server's tool RESULTS (`r.gym_server`,
`r.result`), which the judged agent did not author — and sidestep circularity
entirely. P5 (the end-gate everyone reaches for first) is the **weakest**: by then
the only fresh signal is the agent's own "I'm done" narration — AGENT_AUTHORED, on
the forgeable floor, structurally filtered out by `believe_under_floor`
(`evidence.py:444-449`). A pure END gate is a **mirror-verifier** (docs/141): it
reads generation-#2-about-generation-#1 and adds nothing. P5 is only non-circular if
**P4** has been laying down env-authored checkpoints all along — and even propped up,
it should be **demoted to a refutation-guard** (block the `break` only when a
non-forgeable witness *positively REFUTES*, never on mere absence, ≤1 re-injection),
folded into P4, never shipped standalone.

### Per-placement survival verdicts (adversarial pass, source-verified)

Only **P4 SURVIVES** clean; all others are **WEAKENED** (none DEAD). The honest
per-placement moves (ESTIMATE):

| P | Verdict | Enforce | Honest move (ESTIMATE) | Why weakened |
|---|---|---|---|---|
| P0 | WEAKENED | literal-refuse only | −1 to +1pp | feasibility refuse real but narrow; the obligation-denominator half is model-authored (forgeable) — **drop it** |
| **P1** | WEAKENED | withhold/nudge | −0.5 to +1.5pp | real catch, but task-text ids must be a first-class env source or legit calls false-block |
| P1b | WEAKENED | narrow hard-block | +0.5 to +2pp | only if hard-enforce stays FK-shaped **and** env-absent |
| **P2** | WEAKENED | **advisory nudge only** | 0 to +3pp on ≥8-step tail | enforcing-cut false-fires on idempotent re-reads / eventual-consistency polling |
| P3 | WEAKENED | block-break-on-undischarged | +1 to +3pp on doc-stated-transition slice | weaker on Flash-Lite |
| **P4** | **SURVIVES** | REFUTED→block (advisory-first) | +0.5 to +2pp; −1 to −2pp tail | strongest by byte-inequality (gym-DB-authored read-probe), but cost=medium + double-create tail on consistency lag |
| P5 | WEAKENED | refutation-guard only | 0 to +1pp; negative tail | mirror-verifier alone; fold into P4 |
| P6 | WEAKENED | re-dispatch residual | 0 to +2pp on >12-step tail (~+0.5 mean) | numerator env-authored, denominator model-shaped |
| P7 | WEAKENED | RECORDS_ONLY | **+0.0pp default** (no carryover) | +0 to +1pp only if a carryover channel is threaded; mint-trigger is model inference |

## 5. The honest ceiling — what the adversarial pass established

A multi-agent adversarial audit (3 workflows, ~40 agents) converged on a **deflating
but honest** picture. Accept these:

1. **Avg Success Rate delta ≈ 0pp** (range −1 to +1) as-shipped, for a cheap model.
   Two independent reasons each suffice:
   - **No planner.** The +14–35pp lever is strategic reasoning; DOS owns **0%** of
     it by doctrine ("the phased-plan workflow is host concern, not kernel").
     *Worse:* naive `completion`-residual re-dispatch around a planner-less agent
     risks the paper's own **decomposing-orchestrator regression** (CSM 16.2% vs
     16.7% baseline) — floor here is "0 to slightly negative."
   - **The SQL scorer is already a non-forgeable final-state oracle** — *exactly*
     the distrust adjudication DOS would supply. So scoring-time `verify()` is
     **redundant**; catching a lie *earlier* adds no passing run unless the agent
     had more *correct* steps to take.
2. **Every in-band PEP requires forking the harness.** This is a ServiceNow ReAct
   loop calling MCP tools directly — **no Claude-Code Stop-hook event** (what
   `claim_extract` expects) and **no lease consult** before acting. So `dos hook
   stop` `{ok:false}` and `arbitrate()` refusal bind **only inside `dos_react`**.
   (Which is fine — `dos_react` *is* that fork. But it is a fork, state it.)
3. **The liveness sensor must be rewired.** `liveness`/`resume` read forward delta
   from **git commits / journal events**; the benchmark lands **zero commits** (live
   SQL mutations). Without a **DB-state EvidenceSource**, the verdicts degrade to
   abstain/UNRESUMABLE. This is unbuilt and **load-bearing** for any liveness/resume
   rung — run such a rung without it and you measure DOS abstaining (a
   true-but-uninformative null). *(Note: the R1 `arg_provenance` rung does NOT depend
   on this — it folds over tool_results, not git; ship R1 first regardless.)*
4. **State-corruption is the wrong target.** Table 7 says Integrity is agents'
   *strongest* class; `arbitrate`'s predicate (concurrent path-prefix disjointness)
   mismatches the cause (sequential, data-content); a fresh single-agent DB has no
   second contestant. ~0pp.
5. **Crash-resume is designed away** (fresh DB per run, independent pass@1). ~0pp on
   the benchmark; `resume` is the right syscall for the *production* setting the
   benchmark deliberately excludes.

## 5a. The decisive correction — the accountability-laundering trap

A third adversarial pass (kernel-grounded, source-verified) found a flaw in the
optimistic framing that **both** the placement map and the first reconciliation
shared. It is the most important finding in this audit, so state it plainly:

> **A DB read-probe through the agent's own tool is NOT a non-forgeable witness of
> task-satisfaction, even though its bytes are gym-authored.** `os_acceptance` earns
> `OS_RECORDED` because **the kernel runs the process and the OS writes the exit
> code** — the agent cannot author it. But a SELECT through the agent's read tool
> has *split* provenance: the **bytes** ("rows present") are gym-authored ✅, while
> the **predicate** ("is this the row the task *required*?") is **agent-authored from
> agent-visible prose** ❌. `believe_under_floor` (`evidence.py:444-449`) dutifully
> returns `believe=True` because the *bytes* are non-forgeable — but the predicate is
> forgeable-in-the-agent's-favor. That is the **mirror-verifier** (docs/141): the
> agent grading itself with a rubric it wrote, laundered through a transport-layer
> `OS_RECORDED` sticker. The honesty of `os_acceptance` **does not transfer** to a
> wrapper-authored predicate.

This **sinks the completion-gate, resume-mint, db_state-as-truth, and
triggered-obligation bindings as *truth* claims** (P3/P5/P6 and the db_state
EvidenceSource). Worse, they fire *confidently where redundant* (trivially-checkable
effects) and *abstain where needed* (the hard predicates) — and a false "INCOMPLETE,
continue" on one of the 30 refusal tasks **coaxes a write that trips the
zero-side-effect checks**, converting a would-be-correct refusal into a failure on
the benchmark's worst-scored axis.

**The one binding that survives clean: `arg_provenance`.** It checks
*provenance-of-a-string* — "did this id appear in env-authored read output, or did
the model mint it?" — a **clean byte-author question, not a rubric**. The gym
authored the read-result bytes; the agent did not. So `THIRD_PARTY` is *honestly
earned*. It is provenance-checking, not re-grading, so it sidesteps the
mirror-verifier entirely, needs no answer key and no self-authored predicate, and
attacks two *named* failure modes (Incorrect ID Resolution, Missing Prerequisite
Lookup) that feed the Integrity verifier. (`tool_loop ProgressEvidence`/liveness also
survives — but as a **cost** instrument, not a truth claim: it makes no belief claim,
only a stop-economics verdict.)

> **The single biggest trap, named:** do not let any binding mint
> `verified`/`STEP_VERIFIED`/`COMPLETE` from a DB read whose *predicate* the agent
> authored, then dress it in `OS_RECORDED`/`THIRD_PARTY`. The kernel's floor will say
> `believe=True` on the bytes while the predicate lies. The os_acceptance witness is
> honest because **the kernel runs the process**; the moment the wrapper reads
> through the agent's own tool against a self-authored predicate, that honesty does
> not transfer — and pretending it does is the exact disease DOS exists to refuse,
> turned inward.

Two further source-verified deflations from the same pass:
- **The `refusal-gate` / policy-clause registry has no kernel doing work.** "Does the
  policy forbid this?" is an `if`-statement NL-parsing prose in the wrapper; `refuse()`
  contributes a closed *vocabulary*, not an *adjudication*. The conjunctive floor it
  leans on (`admissible_under_floor`) is about **path-region overlap**, which has
  nothing to do with policy-clause prohibition — the wrong floor. No cheat, but no
  kernel-grounded soundness either. (The *target* — write-verb tools from schemas —
  is structural and is the saving grace; the *reason* is heuristic.)
- **The `integrity-arbiter`'s `arbitrate()` half is theater.** The arbiter serializes
  over an **in-process** `live_leases` list; a single-task gym run is **one process** —
  there is nothing to double-book across. The DB-table→glob-region mapping is a costume
  over an admission kernel built for filesystem lanes. What survives is the
  `believe_under_floor` id-gate, i.e. `arg_provenance` again.

## 6. Where the primary source pushes BACK on the skeptic (reconciliation)

The first skeptical workflow ran *before* the Table-7 + policy-grammar evidence was
pulled. Two of its "≈0pp, redundant" verdicts are too harsh given the primary source:

- **Premature Completion Hallucination is not pure redundancy.** The paper's own
  wording — "declaring completion **before all required steps have been executed**"
  — describes an agent that *had more correct steps queued and stopped early*.
  Forcing continuation there does **not** need a new plan; it needs the agent to
  **finish the plan it was already executing**. That is a *real* (if small) success
  delta on the Task-Completion verifier class, not zero — **conditional on P4
  env-authored checkpoints** making the residual real (not the mirror-verifier).
- **Policy Compliance is DOS's best shot, and it's mechanism not reasoning.** The
  skeptic excluded refusal as "the model's feasibility reasoning, out of DOS's
  mechanism." But Table 7 makes Policy Compliance the **worst, most-concentrated
  weakness after planning** (ITSM 30%, CSM 45.5%, HR 50.4%), and §1c shows the
  policy contract is a **declared precondition grammar** ("first call a permission
  check"; "refuse and state the specific policy reason"). That is `refuse` +
  **precondition-provenance** (P0/P1) — *exactly* DOS mechanism, not planner
  reasoning. This is the **single most defensible success-relevant axis**, and it
  was under-credited.

> Net reconciliation: the headline (**~0pp on Avg Success Rate as-shipped, no
> planner, scorer-redundant, harness-fork required**) stands. But the *distribution*
> of the small non-zero residue is **not** "only cost/efficiency" — it concentrates
> on the **Policy-Compliance verifier class** (the benchmark's worst) via a
> mechanism (declared-precondition refusal) DOS genuinely owns, plus the
> finish-the-started-plan slice of premature-completion. Both are small, both are
> conditional on env-authored evidence, neither is zero.

## 7. The obvious DOS additions this benchmark demands (ranked, after refutation)

All are **driver/config extensions of existing mechanism**, none a new kernel verb,
**none a planner** (out of scope by design). Ranked by *what survives the
accountability test* (§5a), not by intuition:

1. **Tool-argument provenance predicate — THE survivor (`dos.predicates` driver).**
   An arg referencing an ID/FK is believable only if that value appeared in a **prior
   tool result** — byte-inequality (docs/141) at the argument grain. This is the one
   addition whose non-forgeability claim the kernel's floor **honestly underwrites**
   (provenance-of-a-string is a clean byte question, not a self-authored rubric).
   Attacks *Incorrect ID Resolution* + *Missing Prerequisite Lookup* → the Integrity
   verifier. Pure in-process fold over already-accumulated tool_results — no probe, no
   answer key. *(driver; medium; the keystone — ship this first and alone.)*
2. **`tool_loop` ProgressEvidence reader (`dos.evidence`/liveness driver).** A non-git
   liveness reader over the in-process tool_result stream (forward-delta + iteration
   count as a time proxy). Survives **as a cost instrument, not a truth claim** — it
   makes no belief claim, so it cannot launder. Attacks horizon-decay *budget*, not
   score (~0–1pp score, real $/task win on a thrashing cheap model). *(driver; small.)*
3. **DB-state `EvidenceSource` driver — infra, but handle with the §5a warning.** The
   `dos.evidence_sources` entry-point group already exists (no new seam). Useful for
   the *cost* reader above, but **must not** be used to mint `verified`/`COMPLETE`
   from a wrapper-authored predicate (that is the laundering trap). Hard constraint:
   the probe must be **read-only** — a get-or-create style "probe" breaks the 30
   zero-side-effect refusal tasks. *(driver; medium; constrained use only.)*
4. **Policy-clause reason registry for `refuse()` (config).** The system-prompt policy
   doc → a declared `reasons` registry. The *target* (write-verb tools from schemas)
   is structural and sound; the *reason* (which clause forbids what) is an NL
   heuristic with the 660:30 false-block downside (§5a). Net **+1–3pp avg at best, and
   only if precision is near-perfect** — deploy advisory, fire only on exact
   role/permission tokens. *(config + driver; medium; precision-gated.)*

**Out of scope (correctly DROPPED):** a planner / sub-goal decomposer, and NL
policy-clause *inference*. The +14–35pp oracle-plan lever is **not DOS's to close** —
if DOS built the planner it would be a second policy-reasoner subject to the very
forgeability it exists to distrust ([[project-dos-memory-is-an-unverified-agent]]).
That is the honest core of the whole audit: the benchmark's headline gap is **out of
scope by design.**

## 8. The experiment — a one-variable-at-a-time ladder

> **Design rule (why this section was rewritten):** an earlier draft bundled
> `arg_provenance` + the liveness cost-reader into a single "minimal" arm. That is a
> **confound on day one** — if the arm moves, you cannot say which mechanism moved it,
> and the two even read on *different axes* (score vs cost). The corrected design is a
> strict **ladder: one mechanism per rung, highest-P(win)·cleanest-attribution first,
> and rung N+1 is run ONLY if rung N is net-positive AND its delta is attributable to
> its own verifier class.** A rung that regresses feasible tasks is a **STOP**, not a
> "tune and keep going." Same-mechanism variants (nudge vs hard-block) are **mutually
> exclusive** within a sweep — the block confounds the nudge's attribution, so block is
> tested later as a *replacement* to read the block→nudge marginal.

**Fixed across every rung** (the controls): `llms=[gemini-flash-lite]`,
`domains=all 8 + infeasible`, **`mode=oracle-TOOL` never `oracle-PLAN`** (oracle-plan
injects the +14–35pp human plan — the one variable DOS does not touch — and would mask
whether the *loop* changed anything), public ~690-task split (~660 feasible : 30
infeasible), `temperature=0.0`, same `max_iterations`, **3 seeds/run** (the per-rung
deltas are single-digit pp — you need the variance to claim them). **Zero edits to the
SQL verifiers or `compute_score.py`** — that separation is what makes each rung citable.

**The ladder (run top-down; do not skip; each rung is its own sweep):**

| Rung | Arm | The ONE variable vs the rung below | Reads on | Promote to next rung iff |
|---|---|---|---|---|
| **R0** | `react` baseline | — (the control) | all metrics | always (it's the baseline) |
| **R1** | `dos_react` + **`arg_provenance` (advisory nudge only)** | adds id-provenance nudge | **Integrity verifier slice** (primary), avg success, feasible-task rate | Integrity UP **and** feasible-task rate **not down** |
| **R2** | R1 + **`arg_provenance` → HARD-BLOCK** (replaces the nudge) | nudge→block on the *same* mechanism | Integrity slice **+ feasible-task regression** + composite-id livelock rate | block beats nudge on Integrity **and** feasible-task rate still not down |
| **R3** | best-of-{R1,R2} + **P0 literal-token policy-refuse** | adds the policy/refusal gate | **Refusal subset** (30 tasks) + **Permission verifier** slice + feasible-task rate | Refusal UP **and** feasible-task rate not down |
| **R4 (cost, parallel track)** | best-score-arm + **liveness cost-cut (no-belief)** | adds the SPINNING cut | **cost/task + iterations-to-stop** (NOT score) | cost/failed-run DOWN **and** feasible-task rate not down |

**Why this order.** R1 first because `arg_provenance` is the **only** binding the
kernel floor honestly underwrites (§5a), it is **free** (in-process membership over
tool_results already in hand — no extra LLM/MCP call), it is **advisory** (nudge, not
block — near-zero false-block exposure), and it targets a **single** verifier type, so
its delta is cleanly attributable. R2 isolates the *marginal* of hard-blocking the
same mechanism — the riskiest knob (composite-id livelock), so it is gated behind R1
proving the signal exists at all. R3 (the policy gate) is deferred because its *reason*
is an NL heuristic against the brutal 660:30 ratio — only worth adding once the safe
gains are banked. R4 is a **separate track on the cost axis**: liveness makes **no
belief claim** (it cannot launder, §5a), so it can never move score and must not be
read against a score metric — give it its own arm and its own (cost) readout so it
never confounds R1–R3.

**Per-rung primary readout (the attribution discipline):** each rung is judged on the
verifier slice it *targets*, not on avg success alone. A +2pp avg that is **not** in
the Integrity slice for R1 means something *else* moved (noise, or a second-order
effect) — treat it as a non-result, not a win. `compute_score.py` aggregates; you must
read the **per-verifier-type breakdown** (Task Completion / Integrity / Permission)
that Table 7 of the paper exposes, or instrument it.

**Pre-registered predictions (ESTIMATE, falsifiable, per rung):**
- **R1:** Integrity slice **+2 to +6pp**; avg success **+1 to +3pp** (optimistic +4);
  Task-Completion **flat** (the gate forces a lookup, it does not supply a plan);
  feasible-task rate **flat**. *R1 is the load-bearing rung — most of the whole
  DOS delta is predicted to live here.*
- **R2:** Integrity **+0 to +2pp marginal over R1**; **watch composite-id livelock**
  (a legit derived id read as minted → re-read loop → max_iterations timeout). Most
  likely outcome: **R2 ≈ R1 or slightly worse → ship R1's nudge.**
- **R3:** Refusal subset **+3 to +8pp** *if* precise; **+0 and feasible-regression if
  not**. The single most likely rung to **fail its gate**.
- **R4:** cost/failed-run **down**; horizon-decay curve **flatter**; score **~0**.

**The kill-signal (same at every rung): feasible-task regression.** At 660:30, a
~1–2% false-block (7–13 tasks) **erases the entire refusal gain**. If any rung drops
feasible-task success vs the rung below, **STOP and ship the prior rung** — do not
tune-and-continue (tuning on the test split is how you fool yourself).

**Honest expected landing:** **R1 ships** (free, ~+4pp optimistic on Integrity-heavy
domains, a real Pareto-frontier move — the whole closed-source field spans only ~9pp,
so +4pp is a multi-rank jump); **R2 and R3 likely do not clear their gates** for a
cheap model; **R4 ships on the cost track** independently. The defensible V1 is
plausibly **R1 alone** — and that is fine: one free, kernel-honest mechanism with a
clean attributable gain is a *better* V1 story than a bundled stack whose win nobody
can source.

**Files touched (all rungs):** one orchestrator subclass + registry entry, one
`conf/llm/gemini-flash-lite.json`, one `conf/ray/experiment.json` per rung. Each
mechanism is a flag on the subclass so rungs differ by **one config line.**

## 9. Bottom line

Three independent adversarial passes (~45 agents) converge on the same honest answer.

**On the published leaderboard metric, DOS is a small, real, narrowly-concentrated
delta — not a leaderboard move.** ESTIMATE **+1 to +3pp avg success** (optimistic
+4–5), almost entirely from **one binding** (`arg_provenance`) on **one verifier
class** (Integrity Constraints), and it **never crosses 40%**. Two structural facts
cap it: (1) the dominant ~45–55pp of the gap is **strategic planning**, which DOS
**cannot** touch by design (no planner — and building one would make DOS a second
unverified reasoner, the very thing it refuses); and (2) the benchmark's SQL scorer
is **already** the non-forgeable final-state oracle DOS would supply, so DOS adds
nothing at *scoring* time — only in the *loop*.

The audit's sharpest lesson is inward: most of the "obvious" gates (completion,
resume, db_state, triggered-obligations) are a **mirror-verifier wearing an
`OS_RECORDED` costume** — the agent grading itself against a self-authored predicate,
laundered through a transport-layer non-forgeable tag. They **fail DOS's own
byte-inequality axiom** (docs/141), and on this benchmark they actively *backfire*
(a false "not done, continue" on a refusal task coaxes a side-effecting write that
fails the worst-scored axis). **The kernel's floor is honest about bytes, not about
predicates.** Only provenance-of-a-string (`arg_provenance`) and a no-belief cost
verdict (liveness) survive contact with the kernel.

So: **yes, run it as `dos_react` (a clean 4th orchestrator, no verifier fork); ship
`arg_provenance` first and alone; expect a low-single-digit Integrity-slice gain and
a real cost win, not a headline jump.** The single most defensible sentence:
**DOS hardens the execution substrate *under* a cheap agent's plan — catching minted
IDs and cutting doomed loops — it does not supply the better plan the benchmark is
actually starved for, and it must not pretend a self-authored DB check is a
non-forgeable witness.**

## 10. Why a "small" delta is actually a strong V1 (the value framing)

Do not let "+1–3pp, optimistic +4" read as weak. In this benchmark's geometry it is a
**Pareto-frontier move**, which is the axis the paper itself foregrounds (Figure 1):

- **The entire closed-source field spans ~9.4pp** (Opus 37.4 → Gemini-3-Pro 28.0), and
  adjacent models are separated by **0.1–1.8pp**. A clean **+4pp is ~half the whole
  competitive spread** — a multi-rank jump past several *named frontier models*.
- **Gemini-3-Flash already wins the cost/perf Pareto frontier** (31.9% at $0.03/task).
  A **free** wrapper (`arg_provenance` is in-process, no extra call, ~1.0× cost) that
  adds points at ~zero marginal cost **pushes the frontier outward** — a stronger claim
  than "a model improved." The V1 pitch is: *same cheap model, one free orchestrator
  wrapper, +Npp concentrated on the Integrity axis — a frontier move on a benchmark
  whose whole field spans 9pp.*

**The two asterisks that survive even at +4pp** (state them, don't bury them): (a) the
+4 is the **optimistic** end of an ESTIMATE and lives mostly in the **Integrity verifier
slice** — report it *per-verifier-type*, not as a headline avg, or it reads as an
overclaim; (b) "free" holds **only for the advisory `arg_provenance` nudge** — the
moment you ship blocking gates, the 660:30 ratio puts the "free" at risk. Keep V1 to the
survivor + nudge-don't-block and both the "+4" and the "free" are defensible.

## 11. Context + pickup checklist for the next agent

**State as of this doc (2026-06-04, `2d48df4`):** design-only. **Nothing shipped under
`src/dos/`.** No `dos_react` orchestrator exists; no `arg_provenance` predicate exists;
the EnterpriseOps-Gym repo is **not** cloned locally. The audit is complete and the
ladder (§8) is the build/test plan.

**The operator's framing (load-bearing):** a free/low-cost mechanism that shows even
**~+4pp is a real V1 win** here (see §10) — so the goal is **prove the smallest honest
mechanism cleanly**, not stack mechanisms for a bigger bundled number. Ship `arg_provenance`
(R1) first, alone, advisory.

**The one rule you must not break (§5a):** never mint `verified`/`COMPLETE`/`STEP_VERIFIED`
from a DB read whose *predicate* the agent authored, then tag it `OS_RECORDED`/`THIRD_PARTY`.
That is the mirror-verifier (docs/141) and it **backfires** on the 30 refusal tasks. The
kernel floor is honest about **bytes**, not **predicates**. `arg_provenance` is safe because
it checks provenance-of-a-string (a clean byte-author question), not a self-authored rubric.

**Build order (each step is one PR-sized unit):**
1. **`dos.predicates` `arg_provenance` driver** — pure: given a tool-call's args + the
   accumulated prior tool_results, return believe/abstain on whether each id/FK-shaped
   arg value appeared in a prior **read** result. Containment-match to avoid the
   composite-id livelock. Unit-test it in isolation (no harness). *This is the keystone
   and it is testable with zero benchmark access.*
2. **`dos_react` orchestrator subclass** (lives benchmark-side, NOT in `src/dos/` — it's
   a consumer): subclass `AgentOrchestrator`, override the per-tool-call path to consult
   the predicate and, on abstain, **inject a nudge ToolMessage** ("resolve `<id>` via a
   read tool first") rather than dispatch. Register as `--orchestrator dos_react`.
   Mechanisms behind per-flag switches so R1–R4 differ by one config line.
3. **Run the ladder (§8) R0→R1** on the public split. Read the **per-verifier-type**
   breakdown. Promote only on the gate.
4. Only if R1 clears: R2 (hard-block marginal), then R3 (policy gate), then R4 (cost track).

**Unbuilt dependencies to remember:** the **DB-state EvidenceSource** (the read-only
witness) is needed for R4's liveness reader and for any future P4 checkpoint — the
`dos.evidence_sources` entry-point group already exists (`evidence.py:493`), but no DB
backend is written. **Do not** use it to mint belief from an agent-authored predicate
(the §5a trap). `arg_provenance` (R1) does **not** need it — ship R1 without it.

**Cross-refs:** byte-inequality axiom = docs/141; what-is-truth throughline = docs/138;
EvidenceSource seam = docs/121; PDP-no-PEP doctrine = docs/99 + the security-10x/100x
memory. The EnterpriseOps-Gym primary source is arXiv 2603.13594 (Table 7 = per-verifier
pass rates; §4.4 = the four named failure modes; Appendix C = the policy-doc grammar).

## 12. What was actually built and run (2026-06-04 — the SHIPPED reality)

The audit above was the plan. It was executed. Outcome, honest:

**Shipped (kernel + consumer).**
- `src/dos/arg_provenance.py` — the pure R1 fold `classify_call(ToolCall, PriorResults,
  policy) -> ProvenanceVerdict`. Byte-author-only (no satisfaction predicate — the §5a
  trap is unrepresentable: the corpus is `EnvBlob`s tagged `TOOL_RESULT`/`TASK_TEXT`, with
  **no `AGENT_AUTHORED` member**). `dos arg-provenance` CLI verb (exit 0=believe,
  3=UNSUPPORTED). **39 unit tests** incl. real-data regressions; full suite **1947 green**.
- `benchmark/enterpriseops/` (consumer, imports `dos`) — `dos_react`, the 4th gym
  orchestrator (nudge-on-mint, ≤1 per arg-value, fail-open write-verb classifier); a
  faithful non-rigged simulator; the A/B + scorer + deterministic recall harness.

**Run (real harness, real model).** Cloned `ServiceNow/enterpriseops-gym`, 4 Docker MCP
servers (email/itsm/csm/hr, host-port→container 8005), hidden SQL verifiers untouched,
`gemini-3-flash-preview` (the paper's Pareto comparator), a seeded 15 % FK-heavy slice
(55 tasks) paired through `react` vs `dos_react`. R0 baseline: success 36.4 %,
verifier-pass 73.9 %, ~7 tools/task (in-band).

**The three results that matter (all honest):**
1. **The detector is deployment-safe and high-recall** — measured deterministically over
   the real trajectories (variance-free): **0.00 % false-nudge on 249 resolved calls,
   ~83 % recall on genuine injected mints.**
2. **A strong model doesn't mint.** gemini-3-flash resolves its FK ids (reads first) →
   **0 real mints** → the nudge correctly stays silent → no harm. This *confirms* §1's
   Table-7 read ("Integrity is agents' strongest class — less headroom than intuition").
3. **The real run hardened the kernel.** The first detector false-flagged 66/249 real
   calls (verbatim-resolved ids, UUIDs, datetimes, prices) → a live **−9 pp regression**
   (the §8 kill-signal, observed). Four real-data fixes (whole-value direct match;
   UUID-whole; datetime/epoch filter; bare-int-FK recall + a quantity-name stoplist) took
   it to **0 false flags at ~83 % recall**. The "use hashing?" question resolved to **no —
   direct containment is exact and safer** (a resolved id is the same bytes the env wrote).

**The honest position.** On the published leaderboard metric the delta for a *strong*
model is ≈0 (it doesn't mint — the audit's own ceiling). The mechanism's value is on the
*cheap minting* agent the audit is about, where the catch→nudge→recover loop yields a
clean, attributable Integrity-slice lift (the simulator, running the same `classify_call`
whose catch rate matches the measured 83 %, shows **+11 pp** — a simulated estimate
calibrated to that measured catch rate, not a live-model measurement — emergent and
feasible-flat).
DOS hardens the substrate *under* a cheap agent's plan; it does not supply the plan, and it
never pretends a self-authored DB check is a witness. **Full measured write-up:
`benchmark/enterpriseops/RESULTS.md`.**

## 13. Doubling down on the intervention-cost lesson (what DOS should add next)

The live run's load-bearing finding (RESULTS.md "⚑ KEY DATA POINT"): a **sound** verdict
(0 % false-nudge, 83 % recall) was **net-harmful** (−9 pp) because the *intervention*
(skip-the-dispatch + re-prompt) derailed the model mid-plan — even on a true-positive
catch. **Detector-soundness and intervention-safety are orthogonal properties.** DOS has
spent its whole history hardening the *verdict* (the ORACLE→JUDGE→HUMAN ladder, the
forgeability axiom). This benchmark says the next frontier is hardening the *actuation* —
which is squarely the docs/99 / docs/126 PDP-vs-PEP seam. Concretely:

1. **A first-class `intervention` axis (the immediate double-down).** Today a consumer picks
   skip / hard-block / warn ad hoc. Make it a typed, ranked, kernel-described ladder —
   `OBSERVE` (record only) ‹ `WARN` (annotate, still dispatch) ‹ `DEFER` (skip this call,
   let the agent retry) ‹ `BLOCK` (refuse until resolved) — with the **default the least
   disruptive that still informs** (WARN), escalation opt-in. This is the actuation dual of
   the refusal vocabulary: the kernel already has a *closed reason set*; it should have a
   *closed intervention set* with a documented disruption-cost ordering. The live data is
   the calibration: WARN should be the floor because SKIP cost −9 pp on a model that
   recovers only ~75 % of the time.

2. **Measure the intervention, not just the verdict (the eval gap).** Every other DOS axis
   ships an eval harness (`judge_eval`, `overlap_eval`). The arg-provenance work shipped a
   *detector* eval (precision/recall) but the benchmark showed the **decisive** number is
   the *net task delta per intervention* — caught × recovered × (1 − disruption-cost). Add
   an `intervention_eval`: replay a run, and for each verdict score not "was it right?" but
   "did acting on it help or hurt the run?" The friendliness instrument for the PEP, the
   way `overlap_eval` is for admission.

3. **Confidence-gated escalation (the precision→disruption coupling).** A verdict carries a
   rung (`matched_in`, `components_unmatched`). Couple intervention strength to verdict
   confidence: a *whole-value-absent* id (high-confidence mint) earns a DEFER; a
   *one-component-missing* composite (lower confidence) earns only a WARN. This makes the
   disruptive interventions rare and high-precision, which is exactly where the −9 pp came
   from (disruption spent on catches that didn't matter to the verifier).

4. **The non-disruptive enforcement primitive — `BLOCK` without losing the turn.** The
   deepest fix: a PEP that refuses the *minted* call but lets the agent's turn continue
   (return a synthetic "that id is unresolved — here is the read tool" tool-result in place
   of the mutation, so the agent gets a corrective observation WITHOUT a wasted iteration).
   This is the docs/126 `dos apply` gate done right: prevent the bad effect (real PEP) while
   preserving the agent's flow (no disruption tax). It is the one design that could turn the
   −9 pp into the simulator's +11 pp on a real model.

**Next to test (in order):** (a) **ANSWERED — the WARN-only arm recovered the regression:
success −9.1 pp → −1.8 pp and verifier-pass flipped POSITIVE (+1.1 pp), same nudges, fewer
stalls.** WARN beats SKIP by ~7 pp; WARN-only is now the orchestrator default (`DOS_WARN_ONLY=1`,
skip is opt-in). The disruption *was* the problem, not the verdict — the §13 thesis,
confirmed live. (b)+(c) **SHIPPED + ANSWERED on the simulator — the four §13 deliverables are
built** (`dos.intervention`, `dos.intervention_eval`, `dos intervention-eval`, the consumer-side
non-disruptive `BLOCK`; full design + reconciliation in `docs/144`). The typed ladder's
measured cost order is **OBSERVE ‹ WARN ‹ BLOCK ‹ DEFER** (BLOCK preserves the turn, DEFER
spends it — the correction the build made to §13.1's prose). On the simulator A/B
(`python -m benchmark.enterpriseops.intervention_ab`, 690×3): **BLOCK net −0.13 vs DEFER net
−0.53 — a +0.40 swing**, the turn-preserving PEP beating the −9 pp skip posture on identical
caught mints, with feasible-rate held. Confidence-gating helps *additionally* only when the
verifier-irrelevant catches are also lower-confidence (confidence ≠ relevance — the honest
caveat the eval surfaced). (d) re-run the simulator with the *measured* live recovery rate
(~75 %) and disruption cost, and run the live real-model `BLOCK` arm — the remaining experiment
(the candidate for an actual *positive* real-model delta).

The throughline: **on this benchmark DOS built a sound, forgery-resistant verdict cheaply
(0 % false-nudge over 249 resolved calls, ~83 % recall on injected mints). The
benchmark also showed that is necessary but not sufficient — the next moat is a disruption-aware
enforcement layer that makes acting on a true verdict cost less than the harm it prevents.**
That is a kernel-shaped problem (a typed intervention ladder + its eval), not a planner, so
it stays inside DOS's doctrine.

**→ This is now a full design plan: `docs/144_the-intervention-ladder-and-its-eval.md`** —
the `dos.intervention` closed vocabulary (OBSERVE‹WARN‹DEFER‹BLOCK), `dos.intervention_eval`
(net task delta per verdict), confidence-gated escalation, and the non-disruptive `DEFER`
primitive, with the docs/143 live A/B as the eval's seed fixture. Phases 1–2 are pure kernel,
shippable now; Phase 3 is the load-bearing real-model experiment.
