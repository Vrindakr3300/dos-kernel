"""exporter — drain the verdict journal outward to an observability backend (docs/266).

> **DOS records its own disbelief (docs/262) — but the record is a local island.**
> The verdict journal (`verdict_journal.py`) lands every adjudication a fleet makes
> as a `run_id`-correlated `VerdictEvent` in an append-only JSONL file, and `dos
> observe` reads it back. What was MISSING is the last hop: nothing ships that stream
> to where an operator's dashboards/alerts already live — Datadog, Grafana/Loki,
> Honeycomb, an OTLP collector, a syslog file. This seam is that outward connector.
> **No transport name appears in this module.**

Why this seam, not `notify`
===========================

`notify` (docs/225) pushes a *projection snapshot* (`decisions` = "what needs a human
now", `top` = "what's running now") to a transport — it answers "page me on the
current state." That is the wrong shape for observability:

* `notify` sends ONE rendered `Notification` from a point-in-time snapshot; an exporter
  ships a STREAM of structured events — every `VerdictEvent`, counts intact — so a
  time-series backend can chart "liveness STALLED rate over 24h."
* `notify`'s payload is human-facing prose; an exporter's is machine-facing structure
  (a metric point, an OTLP log record, a JSON line) keyed for aggregation.
* `notify` is operator-triggered / cron-cadence; an exporter is DRAIN-shaped — it
  follows the journal forward and flushes new events, the way a log shipper tails a file.

So the exporter is the kernel's FIFTH pure-protocol + by-name-resolver seam — after
`judges` (the JUDGE rung), `overlap_policy` (the disjointness scorer), `hook_dialect`
(the host-hook renderer), and `notify` (the projection-delivery side) — on a new axis:
the verdict *stream*, drained outward. The shape is byte-for-byte `notify.py`'s: a pure
Protocol + a frozen result type + an unshadowable built-in + a by-name resolver + a
fail-soft wrapper. Every real connector (which names a transport as code — an OTLP
shipper is inherently OTLP-specific) lives in a driver and registers through the
`dos.exporters` entry-point group.

The neutral record is already there — `VerdictEvent`
=====================================================

The exporter does NOT invent a payload type. `verdict_journal.VerdictEvent` is already
the transport-agnostic, byte-clean fact: its `detail` carries the
environment-authored evidence counts the verdict was computed from (tokens, work,
ages), NEVER the agent's narration (the docs/138 invariant the journal enforces). An
exporter takes a batch of `VerdictEvent`s and ships them. The hard part — a clean,
correlated, forgeable-narration-free record — is done (docs/262).

Failure direction = fail-SOFT
=============================

Observability must NEVER crash the thing it observes — the same rule as `notify` and
the journal itself (`record()` logs-and-drops). So `export_safely` converts any
transport raise into a non-exported `ExportResult`. A *resolve* of an unknown exporter
name still raises (operator config error, surfaced at config time, the
`resolve_notifier` rule); a *send* never does. A down collector, a bad endpoint, an
absent optional extra → a non-exported result, never an exception into the drain loop.

The advisory floor (docs/99)
============================

The exporter REPORTS; it never acts on the fleet. It reads the journal only — takes no
lease, mints no belief, stops no run, mutates no DOS state. It is a pure
read-of-the-journal → ship. The `decisions`/`observe`/`notify` read-only posture,
extended across the network boundary.

Pure-stdlib. The resolver is the unit-test surface; the only I/O in the whole spine is
inside a driver's `export` (and a `cmd_export` boundary that reads the journal).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Sequence, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only; never imported at runtime
    from dos.verdict_journal import VerdictEvent


# ---------------------------------------------------------------------------
# The result a driver returns — fail-soft: exported=0 is normal, never a raise.
# The `NotifyResult` analogue.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportResult:
    """The outcome of an `export` — always returned, never raised (fail-soft).

    `exported` is how many of the handed events the transport accepted (0 is a
    perfectly normal result — a `null` sink, a `--dry-run`, a down collector). `detail`
    is a one-line human reason (`"wrote 12 lines to …"` / `"dry-run"` / `"null sink"` /
    `"error: …"`). `cursor` is the seq/offset the drain reached — the highest `seq`
    shipped — so a later `--since <cursor>` resumes the forward drain without re-shipping
    (the journal's own monotonic `seq`, nothing fabricated; "" when no event was shipped).
    """

    exported: int
    detail: str = ""
    cursor: str = ""

    def to_dict(self) -> dict:
        return {"exported": self.exported, "detail": self.detail, "cursor": self.cursor}


# ---------------------------------------------------------------------------
# The Exporter protocol + the unshadowable built-in null sink.
# ---------------------------------------------------------------------------


@runtime_checkable
class Exporter(Protocol):
    """A transport that drains a batch of `VerdictEvent`s outward. The driver-side seam.

    `name` is the registered name (`"file"`, `"statsd"`, `"otlp"`); `export` ships the
    batch and returns an `ExportResult`. An implementation MAY write JSONL lines, emit
    one metric per event, or POST OTLP records — that choice is the driver's, not the
    kernel's. It MUST be fail-soft (never raise) on a transport failure; `export_safely`
    is the outer net regardless.
    """

    name: str

    def export(self, events: "Sequence[VerdictEvent]") -> ExportResult: ...


class NullExporter:
    """The honest zero — ships nothing, the unshadowable built-in baseline.

    The default exporter, so a bare `dos export` is a safe no-op that reports how many
    events WOULD ship and sends them nowhere (the `NullNotifier` / `AbstainJudge` /
    `prefix`-floor analogue: the built-in that can never loosen anything and is always
    resolvable). A host opts IN to a real transport by naming one (`--to file`).

    It still reports a `cursor` (the highest seq it saw) so a `--since` drain advances
    even against `null` — useful for "mark these as seen without shipping them."
    """

    name = "null"

    def export(self, events: "Sequence[VerdictEvent]") -> ExportResult:
        n = len(events)
        cursor = _max_seq_cursor(events)
        return ExportResult(
            exported=0,
            detail=f"null sink (no transport configured) — {n} event(s) not shipped",
            cursor=cursor,
        )


_BUILT_IN_EXPORTERS: dict[str, type] = {"null": NullExporter}

EXPORTER_ENTRY_POINT_GROUP = "dos.exporters"


def _max_seq_cursor(events: "Sequence[VerdictEvent]") -> str:
    """The highest `seq` in `events` as a string cursor, or "" when the batch is empty.

    A tiny pure helper every driver reuses to fill `ExportResult.cursor` consistently —
    the resumable-drain offset is the journal's own monotonic `seq`, so "ship past the
    last shipped seq" is `--since <cursor>`. Robust to a non-int seq (degrades to 0)."""
    mx = 0
    for e in events:
        try:
            s = int(getattr(e, "seq", 0) or 0)
        except (TypeError, ValueError):
            s = 0
        if s > mx:
            mx = s
    return str(mx) if events else ""


# ---------------------------------------------------------------------------
# Resolver + discovery — built-ins first, then the `dos.exporters` plugins. The
# `resolve_notifier` / `resolve_judge` shape; discovery I/O at the call boundary.
# ---------------------------------------------------------------------------


def _discover_entry_point_exporters(*, _stderr=None) -> list[tuple[str, "Exporter"]]:
    """Every `dos.exporters` plugin as `(name, exporter)`, sorted by name.

    A plugin that fails to load is SKIPPED with a one-line stderr note rather than
    crashing — the `_discover_entry_point_notifiers` posture (a broken third-party
    plugin is the operator's to fix, not a kernel fault). Does entry-point I/O, so it is
    a call-boundary helper, never called inside the resolve hot path twice."""
    stderr = _stderr if _stderr is not None else sys.stderr
    out: list[tuple[str, Exporter]] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=EXPORTER_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(EXPORTER_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash a call
        return out
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            obj = ep.load()
            exporter = obj() if isinstance(obj, type) else obj
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: exporter plugin {ep.name!r} failed to load ({e}); skipping",
                file=stderr,
            )
            continue
        out.append((ep.name, exporter))
    return out


def _accepted_kwargs(ctor: type, kwargs: dict) -> dict:
    """Filter `kwargs` to the parameters `ctor.__init__` actually accepts.

    The export CLI builds ONE superset bag (path/host/port/endpoint/dry_run/root) and
    hands it to whichever transport was named, so it need not branch per driver. But a
    transport's `__init__` is keyword-only and would raise on an unexpected kwarg (`file`
    does not take `host`; `statsd` does not take `path`). So we pass only the parameters
    the constructor declares — unless it declares `**kwargs` (a `VAR_KEYWORD` param), in
    which case it absorbs the rest and we forward everything. Pure introspection; no I/O.
    The `notify._accepted_kwargs` twin.
    """
    try:
        import inspect

        params = inspect.signature(ctor).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins without a signature
        return kwargs
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


def resolve_exporter(name: str, *, _stderr=None, **kwargs) -> "Exporter":
    """Resolve an exporter by name: built-ins first, then `dos.exporters` plugins.

    Built-ins (`null`) resolve FIRST and cannot be shadowed (the trusted-fallback
    guarantee, identical to `resolve_notifier`). An unknown name fails LOUD with the
    known list — a typo'd `--to` is an operator error, never a silent degrade to `null`
    (which would drop every event quietly). `kwargs` (e.g. `path=…`, `host=…`, `port=…`,
    `endpoint=…`, `dry_run=…`) are forwarded to a CONSTRUCTOR-style occupant (a `type`),
    FILTERED to the parameters that constructor accepts (so the CLI can hand the same
    superset to any transport); a pre-built instance ignores them.
    """
    if name in _BUILT_IN_EXPORTERS:
        cls = _BUILT_IN_EXPORTERS[name]
        accepted = _accepted_kwargs(cls, kwargs)
        return cls(**accepted) if accepted else cls()
    # For discovered plugins we resolve the ENTRY POINT and, if it is a class, construct
    # it with kwargs (so the CLI can pass path/host/port). A plugin that exposes a
    # pre-built instance is used as-is.
    stderr = _stderr if _stderr is not None else sys.stderr
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover
        entry_points = None  # type: ignore[assignment]
    found: object | None = None
    if entry_points is not None:
        try:
            eps = entry_points(group=EXPORTER_ENTRY_POINT_GROUP)
        except TypeError:  # pragma: no cover - py<3.10
            eps = entry_points().get(EXPORTER_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            eps = []
        for ep in eps:
            if ep.name == name:
                try:
                    found = ep.load()
                except Exception as e:  # pragma: no cover - third-party
                    raise ValueError(
                        f"exporter {name!r} failed to load: {e}"
                    ) from e
                break
    if found is not None:
        if isinstance(found, type):
            accepted = _accepted_kwargs(found, kwargs)
            return found(**accepted)  # type: ignore[return-value]
        return found  # a pre-built instance ignores kwargs
    discovered = [n for n, _ in _discover_entry_point_exporters(_stderr=stderr)]
    known = sorted(set(_BUILT_IN_EXPORTERS) | set(discovered))
    raise ValueError(f"unknown exporter {name!r}; known: {', '.join(known)}")


def active_exporters(*, _stderr=None) -> list[tuple[str, "Exporter"]]:
    """Every resolvable exporter as `(name, exporter)` — built-ins THEN discovered.

    The order `dos doctor` would list. Does entry-point discovery (I/O), so it is a
    call-boundary helper, never called inside an adapter (the `active_notifiers` rule).
    """
    built: list[tuple[str, Exporter]] = [(n, cls()) for n, cls in _BUILT_IN_EXPORTERS.items()]
    return built + _discover_entry_point_exporters(_stderr=_stderr)


def active_exporter_names(*, _stderr=None) -> list[str]:
    """The names of every active exporter (built-in + discovered)."""
    return [name for name, _ in active_exporters(_stderr=_stderr)]


# ---------------------------------------------------------------------------
# export_safely — the fail-soft wrapper. An export NEVER crashes the drain.
# ---------------------------------------------------------------------------


def export_safely(exporter: "Exporter", events: "Sequence[VerdictEvent]") -> ExportResult:
    """Ship `events` via `exporter`, converting ANY raise to a non-exported result.

    The fail-soft floor (`notify.send_safely`, re-aimed at the verdict stream):
    observability must never take down the observed, so a transport that raises (a down
    collector, a bad endpoint, a buggy plugin) must never propagate into the drain loop
    that emitted it. A clean `export` returns its own `ExportResult`; a raise becomes
    `ExportResult(exported=0, detail="error: …")`. (Contrast `resolve_exporter`, which
    DOES raise on an unknown name — that is a config-time operator error, surfaced before
    any drain.)
    """
    try:
        result = exporter.export(events)
    except Exception as e:  # noqa: BLE001 - observability must not crash the observed
        return ExportResult(exported=0, detail=f"error: {e}")
    if isinstance(result, ExportResult):
        return result
    # A misbehaving occupant returned a non-ExportResult; treat as a soft failure rather
    # than trusting an unknown shape downstream.
    return ExportResult(exported=0, detail="exporter returned a non-ExportResult")
