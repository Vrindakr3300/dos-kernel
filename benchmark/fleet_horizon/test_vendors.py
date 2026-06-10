"""Multi-vendor honesty tests — proving the A/B is AGENT-AGNOSTIC.

The base suite (`test_fleet_horizon.py`) runs one `FailureModel` across the whole
fleet. These tests answer the orthogonal question a skeptic asks of every
agent-infra claim: *does this only work because the agent is Claude?* It does not.
We run fleets that are (a) heterogeneous — Claude/Gemini/Codex-flavored efforts
failing in different ways at once — and (b) homogeneously a single non-Claude
vendor, through the SAME real kernel, and pin:

  1. the honesty invariant survives heterogeneity (both arms, same ground truth);
  2. the closed loop banks zero lies no matter which mix of vendors is lying;
  3. caught lies attribute back to the exact vendor that emitted them — the kernel
     adjudicated a foreign claim and the scorer can still name the culprit;
  4. the qualitative verdict (closed loop catches exactly the open loop's debt) is
     INVARIANT to swapping the whole fleet's vendor — only the magnitudes move.

The kernel itself reads NO vendor label (it cannot — `oracle.is_shipped` /
`arbiter.arbitrate` take a claim + a footprint, never an identity); that is the
companion fact pinned kernel-side in `tests/test_vendor_agnostic_kernel.py`. Run:

    PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_vendors.py -q
"""
from __future__ import annotations

from collections import Counter

import pytest

from . import open_loop, closed_loop
from .metrics import Event
from .vendors import (
    VENDOR_ARCHETYPES, FleetProfile, round_robin_fleet, single_vendor_fleet,
)
from .workload import generate


def _effort_names(efforts: int) -> list[str]:
    return [f"effort-{e:02d}" for e in range(efforts)]


def _run_both(profile: FleetProfile, *, efforts: int, phases: int,
              seed: int = 1729, shared_ratio: float = 0.3):
    """Run BOTH arms on one workload with a shared per-effort vendor profile.

    The profile is a drop-in for a single `FailureModel` — it exposes the same
    ``worker(effort)`` method — so the arms are called UNCHANGED. Both arms get the
    SAME profile object, so ground truth is identical across the A/B (the honesty
    invariant, now under heterogeneity).
    """
    workload = generate(seed=seed, efforts=efforts, phases=phases,
                        shared_ratio=shared_ratio)
    o, o_events = open_loop.run(workload, profile, run_seed=seed)
    c, c_events = closed_loop.run(workload, profile, run_seed=seed)
    return (o, o_events), (c, c_events)


# --------------------------------------------------------------------------- #
# 1. heterogeneity does not break the honesty invariant
# --------------------------------------------------------------------------- #

def test_heterogeneous_fleet_same_real_ships():
    """The honesty invariant under a MIXED fleet: a profile map where efforts have
    different vendors (hence different lie/flake rates) still drives BOTH arms off
    the same ground truth, so real ships are identical. DOS does not hand a
    heterogeneous fleet a better agent — it hands it a kernel that disbelieves."""
    names = _effort_names(6)
    profile = round_robin_fleet(names, seed=1729)
    # sanity: the fleet really is mixed (not all one vendor)
    assert len(set(profile.vendors.values())) >= 2
    (o, _), (c, _) = _run_both(profile, efforts=6, phases=15)
    assert o.real_ships == c.real_ships, (
        f"real ships diverged across the A/B ({o.real_ships} vs {c.real_ships}) "
        "even though both arms ran the same heterogeneous profile")


def test_heterogeneous_determinism():
    """Same seed → identical metrics for a heterogeneous fleet, both arms. The
    per-effort seeding is a pure function of (seed, position), so a mixed-vendor
    run is as reproducible as a single-model one."""
    names = _effort_names(5)
    p1 = round_robin_fleet(names, seed=42)
    p2 = round_robin_fleet(names, seed=42)
    (o1, _), (c1, _) = _run_both(p1, efforts=5, phases=12, seed=42)
    (o2, _), (c2, _) = _run_both(p2, efforts=5, phases=12, seed=42)
    assert o1.to_row() == o2.to_row()
    assert c1.to_row() == c2.to_row()


# --------------------------------------------------------------------------- #
# 2. the closed loop banks no lies regardless of the vendor mix
# --------------------------------------------------------------------------- #

def test_mixed_fleet_closed_loop_banks_no_lies():
    """The centerpiece, multi-vendor: a fleet of Claude + Gemini + Codex efforts
    lying and flaking at different rates, run through the REAL kernel, banks ZERO
    falsehoods — the oracle re-checks every claim against git ground truth no
    matter which vendor made it. And the open loop banked some (else nothing to
    catch)."""
    names = _effort_names(9)   # 3 of each vendor
    profile = round_robin_fleet(names, seed=1729)
    (o, _), (c, _) = _run_both(profile, efforts=9, phases=20)
    assert c.banked_lies == 0
    assert c.lie_rate == 0.0
    assert o.banked_lies > 0, "the mixed open loop should bank some lies to catch"


@pytest.mark.parametrize("vendor", sorted(VENDOR_ARCHETYPES))
def test_single_vendor_fleet_closed_loop_clean(vendor: str):
    """Swap the WHOLE fleet to one vendor (claude, gemini, OR codex) and the closed
    loop is still clean: zero banked lies. The verdict does not depend on which
    vendor the fleet is — proof the kernel's disbelief is vendor-invariant, not
    Claude-tuned."""
    names = _effort_names(6)
    profile = single_vendor_fleet(names, vendor, seed=1729)
    (o, _), (c, _) = _run_both(profile, efforts=6, phases=20)
    assert c.banked_lies == 0, f"closed loop banked a lie for an all-{vendor} fleet"
    # the open loop's banked lies should be > 0 for vendors that lie at a rate that
    # surfaces over this horizon (all three archetypes do).
    assert o.banked_lies > 0


