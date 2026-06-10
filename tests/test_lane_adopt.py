"""Supervised-child adoption — the ADOPT ownership-transfer op + the child-identity
anchor (C5, docs/95). The kernel half ONLY: it records who the holder spawned and
lets ANY acquirer take over a live orphan's lease without killing the grandchildren.

The load-bearing properties:
  * `children` is an additive anchor on ACQUIRE that survives the replay fold.
  * ADOPT rewrites ownership (holder/pid/host_id) but KEEPS identity, tree, ttl,
    and children — never removes the lease (it's a transfer, not a kill).
  * ADOPT against a released/scavenged key is a no-op (you can't adopt what no one
    holds — the safe direction).
  * `lane_lease.adopt` performs the durable transfer under the mutex.
"""
from __future__ import annotations

import pytest

from dos import lane_journal as lj
from dos import lane_lease
from dos import config as _config


def _lease(lane="ASI", loop_ts="20260603T100000Z", holder="boxA:111", **over):
    base = dict(
        lane=lane, lane_kind="priority", tree=["src/asi/**"], loop_ts=loop_ts,
        host_id="boxA", pid=111, acquired_at="2026-06-03T10:00:00Z",
        heartbeat_at="2026-06-03T10:00:00Z", ttl_minutes=50, holder=holder,
    )
    base.update(over)
    return base


# ── the child-identity anchor survives acquire → replay ─────────────────────


def test_children_anchor_rides_acquire_to_replay():
    kids = [{"run_id": "RID-childA", "pid": 222}, {"run_id": "RID-childB", "pid": 333}]
    e = lj.acquire_entry(_lease(), children=kids)
    [folded] = lj.replay([e])
    assert folded["children"] == kids        # the anchor survived the fold


def test_children_absent_is_unchanged():
    # No children → no key, replayed byte-identical to a pre-C5 ACQUIRE.
    e = lj.acquire_entry(_lease())
    assert "children" not in e["lease"]
    [folded] = lj.replay([e])
    assert "children" not in folded


def test_children_from_lease_dict_is_honored():
    # A host that stamps `children` on the lease dict (not via the arg) still anchors.
    lease = _lease(children=[{"run_id": "RID-x", "pid": 9}])
    e = lj.acquire_entry(lease)
    assert e["lease"]["children"] == [{"run_id": "RID-x", "pid": 9}]


# ── ADOPT replay: ownership transfer, identity/tree/children preserved ───────


def test_adopt_rewrites_ownership_keeps_everything_else():
    kids = [{"run_id": "RID-childA", "pid": 222}]
    acq = lj.acquire_entry(_lease(holder="boxA:111", pid=111), children=kids)
    [before] = lj.replay([acq])
    assert before["holder"] == "boxA:111"

    adopt = lj.adopt_entry(before, new_holder="boxB:999", new_pid=999,
                           new_host_id="boxB")
    [after] = lj.replay([acq, adopt])
    # ownership moved …
    assert after["holder"] == "boxB:999"
    assert after["pid"] == 999
    assert after["host_id"] == "boxB"
    # … but identity, tree, ttl, and the child anchor are intact (no kill).
    assert after["loop_ts"] == before["loop_ts"]
    assert after["lane"] == before["lane"]
    assert after["tree"] == before["tree"]
    assert after["ttl_minutes"] == before["ttl_minutes"]
    assert after["children"] == kids


def test_adopt_refreshes_heartbeat():
    acq = lj.acquire_entry(_lease(heartbeat_at="2026-06-03T10:00:00Z"))
    adopt = lj.adopt_entry(lj.replay([acq])[0], new_holder="boxB:1",
                           heartbeat_at="2026-06-03T10:40:00Z")
    [after] = lj.replay([acq, adopt])
    assert after["heartbeat_at"] == "2026-06-03T10:40:00Z"  # not stale under new owner


def test_adopt_against_released_lease_is_noop():
    # You cannot adopt a lease no one holds — an ADOPT after RELEASE adds nothing.
    acq = lj.acquire_entry(_lease())
    rel = lj.release_entry(lj.replay([acq])[0])
    adopt = lj.adopt_entry(_lease(), new_holder="boxB:1")
    assert lj.replay([acq, rel, adopt]) == []   # still gone, not resurrected


def test_adopt_against_scavenged_lease_is_noop():
    acq = lj.acquire_entry(_lease())
    scav = lj.scavenge_entry(lj.replay([acq])[0], reason="dead")
    adopt = lj.adopt_entry(_lease(), new_holder="boxB:1")
    assert lj.replay([acq, scav, adopt]) == []


def test_adopt_is_state_mutating_op():
    assert lj.OP_ADOPT in lj._STATE_MUTATING_OPS


# ── ADOPT survives compaction ───────────────────────────────────────────────


def test_adopted_lease_survives_compaction():
    kids = [{"run_id": "RID-c", "pid": 5}]
    acq = lj.acquire_entry(_lease(holder="boxA:111"), children=kids)
    adopt = lj.adopt_entry(lj.replay([acq])[0], new_holder="boxB:999", new_pid=999)
    entries = [acq, adopt]
    # compact then replay reproduces the same live set (the replay(compact(E)) invariant)
    compacted = lj.compact(entries)
    [after] = lj.replay(compacted)
    assert after["holder"] == "boxB:999"
    assert after["children"] == kids


# ── lane_lease.adopt — the I/O shell under the mutex ────────────────────────


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_LANE_LEASE_LOCK_PATH", str(tmp_path / ".lane-lease.lock"))
    monkeypatch.setenv("DISPATCH_LANE_JOURNAL_PATH", str(tmp_path / "lane-journal.jsonl"))
    return _config.default_config(str(tmp_path))


def test_lane_lease_adopt_transfers_a_live_lease(cfg):
    # Seed a live lease via a direct ACQUIRE append (its holder is the "orphan").
    path = lane_lease._journal_path(cfg)
    lj.append(lj.acquire_entry(
        _lease(lane="apply", holder="orphan:1", pid=1),
        children=[{"run_id": "RID-kid", "pid": 7}]), path)
    assert any(l["lane"] == "apply" for l in lane_lease.live_leases(cfg))

    ok = lane_lease.adopt(cfg, lane="apply", new_owner="rescuer:2", new_pid=2)
    assert ok is True
    live = {l["lane"]: l for l in lane_lease.live_leases(cfg)}
    assert live["apply"]["holder"] == "rescuer:2"   # ownership moved
    assert live["apply"]["pid"] == 2
    assert live["apply"]["children"] == [{"run_id": "RID-kid", "pid": 7}]  # anchor kept


def test_lane_lease_adopt_no_match_returns_false(cfg):
    # No live lease on the lane → nothing to adopt.
    assert lane_lease.adopt(cfg, lane="nonexistent", new_owner="x:1") is False
