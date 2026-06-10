"""Verdict-journal — a write-ahead log for the kernel's own adjudications (docs/262).

DOS adjudicates a firehose of verdicts every loop — `verify` (SHIPPED /
NOT_SHIPPED), `liveness` (ADVANCING / SPINNING / STALLED), `productivity`,
`efficiency`, `breaker`, `hook_exit`, `reward`, every hook decision — and until
this module **only one of them persisted**: `arbitrate`, and only because the lane
WAL (`lane_journal`) happened to need the lease set across processes. Every other
verdict was computed at the CLI boundary, printed, and evaporated. So "every
liveness verdict this run emitted," "when did efficiency cross into WASTEFUL," and
"what did this fleet decide last hour" were all unanswerable — the read-only
projections (`trace`/`decisions`/`top`) could only join the surfaces that
incidentally persisted.

This module is the missing substrate: the **same WAL discipline `lane_journal`
proves, re-aimed from leases onto verdicts** (the relationship `efficiency` has to
`productivity`, or `resume` to `liveness`). Every adjudication the kernel makes can
be appended — and `fsync`'d — to an append-only JSONL file as a structured,
`run_id`-correlated `VerdictEvent`; `rollup()` folds the log into per-dimension
verdict counts (pure: entries in, counts out, no disk), and `read_all`/`tail`
answer history queries. A new `dos observe` projection reads it.

Design rules (inherited verbatim from `lane_journal` — the LJ scope boundary):

* **Pure where it can be.** `rollup()` / `for_run()` take entries and return data
  — entries in, value out, no disk — so the suite folds them without touching a
  file. Only `record` / `read_all` / `tail` touch disk.
* **Fail-soft, never fail-loud.** Observability must never take down the thing it
  observes: `record()` that cannot write logs-and-drops (the `notify.send_safely`
  posture), it never raises into the syscall that emitted the verdict. A truth
  syscall is not made less true by a full disk.
* **Torn-tail tolerant.** A process killed mid-`record` can leave a partial final
  line. `read_all` skips an unparseable *trailing* line (and only the trailing
  one); a non-trailing corrupt line is kept as a `_CORRUPT` sentinel so an audit
  still sees the integrity breach.
* **Host-local + run-correlated.** Every event stamps the `run_id` spine key (or
  `""` when the emitter had none — surfaced honestly, never guessed by a time
  window). The join to `trace`/`decisions` is the existing `run_id`, nothing
  fabricated (the `trace` non-goal: no second parallel correlation id).
* **The recorder is not a judge.** This module records verdicts other syscalls
  *already minted* — it adds no precondition, runs no `classify`, mints no belief.
  Delete it and you lose the record, not any adjudication. (The `trace` contract.)
* **Byte-clean by construction (docs/138).** A `VerdictEvent.detail` carries the
  *environment-authored* evidence counts the verdict was computed from (tokens,
  work units, ages — the same byte-clean inputs `efficiency`/`liveness` trust),
  NEVER the agent's narration. The recorder is handed a typed verdict downstream of
  the classify; it is structurally incapable of recording "the agent says it's
  done."

Read::

    dos observe                  # fleet-wide rollup over the whole journal
    dos observe --run <run_id>   # one run's verdict history
    dos observe --syscall NAME   # filter to one dimension
    dos observe --tail N         # the last N events, raw
    dos observe --json           # machine-readable

Write is library-only (a syscall verb / hook sensor calls `record()` as it emits)
— there is deliberately no `record` CLI subcommand, so nothing can journal a
verdict the kernel did not actually return.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass
elif not isinstance(sys.stdout, io.TextIOWrapper):  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dos import config as _config

# The durable-schema family + version for verdict-journal records (docs/207). Every
# record is tagged from line 1 (unlike the lane journal, whose lease ops predate the
# tag contract) so a future non-additive shape change migrates cleanly. A new field
# is additive and never bumps it; the version bumps only on a breaking change.
SCHEMA_FAMILY = "verdict-journal"
VERDICT_JOURNAL_SCHEMA = 1

# The closed-ish set of syscall dimensions a verdict event names. "Closed-ish"
# because a host driver may emit its own verdict kind (a JUDGE rung verdict, a
# custom sensor) and the recorder must not refuse it — the set below is the kernel's
# OWN verdict-emitting syscalls, used for the `--syscall` filter's known-values hint
# and the rollup's stable ordering, NOT a validation gate. An unknown syscall is
# recorded as-is (the tolerant-floor posture: never drop a real event).
SYSCALL_VERIFY = "verify"
SYSCALL_LIVENESS = "liveness"
SYSCALL_PRODUCTIVITY = "productivity"
SYSCALL_EFFICIENCY = "efficiency"
SYSCALL_ARBITRATE = "arbitrate"
SYSCALL_REWARD = "reward"
SYSCALL_BREAKER = "breaker"
SYSCALL_HOOK_EXIT = "hook_exit"
SYSCALL_PRETOOL = "pretool"
SYSCALL_POSTTOOL = "posttool"
SYSCALL_STOP = "stop"

# Stable display/rollup order for the kernel's own dimensions; an unknown syscall
# sorts after these (alphabetically) so a custom emitter is visible, just last.
KNOWN_SYSCALLS = (
    SYSCALL_VERIFY,
    SYSCALL_LIVENESS,
    SYSCALL_PRODUCTIVITY,
    SYSCALL_EFFICIENCY,
    SYSCALL_ARBITRATE,
    SYSCALL_REWARD,
    SYSCALL_BREAKER,
    SYSCALL_HOOK_EXIT,
    SYSCALL_PRETOOL,
    SYSCALL_POSTTOOL,
    SYSCALL_STOP,
)

# Who emitted the event — a kernel syscall verb, or a hook sensor. (A driver may
# pass its own source string; like `syscall`, this is descriptive, not validated.)
SOURCE_KERNEL = "kernel"
SOURCE_SENSOR = "sensor"


def journal_now_iso() -> str:
    """Second-resolution UTC stamp for verdict events.

    The same stamp grammar the lane journal uses (`lane_journal.journal_now_iso`):
    fine enough to order events within a minute, with the monotonic `seq` as the
    real tiebreak. Human-readable without ambiguity.
    """
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# The record + the fold result — frozen value objects with to_dict()/from_dict()
# so the JSONL round-trips (mirrors lane_journal entries + decisions.Decision).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictEvent:
    """One adjudication the kernel made — a row in the verdict journal.

    `syscall` is the dimension (`verify`/`liveness`/…); `verdict` is the typed token
    that syscall returned (`SHIPPED`/`STALLED`/`WASTEFUL`…). `run_id` is the
    correlation spine key (or "" when the emitter had none — surfaced honestly, the
    docs/118 fail-toward-no-match rule). `subject` is an optional free identifier
    (a `(plan,phase)`, a command, a step id); `lane` an optional region. `detail` is
    a small dict of the ENVIRONMENT-authored evidence counts the verdict was
    computed from (tokens, work, ages) — never the agent's narration (docs/138).
    `source` names the emitter kind (`kernel`/`sensor`).
    """

    syscall: str
    verdict: str
    run_id: str = ""
    lane: str = ""
    subject: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)
    source: str = SOURCE_KERNEL
    ts: str = ""
    seq: int = 0

    def to_record(self) -> dict:
        """The JSONL record — schema-tagged, every field present.

        The durable-schema tag rides at the top level (`schema_family`/
        `schema_version`) so a reader can branch on shape without guessing.
        """
        return {
            "schema_family": SCHEMA_FAMILY,
            "schema_version": VERDICT_JOURNAL_SCHEMA,
            "ts": self.ts or journal_now_iso(),
            "seq": int(self.seq),
            "syscall": self.syscall,
            "verdict": self.verdict,
            "run_id": self.run_id,
            "lane": self.lane,
            "subject": self.subject,
            "detail": dict(self.detail) if isinstance(self.detail, Mapping) else {},
            "source": self.source,
        }

    # `to_dict` is an alias kept for symmetry with `decisions.Decision.to_dict` /
    # `trace`'s value objects, so a `--json` renderer can call the same method name
    # across every projection.
    to_dict = to_record

    @classmethod
    def from_record(cls, rec: Mapping[str, Any]) -> "VerdictEvent":
        """Rebuild a `VerdictEvent` from a parsed JSONL record (tolerant).

        Missing fields degrade to their defaults — a record written by an older
        kernel (fewer fields) reads cleanly, the additive-schema floor. `detail` is
        coerced to a dict (a malformed non-dict detail becomes {} rather than
        raising — a reader never crashes on one bad row)."""
        detail = rec.get("detail")
        if not isinstance(detail, Mapping):
            detail = {}
        try:
            seq = int(rec.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        return cls(
            syscall=str(rec.get("syscall") or ""),
            verdict=str(rec.get("verdict") or ""),
            run_id=str(rec.get("run_id") or ""),
            lane=str(rec.get("lane") or ""),
            subject=str(rec.get("subject") or ""),
            detail=dict(detail),
            source=str(rec.get("source") or SOURCE_KERNEL),
            ts=str(rec.get("ts") or ""),
            seq=seq,
        )


@dataclass(frozen=True)
class VerdictRollup:
    """The pure fold over a set of verdict events — counts per (dimension, token).

    `by` names the dimension folded on (`syscall` by default; also `verdict`,
    `run_id`, `lane`, `source`). `counts` maps each dimension value to a
    {verdict-token: count} sub-map, so "47 liveness verdicts: 40 ADVANCING, 5
    SPINNING, 2 STALLED" is one lookup. `total` is the event count; `corrupt` the
    number of `_CORRUPT` sentinel lines seen (an integrity tally, surfaced not
    hidden — the lane-journal posture). `dimensions` is the dimension values in
    stable order (known syscalls first, then the rest alphabetically).
    """

    by: str
    counts: Mapping[str, Mapping[str, int]]
    dimensions: tuple[str, ...]
    total: int
    corrupt: int = 0

    def to_dict(self) -> dict:
        return {
            "by": self.by,
            "total": self.total,
            "corrupt": self.corrupt,
            "dimensions": list(self.dimensions),
            "counts": {k: dict(v) for k, v in self.counts.items()},
        }


# ---------------------------------------------------------------------------
# Path resolution — the active workspace's verdict journal, with an env override.
# Mirrors lane_journal._journal_path exactly.
# ---------------------------------------------------------------------------

# The workspace-neutral env override (parallel to DISPATCH_LANE_JOURNAL_PATH).
_ENV_PATH = "DISPATCH_VERDICT_JOURNAL_PATH"


def _default_journal_path() -> Path:
    """The active workspace's verdict journal.

    Falls back to a `verdict-journal.jsonl` sibling of the lane journal when the
    config's `verdict_journal` field is unset (a `PathLayout` constructed
    positionally without the defaulted field) — so a partially-built layout still
    resolves to a sane sibling path rather than crashing on `None`."""
    paths = _config.active().paths
    vj = getattr(paths, "verdict_journal", None)
    if vj is not None:
        return Path(vj)
    return Path(paths.lane_journal).with_name("verdict-journal.jsonl")


def _journal_path(path: Path | None = None) -> Path:
    """Resolve the journal path: explicit arg › env override › active config.

    Re-read each call so a test that sets the env var after import still redirects
    (the lane-journal idiom)."""
    if path is not None:
        return Path(path)
    env = os.environ.get(_ENV_PATH)
    if env:
        return Path(env)
    return _default_journal_path()


# ---------------------------------------------------------------------------
# Write — append one event, fsync'd, FAIL-SOFT. The only mutating I/O.
# ---------------------------------------------------------------------------


def _next_seq(path: Path) -> int:
    """The seq to stamp on the next event = max existing seq + 1 (1-based).

    Best-effort: a read failure yields 1 (start fresh) rather than raising — the
    seq is a within-file tiebreak, not a correctness invariant (the `ts` orders
    across files; an O_APPEND write orders within one). Unlike the lane journal,
    verdict events are not serialized under a lease mutex (they are emitted from
    many independent syscalls), so two concurrent writers MAY mint the same seq —
    tolerable, because the seq is cosmetic-ordering, never an identity. `read_all`
    folds by append order and uses `ts`+`seq` only for display sort.
    """
    mx = 0
    for e in read_all(path):
        try:
            s = int(e.get("seq") or 0)
        except (TypeError, ValueError):
            s = 0
        if s > mx:
            mx = s
    return mx + 1


def record(event: VerdictEvent, *, path: Path | None = None,
           stamp_seq: bool = True) -> bool:
    """Append one `VerdictEvent` to the journal as JSONL, `fsync`'d. FAIL-SOFT.

    Returns True on a successful durable append, False if the write failed (a full
    disk, a permission error, a missing parent that could not be created) — the
    caller's syscall is NEVER interrupted by an observability failure (the
    `notify.send_safely` contract: the thing that observes must not crash the thing
    observed). The dir is created on demand (`mkdir(parents=True)`), like the lease
    writers. When `stamp_seq` (the default), an unset `seq`/`ts` is filled in here so
    a caller can `record(VerdictEvent(syscall=…, verdict=…, run_id=…))` without
    plumbing the clock/counter — the recorder owns the stamp the way `lane_lease`
    owns the journal stamp.
    """
    try:
        p = _journal_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = event.to_record()
        if stamp_seq:
            if not rec.get("ts"):
                rec["ts"] = journal_now_iso()
            if not rec.get("seq"):
                rec["seq"] = _next_seq(p)
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        # O_APPEND keeps concurrent appends from interleaving a single line; fsync
        # makes the record outlive the process that wrote it (the WAL invariant).
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except (OSError, ValueError):  # pragma: no cover - platform fsync quirks
                pass
        return True
    except Exception:
        # FAIL-SOFT: observability never takes down the observed. We deliberately
        # swallow EVERY exception here (not a narrow set) — there is no failure mode
        # of a verdict log worth crashing a truth syscall over.
        return False


# ---------------------------------------------------------------------------
# Read — every event in append order, torn-tail tolerant. Mirrors
# lane_journal.read_all byte-for-byte in posture.
# ---------------------------------------------------------------------------


def read_all(path: Path | None = None) -> list[dict]:
    """Return every journal record (raw dict) in append order.

    Skips an unparseable TRAILING line (a torn final record from a crash
    mid-append — "didn't happen," the safe WAL read) but keeps a non-trailing
    corrupt line as a `{"op": "_CORRUPT", ...}` sentinel so an audit still sees the
    integrity breach (the lane-journal reader, verbatim — same sentinel shape so a
    shared audit can recognize it).
    """
    p = _journal_path(path)
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    out: list[dict] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break  # torn final line — tolerated
            out.append({"op": "_CORRUPT", "_raw": s, "_line": i})
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def tail(n: int = 20, path: Path | None = None) -> list[dict]:
    """The last `n` records (raw dicts) — reads the whole file then slices.

    The journal is NOT auto-rotated; on a long-lived fleet it grows unbounded and
    this is O(file), the documented lane-journal posture (docs/262 Phase 4 folds
    the `[retention]` caps over it). `n <= 0` returns all.
    """
    entries = read_all(path)
    return entries[-n:] if n > 0 else entries


def read_events(path: Path | None = None) -> list[VerdictEvent]:
    """`read_all`, decoded into `VerdictEvent`s, dropping `_CORRUPT` sentinels.

    The typed reader the projections + folds consume. A corrupt sentinel is NOT a
    verdict, so it is excluded here (its existence is still counted by `rollup` via
    a separate pass over `read_all`, so the integrity tally survives)."""
    return [
        VerdictEvent.from_record(rec)
        for rec in read_all(path)
        if rec.get("op") != "_CORRUPT"
    ]


# ---------------------------------------------------------------------------
# The pure folds — entries in, data out, no disk. The unit-test surface.
# ---------------------------------------------------------------------------


def _dimension_value(ev: VerdictEvent, by: str) -> str:
    """The value of event `ev` along dimension `by` (defaults to syscall)."""
    if by == "verdict":
        return ev.verdict or "(none)"
    if by == "run_id":
        return ev.run_id or "(unattributed)"
    if by == "lane":
        return ev.lane or "(none)"
    if by == "source":
        return ev.source or "(none)"
    return ev.syscall or "(none)"  # "syscall" / default


def _order_dimensions(values: Iterable[str], by: str) -> tuple[str, ...]:
    """Stable order: known syscalls first (when by==syscall), then the rest sorted.

    For any other dimension the order is plain sorted (no privileged set). The
    unattributed/none buckets sort to the end of the alphabetic tail naturally
    because of the parenthesis prefix sort — acceptable; they are clearly labelled.
    """
    vals = set(values)
    if by == "syscall":
        head = [s for s in KNOWN_SYSCALLS if s in vals]
        tail = sorted(v for v in vals if v not in set(KNOWN_SYSCALLS))
        return tuple(head + tail)
    return tuple(sorted(vals))


def rollup(events: Iterable[VerdictEvent], *, by: str = "syscall",
           corrupt: int = 0) -> VerdictRollup:
    """Fold events into per-`by` verdict counts. PURE — no disk.

    For each event, increments `counts[dimension_value][verdict_token]`. `by` is one
    of "syscall" (default) / "verdict" / "run_id" / "lane" / "source". `corrupt` is
    the integrity tally the caller carries in from `read_all` (the count of
    `_CORRUPT` sentinels) so the rollup can surface it without re-reading the file.

    This is the lane-journal `replay` analogue: the pure reduction that turns the
    raw event stream into the answer a projection renders. Unit-tested in isolation
    (no file needed) exactly like `replay`.
    """
    counts: dict[str, dict[str, int]] = {}
    total = 0
    for ev in events:
        total += 1
        dim = _dimension_value(ev, by)
        token = ev.verdict or "(none)"
        bucket = counts.setdefault(dim, {})
        bucket[token] = bucket.get(token, 0) + 1
    dims = _order_dimensions(counts.keys(), by)
    # Freeze the sub-maps in a stable order too (verdict tokens sorted) so the
    # rendered + JSON output is deterministic.
    frozen = {d: dict(sorted(counts[d].items())) for d in dims}
    return VerdictRollup(by=by, counts=frozen, dimensions=dims,
                         total=total, corrupt=corrupt)


def for_run(events: Iterable[VerdictEvent], run_id: str) -> list[VerdictEvent]:
    """The slice of events attributed to `run_id` — the `trace` join (docs/262 P3).

    The join key is the existing `run_id` spine, nothing fabricated (the `trace`
    non-goal). Events with no `run_id` are NEVER guessed onto a run by time (the
    docs/118 fail-toward-no-match rule) — a `for_run` over a run that emitted no
    correlated verdict honestly returns []. Preserves append order.
    """
    return [ev for ev in events if ev.run_id == run_id]


def count_corrupt(raw: Iterable[Mapping[str, Any]]) -> int:
    """Count the `_CORRUPT` sentinel rows in a `read_all` result (integrity tally).

    A tiny helper so a projection can do one `read_all`, hand the typed events to
    `rollup`/`for_run` and the raw rows here, without re-reading the file."""
    return sum(1 for r in raw if r.get("op") == "_CORRUPT")
