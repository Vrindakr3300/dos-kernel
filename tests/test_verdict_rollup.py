"""The multi-surface verdict rollup (`dos.verdict_rollup`) — C9, the cross-surface-
drift fix (for the reference benchmark's console/Slack/LLM/JSON divergence).

The load-bearing properties:
  * worst-first fold → ONE headline every surface reproduces (no drift).
  * requested-but-absent is a FIRST-CLASS synthesized item (a missing producer
    surfaces as a typed verdict, never a silently-dropped row).
  * the status vocabulary is CALLER DATA (a StatusRank), the kernel hard-codes none.
  * never raises on a malformed item; composes with the dos.verdict TypedVerdict shape.
"""
from __future__ import annotations

import pytest

from dos import verdict_rollup as vr
from dos.verdict import TypedVerdict


# A caller's vocabulary — worst-first (smaller == more severe). The kernel ships none.
RANK = vr.StatusRank(
    order={"failed": 0, "empty": 1, "degraded": 2, "unknown": 3,
           "requested": 4, "ok": 5},
)


# ── StatusRank validation ───────────────────────────────────────────────────


def test_status_rank_rejects_empty():
    with pytest.raises(ValueError):
        vr.StatusRank(order={})


def test_status_rank_unknown_and_absent_must_be_in_order():
    with pytest.raises(ValueError):
        vr.StatusRank(order={"ok": 0}, unknown_status="nope")
    with pytest.raises(ValueError):
        vr.StatusRank(order={"ok": 0}, absent_status="nope")


def test_unranked_status_sorts_least_severe():
    # A typo'd status must NOT masquerade as the worst — it ranks after everything.
    assert RANK.rank("typo") > RANK.rank("ok")


# ── the worst-status fold ───────────────────────────────────────────────────


def test_worst_status_picks_most_severe():
    r = vr.rollup(
        [{"key": "a", "status": "ok"}, {"key": "b", "status": "empty"},
         {"key": "c", "status": "ok"}],
        rank=RANK, label="cap")
    assert r.worst_status == "empty"        # one empty drags the headline down
    assert r.verdict == "empty"             # TypedVerdict headline == worst_status


def test_empty_rollup_is_clean_and_none():
    r = vr.rollup([], rank=RANK)
    assert r.worst_status is None
    assert r.all_clean is True
    assert r.present is False


def test_all_clean_only_when_every_item_best_and_no_integrity():
    clean = vr.rollup([{"key": "a", "status": "ok"}], rank=RANK)
    assert clean.all_clean is True
    dirty = vr.rollup(
        [{"key": "a", "status": "ok", "integrity": ["truncated"]}], rank=RANK)
    assert dirty.all_clean is False        # an integrity flag is not clean
    worse = vr.rollup([{"key": "a", "status": "degraded"}], rank=RANK)
    assert worse.all_clean is False


def test_reason_is_counts_worst_first():
    r = vr.rollup(
        [{"key": "a", "status": "ok"}, {"key": "b", "status": "ok"},
         {"key": "c", "status": "empty"}],
        rank=RANK)
    assert r.reason == "1 empty, 2 ok"     # worst-first ordering


# ── requested-but-absent: the anti-drift headline feature ───────────────────


def test_absent_producer_becomes_a_typed_item():
    # We asked for "blktrace" and "iostat" but only blktrace produced anything.
    r = vr.rollup(
        [{"key": "blktrace", "status": "ok"}],
        rank=RANK, absent=["iostat"], label="capture")
    keys = {it.key: it for it in r.items}
    assert "iostat" in keys
    assert keys["iostat"].absent is True
    assert keys["iostat"].status == "requested"
    # And it drags the headline — a missing producer is NOT silently clean.
    assert r.all_clean is False
    assert r.worst_status == "requested"   # more severe than the "ok" we got


def test_absent_uses_caller_named_status():
    rank = vr.StatusRank(order={"bad": 0, "MISSING": 1, "fine": 2},
                         unknown_status="bad", absent_status="MISSING")
    r = vr.rollup([], rank=rank, absent=["x"])
    assert r.items[0].status == "MISSING" and r.items[0].absent is True


# ── degrade / never-raise ───────────────────────────────────────────────────


def test_unknown_status_degrades():
    r = vr.rollup([{"key": "a", "status": "wat"}], rank=RANK)
    assert r.items[0].status == "unknown"  # not in order → unknown_status


def test_malformed_item_does_not_raise():
    class Boom:
        @property
        def status(self):
            raise RuntimeError("nope")

    r = vr.rollup([Boom()], rank=RANK)
    assert r.items[0].status == "unknown"
    assert "unreadable" in r.items[0].reason


def test_none_status_degrades_not_crashes():
    r = vr.rollup([{"key": "a", "status": None}], rank=RANK)
    assert r.items[0].status == "unknown"


# ── duck-typed extractors (dict AND object) ─────────────────────────────────


def test_object_items_roll_up_without_adapting():
    class Cap:
        def __init__(self, key, status):
            self.key = key
            self.status = status
            self.reason = "from object"

    r = vr.rollup([Cap("dev0", "ok"), Cap("dev1", "empty")], rank=RANK)
    assert r.worst_status == "empty"
    assert {it.key for it in r.items} == {"dev0", "dev1"}


def test_custom_extractors():
    # A caller whose objects name the fields differently passes its own getters.
    items = [{"name": "x", "health": "failed"}]
    r = vr.rollup(
        items, rank=RANK,
        key_of=lambda x: x["name"], status_of=lambda x: x["health"],
        reason_of=lambda x: "", integrity_of=lambda x: ())
    assert r.worst_status == "failed"
    assert r.items[0].key == "x"


# ── composes with the verdict seam ──────────────────────────────────────────


def test_satisfies_typed_verdict_protocol():
    r = vr.rollup([{"key": "a", "status": "ok"}], rank=RANK)
    assert isinstance(r, TypedVerdict)     # verdict + reason + to_dict, structurally


def test_to_dict_shape():
    r = vr.rollup(
        [{"key": "a", "status": "ok"}], rank=RANK, absent=["b"], label="cap")
    d = r.to_dict()
    assert d["label"] == "cap"
    assert d["verdict"] == d["worst_status"] == "requested"
    assert d["all_clean"] is False
    assert d["present"] is True
    assert len(d["items"]) == 2
    absent_item = next(i for i in d["items"] if i["key"] == "b")
    assert absent_item["absent"] is True
