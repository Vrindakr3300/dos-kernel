"""The shared O_EXCL file-mutex primitives (`dos._filelock`).

These pin the ONE value-keyed steal compare-and-swap that archive_lock, lane_lease,
and home all route through. The load-bearing property is mutual exclusion on the
STEAL path: two concurrent stealers of one stale lock must never both win (the
non-value-keyed unlink-then-create TOCTOU let them). Pinning it here, once, is what
makes the bug unrepresentable for every mutex instead of a per-site choice.
"""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from dos import _filelock


@pytest.fixture
def lock(tmp_path):
    return tmp_path / ".test.lock"


def _stale(lock, owner="orphan", at="2020-01-01T00:00:00Z"):
    lock.write_text(f"owner: {owner}\nacquired_at: {at}\npid: 9\n", encoding="utf-8")


# ── the basic primitives ────────────────────────────────────────────────────


def test_write_then_read_roundtrip(lock):
    _filelock.write_lock(lock, "me")
    info = _filelock.read_lock(lock)
    assert info["owner"] == "me"
    assert "acquired_at" in info and "pid" in info


def test_write_lock_is_exclusive(lock):
    _filelock.write_lock(lock, "first")
    with pytest.raises(FileExistsError):
        _filelock.write_lock(lock, "second")


def test_read_absent_is_none(lock):
    assert _filelock.read_lock(lock) is None


def test_single_stealer_wins(lock):
    _stale(lock)
    stale = _filelock.read_lock(lock)
    assert _filelock.steal_stale(lock, "me", stale) is True
    assert _filelock.read_lock(lock)["owner"] == "me"


def test_steal_fails_when_lock_already_gone(lock):
    # No lock present at all → nothing to steal → False (not a crash).
    stale = {"owner": "orphan", "acquired_at": "2020-01-01T00:00:00Z"}
    assert _filelock.steal_stale(lock, "me", stale) is False


# ── the TOCTOU regression — mutual exclusion on the steal path ──────────────


def test_two_concurrent_stealers_yield_one_owner(lock, monkeypatch):
    """Inject a second stealer at the precise CAS point (just before the first's
    rename lands) and assert exactly one wins — the property the naive
    unlink-then-create steal violated (both won)."""
    _stale(lock)
    stale = _filelock.read_lock(lock)

    real_rename = os.rename
    state = {"in_injection": False, "injected": False, "b_won": None}

    def racing_rename(src, dst):
        if not state["injected"] and not state["in_injection"]:
            state["injected"] = True
            state["in_injection"] = True
            try:
                state["b_won"] = _filelock.steal_stale(lock, "B", stale)
            finally:
                state["in_injection"] = False
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", racing_rename)
    a_won = _filelock.steal_stale(lock, "A", stale)

    assert (a_won, state["b_won"]).count(True) == 1, (
        f"mutual exclusion violated: A={a_won}, B={state['b_won']}"
    )
    owner = _filelock.read_lock(lock)["owner"]
    assert owner == ("A" if a_won else "B")


def test_steal_restores_on_value_mismatch(lock):
    """If the lock content does NOT match the observed stale identity (a racer
    already stole + recreated a fresh lock), the steal must put it back and concede
    — never displace a winner's live lock."""
    _stale(lock, owner="fresh-winner", at="2099-01-01T00:00:00Z")  # NOT the stale we 'observed'
    observed = {"owner": "orphan", "acquired_at": "2020-01-01T00:00:00Z"}
    assert _filelock.steal_stale(lock, "me", observed) is False
    # The fresh winner's lock is intact — we did not clobber it.
    assert _filelock.read_lock(lock)["owner"] == "fresh-winner"


# ── atomic_replace — win32 rename-vs-open-handle retry ──────────────────────
#
# These pin the load-bearing half of the execution-state.yaml lock-storm fix:
# the bounded-backoff retry around os.replace that survives a concurrent reader
# holding the destination open on win32. Most assertions are platform-neutral
# (we simulate the WinError via monkeypatch so CI on any OS exercises the retry
# loop); one real-handle test is win32-only.


def _winerror_oserror(winerror: int, strerror: str = "Access is denied") -> OSError:
    """An OSError that carries `.winerror` on EVERY OS (the retry loop keys on it).

    `OSError(errno, strerror, filename, winerror)`'s 4th positional is HONORED ONLY
    ON WINDOWS — on POSIX it is silently dropped and `.winerror` is absent, so a
    bare `OSError(13, "…", None, 5)` would make the simulated WinError invisible to
    `atomic_replace` (which does `getattr(e, "winerror", None)`) and the retry would
    never trigger off-Windows. Setting the attribute explicitly is portable, so the
    "CI on any OS exercises the retry loop" intent above actually holds on Linux too.
    """
    e = OSError(13, strerror)
    e.winerror = winerror
    return e


