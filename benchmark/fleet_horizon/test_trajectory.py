"""Honesty tests for the trajectory dump + the distillation experiment (docs/84).

These pin the invariants that make the trajectory a TRUSTWORTHY training signal:
the label is ground truth (not the agent's word), the dump is a faithful
projection of the scored run (not a second simulation), and the verifier's
irreducibility floor is real (a flake is shape-identical to a success, so a
claim-side model cannot learn it — the result that earns the kernel its place).

Kept deliberately SMALL (one closed-loop pass per cell — each is a real git repo
with a commit per real-ship, ~0.3s/phase) and the expensive pass is shared across
assertions via a module fixture. Run:

    PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_trajectory.py -q
"""
from __future__ import annotations

import pytest

from .agent import FailureModel
from .workload import generate
from . import closed_loop
from .trajectory import TrajectoryStep, write_jsonl, read_jsonl
from . import verifier


# One shared, small closed-loop pass — the git-subprocess cost is paid once.
@pytest.fixture(scope="module")
def steps() -> list[TrajectoryStep]:
    wl = generate(seed=1729, efforts=4, phases=10, shared_ratio=0.4)
    fm = FailureModel(seed=1729, lie_rate=0.12)
    out: list[TrajectoryStep] = []
    closed_loop.run(wl, fm, run_seed=1729, sink=out.append)
    return out


def test_one_record_per_phase(steps):
    """The dump is a faithful 1:1 projection: exactly one record per workload
    phase (admitted phases recorded at verify, deferred at drain — no double-emit,
    no drops)."""
    wl = generate(seed=1729, efforts=4, phases=10, shared_ratio=0.4)
    assert len(steps) == wl.total_phases
    # every (effort, phase) appears exactly once
    keys = [(s.effort, s.phase_id) for s in steps]
    assert len(set(keys)) == len(keys)


def test_label_is_ground_truth_not_claim(steps):
    """The whole point: the LABEL is `really_committed` (git ground truth), which
    is NOT the worker's `claimed_shipped`. They must actually DIVERGE in the data,
    else the label is just the claim relabeled (and worthless for training)."""
    # every step claims shipped (the worker always reports success in this model)
    assert all(s.claimed_shipped for s in steps)
    # but the ground-truth label is False for the lies+flakes — so label != claim
    falses = [s for s in steps if s.label == 0]
    assert falses, "expected some claimed-but-not-committed steps (the lies/flakes)"
    assert any(s.claimed_shipped and s.label == 0 for s in steps)


def test_dump_banks_no_lies(steps):
    """The closed-loop honesty invariant, visible in the dump: NO step has the
    oracle confirming a ship without a real commit behind it. (The contamination
    the open loop would carry is absent here — this is what makes it clean data.)"""
    banked_false = [s for s in steps if s.verdict_shipped and not s.really_committed]
    assert banked_false == []


def test_caught_lie_flag_matches_definition(steps):
    """`is_caught_lie` == (claimed shipped AND verdict says not shipped) — the
    per-step honesty reward signal, consistent with its definition."""
    for s in steps:
        assert s.is_caught_lie == (s.claimed_shipped and not s.verdict_shipped)


def test_provenance_rung_recorded(steps):
    """Every verdict carries its provenance rung (the calibrated-grading signal,
    docs/76 ladder). Real ships resolve via the registry; lies fall through to the
    grep rung that confirms 'no commit'. Only those two rungs appear here."""
    sources = {s.verdict_source for s in steps}
    assert sources <= {"registry", "grep", "none"}
    assert "registry" in sources  # the real ships resolved against git ground truth


def test_lineage_join_key_is_shared(steps):
    """The credit-assignment spine: every step carries the SAME root_id (one fleet
    root), so `WHERE root_id=?` reconstructs the whole fleet — and per-effort
    run_ids differ (each effort is its own child run)."""
    roots = {s.root_id for s in steps}
    assert len(roots) == 1, "all steps in one fleet run share one root_id"
    run_ids = {s.effort: s.run_id for s in steps}
    assert len(set(run_ids.values())) == 4  # 4 efforts → 4 distinct child run-ids


