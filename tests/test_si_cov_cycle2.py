"""SI cycle-2 coverage test: exercise the in-process-only branches of
`dos.archive_lock`.

The shipped suite drives `archive_lock`'s release/status/main paths only through
the `dos` CLI subprocess (tests/test_archive_lock.py covers acquire + the steal
CAS in-process; release, status, the retry-with-backoff branch, the
malformed-timestamp parse, and the argparse `main()` dispatch are reached only
via `dos archive-lock ...` subprocess calls). coverage.py does not track
subprocess-executed lines in this repo, so those lines (95-97, 141, 162,
186-189, 199-222, 226-237, 241-258, 266) show as uncovered.

This module calls those same code paths IN-PROCESS, against a throwaway lock
file pointed at by the module's own `DISPATCH_ARCHIVE_LOCK_PATH` env override.
Pure, deterministic, no sleeps (retries=0 / interval=0 everywhere), no network,
no writes to tracked paths. It asserts the real observable behavior of each
branch — it is not a coverage-only no-op.
"""

from __future__ import annotations

import argparse

import pytest

from dos import archive_lock as al


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    """Point the module at a throwaway lock file via its env override."""
    lp = tmp_path / ".archive.lock"
    monkeypatch.setenv("DISPATCH_ARCHIVE_LOCK_PATH", str(lp))
    return lp


def _ns(**kw):
    return argparse.Namespace(**kw)


def _write_lock_file(lp, owner="old", acquired_at="2020-01-01T00:00:00Z", pid=999):
    lp.write_text(
        f"owner: {owner}\nacquired_at: {acquired_at}\npid: {pid}\n",
        encoding="utf-8",
    )


# ── _parse_iso / _age_seconds: the malformed-timestamp branches (95-97, 141) ──


def test_parse_iso_accepts_both_formats():
    assert al._parse_iso("2026-06-12T01:02:03Z") is not None
    assert al._parse_iso("2026-06-12T01:02Z") is not None  # second format


def test_parse_iso_returns_none_on_garbage():
    # Drives the `except (ValueError, TypeError): continue` for BOTH fmts, then
    # the final `return None` (lines 95-97).
    assert al._parse_iso("not-a-timestamp") is None
    assert al._parse_iso("") is None


def test_age_seconds_none_when_timestamp_unparseable():
    # `_age_seconds` calls `_parse_iso`; on an unparseable `acquired_at` it must
    # short-circuit to None rather than raise (line 141).
    assert al._age_seconds({"acquired_at": "garbage"}) is None
    assert al._age_seconds({}) is None  # missing key → "" → None


def test_age_seconds_real_value(lock_path):
    age = al._age_seconds({"acquired_at": "2020-01-01T00:00:00Z"})
    assert age is not None and age > 0


# ── cmd_release: every branch (199-222) ──────────────────────────────────────


def test_release_when_no_lock_present(lock_path, capsys):
    # info is None → "released (no-lock)", exit 0 (199-203).
    rc = al.cmd_release(_ns(owner="fanout-A", force=False))
    assert rc == 0
    assert "released (no-lock)" in capsys.readouterr().out


