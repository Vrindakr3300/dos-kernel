"""manifest.py — turn an arm's admitted pool into a training manifest (PURE).

This is the docs/322 P2 spine and the home of the one-boolean ablation at
training scale. It imports NO model, NO torch, NO vendor — only the P1 harness
(for the prompt template and the kernel-not-reimplemented admission gate) and
the task corpus. Every function here is a deterministic fold over the rows the
P1 run already adjudicated; it is fully CPU-testable.

THE ABLATION, restated as a manifest selection rule (the only thing that
differs between the two arms):

  * Arm S (self-judged): SFT on every TRAIN trajectory whose CLAIM is RESOLVED.
    Over-claims — claimed RESOLVED, witness refuted — are INCLUDED. This is the
    poison the self-judged loop trains on; it is today's default RLVR set, not
    a strawman.
  * Arm W (witness-gated): SFT only on trajectories `dos.reward.admit` ACCEPTed
    — claim RESOLVED AND witness ATTESTED. Poison is zero BY CONSTRUCTION
    (`believe_under_floor` cannot admit a refuted claim). The harness never
    re-decides; the kernel verdict on each row is the membership test.

We rebuild the verdict from the row's recorded (claim, witness_confirmed)
rather than trusting a stored `armW_admit` bit — the kernel call is the
membership rule, so the manifest carries the same kernel-not-reimplemented
discipline P1's gate does. A row from a P1 run holds everything we need; we do
not re-run the witness (the exit code is fossilised in `witness_confirmed`).

SFT TARGET. The training example is (prompt, completion) where the prompt is
the EXACT P1 zero-exemplar render of the task (the format the witness expects)
and the completion is the admitted patch plus its CLAIM line — the same two
forgeable bytes a policy authors. Training on the admitted set teaches the
model to reproduce those patches+claims; whether that raises or bounds the
held-out over-claim rate is what the eval measures.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from dos import reward

from .. import harness
from ..harness import CLAIM_RESOLVED, CLAIM_NOT_RESOLVED
from ..tasks import task_by_id, heldout_tasks

# A completion loader maps a trajectory id to the EXACT bytes the policy emitted
# (the fenced patch + CLAIM line). P1 results.json rows record only patch_chars
# (a length), not the patch text — so the SFT target's patch must come from the
# run directory's completion files, the real emitted bytes. The orchestrator
# wires `run_dir_loader`; tests can pass a dict-backed one.
CompletionLoader = Callable[[str], Optional[str]]


# ---------------------------------------------------------------------------
# Records — the on-disk training manifest shapes (JSON-serialisable dataclasses).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SFTRecord:
    """One supervised example: imitate this admitted (patch + claim) for this
    prompt. `poison` is recorded for measurement (the witness refuted it) — the
    trainer never reads it; it is the pool-poison audit the evidence reports."""
    traj_id: str
    task_id: str
    prompt: str
    completion: str
    poison: bool

    def to_json(self) -> Dict:
        return asdict(self)


@dataclass(frozen=True)
class DPORecord:
    """One preference pair for Arm W: the witness-confirmed completion is
    `chosen`, an over-claim on the same task is `rejected`. The REJECT_POISON
    rows P1 already counts are the ready dispreferred members."""
    task_id: str
    prompt: str
    chosen: str
    rejected: str

    def to_json(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# The membership rule — the kernel verdict, not a reimplemented bit.
# ---------------------------------------------------------------------------

def _verdict(row: Dict) -> reward.RewardLabel:
    """Recompute `dos.reward.admit` from the row's fossilised (claim, witness)
    — the same call P1's gate made, so Arm W membership is kernel-decided here
    too. The witness read-back is reconstructed from `witness_confirmed`
    (the OS exit code P1 recorded); we attest/refute at the same rung."""
    claim = row.get("claim")
    confirmed = bool(row.get("witness_confirmed"))
    readback = _readback_from_row(row)
    return harness.witness_admit(claim, readback, row["task_id"])


def _readback_from_row(row: Dict):
    """Rebuild the EvidenceFacts the witness produced, from the fossil. The
    stance is the only thing the kernel reads; detail is carried for audit."""
    from dos.evidence import EvidenceFacts
    from dos.log_source import Accountability
    subject = row["task_id"]
    detail = row.get("witness_detail") or ""
    if row.get("witness_confirmed"):
        return EvidenceFacts.attest(
            harness.WITNESS_SOURCE, Accountability.OS_RECORDED,
            subject=subject, detail=detail or "acceptance test exit 0")
    return EvidenceFacts.refute(
        harness.WITNESS_SOURCE, Accountability.OS_RECORDED,
        subject=subject, detail=detail or "acceptance test refuted")


def _completion_body(row: Dict, loader: CompletionLoader) -> str:
    """The SFT/DPO completion target for a row: the EXACT bytes the policy
    emitted for this trajectory (a fenced patch + the CLAIM line), re-rendered
    through the canonical (parse -> patch + claim -> render) round-trip so the
    target matches the shape the witness reads and the eval produces. The patch
    text comes from the run directory's completion file — never from the row
    (which records only patch_chars). A missing completion yields an empty
    patch + the row's recorded claim (honest, not invented)."""
    raw = loader(row["traj_id"])
    if raw is not None:
        patch, claim = harness.parse_completion(raw)
    else:
        patch, claim = None, row.get("claim")
    patch = patch or ""
    if patch and not patch.endswith("\n"):
        patch += "\n"
    claim = claim or row.get("claim") or CLAIM_NOT_RESOLVED
    return f"```python\n{patch}```\nCLAIM: {claim}\n"


