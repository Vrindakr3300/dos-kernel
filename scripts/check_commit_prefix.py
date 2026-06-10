#!/usr/bin/env python3
"""DOS `/release` commit-prefix lint — opt-in, warn, NEVER block (docs/267).

Wired by `/release` Step 1.5 only when the operator passes `--lint-prefix`. The
lint scans the subject line(s) about to be committed (or, for a dry inspection,
a commit/range on HEAD) and **warns** when a subject's prefix does not match the
shape DOS commit subjects actually use.

This is the DOS analogue of the userland app's `check_release_commit_prefix.py`,
**deliberately de-coupled from that repo's taxonomy.** The userland app imports a
`_NOISE_PREFIXES` set — its dispatch/fanout/replan bookkeeping cluster — to know
the "known-good" prefixes. DOS has no such cluster: its subjects are
conventional-commit-flavoured (`feat(efficiency):`, `docs(CLAUDE):`, `fix(loop_decide):`),
plain `area:` (`paper:`, `release:`), `docs/NN …:` plan refs, or a bare `vX.Y.Z:`
release output (see `git log`). So the DOS lint recognizes the *general* shape
`<token>:` plus `vX.Y.Z:`, with no imported host vocabulary — the same
kernel-imports-no-host discipline the `CLAUDE.md` litmus enforces, applied to the
release tooling.

The lint is **opt-in and never blocks**:

  * Exit code is ALWAYS 0 — this is a warning, not a gate (the `C14-philosophy`:
    existing prefixes cluster cleanly enough to filter; the lint is a low-cost
    sanity check, not enforcement, and DOS does no history rewriting for it).
  * On a known prefix the lint prints nothing (silent OK).
  * On an unknown prefix it prints exactly one line to stderr:
      ``lint: unknown prefix '<x>'``
    and still exits 0. The operator can ignore it or rename and recommit. The
    asymmetric goal is to catch a NEW commit that accidentally lands with a
    malformed / prefix-less subject; the warning is the signal, the operator is
    the gate.

> **Two witnesses, two strengths.** This lint is the cheap, *syntactic* check
> ("does the subject match the grammar?"), run BEFORE the commit. DOS's
> `dos commit-audit` is the *semantic, ground-truth* witness ("does the subject's
> CLAIM match its own diff?"), run AFTER (`/release` post-commit step). The lint
> catches a malformed subject; `commit-audit` catches a lying one. Use both.

Usage::

    python scripts/check_commit_prefix.py --subject "feat(oracle): ship it"
    python scripts/check_commit_prefix.py --rev HEAD
    python scripts/check_commit_prefix.py --rev origin/master..HEAD
    python scripts/check_commit_prefix.py --json --subject "weird subject"

``--subject`` and ``--rev`` are mutually exclusive. Default with neither is
``--rev HEAD`` (lint the tip commit). ``--rev`` accepts any single sha, branch,
tag, or ``A..B`` range that ``git log`` understands; every subject in the range
is linted independently.

This is dev / release tooling — it operates ON the package but is never imported
BY it (the `dos.*` modules import nothing under `scripts/`).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# A bare `vX.Y.Z:` version commit — the legitimate `/release` output.
_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+:")

# A "source-style" prefix has the shape ``<token>:`` where ``<token>`` starts
# with an alphanumeric and contains only alphanumerics, ``.``, ``/``, ``_``,
# ``-``, ``§``, ``(``, ``)`` or a single internal space. This matches every DOS
# subject family observed in `git log`:
#   * conventional-commit:  ``feat(efficiency):``  ``docs(CLAUDE):``  ``fix(loop_decide):``
#   * plain area:            ``paper:``  ``release:``  ``test:``  ``docs:``
#   * plan-ref:              ``docs/125 §8:``  ``docs/267:``
#   * groundwork-tagged:     ``GHF4 (groundwork):``
# It does NOT import a host noise-prefix list (the userland app's `_NOISE_PREFIXES`)
# — DOS names no host in its tooling.
_SOURCE_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_§()\- ]*:")

# A UTF-8 BOM can leak into a subject when a message file was written with a
# BOM-emitting tool (`Out-File utf8` on Windows — a documented DOS scar; see the
# `feedback-pathspec-commit-pulls-working-tree` memory). Strip a leading BOM
# before classifying so a BOM alone never reads as an "unknown prefix" — but the
# `--json` report still flags it (`bom: true`) so the operator can fix the writer.
_BOM = "﻿"


def repo_root() -> Path:
    """The git top-level of the repo this script runs inside (see release_context)."""
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        top = ""
    return Path(top) if top else Path.cwd()


def has_bom(subject: str) -> bool:
    """True if the raw subject leads with a UTF-8 BOM (a writer artifact)."""
    return subject.startswith(_BOM)


def is_known_prefix(subject: str) -> bool:
    """Return True if ``subject`` carries a recognized DOS prefix shape."""
    s = subject.lstrip(_BOM).lstrip()
    if not s:
        return False
    # Version-bump (`vX.Y.Z:`) — the legitimate `/release` output.
    if _VERSION_RE.match(s):
        return True
    # General source-prefix shape — any `<area>:` lead-in.
    if _SOURCE_PREFIX_RE.match(s):
        return True
    return False


def extract_prefix(subject: str) -> str:
    """Best-effort prefix extraction for the warning message.

    Returns whatever sits before the first ``:`` (capped at 40 chars). If there
    is no colon, returns the first whitespace-separated token. Human-facing only.
    """
    s = subject.lstrip(_BOM).lstrip()
    if not s:
        return ""
    if ":" in s:
        head = s.split(":", 1)[0]
    else:
        head = s.split(None, 1)[0]
    return head[:40]


def subjects_from_rev(rev: str, *, root: Path, single: bool) -> list[tuple[str, str]]:
    """Return [(sha, subject)] for the ``rev`` spec.

    ``single`` linting one tip (``git log -1``); otherwise every commit in the
    ``A..B`` range. Exits with git's code on a bad rev (the lint can't lint what
    git can't resolve) — this is the ONE non-zero exit, and it's a usage error,
    not a lint failure.
    """
    cmd = ["git", "log", "--pretty=format:%H%x00%s", rev]
    if single:
        cmd.insert(2, "-1")
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                          encoding="utf-8", check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(proc.returncode)
    rows: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        sha, _, subj = line.partition("\x00")
        rows.append((sha, subj))
    return rows


def lint_subjects(rows: list[tuple[str, str]]) -> list[dict]:
    """Classify each (sha, subject) pair. Returns one report dict per row."""
    out: list[dict] = []
    for sha, subj in rows:
        known = is_known_prefix(subj)
        out.append({
            "sha": sha,
            "subject": subj,
            "known": known,
            "bom": has_bom(subj),
            "prefix": extract_prefix(subj) if not known else None,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument("--subject", help="lint this literal subject string instead of git history")
    src.add_argument("--rev", help="lint every commit subject in this git rev / range (default: HEAD)")
    p.add_argument("--json", action="store_true", help="emit one JSON object per linted commit")
    args = p.parse_args(argv)

    if args.subject is not None:
        rows = [("(arg)", args.subject)]
    else:
        root = repo_root()
        rev = args.rev or "HEAD"
        single = ".." not in rev
        rows = subjects_from_rev(rev, root=root, single=single)

    reports = lint_subjects(rows)

    if args.json:
        for r in reports:
            sys.stdout.write(json.dumps(r) + "\n")
    else:
        for r in reports:
            if not r["known"]:
                sys.stderr.write(f"lint: unknown prefix {r['prefix']!r}\n")
            elif r["bom"]:
                # Known prefix but a BOM leaked in — warn so the writer gets fixed,
                # still exit 0. The BOM is the scar, not the prefix.
                sys.stderr.write("lint: subject leads with a UTF-8 BOM (fix the message writer)\n")

    # Opt-in, warn-never-block — always exit 0.
    return 0


if __name__ == "__main__":
    sys.exit(main())
