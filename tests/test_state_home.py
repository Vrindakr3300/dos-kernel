"""The `.dos/` state-home layout — DOS's emissions live under a per-project
`.dos/`, the host's plan registry stays repo-relative-and-generic, and `job`
does not move (docs/74_state-home-plan.md, Phase 1).

These pin the pure layout/resolution surface (no I/O): `PathLayout.for_dos_dir`,
`resolve_dos_home`'s precedence ladder, `project_id` determinism, and the
load-bearing back-compat invariants the critique flagged — `job_config` byte-
unchanged, the new fields keyword-only at the end, `with_root` preserving style.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dos.config import (
    HomeLayout,
    PathLayout,
    default_config,
    job_config,
    resolve_dos_home,
)


# ---------------------------------------------------------------------------
# for_dos_dir — DOS emissions under .dos/, registry repo-relative + generic.
# ---------------------------------------------------------------------------


def test_dos_emissions_live_under_dot_dos(tmp_path: Path):
    """Every DOS-emission path resolves under `<root>/.dos/`."""
    layout = PathLayout.for_dos_dir(tmp_path)
    d = tmp_path.resolve() / ".dos"
    for field in (
        "fanout_runs", "dispatch_loops", "chained_runs", "next_packets",
        "replan_dir", "soaks_index", "picker_audits", "archive_lock",
        "lane_journal", "leases_dir", "project_card",
    ):
        value = getattr(layout, field)
        assert d in value.parents or value == d, f"{field}={value} not under {d}"


def test_run_dir_trees_collapse_to_one(tmp_path: Path):
    """The three run-dir fields alias one `.dos/runs` directory under the generic
    layout (they stay three fields only for `for_root` back-compat)."""
    layout = PathLayout.for_dos_dir(tmp_path)
    runs = tmp_path.resolve() / ".dos" / "runs"
    assert layout.fanout_runs == runs
    assert layout.dispatch_loops == runs
    assert layout.chained_runs == runs


def test_archive_lock_is_under_leases(tmp_path: Path):
    """The lease/lock live under `.dos/leases/` and the lock is derived from it."""
    layout = PathLayout.for_dos_dir(tmp_path)
    leases = tmp_path.resolve() / ".dos" / "leases"
    assert layout.leases_dir == leases
    assert layout.archive_lock == leases / ".archive.lock"


def test_generic_registry_is_not_job_shaped(tmp_path: Path):
    """The generic default's plan registry must NOT copy job's `docs/_plans` path
    (that would re-bake a host's directory dialect into the domain-free default).
    It is a generic, repo-relative location — `dos.state.yaml`."""
    layout = PathLayout.for_dos_dir(tmp_path)
    assert "_plans" not in str(layout.execution_state)
    assert layout.execution_state == tmp_path.resolve() / "dos.state.yaml"
    assert layout.findings_queue == tmp_path.resolve() / "dos.findings.md"
    # plans_glob stays the conventional discovery glob (harmless — matches nothing
    # in a repo without plan docs, the no-plan contract).
    assert layout.plans_glob == "docs/**/*-plan.md"


def test_dot_dos_and_verdicts_properties(tmp_path: Path):
    """`dot_dos` is derived from root (never duplicates it); `verdicts_dir` IS
    `next_packets` (one directory, one source of truth)."""
    layout = PathLayout.for_dos_dir(tmp_path)
    assert layout.dot_dos == tmp_path.resolve() / ".dos"
    assert layout.verdicts_dir == layout.next_packets


# ---------------------------------------------------------------------------
# Law 1 — job must not move; the generic default flips, the job default doesn't.
# ---------------------------------------------------------------------------


def test_job_config_layout_is_unchanged(tmp_path: Path):
    """`job_config` keeps the `for_root` (docs/_plans) layout byte-for-byte —
    the load-bearing Law-1 proof. Style stays 'repo'; the archive lock keeps its
    literal `docs/_fanout_runs/.archive.lock` (NOT re-derived from leases_dir)."""
    j = job_config(tmp_path).paths
    r = tmp_path.resolve()
    assert j.style == "repo"
    assert j.lane_journal == r / "docs" / "_plans" / "lane-journal.jsonl"
    assert j.execution_state == r / "docs" / "_plans" / "execution-state.yaml"
    assert j.archive_lock == r / "docs" / "_fanout_runs" / ".archive.lock"
    assert j.fanout_runs == r / "docs" / "_fanout_runs"
    assert j.next_packets == r / "output" / "next-up"


def test_default_uses_for_dos_dir(tmp_path: Path):
    """`default_config` is the ONLY place the layout flips to `.dos/`."""
    d = default_config(tmp_path).paths
    assert d.style == "dos"
    assert d.lane_journal == tmp_path.resolve() / ".dos" / "lane-journal.jsonl"


# ---------------------------------------------------------------------------
# with_root — re-points PRESERVING layout style (must not drag .dos/ → job).
# ---------------------------------------------------------------------------


def test_with_root_preserves_dos_style(tmp_path: Path):
    """A `.dos/`-style config re-pointed to a new root stays `.dos/` style under
    the new root — it must never silently revert to the job docs/_plans tree."""
    other = tmp_path / "other"
    repointed = default_config(tmp_path).with_root(other)
    assert repointed.paths.style == "dos"
    assert repointed.paths.lane_journal == other.resolve() / ".dos" / "lane-journal.jsonl"


def test_with_root_preserves_repo_style(tmp_path: Path):
    """A job (`for_root`) config re-pointed stays the job layout."""
    other = tmp_path / "other"
    repointed = job_config(tmp_path).with_root(other)
    assert repointed.paths.style == "repo"
    assert repointed.paths.lane_journal == other.resolve() / "docs" / "_plans" / "lane-journal.jsonl"


# ---------------------------------------------------------------------------
# Back-compat — the new fields are keyword-only with defaults at the END, so
# positional / classmethod construction is unbroken and the two factories'
# archive_lock asymmetry (literal vs leases-derived) is locked.
# ---------------------------------------------------------------------------


def test_new_fields_default_when_unset(tmp_path: Path):
    """A bare `for_root` build leaves the new fields at their defaults except
    where `for_root` sets them (style='repo', leases_dir=docs/_plans)."""
    j = job_config(tmp_path).paths
    assert j.project_card is None
    assert j.leases_dir == tmp_path.resolve() / "docs" / "_plans"
    assert j.style == "repo"


def test_archive_lock_asymmetry_is_locked(tmp_path: Path):
    """`for_root` archive_lock is a literal docs path; `for_dos_dir` derives it
    from leases_dir. Pin the asymmetry so a future editor can't silently unify
    them (which would move job's lock)."""
    repo = PathLayout.for_root(tmp_path)
    dos = PathLayout.for_dos_dir(tmp_path)
    assert repo.archive_lock == tmp_path.resolve() / "docs" / "_fanout_runs" / ".archive.lock"
    assert dos.archive_lock == dos.leases_dir / ".archive.lock"
    assert repo.archive_lock != dos.archive_lock


# ---------------------------------------------------------------------------
# resolve_dos_home — the precedence ladder (pure path math, never creates).
# ---------------------------------------------------------------------------


class TestResolveDosHome:
    def test_explicit_arg_wins(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "env"))
        assert resolve_dos_home(tmp_path / "explicit") == (tmp_path / "explicit").resolve()

    def test_dispatch_home_env_second(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "env"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert resolve_dos_home() == (tmp_path / "env").resolve()

    def test_xdg_data_home_third(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("DISPATCH_HOME", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert resolve_dos_home() == (tmp_path / "xdg" / "dos").resolve()

    def test_win32_appdata_fourth(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("DISPATCH_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        assert resolve_dos_home() == (tmp_path / "appdata" / "dos").resolve()

    def test_home_fallback_last(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("DISPATCH_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")  # skip the appdata branch
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "h"))
        assert resolve_dos_home() == (tmp_path / "h" / ".dos").resolve()

    def test_win32_falls_to_home_when_no_appdata(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("DISPATCH_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "h"))
        assert resolve_dos_home() == (tmp_path / "h" / ".dos").resolve()

    def test_never_creates_the_dir(self, tmp_path: Path, monkeypatch):
        """A read-only syscall must be able to ASK for the home path without a
        write — resolve_dos_home is pure path math, never a mkdir."""
        target = tmp_path / "env"
        monkeypatch.setenv("DISPATCH_HOME", str(target))
        resolve_dos_home()
        assert not target.exists()


def test_home_layout_for_home(tmp_path: Path, monkeypatch):
    """HomeLayout.for_home assembles the central-store paths under DOS_HOME."""
    monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
    h = HomeLayout.for_home()
    base = (tmp_path / "home").resolve()
    assert h.home == base
    assert h.projects_index == base / "projects" / "index.jsonl"
    assert h.decisions_log == base / "decisions.jsonl"
    assert h.home_lock == base / ".home.lock"
    assert not base.exists()  # for_home is pure — never creates
