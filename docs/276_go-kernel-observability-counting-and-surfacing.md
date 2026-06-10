# docs/276 — Making the Go kernel 10× more observable: count every reasonable thing, then surface it

> **Status:** Phase 1 SHIPPED (commit `21235c2` + the `--since` follow-up): the
> `metrics` registry + the per-invocation observation record + the `stats` surfacing
> verb (human/JSON, with a `--since DURATION` window) are landed and pinned by
> `metrics_test`/`observe_test`/`stats_test`/`observe_parity_test`. The gated-byte
> parity guard proves observability never perturbs a decision. Phase 2 (a Python-side
> folder over the same JSONL; sampling/rotation config) is future.

## The gap

The Go native hook fast-path (`go/`, docs/125 GHF) is a *pure, fast decider*: every
invocation produces a rich verdict — a `Decision` (rung / decision-tag / reason-class /
dialect / tree-known), a `verifyVerdict` (shipped / source / supported), a
`markerVerdict` (allow / emitted / reason), a Stop block/let-stop, an exit code
(0 OWNED vs 3 DELEGATE), and a fail-safe recovered-panic path. **None of it is
counted, and none of it is surfaced.** The only observability today is ephemeral
`--debug` stderr lines that nobody aggregates and that are off by default. So an
operator running a fleet of agents behind the binary cannot answer the most basic
questions:

- How many tool calls did the kernel adjudicate, and what fraction did it DENY / WARN / pass through?
- Which reason classes fire (SELF_MODIFY vs lane-collision vs unprovable-warn)?
- How often does the native path DELEGATE to Python (the cost the binary exists to erase)?
- How often does verify-on-stop actually BLOCK a false done? On which (plan, phase)?
- How often is the wait-marker budget hit (the keep-alive cost guard)?
- How fast is each verb really (the docs/270 latency claim, but live and continuous)?
- Did the fail-safe ever fire (a recovered panic — a Go crash that would silently exit 0)?

This is the kernel's own dogfood failing: DOS adjudicates *other* agents' ground
truth from non-forgeable evidence, but emits no evidence about *its own* behavior.

## The design — three parts, all inside the `go/internal/hook` + `cmd/dos-hook` lanes

The whole thing is the "**I/O at the boundary, data to the pure core**" rule applied
to telemetry: the pure deciders stay pure; counting is a side-band the dispatcher
performs at the edge, after the verdict is already decided. Nothing about the gated
decision projection changes (the docs/124 parity contract holds byte-for-byte — the
metrics are strictly *downstream* of an already-decided verdict, exactly like a
dialect is downstream output).

### Part 1 — `metrics`: an in-process counter registry (the counting)

A new file `go/internal/hook/metrics.go` holds a process-global registry of named
counters keyed by a small closed set of dimensions. It is:

- **Atomic + lock-free on increment** (`sync/atomic` over a fixed map built once),
  so it adds nanoseconds, never milliseconds, to the hot path.
- **Stdlib-only** (the go.mod no-dep rule): a `map[string]*int64` plus
  `atomic.AddInt64`. No `expvar` exposure on the hot path (a hook is a one-shot
  process, not a server — there is nothing to scrape; the durable log is the
  cross-process surface, Part 2).
- **A closed metric vocabulary** — the same "closed-set-as-data" discipline the
  kernel uses for reason classes. Every counter name is a const, so the surface is
  enumerable and testable.

The dimensions worth counting (every reasonable thing):

| Family | Counter keys |
|---|---|
| invocation | `invocations{verb}`, `exit{verb,code}`, `panic_recovered{verb}`, `delegate{verb,why}` |
| pretool | `pretool_decision{tag}` (deny/warn/passthrough), `pretool_rung{rung}`, `pretool_reason_class{class}`, `pretool_tree_known{bool}`, `pretool_dialect{dialect}` |
| posttool | `posttool_verdict{state}` (PROCEEDING/REPEATING/STALLED), `posttool_warn_emitted{bool}` |
| marker | `marker_allow`, `marker_refuse`, `marker_unarmed` (no loop signal), `marker_count_at_decision` (sum, for a mean) |
| stop | `stop_block`, `stop_let{why}` (no-claims/all-verified/abstain-delegate), `stop_claims_seen` (sum), `stop_failure{source}` |
| verify | `verify_shipped{source}`, `verify_not_shipped{source}`, `verify_abstain` |
| latency | `latency_ns{verb}` (sum) + `latency_count{verb}` → mean; plus a small fixed bucket histogram |

### Part 2 — the per-invocation observation record (durability + the fleet surface)

A hook is a one-shot process: the in-process registry dies with it. So each
invocation ALSO appends ONE structured JSONL line to
`.dos/metrics/observations.jsonl` under the served workspace — the WAL discipline
(docs/lane_journal) applied to telemetry. The record is schema-tagged
(`family: "hook-observation", version: 1`, the same `durable_schema` gate the
marker/stream accumulators use), carries the full forensic projection of the
verdict (verb, decision, rung, reason_class, dialect, exit_code, verify fields,
latency_ms, ts, run_id from CID_RUN_ID), and is written with the same
`pyJSONDumpsWAL` byte-grammar + best-effort fail-soft semantics as the existing
journal writers (a write fault NEVER changes the emitted dialect or the exit code —
telemetry is advisory, docs/99).

This is the cross-process aggregate substrate: the fleet's many one-shot binaries
all append to per-workspace logs, and the surfacing verb (Part 3) folds them.

**Gating.** Observation-logging is ON by default but bounded and opt-OUT via
`DOS_HOOK_METRICS=0` (symmetry with `DOS_HOOK_NATIVE=0`). The in-process registry
always counts (free); only the durable append is gated, because it is the only part
that touches disk. A `--debug` run always logs regardless (you asked for trace).

### Part 3 — `dos-hook stats`: the surfacing verb (read-only fold)

The verb `dos-hook stats [--workspace DIR] [--json] [--since DURATION]` reads the
observation log and renders the aggregate — the read-only projection half (the
sibling of Python's `dos top` / `dos decisions`, but for the binary's own behavior).
Human render is a compact table (counts by verb, decision, reason-class, delegate
rate, verify block count, marker refuse rate, latency mean/p50/p95/max). `--json`
emits the same as a machine object. `--since` (e.g. `1h`, `30m`) windows the fold to
recent records (an unparseable/absent value = all-time; the clock lives at this
read-only boundary, never in a verdict). It takes no lease, launches nothing, mutates
no state — pure fold over the durable log, exactly the read-only-projection contract
the kernel's other surfaces honor.

## Why this is "10×"

Today: 0 counted dimensions, observability = off-by-default ephemeral stderr.
After: ~30 counted dimensions across every verb, durably logged per-invocation,
foldable across a fleet, and surfaced through a dedicated read-only verb + far
richer `--debug` (now with per-verb latency). The kernel goes from *opaque* to
*self-describing* — it emits non-forgeable evidence about its own adjudication the
same way it demands evidence from the agents it judges.

## What stays out (scope discipline)

- No server / no `expvar` HTTP endpoint (a hook is one-shot; the durable log is the surface).
- No new dependency (stdlib-only; the go.mod rule holds).
- No change to any gated decision byte (parity contract intact; metrics are downstream output).
- No Python-side change required (the observation log is Go-authored; a future
  Python folder can read the same JSONL, but that is not this unit).
- The rich per-workspace metrics CONFIG (renaming the log path, sampling) is a
  later concern — Part 1–3 ship the built-in default surface.
