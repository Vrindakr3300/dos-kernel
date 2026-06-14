# smartphone_tier — does DOS help more as the model shrinks toward a phone? (docs/341)

<!-- dos-bench-stamp: kernel=0.26.0 sha=5422122 date=2026-06-14 -->

> **The question:** DOS is "the part that doesn't believe the agents." If that is
> worth anything, it should be worth MORE on a weak, on-device model than on a
> frontier one — because a weak model fails in ways DOS can flag (it narrates a
> step then stops, invents an id it cannot resolve, loops on the same read), while
> a frontier model that reads-before-it-writes mostly fails SILENTLY, where the
> byte-clean detectors are blind. This benchmark measures that prediction as a
> **capability curve**: the DOS-recoverable failure fraction across the capability
> axis from weak (phone-tier) to frontier.

Run (free — no model, no network, no Docker; the real kernel detectors only):

```bash
PYTHONPATH=. python -m benchmark.smartphone_tier.harness --corpus   # THE MEASUREMENT (real data)
PYTHONPATH=. python -m benchmark.smartphone_tier.harness            # the synthetic pre-registration
PYTHONPATH=. python -m benchmark.smartphone_tier.harness --json     # machine-readable
```

## THE MEASUREMENT (`--corpus`) — real data, the honest headline

Folded over the committed Toolathlon replay corpus —
[`benchmark/toolathlon/_results/replay_all_rows.csv`](../toolathlon/_results/replay_all_rows.csv),
**7,116 recorded runs across 22 real models** (the same rows behind the paper's
detector table), each carrying the third-party oracle verdict and the detectors'
fires. Capability axis = each model's task pass-rate; models binned into tiers:

| capability tier | models | failed runs | recoverable | **recoverable fraction** |
|---|---|---|---|---|
| **very-weak** (<12% pass) | 3 | 893 | 128 | **14.3%** |
| weak (12–20%) | 8 | 2,164 | 151 | **7.0%** |
| mid (20–32%) | 6 | 1,411 | 48 | **3.4%** |
| strong (≥32%) | 5 | 1,014 | 15 | **1.5%** |

**Overall recall (recovered / all failures): 6.2%.** Per-model, the recoverable
fraction correlates with capability at **Pearson r = −0.58** — it genuinely falls as
the model gets stronger.

### Is 80% recovered huge, or are we fooling ourselves?

We were fooling ourselves on the **magnitude**, and we are not on the **direction**.

- **The direction is real and clean.** The recoverable fraction falls monotonically
  across tiers (14.3% → 1.5%), r = −0.58 across 22 models. A weak/phone-tier model's
  failures are ~**10× more** DOS-recoverable than a strong model's. That is the
  thesis, and the real data supports it.
- **The level is ~14% at the weak end, not 80%.** The synthetic pre-registration
  (below) declared 80%; the measurement says ~14%. The detectors are **high-precision,
  low-recall**: when they fire they are almost always right (the paper: 88–98%
  precision, <1.6% false-alarm), but they fire on only a small, *shrinking* slice of
  failures. Most failures — even on weak models — are **silent**: a confidently-wrong
  run that narrates no open work, loops on nothing, and emits no error envelope leaves
  no byte to read. That silent majority is the recall ceiling, and it is the paper's
  central honest result.

So the headline is not "DOS recovers 80% of a phone model's failures." It is: **DOS
recovers a small but capability-dependent slice (~6% overall, ~14% at the weak end),
and that slice is trustworthy and concentrates exactly where a phone-tier model needs
it most.** The value is the *direction plus the precision*, not a big recall number.

## The synthetic pre-registration (default mode) — and why it was optimistic

The default (no `--corpus`) folds the real detectors over a SYNTHETIC corpus whose
per-tier failure counts are a **declared shape**, not a measurement:

| tier | recoverable fraction (synthetic) |
|---|---|
| `<=1B` | 80.0% |
| `1-3B` | 65.7% |
| `3-7B` | 40.0% |
| `frontier` | 11.8% |

