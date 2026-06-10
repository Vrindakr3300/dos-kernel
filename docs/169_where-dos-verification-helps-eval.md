# 169 — Where DOS verification helps eval: the benchmark-grounded survey

> **Every popular agent benchmark grades against a forgeable proxy — a green test
> suite, a matching final state, a string the agent printed, or another model's
> opinion — and every one of their authors eventually ran a manual forensic pass
> to find out how badly that proxy lied. DOS does not propose to *raise the
> benchmark's recall* or *fix its grader*. It proposes to convert the grader's
> binary into a typed-evidence corpus: the productized, reusable form of the
> hand-audit each of these teams already ran once.**

This is a **survey**, not a plan — no code lands with it. It is the
benchmark-grounded sibling of
[`167_the-eval-and-naive-verifier-comparison.md`](167_the-eval-and-naive-verifier-comparison.md):
167 builds the *taxonomy* (the forgeability axis, eval concepts vs. naive
verifiers); this doc *applies* that axis to named, popular benchmarks — SWE-bench,
τ-bench, WebArena, GAIA, MLE-bench, Toolathlon, Cybench, AgentDojo, BIRD, and the
LLM-as-judge family — and asks, concretely, *where DOS's distrust primitives help
the eval, and where they honestly cannot.*

It does **not** re-argue the eval-vs-verifier *philosophy* — the strategy repo
owns that
([`dispatch-os-evals-vs-verification.md`](../../dos-private/dispatch-os-evals-vs-verification.md),
[`dispatch-os-the-verification-substrate-for-agentic-rl.md`](../../dos-private/dispatch-os-the-verification-substrate-for-agentic-rl.md)).
This is the empirical layer beneath it.

**Four claims govern the whole doc; read them before any benchmark row, because
every row inherits them:**

1. **Advisory, not enforcing.** DOS is a PDP, not a PEP. It emits a *parallel
   verdict* a benchmark maintainer may consult; it never blocks a graded run. The
   verbs are *flags / labels / separates / abstains* — never *prevents / rejects*.
2. **Detect, not fix.** DOS does not re-grade a benchmark autonomously or decide a
   test is wrong. It produces *evidence rows* and *advisory flags*; a human or a
   fenced JUDGE fills the bins.
3. **Recall is not the scoreboard, and the effect concentrates on weak models.**
   DOS's own third-party-scored detectors on the public Toolathlon replay run at
   **~92–98% precision but only ~1–6% union recall**, and the detectable signal
   *weakens on the strongest models* ([`157`](157_toolathlon-replay-detector-purchase.md),
   [`158`](158_recall-expansion-silent-and-frontier-failures.md); confirmed live by
   [`benchmark/toolathlon/additivity.py --check`](../benchmark/toolathlon/additivity.py):
   terminal-error 95.0% precision, 1.45% recall, 0.24% false-alarm). So the
   product is **the corpus, not the catch** — see §4.
4. **`verify()` abstains on judgment, and its own lowest rung is forgeable.** It
   grounds the artifact-checkable slice and returns `source=none` on the rest; and
   its grep rung can self-certify on a commit *subject* (the *measure-the-rung-not-the-verdict*
   hole, observed live). DOS's advantage is that it *names the rung*, not that its
   floor is sound.

The motif that recurs in every row: **each benchmark's authors already ran a
manual version of the DOS forensic pass** — METR's maintainer review, OpenAI's
138-problem o3 audit, SWE-bench+'s filtering, WebArena Verified's backend re-check.
DOS is the reusable, typed form of an audit each of these teams had to hand-build
once. The pitch is never "DOS would have found this"; it is "DOS is the audit you
already ran by hand, made a reusable corpus."

---

## 1. The grader-trust taxonomy — four kinds, four DOS responses

The per-benchmark rows below are evidence for one claim: **the dominant grader
failure across agent benchmarks is over-optimism from a forgeable proxy**, and it
comes in exactly four kinds — which matter because they map to four *different* DOS
responses (and two of the four are honest non-wins):

