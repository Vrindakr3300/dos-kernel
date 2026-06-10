"""The grep rung runs IN-PROCESS — equivalent to the old subprocess, and faster (docs/275).

`oracle.default_grep_fallback_batch` used to shell out to a second Python
interpreter (`python -m dos.phase_shipped --batch`) that re-ran `import dos` just
to grep git — ~170ms of pure interpreter-startup overhead per `verify`, paid by a
long-lived consumer (the MCP server, the `dispatch_top`/`plan_board` fan-outs) on
every call. docs/275 made it run in-process by calling the SAME functions the
child's `--batch main()` ran.

This module is the self-test that keeps that change honest. The load-bearing
claim is **byte-identical verdicts** — a performance refactor that changed an
answer would be a silent correctness regression, exactly what the kernel exists to
catch. So the tests pin:

  * the in-process path and the (kept-as-fallback) subprocess path return the SAME
    `shipped`/`source`/`sha`/`rung` on the same repo — the equivalence that makes
    the speedup safe;
  * by DEFAULT, a grep resolves with ZERO subprocess spawns (the structural guard
    that the slow path cannot creep back in — a deterministic check, not a flaky
    wall-clock threshold);
  * the `DOS_ORACLE_GREP_SUBPROCESS=1` escape hatch still forces the out-of-process
    rung (so the fallback is reachable, not dead code);
  * the per-(root, sha) touched-file memo returns a consistent, caller-isolated set.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dos import config as _config
from dos import oracle


@pytest.fixture(autouse=True)
def _restore_global_state():
    """Snapshot and restore the process-global active config + the per-process
    caches around every test here.

    These tests `set_active(cfg)` a config rooted at a `tmp_path` (so the grep
    rung, which reads `config.active()`, scans the right repo). Without restoring
    the PRIOR active config, the global would be left pointing at a tmp_path pytest
    then deletes — and every LATER test in the suite that touches `config.active()`
    would error against a vanished directory. Saving the real prior config (not
    fabricating a fresh one rooted at the doomed tmp_path) is the discipline
    `oracle.is_shipped` itself uses internally; this fixture lifts it to the test
    boundary so a test can never leak a dead-rooted active config.
    """
    prev_active = _config.active()
    oracle._clear_touched_files_cache()
    try:
        yield
    finally:
        _config.set_active(prev_active)
        oracle._clear_touched_files_cache()


# ---------------------------------------------------------------------------
# helpers — a real git repo whose ship is in the SUBJECT (the grep rung's job)
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _repo_with_ship(repo: Path) -> "_config.SubstrateConfig":
    """A plain git repo with a generic-grammar ship subject + a real file commit.

    Returns the workspace config (generic default → `GENERIC_STAMP_CONVENTION`), so
    a bare `<SERIES>: <PHASE>` subject is a direct ship. The file commit gives the
    touched-files memo a real sha to read.
    """
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo")
    (repo / "surfacer.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "surfacer.py")
    _git(repo, "commit", "-m", "AUTH: AUTH2 — ship the surfacer")
    return _config.default_config(repo)


# The pairs every equivalence test checks: one real ship, two honest negatives.
_PAIRS = [
    ("AUTH", "AUTH2"),          # shipped (subject names it)
    ("AUTH", "AUTH9"),          # never shipped — honest negative
    ("NOPE", "NOPE1"),          # unknown series — honest negative
]


def _verdict_tuple(v: "oracle.ShipVerdict") -> tuple:
    """The fields a regression could move — the equivalence key."""
    return (v.shipped, v.source, v.sha, v.rung)


# ---------------------------------------------------------------------------
# the equivalence that makes the speedup SAFE
# ---------------------------------------------------------------------------
def test_in_process_and_subprocess_grep_are_byte_identical(tmp_path, monkeypatch):
    """The in-process rung and the subprocess fallback return the SAME verdicts.

    This is the whole soundness argument for docs/275: the process boundary was an
    implementation detail with a 170ms tax, never part of the verdict. Driven on a
    real repo through `oracle.is_shipped(cfg=…)` (the production call shape) so the
    full pipeline — grep rung → forgeability `source` grading → #399 demotion — is
    compared end-to-end, not just the raw rung.
    """
    cfg = _repo_with_ship(tmp_path)
    oracle._clear_touched_files_cache()

    # Default path (in-process).
    monkeypatch.delenv("DOS_ORACLE_GREP_SUBPROCESS", raising=False)
    in_proc = {p: _verdict_tuple(oracle.is_shipped(p[0], p[1], cfg=cfg)) for p in _PAIRS}

    # Forced subprocess (the kept fallback).
    monkeypatch.setenv("DOS_ORACLE_GREP_SUBPROCESS", "1")
    sub_proc = {p: _verdict_tuple(oracle.is_shipped(p[0], p[1], cfg=cfg)) for p in _PAIRS}

    assert in_proc == sub_proc, (
        f"in-process vs subprocess verdicts diverged:\n  in-process={in_proc}\n"
        f"  subprocess={sub_proc}")
    # And the ship is actually FOUND (a degenerate all-`source=none` match would be
    # equal but meaningless — pin that the real ship resolved through both paths).
    assert in_proc[("AUTH", "AUTH2")][0] is True            # shipped
    assert in_proc[("AUTH", "AUTH2")][1] == "grep-subject"  # the forgeable subject rung
    assert in_proc[("AUTH", "AUTH9")][0] is False           # honest negative


def test_batch_in_process_matches_subprocess_batch(tmp_path, monkeypatch):
    """The same equivalence at the batch entry (`default_grep_fallback_batch`).

    A fan-out caller hits the batch directly (one git-log cache, N pairs). Pin that
    the in-process batch and the subprocess batch agree key-for-key.
    """
    cfg = _repo_with_ship(tmp_path)
    _config.set_active(cfg)  # the autouse fixture restores the prior active config
    monkeypatch.delenv("DOS_ORACLE_GREP_SUBPROCESS", raising=False)
    ip = oracle.default_grep_fallback_batch(list(_PAIRS))
    monkeypatch.setenv("DOS_ORACLE_GREP_SUBPROCESS", "1")
    sp = oracle.default_grep_fallback_batch(list(_PAIRS))

    assert {k: _verdict_tuple(v) for k, v in ip.items()} == \
           {k: _verdict_tuple(v) for k, v in sp.items()}
    # The shipped pair is present in both (not a vacuous empty-vs-empty match).
    assert ip[("AUTH", "AUTH2")].shipped is True
    assert sp[("AUTH", "AUTH2")].shipped is True


# ---------------------------------------------------------------------------
# the STRUCTURAL guard — the slow path cannot creep back (no timing threshold)
# ---------------------------------------------------------------------------
def test_default_grep_spawns_no_subprocess(tmp_path, monkeypatch):
    """By default the grep rung makes ZERO subprocess spawns — the in-process win.

    Rather than assert a flaky millisecond budget, this pins the MECHANISM that made
    it slow: spawning `python -m dos.phase_shipped`. A spy over `subprocess.run` (the
    one the oracle module would use to shell out) records every call; the default
    path must record none of its own. (The in-process rung's `git log` reads go
    through `phase_shipped`'s OWN `subprocess.run`, in that module's namespace — not
    `oracle`'s — so a spy on `oracle.subprocess.run` cleanly isolates "did the rung
    shell out to a python interpreter?" from "did it run git?".)
    """
    cfg = _repo_with_ship(tmp_path)
    _config.set_active(cfg)  # the autouse fixture restores the prior active config
    spawned: list[list[str]] = []
    real_run = subprocess.run

    def _spy(cmd, *a, **kw):
        spawned.append(list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)])
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(oracle.subprocess, "run", _spy)
    monkeypatch.delenv("DOS_ORACLE_GREP_SUBPROCESS", raising=False)
    oracle.default_grep_fallback_batch([("AUTH", "AUTH2")])

    # The oracle module itself spawned no `python -m dos.phase_shipped` child.
    python_children = [c for c in spawned
                       if any("dos.phase_shipped" in str(part) for part in c)]
    assert python_children == [], (
        f"the default grep rung spawned a python subprocess — the docs/275 "
        f"in-process win regressed: {python_children}")


def test_forced_subprocess_env_spawns_the_child(tmp_path, monkeypatch):
    """`DOS_ORACLE_GREP_SUBPROCESS=1` forces the out-of-process rung (fallback is live).

    The complement of the guard above: the kept fallback must be REACHABLE (not dead
    code), so a flip of the env var must produce exactly the `python -m
    dos.phase_shipped` spawn the default path avoids.
    """
    cfg = _repo_with_ship(tmp_path)
    _config.set_active(cfg)  # the autouse fixture restores the prior active config
    spawned: list[list[str]] = []
    real_run = subprocess.run

    def _spy(cmd, *a, **kw):
        spawned.append(list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)])
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(oracle.subprocess, "run", _spy)
    monkeypatch.setenv("DOS_ORACLE_GREP_SUBPROCESS", "1")
    oracle.default_grep_fallback_batch([("AUTH", "AUTH2")])

    python_children = [c for c in spawned
                       if any("dos.phase_shipped" in str(part) for part in c)]
    assert len(python_children) == 1, (
        f"forced-subprocess mode did not spawn exactly one phase_shipped child: "
        f"{python_children}")


# ---------------------------------------------------------------------------
# the touched-file memo — immutable-sha cache, caller-isolated
# ---------------------------------------------------------------------------
def test_touched_files_memo_is_consistent_and_isolated(tmp_path):
    """`_git_touched_files` caches per (root, sha) and never lets a caller poison it.

    A git sha is content-addressed — its footprint is immutable — so a second read
    returns the same set, and the docs/275 memo collapses the duplicate `git show`
    a single `is_shipped` would otherwise make. Pin both the consistency and the
    defensive copy (a caller mutating the result must not corrupt the cache).
    """
    cfg = _repo_with_ship(tmp_path)
    _config.set_active(cfg)  # the autouse fixture restores prior active + clears caches
    sha = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    first = oracle._git_touched_files(sha)
    assert first is not None and "surfacer.py" in first

    # Mutate the returned set — the cache must be unaffected (defensive copy).
    first.add("POISON")
    second = oracle._git_touched_files(sha)
    assert second is not None
    assert "surfacer.py" in second
    assert "POISON" not in second, "a caller's mutation leaked into the memo"


def test_touched_files_unresolvable_sha_is_safe_and_uncached(tmp_path):
    """An unknown sha returns None (permissive) and is NOT frozen into the cache.

    A transient git failure must be retryable — caching a `None` would freeze a
    false miss. Pin that an unresolvable sha yields None and leaves the memo empty
    for that key (so a later, resolvable read of a real sha is unaffected).
    """
    cfg = _repo_with_ship(tmp_path)
    _config.set_active(cfg)  # the autouse fixture restores prior active + clears caches
    assert oracle._git_touched_files("0" * 40) is None      # unknown sha → permissive None
    assert oracle._git_touched_files("") is None            # empty → None, no git call
    assert oracle._TOUCHED_FILES_CACHE == {}, "a None/empty result was cached"


# ---------------------------------------------------------------------------
# default_commit_touches_doc routes through the touched-file memo (docs/284 follow-up)
#
# The registry-side collision check used to shell its OWN `git show --name-only`
# inline, bypassing `_git_touched_files`'s per-(root,sha) memo — so the SAME
# release-bump sha's footprint was fetched once here AND again by the grep-side
# #399 demotion (`_grep_verdict_is_release_bump_falsepos` → `_git_touched_files`),
# and a fan-out re-paid the spawn per repeated sha. The docs/284 "demotion reads
# from the same scan" deferred item, realized via the existing memo: same git
# command, same verdict, one spawn per distinct immutable sha.
# ---------------------------------------------------------------------------
def _repo_with_plan_and_release_bump(repo: Path) -> tuple["_config.SubstrateConfig", str, str]:
    """A git repo with (A) a plan-doc-stamping ship commit and (C) a release-bump
    -only commit. Returns (cfg, sha_plan_ship, sha_release_bump) — the two SHAs the
    registry-collision predicate's Signal A (True) and Signal C (False) ride."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo")
    # (A) a real ship that stamps the expected plan doc + a code file.
    (repo / "docs").mkdir()
    (repo / "docs" / "42_thing-plan.md").write_text("# plan\nstatus: done\n", encoding="utf-8")
    (repo / "thing.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "docs/42_thing-plan.md", "thing.py")
    _git(repo, "commit", "-m", "docs/42: P1 — ship thing")
    sha_ship = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    # (C) a release-bump-only commit (no plan doc, no code) whose SUBJECT names P1.
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nversion='0.2.0'\n", encoding="utf-8")
    _git(repo, "add", "VERSION", "pyproject.toml")
    _git(repo, "commit", "-m", "v0.2.0: P1 closer batched")
    sha_bump = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    return _config.default_config(repo), sha_ship, sha_bump


def test_default_commit_touches_doc_verdicts(tmp_path):
    """The collision predicate's three verdicts (first DIRECT coverage of it).

    Signal A (commit stamped the EXPECTED plan doc) → True; Signal C (release-bump
    -only footprint, names P1 only in its subject) → False; an unresolvable sha →
    None (permissive — never manufacture a false miss from an unknown sha). These
    are the verdicts `_registry_ship_row` rides to skip a cross-plan collision, so
    a regression here silently culls a live pick or admits a collision.
    """
    cfg, sha_ship, sha_bump = _repo_with_plan_and_release_bump(tmp_path)
    _config.set_active(cfg)  # the autouse fixture restores prior active + clears caches
    doc = "docs/42_thing-plan.md"
    assert oracle.default_commit_touches_doc(sha_ship, doc, "P1") is True
    assert oracle.default_commit_touches_doc(sha_bump, doc, "P1") is False
    assert oracle.default_commit_touches_doc("0" * 12, doc, "P1") is None


def test_default_commit_touches_doc_uses_the_touched_files_memo(tmp_path):
    """The predicate reads footprints through `_git_touched_files`, not its own
    `git show` — so a sha it resolves is CACHED, and the grep-side #399 demotion
    that re-reads the same sha spawns ZERO extra git calls (docs/284 follow-up).

    A spy over `git show --name-only` counts footprint spawns. Pin that:
      (1) the predicate populates the memo for the resolvable sha (warming it), and
      (2) a SECOND footprint read of that sha — the cross-rung double-fetch the old
          inline path re-paid — makes no new spawn.
    """
    cfg, sha_ship, sha_bump = _repo_with_plan_and_release_bump(tmp_path)
    _config.set_active(cfg)  # the autouse fixture restores prior active + clears caches
    oracle._clear_touched_files_cache()

    real_run = subprocess.run
    show_spawns: list[list[str]] = []

    def _spy(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and "show" in cmd and "--name-only" in cmd:
            show_spawns.append(list(cmd))
        return real_run(cmd, *a, **kw)

    # The memo lives in the `oracle` namespace, so spy there.
    import unittest.mock as _mock
    with _mock.patch.object(oracle.subprocess, "run", _spy):
        # First read of the release-bump sha — the predicate must spawn exactly one
        # `git show` and CACHE the result.
        assert oracle.default_commit_touches_doc(sha_bump, "docs/42_thing-plan.md", "P1") is False
        assert len(show_spawns) == 1, (
            f"the predicate did not make exactly one footprint spawn: {show_spawns}")
        assert any(k[1] == sha_bump for k in oracle._TOUCHED_FILES_CACHE), (
            "the predicate did not warm the touched-files memo — it shelled its own "
            "uncached `git show` (the docs/284 follow-up regressed)")

        # The grep-side #399 demotion re-reads the SAME sha's footprint. The old
        # inline path re-paid the spawn; routed through the memo it is free.
        before = len(show_spawns)
        again = oracle._git_touched_files(sha_bump)
        assert again is not None and "VERSION".lower() in {p.lower() for p in again}
        assert len(show_spawns) == before, (
            "re-reading a sha the predicate already resolved spawned a NEW git show "
            "— the cross-rung double-fetch the memo was supposed to collapse")
