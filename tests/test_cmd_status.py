"""docs/120 Phase 2 — the `dos status <run_id>` boundary-gather (the folded fact).

`dos status <run_id>` gathers the four already-shipped run verdicts at the CLI
boundary — liveness (is it moving?), ledger-verified progress (never the
self-report), the held-lease region (the spine join), and the resume plan (only
once stopped) — and folds them with the PURE `dos.status.status_digest`. It writes
no new verdict logic; these tests pin the GATHER and the fail-closed defaults.

The load-bearing test is `test_json_has_no_claimed_key`: the digest's whole point
(docs/120 §3) is that a peer reading `--json` structurally cannot pick up a
self-report — there is no `claimed` field, by construction. The rest pin the
fail-closed assembly (no ledger → zero progress, no lease → region (), never a
raise), the spine-join region read, the start_sha three-tier source, and the
automatic stopped-predicate that gates the (expensive) resume re-adjudication.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from dos import cli
from dos import config as _config
from dos import intent_ledger as il
from dos import lane_journal as lj


# A run-id whose embedded start-ms decodes (the cmd_status contract guard). Minted
# the way `dos run-id mint` mints; reused across cases so the digest key is stable.
def _rid() -> str:
    from dos import run_id
    return run_id.mint("dispatch").run_id


def _status_args(tmp_path: Path, rid: str, **kw) -> argparse.Namespace:
    base = dict(
        workspace=str(tmp_path), run_id=rid,
        start_sha="", lane="", loop_ts="",
        now_ms=2_000, last_heartbeat_age_ms=None,
        stopped=False, live=False, json=True, output=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _run(tmp_path: Path, rid: str, capsys, **kw) -> tuple[int, dict]:
    """Invoke cmd_status with --json and return (exit_code, parsed_digest)."""
    rc = cli.cmd_status(_status_args(tmp_path, rid, **kw))
    out = capsys.readouterr().out
    return rc, json.loads(out)


# ---------------------------------------------------------------------------
# 1. The load-bearing invariant — the --json shape carries NO `claimed` key.
# ---------------------------------------------------------------------------

def test_json_has_no_claimed_key(tmp_path: Path, capsys):
    """A claimed-but-unverified step is invisible in the digest — the §3 fail-closed proof.

    The agent self-reported `s1` shipped (a `STEP_CLAIMED`) but the kernel verified
    nothing. The digest must show 0 verified AND its --json must expose no `claimed`
    key anywhere — `dos status --json | grep -c claimed` → 0 (docs/142 §5).
    """
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    il.append(rid, il.intent_entry(goal="g", declared_steps=["s1"]), cfg=cfg)
    il.append(rid, il.step_claimed_entry("s1", "deadbeef" * 5), cfg=cfg)  # self-report only

    rc, out = _run(tmp_path, rid, capsys)
    assert out["progress"]["verified_count"] == 0      # the claim did not count
    assert out["progress"]["declared_count"] == 1
    # The structural litmus, at every level of the shape:
    assert "claimed" not in out
    assert "claimed" not in out["progress"]
    assert "deadbeef" not in json.dumps(out)           # the self-report SHA never leaks


# ---------------------------------------------------------------------------
# 2. Fail-closed assembly — no ledger → zero progress, never a raise.
# ---------------------------------------------------------------------------

def test_no_intent_is_fail_closed(tmp_path: Path, capsys):
    """A run-id with no intent ledger yields a valid zero-progress fact, not an error."""
    rid = _rid()
    rc, out = _run(tmp_path, rid, capsys)            # no ledger written at all
    assert out["progress"]["verified_count"] == 0
    assert out["progress"]["declared_count"] == 0
    assert out["resume"] is None                    # no intent → nothing to resume
    assert out["region"] == []                      # no lease
    assert out["run_id"] == rid
    # The exit code is a valid liveness code (never the argparse contract code 2).
    assert rc in (0, 3, 4)


def test_bad_run_id_is_contract_error(tmp_path: Path, capsys):
    """A run-id token whose start-ms cannot decode is the argparse contract error (2)."""
    rc = cli.cmd_status(_status_args(tmp_path, "not-a-real-rid"))
    assert rc == cli._STATUS_EXIT_CONTRACT_ERROR
    assert "not a valid run-id" in capsys.readouterr().err


def test_empty_run_id_is_contract_error(tmp_path: Path, capsys):
    rc = cli.cmd_status(_status_args(tmp_path, ""))
    assert rc == cli._STATUS_EXIT_CONTRACT_ERROR


# ---------------------------------------------------------------------------
# 3. The held-lease region — the spine join (lease.run_id == run_id → tree).
# ---------------------------------------------------------------------------

def test_region_reads_the_runs_held_lease(tmp_path: Path, capsys):
    """A run holding a lane lease whose ACQUIRE stamped its run_id → region == the tree."""
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    # An ACQUIRE that stamps run_id on the nested lease (docs/118 spine join). The
    # lease carries the granted globs under `tree` — the region the digest reports.
    lease = {"lane": "src", "lane_kind": "cluster", "tree": ["src/dos/**"],
             "loop_ts": "L1", "host_id": "h", "pid": 1, "ttl_minutes": 30,
             "run_id": rid}
    lj.append(lj.acquire_entry(lease, run_id=rid), path=cfg.paths.lane_journal)

    rc, out = _run(tmp_path, rid, capsys)
    assert out["region"] == ["src/dos/**"]


def test_region_empty_when_lease_held_by_a_different_run(tmp_path: Path, capsys):
    """A lease stamped with ANOTHER run's id does not match → region () (fail-closed)."""
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    other = _rid()
    lease = {"lane": "src", "lane_kind": "cluster", "tree": ["src/**"],
             "loop_ts": "L1", "host_id": "h", "pid": 1, "ttl_minutes": 30,
             "run_id": other}
    lj.append(lj.acquire_entry(lease, run_id=other), path=cfg.paths.lane_journal)

    rc, out = _run(tmp_path, rid, capsys)
    assert out["region"] == []                       # not this run's lease


