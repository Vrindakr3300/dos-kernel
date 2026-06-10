"""HALT — the `reap`-family stop-decision verb (docs/99).

Two layers, mirroring the lane-lease split:

  * the PURE journal layer — `OP_HALT` + `halt_entry()`, and its REFUSE-like
    NON-mutating replay fold (a HALT records a stop INTENT; it removes no lease —
    only a later RELEASE/SCAVENGE the driver appends actually evicts);
  * the EFFECTFUL boundary — `lane_lease.halt()`, which records the decision on
    the WAL and proposes a command, and **never** delivers a signal.

The load-bearing properties this pins are the ones that keep `halt` inside the
kernel's advisory-only floor and domain-free contract (docs/99 §3, §5):
the kernel records + proposes, never kills; the handle is opaque and never
interpreted; everything resolves against the injected `SubstrateConfig`.
"""

from __future__ import annotations

import os

import pytest

from dos import lane_lease
from dos import config as _config
from dos.lane_journal import (
    OP_ACQUIRE,
    OP_HALT,
    OP_SCAVENGE,
    _STATE_MUTATING_OPS,
    acquire_entry,
    halt_entry,
    read_all,
    replay,
    scavenge_entry,
)

_LEASE = {
    "lane": "apply",
    "lane_kind": "concurrent",
    "tree": ("agents/apply_*.py",),
    "loop_ts": "2026-06-01T14:00Z",
    "host_id": "host-a",
    "pid": 4242,
    "acquired_at": "2026-06-01T14:00:03Z",
}


# ---------------------------------------------------------------------------
# The pure journal layer — entry builder + non-mutating replay.
# ---------------------------------------------------------------------------

def test_halt_entry_op_and_keys():
    """halt_entry stamps OP_HALT + the opaque handle + reason + command, and
    carries the (forensic) lane/loop_ts for correlation."""
    e = halt_entry("pid:4242", reason="spinning", lane="apply",
                   loop_ts="2026-06-01T14:00Z", run_id="RID-X",
                   command="kill 4242")
    assert e["op"] == OP_HALT
    assert e["handle"] == "pid:4242"
    assert e["reason"] == "spinning"
    assert e["lane"] == "apply"
    assert e["loop_ts"] == "2026-06-01T14:00Z"
    assert e["run_id"] == "RID-X"
    assert e["command"] == "kill 4242"


def test_halt_is_not_a_state_mutating_op():
    """HALT is excluded from the state-mutating set — it is a recorded DECISION,
    like REFUSE, never a lease grant/eviction."""
    assert OP_HALT not in _STATE_MUTATING_OPS


def test_halt_does_not_mutate_replay_state():
    """replay([ACQUIRE(L), HALT(L)]) leaves the lease STILL LIVE — a HALT records
    the stop intent, it does not evict (only RELEASE/SCAVENGE does)."""
    entries = [
        acquire_entry(_LEASE),
        halt_entry("pid:4242", lane="apply", loop_ts="2026-06-01T14:00Z"),
    ]
    live = replay(entries)
    assert len(live) == 1
    assert live[0]["lane"] == "apply"


def test_halt_then_scavenge_evicts():
    """ACQUIRE -> HALT -> SCAVENGE folds to empty: the driver confirmed the stop
    and journaled the eviction. The HALT alone did not remove the lease; the
    SCAVENGE did. This is the kill (HALT->SCAVENGE) vs natural-death (RELEASE)
    distinction the closed op vocabulary preserves."""
    entries = [
        acquire_entry(_LEASE),
        halt_entry("pid:4242", lane="apply", loop_ts="2026-06-01T14:00Z"),
        scavenge_entry(_LEASE, reason="confirmed-halt"),
    ]
    assert replay(entries) == []


# ---------------------------------------------------------------------------
# The effectful boundary — lane_lease.halt(): records + proposes, never signals.
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    # Pin BOTH the lock and the journal at tmp paths so the HALT lands in
    # isolation and we can assert nothing is written under the package tree.
    monkeypatch.setenv("DISPATCH_LANE_LEASE_LOCK_PATH",
                       str(tmp_path / ".lane-lease.lock"))
    monkeypatch.setenv("DISPATCH_LANE_JOURNAL_PATH",
                       str(tmp_path / "lane-journal.jsonl"))
    return _config.default_config(str(tmp_path))


