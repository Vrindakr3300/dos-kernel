# 144 — The intervention ladder, and measuring what acting on a verdict costs

> **Status: Phases 1–2 SHIPPED + Phase 3 consumer wired & simulator-proven; Phase 3 LIVE A/B
> pending. 2026-06-04.** `dos.intervention` (the closed ladder + confidence-gating + the
> synthetic-corrective builder), `dos.intervention_eval` (the net-task-delta harness),
> `dos intervention-eval` (the CLI verb), and the consumer-side non-disruptive BLOCK in
> `benchmark/enterpriseops/dos_react.py` are all built, unit-tested (**108 new tests** across
> `test_intervention.py` / `test_intervention_eval.py` / `test_intervention_cli.py`), wired
> into the config seam + public API, and exercised on the SIMULATOR A/B + a **Tier-0 theory
> sweep** (`intervention_theories.py`, free, no model). **The honest simulator finding —
> which corrects an over-optimistic earlier framing:** BLOCK beats DEFER decisively
> (+0.38 net-delta — the turn-preserving PEP crushes the −9 pp skip-and-re-prompt posture),
> **but DEFER is the wrong baseline.** The docs/143 *live* winner was **WARN** (−1.8 pp ≈ 0),
> and against WARN the simulator says BLOCK wins **only when `mattered_rate ≳ 0.80`** (most
> caught mints actually feed a verifier). At the docs/143-observed *low* mattered-rate, even
> turn-preserving BLOCK is net-NEGATIVE (−0.13 to −0.15) while WARN is 0.0 — preventing a
> write that did not matter still is not free on an irreversible DB. Full suite green.
> **The live A/B HAS NOW RUN (2026-06-04) — and it REFUTES the BLOCK prize, confirms WARN.**
> Full 4-domain run (itsm/csm/email/hr, 80 tasks/arm, 78 paired, gemini-2.5-flash, same injected
> mints, hidden SQL verifiers untouched; `live_ab.py`). Integrity-slice deltas vs the inject-but-
> don't-intervene baseline: **WARN +6.2 pp (the winner), DEFER +2.0 pp, BLOCK +0.0 pp (dead on
> the do-nothing baseline).** The per-task verifier-flip decomposition (`mattered_join.py`) shows
> why: WARN = 14 help-flips / 2 hurt-flips (net +12); **BLOCK = 7 help / 13 HURT (net −6)** —
> withholding the minted call, *even with a synthetic corrective result*, breaks ~5× more
> downstream steps than just warning and letting it dispatch (a synthetic substitution is itself
> a real plan-disruption the simulator modeled as nearly free). The **live mattered-rate is LOW
> (~23–33 %)** — most caught mints miss the verified FKs — exactly the region the Tier-0 sweep
> predicted WARN would win. So: **the least-disruptive-that-still-informs (WARN) is the robust
> optimum; BLOCK/DEFER are high-stakes-effect safety valves, not the default.** The docs/143
> WARN-only fix is confirmed optimal, and the §13.4 "non-disruptive BLOCK is the prize"
> hypothesis is **falsified on live data.** The methodological win: the free $0 Tier-0 sweep
> called this before a cent of API spend — the live run confirmed a prediction, not a hunch. Full
> numbers in `benchmark/enterpriseops/RESULTS.md` (⚑ THE LIVE INTERVENTION A/B) +
> `THEORY_LADDER.md`.
>
> **Two corrections this build made to the plan below (both load-bearing):**
> (1) the measured cost order is **OBSERVE ‹ WARN ‹ BLOCK ‹ DEFER**, NOT the §13.1/§1-table
> prose order — BLOCK is the *non-disruptive* rung (refuse the call but return a synthetic
> corrective result — the turn is PRESERVED); DEFER is the *turn-spending* rung (skip +
> re-prompt — the −9 pp posture). See §1's corrected table.
> (2) an adversarial review found a **refuse-LESS-only escalation hole**: the policy was
> rank-validated only against `BASE_INTERVENTIONS` at construction, but `choose_intervention`
> clamps against a `ladder` PARAMETER that can be rank-reordered — voiding the guarantee for
> a hand-passed ladder. FIXED: `choose_intervention` now RE-validates the policy against the
> ladder in hand (`InterventionPolicy.validate_against`) and fails SAFE to the ladder default
> on a mismatch, so refuse-LESS-only is a property of the ladder-in-use, not just of BASE
> (pinned by `test_choose_intervention_fails_safe_on_reordered_ladder`). The rest of this
> plan stands as the design contract.
>
> *Original framing (still the design contract):* Motivated by a *measured* result, not a
> hunch — docs/143's live run on the real EnterpriseOps-Gym proved a **sound** distrust verdict
> can be **net-harmful** when the *intervention* attached to it is too disruptive.
>
> **One line:** DOS has hardened the **verdict** for its whole history (the ORACLE→JUDGE→
> HUMAN ladder, the forgeability axiom, the evidence floor). The benchmark showed that is
> *necessary but not sufficient*: the next axis is the **intervention** — *how* a consumer
> acts on a true verdict — and it needs the same treatment the verdict got: a **closed,
> typed, ranked vocabulary** with a documented disruption-cost ordering, and an **eval
> harness that scores the net effect of acting**, not just the accuracy of deciding.
>
> **Lineage.** docs/143 §13 is the call for this doc; its RESULTS.md "⚑ KEY DATA POINT" is
> the evidence. docs/126 (the apply-gate PEP) makes a verdict *bind*; this plan is the
> discipline for *how hard* it binds. docs/99 (the actuation boundary) and docs/101
> (the watchdog) are the "record/propose, never actuate" doctrine this refines — the
> ladder's floor (`OBSERVE`/`WARN`) keeps that doctrine; only `DEFER`/`BLOCK` step past it,
> and only by opt-in. The reason vocabulary (`dos.reasons`) is the *decision*-side closed
> set this mirrors on the *actuation* side. The eval is the friendliness instrument the
> way `judge_eval` / `overlap_eval` / `overlap_eval` already are per axis.