| Kind | What it is | Example (cited below) | DOS's response | Honest? |
|---|---|---|---|---|
| **(i) Weak / narrow / wide tests** | grader *correctness* — the test is too loose (passes wrong code) or too strict (rejects right code) | OpenAI: 59.4% of o3's failed cases had flawed tests; SWE-bench+: 31% weak-test passes | DOS offers *typed bins* (a `refuse` vocabulary) but **does not fill them** — deciding a passing patch is functionally-wrong-but-test-weak is the judgment `verify()` ABSTAINS on. DOS *separates* rows for a human/JUDGE to label. | **Not a DOS win** — grader-correctness is outside the oracle. DOS bins, doesn't fix. |
| **(ii) Corrupt success / right-state-wrong-path** | process-blind final-state grading: the post-state is correct but reached by a forbidden/fabricated path | τ-bench: a procedure-aware re-grade found 27–78% corrupt successes (per model, preprint) | DOS reaches the **fabrication subset** cleanly (§2 τ-bench) and the **wrong-path subset only weakly**, via trajectory *ordering* (`tool_stream`), because the final artifact is byte-identical to a clean success — see §3.2. | **Partial** — clean on fabrication, blind on correct-state-wrong-path unless it reads ordering. |
| **(iii) Fabrication / missing witness** | the agent *asserts* a value its tools never *returned* | τ-bench fabricated flight/price/user-ID; AgentDojo injected-instruction-as-command | **DOS's clean ORACLE win.** A claim with no THIRD_PARTY witness in the spine is `AGENT_AUTHORED` — structurally cannot be believed (`believe_under_floor`). | **Yes** — this is the strongest case in the doc. |
| **(iv) Contamination / memorization** | a right answer recalled from training, not solved | SWE-bench+ solution-leakage 33%; GAIA/MLE-bench/Cybench public splits | DOS's **trace-grounding win — *if a tool witness exists***: a right answer with no witnessing tool-result in the spine is `AGENT_AUTHORED` (recalled, not solved). Weak where the answer legitimately has no tool witness (math). | **Conditional** — needs a tool-call chain to ground against. |

The unifying fix-shape is DOS's central axiom: **believe only an un-authored
(`THIRD_PARTY` / `OS_RECORDED`) source.** A verdict whose supporting bytes have no
independent witness in the spine should not be a clean "pass." But two of the four
kinds (i, and the wrong-path half of ii) are *not* clean DOS wins, and the doc says
so out loud.

---

## 2. Per-benchmark rows

Ordered strongest-DOS-case first. Each row: grader mechanism → cited trust stat
(hedged) → which of the four kinds → DOS's response with the **rung and bound
stated inline**. All statistics below were adversarially re-verified against
primary sources; corrections from that pass are folded in.

### 2.1 τ-bench / τ²-bench — DOS's wheelhouse, and the limit of it

- **Grades:** final DB-state set-equality against an annotated goal state, plus
  `pass^k` reliability over repeated trials. τ² adds a dual-control user simulator.
- **Trust problem (kinds ii + iii).** Final-state is blind to the *process*:
  "corrupt success" = right end-state via a fabricated or policy-violating path. A
  single procedure-aware re-grading (**arXiv 2603.03116, a March-2026 preprint**,
  evaluating GPT-5 / Kimi-K2-Thinking / Mistral-Large-3 — **not** gpt-4o) found
  **27–78% of reported successes were corrupt successes** depending on model (the
  78% is Kimi-K2-Thinking concentrated in policy-compliance; the 63 audited cases
  are the Mistral airline subset of 131). *Treat the 27–78% as one un-replicated
  preprint with a wide per-model range, not a stylized fact.* Separately, the
  original τ-bench paper (arXiv 2406.12045) shows runs are *unreliable*: gpt-4o
  succeeds on **under 50%** of tasks at pass@1 and **under 25% at pass^8** in
  retail — single-run success is not reproducible. (The earlier draft of this
  survey cited ">60% pass@1" for gpt-4o; that is **refuted** — it is <50%.)
