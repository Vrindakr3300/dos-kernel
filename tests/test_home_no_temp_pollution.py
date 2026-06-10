"""The machine-global index keeps throwaway workspaces out (2026-06-10 audit).

The central project index (`<DOS_HOME>/projects/index.jsonl`) is append-only
with no retention, and `ensure_project_home` runs on every persisting syscall —
so before this guard, any `dos` run inside a tmp workspace with no home
override registered that workspace into the OPERATOR'S REAL index forever (the
live index was 87% dead pytest tmp dirs: 3796 of 4368 rows). Same disease the
docs/139 unbounded-growth audit fixed on the lane journal, one shared file up.

Two layers, each pinned here:

  * the IN-KERNEL backstop — `ensure_project_home` skips CENTRAL registration
    (never the per-project `.dos/` scaffold) when the workspace root lives
    under the OS temp dir AND no home override (`home=` arg / `DISPATCH_HOME`)
    is in force;
  * the SUITE fixture — conftest pins `DISPATCH_HOME` to a session tmp dir, so
    every test (and every `dos` subprocess a test shells) writes its central
    rows under tmp regardless.

The skip-branch wiring test monkeypatches `ensure_dos_home` to a tripwire
BEFORE exercising the guard (the sacrificial-probe discipline): if the guard
regresses, the test fails on the tripwire — the real `%APPDATA%/dos` is
unreachable either way.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dos import home
from dos.config import ENV_DOS_HOME, default_config
from dos.home import _is_temp_root


# ---------------------------------------------------------------------------
# The pure containment predicate.
# ---------------------------------------------------------------------------


class TestIsTempRoot:
    def test_true_inside_injected_tempdir(self, tmp_path: Path):
        assert _is_temp_root(tmp_path / "ws", tempdir=tmp_path)

    def test_true_for_tempdir_itself(self, tmp_path: Path):
        assert _is_temp_root(tmp_path, tempdir=tmp_path)

    def test_false_outside_tempdir(self, tmp_path: Path):
        outside = tmp_path / "elsewhere"
        assert not _is_temp_root(outside, tempdir=tmp_path / "tmp")

    def test_false_for_sibling_name_prefix(self, tmp_path: Path):
        # `C:\tmp-extra` is NOT under `C:\tmp` — path containment, not a
        # string-prefix match.
        base = tmp_path / "tmp"
        sibling = tmp_path / "tmp-extra" / "ws"
        assert not _is_temp_root(sibling, tempdir=base)

    def test_default_base_is_the_os_tempdir(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(home.tempfile, "gettempdir", lambda: str(tmp_path))
        assert _is_temp_root(tmp_path / "ws")
        assert not _is_temp_root(Path(os.getcwd()))


# ---------------------------------------------------------------------------
# The ensure_project_home wiring — skip central, keep the local scaffold.
# ---------------------------------------------------------------------------


class TestTempRootSkipsCentralRegistration:
    def test_temp_root_with_no_override_never_touches_the_home(
        self, tmp_path: Path, monkeypatch
    ):
        """The guard branch: temp root + no `home=` + no env ⇒ no central write.

        `ensure_dos_home` is replaced with a tripwire FIRST, so a regressed
        guard fails HERE, on a fake, never against the operator's real home.
        """
        monkeypatch.delenv(ENV_DOS_HOME, raising=False)
        monkeypatch.setattr(home.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(
            home, "ensure_dos_home",
            lambda *a, **k: pytest.fail(
                "central registration attempted for a temp-rooted workspace"
            ),
        )
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = default_config(ws)

        dot_dos = home.ensure_project_home(cfg)

        # The per-project scaffold is untouched by the guard: card + gitignore land.
        assert dot_dos.is_dir()
        assert (ws / ".dos" / "project.json").is_file()
        assert (ws / ".dos" / ".gitignore").is_file()

    def test_temp_root_with_env_override_still_registers(
        self, tmp_path: Path, monkeypatch
    ):
        """The hermetic-test idiom keeps working: a redirected home gets the row."""
        redirected = tmp_path / "redirected-home"
        monkeypatch.setenv(ENV_DOS_HOME, str(redirected))
        monkeypatch.setattr(home.tempfile, "gettempdir", lambda: str(tmp_path))
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = default_config(ws)

        home.ensure_project_home(cfg)

        rows = home.read_jsonl(redirected / "projects" / "index.jsonl")
        assert any(r.get("root") == str(ws.resolve()) for r in rows)

    def test_temp_root_with_explicit_home_arg_still_registers(
        self, tmp_path: Path, monkeypatch
    ):
        """An explicit `home=` arg wins over the guard, same as the env override."""
        monkeypatch.delenv(ENV_DOS_HOME, raising=False)
        monkeypatch.setattr(home.tempfile, "gettempdir", lambda: str(tmp_path))
        explicit = tmp_path / "explicit-home"
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = default_config(ws)

        home.ensure_project_home(cfg, home=explicit)

        rows = home.read_jsonl(explicit / "projects" / "index.jsonl")
        assert any(r.get("root") == str(ws.resolve()) for r in rows)

    def test_non_temp_root_with_no_override_registers(
        self, tmp_path: Path, monkeypatch
    ):
        """A REAL (non-temp) workspace still registers when no override is set —
        the guard narrows to temp roots only, it does not turn registration off.
        The 'real default home' is faked via `ensure_dos_home` interception so
        the test never writes outside tmp."""
        monkeypatch.delenv(ENV_DOS_HOME, raising=False)
        # The OS temp dir is somewhere the workspace is NOT.
        monkeypatch.setattr(
            home.tempfile, "gettempdir", lambda: str(tmp_path / "elsewhere-tmp")
        )
        fake_default_home = tmp_path / "fake-default-home"
        real_ensure = home.ensure_dos_home
        monkeypatch.setattr(
            home, "ensure_dos_home", lambda *a, **k: real_ensure(fake_default_home)
        )
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = default_config(ws)

        home.ensure_project_home(cfg)

        rows = home.read_jsonl(fake_default_home / "projects" / "index.jsonl")
        assert any(r.get("root") == str(ws.resolve()) for r in rows)


# ---------------------------------------------------------------------------
# The suite fixture — the session-level redirect is actually in force.
# ---------------------------------------------------------------------------


def test_suite_pins_dispatch_home_under_tmp():
    """The conftest session fixture redirected the home for this whole run.

    This is the witness that the suite is hermetic at the home tier: if the
    fixture is removed (or its env-var name drifts off `config.ENV_DOS_HOME`
    again), this fails immediately rather than the leak resurfacing as silent
    growth of the operator's real index.
    """
    env = os.environ.get(ENV_DOS_HOME)
    assert env, "the suite-level DISPATCH_HOME redirect is not set"
    assert "dos-suite-home" in env
