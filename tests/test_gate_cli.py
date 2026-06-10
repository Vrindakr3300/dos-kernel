"""`dos gate` — the typed empty-packet verdict as a CLI verb (SKP Phase 1b).

`gate_classify.classify_packet` / `classify_packet_file` already turn a packet's
per-pick dispositions into one typed verdict (LIVE / DRAIN / STALE-STAMP /
BLOCKED / RACE). SKP exposes that as a verb so a generic skill gates its empty
case through `dos` instead of re-implementing the classifier inline. This pins:

  * the verdict IS the exit code, and each typed verdict gets a DISTINCT code
    (LIVE=0, DRAIN=3, STALE-STAMP=4, BLOCKED=5, RACE=6) so a skill's shell can
    branch — and all are disjoint from the contract-error code (2);
  * `--picks-json` classifies an in-memory pick list (the in-skill path);
  * a packet (`.dispositions-<tag>.json` sidecar) classifies in file mode, and a
    sibling `.race-<tag>.json` wins precedence (RACE);
  * a missing / malformed sidecar is a CONTRACT error (exit 2 on stderr), never
    a silent fall-through to DRAIN.
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
        [sys.executable, "-m", "dos.cli", "gate", *argv, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


# ---------------------------------------------------------------------------
# --picks-json (in-memory) mode — the verdict→exit-code map
# ---------------------------------------------------------------------------


def test_gate_live_exits_zero(tmp_path: Path):
    proc = _cli(tmp_path, "--picks-json", json.dumps([{"phase": "FB2", "live": True}]))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("LIVE")


def test_gate_empty_packet_is_drain(tmp_path: Path):
    """A zero-pick packet returns DRAIN (exit 3) — a genuine empty backlog."""
    proc = _cli(tmp_path, "--picks-json", "[]")
    assert proc.returncode == 3, proc.stderr
    assert proc.stdout.startswith("DRAIN")


def test_gate_stale_stamp_exits_four(tmp_path: Path):
    """A pick shipped-in-git but plan-doc-unstamped is STALE-STAMP (exit 4) — the
    false-drain the typed gate exists to distinguish from a real DRAIN."""
    picks = [{"phase": "FB2", "live": False, "drop_reason": "shipped",
              "ship_via": "direct", "plan_doc_stamped": False}]
    proc = _cli(tmp_path, "--picks-json", json.dumps(picks))
    assert proc.returncode == 4, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("STALE-STAMP")


def test_gate_blocked_exits_five(tmp_path: Path):
    """A pick blocked by a sibling soft-claim is BLOCKED (exit 5)."""
    picks = [{"phase": "FB2", "live": False, "drop_reason": "soft_claimed",
              "claim_tag": "sib"}]
    proc = _cli(tmp_path, "--picks-json", json.dumps(picks))
    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("BLOCKED")


def test_gate_json_output(tmp_path: Path):
    """`--json` emits a structured {verdict, reason, evidence} object."""
    proc = _cli(tmp_path, "--picks-json", "[]", "--json")
    assert proc.returncode == 3, proc.stderr
    obj = json.loads(proc.stdout)
    assert obj["verdict"] == "DRAIN"
    assert "reason" in obj and "evidence" in obj


# ---------------------------------------------------------------------------
# contract errors — fail loud, never silent DRAIN
# ---------------------------------------------------------------------------


def test_gate_missing_sidecar_is_contract_error(tmp_path: Path):
    proc = _cli(tmp_path, str(tmp_path / ".dispositions-nope.json"))
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "error:" in proc.stderr


def test_gate_bad_picks_json_is_contract_error(tmp_path: Path):
    proc = _cli(tmp_path, "--picks-json", "{not json")
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "error:" in proc.stderr


def test_gate_picks_json_not_a_list_is_contract_error(tmp_path: Path):
    proc = _cli(tmp_path, "--picks-json", '{"phase": "X"}')  # object, not list
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "must be a JSON list" in proc.stderr


def test_gate_both_inputs_is_contract_error(tmp_path: Path):
    proc = _cli(tmp_path, "somepacket", "--picks-json", "[]")
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "exactly one" in proc.stderr


def test_gate_no_input_is_contract_error(tmp_path: Path):
    proc = _cli(tmp_path)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "exactly one" in proc.stderr


# ---------------------------------------------------------------------------
# file mode — the sidecar envelope + RACE precedence
# ---------------------------------------------------------------------------


def _write_sidecar(repo: Path, tag: str, dispositions: list) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    p = repo / f".dispositions-{tag}.json"
    p.write_text(json.dumps({
        "schema": "oc3-dispositions-v1",
        "tag": tag,
        "dispositions": dispositions,
    }), encoding="utf-8")
    return p


def test_gate_file_mode_classifies_sidecar(tmp_path: Path):
    """A well-formed `.dispositions-<tag>.json` sidecar classifies through file
    mode — a LIVE pick is LIVE (exit 0)."""
    p = _write_sidecar(tmp_path, "t1", [{"phase": "FB2", "live": True}])
    proc = _cli(tmp_path, str(p))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("LIVE")


def test_gate_file_mode_wrong_schema_is_contract_error(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / ".dispositions-bad.json"
    p.write_text(json.dumps({"schema": "wrong", "dispositions": []}), encoding="utf-8")
    proc = _cli(tmp_path, str(p))
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "error:" in proc.stderr


def test_gate_file_mode_race_sidecar_wins(tmp_path: Path):
    """A sibling `.race-<tag>.json` (schema next-up-race-v1) makes the verdict
    RACE (exit 6) regardless of the on-disk dispositions — the wrong-scope packet
    must not be read as a real DRAIN/LIVE."""
    p = _write_sidecar(tmp_path, "t2", [{"phase": "FB2", "live": True}])
    race = tmp_path / ".race-t2.json"
    race.write_text(json.dumps({
        "schema": "next-up-race-v1",
        "blocked_by_pid": 1234,
        "attempted_at": "20260601T000000Z",
        "lock_path": str(tmp_path / ".lock"),
    }), encoding="utf-8")
    proc = _cli(tmp_path, str(p))
    assert proc.returncode == 6, (proc.stdout, proc.stderr)
    assert proc.stdout.startswith("RACE")