---

## 0. The measured fact this plan is built on

docs/143 ran a controlled, live mint-injection A/B on the real `ServiceNow/enterpriseops-gym`
(gemini-3-flash, the same injected ID errors in both arms, the only difference the
intervention). The detector was **sound**: 0.00 % false-nudge on 249 real resolved calls,
~83 % recall, and it caught **64 of 73** injected mints (88 %). Yet:

| Arm (same injected mints) | Success | Verifier-pass |
|---|---|---|
| no intervention (baseline) | 32.7 % | 70.9 % |
| **SKIP** the minted call + re-prompt | **23.6 %** (−9.1 pp) | 71.2 % |
| **WARN** but still dispatch | **30.9 %** (−1.8 pp) | **71.98 %** (+1.1 pp) |

**A correct catch, acted on the wrong way, cost −9 pp.** Acted on the *right* way (WARN)
it recovered ~7 pp and flipped the lower-variance metric positive. The verdict was identical
across arms; only the *intervention* changed. So:

> **Detector-soundness and intervention-safety are orthogonal properties.** DOS measures the
> first exhaustively (every axis ships a precision/recall-style eval). It does not measure
> the second at all — and the benchmark showed the second is where the points are won or lost.

This doc fixes that omission.

---

## 1. The intervention ladder (the closed, typed actuation vocabulary)

A consumer that holds a refusing verdict picks *what to do about it*. Today that choice is
ad-hoc per consumer (the gym wrapper hard-coded skip, then warn). Make it a **closed,
ranked set** — the actuation dual of `dos.reasons` — with a **documented disruption-cost
ordering** and the **least-disruptive-that-still-informs as the default**:

**The SHIPPED table (the corrected, measured cost order — supersedes the §13.1 prose):**

| Rung | rank | What the consumer does | `dispatches`? | Disruption cost | Doctrine |
|---|---|---|---|---|---|
| **OBSERVE** | 0 | record the verdict; do nothing visible to the agent | yes | none | pure PDP (docs/99 floor) |
| **WARN** | 10 | annotate the agent's context with the verdict, **but still let the effect proceed** | yes | low — informed, loses no turn | advisory (the docs/143 winner; the default) |
| **BLOCK** | 20 | refuse the effect but **return a synthetic corrective result in its place** — the agent gets "id unresolved; here is the read tool" on the SAME turn | **no** (returns_synthetic) | **medium — turn PRESERVED**, no DB effect | the docs/126 PEP done right (the §1a prize) |
| **DEFER** | 30 | withhold *this* effect, re-prompt, let the agent retry | no | high — **costs the agent a turn**; derails a plan | the old skip behavior, now opt-in |

