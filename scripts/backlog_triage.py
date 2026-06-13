#!/usr/bin/env python3
"""Backlog triage — the deterministic floor under "work the backlog" (docs/315).

Dev tooling that operates ON the repo. It names a vendor (`gh`/GitHub), so it
lives here, never under `src/dos/` — the same placement argument the
issue-work skill makes for itself. It imports `dos` (the allowed direction:
tooling consumes the package; the package is unaware of it).

The shape mirrors the kernel's own discipline: a PURE classify/order core
over plain dicts, with every read — the `gh` call, the lane-journal attempt
history, the SELF_MODIFY surface set, the plan index — gathered at the
boundary in `main()` and handed in as data.

What it answers: "of every open issue, which can a worker ACTUALLY take
right now, in what order, and why is the rest held?" Each issue folds into
exactly one disposition from a closed set:

  READY           offerable now (code/docs work)
  NEEDS_PLAN      `design`-labeled with no plan doc yet — offerable as
                  PLAN-WRITING work (the next unit of work for a design
                  issue is the `docs/NN` plan itself)
  COOLING         recently attempted and didn't move — the `dos.cooldown`
                  fold holds it until the window wall
  T1_GATED        the issue text names a guarded kernel runtime file: the
                  PreToolUse hook will deny the edit, so the fix is the
                  operator's (the ENFORCE_BREAKER storm, prevented at
                  triage time instead of recorded at edit time)
  OPERATOR_GATED  `human-only` label — operator judgment, the fleet skips it

The offerable rows are ordered deterministically, lower-wins:

  (priority tier, ready-label bias, freshness sort_key, issue number)

Priority labels first (high < medium < unlabeled < low); the kernel's
`pick_priority` freshness fold breaks ties WITHIN a tier (never-attempted
first, then least-recently-tried); the issue number is the FIFO tie-break so
old work cannot starve. The floor is ADVISORY (docs/99): it types and
orders; an agent may deviate from the top pick with one stated sentence.

Detection is UNDER-MATCHING by construction: T1_GATED fires only when the
issue text literally names a guarded runtime path. A missed gate degrades to
today's behavior (the edit-time hook deny) — never worse.

The unit-id convention is `issue-N`. `--record-attempt N --outcome X`
appends the standard `lane_journal.attempt_entry`, so the existing kernel
folds — `dos cooldown issue-N`, `dos pick-priority issue-N` — answer
truthfully with no new mechanism.

The verdict IS the exit code (the house idiom):
  0  WORK_AVAILABLE   at least one offerable row
  3  ALL_GATED        open issues exist, but every one is held
  4  EMPTY            no open issues
  2  contract error   bad input / a failed gather
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# The closed disposition set + exit codes.
# ---------------------------------------------------------------------------

READY = "READY"
NEEDS_PLAN = "NEEDS_PLAN"
COOLING = "COOLING"
T1_GATED = "T1_GATED"
OPERATOR_GATED = "OPERATOR_GATED"

OFFERABLE = (READY, NEEDS_PLAN)
HELD = (COOLING, T1_GATED, OPERATOR_GATED)

EXIT_WORK_AVAILABLE = 0
EXIT_CONTRACT_ERROR = 2
EXIT_ALL_GATED = 3
EXIT_EMPTY = 4

# The recorded-outcome vocabulary `dos.cooldown.AttemptOutcome` folds.
OUTCOMES = ("shipped", "drained", "blocked", "error")

_PRIORITY_TIERS = {"priority:high": 0, "priority:medium": 1, "priority:low": 3}
_UNLABELED_TIER = 2

_UNIT_PREFIX = "issue-"


# ---------------------------------------------------------------------------
# Pure core — classify, order, fold. No I/O anywhere below this line until
# the "boundary" section.
# ---------------------------------------------------------------------------


def normalize_issue(raw: dict) -> dict:
    """Flatten a `gh issue list --json` row to the plain shape the core reads."""
    labels = raw.get("labels") or []
    names = sorted(
        {(l.get("name") if isinstance(l, dict) else str(l)) or "" for l in labels} - {""}
    )
    return {
        "number": int(raw["number"]),
        "title": str(raw.get("title") or ""),
        "labels": names,
        "body": str(raw.get("body") or ""),
        "updated_at": str(raw.get("updatedAt") or raw.get("updated_at") or ""),
    }


def priority_tier(labels) -> int:
    """Lower wins. high=0 / medium=1 / unlabeled=2 / low=3 (an unlabeled issue
    outranks an explicit `priority:low` — silence is not a deferral)."""
    tiers = [_PRIORITY_TIERS[l] for l in labels if l in _PRIORITY_TIERS]
    return min(tiers) if tiers else _UNLABELED_TIER


def names_guarded_surface(text: str, surfaces) -> str:
    """The first guarded runtime path `text` literally names, else "".

    UNDER-MATCHING on purpose: a literal relative-path substring match (with
    `\\` normalized to `/`), never a basename or fuzzy match — the
    conservative direction. An empty surface set matches nothing.
    """
    t = (text or "").replace("\\", "/")
    for s in surfaces or ():
        if s and s in t:
            return s
    return ""


def classify_issue(
    issue: dict,
    *,
    t1_surfaces=(),
    planned_numbers=frozenset(),
    cooling=None,
) -> dict:
    """Fold one issue into its disposition row. PURE.

    Precedence (first hold wins): human-only → T1 surface → cooldown →
    the design/plan split → READY. `cooling` is a `{number: {until_ms,
    reason}}` map the boundary derived from the kernel's cooldown fold.
    """
    number = issue["number"]
    labels = issue["labels"]
    row = {
        "number": number,
        "title": issue["title"],
        "labels": labels,
        "priority_tier": priority_tier(labels),
        "disposition": READY,
        "work_kind": "code",
        "reason": "",
    }
    if "human-only" in labels:
        row["disposition"] = OPERATOR_GATED
        row["work_kind"] = "operator"
        row["reason"] = "labeled human-only — operator judgment, the fleet skips it"
        return row
    hit = names_guarded_surface(issue["title"] + "\n" + issue["body"], t1_surfaces)
    if hit:
        row["disposition"] = T1_GATED
        row["work_kind"] = "operator"
        row["reason"] = (
            f"fix surface names guarded runtime file {hit} — the hook will deny a "
            "live loop; the edit needs the operator (between loop runs or the "
            "override window)"
        )
        return row
    cool = (cooling or {}).get(number)
    if cool:
        row["disposition"] = COOLING
        row["work_kind"] = "wait"
        row["reason"] = str(cool.get("reason") or "recently attempted; in the cooldown window")
        row["until_ms"] = int(cool.get("until_ms") or 0)
        return row
    if "design" in labels:
        if number in planned_numbers:
            row["work_kind"] = "execute-plan"
            row["reason"] = "design issue with a plan doc — the plan's phases are the work"
        else:
            row["disposition"] = NEEDS_PLAN
            row["work_kind"] = "write-plan"
            row["reason"] = "design issue with no docs/NN plan yet — writing the plan IS the next unit of work"
        return row
    row["reason"] = "no hold — offerable"
    return row


def freshness_key(number: int, latest_attempt_ms: dict) -> tuple:
    """The kernel `pick_priority` sort_key for `issue-N`, from a
    `{number: last_attempt_ms}` map the boundary folded out of the journal."""
    from dos import pick_priority as _pp

    ms = latest_attempt_ms.get(number)
    summary = None if ms is None else _pp.AttemptSummary(attempted=True, last_attempt_ms=ms)
    return _pp.classify(f"{_UNIT_PREFIX}{number}", summary).sort_key


def order_queue(rows, latest_attempt_ms: dict) -> list:
    """Order the OFFERABLE rows. Lower-wins on
    (priority tier, ready bias, freshness sort_key, number)."""

    def key(r):
        return (
            r["priority_tier"],
            0 if "ready" in r["labels"] else 1,
            freshness_key(r["number"], latest_attempt_ms),
            r["number"],
        )

    return sorted((r for r in rows if r["disposition"] in OFFERABLE), key=key)


def latest_attempts(attempt_records) -> dict:
    """Fold OP_ATTEMPT records into `{issue_number: newest attempted_at_ms}`.
    Non-issue units and unreadable stamps are skipped (fail-open)."""
    latest: dict = {}
    for rec in attempt_records or ():
        uid = str(rec.get("unit_id") or "")
        if not uid.startswith(_UNIT_PREFIX):
            continue
        try:
            n = int(uid[len(_UNIT_PREFIX):])
            ms = int(rec.get("attempted_at_ms") or 0)
        except (TypeError, ValueError):
            continue
        latest[n] = max(latest.get(n, 0), ms)
    return latest


def queue_exit_code(rows) -> int:
    if not rows:
        return EXIT_EMPTY
    if any(r["disposition"] in OFFERABLE for r in rows):
        return EXIT_WORK_AVAILABLE
    return EXIT_ALL_GATED


def triage(issues, *, t1_surfaces=(), planned_numbers=frozenset(), cooling=None,
           attempt_records=()) -> dict:
    """The full pure fold: issues + gathered facts → rows, ordered queue, counts."""
    rows = [
        classify_issue(
            i,
            t1_surfaces=t1_surfaces,
            planned_numbers=planned_numbers,
            cooling=cooling,
        )
        for i in issues
    ]
    latest = latest_attempts(attempt_records)
    queue = order_queue(rows, latest)
    counts: dict = {}
    for r in rows:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1
    return {
        "rows": rows,
        "queue": queue,
        "counts": counts,
        "exit_code": queue_exit_code(rows),
    }


def render(result: dict, *, top: int = 0) -> str:
    """The operator-facing table. The queue is the headline; holds are grouped."""
    rows, queue, counts = result["rows"], result["queue"], result["counts"]
    out = []
    offer = sum(counts.get(d, 0) for d in OFFERABLE)
    held = sum(counts.get(d, 0) for d in HELD)
    out.append(f"BACKLOG TRIAGE — {len(rows)} open issues: {offer} offerable, {held} held")
    parts = [f"{d} {counts[d]}" for d in (READY, NEEDS_PLAN, COOLING, T1_GATED, OPERATOR_GATED) if counts.get(d)]
    out.append("  " + " · ".join(parts) if parts else "  (empty backlog)")
    out.append("")
    if queue:
        pick = queue[0]
        out.append(f"NEXT PICK → #{pick['number']} ({pick['work_kind']}) {pick['title']}")
        out.append(f"  why: {_why(pick)}")
        out.append("")
        out.append("QUEUE (offerable, in order — deviate only with a stated reason)")
        shown = queue[:top] if top else queue
        for i, r in enumerate(shown, 1):
            lbl = ",".join(r["labels"]) or "-"
            out.append(f"  {i:>2}. #{r['number']:<4} [{lbl}] ({r['work_kind']}) {r['title']}")
        if top and len(queue) > top:
            out.append(f"  … {len(queue) - top} more (run without --top to see all)")
    else:
        out.append("QUEUE — empty (no offerable issue right now)")
    held_rows = [r for r in rows if r["disposition"] in HELD]
    if held_rows:
        out.append("")
        out.append("HELD")
        for r in sorted(held_rows, key=lambda r: (r["disposition"], r["number"])):
            out.append(f"  {r['disposition']:<14} #{r['number']:<4} {r['title']}")
            out.append(f"  {'':<14} └ {r['reason']}")
    return "\n".join(out)


def _why(row: dict) -> str:
    tier_names = {0: "priority:high", 1: "priority:medium", 2: "no priority label", 3: "priority:low"}
    bits = [tier_names[row["priority_tier"]]]
    if "ready" in row["labels"]:
        bits.append("ready (done-condition declared)")
    bits.append(row["reason"] or row["work_kind"])
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Boundary — every read lives here, gathered once, handed to the pure core.
# ---------------------------------------------------------------------------


def gather_issues(limit: int = 200) -> list:
    """`gh issue list` → normalized rows. Raises on a failed call (the caller
    maps it to the contract-error exit)."""
    proc = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--limit", str(limit),
         "--json", "number,title,labels,body,updatedAt"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {(proc.stderr or '').strip()}")
    return [normalize_issue(r) for r in json.loads(proc.stdout or "[]")]


def gather_t1_surfaces():
    """The guarded runtime-file set, from the kernel itself. Fail-open to ()
    with a warning — under-matching is the documented degrade direction."""
    try:
        from dos.self_modify import _DISPATCH_RUNTIME_FILES
        return tuple(_DISPATCH_RUNTIME_FILES)
    except Exception as e:  # pragma: no cover - import-environment dependent
        print(f"warning: could not load the guard surface set ({e}); "
              "T1_GATED detection is OFF this run", file=sys.stderr)
        return ()


def gather_planned_numbers(root: Path) -> tuple:
    """Which issue numbers already have a plan doc behind them.

    Two signals, unioned: a plan doc that references `#N` / `issues/N`, and
    an issue body that names a `docs/NN_` plan which exists on disk is caught
    later via `body_names_existing_plan` — this gathers the first plus the
    set of existing plan numbers for the second."""
    referenced = set()
    existing = set()
    for p in sorted(root.glob("docs/**/*-plan.md")):
        m = re.match(r"(\d+)_", p.name)
        if m:
            existing.add(int(m.group(1)))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for hit in re.finditer(r"(?<![\w&])#(\d{1,4})\b", text):
            referenced.add(int(hit.group(1)))
        for hit in re.finditer(r"issues/(\d{1,4})\b", text):
            referenced.add(int(hit.group(1)))
    return frozenset(referenced), frozenset(existing)


def body_names_existing_plan(body: str, existing_plan_numbers) -> bool:
    """True iff the issue body names a `docs/NN` plan that exists on disk."""
    for hit in re.finditer(r"docs/(\d{1,4})\b", body or ""):
        if int(hit.group(1)) in existing_plan_numbers:
            return True
    return False


def gather_attempts() -> list:
    """The lane-journal OP_ATTEMPT rows, `ts` → `attempted_at_ms` derived
    exactly as `dos cooldown`'s CLI does."""
    from dos import lane_journal as _lj

    rows = []
    for rec in _lj.read_all():
        if str(rec.get("op") or "") != "ATTEMPT":
            continue
        if "attempted_at_ms" not in rec:
            ts = str(rec.get("ts") or "")
            try:
                dtv = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=_dt.timezone.utc)
                rec = {**rec, "attempted_at_ms": int(dtv.timestamp() * 1000)}
            except ValueError:
                continue
        rows.append(rec)
    return rows


