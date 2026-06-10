# 266 — The verdict exporter: shipping the journal to where the dashboards live

> **DOS now records its own disbelief — but the record is a local island.** docs/262
> shipped the verdict journal (`verdict_journal.py`: `record`/`read_all`/`tail`/
> `rollup`/`for_run` + the `--observe`/`DISPATCH_OBSERVE=1` auto-emit wiring at
> `cli.py:203`). Every adjudication a fleet makes can now land as a `run_id`-correlated
> `VerdictEvent` in an append-only JSONL file, and `dos observe` reads it back. What is
> **missing is the last hop**: nothing ships that stream to where an operator's
> dashboards and alerts already live — Datadog, Grafana/Loki, Honeycomb, an
> OpenTelemetry collector, a plain syslog file, a metrics endpoint. The journal is a
> witness the kernel keeps for itself; this plan gives it an **outward connector** so
> the witness reaches the operator's existing observability plane. It is the
> *delivery-side* sibling of docs/262's *recording-side*, exactly as `notify` is the
> delivery side of the `decisions`/`top` projections.

*Status: Phases 1–3 SHIPPED. The recorder (docs/262 Phase 1) and the auto-emit (Phase 2)
were already SHIPPED; this plan is the export connector docs/262 Phase 4 gestures at
("how to alert on them is policy … `notify` already pipes a projection to a transport")
but never specifies. Now built: the kernel seam `src/dos/exporter.py` (the fifth
pure-protocol + by-name-resolver seam — `Exporter` Protocol + frozen `ExportResult` +
unshadowable `NullExporter` + `resolve_exporter` over `dos.exporters` + fail-soft
`export_safely`), the `dos export` verb (`cmd_export`: read the journal → slice by
`--since` → resolve → drain), and the three first drivers — `file` (stdlib JSONL append,
Phase 1), `statsd` (stdlib UDP DogStatsD counters, Phase 2), and `otlp` (OTLP/HTTP log
records behind the `[export-otlp]` extra, Phase 3). Pinned by `tests/test_exporter.py`,
`test_export_cli.py`, `test_export_statsd.py`, `test_export_otlp.py` (59 tests). Phase 4
(`--follow` + cursor persistence) is the remaining lift.*

## 0. Why a new seam and not just `notify`

`notify` (docs/225) already pushes a *projection snapshot* (`decisions` = "what needs
a human now", `top` = "what's running now") to a transport. It answers **"page me on
the current state."** That is the wrong shape for observability:

- `notify` sends **one rendered `Notification`** built from a point-in-time snapshot.
  An exporter sends **a stream of structured events** — every `VerdictEvent`, with its
  `syscall`/`verdict`/`detail` counts intact — so a time-series backend can chart
  "liveness STALLED rate over the last 24h" or "efficiency WASTEFUL events per run."
- `notify`'s payload is **human-facing prose** (a title + fields + a fenced summary).
  An exporter's payload is **machine-facing structure** (a metric point, an OTLP span,
  a JSON line) keyed for aggregation, not reading.
- `notify` is **operator-triggered or cron-cadence** ("run `dos notify decisions`").
  An exporter is **drain-shaped**: it follows the journal forward and flushes new
  events, the way a log shipper tails a file.

These are different enough that folding export into `Notifier` would distort both. So
the exporter is the kernel's **fifth pure-protocol + by-name-resolver seam** — after
`judges`, `overlap_policy`, `hook_dialect`, `notify` — on a new axis: the verdict
*stream*, drained outward.

## 1. The shape — `dos.exporter`, the journal's lateral delivery seam

### 1a. The neutral record is already there

The exporter does **not** invent a payload type — `verdict_journal.VerdictEvent` is
already the transport-agnostic, byte-clean fact (its `detail` carries
environment-authored counts, never the agent's narration — the docs/138 invariant the
journal enforces). An exporter takes a batch of `VerdictEvent`s and ships them. The
hard part (a clean, correlated, forgeable-narration-free record) is done.

### 1b. The Protocol + resolver (new kernel seam — `src/dos/exporter.py`)

```python
@dataclass(frozen=True)
class ExportResult:           # fail-soft, like NotifyResult — never raised
    exported: int             # how many events the transport accepted
    detail: str = ""          # one-line human reason
    cursor: str = ""          # the seq/offset reached, for resumable drain

@runtime_checkable
class Exporter(Protocol):
    name: str
    def export(self, events: Sequence["VerdictEvent"]) -> ExportResult: ...

class NullExporter:           # the unshadowable built-in baseline
    name = "null"
    def export(self, events): return ExportResult(exported=0, detail="null sink")

EXPORTER_ENTRY_POINT_GROUP = "dos.exporters"
def resolve_exporter(name, **kwargs) -> Exporter: ...   # built-ins first, then plugins
def export_safely(exporter, events) -> ExportResult: ... # ANY raise → non-exported result
```

