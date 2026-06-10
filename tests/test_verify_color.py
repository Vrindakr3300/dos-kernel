"""The provenance-rung tell — `dos verify` colors the SHIPPED/NOT_SHIPPED mark
and the `(via <rung>)` evidence grade for a human at a TTY, while keeping the
piped/JSON output BYTE-IDENTICAL to the byte-faithful `text` renderer.

This is the iconicity move from the make-dos-iconic synthesis ("make `(via
<rung>)` the visual icon"), implemented at the CLI presentation boundary — NOT
in the renderer — precisely so the RND byte-faithfulness contract
(`tests/test_render.py`) is untouched. These tests pin BOTH halves:

  * the pure color helpers (`_color_verdict_line` / `_color_enabled`), and
  * the end-to-end guarantee that a pipe (the machine/grep path) sees no escapes,
    so `dos verify | grep 'via none'` keeps working and CI logs stay clean.

The discipline under test: color is presentation a human opts out of with
`NO_COLOR`; the verdict CONTENT (and exit code) never changes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dos import cli
from dos.oracle import ShipVerdict


ESC = "\033["


def _args(**kw) -> argparse.Namespace:
    """An argparse-shaped namespace with the output flags `_color_enabled` reads."""
    ns = argparse.Namespace()
    ns.output = kw.get("output", None)
    ns.json = kw.get("json", False)
    return ns


# ---------------------------------------------------------------------------
# the pure line-coloring helper — additive only, content unchanged
# ---------------------------------------------------------------------------
def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


def test_color_via_none_is_red_and_content_preserved():
    v = ShipVerdict(plan="docs/99_x", phase="halt", shipped=False, sha=None, source="none")
    plain = f"NOT_SHIPPED {v.plan} {v.phase} (via none)"
    colored = cli._color_verdict_line(plain, v)
    assert ESC in colored                      # it DID color
    assert _strip_ansi(colored) == plain       # but changed no character of content
    assert cli._ANSI["red"] in colored         # the no-evidence tell is red


def test_color_via_grep_is_green():
    v = ShipVerdict(plan="docs/82_x", phase="liveness", shipped=True, sha="80d4f30", source="grep")
    plain = f"SHIPPED {v.plan} {v.phase} {v.sha} (via grep)"
    colored = cli._color_verdict_line(plain, v)
    assert cli._ANSI["green"] in colored
    assert _strip_ansi(colored) == plain
    assert "(via grep)" in _strip_ansi(colored)


def test_color_leaves_via_token_greppable():
    """The literal `(via none)` survives inside the colored span, so a downstream
    `grep 'via none'` on a (forced-color) stream still matches."""
    v = ShipVerdict(plan="p", phase="ph", shipped=False, sha=None, source="none")
    colored = cli._color_verdict_line(f"NOT_SHIPPED p ph (via none)", v)
    assert "(via none)" in colored             # contiguous, not split by escapes


# ---------------------------------------------------------------------------
# _color_enabled — the gate (machine form never colored; NO_COLOR wins)
# ---------------------------------------------------------------------------
def test_color_disabled_for_json_output():
    assert cli._color_enabled(_args(json=True)) is False
    assert cli._color_enabled(_args(output="json")) is False


def test_color_disabled_for_named_renderer():
    assert cli._color_enabled(_args(output="terse")) is False


def test_no_color_beats_force_always(monkeypatch):
    """no-color.org contract: presence of NO_COLOR disables, even over DOS_COLOR=always."""
    monkeypatch.setenv("DOS_COLOR", "always")
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli._color_enabled(_args()) is False


def test_dos_color_always_forces_on(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("DOS_COLOR", "always")
    assert cli._color_enabled(_args()) is True


def test_dos_color_never_forces_off(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("DOS_COLOR", "never")
    assert cli._color_enabled(_args()) is False


# ---------------------------------------------------------------------------
# end-to-end: a PIPE is byte-identical to baseline; exit code is preserved
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _verify(repo: Path, plan: str, phase: str, *, extra_env=None):
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("DOS_COLOR", None)
    env.pop("NO_COLOR", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "verify", "--workspace", str(repo), plan, phase],
        capture_output=True, text=True, env=env,
    )


def test_piped_verify_has_no_escapes_and_preserves_exit(tmp_path):
    """Captured (non-TTY) stdout must carry NO ANSI — the machine/grep path — and
    a NOT_SHIPPED still exits 1."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init")
    proc = _verify(tmp_path, "NOPLAN", "NOPHASE")
    assert ESC not in proc.stdout              # subprocess stdout is a pipe → no color
    assert proc.stdout.strip().startswith("NOT_SHIPPED")
    assert proc.stdout.strip().endswith("(via none)")
    assert proc.returncode == 1                # exit-code contract intact


def test_dos_color_always_emits_escapes_even_when_piped(tmp_path):
    """With DOS_COLOR=always the operator opted into color even off-TTY — the
    escape codes appear, and the exit code is STILL 1 (color never touches it)."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init")
    proc = _verify(tmp_path, "NOPLAN", "NOPHASE", extra_env={"DOS_COLOR": "always"})
    assert ESC in proc.stdout
    assert "(via none)" in proc.stdout         # token still contiguous/greppable
    assert proc.returncode == 1
