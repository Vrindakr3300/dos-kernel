"""Tests for F4 — the headline fleet payoff surface (docs/256).

The surface JOINS three live-measured results into one figure. The live profile
read is non-stationary (the corpus grows), so it is only smoke-exercised; the
COMPOSITION MATH — the rate→cascade projection that is the load-bearing docs/245
F4 step — is pure and deterministically pinned here, the same discipline as
`test_real_collisions_from_track_a` applies to the rate projection it extends.

The two invariants that keep the headline honest:
  * the fleet-of-one floor (K=1 -> 0 payoff): the docs/204 §1 falsifier;
  * F^D reproduces the docs/253 live measurement (4@D2, 8@D3) exactly: the
    cascade load is a MEASURED fact, not a tunable, so the closed form must agree.
"""
from __future__ import annotations

import math

from benchmark.fleet_horizon.fleet_payoff_surface import (
    RealCollisionProfile, build_surface, cascade_load, clobbers_prevented,
    concurrent_pairs, headline_slice, payoff, MEASURED_CASCADE,
    F2_NATURAL_CLOBBER_J,
)


def _profile(shared_ratio=0.2, clobber_fraction=0.25):
    return RealCollisionProfile(
        n_sessions=250, concurrent_pairs=1275, shared_region_pairs=245,
        clobber_pairs=56, shared_ratio_real=shared_ratio,
        clobber_fraction=clobber_fraction, kernel_specificity=1.0,
        kernel_sensitivity=1.0, as_of="2026-06-08", frozen_before=None,
    )


# --- the cascade load (F^D) ---------------------------------------------------

def test_cascade_load_is_f_to_the_d():
    assert cascade_load(0, 2) == 1      # no downstream -> the bare event
    assert cascade_load(1, 2) == 2
    assert cascade_load(2, 2) == 4
    assert cascade_load(3, 2) == 8
    assert cascade_load(4, 2) == 16
    assert cascade_load(3, 3) == 27


def test_cascade_load_chain_is_unit():
    # F=1 is a chain (no branching): F^D = 1 at every depth.
    for d in range(5):
        assert cascade_load(d, 1) == 1


def test_cascade_closed_form_matches_live_measurement():
    # the docs/253 live run measured these corrupt-leaf counts; F^D must agree
    # EXACTLY (the surface plots what F1-super-linear proved, not an assumption).
    for (depth, fanout), observed in MEASURED_CASCADE.items():
        assert cascade_load(depth, fanout) == observed


# --- the concurrent-pair count (quadratic in K, 0 at the floor) ---------------

def test_concurrent_pairs_quadratic():
    assert concurrent_pairs(1) == 0
    assert concurrent_pairs(2) == 1
    assert concurrent_pairs(4) == 6
    assert concurrent_pairs(8) == 28
    assert concurrent_pairs(32) == 496


def test_fleet_of_one_floor_no_pairs():
    assert concurrent_pairs(1) == 0
    assert concurrent_pairs(0) == 0


# --- clobbers prevented = C(K,2) * shared_ratio * clobber_fraction ------------

def test_clobbers_prevented_applies_both_rates():
    p = _profile(shared_ratio=0.2, clobber_fraction=0.25)
    # K=20 -> 190 pairs; 190 * 0.2 * 0.25 = 9.5
    assert clobbers_prevented(p, 20) == 9.5
    # the natural-rate override (F2's 4/6):
    nat = clobbers_prevented(p, 20, clobber_fraction=4 / 6)
    assert math.isclose(nat, 190 * 0.2 * (4 / 6))


def test_clobbers_prevented_zero_at_fleet_of_one():
    p = _profile()
    assert clobbers_prevented(p, 1) == 0.0


# --- the headline payoff = clobbers_prevented(K) * F^D ------------------------

