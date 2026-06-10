"""LVN Phase 1 — the liveness verdict + the pure classifier (docs/82).

`liveness.classify` is the 4th distrust syscall's kernel: a PURE verdict over
already-gathered ground-truth evidence (commit delta + heartbeat age), the
temporal sibling of `verify`. These tests pin the Phase-1 ladder on FROZEN
evidence (no live git, no clock) and the no-plan rail through the real CLI.

The verdict ladder under test (the Phase-1 resolution of the two windows —
`spin_ms` is the alive/dead heartbeat-freshness bound, `grace_ms` is the minimum
run-age before an alive-but-idle run is accused of SPINNING):

  1. ADVANCING — ≥1 commit (or journal event) since start; OR a fresh heartbeat
                 on a run younger than grace_ms (alive, too young to judge).
  2. SPINNING  — 0 forward delta, heartbeat fresh (≤ spin_ms), run-age ≥ grace_ms.
  3. STALLED   — 0 forward delta, heartbeat stale (> spin_ms) or absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import liveness
from dos.liveness import Liveness, LivenessPolicy, ProgressEvidence, classify

# A policy with explicit windows so the tests read concretely (5 min spin / 10
# min grace). Ages below are in ms.
_MIN = 60 * 1000
_POLICY = LivenessPolicy(grace_ms=10 * _MIN, spin_ms=5 * _MIN)

# A canonical run-start / now pair: the run began 40 minutes ago. 40 min ≥ the
# 10-min grace, so an alive-but-idle run with this age is OLD ENOUGH to be judged
# spinning (it is not shielded by the young-and-alive guard).
_STARTED = 1_780_000_000_000
_NOW_40MIN = _STARTED + 40 * _MIN


def _ev(**over) -> ProgressEvidence:
    """A ProgressEvidence with sensible defaults; override per test.

    Defaults: the 40-min-old run, 0 commits, 0 journal events, no heartbeat.
    """
    base = dict(
        run_started_ms=_STARTED,
        now_ms=_NOW_40MIN,
        commits_since_start=0,
        journal_events_since=0,
        last_heartbeat_age_ms=None,
        tokens_spent_since=None,
    )
    base.update(over)
    return ProgressEvidence(**base)


# ---------------------------------------------------------------------------
# 1. The three rungs, on frozen evidence (the core Phase-1 litmus).
# ---------------------------------------------------------------------------


def test_commits_since_start_is_advancing():
    """≥1 commit since start → ADVANCING, regardless of heartbeat (the no-plan
    floor: a commit alone, with no journal and no heartbeat, is sufficient)."""
    v = classify(_ev(commits_since_start=1, last_heartbeat_age_ms=None), _POLICY)
    assert v.verdict is Liveness.ADVANCING
    # The forward-delta rung wins even when the heartbeat is stale/absent.
    v2 = classify(
        _ev(commits_since_start=3, last_heartbeat_age_ms=99 * _MIN), _POLICY
    )
    assert v2.verdict is Liveness.ADVANCING
    assert "3 commit" in v2.reason


def test_no_commits_fresh_heartbeat_is_spinning():
    """0 commits + a fresh heartbeat on a run old enough to judge → SPINNING.

    The North-star case: alive (heartbeat 2 min < 5-min spin window), 40 min into
    the run (≥ 10-min grace), zero forward delta — narrating motion it isn't
    making.
    """
    v = classify(_ev(commits_since_start=0, last_heartbeat_age_ms=2 * _MIN), _POLICY)
    assert v.verdict is Liveness.SPINNING
    assert v.evidence.commits_since_start == 0


def test_no_commits_no_heartbeat_past_grace_is_stalled():
    """0 commits + heartbeat past the window (or absent) → STALLED.

    Two shapes, both STALLED: a heartbeat older than spin_ms (proof of life
    expired), and no heartbeat at all. A run "past grace" (here 40 min, well past
    both windows) with no commits is dead/hung, not spinning.
    """
    # Heartbeat older than spin_ms (and older than grace_ms too) → STALLED.
    v_stale = classify(
        _ev(commits_since_start=0, last_heartbeat_age_ms=35 * _MIN), _POLICY
    )
    assert v_stale.verdict is Liveness.STALLED
    # No heartbeat at all → STALLED.
    v_none = classify(
        _ev(commits_since_start=0, last_heartbeat_age_ms=None), _POLICY
    )
    assert v_none.verdict is Liveness.STALLED
    assert "dead or hung" in v_none.reason


def test_young_alive_run_is_not_yet_spinning():
    """The grace guard: a fresh heartbeat on a run YOUNGER than grace_ms is not
    accused of SPINNING — it is alive and too young to judge (ADVANCING-benign).

    This is the false-positive guard the chosen two-window semantics add: a run
    in its first few minutes that simply hasn't committed yet must not read as
    SPINNING. The reason makes clear no commit landed (ADVANCING here means "no
    liveness problem yet", not "state moved")."""
    young_now = _STARTED + 2 * _MIN  # 2 min into the run; grace is 10 min
    v = classify(
        ProgressEvidence(
            run_started_ms=_STARTED,
            now_ms=young_now,
            commits_since_start=0,
            last_heartbeat_age_ms=30 * 1000,  # 30s — fresh, alive
        ),
        _POLICY,
    )
    assert v.verdict is Liveness.ADVANCING
    assert "too young to judge" in v.reason
    # ...but the SAME fresh-heartbeat/0-commit run, once it is old enough, flips
    # to SPINNING — proving grace_ms is the only thing separating the two.
    old_now = _STARTED + 20 * _MIN  # 20 min ≥ 10-min grace
    v2 = classify(
        ProgressEvidence(
            run_started_ms=_STARTED,
            now_ms=old_now,
            commits_since_start=0,
            last_heartbeat_age_ms=30 * 1000,
        ),
        _POLICY,
    )
    assert v2.verdict is Liveness.SPINNING


def test_journal_event_without_commit_is_advancing():
    """A state-mutating journal event since start counts as forward progress even
    with 0 commits (lease-layer work). Phase 1 leaves the CLI rung at 0, but the
    pure classifier already honors it (Phase 2 wires the journal fold in)."""
    v = classify(
        _ev(commits_since_start=0, journal_events_since=1, last_heartbeat_age_ms=None),
        _POLICY,
    )
    assert v.verdict is Liveness.ADVANCING
    assert "lease layer" in v.reason


# ---------------------------------------------------------------------------
# 2. Purity — classify() touches no subprocess, no file, no clock.
# ---------------------------------------------------------------------------


def test_classify_is_pure(monkeypatch):
    """`classify()` makes no subprocess/file/clock call — the arbiter discipline.

    We poison the three I/O surfaces a verdict must never touch (subprocess.run,
    builtins.open, time.time) so any accidental call raises loudly, then assert a
    clean verdict still comes back. This is what lets LVN be replay-tested on
    frozen fixtures instead of needing a live multi-minute agent run.
    """
    import builtins
    import time as _time

    def _boom(*a, **k):  # pragma: no cover - only runs if purity is violated
        raise AssertionError("classify() performed I/O — it must be pure")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(_time, "time", _boom)

    v = classify(_ev(commits_since_start=1), _POLICY)
    assert v.verdict is Liveness.ADVANCING
    # Exercise every branch under the poison so no rung secretly does I/O.
    assert classify(_ev(last_heartbeat_age_ms=2 * _MIN), _POLICY).verdict is Liveness.SPINNING
    assert classify(_ev(last_heartbeat_age_ms=None), _POLICY).verdict is Liveness.STALLED


def test_verdict_to_dict_round_trips_evidence():
    """`--output json` payload carries the verdict AND the driving evidence so the
    operator sees not just SPINNING but why (legible distrust)."""
    v = classify(_ev(commits_since_start=0, last_heartbeat_age_ms=2 * _MIN), _POLICY)
    d = v.to_dict()
    assert d["verdict"] == "SPINNING"
    assert d["evidence"]["commits_since_start"] == 0
    assert d["evidence"]["last_heartbeat_age_ms"] == 2 * _MIN
    # JSON-serialisable (the renderer seam will dump it).
    json.dumps(d)


def test_policy_rejects_negative_windows():
    with pytest.raises(ValueError):
        LivenessPolicy(grace_ms=-1)
    with pytest.raises(ValueError):
        LivenessPolicy(spin_ms=-1)


def test_evidence_rejects_negative_counts():
    with pytest.raises(ValueError):
        ProgressEvidence(run_started_ms=0, now_ms=0, commits_since_start=-1)


# ---------------------------------------------------------------------------
# 3. The no-plan rail — `dos liveness` against a plain git repo (CLI throughline).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )


def _plain_repo(repo: Path) -> str:
    """A git repo with zero phased-plan surface. Returns the start SHA."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo, no phased plan")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return sha


def _mint_run_id(now_ms: int) -> str:
    """Mint a real run-id whose decoded start-ms == now_ms (deterministic)."""
    from dos import run_id
    run = run_id.mint("liveness-test", clock_ms=lambda: now_ms, entropy=lambda: 0)
    # Sanity: the token decodes back to the ms we asked for (the CLI relies on it).
    assert run_id.ts_ms_of(run.run_id) == now_ms
    return run.run_id


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv],
        capture_output=True, text=True,
    )


def test_liveness_no_plan(tmp_path: Path):
    """`dos liveness` returns a verdict in a plain git repo with no plan/registry/
    journal — the temporal sibling of `test_verify_no_plan` (commits-since-start
    alone suffices)."""
    start_sha = _plain_repo(tmp_path)
    # Run started 1 hour ago; "now" is supplied so the test is deterministic.
    started_ms = 1_780_000_000_000
    now_ms = started_ms + 60 * _MIN
    rid = _mint_run_id(started_ms)

    # No commits since start, no heartbeat → STALLED (a 1-hour-old run that never
    # moved and never beat is dead/hung). The point pinned: it ANSWERS, with no
    # plan doc, no execution-state, no journal present.
    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha,
        "--now-ms", str(now_ms), "--json",
    )
    assert proc.returncode == 4, proc.stderr  # STALLED exit code
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "STALLED"
    assert payload["evidence"]["commits_since_start"] == 0

    # No `.dos/` was created — `dos liveness` is read-only like `dos verify`.
    # With the Phase-2 journal rung LIVE, the boundary read must still not create
    # the journal (or its parent .dos/ dir): read_all returns [] on a missing path
    # without mkdir, so the no-plan / read-only rail holds across the new rung.
    assert not (tmp_path / ".dos").exists()
    assert not (tmp_path / ".dos" / "lane-journal.jsonl").exists()


def test_liveness_cli_advancing_after_commit(tmp_path: Path):
    """A commit lands after the start SHA → ADVANCING (exit 0), through the real
    CLI's git rung — the North-star's 'same run after a commit lands' line."""
    start_sha = _plain_repo(tmp_path)
    _git(tmp_path, "commit", "--allow-empty", "-m", "RS: RS1 — ship the surfacer")
    started_ms = 1_780_000_000_000
    rid = _mint_run_id(started_ms)

    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha,
        "--now-ms", str(started_ms + 60 * _MIN),
    )
    assert proc.returncode == 0, proc.stderr  # ADVANCING
    assert "ADVANCING" in proc.stdout
    assert "1 commit" in proc.stdout


def test_liveness_cli_spinning(tmp_path: Path):
    """Fresh heartbeat (caller-supplied) + 0 commits on an old run → SPINNING
    (exit 3), through the CLI. Proves --last-heartbeat-age-ms feeds the verdict
    (the Phase-2 journal rung's caller-supplied stand-in)."""
    start_sha = _plain_repo(tmp_path)
    started_ms = 1_780_000_000_000
    rid = _mint_run_id(started_ms)

    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha,
        "--now-ms", str(started_ms + 40 * _MIN),   # 40 min in — old enough to judge
        "--last-heartbeat-age-ms", str(2 * _MIN),  # alive
    )
    assert proc.returncode == 3, proc.stderr  # SPINNING
    assert "SPINNING" in proc.stdout


def test_liveness_cli_rejects_bad_run_id(tmp_path: Path):
    """A non-run-id token is a contract error (exit 2), not a silent verdict."""
    _plain_repo(tmp_path)
    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", "not-a-real-rid", "--start-sha", "abc123",
    )
    assert proc.returncode == 2, proc.stdout
    assert "not a valid run-id" in proc.stderr


