"""Honesty test for fold_consumer_ab — the docs/219 fold-consumer A/B.

Pins the load-bearing CLAIMS (not just arithmetic): the arm-B consumer is additive
(B deliverables >= A and B launders nothing), the arm-C re-prompt is the perturbation
harm (C <= A), the retry recovery is monotone in budget, and the recovery sampler
reproduces the MEASURED median (31s). So the numbers docs/219 §5a/§5b cite rest on a
verified mechanism, not a one-off run. Run:

    PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_fold_consumer_ab.py -q
"""
from __future__ import annotations

import random

from . import fold_consumer_ab as fca


def test_attempt_times_exponential_and_constant():
    assert fca.RetryPolicy(60.0, 3, exponential=True).attempt_times() == [60.0, 180.0, 420.0]
    assert fca.RetryPolicy(60.0, 3, exponential=False).attempt_times() == [60.0, 120.0, 180.0]
    assert fca.RetryPolicy(60.0, 0).attempt_times() == []


def test_consumer_recovers_iff_an_attempt_clears_the_window():
    pol = fca.RetryPolicy(60.0, 3, exponential=True)   # attempts at 60, 180, 420
    ok, wait = fca.consumer_recovers(30.0, pol)
    assert ok and wait == 60.0                          # first attempt clears
    ok, wait = fca.consumer_recovers(400.0, pol)
    assert ok and wait == 420.0                         # third attempt clears
    ok, _ = fca.consumer_recovers(500.0, pol)
    assert not ok                                       # account heals after the budget


def test_recovery_sampler_reproduces_measured_median():
    rng = random.Random(7)
    xs = [fca._sample_recovery_sec(rng) for _ in range(20000)]
    assert all(1.0 <= x <= 21600.0 for x in xs)         # bounded by the measured CDF
    xs.sort()
    median = xs[len(xs) // 2]
    # measured median is 31.1s; the log-interpolated sampler should land close.
    assert 24.0 <= median <= 40.0, median


def test_recovery_sweep_is_monotone_in_budget():
    rows = fca.recovery_sweep(random.Random(1), n=5000, backoffs=[60.0], ks=[1, 3, 5])
    fracs = [r["recovered_frac"] for r in rows]          # same backoff, rising K
    assert fracs == sorted(fracs)                        # more retries never recovers less


def test_arm_B_is_additive_and_launders_nothing_arm_C_harms():
    """The docs/219 structural claims — hold for ANY seed, by construction."""
    for seed in (0, 1, 219, 4242):
        rng = random.Random(seed)
        pol = fca.RetryPolicy(60.0, 5)
        r = fca.run_ab(rng, units=4000, death_rate=0.318, neg_rate=0.15,
                       policy=pol, perturb_p=0.5)
        h = r["headline"]
        # B is ADDITIVE: it never yields fewer deliverables than A (it only recovers).
        assert h["arm_B_deliverables"] >= h["arm_A_deliverables"]
        # B launders ZERO deaths as findings (it counts them in the denominator).
        assert h["B_laundered_findings"] == 0
        # A launders every death; B never exceeds the achievable ceiling.
        assert h["A_laundered_findings"] == r["deaths"]
        assert h["arm_B_deliverables"] <= r["achievable_deliverable_ceiling"]
        # C is the perturbation HARM: it drops at or below A (never above).
        assert h["arm_C_deliverables"] <= h["arm_A_deliverables"]
