"""The `dos doctor --check` state-file health rail (the CLI-boundary wiring).

`test_state_health.py` pins the pure `classify_state_file` fold; THIS file pins the
operator-facing surface — that `dos doctor --check` actually gathers the workspace's
execution-state file (at the path `[paths].execution_state` declares) and surfaces a
bloat finding + a non-zero exit, and stays quiet on a healthy/absent file. Same
subprocess harness as `test_stamp_doctor`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo")


def _doctor(repo: Path, *extra: str):
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "doctor", "--workspace", str(repo), *extra],
        capture_output=True, text=True, env=env,
    )


def _write_state(repo: Path, *, recently_completed: int, abandoned: int, pad_bytes: int = 0) -> Path:
    """Write a minimal execution-state.yaml with the named cold-section row counts."""
    state_dir = repo / "docs" / "_plans"
    state_dir.mkdir(parents=True, exist_ok=True)
    lines = ["schema_version: 2", "plans: []", "active_work: []", "recently_completed:"]
    for i in range(recently_completed):
        lines.append(f"- id: rc-{i}")
        lines.append(f"  completed_at: '2026-06-0{(i % 9) + 1}T00:00Z'")
    lines.append("abandoned:")
    for i in range(abandoned):
        lines.append(f"- id: ab-{i}")
    if pad_bytes:
        lines.append("# " + ("x" * pad_bytes))
    p = state_dir / "execution-state.yaml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _declare_state_path(repo: Path) -> None:
    (repo / "dos.toml").write_text(
        'workspace = "."\n[paths]\nexecution_state = "docs/_plans/execution-state.yaml"\n',
        encoding="utf-8",
    )


def test_check_flags_bloated_state_file(tmp_path):
    _repo(tmp_path)
    _declare_state_path(tmp_path)
    # Over the default 150-row cold-section cap AND over 200 KB total.
    _write_state(tmp_path, recently_completed=227, abandoned=207, pad_bytes=210_000)
    proc = _doctor(tmp_path, "--check")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    # `--check` findings print to STDERR (the cmd_doctor convention); the report
    # header (incl. the resolved path) prints to STDOUT.
    assert "execution-state.yaml" in proc.stdout
    findings = proc.stderr
    assert "recently_completed" in findings and "227 rows" in findings
    assert "abandoned" in findings and "207 rows" in findings
    assert "over the size budget" in findings


def test_check_quiet_on_healthy_state_file(tmp_path):
    _repo(tmp_path)
    _declare_state_path(tmp_path)
    # Small file, cold sections well under the cap.
    _write_state(tmp_path, recently_completed=10, abandoned=5)
    proc = _doctor(tmp_path, "--check")
    # No state-health finding (other rails may exist, but not ours).
    assert "over the size budget" not in proc.stderr
    assert "rows — over the per-section cap" not in proc.stderr


def test_check_quiet_when_state_file_absent(tmp_path):
    _repo(tmp_path)
    _declare_state_path(tmp_path)  # declared, but the file does not exist
    proc = _doctor(tmp_path, "--check")
    assert "over the size budget" not in proc.stderr
    assert "rows — over the per-section cap" not in proc.stderr


def test_json_includes_state_findings_under_check(tmp_path):
    _repo(tmp_path)
    _declare_state_path(tmp_path)
    _write_state(tmp_path, recently_completed=227, abandoned=207, pad_bytes=210_000)
    proc = _doctor(tmp_path, "--check", "--json")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    import json

    report = json.loads(proc.stdout)
    findings = report.get("findings", [])
    assert any("execution-state.yaml" in f and "over the size budget" in f for f in findings)