# ---------------------------------------------------------------------------
# 4. The Phase-2 journal rungs through the real CLI (boundary read + fold).
# ---------------------------------------------------------------------------


def _iso(ms: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _seed_journal(tmp_path: Path, entries: list[dict]) -> None:
    """Write a real lane journal at the served workspace's journal path via the
    library appender (the only writer), so `dos liveness`'s boundary read folds
    it. The generic --workspace layout puts it at <ws>/.dos/lane-journal.jsonl."""
    from dos import lane_journal
    jp = tmp_path / ".dos" / "lane-journal.jsonl"
    for i, e in enumerate(entries):
        lane_journal.append({"seq": i + 1, **e}, path=jp)


def test_liveness_cli_journal_event_advancing(tmp_path: Path):
    """A real lane journal carrying THIS run's ACQUIRE (at start) + a LATER
    RECONCILE (lease-work, after start) for the run's lane, invoked with matching
    --lane/--loop-ts and 0 commits → ADVANCING (exit 0) via the journal-event
    rung. Proves the boundary read + fold + classify path live end-to-end."""
    start_sha = _plain_repo(tmp_path)
    started_ms = 1_780_000_000_000
    rid = _mint_run_id(started_ms)
    loop_ts, lane = "2026-06-01T14:00Z", "apply"
    _seed_journal(tmp_path, [
        {"op": "ACQUIRE", "loop_ts": loop_ts, "lane": lane, "ts": _iso(started_ms)},
        {"op": "RECONCILE", "loop_ts": loop_ts, "lane": lane,
         "ts": _iso(started_ms + 5 * _MIN)},
    ])
    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha,
        "--now-ms", str(started_ms + 40 * _MIN),
        "--lane", lane, "--loop-ts", loop_ts,
    )
    assert proc.returncode == 0, proc.stderr  # ADVANCING
    assert "ADVANCING" in proc.stdout
    assert "lease layer" in proc.stdout


