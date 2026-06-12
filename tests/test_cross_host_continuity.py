"""docs/313 P2 — one repo, one referee: state written via one host surface
adjudicates every other host surface.

The platform-agnosticism claim that matters operationally is not "DOS runs
under N hosts" but "N hosts against one repo share ONE referee with ONE
memory" — because all shared state is repo-resident (`dos.toml` policy in,
`.dos/` fossils through, git evidence out; docs/DOT_DOS.md), a host holds
zero state and cannot have a private view of the world.

Pinned here, end-to-end through the REAL CLI surfaces (subprocesses, no
monkeypatching — the claim is about surfaces, so the surfaces are what run):

  1. a lane lease durably taken via the CLI verb (`dos lease-lane acquire`,
     the surface a shelling host wraps) DENIES the colliding Write arriving
     through the HOOK surface (`dos hook pretool`, the surface Claude Code /
     Gemini fire) — same WAL, one arbiter;
  2. the deny is dialect-independent: the SAME event through `--dialect
     claude-code` and `--dialect gemini` both refuse, each in its own host's
     envelope (the decided-once/rendered-per-host seam, docs/217 — its suite
     pins the rendering; THIS file pins the shared-state half);
  3. a disjoint Write passes through both dialects (the deny is the
     collision, not noise);
  4. both hook calls' observation rows accumulate in the ONE per-repo log
     (`.dos/metrics/observations.jsonl`), beside the WAL row the CLI verb
     wrote — one `.dos/`, every surface's memory.

Fixture discipline: a throwaway repo per test (`test_verify_no_plan.py`
style); this suite never touches the kernel repo's own live `.dos/`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TWO_LANES = """\
[lanes]
concurrent = ["alpha", "beta"]
autopick   = ["alpha", "beta"]

[lanes.trees]
alpha = ["alpha/**"]
beta  = ["beta/**"]
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "dos.toml").write_text(_TWO_LANES, encoding="utf-8")
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(argv, cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _lease(repo: Path, lane: str, owner: str) -> None:
    """Surface A — the CLI verb a shelling host wraps. Writes the durable WAL."""
    proc = subprocess.run(
        [sys.executable, "-m", "dos.cli", "lease-lane", "--workspace", str(repo),
         "acquire", "--lane", lane, "--owner", owner],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


def _hook_pretool(repo: Path, file_path: str, *, dialect: str,
                  session: str) -> subprocess.CompletedProcess:
    """Surface B — the hook path a runtime fires, in that runtime's dialect."""
    event = {
        "tool_name": "Write",
        "session_id": session,
        "cwd": str(repo),
        "tool_input": {"file_path": str(repo / file_path)},
    }
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "hook", "pretool",
         "--workspace", str(repo), "--dialect", dialect],
        input=json.dumps(event), capture_output=True, text=True,
    )


def test_cli_lease_denies_hook_write_claude_code(repo: Path):
    """The cross-host moment: a lease one surface wrote refuses another surface's
    colliding call — in the envelope real Claude Code enforces."""
    _lease(repo, "alpha", "host-a")

    proc = _hook_pretool(repo, "alpha/file.py", dialect="claude-code", session="S-b")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    hso = payload["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert "alpha" in hso["permissionDecisionReason"]


def test_same_event_denies_in_gemini_envelope_too(repo: Path):
    """Dialect-independence of the DECISION: the same colliding event through the
    gemini dialect also refuses — rendered as the `continue: false` envelope
    Gemini's BeforeTool gate actually enforces (docs/268), not CC's shape."""
    _lease(repo, "alpha", "host-a")

    proc = _hook_pretool(repo, "alpha/file.py", dialect="gemini", session="S-c")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["continue"] is False
    assert "alpha" in payload["stopReason"]


def test_disjoint_write_passes_both_dialects(repo: Path):
    """The deny above is the collision, not hook noise: a Write into the FREE
    lane's tree passes through silently (the documented passthrough contract —
    empty stdout, exit 0) under both dialects."""
    _lease(repo, "alpha", "host-a")

    for dialect in ("claude-code", "gemini"):
        proc = _hook_pretool(repo, "beta/file.py", dialect=dialect, session="S-d")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "", (dialect, proc.stdout)


def test_one_dot_dos_accumulates_every_surface(repo: Path):
    """One `.dos/`, every surface's memory: the WAL row the CLI verb wrote and
    the observation rows BOTH hook dialects wrote land in the same per-repo
    files — the shared substrate the throughline page names."""
    _lease(repo, "alpha", "host-a")
    _hook_pretool(repo, "alpha/file.py", dialect="claude-code", session="S-cc")
    _hook_pretool(repo, "alpha/file.py", dialect="gemini", session="S-gm")

    journal = repo / ".dos" / "lane-journal.jsonl"
    assert journal.exists()
    journal_rows = [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r.get("lane") == "alpha" for r in journal_rows)

    obs = repo / ".dos" / "metrics" / "observations.jsonl"
    assert obs.exists()
    obs_rows = [json.loads(l) for l in obs.read_text(encoding="utf-8").splitlines() if l.strip()]
    denies = [r for r in obs_rows if r.get("verb") == "pretool" and r.get("outcome") == "deny"]
    assert {r.get("dialect") for r in denies} >= {"claude-code", "gemini"}, obs_rows
