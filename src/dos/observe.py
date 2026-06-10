"""`dos observe` — the verdict-journal projection, read-only (docs/262).

The reader over the verdict journal (`verdict_journal`), the way `decisions` reads
the refusal sources and `trace` reads the spine/ledger/WAL/git. It answers the
questions the verdict journal was built to make cheap:

    dos observe                  # fleet-wide rollup: counts per syscall × verdict
    dos observe --run <run_id>   # one run's verdict history, in order
    dos observe --syscall NAME   # filter the rollup/history to one dimension
    dos observe --by verdict     # fold on a different dimension (verdict/run_id/lane/source)
    dos observe --tail N         # the last N raw events
    dos observe --json           # machine-readable (for the trajectory-audit)

It is a **read-only projection**, never a store — the `decisions`/`trace`/`top`
contract: it reads the journal only, takes no lease, mints no belief, adjudicates
*nothing new*. The verdicts it shows were minted by the syscalls; this module only
folds and renders them. Delete it and you lose the reader, not the data.

Pure-where-it-can-be: the fold (`verdict_journal.rollup`/`for_run`) and the render
functions here are pure and are the unit-test surface; the only I/O is the single
`verdict_journal.read_all` at the boundary (mirrors `decisions.collect_decisions` /
`timeline.build_timeline`).
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass
elif not isinstance(sys.stdout, io.TextIOWrapper):  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dos import verdict_journal as _vj


# ---------------------------------------------------------------------------
# The assembled projection — one read, filtered + folded. The render surface.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObserveFrame:
    """What every observe renderer consumes — the filtered events + their rollup.

    `events` is the filtered, append-ordered event list (after `--run`/`--syscall`);
    `rollup` is the fold over them on the requested dimension; `corrupt` is the
    integrity tally (count of `_CORRUPT` sentinel lines in the journal). `run` /
    `syscall_filter` echo the active filters so a renderer can title itself.
    """

    events: tuple[_vj.VerdictEvent, ...]
    rollup: _vj.VerdictRollup
    corrupt: int
    run: str = ""
    syscall_filter: str = ""

    def to_dict(self) -> dict:
        return {
            "run": self.run,
            "syscall_filter": self.syscall_filter,
            "corrupt": self.corrupt,
            "rollup": self.rollup.to_dict(),
            "events": [e.to_dict() for e in self.events],
        }


def build_frame(*, run: str = "", syscall: str = "", by: str = "syscall",
                path=None) -> ObserveFrame:
    """Read the journal once, apply the filters, fold the rest. Read-only.

    `run` filters to one run_id (the `trace` join key); `syscall` filters to one
    dimension; `by` chooses the rollup dimension. A single `read_all` does the I/O;
    everything after is pure (`for_run`/`rollup` + a list-comprehension filter), so
    the assembly is unit-tested without a file the way `decisions.collect_decisions`
    is.
    """
    raw = _vj.read_all(path)
    corrupt = _vj.count_corrupt(raw)
    events = [
        _vj.VerdictEvent.from_record(rec)
        for rec in raw
        if rec.get("op") != "_CORRUPT"
    ]
    if run:
        events = _vj.for_run(events, run)
    if syscall:
        events = [e for e in events if e.syscall == syscall]
    roll = _vj.rollup(events, by=by, corrupt=corrupt)
    return ObserveFrame(
        events=tuple(events),
        rollup=roll,
        corrupt=corrupt,
        run=run,
        syscall_filter=syscall,
    )


# ---------------------------------------------------------------------------
# Rendering — the plain-text floor (rollup table + optional event list).
# ---------------------------------------------------------------------------


def render_rollup_text(frame: ObserveFrame) -> str:
    """The fleet-wide rollup: a compact per-dimension verdict-count table.

    One block per dimension value (a syscall, by default), each listing its verdict
    tokens and counts. Mirrors the small-column idiom of `decisions.render_list_plain`.
    """
    roll = frame.rollup
    out: list[str] = []
    title = "# observe"
    if frame.run:
        title += f" · run {frame.run}"
    if frame.syscall_filter:
        title += f" · syscall {frame.syscall_filter}"
    out.append(title)
    out.append(f"  {roll.total} verdict event(s) recorded"
               + (f", folded by {roll.by}" if roll.by != "syscall" else ""))
    if roll.corrupt:
        out.append(f"  ⚠ {roll.corrupt} corrupt/unreadable journal line(s) "
                   f"(integrity breach — not a torn tail)")
    if not roll.total:
        out.append("  (no verdicts recorded yet — wire a syscall to "
                   "verdict_journal.record, or run with DISPATCH_OBSERVE=1)")
        return "\n".join(out)
    out.append("")
    for dim in roll.dimensions:
        bucket = roll.counts.get(dim, {})
        n = sum(bucket.values())
        # "liveness  47  ADVANCING=40 SPINNING=5 STALLED=2"
        pairs = " ".join(f"{tok}={cnt}" for tok, cnt in bucket.items())
        out.append(f"  {dim:<16} {n:>4}  {pairs}")
    return "\n".join(out)


_TS_W = 20


def render_history_text(frame: ObserveFrame, *, limit: int = 0) -> str:
    """The per-run (or filtered) verdict history, one event per line, in order.

    `limit > 0` shows only the last `limit` events. Used by `--run` and `--tail`.
    Provenance-first: ts, syscall, verdict, the run/subject/lane, and the evidence
    detail that produced it — the byte-clean counts, never narration.
    """
    out: list[str] = []
    title = "# observe · history"
    if frame.run:
        title += f" · run {frame.run}"
    if frame.syscall_filter:
        title += f" · syscall {frame.syscall_filter}"
    out.append(title)
    events = list(frame.events)
    if limit and limit > 0:
        events = events[-limit:]
    if not events:
        out.append("  (no matching verdict events)")
        return "\n".join(out)
    header = f"  {'ts':<{_TS_W}} {'syscall':<12} {'verdict':<14} subject / detail"
    out.append(header)
    out.append("  " + "-" * (len(header) - 2))
    for e in events:
        subj = e.subject or e.lane or ""
        det = ""
        if e.detail:
            det = " {" + ", ".join(f"{k}={v}" for k, v in sorted(e.detail.items())) + "}"
        run_tag = f"  [{e.run_id}]" if (e.run_id and not frame.run) else ""
        out.append(f"  {(e.ts or '-'):<{_TS_W}} {(e.syscall or '-'):<12} "
                   f"{(e.verdict or '-'):<14} {subj}{det}{run_tag}")
    return "\n".join(out)