def test_liveness_cli_journal_spinning(tmp_path: Path):
    """A real journal whose only THIS-lease trace is a fresh HEARTBEAT (a beat,
    not a work event), 0 commits, old run → SPINNING (exit 3) from the
    journal-derived heartbeat age alone (no --last-heartbeat-age-ms)."""
    start_sha = _plain_repo(tmp_path)
    started_ms = 1_780_000_000_000
    now_ms = started_ms + 40 * _MIN
    rid = _mint_run_id(started_ms)
    loop_ts, lane = "2026-06-01T14:00Z", "apply"
    _seed_journal(tmp_path, [
        {"op": "ACQUIRE", "loop_ts": loop_ts, "lane": lane, "ts": _iso(started_ms)},
        {"op": "HEARTBEAT", "loop_ts": loop_ts, "lane": lane,
         "ts": _iso(now_ms - 2 * _MIN)},  # fresh beat, but not progress
    ])
    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha,
        "--now-ms", str(now_ms), "--lane", lane, "--loop-ts", loop_ts,
    )
    assert proc.returncode == 3, proc.stderr  # SPINNING
    assert "SPINNING" in proc.stdout


def test_liveness_cli_heartbeat_override_wins_over_journal(tmp_path: Path):
    """--last-heartbeat-age-ms OVERRIDES the journal-derived age: a journal with a
    STALE beat for the run's lane, invoked WITH --lane/--loop-ts AND an explicit
    FRESH --last-heartbeat-age-ms → the flag wins (SPINNING), the stale beat is
    ignored. Pins the override precedence (`args.X if not None else journal)."""
    start_sha = _plain_repo(tmp_path)
    started_ms = 1_780_000_000_000
    now_ms = started_ms + 40 * _MIN
    rid = _mint_run_id(started_ms)
    loop_ts, lane = "2026-06-01T14:00Z", "apply"
    _seed_journal(tmp_path, [
        # The run's BOUNDARY ACQUIRE (at start): excluded from the event count
        # (floors to the start second), but it IS a beat — and at 40 min old it is
        # stale (> the 15-min default spin window). So the journal alone → STALLED,
        # with 0 events (no later lease-work), isolating the heartbeat override.
        {"op": "ACQUIRE", "loop_ts": loop_ts, "lane": lane, "ts": _iso(started_ms)},
    ])
    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha, "--now-ms", str(now_ms),
        "--lane", lane, "--loop-ts", loop_ts,
        "--last-heartbeat-age-ms", str(2 * _MIN),  # explicit fresh override
    )
    assert proc.returncode == 3, proc.stderr  # SPINNING (the fresh override wins)
    assert "SPINNING" in proc.stdout
    # And WITHOUT the override, the same stale journal beat → STALLED (the beat
    # is what the journal rung derives; proves the override is what flipped it).
    proc2 = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha, "--now-ms", str(now_ms),
        "--lane", lane, "--loop-ts", loop_ts,
    )
    assert proc2.returncode == 4, proc2.stderr  # STALLED (stale journal beat)
    # An EXPLICIT 0 override (freshest possible) must WIN, not fall through to the
    # journal — pins `is not None` over a bare `or` (a `0 or journal` bug would
    # silently use the stale journal beat → STALLED). 0-age beat on a 40-min run
    # with 0 commits → SPINNING.
    proc3 = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha, "--now-ms", str(now_ms),
        "--lane", lane, "--loop-ts", loop_ts, "--last-heartbeat-age-ms", "0",
    )
    assert proc3.returncode == 3, proc3.stderr  # SPINNING (the explicit 0 won)


