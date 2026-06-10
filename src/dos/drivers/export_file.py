"""dos.drivers.export_file — the append-to-a-file occupant of `dos.exporter` (docs/266).

The first connector behind the verdict exporter, and the KEYSTONE one. Where the
kernel seam (`dos.exporter`) is transport-agnostic and names no transport, THIS is
where "append to a path" is allowed to be code — and it names no SPECIFIC vendor: it
re-emits each `VerdictEvent` as one JSONL line to an operator-chosen path, so the one
driver reaches *most* of the observability market for free. A JSONL stream at a path is
the universal adapter — Datadog's agent, Vector, Fluent Bit, Promtail, Splunk's
forwarder, and `logger(1)` all tail a file. It registers through the `dos.exporters`
entry-point group, so `resolve_exporter("file")` finds it by name and no kernel module
imports it.

Why it ships in the core (no extra)
===================================

A file append needs only `pathlib` + `json` from the standard library. So this driver
adds NO dependency and ships in the core install — a `pip install dos-kernel` can
already drain its verdict journal to any log shipper. (The StatsD driver is also
stdlib; only the OTLP driver pulls a real SDK, behind the `[export-otlp]` extra.)

The shape it writes
===================

ONE line per event — the event's own `to_record()` JSON (schema-tagged, byte-clean
`detail`), the SAME line shape the verdict journal itself writes. That is deliberate:
the export target is just a SECOND copy of the journal lines at a path a shipper
already watches, so a downstream parser that already understands a DOS verdict record
needs no new schema. The append is `O_APPEND` + line-buffered so concurrent appenders
(a `--follow` drain + a fresh run) never interleave a single line.

Disciplines (inherited from the seam — the `notify_webhook` posture, verbatim)
==============================================================================

  * **Fail-soft.** `export` returns an `ExportResult`, never raises — no path, an
    unwritable directory, a full disk, or a non-serializable field all degrade to
    `exported=0` with a one-line reason. (The seam's `export_safely` is the outer net;
    this is the inner one, so even a direct `FileExporter().export(...)` is crash-free.)
  * **Advisory only.** It reads a batch → appends lines. It mutates no DOS state, takes
    no lease, stops no run, adjudicates nothing. It does NOT rotate or cap the file —
    that is the log shipper's job (and docs/262 Phase 4's `[retention]` for the journal
    itself); a file exporter writes, the shipper consumes + truncates.

Routing (the `notify_webhook.resolve_url` ladder, generalized to a path)
========================================================================

  * **path**: explicit arg › `$DOS_EXPORT_FILE` › the workspace `.env`
    (`<root>/.env`'s `DOS_EXPORT_FILE`). No path anywhere → a non-exported result. A
    relative path resolves against the workspace `root` (so `--path verdicts.jsonl`
    lands under the workspace, not the cwd of whatever drove the drain).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dos.exporter import ExportResult, _max_seq_cursor


def _read_env_file(root: Path) -> dict[str, str]:
    """Best-effort parse of `<root>/.env` → {KEY: value}. Never raises.

    The `notify_webhook._read_env_file` twin (same parser, different key)."""
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


def resolve_path(explicit: str | None, *, root: Path | None) -> str:
    """Export path: explicit arg › `$DOS_EXPORT_FILE` › `<root>/.env`. "" if none.

    A relative result is resolved against `root` so the export lands under the workspace
    regardless of the drain's cwd (the `SubstrateConfig.root` anchor; the package never
    assumes it lives in the repo it serves)."""
    raw = explicit or os.environ.get("DOS_EXPORT_FILE") or ""
    if not raw and root is not None:
        raw = _read_env_file(root).get("DOS_EXPORT_FILE", "")
    if not raw:
        return ""
    p = Path(raw)
    if not p.is_absolute() and root is not None:
        p = Path(root) / p
    return str(p)


class FileExporter:
    """Drain a batch of `VerdictEvent`s by appending each as one JSONL line to a path.

    Parameters
    ----------
    path:
        The export file; defaults to `$DOS_EXPORT_FILE` / the workspace `.env`
        (`resolve_path`). A relative path resolves against `root`.
    root:
        Workspace root for `.env` + relative-path resolution (the `SubstrateConfig.root`).
    dry_run:
        Resolve + count + report what WOULD be written, write NOTHING.

    The constructor accepts-and-ignores the export CLI's other superset kwargs
    (`host`/`port`/`endpoint`) only by NOT declaring them — `exporter._accepted_kwargs`
    filters the bag to the params below, so a caller can hand the same kwargs to any
    transport without branching per driver.
    """

    name = "file"

    def __init__(self, *, path: str = "",
                 root: "os.PathLike[str] | str | None" = None,
                 dry_run: bool = False):
        self._path_arg = path
        self._root = Path(root) if root is not None else None
        self._dry_run = bool(dry_run)

    def export(self, events) -> ExportResult:
        """Append each event as a JSONL line. Returns an `ExportResult`; NEVER raises."""
        path = resolve_path(self._path_arg, root=self._root)
        cursor = _max_seq_cursor(events)
        n = len(events)
        if not path:
            return ExportResult(
                exported=0,
                detail="no export path (pass --path, set $DOS_EXPORT_FILE, "
                       "or add DOS_EXPORT_FILE to the workspace .env)",
                cursor=cursor,
            )

        if self._dry_run:
            return ExportResult(
                exported=0,
                detail=f"[dry-run] would append {n} event(s) to {path}",
                cursor=cursor,
            )

        if n == 0:
            # Nothing to ship — a perfectly normal drain when no new events landed.
            return ExportResult(exported=0, detail=f"no new events for {path}", cursor=cursor)

        # Build all the lines first; a single non-serializable field fails the whole
        # batch cleanly (fail-soft) rather than writing a partial file then raising.
        try:
            lines = [
                json.dumps(e.to_record(), ensure_ascii=False, sort_keys=True)
                for e in events
            ]
        except Exception as e:  # noqa: BLE001 - a bad field must not crash the drain
            return ExportResult(
                exported=0, detail=f"error: event not serializable: {e}", cursor=cursor)

        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            # O_APPEND keeps concurrent appends from interleaving a single line (the
            # verdict_journal.record discipline); we flush so a tailing shipper sees the
            # lines promptly. No fsync here — the journal is the durable WAL; this is a
            # best-effort outward copy, and an fsync per drain would throttle a follow loop.
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
                fh.flush()
        except Exception as e:  # noqa: BLE001 - advisory; report, don't crash the producer
            return ExportResult(exported=0, detail=f"error: {e}", cursor=cursor)

        return ExportResult(
            exported=n, detail=f"appended {n} event(s) to {path}", cursor=cursor)
