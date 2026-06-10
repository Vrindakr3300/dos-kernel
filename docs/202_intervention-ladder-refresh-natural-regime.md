# 202 — Refreshing the intervention ladder against the natural regime: the +6.2pp was injected-only

> **Type:** results refresh (re-scoring docs/151 against the docs/198 feasibility correction).
> **Status:** COMPLETE (2026-06-06). $0 re-score adversarially verified; the targeted live
> curable-slice conversion run has landed (§5.1) — over-sampling lifted the curable slice to n=19
> but reached only d=1 convertible flip, so conversion is **unreachable to power** on this
> benchmark (the convertible population is too thin even when hunted).
> **Supersedes:** the docs/151 headline *as a general claim*. docs/151's mechanism (WARN is the
> least-disruptive intervention; BLOCK's withholding breaks downstream steps) still HOLDS; what
> changes is that its **+6.2pp integrity lift is now regime-qualified to the INJECTED-mint regime
> only** — on the natural failure stream it evaporates to a flat +0.20pp.
>
> **One-sentence result:** docs/151's WARN +6.2pp reproduces at **+6.03pp on the injected corpus**
> but goes **flat (+0.20pp) on the natural failure stream** — because natural thrash is dominated
> by the WALLED, infeasible `create_filter` (0 successes ever / 278 errors) that no cure can
> convert (the docs/198 category error), so the durable, regime-independent win is **feasibility-
> gated early-halt** (false-abandon 0.000, 3.5k–22.8k tokens saved across all four corpora), not
> the intervention lift.

---

## 0. Why this refresh exists

The operator's read was *"the 151 thing feels outdated."* It is — and the reason is exactly the
[docs/198 feasibility correction](198_the-feasibility-witness-and-give-up-correctly.md), applied to
the one study that most prominently rests on the old framing.

docs/151 measured a 4-arm intervention A/B (`none`/`DEFER`/`WARN`/`BLOCK`) on EnterpriseOps-Gym
and reported **WARN +6.2pp integrity** as the headline. But that study ran in the **injected-mint
regime** (`DOS_MINT_RATE` nominal 0.3, realized ~0.10): it *manufactures* the invented-FK failure
mode by corrupting argument bytes, because a capable model's *natural* mint rate is ~0. docs/198
then established (2026-06-06) that every cure on this benchmark line had been scored against a
**denominator polluted with infeasible tasks** — and that the honest move is to **split the
population by a byte-clean feasibility witness FIRST** (WALLED = a tool with 0 successes anywhere;
CURABLE = a tool that succeeds on some run), score *conversion* only on the curable slice, and
score *give-up-correctly* on the walled slice.

This document does that to docs/151: it re-scores **every recorded EnterpriseOps corpus** —
natural and injected — through the shipped `feasibility_split.py`, and asks: **how much of the
+6.2pp survives on the natural failure stream a real model inhabits?**

Answer: essentially none. The +6.2pp is a property of the *injection*, not of *WARN*.

## 1. The four corpora re-scored

