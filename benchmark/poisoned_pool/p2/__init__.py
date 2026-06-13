"""p2 — the docs/322 P2 real-weights upgrade of the poisoned-pool PoC (issue #36).

P1 (run.py / run2.py) moved the PROMPT: each arm's admitted pool conditioned
the next generation as few-shot exemplars. P2 moves the WEIGHTS: each arm's
admitted pool becomes an SFT training manifest, LoRA SFT actually updates the
parameters, and the held-out over-claim / true-success metrics are measured on
the TRAINED model — same witness subprocess, same `dos.reward.admit` gate,
byte-for-byte.

The one-boolean ablation is unchanged, lifted from the prompt layer to the
training set:

  * Arm S (self-judged): the manifest is every train trajectory that CLAIMED
    RESOLVED — over-claims (poison) included. Today's default RLVR SFT set.
  * Arm W (witness-gated): the manifest is only the trajectories `dos.reward.
    admit` ACCEPTed — witness-confirmed wins, poison zero by construction. The
    REJECT_POISON rows are the ready dispreferred DPO members.

LAYERING. This subpackage splits cleanly:

  * `manifest.py` — PURE. Pool rows -> SFT/DPO training records. No torch, no
    model, no vendor. The ablation lives here and is CPU-testable.
  * `eval.py` — PURE fold + the witness call. Turns a trained model's
    completions into the same metrics P1 reports, via the SAME harness witness
    and the SAME `dos.reward.admit`. No model loading.
  * `train.py` — the DRIVER. transformers/peft/trl, GPU, a named base model:
    the only place a vendor or accelerator is named, behind the `[p2]` extra,
    imported lazily. Nothing else imports it.
  * `run_p2.py` — the orchestration CLI: take a finished P1 run dir, build both
    arms' manifests, train both, eval both, fold + stamp the evidence.
"""
