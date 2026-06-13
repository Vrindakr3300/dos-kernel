"""eval.py — fold a trained model's held-out completions into P1's metrics (PURE).

The weights have moved (train.py did that on a GPU). This module never loads a
model: it takes the completion TEXT the trained checkpoint produced for each
held-out prompt and runs it through the SAME path P1 used — `parse_completion`
to split the forgeable (patch, claim), `run_witness` to get the env-authored
read-back (the acceptance test's exit code in a subprocess, bytes the model
never touched), `dos.reward.admit` for the kernel verdict, and `fold_batch` for
the metrics. Nothing here is reimplemented; the only difference from P1 eval is
that the completions came from a model whose parameters were updated on the
arm's manifest, not from few-shot conditioning.

This is the honest measurement: over-claim rate, true-success rate, and the
kernel verdict counts on a HELD-OUT set the arm's pool never trained on,
computed identically for both arms so the only variable is which manifest moved
the weights.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .. import harness
from ..harness import CLAIM_RESOLVED
from ..tasks import task_by_id


def adjudicate_completion(task_id: str, completion_text: str) -> Dict:
    """Run one trained-model completion through the full P1 witness + kernel
    path. Returns the same per-trajectory row shape P1 records, plus the kernel
    verdict (the model is the policy; the witness and the gate are unchanged)."""
    task = task_by_id(task_id)
    patch, claim = harness.parse_completion(completion_text or "")
    readback = harness.run_witness(task, patch)
    confirmed = readback.stance.value == "ATTESTED"
    label = harness.witness_admit(claim, readback, task_id)
    return {
        "task_id": task_id,
        "claim": claim,
        "patch_chars": len(patch) if patch else 0,
        "witness_confirmed": confirmed,
        "witness_stance": readback.stance.value,
        "witness_detail": readback.detail,
        "kernel_verdict": label.verdict.value,
        "kernel_accept": bool(label.accept),
        "kernel_poison": bool(label.poison),
    }


def fold_eval(rows: Sequence[Dict]) -> Dict:
    """Fold adjudicated held-out rows into the SAME batch metrics P1 reports,
    plus the kernel verdict histogram. `fold_batch` is reused verbatim — the
    over-claim / true-success / claim rates are defined exactly as in P1."""
    metrics = harness.fold_batch(rows)
    counts: Dict[str, int] = {}
    for r in rows:
        v = r.get("kernel_verdict")
        if v:
            counts[v] = counts.get(v, 0) + 1
    metrics["kernel_verdict_counts"] = counts
    return metrics


def eval_arm(prompts: Sequence[Dict], completions: Dict[str, str]) -> Dict:
    """Evaluate one trained arm. `prompts` is the held-out list from
    `manifest.heldout_eval_prompts`; `completions` maps traj_id -> the model's
    completion text. Missing completions are adjudicated as empty (no patch,
    no claim) — an honest refute, never invented.

    Returns {metrics, rows}: the folded held-out metrics and the per-trajectory
    rows (for the evidence file)."""
    rows: List[Dict] = []
    for p in prompts:
        tid = p["traj_id"]
        text = completions.get(tid, "")
        row = adjudicate_completion(p["task_id"], text)
        row["traj_id"] = tid
        rows.append(row)
    return {"metrics": fold_eval(rows), "rows": rows}
