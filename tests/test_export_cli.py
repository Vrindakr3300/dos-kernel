"""`dos export` CLI wiring (docs/266) — since-slice + exit codes + null-default safety.

Drives `cmd_export` directly with a fake argparse namespace and a redirected verdict
journal (`DISPATCH_VERDICT_JOURNAL_PATH`), so NOTHING touches a real workspace or the
network. Pins the safe-by-default contract: the default `null` exporter reports + ships
nothing (exit 0), an unknown `--to` fails loud (exit 2), a `--since` cursor slices the
drain, and a REAL transport that ships nothing while events are pending exits 1 (so a
cron notices) while null / dry-run / an empty journal never do.
"""

from __future__ import annotations

import argparse
import json as _json

import pytest

from dos import cli
from dos import verdict_journal as vj
from dos.verdict_journal import VerdictEvent


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    """A redirected, pre-seeded verdict journal (3 events, seq 1..3)."""
    p = tmp_path / "verdict-journal.jsonl"
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH", str(p))
    for i, (sc, vd) in enumerate(
        [("liveness", "STALLED"), ("efficiency", "WASTEFUL"), ("verify", "SHIPPED")], start=1
    ):
        vj.record(VerdictEvent(syscall=sc, verdict=vd, run_id=f"RID-{i}", seq=i),
                  path=p, stamp_seq=False)
    return p


