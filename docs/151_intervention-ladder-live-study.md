# 151 — Measuring the cost of acting on a true verdict: a live study of the intervention ladder

> **Type:** methodology + results paper (a self-contained writeup of the docs/144 live study).
> **Status:** complete. The kernel is shipped (docs/144); the live experiment ran end-to-end on
> the real `ServiceNow/EnterpriseOps-Gym` (2026-06-04). This document is the methods-and-results
> record — what we measured, how, what we found, and what holds under scrutiny.
>
> **One-sentence result:** a *sound* distrust verdict can be acted on four ways
> (OBSERVE / WARN / DEFER / BLOCK), and on the real benchmark the **least-disruptive that still
> informs (WARN) is the optimum** — the turn-preserving "non-disruptive BLOCK" we hypothesized
> would win is **neutral at best**, because withholding a call (even with a synthetic
> corrective result) breaks more downstream steps than it fixes.

---

## Abstract

DOS is a trust kernel: it adjudicates whether an autonomous agent's claims are grounded in
non-forgeable evidence, without believing the agent's self-report. Prior work (docs/143) shipped
`arg_provenance`, a detector for **minted identifiers** — foreign-key IDs an agent fabricates
instead of resolving from environment-authored bytes — and measured it sound on this benchmark
(0 % false-flag observed, ~83 % recall). It also surfaced a sharper problem: a *correct* catch, acted on
the wrong way, **hurt the task** (−9 pp). Detector-soundness and intervention-safety are
orthogonal.

This study builds and evaluates the **intervention ladder**: a closed, typed, rank-ordered
vocabulary for *how hard* a consumer acts on a verdict (`dos.intervention`, docs/144), plus an
eval that scores the **net task effect of acting**, not the accuracy of deciding
(`dos.intervention_eval`). We test it with a tiered experimental design — a free theory sweep, a
simulator, and a live A/B on the real gym — and find that the live data **falsifies our central
hypothesis** (the turn-preserving BLOCK is the prize) and **confirms the cheaper alternative**
(WARN, inform-and-still-dispatch). The free theory sweep *predicted* this before any API spend,
which is the methodological contribution: map the recovery-dynamics region first, then let the
expensive live run confirm a prediction rather than be a blind first data point.

---

## 1. Background and the question

### 1.1 Minting, and why it is the one binding that survives the byte-inequality axiom

The benchmark (EnterpriseOps-Gym; arXiv 2603.13594) puts an LLM agent in front of a 164-table
enterprise database exposed via MCP tools, and scores each task with **hidden, expert-authored
SQL verifiers run against the final DB state** — never the agent's narration, never the action
sequence. To act on a record the agent must reference its foreign-key ID (`INC0010023`,
`group_id=81`). The correct move is to *resolve* the ID — issue a read, observe the real ID, use
it. A weaker/cheaper agent **mints** it — fabricates a right-shaped but invented ID
(`INC9999999`) that points at no real row, silently corrupting the shared DB.

This is the one signal DOS can adjudicate **without believing the agent**: *did the ID's bytes
appear in prior environment-authored evidence (resolved), or were they authored by the model
(minted)?* It is a pure byte-provenance question — the only kind that survives DOS's axiom that
the byte-author must differ from the judged agent (docs/141). A self-authored "I verified the
row exists" predicate does not survive it; a byte-containment check does.

### 1.2 The orthogonality problem

docs/143's live run proved the detector sound but also showed the *default* intervention
(skip-the-call + re-prompt) was net-harmful: even on a true-positive catch, spending the agent's
turn derailed a *different* downstream step. The lesson: **a true verdict is necessary but not
sufficient; the intervention attached to it is where points are won or lost.** This study asks the
follow-on question: **of the ways to act on a true mint-verdict, which maximizes the net task
effect on real ground truth?**

---

## 2. The intervention ladder (the mechanism under test)

`dos.intervention` (kernel, pure, advisory) defines a **closed, rank-ordered** set — the
actuation dual of the closed refusal vocabulary `dos.reasons`:

| Rung | What the consumer does | Dispatches the real call? | Disruption |
|---|---|---|---|
| **OBSERVE** | record the verdict; agent never sees it | yes | none |
| **WARN** | annotate the agent's context, **then dispatch anyway** | yes | low (informs, never withholds) |
| **BLOCK** | withhold the call, return a **synthetic corrective result** ("id unresolved; use a read tool") in its place | no | medium (turn preserved, call withheld) |
| **DEFER** | skip the call and re-prompt; agent retries | no | high (spends the turn — the docs/143 −9 pp posture) |

