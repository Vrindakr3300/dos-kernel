"""Every tracked .gitignore pattern line must be ALL pattern — the space litmus.

Two shipped instances of the same silent failure class (both found and fixed
2026-06-10, after the public seed):

- benchmark/toolathlon/.gitignore carried trailing inline comments on three
  negation lines (`!_results/replay_all_rows.csv      # the flat per-run rows`).
  A `#` only starts a comment at line START, so the comment text became part of
  the pattern, the negation matched nothing, and the durable deliverables the
  comments promised were silently NOT tracked — the public seed shipped without
  them (the file's own NB documented the trap; the early lines predated it).
- The root .gitignore shipped (in the v0.22.0 seed commit itself) a pattern line
  fused with comment prose: `benchmark/_cc_* is handled in paper/.gitignore — …`.
  As a pattern it matched nothing, so the scratch family it was meant to keep
  out of the public tree was not actually ignored.

Both bugs share one observable: a non-comment line containing an internal
space. No legitimate pattern in this repo contains one (verified repo-wide at
authoring time), so the lint is exact here. If a path with a real space is ever
needed, extend this test's allowlist rather than weakening the rule.

The second test closes the loop from the other side: every NEGATION naming a
literal path (no glob metacharacters) is a promise that the path is trackable —
ask `git check-ignore` whether the promise holds for the paths that exist. That
catches the failure class regardless of cause (trailing comment, prose fusion,
or a parent-directory exclusion swallowing the re-include).

The roster is `git ls-files`, honoring "tracked here = ships": a gitignored
local scratch .gitignore must not redden the suite.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Glob metacharacters: a negation containing one names a family, not a literal
# path, so it cannot be existence-checked.
_GLOB_CHARS = set("*?[")


def _tracked_gitignore_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "*.gitignore"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / rel for rel in out.split("\0") if rel]


def _pattern_lines(path: Path) -> list[tuple[int, str]]:
    """(1-based line number, rstripped line) for every non-comment, non-blank line."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip()  # git itself trims unescaped trailing whitespace
        if not line or line.startswith("#"):
            continue
        out.append((i, line))
    return out


def test_no_internal_space_in_any_pattern_line():
    files = _tracked_gitignore_files()
    assert files, (
        "no tracked .gitignore files found — "
        "either the checkout is broken or this litmus's roster query is"
    )
    offenders = []
    for path in files:
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in _pattern_lines(path):
            if " " in line:
                offenders.append(f"{rel}:{lineno}: {line}")
    assert not offenders, (
        "a .gitignore pattern line containing a space is almost certainly a "
        "trailing inline comment or comment prose fused onto the pattern — "
        "either way the pattern silently matches nothing (the toolathlon "
        "negation / root benchmark/_cc_* failure class). Move the comment to "
        "its own line:\n" + "\n".join(offenders)
    )


def test_negated_literal_paths_are_actually_includable():
    checked = 0
    broken = []
    for path in _tracked_gitignore_files():
        rel_dir = path.parent.relative_to(REPO_ROOT)
        for lineno, line in _pattern_lines(path):
            if not line.startswith("!"):
                continue
            body = line[1:]
            if _GLOB_CHARS & set(body):
                continue  # a family negation, not a literal path
            # A pattern is relative to its .gitignore's directory.
            target = (REPO_ROOT / rel_dir / body.strip("/")).resolve()
            if not target.exists():
                continue  # nothing on disk to adjudicate yet
            checked += 1
            verdict = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--",
                 str(target.relative_to(REPO_ROOT))],
                capture_output=True,
            )
            if verdict.returncode == 0:  # 0 = the path IS ignored: negation dead
                where = f"{path.relative_to(REPO_ROOT)}:{lineno}"
                broken.append(f"{where}: '!{body}' does not re-include {target.relative_to(REPO_ROOT)}")
    assert checked, "no literal negations resolved to an existing path — roster query broken?"
    assert not broken, (
        "these negations promise a trackable path but git still ignores it "
        "(dead re-include — the silently-untracked-deliverable failure class):\n"
        + "\n".join(broken)
    )