def _ns(**kw):
    base = dict(
        workspace=".", to="null", path="", host="", port=0, endpoint="",
        since="", tail=0, dry_run=False, json=False,
        follow=False, follow_interval=0.0, follow_max=0,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_null_default_reports_and_ships_nothing_exit_0(journal, capsys):
    rc = cli.cmd_export(_ns())
    out = capsys.readouterr().out
    assert rc == 0
    assert "3 event(s) pending" in out
    assert "null sink" in out
    assert "cursor: 3" in out


def test_unknown_transport_exits_2(journal, capsys):
    rc = cli.cmd_export(_ns(to="nope"))
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown exporter 'nope'" in err


def test_since_slices_the_drain(journal, capsys):
    """--since 2 drains only events after seq 2 → just the seq-3 verify event."""
    rc = cli.cmd_export(_ns(since="2", json=True))
    out = capsys.readouterr().out
    assert rc == 0
    obj = _json.loads(out)
    assert obj["shipped"] == 1          # only seq 3 survived the slice
    assert obj["since"] == 2
    assert obj["result"]["cursor"] == "3"


def test_since_at_head_drains_nothing(journal, capsys):
    rc = cli.cmd_export(_ns(since="3", json=True))
    obj = _json.loads(capsys.readouterr().out)
    assert rc == 0
    assert obj["shipped"] == 0          # nothing past seq 3
    assert obj["result"]["cursor"] == ""  # empty batch → no advance


def test_bad_since_exits_2(journal, capsys):
    rc = cli.cmd_export(_ns(since="not-a-number"))
    err = capsys.readouterr().err
    assert rc == 2
    assert "--since must be an integer" in err


def test_file_transport_round_trip_exit_0(journal, tmp_path, capsys):
    out_file = tmp_path / "shipped.jsonl"
    rc = cli.cmd_export(_ns(to="file", path=str(out_file)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "shipped 3/3 via file" in out
    assert len(out_file.read_text(encoding="utf-8").splitlines()) == 3


def test_file_transport_no_path_exits_1(journal, tmp_path, monkeypatch, capsys):
    """A REAL transport asked to ship pending events but shipping none → exit 1
    (cron-alertable). The `file` driver with no path is the 'down collector' case."""
    monkeypatch.delenv("DOS_EXPORT_FILE", raising=False)
    rc = cli.cmd_export(_ns(to="file", path="", workspace=str(tmp_path)))
    out = capsys.readouterr().out
    assert rc == 1
    assert "NOT shipped 0/3" in out


def test_file_dry_run_exits_0(journal, tmp_path, capsys):
    """A dry-run ships nothing but is a success no-op (must not exit non-zero)."""
    out_file = tmp_path / "shipped.jsonl"
    rc = cli.cmd_export(_ns(to="file", path=str(out_file), dry_run=True))
    assert rc == 0
    assert not out_file.exists()


def test_empty_journal_real_transport_exits_0(tmp_path, monkeypatch, capsys):
    """A real transport against an EMPTY journal has nothing pending → exit 0, not 1
    (an empty drain is an honest success, not a broken collector)."""
    p = tmp_path / "empty.jsonl"
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH", str(p))
    monkeypatch.delenv("DOS_EXPORT_FILE", raising=False)
    rc = cli.cmd_export(_ns(to="file", path=str(tmp_path / "out.jsonl")))
    assert rc == 0


def test_tail_caps_before_since(journal, capsys):
    """--tail 1 takes only the last journal event before the --since slice."""
    rc = cli.cmd_export(_ns(tail=1, json=True))
    obj = _json.loads(capsys.readouterr().out)
    assert rc == 0
    assert obj["shipped"] == 1  # only the last (seq-3) event


def test_json_output_shape(journal, capsys):
    rc = cli.cmd_export(_ns(json=True))
    obj = _json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(obj) == {"result", "exporter", "shipped", "since", "persist"}
    assert obj["exporter"] == "null"
    assert obj["shipped"] == 3
    assert obj["persist"] is False
    assert set(obj["result"]) == {"exported", "detail", "cursor"}


# =====================================================================================
# Phase 4 — cursor persistence (--since auto) + the bounded --follow loop
# =====================================================================================


@pytest.fixture()
def cursor(tmp_path, monkeypatch):
    """Redirect the export-cursor file so tests never touch the real workspace."""
    monkeypatch.setenv("DISPATCH_EXPORT_CURSOR_PATH", str(tmp_path / "export-cursor"))
    monkeypatch.delenv("DOS_EXPORT_FILE", raising=False)
    return tmp_path / "export-cursor"


def test_since_auto_persists_cursor_after_a_real_ship(journal, cursor, tmp_path, capsys):
    """--since auto with a real transport: ships the tail AND writes the high-water seq
    to .dos/export-cursor.<transport>, so the next drain resumes past it."""
    from dos import export_cursor as ec
    out_file = tmp_path / "shipped.jsonl"
    rc = cli.cmd_export(_ns(to="file", path=str(out_file), since="auto"))
    assert rc == 0
    assert len(out_file.read_text(encoding="utf-8").splitlines()) == 3
    # cursor advanced to the highest shipped seq (3), under the per-transport suffix
    assert ec.read_cursor(transport="file") == 3
    # a SECOND auto drain now resumes from 3 → nothing new to ship
    out2 = capsys.readouterr()  # drain stdout
    rc2 = cli.cmd_export(_ns(to="file", path=str(out_file), since="auto", json=True))
    obj = _json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert obj["shipped"] == 0           # resumed past seq 3
    assert obj["since"] == 3
    # the file did not grow (no re-ship)
    assert len(out_file.read_text(encoding="utf-8").splitlines()) == 3


def test_since_auto_does_not_persist_for_null(journal, cursor, capsys):
    """null ships nothing → the cursor must NOT advance past unshipped events (fail-soft:
    persist only when a real transport actually shipped)."""
    from dos import export_cursor as ec
    rc = cli.cmd_export(_ns(to="null", since="auto"))
    assert rc == 0
    assert ec.read_cursor(transport="null") == 0   # not advanced


def test_since_auto_does_not_persist_on_dry_run(journal, cursor, tmp_path, capsys):
    from dos import export_cursor as ec
    rc = cli.cmd_export(_ns(to="file", path=str(tmp_path / "o.jsonl"),
                            since="auto", dry_run=True))
    assert rc == 0
    assert ec.read_cursor(transport="file") == 0   # dry-run never advances


def test_since_auto_does_not_persist_when_ship_fails(journal, cursor, tmp_path, capsys):
    """A real transport that ships NOTHING (no path) must not advance the cursor."""
    from dos import export_cursor as ec
    rc = cli.cmd_export(_ns(to="file", path="", since="auto", workspace=str(tmp_path)))
    assert rc == 1                                  # broken transport
    assert ec.read_cursor(transport="file") == 0   # cursor held


def test_explicit_integer_since_does_not_persist(journal, cursor, tmp_path, capsys):
    """An explicit --since N is a one-shot; it must NOT write the cursor (only `auto`/
    `--follow` persist)."""
    from dos import export_cursor as ec
    out_file = tmp_path / "o.jsonl"
    rc = cli.cmd_export(_ns(to="file", path=str(out_file), since="2"))
    assert rc == 0
    assert ec.read_cursor(transport="file") == 0   # explicit one-shot does not persist


def test_since_auto_invalid_token_exits_2(journal, cursor, capsys):
    rc = cli.cmd_export(_ns(since="bogus"))
    err = capsys.readouterr().err
    assert rc == 2
    assert "integer seq cursor or 'auto'" in err


def test_follow_bounded_terminates_and_persists(journal, cursor, tmp_path, capsys):
    """--follow with --follow-max 2 runs exactly 2 ticks then returns (NOT a daemon).
    First tick ships the 3 events + persists; second tick has nothing new."""
    from dos import export_cursor as ec
    out_file = tmp_path / "follow.jsonl"
    rc = cli.cmd_export(_ns(to="file", path=str(out_file), since="auto",
                            follow=True, follow_interval=0.0, follow_max=2))
    out = capsys.readouterr().out
    assert rc == 0
    # two ticks rendered
    assert out.count("# export ·") == 2
    # the 3 events shipped exactly once (the follow loop advanced its floor)
    assert len(out_file.read_text(encoding="utf-8").splitlines()) == 3
    assert ec.read_cursor(transport="file") == 3


def test_follow_advances_floor_across_ticks_when_new_events_land(cursor, tmp_path, monkeypatch, capsys):
    """A second tick that sees a NEWLY-appended event ships only that one (the floor
    advanced past tick-1's events)."""
    from dos import verdict_journal as vj
    from dos.verdict_journal import VerdictEvent
    jp = tmp_path / "vj.jsonl"
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH", str(jp))
    vj.record(VerdictEvent(syscall="liveness", verdict="STALLED", seq=1), path=jp, stamp_seq=False)

    out_file = tmp_path / "follow2.jsonl"
    # tick 1 ships seq-1; then we append seq-2 BEFORE tick 2 via follow_max=1 twice.
    rc1 = cli.cmd_export(_ns(to="file", path=str(out_file), since="auto",
                             follow=True, follow_interval=0.0, follow_max=1))
    assert rc1 == 0
    assert len(out_file.read_text(encoding="utf-8").splitlines()) == 1
    # a new event lands
    vj.record(VerdictEvent(syscall="verify", verdict="SHIPPED", seq=2), path=jp, stamp_seq=False)
    capsys.readouterr()
    rc2 = cli.cmd_export(_ns(to="file", path=str(out_file), since="auto",
                             follow=True, follow_interval=0.0, follow_max=1, json=True))
    obj = _json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert obj["shipped"] == 1                # only the new seq-2 event
    assert len(out_file.read_text(encoding="utf-8").splitlines()) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