All numbers are `$0`/deterministic re-scores of already-recorded trajectories (no new model
calls), via the shipped `feasibility_split.py` / `feasibility_witness.py` (which import the
kernel's byte-identical struct-error grammar). Every headline number below was independently
re-derived from the raw `results_*.json` bytes by an adversarial verifier — see §4.

| corpus | regime | arm | integrity % | Δ vs none | success % | curable-slice conv. | powered? |
|---|---|---|---|---|---|---|---|
| `live_results` (docs/151 source) | **INJECTED** (mint ~0.3 nom / ~0.10 real) | none | 40.32 | — | 11.11 | — (baseline) | — |
| `live_results` | INJECTED | defer | 41.85 | +1.54 | 12.50 | n=4, net +1, p=1.0 | no (n<30, d=1) |
| `live_results` | INJECTED | **warn** | 46.35 | **+6.03** | 16.05 | n=4, net +2, p=0.5 | no (n<30, d=2) |
| `live_results` | INJECTED | block | 40.20 | −0.12 | 10.26 | n=4, net +1, p=1.0 | no (n<30, d=1) |
| `live_results_natural` | **NATURAL** (mint 0.0) | none | 50.38 | — | 16.67 | — (baseline) | — |
| `live_results_natural` | NATURAL | **warn** | 50.58 | **+0.20 (FLAT)** | 10.00 | **n=0, d=0 — UNTESTED** | no |
| `live_results_natural_ab` | NATURAL (mint 0.0) | none | 38.86 | — | 9.17 | — (baseline) | — |
| `live_results_natural_ab` | NATURAL | rewind_natural | 42.48 | +3.62 pooled / +0.94 paired | 9.58 | n=6, net 0, d=0 — UNTESTED | no |
| `live_results_natural_run` | NATURAL (mint 0.0) | none | 46.55 | — | 14.00 | — (baseline) | — |
| `live_results_natural_run` | NATURAL | resurface | 44.67 | −1.88 | 11.00 | n=1, d=0 — UNTESTED | no |

> Integrity == verifier-pass in every corpus by construction (the gym's scored DB-state
> verifications ARE the integrity measure). Pooled = per-verifier over all runs; "paired" deltas
> (where they differ) are noted inline. Conversion columns use `feasibility_split`'s pre-registered
> CURABLE-slice rule: **powered ⟺ curable n ≥ 30 AND discordant pairs d ≥ 6.** No recorded corpus
> meets it — see §5.

## 2. The delta-of-deltas — the core finding

- **Injected WARN delta:** +6.03pp integrity (46.35 − 40.32). Reproduces the docs/151 headline
  (the published "+6.2" is within rounding/n-drift of this exact on-disk run).
- **Natural WARN delta:** +0.20pp integrity (50.58 − 50.38). FLAT. And task success *drops*
  16.67% → 10.00% (n=60 paired; **not** significant — sign-p = 0.219, only 6 discordant pairs —
  so a non-significant *hurt*, not a measured loss).
- **Delta-of-deltas ≈ +6.0pp of pure regime artifact.**

**The mechanism (docs/198 made concrete).** Split the `none` arm of each corpus by feasibility:

| corpus | regime | WALLED | CURABLE | NO_THRASH |
|---|---|---|---|---|
| `live_results` | INJECTED | 3 | 4 | 74 |
| `live_results_natural` | NATURAL | 5 | **0** | 55 |
| `live_results_natural_ab` | NATURAL | 9 | 6 | 225 |
| `live_results_natural_run` | NATURAL | 6 | 1 | 93 |

On the natural stream the thrash is **dominated by `create_filter`** — 0 ok / 278 errors across
the natural_ab corpus, every call returning `isError: criteria.<field> is required`. Its schema
demands all ~9 `criteria` fields non-empty, so the task "filter on sender only" is **infeasible**:
a WALLED wall no cure can convert. With essentially **zero curable thrash to act on**, WARN nudges
a handful of times and moves ground-truth DB state nowhere helpful — integrity stays flat.

The injected regime is different precisely because the injection *manufactures* a curable-ish
failure: forged argument bytes WARN can re-surface. Even there, though, the +6pp does **not** come
from the curable slice (n=4, underpowered, d=2, sign-p=0.5) — it is a broad small per-verifier
improvement spread across the 74 no-thrash runs that the injection pressure made reachable. So the
+6.2pp is doubly a creature of the injection: the injection both creates the curable failures
*and* applies the across-the-board pressure the lift rides on.

## 3. What supersedes docs/151, and what holds

**SUPERSEDED (regime-qualified):** the claim that *WARN delivers a +6.2pp integrity lift* as a
**general** property of the intervention. That number is now **injected-mint-only**. It must no
longer be cited as "what WARN buys you"; cite it as "what WARN buys you *when the failure mode is
forgeable argument bytes the cure can re-surface*."

**HOLDS:**

1. **WARN is still the least-disruptive intervention.** On natural it nudges without the
   catastrophic flips BLOCK causes; it never refuses a lease or kills a process. The docs/151
   *cost-of-acting* ordering (OBSERVE ‹ WARN ‹ BLOCK ‹ DEFER) is untouched.
2. **BLOCK's disruption mechanism is real and re-confirmed here.** On the injected corpus BLOCK is
   null-to-harmful (integrity −0.12pp vs none; success 10.26% *below* none's 11.11%), consistent
   with the docs/151 "13 hurt-flips" story: withholding forgeable bytes derails more than it saves.
3. **The docs/198 feasibility split is the methodological fix that makes all of this legible.**
   Scoring a cure against a polluted denominator (WALLED + CURABLE + NO_THRASH mixed) produced the
   false "general lift"; splitting the population first reveals natural thrash is WALLED-dominated,
   so the cure has almost nothing curable to act on.
4. **Witness-gated early-halt is the regime-independent survivor** — see §6.

## 4. Adversarial verification (all three claims reproduced, none refuted)

Three skeptic agents re-derived each headline straight from the raw `results_*.json` bytes — NOT
from the scorer's printed output — several with a **hand-retyped struct-error grammar** rather than
importing the kernel, defaulting to `refuted=true` if the bytes did not support the claim.

- **Natural FLAT:** none integrity 132/262 = 50.382%, warn 131/259 = 50.579% → Δ +0.20pp;
  success 16.7% → 10.0% (warn arm 10 → 6 successes). Reproduced to < 0.1pp. **Not refuted.**
- **`create_filter` is WALLED:** 0 ok / 278 err across both arms; every call returns
  `isError: criteria.X is required` (a genuine env-authored schema wall). Natural curable slice
  re-derived exactly: n=6, d=0. **Not refuted.**
- **Witness-gated early-halt PASSES:** gated FA-rate 0.000 at K=2/3/4; gated K=2 = 22,851 tokens
  saved (correctly the *gated* figure, not the un-gated 33,132). Two walled-fired runs spot-checked
  against the gym's hidden SQL and confirmed *failed* (so halting them costs no real success).
  **Not refuted.**

Two honesty flags, neither a refutation: (a) published "+6.2pp" vs this run's +6.03pp pooled —
within rounding/n-drift; (b) the injected corpus's recorded mint arg is 0.3 (realized ~0.10), not
the 0.35 a stale note implied — we report what the corpus contains.

## 5. The (formerly open) arm — natural CURABLE-slice conversion

**On found data this was untested on every recorded corpus.** The curable slice was n=0
(`live_results_natural`), n=6 (`live_results_natural_ab`), n=1 (`live_results_natural_run`), with
discordant flips d=0 in all three — far below the pre-registered power rule (n ≥ 30 AND d ≥ 6). So
the curable NET could **not** be read as a result; WARN's *natural* value was **UNKNOWN, not zero**.
**§5.1 closes this with a targeted live run** — and the answer is that the convertible population is
too thin to power even when deliberately over-sampled (n=19, d=1).

Natural thrash is simply too rare and too concentrated on infeasible WALLED tools (the docs/198
trap) to settle conversion on found data. The decision-relevant spend docs/198 §4.2 identified is
the **only** new run: over-sample the curable-thrash task families to drive the curable slice to
n ≥ 30. **That run has now landed (§5.1) — and the answer is that even targeted over-sampling
cannot reach power: the curable slice grew to n=19 but yielded only d=1 convertible flip.** The
command that produced it:

```
python live_ab.py --task-ids <11 curable-thrash families> --reps 5 \
    --arms none warn restart_seeded --domains email itsm --mint-rate 0.0 \
    --out live_results_curable_ab
python feasibility_split.py --out live_results_curable_ab --cure warn --min-curable-n 30
```

**§5.1 — the curable-slice result (live, 2026-06-06): conversion stays UNTESTED-toward-null even
under targeted over-sampling.** The run landed: 55 paired runs/arm (11 curable-thrash families × 5
reps), `none`/`warn`/`restart_seeded`, natural regime, gemini-2.5-flash. The over-sample **worked**
— it lifted the curable slice from n=6 (found data) to **n=19** — but the pre-registered kill is
**still not reachable**, because the convertible *flips* are too rare:

| slice | n | help | hurt | net | sign-p | powered? |
|---|---|---|---|---|---|---|
| all paired | 55 | 3 | 3 | +0 | 1.000 | — |
| no-thrash | 26 | 2 | 3 | −1 | 1.000 | — |
| WALLED-only | 10 | 0 | 0 | +0 | n/a | — |
| **has CURABLE thrash** | **19** | **1** | **0** | **+1** | **1.000** | **no (d=1 < 6)** |

**The curable slice reached n=19 but only d=1 discordant flip** — far below the d ≥ 6 a sign test
needs to reach p < 0.05. So WARN's curable-slice NET (+1) **must not be read as a win**; the honest
verdict is **conversion remains untested, trending null**. And this is itself the finding: *even a
targeted run that deliberately over-samples the curable-thrash task families cannot manufacture
enough convertible flips* — natural curable-thrash is rare AND, when it fires, the cure rarely flips
the scored outcome. The over-sample confirms the population is thin rather than refuting it.

Two corroborating reads from the same run:

- **`restart_seeded` (the docs/193 structural-escape comparand) was clearly worse here** — integrity
  10% vs none's 30% (−20pp), success 0% all arms. Clean-restart-with-seeded-knowledge cost more
  than it saved on these tasks (it re-pays the prefix and the curable-thrash tasks are long).
- **Witness-gated early-halt PASSES again, with the largest savings yet** — gated FA-rate 0.000 at
  K=[2,3,4], **43,678 tokens saved** at K=2 (15 runs halted, all on a WALLED wall). The *un-gated*
  variant FAILS the kill here (FA-rate 0.062–0.080 — it kills 2–3 actually-succeeding runs), so the
  **witness gate is load-bearing**, re-confirmed on a third corpus.

**Net effect on this document's thesis:** the open question of §5 is now answered *as far as found-
and-targeted data can answer it* — **natural curable-slice conversion is unreachable to power on
this benchmark** (the convertible flips are too few even when you hunt for them), so WARN's
*measured* natural value is **null-to-untestable**, while the regime-independent early-halt win only
strengthens (43.7k tokens saved). This does not refute that a cure *could* convert curable thrash in
principle — it establishes that on the EnterpriseOps natural stream the population is too thin to
demonstrate it, which is the docs/198 lesson at its sharpest.

## 6. The durable, regime-independent win: feasibility-gated early-halt

The value that survives across **all four** corpora — injected and natural alike — is **giving up
correctly** on a WALLED wall:

| corpus | regime | fired (K=2) | false-abandon | FA-rate | tokens saved | passes kill (K=2,3,4)? |
|---|---|---|---|---|---|---|
| `live_results` | INJECTED | 3 | 0 | 0.000 | 3,498 | yes |
| `live_results_natural` | NATURAL | 5 | 0 | 0.000 | 3,521 | yes |
| `live_results_natural_ab` | NATURAL | 10 | 0 | 0.000 | 22,851 | yes |
| `live_results_natural_run` | NATURAL | 7 | 0 | 0.000 | 6,653 | yes (un-gated FAILS: FA 0.111) |

Witness-gated early-halt clears its pre-registered kill (FA-rate 0.000 AND positive token savings)
at K=[2,3,4] on every corpus, because **you structurally cannot kill a winner on a tool that never
wins**. On `live_results_natural_run` the *un-gated* (any-tool) variant FAILS the kill (it would
halt 1 actually-succeeding run, FA-rate 0.111) — so the **witness gate is load-bearing**, not
cosmetic. This is the docs/198 "give-up-correctly on the walled slice" value, confirmed across the
whole corpus set.

## 7. Bottom line

- **Stop citing +6.2pp as WARN's general worth.** It is an injected-mint-regime number (+6.03pp
  there, +0.20pp flat on natural). The delta-of-deltas is ~+6.0pp of pure regime artifact.
- **The mechanism is the docs/198 feasibility category error:** natural thrash is WALLED-dominated
  (`create_filter` 0 successes ever), so the cure has almost nothing curable to convert.
- **What holds from docs/151:** WARN is still the least-disruptive intervention; BLOCK's
  withholding-breaks-downstream disruption is real and re-confirmed; the feasibility split is the
  methodological fix.
- **The regime-independent win is feasibility-gated early-halt** (FA 0.000, 3.5k–22.8k tokens
  saved), not the intervention lift.
- **The one open question — natural curable-slice conversion — is now answered as far as the data
  allows** (§5.1): a targeted over-sample lifted the curable slice to n=19 but produced only d=1
  convertible flip, so conversion is **unreachable to power** on this benchmark — WARN's natural
  value is **null-to-untestable**, not a measured win. The thinness of the convertible population
  *is* the result; the early-halt win (43.7k tokens saved) only strengthens.

> **Reproduce (all $0):**
> ```
> python benchmark/enterpriseops/feasibility_witness.py --out benchmark/enterpriseops/live_results_natural
> python benchmark/enterpriseops/feasibility_split.py  --out benchmark/enterpriseops/live_results_natural --cure warn
> python benchmark/enterpriseops/feasibility_split.py  --out benchmark/enterpriseops/live_results --cure warn   # the injected +6.03pp
> python benchmark/enterpriseops/feasibility_split.py  --out benchmark/enterpriseops/live_results_natural_ab --cure rewind_natural
> ```