- **DOS response.** *Lead with the bound:* DOS adds a **thin, high-precision
  (~92–95% precision), low-recall (~1–6%) layer** of un-deniable flags on top of
  the final-state grader — it does **not** relabel the 27–78%. Within that thin
  layer: (1) `arg_provenance` / the Accountability axiom catches the **fabrication
  subset** cleanly — a flight number or price asserted in the agent's text but never
  returned by a tool is `AGENT_AUTHORED` (the ORACLE rung; this is the doc's
  cleanest win). (2) `tool_stream` / `liveness` flags policy-loop spinning. But the
  *correct-state-wrong-path* subset (kind ii) is byte-identical to a clean success
  and the forgeability argument **does not reach it** — only the weaker, lower-precision
  ordering signal does (§3.2). So DOS catches *fabrication*, partially reaches
  *wrong-path*, and is honest that the headline 27–78% is mostly the latter.

### 2.2 WebArena / VisualWebArena — DOS converges with the fix the authors already shipped

- **Grades:** programmatic reward functions — `string_match` / `fuzzy_match` /
  `must_include` on the rendered answer, URL-match, some backend-state checks.
  Binary per task. VWA adds VQA + SSIM image comparators.
- **Trust problem (kinds i + iii).** Reward brittleness *both* directions: substring
  matchers over-credit partial matches and can credit "N/A" *without verifying the
  agent attempted the task* (false **positives**), while penalizing correct-but-rephrased
  answers (false **negatives**). **WebArena Verified** (ServiceNow, NeurIPS 2025 SEA
  Workshop) re-audited all 812 tasks and **cut the false-negative rate by 11.3
  percentage points** by replacing substring matching with type/normalization-aware
  comparators *plus backend-state verification* (brittle matching also inflated
  success ~1.4–5.2%, paper-cited, one notch less verified). VWA: 8.7% of 910 tasks
  need exact image match; best agent at publication 16.4% vs 88.7% human (a Jan-2024
  GPT-4V-era figure, not current SOTA).
- **DOS response.** The WebArena Verified fix — *"verify the backend state for
  state-changing tasks instead of trusting the rendered string"* — **is `verify()`'s
  thesis** (grade the un-authored DB artifact, not the self-narrated answer string).
  The honest framing is **convergence, not replacement**: WebArena Verified already
  built the backend-state check by hand; DOS's claim is only that it is the
  *generalized, typed, auditable* form of a fix the authors independently validated.
  The "credit N/A without an attempt" false-positive is a missing-`THIRD_PARTY`-witness
  case: no state-change artifact ⇒ the effect never happened, which the axiom catches
  structurally. **Bound:** helps on *state-changing* tasks (un-authored artifact
  exists); pure information-retrieval answer-string tasks remain a normalization
  judgment DOS abstains on.

### 2.3 GAIA — the trace-grounding case, and where it thins out

- **Grades:** quasi-exact-match — the final answer is normalized by ground-truth
  "type" and compared to a single annotated answer. 466 questions (166 public / 300
  held-out). The reasoning trace is **not** graded.
- **Trust problem (kinds i + iv).** (1) Brittleness: exact-match penalizes correct
  values embedded in reasoned prose; the paper itself states *"GAIA does not evaluate
  the trace leading to the answer."* (2) Contamination: the validation/dev split is
  public and has likely leaked into pretraining by 2025–2026. *(The earlier draft
  cited a ">5-point validation–test gap = contamination" heuristic — that is a
  third-party blog heuristic, **not** a formal GAIA criterion; dropped.)*
