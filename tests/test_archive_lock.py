"""Archive-lock mutex (`dos.archive_lock`) — the Step-9.5 archive-ceremony lock.

The lock exists to stop two near-concurrent fanouts both running the archive
ceremony and clobbering INDEX.md / execution-state.yaml (queue finding #34). The
load-bearing property is therefore **mutual exclusion**: at most one owner at a
time, even on the stale-lock STEAL path. These tests pin the normal acquire/
re-entrant/busy behavior and — the regression that matters — that two concurrent
stealers of one stale lock can NEVER both come away holding the mutex (the old
unlink-then-recreate steal was a TOCTOU that let exactly that happen).
"""

from __future__ import annotations

import argparse
import os

import pytest

from dos import archive_lock as al


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    """Point the module at a throwaway lock file via its env override."""
    lp = tmp_path / ".archive.lock"
    monkeypatch.setenv("DISPATCH_ARCHIVE_LOCK_PATH", str(lp))
    return lp


def _acquire(owner, *, ttl=300, retries=0, interval=0):
    return al.cmd_acquire(argparse.Namespace(
        owner=owner, ttl_seconds=ttl, retries=retries, retry_interval=interval))


def _write_stale(lp, owner="old", acquired_at="2020-01-01T00:00:00Z", pid=999):
    lp.write_text(f"owner: {owner}\nacquired_at: {acquired_at}\npid: {pid}\n", encoding="utf-8")


# ── normal paths ────────────────────────────────────────────────────────────


def test_acquire_when_free(lock_path):
    assert _acquire("fanout-A") == 0
    assert al._read_lock()["owner"] == "fanout-A"


def test_reentrant_same_owner(lock_path):
    assert _acquire("fanout-A") == 0
    assert _acquire("fanout-A") == 0  # re-entrant refresh, still 0
    assert al._read_lock()["owner"] == "fanout-A"


def test_busy_other_owner_live(lock_path):
    # A fresh (non-stale) lock held by another owner → busy, exit 1.
    _write_stale(lock_path, owner="fanout-A", acquired_at=al._now_iso())
    assert _acquire("fanout-B", retries=0) == 1
    assert al._read_lock()["owner"] == "fanout-A"  # untouched


def test_single_stealer_takes_stale_lock(lock_path):
    _write_stale(lock_path, owner="orphan")
    assert _acquire("fanout-B") == 0
    assert al._read_lock()["owner"] == "fanout-B"


# ── the TOCTOU regression — mutual exclusion on the steal path ──────────────


def test_steal_is_atomic_cas(lock_path, monkeypatch):
    """`_steal_stale_lock` is a compare-and-swap on the lock inode: exactly one of
    two concurrent stealers wins. We inject the second stealer at the precise CAS
    point (just before the winner's `os.rename` lands) — the worst interleaving —
    and assert the second does NOT also acquire. A re-entry guard ensures the
    intruder's own (nested) rename runs the real syscall, not the injector again."""
    _write_stale(lock_path, owner="orphan")
    stale = al._read_lock()  # the SAME stale identity both stealers observe

    real_rename = os.rename
    state = {"in_injection": False, "injected": False, "intruder_won": None}

    def racing_rename(src, dst):
        # Only the OUTER stealer (A) triggers the intruder, exactly once, and the
        # re-entry guard makes the intruder's nested rename fall straight through.
        if not state["injected"] and not state["in_injection"]:
            state["injected"] = True
            state["in_injection"] = True
            try:
                state["intruder_won"] = al._steal_stale_lock("intruder-B", stale)
            finally:
                state["in_injection"] = False
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", racing_rename)
    a_won = al._steal_stale_lock("stealer-A", stale)

    # Exactly one of the two stealers may have won — never both (the TOCTOU bug let
    # both win; the CAS makes that impossible).
    assert (a_won, state["intruder_won"]).count(True) == 1, (
        f"mutual exclusion violated: A_won={a_won}, B_won={state['intruder_won']}"
    )
    # The lock's recorded owner is exactly the single winner.
    owner = al._read_lock()["owner"]
    winner = "stealer-A" if a_won else "intruder-B"
    assert owner == winner, f"lock owner {owner!r} != the winning stealer {winner!r}"


def test_concurrent_cmd_acquire_steal_yields_one_owner(lock_path, monkeypatch):
    """End-to-end through `cmd_acquire`: two stealers racing on one stale lock must
    leave the mutex with a single owner and the recorded owner's acquire returned 0."""
    _write_stale(lock_path, owner="orphan")

    real_rename = os.rename
    state = {"in_injection": False, "injected": False, "B_rc": None}

    def racing_rename(src, dst):
        if not state["injected"] and not state["in_injection"]:
            state["injected"] = True
            state["in_injection"] = True
            try:
                state["B_rc"] = _acquire("fanout-B", retries=0)  # full second acquire mid-CAS
            finally:
                state["in_injection"] = False
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", racing_rename)
    a_rc = _acquire("fanout-A", retries=0)

    # The lock ends with exactly one owner, one of the two contenders.
    owner = al._read_lock()["owner"]
    assert owner in {"fanout-A", "fanout-B"}, owner
    # The recorded owner is whichever stealer's acquire returned 0 — and only one did
    # for the WIN (the other either lost the CAS → busy/retry, or never owned).
    winner_rc = a_rc if owner == "fanout-A" else state["B_rc"]
    assert winner_rc == 0
