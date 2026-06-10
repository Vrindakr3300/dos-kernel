"""The `statsd` exporter driver (`dos.drivers.export_statsd`) — golden bytes, no network (docs/266).

Pins the StatsD/DogStatsD wire format against a fixed batch (a fake socket transport, so
NOTHING touches the network), plus the seam disciplines inherited from `dos.exporter`:
fail-soft on a raising transport, aggregation by (syscall, verdict), tag sanitization,
the host/port resolution ladder, and discovery-by-name through the entry-point group.
"""

from __future__ import annotations

import pytest

from dos.exporter import resolve_exporter, export_safely, active_exporter_names
from dos.drivers.export_statsd import (
    StatsdExporter,
    build_lines,
    resolve_host,
    resolve_port,
    _sanitize_tag,
)
from dos.verdict_journal import VerdictEvent


def _ev(syscall, verdict, *, seq=0):
    return VerdictEvent(syscall=syscall, verdict=verdict, seq=seq, ts="2026-06-09T00:00:00Z")


class _FakeSocket:
    """Records (host, port, lines) instead of sending; the injected transport."""

    def __init__(self, *, boom: bool = False):
        self.calls: list[tuple[str, int, list[str]]] = []
        self._boom = boom

    def send(self, host, port, lines) -> int:
        if self._boom:
            raise OSError("network unreachable")
        self.calls.append((host, port, list(lines)))
        return sum(len(l.encode()) for l in lines)


# =====================================================================================
# golden bytes — the exact lines for a fixed batch
# =====================================================================================


def test_build_lines_golden():
    """One counter per distinct (syscall, verdict), value = count, DogStatsD tags,
    sorted deterministically."""
    batch = [
        _ev("liveness", "STALLED", seq=1),
        _ev("liveness", "ADVANCING", seq=2),
        _ev("liveness", "ADVANCING", seq=3),   # 2× ADVANCING → one line, value 2
        _ev("efficiency", "WASTEFUL", seq=4),
    ]
    lines = build_lines(batch)
    assert lines == [
        "dos.verdict:1|c|#syscall:efficiency,verdict:WASTEFUL",
        "dos.verdict:2|c|#syscall:liveness,verdict:ADVANCING",
        "dos.verdict:1|c|#syscall:liveness,verdict:STALLED",
    ]


def test_build_lines_custom_prefix():
    lines = build_lines([_ev("verify", "SHIPPED")], prefix="acme.dos")
    assert lines == ["acme.dos:1|c|#syscall:verify,verdict:SHIPPED"]


def test_export_sends_over_the_fake_socket():
    sock = _FakeSocket()
    ex = StatsdExporter(host="10.0.0.5", port=9999, transport=sock)
    res = ex.export([_ev("liveness", "STALLED", seq=7), _ev("verify", "SHIPPED", seq=8)])
    assert res.exported == 2
    assert res.cursor == "8"
    assert "to 10.0.0.5:9999" in res.detail
    # the fake recorded exactly the two counters, at the resolved host/port
    assert len(sock.calls) == 1
    host, port, lines = sock.calls[0]
    assert (host, port) == ("10.0.0.5", 9999)
    assert lines == [
        "dos.verdict:1|c|#syscall:liveness,verdict:STALLED",
        "dos.verdict:1|c|#syscall:verify,verdict:SHIPPED",
    ]


# =====================================================================================
# seam disciplines — fail-soft, dry-run, empty, sanitize, resolution
# =====================================================================================


def test_fail_soft_on_a_raising_transport():
    """An unroutable host / socket error → exported=0, never a raise (export_safely is
    the outer net, but the driver's inner net catches it first)."""
    ex = StatsdExporter(host="bad", transport=_FakeSocket(boom=True))
    res = ex.export([_ev("liveness", "STALLED")])
    assert res.exported == 0
    assert "error:" in res.detail
    assert "network unreachable" in res.detail
    # and through the seam wrapper too
    res2 = export_safely(ex, [_ev("liveness", "STALLED")])
    assert res2.exported == 0


def test_dry_run_sends_nothing():
    sock = _FakeSocket()
    ex = StatsdExporter(host="h", port=1, transport=sock, dry_run=True)
    res = ex.export([_ev("liveness", "STALLED", seq=3)])
    assert res.exported == 0
    assert "[dry-run]" in res.detail
    assert sock.calls == []         # nothing left the host
    assert res.cursor == "3"        # cursor still advances


def test_empty_batch_is_a_clean_noop():
    sock = _FakeSocket()
    res = StatsdExporter(transport=sock).export([])
    assert res.exported == 0
    assert "no new events" in res.detail
    assert sock.calls == []


def test_sanitize_tag_strips_delimiters():
    # the kernel's closed sets never contain these, but a custom host verdict might
    assert _sanitize_tag("we|ird:tok,en#x") == "we_ird_tok_en_x"
    assert _sanitize_tag("") == "none"
    # a sanitized token never breaks the line shape
    line = build_lines([_ev("sys|tem", "ver:dict")])[0]
    assert line == "dos.verdict:1|c|#syscall:sys_tem,verdict:ver_dict"


def test_host_resolution_ladder(tmp_path, monkeypatch):
    monkeypatch.delenv("DOS_STATSD_HOST", raising=False)
    # default
    assert resolve_host("", root=None) == "127.0.0.1"
    # env
    monkeypatch.setenv("DOS_STATSD_HOST", "envhost")
    assert resolve_host("", root=tmp_path) == "envhost"
    # explicit wins
    assert resolve_host("argh", root=tmp_path) == "argh"
    # .env fallback (env unset)
    monkeypatch.delenv("DOS_STATSD_HOST", raising=False)
    (tmp_path / ".env").write_text("DOS_STATSD_HOST=dothost\n", encoding="utf-8")
    assert resolve_host("", root=tmp_path) == "dothost"


def test_port_resolution_ladder(tmp_path, monkeypatch):
    monkeypatch.delenv("DOS_STATSD_PORT", raising=False)
    assert resolve_port(0, root=None) == 8125            # default
    assert resolve_port(9001, root=None) == 9001         # explicit
    monkeypatch.setenv("DOS_STATSD_PORT", "9002")
    assert resolve_port(0, root=tmp_path) == 9002        # env
    monkeypatch.setenv("DOS_STATSD_PORT", "not-a-port")  # bad env → default
    assert resolve_port(0, root=tmp_path) == 8125


def test_resolvable_by_name_and_kwarg_filtered():
    """`resolve_exporter("statsd")` finds it by name and ignores the file driver's
    `path` kwarg (the superset-bag filter)."""
    ex = resolve_exporter("statsd", host="h", port=1234, path="/ignored")
    assert isinstance(ex, StatsdExporter)
    assert ex.name == "statsd"


def test_statsd_in_active_names():
    assert "statsd" in active_exporter_names()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
