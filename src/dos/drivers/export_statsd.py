"""dos.drivers.export_statsd — the StatsD/DogStatsD occupant of `dos.exporter` (docs/266).

The second connector behind the verdict exporter, and the native METRICS path. Where
`export_file` re-emits the journal lines for a log shipper to parse, THIS driver turns
the verdict stream into COUNTERS — one increment per `(syscall, verdict)` pair — so a
time-series backend charts "liveness STALLED per minute" or "efficiency WASTEFUL events
per run" without a log-parsing rule in between. It speaks the StatsD line protocol over
UDP (the lingua franca Datadog's DogStatsD, Telegraf, Vector, and statsd_exporter all
ingest). It registers through the `dos.exporters` entry-point group, so
`resolve_exporter("statsd")` finds it by name and no kernel module imports it.

Why it ships in the core (no extra)
===================================

The StatsD protocol is a one-line UDP datagram — `stdlib socket` is all it needs, no
client library. So this driver adds NO dependency and ships in the core, the same as
`export_file` (only the OTLP driver pulls a real SDK, behind `[export-otlp]`).

The line it emits (the DogStatsD form, docs/266 §2)
===================================================

    dos.verdict:1|c|#syscall:liveness,verdict:STALLED

One COUNTER (`|c|`) per distinct `(syscall, verdict)` in the batch, its value the count
of matching events, tagged `syscall:` + `verdict:` (DogStatsD `|#tag:val` extension —
what Datadog/Telegraf/Vector accept; a plain-StatsD collector ignores the tag suffix and
still counts the metric). Aggregating identical pairs into one datagram (rather than one
per event) keeps the wire traffic proportional to the verdict CARDINALITY, not the event
count — a fleet that emits 10k ADVANCING verdicts sends one `…:10000|c|…` line. The
`run_id`/`lane` are deliberately NOT tags: they are high-cardinality (one series per run
would explode a metrics backend), and the per-run history already lives in `dos observe
--run`. Metrics are for trends; the journal/`observe` is for drill-down.

Disciplines (inherited from the seam — the `export_file`/`notify_webhook` posture)
==================================================================================

  * **Fail-soft.** `export` returns an `ExportResult`, never raises — an unroutable host,
    a closed socket, a send error all degrade to `exported=0` with a one-line reason. UDP
    is fire-and-forget, so a "successful" send only means the datagram left the host; that
    is the strongest delivery guarantee StatsD offers and we report it honestly.
  * **Advisory only.** It reads a batch → sends counters. It mutates no DOS state, takes
    no lease, stops no run, adjudicates nothing.

Routing
=======

  * **host**: explicit arg › `$DOS_STATSD_HOST` › `<root>/.env` › `127.0.0.1`.
  * **port**: explicit arg › `$DOS_STATSD_PORT` › `<root>/.env` › `8125`.
  * **prefix**: the metric name (default `dos.verdict`); override for a namespaced shop.
"""

from __future__ import annotations

import os
from pathlib import Path

from dos.exporter import ExportResult, _max_seq_cursor

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8125
_DEFAULT_PREFIX = "dos.verdict"


def _read_env_file(root: Path) -> dict[str, str]:
    """Best-effort parse of `<root>/.env` → {KEY: value}. Never raises.

    The `export_file._read_env_file` twin (same parser, different keys)."""
    out: dict[str, str] = {}
    try:
        text = (root / ".env").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def resolve_host(explicit: str | None, *, root: Path | None) -> str:
    """StatsD host: explicit arg › `$DOS_STATSD_HOST` › `<root>/.env` › 127.0.0.1."""
    if explicit:
        return explicit
    env = os.environ.get("DOS_STATSD_HOST")
    if env:
        return env
    if root is not None:
        v = _read_env_file(root).get("DOS_STATSD_HOST")
        if v:
            return v
    return _DEFAULT_HOST


def resolve_port(explicit: int | None, *, root: Path | None) -> int:
    """StatsD port: explicit arg › `$DOS_STATSD_PORT` › `<root>/.env` › 8125.

    A non-numeric override anywhere degrades to the default rather than raising."""
    if explicit:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            return _DEFAULT_PORT
    for raw in (os.environ.get("DOS_STATSD_PORT"),
                (_read_env_file(root).get("DOS_STATSD_PORT") if root is not None else None)):
        if raw:
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
    return _DEFAULT_PORT


def _sanitize_tag(value: str) -> str:
    """Make a tag value safe for the StatsD line: strip the metric delimiters.

    `|`, `:`, `,`, `#`, and whitespace are the StatsD/DogStatsD line separators — a
    verdict token or syscall name containing one (none of the kernel's closed sets do,
    but a host driver's custom verdict might) would corrupt the datagram. We replace each
    with `_` so a hostile/odd token degrades to a still-parseable tag, never a malformed
    line (the byte-clean posture extended to the wire)."""
    out = str(value)
    for ch in ("|", ":", ",", "#", " ", "\n", "\t", "\r"):
        out = out.replace(ch, "_")
    return out or "none"


