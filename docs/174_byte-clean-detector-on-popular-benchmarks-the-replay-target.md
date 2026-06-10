# 174 — The byte-clean detector on POPULAR benchmarks: the replay target + build-vs-extend call

> Status: decision memo (2026-06-05). Grounded in a 13-agent research workflow
> (`wf_493d1694-771`) with web-confirmed artifact availability and an adversarial pass
> that loaded the actual datasets. Where survey optimism and the adversarial check
> conflicted, the adversarial correction wins (it loaded the bytes; the survey read
> abstracts). The shipped method this extends: docs/166 §4b-ii
> (`benchmark/agenthallu/detector.py`, commit `660b6a2`).

## The question

Can the byte-clean **structural error-channel + unrecovered-error-gate** step-localizer
(false-alarm 35.2%→1.2%, 83.8% precision, 30.1% exact on AgentHallu) apply to **more
popular** benchmarks so a result lands harder than on a niche 700-trajectory corpus —
and/or should we build our own?

## The method's two halves (what a target must supply)

1. **Structural error-CHANNEL** — fire on env-authored `{"error":...}` keys / `Traceback` /
   non-zero-exit in tool RESULT bytes, never an error WORD in legit data. Needs: replayable
   per-step **tool result bytes**.
2. **The unrecovered-error GATE** — suppress if a later step at the same locus returned clean.
   Needs: **multi-step trajectories** where errors can be recovered (else the gate is inert).

Plus, to *score*: a **per-step gold** label. The invariant: byte-author ≠ judged-agent — read
only env bytes, never agent narration or a satisfaction predicate.

## The shortlist (survives both halves + $0-replay + per-step gold)

### #1 — AgentProcessBench (RUCBM, arXiv 2603.14465) — the one true fit
- **Artifact:** `huggingface.co/datasets/LulaCola/AgentProcessBench` (MIT, 40 MB, 4 configs:
  `bfcl` / `gaia_dev` / `hotpotqa` / `tau2`, `split=test`). Code: `github.com/RUCBM/AgentProcessBench`.
- **Witness (confirmed by loading row 0):** `tool_metrics{tool:[{status:success/error}]}` +
  `role:"tool"` messages with literal `{"error":...}` keys (e.g. `mv: cannot move ... No such
  file or directory`), AND a real error→clean **recovery** pair (cp: 3 errors then a later
  success). Byte-clean; the gate has bite.
- **Gold:** **per-step** — `step_labels {idx:+1/0/-1}`, 8,509 human labels, 89.1% IAA. Paper's
  metric **FirstErrAcc** = AgentHallu's exact-step-localization analogue. Published bar:
  Gemini-3-Flash-Thinking 81.6% StepAcc / 65.8% FirstErrAcc across 20 LLM-judge baselines.
- **Why #1:** the *only* candidate that is simultaneously $0 static-replay, per-step human gold,
  data drawn from the popular benches (BFCL/tau2/GAIA/HotpotQA), AND has a published LLM-judge
  leaderboard to contrast — the exact "$0 deterministic detector vs expensive judge" framing DOS
  already won on AgentHallu, now on a bigger, more-popular corpus.
- **THE CEILING (material — do not skip):** gold measures task **effectiveness** (+1 advances /
  −1 incorrect-or-counterproductive), **not** tool-execution errors. A `−1` can sit on a
  `status:success` step where the agent chose wrong *logic* — which a byte-clean detector is
  blind to by design. So we **cannot** claim parity with 81.6% StepAcc on the full corpus (a
  superset task). Defensible target = FirstErrAcc on the **error-caused-divergence slice** +
  false-alarm reduction on bfcl/tau2. Free-text `gaia_dev`/`hotpotqa` degrade (GAIA row 0 had no
  structured error key) — restrict the headline to bfcl/tau2.

### #2 — TRAIL (Patronus AI, arXiv 2505.08638) — narrow cheap-floor, NOT a strong secondary
- Un-gated mirror `github.com/patronus-ai/trail-benchmark` (`data/{GAIA,SWE_bench}/*.json`),
  OTel spans with `status_code:"Error"` + per-span gold. **Blocker:** the System-Execution error
  class the method may legitimately read is **~8% of 841 errors (~67 corpus-wide)**; ~92% is
  Output-Generation/Reasoning — forgeable judgments the invariant forbids. Use only as a thin
  "survives a second annotation scheme" floor on GAIA, never a topline (it already has a strong
  SOTA, arXiv 2605.14865).