This got the *direction* right (monotone fall, frontier ≈ the gemini null) but
**over-stated the level by ~5–6×** at the weak end. It assumed a weak model's
failures are mostly the three DOS-shaped kinds; the real corpus shows the silent kind
dominates at every tier. Keeping both side by side is the lesson: a declared shape is
a hypothesis; the corpus is the verdict (docs/145). The synthetic mode still earns
its place as the instrument self-test (it proves the detectors fold correctly and the
directional falsifier fires), but **the measured curve is the one to cite.**

## What is real, and what is a placeholder

- **Real (both modes):** every fire is the live kernel detector
  (`dos.dangling_intent` / `dos.tool_stream` / `dos.arg_provenance`, plus
  Toolathlon's `terminal_error` in the corpus mode); the harness never re-encodes a
  rule (pinned by `test_kernel_verdict_not_reimplemented`).
- **Real (corpus mode):** the failure counts and oracle verdicts are the recorded
  Toolathlon corpus — a third-party grader the agents could not influence.
- **Placeholder (synthetic mode only):** the per-tier failure *counts* are a declared
  pre-registration. Captioned as such; the measurement supersedes it.

## A true on-device run (`_drive_cpu_model.py`) — and a surprise at the extreme low end

The corpus above is 22 cloud/open models replayed; none is a sub-1B model actually
running on a phone-class device. So we drove the smallest real instruct model we could
— **SmolLM2-135M-Instruct, on CPU** (no GPU, no torch-CUDA, ~270 MB) — over two
tool-use tasks and folded the SAME detectors through `--recordings`:

```bash
pip install --user --index-url https://download.pytorch.org/whl/cpu torch
pip install --user transformers
python -m benchmark.smartphone_tier._drive_cpu_model --out /tmp/smol_runs
python -m benchmark.smartphone_tier.harness --recordings /tmp/smol_runs --tier-name "SmolLM2-135M"
```

**Result: 6/6 runs FAILED, 0% DOS-recoverable.** The 135M model failed *below the
detectors' reach* — and the reason is instructive, not a bug:

- On the lookup task it emitted `DONE` immediately, with **no tool call and no
  "I still need to…" cue** — a silent premature stop, so `dangling_intent` correctly
  abstains (it is a DONE-claim, not an open-obligation admission).
- On the assign task it hallucinated a tool literally named `U7` (it echoed the user
  id as the tool name) — malformed garbage the env rejected, **not a minted id on a
  real mutating tool**, so `arg_provenance` correctly abstains.

This is the **recall ceiling turned the other way**: there is a capability floor below
which a model is *too weak to fail in a DOS-shaped way*. It does not narrate abandoned
plans (it just says DONE); it does not mint a plausible FK on a real tool (it emits
nonsense). So the recoverable curve is **not monotone-rising all the way down** — it
rises from frontier toward the weak tiers, then **falls again at the sub-0.5B extreme**
where failures stop being structured. The byte-clean detectors need a model competent
enough to fail *coherently*. That is a real, citable nuance the synthetic 80% hid
entirely, and it sharpens the paper's silent-failure story: silence dominates at *both*
ends of the capability axis, for opposite reasons (frontier = succeeds-or-fails-cleanly;
sub-0.5B = fails-incoherently).

(The dump dir is scratch — gitignored. SmolLM2 weights cache under `~/.cache/huggingface`,
not in the repo.)

## Reading order

- **docs/341** — the design note: smartphone-tier as a measurable capability
  coordinate, and the synthetic-vs-measured honesty.
- **paper §5 (`paper/sections/05_detectors.html`)** — the recall ceiling and the
  capability figure (`fig1_purchase_vs_capability.png`) this benchmark extends.
- **docs/123** — where a model runs is a trust coordinate, not a deployment detail.
- **docs/153 §5 / docs/149** — "can DOS lift a weak model?" and the measured failure
  distribution (the silent-majority ceiling).
- **`benchmark/enterpriseops/weak_model_gate.py`** — the recoverable-fraction unit
  and the enrichment guard this benchmark reuses.
