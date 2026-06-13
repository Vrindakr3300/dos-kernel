"""Pins for the keep-gate ablation (docs/318 P1–P2).

Run by path — `benchmark/` is outside the suite's `testpaths`:

    python -m pytest benchmark/improve_ablation -q
"""
from __future__ import annotations

import json

from benchmark.improve_ablation import baits, run_ablation, task


def _small_run(seed: int = 0):
    return run_ablation.run(master=seed, cycles=8, gate_k=3, plot_seeds=4, fresh_seeds=6)


def _bait_run(seed: int = 0):
    # A longer run so each bait class is sampled enough times to pin the
    # channel-routing structurally (the #35 surface needs witness-tamper keeps).
    return run_ablation.run(master=seed, cycles=50, gate_k=5, plot_seeds=4, fresh_seeds=6)


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


# --------------------------------------------------------------------------
# docs/318 P2 — the bait taxonomy (the #35 surface).
# --------------------------------------------------------------------------
def test_bait_scoreboard_schema_and_tally_invariant():
    # Every arm carries a scoreboard over the closed bait vocabulary, and for
    # every class kept + refused == taken (a bait taken was either carried or
    # rejected — there is no third outcome).
    res = _bait_run()
    for arm in res["arms"].values():
        board = arm["bait_scoreboard"]
        assert set(board) == set(baits.BAIT_CLASSES)
        for counts in board.values():
            assert counts["kept"] + counts["refused"] == counts["taken"]
            assert counts["flattered_kept"] <= counts["kept"]


def test_baits_are_faced_identically_per_cycle_across_arms():
    # The bait stream is shared: on any cycle BOTH arms reach, they face the
    # SAME hack, so the scoreboard isolates the keep RULE, never luck. (An arm
    # that ESCALATEs early simply faces fewer baits — its 'taken' is a prefix,
    # not a different draw — so we compare per-cycle on the cycles both ran.)
    res = _bait_run()
    by_cycle = {
        arm: {r["cycle"]: r["bait"] for r in res["arms"][arm]["rows"]} for arm in ("A", "B", "C")
    }
    shared = set(by_cycle["A"]) & set(by_cycle["B"]) & set(by_cycle["C"])
    assert shared  # the arms overlap on at least the pre-escalation cycles
    for cycle in shared:
        assert by_cycle["A"][cycle] == by_cycle["B"][cycle] == by_cycle["C"][cycle], cycle


def test_claim_channel_bait_mints_no_keep_on_the_gated_arm():
    # The structural litmus: a claim-channel bait (the readable val split) rides
    # the forgeable channel the gate refuses to read, so it can NEVER fake a
    # keep on the gated arms. Its witness-flattered-keep count is zero for arms
    # A and C by construction (the gate reads the witness, which the leak never
    # touches) — across a small seed sweep so this is not a one-seed accident.
    for seed in range(4):
        res = _bait_run(seed)
        for arm in ("A", "C"):
            board = res["arms"][arm]["bait_scoreboard"][baits.READABLE_VAL_SPLIT]
            assert board["flattered_kept"] == 0, (seed, arm, board)


def test_self_certified_arm_keeps_the_claim_channel_leak():
    # The other half of the claim-channel ablation: arm B grades its own
    # homework, so the readable val split (which makes its self-claim look true)
    # IS kept by B. Summed over a small sweep so the count is robust.
    kept_B = sum(
        _bait_run(s)["arms"]["B"]["bait_scoreboard"][baits.READABLE_VAL_SPLIT]["kept"]
        for s in range(4)
    )
    assert kept_B > 0


def test_witness_tamper_is_the_35_hole_kept_by_the_gated_arm():
    # The #35 surface, made countable: the editable-eval-script tamper corrupts
    # the referee's OWN measure — the bytes even the gated arm trusts — so arm A
    # KEEPS it, and every such keep is a faked-metric keep (flattered). Summed
    # over a small sweep so the hole is demonstrated, not one-seed luck.
    flattered_A = sum(
        _bait_run(s)["arms"]["A"]["bait_scoreboard"][baits.EDITABLE_EVAL_SCRIPT]["flattered_kept"]
        for s in range(4)
    )
    assert flattered_A > 0, "the editable-eval-script tamper must fool the gated arm (the #35 hole)"


def test_headline_carries_the_bait_aggregates():
    res = _bait_run()
    h = res["headline"]
    assert set(h["hacks_kept"]) == {"A", "B", "C"}
    assert set(h["witness_tampers_kept"]) == {"A", "B", "C"}
    # The gated arm's #35-hole count equals the editable-eval-script flattered
    # keeps plus any persistent-cache flattered keeps — a witness-only sum that
    # never counts the claim-channel bait.
    a = res["arms"]["A"]["bait_scoreboard"]
    expected = sum(
        a[k]["flattered_kept"] for k in baits.BAIT_CLASSES if baits.BAIT_CHANNEL[k] == "witness"
    )
    assert h["witness_tampers_kept"]["A"] == expected


def test_render_md_carries_the_bait_scoreboard():
    res = _bait_run()
    res["sweep"] = run_ablation.sweep([0, 1], cycles=50, gate_k=5)
    md = run_ablation.render_md(res)
    assert "bait scoreboard" in md
    assert "#35" in md
    for label in ("readable val split", "persistent cache", "editable eval script"):
        assert label in md
    assert "faked the metric" in md


def test_persistent_cache_is_keyed_by_order_and_keeps_best():
    # The cache bait's mechanism, pinned directly: a stale lower entry for the
    # same order is reported (and flagged flattered); a higher honest measure
    # for an unseen order is reported faithfully.
    cache = baits.new_cache()
    nll0, flat0 = cache.lookup_or_record(order=3, honest_nll=2.0)
    assert (nll0, flat0) == (2.0, False)  # first sight of order 3 — faithful
    nll1, flat1 = cache.lookup_or_record(order=3, honest_nll=2.5)
    assert nll1 == 2.0 and flat1 is True  # stale best under-reports the honest 2.5
    nll2, flat2 = cache.lookup_or_record(order=4, honest_nll=1.0)
    assert (nll2, flat2) == (1.0, False)  # different order — no stale entry