Two design points, both load-bearing and both *measured corrections* to the original plan:

1. **The cost order is OBSERVE < WARN < BLOCK < DEFER** — BLOCK *below* DEFER, because BLOCK
   preserves the agent's turn while DEFER spends it. docs/144's prose had the reverse; the build
   inverted it on the measured reasoning, and a test pins it.
2. **Confidence-gating, refuse-LESS-only.** `assess_confidence` reads a high-confidence mint only
   off a whole-value-absent scalar id; a composite/partial is low-confidence. `choose_intervention`
   maps confidence → rung under a structural guarantee: a lower-confidence verdict can only ever
   map to a *no-more*-disruptive rung. (An adversarial review found this guarantee was enforced
   only against the built-in ladder, not a caller-supplied one — a real escalation hole —
   subsequently fixed by re-validating against the ladder actually in use, failing safe.)

`dos.intervention_eval` scores a *policy* (a confidence→rung mapping) by **net task delta** — the
sum over cases of `prevention − disruption` — with the dangerous cell being *wasted disruption*:
a withheld turn spent on a catch that did not matter to any verifier.

**The hypothesis this study tests:** BLOCK is the prize — a real PEP (the bad write never lands)
at WARN-level disruption (the turn is preserved), turning the live −9 pp positive.

---

## 3. Experimental design — a tiered ladder, cheap first

The expensive thing (a live A/B on real model + Docker + API spend) answers the question at **one
point** in a space of unknown recovery dynamics. So we built three tiers, each strictly cheaper
than the next, and climbed only as far as the question required.

| Tier | Instrument | Cost | What it answers |
|---|---|---|---|
| **0** | `intervention_theories.py` — sweep the simulator's recovery parameters, scored by the real `intervention_eval` | **$0, seconds** | *Under what assumptions does each rung win?* (the decision boundary) |
| **0b** | `intervention_ab.py` — the simulator at one tuned point | $0, seconds | mechanism check (BLOCK vs DEFER vs WARN) |
| **1** | `replay_recall.py` — re-score recorded real trajectories, no new model calls | $0 | detector precision/recall, variance-free |
| **2–4** | `live_ab.py` — the live A/B, scaled by `--tasks` (3 smoke → 12 pilot → 80 full) | minutes–hours, API $ | the ground-truth net effect on a real DB |

The decisive insight is that **Tier 0 is a predictor, not a warm-up.** Map the recovery-dynamics
region for free; then the live run either confirms the prediction (cheap was enough) or surprises
(the live run earned its cost). Either outcome is informative.

### 3.1 What the live run actually did (step by step)

For each of 80 tasks per arm, in each arm:

1. **Seed a fresh DB** — POST the task's seed SQL to the domain's Docker MCP server (each run
   isolated; arms never contaminate each other).
2. **Run the real agent loop** — gemini-2.5-flash drives the gym's ReAct loop over the real MCP
   tools.
3. **Inject the SAME mints** — before each mutating call, with prob `--mint-rate`, corrupt one
   correctly-resolved ID into a minted-looking one. A stable per-task seed means **every arm
   sees the identical corruptions**; the only between-arm difference is the intervention.
4. **Consult the kernel** — `arg_provenance.classify_call` folds over the env-authored bytes and
   returns RESOLVED/MINTED per argument.
5. **Act per the arm's rung** — `choose_intervention` → OBSERVE/WARN/DEFER/BLOCK (the `none` arm
   skips the consult entirely: inject, don't intervene — the weak-model baseline).
6. **Score with the gym's hidden SQL verifiers, untouched** — the non-forgeable oracle. Each
   arm's verifier-pass % is the fraction of those checks that pass against the final DB state.

The arms are the kernel env seam in the reference consumer (`dos_react.py`): `none`=`DOS_CONSULT=0`,
`warn`/`defer`/`block`=`DOS_INTERVENTION=…`. Scoring code and verifiers were never modified.

### 3.2 Honest deviations (stated up front)

- **Injected mints, not natural errors.** Injection is the controlled perturbation that *creates*
  the signal — a strong model rarely mints on its own, so without injection there is nothing to
  catch and nothing to compare. This is the same A/B methodology as docs/143. (A separate
  *natural* run — no injection — confirms the harmlessness claim: gemini-2.5-flash resolves its
  IDs, mints ≈ 0, so DOS correctly stays silent. See §6.)
- **Model substitution.** docs/143 used `gemini-3-flash-preview`; the installed
  `langchain-google-genai` raises on Gemini-3's required `thought_signature` in the multi-turn
  tool loop, so we used **`gemini-2.5-flash`**. Being slightly less capable, it is a *better* fit
  for the mint-prone regime the intervention targets.