def _payload(tmp_path, body: str = "new\n"):
    """A (src, dst) pair where src holds `body` and dst pre-exists with old content."""
    dst = tmp_path / "state.yaml"
    dst.write_text("old\n", encoding="utf-8")
    src = tmp_path / "state.yaml.tmp"
    src.write_text(body, encoding="utf-8")
    return src, dst


def test_atomic_replace_succeeds_with_no_contention(tmp_path):
    src, dst = _payload(tmp_path)
    _filelock.atomic_replace(src, dst)
    assert dst.read_text(encoding="utf-8") == "new\n"
    assert not src.exists()


def test_atomic_replace_retries_then_succeeds(tmp_path, monkeypatch):
    """Two simulated WinError-5 failures then success → the write lands, content
    is the writer's payload (not the stale pre-existing content), within budget."""
    src, dst = _payload(tmp_path)
    real = os.replace
    calls = {"n": 0}

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _winerror_oserror(5)  # winerror=5, portable across OSes
        return real(s, d)

    monkeypatch.setattr(os, "replace", flaky)
    # Tiny backoff so the test is fast; budget comfortably covers 2 retries.
    _filelock.atomic_replace(src, dst, budget_s=5.0, base_s=0.001, cap_s=0.005)
    assert calls["n"] == 3
    assert dst.read_text(encoding="utf-8") == "new\n"


def test_atomic_replace_raises_when_budget_exhausted(tmp_path, monkeypatch):
    """A handle held LONGER than the budget → the writer RAISES (the documented
    budget-exhaustion boundary), it does not silently swallow the failure."""
    src, dst = _payload(tmp_path)

    def always_denied(s, d):
        raise _winerror_oserror(5)

    monkeypatch.setattr(os, "replace", always_denied)
    with pytest.raises(OSError) as ei:
        _filelock.atomic_replace(src, dst, budget_s=0.05, base_s=0.001, cap_s=0.005)
    assert ei.value.winerror == 5
    # dst keeps its old content — a swallowed failure would NOT have raised.
    assert dst.read_text(encoding="utf-8") == "old\n"


def test_atomic_replace_does_not_retry_unrelated_oserror(tmp_path, monkeypatch):
    """A non-retry winerror (e.g. ENOENT-shaped, winerror=2) re-raises on the
    FIRST attempt — we only retry the rename-over-open-handle codes."""
    src, dst = _payload(tmp_path)
    calls = {"n": 0}

    def other(s, d):
        calls["n"] += 1
        raise _winerror_oserror(2, "No such file")  # winerror=2, not a retry code

    monkeypatch.setattr(os, "replace", other)
    with pytest.raises(OSError):
        _filelock.atomic_replace(src, dst, budget_s=5.0)
    assert calls["n"] == 1  # no retry


def test_atomic_replace_posix_single_attempt(tmp_path, monkeypatch):
    """On POSIX a failure carries winerror=None → the guard is false → exactly
    one attempt (no retry), matching the documented degradation."""
    src, dst = _payload(tmp_path)
    calls = {"n": 0}

    def posix_fail(s, d):
        calls["n"] += 1
        raise OSError(13, "Permission denied")  # winerror is None

    monkeypatch.setattr(os, "replace", posix_fail)
    with pytest.raises(OSError):
        _filelock.atomic_replace(src, dst, budget_s=5.0)
    assert calls["n"] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="real rename-over-open-handle race is win32-only")
def test_atomic_replace_survives_real_open_reader_win32(tmp_path):
    """The genuine scenario: a thread holds dst open via PLAIN open() (the share
    mode the real readers use — NOT FILE_SHARE_DELETE, which would assert the
    wrong scenario) for ~150ms during the replace; the write must still land."""
    src, dst = _payload(tmp_path)
    stop = threading.Event()

    def hold_open():
        with open(dst, encoding="utf-8"):
            stop.wait(0.15)

    t = threading.Thread(target=hold_open)
    t.start()
    time.sleep(0.02)  # ensure the reader has the handle before we replace
    _filelock.atomic_replace(src, dst, budget_s=3.0)
    stop.set()
    t.join()
    assert dst.read_text(encoding="utf-8") == "new\n"
