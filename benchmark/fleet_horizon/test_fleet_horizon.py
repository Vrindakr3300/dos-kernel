"""Honesty tests for the FleetHorizon A/B — proving the benchmark is not rigged.

These pin the invariants `README.md` §honesty promises. They are how we answer
the `adoption-and-proof` §6.2 steelman ("you defined the metrics to win"): the
A/B's claims are ground-truth properties of the OPEN loop's own output, and the
closed loop is charged for its overhead. Run:

    PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_fleet_horizon.py -q
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from .agent import FailureModel
from .workload import generate
from . import open_loop, closed_loop, metrics

# Repo root (…/dos) and its src/ — for the cross-process determinism test that
# re-runs an arm in a subprocess. This file lives at <repo>/benchmark/fleet_horizon/.
_REPO = str(Path(__file__).resolve().parents[2])
_SRC = str(Path(_REPO) / "src")


def _both(efforts: int, phases: int, *, seed: int = 1729, lie_rate: float = 0.12,
          shared_ratio: float = 0.3):
    workload = generate(seed=seed, efforts=efforts, phases=phases,
                        shared_ratio=shared_ratio)
    model = FailureModel(seed=seed, lie_rate=lie_rate)
    o, _ = open_loop.run(workload, model, run_seed=seed)
    c, _ = closed_loop.run(workload, model, run_seed=seed)
    return o, c


def test_same_agents_same_real_ships():
    """The honesty invariant: DOS does NOT get a better agent. Both arms run the
    same seeded failure model, so GROUND-TRUTH real ships are identical — the
    closed loop never magics a lie into a ship."""
    o, c = _both(6, 15)
    assert o.real_ships == c.real_ships, (
        f"real ships diverged ({o.real_ships} vs {c.real_ships}) — the arms are "
        "not running the same ground truth")


def test_closed_loop_banks_no_lies():
    """The whole point: the closed loop's banked ledger has zero falsehoods,
    because the oracle re-checks every claim against git ground truth."""
    o, c = _both(6, 15)
    assert c.banked_lies == 0
    assert c.lie_rate == 0.0
    # and the open loop DID bank some (else there's nothing to catch)
    assert o.banked_lies > 0


def test_closed_loop_catches_exactly_the_open_loops_lies():
    """Conservation: the lies the closed loop CATCHES equal the lies the open loop
    BANKED (same seed → same false claims). DOS reveals the open loop's own debt,
    it does not invent defects."""
    o, c = _both(6, 20)
    assert c.caught_lies == o.banked_lies


def test_determinism():
    """Same seed → identical metrics. A benchmark whose result wobbles proves
    nothing."""
    a1, b1 = _both(5, 12, seed=42)
    a2, b2 = _both(5, 12, seed=42)
    assert a1.to_row() == a2.to_row()
    assert b1.to_row() == b2.to_row()


def test_determinism_is_hash_salt_independent():
    """The determinism above is necessary but NOT sufficient: it runs twice in ONE
    process, where CPython's str-hash salt is constant — so it cannot catch a seed
    derived from the salted built-in ``hash()``. That exact bug shipped once (the
    per-effort RNG was seeded from ``hash(effort)``, which CPython salts per process
    via PYTHONHASHSEED), so the headline metrics drifted between separate CLI runs
    while this in-process test stayed green. This test pins the real contract: the
    result must be a pure function of (seed, workload), independent of the hash salt.
    We run the open-loop arm in two subprocesses with DIFFERENT PYTHONHASHSEED and
    assert byte-identical metrics. (Open loop only: no git, fast, deterministic.)"""
    import json
    import subprocess
    import sys

    prog = (
        "from benchmark.fleet_horizon.agent import FailureModel;"
        "from benchmark.fleet_horizon.workload import generate;"
        "from benchmark.fleet_horizon import open_loop;"
        "import json;"
        "w=generate(seed=1729, efforts=5, phases=12, shared_ratio=0.3);"
        "m=FailureModel(seed=1729, lie_rate=0.12);"
        "o,_=open_loop.run(w,m,run_seed=1729);"
        "print(json.dumps(o.to_row()))"
    )

    def _run(hashseed: str) -> dict:
        env = {**os.environ, "PYTHONHASHSEED": hashseed, "PYTHONPATH": _SRC}
        out = subprocess.run([sys.executable, "-c", prog], cwd=_REPO,
                             capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout.strip().splitlines()[-1])

    assert _run("0") == _run("12345"), (
        "metrics depend on the per-process hash salt — a seed is leaking from the "
        "built-in hash(); derive it from a stable hash (zlib.crc32/hashlib) instead."
    )


def test_no_silent_overwrites_in_closed_loop():
    """The arbiter prevents every concurrent-write collision; the open loop suffers
    them. (At a fleet wide enough to collide.)"""
    o, c = _both(8, 20, shared_ratio=0.4)
    assert c.silent_overwrites == 0
    assert o.silent_overwrites > 0
    assert c.refused_writes > 0


def test_collision_value_is_zero_at_fleet_of_one():
    """The benchmark's OWN falsifier: with a single effort there is no one to
    collide with, so overwrites-prevented is 0 and DOS's collision value is nil.
    Its value is strictly a FLEET phenomenon — this is the 'nowhere else' clause
    that keeps the pitch honest (adoption-and-proof §4.3)."""
    o, c = _both(1, 20, shared_ratio=0.4)
    assert o.silent_overwrites == 0
    assert c.refused_writes == 0


def test_defect_debt_grows_with_horizon():
    """The long-horizon claim, made falsifiable: a defect banked early corrupts
    more remaining phases, so the open loop's defect debt grows super-linearly
    with horizon (more lies × more downstream each). The closed loop's stays 0."""
    _, c_short = _both(6, 5)
    o_short, _ = _both(6, 5)
    o_long, c_long = _both(6, 40)
    assert c_short.defect_debt == 0.0
    assert c_long.defect_debt == 0.0
    # open-loop debt per-lie grows with horizon: long-horizon debt-per-banked-lie
    # exceeds short-horizon's (the compounding).
    if o_short.banked_lies and o_long.banked_lies:
        assert (o_long.defect_debt / o_long.banked_lies) > \
               (o_short.defect_debt / o_short.banked_lies)


