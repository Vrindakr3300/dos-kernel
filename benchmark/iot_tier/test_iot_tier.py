"""Deterministic tests for the iot_tier sweep.

The load-bearing self-test (mirrors weak_model_gate's gemini self-test): the FRONTIER tier,
calibrated to the gemini shape, must reproduce the published null — recoverable < 15%, MINT
excluded as noise, DANGLE+LOOP signal. Plus: the corpus is byte-faithful (each failure shape
makes the intended detector fire and the unreachable shapes fire NONE), the curve is non-monotone
(rises then collapses), and generation is deterministic.
"""

from __future__ import annotations

from dos.dangling_intent import StopEvidence, classify_stop
from dos.tool_stream import StreamState, classify_stream

from benchmark.enterpriseops.weak_model_gate import (
    THRESHOLD, gate_fraction, _fires_mint, _fires_loop, _fires_dangle,
)
from benchmark.enterpriseops.replay_stall import stream_of
from benchmark.iot_tier import synth
from benchmark.iot_tier.tiers import LADDER, by_name, FAILURE_SHAPES
from benchmark.iot_tier import harness


# --------------------------------------------------------------------------- corpus byte-fidelity
def test_mint_run_fires_only_mint():
    r = synth._mint_run(__import__("random").Random(1))
    assert _fires_mint(r, synth.TASK_TEXT) is True
    assert _fires_loop(r) is False
    assert _fires_dangle(r) is False


def test_loop_run_fires_only_loop():
    r = synth._loop_run(__import__("random").Random(1))
    assert classify_stream(stream_of(r)).state is not StreamState.ADVANCING
    assert _fires_loop(r) is True
    assert _fires_mint(r, synth.TASK_TEXT) is False
    assert _fires_dangle(r) is False


def test_narrating_stop_run_fires_only_dangle():
    r = synth._narrating_stop_run(__import__("random").Random(1))
    assert classify_stop(StopEvidence(final_turn_text=r["model_response"])).is_dangling is True
    assert _fires_dangle(r) is True
    assert _fires_loop(r) is False
    assert _fires_mint(r, synth.TASK_TEXT) is False


def test_unreachable_shapes_fire_nothing():
    for shape in ("silent_stop", "planning"):
        r = synth._silent_or_planning_run(__import__("random").Random(1), shape)
        assert _fires_mint(r, synth.TASK_TEXT) is False, shape
        assert _fires_loop(r) is False, shape
        assert _fires_dangle(r) is False, shape


def test_clean_pass_fires_nothing_by_default():
    # zero incidental rate => a clean pass fires no detector
    r = synth._pass_run(__import__("random").Random(1), {})
    assert _fires_mint(r, synth.TASK_TEXT) is False
    assert _fires_loop(r) is False
    assert _fires_dangle(r) is False


# ---------------------------------------------------------------- the frontier null self-test
def test_frontier_reproduces_the_gemini_null():
    """Calibrated to the gemini shape, the frontier tier must land < 15% (the docs/153 §5 null)."""
    corpus = synth.generate_corpus(by_name("frontier"), n_runs=600, seed=1729)
    res = gate_fraction(corpus["runs"], synth.TASK_TEXT, model="frontier")
    assert res.frac < THRESHOLD, f"frontier {res.frac:.0%} should be < {THRESHOLD:.0%} (the null)"


def test_frontier_excludes_mint_as_noise():
    """The enrichment filter must mark MINT as NOISE on the frontier (it fires >= on passes)."""
    corpus = synth.generate_corpus(by_name("frontier"), n_runs=600, seed=1729)
    res = gate_fraction(corpus["runs"], synth.TASK_TEXT, model="frontier")
    assert res.enriched["mint"] is False, "MINT must be excluded as noise on the frontier tier"
    # DANGLE is the one naturally-firing signal axis (docs/153 §5)
    assert res.enriched["dangle"] is True, "DANGLE must be SIGNAL on the frontier tier"


# ------------------------------------------------------------------------ the curve + falsifier
def test_curve_is_non_monotone_rises_then_collapses():
    rows = harness.run_sweep(n_runs=400, seed=1729)
    fracs = {r["tier"]: r["recoverable_frac"] for r in rows}
    # rises off the frontier to a middle peak...
    assert fracs["mid"] > fracs["frontier"], "the middle tier should peak above the frontier null"
    # ...then collapses at the IoT end, back below the peak
    assert fracs["iot"] < fracs["mid"], "the IoT tier should collapse below the peak"


def test_falsifier_holds_on_the_calibrated_ladder():
    rows = harness.run_sweep(n_runs=400, seed=1729)
    assert harness.check_falsifier(rows) == [], "the docs/153 prediction must hold on the ladder"


def test_declared_unreachable_share_climbs_from_peak_to_iot():
    """The DECLARED share DOS owns 0% of (silent-stop + planning) must climb from the peak (mid)
    tier to the IoT end — the docs/153 §1 collapse mechanism: as the model weakens past the
    middle, the can-do-when-nudged decay migrates recoverable narration INTO silent-stops.

    The full ladder's unreachable share is U-shaped, NOT monotone: the frontier (gemini) is
    ALREADY ~86% unreachable (docs/153 §5 — its failures are mostly silent), the MIDDLE tier is
    the trough (most failures recoverable => the peak), then it climbs again toward IoT. So the
    honest, true invariant is the right arm of the U: mid -> small -> iot is monotone up. (The
    post-enrichment unreachable RATE is the inverse of the recoverable fraction and dips at the
    peak by construction — asserting monotonicity on it across ALL tiers is the trap.)
    """
    right_arm = [by_name(n).fail_mix["silent_stop"] + by_name(n).fail_mix["planning"]
                 for n in ("mid", "small", "iot")]
    assert right_arm == sorted(right_arm), \
        f"declared unreachable share must climb mid->small->iot, got {right_arm}"


def test_main_exit_zero_when_prediction_holds():
    assert harness.main(["--runs", "400", "--seed", "1729"]) == 0


# ---------------------------------------------------------------------------------- determinism
def test_generation_is_deterministic():
    a = synth.generate_corpus(by_name("mid"), n_runs=200, seed=42)
    b = synth.generate_corpus(by_name("mid"), n_runs=200, seed=42)
    assert a == b


def test_every_tier_fail_mix_sums_to_one():
    for t in LADDER:
        s = sum(t.fail_mix.get(k, 0.0) for k in FAILURE_SHAPES)
        assert abs(s - 1.0) < 1e-6, f"{t.name}: {s}"
