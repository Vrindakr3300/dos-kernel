"""marker-sensor — the boundary I/O for the wait-marker budget (loop_decide §wait-marker).

> **`loop_decide.wait_marker_budget(markers_emitted, max_markers)` is a PURE
> verdict over an integer count. SOMETHING has to remember, across the many
> short-lived hook invocations of one session, HOW MANY keep-alive markers this
> loop has already emitted — the Stop event the host hands us carries no such
> count. That is this module: the wait-marker axis's `posttool_sensor` — boundary
> I/O (the per-session `.dos/markers/<sid>.jsonl` tally) feeding the pure core,
> never inside the verdict.**

The problem this closes (docs: [[project-dos-poll-loop-antipattern]], the
`wait_marker_budget` docstring's "session 4b4ff97c burned 252 markers / ~$7.80"):
a `/loop`-style dispatch loop holds its turn open by emitting `claude -p`
keep-alive markers (or by re-reading a `.output` file in a tight tick), and each
marker is a FULL assistant turn that replays the whole system+skill+context out of
prompt cache for zero forward work. The pure `wait_marker_budget` can refuse a
marker once a budget is reached — but only if it is told the running count, and a
count threaded through a CLI flag (`--emitted N`) is exactly the "prose the model
must remember" the budget docstring criticizes. So we make the count
GROUND-TRUTH DURABLE STATE the model cannot forget: one append-only record per
marker, under the session's `.dos/markers/<sid>.jsonl`, replayed back to a count.

Why this is the EXACT sibling of `posttool_sensor`
==================================================

`posttool_sensor` is the in-flight boundary for `tool_stream`: append one
`StreamStep` per PostToolUse fire, replay the session's steps into a `ToolStream`
the pure `classify_stream` folds. This module is the SAME shape for the wait-marker
budget, but the fold is the simplest possible one — a COUNT:

  * **the accumulator** (`record_marker` / `marker_count`) — the one impure part:
    an append-only, `fsync`'d, schema-tagged, torn-tail-tolerant session tally,
    byte-mirroring `intent_ledger`'s ARIES discipline (the same idiom
    `posttool_sensor.append_step` / `read_stream` copy) so the count survives across
    the many separate hook processes of one session. A record is one tagged
    `{"op":"MARKER"}` line; the COUNT is the number of valid records replayed back.
  * the verdict itself is `loop_decide.wait_marker_budget` — PURE, already shipped,
    already green. This module never re-implements the allow/refuse arithmetic; it
    only supplies the count and persists the increment.

The polarity, stated sharply (the load-bearing correctness fact)
================================================================

This binds to a **Stop** hook, and its polarity is the INVERSE of `cmd_hook_stop`.
A keep-alive wait-marker is the loop CHOOSING NOT TO STOP — blocking its own Stop
to keep waiting. So:

  * budget REMAINS  (`wait_marker_budget(...).allow is True`)  → the loop MAY emit
    another marker → **block the Stop** (`{"decision":"block", "reason": …}`),
    holding the turn open one more marker.
  * budget EXHAUSTED (`.allow is False`)                       → stop polling →
    **allow the Stop** (emit NOTHING — an empty Stop output is CC's "allow stop") →
    the loop ends its turn and waits on the real Bash `<task-notification>`, which
    fires on the child's true exit regardless ([[project-dos-poll-loop-antipattern]]).

`cmd_hook_stop` BLOCKS a *false done* (the agent claimed ship, git disagrees);
this BLOCKS a *premature give-up only while the marker budget is unspent*, then
gets out of the way. Two Stop hooks, opposite triggers — keep them apart.

Why it is ADVISORY and fail-safe
================================

The kernel stays a PDP, not a PEP (docs/99): the block is a PROPOSAL the runtime
consumes. Every failure mode degrades to "emit nothing, exit 0" = let the agent
stop — a missing stdin, unparseable JSON, an unusable session_id, an accumulator
I/O error. The hook can refuse to keep a loop polling past its budget; it never
traps a loop open on its own inability to read or write, and it never blocks a
loop that has a real reason to keep working (the budget only counts MARKERS the
loop itself declared by firing this hook on a keep-alive turn).

⚓ Kernel discipline (the litmus): a PURE verdict-adapter — imports only sibling
kernel modules (`loop_decide`, `config`, `durable_schema`), names no host /
driver, resolves every path via `SubstrateConfig.paths` (never `__file__`), and
carries no policy of its own (the threshold is `wait_marker_budget`'s
`max_markers`, handed in at the CLI).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

from dos import config as _config
from dos import durable_schema as _schema

# The durable-schema family + version every marker record carries (the §6 schema
# gate, byte-mirroring `posttool_sensor`). Bumped ONLY on a NON-additive shape
# change. A record tagged a non-additively-newer version is REFUSED at read (never
# best-effort-parsed into a forged count).
SCHEMA_FAMILY = "wait-marker"
WAIT_MARKER_SCHEMA = 1

# The directory the per-session marker tallies live under, beneath `.dos/`. A
# sibling of `posttool_sensor`'s `.dos/streams/` — keyed by the host-authored
# `session_id` (the Stop event carries a `session_id`, not a DOS run-id), exactly
# as the stream accumulator is.
MARKERS_DIRNAME = "markers"

# The closed op vocabulary the tally records. `MARKER` is one no-op (keep-alive) turn;
# `RESET` is a forward-delta / session-boundary marker that ZEROES the running count
# (docs/259 §Follow-up 2 — the `tool_stream` ADVANCING analogue: progress earns the
# loop a fresh budget). A new op is ADDITIVE in a closed vocabulary, so adding `RESET`
# does NOT bump `WAIT_MARKER_SCHEMA` (the `durable_schema` additive contract): an old
# reader simply skips an op it does not count, a new reader gives it meaning.
MARKER_OP = "MARKER"
RESET_OP = "RESET"


def _now_iso() -> str:
    """Second-resolution UTC stamp for a marker record (the `intent_ledger` idiom)."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Boundary I/O — the ONE impure part: the session-scoped marker tally.
