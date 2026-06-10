"""dos.drivers.watchdog — the push-model supervisor that polls `liveness()`.

Hermetic, the supervisor-driver test idiom: the liveness EVIDENCE is controlled by
monkeypatching the two `cli` boundary helpers the watchdog reuses
(`cli._git_delta_count` for the commit rung, `cli._journal_delta` for the journal
rung), so each tracked run classifies to the verdict we choose WITHOUT a real git
or journal. The `halt` effect is injected as a recorder so we assert the proposal
without a real WAL write — except two tests that exercise the REAL `lane_lease.halt`
against a tmp journal (the OP_HALT lands) and that monkeypatch `os.kill`/`Popen` to
raise (the watchdog never signals).

The verdict math (default `LivenessPolicy`: grace_ms=30m, spin_ms=15m):
  * ADVANCING — ≥1 commit (any), OR a fresh beat on a run younger than grace.
  * SPINNING  — 0 commits, 0 events, a FRESH beat (age ≤ spin_ms), run age ≥ grace.
  * STALLED   — 0 commits, 0 events, a STALE/absent beat.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dos import config as _config
from dos import journal_delta, lane_journal, run_id
from dos.drivers import watchdog

# Window constants in ms (mirror the default LivenessPolicy so the fixtures are
# self-documenting — a change to the kernel default that breaks these is a real
# signal, not test brittleness).
_MIN = 60_000
_GRACE_MS = 30 * _MIN
_SPIN_MS = 15 * _MIN


def _cfg(tmp_path: Path):
    return _config.default_config(tmp_path)


def _mint() -> str:
    """A real CID run-id token (decodes a start ms via run_id.ts_ms_of)."""
    return run_id.mint("PROC-watchdog-test").run_id


class _HaltRecorder:
    """A `lane_lease.halt` stand-in: records each call's kwargs, writes nothing."""

    def __init__(self):
        self.calls = []

    def __call__(self, cfg, **kwargs):
        self.calls.append(kwargs)
        return object()  # the driver ignores the return value

    @property
    def handles(self):
        return [c.get("handle") for c in self.calls]

    @property
    def run_ids(self):
        return [c.get("run_id") for c in self.calls]


def _patch_rungs(monkeypatch, *, commits: int, events: int, hb_age_ms):
    """Force the two boundary helpers the watchdog reuses to return crafted rungs.

    This is the watchdog analogue of the supervisor test's `_patch_evidence`: it
    controls `assess_run`'s inputs exactly, so the verdict is whatever we choose.
    """
    from dos import cli

    monkeypatch.setattr(cli, "_git_delta_count", lambda start_sha, cfg: commits)
    monkeypatch.setattr(
        cli, "_journal_delta",
        lambda cfg, *, started_ms, now_ms, lease_key:
            journal_delta.JournalDelta(events, hb_age_ms, False),
    )


def _tracked(rid, *, budget_ms=None, command="dos lease-lane release --lane api --owner w"):
    return watchdog.TrackedRun(
        run_id=rid, start_sha="abc123", lane="api",
        loop_ts="2026-06-02T10:00:00Z", handle="4242",
        budget_ms=budget_ms, stop_command=command,
    )


# --------------------------------------------------------------------------
# SPINNING — a tracked run that is alive but landing nothing → one halt proposal.
# --------------------------------------------------------------------------
def test_spinning_run_records_a_halt_proposal(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    # 0 commits, 0 events, fresh beat (1m), run aged past grace → SPINNING.
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    started = run_id.ts_ms_of(rid)
    now_ms = started + _GRACE_MS + _MIN  # past grace → eligible for SPINNING
    rec = _HaltRecorder()
    proposed: dict = {}

    verdicts, actions = watchdog.tick(
        cfg, [_tracked(rid)], now_ms=now_ms, proposed=proposed, halt=rec)

    assert actions.spinning == [rid]
    assert actions.proposed_halts == [rid]
    # exactly one halt, carrying the run's handle + the host stop command + run-id
    assert len(rec.calls) == 1
    assert rec.calls[0]["handle"] == "4242"
    assert rec.calls[0]["run_id"] == rid
    assert rec.calls[0]["command"] == "dos lease-lane release --lane api --owner w"
    assert "SPINNING" in rec.calls[0]["reason"]
    assert proposed.get(rid) == now_ms  # the idempotence memory is set


# --------------------------------------------------------------------------
# ADVANCING — a moving run is left entirely alone.
# --------------------------------------------------------------------------
def test_advancing_run_records_nothing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    _patch_rungs(monkeypatch, commits=2, events=0, hb_age_ms=_MIN)  # commits → ADVANCING
    now_ms = run_id.ts_ms_of(rid) + _GRACE_MS + _MIN
    rec = _HaltRecorder()

    verdicts, actions = watchdog.tick(
        cfg, [_tracked(rid)], now_ms=now_ms, proposed={}, halt=rec)

    assert actions.advancing == [rid]
    assert actions.proposed_halts == []
    assert rec.calls == []


# --------------------------------------------------------------------------
# STALLED within budget vs past budget — the budget split.
# --------------------------------------------------------------------------
def test_stalled_within_budget_records_nothing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    # Stale beat → STALLED, but the run is only 10m old and the budget is 60m.
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=40 * _MIN)
    now_ms = run_id.ts_ms_of(rid) + 10 * _MIN
    rec = _HaltRecorder()

    verdicts, actions = watchdog.tick(
        cfg, [_tracked(rid, budget_ms=60 * _MIN)], now_ms=now_ms, proposed={}, halt=rec)

    assert verdicts[rid].verdict.value == "STALLED"
    assert actions.stalled_within_budget == [rid]
    assert actions.proposed_halts == []
    assert rec.calls == []


