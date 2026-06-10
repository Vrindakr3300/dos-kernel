"""Pin the load-bearing invariants of the give-up-correctly arm (docs/201).

These are the facts the doc + the SHIP decision rest on, measured over the full natural A/B
corpus (240 runs/arm). If the corpus is absent the data-dependent tests skip; the soundness-
direction test (RLCW refuses-MORE than plain) is pure and always runs.

    python -m pytest test_giveup_arm.py -q
"""
from __future__ import annotations

import os

import pytest

import giveup_arm as G

_HERE = os.path.dirname(os.path.abspath(__file__))
_AB = os.path.join(_HERE, "live_results_natural_ab")
_HAVE_CORPUS = os.path.isdir(os.path.join(_AB, "none")) and os.path.isdir(os.path.join(_AB, "rewind_natural"))
needs_corpus = pytest.mark.skipif(not _HAVE_CORPUS, reason="natural A/B corpus not present")


def _walled():
    witness = G.feasibility_witness(os.path.join(_AB, "*", "results_*.json"))
    return {t for t, ok, er in witness if er >= 5 and ok == 0}


# --- pure: the gate is run-local (no corpus state in the fire decision) --------------------

def test_first_fire_is_run_local_and_forward_only():
    # a tool that errors twice then recovers STILL fires (forward-only view: a live gate cannot
    # see the future recovery) -- this is the deployable arm's defining property.
    err = {"tool_name": "x", "result": {"isError": True, "content": "Invalid Tool Arguments: ['a: is required']"}}
    ok = {"tool_name": "x", "result": {"ok": True}}
    trs = [err, err, ok]
    idx, tool = G._first_fire(trs, 2)
    assert (idx, tool) == (1, "x")  # fires AT the 2nd error, before the recovery


def test_first_fire_needs_latest_to_be_error_at_threshold():
    err = {"tool_name": "x", "result": {"isError": True, "content": "Invalid Tool Arguments: ['a: is required']"}}
    ok = {"tool_name": "x", "result": {"ok": True}}
    # one error then a success: never reaches K=2 errors -> no fire
    assert G._first_fire([err, ok], 2) == (None, None)


# --- corpus: the verified full-A/B invariants the SHIP decision rests on -------------------

@needs_corpus
def test_no_winner_thrashes_so_giveup_is_structurally_safe_on_none():
    # docs/201 §1: no task-winner on the none arm reaches even 2 struct-errors on a single tool.
    scores, _ = G.score_arm(os.path.join(_AB, "none", "results_*.json"), [2, 3, 4, 5], _walled())
    for k in (2, 3, 4, 5):
        assert scores[k]["false_halt"] == 0, f"none arm K={k} should never halt a winner"
        assert scores[k]["fired"] > 0


@needs_corpus
def test_k2_is_unsound_but_k3plus_is_sound_cross_arm():
    # docs/201 §2: the plain run-local gate false-halts 1 winner on the pooled corpus at K=2
    # (a curable arg-provenance recovery) but is SOUND on BOTH arms at K>=3.
    walled = _walled()
    pooled = {k: 0 for k in (2, 3, 4, 5)}
    for arm in G.ARMS:
        scores, _ = G.score_arm(os.path.join(_AB, arm, "results_*.json"), [2, 3, 4, 5], walled)
        for k in (2, 3, 4, 5):
            pooled[k] += scores[k]["false_halt"]
    assert pooled[2] == 1, "K=2 should false-halt exactly 1 winner on the pooled corpus"
    assert pooled[3] == 0 and pooled[4] == 0 and pooled[5] == 0, "K>=3 must be cross-arm sound"


@needs_corpus
def test_rlcw_refuses_more_than_plain_never_admits_a_winner_halt():
    # docs/201 §2: RLCW (run-local AND corpus-WALLED) is sound at EVERY K on both arms -- it
    # only ever fires on create_filter (0 winners by construction), so rlcw_fh is always 0 and
    # rlcw_fired <= fired (refuses MORE, never more-aggressively than the plain gate admits).
    walled = _walled()
    for arm in G.ARMS:
        scores, _ = G.score_arm(os.path.join(_AB, arm, "results_*.json"), [2, 3, 4, 5], walled)
        for k in (2, 3, 4, 5):
            assert scores[k]["rlcw_fh"] == 0, f"{arm} K={k}: RLCW must never halt a winner"
            assert scores[k]["rlcw_fired"] <= scores[k]["fired"], "RLCW fires a subset of plain"


@needs_corpus
def test_walled_set_is_create_filter_only_at_display_floor():
    # docs/201 §2: create_filter is the only tool clearing the min_err>=5 WALLED display floor.
    assert _walled() == {"create_filter"}


@needs_corpus
def test_real_token_telemetry_exists_and_beats_the_char4_proxy():
    # docs/201 §4: the corpus DOES carry real usage_metadata (the "char/4 is the only proxy"
    # premise was wrong); the real-token total dwarfs the char/4 result-payload proxy.
    scores, _ = G.score_arm(os.path.join(_AB, "none", "results_*.json"), [3], _walled())
    s = scores[3]
    assert s["real_total"] > 0, "real usage_metadata must be present"
    assert s["real_total"] > s["proxy_total"] * 5, "real total should dwarf the char/4 proxy"
    assert s["real_saved"] > 0


@needs_corpus
def test_pre_registered_kill_passes_at_k3():
    # docs/194 §5 kill: FA-rate<0.10 AND saved>0. On the deployable none-arm plain gate at K=3.
    scores, _ = G.score_arm(os.path.join(_AB, "none", "results_*.json"), [3], _walled())
    s = scores[3]
    assert s["fa_rate"] < 0.10 and s["real_saved"] > 0, "give-up arm must pass its kill at K=3"
