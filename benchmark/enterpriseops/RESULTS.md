# docs/143 — EnterpriseOps-Gym × DOS arg_provenance: the real run

<!-- dos-bench-stamp: kernel=0.13.0 sha=227aec8 date=2026-06-06 -->
<!-- ^ machine-parseable provenance for `benchmark._run status`. RE-STAMPED 2026-06-06
     (docs/202): the numbers below were captured at kernel 0.11.0 in the INJECTED-mint
     regime; they remain valid AS injected-regime results, but see the refresh banner —
     the WARN +6.2pp headline does NOT generalize to the natural failure stream. -->

> ## ⚑ REFRESH 2026-06-06 (docs/202) — the +6.2pp WARN headline is INJECTED-mint-ONLY
>
> Everything below was measured in the **injected-mint regime** (`DOS_MINT_RATE` ~0.3,
> realized ~0.10) — it *manufactures* the invented-FK failure a capable model rarely
> produces naturally. Re-scored through the [docs/198 feasibility split](../../docs/198_the-feasibility-witness-and-give-up-correctly.md)
> against **every recorded corpus** ([docs/202](../../docs/202_intervention-ladder-refresh-natural-regime.md)).
> The feasibility split is [docs/198](../../docs/198_the-feasibility-witness-and-give-up-correctly.md):
>
> | regime | WARN integrity Δ vs none | reading |
> |---|---|---|
> | **INJECTED** (`live_results`) | **+6.03pp** (40.32 → 46.35) | reproduces the docs/151 headline |
> | **NATURAL** (`live_results_natural`, mint 0.0) | **+0.20pp — FLAT** (50.38 → 50.58) | the lift evaporates; success even drops 16.7%→10.0% (n.s.) |
>
> **Why:** natural thrash is dominated by the WALLED, infeasible `create_filter`
> (0 successes / 278 errors — schema demands all ~9 `criteria` fields), so the cure has
> almost nothing curable to convert (the docs/198 category error). The +6.2pp is a
> property of the *injection*, not of *WARN*. **What still holds:** WARN is the
> least-disruptive intervention; BLOCK's withholding-breaks-downstream disruption is real
> (injected: −0.12pp, success *below* none). **The regime-independent survivor is
> witness-gated early-halt** (false-abandon 0.000, 3.5k–22.8k tokens saved on all four
> corpora; the live curable run added a 5th at 43.7k). **Curable conversion (now settled,
> docs/202 §5.1):** a targeted live run (`live_results_curable_ab`, 55 paired/arm) lifted the
> curable slice to n=19 but reached only **d=1** convertible flip — conversion is **unreachable
> to power** on this benchmark (the convertible population is too thin even when hunted), so
> WARN's natural value is null-to-untestable, not a measured win. **Read the rest of this file
> as the injected-regime record.**

**The keystone (`dos.arg_provenance`) built, then run end-to-end on the actual
ServiceNow benchmark with a real Gemini model. 2026-06-04.**

This is the measured companion to the design audit in `docs/143`. The audit named one
binding that survives DOS's byte-inequality axiom cleanly — **argument provenance**
("did the model MINT this id/FK, or RESOLVE it from env-authored bytes?"). It is now a
shipped kernel module (`dos.arg_provenance`), wired into a 4th gym orchestrator
(`dos_react`), and validated on the live benchmark.

## What was run

- **Harness:** the real `ServiceNow/enterpriseops-gym` (cloned), 4 domain MCP servers in
  Docker (email/itsm/csm/hr), the hidden expert-SQL verifiers unchanged.
- **Model:** `gemini-3-flash-preview` — the paper's cost/perf Pareto-frontier comparator
  (the "Gemini-3-Flash" of Table 1a), via the real `GEMINI_API_KEY`.
- **Sample:** a deterministic, seeded 15% stratified slice of the FK-heavy domains
  (itsm/csm/hr) + email = **55 tasks**, run paired through `react` (R0) and `dos_react` (R1).
- **The only change between arms:** before each mutating tool call, `dos_react` folds
  `dos.arg_provenance.classify_call` over the env-authored bytes the agent already saw
  (prior tool RESULTS + the task text) and, on a minted id, injects ONE advisory nudge
  instead of dispatching. Same model, same 512 tools, same SQL scorer.

## The headline finding (honest)