def test_liveness_cli_no_identity_journal_silent(tmp_path: Path):
    """The "require identity always" rail through the CLI: a real journal carrying
    THIS lane's fresh HEARTBEAT, but invoked with NO --lane/--loop-ts, leaves the
    journal rungs SILENT — the bare North-star form answers from the commit rung
    alone (0 commits, no heartbeat → STALLED), never picking up the journal beat
    without identity. The CLI analogue of test_neighbor_*'s lease_key=None."""
    start_sha = _plain_repo(tmp_path)
    started_ms = 1_780_000_000_000
    now_ms = started_ms + 40 * _MIN
    rid = _mint_run_id(started_ms)
    loop_ts, lane = "2026-06-01T14:00Z", "apply"
    _seed_journal(tmp_path, [
        {"op": "HEARTBEAT", "loop_ts": loop_ts, "lane": lane,
         "ts": _iso(now_ms - 2 * _MIN)},  # fresh beat present in the journal
    ])
    # No --lane/--loop-ts → journal rungs silent → STALLED from the commit rung.
    proc = _run_cli(
        "liveness", "--workspace", str(tmp_path),
        "--run-id", rid, "--start-sha", start_sha, "--now-ms", str(now_ms),
    )
    assert proc.returncode == 4, proc.stderr  # STALLED (journal not consulted)
    assert "STALLED" in proc.stdout