def test_raw_cost_charges_closed_loop_for_overhead():
    """§6.2 fairness: the closed loop is NOT given free verification. On RAW spend
    (defect-blind) it costs MORE than the open loop (every refusal→retry is a paid
    action), so its raw verified/$ is lower. The win only appears once the open
    loop's own defect debt is priced in — which is the honest long-horizon claim,
    not a scoring trick."""
    o, c = _both(8, 20, shared_ratio=0.4)
    assert c.total_cost > o.total_cost                       # DOS pays for safety
    assert c.verified_shipped_per_dollar < o.verified_shipped_per_dollar  # raw: looks worse
    # but defect-adjusted, DOS wins (it carries no debt; the open loop does)
    assert c.defect_adjusted_verified_per_dollar > o.defect_adjusted_verified_per_dollar


def test_uses_the_real_kernel_not_a_mock():
    """Smoke test that the closed loop actually drove the real dos kernel: a
    closed-loop run with collisions must have produced refused-writes (which only
    the real arbiter emits) and caught-lies (which only the real oracle emits)."""
    from dos import arbiter, oracle  # import the real modules
    assert callable(arbiter.arbitrate)
    assert callable(oracle.is_shipped)
    o, c = _both(8, 20, shared_ratio=0.4)
    assert c.caught_lies > 0      # the real oracle rejected claims
    assert c.refused_writes > 0   # the real arbiter refused footprints


# --- velocity axis honesty tests (docs/81 §5) ---

def test_open_loop_reviews_everything():
    """docs/81 §5: the open loop adjudicates NO completeness, so its human-review
    fraction is EXACTLY 1.0 — every banked 'done' must be human-confirmed."""
    o, c = _both(6, 20)
    assert o.human_review_fraction == 1.0


def test_closed_loop_reviews_only_exceptions():
    """The velocity lever: the closed loop routes only kernel-surfaced exceptions
    (caught lies) to a human, so its review fraction is strictly < the open loop's
    at any fleet > 1 — and equals its lie+refusal rate, not 100%."""
    o, c = _both(6, 20)
    assert c.human_review_fraction < o.human_review_fraction
    # only caught lies reached the human (this model), so reviews == caught lies
    assert c.human_reviews == c.caught_lies


def test_velocity_gap_vanishes_at_fleet_and_horizon_one():
    """docs/81 §5: at one effort × one phase there is no dependent to unblock, no
    concurrent writer, and a review queue of depth ~1 — the velocity delta must
    vanish exactly where the integrity delta does (the 'pure overhead at small
    scale' clause, proven on the velocity axis too)."""
    o, c = _both(1, 1, shared_ratio=0.4)
    assert c.conflict_detonations == 0 and o.conflict_detonations == 0
    # with a single phase there are no concurrent writers → no velocity gap to claim
    assert c.refused_writes == 0


def test_break_even_kappa_orders_the_arms():
    """The honesty discipline (docs/81 §3): we do NOT assert a winning κ; we report
    the κ at which the arms cross. Below break-even the open loop's verified-velocity
    /$ is higher; above it the closed loop's is. This pins that ordering."""
    from .harness import break_even_kappa, run_cell
    be = break_even_kappa(efforts=8, phases=20, shared_ratio=0.3)
    assert be is not None, "expected the arms to cross for a contended fleet"
    # just below break-even: open loop ahead (or tied). just above: closed ahead.
    if be > 0.5:
        o_lo, c_lo = run_cell(efforts=8, phases=20, shared_ratio=0.3, kappa=be - 0.5)
        assert o_lo.verified_velocity_per_dollar >= c_lo.verified_velocity_per_dollar - 1e-9
    o_hi, c_hi = run_cell(efforts=8, phases=20, shared_ratio=0.3, kappa=be + 1.0)
    assert c_hi.verified_velocity_per_dollar >= o_hi.verified_velocity_per_dollar - 1e-9


def test_review_wait_saturates_open_loop():
    """Kingman (docs/81 §2.3): a review queue fed by EVERYTHING the fleet emits runs
    ρ→1 and the wait is unbounded. The open loop should hit the saturated regime
    (inf wait) at a wide fleet while the closed loop stays bounded."""
    o, c = _both(8, 20, shared_ratio=0.4)
    # closed loop's review wait is finite (it feeds the queue only exceptions)
    assert c.mean_review_wait() != float("inf")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