def test_region_empty_for_old_acquire_without_run_id(tmp_path: Path, capsys):
    """An OLD ACQUIRE that never stamped run_id won't match → region () (backward-compat).

    The `.get("run_id")` filter (not bracket indexing) means a pre-spine-join lease
    simply doesn't match — a valid "not attributable" fact, never a KeyError.
    """
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    lease = {"lane": "src", "lane_kind": "cluster", "tree": ["src/**"],
             "loop_ts": "L1", "host_id": "h", "pid": 1, "ttl_minutes": 30}  # no run_id
    lj.append(lj.acquire_entry(lease), path=cfg.paths.lane_journal)

    rc, out = _run(tmp_path, rid, capsys)
    assert out["region"] == []


# ---------------------------------------------------------------------------
# 4. The resume read — None while live, the verdict once stopped (the predicate).
# ---------------------------------------------------------------------------

def test_live_run_has_no_resume(tmp_path: Path, capsys):
    """An ADVANCING run (committed since start) is LIVE → resume stays null.

    --now-ms is close to the run-start so a fresh-enough heartbeat / commit keeps it
    out of STALLED; with no SUSPEND in the ledger the run is live and the expensive
    ancestry re-adjudication is skipped.
    """
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    il.append(rid, il.intent_entry(goal="g", start_sha="START",
                                   declared_steps=["s1"]), cfg=cfg)
    # Force liveness ADVANCING via a fresh heartbeat override + force --live to be
    # explicit about the predicate (belt-and-suspenders against clock flakiness).
    rc, out = _run(tmp_path, rid, capsys, last_heartbeat_age_ms=0, live=True)
    assert out["resume"] is None


def test_suspended_run_yields_a_resume_verdict(tmp_path: Path, capsys):
    """A run whose ledger SUSPENDed is STOPPED → the resume verdict is folded in.

    `LedgerState.suspended` (the voluntary `dos halt --resumable` pause) is the
    automatic stopped-predicate; once stopped, `gather_ancestry` + `resume_plan`
    run and the digest carries a non-null resume dict.
    """
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    il.append(rid, il.intent_entry(goal="finish the thing", start_sha="START"),
              cfg=cfg)
    il.append(rid, il.suspend_entry(reason="park"), cfg=cfg)

    rc, out = _run(tmp_path, rid, capsys)
    assert out["resume"] is not None
    assert out["resume"]["verdict"] in ("RESUMABLE", "COMPLETE",
                                        "DIVERGED", "UNRESUMABLE")