- **DOS response.** GAIA's own stated gap — *"we don't evaluate the trace"* — is
  precisely what DOS's correlation-spine is: the trace-as-evidence corpus. A grader
  could check the answer was *reached* via a real tool-call chain (a `THIRD_PARTY`
  web-fetch witnessed the fact), separating a grounded solve from a
  memorized-validation guess: a right answer with **no witnessing tool-result in the
  spine** is the `AGENT_AUTHORED` rung the axiom distrusts (kind iv). **Bound, and
  it is a real one:** GAIA answers frequently have *no* tool witness even when
  legitimately solved (a multi-hop reasoning answer the model computed in-context),
  so the trace-grounding signal is *present but partial* — and DOS cannot adjudicate
  free-form answer equivalence (the brittle-string-match kind-i problem is a judgment
  it abstains on).

### 2.4 SWE-bench / SWE-bench Verified — the right shape, and the correctness-vs-honesty line

- **Grades:** a held-out FAIL_TO_PASS + PASS_TO_PASS unit-test suite is run against
  the patch; resolved iff the designated tests flip/stay green. "Verified" is a
  500-instance human-screened subset.
- **Trust problem (kinds i + iv), three independent audits all pointing at
  over-optimism.** (1) **METR** (note 2026-03-10): expert maintainers reviewed 296
  SWE-bench-passing AI PRs; the automated grader runs **~24.2pp higher (SE 2.7)**
  than maintainer merge decisions, and while **100% of golden patches pass the
  grader, only ~68% are actually merged** — from which METR's headline *"roughly half
  of passing PRs would not be merged"* follows as a **normalized estimate** (not a
  literal measured 50%; attribute it that way). (2) **OpenAI** (*"why we no longer
  evaluate SWE-bench Verified"*): of 138 problems o3 failed, **59.4% had material
  test/spec flaws** (35.5% narrow tests rejecting functionally-correct patches, 18.8%
  wide tests checking unspecified behavior). (3) **SWE-bench+** (arXiv 2410.06992):
  **32.67% solution leakage** (fix shown in the issue/comments), **31.08% weak-test
  passes**, resolution dropping 12.47%→3.97% after filtering; the *"SWE-bench
  Illusion"* (arXiv 2506.12286) found models recall buggy file paths from issue text
  alone *up to* 76% (vs *up to* 53% on outside repos) — memorization, not reasoning.
- **DOS response — and the sharpest honesty line in the doc.** `verify()` is the
  right *shape*, but **DOS must not conflate correctness with honesty.** The OpenAI
  59.4%-flawed-tests slice is a **grader-correctness** problem (kind i): DOS has no
  model of intended behavior, so it **cannot** autonomously decide a passing patch is
  functionally-wrong-but-test-weak — that is exactly what the oracle ABSTAINS on. What
  DOS *does*: (a) the correlation-spine builds a `(claim=resolved, which FAIL_TO_PASS
  test flipped, the diff, verdict)` corpus so the weak-test-pass and narrow-test-reject
  rows are **separable and re-gradeable** *when a human supplies the labels* — it
  offers bins, it does not fill them; (b) the Accountability axiom flags **solution
  leakage** (kind iv) — a patch whose bytes were authored in the issue/comment stream
  is `AGENT_AUTHORED`-adjacent, not an independent solve. **And the self-incriminating
  caveat:** SWE-bench's "resolved" binary is exactly the kind a *grep-rung* `verify()`
  would self-certify on a commit subject containing the test name — DOS's own lowest
  rung is forgeable in the same family as SWE-bench's weak-test rung. DOS's advantage
  is that it *names the rung* (grep vs. ancestry vs. artifact), not that its floor is
  sound.

### 2.5 The LLM-as-judge family (MT-Bench, AlpacaEval, Arena-Hard, Chatbot Arena) — where the ORACLE rung is *empty*

- **Grades:** a strong model scores a single answer or picks a pairwise winner; the
  judge's verdict *is* the grade. The dominant mode wherever no programmatic oracle
  exists.
- **Trust problem (the breakdown case — see §3.1).** The judge is itself an unverified
  agent whose verdict is a self-report about quality, and it is systematically biased.
  **CALM** (arXiv 2410.02736) quantifies 12 bias types: position-bias robustness as
  low as **0.566** (ChatGPT, the lowest tested); self-enhancement error ~**1.16%**
  (GPT-4-Turbo) → ~**16.1%** (Qwen2) — judges favor their own outputs (the precise
  percentages are confirmed-once; the *direction* is robust); verbosity-bias robustness
  0.977 (GPT-4o) vs 0.900 (ChatGPT). Position bias's dependence on option-count is
  **capability-dependent**, not a universal "worsens with more options" law (arXiv
  2406.07791): capable judges hold consistency, weak ones degrade.
- **DOS response — the honest non-win.** This is DOS's sharpest *structural* argument
  and its clearest *limit*. A judge scoring outputs its own family produced violates
  the **referee-can't-report-to-a-contestant** separation, and self-enhancement bias
  is the axiom's empirical confirmation (a model re-deriving another model's bytes is
  *consistency, not grounding*). But here **there is no un-forgeable byte** — the
  "correct answer" is generation #2 about generation #1. DOS does **not** ground this;
  it correctly **demotes to the JUDGE rung** (`judges.py`: advisory, deterministic-first,
  fail-to-abstain) and *inherits* the judge's biases. The honest claim is "DOS makes
  the rung *visible* — you are on JUDGE, not ORACLE — and fails-to-abstain on the
  residue," **not** "DOS grounds it." The spine still adds value: it records
  `(judge claim, the artifact it should have grounded against, deterministic verdict)`
  so the gamed cases become *auditable* — but on pure style/helpfulness DOS abstains
  too, shrinking the judge's territory to the irreducible seed, not eliminating it.

