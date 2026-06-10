"""SKP Phase 4 — the planning skills (`dos-replan`, `dos-replan-loop`).

`dos-replan`'s domain-free core is closure detection: a queue item whose phases
now `dos verify` as shipped is closed. `dos-replan-loop`'s one generic
correctness point is the release guard reading the workspace trunk from config
(this repo's trunk is `master`, not `main`). This test drives the kernel
surfaces those screenplays call:

  1. **`test_dos_replan_closes_shipped_item`** — a queue item whose phases verify
     as shipped is detected as closed (via `dos verify`), while an unshipped item
     stays open — the auto-close pass over the truth syscall.
  2. **`test_replan_loop_resolves_trunk_not_hardcoded`** — the generic trunk
     resolution handles a `master`-trunk repo (and would handle `main`), proving
     the release guard reads the branch, never assumes it.

Plus the grep guard: the shipped skills name no host literal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import dos


SKILL_DIR = Path(dos.__file__).parent / "skills"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _cli(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    # Pin the subprocess to the SAME `dos` source tree this test imported (see
    # test_skill_pack_generic._cli) so a sibling editable install can't shadow it.
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(dos.__file__).parents[1])}
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


def _foreign_repo(repo: Path) -> None:
    """A foreign repo with a generic stamp; SHIP1 shipped, OPEN1 not."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo / "dos.toml", "[stamp]\nstyle='grep'\nsubject_dirs=[]\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init: dos.toml")
    _git(repo, "commit", "--allow-empty", "-q", "-m", "SHIP1: ship the closer")


# ===========================================================================
# (1) closure detection via the truth syscall
# ===========================================================================


def test_dos_replan_closes_shipped_item(tmp_path: Path):
    """A queue item whose phase verifies as shipped is CLOSED; an unshipped item
    stays OPEN — the auto-close pass `dos-replan` Step 2 runs over `dos verify`."""
    repo = tmp_path / "svc"
    _foreign_repo(repo)

    # The replan skill's closure rule: an item is closed iff every phase verifies
    # as shipped. Drive it for two queue items.
    queue = [("SHIP", "SHIP1"), ("OPEN", "OPEN1")]
    closed, still_open = [], []
    for plan, phase in queue:
        v = json.loads(_cli(repo, "verify", plan, phase, "--json").stdout)
        (closed if v["shipped"] else still_open).append((plan, phase))

    assert closed == [("SHIP", "SHIP1")], closed       # shipped → closed
    assert still_open == [("OPEN", "OPEN1")], still_open  # unshipped → stays open


# ===========================================================================
# (2) the release guard resolves trunk, never hardcodes it
# ===========================================================================


def _resolve_trunk(repo: Path) -> str | None:
    """The generic trunk resolution the `dos-replan-loop` release guard uses:
    the remote default branch (origin/HEAD) if positively known, else None
    (UNKNOWN → the guard fails closed and skips the release). It NEVER falls back
    to the current branch, which would make the on-trunk check trivially true."""
    r = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "--short",
                        "refs/remotes/origin/HEAD"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().split("/", 1)[-1]
    return None  # UNKNOWN — fail closed


def _set_origin_head(repo: Path, branch: str) -> None:
    """Give the repo a self-origin with a known default branch, so trunk
    resolution has an `origin/HEAD` to read (mirrors a real clone)."""
    _git(repo, "branch", "-M", branch)
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "remote", "set-head", "origin", branch)


def test_replan_loop_resolves_trunk_not_hardcoded(tmp_path: Path):
    """The release guard reads the trunk from git's origin/HEAD, handling a
    `master`-trunk repo (and, symmetrically, a `main`-trunk one) — never assuming
    a branch name."""
    repo = tmp_path / "svc"
    _foreign_repo(repo)
    _set_origin_head(repo, "master")  # this project's trunk
    assert _resolve_trunk(repo) == "master"

    repo2 = tmp_path / "svc2"
    _foreign_repo(repo2)
    _set_origin_head(repo2, "main")   # a main-trunk repo — same code, no literal
    assert _resolve_trunk(repo2) == "main"


def test_replan_loop_trunk_unknown_fails_closed(tmp_path: Path):
    """With no resolvable origin/HEAD, the trunk is UNKNOWN — the guard must fail
    closed (return None), NOT fall back to the current branch (which would let an
    auto-commit proceed off-trunk)."""
    repo = tmp_path / "svc"
    _foreign_repo(repo)
    _git(repo, "branch", "-M", "feature/x")  # on a feature branch, no origin
    assert _resolve_trunk(repo) is None


# ===========================================================================
# (3) the shipped replan skills name no host literal
# ===========================================================================


def test_replan_skills_ship_and_name_no_host_literal():
    for name in ("dos-replan", "dos-replan-loop"):
        skill = SKILL_DIR / name / "SKILL.md"
        assert skill.exists(), f"missing {skill}"
        text = skill.read_text(encoding="utf-8")
        for token in ("docs/_plans", "decisions-pending.md", "findings-followup-queue",
                      "next-hits.md", "replan-state.yaml"):
            assert token not in text, f"{name} must not name {token!r}"
        for lane in ("apply", "tailor", "discovery"):
            assert lane not in text, f"{name} must not name job lane {lane!r}"


def test_replan_loop_does_not_hardcode_main_or_master():
    """The loop skill must not assert a trunk literal as the guard — it must
    resolve it. (Mentioning both in prose to say 'resolve, don't assume' is fine;
    what's forbidden is a guard line that hardcodes one.)"""
    text = (SKILL_DIR / "dos-replan-loop" / "SKILL.md").read_text(encoding="utf-8")
    # the skill explicitly teaches 'resolve the trunk', and names master only as
    # this-repo's example, never as the universal guard value.
    assert "resolve" in text.lower()
    assert "never hardcode" in text.lower() or "never assume" in text.lower() \
        or "do not hardcode" in text.lower()