This is byte-for-byte the `notify.py` seam shape (Protocol + frozen result + `null`
built-in + by-name resolver + a fail-soft wrapper), which is the proof it belongs in
the kernel: it is mechanism that names no vendor. **Fail-soft** is mandatory for the
same reason as `notify` and the journal itself — observability must never crash the
thing it observes (`export_safely` converts any transport raise to a non-exported
result). **Resolve** of an unknown name raises (operator config error, surfaced at
config time, the `resolve_notifier` rule).

### 1c. The drain — `dos export`, a read-only Layer-3 verb

```
dos export --to otlp --endpoint http://localhost:4318      # ship new events to an OTLP collector
dos export --to file --path /var/log/dos-verdicts.jsonl    # append-stream to a file/pipe a shipper tails
dos export --to statsd --host 127.0.0.1 --port 8125        # emit one counter per (syscall, verdict)
dos export --to null --dry-run                             # render what WOULD ship, send nothing
dos export --since <cursor>                                # drain only events after a saved offset
dos export --follow                                        # stay open, flush new events as they land
```

`cmd_export` (the boundary) reads the verdict journal via the existing
`verdict_journal.read_all`/`tail`, slices to events after `--since`, resolves the named
exporter, calls `export_safely`, and prints the `ExportResult` (`--json` for piping).
It **reads the journal only** — takes no lease, mints no belief, adjudicates nothing
new (the `decisions`/`trace`/`observe` posture). Delete it and you lose the shipper,
not the data.

The drain cursor is the journal's own `seq` (monotonic per file) — so `--since
<seq>` is a resumable offset, and `--follow` is "poll `read_all`, ship anything past
the last shipped seq, repeat." No new correlation id, no parallel state: the cursor is
a number the operator (or a `/loop`) carries forward.

## 2. The three first drivers (the connectors, in `drivers/`)

Each names its vendor/protocol as code (an OTLP shipper is inherently OTLP-specific —
the `SlackNotifier` rule), so it lives in a driver and registers through
`dos.exporters`. Ordered cheapest-first.

| Driver | Transport | New dependency | Maps a `VerdictEvent` to |
|---|---|---|---|
| `export_file` | append-stream to a file/FIFO | **none (stdlib)** | one JSONL line (the journal line, re-emitted to an operator-chosen path a log shipper already tails) |
| `export_statsd` | StatsD/DogStatsD UDP | **none (stdlib `socket`)** | `dos.verdict:1|c|#syscall:liveness,verdict:STALLED` — one counter per `(syscall, verdict)` |
| `export_otlp` | OTLP/HTTP (OpenTelemetry) | `[export-otlp]` extra (`opentelemetry-sdk`) | a log record (and/or a span keyed on `run_id`) with `detail` as attributes |

`export_file` and `export_statsd` are **stdlib-only** — they ship in the package with
no new dependency, the same way `dos top --json` works with no `[tui]` extra. Only the
OTLP driver pulls a real SDK, behind a `[export-otlp]` extra (the `[mcp]`/`[notify-slack]`
precedent), lazy-imported so entry-point discovery never fails when the extra is absent.

The `export_file` driver is the keystone connector: a JSONL stream at a path is the
universal adapter — Datadog's agent, Vector, Fluent Bit, Promtail, and `logger(1)` all
tail a file. So one stdlib driver reaches *most* of the observability market for free;
the StatsD and OTLP drivers are the native paths for shops that want metrics/traces
directly rather than via a log shipper.

## 3. Why this is mechanism, not policy (it belongs in the kernel seam)

The thing being shipped — *the kernel's own verdict events, in the kernel's own closed
vocabulary* — is mechanism. WHICH events an operator exports (`--syscall` filter),
WHERE (`--to`), and HOW OFTEN (`--follow` cadence, driven by a host's `/loop`/cron — no
daemon in the kernel) are policy, and they ride the verb's flags + the driver. The
kernel seam names no transport; the drivers name one each. This is the exact
mechanism/policy split as `notify` (the seam is kernel; Slack is a driver) and the
journal itself (records everything; `observe` reads selectively).

The litmus tests hold by construction:
- **Kernel imports no driver / names no vendor.** `exporter.py` is pure stdlib + the
  `VerdictEvent` type; the OTLP/StatsD/file names live only in `drivers/` +
  `pyproject`. Pinned by `test_vendor_agnostic_kernel.py` (the resolver discovers by
  name; the kernel imports none).
