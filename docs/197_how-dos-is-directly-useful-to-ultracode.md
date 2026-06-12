# 197 — How DOS is directly useful to ultracode

> **An ultracode `Workflow` is a competent *scheduler* and *text-aggregator* with
> no *trust seam*. Its one structural flaw is the fold site — the `${result}`
> template substitution where `agent()`'s self-authored return value becomes
> authoritative input to synthesis with no intervening ground-truth check. DOS is
> the byte-clean referee that adjudicates an ultracode result WITHOUT believing
> the agent, because every shipped syscall reads a *different byte-author* than
> the judged worker: git ancestry, the env tool-result, the lease WAL, or — for
> the dominant real failure here — the harness's own `<synthetic>` rate-limit
> stamp. The agent's "✅ done" string is `AGENT_AUTHORED`, the forgeable floor;
> it can never, by itself, move `verify` to belief.**

This is a mechanism doc in the house style of
[`98`](98_the-orchestrator-is-a-driver.md) (the orchestrator-is-a-driver frame)
and [`128`](https://github.com/anthony-chaudhary/dos-private/blob/master/128_the-ultracode-economics-and-how-the-kernel-saves-spend.md) (the
ultracode-spend frame). Where `98` asks *"can a foreign orchestrator keep the
trust guarantees"* and `128` asks *"how does the kernel save dollars,"* this asks
the third question they leave open: **once an ultracode subagent returns, what in
its return is trustworthy, and which DOS syscall adjudicates it without believing
it?** Every kernel claim carries a `file:line`; every lever is adversarially
adjudicated to its *honest* status; the marketing-optimistic version is discarded
in favor of the verified one. The discipline of
[`128` §9](https://github.com/anthony-chaudhary/dos-private/blob/master/128_the-ultracode-economics-and-how-the-kernel-saves-spend.md#9-honest-limits--what-dos-does-not-save)
is kept: an [Honest-limits §6](#6-honest-limits--every-lever-is-advisory-and-host-realized).

The doc was assembled from a fan-out + adversarial-verification pass over **2305
real workflow subagent transcripts across 131 workflows + 114 workflow scripts**,
plus a line-by-line read of the named `src/dos/` modules. The numbers below are
measured, not asserted.

---

## 1. The frame — the fold site is the one unverified-self-report boundary

A `Workflow` does exactly two things: (1) **schedule** subagents — `agent()` /
`parallel()` (a barrier; a dead thunk becomes `null`) / `pipeline()` (no barrier;
a stage-throw drops the item to `null`), throttled to ≤16 concurrent / ≤1000
total, often hand-staggered into waves; and (2) **aggregate** their *return
values* — the self-authored final text, or a `{schema}`-validated object — by
string-interpolating them into a final synthesis prompt.

Between "the agent returned `X`" and "`X` is authoritative input to synthesis"
there is **no ground-truth check anywhere in the corpus.** When a workflow *does*
"verify," verification is itself another `agent()` — an adversarial-verifier or
judge-panel subagent whose verdict is again self-authored text (model-grading-
model). Across all 114 real scripts, **every** `dos verify` / `dos arbitrate` /
`dos lease-lane` string is *prompt text* handed to a subagent, **never** a call
the orchestrator JS makes; **0/114** scripts shell out via `child_process`.

The organizing invariant is the one DOS is built on (the
[consistency-is-not-grounding](185_native-log-adapters-and-the-actor-witness-split.md)
law, [`116` §2.5](116_the-durable-commons-and-the-constrained-a2a-problem.md)):

> **A verdict is *grounding* only when the byte-author of the evidence differs
> from the judged agent. A subagent re-reading or re-narrating its own output is
> *consistency*, not grounding.**

Every ultracode-specific distrust gap is a different way the fold believes
self-authored (or harness-authored-but-treated-as-agent) bytes. DOS is directly
useful precisely at that fold.

---

## 2. The keystone worked example — the rate-limit that became a "finding"

### 2.1 The byte-for-byte artifact

The dominant real failure is not subtle. **736 of 2305 subagents (32%)** have
their *last transcript line* be a synthetic 429 rate-limit error — the very thing
the workflow received as that agent's result was the error string, not a finding.
These deaths span **45 of 131 workflows (34%)**, and the signal is monolithic:
all 738 synthetic lines are `apiErrorStatus:429` / `error:rate_limit` /
`stop_reason:stop_sequence` — zero other classes. Death concentrates
catastrophically: `wf_516412fb-5cc` lost **168/178 (94%)**, `wf_152c7778-165`
lost **107/118 (91%)**, the keystone's own `wf_2ad42706-e75` was **8/8 (100%)**.

The keystone is pinned byte-for-byte. In

```
…/056be9e3-…/subagents/workflows/wf_2ad42706-e75/agent-a17d385233253e0a6.jsonl  L4
```

the message is:

```json
{ "model": "<synthetic>", "stop_reason": "stop_sequence",
  "error": "rate_limit", "isApiErrorMessage": true, "apiErrorStatus": 429,
  "content": [{"type":"text","text":
    "API Error: Server is temporarily limiting requests (not your usage limit) · Rate limited"}] }
```

The `agentId` is the subagent. But **`model:"<synthetic>"` means the Claude Code
*harness* synthesized this message — the subagent's model did not generate it.**
The `role:"assistant"` is merely the conversation slot, not authorship. In a
`Workflow`, this final-text string is *what `agent()` returns to the
orchestrator*. It is non-null, so it survives `.filter(Boolean)` (used in
**89/114** scripts), and it interpolates verbatim into the synthesis prompt as a
"finding."

### 2.2 Why the fold cannot see it — and why DOS can

The fold reads the *return value*. A dead 429 child and a real negative both
arrive as truthy-or-null; `.filter(Boolean)` collapses them, and the only signal
is a smaller numerator the synthesizer never sees. Worse, real code subtracts
instead of counting: `const failed = SKEPTICS.length - checked.length`
(`audit-rewind-usefulness-wf_4f2bebe8-0b5.js:70`) and
`failed = toDeepRead.length - fits.length`
(`dos-sota-opportunity-scout-wf_39a9b3c4-ceb.js:173`) — a rate-limited null is
counted as "failed" indistinguishably from a genuine disagreement, and the
survivor-only array is fed to the next stage (the steelman is *silently
weakened*). There is **no retry/backoff on the 429 anywhere in the 114 scripts**;
lost work is permanent and silent.

DOS catches this because the catch reads a **different byte-author**: the
harness-authored terminal state (`model=="<synthetic>"` / `isApiErrorMessage` /
`apiErrorStatus==429` / `stop_reason`), one line *before* `.filter(Boolean)`
collapses a death into the same `null` as a real negative. That is grounding, not
consistency — the hard DOS law is satisfied.

### 2.3 The self-referential proof — observed live, in the act of writing this

**This very workflow studying the pathology exhibited the pathology.** On its
first run, `wf_72b5f6a5-9fe` had **4 of its 6 agents die on the identical
`· Rate limited` synthetic error** — two at line 4 (instant death, exactly like
the keystone), yet the `Workflow` tool reported status **`completed`** with
`doc_markdown=null` and `lever_count=0`. The orchestrator's own "completed"
framing hid an empty deliverable. The operator caught it only because the *outer*
agent — reading the budget and the `<failures>` channel directly — noticed the
mismatch between "completed" and "nothing was produced." That is seed example #1,
caught in the act. It is the cleanest possible argument for a result-state
witness at the fold: the orchestrator's `completed` is a self-report; the empty
doc is the un-authored effect; only the second is evidence.

---

## 3. The taxonomy of ultracode-specific distrust gaps

Ordered by how directly DOS catches each one *today*. Every axis is a different
way the fold believes bytes whose author is not the thing being judged-as-real.

- **(A) PARTIAL-RESULT-FRAMED-AS-COMPLETE — the keystone.** A subagent
  terminates abnormally (429, `max_tokens`, budget/agent-cap exhaustion,
  null-thunk-filtered death) but a non-null string still reaches the fold and is
  banked as a finished finding. Overwhelmingly dominant: 32% of subagents
  returned a synthetic 429 *string* as their result. Byte-author of the death is
  the **harness** (`<synthetic>`). Sub-class: null-thunk-dropped +
  denominator-by-subtraction is structurally invisible (`failed = total −
  survivors` cannot tell a dead worker from a real disagreement).

- **(B) UNVERIFIED-SELF-REPORT at the `agent()` return boundary — the general
  frame for (A).** The return value *asserts* an effect; only the un-authored
  effect is evidence ([`116`](116_the-durable-commons-and-the-constrained-a2a-problem.md)).
  The grounding move: demand an external artifact for any actionable claim —
  `verify()` the `(plan,phase)` against git ancestry, or `effect_witness` /
  `believe_under_floor` the claimed world-change against an independent read-back.

- **(C) WEAK / MIXED-MODEL FAN-OUT TRUST — seed example #2.** A weak-model result
  and a strong-model result are structurally indistinguishable strings in the
  same array; no tier tag survives return. *Measured-absent in this corpus* (0
  weak downgrades; only 13 `opus` upgrades) but real in shape. The answer is NOT
  "trust the stronger model more" — it is to adjudicate **all** workers' returns
  against un-authored effects, making tier irrelevant. See [§5](#5-the-weak-model-fan-out--seed-example-2).

- **(D) PARALLEL COORDINATION / COLLISION.** `parallel()`/`pipeline()` branches
  are separate processes; the barrier collects return *values* but never
  serializes *effects*, so concurrent writers double-book a region — detected-
  later-by-`verify`, not prevented. Latent in this read-heavy corpus; **measured
  real on a live frontier fleet** in
  [`190`](190_coordination-measured-and-the-f3-gateability-split.md) (5 cross-
  session same-region collisions at a 10s window).

- **(E) REPEATED / SPINNING SUBAGENTS.** A long-running subagent thrashes the
  same `(tool, args, result)` triple or never advances git state. Keyed on the
  **env-authored** `result_digest` (`tool_stream`) or git/WAL advance
  (`liveness`).

The ruthless cut: **any lever whose only evidence is the subagent's own return
text is consistency and is marked wishful** — a model-judge fed the return
string; `claim_extract` mistaken for a verifier. See [§4](#4-the-lever-table)'s
last group.

---

## 4. The lever table

Gap → DOS mechanism (`file:line`) → byte-author → shipped status → seam → caveat.
Grouped by readiness; **lead with what is useful today.** The recurring honest
truth, stated once: **DOS ships no `Workflow` hooks.** "Shipped-but-unwired-to-
ultracode" means *the kernel verdict is real, pure, byte-clean, and callable via
CLI/MCP, but 0 workflow scripts call it* — the wiring is a workflow-author's
stage, not a kernel build. (See [§6](#6-honest-limits--every-lever-is-advisory-and-host-realized).)

### 4a. Shipped + byte-clean + live-binding exists (closest to useful today)

| Gap (ultracode) | Mechanism (`file:line`) | Byte-author | Status | Seam | Caveat |
|---|---|---|---|---|---|
| A long-running subagent re-issues the same `(tool,args,result)` triple N times — loop-thrash / eventual-consistency poll | `tool_stream.classify_stream` (`tool_stream.py:285`); repeat-identity key (`tool_stream.py:199`); live binding `posttool_sensor.step_from_event` (`posttool_sensor.py:200`) | **ENV** — `result_digest` is authored by the tool/MCP server; the agent did not author the *identity* of its repeated env-results (`tool_stream.py:40`) | shipped; live binding exists (single CC session only) | bind `dos hook posttool` to each subagent's tool stream; a `REPEATING` verdict attaches a turn-preserving WARN | the only production caller today is **one** CC session keyed by host `session_id`; **0** subagent/sidechain records exist, so thrash-in-a-fan-out is unconfirmed. Out of scope for the 429 case (a synthetic stop is an assistant text record, never a `tool_result`). Advisory: PostToolUse fires *after* the tool ran — WARN only, never a cut |

### 4b. Shipped + byte-clean, but no ultracode caller (the bulk of the value)

| Gap (ultracode) | Mechanism (`file:line`) | Byte-author | Status | Seam | Caveat |
|---|---|---|---|---|---|
| A confidently-narrated success the world does not corroborate (and a truncated answer that still parses) is folded as real | `effect_witness.witness_effect` (`effect_witness.py:169`) — `CONFIRMED/REFUTED/UNWITNESSED/NO_CLAIM`, trust capped by `evidence.believe_under_floor` (`evidence.py:412`) | the **read-back witness** (fresh GET / state-diff / OS exit code / git existence) — a surface the agent did not control; the claim is `AGENT_AUTHORED` (forgeable floor, `evidence.py:53`) | shipped-but-unwired | extract the claim at the boundary, gather a read-back via a `drivers/*` witness, fold only `CONFIRMED`; surface `REFUTED` as a visible silent-success | *the* check whose value **grows** with model strength (`effect_witness.py:5`) — but it needs a checkable effect claim + a driver read-back. Inert for a pure-text research return with no world effect |
| A subagent claims it shipped/landed a phase; the "✅ done" is folded with no check the commit exists | `oracle.is_shipped` → `verify()` (`oracle.py:747`); rung grading `oracle.py:1046` | **git** ancestry + files-touched + run registry — not the agent's narration | shipped-but-unwired (CLI `dos verify`, MCP `dos_verify`) | after a build/ship subagent returns, shell `dos verify <plan> <phase>` and fold only `SHIPPED`; route `NOT_SHIPPED` to the residual | applies **only** to git-effect deliverables (~20% of this corpus's subagents even touch `git commit`). **Must pin the rung to registry/file-path**: the grep-SUBJECT rung rests on the agent-authored commit subject and is forgeable via `git commit --allow-empty` — only `file-path` is non-forgeable (`oracle.py:1031`) |
| `failed = N − survivors.length`; survivor-only arrays fed downstream; 4/7 framed as 7/7 | `completion.classify` (`completion.py:172`); `convergence` `THRASHING/STARVED` (`completion.py:365`) | residual = declared − **git-ancestry-verified**, never declared − self-reported (`test_completion.py`: a `STEP_CLAIMED` stays in the residual unless git confirms) | shipped-but-unwired (CLI `dos complete`) | compute a coverage verdict over `{declared N, witnessed-live-returns}` and **feed it into the synthesis prompt** (today coverage is only `log()`-ed, never handed to the synthesizer) | the *strong* form needs declared steps + committed artifacts (the intent-ledger/ancestry rung) the fan-out doesn't produce; for read/research fan-outs only the **cheap count gate** applies, which itself needs the §4c terminal-state witness to tell DEAD from genuine-negative. It reports coverage; it does not re-run dead workers |
| Two concurrent file-writing subagents double-book a region | `arbiter.arbitrate` (`arbiter.py:146`); `overlap_policy.admissible_under_floor` (`overlap_policy.py:181`) — a lying/buggy policy can only refuse-MORE | the live **leases** (folded from the WAL via `lane_journal.replay`) + requested file-tree geometry — never an agent claim | shipped-but-unwired (CLI `dos arbitrate`/`dos lease-lane`, MCP `dos_arbitrate`) | before `parallel()`-launching N writers, shell `dos lease-lane acquire` per branch BEFORE launch and gate on the exit code; launch only those that acquire | a bare `dos arbitrate` is pure and persists nothing — without the `lease-lane` WAL **write-back** siblings still race a stale view. Guarantee is over **declared** regions only; DOS has **no PEP** (`enforce.py` is a proposal seam) — a worker writing outside its declared tree escapes the lease. Collision is **measured real** on a live fleet ([`190`](190_coordination-measured-and-the-f3-gateability-split.md)) |
| A subagent narrates "making progress" while git/WAL state does not move; a wave silently stalls mid-fan-out | `liveness.classify` (`liveness.py:227`) over `ProgressEvidence` (`liveness.py:135`) | **git** commits-since-start + the lane-journal's own append `ts` (never the copy-prone self-reported `heartbeat_at`) | shipped-but-unwired (CLI `dos liveness`/`dos status`, MCP) | poll at the orchestrator's wave boundary; `SPINNING/STALLED` gates the wave instead of awaiting a barrier that returns a partial | has signal **only** for a subagent wired to the DOS spine (run-id + start-SHA + commits or a WAL heartbeat). The dominant ultracode subagent is a pure read/research worker (~16% of 200 sampled ran `git commit`) → reads ADVANCING-young then STALLED with no discrimination. The budget/429 case is harness-authored and caught by §4c, **not** by liveness (which never reads `stop_reason`) |
| 94% of a wave dies on a 429 burst; lost work is permanent and silent; the successor restarts from scratch or from the dead run's self-report | `resume.resume_plan` (`resume.py:265`) over a `run_id`-keyed `intent_ledger`; `AncestryFacts` re-adjudicated at read | the verified/done set is **git ancestry + file-path footprint re-check**, not the dead run's `STEP_CLAIMED` (`resume.py:113`: stored `via` is "an UNAUTHENTICATED HINT") | shipped-but-unwired (CLI `dos resume`, MCP) | give each subagent a `run_id`-keyed ledger to declare steps; after a wave death, compute the residual and re-dispatch only the unfinished work | the **write side is inert**: no production code writes an `INTENT`/`STEP_CLAIMED` — over an empty ledger `resume_plan` returns `UNRESUMABLE "no INTENT"` (`resume.py:323`). Recovers only **committed, region-pinned** work — never in-context-only research a dead text agent never persisted |
| No measurement of whether any catch above adds signal or cost across the fleet | `firing_label.label_firings` (`firing_label.py:328`); `fleet_roll` (mints zero labels) | the **git-minted** run outcome (residual + commits), never `claimed_sha` (`firing_label.py:23`) | shipped (importable fn only — no CLI/MCP verb) | a *measurement* seam, not a runtime gate: score lift + false-alarm over the corpus before trusting any lever | live ultracode firings stamp **no `run_id`** (`CID_RUN_ID` unset in CC; 0/65 recorded firings carry one) and there are **0** `run.json` frames to join against → every live firing collapses to `BROKEN_LINK`. Validated against the frozen Toolathlon corpus (+173 net-new), **not** the ultracode fleet |

### 4c. Named gap (strong evidentiary basis, not yet built anywhere)

| Gap (ultracode) | Mechanism (proposed) | Byte-author | Status | Seam | Caveat |
|---|---|---|---|---|---|
| **The keystone.** 736/2305 (32%) subagents return a synthetic 429 error *string*; it passes `.filter(Boolean)` and folds as a finished finding | a result-state classifier over the subagent transcript's **last** message: `stop_reason` / `model=="<synthetic>"` / `isApiErrorMessage` / `apiErrorStatus==429`. Shape-analogous to `benchmark/toolathlon/trajectory.py:494` `terminal_error_fired` + the refusal envelope `wedge_reason.envelope_is_refusal` (`wedge_reason.py:249`) | the **HARNESS** — the synthetic line is `model:"<synthetic>"`, pinned at `agent-a17d385233253e0a6.jsonl L4`, NOT the subagent | **named-gap** | inside the `.filter(Boolean)` fold (89/114 scripts): replace `results.filter(Boolean)` with a partition that routes any transcript whose terminal line is synthetic/429 to a DEAD bucket, count it in the denominator, refuse to fold it | **no `src/dos` module classifies a transcript terminal-state today.** The existing `_STRUCT_ERR` grammar (`trajectory.py:340`) does **not** match the 429 string (leads with "API Error:", not "Error:") and walks only `role=="tool"` messages — so this needs a **new grammar over a new message role**, real new kernel code, not a drop-in reuse. Catches abnormal-termination only; a well-formed-but-empty answer still needs `effect_witness` |

### 4d. Wishful — DO NOT (the consistency trap)

| The seductive "fix" | Mechanism (`file:line`) | Byte-author | Status | Why it fails |
|---|---|---|---|---|
| When a `Workflow` "verifies," it spawns **another** `agent()` (adversarial-verifier / judge-panel) whose verdict is again self-authored text | `judges.run_judge` (`judges.py:243`) | **SAME as the judged agent** when the only evidence is the subagent's own output | **wishful** | a model verifying a model over self-authored bytes is *consistency, not grounding* (re-deriving an author's own bytes). It is `safe` (fail-to-ABSTAIN — `run_judge` converts any raise/bad-return to ABSTAIN, never AGREE) but **safe ≠ grounding**. Legitimate ONLY if the `evidence` tuple carries independent non-forgeable bytes (git/env/witness), at which point the grounding is the **witness's**, not the judge's. The one production claim-bridge, `claim_extract`, deliberately does NOT model-grade prose — it extracts `(plan,phase)` and routes to the deterministic git oracle ("abstain, never invent") |

---

## 5. The weak-model fan-out — seed example #2

The operator's second seed: *"a bunch of weak models are used — how does that get
verified / trusted / not."* The instinct is to reach for
[`153`](153_can-dos-lift-a-weak-model.md) (can DOS *lift* a weak model toward
strong?). **That is the wrong question for a fan-out.** `153` is single-model
lift; the fan-out question is **"do you believe N weak workers' *results*?"** —
and the answer is the same invariant as everywhere else in this doc: **do not
believe the worker; adjudicate its claimed effect against an independent
byte-author.**

The structural fact (measured): a weak-model result and a strong-model result are
**both just strings** (or both schema-valid objects) in the same results array.
After return they are *indistinguishable* — no model-provenance tag, no
tier-weighted confidence, no re-check of a cheap claim against an oracle. In this
corpus, only the **synthesis** step is ever pinned to `opus`; the investigators
take the default model, and their strings fold with no tier marker. So a workflow
can mix tiers freely and the synthesis cannot tell which finding came from which
model. (Measured-absent here — 0 weak downgrades, 13 `opus` upgrades, 37
`agentType:'Explore'` agents trusted equally for both Map and Verify — but the
*shape* is real and a deliberate weak-fleet would surface it immediately.)

DOS's move makes the model **tier irrelevant to trust** by grounding on the
*effect*, not the *narration*. A weak worker's claim "I created table X / wrote
file Y / row Z exists" is adjudicated by `effect_witness.witness_effect`
(`effect_witness.py:169`) against an independently-authored read-back — and
`believe_under_floor` (`evidence.py:412`) grants belief *only* when a
non-forgeable source attested. A strong worker's claim runs the **same** gate. If
the effect is `CONFIRMED`, the tier never mattered; if `REFUTED`, the silent
failure is visible regardless of how confident the prose was. This is the right
shape because `effect_witness` is the one check whose value *grows* with model
strength (`effect_witness.py:5`) — it does not read the trajectory at all, so a
competent weak model that fails silently is caught exactly like a competent strong
one that does.

This is the `ORACLE → JUDGE → HUMAN` ladder (`judges.py:9`) applied to a fleet:
the deterministic oracle / effect-witness rules first (**deterministic-first**);
a model-judge sits only on the *residue*, **fed independent evidence, never the
subagent's own string** (`judges.py:30`); the human only at the irreducible seed.
A model-judge over the return *text* is the [§4d](#4d-wishful--do-not-the-consistency-trap)
trap — model-grading-model, explicitly wishful. The trust answer for N weak
workers is not a stronger judge; it is a non-forgeable witness, which the weak and
the strong both face identically.

---

## 6. Honest limits — every lever is advisory and host-realized

Faithful to [`128` §9](https://github.com/anthony-chaudhary/dos-private/blob/master/128_the-ultracode-economics-and-how-the-kernel-saves-spend.md#9-honest-limits--what-dos-does-not-save):
state what DOS does **not** do.

1. **DOS ships no `Workflow` hooks.** "Directly useful to ultracode" means
   *callable from a workflow-script stage, the `dos` CLI, or the MCP server* — it
   does **not** mean automatically wired into the `Workflow` tool. There is no
   `SubagentStop`/fold interception today;
   [`165`](165_dos-into-claude-code-the-runtime-binding-roadmap.md) lists a `SubagentStop` fleet-gate
   as a roadmap item, and [`170`](170_frontier-lift-where-it-lives-and-the-features-that-grow-it.md)
   notes the whole `Stop` family is dead until the F1 dialect fix lands. **0/114**
   scripts shell out to any `dos` verb; every `dos verify`/`arbitrate` string in
   the corpus is prompt text. Each [§4b](#4b-shipped--byte-clean-but-no-ultracode-caller)
   lever is **inert until a workflow author calls it.**

2. **Two levers are inert even if called, without a prerequisite the fan-out does
   not produce.** `resume.resume_plan` recovers only work declared into a
   `run_id`-keyed intent ledger AND committed to git — the write side is exercised
   only by tests, so over a real dead wave the ledger is empty and the verdict is
   `UNRESUMABLE`. `liveness.classify` and the *strong* form of
   `completion.classify` need the same spine (run-id + commits/heartbeat); the
   dominant pure-text research subagent produces none, so they read ADVANCING-then-
   STALLED with no discrimination. `firing_label` cannot join live ultracode
   firings at all (no `run_id` is stamped; `CID_RUN_ID` is unset in CC).

3. **The keystone is a named gap, not a shipped catch.** The phenomenon is
   confirmed byte-for-byte and at ~32% prevalence, the *pattern* is proven
   benchmark-side, and the refusal envelope is real — but no `src/dos` module
   classifies a subagent transcript's terminal assistant-message, and the existing
   `terminal_error` grammar does **not** match the 429 string. Shipping it is new
   kernel code plus a workflow-side fold partition.

4. **The keystone catch is abnormal-termination only.** A well-formed-but-empty
   answer (schema-valid with empty arrays; a `max_tokens`-truncated string that
   still parses — `max_tokens` is *unobserved* in this corpus, present in
   principle only) is non-null and passes the terminal-state gate. That residue
   needs lever (B) — `effect_witness` / `believe_under_floor` — not the terminal-
   state witness.

5. **Detection soundness and intervention safety are orthogonal.** A *sound*
   true-positive catch was measured **net −9pp** because the intervention derailed
   the model mid-plan (`intervention.py:7`). On the keystone the safe action is to
   route the dead child to a DEAD bucket and re-dispatch *its own* unit — never to
   re-prompt the synthesizer. Keep every binding at WARN/BLOCK-with-synthetic-
   return, never DEFER. DOS is a **PDP with no PEP** (`enforce.py:3`): it reports
   and proposes; the arbiter guarantees apply only to **declared** regions —
   nothing confines a worker's actual writes.

6. **The collision lever needs the WAL write-back, not just the pure call.** A
   bare `dos arbitrate` persists nothing; siblings in separate processes still
   race a stale view unless each shells `dos lease-lane acquire` *before* launch
   and gates on the exit code. This is exactly the
   [`98`](98_the-orchestrator-is-a-driver.md) subtlety, re-grounded on the
   ultracode fan-out.

---

## 7. The build proposal — two small things (`79` primitives)

> **SHIPPED — `dos verify-result` (1) landed `src/dos/result_state.py` +
> `cli.cmd_verify_result` + `tests/test_result_state.py`.** Two corrections the
> real corpus forced on the §2.1/§4c spec, both grounded in an empirical sweep of
> **2,935 real `model:"<synthetic>"` records** (not the doc's single keystone):
> - **Broader than 429.** Keying the gate on `apiErrorStatus==429` would miss
>   **43%** of the synthetic deaths — only 1,688/2,935 (57%) are rate-limits; the
>   rest are auth (401), org-disabled (403), server (500), and the weekly/session
>   limit-text deaths that carry **no `apiErrorStatus` at all** (50/2,935). So the
>   gate keys on `message.model == "<synthetic>"` (the unforgeable harness-author
>   marker, 100% of the corpus), corroborated by top-level `isApiErrorMessage` +
>   `stop_reason == "stop_sequence"`; `apiErrorStatus` + a coarse class
>   (RATE_LIMIT/AUTH/SERVER/USAGE_LIMIT/OTHER) are reported as *detail*, never the
>   gate. The verb catches the whole synthetic-terminal family.
> - **Top-level, not in `message`.** §2.1 placed `isApiErrorMessage`/
>   `apiErrorStatus` inside the `message` object; in real records they are
>   **top-level siblings** of `message` — corrected in the reader.
> - **Reuse found by probing first.** The transcript read reuses
>   `claim_extract._read_lines` (the one transcript reader in the kernel) so the two
>   can't drift; the refusal envelope is `wedge_reason`-shaped
>   (`envelope_is_refusal`-readable) with a `RESULT_DEAD_<CLASS>`/`RESULT_EMPTY`
>   `reason_class`. Confirmed `terminal_error_fired` is **not** reusable (walks
>   `role=="tool"`; `^\s*Error:` ≠ `API Error:`), as §4c claimed.
> - **The exit-code contract.** Top-level `dos verify-result --transcript PATH` (or
>   a hook event with `transcript_path` on stdin): exit **3** = DEAD (route to a
>   DEAD bucket, count in the denominator, do not fold), **0** = HEALTHY *or*
>   UNREADABLE (the fail-safe floor — a read fault never fabricates a death that
>   drops a real result), **2** = contract error. `--json` carries the verdict +
>   envelope. Published in `dos doctor --json` `exit_codes`.
> - **Self-validating provenance.** The mapping workflow that scoped this build
>   *itself* exhibited the pathology — its synthesis agent died on a
>   `You've hit your session limit` synthetic terminal (`synthesis: null`) while the
>   `Workflow` tool reported `completed`. Exactly the §2.3 seed, caught again in the
>   act of building the catch for it.
>
> The coverage-classify pairing (below) is **not yet built** — it remains the
> follow-up. The witness-routing convention (2) is also still a future skill-pack
> stage.

Keep it to the smallest primitives that unlock the most value
([`79`](79_primitives-not-features.md)). Two new things, in priority order.

**(1) `dos verify-result` — a fold-site stage helper (the keystone catch).** A
single CLI verb a workflow calls on each subagent's *transcript* (not its return
string) immediately after the `parallel()`/`pipeline()` barrier, before the
`${result}` interpolation. It classifies the terminal assistant message —
`model=="<synthetic>"` / `isApiErrorMessage` / `apiErrorStatus` / `stop_reason` —
emits a `wedge_reason`-shaped refusal envelope (`wedge_reason.py:249`)
for a dead/synthetic terminal, and returns an exit code the workflow branches on
to route the result to a DEAD bucket and count it in the denominator. This is
genuinely new kernel code (a new grammar over the assistant role, **not** a reuse
of `trajectory.terminal_error_fired`), but it is small, pure-given-evidence, and
sits exactly one line before the `.filter(Boolean)` in 89/114 real scripts. It
converts the 32%-prevalence silent death into a counted, refused, re-dispatchable
event. Pair it with a thin coverage-classify (the cheap form of
`completion.classify`) over `{declared N, witnessed-live-returns}` and **feed the
real coverage into the synthesis prompt** — so a sub-quorum fan-out can no longer
be laundered as full.

**(2) A workflow-native convention for routing actionable claims through the
witness rung.** Not a new kernel module — a documented stage pattern (a `SKILL.md`
in the skill pack, [`74`](74_skill-pack-plan.md)): for any subagent whose
deliverable is a *checkable effect* (a git phase, a created file, a DB row),
extract the claim at the boundary (`claim_extract`, "abstain, never invent"),
gather a read-back via a `drivers/*` witness, and fold only `CONFIRMED`
(`effect_witness.py:169` / `evidence.py:412`). This is the seed-#2 answer made
operational: it runs the **same** witness gate over every worker's claim, so the
model tier of the worker is irrelevant to whether its result is believed — and it
keeps any model-judge strictly on the residue, fed witness evidence, never the
subagent's own string ([§4d](#4d-wishful--do-not-the-consistency-trap)).

Both are workflow-side stages over kernel verdicts that already exist (or, for the
keystone, one small new verb). Neither asks ultracode to adopt DOS's dispatch
loop; both are the `98` "foreign orchestrator calling the seam" pattern, aimed at
the *result*-integrity half that `98` (lease visibility) and `128` (spend) leave
open.

---

## 8. One-line synthesis

**An ultracode `Workflow` folds `agent()`'s self-authored return as ground truth
at exactly one place, and 32% of real subagents fold a harness-authored `429`
string there as a "finding"; DOS is directly useful as the byte-clean referee at
that fold — it adjudicates the result against a *different* byte-author (git, the
env tool-result, the WAL, the `<synthetic>` stamp), makes the model tier
irrelevant to trust by grounding on the effect rather than the narration, and
needs only one small new verb (`dos verify-result`) plus a witness-routing
convention to turn every silent death and every empty deliverable into a counted,
refusable event.**

---

## 9. Implications of shipping the keystone (the learning to fold into the thesis)

`dos verify-result` is built (`f43db8d`; §7 SHIPPED note), and its consumer half is
started (`c449f76`; §9.1). The verb itself is small; its *implications* are the part
that updates the paper. Six, ordered by how much they change the thesis rather than
confirm it.

### 9.1 The keystone closes the DETECTION half and SHARPENS the value-capture half

§8 framed this as "the one small new verb needed." It is now built — so the
**detection** half of the fold problem is solved: a sound, byte-clean catch for a
32%-prevalence failure exists and is live-verified. But the binding constraint was
never detection (the
[conversion-gap synthesis](190_coordination-measured-and-the-f3-gateability-split.md),
`wf_6647ad3c`: *detection SOLVED, value-capture is the open problem; change the
CONSUMER not the threshold*). Shipping `verify-result` does not move that constraint
— it relocates the open question one step downstream: **0/114 real workflow scripts
call any `dos` verb**, so the verb is inert until a consumer invokes it and acts on
exit 3. `verify-result` joins the [§4b](#4b-shipped--byte-clean-but-no-ultracode-caller)
bucket (kernel-real, byte-clean, CLI/MCP-callable, zero ultracode callers). The
lesson: **a new sound detector is necessary and not sufficient; the next unit of
value is a CONSUMER, not a sharper verdict.** This is the same conclusion docs/188
reached when it killed the agent-side WARN bet — the action belongs at the
orchestrator, not the agent.

**The consumer half, started (`c449f76`).** Two pieces now exist over the verb: a
`$0` real-corpus measure (`benchmark/fleet_horizon/measure_fold_deaths.py`, sibling
of docs/190's `measure_real_collisions.py`) and the fold-partition recipe
(`EXAMPLES.md` Recipe 9 — the §7(2) witness-routing convention: branch a fan-out on
`verify-result` exit 3 one line before `.filter(Boolean)`). The measure runs the
SHIPPED `result_state.verify_transcript` over **4,698 real workflow subagent
transcripts** and **independently reproduces the headline**: **31.2% DEAD** (1,467)
— and reproduces the §2.1 concentrations byte-for-byte (`wf_516412fb-5cc` 168/178 =
94%, `wf_152c7778-165` 107/118 = 91%). So the prevalence is now confirmed on a
larger, independent corpus, and the partition a consumer would apply is measured.
What remains genuinely open is a *live* A/B: a real workflow whose fold calls the
verb, showing the recovered work is net-positive (the
[`151`](151_intervention-ladder-live-study.md) §5 −9 pp caution — the safe action
re-dispatches the dead child's own unit, never re-prompts the synthesizer).

### 9.2 The byte-author law got its cleanest possible demonstration

`message.model == "<synthetic>"` is the *purest* grounding signal in the kernel.
Every other syscall argues "the evidence's byte-author differs from the judged
agent" with some indirection — git ancestry (`oracle`), the env `result_digest`
(`tool_stream`), the lease WAL (`arbiter`). Here it is **literal and
self-identifying**: the harness writes its own authorship into the record as the
string `<synthetic>`; the `role:"assistant"` slot is merely the conversation
position, not authorship (§2.1). The judged agent cannot forge "I am the harness."

The implication for the
[verification-substrate thesis](138_what-is-truth-the-throughline.md) and the
[byte-inequality axiom](141_byte-inequality-and-the-derivative-problem.md): this is
the example to LEAD with when refuting the model-grading-model objection. It needs
no statistic, no AUROC, no threshold — a skeptic verifies it with `grep
'"model":"<synthetic>"'`. It is the [`151`](151_intervention-ladder-live-study.md)
§1.1 minting argument inverted: where minting is the agent authoring a value it had
no right to author, the `<synthetic>` stamp is the *harness* authoring a terminal the
agent had no part in — and the fold's bug is believing the conversation slot over the
authorship stamp.

### 9.3 The self-referential proof is now REPEATABLE, not anecdotal

§2.3 recorded one workflow dying on a synthetic terminal while reporting
`completed`. The build's own scoping workflow (`wf_1cc4fceb-6ba`) did it **again,
independently**: its synthesis agent died on a `You've hit your session limit`
synthetic terminal (`synthesis: null`), while the `Workflow` tool reported
`completed` with `probe_count: 5`. Two independent occurrences, both in the act of
studying/building the catch.

This promotes the claim from tail-anecdote to **live, reproducing-under-hand fact**
— stronger than "32% of a frozen corpus" because it fires on the very tooling DOS is
built with. It also generalizes the finding: the fold believes `agent()`'s return
*and* believes the orchestrator's own `completed` status. **The `Workflow` tool's
`completed` is itself an unverified self-report** — it narrates success over an empty
deliverable (`doc_markdown=null`). So the result-state witness is needed at *two*
fold levels: per-subagent (the terminal record) and per-workflow (the orchestrator's
own completion claim vs. the un-authored deliverable). The §7(1) verb covers the
first; the second is the coverage-classify pairing (still unbuilt).

### 9.4 The catchable surface is ABNORMAL-TERMINATION, not "rate limits"

The 2,935-record sweep forced the 43%-miss correction (§7 SHIPPED note): only 57% of
synthetic deaths are rate-limits; the rest are auth (401), org-disabled (403), server
(500), and quota/limit-text deaths with no `apiErrorStatus` at all. The implication
is a **reframing, not a tuning**: the verb is not "a rate-limit guard" (policy that
changes) but a **terminal-state witness** for the whole family of harness-injected
deaths (structural). This slots cleanly into the
[taxonomy of refusal](182_the-kernel-is-a-taxonomy-of-refusal.md): `verify-result` is to the
*transcript terminal* what `tool_stream` is to the *tool-result stream* and
`liveness` is to *git/WAL advance* — three temporal-distrust witnesses, three
byte-authors (harness / env / git), one shape. The lesson for future detectors:
**name the witness by its byte-author and temporal locus, not by the policy
instance that motivated it** — the 429 framing would have shipped a verb that missed
nearly half its own population.

### 9.5 The natural home of the verdict is the CONDUCTOR, not the agent

`verify-result`'s consumer is the orchestrator's fold logic (partition the results
array on exit 3), never the agent (an agent-side WARN at the fold is the dead bet,
docs/188). This is concrete evidence for the
[two-product coupling thesis](98_the-orchestrator-is-a-driver.md): the verdict
should route to the fleet *conductor*, which is DOS's missing non-agent consumer.
`verify-result` is thus a textbook instance of the seam the fleet product owns — a
kernel verdict whose only sound actuation lives in the workflow runner's
partition-and-re-dispatch logic, kept at WARN/route-to-DEAD-bucket and never the
−9 pp DEFER-shaped synthesizer re-prompt ([`151`](151_intervention-ladder-live-study.md)
§5). **The kernel supplies the byte-clean verdict; the conductor captures the
value.** That division is the whole architecture, observed at one more seam.

### 9.6 The honest boundary (what the keystone does NOT imply)

- It closes the *abnormal-termination* hole, not the *empty-deliverable* hole. A
  schema-valid object with empty arrays, or a `max_tokens`-truncated string that
  still parses, is non-null and reads HEALTHY — that residue is `effect_witness`'s
  job ([§4b](#4b-shipped--byte-clean-but-no-ultracode-caller)), not this gate's.
- It gives a *per-worker* DEAD signal, not an honest *denominator*. Turning DEAD
  counts into a coverage number the synthesizer sees (so 4-of-7 cannot launder as
  7-of-7) is the unbuilt coverage-classify pairing.
- It is a PDP: exit 3 reports; nothing re-runs the dead worker. The safe consumer
  re-dispatches the dead child's OWN unit; it never re-prompts the synthesizer.