# --------------------------------------------------------------------------- #
# 3. caught lies attribute back to the emitting vendor
# --------------------------------------------------------------------------- #

def _by_vendor(events: list[Event], profile: FleetProfile, kind: str) -> Counter:
    """Group events of one kind by the VENDOR of the effort that emitted them.

    This is a pure projection over the returned event log — the arms tag every
    event with its `effort`, and the profile maps effort → vendor. The kernel never
    did this mapping; the scorer does, after the fact."""
    out: Counter = Counter()
    for e in events:
        if e.kind == kind:
            out[profile.vendor_of(e.effort)] += 1
    return out


def test_caught_lies_attribute_to_the_right_vendor():
    """The kernel adjudicated foreign claims; the scorer can still name the culprit.
    Every caught lie maps back (via its effort tag) to the vendor that emitted it,
    and the per-vendor counts sum to the total caught — no lie is lost or
    misattributed. This is the multi-vendor analogue of the conservation test."""
    names = _effort_names(9)
    profile = round_robin_fleet(names, seed=1729)
    (o, o_events), (c, c_events) = _run_both(profile, efforts=9, phases=25)

    caught_by_vendor = _by_vendor(c_events, profile, "caught-lie")
    banked_by_vendor = _by_vendor(o_events, profile, "banked-lie")

    # conservation, per vendor: the closed loop catches exactly the lies the open
    # loop banked, vendor by vendor (same profile, same seed → same false claims).
    assert caught_by_vendor == banked_by_vendor, (
        f"per-vendor catch != per-vendor banked\ncaught={dict(caught_by_vendor)}\n"
        f"banked={dict(banked_by_vendor)}")
    # and the per-vendor counts reconcile with the scalar metric.
    assert sum(caught_by_vendor.values()) == c.caught_lies == o.banked_lies


def test_higher_lie_rate_vendor_contributes_more_caught_lies():
    """Behavioral sanity: the over-claimer archetype (gemini, lie_rate 0.18)
    contributes MORE caught lies than the steady baseline (claude, 0.12) when each
    has the same number of efforts and phases. The kernel didn't know their rates —
    it just caught what was false — yet the attribution recovers the rate ordering.
    This proves the per-vendor signal is real, not noise.

    Aggregated over several seeds so the claim is the EXPECTED-value ordering, not a
    single-seed coincidence: with 3 efforts × 40 phases per vendor the gap is large
    in expectation (≈0.06 × 120 ≈ 7 more caught), but any one seed can be thin — the
    honest assertion is over the pooled total, which is comfortably separated."""
    gemini_total = claude_total = 0
    for seed in (1729, 42, 7, 2024):
        names = _effort_names(9)   # round-robin → 3 claude, 3 gemini, 3 codex
        profile = round_robin_fleet(names, seed=seed)
        # equal effort counts per vendor so the comparison is apples-to-apples.
        assert Counter(profile.vendors.values())["gemini"] == \
               Counter(profile.vendors.values())["claude"]
        (_, _), (c, c_events) = _run_both(profile, efforts=9, phases=40, seed=seed)
        caught = _by_vendor(c_events, profile, "caught-lie")
        gemini_total += caught["gemini"]
        claude_total += caught["claude"]
    # pooled over seeds, the higher-lie-rate vendor clearly dominates caught lies.
    assert gemini_total > claude_total, (
        f"expected the higher-lie-rate vendor to dominate caught lies over seeds: "
        f"gemini={gemini_total} claude={claude_total}")


# --------------------------------------------------------------------------- #
# 4. the qualitative verdict is invariant to the vendor
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("vendor", sorted(VENDOR_ARCHETYPES))
def test_verdict_invariant_across_vendors(vendor: str):
    """The A/B's QUALITATIVE result holds for every vendor: the closed loop catches
    exactly what the open loop banked, banks none itself, and prevents every
    overwrite. Only the magnitudes differ between an all-gemini and an all-codex
    fleet — the verdict does not. This is the 'not Claude-specific' claim, pinned
    one vendor at a time."""
    names = _effort_names(8)
    profile = single_vendor_fleet(names, vendor, seed=1729)
    (o, _), (c, _) = _run_both(profile, efforts=8, phases=20, shared_ratio=0.4)
    # closed loop: clean ledger, exception-only review, no overwrites.
    assert c.banked_lies == 0
    assert c.caught_lies == o.banked_lies          # conservation
    assert c.silent_overwrites == 0 and o.silent_overwrites > 0
    assert c.refused_writes > 0                    # the real arbiter fired
    # raw cost: the closed loop still pays for safety (no free verification).
    assert c.total_cost > o.total_cost


def test_uses_real_kernel_on_a_non_claude_fleet():
    """Smoke test that the REAL kernel adjudicated a fleet with NO Claude effort in
    it at all (all gemini): refused-writes (only the real arbiter emits them) and
    caught-lies (only the real oracle emits them) both appear. The kernel served a
    fleet it has no name for, unchanged — the CLAUDE.md 'arbitrates a foreign
    domain unchanged' litmus, at the vendor level."""
    from dos import arbiter, oracle
    assert callable(arbiter.arbitrate) and callable(oracle.is_shipped)
    names = _effort_names(8)
    profile = single_vendor_fleet(names, "gemini", seed=1729)
    assert "claude" not in set(profile.vendors.values())
    (_, _), (c, _) = _run_both(profile, efforts=8, phases=20, shared_ratio=0.4)
    assert c.caught_lies > 0     # the real oracle rejected foreign claims
    assert c.refused_writes > 0  # the real arbiter refused foreign footprints


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
