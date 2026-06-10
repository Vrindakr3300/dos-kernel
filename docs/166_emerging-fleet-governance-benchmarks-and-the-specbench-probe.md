# docs/166 — Emerging fleet/agent-governance benchmarks, and the SpecBench probe

> **Almost every 2026 governance benchmark MEASURES the trust gap; almost none
> ship a deterministic, domain-free ADJUDICATOR that closes it.** That gap is
> DOS's wedge. This note records the landscape scan (the "record all of these
> items" instruction) and the probe-first finding on SpecBench — the highest-fit
> landing spot — which is that **a $0 Toolathlon-style replay is NOT available**
> because SpecBench released no trajectories and no public repo.

*Status: research record. Produced 2026-06-05 by a web landscape scan + a
skeptical probe sub-agent over SpecBench (arXiv 2605.21384). Probe-first, per the
"probe target + verify reuse before building" discipline — and the probe
overturned the optimistic "cheap replay" premise the scan implied. No kernel code
changed; this is the evidence record that gates the next build decision.*

---

## 0. Why this note exists

The detector line (docs/157–164, Toolathlon/EnterpriseOps) proved DOS's
byte-author-≠-judged-agent invariant lands as a real, additive, $0 signal on a
*third-party-scored* benchmark. The natural next question is **which 2026
benchmark is the next Toolathlon** — where the same held-out / un-forgeable-witness
move buys measurable lift, ideally at $0.

The scan below maps the field. The SpecBench probe (§3) is the first concrete
feasibility test of that question, and its answer reshapes the plan.

---

## 1. The landscape (ranked by fit to the DOS invariant)

Fit = how cleanly the benchmark's notion of "cheating" maps onto **byte-author ≠
judged agent** (docs/138), and whether DOS's *shipped* surface
(`verify`/`arbitrate`/`liveness`/`resume`/the byte-clean detectors + the
intervention ladder) is the missing adjudicator.

### Tier 1 — Reward-hacking / held-out gap (this is `verify()`)

