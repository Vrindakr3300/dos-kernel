"""Lane-journal — a write-ahead log for the lane-lease arbiter (LJ-series).

The pure lane arbiter (`arbiter.arbitrate`) decides admission from a *live-lease
set* — current state only, no history. Without a durable record of what the
arbiter *decided*, "why was I refused at 14:03?", "when did this orphan die and
who reclaimed it?", and "reconstruct the lane state after a crash" are all
unanswerable, and the live set itself has nowhere durable to live across
processes.

This module is the **write-ahead log** that classic schedulers and lock managers
always keep: every lane decision (ACQUIRE / RELEASE / HEARTBEAT / SCAVENGE /
REFUSE / HALT / RECONCILE / ENFORCE / SPAWN) is appended — and `fsync`'d — to an append-only JSONL
file. `replay()` folds the log back into the authoritative live-lease set (so the
journal *is* the cross-process registry — there is no second store to keep in
sync), and `tail`/`read_all` answer history queries. The generic writer is the
Layer-3 `lane_lease` shell (`acquire`/`release`/`heartbeat`/`halt`) plus the
supervisor driver's `scavenge`; each appends inside its own `_Mutex`, so journal
append order equals decision order — the WAL invariant. `replay` folds by append
order and ignores `seq` (which is cosmetic), so an `O_APPEND` write under that
mutex is sufficient.

Design rules (the LJ scope boundary):

* **Pure where it can be.** `replay()` / `compact()` take entries and return
  entries — entries in, list out, no disk — so the suite replays and compacts
  them without touching a file. Only `append` / `read_all` / `tail` touch disk.
* **Log under the lock.** The writer appends inside the lease mutex that
  serializes the decision, so a reader's `replay` sees a consistent order.
* **Torn-tail tolerant.** A process killed mid-`append` can leave a partial
  final line. `read_all` skips an unparseable *trailing* line (and only the
  trailing one) rather than raising — a half-written record is "didn't happen",
  the safe WAL reading. A non-trailing corrupt line is kept as a `_CORRUPT`
  sentinel so an audit still sees the integrity breach (and `compact` preserves
  it — a rewrite must never silently erase it).
* **Host-local.** One journal per host. Every entry stamps `host_id` so a future
  cross-host merge is *possible*, but cross-host coordination is out of scope.
* **Bounded by an explicit compaction, not auto-rotation.** The WAL is
  append-only; `compact()` folds it to a single CHECKPOINT snapshot of the live
  set when an operator runs `dos journal compact`. It is **live-set-preserving**
  (`replay(compact(E)) == replay(E)` — the arbiter sees the identical leases), but
  NOT liveness-fold-preserving: a CHECKPOINT carries no `ts`, so a mid-flight
  compaction makes a still-live run read STALLED until its next beat (always the
  safe direction — compaction can never fabricate a beat/event). Run it in a quiet
  window. An automatic size/age trigger + a `[journal]` retention seam is deferred.

Read::

    dos journal tail [N]      # last N entries (default 20)
    dos journal replay        # reconstructed live-lease set
    dos journal seq           # current max seq
    dos journal compact       # fold to a CHECKPOINT snapshot (bound the file)

Write is library-only (the writers are `lane_lease` / the supervisor driver, each
under its own mutex) — there is deliberately no `append` CLI subcommand, so
nothing can journal a decision outside the lock that serializes it.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dos import config as _config
from dos import durable_schema as _schema

# The durable-schema family + version for lane-journal records that carry a tag.
# Today ONLY the OP_ATTEMPT event tags itself (docs/207 §3) — the lease ops predate
# the tag contract and replay reads them as UNTAGGED (the tolerant legacy floor, so
# no existing journal needs migrating). The version is bumped ONLY on a non-additive
# change to a tagged record's shape; a new field is additive and never bumps it.
SCHEMA_FAMILY = "lane-journal"
LANE_JOURNAL_SCHEMA = 1

# Host-local WAL. The default resolves against the ACTIVE WORKSPACE (the injected
# config), never the package's own tree (the workspace-root rule). The
# `DISPATCH_LANE_JOURNAL_PATH` env override is the workspace-neutral alias;
# `JOB_LANE_JOURNAL_PATH` is a back-compat alias an early consumer still sets.


def _default_journal_path() -> Path:
    return _config.active().paths.lane_journal


# Module-level convenience handle, resolved LAZILY (PEP 562 `__getattr__`) the
# first time `lane_journal.JOURNAL_PATH` is actually read — NOT at import. The
# original eager `JOURNAL_PATH = Path(... or _default_journal_path())` forced
# `config.active()` (→ `default_config` → the git-SHA subprocess + the WMI
# platform probe in `gather_env_print`) to run the instant `import dos`
# happened, taxing EVERY consumer's cold start ~tens of ms for a path almost no
# caller reads as a value (the live functions all call `_journal_path()` below,
# which re-resolves per call so a test that sets the env override after import
# still redirects). Deferring it keeps `import dos` cheap; the name stays exported
# for back-compat (`from dos.lane_journal import *` / the host re-export shims).
def __getattr__(name: str) -> Any:  # noqa: D401 — PEP 562 module hook
    if name == "JOURNAL_PATH":
        return _journal_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# The decision vocabulary. ACQUIRE/RELEASE ship in LJ1 (the throughline);
# the rest are wired in LJ2/LJ5 but the replay folder already understands
# them so a forward-compatible journal replays cleanly the day they appear.
OP_ACQUIRE = "ACQUIRE"
OP_RELEASE = "RELEASE"
OP_HEARTBEAT = "HEARTBEAT"
OP_SCAVENGE = "SCAVENGE"
OP_REFUSE = "REFUSE"        # LJ2 — recorded, but does NOT mutate lease state
OP_RECONCILE = "RECONCILE"  # LJ5 — crash-recovery reconcile, recorded. NO
                            # in-kernel writer: RECONCILE re-asserts a lease into
                            # a SEPARATE live registry the WAL says is held. This
                            # kernel has ONE store — `replay` reconstructs the
                            # registry FROM the WAL — so there is no second store
                            # to reconcile into, and the writer is host-side (a
                            # host with its own execution-state.yaml). The op +
                            # the replay fold (folds it identically to ACQUIRE)
                            # stay for that forward-compat; the kernel just never
                            # emits one. (Contrast SCAVENGE, which IS in-repo —
                            # eviction is a real action against the one WAL.)
OP_HALT = "HALT"            # docs/99 — a STOP DECISION for an in-flight run;
                            # recorded as INTENT, does NOT mutate lease state
                            # (the eventual RELEASE/SCAVENGE confirms eviction)
OP_ENFORCE = "ENFORCE"      # docs/189 §C4 — an ENFORCEMENT OUTCOME: a handler
                            # (dos.enforce) proposed an effect on an intervention
                            # decision (observe/warn/block/defer). Recorded for
                            # forensics like REFUSE/HALT — it grants/removes NO
                            # lease, so replay ignores it for state. This is the
                            # missing PRODUCER that makes "which call was blocked,
                            # by which handler, and what was substituted?" answerable
                            # from the spine (the ARIES-recovery gap a blocking
                            # handler otherwise left no trace of). The kernel records
                            # the proposal; a host PEP performed (or did not) the act.
OP_ADOPT = "ADOPT"          # C5 (docs/95) — a lease OWNERSHIP TRANSFER: a new
                            # acquirer takes over a lease whose holder is gone but
                            # whose recorded children are still live. replay rewrites
                            # the live lease's holder/pid/host_id to the adopter while
                            # KEEPING its (loop_ts, lane) identity, tree, and children
                            # — adoption is an ownership rewrite, NEVER a kill (the
                            # grandchildren keep running). The host decides WHEN to
                            # adopt (it measures child liveness at the boundary, now
                            # keyed on the kernel's recorded child pids via the
                            # proc-liveness rung); the kernel provides only the
                            # non-forgeable child-identity ANCHOR + this transfer op.
OP_ATTEMPT = "ATTEMPT"      # docs/207 §3 — a PICK ATTEMPT was made on a unit, with
                            # its outcome when known. The anti-churn cross-run memory
                            # the bare loop lacked: `cooldown.cooldown_verdict` folds
                            # these to answer "have I already tried this unit and it
                            # didn't move?" Like REFUSE/HALT/ENFORCE it grants/removes
                            # NO lease, so replay ignores it for state — it is a
                            # forensic event the cooldown fold reads via `read_all`,
                            # never `replay`. Carries a `durable_schema` tag (the FIRST
                            # lane-journal record to — older readers see UNTAGGED and a
                            # tolerant fold accepts it; the tag future-proofs the fold).
OP_SPAWN = "SPAWN"          # docs/reports/2026-06-09 (the dos-top visibility gap) —
                            # an INTENT-TO-TAKE-A-LANE recorded the instant a launcher
                            # commits to a lane, BEFORE preflight and before the durable
                            # ACQUIRE lands. It closes the SPAWN→ACQUIRE blind window:
                            # `dos top` reads only the WAL, so a loop that has decided
                            # its lane but not yet acquired is invisible (a *successful*
                            # `arbitrate` PERSISTS nothing — purity boundary). Like
                            # REFUSE/HALT/ENFORCE/ATTEMPT it grants/removes NO lease, so
                            # it is NOT in `_STATE_MUTATING_OPS` and `replay` ignores it
                            # for state — a not-yet-real run can therefore NEVER
                            # double-book a region (the docs/281 phantom-lease failure
                            # mode is structurally impossible here: an intention is not a
                            # hold). It is the durable, cross-process home for the
                            # supervisor's in-memory `pending` field (`supervise.py:106`):
                            # `dispatch_top` folds the RECENT SPAWNs for a lane with no
                            # live lease into a `SPAWNING` chip with a short TTL, so a
                            # launch that dies in preflight ages out on its own (the same
                            # self-heal `_expire_dead` gives a crashed holder). The
                            # eventual ACQUIRE supersedes the SPAWN (a held lease wins the
                            # chip); a RELEASE with no intervening ACQUIRE is a
                            # launch-aborted record.
OP_CHECKPOINT = "CHECKPOINT"  # LJ compaction (docs/82) — a SNAPSHOT of the live
                            # set written at the head of a compacted journal.
                            # NOT a state-mutating op in the incremental sense:
                            # `replay` handles it specially — it RESETS the
                            # reconstructed live set to the checkpoint's payload,
                            # then folds the tail of fresh entries that follow it.
                            # This is what lets `compact` discard the long history
                            # of dead leases without losing a still-live one: the
                            # surviving leases ride forward in the snapshot, not as
                            # their (now-deleted) original ACQUIRE lines.

# Ops that change the reconstructed lease set. REFUSE is a decision worth
# logging (someone wanted a lane and couldn't have it) but it grants nothing,
# so replay ignores it for state reconstruction. HALT is likewise a recorded
# DECISION (docs/99): "stop this run that is not done" — but it is the kernel's
# *intent*, decoupled from the *fact* of the lease ending (the kernel cannot
# know the host's stop signal landed), so like REFUSE it grants/removes nothing
# in replay; a later RELEASE/SCAVENGE the driver appends is what actually evicts.
# SPAWN is the symmetrical INTENT on the acquire side: "a run is coming to this
# lane" — also decoupled from the *fact* of the hold, which only the eventual
# ACQUIRE records, so it too grants nothing in replay (an intention that never
# acquires can never strand a phantom hold). This is what lets an auditor tell a
# *kill* (HALT→SCAVENGE) from a *natural death* (RELEASE), and a *coming* run
# (SPAWN→ACQUIRE) from a *held* one — the forensic point of the closed op
# vocabulary.
_STATE_MUTATING_OPS = frozenset(
    {OP_ACQUIRE, OP_RELEASE, OP_HEARTBEAT, OP_SCAVENGE, OP_RECONCILE, OP_ADOPT}
)


def journal_now_iso() -> str:
    """Second-resolution UTC stamp for journal entries.

    Deliberately finer than a minute-only loop stamp: the journal needs to order
    events within a minute, and the monotonic `seq` is the real tiebreak, but a
    second-resolution `ts` makes the log human-readable without ambiguity (and is
    the instant the heartbeat-freshness fold trusts — `journal_delta`).
    """
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _journal_path() -> Path:
    # Re-read the env var each call so a test that sets the override after
    # import still redirects. Falls back to the active workspace config when no
    # override is set.
    return Path(
        os.environ.get("DISPATCH_LANE_JOURNAL_PATH")
        or os.environ.get("JOB_LANE_JOURNAL_PATH")
        or _default_journal_path()
    )


def read_all(path: Path | None = None) -> list[dict]:
    """Return every journal entry in append order.

    Skips an unparseable TRAILING line (a torn final record from a crash
    mid-append) — but a non-trailing corrupt line is a real integrity problem
    and is surfaced (kept as a sentinel so a caller/audit notices), never
    silently dropped from the middle of the order.
    """
    p = path or _journal_path()
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
            # Tolerate ONLY a torn final line (crash mid-append). Any earlier
            # corrupt line is a genuine integrity breach — record a sentinel
            # so audit/replay can flag it rather than pretend order is intact.
            if i == len(lines) - 1:
                break
            out.append({"op": "_CORRUPT", "_raw": s, "_line": i})
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def tail(n: int = 20, path: Path | None = None) -> list[dict]:
    """The last `n` entries — reads the whole file then slices.

    The journal is NOT auto-rotated: on a long-lived fleet it grows unbounded and
    this (like `read_all`/`replay`/`next_seq`) is O(file). Run `dos journal
    compact` (`compact()` + the `lane_lease.compact_journal` I/O shell) to bound
    it: that folds the WAL to a single CHECKPOINT snapshot of the live set,
    live-set-preserving (`replay(compact(E)) == replay(E)` — the arbiter sees the
    identical leases; see `compact` for the liveness-fold caveat). An automatic
    size/age-triggered rotation + a `[journal]` retention seam is deferred."""
    entries = read_all(path)
    return entries[-n:] if n > 0 else entries


def next_seq(path: Path | None = None) -> int:
    """The seq to stamp on the next entry = max existing seq + 1 (1-based).

    Read under the SAME `_StateFileLock` the caller holds for the registry
    write, so two concurrent acquirers can't mint the same seq.
    """
    mx = 0
    for e in read_all(path):
        try:
            s = int(e.get("seq") or 0)
        except (TypeError, ValueError):
            s = 0
        # An OP_CHECKPOINT carries the high-water `seq` of the history it
        # replaced (`seq_watermark`). After a compaction discards the lines that
        # held the prior max seq, the watermark is the ONLY surviving record of
        # it — so it must bound `next_seq` too, or a rewrite would let the next
        # append REUSE a seq from the discarded prefix and corrupt append order.
        try:
            w = int(e.get("seq_watermark") or 0)
        except (TypeError, ValueError):
            w = 0
        mx = max(mx, s, w)
    return mx + 1


def append(entry: dict, path: Path | None = None) -> dict:
    """Append one entry to the journal and `fsync` it to disk.

    `entry` is the caller's decision payload; this stamps `seq` (if absent),
    `ts` (if absent), and writes a single canonical-JSON line followed by a
    newline, then `flush()` + `os.fsync()` so the record is durable before
    the function returns (and thus before the caller mutates the registry).

    Returns the stamped entry (with seq/ts filled in) so the caller can log
    it. The caller is responsible for holding the state lock — `append` does
    NOT lock, because journal order must equal registry-mutation order and
    only the caller knows the surrounding critical section.
    """
    p = path or _journal_path()
    e = dict(entry)
    e.setdefault("seq", next_seq(p))
    e.setdefault("ts", journal_now_iso())
    line = json.dumps(e, sort_keys=True, default=str, ensure_ascii=False) + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    # O_APPEND makes the write atomic w.r.t. other appenders at the OS level;
    # the surrounding _StateFileLock already serializes our own callers, but
    # O_APPEND is the belt to that suspenders.
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return e


def _lease_identity(rec: dict) -> tuple[str, str]:
    """(loop_ts, lane) — the true lease identity (a loop_ts is minute-
    resolution so two disjoint-lane loops can share one; lane disambiguates).
    The same identity `journal_delta` scopes its liveness fold to."""
    return (str(rec.get("loop_ts") or ""), str(rec.get("lane") or ""))


def replay(entries: Iterable[dict]) -> list[dict]:
    """Fold the decision sequence into the authoritative live-lease set.

    Pure: entries in, lease list out (no disk). This is the WAL-recovery core
    and the LJ5 hero invariant — replaying the journal must reproduce the
    authoritative live-lease set the arbiter admits against. Folding rules:

      * ACQUIRE  -> add/replace the (loop_ts, lane) lease with its payload.
      * RELEASE  -> remove the (loop_ts, lane) lease.
      * SCAVENGE -> remove the (loop_ts, lane) lease (eviction).
      * HEARTBEAT-> update the live lease's heartbeat_at (no-op if absent).
      * RECONCILE-> re-assert a lease a separate registry was missing (LJ5; no
        in-kernel writer — single-store kernels reconcile via this very replay).
      * CHECKPOINT-> RESET the live set to the snapshot's `leases` payload, in
        payload order, then keep folding the tail (LJ compaction, docs/82). This
        is what lets `compact` discard the long dead-lease history without losing
        a still-live lease — the surviving leases ride forward in the snapshot.
        Handled BEFORE the state-mutating-ops gate so it can never be skipped.
      * HALT / REFUSE / ENFORCE / ATTEMPT / SPAWN / _CORRUPT / unknown -> ignored for
        state (HALT records a stop INTENT, REFUSE a denied request, ENFORCE an
        enforcement outcome, ATTEMPT a pick attempt for the cooldown fold, SPAWN an
        intent-to-take-a-lane for the dos-top SPAWNING chip — none grants or removes a
        lease; a corrupt sentinel must not silently mutate state).

    Returns leases in first-acquired order (stable), each a dict shaped like the
    lease rows `lane_lease.acquire` writes, so an audit can diff byte-for-byte.
    """
    # Ordered by first-acquire so the reconstructed list is stable/comparable.
    live: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []

    def _forget(key: tuple[str, str]) -> None:
        live.pop(key, None)
        if key in order:
            order.remove(key)

    for e in entries:
        op = str(e.get("op") or "")
        if op == OP_CHECKPOINT:
            # A compaction snapshot: RESET the reconstructed live set to exactly
            # the leases the checkpoint carries (in payload order), discarding
            # whatever was folded so far. This must run BEFORE the
            # _STATE_MUTATING_OPS gate below — a checkpoint is not an incremental
            # op, it is a re-base of the fold. Because `compact` writes a snapshot
            # of `replay(prefix)`, re-basing onto it yields the identical live set:
            # the replay(compact(E)) == replay(E) invariant.
            live.clear()
            order.clear()
            payload = e.get("leases")
            if isinstance(payload, list):
                for lease in payload:
                    if not isinstance(lease, dict):
                        continue
                    key = _lease_identity(lease)
                    if not key[0] and not key[1]:
                        continue
                    if key not in live:
                        order.append(key)
                    live[key] = dict(lease)
            continue
        if op not in _STATE_MUTATING_OPS:
            continue  # REFUSE, HALT, ENFORCE, _CORRUPT, unknown — recorded, not state
        key = _lease_identity(e)
        if not key[0] and not key[1]:
            continue
        if op in (OP_ACQUIRE, OP_RECONCILE):
            lease = e.get("lease")
            if not isinstance(lease, dict):
                # Forward-compat: an ACQUIRE may carry the lease fields inline
                # rather than nested under "lease". Reconstruct from the
                # known lease keys present on the entry.
                lease = {
                    k: e[k] for k in (
                        "lane", "lane_kind", "tree", "loop_ts", "host_id",
                        "pid", "acquired_at", "heartbeat_at", "ttl_minutes",
                        "holder", "run_id",
                    ) if k in e
                }
            if key not in live:
                order.append(key)
            live[key] = dict(lease)
        elif op in (OP_RELEASE, OP_SCAVENGE):
            _forget(key)
        elif op == OP_HEARTBEAT:
            if key in live:
                hb = e.get("heartbeat_at") or e.get("ts")
                if hb:
                    live[key]["heartbeat_at"] = hb
        elif op == OP_ADOPT:
            # Ownership TRANSFER (C5): a new acquirer takes over the live lease at
            # this (loop_ts, lane). Rewrite ONLY ownership (holder/pid/host_id) +
            # refresh the heartbeat so the adopted lease is not immediately stale;
            # KEEP the lease's identity, tree, ttl, and children. NEVER add a lease
            # that isn't live — adoption transfers an EXISTING hold, it does not
            # grant one (an ADOPT against a released/scavenged key is a no-op, the
            # safe direction: you cannot adopt a lease no one holds).
            if key in live:
                lease = live[key]
                for fld in ("holder", "pid", "host_id"):
                    if fld in e and e[fld] is not None:
                        lease[fld] = e[fld]
                hb = e.get("heartbeat_at") or e.get("ts")
                if hb:
                    lease["heartbeat_at"] = hb
    return [live[k] for k in order if k in live]


# --------------------------------------------------------------------------
# Entry builders — the writer (`lane_lease` / the supervisor driver) uses these
# so the entry shape is defined HERE (one home), not duplicated at each call
# site. Pure constructors.
# --------------------------------------------------------------------------


def adopt_entry(lease: dict, *, new_holder: str, new_pid: Any = None,
                new_host_id: str = "", heartbeat_at: str = "", reason: str = "") -> dict:
    """Build an ADOPT entry: transfer ownership of a live lease to `new_holder` (C5).

    The eviction-free sibling of `scavenge_entry`. Where SCAVENGE removes a lease
    whose holder is gone AND whose work is done, ADOPT transfers a lease whose holder
    is gone but whose recorded children are STILL LIVE — so the lane keeps its
    in-flight grandchildren instead of being reclaimed out from under them or wedged
    to TTL. replay rewrites the live lease's `holder`/`pid`/`host_id` (and refreshes
    the heartbeat) while keeping its identity, tree, ttl, and children.

    The KERNEL never decides to adopt — it cannot non-forgeably tell orphaned-but-
    working from stalled-dead (that needs grandchild liveness, host boundary I/O via
    the proc-liveness rung). The host gathers that evidence, decides, and appends this
    op; the kernel provides only the transfer mechanism + the child-identity anchor
    `acquire_entry` records. `heartbeat_at` defaults to now so the adopted lease is not
    instantly stale under the new owner.
    """
    return {
        "op": OP_ADOPT,
        "lane": lease.get("lane"),
        "loop_ts": lease.get("loop_ts"),
        "holder": new_holder,
        "pid": new_pid,
        "host_id": new_host_id or lease.get("host_id"),
        "prev_holder": lease.get("holder"),
        "heartbeat_at": heartbeat_at or journal_now_iso(),
        "reason": reason,
    }


def acquire_entry(lease: dict, *, reason: str = "", prev_holder: Any = None,
                  env_digest: str = "", children: Any = None,
                  run_id: Any = None) -> dict:
    """Build an ACQUIRE entry from the lease dict the writer just minted.

    `run_id` (OPTIONAL, docs/118 Size S / docs/137) is the CID spine id of the run
    that took this lease — the field that closes the WAL↔spine join. `refuse_entry`
    and `halt_entry` already carry a `run_id`; the GRANT side did not, so a *held*
    lane (unlike a *refused* one) could not be traced back to the run that wanted
    it — the exact gap docs/118 measured at `0` join-ready ACQUIREs. It rides on
    the NESTED lease so `replay` reconstructs it onto the live lease (and an ADOPT
    preserves it), where any reader keyed on `run_id` (`decisions`,
    `trajectory_audit._lease_run_id`, `dos trace`) reads it off. Purely ADDITIVE
    like `env_digest`/`children`: an ACQUIRE with no `run_id` replays byte-identically
    (the lane-journal forward-compat contract). Recorded, never adjudicated on — the
    kernel does not gate on which run holds a lane; it just makes the hold
    *attributable* (the docs/76 record-don't-decide line).

    `children` (OPTIONAL, C5) is the list of child identities the holder spawned —
    `[{"run_id": ..., "pid": ...}, ...]` — the non-forgeable ANCHOR that lets a later
    acquirer tell "the holder is gone but its grandchildren are still working" from
    "this lease is simply dead." Purely ADDITIVE like `env_digest`: an ACQUIRE with no
    `children` replays unchanged. The kernel RECORDS the anchor; it never measures the
    children's liveness (that is host boundary I/O via the proc-liveness rung) — it
    just makes the host's later child-liveness probe key on a durable identity instead
    of a forgeable log-growth signal. Rides on the lease payload so replay carries it
    onto the reconstructed lease (and an ADOPT preserves it).

    `env_digest` (OPTIONAL) is the holder's environment-print digest — the
    `env_print.EnvPrint.digest` of the runtime that took the lease (docs/115
    primitive 1). The ACQUIRE is where a lease is BORN (once per run's hold), so it
    is the right entry to carry *under what* the hold happened; later beats /
    releases carry only identity. Just the cheap KEY rides here, not the full print
    (that lands once per run-dir in the intent ledger's INTENT record) — so
    `dos top` / replay can answer "which environment holds this lane" and join back
    to the full print by digest. Purely ADDITIVE: an ACQUIRE with no `env_digest`
    is a hold from a kernel that did not stamp prints, replayed unchanged (a new
    optional field never disturbs the fold — the lane-journal forward-compat
    contract). Recorded, never adjudicated on (the docs/76 line); the
    `FLEET_ENV_MISMATCH` gate that COMPARES a digest to a pin is a later phase, and
    it lives in the arbiter, not here.
    """
    e = {
        "op": OP_ACQUIRE,
        "lane": lease.get("lane"),
        "lane_kind": lease.get("lane_kind"),
        "tree": lease.get("tree"),
        "loop_ts": lease.get("loop_ts"),
        "host_id": lease.get("host_id"),
        "pid": lease.get("pid"),
        "ttl_minutes": lease.get("ttl_minutes"),
        "prev_holder": prev_holder,
        "reason": reason,
        # Nest the full lease so replay reconstructs it exactly.
        "lease": dict(lease),
    }
    if env_digest:
        e["env_digest"] = env_digest
    # The CID spine id (docs/118 S / docs/137) rides on the NESTED lease so replay
    # carries it onto the reconstructed live lease and a later ADOPT preserves it —
    # the WAL↔spine join key. Prefer an explicit `run_id` arg; else honor one already
    # on the lease dict (a host that stamped it at mint time). Additive — absent ⇒ no
    # `run_id` on the lease, replayed unchanged.
    rid = run_id if run_id is not None else lease.get("run_id")
    if rid:
        e["lease"] = {**e["lease"], "run_id": str(rid)}
    # The child-identity anchor (C5) rides on the nested lease so replay carries it
    # onto the reconstructed lease and a later ADOPT preserves it. Prefer an explicit
    # `children` arg; else honor one already on the lease dict (a host that stamps it
    # at mint time). Additive — absent ⇒ no `children` key, replayed unchanged.
    kids = children if children is not None else lease.get("children")
    if kids:
        e["lease"] = {**e["lease"], "children": list(kids)}
    return e


def release_entry(lease: dict, *, reason: str = "explicit") -> dict:
    """Build a RELEASE entry for a dropped lease."""
    return {
        "op": OP_RELEASE,
        "lane": lease.get("lane"),
        "loop_ts": lease.get("loop_ts"),
        "host_id": lease.get("host_id"),
        "reason": reason,
    }


def heartbeat_entry(lease: dict, *, heartbeat_at: str = "") -> dict:
    """Build a HEARTBEAT entry refreshing a live lease's liveness stamp.

    The HEARTBEAT path is now complete end-to-end: this builder, the `replay`
    fold (which sets a live lease's `heartbeat_at` from this entry's
    `heartbeat_at` or its `ts`), the `journal_delta._HEARTBEAT_OPS` freshness
    rung, AND the effectful writer (`lane_lease.heartbeat`, the verb behind
    `dos lease-lane heartbeat`). That writer is what makes liveness SPINNING
    reachable from real journal evidence — before it, nothing emitted an
    OP_HEARTBEAT, so the newest beat was always the boundary ACQUIRE, which aged
    out to STALLED.

    A HEARTBEAT is a *beat*, not a state-change: replay keys it on the
    `(loop_ts, lane)` identity and updates the freshness of an already-live lease
    (a no-op if that lease isn't currently held), so it carries just the identity
    + the stamp, not the full lease body — and it is deliberately EXCLUDED from
    `journal_delta._EVENT_OPS`, so a fresh beat proves life without counting as
    progress (the SPINNING rung). `heartbeat_at` defaults to the entry `ts`
    (filled by `append`); `lane_lease.heartbeat` passes the append instant
    explicitly so the fold trusts the writer's own clock.
    """
    e = {
        "op": OP_HEARTBEAT,
        "lane": lease.get("lane"),
        "loop_ts": lease.get("loop_ts"),
        "host_id": lease.get("host_id"),
    }
    if heartbeat_at:
        e["heartbeat_at"] = heartbeat_at
    return e


def attempt_entry(
    unit_id: str,
    *,
    outcome: str,
    run_id: Any = None,
    lane: str = "",
    loop_ts: str = "",
    host_id: Any = None,
) -> dict:
    """Build an OP_ATTEMPT entry — a recorded PICK ATTEMPT on a unit (docs/207 §3).

    The anti-churn cross-run memory the bare loop lacked: a loop re-picked the same
    drained unit every iteration once its claim TTL lapsed (measured ~5% of runs
    shipping). This event records that a pick was ATTEMPTED, carrying its
    ``outcome`` when known, so `cooldown.cooldown_verdict` can fold the recent
    history and answer "have I already tried this unit and it didn't move?" — the
    `RECENTLY_ATTEMPTED` hold that skips a just-drained unit instead of re-dispatching.

    ``outcome`` is a typed token the cooldown fold reads (the closed set lives in
    `dos.cooldown.AttemptOutcome` — e.g. ``"shipped"`` / ``"drained"`` /
    ``"blocked"`` / ``"error"``); recorded verbatim, interpreted only by the fold.
    ``run_id`` is the CID spine id of the attempting run (optional). ``lane`` /
    ``loop_ts`` / ``host_id`` correlate the attempt to a lease when known.

    Like REFUSE/HALT/ENFORCE this is a FORENSIC event: OP_ATTEMPT is NOT in
    `_STATE_MUTATING_OPS`, so `replay` ignores it for lease-state reconstruction (a
    pick attempt grants/removes no lease) — journaling every attempt can never lose
    or invent a live lease, it only adds the history the cooldown fold reads via
    `read_all`. It carries a `durable_schema` tag (the FIRST lane-journal record to);
    `append` merges it if absent, so the fold is version-forward-compatible.
    """
    e = {
        **_schema.tag(SCHEMA_FAMILY, LANE_JOURNAL_SCHEMA),
        "op": OP_ATTEMPT,
        "unit_id": str(unit_id),
        "outcome": str(outcome),
        "lane": lane,
        "loop_ts": loop_ts,
        "host_id": host_id,
    }
    if run_id is not None:
        e["run_id"] = str(run_id)
    return e


def spawn_entry(
    *,
    lane: str,
    loop_ts: str = "",
    holder: str = "",
    host_id: Any = None,
    pid: Any = None,
    run_id: Any = None,
    reason: str = "",
) -> dict:
    """Build an OP_SPAWN entry — a recorded INTENT TO TAKE A LANE (the dos-top gap).

    The acquire-side sibling of `halt_entry`. A HALT says "a held run is going to
    stop"; a SPAWN says "a run is *coming* to this lane" — recorded the instant a
    launcher commits to a lane, BEFORE preflight and before the durable ACQUIRE. It
    exists to close the SPAWN→ACQUIRE blind window the audit names: `dos top` reads
    only the WAL, and a *successful* `arbitrate` persists nothing, so between launch
    and the first ACQUIRE a loop is invisible on the only surface the watchdog reads.

    Like `halt_entry`/`refuse_entry`/`attempt_entry` this is a FORENSIC INTENT, not a
    grant: OP_SPAWN is NOT in `_STATE_MUTATING_OPS`, so `replay` ignores it for lease
    reconstruction. That is the whole safety argument — an intent that never acquires
    can never strand a phantom hold (the docs/281 failure mode), and a not-yet-real
    run can never double-book a region the arbiter admits against. The `dispatch_top`
    SPAWNING chip is a SEPARATE fold over the recent SPAWNs (TTL-bounded, no-live-lease
    only), never the admission live set.

    `lane` is required (the region being committed to). `loop_ts`/`holder`/`host_id`/
    `pid`/`run_id` correlate the intent to the eventual ACQUIRE when known — the same
    identity tuple `acquire_entry` stamps, so a reader can join SPAWN→ACQUIRE. `reason`
    is free text for the operator (e.g. the launch context). All optional but `lane`.
    """
    e: dict = {
        "op": OP_SPAWN,
        "lane": lane,
        "loop_ts": loop_ts,
        "holder": holder,
        "host_id": host_id,
        "pid": pid,
        "reason": reason,
    }
    if run_id is not None:
        e["run_id"] = str(run_id)
    return e


def scavenge_entry(
    lease: dict, *, reason: str = "scavenged", prev_holder: Any = None
) -> dict:
    """Build a SCAVENGE entry for an evicted (orphaned) lease.

    The eviction sibling of `release_entry`: replay folds OP_SCAVENGE
    identically to OP_RELEASE (it removes the `(loop_ts, lane)` lease), so this
    carries the same eviction key — `loop_ts` + `lane` + `host_id` + `reason`.
    A scavenge is an *eviction*, not a voluntary drop, so it ALSO carries the
    forensic pair `pid` + `prev_holder` (`acquire_entry` stamps the same two):
    an operator reading the journal can see exactly which process/holder was
    reclaimed and why, without re-joining to the prior ACQUIRE. (The supervisor
    driver writes this when `supervise()` returns a REAP for a STALLED lease.)
    """
    return {
        "op": OP_SCAVENGE,
        "lane": lease.get("lane"),
        "loop_ts": lease.get("loop_ts"),
        "host_id": lease.get("host_id"),
        "pid": lease.get("pid"),
        "prev_holder": prev_holder,
        "reason": reason,
    }


def halt_entry(
    handle: str,
    *,
    reason: str = "",
    lane: str = "",
    loop_ts: str = "",
    host_id: Any = None,
    run_id: Any = None,
    command: Any = None,
) -> dict:
    """Build a HALT entry — a recorded STOP DECISION for an in-flight run (docs/99).

    The DOMAIN-FREE contract: `handle` is an **opaque** identifier the HOST
    supplies for the thing to stop — a pid string, a container id, a remote-task
    token, a harness `Workflow` id. The kernel records it verbatim and interprets
    NOTHING about it (it never learns "a run is a pid on this host" — that is the
    domain knowledge a substrate must not carry, docs/99 §3). `command`, if given,
    is the equally host-supplied stop command echoed onto the spine for forensics
    — the kernel records the proposed command, it never runs it.

    Unlike `scavenge_entry`, HALT carries no lease payload and removes no lease in
    `replay` (it is NOT in `_STATE_MUTATING_OPS`): it is the kernel's *intent* to
    stop, decoupled from the *fact* of the lease ending, which only a later
    RELEASE/SCAVENGE the driver appends (once the stop is confirmed) records. The
    lane/loop_ts/host_id are carried when known purely so an operator can correlate
    the HALT to the lease it targeted, without re-joining to the ACQUIRE.
    """
    return {
        "op": OP_HALT,
        "handle": handle,
        "lane": lane,
        "loop_ts": loop_ts,
        "host_id": host_id,
        "run_id": run_id,
        "command": command,
        "reason": reason,
    }


def refuse_entry(
    decision: Any,
    *,
    owner: str,
    lane: str = "",
    loop_ts: str = "",
    host_id: Any = None,
    run_id: Any = None,
    reason_class: str = "",
) -> dict:
    """Build a REFUSE entry — a recorded DENIED lane request (LJ2 / docs/82).

    The forensic sibling of `acquire_entry`: an ACQUIRE records that someone GOT a
    lane; a REFUSE records that someone WANTED one and could not have it. Without
    it the journal cannot answer the question its own module docstring poses —
    "why was I refused at 14:03?" — because a denied `arbitrate` leaves no trace
    at all. Three readers already CONSUME `OP_REFUSE` (the decisions queue, the
    central-index home, the trajectory audit); this is the missing PRODUCER.

    `decision` is duck-typed off the pure `arbiter.LaneDecision` (or any object
    exposing `.reason` / `.lane`) — the builder reads only those two attributes,
    so it stays a pure stdlib leaf with no kernel import of the arbiter. `owner`
    is the requester tag (recorded as `holder`, mirroring how `acquire_entry`
    threads the lease holder). `reason_class` is the *typed* refusal token for a
    future arbiter surface that carries one (`AdmissionVerdict.reason_class`);
    today it defaults to `""` and the readers degrade an empty token gracefully.

    Crucially, `OP_REFUSE` is NOT in `_STATE_MUTATING_OPS`, so `replay` ignores it
    for state reconstruction (a denied request grants nothing): journaling every
    refuse can never lose or invent a live lease — it only adds history.
    """
    return {
        "op": OP_REFUSE,
        "lane": lane or getattr(decision, "lane", "") or "",
        "loop_ts": loop_ts,
        "host_id": host_id,
        "run_id": run_id,
        "holder": owner,
        "reason": getattr(decision, "reason", "") or "",
        "reason_class": reason_class,
    }


def enforce_entry(
    proposal: Any,
    *,
    owner: str = "",
    lane: str = "",
    loop_ts: str = "",
    host_id: Any = None,
    run_id: Any = None,
    tool: str = "",
) -> dict:
    """Build an OP_ENFORCE entry — a recorded ENFORCEMENT OUTCOME (docs/189 §C4).

    The forensic sibling of `refuse_entry`, for the actuation seam (`dos.enforce`):
    a REFUSE records that a lane request was denied; an ENFORCE records that a
    handler PROPOSED an effect on an intervention decision — observe / warn / block
    (with a synthetic substitute) / defer. Without it, a handler that withholds a
    tool call leaves no trace on the spine, so an auditor (or a `resume`) cannot
    answer "which call was blocked at 14:03, by which handler, and what was
    substituted?" — the ARIES-recovery gap docs/189 names.

    `proposal` is duck-typed off `dos.enforce.EffectProposal` (the builder reads
    only `.to_dict()`, or falls back to the bare attributes) so this stays a pure
    stdlib leaf with no kernel import of the enforce module — the same discipline
    `refuse_entry` uses to read a `LaneDecision` without importing the arbiter. The
    proposal body is stored under `proposal`; the chosen rung is lifted to a
    top-level `intervention` for cheap filtering, the typed `reason_class` is lifted
    to the top level (the SAME closed-vocab token `refuse_entry` writes — the
    decisions queue and the cause-resolution fold read it there, never the nested
    body), and `dispatch_call` / `withheld` make "did the real call fire?" answerable
    without re-reading the body.

    `owner` is the requester/actor tag (recorded as `holder`, mirroring
    `acquire_entry`/`refuse_entry`); `tool` is the host-supplied name of the tool
    call the decision was about (opaque to the kernel, echoed for correlation).

    Crucially, `OP_ENFORCE` is NOT in `_STATE_MUTATING_OPS`, so `replay` ignores it
    for state reconstruction (an enforcement proposal grants/removes no lease):
    journaling every enforcement outcome can never lose or invent a live lease — it
    only adds history.
    """
    body = proposal.to_dict() if hasattr(proposal, "to_dict") else dict(proposal or {})
    # Lift the rung + dispatch flag to the top level for cheap forensic filtering,
    # tolerating either an EffectProposal (`.intervention` is an enum) or a raw dict.
    rung = body.get("intervention", getattr(proposal, "intervention", ""))
    rung = getattr(rung, "value", rung) or ""
    dispatch = body.get("dispatch_call")
    if dispatch is None:
        dispatch = getattr(proposal, "dispatch_call", None)
    # The TYPED refusal token is lifted to the top level for the SAME reason
    # `refuse_entry` lifts it (and `intervention`/`reason` above): the decisions
    # queue and the cause-resolution fold (`decisions._refusal_kind`,
    # `picker_oracle.resolve_cause`) read the top-level `reason_class`, NOT the
    # nested `proposal` body. Without this lift an ENFORCE-recorded refusal is
    # LESS forensically recoverable than a REFUSE-recorded one — the closed-vocab
    # token that the whole refusal-recovery story turns on is buried where no
    # reader looks, so a SELF_MODIFY block reads as an UNCLASSIFIED refusal. An
    # absent token degrades to "" exactly as `refuse_entry`'s does.
    reason_class = (
        body.get("reason_class", getattr(proposal, "reason_class", "")) or ""
    )
    return {
        "op": OP_ENFORCE,
        "lane": lane,
        "loop_ts": loop_ts,
        "host_id": host_id,
        "run_id": run_id,
        "holder": owner,
        "tool": tool,
        "intervention": str(rung),
        "dispatch_call": bool(dispatch) if dispatch is not None else None,
        "withheld": (not dispatch) if dispatch is not None else None,
        "handler": body.get("handler", getattr(proposal, "handler", "")) or "",
        "reason": body.get("reason", getattr(proposal, "reason", "")) or "",
        "reason_class": reason_class,
        "proposal": body,
    }


def checkpoint_entry(leases: list[dict], *, seq_watermark: int) -> dict:
    """Build an OP_CHECKPOINT snapshot of the authoritative live-lease set.

    Written at the HEAD of a compacted journal (`compact`): it carries the full
    live set folded from the discarded history so `replay` can reconstitute it
    without the original ACQUIRE lines, plus `seq_watermark` (the max `seq` seen
    in the discarded history) so `next_seq` stays monotonic across a rewrite that
    deleted the lines holding the prior high-water mark. Pure constructor.
    """
    return {
        "op": OP_CHECKPOINT,
        "leases": [dict(l) for l in leases],
        "seq_watermark": int(seq_watermark),
    }


def compact(entries: Iterable[dict]) -> list[dict]:
    """Fold a journal down to a single CHECKPOINT (+ preserved corrupt sentinels).

    PURE — entries in, a SHORTER entry list out, no disk, no clock. This is the
    compaction core the I/O shell (`lane_lease.compact_journal`) writes back over
    the WAL crash-safely. The discipline that makes it safe to discard the long
    history of dead leases is the same one `replay` uses: fold to the authoritative
    live set, then SNAPSHOT it — so a still-live ACQUIRE older than any cutoff
    survives in the checkpoint payload, never dropped. A naive "delete old lines"
    would forget a held lane and the kernel would false-ADMIT a colliding tree —
    the catastrophic lost-live-lease bug this fold-to-snapshot design forecloses.

    The DIFFERENTIAL-EQUIVALENCE invariant (pinned by a test):
        replay(compact(E)) == replay(E)
    holds because `replay`'s CHECKPOINT branch RESETS its live set to exactly the
    payload this writes — the leases `replay(E)` would itself reconstruct. This is
    equivalence for the ARBITER's live set, NOT for the liveness fold: a CHECKPOINT
    carries no `ts` and is in neither `journal_delta._EVENT_OPS` nor
    `_HEARTBEAT_OPS`, so a still-live run's beat anchor is dropped by compaction and
    it reads STALLED to the liveness oracle until its next ACQUIRE/HEARTBEAT. That
    is always the SAFE direction — compaction can never fabricate an event or beat,
    so it can never cause a false-ADVANCING/SPINNING — but it is why compaction is
    an operator verb for a quiet window, not an automatic per-append rotation.

    `seq_watermark` is derived from the input only (max existing `seq`), so the
    fold reads no clock and `next_seq` over the compacted journal is `>=`
    `next_seq` over the original — never a reused seq. A `_CORRUPT` sentinel in the
    input is PRESERVED into the output (appended after the checkpoint): a mid-file
    integrity breach is real signal an audit must still see, never silently erased
    by a rewrite.
    """
    materialized = list(entries)
    live = replay(materialized)
    watermark = 0
    corrupt: list[dict] = []
    for e in materialized:
        try:
            s = int(e.get("seq") or 0)
        except (TypeError, ValueError):
            s = 0
        # A pre-existing checkpoint's watermark also bounds the next seq.
        try:
            w = int(e.get("seq_watermark") or 0)
        except (TypeError, ValueError):
            w = 0
        watermark = max(watermark, s, w)
        if str(e.get("op") or "") == "_CORRUPT":
            corrupt.append(dict(e))
    return [checkpoint_entry(live, seq_watermark=watermark)] + corrupt


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_tail = sub.add_parser("tail", help="print the last N entries")
    p_tail.add_argument("n", nargs="?", type=int, default=20)
    p_tail.add_argument("--json", action="store_true", help="raw JSONL")
    sub.add_parser("replay", help="print the reconstructed live-lease set")
    sub.add_parser("seq", help="print the current max seq")
    args = ap.parse_args(argv)

    if args.cmd == "tail":
        entries = tail(args.n)
        if args.json:
            for e in entries:
                print(json.dumps(e, sort_keys=True, default=str))
        else:
            if not entries:
                print("(journal empty)")
            for e in entries:
                seq = e.get("seq", "?")
                ts = e.get("ts", "?")
                op = e.get("op", "?")
                lane = e.get("lane", "")
                extra = e.get("reason") or ""
                loop = e.get("loop_ts") or ""
                print(f"#{seq:<5} {ts}  {op:9} {str(lane):14} "
                      f"{str(loop):16} {extra}")
        return 0

    if args.cmd == "replay":
        leases = replay(read_all())
        print(json.dumps(leases, indent=2, sort_keys=True, default=str))
        return 0

    if args.cmd == "seq":
        print(next_seq() - 1)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