**`gemini-3-flash` resolves its FK ids correctly** — it issues the prerequisite read,
then references the id it read back. Across **249 real mutating calls**, the hardened
detector flags **0 genuine mints**. This is not a null result; it is a *confirmation* of
the audit's own prediction and the paper's Table 7: **Integrity (FK-validity) is agents'
*strongest* verifier class** — a capable model has little ID-resolution headroom to gain.
So on a strong model, `arg_provenance` correctly **does nothing** — and, after hardening,
does no harm (R1 ≈ R0; the apparent live ±pp is run-to-run model variance at ~0 nudges,
not the mechanism).

> R0 baseline (gemini-3-flash, 55 tasks): **success 36.4%, verifier-pass 73.9%, avg 7.1
> tools/task** — squarely in the paper's band (Gemini-3-Flash = 31.9% on the full set).

## The mechanism IS sound and high-recall — measured deterministically

The live A/B is dominated by model non-determinism (Gemini at temp 0 is not fully
deterministic; the DB-state verifiers see irreversible mutations). So the detector was
also evaluated **deterministically by replaying the real recorded trajectories** — no new
model calls, zero variance (`replay_recall.py`):

| Property | Measured (real gemini-3-flash trajectories) |
|---|---|
| **Precision** (false-nudge rate on really-resolved ids) | **0.00 %** (0 / 249) — deployment-safe |
| **Recall** (genuine injected mints caught) | **~83 %** (stable 81.7–84.4 % across seeds) |

The mint injection is the *only* perturbation (each real resolved id is replaced, in a
controlled clone, with a right-shape / wrong-content id verified ABSENT from that call's
corpus — the named "Incorrect ID Resolution" failure). So recall is attributable purely
to the detector. The ~17 % it misses are short ids that coincidentally trace or fall below
the matching threshold — the documented *safe* miss (a false-SUPPORTED degrades to
baseline; the detector never trades that for a precision-killing false flag).

## The real run made the detector better (the load-bearing work)

