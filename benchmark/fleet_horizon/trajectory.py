"""Per-step trajectory records — the closed loop as a ground-truth-label factory.

The A/B harness collapses each run into scalar `Metrics`. That throws away the
one thing the closed loop is uniquely positioned to emit: a per-step record that
keeps the worker's CLAIM *apart from* the kernel's adjudication *apart from* the
ground truth. That separation is the supervision signal agent-training data is
starved for (`docs/84`):

  * outcome-labeled data carries one reward per trajectory and bakes in grader
    over-optimism (METR ~24pp, PAE 27-78% procedurally-corrupt "successes");
  * self-narrated data IS the agent's own trace — training on it trains the
    narration, which is the failure mode METR measured.

A `TrajectoryStep` is neither. It is the tuple almost nothing else has:

    (claim-side features) → (ground-truth label) ⟂ (kernel verdict + provenance)

where the LABEL is `really_committed` (did a real commit land — checkable by hand
with `git log` in the bench's temp repo), the FEATURES are only what a believer
could see (what the worker SAID + what it wrote), and the VERDICT/PROVENANCE are
how the kernel adjudicated it (`oracle.is_shipped().source`: registry/grep/none).
The label is NOT the agent's word and NOT a human's after-the-fact guess.

Why the split is load-bearing (the `docs/84` falsifier):
  The experiment `verifier.py` runs is "predict the label from the FEATURES
  ALONE." If a cheap model can, the kernel's verdicts are *distillable* into an
  inference-time check. If it cannot (lies are shape-identical to truth without
  git), the referee is *irreducible* — you must keep the kernel in the loop. The
  feature/label/verdict columns are kept rigidly apart here precisely so that
  question is answerable and not begged.

This module is pure data + a sink. `closed_loop.run(..., sink=...)` calls the
sink at each adjudication; nothing here drives the loop, so the trajectory is a
faithful projection of the SAME run the A/B scores, not a second simulation.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Iterable, Iterator

from .agent import Claim


@dataclasses.dataclass(frozen=True)
class TrajectoryStep:
    """One adjudicated step: features ⟂ label ⟂ verdict, kept deliberately apart.

    The field groups are commented because the WHOLE point is which side of the
    epistemic line each lives on — a trainer that mixes them re-creates the
    self-report contamination this record exists to avoid.
    """

    # --- identity / spine (lineage, for credit assignment — docs/84 §4) ---
    step: int                # position in the interleaved fleet timeline
    effort: str              # which effort (== plan key the oracle verifies)
    phase_id: str            # the (plan, phase) key, e.g. "E03.07"
    run_id: str              # this effort's run-id (carries root_id lineage)
    root_id: str             # the fleet root — `WHERE root_id=?` joins the tree

    # --- FEATURES: only what a BELIEVER could observe (claim-side) ---
    # These are the model's inputs in the distillation experiment. Crucially they
    # do NOT include really_committed / real_sha / the verdict — that would leak
    # the label. A plain orchestrator sees exactly this much and no more.
    claimed_shipped: bool    # the worker's self-report
    claimed_sha: str         # the sha it reported (may be fabricated)
    n_files_written: int     # how many files it claims to have touched
    touches_shared: bool     # did its footprint reach shared state
    is_rework: bool          # was this phase already shipped (redundant work)
    sha_looks_real: bool     # surface tell ONLY (prefix) — see note in to_features

    # --- LABEL: ground truth (checkable by hand in the temp git repo) ---
    really_committed: bool   # THE label: did a real commit actually land?
    real_sha: str            # the real sha if it committed, else ""

    # --- KERNEL VERDICT + PROVENANCE (the adjudication; the teacher signal) ---
    verdict_shipped: bool    # oracle.is_shipped().shipped
    verdict_source: str      # provenance rung: "registry" | "grep" | "none"
    is_caught_lie: bool      # claimed shipped, verdict says no → a caught lie
    arbiter_outcome: str     # "acquire" | "refuse" (the write-collision decision)
    refusal_reason: str      # the closed-vocabulary reason if refused, else ""
    # docs/86 §3 — the typed-verdict surface's NEW columns: dimensions the fleet
    # already SIMULATES but the trajectory previously banked silently. Both are
    # verdict-side (the teacher signal), NOT features — they are deliberately
    # absent from `to_features()` so they cannot leak into the distillation X.
    # The distillation experiment can now ask a SEPARATE irreducibility question
    # per column (predict scope-violation? spin?), not just `really_committed`.
    verdict_in_scope: str = ""   # scope.classify: IN_SCOPE | SCOPE_CREEP | WRONG_TARGET
    verdict_advancing: str = ""  # liveness.classify: ADVANCING | SPINNING | STALLED

    def to_features(self) -> dict[str, float]:
        """The claim-side feature vector for the distillation experiment.

        ONLY believer-observable signal — no label leakage. `sha_looks_real` is a
        deliberately weak surface tell (the sim uses a 'fake'/'real' prefix); a
        real fleet wouldn't hand you that, so the experiment also reports the
        verifier's score WITHOUT it (`verifier.py` ablates it) to avoid claiming a
        win that rests on a simulation artifact.
        """
        return {
            "claimed_shipped": float(self.claimed_shipped),
            "n_files_written": float(self.n_files_written),
            "touches_shared": float(self.touches_shared),
            "is_rework": float(self.is_rework),
            "sha_looks_real": float(self.sha_looks_real),
            "bias": 1.0,
        }

    @property
    def label(self) -> int:
        """The supervised target: 1 iff a real commit actually landed."""
        return int(self.really_committed)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def step_from_claim(
    *,
    step: int,
    claim: Claim,
    run_id: str,
    root_id: str,
    verdict_shipped: bool,
    verdict_source: str,
    arbiter_outcome: str,
    refusal_reason: str = "",
    verdict_in_scope: str = "",
    verdict_advancing: str = "",
) -> TrajectoryStep:
    """Build a step from the closed loop's own values at the adjudication point.

    Called by `closed_loop.run`'s sink — so every field is the SAME value the A/B
    scored, never a re-derivation. `sha_looks_real` keys off the sim's sha prefix
    convention (`real…` vs `fake…`); it is the only feature that peeks at the sha
    string shape, and the verifier ablates it.
    """
    claimed = claim.claimed_sha or ""
    return TrajectoryStep(
        step=step,
        effort=claim.phase.effort,
        phase_id=claim.phase.phase_id,
        run_id=run_id,
        root_id=root_id,
        claimed_shipped=claim.claimed_shipped,
        claimed_sha=claimed,
        n_files_written=len(claim.wrote_files),
        touches_shared=any(f.startswith("shared/") for f in claim.wrote_files),
        is_rework=claim.is_rework,
        sha_looks_real=claimed.startswith("real"),
        really_committed=claim.really_committed,
        real_sha=claim.real_sha,
        verdict_shipped=verdict_shipped,
        verdict_source=verdict_source,
        is_caught_lie=bool(claim.claimed_shipped and not verdict_shipped),
        arbiter_outcome=arbiter_outcome,
        refusal_reason=refusal_reason,
        verdict_in_scope=verdict_in_scope,
        verdict_advancing=verdict_advancing,
    )


def write_jsonl(steps: Iterable[TrajectoryStep], path: Path) -> int:
    """Write the trajectory as JSONL (one record per line). Returns the count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for s in steps:
            f.write(json.dumps(s.to_dict(), sort_keys=True) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> Iterator[dict]:
    """Read a trajectory JSONL back (records as dicts, in file order)."""
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