# ---------------------------------------------------------------------------
# Completion loaders — the real emitted bytes the manifest's patch comes from.
# ---------------------------------------------------------------------------

def run_dir_loader(run_dir: Path) -> CompletionLoader:
    """A loader backed by a P1 run directory's completion files. The files are
    `completions/gen<g>/<traj_id>.md`; the trajectory id encodes its generation
    so we can find its file. Returns None for an id with no file (missing
    completion)."""
    run_dir = Path(run_dir)

    def _load(traj_id: str) -> Optional[str]:
        tid = harness.TrajId.parse(traj_id)
        path = run_dir / "completions" / f"gen{tid.gen}" / f"{traj_id}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    return _load


def dict_loader(by_id: Dict[str, str]) -> CompletionLoader:
    """A loader backed by an in-memory {traj_id: completion_text} map — for
    tests and for callers that already hold the emitted bytes."""
    return lambda traj_id: by_id.get(traj_id)


# ---------------------------------------------------------------------------
# SFT manifest builders — the ablation.
# ---------------------------------------------------------------------------

def _train_rows(rows: Sequence[Dict]) -> List[Dict]:
    """Train-split rows only; eval rows are measured, never trained on."""
    return [r for r in rows if r.get("kind") == "train"]


def _zero_shot_prompt(task_id: str) -> str:
    """The EXACT P1 render of a task with an empty exemplar block — the prompt
    format the witness was built against. SFT trains the policy to answer this
    canonical prompt, so the eval (same render) is in-distribution."""
    return harness.render_prompt(task_by_id(task_id), [])


def build_sft_manifest(rows: Sequence[Dict], arm: str,
                       loader: CompletionLoader) -> List[SFTRecord]:
    """The arm's SFT training set — the one-boolean ablation.

    Arm S: every train row that CLAIMED RESOLVED (poison included).
    Arm W: every train row `dos.reward.admit` ACCEPTed (poison zero by
           construction — the kernel cannot admit a refuted claim).

    `loader` supplies the real emitted completion bytes per trajectory (the
    patch text the row does not carry)."""
    if arm not in ("S", "W"):
        raise ValueError(f"arm must be 'S' or 'W', got {arm!r}")
    out: List[SFTRecord] = []
    for r in _train_rows(rows):
        claim = r.get("claim")
        if arm == "S":
            admit = claim == CLAIM_RESOLVED
        else:  # W — the kernel verdict decides
            admit = _verdict(r).accept
        if not admit:
            continue
        poison = not bool(r.get("witness_confirmed"))
        out.append(SFTRecord(
            traj_id=r["traj_id"], task_id=r["task_id"],
            prompt=_zero_shot_prompt(r["task_id"]),
            completion=_completion_body(r, loader), poison=poison))
    return out


def build_dpo_manifest(rows: Sequence[Dict],
                       loader: CompletionLoader) -> List[DPORecord]:
    """Arm W's preference pairs: pair each witness-confirmed win (chosen) with
    a REJECT_POISON over-claim on the SAME task (rejected). The dispreferred
    member is the kernel's REJECT_POISON row — already labelled, not invented.

    A task with no available poison row yields no pair (we never fabricate a
    rejected member). Deterministic: rows are paired in recorded order."""
    train = _train_rows(rows)
    chosen_by_task: Dict[str, List[Dict]] = {}
    poison_by_task: Dict[str, List[Dict]] = {}
    for r in train:
        label = _verdict(r)
        if label.accept:
            chosen_by_task.setdefault(r["task_id"], []).append(r)
        elif label.poison:
            poison_by_task.setdefault(r["task_id"], []).append(r)
    out: List[DPORecord] = []
    for task_id, chosens in chosen_by_task.items():
        poisons = poison_by_task.get(task_id, [])
        for chosen, rejected in zip(chosens, poisons):
            out.append(DPORecord(
                task_id=task_id, prompt=_zero_shot_prompt(task_id),
                chosen=_completion_body(chosen, loader),
                rejected=_completion_body(rejected, loader)))
    return out


# ---------------------------------------------------------------------------
# Manifest audit — the poison fraction of each arm's TRAINING set, the
# structural docs/234 floor the evidence reports (S>0, W=0 by construction).
# ---------------------------------------------------------------------------

def manifest_poison(records: Sequence[SFTRecord]) -> Dict:
    n = len(records)
    poison = sum(1 for r in records if r.poison)
    return {
        "size": n,
        "poison_n": poison,
        "poison_frac": poison / n if n else 0.0,
    }


# ---------------------------------------------------------------------------
# The held-out eval prompts — the SAME tasks P1 measures, the SAME render. The
# trained model answers these (no execution); the witness re-reads each.
# ---------------------------------------------------------------------------

def heldout_eval_prompts(k_eval: int = 1) -> List[Dict]:
    """Return [{traj_id, task_id, prompt}] for the held-out set, k_eval samples
    per task. traj_id mirrors the P1 grammar so the fold + verdict path is
    shared verbatim."""
    out: List[Dict] = []
    for t in heldout_tasks():
        for k in range(k_eval):
            tid = f"p2.eval.{t.task_id}.{k}"
            out.append({"traj_id": tid, "task_id": t.task_id,
                        "prompt": harness.render_prompt(t, [])})
    return out