The **first** detector false-flagged **66 / 249** real calls — every one a value the model
had correctly resolved (`INC_004`, a UUID, `jason.smith10@…`, a datetime). Run live with
that bug, `dos_react` *regressed the benchmark* (−9 pp success via false nudges — the
audit's §8 "kill-signal" observed for real). Four real-data fixes took it to **0 false
flags**:

1. **Whole-value direct match** (the keystone): an id read back verbatim is RESOLVED by
   plain containment, answered *before* decomposition. No hashing needed — a resolved id is
   the *same bytes* the env authored, so direct substring is the exact, honest test.
2. **UUID / 32-hex matched whole**, never split into sub-chunks that can't trace.
3. **email username digit-suffix** + **full ISO datetimes / ms-epochs** negative-filtered.
4. **bare-integer FK recall** (`group_id=81`) + a **quantity-name stoplist**
   (`contract_price=33414` is a value the model sets, not an FK) — lifting recall 55 %→83 %
   while *holding* precision at 0 %.

All four are pinned by real-data regression tests (`tests/test_arg_provenance.py`).

## The recovery dynamic — where the points come from

A detector that catches mints only helps if the model then *recovers* (does the lookup it
skipped). On a model that doesn't mint, there is nothing to recover. The faithful,
non-rigged simulator (`simulator.py`, running the **same** `classify_call` the kernel
ships — its catch rate, 89 %, matches the real-data 83 %) models a *cheap minting* agent
and measures the recover loop:

> Integrity (FK-valid) slice **71.4 % → 82.7 %, +11.3 pp**, feasible-task rate flat — and
> the bump is **emergent**: it → 0 when the nudge is ignored (q_recover=0) and shrinks with
> fewer mints / shorter horizons (the mechanism-driven sweep, `run_ab.py --sweep`).

## ⚑ KEY DATA POINT — the nudge's *disruption cost* is real (live, 2026-06-04)

The most important empirical finding of the real run, because it contradicts the
simulation's optimism and refines the mechanism design. A **controlled mint-injection
A/B** on the live harness (same model, same 55 tasks, a 30 % simulated ID-error rate, both
arms injecting the **identical** mints via a stable per-task seed; the only difference is
whether R1 runs the nudge) produced:

| Arm (gemini-3-flash, ~75 injected mints, same seed) | Success | Verifier-pass | no-tool |
|---|---|---|---|
| **R0** — inject, NO nudge (weak-model baseline) | 32.7 % | 70.9 % | 3 |
| **R1-SKIP** — inject + skip-dispatch nudge | **23.6 %** | 71.2 % | 4 |
| **R1-WARN** — inject + warn-but-still-dispatch | **30.9 %** | **71.98 %** | **1** |

The detector worked — **64 of 73 injected mints were caught (88 %)**, matching the
deterministic 83 % recall — and after a nudge the model issued a follow-up tool call
**75 %** of the time (48/64). Yet under the default **SKIP** nudge, **success fell −9 pp**
while verifier-pass barely moved (+0.4 pp); task-level **6 tasks went pass→fail, only 1
fail→pass**. **The catch was right; the *intervention* was wrong.**

**The fix, confirmed.** The **WARN-only** arm (same 62 nudges, same injected mints, but the
call still dispatches) **recovered most of the loss: success −9.1 pp → −1.8 pp, and
verifier-pass went POSITIVE (+1.1 pp)** with *fewer* no-tool stalls (1 vs 4). The remaining
−1.8 pp is within the run-to-run variance band (the zero-nudge clean A/B was itself ±5 pp
of pure model non-determinism); the lower-variance verifier-pass metric moved the *right*
way. So: **WARN beats SKIP by ~7 pp on success and flips verifier-pass positive — the
disruption was the problem, not the verdict.**

**Why (the load-bearing lesson):** the default nudge **SKIPS the dispatch and re-prompts**.
That derails a model mid-plan — even on a *true-positive* catch, and even when the caught
FK was not the one the verifier checked (so R0 passed *despite* the mint, while R1's
disruption broke a *different* step). This is the audit's own §8 **"feasible-task
kill-signal" and P5 "the nudge does not save every mint," observed live on real DB state.**
A catch is necessary but not sufficient; the *intervention* must not cost more than the
mint it prevents.

**The fix it motivated:** an **advisory WARN-ONLY mode** (the nudge is recorded and shown
to the model, but the call STILL dispatches — the model is informed and may self-correct on
its next turn, without losing this one). This is truer to DOS's advisory-only doctrine
(report, don't actuate) than skip-and-re-prompt. `DOS_WARN_ONLY=1`; the skip behavior is
now opt-in, not the default posture for a benchmark where disruption is expensive.

> **The transferable principle:** a distrust verdict that is *correct* can still be *net
> harmful* if the enforcement attached to it is too disruptive. Soundness of the detector
> and safety of the intervention are SEPARATE properties — DOS proved the first here
> (0 % false-nudge, 83 % recall) but the live run showed the second is where the points are
> won or lost. Measure the intervention's cost, not just the verdict's accuracy.

### What "verifier-pass" is, and exactly what was lost vs gained

**The verifier IS the real test — and it is the benchmark's, not ours.** EnterpriseOps-Gym
scores every task with **hidden, expert-authored SQL queries run against the FINAL database
state** after the agent finishes (avg ~5.3 per task). A verifier passes iff its SQL assertion
is true (e.g. `SELECT COUNT(*) FROM drafts WHERE id='draft_001'` returns `0` — the draft was
actually sent). It checks the **real effect on the shared DB**, never the agent's claim and
never the action sequence — exactly the non-forgeable, byte-author-≠-judged-agent oracle DOS
is built around (which is *why* §5 of the audit calls scoring-time `verify()` redundant: the
gym already is that oracle). **We changed none of it** — the SQL verifiers and `compute_score`
were untouched across every arm. Two numbers fall out:

- **Verifier-pass %** — the fraction of *individual* hidden SQL checks that pass. The
  fine-grained ground truth, and the **lower-variance** signal (it averages over ~290 checks
  across the 55 tasks).
- **Success %** — the fraction of *tasks* where **all** verifiers pass. The strict
  all-or-nothing leaderboard roll-up, and the **higher-variance** signal (one broken step
  fails the whole task; at n=55 with a stochastic model on irreversible DB state it carries
  ±~5 pp of pure run-to-run noise).

**What each intervention lost and gained** (same injected mints in every arm; the only change
is the intervention):

| Arm | Success (all checks) | Verifier-pass (each check) | Reading |
|---|---|---|---|
| baseline (mints, no intervention) | 32.7 % | 70.9 % | — |
| **SKIP** call + re-prompt | 23.6 % (**−9.1 pp**) | 71.2 % (+0.3) | **lost** 9 pp of whole-task success; gained ~nothing per-check — the recovered FKs barely moved the needle while skipping derailed *other* steps |
| **WARN** (inform, still dispatch) | 30.9 % (−1.8 pp) | 71.98 % (**+1.1 pp**) | **gained** on the fine-grained truth (more individual checks pass — the recovered-FK benefit showing through); lost only within the noise band on success |

So the honest accounting: **SKIP's loss was the disruption, not the verdict** — it cost 9 pp
of all-or-nothing success to recover FKs that barely registered per-check, because a skipped
call breaks a *different* step of the same task. **WARN keeps the gain and drops the loss** —
it lifts the trustworthy per-check metric (+1.1 pp) and stays inside the noise on success. The
gain is real and shows where the signal is cleanest; the loss was an artifact of *how* the
true verdict was enforced. (Trust the verifier-pass delta over the success delta here — at
n=55, success is noisy; verifier-pass, averaging hundreds of independent SQL checks, is not.)

## The intervention ladder — the §13 double-down, shipped + proven (2026-06-04)

The −9 pp lesson said the next frontier is hardening the *actuation*, not the verdict. That is
now built (docs/144; `src/dos/intervention.py` + `src/dos/intervention_eval.py` + `dos
intervention-eval` + the consumer-side non-disruptive `BLOCK` in `dos_react.py`; 108 new tests,
green suite). **NB — the live A/B below REFUTED the BLOCK-prize hypothesis (WARN is optimal); read
"⚑ THE LIVE INTERVENTION A/B" for the ground truth. The simulator result here is the *mechanism*,
not the live recovery dynamics.** The four §13 deliverables:

1. **A typed intervention ladder** (`dos.intervention`) — a closed, ranked set the actuation
   dual of `dos.reasons`. The **measured** cost order is `OBSERVE ‹ WARN ‹ BLOCK ‹ DEFER` —
   BLOCK below DEFER, because BLOCK preserves the agent's turn while DEFER spends it (the
   correction the build made to §13.1's prose order; the live −9 pp *was* the spent turn).
2. **An `intervention_eval` harness** — scores a policy by **net task delta** (caught ×
   recovered × (1 − disruption_cost), generalized to all cells), NOT verdict accuracy. The
   dangerous cell is `wasted_disruption_rate` — disruption spent on a catch the verifier never
   checked, the exact −9 pp. The friendliness instrument for the PEP, the `overlap_eval` twin.
3. **Confidence-gated escalation** — `assess_confidence` reads HIGH only on a whole-value-absent
   scalar mint → BLOCK; a composite/container is LOW → WARN. The policy's `__post_init__` makes
   refuse-LESS-only *structural* (a lower-confidence verdict can only map to a no-more-disruptive
   rung; DEFER is unreachable under the default ceiling).
4. **The non-disruptive `BLOCK` primitive** — refuse the minted call but return a *synthetic
   corrective result* ("id unresolved; here is the read tool") in its place, so the agent gets a
   corrective observation on the SAME turn, the real mutation never fires, and the turn is not
   lost. Anti-laundering: the synthetic payload is stamped `dos_blocked` and excluded from the
   provenance corpus, so a BLOCK can never teach the detector to trust the id it blocked.

**The simulator A/B (`python -m benchmark.enterpriseops.intervention_ab`, 690 tasks × 3 seeds,
the SAME `dos.intervention_eval` the kernel ships scoring each policy):**

| Policy | net task delta | wasted-disruption | reading |
|---|---|---|---|
| **DEFER** (skip + re-prompt, the −9 pp posture) | **−0.53** | 0.38 | the disruption tax, paid on every withheld turn incl. the verifier-irrelevant catches |
| **WARN** (inform + still dispatch) | **0.00** | 0.00 | never withholds a turn → never wasted; but on an irreversible DB a dispatched mint already corrupted the scored state, so it prevents nothing |
| **BLOCK** confidence-gated (the §13 PEP) | **−0.13** | 0.38 | refuses the mint AND keeps the turn → **+0.40 net-delta over DEFER**, the turn-preserving PEP winning on identical caught mints |

In the simulator BLOCK beats DEFER by +0.40 — but DEFER is the wrong baseline. The Tier-0 sweep
(`intervention_theories.py`) showed the honest baseline is **WARN**, and BLOCK beats WARN only
when `mattered_rate ≳ 0.80`. **The live run measured the real mattered-rate at ~23–33 % (LOW) and
found BLOCK does NOT beat WARN — it is the worst intervening arm** (its synthetic-result
substitution disrupts real multi-step plans: 11 hurt-flips vs WARN's 2). So the simulator's
"BLOCK ≫ DEFER" is true but not the operative comparison; the live ground truth is **WARN wins**
(see "⚑ THE LIVE INTERVENTION A/B"). The simulator's BLOCK-recovery parameter was too optimistic —
exactly the gap a live run exists to close.

## ⚑ THE LIVE INTERVENTION A/B — BLOCK did NOT win; WARN is optimal (2026-06-04)

> **Paper:** the full methodology + results writeup is `docs/151_intervention-ladder-live-study.md`
> (abstract → tiered design → results → robustness → limitations → conclusion). This section is
> the data record; docs/151 is the explainer.

The simulator predicted **BLOCK beats DEFER**; a free **Tier-0 theory sweep**
(`intervention_theories.py`) then corrected the framing — the honest baseline is **WARN, not
DEFER**, and BLOCK beats WARN *only when the mattered-rate ≳ 0.80*. The live 4-arm A/B on the
real gym **confirms the Tier-0 prediction and refutes the BLOCK-prize hypothesis.**

**Setup (honest, with the substitutions made):** real `ServiceNow/EnterpriseOps-Gym`, 4 FK-heavy
domains (itsm/csm/email/hr) via Docker MCP servers, the hidden SQL verifiers untouched. **80
tasks/arm**, the SAME injected mints across arms (`DOS_MINT_RATE=0.35`, stable seed). Two honest
deviations from docs/143: the model is **`gemini-2.5-flash`** (the installed
`langchain-google-genai` raises on `gemini-3-flash-preview`'s required `thought_signature` in the
tool loop; 2.5-flash works and, being slightly weaker, is a *better* fit for the mint-prone
regime); and the arms are **not verifier-paired** (each re-seeds a fresh DB, so small-N spread
carries noise — trust the aggregate). Detector recall live: **72–82 %**, matching the
deterministic 83 %.

**The scores — final, paired on 78 tasks, integrity slice (= all 306 `database_state` verifiers):**

| Arm (same injected mints) | integrity / verifier-pass % | Δ vs none | success % |
|---|---|---|---|
| **none** (inject, no intervention) | 40.2 % | — | 10.3 % |
| **DEFER** (skip + re-prompt) | 42.2 % | **+2.0** | 12.8 % |
| **WARN** (inform + still dispatch) | **46.4 %** | **+6.2** | **15.4 %** |
| **BLOCK** (synthetic corrective, turn-preserving) | 40.2 % | **+0.0** | 10.3 % |

**WARN wins decisively (+6.2 pp integrity, +5.1 pp success). BLOCK is dead-on the do-nothing
baseline (+0.0 pp) — every withheld call's prevention exactly cancelled by the plan-disruption it
caused.** The ordering is stable across the whole run (same at 48, 72, 75, and the final 78 paired
tasks). The §13.4 "BLOCK is the prize" hypothesis is **falsified on live data.**

**Why — the per-task verifier-flip decomposition (`mattered_join.py`):** for each caught-mint
task, did the intervention flip a scored verifier vs the baseline? FALSE→TRUE = the catch fixed a
checked FK (*helped*); TRUE→FALSE = the disruption broke a different step (*hurt*).

| Arm | help-flips | hurt-flips | net | mattered % |
|---|---|---|---|---|
| DEFER | 9 | 2 | +7 | 33 % |
| **WARN** | **14** | **2** | **+12** | 27 % |
| BLOCK | 7 | **13** | **−6** | 20 % |

**The smoking gun is BLOCK's 13 hurt-flips** (vs WARN's 2). Withholding the minted call — *even
with a synthetic "id unresolved; use a read tool" result in its place* — **breaks ~6× more
downstream steps than just warning and letting it dispatch.** On a real multi-step plan the agent
expected the *real* effect; substituting a synthetic tool-result derails the steps that depended
on it. WARN's strategy (never withhold, just annotate) is safest precisely because the
**live mattered-rate is LOW (~23–33 %)** — most caught mints land on FKs no verifier checks, so
the cheapest thing that still informs the model wins, exactly as the Tier-0 sweep predicted.

> **The verdict does NOT depend on the flip analysis.** The help/hurt table is the *microscope*
> (it explains WHY), not the result. The plain per-arm aggregate — sum each arm's passed/total
> verifiers, NO baseline pairing, NO flip — gives the identical ordering: `none 39.9 · DEFER 41.9
> · WARN 46.0 · BLOCK 40.2` verifier-pass (WARN +6.1, BLOCK +0.3, DEFER +2.0). Remove the
> per-task flip decomposition entirely and the conclusion is unchanged; you just lose the *why*.
> See `THEORY_LADDER.md` → "Does the result hold without the flip" for both reads side by side.

**The transferable lesson (it deepens, not contradicts, docs/143):** docs/143 showed the *skip*
intervention (DEFER) was too disruptive (−9 pp there). The live ladder shows the disruption tax is
about **withholding the call at all** — and the turn-preserving BLOCK, which the simulator modeled
as nearly free, is *not* free on real plans: a synthetic substitution is itself a plan-disruption.
**The least-disruptive-that-still-informs (WARN) is the robust optimum at a low mattered-rate;
BLOCK/DEFER are the high-stakes-effect safety valves, not the default.** The cheap $0 theory sweep
called this before a cent was spent — which is the methodological point: *map the recovery-dynamics
region first, then the live run confirms a prediction instead of being a blind first data point.*

**Reproduce:** `python live_ab.py --tasks 20 --arms none defer warn block --domains itsm csm
email hr --mint-rate 0.35` then `python analyze_live.py` + `python mattered_join.py`
(see `THEORY_LADDER.md` for the full tier ladder + one-time gym setup).

## Bottom line

- **WARN is the optimal intervention on live data** (+6.2 pp integrity); BLOCK (+0.0) and DEFER
  (+2.0) do not beat it. The turn-preserving BLOCK's synthetic substitution disrupts real plans
  (13 hurt-flips) — the prize hypothesis is refuted, and the docs/143 WARN-only default confirmed.
- **The mechanism works and is safe**: 0 % false-nudge, ~83 % mint-recall, on real data.
- **On a capable model it correctly stays silent** — the natural no-injection control (gemini-2.5
  -flash, 56 tasks, **406 mutating calls, 0 natural mints**) reproduces the docs/143 gemini-3
  finding: the model resolves its foreign keys, so DOS fires 0 nudges and the WARN arm is identical
  to the plain baseline. **DOS is harmless when the model behaves**; the points only appear in the
  cheap-agent (mint-prone) regime.
- **The points appear when the agent mints** — the realistic *cheap-agent* deployment the
  audit is about — where the catch→nudge→recover loop yields a clean, attributable,
  >4 pp Integrity-slice lift (+11 pp simulated, validated against the measured catch rate).
- DOS hardens the execution substrate *under* a cheap agent's plan — catching minted IDs —
  it does not supply the plan, and it must not (and does not) pretend a self-authored DB
  check is a non-forgeable witness. Only provenance-of-a-string survived, and it shipped.

## Reproduce

```bash
# kernel (pure, no benchmark needed):
python -m pytest tests/test_arg_provenance.py          # 39 tests incl. real-data regressions
python -m pytest tests/test_intervention.py tests/test_intervention_eval.py   # the §13 ladder + eval
python -m benchmark.enterpriseops.run_ab --sweep       # the simulated detector A/B + mechanism sweep
python -m benchmark.enterpriseops.intervention_ab      # the §13 intervention A/B (WARN vs BLOCK vs DEFER)
dos intervention-eval --cases cases.jsonl              # score an actuation policy by net task delta

# real run (needs Docker + a Gemini key):
#   clone ServiceNow/enterpriseops-gym; unzip gym_dbs.zip; docker run the domain MCP servers
#   (host port -> container 8005); conf/llm/gemini-flash.json = gemini-3-flash-preview
python sample_and_run.py --domains itsm csm hr email --frac 0.15 --out sample_ab
python evaluate.py --configs_folder sample_ab --orchestrator react     --output_folder results/ab/react ...
python evaluate.py --configs_folder sample_ab --orchestrator dos_react  --output_folder results/ab/dos_react ...
python score_ab.py  --r0 results/ab/react --r1 results/ab/dos_react --sample sample_ab
python replay_recall.py --results results/ab/react      # the variance-free precision/recall
```