def test_stopped_flag_forces_the_resume_read(tmp_path: Path, capsys):
    """`--stopped` overrides the automatic predicate and computes resume on demand."""
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    il.append(rid, il.intent_entry(goal="g", start_sha="START"), cfg=cfg)
    # Without --stopped and with a fresh heartbeat this would be live (resume null);
    # --stopped forces the read.
    rc, out = _run(tmp_path, rid, capsys, last_heartbeat_age_ms=0, stopped=True)
    assert out["resume"] is not None


# ---------------------------------------------------------------------------
# 5. start_sha source + the human renderer.
# ---------------------------------------------------------------------------

def test_start_sha_falls_back_to_ledger(tmp_path: Path, capsys):
    """With no --start-sha, the run's declared start_sha off the ledger is used.

    We can't easily assert the git delta in a non-repo tmp dir, but we CAN assert the
    gather doesn't crash and produces a valid digest when start_sha comes from the
    ledger rather than the flag (the tier-2 fallback path executes).
    """
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    il.append(rid, il.intent_entry(goal="g", start_sha="LEDGERSHA"), cfg=cfg)
    rc, out = _run(tmp_path, rid, capsys)            # no --start-sha passed
    assert out["run_id"] == rid
    assert "liveness" in out


def test_human_output_renders_the_four_axes(tmp_path: Path, capsys):
    """The text renderer prints the four folded axes and never the word 'claimed'."""
    cfg = _config.default_config(tmp_path)
    rid = _rid()
    il.append(rid, il.intent_entry(goal="g", declared_steps=["s1"]), cfg=cfg)
    il.append(rid, il.step_claimed_entry("s1", "c1"), cfg=cfg)

    cli.cmd_status(_status_args(tmp_path, rid, json=False))
    out = capsys.readouterr().out
    assert "progress" in out
    assert "region" in out
    assert "resume" in out
    assert "claimed" not in out                      # not even in the human text


# ---------------------------------------------------------------------------
# 6. End-to-end via the real CLI dispatcher (subprocess) — the grep proof.
# ---------------------------------------------------------------------------

def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _rev(cwd) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
def test_status_cli_end_to_end_real_repo(tmp_path: Path):
    """The full `dos status` verb over a real repo: a verified step, a held lease, --json.

    Proves the boundary-gather wires end-to-end through `python -m dos.cli status` and
    that the A2A `--json` shape carries ZERO `claimed` keys (docs/142 §5).
    """
    from dos import run_id as _run_id
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    _git(["add", "a.txt"], repo)
    _git(["commit", "-q", "-m", "start"], repo)
    start = _rev(repo)
    (repo / "b.txt").write_text("y\n", encoding="utf-8")
    _git(["add", "b.txt"], repo)
    _git(["commit", "-q", "-m", "s1 real"], repo)
    s1_sha = _rev(repo)

    cfg = _config.default_config(repo)
    rid = _run_id.mint("dispatch").run_id
    p = il.ledger_path_for(rid, cfg=cfg)
    il.append(rid, il.intent_entry(goal="g", start_sha=start,
                                   declared_steps=["s1", "s2"]), path=p)
    il.append(rid, il.step_claimed_entry("s1", s1_sha), path=p)
    il.append(rid, il.step_verified_entry("s1", s1_sha, via="file-path"), path=p)
    il.append(rid, il.step_claimed_entry("s2", "deadbeef"), path=p)  # claimed, never landed

    # A held lane lease stamped with this run's id (the spine join).
    lease = {"lane": "src", "lane_kind": "cluster", "tree": ["src/dos/**"],
             "loop_ts": "L1", "host_id": "h", "pid": 1, "ttl_minutes": 30,
             "run_id": rid}
    lj.append(lj.acquire_entry(lease, run_id=rid), path=cfg.paths.lane_journal)

    proc = subprocess.run(
        ["python", "-m", "dos.cli", "status", rid, "--workspace", str(repo), "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode in (0, 3, 4), proc.stderr      # a valid liveness code
    out = json.loads(proc.stdout)
    assert out["run_id"] == rid
    assert out["progress"]["verified_count"] == 1         # s1 verified
    assert out["progress"]["declared_count"] == 2
    assert out["region"] == ["src/dos/**"]                # the run's held lease
    # The load-bearing grep proof: no `claimed` key anywhere in the A2A shape.
    assert proc.stdout.count("claimed") == 0