### 2.6 A reasoning/math benchmark (GSM8K / MATH / AIME) — the floor of DOS's usefulness

- **Grades:** the final answer is a number; an exact/normalized check against the
  gold answer. Robust grader.
- **Trust problem (kind iv only).** When the grader is already a clean un-authored
  check, **contamination is the only live problem** — public splits leak into
  pretraining (GSM1K, Zhang et al. 2024, rebuilt GSM8K fresh and exposed drops
  correlated with a model's probability of *generating* the originals — see
  [`167 §1.1`](167_the-eval-and-naive-verifier-comparison.md)).
- **DOS response — the bound from the other side.** When the grader is good, the only
  thing DOS's spine adds is contamination/trace-grounding (was the answer *reached* or
  *recalled*?), **and even that is weak** because a math answer often has *no tool-call
  witness at all* — the model computed it in-context, so there is nothing for the spine
  to ground against. This is the *floor* of DOS's usefulness, stated deliberately: on a
  clean-oracle, no-tool-witness benchmark, DOS adds nearly nothing, and the doc says so.
  (HumanEval / MBPP are the same floor for code: pure unit-test graders on self-contained
  functions, near-saturated, heavily contaminated — DOS's artifact slice is trivially
  clean, so it adds nothing there either.)

### 2.7 The rest of the agent-eval zoo (roundup)

- **Toolathlon** (32 apps / 604 tools / 108 tasks / ~20 turns; arXiv 2510.25726) —
  final-state verification scripts, process-blind on a 20-turn horizon. **DOS has
  already been run here**, so the value is *measured, not hypothetical*: `tool_stream`
  / `terminal_error` / `dangling_intent` add a ~92–98%-precision, ~1–6%-recall process-failure
  layer; terminal-error is a byte-clean additive signal (95.0% precision, 1.45% recall,
  +30% relative union-recall — [`additivity.py`](../benchmark/toolathlon/additivity.py),
  [`157`](157_toolathlon-replay-detector-purchase.md)/[`158`](158_recall-expansion-silent-and-frontier-failures.md)).
  This is the doc's empirical anchor and its humility check: union recall is *low* and
  the signal *weakens on strong models*.
