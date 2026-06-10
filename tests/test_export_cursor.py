"""The export-cursor (`dos.export_cursor`) — resumable drain offset, fail-soft (docs/266 Phase 4).

Covers the cursor read/write/resolve helpers in isolation: the path resolution ladder
(explicit › env › `.dos/export-cursor` sibling), the per-transport suffix, the fail-soft
read (missing/empty/non-int → 0) and write (failure → False, never a raise), and
`resolve_since`'s mapping ("" → no-slice, integer → one-shot, `auto` → read-cursor +
persist-flag, garbage → ValueError).
"""

from __future__ import annotations

import pytest

from dos import export_cursor as ec


# =====================================================================================
# path resolution
# =====================================================================================


def test_cursor_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_EXPORT_CURSOR_PATH", str(tmp_path / "cur"))
    assert ec.cursor_path() == tmp_path / "cur"


def test_cursor_path_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_EXPORT_CURSOR_PATH", str(tmp_path / "env"))
    assert ec.cursor_path(tmp_path / "explicit") == tmp_path / "explicit"


def test_cursor_path_per_transport_suffix(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_EXPORT_CURSOR_PATH", str(tmp_path / "export-cursor"))
    assert ec.cursor_path(transport="file") == tmp_path / "export-cursor.file"
    assert ec.cursor_path(transport="otlp") == tmp_path / "export-cursor.otlp"
    # distinct transports → distinct files (no clobber)
    assert ec.cursor_path(transport="file") != ec.cursor_path(transport="otlp")


def test_cursor_path_default_is_journal_sibling(monkeypatch):
    """With no override, the cursor sits beside the verdict journal (.dos/export-cursor)."""
    from dos import config as cfg
    p = ec.cursor_path()
    assert p.name == "export-cursor"
    # same dir as the verdict journal
    vj = getattr(cfg.active().paths, "verdict_journal", None)
    if vj is not None:
        from pathlib import Path
        assert p.parent == Path(vj).parent


# =====================================================================================
# read / write — fail-soft
# =====================================================================================


def test_read_missing_is_zero(tmp_path):
    assert ec.read_cursor(tmp_path / "nope") == 0


def test_write_then_read_round_trip(tmp_path):
    p = tmp_path / "cur"
    assert ec.write_cursor(42, p) is True
    assert ec.read_cursor(p) == 42


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "nested" / "deep" / "cur"
    assert ec.write_cursor(7, p) is True
    assert ec.read_cursor(p) == 7


def test_read_empty_or_garbage_is_zero(tmp_path):
    p = tmp_path / "cur"
    p.write_text("", encoding="utf-8")
    assert ec.read_cursor(p) == 0
    p.write_text("not-a-number\n", encoding="utf-8")
    assert ec.read_cursor(p) == 0


def test_write_is_fail_soft_on_bad_target(tmp_path):
    """A write to an impossible target returns False, never raises (a cursor-persistence
    failure must not crash the drain). We point at a path whose parent is a FILE."""
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    target = blocker / "cur"   # parent is a file → mkdir/write fails
    assert ec.write_cursor(5, target) is False


def test_round_trip_per_transport_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_EXPORT_CURSOR_PATH", str(tmp_path / "export-cursor"))
    ec.write_cursor(10, transport="file")
    ec.write_cursor(99, transport="otlp")
    assert ec.read_cursor(transport="file") == 10
    assert ec.read_cursor(transport="otlp") == 99   # independent


# =====================================================================================
# resolve_since — the --since mapping
# =====================================================================================


def test_resolve_since_empty_is_no_slice():
    assert ec.resolve_since("") == (0, False)        # drain everything, do not persist
    assert ec.resolve_since("   ") == (0, False)


def test_resolve_since_integer_is_one_shot():
    assert ec.resolve_since("42") == (42, False)     # explicit offset, do not persist


def test_resolve_since_auto_reads_cursor_and_flags_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_EXPORT_CURSOR_PATH", str(tmp_path / "export-cursor"))
    ec.write_cursor(17, transport="file")
    seq, auto = ec.resolve_since("auto", transport="file")
    assert (seq, auto) == (17, True)                 # resume from persisted, persist after
    # case-insensitive
    assert ec.resolve_since("AUTO", transport="file") == (17, True)


def test_resolve_since_auto_with_no_cursor_is_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_EXPORT_CURSOR_PATH", str(tmp_path / "export-cursor"))
    assert ec.resolve_since("auto", transport="file") == (0, True)  # from the start


def test_resolve_since_garbage_raises():
    with pytest.raises(ValueError):
        ec.resolve_since("twelve")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
