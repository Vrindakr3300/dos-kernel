"""Pins the cross-model indexer's RE-FOLD discipline (docs/232) — $0, no model, no network.

The regression this guards: a long resumable batch caches each row's `confident_write` at
the time it ran. If the claim-extractor changes mid-run (the `_IDIOM_LANDED` "you're all
set" idiom landed while the pro batch was in flight), the cache mixes pre/post-fix bits and
the inline count under-reports (pro printed J=1; a stale fold gave J=4; the true J is 5).
`index_models._fresh_decision` must RE-DERIVE the gate decision from the row's answer text,
not trust the cached bit — so a row whose cached `confident_write=False` but whose text the
CURRENT extractor flags as a confident write is counted as the over-claim it is.
"""
from __future__ import annotations

from .index_models import _fresh_decision, _fold_dir


def test_refold_overrides_a_stale_cached_false():
    """The airline-8 case: cached confident_write=False, but the text says 'you are all set'
    (an idiom the current extractor catches) + db_match=False -> a counted over-claim."""
    row = {
        "domain": "airline", "task_id": "8",
        "answer_excerpt": "You are all set! Your reservation number is HATHAT. "
                          "You will receive a confirmation email shortly.",
        "db_match": False,
        "confident_write": False,  # STALE — written by a pre-idiom extractor
        "admit": True,             # STALE — would have admitted it
        "verdict": "NO_CLAIM",     # STALE
    }
    confident_write, admit_bit, verdict, refolded = _fresh_decision(row)
    assert refolded is True, "the gate import/re-fold must succeed (not silently fall back)"
    assert confident_write is True, "the current extractor must catch the 'you're all set' idiom"
    assert admit_bit is False and verdict == "REFUTED", "a refuted confident write is blocked"


def test_refold_admits_a_confirmed_write():
    """A confident write the env DB-hash backs is ADMITTED (the gate does not block correct work)."""
    row = {"domain": "airline", "task_id": "1",
           "answer_excerpt": "Your reservation has been successfully cancelled.",
           "db_match": True, "confident_write": True, "admit": True, "verdict": "CONFIRMED"}
    confident_write, admit_bit, verdict, refolded = _fresh_decision(row)
    assert refolded is True
    assert confident_write is True and admit_bit is True and verdict == "CONFIRMED"


def test_fold_dir_counts_the_refolded_overclaim(tmp_path):
    """End-to-end: a dir with one stale-cached over-claim row folds to J=1, refolded=True."""
    import json
    (tmp_path / "airline__8.json").write_text(json.dumps({
        "domain": "airline", "task_id": "8",
        "answer_excerpt": "You are all set! Your reservation number is HATHAT.",
        "db_match": False, "confident_write": False, "admit": True, "verdict": "NO_CLAIM",
        "agent_cost": 0.05,
    }), encoding="utf-8")
    out = _fold_dir(tmp_path)
    assert out["refolded_with_current_extractor"] is True
    assert out["n_overclaim_events"] == 1
    assert out["J_blocked"] == 1