def test_stalled_past_budget_records_a_halt(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=40 * _MIN)
    now_ms = run_id.ts_ms_of(rid) + 90 * _MIN  # past the 60m budget
    rec = _HaltRecorder()

    verdicts, actions = watchdog.tick(
        cfg, [_tracked(rid, budget_ms=60 * _MIN)], now_ms=now_ms, proposed={}, halt=rec)

    assert verdicts[rid].verdict.value == "STALLED"
    assert actions.proposed_halts == [rid]
    assert len(rec.calls) == 1
    assert "hung past budget" in rec.calls[0]["reason"]


def test_stalled_with_no_budget_records_a_halt(tmp_path, monkeypatch):
    """budget_ms=None → any STALLED run is treated as past-budget (still hung)."""
    cfg = _cfg(tmp_path)
    rid = _mint()
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=40 * _MIN)
    now_ms = run_id.ts_ms_of(rid) + 5 * _MIN  # young, but no budget declared
    rec = _HaltRecorder()

    verdicts, actions = watchdog.tick(
        cfg, [_tracked(rid, budget_ms=None)], now_ms=now_ms, proposed={}, halt=rec)

    assert actions.proposed_halts == [rid]


# --------------------------------------------------------------------------
# Idempotence — a run spinning across many ticks earns ONE proposal per window.
# --------------------------------------------------------------------------
def test_halt_proposal_is_idempotent_within_window(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    started = run_id.ts_ms_of(rid)
    rec = _HaltRecorder()
    proposed: dict = {}
    runs = [_tracked(rid)]

    # Three ticks, all within the default repropose window (30m), all SPINNING.
    for k in range(3):
        now_ms = started + _GRACE_MS + _MIN + k * _MIN
        watchdog.tick(cfg, runs, now_ms=now_ms, proposed=proposed, halt=rec)

    assert len(rec.calls) == 1  # ONE proposal across three SPINNING ticks


def test_recovered_run_can_be_reproposed(tmp_path, monkeypatch):
    """SPINNING → (proposal) → ADVANCING (forgotten) → SPINNING again → re-proposed."""
    cfg = _cfg(tmp_path)
    rid = _mint()
    started = run_id.ts_ms_of(rid)
    rec = _HaltRecorder()
    proposed: dict = {}
    runs = [_tracked(rid)]

    # Tick 1 — SPINNING → proposal.
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    watchdog.tick(cfg, runs, now_ms=started + _GRACE_MS + _MIN, proposed=proposed, halt=rec)
    assert len(rec.calls) == 1
    assert rid in proposed

    # Tick 2 — ADVANCING (a commit landed) → the proposal memory is dropped.
    _patch_rungs(monkeypatch, commits=1, events=0, hb_age_ms=_MIN)
    watchdog.tick(cfg, runs, now_ms=started + _GRACE_MS + 2 * _MIN, proposed=proposed, halt=rec)
    assert rid not in proposed
    assert len(rec.calls) == 1  # no new proposal for an advancing run

    # Tick 3 — SPINNING again → a fresh proposal is allowed (not blocked by window).
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    watchdog.tick(cfg, runs, now_ms=started + _GRACE_MS + 3 * _MIN, proposed=proposed, halt=rec)
    assert len(rec.calls) == 2


# --------------------------------------------------------------------------
# A bad run-id is skipped (cannot be timed → cannot be classified).
# --------------------------------------------------------------------------
def test_uncodable_run_id_is_skipped(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    bad = watchdog.TrackedRun(run_id="not-a-run-id", handle="x")
    rec = _HaltRecorder()

    verdicts, actions = watchdog.tick(
        cfg, [bad], now_ms=1_000_000_000_000, proposed={}, halt=rec)

    assert actions.skipped == ["not-a-run-id"]
    assert verdicts == {}
    assert rec.calls == []


# --------------------------------------------------------------------------
# The REAL halt records an OP_HALT on the journal (end-to-end, no injection).
# --------------------------------------------------------------------------
def test_spinning_records_a_real_op_halt_on_the_journal(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    now_ms = run_id.ts_ms_of(rid) + _GRACE_MS + _MIN

    # No `halt=` override → the real lane_lease.halt writes the OP_HALT.
    verdicts, actions = watchdog.tick(
        cfg, [_tracked(rid)], now_ms=now_ms, proposed={})

    assert actions.proposed_halts == [rid]
    entries = lane_journal.read_all(path=cfg.paths.lane_journal)
    halts = [e for e in entries if e.get("op") == lane_journal.OP_HALT]
    assert len(halts) == 1
    assert halts[0]["handle"] == "4242"
    assert halts[0]["run_id"] == rid
    assert halts[0]["command"] == "dos lease-lane release --lane api --owner w"
    # The HALT is intent-only: it does NOT mutate lease state (no live lease existed,
    # and replay still folds to empty — a HALT is not in _STATE_MUTATING_OPS).
    assert lane_journal.replay(entries) == []


# --------------------------------------------------------------------------
# The watchdog PROPOSES, it never SIGNALS — os.kill / Popen raise, tick succeeds.
# (The actuation-boundary proof, lifted from test_halt_proposes_does_not_signal.)
# --------------------------------------------------------------------------
def test_watchdog_proposes_does_not_signal(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    now_ms = run_id.ts_ms_of(rid) + _GRACE_MS + _MIN

    import os
    import subprocess

    def _boom(*a, **k):
        raise AssertionError("the watchdog must never deliver a signal")

    monkeypatch.setattr(os, "kill", _boom, raising=False)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    # also guard the driver-module-local reference to subprocess
    monkeypatch.setattr(watchdog.subprocess, "Popen", _boom)

    # A full tick over a SPINNING run still records the OP_HALT — proving the
    # watchdog records + proposes and NEVER calls os.kill / Popen.
    verdicts, actions = watchdog.tick(
        cfg, [_tracked(rid)], now_ms=now_ms, proposed={})

    assert actions.proposed_halts == [rid]
    halts = [e for e in lane_journal.read_all(path=cfg.paths.lane_journal)
             if e.get("op") == lane_journal.OP_HALT]
    assert len(halts) == 1


# --------------------------------------------------------------------------
# run() — bounded by max_ticks, deterministic clock, no real sleep.
# --------------------------------------------------------------------------
def test_run_is_bounded_by_max_ticks(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    _patch_rungs(monkeypatch, commits=0, events=0, hb_age_ms=_MIN)
    fixed_now = run_id.ts_ms_of(rid) + _GRACE_MS + _MIN
    rec = _HaltRecorder()
    sleeps = []

    rc = watchdog.run(
        config=cfg, tracked_runs=[_tracked(rid)], interval=0.0, max_ticks=3,
        clock_ms=lambda: fixed_now, sleep=lambda s: sleeps.append(s), halt=rec)

    assert rc == 0
    # Same clock each tick + the idempotence memory ⇒ exactly ONE proposal across 3 ticks.
    assert len(rec.calls) == 1
    # max_ticks bounds the loop: sleeps between ticks but not after the last one.
    assert len(sleeps) == 2


# --------------------------------------------------------------------------
# assess_run reuses the cli boundary helpers (the no-drift proof).
# --------------------------------------------------------------------------
def test_assess_run_reuses_cli_boundary(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rid = _mint()
    from dos import cli

    seen = {"git": False, "journal": False}

    def _git(start_sha, cfg):
        seen["git"] = (start_sha, )
        return 0

    def _journal(cfg, *, started_ms, now_ms, lease_key):
        seen["journal"] = lease_key
        return journal_delta.JournalDelta(0, _MIN, False)

    monkeypatch.setattr(cli, "_git_delta_count", _git)
    monkeypatch.setattr(cli, "_journal_delta", _journal)

    now_ms = run_id.ts_ms_of(rid) + _GRACE_MS + _MIN
    verdict = watchdog.assess_run(cfg, _tracked(rid), now_ms=now_ms)

    assert verdict is not None and verdict.verdict.value == "SPINNING"
    assert seen["git"] == ("abc123",)               # the commit rung was consulted
    assert seen["journal"] == ("2026-06-02T10:00:00Z", "api")  # the journal rung, scoped to the lease


def test_assess_run_without_identity_silences_journal(tmp_path, monkeypatch):
    """A tracked run missing lane/loop_ts passes lease_key=None (journal silent)."""
    cfg = _cfg(tmp_path)
    rid = _mint()
    from dos import cli

    captured = {}
    monkeypatch.setattr(cli, "_git_delta_count", lambda start_sha, cfg: 0)
    monkeypatch.setattr(
        cli, "_journal_delta",
        lambda cfg, *, started_ms, now_ms, lease_key: captured.setdefault("key", lease_key)
        or journal_delta.JournalDelta(0, None, False))

    tr = watchdog.TrackedRun(run_id=rid, start_sha="abc123")  # no lane/loop_ts
    watchdog.assess_run(cfg, tr, now_ms=run_id.ts_ms_of(rid) + _GRACE_MS + _MIN)
    assert captured["key"] is None


# --------------------------------------------------------------------------
# discover_tracked_runs — fold the live-lease set into tracked runs.
# --------------------------------------------------------------------------
def test_discover_tracked_runs_from_live_leases(tmp_path):
    cfg = _cfg(tmp_path)
    rid = _mint()
    # A live lease whose loop_ts IS a CID run-id (so it can be timed).
    lease = {"lane": "api", "tree": ("src/api/**",), "loop_ts": rid,
             "host_id": "host-a", "pid": 777, "acquired_at": "2026-06-02T10:00:00Z"}
    lane_journal.append(lane_journal.acquire_entry(lease), path=cfg.paths.lane_journal)

    tracked = watchdog.discover_tracked_runs(cfg, budget_ms=60 * _MIN)
    assert len(tracked) == 1
    t = tracked[0]
    assert t.run_id == rid
    assert t.lane == "api"
    assert t.handle == "777"
    assert t.start_sha == ""           # the honest floor — a lease records no start SHA
    assert t.budget_ms == 60 * _MIN


def test_discover_skips_leases_without_a_codable_identity(tmp_path):
    cfg = _cfg(tmp_path)
    # loop_ts is a plain timestamp (not a run-id) and no run_id field → cannot be timed.
    lease = {"lane": "api", "loop_ts": "2026-06-02T10:00:00Z", "pid": 1,
             "acquired_at": "2026-06-02T10:00:00Z"}
    lane_journal.append(lane_journal.acquire_entry(lease), path=cfg.paths.lane_journal)
    assert watchdog.discover_tracked_runs(cfg) == []


# --------------------------------------------------------------------------
# Layering — the one-way arrow (the kernel imports no driver).
#
# The AUTHORITATIVE bulkhead pin is `tests/test_vendor_agnostic_kernel.py::
# test_no_kernel_module_imports_a_driver`: it AST-walks every `src/dos/*.py`
# (excluding `drivers/`) and forbids a static `import dos.drivers...`. That test
# already covers the watchdog — `cli.py`'s `dos watch` verb resolves the driver
# BY NAME (`_load_watchdog()` → `importlib.import_module("dos.drivers.watchdog")`),
# never a static import, precisely so the kernel imports/packages without the
# driver and the arrow holds. We do NOT duplicate that broad scan here (a second,
# subtly-different copy is how a litmus drifts). Instead we pin the *property that
# loader relies on*: the driver is import-resolvable by its dotted name at runtime.
# --------------------------------------------------------------------------
def test_watchdog_is_resolvable_by_name_at_runtime():
    """The driver loads via importlib by dotted name (the runtime-optional contract
    `cli._load_watchdog` depends on — a static kernel import would breach the
    bulkhead pinned by test_vendor_agnostic_kernel)."""
    import importlib

    mod = importlib.import_module("dos.drivers.watchdog")
    # the API surface cli.cmd_watch calls (TrackedRun / tick / discover / the const)
    assert hasattr(mod, "TrackedRun")
    assert hasattr(mod, "tick")
    assert hasattr(mod, "discover_tracked_runs")
    assert isinstance(mod.DEFAULT_REPROPOSE_MS, int)


def test_pure_verdict_modules_do_not_import_drivers():
    """The two pure verdicts the watchdog builds on stay driver-free (the arrow)."""
    import ast

    def _imports_dos_drivers(py: Path) -> bool:
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("dos.drivers"):
                return True
            if isinstance(node, ast.Import) and any(
                a.name.startswith("dos.drivers") for a in node.names
            ):
                return True
        return False

    from dos import liveness as _lv
    from dos import supervise as _sup

    assert not _imports_dos_drivers(Path(_lv.__file__))
    assert not _imports_dos_drivers(Path(_sup.__file__))