> **Why BLOCK ranks BELOW DEFER (the correction the build made).** The §13.1 sketch and the
> first draft of this table put `DEFER ‹ BLOCK`, reading "block" as the harder "dead-end."
> The live run inverts it: the disruption that cost −9 pp was *spending the agent's turn*
> (skip + re-prompt), and the rung that *avoids* that — refuse the call but hand back a
> synthetic corrective observation so the turn is not lost — is the CHEAPER one. So in the
> shipped ladder **BLOCK preserves the turn (rank 20)** and **DEFER spends it (rank 30)**.
> The non-disruptive enforcement primitive of §1a is therefore `BLOCK`, not a "non-disruptive
> DEFER." Pinned by `tests/test_intervention.py::test_block_cheaper_than_defer`.

The ordering is **monotone in disruption** (the rank field is a strict total order) and the
rung names round-trip as tokens (the `Severity`/`Liveness` idiom). The kernel ships the *type*
+ the ordering + the floor (`OBSERVE`/`WARN` `dispatches=True` — they never withhold the call,
so they cannot break the docs/99 advisory doctrine); the *withholding* rungs (`BLOCK`/`DEFER`,
`dispatches=False`) are where a consumer opts into the docs/126 PEP, and the seam makes that
choice **explicit and rankable** (read off the `dispatches`/`returns_synthetic` DATA, never
the token name) instead of a buried `if`.

**Why closed-and-typed, not a free callback.** The same reason the reason set is closed:
an open "do whatever" actuation surface cannot be *evaluated* (you cannot score an arbitrary
side effect) and cannot carry a *safe-direction guarantee* (a consumer can always escalate
past WARN, but the type makes the escalation visible and the default safe). Four rungs are
enough to span "record" → "refuse"; more would be ceremony.

### 1a. The non-disruptive enforcement primitive (the prize) — SHIPPED as `BLOCK`

The rung the live run said was missing: **prevent the bad effect WITHOUT costing the agent
its turn.** `DEFER` (skip + re-prompt) both withholds the effect *and* burns the agent's turn
— and the burnt turn is what derailed the model (−9 pp). The primitive that fixes it,
**shipped as `BLOCK`**, returns a **synthetic corrective observation in place of the effect**
— "that id is unresolved; here is the read tool," delivered as the tool-result the agent
expected — so the agent gets a *correcting input* on the **same** step, not a wasted one. A
real PEP (the effect did not land, the DB is untouched) with WARN-level disruption (the agent
did not lose its flow). The synthesis of docs/126 (bind the verdict) and docs/143 (don't pay
the disruption tax).

The kernel owns the **pure content builder** `intervention.synthetic_corrective_result(verdict,
tool_name, read_tool_hint) -> dict` (a `build_nudge_text` sibling — dict in, dict out, no
dispatch); the consumer (`dos_react`) does the **actuation** (substitute that dict for the
withheld mutation, continue the loop without counting a skipped turn). **Anti-laundering
(the highest-severity adversarial finding):** the synthetic payload reports the unresolved id
by arg-name + component tokens only (never the raw minted value as a standalone field) and is
stamped `dos_blocked: True`; the consumer EXCLUDES `dos_blocked` records from the provenance
corpus, so a BLOCK can never teach `classify_arg`'s whole-value-direct-match to TRUST the very
id it blocked. Pinned by `test_synthetic_result_no_raw_value_leak` + the corpus-exclusion
check in `dos_react`.

Proven on the simulator A/B (`intervention_ab.py`, 690 tasks × 3 seeds): **BLOCK net −0.13 vs
DEFER net −0.53 — a +0.40 net-delta swing**, the turn-preserving PEP beating the −9 pp skip
posture on identical caught mints. (WARN sits at 0.0 — safe but, on the irreversible gym DB, a
dispatched mint already corrupted the scored state, so WARN prevents nothing; it wins by never
paying disruption. BLOCK is the only rung that both prevents AND keeps the turn.)

