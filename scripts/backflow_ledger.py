#!/usr/bin/env python3
"""The job→DOS back-flow ledger generator (docs/207-backflow-ledger.md, live).

Answers one question with evidence, not narration: *are recent `job` dispatch
fixes reaching the kernel, or stranding host-side?*

Two halves:

  LANDED   — auto-derived. A kernel module that lifts a `job` fix CITES that
             fix-id in its source (the docs/207 §8d review rule), so the manifest
             is a `grep` over `src/dos/*.py`, never a registry that drifts. "Did
             fix X land?" is answered by ground truth: the citation lives in the
             module that implements it.

  STRANDED — curated. The high-value `job` dispatch fixes that have NO kernel
             home yet, each with a DECIDED disposition (LIFT→phase / SCOPE-OUT /
             N-A). This is the work-list docs/207 moves. Edited by hand when a new
             fix ships; the OWED detector below flags when that edit is overdue.

The OWED detector (best-effort): if the sibling `job` repo is reachable, scan its
recent `fix(...)`/`feat(...)` dispatch-family commits, drop the ones whose fix-id
already appears LANDED or in the curated STRANDED list, and surface the remainder
as `owed` — a fix that shipped in `job` and is tracked nowhere here. An owed row
means: decide its disposition (lift or scope-out) and add it to STRANDED below.

This is **dev / audit tooling, not kernel** — it operates ON the package and is
never imported BY it (nothing under `src/dos/` imports `scripts/`). Run it in the
docs/127 (DOS↔Bench/Job integration audit) cadence.

Workspace anchor: `git rev-parse --show-toplevel` (the repo this is run inside),
never `__file__/../..`, so it stays honest if `scripts/` is vendored elsewhere.

Usage:
  python scripts/backflow_ledger.py                 # the text ledger, both halves
  python scripts/backflow_ledger.py --json          # machine-readable (for the audit)
  python scripts/backflow_ledger.py --job ../job    # point at the job repo explicitly
  python scripts/backflow_ledger.py --landed-only   # just the grep-derived LANDED half

Exit code: 0 always for a plain render; 1 with --check if any OWED row exists
(so a CI/audit step can fail when a job dispatch fix is tracked nowhere).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# ── The fix-id grammar a kernel citation uses ──────────────────────────────────
# A lift cites its origin as `FQ-<n>` or the `MQ3X` extraction tag. (`finding #n`
# / `#nnn` are the noisier host spellings — we normalize FQ-ids, the durable form.)
_FIX_ID = re.compile(r"\bFQ-\d+\b|\bMQ3X\b")

# ── STRANDED: the curated work-list (docs/207-backflow-ledger.md §STRANDED) ─────
# One row per high-value `job` dispatch fix with NO kernel home. Keep in sync with
# the ledger doc. `fix_ids` is what the OWED detector matches a job commit against.
STRANDED: list[dict] = [
    {
        "id": "S1",
        "fix_ids": ["FQ-491", "FQ-493"],
        "summary": "pickability gap — phase_prefix deriver + stale-% classifier (72082eca)",
        "shipped": "2026-06-07",
        "value": "HIGH",
        "disposition": "LIFT",
        "target": "Phase 2 — enumerate (the phase-list producer)",
    },
    {
        "id": "S2",
        "fix_ids": ["FQ-494"],
        "summary": "deterministic cooldown reset in replan_autoclose (4eea0690)",
        "shipped": "2026-06-06",
        "value": "HIGH",
        "disposition": "LIFT",
        "target": "Phase 3 — the cooldown primitive (ATTEMPT WAL event + PICK_COOLDOWN rung)",
    },
    {
        "id": "S3",
        "fix_ids": [],  # the detached-launch fix carries no FQ-id; matched by keyword
        "match_text": ["child2", "DETACHED", "launch_fanout"],
        "summary": "child2 /fanout launched DETACHED to survive parent -p exit (4c7672cb)",
        "shipped": "2026-06-07",
        "value": "MED",
        "disposition": "SCOPE-OUT",
        "target": "heavy tier (SKP F3) — process-survival is host-orchestration; friction-log",
    },
    {
        "id": "S4",
        "fix_ids": ["FQ-367"],
        "summary": "release orphaned soft-claims from dead /fanout children (d2b8a897)",
        "shipped": "2026-06-07",
        "value": "MED",
        "disposition": "SCOPE-OUT",
        "target": "soft-claim core is the parked heavy tier (SKP F3); lease-health slice already crossed (MQ3X)",
    },
    {
        "id": "S5",
        "fix_ids": ["FQ-498"],
        "summary": "lease scavenged mid-iteration — TTL vs wall-time (47a6e11a)",
        "shipped": "2026-06-07",
        "value": "MED",
        "disposition": "SCOPE-OUT",
        "target": "host lease-TTL value, not a kernel rule; note in docs/110 if a 2nd consumer wants it tunable",
    },
]

# Fix-ids known to be out-of-lane (apply-backend etc.) — never flag these OWED.
_OUT_OF_LANE = {"FQ-472"}

# Commits whose disposition is KNOWN but whose subject carries no FQ-/#nnn token a
# code-citation grep can match (a bare `529`, a `claim_status` keyword, a pure
# host rename). Keyed by job short-sha → (state, where/why). Without this they
# would re-surface OWED every run despite being resolved. Audited 2026-06-07.
_RESOLVED_BY_COMMIT: dict[str, tuple[str, str]] = {
    "3b0d08ae": ("LANDED", "FQ-420 set-not-list root → packet_sidecar.py owns the serialize"),
    "3dde4800": ("LANDED", "bare `529` false-OVERLOADED → loop_decide.py"),
    "6fcf0392": ("LANDED", "dead pid:0 lease reclaim → lease_health.py / supervise.py"),
    "4c9e3253": ("LANDED", "claim_status respect → claim_ttl.py / oracle.py / preflight.py"),
    "f8dc1e6a": ("LANDED", "own-packet self-collision → preflight.py own_packet_basename"),
    "c964281f": ("HOST-ONLY", "agents/ dir rename — host package layout, no kernel concept"),
    "06489e1f": ("HOST-ONLY", "apply gates/ subpackage extract — host refactor"),
    "d876639c": ("HOST-ONLY", "ApplyResult cycle-break — host apply pipeline refactor"),
}

# job dispatch-family commit filter for the OWED scan.
_JOB_DISPATCH = re.compile(
    r"dispatch|fanout|next.?up|replan|picker|pickable|scout|lane|loop|"
    r"cooldown|wedge|drain|ladder|ship_oracle|claim|lease|orphan|gate",
    re.I,
)
_JOB_NOISE = re.compile(r"archive|coalesce|telemetry|reconcile orphaned", re.I)


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return ""


def _toplevel() -> Path:
    out = _run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    return Path(out.strip()) if out.strip() else Path.cwd()


def derive_landed(repo: Path) -> dict[str, list[str]]:
    """fix_id -> sorted list of kernel modules citing it. The LANDED manifest."""
    src = repo / "src" / "dos"
    landed: dict[str, set[str]] = {}
    if not src.is_dir():
        return {}
    for py in sorted(src.glob("*.py")):
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for fid in set(_FIX_ID.findall(text)):
            landed.setdefault(fid, set()).add(py.name)
    return {k: sorted(v) for k, v in sorted(landed.items())}


def scan_job_fixes(job_repo: Path, since: str = "2026-04-24") -> list[tuple[str, str]]:
    """Recent `fix/feat/refactor(...)` dispatch-family commits in the job repo.

    Returns (short_sha, subject) pairs, newest first. Empty if job is unreachable.
    """
    if not (job_repo / ".git").exists():
        return []
    raw = _run(
        ["git", "log", "--oneline", f"--since={since}", "--no-merges"], job_repo
    )
    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        sha, _, subj = line.partition(" ")
        if not re.match(r"^(fix|feat|refactor)\b", subj, re.I):
            continue
        if not _JOB_DISPATCH.search(subj) or _JOB_NOISE.search(subj):
            continue
        out.append((sha, subj))
    return out


def _commit_fix_ids(subject: str) -> set[str]:
    # job spells ids as FQ-n, #n, or (#n/#m); normalize the bare #n to FQ-n.
    ids = set(re.findall(r"\bFQ-\d+\b", subject))
    ids |= {f"FQ-{n}" for n in re.findall(r"#(\d{3,})", subject)}
    return ids


def detect_owed(
    job_fixes: list[tuple[str, str]],
    landed: dict[str, list[str]],
    stranded: list[dict],
) -> list[tuple[str, str]]:
    """job dispatch fixes tracked NOWHERE (not landed, not in the curated list)."""
    landed_ids = set(landed)
    tracked_ids = {fid for row in stranded for fid in row.get("fix_ids", [])}
    tracked_text = [t.lower() for row in stranded for t in row.get("match_text", [])]
    owed: list[tuple[str, str]] = []
    for sha, subj in job_fixes:
        if sha in _RESOLVED_BY_COMMIT:  # known disposition, unmatchable subject
            continue
        ids = _commit_fix_ids(subj)
        if ids & (landed_ids | tracked_ids | _OUT_OF_LANE):
            continue
        if any(t in subj.lower() for t in tracked_text):
            continue
        # a fix with no id at all AND no curated keyword match → genuinely untracked
        owed.append((sha, subj))
    return owed


def render_text(landed, stranded, owed, job_reachable) -> str:
    L = []
    L.append("# job→DOS back-flow ledger (live)\n")
    L.append(f"LANDED: {len(landed)} dispatch fix-ids cited in src/dos/  "
             "(grep -rhoE 'FQ-[0-9]+|MQ3X' src/dos/*.py)\n")
    for fid, mods in landed.items():
        L.append(f"  {fid:<10} {' '.join(mods)}")
    L.append("")
    L.append(f"STRANDED: {len(stranded)} high-value items with no kernel home")
    for r in stranded:
        L.append(f"  {r['id']} [{r['value']:<4} {r['disposition']:<9}] "
                 f"{r['summary']}")
        L.append(f"        → {r['target']}")
    L.append("")
    if _RESOLVED_BY_COMMIT:
        nl = sum(1 for v in _RESOLVED_BY_COMMIT.values() if v[0] == "LANDED")
        nh = sum(1 for v in _RESOLVED_BY_COMMIT.values() if v[0] == "HOST-ONLY")
        L.append(f"RESOLVED (subject carries no matchable id): {nl} LANDED, "
                 f"{nh} HOST-ONLY — see _RESOLVED_BY_COMMIT")
        L.append("")
    if not job_reachable:
        L.append("OWED: (job repo not reachable — pass --job <path> to enable the detector)")
    elif not owed:
        L.append("OWED: none — every recent job dispatch fix is LANDED or has a disposition. ✓")
    else:
        L.append(f"OWED: {len(owed)} job dispatch fix(es) tracked NOWHERE — "
                 "decide a disposition and add to STRANDED:")
        for sha, subj in owed:
            L.append(f"  {sha}  {subj}")
    return "\n".join(L)


def main(argv=None) -> int:
    # Windows consoles default to cp1252; the ledger prints → / ✓. Force UTF-8 so
    # the same output renders identically on win32 and POSIX.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--job", help="path to the job repo (default: ../job)")
    ap.add_argument("--landed-only", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any OWED row exists (CI/audit gate)")
    ap.add_argument("--since", default="2026-04-24")
    args = ap.parse_args(argv)

    repo = _toplevel()
    landed = derive_landed(repo)

    job_repo = Path(args.job) if args.job else (repo.parent / "job")
    job_fixes = scan_job_fixes(job_repo, args.since) if not args.landed_only else []
    job_reachable = bool(job_fixes) or (job_repo / ".git").exists()
    owed = detect_owed(job_fixes, landed, STRANDED) if job_fixes else []

    if args.json:
        print(json.dumps({
            "landed": landed,
            "stranded": STRANDED if not args.landed_only else [],
            "owed": [{"sha": s, "subject": j} for s, j in owed],
            "job_reachable": job_reachable,
        }, indent=2))
    elif args.landed_only:
        for fid, mods in landed.items():
            print(f"{fid:<10} {' '.join(mods)}")
    else:
        print(render_text(landed, STRANDED, owed, job_reachable))

    return 1 if (args.check and owed) else 0


if __name__ == "__main__":
    sys.exit(main())
