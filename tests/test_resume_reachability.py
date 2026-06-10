"""docs/107 Phase 4 — pause/resume, the SUSPENDED state, and the GC reachability clause (§4).

Two pins:
  * `resume.classify_run_dir_reachability` — the docs/106 reachability rule extended
    from leases to unfinished work: a run-dir is garbage ONLY if COMPLETE or
    UNRESUMABLE; a SUSPENDED-RESUMABLE (or DIVERGED) run-dir is REACHABLE regardless
    of age. Reachability is ADJUDICATED, never refcounted/clocked.
  * `dos halt --resumable` — the halt that stops a run *resumably*: it appends a
    SUSPEND to the run's intent ledger (parked & scavenge-immune) on top of the WAL
    HALT, so the run's residual survives a stop instead of a hard kill losing it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dos import config as _config
from dos import intent_ledger as il
from dos import resume as rz
from dos.intent_ledger import LedgerState, VerifiedStep
from dos.resume import AncestryFacts, Reachability, Resume


# ==========================================================================
# classify_run_dir_reachability — the §4 GC clause (pure).
# ==========================================================================


_C1, _C2 = "c1aaaaa", "c2bbbbb"


def _resumable_state() -> LedgerState:
    return LedgerState(
        run_id="RID-R", goal="g", start_sha=_C1,
        declared_steps=("s1", "s2"),
        verified={"s1": VerifiedStep("s1", _C1, via="file-path")},
    )


def _anc(*, in_ancestry=(), verified_steps=(), diverged=False) -> AncestryFacts:
    return AncestryFacts(
        shas_in_ancestry=frozenset(in_ancestry),
        steps_verified_at_read=frozenset(verified_steps),
        lane_advanced_past_resume=diverged,
    )


def test_resumable_run_dir_is_reachable():
    state = _resumable_state()
    plan = rz.resume_plan(state, _anc(in_ancestry={_C1}, verified_steps={"s1"}))
    assert plan.verdict is Resume.RESUMABLE
    r = rz.classify_run_dir_reachability(state, plan)
    assert r.reachability is Reachability.REACHABLE
    assert not r.is_collectible


def test_suspended_resumable_run_dir_is_reachable_regardless_of_age():
    # The headline §4 clause: a SUSPENDED (parked) run released its lane but its
    # ledger is reachable — never GC'd while it can still make progress.
    state = LedgerState(
        run_id="RID-R", goal="g", start_sha=_C1,
        declared_steps=("s1", "s2"),
        verified={"s1": VerifiedStep("s1", _C1, via="file-path")},
        suspended=True, suspend_resume_sha=_C1,
    )
    plan = rz.resume_plan(state, _anc(in_ancestry={_C1}, verified_steps={"s1"}))
    assert plan.verdict is Resume.RESUMABLE
    r = rz.classify_run_dir_reachability(state, plan)
    assert r.reachability is Reachability.REACHABLE
    assert r.suspended is True
    assert "SUSPENDED" in r.reason


def test_complete_run_dir_is_collectible():
    state = LedgerState(
        run_id="RID-R", goal="g", declared_steps=("s1",),
        verified={"s1": VerifiedStep("s1", _C1, via="file-path")},
    )
    plan = rz.resume_plan(state, _anc(in_ancestry={_C1}, verified_steps={"s1"}))
    assert plan.verdict is Resume.COMPLETE
    r = rz.classify_run_dir_reachability(state, plan)
    assert r.reachability is Reachability.COLLECTIBLE
    assert r.is_collectible


def test_unresumable_run_dir_is_collectible():
    state = LedgerState(run_id="RID-R")  # no intent
    plan = rz.resume_plan(state, AncestryFacts())
    assert plan.verdict is Resume.UNRESUMABLE
    r = rz.classify_run_dir_reachability(state, plan)
    assert r.reachability is Reachability.COLLECTIBLE


def test_diverged_run_dir_is_reachable_needs_a_human():
    state = _resumable_state()
    plan = rz.resume_plan(state, _anc(in_ancestry={_C1}, verified_steps={"s1"},
                                      diverged=True))
    assert plan.verdict is Resume.DIVERGED
    r = rz.classify_run_dir_reachability(state, plan)
    # A DIVERGED run-dir must NOT be reaped — it needs a human decision, surfaced.
    assert r.reachability is Reachability.REACHABLE


def test_reachability_to_dict_round_trips():
    import json
    state = _resumable_state()
    plan = rz.resume_plan(state, _anc(in_ancestry={_C1}, verified_steps={"s1"}))
    d = rz.classify_run_dir_reachability(state, plan).to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["reachability"] == "REACHABLE"


# ==========================================================================
# dos halt --resumable — the SUSPEND-on-halt wiring (§4).
# ==========================================================================


def _halt_args(tmp_path: Path, **kw) -> argparse.Namespace:
    base = dict(
        workspace=str(tmp_path), handle="pid-123", lane="", loop_ts="",
        owner="op", reason="", run_id="", command="", resumable=False,
        resume_sha="", pretty=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_halt_resumable_appends_suspend_to_the_ledger(tmp_path: Path):
    from dos import cli
    args = _halt_args(tmp_path, run_id="RID-H", resumable=True, resume_sha="abc",
                      reason="operator pause")
    rc = cli.cmd_halt(args)
    assert rc == 0
    # The run's intent ledger now carries a SUSPEND → replay sees it suspended.
    cfg = _config.default_config(tmp_path)
    state = il.replay(il.read_all("RID-H", cfg=cfg))
    assert state.suspended is True
    assert state.suspend_resume_sha == "abc"


def test_halt_resumable_without_run_id_degrades_to_plain_halt(tmp_path: Path, capsys):
    from dos import cli
    args = _halt_args(tmp_path, run_id="", resumable=True)
    rc = cli.cmd_halt(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "no run to suspend" in out or "needs --run-id" in out


def test_halt_without_resumable_writes_no_ledger(tmp_path: Path):
    from dos import cli
    args = _halt_args(tmp_path, run_id="RID-H", resumable=False)
    cli.cmd_halt(args)
    cfg = _config.default_config(tmp_path)
    # A plain HALT touches the WAL, NOT the intent ledger — no SUSPEND.
    assert il.read_all("RID-H", cfg=cfg) == []
