# poisoned_pool / p2 — real weights (docs/322 P2, issue #36)

P1 moved the **prompt**: each arm's admitted pool conditioned the next
generation as few-shot exemplars. P2 moves the **weights**: each arm's admitted
pool becomes a LoRA SFT training set, the parameters actually update, and the
held-out over-claim / true-success metrics are measured on the **trained**
model — same witness subprocess, same `dos.reward.admit` gate, byte-for-byte.

The one-boolean ablation is unchanged, lifted to the training set:

| arm | SFT manifest | poison |
|---|---|---|
| **S** (self-judged) | every train trajectory that **claimed** RESOLVED | over-claims included |
| **W** (witness-gated) | only trajectories `dos.reward.admit` **ACCEPTed** | **0 by construction** |

Arm W's `REJECT_POISON` rows are ready DPO dispreferred members; the rig emits a
DPO manifest beside the SFT ones.

## Layers (the kernel's import contract, kept here too)

- `manifest.py` — **pure**. Pool rows → SFT/DPO records. The ablation lives
  here. No torch, no model, no vendor. CPU-testable.
- `eval.py` — **pure** fold + the witness call. A trained model's completions →
  P1's metrics, via the SAME `fold_batch` + `dos.reward.admit`.
- `train.py` — the **driver**. transformers/peft/trl/torch, a GPU, a named base
  model. The only place a vendor or accelerator is named; imported lazily,
  behind the GPU deps. Nothing else imports it.
- `run_p2.py` — the CLI: synthesize a deterministic P1 run, build both
  manifests, train both arms, eval both, fold + stamp `RESULTS_run3.md`.

## The CPU preflight (no GPU, what the suite pins)

Builds + audits both arms' manifests from a freshly-synthesized, deterministic
P1 run. The structural floor (S poison > 0, W poison = 0) is visible here,
before any weight moves:

```bash
python -m benchmark.poisoned_pool.p2.run_p2 --run-dir /scratch/pp_p2 --manifest-only
```

Pinned by `tests/test_poisoned_pool_p2.py` (the ablation, kernel-decided
membership, real-patch completions, the eval fold, determinism, the DPO pairs).

## The full run (needs a GPU)

```bash
# 1. install the GPU deps (match torch to the box's CUDA first)
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r benchmark/poisoned_pool/p2/requirements-gpu.txt

# 2. run both arms end to end, write the evidence beside the bench
python -m benchmark.poisoned_pool.p2.run_p2 \
    --run-dir /scratch/pp_p2 \
    --base-model Qwen/Qwen2.5-Coder-1.5B-Instruct \
    --epochs 3 --k-eval 3 --write-beside
```

Output: `RESULTS_run3.md` + `results_run3.json` (the held-out metrics for both
arms, the training-set poison audit, the per-arm train summary with the base
model + library versions + seed). The stamp line is what `dos bench status`
reads.

### Running it on a Google Cloud GPU

The synthetic P1 run and the manifest build are CPU work; only the SFT + eval
need the accelerator. A single L4 (24 GB) or A100 is ample for a 0.5–1.5 B base
model with LoRA.

```bash
# provision (an L4 is the cheapest that fits; T4-16G also works for 0.5B)
gcloud compute instances create pp-p2 \
    --zone=us-central1-a --machine-type=g2-standard-8 \
    --accelerator=type=nvidia-l4,count=1 \
    --image-family=common-cu121-debian-11 --image-project=deeplearning-platform-release \
    --maintenance-policy=TERMINATE --boot-disk-size=100GB

# on the box: clone, install, run the full command above, then copy the
# evidence back and DELETE the instance (it bills per second while up):
gcloud compute scp pp-p2:/scratch/pp_p2/RESULTS_run3.md . --zone=us-central1-a
gcloud compute scp pp-p2:/scratch/pp_p2/results_run3.json . --zone=us-central1-a
gcloud compute instances delete pp-p2 --zone=us-central1-a --quiet
```

`gcloud` must be authenticated (`gcloud auth login`) with a project that has GPU
quota in the chosen region.

## Threats to validity (also in `docs/322` §3, and the evidence file)

- **Small N** — counts ship beside rates; noise is visible.
- **GPU non-determinism** — training/sampling are not bit-reproducible across
  hardware; the base model + library versions + seed are recorded, eval is
  greedy (temperature 0).
- **No-execution rule is instruction-enforced** — a model that fabricated a
  witness could only *deflate* over-claims, symmetrically in both arms; it
  cannot manufacture the predicted S-vs-W asymmetry.
- **The structural floor holds regardless** — Arm W's training-set poison is 0
  by construction (the kernel cannot admit a refuted claim), whatever the
  held-out rates do.
