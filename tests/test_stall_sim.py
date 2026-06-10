"""Regression tests for the stall-reader simulator (docs/145, benchmark/enterpriseops/stall_sim.py).

The sim proves `dos.tool_stream.classify_stream` recovers *stuck* episodes without failing on
*legitimate polling*, with the delta EMERGING from a generative stuck/advance/poll dynamic — never
hardcoded. These tests pin the emergence (the honesty property: the bump must vanish when there is
nothing to recover) and the false-resurface accounting (the §3 hole made measurable), so a future
edit cannot silently turn the sim into a rigged constant.

This is the loop-economics analogue of test coverage over `simulator.py` (the arg_provenance sim).
"""
from __future__ import annotations

from benchmark.enterpriseops.stall_sim import StallParams, run_split


def _delta(p: StallParams, n: int = 400, seeds=(1, 2, 3)) -> float:
    r0c = r1c = r0n = r1n = 0
    for s in seeds:
        r0, r1 = run_split(s, n, p)
        r0c += r0.completed; r0n += r0.n
        r1c += r1.completed; r1n += r1.n
    return 100.0 * r1c / r1n - 100.0 * r0c / r0n


def test_delta_is_zero_with_no_stuck_episodes():
    """The load-bearing honesty check: a model that never loops gets NO gain (the bump is not a
    hardcoded constant — it is the recovered-stuck dynamic). The tool_stream analogue of
    arg_provenance vanishing on a non-minting model — here on the LOOPING axis."""
    assert _delta(StallParams(p_stuck=0.0)) == 0.0


def test_delta_is_zero_when_resurface_is_ignored():
    """q_unstick=0 — the agent ignores every re-surface → no recovery → 0 delta. The bump is a
    function of the modeled second chance, never a free lunch."""
    assert _delta(StallParams(q_unstick=0.0)) == 0.0


def test_delta_is_positive_and_monotone_in_stuck_rate():
    """More stuck episodes → more to recover → bigger delta (a real, emergent gain)."""
    d_low = _delta(StallParams(p_stuck=0.10))
    d_high = _delta(StallParams(p_stuck=0.30))
    assert d_low > 0.0
    assert d_high > d_low


def test_feasible_advancing_episodes_never_fire():
    """An all-advancing population (no stuck, no polling) → the reader fires on nothing and the
    delta is exactly 0 — the false-fire-on-a-healthy-run exposure is zero by construction."""
    p = StallParams(p_stuck=0.0, p_poll=0.0)
    _r0, r1 = run_split(1, 400, p)
    assert r1.fired == 0
    assert r1.fired_polling == 0


def test_pollers_caught_mid_wait_count_as_false_resurface():
    """A polling population IS caught mid-wait (the incremental fold, not the final-stream fold)
    → counted as false-resurface; this is the §3 honest hole, and it must be VISIBLE (non-zero)
    so the ignore_tools knob has something to remove."""
    p = StallParams(p_stuck=0.0, p_poll=1.0, ignore_pollers=False)
    _r0, r1 = run_split(1, 300, p)
    assert r1.fired_polling > 0


def test_ignore_pollers_drops_false_resurface_to_zero_without_changing_recovery():
    """The calibration story, pinned: exempting the pollers drops false-resurfaces to 0 while the
    stuck-recovery (and thus the completion delta) is UNCHANGED — exempting noise costs nothing."""
    base = StallParams(ignore_pollers=False)
    exempt = StallParams(ignore_pollers=True)
    _r0a, r1a = run_split(7, 500, base)
    _r0b, r1b = run_split(7, 500, exempt)
    assert r1a.fired_polling > 0
    assert r1b.fired_polling == 0
    # recovery (the real gain) is identical — the poller exemption only removes harmless noise
    assert r1a.recovered == r1b.recovered
    assert _delta(base) == _delta(exempt)