- **MLE-bench** (75 Kaggle competitions; o1-preview+AIDE bronze in 16.9%; arXiv
  2410.07095) — sound held-out metric, but the *run integrity* is weak: OpenAI
  **paused the leaderboard (~2026-04)** to build a fairer submission process — an
  admission the grader can't police contamination/rule-violations. DOS's `liveness`/trace
  is the missing integrity instrument (a winning artifact with no witnessed training run
  is the leaked-solution rung; leasing the data region makes test-set peeking a
  `refuse`-able event). Contamination % UNVERIFIED.
- **Cybench** (40 CTF tasks, 4 competitions, 6 domains; arXiv 2408.08926) — the
  **flag oracle is the gold-standard grader** (a secret string the agent did not author
  — the axiom's strongest rung). DOS *learns from* it, doesn't patch it; its only lift
  is contamination/process (a flag reached with no witnessed exploit chain is a
  memorized leak). Contamination rate UNVERIFIED.
- **AgentDojo** (97 tasks, 629 security cases, 4 envs; arXiv 2406.13352) — dual
  programmatic checks (utility + attack-success-rate). A **natural fit for the axiom**:
  a prompt-injection *is* a byte-provenance violation — an instruction that entered via
  `THIRD_PARTY` tool data being treated as a user command is exactly the
  agent-authored-vs-environment-authored confusion the axiom names; `arg_provenance`
  attributes each malicious tool-call to its byte-author, making ASR a *provenance
  verdict* rather than a final-state guess. (GPT-4o ~69% benign / ~45% under attack /
  ~53% targeted ASR are v1 figures; v3 revised to ~50% / ~48%.) **Bound:** catches the
  high-precision provenance-violation slice; novel injections with no distinct
  byte-author signal remain for the benchmark's adaptive attacks.
- **BIRD (text-to-SQL)** (12,751 pairs / 95 DBs / 37 domains; arXiv 2305.03111) —
  denotation-match against one gold query, both too strict and too loose. **FLEX**
  (NAACL 2025) found BIRD's execution-accuracy reaches only *substantial* agreement
  with human experts (**Cohen's κ = 0.62; ~81% raw accuracy** on a balanced 200-query
  audit — note: the popular "62% agreement / 40% disagreement" phrasing **conflates the
  κ coefficient with a percentage** and overstates disagreement; true raw disagreement
  ~19%). DOS's contribution is **principled abstention**: where execution-accuracy and
  human judgment diverge, the honest verdict is ABSTAIN-to-human (SQL equivalence is a
  judgment call / undecidable in general), not a falsely-confident binary — converting
  the binary into abstain+evidence is a calibration win, not a coverage one.
- **SWE-Lancer** (1,400+ Upwork tasks, $1M payouts; arXiv 2502.12115), **Terminal-Bench**
  (89 tasks; arXiv 2601.11868), **SWT-bench** (test-generation, Lite=276; arXiv
  2406.12952) — all grade against a genuinely un-authored artifact (E2E flows / final
  container state / a golden patch's fail-to-pass behavior), so they are **`verify()`
  in the wild**, the design DOS would copy. Their residual weaknesses: SWE-Lancer's
  E2E suite has a documented test-overwrite vulnerability (the agent can overwrite the
  password-zipped tests — a `SELF_MODIFY` hazard by another name; *do not cite the
  unverified "99% agreement" figure*); Terminal-Bench's own maintainers flag flakiness
  (non-determinism from CPU arch / external APIs), which `liveness` (ADVANCING vs
  STALLED-on-external-API) can *label* so the grader stops scoring infra noise as
  capability; SWT-bench's fail-to-pass is gameable in shape (a test flipping on an
  incidental side-effect, not the bug behavior — UNVERIFIED rate). **AgentBench**
  (arXiv 2308.03688) is *not* a clean LLM-judge example — its 8 environments are
  **all rule-based** (its only model-in-the-loop is a card-game *host*, not a grader);
  its lift is uniformity (one evidence layer across heterogeneous envs), an
  instrumentation argument, not a measured flaw-fix (magnitude UNVERIFIED).

---

## 3. Where the forgeability axis is right — and the two places it breaks

The axis (believe only across the agent-authorship line) is the right tool when an
un-authored, third-party-witnessed artifact exists: τ-bench fabricated values
(witness-absent ⇒ `AGENT_AUTHORED`), WebArena state-changing tasks (the DB row is
env-authored), GAIA contamination (an answer with no tool witness). But it breaks in
two distinct, citable ways, and a survey that hides them is the over-claim it warns
against.

### 3.1 When the benchmark's ground truth is itself a model judgment

LLM-as-judge (MT-Bench, Arena, AlpacaEval), the LLM-judge slices of mixed benchmarks,
τ²'s user-simulator: **there is no un-forgeable byte.** The "correct answer" is
generation #2 about generation #1 — the structure that can *refute* but never *be
believed* ([`167 §3`](167_the-eval-and-naive-verifier-comparison.md)). DOS does not
solve this; it **demotes to the JUDGE rung and inherits the judge's biases.** The
honest claim is "DOS makes the rung *visible* (JUDGE, not ORACLE) and fails-to-abstain,"
not "DOS grounds it." The axis sorts correctly — it *tells you the ground truth is
forgeable* — but it offers no oracle where the field most wants one.

### 3.2 When the env post-state is authored by the agent's own writes

This is the subtle one. In τ-bench / WebArena, *some* state changes **are** the
agent's authorized effect — it is *supposed* to write the DB row. When the agent
writes row X via a *forbidden path* and the row is correct, the post-state is
**byte-identical** to a clean success. So the forgeability axis catches *fabrication*
(asserted-but-never-written, §kind iii) cleanly, but it is **blind to corrupt success
where the write happened via a forbidden path** — the procedure violation lives in the
*trajectory ordering*, not the final artifact. `tool_stream` / trace can *sometimes*
see the bad ordering, but that is a weaker, lower-precision signal than the clean
byte-author argument. **Consequence:** the doc must not imply the Accountability axiom
catches the headline τ-bench 27–78% — it catches the *fabrication subset*, and reaches
the *correct-state-wrong-path subset* only weakly, via ordering. The axiom's reach onto
that headline number is partial by construction.

---

## 4. The strongest objection — "the recall objection" — and the honest rebuttal

A τ-bench / SWE-bench author raises the killer, and it is sourced *from DOS's own
measurements* (the weak-plus-substrate finding in [`153`](153_can-dos-lift-a-weak-model.md):
conversion-ceiling 0.00pp on gpt-5 / gemini-3-pro / claude-4.5):

> *"Your own data says ~1–6% recall and that the effect vanishes on the strongest
> model. My benchmark exists to rank frontier models. A re-grader that fires on a
> handful of cases and goes silent exactly where I need it most doesn't improve my
> benchmark — it improves my benchmark's evaluation of weak models, which I don't
> care about. You're selling me a flashlight that dims as it gets dark."*

This is true, and a dodge would sink the doc. The honest rebuttal **reframes the
product from the catch to the corpus**:

> DOS does not propose to raise your model ranking's recall. It converts your *binary,
> forgeable grader into a labeled-evidence corpus* — and **that value is independent of
> recall and independent of model strength.** Even at 0% relabeling, the spine turns
> "271 of 1000 passed" into "271 passed, of which N were witnessed by an independent
> tool-result, M were `AGENT_AUTHORED`-adjacent (leaked / fabricated), and K abstained."
> That decomposition is the deliverable; the high-precision flags are a *bonus on the
> weak-model tail*, not the product. A benchmark author's real pain is not "I can't
> catch the best model's rare lie" — it is "my single resolved/not-resolved bit can't
> distinguish a real solve from a leaked-solution pass (SWE-bench+: 33%), and I have no
> audit trail to re-grade a disputed score." DOS sells the **audit trail and the
> rung-typing** — exactly what METR, OpenAI, SWE-bench+, and WebArena Verified each had
> to *hand-build once, post-hoc.* DOS is the productized, typed, reusable form of the
> forensic pass each of those teams ran by hand. **The recall number is irrelevant to
> that claim** — which is why this doc's spine is *corpus-not-catch*, and why every
> "DOS catches X" sentence above carries its rung and its bound in the same breath.

---

## 5. What DOS does NOT do (the hard boundary)

A box, not prose, because the doc means these literally:

- **It does not decide a test is wrong.** Grader-correctness (narrow/wide/weak tests,
  the OpenAI 59.4%) is outside the oracle; DOS offers bins, a human/JUDGE fills them.
- **It does not reproduce human merge judgment.** The METR 24.2pp "would-a-human-merge"
  gap is a judgment call; `verify()` abstains on it.
- **It does not adjudicate free-form answer equivalence** (GAIA's normalizer, BIRD's
  SQL equivalence) — it REFUSES to certify, converting a falsely-confident binary into
  an explicit abstain+evidence.
- **It does not fix LLM-judge bias** — where the ground truth is a model, the ORACLE
  rung is empty and DOS inherits the JUDGE's biases (it only makes the rung visible).
- **Its own grep rung is forgeable** (commit-subject self-certification) — the advantage
  is naming the rung, not a sound floor.
- **Its effect concentrates on weak models** and its measured recall is low (~1–6%) —
  the product is the corpus, not the catch.

---

## Related reading

- **[`167_the-eval-and-naive-verifier-comparison.md`](167_the-eval-and-naive-verifier-comparison.md)**
  — the taxonomy this doc applies: the forgeability axis, eval concepts vs. naive
  verifiers, the `Accountability` spectrum and `believe_under_floor`.
- **[`84_ground-truth-trajectories-for-training.md`](84_ground-truth-trajectories-for-training.md)**
  — the lie-vs-flake irreducibility result and the contamination-at-the-source table
  (METR's grader over-optimism, PAE's procedurally-corrupt successes) that seeds §1.
- **[`157`](157_toolathlon-replay-detector-purchase.md)** /
  **[`158`](158_recall-expansion-silent-and-frontier-failures.md)** /
  **[`benchmark/toolathlon/additivity.py`](../benchmark/toolathlon/additivity.py)** —
  the measured DOS detector numbers (the §1 claim-3 bound) and the SSOT behind them.
- **[`138_what-is-truth-the-throughline.md`](138_what-is-truth-the-throughline.md)** —
  the byte-author-≠-judged-agent invariant the whole survey rests on.
- **Strategy (philosophy, not mechanism):**
  [`dispatch-os-evals-vs-verification.md`](../../dos-private/dispatch-os-evals-vs-verification.md)
  and
  [`dispatch-os-the-verification-substrate-for-agentic-rl.md`](../../dos-private/dispatch-os-the-verification-substrate-for-agentic-rl.md)
  — read for *why eval ≠ verification*; this doc is the benchmark-grounded *where*.

> **Sourcing note.** Every load-bearing statistic above was adversarially re-verified
> against its primary source in a dedicated pass; corrections are folded in (τ-bench's
> ">60% pass@1" refuted to <50% and the 27–78% scoped to a GPT-5/Kimi/Mistral preprint,
> not gpt-4o; BIRD's "62%/40%" corrected to κ=0.62 / ~81% accuracy; GAIA's ">5pt"
> heuristic dropped; METR's "~50%" attributed as a normalized derivation; SWE-Lancer's
> "99%" dropped as unverifiable; AgentDojo's GPT-4o figures scoped to v1; Cybench's
> "39-task" variant dropped; AgentBench corrected to all-rule-based). Items marked
> UNVERIFIED (MLE-bench / Cybench contamination rates, SWT-bench incidental-flip rate,
> AgentBench magnitude) are flagged inline. The DOS-side detector numbers are
> DOS-internal measurements ([`157`](157_toolathlon-replay-detector-purchase.md)/[`158`](158_recall-expansion-silent-and-frontier-failures.md)),
> not third-party-verified, and are labeled as such. Re-verify against primary sources
> before any external use.
