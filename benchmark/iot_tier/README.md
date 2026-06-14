# iot_tier — does DOS help more as the model shrinks toward IoT-class?

> **One line.** DOS's recoverable-failure fraction is **non-monotone in model size**: it
> rises from the strong-model null to a **peak on a middle model**, then **collapses** at the
> IoT (sub-3B edge) end — because the weakest models' failures migrate into *silent* stops DOS
> owns 0% of. The proof point is the **middle**, not the weakest model. This is a **calibrated
> simulation** (synthetic corpora, real shipped detectors); the measurement that would replace
> the calibration is the docs/153 Stage-0 ~$50 real IoT-corpus run.

## The research question

The DOS thesis ([docs/153](../../docs/153_can-dos-lift-a-weak-model.md)): *DOS hardens the
execution substrate UNDER a cheap agent's plan.* It recovers the **execution-substrate
fraction** of a model's failures — minted ids, byte-identical loops, and the *narrating*
premature stop — and owns **0%** of planning + *silent* stops. So a weaker model, failing
*more* at the substrate, should have a *more DOS-shaped* failure mix.

But docs/153 §1 predicts this does **not** continue all the way down: at the weakest end the
`can-do-step-when-nudged` factor decays toward 0 — a tiny model narrates "I need X" *because* X
is the step it cannot form, so as it weakens further it stops even narrating, and its failures
become *silent*. So the recoverable fraction should **rise then fall**.

The repo already had the instrument to test this —
[`weak_model_gate.py`](../enterpriseops/weak_model_gate.py), the model-agnostic gate that folds
the three shipped byte-clean detectors over any corpus and reports the deduped,
enrichment-filtered recoverable fraction vs a pre-registered 15% threshold. It was
self-validated on gemini (the strong-model null: ~13% < 15% → DOS-shape FALSE). **Nobody had run
it across a model-size ladder.** `iot_tier` does — it turns the single-corpus gate into a sweep.

## The curve (run it: `python -m benchmark.iot_tier.harness`)

```
  tier      model class              recoverable-fraction (deduped, enriched)
  frontier  gemini-2.5-flash class   ####------------------------  13%
  mid       DeepSeek-V3.2 class      ##########------------------  34%  <- PEAK
  small     Qwen3-class              #######---------------------  23%
  iot       sub-3B edge class        ###-------------------------  10%  <- COLLAPSE
                                       |
                                   15% threshold
```

**Reading:** DOS's lift is largest on the **middle** model (it can plan a task it then fumbles in
execution — exactly the slice DOS guards). The frontier rarely fumbles the substrate (the null);
the IoT tier fumbles it *more* but those fumbles are silent-stops, not the recoverable kind — so
the curve falls back below the null. Only `mid` clears the 15% "run the live A/B" gate. The
detector enrichment per tier confirms the mechanism: MINT is **excluded as noise** on the
frontier (it fires ≥ on passes — the docs/153 §5 residual false-flag), and the unreachable
remainder grows from the peak to IoT (the collapse).

## The honesty contract — why this is not a guessed magnitude

docs/153's discipline is *measure, don't guess*. This benchmark keeps it three ways:

1. **The detectors are the REAL shipped kernel functions** (`dos.dangling_intent.classify_stop`,
   `dos.tool_stream.classify_stream`, `dos.arg_provenance` via the validated `replay_recall`
   path), folded by the **REAL** gate (`weak_model_gate.gate_fraction` — the exact enrichment
   logic, reused, not reimplemented). The recoverable fraction is computed by the validated path,
   including the signal-vs-noise filter that excludes detectors firing equally on passes.
2. **The corpus is synthetic but its calibration is declared and cited.** Every tier's failure
   mix is an auditable table in [`tiers.py`](tiers.py) — a per-task failure rate and the split
   across `{mint, loop, narrating_stop, silent_stop, planning}`, each number cited to docs/153
   §1–§2. The reader sees exactly what was assumed. The IoT extrapolation rule (narrating-stop
   migrates into silent-stop as `can-do-when-nudged` decays) is stated, not hidden.
3. **The instrument self-validates against the known null.** The `frontier` tier, calibrated to
   the gemini shape, **reproduces the gate's published result** (< 15%, MINT excluded as noise,
   DANGLE+LOOP signal). If it didn't, the in-band falsifier exits non-zero. A test asserts it.

**The falsifier is in-band.** The harness exits non-zero if (a) the frontier fails to reproduce
the null, or (b) the curve is flat / monotone instead of rise-then-collapse. A wrong calibration
says so loudly — the honest kill, not a silent pass.

**What would replace the calibration with a measurement:** the docs/153 Stage-0 ~$50 real run at
the IoT tier — record a real sub-3B model's trajectories through `dos_react` (no intervention,
just record), then fold this same gate over the real bytes. That run is tracked as a GitHub issue.
Until then, `iot_tier` headlines the **shape and the mechanism**, never a measured pp lift.

## Files

| file | role |
|---|---|
| [`tiers.py`](tiers.py) | the declared, cited model-tier ladder (the calibration, for audit) |
| [`synth.py`](synth.py) | deterministic synthetic-trajectory generator (the gate's exact JSON shape) |
| [`harness.py`](harness.py) | the sweep: fold the real gate per tier → ASCII curve + `--json` + falsifier |
| [`test_iot_tier.py`](test_iot_tier.py) | byte-fidelity + the frontier null self-test + the curve falsifier |
| [`RESULTS.md`](RESULTS.md) | the committed scored summary |

## Run

```bash
python -m benchmark.iot_tier.harness            # the ASCII curve (exit 0 iff the prediction holds)
python -m benchmark.iot_tier.harness --json     # machine-readable rows
python -m benchmark._run run iot_tier           # via the standardized runner (stamped)
python -m pytest -q benchmark/iot_tier/         # the tests incl. the frontier self-test
```

`$0` — no key, no Docker, no spend. Pure replay over the real detectors. This is a **consumer** of
the kernel (the one-way arrow: nothing under `src/dos/` imports it).
