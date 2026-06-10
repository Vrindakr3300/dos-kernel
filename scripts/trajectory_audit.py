"""Sweep recent Claude Code session trajectories AND join them to DOS kernel
artifacts — one ranked report fusing what an agent *said it did* (the transcript)
with what the kernel *adjudicated* (the lane journal, run-id spine, liveness).

This is the DOS port + extension of the reference userland app's trajectory-audit
helper. The per-session fold (token waste, read-loops, shell-poll, keepalive-poll,
cache-miss, glob-storms, heaviest-by-cache-read) is lifted near-verbatim from that helper and
stays comparable to its waste-flag vocabulary. What DOS adds is the **join**: the
trajectory is the worker's self-narration; the lane journal + run-id spine are the
ground truth DOS exists to adjudicate. The headline this surfaces is the
narration-vs-ground-truth divergence — an agent burning tokens / polling WHILE the
kernel was *refusing* its lane (lease contention vs trajectory waste).

It is dev tooling that operates ON the package (it `import dos`); nothing under
`src/dos/` imports it — the one-way arrow `scripts/` keeps with the kernel, the
same as `release_context.py`. No kernel module is edited.

HONESTY DISCIPLINE (the whole point of DOS, applied to its own audit):

  * The live `.dos/lane-journal.jsonl` may be **benchmark exhaust** (the
    FleetHorizon closed-loop writes a synthetic journal of all-ACQUIRE entries
    with null `loop_ts` and `lane-NN` lanes). The report DETECTS this
    (`_journal_is_benchmark_only`) and flags it loudly so a synthetic journal
    never masquerades as real fleet evidence.
  * Refusals in today's journal are recorded as `op:ACQUIRE` with a
    `reason:"REFUSED: ..."` (the benchmark shape) — NOT `op:REFUSE`. So a refusal
    is recovered as `op==REFUSE` OR (`op==ACQUIRE` and `reason` matches
    `^REFUSED:`), covering both the future real writer and today's data.
  * There is **no shared key** between a session and a lease: a transcript carries
    `sessionId/cwd/gitBranch/timestamp`; a journal lease carries `run_id/lane/ts`.
    They never share a field. The join is therefore **time-window + workspace
    overlap**, and an overlap that is not 1:1 is reported as `AMBIGUOUS_JOIN`,
    never guessed.
  * SPINNING / SCAVENGED are NOT surfaced: nothing in the DOS dispatch path emits
    HEARTBEAT / SCAVENGE journal ops yet, so there is no evidence to back them.
    The liveness column (opt-in via `--start-sha`) is driven by the unambiguous
    git-commit rung, never the poisonable journal-event rung.

Pure over the files — single sequential read each, no tailing/polling (the very
anti-pattern this audit exists to catch). The clock and the report timestamp are
INJECTED (`--now-ms`, `--stamp`) so a reproducible path never reads a wall clock.

Usage:
    python scripts/trajectory_audit.py
        [--workspace <dir>]         # the audited DOS workspace (cfg seam; default cwd)
        [--projects-dir <dir>]      # override the transcript dir (default: derived from workspace)
        [--last <N>]                # default 30 most-recent sessions
        [--since <ISO|Nd|Nh>]       # e.g. 3d, 12h, 2026-05-17 (overrides --last)
        [--start-sha <sha>]         # baseline SHA → populate the liveness column
        [--format json|md]          # default md
        [--out <path>]              # write the report (default: stdout). Bare name → .dos/audits/
        [--stamp <YYYYmmddTHHMMSSZ>] # report timestamp (the skill passes Get-Date); else "report"
        [--now-ms <int>]            # injected wall clock for the liveness column
        [--route-findings]          # opt-in: append systemic findings to ~/.dos/decisions.jsonl
        [--read-loop-threshold <N>]      # default 4   (same file Read N+ times)
        [--poll-threshold <N>]           # default 3   (tail/cat/Get-Content same path)
        [--keepalive-threshold <N>]      # default 5   (wait-marker no-ops)
        [--glob-storm-threshold <N>]     # default 10  (Glob calls in one session)
        [--cache-miss-ratio <FLOAT>]     # default 0.30
        [--min-turns <N>]                # default 5   (cache-miss floor)

Exit codes:
    0   report produced
    2   no readable session files found / contract error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# scripts/ → repo root → make `import dos` work from a source checkout without an
# editable install (the release_context.py idiom). A real install already has it
# on the path; this is the belt to that suspenders.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# --- shared waste-flag vocabulary (kept in sync with job/headless_telemetry) ---
_POLL_COMMAND_PREFIXES = ("tail ", "head ", "cat ", "Get-Content ", "type ")
_KEEPALIVE_MARKERS = ("wait-marker", "keep-alive marker", "keepalive marker")

# A refusal recorded the benchmark way: op:ACQUIRE carrying a REFUSED: reason.
_REFUSED_REASON = re.compile(r"^\s*REFUSED:", re.IGNORECASE)
# The benchmark journal's lane shape (`lane-04`) / effort shape — a tell that the
# journal is synthetic FleetHorizon exhaust, not a real dispatch lane taxonomy.
_BENCH_LANE = re.compile(r"^lane-\d+$")

# --- token pricing (docs/130 Prong C: the $0 "observe" tier) ---------------
# The audit already reads REAL session token telemetry (input / cache_creation /
# cache_read / output); this prices it. Default $/MTok is Claude Opus 4.8 list
# (docs/128 §1, https://platform.claude.com/docs/en/about-claude/pricing):
#   input (cold)  $5    cache write counts as billed input at the 1.25× write
#   output        $25   rate; we fold cache_creation into billed input at the
#   cache read    $0.50 base $5 as a deliberate UNDER-estimate (see note).
# Overridable from the CLI (--price-in / --price-out / --price-cache-read) so a
# skeptic can plug in Sonnet/Haiku/a negotiated rate, or a real invoice. This is
# an ILLUSTRATION over historical spend, not a billed figure — list price, and
# cache_creation is charged at 1.0× not 1.25×, so the true bill is somewhat higher.
DEFAULT_PRICE = {
    "in": 5.0,          # $/MTok — billed input (cold input + cache creation)
    "out": 25.0,        # $/MTok — output
    "cache_read": 0.50,  # $/MTok — cache hit (0.1× of base input)
}
_MTOK = 1_000_000.0


def price_tokens(tokens: dict[str, int], price: dict[str, float]) -> dict[str, float]:
    """Pure: a token vector → a dollar breakdown. No I/O, no clock.

    `tokens` is the per-session/aggregate dict with keys input, cache_creation,
    cache_read, output. Returns dollars per category plus the total and the
    `cache_miss_premium`: the EXTRA paid because billed input was reprocessed at
    the input rate instead of hitting cache at the read rate — i.e. what a warm
    cache (the docs/128 §1 5-min-TTL lever) would have saved on this very spend.
    """
    billed_in = (tokens.get("input", 0) or 0) + (tokens.get("cache_creation", 0) or 0)
    cache_read = tokens.get("cache_read", 0) or 0
    output = tokens.get("output", 0) or 0
    in_cost = billed_in / _MTOK * price["in"]
    read_cost = cache_read / _MTOK * price["cache_read"]
    out_cost = output / _MTOK * price["out"]
    # the avoidable overpay: billed_in priced at the cache-READ rate is the floor;
    # the gap to the input rate is what re-paying-cold (cache miss) cost.
    miss_premium = billed_in / _MTOK * (price["in"] - price["cache_read"])
    return {
        "input_cost": round(in_cost, 2),
        "cache_read_cost": round(read_cost, 2),
        "output_cost": round(out_cost, 2),
        "total_cost": round(in_cost + read_cost + out_cost, 2),
        "cache_miss_premium": round(miss_premium, 2),
    }


# ---------------------------------------------------------------------------
# Per-session fold — lifted near-verbatim from the reference userland app's helper.
# Session `.jsonl` files put usage under `assistant.message.usage` with `*_tokens`
# suffixes, carry `isSidechain` (subagent turns) + extra line types, and have no
# single `result` envelope. The waste-flag concepts/thresholds match the job tool.
# ---------------------------------------------------------------------------
def _default_projects_dir(workspace: Path) -> Path:
    """The Claude Code transcript dir for ``workspace``.

    Claude stores transcripts under ~/.claude/projects/<slugified-root>/. The slug
    replaces path separators and ':' with '-'. Derived from the AUDITED workspace
    (not this script's location) so a `--workspace` pointed at a foreign repo finds
    that repo's transcripts.
    """
    home = Path(os.path.expanduser("~"))
    slug = str(workspace).replace("\\", "-").replace("/", "-").replace(":", "-")
    return home / ".claude" / "projects" / slug


def _parse_since(spec: str, *, now_s: float) -> float:
    """Return an epoch-seconds floor from '3d' / '12h' / ISO date. `now_s` is the
    injected clock (never read here) so the window is reproducible."""
    spec = spec.strip()
    if spec.endswith("d") and spec[:-1].isdigit():
        return now_s - int(spec[:-1]) * 86400
    if spec.endswith("h") and spec[:-1].isdigit():
        return now_s - int(spec[:-1]) * 3600
    try:
        dt = datetime.fromisoformat(spec)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        raise SystemExit(f"--since: cannot parse {spec!r} (use Nd / Nh / ISO date)")


def _collapse(cmd: str) -> str:
    return " ".join(cmd.split())


def _poll_target(cmd: str) -> str | None:
    c = _collapse(cmd)
    for pfx in _POLL_COMMAND_PREFIXES:
        if c.startswith(pfx):
            rest = c[len(pfx):].strip()
            toks = rest.split()
            i = 0
            while i < len(toks) and toks[i].startswith("-"):
                if i + 1 < len(toks) and toks[i + 1].lstrip("-").isdigit():
                    i += 2
                else:
                    i += 1
            if i < len(toks):
                cand = toks[i].strip('"').strip("'")
                if cand in (">", ">>", "|", "&", "&&", "||", ";", "2>&1"):
                    return None
                return cand
            return None
    return None


def _is_keepalive(cmd: str) -> bool:
    c = _collapse(cmd).lower()
    return any(m in c for m in _KEEPALIVE_MARKERS)


def _tool_target(tool: str, ti: dict[str, Any]) -> str | None:
    if not isinstance(ti, dict):
        return None
    if tool in ("Read", "Edit", "Write", "NotebookEdit"):
        fp = ti.get("file_path")
        return str(fp) if fp else None
    if tool in ("Glob", "Grep"):
        return ti.get("pattern")
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command")
        return _collapse(cmd)[:80] if cmd else None
    return None


def _iso_to_epoch_ms(ts: str | None) -> Optional[int]:
    """Parse a transcript `timestamp` (ms ISO, often Z-suffixed) → epoch-ms.

    The session envelope's `timestamp` is millisecond ISO-8601 (e.g.
    `2026-06-01T14:46:03.120Z`). None on missing/unparseable input (the safe
    direction — an unplaceable session simply doesn't join).
    """
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    # `fromisoformat` handles the offset/fractional forms; normalise a trailing Z.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def audit_session(path: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Single sequential read of one session file → per-session summary."""
    tokens = {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0}
    tool_counter: Counter[str] = Counter()
    read_targets: Counter[str] = Counter()
    poll_targets: Counter[str] = Counter()
    keepalive_calls = 0
    glob_calls = 0
    assistant_turns = 0
    user_msgs = 0
    sidechain_lines = 0
    first_ts = last_ts = None
    first_user_text = ""
    version = None
    git_branch = None
    cwd = None

    try:
        lines_parsed = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    o = json.loads(raw)
                except Exception:
                    continue
                lines_parsed += 1
                if o.get("isSidechain"):
                    sidechain_lines += 1
                ts = o.get("timestamp")
                if ts:
                    first_ts = first_ts or ts
                    last_ts = ts
                version = version or o.get("version")
                git_branch = git_branch or o.get("gitBranch")
                cwd = cwd or o.get("cwd")
                t = o.get("type")
                msg = o.get("message") if isinstance(o.get("message"), dict) else {}

                if t == "assistant":
                    assistant_turns += 1
                    u = msg.get("usage") or {}
                    tokens["input"] += u.get("input_tokens", 0) or 0
                    tokens["cache_creation"] += u.get("cache_creation_input_tokens", 0) or 0
                    tokens["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
                    tokens["output"] += u.get("output_tokens", 0) or 0
                    content = msg.get("content")
                    if isinstance(content, list):
                        for b in content:
                            if not isinstance(b, dict) or b.get("type") != "tool_use":
                                continue
                            name = b.get("name", "?")
                            tool_counter[name] += 1
                            ti = b.get("input") or {}
                            if name == "Glob":
                                glob_calls += 1
                            if name == "Read":
                                tgt = _tool_target(name, ti)
                                if tgt:
                                    read_targets[tgt] += 1
                            if name in ("Bash", "PowerShell"):
                                cmd = ti.get("command", "")
                                if _is_keepalive(cmd):
                                    keepalive_calls += 1
                                pt = _poll_target(cmd)
                                if pt:
                                    poll_targets[pt] += 1
                elif t == "user":
                    user_msgs += 1
                    if not first_user_text:
                        content = msg.get("content")
                        txt = ""
                        if isinstance(content, str):
                            txt = content
                        elif isinstance(content, list):
                            txt = "\n".join(
                                c.get("text", "") for c in content
                                if isinstance(c, dict) and c.get("type") == "text"
                            )
                        s = txt.strip()
                        if s and not s.startswith("<") and "<command-name>" not in s:
                            first_user_text = s.splitlines()[0][:120]
    except OSError:
        return None

    if lines_parsed == 0:
        return None

    total_read = tokens["cache_read"] + tokens["cache_creation"] + tokens["input"]
    cache_read = tokens["cache_read"]
    billed_input = tokens["input"] + tokens["cache_creation"]
    miss_ratio = (billed_input / total_read) if total_read else 0.0

    # --- per-session waste flags ---
    flags: list[dict[str, Any]] = []
    rl_t = cfg["read_loop_threshold"]
    for tgt, cnt in read_targets.items():
        if cnt >= rl_t:
            flags.append({"name": "read_loop", "detail": f"Read {tgt} {cnt}x"})
    p_t = cfg["poll_threshold"]
    for tgt, cnt in poll_targets.items():
        if cnt >= p_t:
            flags.append({"name": "shell_poll", "detail": f"poll {tgt} {cnt}x"})
    if keepalive_calls >= cfg["keepalive_threshold"]:
        # `observed` carries the RAW marker count (an int, not just the human `detail`
        # string) so `route_findings` can hand it to `loop_decide.propose_tighter_budget`
        # WITHOUT re-parsing the prose (docs/259 §Follow-up 3, the audit→budget loop).
        flags.append({"name": "keepalive_poll",
                      "detail": f"{keepalive_calls} wait-marker calls",
                      "observed": keepalive_calls})
    if glob_calls >= cfg["glob_storm_threshold"]:
        flags.append({"name": "glob_storm", "detail": f"{glob_calls} Glob calls"})
    if assistant_turns >= cfg["min_turns"] and miss_ratio >= cfg["cache_miss_ratio"]:
        flags.append({
            "name": "cache_miss",
            "detail": f"{miss_ratio:.0%} billed-input vs cache over {assistant_turns} turns",
        })

    return {
        "session": path.stem,
        "mtime": path.stat().st_mtime,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "first_ts_ms": _iso_to_epoch_ms(first_ts),
        "last_ts_ms": _iso_to_epoch_ms(last_ts),
        "version": version,
        "git_branch": git_branch,
        "cwd": cwd,
        "first_user": first_user_text,
        "assistant_turns": assistant_turns,
        "user_msgs": user_msgs,
        "sidechain_lines": sidechain_lines,
        "tokens": tokens,
        "cache_read": cache_read,
        "tool_calls": dict(tool_counter),
        "tool_call_total": sum(tool_counter.values()),
        "top_read_targets": read_targets.most_common(3),
        "top_poll_targets": poll_targets.most_common(3),
        "keepalive_calls": keepalive_calls,
        "glob_calls": glob_calls,
        "cache_miss_ratio": round(miss_ratio, 3),
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# The DOS join layer — read the lane journal at the boundary, recover leases +
# refusals, and join sessions to leases by time-window + workspace overlap.
# ---------------------------------------------------------------------------
def _journal_is_benchmark_only(entries: list[dict]) -> bool:
    """True iff the journal looks like FleetHorizon synthetic exhaust.

    Two independent tells (either suffices): every entry has a null `loop_ts`
    (the real `fanout_state` writer always stamps one), OR every lane matches the
    benchmark `lane-NN` shape. An empty journal is NOT benchmark-only (there is
    nothing to misread). Conservative: any real-looking entry (a non-null loop_ts
    with a non-`lane-NN` lane) flips it off.
    """
    real_entries = [e for e in entries if e.get("op") != "_CORRUPT"]
    if not real_entries:
        return False
    all_null_loop_ts = all(e.get("loop_ts") in (None, "") for e in real_entries)
    all_bench_lane = all(_BENCH_LANE.match(str(e.get("lane") or "")) for e in real_entries)
    return all_null_loop_ts or all_bench_lane


def _is_refusal(entry: dict) -> bool:
    """A journal entry that records a REFUSED decision.

    Covers both the future real writer (`op==REFUSE`, the `lane_journal.OP_REFUSE`
    constant) and today's benchmark shape (`op==ACQUIRE` carrying a
    `reason:"REFUSED: ..."`). `decisions._from_lane_journal` only reads the former;
    this recovers the latter too so the contention signal is not silently zero.
    """
    from dos import lane_journal
    op = str(entry.get("op") or "")
    if op == lane_journal.OP_REFUSE:
        return True
    return op == lane_journal.OP_ACQUIRE and bool(_REFUSED_REASON.match(str(entry.get("reason") or "")))


def _lease_run_id(entry: dict) -> str | None:
    """The run_id carried by a journal entry's lease payload (None if absent).

    The run_id lives on the nested `lease` (`acquire_entry` nests the full lease);
    a forward-compat inline `run_id` is also honoured.
    """
    lease = entry.get("lease")
    if isinstance(lease, dict) and lease.get("run_id"):
        return str(lease["run_id"])
    rid = entry.get("run_id")
    return str(rid) if rid else None


def fold_journal(entries: list[dict], *, since_ms: Optional[int]) -> dict[str, Any]:
    """Reduce raw journal entries → the leases + refusals the join consumes.

    PURE over the materialized list (the caller does the `read_all`). Each entry's
    own append `ts` (parsed via the kernel's `journal_delta._parse_journal_ts` — we
    do NOT write a fourth copy of that two-format/utc parse) places it in time;
    `since_ms` drops anything older than the window before joining (the benchmark
    journal's 60K+ entries are clustered in a synthetic span, so a `--since` floor
    is the cheapest way to keep them out of a real audit).
    """
    from dos import journal_delta, run_id

    benchmark_only = _journal_is_benchmark_only(entries)
    leases: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    saw_corrupt = False
    for e in entries:
        if e.get("op") == "_CORRUPT":
            saw_corrupt = True
            continue
        ts_ms = journal_delta._parse_journal_ts(e.get("ts"))
        if ts_ms is None:
            ts_ms = journal_delta._parse_journal_ts(e.get("heartbeat_at"))
        if ts_ms is None:
            continue  # can't place it in time → drop (the safe direction)
        if since_ms is not None and ts_ms < since_ms:
            continue
        rid = _lease_run_id(e)
        rec = {
            "ts_ms": ts_ms,
            "lane": e.get("lane"),
            "run_id": rid,
            "run_started_ms": run_id.ts_ms_of(rid) if rid and run_id.is_run_id(rid) else None,
            "op": e.get("op"),
            "reason": e.get("reason") or "",
            "seq": e.get("seq"),
        }
        leases.append(rec)
        if _is_refusal(e):
            refusals.append(rec)
    return {
        "benchmark_only": benchmark_only,
        "saw_corrupt": saw_corrupt,
        "total_entries": len(entries),
        "leases": leases,
        "refusals": refusals,
    }


def join_sessions_to_leases(
    sessions: list[dict[str, Any]],
    journal: dict[str, Any],
    *,
    slack_ms: int,
) -> dict[str, Any]:
    """Join sessions to journal leases by **time-window overlap** — honestly.

    There is no shared key (a transcript has no run_id; a lease has no sessionId),
    so a session [first_ts_ms, last_ts_ms] window is matched against a lease's `ts`
    instant widened by `slack_ms` (the same 1s future-skew slack `journal_delta`
    uses, applied symmetrically; failing toward "no match" is the safe direction).
    A lease whose `ts` falls inside a session's slack-widened window is a candidate.

    Ambiguity is REPORTED, never guessed:
      * exactly one session ↔ exactly one lease  → a `(session, run_id, lane)` triple.
      * a session matched by >1 lane, OR a lease matched by >1 session → an
        `ambiguous` row listing every candidate (so the operator sees the smear,
        rather than a fabricated attribution).
    Sessions with no overlapping lease and leases with no overlapping session are
    carried separately (trajectory-only / journal-only).
    """
    leases = journal["leases"]

    # candidate edges: session_idx -> set(lease_idx) and the reverse
    sess_to_leases: dict[int, list[int]] = defaultdict(list)
    lease_to_sessions: dict[int, list[int]] = defaultdict(list)
    for si, s in enumerate(sessions):
        lo, hi = s.get("first_ts_ms"), s.get("last_ts_ms")
        if lo is None or hi is None:
            continue
        lo -= slack_ms
        hi += slack_ms
        for li, lease in enumerate(leases):
            t = lease["ts_ms"]
            if lo <= t <= hi:
                sess_to_leases[si].append(li)
                lease_to_sessions[li].append(si)

    triples: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    matched_sessions: set[int] = set()
    matched_leases: set[int] = set()

    for si, lis in sess_to_leases.items():
        # distinct lanes this session overlapped
        lanes = {leases[li]["lane"] for li in lis}
        # is every overlapping lease's lane uniquely this session's? (1:1 means a
        # single lane AND that lane's lease(s) overlap no OTHER session)
        contended = any(len(set(lease_to_sessions[li])) > 1 for li in lis)
        if len(lanes) == 1 and not contended:
            lane = next(iter(lanes))
            rids = sorted({leases[li]["run_id"] for li in lis if leases[li]["run_id"]})
            n_ref = sum(1 for li in lis if _rec_is_refusal(leases[li]))
            triples.append({
                "session": sessions[si]["session"],
                "run_id": rids[0] if len(rids) == 1 else (rids or None),
                "lane": lane,
                "flags": sorted({f["name"] for f in sessions[si]["flags"]}),
                "lease_events": len(lis),
                "refusal_events": n_ref,
                "first_user": sessions[si]["first_user"],
            })
            matched_sessions.add(si)
            matched_leases.update(lis)
        else:
            ambiguous.append({
                "session": sessions[si]["session"],
                "window": [sessions[si]["first_ts"], sessions[si]["last_ts"]],
                "candidate_lanes": sorted(str(x) for x in lanes),
                "candidate_run_ids": sorted({leases[li]["run_id"] for li in lis if leases[li]["run_id"]}),
                "lease_events": len(lis),
                "note": (
                    f"{len(lanes)} lane(s) overlap this session's window"
                    + ("; lane shared with another session" if contended else "")
                    + " — not attributed"
                ),
            })
            matched_sessions.add(si)
            matched_leases.update(lis)

    trajectory_only = [
        {
            "session": s["session"],
            "flags": sorted({f["name"] for f in s["flags"]}),
            "cache_read": s["cache_read"],
            "first_user": s["first_user"],
        }
        for si, s in enumerate(sessions) if si not in matched_sessions
    ]
    journal_only_count = sum(1 for li in range(len(leases)) if li not in matched_leases)

    return {
        "triples": triples,
        "ambiguous": ambiguous,
        "trajectory_only": trajectory_only,
        "journal_only_lease_count": journal_only_count,
    }


def _rec_is_refusal(rec: dict) -> bool:
    """A folded lease record (from `fold_journal`) that is a refusal."""
    from dos import lane_journal
    op = str(rec.get("op") or "")
    if op == lane_journal.OP_REFUSE:
        return True
    return op == lane_journal.OP_ACQUIRE and bool(_REFUSED_REASON.match(str(rec.get("reason") or "")))


def contention_vs_waste(sessions: list[dict[str, Any]], join: dict[str, Any]) -> list[dict[str, Any]]:
    """The headline cross-signal: a session with >=1 waste-flag whose joined lane
    saw a refusal in the same window — the agent burned tokens / polled WHILE the
    kernel was refusing its lane (lease contention vs trajectory waste). Computed
    only over confidently-attributed triples (never over an `AMBIGUOUS_JOIN`)."""
    by_session = {s["session"]: s for s in sessions}
    out = []
    for tr in join["triples"]:
        if tr["refusal_events"] <= 0:
            continue
        s = by_session.get(tr["session"]) or {}
        wf = sorted({f["name"] for f in s.get("flags", [])})
        if not wf:
            continue
        out.append({
            "session": tr["session"],
            "run_id": tr["run_id"],
            "lane": tr["lane"],
            "waste_flags": wf,
            "refusal_events": tr["refusal_events"],
        })
    return out


# ---------------------------------------------------------------------------
# Liveness column (opt-in, commit-driven). Offline replay of the pure
# `liveness.classify` — no live process, the clock injected. Driven by the
# UNAMBIGUOUS git-commit rung (a real commit can't be faked), never the
# journal-event rung (which the benchmark journal would poison).
# ---------------------------------------------------------------------------
def liveness_column(
    sessions: list[dict[str, Any]],
    *,
    start_sha: str,
    workspace: Path,
    now_ms: int,
) -> list[dict[str, Any]]:
    from dos import git_delta, liveness

    commits = git_delta.count_commits_since(start_sha, root=workspace)
    out = []
    for s in sessions:
        started = s.get("first_ts_ms")
        if started is None:
            continue
        ev = liveness.ProgressEvidence(
            run_started_ms=started,
            now_ms=s.get("last_ts_ms") or now_ms,
            commits_since_start=commits,        # workspace-wide delta since the baseline
            journal_events_since=0,             # commit rung only (journal not REFUSE-aware yet)
            last_heartbeat_age_ms=None,
        )
        v = liveness.classify(ev)
        out.append({
            "session": s["session"],
            "verdict": v.verdict.value,
            "reason": v.reason,
        })
    return out


# ---------------------------------------------------------------------------
# Rollup + render (the trajectory half — lifted from job, unchanged shape).
# ---------------------------------------------------------------------------
def rollup(sessions: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    flag_sessions: dict[str, list[str]] = defaultdict(list)
    flag_detail: dict[str, list[str]] = defaultdict(list)
    flag_observed: dict[str, int] = defaultdict(int)  # max raw count per flag (e.g. keepalive markers)
    repeat_read: Counter[str] = Counter()
    total_cache_read = 0
    total_output = 0
    agg_tokens = {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0}
    tool_totals: Counter[str] = Counter()

    for s in sessions:
        total_cache_read += s["cache_read"]
        total_output += s["tokens"]["output"]
        for k in agg_tokens:
            agg_tokens[k] += s["tokens"].get(k, 0) or 0
        for k, v in s["tool_calls"].items():
            tool_totals[k] += v
        for f in s["flags"]:
            flag_sessions[f["name"]].append(s["session"])
            flag_detail[f["name"]].append(f"{s['session'][:8]}: {f['detail']}")
            # Carry the MAX raw `observed` count (when a flag has one) so a numeric
            # finding survives the rollup — the `keepalive_poll` proposal needs the int,
            # not the prose (docs/259 §Follow-up 3, R5: the count is otherwise lost here).
            if "observed" in f:
                flag_observed[f["name"]] = max(flag_observed[f["name"]], int(f["observed"]))
        for tgt, cnt in s["top_read_targets"]:
            if cnt >= cfg["read_loop_threshold"]:
                repeat_read[tgt] += cnt

    findings = []
    for name, sess in sorted(flag_sessions.items(), key=lambda kv: -len(kv[1])):
        n = len(set(sess))
        severity = "HIGH" if n >= 3 else ("MED" if n >= 2 else "LOW")
        finding = {
            "flag": name,
            "sessions_affected": n,
            "severity": severity,
            "examples": flag_detail[name][:5],
        }
        # Attach the raw observed count for flags that carry one (keepalive_poll), so
        # the audit→budget proposal (docs/259 §Follow-up 3) has the int it needs.
        if name in flag_observed:
            finding["observed"] = flag_observed[name]
        findings.append(finding)

    price = cfg.get("price", DEFAULT_PRICE)
    spend = price_tokens(agg_tokens, price)
    # rank heaviest by PRICED total, not raw cache-read — dollars are the point now.
    heaviest = sorted(sessions, key=lambda s: -price_tokens(s["tokens"], price)["total_cost"])[:5]

    return {
        "window_sessions": len(sessions),
        "total_cache_read_tokens": total_cache_read,
        "total_output_tokens": total_output,
        "tokens": agg_tokens,
        "spend": spend,
        "price": price,
        "tool_totals": dict(tool_totals.most_common(12)),
        "systemic_findings": findings,
        "repeat_read_files": repeat_read.most_common(8),
        "heaviest_sessions": [
            {
                "session": s["session"][:8],
                "cache_read": s["cache_read"],
                "cost": price_tokens(s["tokens"], price)["total_cost"],
                "turns": s["assistant_turns"],
                "flags": sorted({f["name"] for f in s["flags"]}),
                "first_user": s["first_user"],
            }
            for s in heaviest
        ],
    }


def render_md(roll: dict[str, Any], dos: dict[str, Any], cfg: dict[str, Any], *, stamp: str) -> str:
    L = []
    L.append(f"# Trajectory audit — {stamp}")
    L.append("")
    L.append(f"Swept **{roll['window_sessions']}** recent session trajectories, "
             f"joined to the DOS lane journal.")
    L.append("")
    cr = roll["total_cache_read_tokens"]
    L.append(f"- Total cache-read tokens (window): **{cr:,}**")
    L.append(f"- Total output tokens (window): **{roll['total_output_tokens']:,}**")
    L.append("")

    # --- token spend, priced (docs/130 Prong C — the $0 observe tier) ---
    sp = roll.get("spend")
    pr = roll.get("price", DEFAULT_PRICE)
    if sp:
        L.append("## Token spend (priced)")
        L.append("")
        L.append(f"> List-price ILLUSTRATION over historical spend, not a billed "
                 f"figure. Rate: ${pr['in']:.0f}/${pr['out']:.0f}/MTok in/out, "
                 f"${pr['cache_read']:.2f}/MTok cache-read "
                 f"(default = Claude Opus 4.8 list, docs/128 §1; override with "
                 f"`--price-in/--price-out/--price-cache-read`). cache_creation is "
                 f"charged at the input rate (1.0×, not the 1.25× write rate), so "
                 f"the true bill is somewhat higher.")
        L.append("")
        L.append(f"- **Total window spend: ~${sp['total_cost']:,.2f}** "
                 f"(input ${sp['input_cost']:,.2f} + output ${sp['output_cost']:,.2f} "
                 f"+ cache-read ${sp['cache_read_cost']:,.2f})")
        L.append(f"- **Cache-miss premium: ~${sp['cache_miss_premium']:,.2f}** — the "
                 f"avoidable overpay from re-paying billed input cold instead of "
                 f"hitting cache (the docs/128 §1 5-min-TTL lever, priced on this "
                 f"window's own spend).")
        L.append("")

    # --- the DOS cross-signal headline, first (it's the point of this tool) ---
    j = dos["journal"]
    L.append("## DOS cross-signal — contention vs waste")
    L.append("")
    if j["benchmark_only"]:
        L.append("> ⚠️ **The lane journal is benchmark-only exhaust** (all-`ACQUIRE`, "
                 "null `loop_ts` / `lane-NN` lanes — FleetHorizon synthetic data). "
                 "The join below is over synthetic leases; treat it as a shape demo, "
                 "not real fleet evidence. Run a real dispatch loop to populate it.")
        L.append("")
    cw = dos["contention_vs_waste"]
    if not cw:
        L.append("_No session showed a waste-flag while its joined lane was being "
                 "refused. (SPINNING/SCAVENGED are not surfaced — the DOS dispatch "
                 "path emits no HEARTBEAT/SCAVENGE journal ops yet.)_")
    else:
        L.append("| Session | Run-id | Lane | Waste flags | Refusals in window |")
        L.append("|---|---|---|---|---|")
        for c in cw:
            rid = (c["run_id"] or "—")
            rid = rid if isinstance(rid, str) else ",".join(rid)
            L.append(f"| `{c['session'][:8]}` | `{rid}` | {c['lane']} | "
                     f"{','.join(c['waste_flags'])} | {c['refusal_events']} |")
    L.append("")

    jn = dos["join"]
    L.append(f"- Confident `(session, run_id, lane)` triples: **{len(jn['triples'])}**")
    L.append(f"- `AMBIGUOUS_JOIN` rows (overlap not 1:1, not attributed): "
             f"**{len(jn['ambiguous'])}**")
    L.append(f"- Trajectory-only sessions (no overlapping lease): "
             f"**{len(jn['trajectory_only'])}**")
    L.append(f"- Journal-only leases (no overlapping session): "
             f"**{jn['journal_only_lease_count']}**")
    L.append(f"- Refusals recovered from journal: **{len(j['refusals'])}** "
             f"(of {j['total_entries']} entries)")
    L.append("")
    if jn["ambiguous"]:
        L.append("### Ambiguous joins (reported, not guessed)")
        L.append("")
        for a in jn["ambiguous"][:8]:
            lanes = ", ".join(a["candidate_lanes"]) or "—"
            L.append(f"- `{a['session'][:8]}` — {a['note']} (lanes: {lanes})")
        L.append("")

    if dos.get("liveness"):
        L.append("## Liveness (commit-rung, offline replay)")
        L.append("")
        L.append("| Session | Verdict | Reason |")
        L.append("|---|---|---|")
        for lv in dos["liveness"][:12]:
            L.append(f"| `{lv['session'][:8]}` | {lv['verdict']} | {lv['reason']} |")
        L.append("")

    # --- the trajectory half (job-shaped) ---
    L.append("## Systemic findings (cross-session)")
    L.append("")
    if not roll["systemic_findings"]:
        L.append("_No flagged pathologies in the window._")
    else:
        L.append("| Severity | Flag | Sessions | Example |")
        L.append("|---|---|---|---|")
        for f in roll["systemic_findings"]:
            ex = f["examples"][0] if f["examples"] else ""
            L.append(f"| {f['severity']} | `{f['flag']}` | {f['sessions_affected']} | {ex} |")
    L.append("")
    if roll["repeat_read_files"]:
        L.append("## Files re-read within a session (≥ threshold)")
        L.append("")
        for tgt, cnt in roll["repeat_read_files"]:
            L.append(f"- `{tgt}` — {cnt} reads")
        L.append("")
    L.append("## Heaviest sessions by spend")
    L.append("")
    L.append("| Session | ~$ | Cache-read | Turns | Flags | First message |")
    L.append("|---|---|---|---|---|---|")
    for s in roll["heaviest_sessions"]:
        fl = ",".join(s["flags"]) or "—"
        fu = (s["first_user"] or "").replace("|", "\\|")[:60]
        cost = s.get("cost", 0.0)
        L.append(f"| `{s['session']}` | ${cost:,.2f} | {s['cache_read']:,} | "
                 f"{s['turns']} | {fl} | {fu} |")
    L.append("")
    L.append("## Tool-call totals (window)")
    L.append("")
    for k, v in roll["tool_totals"].items():
        L.append(f"- {k}: {v}")
    L.append("")
    L.append("---")
    L.append(
        "_Thresholds: read-loop≥{rl}, poll≥{p}, keepalive≥{k}, glob-storm≥{g}, "
        "cache-miss≥{cm:.0%} over ≥{mt} turns. Join: time-window overlap "
        "(±{slack}ms slack); SPINNING/SCAVENGED suppressed (no emitter)._".format(
            rl=cfg["read_loop_threshold"], p=cfg["poll_threshold"],
            k=cfg["keepalive_threshold"], g=cfg["glob_storm_threshold"],
            cm=cfg["cache_miss_ratio"], mt=cfg["min_turns"], slack=cfg["slack_ms"],
        )
    )
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Findings routing (opt-in) — the DOS-native sink, not job's markdown queue.
# ---------------------------------------------------------------------------
def route_findings(cfg_obj, roll: dict[str, Any], dos: dict[str, Any],
                   current_max_markers: int = 4) -> int:
    """Append each systemic finding to `~/.dos/decisions.jsonl` via the kernel's
    `home.append_decision` (idempotent — deduped by identity, so re-running is
    safe). Returns the number of NEW rows written. This is the only persisting
    write the tool makes and is OFF by default (the read-only / `dos verify`
    discipline). Findings then surface via `dos decisions` / `dos learn`.

    For a `keepalive_poll` finding, the row ALSO carries a `proposed_max_markers` —
    the audit→budget loop closing (docs/259 §Follow-up 3): the post-hoc detector
    proposes a tighter pre-hoc `wait_marker_budget` cap (via the PURE
    `loop_decide.propose_tighter_budget`). It stays ADVISORY — `resolver_kind:"HUMAN"`,
    a proposal a human/host applies, NEVER auto-fed back into the live budget.

    Dedup caveat (R6): `home.append_decision` keys identity on
    (project, lane, reason_token, run_ts, action) — NOT on `resolution`. A
    `keepalive_poll` finding has empty lane/run_ts, so its identity is constant across
    audit runs and the FIRST routed proposal sticks until the local mirror is cleared;
    a later run proposing a different number is silently deduped. Acceptable for an
    idempotent advisory surface (the row's `observed_markers` carries the live alarm)."""
    from dos import home
    from dos import loop_decide
    written = 0
    # The trajectory systemic findings.
    for f in roll["systemic_findings"]:
        resolution: dict[str, Any] = {
            "severity": f["severity"],
            "sessions_affected": f["sessions_affected"],
            "examples": f["examples"][:3],
        }
        # The audit→budget loop (docs/259 §Follow-up 3): a keepalive_poll finding
        # proposes a tighter wait-marker budget off the observed burst.
        if f["flag"] == "keepalive_poll" and "observed" in f:
            observed = int(f["observed"])
            resolution["observed_markers"] = observed
            resolution["current_max_markers"] = current_max_markers
            resolution["proposed_max_markers"] = loop_decide.propose_tighter_budget(
                observed, current_max=current_max_markers)
            # When the burst EXCEEDED the current cap, the cap was not enforced (the hook
            # was unwired/bypassed) — the proposal won't tighten (the monotone-down
            # clamp); flag that the real fix is to WIRE the hook, not lower the number.
            if observed > current_max_markers:
                resolution["lever_not_wired"] = True
        row = {
            "kind": "TRAJECTORY_AUDIT",
            "resolver_kind": "HUMAN",
            "lane": "",
            "reason_token": f["flag"],
            "reason_category": "efficiency",
            "run_ts": "",
            "resolution": resolution,
        }
        if home.append_decision(cfg_obj, row) is not None:
            written += 1
    # The DOS cross-signal findings (the headline) — one per contention-vs-waste hit.
    for c in dos["contention_vs_waste"]:
        rid = c["run_id"] if isinstance(c["run_id"], str) else (c["run_id"] or [None])[0]
        row = {
            "kind": "TRAJECTORY_AUDIT",
            "resolver_kind": "HUMAN",
            "lane": c["lane"] or "",
            "reason_token": "contention_vs_waste",
            "reason_category": "efficiency",
            "run_ts": rid or "",
            "resolution": {
                "session": c["session"],
                "waste_flags": c["waste_flags"],
                "refusal_events": c["refusal_events"],
            },
        }
        if home.append_decision(cfg_obj, row) is not None:
            written += 1
    return written


def _resolve_out_path(out: str, cfg_obj, fmt: str, stamp: str) -> Path:
    """A bare `--out` name (no separator) lands under `.dos/audits/`; an explicit
    path is honoured as-is. Mirrors how DOS emissions live under `.dos/`."""
    p = Path(out)
    if p.parent == Path(".") and "/" not in out and "\\" not in out:
        return cfg_obj.paths.dot_dos / "audits" / out
    if out in ("", "."):
        ext = "json" if fmt == "json" else "md"
        return cfg_obj.paths.dot_dos / "audits" / f"trajectory-audit-{stamp}.{ext}"
    return p


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252 and choke on the ≥/% glyphs in the report.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace")
    ap.add_argument("--projects-dir")
    ap.add_argument("--last", type=int, default=30)
    ap.add_argument("--since")
    ap.add_argument("--start-sha")
    ap.add_argument("--format", choices=("json", "md"), default="md")
    ap.add_argument("--out")
    ap.add_argument("--stamp", default="report")
    ap.add_argument("--now-ms", type=int)
    ap.add_argument("--route-findings", action="store_true")
    ap.add_argument("--read-loop-threshold", type=int, default=4)
    ap.add_argument("--poll-threshold", type=int, default=3)
    ap.add_argument("--keepalive-threshold", type=int, default=5)
    ap.add_argument("--current-max-markers", type=int, default=4,
                    help="the wait-marker budget currently in force (default 4 = "
                         "wait_marker_budget's default); a routed keepalive_poll finding "
                         "proposes a tighter cap relative to THIS (docs/259 §Follow-up 3)")
    ap.add_argument("--glob-storm-threshold", type=int, default=10)
    ap.add_argument("--cache-miss-ratio", type=float, default=0.30)
    ap.add_argument("--min-turns", type=int, default=5)
    ap.add_argument("--slack-ms", type=int, default=1000)
    ap.add_argument("--price-in", type=float, default=DEFAULT_PRICE["in"],
                    help="$/MTok billed input (default Opus 4.8 list = 5.0)")
    ap.add_argument("--price-out", type=float, default=DEFAULT_PRICE["out"],
                    help="$/MTok output (default Opus 4.8 list = 25.0)")
    ap.add_argument("--price-cache-read", type=float, default=DEFAULT_PRICE["cache_read"],
                    help="$/MTok cache hit (default Opus 4.8 list = 0.50)")
    args = ap.parse_args(argv)

    import time
    from dos import config as _config

    now_ms = args.now_ms if args.now_ms is not None else int(time.time() * 1000)
    now_s = now_ms / 1000.0

    cfg_obj = _config.load_workspace_config(args.workspace)
    workspace = cfg_obj.paths.root

    cfg = {
        "read_loop_threshold": args.read_loop_threshold,
        "poll_threshold": args.poll_threshold,
        "keepalive_threshold": args.keepalive_threshold,
        "glob_storm_threshold": args.glob_storm_threshold,
        "cache_miss_ratio": args.cache_miss_ratio,
        "min_turns": args.min_turns,
        "slack_ms": args.slack_ms,
        "price": {
            "in": args.price_in,
            "out": args.price_out,
            "cache_read": args.price_cache_read,
        },
    }

    pdir = Path(args.projects_dir) if args.projects_dir else _default_projects_dir(workspace)
    if not pdir.is_dir():
        print(f"projects dir not found: {pdir}", file=sys.stderr)
        return 2
    files = sorted(pdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print(f"no .jsonl session files in {pdir}", file=sys.stderr)
        return 2

    since_floor_s: Optional[float] = None
    if args.since:
        since_floor_s = _parse_since(args.since, now_s=now_s)
        files = [p for p in files if p.stat().st_mtime >= since_floor_s]
    else:
        files = files[: args.last]

    sessions = []
    for p in files:
        s = audit_session(p, cfg)
        if s:
            sessions.append(s)
    if not sessions:
        print("no readable sessions in window", file=sys.stderr)
        return 2

    # --- the DOS join (read the journal at the boundary, fold + join purely) ---
    from dos import lane_journal
    try:
        entries = lane_journal.read_all(path=cfg_obj.paths.lane_journal)
    except Exception:  # noqa: BLE001 — a bad journal must not crash the audit
        entries = []
    since_ms = int(since_floor_s * 1000) if since_floor_s is not None else None
    journal = fold_journal(entries, since_ms=since_ms)
    join = join_sessions_to_leases(sessions, journal, slack_ms=args.slack_ms)
    dos = {
        "journal": {k: journal[k] for k in ("benchmark_only", "saw_corrupt", "total_entries")}
        | {"refusals": journal["refusals"]},
        "join": join,
        "contention_vs_waste": contention_vs_waste(sessions, join),
    }
    if args.start_sha:
        dos["liveness"] = liveness_column(
            sessions, start_sha=args.start_sha, workspace=workspace, now_ms=now_ms)

    roll = rollup(sessions, cfg)

    # --- opt-in findings routing (the only persisting write) ---
    routed = 0
    if args.route_findings:
        routed = route_findings(cfg_obj, roll, dos,
                                current_max_markers=args.current_max_markers)

    out_text = (
        json.dumps({
            "config": cfg, "workspace": str(workspace), "stamp": args.stamp,
            "rollup": roll, "dos": dos, "sessions": sessions,
            "routed_findings": routed,
        }, indent=2, default=str)
        if args.format == "json"
        else render_md(roll, dos, cfg, stamp=args.stamp)
    )

    if args.out:
        target = _resolve_out_path(args.out, cfg_obj, args.format, args.stamp)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(out_text, encoding="utf-8")
        print(f"wrote {target} ({len(sessions)} sessions"
              + (f", {routed} finding(s) routed" if args.route_findings else "") + ")")
    else:
        print(out_text)
        if args.route_findings:
            print(f"# {routed} finding(s) routed to ~/.dos/decisions.jsonl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
