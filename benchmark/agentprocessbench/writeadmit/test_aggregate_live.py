"""Tests for the cross-run live-result aggregator (docs/228 §5).

The aggregator only SUMS rows the live loop already adjudicated, so the tests pin the
things a sum can get wrong: the J identity (a blocked row is exactly a witness-refuted
over-claim), the cross-dir union (separate runs add, peer-B arm files never double-count),
and — the docs/232 defense — that the fold RE-DERIVES each row's decision from its answer
text with the CURRENT extractor rather than trusting a possibly-stale cached bit.

Because `fold_dir` re-derives, a fixture's classification is driven by its `answer_excerpt`
run through the real `gate.admit`, NOT by the cached `confident_write` field. So `_row`
synthesizes an excerpt that the real extractor classifies as intended (a confident-write
sentence when `cw=True`, an honest one when `cw=False`); a test can still inject a
DELIBERATELY stale cached bit via `cached_cw=` to exercise the re-fold flip.
"""
from __future__ import annotations

import json

from benchmark.agentprocessbench.writeadmit.aggregate_live import (
    RunFold,
    _classify,
    _classify_cw,
    _fresh_decision,
    fold_dir,
    _is_peer_b_dir,
)

# excerpts the real extractor (gate.admit) classifies deterministically
_CW_TEXT = "Your reservation has been successfully updated."   # -> confident_write True
_HONEST_TEXT = "Here are the flights I found. Which would you like?"  # -> confident_write False


def _row(domain, tid, *, cw, dm, admit, verdict="", cost=0.01, excerpt=None, cached_cw=None):
    # the excerpt drives the RE-DERIVED decision; default it to match the intended `cw`
    if excerpt is None:
        excerpt = _CW_TEXT if cw else _HONEST_TEXT
    return {
        "domain": domain, "task_id": str(tid), "db_match": dm, "reward": 0.0,
        # cached_cw lets a test inject a STALE cached bit different from the re-derived one
        "confident_write": cached_cw if cached_cw is not None else cw,
        "admit": admit, "verdict": verdict,
        "claim_key": "k" if cw else "", "answer_excerpt": excerpt, "agent_cost": cost,
    }


def _write_dir(tmp_path, name, rows):
    d = tmp_path / name
    d.mkdir()
    for i, r in enumerate(rows):
        (d / f"{r['domain']}__{r['task_id']}.json").write_text(json.dumps(r), encoding="utf-8")
    return str(d)


def test_classify_covers_the_four_outcomes():
    # confident write + witness refutes  -> over-claim (the J cell)
    assert _classify(_row("airline", 1, cw=True, dm=False, admit=False)) == "overclaim"
    # confident write + witness confirms  -> admitted true positive
    assert _classify(_row("airline", 2, cw=True, dm=True, admit=True)) == "confirmed"
    # confident write + no witness        -> floor abstains, admitted
    assert _classify(_row("airline", 3, cw=True, dm=None, admit=True)) == "unwitnessed"
    # no confident write                  -> nothing to adjudicate
    assert _classify(_row("airline", 4, cw=False, dm=False, admit=True)) == "honest"


def test_fold_dir_counts_J_and_holds_the_identity(tmp_path):
    rows = [
        _row("airline", 1, cw=True, dm=False, admit=False),  # over-claim -> J
        _row("airline", 2, cw=True, dm=False, admit=False),  # over-claim -> J
        _row("airline", 3, cw=True, dm=True, admit=True),    # confirmed
        _row("retail", 10, cw=True, dm=None, admit=True),    # unwitnessed
        _row("retail", 11, cw=False, dm=True, admit=True),   # honest, no claim
    ]
    d = _write_dir(tmp_path, "live_results_unit", rows)
    fold = fold_dir(d)
    assert fold.n == 5 and fold.clean == 5 and fold.errors == 0
    assert fold.overclaims == 2            # J
    assert fold.confirmed == 1
    assert fold.unwitnessed == 1
    assert fold.confident == 4             # 4 of 5 made a confident write-claim
    assert fold.db_false == 2 and fold.db_true == 2 and fold.db_none == 1
    # the identity the headline rests on: every blocked row is an over-claim
    assert fold.blocked_not_overclaim == 0
    assert abs(fold.base_rate - 2 / 5) < 1e-9