# Byte-mirrors `posttool_sensor`'s accumulator (which itself mirrors
# `intent_ledger`): fsync, O_APPEND, torn-tail tolerance, the §6 schema gate.
# A marker record is one append-only line; the COUNT is the number of valid lines.
# ---------------------------------------------------------------------------
def _safe_session_name(session_id: str) -> Optional[str]:
    """The sanitized filename stem for a host-authored `session_id`, or None to skip.

    Byte-identical to `posttool_sensor._safe_session_name`: `session_id` is a
    distrusted host-authored token, so strip any path separators / `..` / drive
    components (a path-traversal surface) and keep only the safe characters of a
    normal session uuid. An empty/whitespace token (or one that sanitizes to empty)
    returns None — no identity, no accumulator (the caller emits nothing rather than
    writing to a junk path).
    """
    if not isinstance(session_id, str):
        return None
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return safe or None


def markers_dir_for(cfg: "_config.SubstrateConfig | None" = None) -> Path:
    """The `.dos/markers/` directory under the active workspace. PURE path arithmetic.

    Rides `cfg.paths.dot_dos` (the per-project `.dos/` home), the sibling of
    `posttool_sensor`'s `.dos/streams/`. Never creates the dir — `record_marker` is
    the only creator (the read-only-path discipline)."""
    cfg = _config.ensure(cfg)
    return cfg.paths.dot_dos / MARKERS_DIRNAME


def marker_path_for(
    session_id: str, cfg: "_config.SubstrateConfig | None" = None
) -> Optional[Path]:
    """The `.dos/markers/<session_id>.jsonl` path for a session, or None if unusable.

    Pure path arithmetic (the `posttool_sensor.stream_path_for` idiom): never creates
    anything. Returns None when `session_id` sanitizes to empty (no safe filename) —
    the caller treats that as "no accumulator," emitting nothing.
    """
    safe = _safe_session_name(session_id)
    if safe is None:
        return None
    return markers_dir_for(cfg) / f"{safe}.jsonl"


def _marker_entry(*, reason: str | None = None, run_id: str | None = None) -> dict:
    """The durable record for one emitted marker — schema-tagged, canonical. PURE.

    Carries the §6 schema tag so a record written directly is self-declaring (the
    `posttool_sensor._step_entry` posture). `reason` (the budget verdict's
    operator-facing line) and `run_id` (the correlation-spine join key, when the
    active env carries one) are ADDITIVE optional fields — present only when known —
    so a record without them reads back identically and the schema version does NOT
    bump (the `durable_schema` additive contract).
    """
    e: dict = {
        **_schema.tag(SCHEMA_FAMILY, WAIT_MARKER_SCHEMA),
        "op": MARKER_OP,
    }
    if reason:
        e["reason"] = reason
    if run_id:
        e["run_id"] = run_id
    return e