def build_lines(events, *, prefix: str = _DEFAULT_PREFIX) -> list[str]:
    """A batch of `VerdictEvent`s → the StatsD counter lines (pure; no I/O).

    Aggregates identical `(syscall, verdict)` pairs into ONE counter line whose value is
    the count, so wire traffic scales with verdict cardinality, not event count. Sorted
    by (syscall, verdict) so the output is deterministic (golden-bytes testable). The
    spine's analogue of `notify_webhook.build_payload` / `export_file`'s line builder —
    kept pure and out of the kernel seam.
    """
    counts: dict[tuple[str, str], int] = {}
    for e in events:
        key = (getattr(e, "syscall", "") or "none", getattr(e, "verdict", "") or "none")
        counts[key] = counts.get(key, 0) + 1
    lines: list[str] = []
    for (syscall, verdict), n in sorted(counts.items()):
        tags = f"syscall:{_sanitize_tag(syscall)},verdict:{_sanitize_tag(verdict)}"
        lines.append(f"{prefix}:{n}|c|#{tags}")
    return lines


class _UdpTransport:
    """The stdlib UDP send. Returns the byte count sent; raises on a socket error.

    Kept behind a method so tests inject a fake with the same `send(host, port, lines)`
    shape instead of patching socket (the `notify_webhook._UrllibTransport` posture).
    One datagram per line (StatsD convention; a multi-metric datagram is an optimization
    a real shop's local agent does, not us)."""

    def send(self, host: str, port: int, lines: list[str]) -> int:
        import socket

        sent = 0
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for line in lines:
                payload = line.encode("utf-8")
                sock.sendto(payload, (host, int(port)))
                sent += len(payload)
        finally:
            sock.close()
        return sent


class StatsdExporter:
    """Drain a batch of `VerdictEvent`s as StatsD counters over UDP.

    Parameters
    ----------
    host:
        StatsD/DogStatsD host; defaults to `$DOS_STATSD_HOST` / `.env` / 127.0.0.1.
    port:
        StatsD port; defaults to `$DOS_STATSD_PORT` / `.env` / 8125.
    prefix:
        The counter metric name (default `dos.verdict`).
    root:
        Workspace root for `.env` resolution (the `SubstrateConfig.root`).
    dry_run:
        Resolve + build the lines + report, send NOTHING.
    transport:
        Inject a fake with a `send(host, port, lines) -> int` method in tests; None uses
        the stdlib UDP transport.

    The constructor accepts-and-ignores the export CLI's `path`/`endpoint` superset
    kwargs by NOT declaring them — `exporter._accepted_kwargs` filters the bag to the
    params below, so a caller hands the same kwargs to any transport without branching.
    """

    name = "statsd"

    def __init__(self, *, host: str = "", port: int = 0, prefix: str = _DEFAULT_PREFIX,
                 root: "os.PathLike[str] | str | None" = None,
                 dry_run: bool = False, transport=None):
        self._host_arg = host
        self._port_arg = port
        self._prefix = prefix or _DEFAULT_PREFIX
        self._root = Path(root) if root is not None else None
        self._dry_run = bool(dry_run)
        self._transport = transport

    def export(self, events) -> ExportResult:
        """Send one counter per (syscall, verdict). Returns an `ExportResult`; NEVER raises."""
        cursor = _max_seq_cursor(events)
        n = len(events)
        host = resolve_host(self._host_arg, root=self._root)
        port = resolve_port(self._port_arg, root=self._root)

        if n == 0:
            return ExportResult(
                exported=0, detail=f"no new events for {host}:{port}", cursor=cursor)

        lines = build_lines(events, prefix=self._prefix)

        if self._dry_run:
            return ExportResult(
                exported=0,
                detail=f"[dry-run] would send {len(lines)} counter(s) "
                       f"for {n} event(s) to {host}:{port}",
                cursor=cursor,
            )

        transport = self._transport if self._transport is not None else _UdpTransport()
        try:
            transport.send(host, port, lines)
        except Exception as e:  # noqa: BLE001 - advisory; report, don't crash the producer
            return ExportResult(exported=0, detail=f"error: {e}", cursor=cursor)

        # UDP is fire-and-forget: a clean send means the datagrams left this host, which
        # is the strongest guarantee StatsD offers. We count the EVENTS exported (what
        # the operator asked to ship), and note the counter line count in the detail.
        return ExportResult(
            exported=n,
            detail=f"sent {len(lines)} counter(s) for {n} event(s) to {host}:{port}",
            cursor=cursor,
        )
