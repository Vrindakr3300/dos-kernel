# poisoned_pool — run 3: real weights (docs/322 P2, issue #36)

<!-- dos-bench-stamp: kernel=0.25.0 sha=f4c6f77 date=2026-06-12 -->

> Does training a policy's WEIGHTS on a self-judged admitted pool (Arm S) carry poison the witness-gated kernel pool (Arm W, dos.reward.admit) keeps out by construction — measured on a held-out set the pools never trained on?

## Manifest preflight (CPU — no weights moved yet)

This block is the GPU-free preflight: it builds each arm's SFT training manifest from a finished P1 run and audits the poison fraction of the TRAINING set. The full run (below, once a GPU is available) LoRA-SFTs both arms and measures the trained model on the held-out set.

| arm | manifest size | poison_n | poison_frac |
|---|---|---|---|
| S | 113 | 52 | 0.460 |
| W | 61 | 0 | 0.000 |

Arm W DPO preference pairs available: 26 (chosen = witness-confirmed, rejected = REJECT_POISON).

**The structural floor (docs/234), visible already in the manifest:** Arm S's training set carries the over-claim poison (poison_frac > 0); Arm W's is exactly 0 — the kernel cannot admit a refuted claim, so it cannot enter the manifest. Weights have not moved yet; what moves them is the manifest, and the manifests already differ in exactly the predicted way.