def _reset_entry(*, reason: str | None = None, run_id: str | None = None) -> dict:
    """The durable record for one forward-delta / session-boundary RESET. PURE.

    Identical shape to `_marker_entry` but `op:"RESET"` — a record that, on replay,
    ZEROES the running no-op count (the `tool_stream` ADVANCING analogue, docs/259
    §Follow-up 2). Carries the same §6 schema tag (so it is self-declaring) and the
    same ADDITIVE optional `reason`/`run_id` fields; an additive new op never bumps the
    schema version (the `durable_schema` contract).
    """
    e: dict = {
        **_schema.tag(SCHEMA_FAMILY, WAIT_MARKER_SCHEMA),
        "op": RESET_OP,
    }
    if reason:
        e["reason"] = reason
    if run_id:
        e["run_id"] = run_id
    return e


def record_marker(
    session_id: str,
    cfg: "_config.SubstrateConfig | None" = None,
    *,
    path: Path | None = None,
    reason: str | None = None,
    run_id: str | None = None,
) -> None:
    """Append ONE marker record to the session's tally and `fsync` it.

    Copies `posttool_sensor.append_step`'s durability idiom EXACTLY (itself a copy of
    `intent_ledger.append`): stamp the record (the §6 schema tag + a `ts`), write one
    canonical-JSON line + newline through `os.open(O_WRONLY|O_APPEND|O_CREAT)` +
    `os.write` + `os.fsync` + `os.close`, so the record is durable before this
    returns and the append is atomic w.r.t. any other appender at the OS level.
    `mkdir(parents=True)` the markers dir lazily (the only creator). `path` overrides
    the resolved location (tests).

    Raises on an unusable `session_id` (no `path` and the session sanitizes to
    empty) — the CLI wraps this whole call in a fail-safe try/except (advisory: never
    block a real workflow on the sensor's own write failure), so a raise here degrades
    to "emit nothing," never a crashed turn.
    """
    _append_record(
        _marker_entry(reason=reason, run_id=run_id),
        session_id,
        cfg,
        path=path,
        what="record_marker",
    )


def record_reset(
    session_id: str,
    cfg: "_config.SubstrateConfig | None" = None,
    *,
    path: Path | None = None,
    reason: str | None = None,
    run_id: str | None = None,
) -> None:
    """Append ONE forward-delta RESET record to the session's tally and `fsync` it.

    The §Follow-up 2 zeroing event: a forward delta (a commit, a real tool result, or
    a host re-entering a fresh wait phase) appends a `RESET` record, and `marker_count`
    replays the count as markers-AFTER-the-last-reset — so progress earns the loop a
    fresh budget (the `tool_stream` ADVANCING analogue). Same durability idiom as
    `record_marker` (the `intent_ledger`/`posttool_sensor` `O_APPEND`+`fsync` append):
    the reset is durable and atomic at the OS level before this returns, never a
    truncation of the append-only log.

    Raises on an unusable `session_id` (no `path` and the session sanitizes to empty);
    the CLI wraps the call in a fail-safe try/except (advisory: a reset we could not
    persist must not crash the turn — it degrades to "no reset," which leaves the count
    HIGHER, the conservative refuse-more direction for a cost guard).
    """
    _append_record(
        _reset_entry(reason=reason, run_id=run_id),
        session_id,
        cfg,
        path=path,
        what="record_reset",
    )


