"""`dos init --with-hooks` — the runtime-binding on-ramp (docs/134 §6 / docs/165).

`dos init` scaffolds `dos.toml`; `--with-hooks` ALSO wires the three SHIPPED DOS
Claude-Code hooks into the workspace's `.claude/settings.json` so a CC launch binds
the verdict to the runtime with no hand-editing:

  Stop        → `dos hook stop`     (refuse to stop on an unverified claim)
  PreToolUse  → `dos hook pretool`  (deny a structurally-refused call before it runs)
  PostToolUse → `dos hook posttool` (re-surface a stalled tool stream, advisory)

The load-bearing disciplines pinned here:
  * the wired commands are the real verbs, in the verified CC settings shape
    ({event: [{"hooks": [{"type": "command", "command": …}]}]});
  * the block is MERGED into an existing settings.json — a user's own hooks/keys
    survive (never clobbered);
  * re-running is idempotent (an already-wired DOS hook is not duplicated);
  * `--force` repairs/replaces an existing DOS hooks block (and rescues a malformed
    settings.json) without touching the user's non-DOS hooks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import dos

_EVENTS = {"Stop", "PreToolUse", "PostToolUse"}


def _cli(*argv: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(Path(dos.__file__).parents[1])}
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv],
        capture_output=True, text=True, env=env,
    )


def _settings(dest: Path) -> dict:
    return json.loads((dest / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _dos_commands(settings: dict, event: str) -> list[str]:
    """Every `dos hook …` command wired under `event`."""
    cmds: list[str] = []
    for group in settings.get("hooks", {}).get(event, []):
        for h in group.get("hooks", []):
            c = h.get("command", "")
            if c.startswith("dos hook "):
                cmds.append(c)
    return cmds


def test_with_hooks_wires_all_three_in_cc_shape(tmp_path: Path):
    dest = tmp_path / "svc"
    proc = _cli("init", "--with-hooks", str(dest))
    assert proc.returncode == 0, proc.stderr
    settings = _settings(dest)
    assert set(settings["hooks"]) >= _EVENTS
    # Each event runs exactly its DOS verb, in the verified matcher-group shape.
    assert _dos_commands(settings, "Stop") == ["dos hook stop --workspace ."]
    assert _dos_commands(settings, "PreToolUse") == ["dos hook pretool --workspace ."]
    assert _dos_commands(settings, "PostToolUse") == ["dos hook posttool --workspace ."]
    # The shape CC parses: event → list of groups, each {"hooks": [{type, command}]}.
    grp = settings["hooks"]["Stop"][0]
    assert grp["hooks"][0]["type"] == "command"


def test_with_hooks_merges_into_existing_settings(tmp_path: Path):
    dest = tmp_path / "svc"
    dest.mkdir()
    claude = dest / ".claude"
    claude.mkdir()
    # A pre-existing settings.json with the user's OWN hook + an unrelated key.
    (claude / "settings.json").write_text(json.dumps({
        "model": "claude-opus-4-8",
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "my-own-linter"}]}],
        },
    }), encoding="utf-8")

    proc = _cli("init", "--with-hooks", str(dest))
    assert proc.returncode == 0, proc.stderr
    settings = _settings(dest)
    # The user's unrelated key survives.
    assert settings["model"] == "claude-opus-4-8"
    # The user's own Stop hook is preserved ALONGSIDE the DOS one (merge, not clobber).
    stop_cmds = [h["command"]
                 for g in settings["hooks"]["Stop"] for h in g["hooks"]]
    assert "my-own-linter" in stop_cmds
    assert "dos hook stop --workspace ." in stop_cmds
    # And the other two DOS events were added.
    assert _dos_commands(settings, "PreToolUse") == ["dos hook pretool --workspace ."]


def test_with_hooks_is_idempotent(tmp_path: Path):
    dest = tmp_path / "svc"
    _cli("init", "--with-hooks", str(dest))
    proc = _cli("init", "--with-hooks", str(dest))
    assert proc.returncode == 0, proc.stderr
    assert "left 3 existing DOS hook(s) untouched" in proc.stdout
    settings = _settings(dest)
    # No duplication — still exactly one DOS command per event after a second run.
    assert len(_dos_commands(settings, "Stop")) == 1
    assert len(_dos_commands(settings, "PreToolUse")) == 1
    assert len(_dos_commands(settings, "PostToolUse")) == 1


def test_with_hooks_works_on_already_initd_workspace(tmp_path: Path):
    dest = tmp_path / "svc"
    _cli("init", str(dest))                      # dos.toml only
    assert (dest / "dos.toml").exists()
    proc = _cli("init", "--with-hooks", str(dest))  # add hooks to existing workspace
    assert proc.returncode == 0, proc.stderr
    assert "wired 3 DOS hook(s)" in proc.stdout
    assert set(_settings(dest)["hooks"]) >= _EVENTS


def test_force_repairs_a_malformed_settings(tmp_path: Path):
    dest = tmp_path / "svc"
    dest.mkdir()
    claude = dest / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{ not valid json", encoding="utf-8")
    # Without --force, a malformed file is a reported error (never silently lost).
    proc = _cli("init", "--with-hooks", str(dest))
    assert proc.returncode == 1
    assert "not valid json" in proc.stderr.lower() or "valid json" in proc.stderr.lower()
    # With --force, it is rescued and the DOS hooks are written.
    proc = _cli("init", "--with-hooks", "--force", str(dest))
    assert proc.returncode == 0, proc.stderr
    assert _dos_commands(_settings(dest), "Stop") == ["dos hook stop --workspace ."]