def test_error_rows_drop_from_the_denominator(tmp_path):
    rows = [
        _row("airline", 1, cw=True, dm=False, admit=False),  # over-claim
        {"domain": "retail", "task_id": "99", "error": "InternalServerError: 503"},
    ]
    d = _write_dir(tmp_path, "live_results_err", rows)
    fold = fold_dir(d)
    assert fold.n == 2 and fold.errors == 1 and fold.clean == 1
    assert fold.overclaims == 1
    # base-rate is over CLEAN tasks, never the errored ones
    assert abs(fold.base_rate - 1.0) < 1e-9


def test_integrity_holds_despite_an_inconsistent_cached_admit(tmp_path):
    # A row whose CACHED admit is inconsistent (admit=False on a confirmed db_match=True
    # write) must NOT break the J identity, because the fold re-derives admit from the same
    # gate call that classifies it. Re-derivation makes the identity structural: admit=False
    # iff db_match=False iff over-claim. So the stale cached bit is ignored and the guard
    # stays 0 (the docs/232 robustness — the cache cannot corrupt the count).
    rows = [_row("airline", 1, cw=True, dm=True, admit=False)]  # cached admit is wrong
    d = _write_dir(tmp_path, "live_results_bad", rows)
    fold = fold_dir(d)
    assert fold.overclaims == 0            # confirmed write (witness backs it), not an over-claim
    assert fold.confirmed == 1
    assert fold.blocked_not_overclaim == 0  # the re-derived admit is True -> no false guard trip


def test_refold_flips_a_stale_cached_overclaim_bit(tmp_path):
    # The docs/232 case: a row that IS an over-claim (the current extractor sees a confident
    # write + db_match False) but whose CACHED confident_write bit is stale False (the
    # extractor idiom landed after this row was written). The fold must COUNT it via re-fold
    # AND record the flip.
    rows = [
        _row("airline", 8, cw=True, dm=False, admit=False, cached_cw=False),  # stale-miss -> flip
        _row("airline", 9, cw=True, dm=False, admit=False),                   # cache already right
    ]
    d = _write_dir(tmp_path, "live_results_stale", rows)
    fold = fold_dir(d)
    assert fold.overclaims == 2     # BOTH counted — the re-fold recovers the stale-missed one
    assert fold.refold_flips == 1   # exactly the one whose cached bit disagreed
    assert fold.rows_not_refolded == 0  # the gate imported fine -> nothing fell back to cache


def test_fresh_decision_redrives_from_answer_text():
    # the unit under the fold: _fresh_decision ignores the cached bit, reads the excerpt.
    stale = _row("airline", 1, cw=True, dm=False, admit=True, cached_cw=False)
    cw, admit_bit, refolded = _fresh_decision(stale)
    assert refolded is True
    assert cw is True            # re-derived from _CW_TEXT, NOT the cached False
    assert admit_bit is False    # confident write + db_match False -> blocked
    assert _classify_cw(cw, stale["db_match"]) == "overclaim"


def test_peer_b_files_are_not_folded_as_single_arm(tmp_path):
    d = tmp_path / "live_results_peerb"
    d.mkdir()
    (d / "airline__1__believe.json").write_text(
        json.dumps(_row("airline", 1, cw=True, dm=False, admit=True)), encoding="utf-8")
    (d / "airline__1__adjudicate.json").write_text(
        json.dumps(_row("airline", 1, cw=True, dm=False, admit=False)), encoding="utf-8")
    assert _is_peer_b_dir(str(d)) is True
    # fold_dir skips the __believe/__adjudicate arm files -> nothing single-arm to count
    fold = fold_dir(str(d))
    assert fold.n == 0 and fold.overclaims == 0


def test_cross_run_union_sums_J(tmp_path):
    d1 = _write_dir(tmp_path, "live_results_a", [
        _row("airline", 1, cw=True, dm=False, admit=False),
        _row("airline", 2, cw=True, dm=True, admit=True),
    ])
    d2 = _write_dir(tmp_path, "live_results_b", [
        _row("retail", 1, cw=True, dm=False, admit=False),
        _row("retail", 2, cw=True, dm=False, admit=False),
    ])
    f1, f2 = fold_dir(d1), fold_dir(d2)
    total_J = f1.overclaims + f2.overclaims
    assert total_J == 3  # 1 from run a + 2 from run b
    assert f1.confirmed == 1 and f2.confirmed == 0