### #3 — AgentHallu (the anchor we hold) — keep, don't abandon
- Validated $0 third-party-gold home of the method (per-step `hallucination_step`). But niche
  (700 traj) and the recovery gate is thinly exercised (4 suppressions). It is the credibility
  anchor; it does **not** by itself answer "land harder on a popular benchmark" — that is the gap
  #1 fills.

## The boundary (do NOT target — the method's honest domain limit)

Refuted by the adversarial pass (survey was over-optimistic):
- **SWE-bench/experiments** — `test_output.txt` is a single *final-patch* eval, no per-step
  sequence → **recovery gate inert**; `trajs/*.traj` unstandardized + often absent; S3-cred wall
  (not git-clone $0); `resolved` gold ≥59.4% flawed (OpenAI Feb-2026 audit; bench retired). Usable
  only for the channel half.
- **OpenHands SWE dumps** (nvidia/SWE-Hero, nebius, SWE-Gym) — HF serialization **flattens to
  chat messages and strips** `observation.is_error`/`exit_code`; gold trajectory-level or absent.
  $0 to read, not to score-as-specified.
- **HAL / hal_traces** — traces are per-scaffold Weave **LLM-call** logs (no unified env-observation
  field; observations nested in the **agent-authored** payload → breaks the invariant); step
  findings are LLM-judge, not gold. The "9-bench schema lever" is structurally false.
- **GAIA (raw)** — QA pairs only, zero trajectories.
- **tau-bench/BFCL/AppWorld/WebArena (live)** — live-execution, not statically replayable; the
  BFCL/tau signal is already covered by #1+#3.
- **WebArena/RepoBench/Aider/SWE-bench Multimodal-Pro** — no env error-channel and/or no public
  per-step dump.

**Silent-failure boundary (put in the paper):** the detector reads env error *bytes*; it is blind
by construction to failures emitting no error byte — **MALT** (sandbagging/refusal), **RHB/
SpecBench** (reward-hacking = silent success-by-shortcut), **HalluLens/FaithBench** (pure text, no
env, labels over model-authored bytes). Those are narration/provenance problems — the
`arg_provenance` line's territory, not this detector's. Don't force the method onto them.

## Build-vs-extend: REPLAY-FIRST on AgentProcessBench

Do **not** build-our-own first. Reasoning:
- Replay borrows the expensive ingredient (8,509 human per-step labels, MIT) at ~**1 engineer-day,
  $0 model spend**; reuse `benchmark/agenthallu/{detector,scoring}.py` wholesale + one adapter
  (`messages`+`tool_metrics` → per-step `(tool, args, result, status)` stream). It lands the proven
  method on popular-bench data against a *published* judge leaderboard.