def test_release_force_removes_regardless_of_owner(lock_path, capsys):
    # --force unlinks even when owner differs (205-211).
    _write_lock_file(lock_path, owner="someone-else", acquired_at=al._now_iso())
    rc = al.cmd_release(_ns(owner="fanout-A", force=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "force-released" in out and "someone-else" in out
    assert not lock_path.exists()


def test_release_owner_mismatch_leaves_lock(lock_path, capsys):
    # Non-force, owner mismatch → WARN, leave lock, exit 0 (213-215).
    _write_lock_file(lock_path, owner="holder", acquired_at=al._now_iso())
    rc = al.cmd_release(_ns(owner="not-the-holder", force=False))
    assert rc == 0
    err = capsys.readouterr().err
    assert "owner mismatch" in err
    assert lock_path.exists()  # untouched
    assert al._read_lock()["owner"] == "holder"


def test_release_owner_match_unlinks(lock_path, capsys):
    # Non-force, owner matches → unlink, "released <owner>", exit 0 (217-222).
    _write_lock_file(lock_path, owner="fanout-A", acquired_at=al._now_iso())
    rc = al.cmd_release(_ns(owner="fanout-A", force=False))
    assert rc == 0
    assert "released fanout-A" in capsys.readouterr().out
    assert not lock_path.exists()


# ── cmd_status: free / held / stale (226-237) ────────────────────────────────


def test_status_free(lock_path, capsys):
    rc = al.cmd_status(_ns(ttl_seconds=300))
    assert rc == 0
    assert capsys.readouterr().out.strip() == "free"


def test_status_held_when_fresh(lock_path, capsys):
    _write_lock_file(lock_path, owner="fanout-A", acquired_at=al._now_iso())
    rc = al.cmd_status(_ns(ttl_seconds=300))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("held fanout-A age=")


def test_status_stale_when_old(lock_path, capsys):
    # Old acquired_at → age >= ttl → "stale ...".
    _write_lock_file(lock_path, owner="orphan", acquired_at="2020-01-01T00:00:00Z")
    rc = al.cmd_status(_ns(ttl_seconds=300))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("stale orphan age=")


def test_status_unparseable_age_renders_qmark(lock_path, capsys):
    # acquired_at present but unparseable → _age_seconds None → "?s", and the
    # `age is None` arm of the stale check → falls to "held ... age=?s".
    _write_lock_file(lock_path, owner="weird", acquired_at="garbage")
    rc = al.cmd_status(_ns(ttl_seconds=300))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("held weird age=?s")


# ── cmd_acquire: the retry-with-backoff WAITING branch (162, 185-189) ─────────


def test_acquire_waiting_branch_then_busy(lock_path, monkeypatch, capsys):
    # A fresh lock held by another owner with retries=1 and a zero-interval
    # exercises the `attempt < retries` waiting branch (185-189) before the final
    # `busy` (191-193). We stub time.sleep so it stays instant and deterministic.
    _write_lock_file(lock_path, owner="holder", acquired_at=al._now_iso())
    monkeypatch.setattr(al.time, "sleep", lambda _s: None)
    rc = al.cmd_acquire(
        _ns(owner="fanout-B", ttl_seconds=300, retries=1, retry_interval=0)
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "waiting on holder" in err
    assert "busy holder" in err
    assert al._read_lock()["owner"] == "holder"  # never stolen


def test_acquire_info_none_retry_then_success(lock_path, monkeypatch):
    # Force the EEXIST → `info is None` → `continue` arm (160-162): make the first
    # write_lock raise FileExistsError while the lock reads as absent, then let the
    # retry's write succeed.
    calls = {"n": 0}
    real_write = al._write_lock

    def flaky_write(owner):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileExistsError  # pretend a racer held it for one beat
        return real_write(owner)

    monkeypatch.setattr(al, "_write_lock", flaky_write)
    monkeypatch.setattr(al, "_read_lock", lambda: None)  # vanished between EEXIST + read
    monkeypatch.setattr(al.time, "sleep", lambda _s: None)

    rc = al.cmd_acquire(
        _ns(owner="fanout-A", ttl_seconds=300, retries=2, retry_interval=0)
    )
    assert rc == 0
    assert calls["n"] == 2  # first raised, retry wrote
    assert lock_path.exists()


# ── main(): the argparse dispatch table (241-258, 266) ───────────────────────


def test_main_status_dispatch(lock_path, monkeypatch, capsys):
    monkeypatch.setattr(al.sys, "argv", ["archive_lock", "status"])
    rc = al.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == "free"


def test_main_acquire_then_release_roundtrip(lock_path, monkeypatch, capsys):
    monkeypatch.setattr(al.sys, "argv", ["archive_lock", "acquire", "fanout-A"])
    assert al.main() == 0
    assert al._read_lock()["owner"] == "fanout-A"
    capsys.readouterr()

    monkeypatch.setattr(al.sys, "argv", ["archive_lock", "release", "fanout-A"])
    assert al.main() == 0
    assert not lock_path.exists()
    assert "released fanout-A" in capsys.readouterr().out


def test_main_release_force_flag(lock_path, monkeypatch, capsys):
    _write_lock_file(lock_path, owner="orphan", acquired_at=al._now_iso())
    monkeypatch.setattr(
        al.sys, "argv", ["archive_lock", "release", "anyone", "--force"]
    )
    assert al.main() == 0
    assert not lock_path.exists()
    assert "force-released" in capsys.readouterr().out
