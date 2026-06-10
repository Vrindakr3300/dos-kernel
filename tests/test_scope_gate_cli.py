"""`dos scope-gate` — the binding pre-effect scope gate as a CLI verb (docs/102 §5).

`scope.gate` decides whether a PROPOSED write may land inside the lane it claims;
this verb exposes it so an edit-time hook / a single-writer commit broker can
branch on the decision (refuse the patch) BEFORE applying it. This pins the
WIRING the pure-classifier tests (`test_scope_gate.py`) can't see:

  * the decision IS the exit code, distinct per underlying verdict (ALLOW=0,
    SCOPE_CREEP=5, WRONG_TARGET=6 — matching `verdict_cli._SCOPE_EXIT`), all
    disjoint from the contract-error code (2);
  * `--file` supplies the proposed write-set without git (the broker path);
  * the ASYMMETRIC lane fallback: no `--lane` → generic `**/*` ALLOW (no-plan
    floor); a named-but-UNDECLARED lane → REFUSE (unknown blast radius), NOT a
    silent generic pass — the under-declaration hole the gate exists to close;
  * a declared lane resolves to its tree (ALLOW in-tree, REFUSE on overrun).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import dos


def _cli(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(dos.__file__).parents[1])}
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "scope-gate", *argv, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


def _workspace_with_lane(repo: Path) -> Path:
    """A workspace whose `[lanes.trees]` declares one narrow lane `apply`."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "dos.toml").write_text(
        "[lanes]\n"
        'concurrent = ["apply", "main"]\n'
        'exclusive = ["global"]\n'
        'autopick = ["apply", "main"]\n'
        "\n"
        "[lanes.trees]\n"
        'apply = ["agents/apply_"]\n'
        'main = ["**/*"]\n',
        encoding="utf-8",
    )
    return repo


# ---------------------------------------------------------------------------
# 1. The decision → exit-code map (the verb's whole contract).
# ---------------------------------------------------------------------------


def test_no_lane_generic_floor_allows(tmp_path: Path):
    """No `--lane` → the generic `**/*` tree → ALLOW (exit 0): a workspace that
    named no lane has no scope to bind against (the no-plan floor)."""
    proc = _cli(tmp_path, "--file", "agents/apply_x.py", "--file", "docs/foo.md")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("ALLOW")


def test_named_undeclared_lane_refuses_wrong_target(tmp_path: Path):
    """A NAMED but UNDECLARED lane → REFUSE WRONG_TARGET (exit 6), NOT a silent
    generic pass. This is the core hole the binding gate closes: a typo'd / stale
    lane name must not let an arbitrary write land."""
    proc = _cli(tmp_path, "--lane", "no-such-lane", "--file", "agents/apply_x.py")
    assert proc.returncode == 6, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("REFUSE")
    assert "unknown blast radius" in proc.stdout or "no tree" in proc.stdout


def test_declared_lane_in_tree_allows(tmp_path: Path):
    """A declared lane + a write wholly inside its tree → ALLOW (exit 0)."""
    repo = _workspace_with_lane(tmp_path)
    proc = _cli(repo, "--lane", "apply", "--file", "agents/apply_tailor.py")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("ALLOW")


def test_declared_lane_overrun_refuses_scope_creep(tmp_path: Path):
    """A declared lane + a write that touches its tree AND escapes it → REFUSE
    SCOPE_CREEP (exit 5): the under-declared overrun, refused before it lands."""
    repo = _workspace_with_lane(tmp_path)
    proc = _cli(repo, "--lane", "apply",
                "--file", "agents/apply_tailor.py",
                "--file", "agents/discovery.py")
    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("REFUSE")
    assert "SCOPE_CREEP" in proc.stdout


def test_declared_lane_total_miss_refuses_wrong_target(tmp_path: Path):
    """A declared lane + a write entirely outside it → REFUSE WRONG_TARGET (exit 6)."""
    repo = _workspace_with_lane(tmp_path)
    proc = _cli(repo, "--lane", "apply", "--file", "agents/discovery.py")
    assert proc.returncode == 6, (proc.stdout, proc.stderr)
    assert "WRONG_TARGET" in proc.stdout


def test_empty_footprint_allows(tmp_path: Path):
    """No proposed files at all (an empty range / no --file) → ALLOW (a write of
    nothing escapes nothing). With no git diff and no --file the gather is empty."""
    repo = _workspace_with_lane(tmp_path)
    proc = _cli(repo, "--lane", "apply", "--base", "HEAD", "--head", "HEAD")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("ALLOW")


# ---------------------------------------------------------------------------
# 2. The --json machine surface.
# ---------------------------------------------------------------------------


def test_json_output_carries_decision_and_verdict(tmp_path: Path):
    repo = _workspace_with_lane(tmp_path)
    proc = _cli(repo, "--lane", "apply",
                "--file", "agents/apply_tailor.py",
                "--file", "agents/discovery.py", "--json")
    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    obj = json.loads(proc.stdout)
    assert obj["allowed"] is False
    assert obj["verdict"] == "SCOPE_CREEP"
    assert "agents/discovery.py" in obj["refused_files"]
    # the nested full scope verdict travels too (decision + grade in one object).
    assert obj["scope"]["verdict"] == "SCOPE_CREEP"