- **`verify`/`liveness` still need no plan to emit a verdict.** The exporter reads an
  *already-recorded* journal; it adds no precondition to any syscall (the journal's own
  rule, inherited).
- **Advisory floor (docs/99).** The exporter REPORTS; it takes no lease, stops no run,
  mutates no DOS state. It is a pure read-of-the-journal → ship.
- **Fail-soft.** `export_safely` + each driver's inner net: a down collector / bad
  endpoint / absent extra degrades to a non-exported `ExportResult`, never a crash.

## 4. Build order (each rung independently shippable + testable)

- ✅ **Phase 1 (SHIPPED) — the seam + the `file` driver (the floor + the universal adapter).**
  `exporter.py` (Protocol + `ExportResult` + `NullExporter` + `resolve_exporter` +
  `export_safely`) + `drivers/export_file.py` + `cmd_export` (`--to`/`--since`/`--json`/
  `--dry-run`) + tests. Gate: a fake-path round-trip ships N events as N JSONL lines;
  `null` + `--dry-run` ships nothing; an unknown `--to` raises; a driver raise → a
  non-exported result. Stdlib-only; no new dependency.
- ✅ **Phase 2 (SHIPPED) — the `statsd` driver.** `drivers/export_statsd.py` — one UDP
  counter per `(syscall, verdict)` with tags, stdlib `socket`, fail-soft on an
  unroutable host. Golden-bytes test (a fixed `VerdictEvent` → the exact StatsD
  datagram), no network (inject a fake socket). Registered under `dos.exporters`.
- ✅ **Phase 3 (SHIPPED) — the `otlp` driver + `[export-otlp]` extra.** `drivers/export_otlp.py` —
  lazy `opentelemetry-sdk` + the OTLP/HTTP log exporter, a `VerdictEvent` → an OTLP log
  record (`run_id` as a correlated attribute; `detail` counts as attributes). Absent
  extra → a non-exported result with an install hint (the `notify_slack` lazy-import
  discipline). Golden-shape test against a fake exporter (the pure `build_records` is
  import-free, so the mapping is testable with or without the SDK).
- ✅ **Phase 4 (SHIPPED) — `--follow` (the drain loop) + cursor persistence.** The resumable
  forward drain: `--since auto` reads the persisted offset, ships past the last shipped
  `seq`, and writes the new high-water mark to `.dos/export-cursor.<transport>` (a
  per-transport suffix so a `file` drain and an `otlp` drain track independent progress).
  Host-cadence-free (a fleet drives the poll via `/loop`/cron; the kernel ships no daemon
  — the `dos notify` posture): `--follow` is a BOUNDED foreground convenience
  (poll → drain → persist → sleep, terminating on `--follow-max` or `^C`), never a
  `while True` blocker. The cursor lives in `src/dos/export_cursor.py` (a WAL-adjacent
  substrate data module, resolved as a verdict-journal sibling — the
  `verdict_journal._default_journal_path` idiom — NOT in the pure `exporter.py` seam),
  fail-soft on read (missing/garbage → 0) and write (failure → False, never crashes the
  drain). Persist fires ONLY when a real transport actually shipped (null/dry-run/failed
  drains hold the cursor — "ship past the last SHIPPED seq"). Pinned by
  `tests/test_export_cursor.py` + the Phase-4 cases in `test_export_cli.py`.

## 5. The one-line thesis

DOS keeps a durable record of every verdict it returns (docs/262) — but a record no
dashboard can see is a witness with no audience. The exporter is the last hop: a pure
seam + a stdlib file/statsd driver + an OTLP driver that drains the verdict stream into
the operator's existing observability plane, fail-soft, advisory, vendor-blind in the
kernel. It makes the fleet's adjudication history a first-class citizen of the tools an
operator already watches, instead of a JSONL island under `.dos/`.

## 6. See also

- docs/262 — the verdict journal this drains: the `VerdictEvent` record, the
  `record`/`read_all`/`rollup` API, the `--observe` auto-emit, and the Phase-4
  retention this composes with.
- docs/225 (notification spine) — the *projection-snapshot* delivery seam this is the
  *event-stream* sibling of; the `Notifier` Protocol + `send_safely` shape `Exporter`
  mirrors.
- `src/dos/verdict_journal.py` — the recorder + reader the exporter reads from; the
  byte-clean `detail` discipline the exported payload inherits.
- `src/dos/notify.py` — the seam template (Protocol + frozen result + `null` built-in +
  by-name resolver + fail-soft wrapper) `exporter.py` copies.
