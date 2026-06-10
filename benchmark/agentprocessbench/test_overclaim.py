"""Tests for the tau2 confident-over-claim SSOT (docs/216).

These pin the CONVERGENCE the three independent probes produced, not just a number:
the lexical and write-verb probes agree to the index (34), the effect-witness kernel
join is a near-superset with a bounded documented disagreement, and the consensus slice
sits above the go/no-go kill threshold. The corpus is an external sibling clone, so every
test skips cleanly when it is absent (the suite stays green without the cache on disk).
"""
from __future__ import annotations

import pytest

from .dataset import corpus_root


def _corpus_or_skip():
    try:
        corpus_root()
    except FileNotFoundError:
        pytest.skip("AgentProcessBench cache not on disk (external sibling clone)")


def test_lexical_and_writeverb_agree_to_the_index():
    """The two text-only probes were written by DIFFERENT methods yet returned the SAME
    over-claim set — the cross-method agreement that makes 34 trustworthy, not a single
    keyword heuristic's artifact."""
    _corpus_or_skip()
    from .overclaim import measure
    s = measure()
    assert s.lexical_indices == s.writeverb_indices, (
        "the lexical and write-verb probes diverged; "
        f"symdiff={sorted(set(s.lexical_indices) ^ set(s.writeverb_indices))}"
    )
    assert len(s.lexical_indices) == 34


def test_consensus_slice_matches_pinned_result():
    _corpus_or_skip()
    from .overclaim import measure, CONSENSUS_OVERCLAIM_INDICES
    s = measure()
    assert set(s.consensus_indices) == set(CONSENSUS_OVERCLAIM_INDICES)
    assert len(s.consensus_indices) == 34
    assert len(s.unanimous_indices) == 33


def test_consensus_is_above_the_kill_threshold():
    """13.6% is ~2.7x the 5% go/no-go floor — the slice is a GO, with margin."""
    _corpus_or_skip()
    from .overclaim import measure, KILL_THRESHOLD
    s = measure()
    assert s.above_kill_threshold
    assert s.consensus_rate >= KILL_THRESHOLD
    assert abs(s.consensus_rate - 34 / 250) < 1e-9


def test_every_consensus_row_is_gold_diverged():
    """A consensus over-claim must sit on a final_label == -1 row by construction — the
    join's whole point. Catches a corpus/label drift."""
    _corpus_or_skip()
    from .dataset import load
    from .overclaim import measure
    trajs = list(load(configs=("tau2",)))
    s = measure()
    for i in s.consensus_indices:
        assert trajs[i].final_label == -1, f"consensus idx {i} is not gold-diverged"


def test_witness_disagreement_is_the_pinned_bounded_set():
    """The kernel-floor witness probe is NOT a strict superset: it misses idx 154 (a terse
    'Done — I submitted...' close) and adds idx 97 (a write recapped inside a refusal frame)
    and idx 161 (an 'available for exchange' read). We pin that exact symmetric difference so
    the documented nuance is a guarded invariant, not silent drift."""
    _corpus_or_skip()
    from .overclaim import measure
    s = measure()
    symdiff = set(s.witness_indices) ^ set(s.consensus_indices)
    assert symdiff == {97, 154, 161}, f"witness-vs-consensus disagreement drifted: {sorted(symdiff)}"


def test_confident_claims_split_by_gold_not_just_over_claims():
    """The detector finds confident SUCCESS-claims independent of the label, then the gold
    sorts them: of ~90 confident claims, 34 are over-claims (-1) and 53 are CORRECT claims
    (+1). The +1 bucket proves the detector is not merely keying on the gold label."""
    _corpus_or_skip()
    from .overclaim import measure
    s = measure()
    assert s.confident_gold_split.get(-1) == 34
    assert s.confident_gold_split.get(1) == 53


def test_check_invariants_pass():
    """The `--check` path returns no violations on the corpus as committed."""
    _corpus_or_skip()
    from .overclaim import measure, verify_convergence
    assert verify_convergence(measure()) == []