def _journal(cfg):
    return lane_lease._journal_path(cfg)


def test_halt_records_on_spine(cfg):
    """After halt(), the WAL holds exactly one OP_HALT carrying the handle."""
    res = lane_lease.halt(cfg, handle="pid:9001", reason="spinning",
                          command="kill 9001")
    assert res.recorded is True
    assert res.handle == "pid:9001"
    assert res.command == "kill 9001"
    entries = [e for e in read_all(_journal(cfg)) if e.get("op") == OP_HALT]
    assert len(entries) == 1
    assert entries[0]["handle"] == "pid:9001"
    assert entries[0]["command"] == "kill 9001"


def test_halt_resolves_via_config_not_file(cfg, tmp_path):
    """The HALT lands at the configured journal path; NOTHING is written under
    the package source tree (the layering litmus: paths resolve against the
    injected SubstrateConfig, never __file__)."""
    lane_lease.halt(cfg, handle="pid:1", reason="t")
    assert (tmp_path / "lane-journal.jsonl").exists()
    # The kernel package dir must be untouched by a HALT.
    pkg_dir = os.path.dirname(lane_lease.__file__)
    assert not os.path.exists(os.path.join(pkg_dir, "lane-journal.jsonl"))


def test_halt_is_domain_free(cfg):
    """A pid handle, a container-id handle, and an opaque token are recorded
    IDENTICALLY and interpreted in NO way — the kernel never learns what a
    'process' is (docs/99 Gate 3)."""
    handles = ["12345", "docker://abc123", "wf_task_7f3a", "RID-deadbeef"]
    for h in handles:
        res = lane_lease.halt(cfg, handle=h, reason="x")
        assert res.recorded is True
        assert res.handle == h
    recorded = [e for e in read_all(_journal(cfg)) if e.get("op") == OP_HALT]
    assert [e["handle"] for e in recorded] == handles


def test_halt_proposes_does_not_signal(cfg, monkeypatch):
    """The four-gate proof that HALT deliberately FAILS the effect-performance
    gate: even if os.kill / subprocess would RAISE, halt() still succeeds — proof
    the kernel never calls them. It records + proposes; the signal is a driver's."""
    import subprocess

    def _boom(*a, **k):
        raise AssertionError("the kernel must NEVER deliver a signal")

    monkeypatch.setattr(os, "kill", _boom, raising=False)
    monkeypatch.setattr(subprocess, "Popen", _boom, raising=False)
    monkeypatch.setattr(subprocess, "run", _boom, raising=False)

    res = lane_lease.halt(cfg, handle="pid:5", reason="spinning",
                          command="kill 5")
    assert res.recorded is True
    # The command is PROPOSED (echoed), never executed.
    assert res.command == "kill 5"


def test_halt_correlates_to_live_lease_for_forensics(cfg):
    """When a live lease matches (by lane), halt() stamps the lease's loop_ts onto
    the record so an operator can join HALT -> lease — forensic only, the HALT
    still records with or without a match. (The generic default taxonomy
    auto-picks a bare lane to the concurrent default 'main', so we correlate on
    the lane the lease actually got.)"""
    res_acq = lane_lease.acquire(cfg, lane="", kind="concurrent",
                                 tree=["agents/apply_*.py"], owner="worker-1",
                                 loop_ts="2026-06-01T15:00Z")
    held_lane = res_acq.decision.lane  # 'main' under the generic default
    res = lane_lease.halt(cfg, handle="pid:4242", lane=held_lane, reason="spinning")
    assert res.recorded is True
    assert res.lane == held_lane
    assert res.loop_ts == "2026-06-01T15:00Z"


def test_halt_records_without_a_matching_lease(cfg):
    """A handle that matches no live lease still records (the bare-handle path —
    you can halt a run whose lease already ended or was never journaled)."""
    res = lane_lease.halt(cfg, handle="pid:99999", reason="orphan")
    assert res.recorded is True
    assert res.handle == "pid:99999"
