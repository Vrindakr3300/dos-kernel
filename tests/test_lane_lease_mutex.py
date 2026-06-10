"""The lane-lease cross-process mutex steal (`dos.lane_lease._Mutex`).

`_Mutex` serializes the read-arbitrate-append critical section of a lane-lease
grant; if two cross-process acquirers both win a stale orphan lock they both fold
the same pre-other's-ACQUIRE live-lease set and both ADMIT one colliding tree — the
worst-class false-admit this module exists to prevent. The steal now routes through
the shared value-keyed CAS (`_filelock.steal_stale`); this pins that a stale lock is
stolen by exactly one holder and that the normal O_EXCL acquire is unaffected.
"""

from __future__ import annotations

import os

import pytest

from dos import _filelock, lane_lease
from dos import config as _config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_LANE_LEASE_LOCK_PATH", str(tmp_path / ".lane-lease.lock"))
    return _config.default_config(str(tmp_path))


def _lock(cfg):
    return lane_lease._lock_path(cfg)


def test_mutex_acquires_when_free(cfg):
    with lane_lease._Mutex(cfg, "owner-A", retries=0):
        assert _filelock.read_lock(_lock(cfg))["owner"] == "owner-A"
    # released on exit
    assert _filelock.read_lock(_lock(cfg)) is None


def test_mutex_busy_raises_timeout(cfg):
    # A fresh (non-stale) lock by another owner → cannot acquire within budget.
    _filelock.write_lock(_lock(cfg), "owner-A")
    with pytest.raises(TimeoutError):
        with lane_lease._Mutex(cfg, "owner-B", retries=0):
            pass


def test_mutex_steals_stale_lock(cfg):
    # A stale orphan lock (old acquired_at, past ttl) is stealable.
    _lock(cfg).parent.mkdir(parents=True, exist_ok=True)
    _lock(cfg).write_text(
        "owner: orphan\nacquired_at: 2020-01-01T00:00:00Z\npid: 9\n", encoding="utf-8")
    with lane_lease._Mutex(cfg, "owner-B", retries=2, ttl_seconds=1):
        assert _filelock.read_lock(_lock(cfg))["owner"] == "owner-B"


def test_two_mutex_stealers_yield_one_owner(cfg, monkeypatch):
    """Two cross-process stealers racing on one stale lock: exactly one acquires.
    Inject the second steal at the CAS point of the first (the worst interleaving)."""
    _lock(cfg).parent.mkdir(parents=True, exist_ok=True)
    _lock(cfg).write_text(
        "owner: orphan\nacquired_at: 2020-01-01T00:00:00Z\npid: 9\n", encoding="utf-8")
    stale = _filelock.read_lock(_lock(cfg))

    real_rename = os.rename
    state = {"in_injection": False, "injected": False, "b_won": None}

    def racing_rename(src, dst):
        if not state["injected"] and not state["in_injection"]:
            state["injected"] = True
            state["in_injection"] = True
            try:
                state["b_won"] = _filelock.steal_stale(_lock(cfg), "B", stale)
            finally:
                state["in_injection"] = False
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", racing_rename)
    a_won = _filelock.steal_stale(_lock(cfg), "A", stale)

    assert (a_won, state["b_won"]).count(True) == 1
    assert _filelock.read_lock(_lock(cfg))["owner"] == ("A" if a_won else "B")
