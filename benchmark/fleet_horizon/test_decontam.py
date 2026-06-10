"""Tests for the E2 decontamination-lift experiment (docs/206 §5).

These pin the mechanism, not just a number: (1) with NO contamination the lift is
exactly 0 (the lift is caused by removing fabrications, not an artifact); (2) the
verify-filtered policy learns the TRUE landing rate while the self-report policy is
inflated; (3) the inflation concentrates in the HARD contexts; (4) the lift is
non-negative and grows with contamination correlation.
"""
from __future__ import annotations

import random

from .decontam import (
    _generate_corpus, _make_contexts, _train_imitator, run_once, sweep,
)


def test_zero_contamination_gives_zero_lift():
    """No lie to remove -> filtering changes nothing. The control that proves the
    lift is caused by removing fabricated rows, not by a base-rate side effect."""
    for c in (0.0, 0.5, 1.0):
        r = run_once(correlation=c, contam_rate=0.0, seed=1729)
        assert abs(r.lift) < 1e-9, f"c={c}: lift should be 0 with no contamination"


def test_admitted_policy_learns_truth_unfiltered_is_inflated():
    rng = random.Random(1729)
    p_real = _make_contexts(40, rng)
    corpus = _generate_corpus(p_real, n=20000, contam_rate=0.2,
                              correlation=1.0, rng=rng)
    pol_unf = _train_imitator(corpus, 40, filtered=False)
    pol_adm = _train_imitator(corpus, 40, filtered=True)
    adm_err = sum(abs(pol_adm[k] - p_real[k]) for k in range(40)) / 40
    unf_excess = sum(pol_unf[k] - p_real[k] for k in range(40)) / 40
    assert adm_err < 0.05, "verify-filtered policy should track the real landing rate"
    assert unf_excess > 0.03, "self-report policy should be inflated by the lie"


def test_inflation_concentrates_in_hard_contexts_when_correlated():
    rng = random.Random(1729)
    p_real = _make_contexts(40, rng)
    corpus = _generate_corpus(p_real, n=20000, contam_rate=0.2,
                              correlation=1.0, rng=rng)
    pol_unf = _train_imitator(corpus, 40, filtered=False)
    hard = sorted(range(40), key=lambda k: p_real[k])[:10]
    easy = sorted(range(40), key=lambda k: p_real[k])[-10:]
    excess_hard = sum(pol_unf[k] - p_real[k] for k in hard) / 10
    excess_easy = sum(pol_unf[k] - p_real[k] for k in easy) / 10
    # the lie concentrates where it's hard: the unfiltered policy over-claims most there
    assert excess_hard > excess_easy + 0.05


def test_lift_is_nonnegative_and_grows_with_correlation():
    cs = [0.0, 0.5, 1.0]
    results = sweep(cs, contam_rate=0.2, seed=1729)
    lifts = [r.lift for r in results]
    assert all(x >= -1e-9 for x in lifts), "filtering must not INCREASE over-claiming"
    assert lifts[-1] > lifts[0], "lift should grow as contamination concentrates"


def test_deterministic_from_seed():
    a = run_once(correlation=0.5, seed=42)
    b = run_once(correlation=0.5, seed=42)
    assert a.lift == b.lift