- **Arms are not verifier-paired at the model level.** Each arm re-seeds a fresh DB and the model
  is stochastic, so small-N spread carries run-to-run noise. We therefore report the integrity
  slice (lower variance, averaging over hundreds of SQL checks) and confirm stability of the
  ordering across run sizes.

---

## 4. Results

### 4.1 The detector is sound on live data

Across the arms, the live mint-catch rate was **72–82 %**, matching the variance-free replay
recall of ~83 % (docs/143). The detector fires on the injected corruptions and almost never on a
correctly-resolved ID. Soundness is not in question; the intervention is.

### 4.2 The headline — WARN wins, BLOCK is neutral (live, 80 tasks/arm, 78 paired)

Integrity slice (= all 306 `database_state` verifiers; deltas vs the inject-but-don't-intervene
baseline):

| Arm (same injected mints) | integrity / verifier-pass % | Δ vs none | success % |
|---|---|---|---|
| **none** (inject, no intervention) | 40.2 % | — | 10.3 % |
| **DEFER** (skip + re-prompt) | 42.2 % | +2.0 | 12.8 % |
| **WARN** (inform + still dispatch) | **46.4 %** | **+6.2** | **15.4 %** |
| **BLOCK** (synthetic corrective, turn-preserving) | 40.2 % | **+0.0** | 10.3 % |

**WARN leads on this run (+6.2 pp integrity, +5.1 pp success); BLOCK lands on the do-nothing
baseline.** The integrity slice is the lower-variance signal and the ordering is stable across the
run (same at 48, 72, 75, and the final 78 paired tasks); read the success-% gap as directional, not
precise, at this n. On these results the §13.4 "BLOCK is the prize" hypothesis does **not** hold —
BLOCK matches `none` here, with the per-task flip decomposition below as the mechanism.

### 4.3 Why — the per-task verifier-flip decomposition

For each caught-mint task, compare each verifier against the same task in the `none` arm:
FALSE→TRUE = the catch *helped* (fixed a checked FK); TRUE→FALSE = the disruption *hurt* (broke a
different step). (`mattered_join.py`.)

| Arm | help-flips | hurt-flips | net | mattered % |
|---|---|---|---|---|
| DEFER | 9 | 2 | +7 | 33 % |
| **WARN** | **14** | **2** | **+12** | 27 % |
| BLOCK | 7 | **13** | **−6** | 20 % |

**The smoking gun is BLOCK's 13 hurt-flips vs WARN's 2.** Withholding the minted call — *even with
a synthetic "id unresolved; use a read tool" result in its place* — breaks ~6× more downstream
steps than just warning and letting it dispatch. On a real multi-step plan the agent expected the
*real* effect; substituting a synthetic tool-result derails the steps that depended on it. WARN
never withholds, so it never breaks the plan; it just informs, and the model self-corrects when
the catch matters.

### 4.4 The mattered-rate is low — which is why WARN wins

Across arms, only **~20–33 %** of caught-mint tasks had the catch actually flip a scored verifier.
Most injected mints land on FKs no verifier checks. In that regime, the value of *prevention* is
small and the cost of *disruption* dominates — so the cheapest rung that still informs (WARN)
wins. This is exactly what the free Tier-0 sweep predicted: BLOCK only overtakes WARN when
`mattered_rate ≳ 0.80`, and the live mattered-rate is far below that.

### 4.5 The result does NOT depend on the flip analysis (robustness)

The flip decomposition (§4.3) is the *microscope* that explains the verdict; it is not the
verdict. The plain per-arm aggregate — sum each arm's passed/total verifiers, **no baseline
pairing, no flip** — gives the identical ordering:

> `none 39.9 % · DEFER 41.9 % · WARN 46.0 % · BLOCK 40.2 %` verifier-pass
> (WARN +6.1, DEFER +2.0, BLOCK +0.3).

Remove the per-task flip analysis entirely and the conclusion is unchanged; you only lose the
*why*. Two independent reductions (aggregate and paired-flip) agree, which is the robustness check.

---

## 5. The methodological finding (the part that generalizes)

The expensive live run **confirmed a prediction the free Tier-0 sweep made before a cent was
spent.** The simulator's "BLOCK ≫ DEFER" was true but compared against the wrong baseline (DEFER,
the loser DOS already abandoned); the Tier-0 sweep identified the right baseline (WARN) and the
decision variable (mattered-rate), and predicted WARN would win in the low-mattered regime. The
live run landed exactly there.