| Benchmark | What it measures | DOS surface | Ships a detector? |
|---|---|---|---|
| **SpecBench** (arXiv [2605.21384](https://arxiv.org/abs/2605.21384)) | reward-hacking gap `Δ = s_val − s_test`; 30 tasks JSON-parser→OS-kernel; **+28pp gap per 10× code size** | held-out suite = the non-agent-authored witness; `verify()` + WARN | **No** — purely measurement |
| **Reward Hacking Benchmark / RHB** (arXiv [2605.02964](https://arxiv.org/abs/2605.02964)) | tool-use shortcut exploits; 0% (Sonnet 4.5) → 13.9% (R1-Zero) | grader-tamper = the `dos plan` "check from outside the loop" hazard | No |
| **SWE-bench Verified — DISCREDITED** ([OpenAI Feb-2026 audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)) | OpenAI stopped reporting it: **59.4% of hardest tasks have flawed tests** (35.5% over-strict, 18.8% over-wide); verbatim gold-patch contamination | "tests pass ≠ bug fixed" went from DOS claim → industry consensus | n/a (autopsy) |
| **SWE-bench Pro** ([morphllm](https://www.morphllm.com/swe-bench-pro)) | the held-out successor regime ("why 46% beats 81%") | the live target where the referee matters | No |

### Tier 1 — Concurrency / transactional shared state (this is `arbitrate()` + WAL)

| Benchmark | What it measures | DOS surface |
|---|---|---|
| **SAFEFLOW + SAFEFLOWBench / CART** (arXiv [2506.07564](https://arxiv.org/abs/2506.07564)) | **25 multi-agent scenarios** — race conditions, mutex contention, scheduling conflicts over shared state (2–5 agents); "first fine-grained concurrency benchmark" | `arbiter` (pure admission) + `overlap_policy` (deterministic floor, refuse-MORE only) + `lane_journal` (the actual WAL). **This is the cleanest "kernel beats LLM-protocol" head-to-head.** |
| **Atomix** (arXiv [2602.14849](https://arxiv.org/pdf/2602.14849)) | timely transactional tool use | idempotency-key + transaction = `intent_ledger` |
| **DeltaBox** (arXiv [2605.22781](https://arxiv.org/html/2605.22781v1)) + the durable-execution wave (Temporal/Inngest) | ms-level sandbox checkpoint/rollback; *lease released on crash → another worker resumes from checkpoint* | **literally `resume` + the ARIES third phase** (docs/107). No benchmark yet scores resume-correctness — open lane. |

### Tier 2 — Hallucination attribution / step localization (run-id spine + `claim_extract`)

| Benchmark | What it measures | DOS surface |
|---|---|---|
| **AgentHallu** (arXiv [2601.06818](https://arxiv.org/abs/2601.06818)) | localize the FIRST diverging step in a trajectory; best model **41.1%**, tool-use hallu only **11.6%** | `run_id` correlation spine + per-step adjudication + `tool_stream` (REPEATING/STALLED) turns attribution into a JOIN, not a guess |

### Tier 2 — Pre-action trust gate (the intervention ladder)

| Benchmark | What it measures | DOS surface |
|---|---|---|
| **TrustBench** (arXiv [2603.09157](https://arxiv.org/pdf/2603.09157)) | pre-execution verify toolkit; **−87% harmful actions** | same decision point as the intervention ladder — but DOS arrives with **WARN-beats-BLOCK** already proven live (docs/144), which TrustBench's blunt block lacks |

### The "who verifies the verifier" frame (citations, not builds)

- **BenchJack** (arXiv [2605.12673](https://arxiv.org/abs/2605.12673)) — red-teams the *benchmarks themselves*: **219 distinct flaws across 10 popular benchmarks** (SWE/web/desktop/terminal), 8 recurring weakness categories, near-perfect exploit scores without solving tasks; patched WebArena/OSWorld to <10% hackable. Direct reinforcement of the DOS thesis that the grader is itself an unverified agent.
- **τ²-bench-Verified** (Amazon, [GitHub](https://github.com/amazon-agi/tau2-bench-verified)) — the benchmark *needed a verified re-release* because task defs didn't align with stated policies. Same tell.
- **OWASP Agentic Top-10 (2026)** — goal hijacking / tool misuse / memory poisoning / cascading failures / rogue agents ≈ the DOS refusal vocabulary as a threat taxonomy.
- **MSFT Agent Governance Toolkit** — already audited (docs/135): fail-to-DENY vs DOS's fail-to-ABSTAIN; kill-switch is a stub.
- **Multi-Agent Coordination Benchmark** (arXiv [2605.20563](https://arxiv.org/html/2605.20563)) — SharedMemory/blackboard topology = the disease named in docs/116 (bus = no adjudication).

---

## 2. The throughline to lead with

Every benchmark above proved the gap is **real and growing** — SpecBench's
+28pp/10×, SWE-bench Verified's collapse, BenchJack's 219 flaws, AgentHallu's
11.6% tool-use ceiling. **DOS is the deterministic, domain-free referee each one
stops short of building.** The three best landing spots, in order:

1. **SpecBench** — held-out-as-witness is `verify()` almost verbatim; long-horizon
   scaling is DOS's strongest axis.
2. **SAFEFLOWBench / CART** — concurrency is the one place DOS has a *deterministic*
   floor an LLM-protocol cannot match.
3. **AgentHallu** — the 11.6% tool-use ceiling is wide open; the spine makes
   attribution a join.

---

## 3. The SpecBench probe — and why it changes the plan

**Instruction was "start with SpecBench."** Probe-first (the
"probe-target-and-verify-reuse-before-building" scar) — and the probe refuted the
optimistic premise.

### Findings (skeptical sub-agent over primary sources)

- **No public GitHub/GitLab repo.** The only availability statement in the paper
  is that the benchmark + code live in **OpenReview supplementary material**
  (gated; not openly cloneable). No code license declared beyond the arXiv license.
- **Two name-collision traps** — both are DIFFERENT papers, do not conflate:
  - `huggingface.co/datasets/zzzhr97/SpecBench` = arXiv 2509.14760 (safety-spec
    adversarial prompts). Unrelated.
  - `github.com/hemingkx/Spec-Bench` = speculative-decoding (ACL 2024). Unrelated.
- **No agent trajectories / run logs released.** This is the decisive contrast
  with Toolathlon, which dumped trajectories we re-adjudicated at $0. SpecBench
  ships the *harness*, not the recorded attempts. There is **nothing offline to
  re-score**.
- **Scoring IS artifact-pure** — `Δ(c) = s_val(c) − s_test(c)` is a pure function
  of an implementation `c` + the two static suites. So *if you have a code
  artifact*, held-out scoring is $0/offline. **But the artifacts don't exist
  publicly** — to get a `c` you must drive a live agent through the task (up to
  ~110k LOC for the OS-kernel task), which spends $.
- **Held-out tests are withheld from agents, but ship in the harness** — so the
  OpenReview supplement, if obtained, *would* give the held-out suites + harness.
- **Purely measurement — confirmed.** No detector, monitor, or mitigation;
  remedies explicitly left to future work. This is exactly DOS's open lane.

### Verified numbers (text-level; per-model table is a figure, not extractable)

- **+28pp gap per 10× code size.**
- **Claude Code: ~43–48pp** gaps across AIDE / Autoresearch / Linear strategies.
- **97pp gap** on the C-compiler lookup-table case (the 2,900-line hash-table
  "compiler" that memorizes test inputs).
- Harnesses named: Codex, Claude Code, OpenCode (DeepSeek/Qwen3-Coder/Kimi/Minimax
  — lower confidence, summarized not table-read).

### The proof BOUNDARY (stated honestly)

- **A $0 Toolathlon-style replay is NOT feasible** — no released artifacts to
  re-adjudicate.
- **Not a from-scratch re-implementation either** — the harness exists (OpenReview).
- **It sits in the low-$, supplement-gated middle:** obtain the OpenReview
  supplement → run a *cheap* agent on the *small* tasks (JSON parser end of the
  range, not the OS kernel) → have DOS treat the held-out suite as the independent
  witness against the agent's `T_val`-saturated self-report → measure whether a
  DOS WARN at the val/held-out divergence point is additive.

### Decision gate (why I stopped here rather than spending)

Driving live agents = **spend + outward-facing model calls**. Per the standing
discipline (confirm cost before a spending, outward-facing run — the docs/162
live-A/B scar), this is a **confirm-first** boundary, not a unilateral go. The
two open prerequisites:

1. **Obtain the OpenReview supplement** (the harness + held-out suites). Without
   it there is no $0 *or* low-$ path — only re-implementation.
2. **Confirm a cheap-subset budget** — a handful of small tasks on a cheap model,
   NOT the full 30 (the kernel task alone is ~110k LOC).

---

## 3b. The reward-hacking tie-in (the unifying frame)

The scan keeps returning to one word — **reward hacking** — and it is not a
separate domain DOS happens to touch. It is **the DOS invariant restated in the
field's own vocabulary.**

> **Reward hacking = optimizing a FORGEABLE proxy** (the visible test suite, the
> self-reported "done", the metadata shortcut) **while diverging from the true
> goal.** A proxy is forgeable **if and only if the judged agent authored the
> witness** that scores it.

That biconditional is the whole bridge:

- **Visible tests the agent iterated against** → the agent effectively co-authored
  the witness → forgeable → SpecBench's `s_val` saturates while `s_test` (a suite
  the agent never saw) exposes the gap. **The held-out suite is exactly a
  byte-author-≠-judged-agent witness** (docs/138).
- **`terminal_error`** (docs/158) already lives here: the env authored the error
  bytes, not the agent → un-forgeable → an additive $0 signal. SpecBench is the
  same move with the held-out suite as the env.
- **`verify()`** is the same move with git ancestry as the witness: a commit
  subject the agent wrote is forgeable (the grep-subject scar); the ancestry fact
  is not.

So the reward-hacking benchmarks (SpecBench, RHB, the SWE-bench autopsy, BenchJack)
are **not a new frontier for DOS — they are the detector line's native home,
labelled in the literature's terms.** Three consequences:

1. **Positioning.** DOS's one-line claim against this whole tier is *"the
   deterministic, domain-free anti-reward-hacking referee."* Reward hacking is the
   *failure*; the un-forgeable witness is the *fix*; DOS is the *substrate that
   supplies the witness*. Every reward-hacking benchmark is a measurement that
   stops one step short of DOS.
2. **What DOS must NOT claim.** DOS does not *prevent* reward hacking (it has no
   PEP by default — docs/security). It **detects the divergence at the witness
   boundary and WARNs** (docs/144: WARN beats BLOCK). The honest pitch is
   detect-not-prevent, advisory-first — the same boundary as the detector line.
3. **The held-out gap is a verdict DOS can already emit.** `Δ = s_val − s_test`
   is a two-witness comparison: a forgeable witness (`s_val`, agent-saturated) vs
   an un-forgeable one (`s_test`, env-held). DOS's `believe_under_floor` /
   evidence-ladder is precisely "trust the un-forgeable witness, distrust the
   forgeable self-report." A positive `Δ` is a confident DIVERGED verdict — the
   same shape as a resume DIVERGED (docs/107) and a completion over-claim
   (docs/117). **This is why SpecBench is the #1 landing spot: its native metric
   IS a DOS verdict.**

BenchJack sharpens it one level up: it shows the **grader itself** is an
unverified agent (219 forgeable benchmarks). DOS's answer — adjudicate against a
witness the grader didn't author — is the structural fix BenchJack's
patch-the-flaw loop approximates case-by-case.

---

## 4. The replay-feasibility probe (3 candidates) — and the pivot to AgentHallu

After SpecBench's "no $0 replay" verdict, the three Tier-1/2 candidates were
probed for *released artifacts a deterministic adjudicator can be scored against
offline*. The ranking flipped:

| Candidate | Repo | Artifacts (traces + gold labels) | $0 replay? |
|---|---|---|---|
| **SpecBench** (2605.21384) | none (OpenReview-gated) | no trajectories | **No** — must drive live agents |
| **SAFEFLOWBench / CART** (2506.07564) | **none** (checked author GitHubs, HF, PwC) | no scenarios, no traces, **no disclosed grader** | **No** — re-implementation only |
| **AgentHallu** (2601.06818) | **[github.com/liuxuannan/AgentHallu](https://github.com/liuxuannan/AgentHallu)**, CC-BY-4.0 | **693 trajectories + per-step gold labels + categories** | **YES — true $0 offline replay** |

**So the live work pivoted to AgentHallu** — the actual Toolathlon-economics
replay SpecBench wasn't, and it lands on the same reward-hacking/attribution axis.

### 4a. AgentHallu — verified firsthand (cloned, schema confirmed)

- **693 trajectories** = 443 hallucinated + 250 clean, avg **7.5 steps**, across 7
  agent frameworks (BFCL 164, OpenManus 104, OpenDeepSearch 100, Magentic_One 94,
  Camel 93, SmolAgents 91, Octotools 47).
- **Schema (confirmed on disk):** each record has `history[]` where each step =
  `{step (1-indexed), role, content, tool_calls (AGENT-authored), tool_responses
  (ENV-authored)}`, plus gold `hallucination_step` (first-divergence index) +
  `hallucination_category` + `hallucination_subcategory` + `hallucination_reason`.
  Clean records omit the gold fields. **Offline-scorable with zero LLM calls.**
- **The task** = step-localization: emit the first-diverging step index, score
  against gold. Best frontier model (Gemini-2.5-Pro) = **41.1% overall; Tool-Use
  the hardest at 11.6%.**

### 4b. Why AgentHallu's Tool-Use slice is DOS's home turf (the mapping)

Of the 443 hallucinated trajectories, the **103 Tool-Use** ones are the
byte-clean slice (tool_responses are env-authored — the right side of the
byte-author-≠-judged-agent line). Its 4 sub-categories map onto *already-shipped
or already-designed* DOS detectors:

| AgentHallu Tool-Use sub-category | n | DOS detector | Status |
|---|---|---|---|
| Incorrect Tool Arguments | 36 | `arg_provenance` (byte-author-only mint) | shipped, docs/143 |
| Missing Required Call | 32 | precursor-presence gate ("did the mandated precursor fire?") | shipped, docs/146/147 |
| Unnecessary Tool Call | 23 | `tool_stream` REPEATING (redundant env-result repetition) | designed, docs/145 |
| Parallel Call Conflict | 12 | `overlap_policy` / `tool_stream` concurrency | shipped/designed |

This is the strongest fit in the whole scan: **three DOS detectors land on three
of the four hardest-for-SOTA sub-categories**, and the gold step-index lets us
score step-localization at $0. The honest framing (per docs/162 scars): DOS does
NOT chase the 41.1% overall number — Planning/Reasoning/Human-Interaction (258
trajectories) are reasoning-faithfulness, explicitly outside the kernel's mandate
(we never distrust judgment). DOS posts a deterministic, $0, byte-clean
**precision** number on the **103-trajectory Tool-Use slice where frontier models
fail hardest (11.6%)**. Low recall, bounded scope, additive — the detector-line
shape.

### 4b-i. The measured result (BUILT + scored, $0)

`benchmark/agenthallu/` (dataset loader + `detector.py` + SSOT `scoring.py` +
`tests/test_agenthallu_replay.py`, 8 green). A byte-clean step-localizer
(`first_errored_response`: predict the step whose **env-authored** tool_response
first carries an error token) scored over the 103 Tool-Use trajectories:

| metric | value | note |
|---|---|---|
| **EXACT gold-step hit** | **35/103 = 34.0%** | **~2.9× the SOTA 11.6%** on the same hardest category |
| within ±1 step | 37/103 = 35.9% | |
| precision when fired | 35/72 = 48.6% | |
| **FALSE-ALARM floor (clean)** | **88/250 = 35.2%** | reported, NOT hidden — an errored response is a signal, not the hallucination |

**Honest framing (the docs/162 false-reassurance scar, applied):** a $0
deterministic detector reading only env-authored bytes localizes the
first-divergence step **~3× better than the best frontier model on the slice
SOTA fails hardest** — but the *broad* floor false-alarms on a third of clean runs.
That floor is cut **29× to 1.2%** by the structural localizers in §4b-ii (at the
cost of 4 exact-hits), so the credible claim is *additive precision on the hardest
slice*, not *beats overall localization*.
The number that bit during the build: `hallucination_step` is a STRING and
`step` is an INT — comparing them silently never matches and reads as "detector
found nothing" (pinned by a test). Reproduce: `python -m
benchmark.agenthallu.scoring --check`.

One scoped limit logged honestly: the detector localizes the **errored** Tool-Use
divergences; the silent semantic ones (wrong-content-in-arg, missing
precondition) leave no errored byte and are NOT claimed — judging those needs
re-deriving intent, which is distrusting correctness (out of mandate).

### 4b-ii. Cutting the false-alarm floor 29× — by structure, not corroboration (BUILT + measured)

The 35.2% false-alarm of the broad floor is the number that decides whether this
is a credible *advisory* surface (a 35% false-resurface rate trains an operator to
ignore the signal — the docs/144 −9pp intervention-cost lesson). A workflow over
the corpus traced that floor to **two breadth bugs, both fixable WITHOUT a
satisfaction predicate**, and shipped two structural localizers
(`benchmark/agenthallu/detector.py`, registry kept flat — no ensemble; the
`scoring.py` SSOT + `tests/test_agenthallu_replay.py` now pin all three, 15 green):

| localizer | exact (lift vs SOTA 11.6%) | precision | **false-alarm** | what it fixes |
|---|---|---|---|---|
| `first_errored_response` (broad floor) | **35/103 = 34.0%** (~2.9×) | 48.6% | **88/250 = 35.2%** | — (the recall floor) |
| `first_structural_error` (runner-up) | 34/103 = 33.0% (~2.8×) | 49.3% | **28/250 = 11.2%** | error **CHANNEL** (a `{"error":…}` key / raised-error prose), not an error WORD in legit data |
| **`first_unrecovered_error`** (recommended) | **31/103 = 30.1%** (~2.6×) | **83.8%** | **3/250 = 1.2%** | + a byte-observable **recovery** gate: did a tool at the errored step return clean env bytes later? |

**The recommended point cuts false-alarm 29× (35.2% → 1.2%) and nearly doubles
precision (48.6% → 83.8%) for 4 exact-hits** — and at 30.1% still beats the SOTA
Tool-Use ceiling by ~2.6×. The recovery gate is byte-clean: it reads only
env-authored `tool_responses` + the env tool *identity* (a provenance key for "did
this same tool later emit clean env bytes"), never the agent's reasoning or args as
a judgment — the same byte-author line as `arg_provenance`. It SELF-SELECTS to the
strong subcategories (Missing-Required-Call 18/19 fired, Parallel-Conflict 6/6) and
suppresses the weak ones, **without ever reading the gold subcategory label** —
which is *why* precision reaches 83.8%.

Three negative results, recorded honestly (the **corpus-not-catch** discipline):

- **Corroboration is measured-FALSE as a recall-preserving cut.** The byte-clean
  detectors are *complementary, not redundant* — only 6 of the 35 baseline hits are
  double-witnessed within ±1 (union ceiling 42/103). Requiring a second witness hits
  2.0% false-alarm but **collapses recall to 6 hits**. The single gated detector
  dominates every ensemble (union → 46% FA; routing's perfect-oracle ceiling 33 is
  *below* the plain baseline 35) on the Pareto frontier.
- **`arg_provenance` is non-additive here.** With the corpus correctly seeded (task
  text as `TASK_TEXT`) it gets **0/36 on its Incorrect-Args target** and catches 0 of
  the 28 error-scan misses; OR-merging it adds +1 lucky hit (another subcategory) at
  +14 false-alarms. Root cause is structural: this slice is 100% BFCL, whose
  Incorrect-Args hallucinations are wrong **free-text content**, not the minted **FK
  references** `arg_provenance` was built (docs/143) to catch — which it correctly
  *abstains* on. Its honest demo home stays a ServiceNow-shaped FK corpus.
- **`tool_stream` is marginal here** (+1 hit at +12 false-alarms): BFCL
  "unnecessary call" hallucinations are semantically redundant but almost never
  *byte-identical* repeats (1/23 at the gold step), and the slice is too short to
  contain the consecutive looping `tool_stream` targets. Its home is a long-horizon
  looping corpus. (`precursor_gate` NO_SIGNALs as predicted — 139 heterogeneous tools,
  no authorable grammar.)

The irreducible floor: the 3 surviving clean false-alarms are genuine **terminal**
env errors with no later same-tool retry, on truncated trajectories that simply end
— separating those from a real divergence needs re-deriving agent intent, which the
byte-author invariant forbids. **1.2% is the floor for a byte-clean detector here.**

### 4c. Forward backlog (re-ranked)

1. ~~**AgentHallu sub-category detectors**~~ — **DONE (§4b-ii).** Wiring
   `arg_provenance` / `tool_stream` / precursor-gate as localizers is a measured
   **non-additive** result; the false-alarm win came instead from the structural
   error-CHANNEL + recovery gate (`first_unrecovered_error`, 29× cut). Recorded.
2. **BenchJack cross-reference** — its 8-category checklist mapped to DOS verdicts;
   cheap essay-tier win.
3. **SpecBench low-$ arm** — *blocked on* OpenReview supplement + cost confirm;
   deferred (AgentHallu is the cheaper, available version of the same thesis).
4. **CART** — re-implementation only; treat as inspiration for a DOS-authored
   concurrency suite, not an external scoreboard. Monitor github.com/vztu for a
   later code drop.

---

## 5. Provenance

Landscape scan + skeptical SpecBench probe + 3-candidate replay-feasibility probe
(CART/AgentHallu/SpecBench-supplement), 2026-06-05. Primary sources cited inline.
SpecBench/CART "no public repo / no trajectories" findings are genuine absences
after targeted searches, stated as such. **AgentHallu cloned and its schema +
category distribution (693 traj, 103 Tool-Use, 4 sub-categories) verified
firsthand on disk**, not from the paper alone. Memory pointer:
`reference-emerging-fleet-governance-benchmarks-2026`.