def gather_cooling(numbers, attempts, *, now_ms: int) -> dict:
    """Run the kernel cooldown fold per issue → `{number: {until_ms, reason}}`
    for the held ones only. The policy is the workspace's own `[cooldown]`."""
    from dos import config as _config
    from dos.cooldown import CooldownState, cooldown_verdict

    policy = _config.active().cooldown
    out = {}
    for n in numbers:
        v = cooldown_verdict(f"{_UNIT_PREFIX}{n}", attempts, now_ms=now_ms, policy=policy)
        if v.state is CooldownState.RECENTLY_ATTEMPTED:
            out[n] = {"until_ms": v.until_ms, "reason": v.reason}
    return out


def record_attempt(number: int, outcome: str) -> dict:
    """Append the standard OP_ATTEMPT for `issue-N` so the kernel folds see it."""
    from dos import lane_journal as _lj

    entry = _lj.attempt_entry(f"{_UNIT_PREFIX}{number}", outcome=outcome, lane="backlog")
    return _lj.append(entry)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="backlog_triage",
        description="Deterministic triage of the open-issue backlog (docs/315). "
                    "Types every issue, orders the offerable queue, exit IS the verdict.",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    ap.add_argument("--top", type=int, default=0, metavar="N",
                    help="show only the first N queue rows in the table")
    ap.add_argument("--limit", type=int, default=200, help="gh issue list --limit")
    ap.add_argument("--issues-json", default=None, metavar="PATH",
                    help="replay/test mode: read issues from a JSON file ('-' = stdin) "
                         "instead of calling gh")
    ap.add_argument("--root", default=".", help="repo root for the plan-doc index")
    ap.add_argument("--record-attempt", type=int, default=None, metavar="N",
                    help="record a pick attempt on issue N (writes the lane-journal "
                         "OP_ATTEMPT for unit issue-N), then exit")
    ap.add_argument("--outcome", default=None, choices=OUTCOMES,
                    help="the attempt's outcome (required with --record-attempt)")
    args = ap.parse_args(argv)

    if args.record_attempt is not None:
        if not args.outcome:
            print("error: --record-attempt requires --outcome "
                  f"{{{','.join(OUTCOMES)}}}", file=sys.stderr)
            return EXIT_CONTRACT_ERROR
        entry = record_attempt(args.record_attempt, args.outcome)
        print(json.dumps({"recorded": entry}, indent=2, sort_keys=True))
        return 0

    try:
        if args.issues_json:
            raw = (sys.stdin.read() if args.issues_json == "-"
                   else Path(args.issues_json).read_text(encoding="utf-8"))
            issues = [normalize_issue(r) for r in json.loads(raw)]
        else:
            issues = gather_issues(limit=args.limit)
    except Exception as e:
        print(f"error: could not gather issues: {e}", file=sys.stderr)
        return EXIT_CONTRACT_ERROR

    root = Path(args.root).resolve()
    referenced, existing = gather_planned_numbers(root)
    planned = set(referenced)
    for i in issues:
        if body_names_existing_plan(i["body"], existing):
            planned.add(i["number"])

    try:
        attempts = gather_attempts()
    except Exception as e:
        print(f"warning: could not read the attempt journal ({e}); "
              "cooldown/freshness are OFF this run", file=sys.stderr)
        attempts = []
    now_ms = int(time.time() * 1000)
    try:
        cooling = gather_cooling([i["number"] for i in issues], attempts, now_ms=now_ms)
    except Exception as e:
        print(f"warning: cooldown fold unavailable ({e})", file=sys.stderr)
        cooling = {}

    result = triage(
        issues,
        t1_surfaces=gather_t1_surfaces(),
        planned_numbers=frozenset(planned),
        cooling=cooling,
        attempt_records=attempts,
    )
    if args.json:
        print(json.dumps(
            {k: result[k] for k in ("rows", "queue", "counts", "exit_code")},
            indent=2, sort_keys=True))
    else:
        print(render(result, top=args.top))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
