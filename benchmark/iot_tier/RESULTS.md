# iot_tier — results

<!-- dos-bench-stamp: kernel=0.26.0 sha=c3f33a9 date=2026-06-14 -->

> **Calibrated simulation** (synthetic corpora, real shipped detectors via the real gate fold).
> The headline is the **shape and the mechanism**, never a measured pp lift. The measurement that
> would replace the calibration is the docs/153 Stage-0 ~$50 real IoT-corpus run (tracked as a
> GitHub issue). Reproduce: `python -m benchmark.iot_tier.harness` (deterministic, seed 1729).

## The recoverable-fraction curve (n=400 runs/tier, seed 1729)

| tier | model class | per-task fail | recoverable fraction | enriched detectors | unreachable |
|---|---|---|---|---|---|
| frontier | gemini-2.5-flash class | 0.45 | **13%** (the null) | loop, dangle (MINT=noise) | 150/173 |
| mid | DeepSeek-V3.2 class | 0.75 | **34%** ← PEAK | mint, loop, dangle | 196/298 |
| small | Qwen3-class | 0.84 | **23%** | mint, loop, dangle | 253/330 |
| iot | sub-3B edge class | 0.92 | **10%** ← COLLAPSE | mint, loop, dangle | 328/366 |

(15% = the docs/153 §3 pre-registered "run the live A/B" threshold. Only `mid` clears it.)

## What the curve shows

1. **Non-monotone in model size.** The recoverable fraction rises from the strong-model null
   (frontier 13%) to a **peak on the middle model** (mid 34%), then **collapses** at the IoT end
   (iot 10%) — back below the frontier null. This is the docs/153 §1 prediction, made visible.

2. **The proof point is the MIDDLE, not the weakest model** (docs/153 §2, now *measured* on the
   calibrated ladder rather than only asserted). A middle model can plan a task it then fumbles in
   execution — so execution fumbles are a bigger share of its gap, and DOS's detectors fire on a
   bigger share of its failures. The IoT model fumbles *more* overall, but its fumbles are silent.

3. **The mechanism is the unreachable remainder.** The share DOS owns 0% of (silent-stop +
   planning) is the trough at `mid` and climbs to IoT (196/298 → 328/366 ≈ 66% → 90% of failures
   unreachable). At the IoT tier the `can-do-when-nudged` decay migrates the narrating-stop share
   into silent-stops — the failures stop being legible.

4. **The frontier self-test passed.** Calibrated to the gemini shape, the frontier tier reproduced
   the published null: 13% < 15%, MINT **excluded as noise** (it fires ≥ on passes — the residual
   false-flag docs/153 §5 reports), DANGLE the one naturally-firing signal axis. The instrument is
   measuring the same thing `weak_model_gate.py` self-validated on real gemini recordings.

## The honest caveat

These four points are properties of a **calibrated simulation**: the failure-mix per tier is a
*declared input* ([`tiers.py`](tiers.py)), cited to docs/153 §1–§2, not a measured magnitude. What
the simulation contributes is: (a) the gate's real enrichment logic applied across a ladder for the
first time, (b) a falsifiable rise-then-collapse curve with an in-band falsifier, and (c) the
frontier self-test grounding it to the known real null. The number that turns the assumptions into
a measurement is the real sub-3B corpus run — until then, no pp lift is claimed for any real model.
