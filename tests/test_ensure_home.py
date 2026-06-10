"""Auto-create-on-first-write — `ensure_project_home` lazily scaffolds `.dos/`,
read-only syscalls write nothing, and the courtesy line fires exactly once
(docs/75_state-home-plan.md, Phase 2).

The headline safety property is `TestReadOnlySyscallsWriteNothing`: a stranger
running `dos verify`/`man`/`doctor`/`decisions`/`judge` against a foreign repo
gets no `.dos/` dir and no `~/.dos` row. Every test redirects DOS_HOME into
`tmp_path` so the real `~/.dos` is never touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import home
from dos.config import default_config
# `project_id_for` lives in dos.home (it is home-tier, not config-tier).
from dos.home import project_id_for


@pytest.fixture
def fixed_clock():
    """A frozen injectable clock so created_at/last_seen are deterministic."""
    return lambda: 1_780_000_000_000  # a fixed epoch-ms


# ---------------------------------------------------------------------------
# project_id — deterministic, path-derived (deferred here from Phase 1 since the
# function lives in dos.home).
# ---------------------------------------------------------------------------


class TestProjectId:
    def test_is_deterministic(self, tmp_path: Path):
        assert project_id_for(tmp_path) == project_id_for(tmp_path)

    def test_differs_by_root(self, tmp_path: Path):
        assert project_id_for(tmp_path / "a") != project_id_for(tmp_path / "b")

    def test_normalizes_root(self, tmp_path: Path):
        # A non-normalized path resolves to the same id as its realpath.
        messy = tmp_path / "x" / ".." / "x"
        assert project_id_for(messy) == project_id_for(tmp_path / "x")

    def test_is_16_hex_chars(self, tmp_path: Path):
        pid = project_id_for(tmp_path)
        assert len(pid) == 16
        int(pid, 16)  # parses as hex


# ---------------------------------------------------------------------------
# Lazy create — the first persist scaffolds .dos/ + card + gitignore.
# ---------------------------------------------------------------------------


class TestLazyCreate:
    def test_first_write_creates_dot_dos(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
        cfg = default_config(tmp_path)
        assert not (tmp_path / ".dos").exists()
        home.ensure_project_home(cfg)
        assert (tmp_path / ".dos").is_dir()

    def test_project_json_is_identity_card(self, tmp_path: Path, monkeypatch, fixed_clock):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
        cfg = default_config(tmp_path)
        home.ensure_project_home(cfg, clock=fixed_clock)
        card = json.loads((tmp_path / ".dos" / "project.json").read_text(encoding="utf-8"))
        assert card["project_id"] == project_id_for(tmp_path)
        assert card["created_at"]
        assert card["dos_version"]

    def test_gitignore_written_with_star(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
        cfg = default_config(tmp_path)
        home.ensure_project_home(cfg)
        gi = (tmp_path / ".dos" / ".gitignore").read_text(encoding="utf-8")
        assert "*" in gi
        assert "!.gitignore" in gi

    def test_idempotent_preserves_created_at(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
        cfg = default_config(tmp_path)
        home.ensure_project_home(cfg, clock=lambda: 1_000_000_000_000)
        card1 = json.loads((tmp_path / ".dos" / "project.json").read_text())
        home.ensure_project_home(cfg, clock=lambda: 2_000_000_000_000)
        card2 = json.loads((tmp_path / ".dos" / "project.json").read_text())
        assert card1["created_at"] == card2["created_at"]  # minted once, preserved
        assert card1["project_id"] == card2["project_id"]

    def test_gitignore_not_overwritten(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
        cfg = default_config(tmp_path)
        (tmp_path / ".dos").mkdir()
        (tmp_path / ".dos" / ".gitignore").write_text("CUSTOM\n", encoding="utf-8")
        home.ensure_project_home(cfg)
        assert (tmp_path / ".dos" / ".gitignore").read_text() == "CUSTOM\n"


# ---------------------------------------------------------------------------
# The headline safety property — read-only syscalls write NOTHING.
# ---------------------------------------------------------------------------


def _plain_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for args in (("init",), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t"),
                 ("commit", "--allow-empty", "-m", "init")):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, text=True)


def _run_cli(repo: Path, home_dir: Path, *cli_args: str):
    import os
    env = dict(os.environ)
    env["DISPATCH_HOME"] = str(home_dir)
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *cli_args, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


class TestReadOnlySyscallsWriteNothing:
    """Each read-only verb leaves no `.dos/` and no central index behind."""

    @pytest.mark.parametrize("cli_args", [
        ("verify", "SOMEPLAN", "1"),
        ("doctor",),
        ("decisions", "--no-tui"),
        ("man", "wedge"),
    ])
    def test_read_only_verb_writes_nothing(self, tmp_path: Path, cli_args):
        repo = tmp_path / "repo"
        home_dir = tmp_path / "home"
        _plain_repo(repo)
        proc = _run_cli(repo, home_dir, *cli_args)
        # The command runs (exit code varies — verify exits 1 for not-shipped);
        # what matters is it created no state.
        assert not (repo / ".dos").exists(), f"{cli_args} created .dos/: {proc.stderr}"
        assert not (home_dir / "projects").exists(), f"{cli_args} wrote central index"

    def test_judge_is_read_only(self, tmp_path: Path):
        """`dos judge` stays read-only (the resolved §5.7 contradiction)."""
        repo = tmp_path / "repo"
        home_dir = tmp_path / "home"
        _plain_repo(repo)
        _run_cli(repo, home_dir, "judge", "wedge", "20260531T010000Z")
        assert not (repo / ".dos").exists()
        assert not (home_dir / "projects").exists()


# ---------------------------------------------------------------------------
# The courtesy line — exactly once on first persist, never on repeat.
# ---------------------------------------------------------------------------


class TestCourtesyLine:
    def test_first_persist_prints_one_courtesy_line(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
        cfg = default_config(tmp_path)
        home.ensure_project_home(cfg)
        err = capsys.readouterr().err
        assert err.count("created .dos/") == 1

    def test_courtesy_line_not_repeated(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.setenv("DISPATCH_HOME", str(tmp_path / "home"))
        cfg = default_config(tmp_path)
        home.ensure_project_home(cfg)
        capsys.readouterr()  # drain
        home.ensure_project_home(cfg)
        err = capsys.readouterr().err
        assert "created .dos/" not in err


# ---------------------------------------------------------------------------
# The persisting CLI path — `dos lease acquire` creates .dos/.
# ---------------------------------------------------------------------------


def test_lease_acquire_creates_dot_dos(tmp_path: Path):
    import os
    repo = tmp_path / "repo"
    home_dir = tmp_path / "home"
    _plain_repo(repo)
    # `--workspace` is a flag on the `lease` subparser, so it goes right after
    # `lease` (before the acquire sub-subcommand + its positional owner).
    env = dict(os.environ)
    env["DISPATCH_HOME"] = str(home_dir)
    proc = subprocess.run(
        [sys.executable, "-m", "dos.cli", "lease", "--workspace", str(repo),
         "acquire", "test-owner"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert (repo / ".dos").is_dir()
    assert (repo / ".dos" / "leases").is_dir() or (repo / ".dos" / "project.json").exists()
    assert (repo / ".dos" / "project.json").exists()