---

## 2. `intervention_eval` — score the net effect of acting, not the accuracy of deciding

Every other DOS axis ships an eval (`judge_eval`'s confusion grid + false-clear rate,
`overlap_eval`'s false-ADMIT rate + safe-concurrency-forgone). The arg-provenance work
shipped a *detector* eval (precision/recall over `classify_call`). The benchmark proved the
**decisive** number is not "was the verdict right?" but **"did acting on it help or hurt the
run?"** So add the missing instrument:

> **`intervention_eval`** — replay a run (or an A/B), and for each verdict-and-its-chosen-rung
> score the **net task delta**: did the intervention move the task toward success, leave it
> unchanged, or break it? The headline cell is the **net-harmful intervention rate** — a
> *true-positive* verdict whose *intervention* still cost the run (the −9 pp class). The dual
> of `judge_eval`'s false-clear: there a true judgment is wasted by abstaining; here a true
> verdict is wasted by *over-acting*.

The eval is what makes the ladder's default *calibratable from data*: WARN is the floor
**because** the eval measured DEFER's net-harm rate as high and WARN's as low on a model that
recovers only ~75 % of the time. A different host (a deterministic agent, a higher-stakes
effect) re-runs the eval and may calibrate the default up to DEFER. The instrument turns the
intervention choice from a hunch into a measured, per-deployment decision — the
research-friendliness thesis (`docs/90 §2`), re-aimed at actuation.

---

## 3. Confidence-gated escalation (couple intervention strength to verdict confidence)

The −9 pp came from spending *disruptive* interventions on catches that **didn't matter to
the verifier** (the injected mint was on an FK the task didn't check, so the baseline passed
*despite* it, and only the disruption broke a different step). The structural fix: **the
intervention rung is a function of the verdict's confidence rung, not a flat policy.** A
verdict already carries its evidence rung (`arg_provenance` reports `matched_in`,
`components_unmatched`; a whole-value-absent id is a high-confidence mint, a
one-component-missing composite is lower). Couple them:

- **whole-value absent** (high-confidence mint) → may escalate to `BLOCK` (the default
  `on_high_confidence`; the turn-preserving PEP, not the turn-spending `DEFER`).
- **one component missing** of a composite, OR a container/multi-component arg (lower
  confidence) → cap at `WARN`.
- **believe / abstain** → `OBSERVE` only.

**The shipped confidence signal (the build's correctness fix).** `assess_confidence(verdict)`
reads HIGH iff a single data-bearing component is wholly unmatched (`len(components_checked)
== 1 and len(components_unmatched) == 1` — the exact shape `_data_bearing_components` produces
for a scalar mint); everything else (composite, container superset, one-of-many-missing) is
LOW, the safe under-intervene direction. It deliberately does **not** read `matched_in` — that
field is grammar/substring-polluted (an `INC` prefix substrings env bytes), so a `not
matched_in` conjunct would make HIGH never fire. The `InterventionPolicy.__post_init__` makes
the safe direction **structural**: it rejects every inverted combination (low-conf more
disruptive than high-conf, none more than low, floor past ceiling, a rung past the ceiling), so
a lower-confidence verdict can only ever map to a *no-more-disruptive* rung (refuse-LESS-only —
the admission-floor / fail-to-abstain discipline re-aimed at actuation). DEFER is **unreachable
under the default `ceiling=BLOCK`** — the turn-spending rung is opt-in (raise the ceiling).

This makes the disruptive rungs **rare and high-precision** — exactly where disruption is
*worth* its cost — and keeps the long tail of lower-confidence verdicts on the
non-disruptive floor. It is the actuation analogue of the evidence-ladder grading by
forgeability (docs/138): grade the *intervention* by the *confidence* of the verdict it acts
on. (One honest caveat the simulator surfaced: **confidence is not relevance.** Gating helps
only when the catches that don't matter to the verifier are *also* lower-confidence; when all
mints are HIGH, the decisive lever is BLOCK's lower cost vs DEFER, not the gate. See the
`intervention_eval` fixture `test_confidence_gating_helps_when_irrelevant_are_low_confidence`.)

---

## 4. Where it lives (the layering)

- **Kernel (mechanism) — SHIPPED `src/dos/intervention.py`:** the pure leaf — the
  `Intervention` str-enum (OBSERVE/WARN/BLOCK/DEFER) + `InterventionSpec`/`InterventionLadder`
  (the closed, rank-ordered registry, the `ReasonSpec`/`ReasonRegistry` shape) +
  `BASE_INTERVENTIONS` + `assess_confidence(verdict)` + `choose_intervention(verdict, policy,
  ladder) -> InterventionDecision` (the §3 coupling, no I/O) + `synthetic_corrective_result`
  (the §1a content builder) + the `dos.toml [intervention]` on-ramp + the floor guarantee
  (`OBSERVE`/`WARN` `dispatches=True`). Sits beside `dos.reasons` — imports only
  `dos.arg_provenance` (a sibling). Pure stdlib, names no host (pinned by a litmus test).
- **Kernel (eval) — SHIPPED `src/dos/intervention_eval.py`:** the pure harness over labelled
  `InterventionCase`s → the net-task-delta grid + `wasted_disruption_rate` (the dangerous
  cell). Beside `judge_eval`/`overlap_eval`; imports only `dos.intervention`. Scores the
  policy through the SAME `choose_intervention` path the consumer takes (the "score under the
  floor" discipline). Boundary I/O (reading a run's outcomes) at the call site, the fold pure.
- **Driver / consumer — SHIPPED `benchmark/enterpriseops/dos_react.py`:** the *withholding*
  rungs (`BLOCK` — return a synthetic corrective result; `DEFER` — skip + re-prompt) actuate
  where the effect lives — the `dos_react` orchestrator is the reference consumer (a typed
  `intervention` mode + `InterventionPolicy`, back-compat for `enforce`/`DOS_WARN_ONLY`). The
  kernel ships the ladder + escalation + eval + the synthetic-result builder; it never performs
  the actuation (the docs/99 line, held — the consumer substitutes the dict and continues the
  loop).
- **Operator surface — SHIPPED `dos intervention-eval`:** the CLI verb (mirroring `dos
  judge-eval` / `dos overlap-eval`; exit 1 iff the policy is net-harmful). Surfacing the
  recommended rung in `dos decisions` is the remaining Phase-4 lift.

The litmus the layering keeps: the kernel can *recommend* a rung and *score* the net effect
of any rung, but **the kernel never actuates** — OBSERVE/WARN are non-actuating by type, and
DEFER/BLOCK are a consumer's opt-in. The PDP stays pure; the PEP stays a driver.

---

## 5. Phasing

1. **`dos.intervention` (the type + ordering + escalate + floor).** Pure, unit-tested in
   isolation — the `dos.reasons` analogue. Ships the closed vocabulary and the
   confidence→rung coupling. (No actuation; the floor guarantee is a type test.)
2. **`dos.intervention_eval` + `dos intervention-eval`.** The net-harm grid over replayed
   outcomes. Re-score the docs/143 live A/B through it as the seed fixture (SKIP =
   high net-harm, WARN = low) — the eval's first datum is the result that motivated it.
3. **The non-disruptive `BLOCK` primitive** in the reference consumer (`dos_react`): a
   synthetic corrective tool-result in place of the minted mutation, turn preserved. Run the
   A/B arm (§1a). **SHIPPED + proven** on the simulator (BLOCK +0.40 net-delta over DEFER);
   the real-model run is the remaining live experiment.
4. **Wire the rung into `dos decisions`** (a refusing verdict surfaces its recommended
   intervention) and into the docs/126 apply-gate (the PEP reads the rung instead of a flat
   block). Optional `dos.toml [intervention]` for a host's escalation policy — **the config
   seam is SHIPPED** (`SubstrateConfig.interventions` + `intervention.load_from_toml`, the
   closed-config-as-data pattern, like `[liveness]`/`[reasons]`); the `dos decisions` /
   apply-gate wiring is the remaining lift.

Phases 1–3 are SHIPPED (Phases 1–2 pure kernel; Phase 3 the consumer-side BLOCK + the
simulator proof). The remaining work is Phase 4's `decisions`/apply-gate wiring and the live
real-model BLOCK arm.

---

## 6. The honest non-goals

- **Not a planner.** The intervention is about *how to act on a verdict*, never *what the
  agent should do instead* — recommending the agent's next step is the planner DOS refuses
  to be (docs/143 §7, [[project-dos-memory-is-an-unverified-agent]]).
- **Not a sandbox.** DEFER/BLOCK withhold a *specific adjudicated effect*; they do not
  intercept arbitrary syscalls or mediate every write (the docs/126 "narrow shape" discipline
  — one effect-typed chokepoint, not a container).
- **Not mandatory enforcement.** The floor stays advisory (OBSERVE/WARN), preserving the
  docs/99 "report, don't actuate" doctrine for every host that wants it; enforcement is opt-in
  per rung, and the eval is what tells a host whether opting in pays.

---

## 7. Why this is the right next moat

DOS's pitch has been "a sound, forgery-resistant verdict, cheaply, vendor-neutral." The
EnterpriseOps-Gym run proved that pitch is *real* (0 % false-nudge, 83 % recall on a real
benchmark) **and** that it is *not enough* (a sound verdict, badly enforced, lost points).
Every competitor that ships a PEP (the Microsoft AGT line in the security sweep —
[[project-dos-devices-and-unattended]]) competes on enforcement; DOS competes on a *sound*
verdict but has no disciplined enforcement story. This plan is that story, and it is
*differentiated*: not "we can block" (everyone can block) but "**we know, per deployment and
from data, the cheapest intervention that makes a true verdict bind without costing more than
the harm it prevents.**" That is a measured, evaluable claim — the same shape as every other
DOS axis — and it is the half of the security program (`dos-private/…security-10x-100x.md`)
that the verdict work alone could never reach.

**Cross-refs:** the motivating measurement = docs/143 §0/§13 + `benchmark/enterpriseops/RESULTS.md`;
the PEP this disciplines = docs/126; the advisory floor it preserves = docs/99 + docs/101;
the decision-side closed set it mirrors = `dos.reasons`; the per-axis eval pattern it follows
= `judge_eval` / `overlap_eval`; the evidence-confidence grading §3 reuses = docs/138.

**Live experiment artifacts (the read order):**
- `docs/151_intervention-ladder-live-study.md` — **the paper:** the self-contained methodology +
  results writeup (abstract → tiered design → results → robustness → limitations → conclusion).
- `benchmark/enterpriseops/THEORY_LADDER.md` — the tiered test plan, "what the live run did"
  step by step, and the flip-independence robustness check (the verdict holds on the plain
  aggregate, no per-task flip needed).
- `benchmark/enterpriseops/intervention_theories.py` — Tier 0, the $0 sweep that PREDICTED the
  result (WARN optimal at a low mattered-rate) before any API spend.
- `benchmark/enterpriseops/intervention_ab.py` — the simulator A/B (mechanism only).
- `benchmark/enterpriseops/live_ab.py` — the live runner (Tiers 2–4, scaled by `--tasks`).
- `benchmark/enterpriseops/analyze_live.py` — the unified live report (mechanism + aggregate scores).
- `benchmark/enterpriseops/mattered_join.py` — the per-task verifier-flip decomposition (the *why*).
- `[[reference-enterpriseops-gym-runnable]]` + `[[project-dos-intervention-ladder-built]]` — the
  memory pointers (key + Docker present; the live finding).

**The live verdict (2026-06-04, final):** on the REAL gym (4 FK-heavy domains, 80 tasks/arm,
gemini-2.5-flash, the gym's own hidden SQL verifiers untouched), with the SAME injected mints
across arms — **WARN +6.2 pp (winner), DEFER +2.0, BLOCK +0.0 (dead on the do-nothing baseline).**
The §13.4 "non-disruptive BLOCK is the prize" hypothesis is **falsified on live data**: withholding
the call, even with a synthetic corrective result, breaks ~6× more downstream steps (BLOCK 13
hurt-flips vs WARN 2). WARN — inform-and-still-dispatch — is the robust optimum; BLOCK/DEFER are
high-stakes-effect safety valves, not the default. The result holds on the plain aggregate
(no flip): `none 39.9 · DEFER 41.9 · WARN 46.0 · BLOCK 40.2` verifier-pass.