def test_payoff_is_clobbers_times_cascade():
    p = _profile(shared_ratio=0.2, clobber_fraction=0.25)
    # K=8 -> 28 pairs * 0.2 * 0.25 = 1.4 clobbers; D=3,F=2 -> F^D=8 -> 11.2 leaves
    assert math.isclose(payoff(p, 8, 3, 2), 1.4 * 8)
    assert math.isclose(payoff(p, 8, 3, 2), 11.2)


def test_payoff_zero_at_fleet_of_one_every_cell():
    # the falsifier: at K=1 there is no pair, so the payoff is 0 regardless of
    # how deep/wide the cascade would have been.
    p = _profile()
    for d in range(5):
        for f in (1, 2, 3):
            assert payoff(p, 1, d, f) == 0.0


def test_payoff_super_linear_in_depth():
    # at a fixed fleet, doubling effect: each extra depth level multiplies by F.
    p = _profile()
    base = payoff(p, 16, 0, 2)
    assert base > 0
    assert math.isclose(payoff(p, 16, 1, 2), base * 2)
    assert math.isclose(payoff(p, 16, 2, 2), base * 4)
    assert math.isclose(payoff(p, 16, 3, 2), base * 8)


def test_payoff_quadratic_in_fleet():
    # at a fixed cascade cell, payoff scales with the pair count C(K,2).
    p = _profile()
    d, f = 2, 2
    assert math.isclose(payoff(p, 4, d, f) / payoff(p, 2, d, f),
                        concurrent_pairs(4) / concurrent_pairs(2))


# --- the assembled surface ----------------------------------------------------

def test_surface_carries_both_edges_and_floor():
    p = _profile(shared_ratio=0.2, clobber_fraction=0.25)
    s = build_surface(p, fleets=(1, 8), depths=(0, 3), fanouts=(2,))
    assert len(s.points) == 2 * 2 * 1
    floor = [pt for pt in s.points if pt.fleet_size == 1]
    assert all(pt.leaves_prevented_conservative == 0.0 for pt in floor)
    assert all(pt.leaves_prevented_natural == 0.0 for pt in floor)
    # the natural edge is strictly larger than the conservative edge where K>1
    grown = [pt for pt in s.points if pt.fleet_size == 8 and pt.depth == 3]
    assert grown
    for pt in grown:
        assert pt.leaves_prevented_natural > pt.leaves_prevented_conservative


def test_surface_cascade_checks_agree():
    p = _profile()
    s = build_surface(p)
    assert s.measured_cascade_checks  # non-empty
    assert all(c["agrees"] for c in s.measured_cascade_checks.values())


def test_headline_slice_selects_cell():
    p = _profile()
    s = build_surface(p, fleets=(1, 2, 4, 8), depths=(0, 1, 2, 3), fanouts=(2, 3))
    sl = headline_slice(s, depth=3, fanout=2)
    assert {pt.fleet_size for pt in sl} == {1, 2, 4, 8}
    assert all(pt.depth == 3 and pt.fanout == 2 for pt in sl)


def test_f2_natural_rate_constant():
    # the F2 live result is 4 of 6 — pin it so a typo can't silently re-weight
    # the natural edge of the band.
    assert F2_NATURAL_CLOBBER_J == (4, 6)


def test_build_surface_smoke_from_live_profile():
    # end-to-end: read the live corpus, build the surface; assert coherence only
    # (the corpus is non-stationary, so no exact-number assertions).
    from benchmark.fleet_horizon.real_collisions_from_track_a import build_profile
    p = build_profile(".", use_git=False)
    s = build_surface(p, fleets=(1, 4, 16), depths=(0, 2, 4), fanouts=(2,))
    assert len(s.points) == 9
    # monotone non-decreasing in fleet at a fixed cell (pairs grow with K)
    cell = sorted([pt for pt in s.points if pt.depth == 2],
                  key=lambda pt: pt.fleet_size)
    vals = [pt.leaves_prevented_conservative for pt in cell]
    assert vals == sorted(vals)
    assert vals[0] == 0.0  # K=1 floor
