"""Tests for the docs/243->244 dovetail bridge — Track A's real collision
distribution feeding the fleet-scale harness.

The profile build itself reads the live corpus + shells git, so it is exercised by
a smoke run (not asserted on exact live numbers — the corpus is non-stationary).
The PROJECTION math is pure and deterministically pinned: the fleet-size scaling is
the load-bearing docs/244 step (rate -> cascade), so its arithmetic must be exact.
"""
from __future__ import annotations

from benchmark.fleet_horizon.real_collisions_from_track_a import (
    RealCollisionProfile, project_to_fleet_size,
)


def _profile(shared_ratio, clobber_fraction):
    return RealCollisionProfile(
        n_sessions=240, concurrent_pairs=1200, shared_region_pairs=226,
        clobber_pairs=52, shared_ratio_real=shared_ratio,
        clobber_fraction=clobber_fraction, kernel_specificity=1.0,
        kernel_sensitivity=1.0, as_of="2026-06-08", frozen_before=None,
    )


def test_projection_pairs_grow_quadratically():
    p = _profile(0.2, 0.25)
    # N agents -> N*(N-1)/2 concurrent pairs
    assert project_to_fleet_size(p, 2)["concurrent_pairs"] == 1
    assert project_to_fleet_size(p, 8)["concurrent_pairs"] == 28
    assert project_to_fleet_size(p, 20)["concurrent_pairs"] == 190


def test_projection_applies_measured_ratios():
    p = _profile(0.2, 0.25)
    proj = project_to_fleet_size(p, 20)
    # 190 pairs * 0.2 shared = 38 colliding; * 0.25 clobber = 9.5
    assert proj["expected_colliding_pairs"] == 38.0
    assert proj["expected_clobber_pairs"] == 9.5


def test_fleet_of_one_has_no_collisions():
    # the four-walls §1 floor: a single agent collides with no one.
    p = _profile(0.2, 0.25)
    proj = project_to_fleet_size(p, 1)
    assert proj["concurrent_pairs"] == 0
    assert proj["expected_colliding_pairs"] == 0.0
    assert proj["expected_clobber_pairs"] == 0.0


def test_zero_ratio_zero_collisions():
    p = _profile(0.0, 0.0)
    proj = project_to_fleet_size(p, 50)
    assert proj["expected_colliding_pairs"] == 0.0


def test_build_profile_smoke():
    # the live build runs Track A end-to-end; just confirm it returns a coherent
    # profile (ratios in [0,1], counts non-negative) without asserting exact live
    # numbers (the corpus is non-stationary).
    from benchmark.fleet_horizon.real_collisions_from_track_a import build_profile
    p = build_profile(".", use_git=False)
    assert 0.0 <= p.shared_ratio_real <= 1.0
    assert 0.0 <= p.clobber_fraction <= 1.0
    assert p.concurrent_pairs >= 0
    assert p.shared_region_pairs >= p.clobber_pairs