def test_determinism(steps):
    """Same seed → identical TRAINING SIGNAL (features + label + verdict). A
    training set that wobbles run-to-run is not a training set.

    Scoped deliberately: the run_id/root_id lineage fields are minted from the
    wall clock + a process counter (`run_id._default_entropy`) and are UNIQUE per
    run BY DESIGN — that is what a correlation spine is for. So the dataset's
    reproducibility guarantee covers everything a trainer learns from, while
    lineage stays a per-run identifier (the honest scope, docs/84 §2)."""
    wl = generate(seed=1729, efforts=4, phases=10, shared_ratio=0.4)
    fm = FailureModel(seed=1729, lie_rate=0.12)
    again: list[TrajectoryStep] = []
    closed_loop.run(wl, fm, run_seed=1729, sink=again.append)

    def _signal(s: TrajectoryStep) -> dict:
        d = s.to_dict()
        d.pop("run_id"); d.pop("root_id")   # per-run identifiers, not signal
        return d

    assert [_signal(s) for s in again] == [_signal(s) for s in steps]
    # and the lineage IS present (just not asserted equal) — sanity that we
    # dropped real fields, not typo'd names.
    assert all(s.run_id and s.root_id for s in again)


def test_jsonl_roundtrip(steps, tmp_path):
    """The dump serializes to JSONL and reads back field-for-field (the on-disk
    dataset format)."""
    p = tmp_path / "trajectory.jsonl"
    n = write_jsonl(steps, p)
    assert n == len(steps)
    back = list(read_jsonl(p))
    assert len(back) == len(steps)
    assert back[0] == steps[0].to_dict()


# --- the distillation experiment's load-bearing claim (docs/84 §3) ---

def test_pure_lies_are_learnable_but_flakes_are_not():
    """THE result: a claim-side verifier recovers pure lies (0 files written) but
    CANNOT catch flakes (files written, commit failed) — a flake is shape-identical
    to a success, so only git separates them. This is the irreducibility boundary
    that earns the kernel its place; if it ever broke, the docs/84 thesis is wrong.

    Uses the ablated feature set (no sha-prefix artifact) — the honest one.
    """
    ablated = [n for n in verifier.FEATURE_ORDER if n != verifier.ARTIFACT_FEATURE]
    # a slightly larger cell so the test set reliably contains both lies and flakes
    steps = verifier.generate_trajectory(efforts=8, phases=20, seed=1729,
                                         lie_rate=0.12, shared_ratio=0.3)
    res = verifier.score_feature_set(steps, seed=1729, feature_names=ablated)
    # there ARE flakes in the held-out set (else the claim is vacuous)
    assert res.flakes_total > 0, "expected flakes in the test set to make the point"
    # the model catches (most) pure lies from shape...
    pure_total = res.lies_total - res.flakes_total
    if pure_total > 0:
        assert res.pure_lies_caught >= 1
    # ...but cannot catch the flakes — they are shape-identical to real ships.
    assert res.flakes_caught < res.flakes_total
    # and the honest (ablated) verifier still beats base rate overall
    assert res.accuracy >= res.base_rate


def test_ablation_drops_the_simulation_artifact():
    """The `sha_looks_real` feature is a sim artifact (a forgeable prefix). With it
    the verifier looks perfect; the ablation removes it so the reported number is
    honest. Pin that the full set scores >= the ablated set (the artifact only ever
    helps), so the experiment is correctly LOSING information by ablating — i.e.
    the ablated number is the conservative one we cite."""
    steps = verifier.generate_trajectory(efforts=8, phases=20, seed=1729,
                                         lie_rate=0.12, shared_ratio=0.3)
    full = verifier.score_feature_set(steps, seed=1729)
    ablated_names = [n for n in verifier.FEATURE_ORDER if n != verifier.ARTIFACT_FEATURE]
    ablated = verifier.score_feature_set(steps, seed=1729, feature_names=ablated_names)
    assert full.auc >= ablated.auc - 1e-9


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
