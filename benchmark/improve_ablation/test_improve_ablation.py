"""Pins for the keep-gate ablation (docs/318 P1).

Run by path — `benchmark/` is outside the suite's `testpaths`:

    python -m pytest benchmark/improve_ablation -q
"""
from __future__ import annotations

import json

from benchmark.improve_ablation import run_ablation, task


def _small_run(seed: int = 0):
    return run_ablation.run(master=seed, cycles=8, gate_k=3, plot_seeds=4, fresh_seeds=6)


def test_deterministic_from_the_one_seed():
    a = json.dumps(_small_run(), sort_keys=True)
    b = json.dumps(_small_run(), sort_keys=True)
    assert a == b


def test_arm_a_keeps_only_witnessed_gains():
    # The structural litmus from docs/318: every arm-A keep has referee work
    # STRICTLY above the carried baseline — the keep-bit reads zero
    # loop-authored bytes, so no claim can move it.
    res = _small_run()
    for row in res["arms"]["A"]["rows"]:
        if row["kept"]:
            assert row["gate_work"] > row["baseline_work_before"]


def test_self_grading_optimism_gradient_exists():
    # The trap arm B walks into is real, not contrived: an over-capacity
    # recipe looks BETTER in-sample and WORSE held-out than a modest one.
    corpus = task.make_corpus(99)
    modest = task.Recipe(order=2, add_k=0.5)
    bloated = task.Recipe(order=7, add_k=0.001)
    seeds = [11, 22, 33]
    in_modest = sum(task.in_sample_nll(corpus, modest, s) for s in seeds)
    in_bloated = sum(task.in_sample_nll(corpus, bloated, s) for s in seeds)
    out_modest = sum(task.heldout_nll(corpus, modest, s) for s in seeds)
    out_bloated = sum(task.heldout_nll(corpus, bloated, s) for s in seeds)
    assert in_bloated < in_modest, "capacity must flatter the in-sample estimate"
    assert out_bloated > out_modest, "and hurt the held-out witness"


def test_result_schema_carries_the_deltas():
    res = _small_run()
    assert set(res["arms"]) == {"A", "B", "C"}
    h = res["headline"]
    assert "witnessed_gain_gap_A_minus_B_mbits" in h
    for arm in res["arms"].values():
        assert len(arm["curve_witnessed_mbits"]) == res["cycles"]
        assert isinstance(arm["overclaims_kept"], int)


def test_render_md_mentions_the_repro_command():
    res = _small_run()
    md = run_ablation.render_md(res)
    assert "run_ablation --seed 0" in md
    assert "ratchet curve" in md