- The **concurrency build-own** (SAFEFLOW/CART gap) is REFUTED for *this* method: (a) not
  $0-replayable — SAFEFLOW/CART ships no repo/scenarios/grader; (b) the method doesn't transfer —
  concurrency failures are silent races caught by the **arbiter/WAL at write-time**, a *different*
  DOS mechanism with no error key and no recovery gate; (c) FleetHorizon, the closest local
  instrument, is fatally **simulated** (`benchmark/fleet_horizon/agent.py` = `random.Random`
  drawing lie/flake/success — byte-author == the bench's own RNG, nothing to distrust). The
  concurrency suite is a real *later, narrow* ARBITER-mechanism opening (needs a live-LLM arm +
  must clear BenchJack's <10%-hackable bar), but it lands softer than a replay — do NOT lead with it.

**Sequence:** AgentHallu (anchor, held) → AgentProcessBench (popularity/per-step-gold replay = the
headline) → TRAIL (thin 2nd-scheme floor) → only then a live-LLM concurrency arm for the arbiter.

## PROBE RESULT (2026-06-05) — K2 FIRED: reframe, do not claim parity

The $0 probe below was **run firsthand** (loaded `LulaCola/AgentProcessBench` bfcl+tau2,
500 trajectories). The schema confirmed exactly (4 configs × 250; `messages` / `tool_metrics`
{tool:[{status:success/error}]} / `step_labels` {idx:+1/0/−1} / `final_label`). The error channel
is real (`tool_metrics.status`: bfcl 166 errors in 100/250 traj; tau2 245 errors in 70/250) and
recovery exists (bfcl 115/250 have an error→clean pair; **tau2 has 0** text-level recoveries).

**But K2 — the label-semantics ceiling — FIRED hard.** Aligning the authoritative
`tool_metrics.status` channel to the gold `−1` steps:

| subset | localizable traj | first `−1` gold step coincides with a tool ERROR |
|---|---|---|
| bfcl | 184 | **20 (11%)** |
| tau2 | 143 | **39 (27%)** |

So **only 11–27% of gold first-divergences are error-caused** — the rest are *semantic*
divergences (wrong logic on a `status:success` call) that a byte-clean detector is blind to BY
DESIGN. The byte-clean **ceiling** on FirstErrAcc is therefore ~11–27%, **far below** the LLM-judge's
published 65.8%. The gold here measures task **effectiveness**, not tool errors — exactly the K2 risk,
now measured. **This kills the "matches/beats the judge on localization" headline before any build.**

**The honest reframe (this IS the result, not a failure):**
- AgentProcessBench is a **complementary deterministic floor on the error-caused slice**, NOT a
  head-to-head localization win. On the ~11–27% of divergences that *are* error-caused, a $0
  byte-clean detector localizes them deterministically at near-zero false-alarm — a floor the
  forgeable LLM judge must beat, and an **attribution** the pass/fail gold does not give.
- The dominant value is **measuring the boundary precisely**: on a per-step-human-labeled corpus
  drawn from popular benches, **73–89% of agent divergences leave no error byte** — they are
  semantic/effectiveness failures. That quantifies *where the byte-clean line ends* and where the
  judge/provenance rungs (ORACLE→JUDGE) must take over. That is a paper-worthy boundary result in the
  field's own data, and it is the docs/162 "errored ≠ wrong" scar generalized to a popular corpus.
- **Build decision:** a small adapter + scored floor is still worth ~1 day (it produces the boundary
  number + the error-slice floor), but **frame it as the boundary/floor result, not parity.** The
  detector must read `tool_metrics.status`, not only the message-text `{"error":...}` (tau2 flags
  errors in status, not always in text — the text-only scan under-counts).

## BUILT (2026-06-06) — `benchmark/agentprocessbench/`, the boundary measured

Shipped the module (dataset loader over the cached 4 configs + detector reading the authoritative
`tool_metrics.status` channel + SSOT scorer; `tests/test_agentprocessbench_replay.py`, 12 green).
The build CONFIRMED and sharpened the probe into a complete result:

| subset | error-caused boundary | error-slice FLOOR (`first_env_error`) | false-alarm | byte-clean ceiling vs judge 65.8% |
|---|---|---|---|---|
| **bfcl** | **20/184 = 10.9%** | **19/20 = 95.0%** | 40.3% (plain) / 1.6% (gated) | 10.3% |
| **tau2** | **39/143 = 27.3%** | **39/39 = 100.0%** | 5.8% (plain) / 1.9% (gated) | 27.3% |
| gaia_dev | 0/183 = 0.0% | — | 0.0% | 0.0% |
| hotpotqa | 1/104 = 1.0% | 100.0% | 0.7% | 1.0% |
| **structured headline** | **59/327 = 18.0%** | — | — | — |

**The two findings, both measured:**
1. **The BOUNDARY (the headline):** on the structured subsets **only 18.0% of gold first-divergences
   are error-caused — 82% are SILENT** semantic failures (wrong logic on a `status:success` call)
   that leave no error byte. The free-text subsets are ~0% error-caused (gaia 0/183), confirming the
   method has essentially nothing to read there. This quantifies, in the field's own per-step-labeled
   popular-bench data, exactly where the deterministic ORACLE rung ends and the JUDGE/provenance rung
   must take over. The byte-clean ceiling (10–27%) sits far below the judge's 65.8% **by construction**
   — and that gap IS the result, not a shortfall.
2. **The FLOOR (the positive result):** *where an error does cause the divergence,* the $0
   deterministic detector nails it — **bfcl 95.0%, tau2 100.0%** FirstErrAcc-on-slice — with
   attribution the pass/fail gold does not give, at zero model cost. A forgeable LLM judge must beat
   this floor on the slice where it is cheapest to be right.

**The recovery-gate nuance (a measured cross-corpus lesson, surfaced not hidden):** the AgentHallu
recovery gate is **corpus-dependent.** On tau2 it behaves (false-alarm 5.8%→1.9%, slice-hit 39→25).
On **bfcl it over-suppresses** (slice-hit 19→2) because bfcl divergences are predominantly
*errored-then-nominally-recovered-yet-still-wrong* — the docs/159 false-reassurance phenomenon: a
later same-tool success does NOT mean the original action was right. So the plain `first_env_error` is
the better bfcl floor (95% slice-hit, 40% false-alarm is its honest cost); the gate is a tau2/AgentHallu
tool, not universal. Both are registered + scored; the SSOT reports both so the trade-off is legible.

**Build decision RESOLVED:** done as a boundary+floor result (~the estimated 1 day), NOT a parity
claim. SSOT `--check` green; reproduce with `python -m benchmark.agentprocessbench.scoring --check`.

## The next $0 step: probe-first de-risk AgentProcessBench

Clone + schema-verify BEFORE any detector code (the AgentHallu discipline):
1. Pull the 4 configs from HF; on **raw rows** (the HF viewer errors) confirm `messages[]` carry
   `role:"tool"` bytes with `{"error":...}` on bfcl/tau2, `tool_metrics{status}` present,
   `step_labels {idx}` align to message indices.
2. Find ≥1 error→clean recovery pair in bfcl/tau2 (gate must bite — row 0 cp case is the existence
   proof).
3. **Quantify the ceiling (K2):** per subset, count `−1` gold steps that coincide with an env
   `status:error` vs sit on `status:success`. This sizes the achievable recall before committing a
   number.

**Kill-criteria (any → re-scope, not build):**
- **K1 recovery-gate inert** — bfcl/tau2 too short/non-recoverable. *(Low risk; row 0 has a case.)*
- **K2 label-semantics ceiling too low** — most `−1` are `status:success`-but-wrong-logic →
  byte-clean recall ceiling far below judge FirstErrAcc → reframe as a *complementary deterministic
  floor*, not a head-to-head win.
- **K3 free-text dominates** — gaia_dev/hotpotqa carry no structured error key → restrict headline
  to bfcl/tau2.

## The claim — CORRECTED by the probe (the boundary IS the result)

The probe forbids any "matches/beats the judge on localization" claim (byte-clean ceiling 11–27%
FirstErrAcc vs judge 65.8%). The defensible, measured claim is a **boundary + floor** result:

> On a per-step-human-labeled agent corpus drawn from popular benchmarks (BFCL, tau2), **only
> 11–27% of gold first-divergences are caused by an env-authored error** — the remaining 73–89% are
> semantic/effectiveness failures that leave no error byte. A $0, training-free, deterministic
> byte-clean detector reading only the env-authored tool-status channel localizes the error-caused
> slice deterministically at near-zero false-alarm and zero model cost — a floor a forgeable LLM
> judge must beat, with attribution the pass/fail label does not give — and the 73–89% it cannot see
> is the precise, measured boundary where the deterministic rung ends and the JUDGE/provenance rungs
> must take over (the docs/162 "errored ≠ wrong" scar, generalized to a popular corpus).

This is *stronger science* than a contested parity claim: it draws the byte-clean line exactly, in
the field's own per-step-labeled data, and motivates the ORACLE→JUDGE ladder with a number.

**Evidence state:** the 11–27% error-caused fraction is MEASURED (this probe). The error-slice
floor's exact FirstErrAcc + false-alarm on AgentProcessBench is NOT yet built (the ~1-day adapter,
reading `tool_metrics.status`, would produce it). The `<2%` false-alarm is proven only on AgentHallu
(1.2%). The recovery GATE is exercised on bfcl (115/250 have recovery pairs) but is INERT on tau2
(0 recoveries) — so the gate's cross-corpus generalization is partial, not universal.
