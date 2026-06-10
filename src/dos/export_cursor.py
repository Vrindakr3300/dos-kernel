"""export_cursor — the resumable drain offset for `dos export` (docs/266 Phase 4).

The verdict exporter (`dos.exporter` + the `file`/`statsd`/`otlp` drivers) drains the
verdict journal forward; the cursor is *how far it got*. It is the journal's OWN
monotonic `seq` (nothing fabricated — the docs/262 spine key, the `--since` offset
Phases 1–3 already carry on every `ExportResult.cursor`), persisted to a tiny file so a
repeated `dos export` auto-resumes WITHOUT the operator threading the number forward by
hand.

Why a separate module, not `exporter.py`
=========================================

`exporter.py` is the kernel SEAM — a pure Protocol + resolver + fail-soft wrapper, the
`notify.py` shape, deliberately import-light and (apart from entry-point discovery)
I/O-free. The cursor is WAL-ADJACENT STATE — a one-line file read/written at the drain
boundary, exactly the kind of thing `verdict_journal.py` (a substrate data module) owns,
not the pure seam. So it lives here, resolved as a sibling of the verdict journal (the
`verdict_journal._default_journal_path` idiom), with the same fail-soft posture: a read
that cannot parse returns 0 (drain from the start), a write that fails is swallowed (a
cursor-persistence failure must never crash the drain — the `verdict_journal.record`
contract, inherited).

Host-cadence-free (the kernel ships no daemon)
==============================================

The cursor makes the drain RESUMABLE; it does NOT make it a daemon. A fleet drives the
*cadence* — `dos export --to file --since auto` on a `/loop`/cron tick reads the cursor,
ships the new tail, writes the cursor back. The kernel owns the OFFSET, the host owns the
CLOCK (the `dos notify` / `dos top` posture: no `while True` in the kernel). The
`--follow` convenience verb is a BOUNDED foreground loop (it always terminates on a max
iteration / a quiet streak), never an unbounded blocker.

The file is `.dos/export-cursor` (docs/266 §4) — a sibling of the journal it tracks, one
line: the highest `seq` shipped. A per-transport suffix keeps two destinations
(a file shipper + an OTLP collector) from clobbering each other's progress.
"""

from __future__ import annotations

import os
from pathlib import Path

from dos import config as _config

# The workspace-neutral env override (parallel to DISPATCH_VERDICT_JOURNAL_PATH). Points
# at the cursor FILE (or its stem when a per-transport suffix is appended).
_ENV_PATH = "DISPATCH_EXPORT_CURSOR_PATH"

# The sentinel a CLI passes for `--since` to mean "read the persisted cursor" rather than
# an explicit integer. Kept here so the verb and the helpers agree on the spelling.
AUTO = "auto"


def _default_cursor_path() -> Path:
    """The active workspace's export-cursor file — `.dos/export-cursor`, a journal sibling.

    Mirrors `verdict_journal._default_journal_path`: derive it from the resolved verdict
    journal (so a `DISPATCH_VERDICT_JOURNAL_PATH` redirect carries the cursor along), or
    fall back to a lane-journal sibling when the layout field is unset."""
    paths = _config.active().paths
    vj = getattr(paths, "verdict_journal", None)
    base = Path(vj) if vj is not None else Path(paths.lane_journal).with_name(
        "verdict-journal.jsonl")
    return base.with_name("export-cursor")


def cursor_path(path: Path | None = None, *, transport: str = "") -> Path:
    """Resolve the cursor file: explicit arg › env override › `.dos/export-cursor`.

    `transport` (when given) is appended as a `.<transport>` suffix so distinct
    destinations track independent progress — `.dos/export-cursor.file` vs
    `.dos/export-cursor.otlp` — and a `dos export --to file` drain never advances the
    cursor an OTLP drain reads. Re-read each call so a test that sets the env var after
    import still redirects (the lane-journal idiom)."""
    if path is not None:
        base = Path(path)
    else:
        env = os.environ.get(_ENV_PATH)
        base = Path(env) if env else _default_cursor_path()
    if transport:
        return base.with_name(f"{base.name}.{transport}")
    return base


def read_cursor(path: Path | None = None, *, transport: str = "") -> int:
    """The persisted cursor (highest seq shipped), or 0 when none/unreadable. FAIL-SOFT.

    A missing file, an empty file, or a non-integer body all return 0 — "drain from the
    start," the safe default (re-shipping a few events is harmless and idempotent for a
    file/statsd/otlp sink; never advancing past unread events is the failure to avoid).
    Never raises (the `verdict_journal.read_all` posture)."""
    p = cursor_path(path, transport=transport)
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def write_cursor(value: int, path: Path | None = None, *, transport: str = "") -> bool:
    """Persist `value` as the new cursor. Returns True on success, False on failure. FAIL-SOFT.

    The dir is created on demand (`mkdir(parents=True)`, like the journal writers). A
    write failure (full disk, permission) is swallowed and reported as False — a
    cursor-persistence failure must never crash the drain that produced the events (the
    `verdict_journal.record` fail-soft contract). A negative/zero value is written as-is
    (0 is the honest "nothing shipped yet" cursor)."""
    p = cursor_path(path, transport=transport)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{int(value)}\n", encoding="utf-8")
        return True
    except Exception:
        return False


def resolve_since(since_arg: str, *, path: Path | None = None, transport: str = "") -> tuple[int, bool]:
    """Turn a `--since` value into (seq, auto). Pure-ish (reads the cursor only for AUTO).

    Returns `(seq, auto)` where `auto` is True iff the operator passed the `AUTO` sentinel
    (so the verb knows to WRITE the cursor back after a successful drain). The mapping:

      * "" / missing      → (0, False)   — no slice, drain everything; do NOT persist
      * "auto"            → (read_cursor(), True) — resume from the persisted cursor,
                            and persist the new high-water mark after the drain
      * an integer string → (int, False) — explicit one-shot offset; do NOT persist

    A non-integer, non-`auto` value raises ValueError (an operator typo, surfaced at the
    boundary — the `resolve_notifier` loud-on-bad-input rule). So a `/loop` runs
    `dos export --since auto` and the cursor threads itself; a human debugging runs
    `--since 42` for a one-shot without disturbing the persisted offset.
    """
    s = (since_arg or "").strip()
    if not s:
        return (0, False)
    if s.lower() == AUTO:
        return (read_cursor(path, transport=transport), True)
    return (int(s), False)  # raises ValueError on a bad token — caught at the boundary