def _append_record(
    entry: dict,
    session_id: str,
    cfg: "_config.SubstrateConfig | None" = None,
    *,
    path: Path | None = None,
    what: str = "record",
) -> None:
    """The shared durable-append both `record_marker` and `record_reset` ride. Impure.

    Stamp the (already schema-tagged) record with a `ts`, write one canonical-JSON line
    + newline through `os.open(O_WRONLY|O_APPEND|O_CREAT)` + `os.write` + `os.fsync` +
    `os.close` (the `posttool_sensor.append_step` / `intent_ledger.append` idiom), so
    the record is durable before this returns and the append is atomic w.r.t. any other
    appender at the OS level. `mkdir(parents=True)` the markers dir lazily (the only
    creator). `path` overrides the resolved location (tests). Raises (with `what` named)
    on an unusable `session_id` and no explicit `path`.
    """
    p = path or marker_path_for(session_id, cfg)
    if p is None:
        raise ValueError(f"{what} needs a usable session_id or an explicit path")
    entry.setdefault("ts", _now_iso())
    line = json.dumps(entry, sort_keys=True, default=str, ensure_ascii=False) + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def marker_count(
    session_id: str,
    cfg: "_config.SubstrateConfig | None" = None,
    *,
    path: Path | None = None,
    understands: int = WAIT_MARKER_SCHEMA,
) -> int:
    """Replay the session's tally into the no-op COUNT SINCE THE LAST RESET. The read-side.

    The count is "the number of readable MARKER records that appear AFTER the last
    readable RESET record" (docs/259 §Follow-up 1+2): a single forward pass where a
    MARKER increments and a RESET zeroes. With NO RESET in the file (every host today),
    this is byte-identical to the old "count all MARKERs" — so the shipped `dos hook
    marker` behavior is unchanged for any current tally; the reset only bites once a
    forward-delta RESET is written.

    Two distrust postures layered, byte-mirroring `posttool_sensor.read_stream` /
    `intent_ledger.read_all`:

      * **Torn-tail tolerance** — an unparseable line (a crash mid-append, or a
        mid-file corrupt line) is skipped: a half-written record is "didn't happen."
        For a MARKER this UNDER-counts (admit one more marker than strictly emitted);
        for a RESET this means the reset "didn't happen" so the count stays HIGHER —
        BOTH are the same conservative direction (refuse one MORE no-op turn, never one
        fewer), the right bias for an advisory cost guard. A torn RESET can never erase
        a real marker count it failed to fully write.
      * **Schema gate** (§6) — a record whose `schema` tag is a non-additively-newer
        version than `understands` is SKIPPED (a record this kernel is too old to
        read can never fabricate OR erase a count — a too-new RESET does not zero). An
        UNTAGGED (legacy) record is read permissively (the `durable_schema.UNTAGGED`
        tolerant side); a WRONG_FAMILY record (a foreign line) is skipped. An unknown
        op (neither MARKER nor RESET) is ignored, count unchanged.

    Returns 0 when the file is absent (no markers emitted yet — the budget's fresh
    floor). `understands` is injectable so a test can simulate an OLD reader meeting a
    NEW record.
    """
    p = path or marker_path_for(session_id, cfg)
    if p is None or not p.exists():
        return 0
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    count = 0
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            # Torn final / corrupt mid-file line → "didn't happen". For a MARKER this
            # under-counts; for a RESET the zeroing is skipped so the count stays
            # higher — both the safe (refuse-more) direction for a cost guard.
            continue
        if not isinstance(obj, dict):
            continue
        # The §6 schema gate. READABLE/UNTAGGED proceed; UNREADABLE_NEWER and
        # WRONG_FAMILY are skipped (a too-new/foreign record never forges a count and
        # — critically for a RESET — never erases one).
        v = _schema.classify(obj, family=SCHEMA_FAMILY, understands=understands)
        if v.readability not in (
            _schema.Readability.READABLE,
            _schema.Readability.UNTAGGED,
        ):
            continue
        op = obj.get("op")
        if op == MARKER_OP:
            count += 1
        elif op == RESET_OP:
            # A forward-delta reset zeroes the running no-op count — progress earns the
            # loop a fresh budget (the `tool_stream` ADVANCING analogue).
            count = 0
        # else: an unknown/absent op is not a counted no-op turn and not a reset.
    return count


# The session-boundary RESET (docs/259 §Follow-up 2) is now LIVE: `record_reset`
# appends an `op:"RESET"` record and `marker_count` replays the count as
# markers-after-the-last-reset, so a forward delta (or a host re-entering a fresh wait
# phase) zeroes the tally — the `tool_stream` ADVANCING analogue. The pure verdict over
# the resulting count is `noop_streak.classify` (the generalization of
# `wait_marker_budget` off "markers emitted" onto "no-op turns since the last forward
# delta"). What is STILL explicit (not auto-derived) is the reset TRIGGER: a host fires
# `dos hook marker --reset` on a forward-progress hook (SessionStart/UserPromptSubmit)
# or after a commit. Auto-deriving a RESET from a live git/journal delta (pulling
# `git_delta` into the marker boundary, the `liveness` evidence reader) is the remaining
# future step — it would close the loop fully but is a larger change than this cut.