This is the reusable shape for any "should we act on this verdict, and how hard?" question:

1. **Build the eval first** (`intervention_eval`) — score the *net effect of acting*, not the
   accuracy of deciding.
2. **Sweep the cheap proxy** to map the decision boundary across the unknown dynamics ($0).
3. **Run the expensive ground truth** to confirm a *prediction*, not to take a blind first datum.
4. **Reduce two independent ways** (aggregate + paired) and require agreement before believing.

The simulator was wrong about one thing the live run corrected: it modeled the turn-preserving
BLOCK's recovery as nearly free. On real plans it is *not* free — a synthetic substitution is
itself a plan-disruption. That gap is precisely what a live run exists to close.

---

## 6. The natural (no-injection) control

The injected A/B answers "does the *intervention* help when errors exist." A separate **natural
run** (no injection, `DOS_MINT_RATE=0`, `none` vs `WARN`) answers the orthogonal safety question:
"on the un-perturbed real benchmark, does the model mint on its own, and is DOS harmless?"

**Measured (live, no injection, gemini-2.5-flash, 4 domains):** across **56 tasks and 406 real
mutating calls, the detector found ZERO natural mints** (0 fabricated IDs). The model resolves its
foreign keys — it issues the prerequisite read, then references the id it read back — exactly the
docs/143 finding for gemini-3, reproduced here. With 0 mints there is nothing to catch, so the
WARN arm fires **0 nudges** and is identical to the plain baseline by construction: **DOS is
harmless when the model behaves.** (This is the deductive complement to the injected A/B: the
intervention only acts when a mint exists, and on the natural benchmark mints ≈ 0, so the
"does it do harm in the common case?" answer is *no, it does nothing*.) The points only appear in
the *cheap-agent* regime the injected A/B simulates. Run: `live_ab.py --mint-rate 0 --arms none
warn`.

---

## 7. Limitations and threats to validity

- **Single model.** gemini-2.5-flash only; a stronger model mints less (less leverage), a weaker
  one more (more leverage). The *direction* (WARN ≥ BLOCK at low mattered-rate) is a property of
  the disruption cost, not the model, but the magnitudes are model-specific.
- **Injection realism.** Injected mints are right-shape/wrong-content corruptions of resolved
  IDs; they model "Incorrect ID Resolution" but not every natural failure mode.
- **Mattered-rate is benchmark-specific.** A deployment where most mutations *are* verifier-
  checked (higher mattered-rate) could flip the verdict toward BLOCK — which is exactly why the
  ladder is a *policy*, calibratable per deployment by re-running the eval, not a fixed default.
- **n and pairing.** 80 tasks/arm, not verifier-paired; success% carries ±~5 pp noise, hence the
  reliance on the integrity slice and the cross-size stability check.

---

## 8. Conclusion

On the real benchmark, the optimal way to act on a sound mint-verdict is the **least-disruptive
that still informs** — WARN: tell the model, let the call proceed, let it self-correct. The
turn-preserving BLOCK we hypothesized would dominate is neutral, because *withholding the call at
all* — even with a synthetic correction — disrupts real multi-step plans more than it prevents,
in the low-mattered regime real benchmarks occupy. DEFER (the −9 pp posture) is the worst kind of
withholding. **BLOCK and DEFER are high-stakes-effect safety valves, not the default.** The
docs/143 WARN-only fix is confirmed optimal — and a free theory sweep called it before the live
run spent a cent, which is the transferable methodological lesson.

---

## Artifacts (reproduce)

- **Kernel:** `src/dos/intervention.py`, `src/dos/intervention_eval.py`, `dos intervention-eval`
  (+ `tests/test_intervention*.py`, 108 tests). Design: `docs/144`.
- **Tier 0:** `python -m benchmark.enterpriseops.intervention_theories`
- **Simulator:** `python -m benchmark.enterpriseops.intervention_ab`
- **Live (Tiers 2–4):** `python benchmark/enterpriseops/live_ab.py --tasks N --arms none defer
  warn block --domains itsm csm email hr --mint-rate 0.35`
- **Analysis:** `python benchmark/enterpriseops/analyze_live.py` (mechanism + aggregate scores);
  `python benchmark/enterpriseops/mattered_join.py` (per-task flip decomposition).
- **Setup + tier ladder:** `benchmark/enterpriseops/THEORY_LADDER.md`.
- **Full results writeup:** `benchmark/enterpriseops/RESULTS.md` → "⚑ THE LIVE INTERVENTION A/B".
- **Memory:** `[[project-dos-intervention-ladder-built]]`, `[[reference-enterpriseops-gym-runnable]]`.
