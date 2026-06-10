"""Tests for `dos plan` — the work-terrain board (`dos.plan_board` + `_tui`).

`dos plan` is the third read-only projection: a verify()-fan-out over candidate plan
rows, headlined by the claimed-vs-oracle divergence cell. These tests pin:

  * the divergence truth table — the oracle is ALWAYS the authority; the claim only
    selects which of the four cells we are in (the believed-vs-adjudicated headline);
  * the pure join — a row's lane chip comes from a live lease, its gate from a decision;
  * the fresh-repo floor — a repo with NO plans renders a frame (the `dos top` contract);
  * verify fail-safe — a flaky oracle degrades a row, never crashes the board;
  * the rich-absent / non-tty TUI floor.

Pure throughout: clock injected (`now=`), oracle `verify` faked, the one git read
exercised against a real tmp git repo (the honest fresh-repo proof).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from dos import dispatch_top as DT
from dos import plan_board as PB
from dos import plan_board_tui as TUI
from dos import plan_source as PS
from dos.config import default_config


NOW = dt.datetime(2026, 6, 1, 12, 0, 0, tzinfo=dt.timezone.utc)


def _git_repo(path: Path, *, commits=("initial commit",)) -> Path:
    path.mkdir(parents=True, exist_ok=True)

    def _git(*args):
        subprocess.run(["git", *args], cwd=str(path), check=True,
                       capture_output=True, text=True)

    _git("init")
    _git("config", "user.email", "t@t.t")
    _git("config", "user.name", "t")
    for i, msg in enumerate(commits):
        (path / f"file{i}.txt").write_text(f"content {i}\n", encoding="utf-8")
        _git("add", "-A")
        _git("commit", "-m", msg)
    return path


def _row(plan, phase, claimed=PS.CLAIMED_UNKNOWN, lane=""):
    return PS.PlanRow(plan=plan, phase=phase, claimed_status=claimed, lane=lane)


# ---------------------------------------------------------------------------
# THE HEADLINE: the divergence truth table. The oracle is the authority.
# ---------------------------------------------------------------------------


class TestDivergence:
    def test_claim_shipped_oracle_yes_is_agreed_shipped(self):
        assert PB.divergence(PS.CLAIMED_SHIPPED, True) == PB.DIV_OK_SHIPPED

    def test_claim_shipped_oracle_no_is_OVERCLAIM(self):
        """The headline cell: the plan stamps SHIPPED but the oracle says not."""
        assert PB.divergence(PS.CLAIMED_SHIPPED, False) == PB.DIV_OVERCLAIM

    def test_claim_open_oracle_yes_is_underclaim(self):
        """Benign drift: the plan stamp lags reality (the oracle confirms a ship)."""
        assert PB.divergence(PS.CLAIMED_OPEN, True) == PB.DIV_UNDERCLAIM

    def test_claim_blocked_oracle_yes_is_underclaim(self):
        assert PB.divergence(PS.CLAIMED_BLOCKED, True) == PB.DIV_UNDERCLAIM

    def test_claim_open_oracle_no_is_pending(self):
        assert PB.divergence(PS.CLAIMED_OPEN, False) == PB.DIV_PENDING

    def test_claim_unknown_oracle_no_is_dash(self):
        """No claim ⇒ nothing to diverge from; never call it an over/under-claim."""
        assert PB.divergence(PS.CLAIMED_UNKNOWN, False) == PB.DIV_UNKNOWN

    def test_claim_unknown_oracle_yes_is_shipped(self):
        assert PB.divergence(PS.CLAIMED_UNKNOWN, True) == PB.DIV_OK_SHIPPED

    def test_only_over_and_under_claim_count_as_divergent(self):
        assert PB.DIV_OVERCLAIM in PB._DIVERGENT
        assert PB.DIV_UNDERCLAIM in PB._DIVERGENT
        assert PB.DIV_OK_SHIPPED not in PB._DIVERGENT
        assert PB.DIV_PENDING not in PB._DIVERGENT


# ---------------------------------------------------------------------------
# build_phase_rows — the pure adapter: rows × oracle × lease-join × decision-join.
# ---------------------------------------------------------------------------


class TestBuildPhaseRows:
    def test_oracle_drives_status_not_the_claim(self):
        """A SHIPPED-claimed phase the oracle says is NOT shipped reads OVERCLAIM —
        proving the board trusts the oracle, never the plan's stamp (the whole point)."""
        rows = [_row("IF", "IF4.1", claimed=PS.CLAIMED_SHIPPED)]
        out = PB.build_phase_rows(rows, verify=lambda p, ph: False)
        assert out[0].divergence == PB.DIV_OVERCLAIM
        assert out[0].is_divergent is True
        assert out[0].oracle_shipped is False

    def test_bool_verify_is_accepted(self):
        out = PB.build_phase_rows([_row("IF", "IF4.1", claimed=PS.CLAIMED_SHIPPED)],
                                  verify=lambda p, ph: True)
        assert out[0].oracle_shipped is True
        assert out[0].divergence == PB.DIV_OK_SHIPPED

    def test_shipverdict_verify_carries_source_and_sha(self):
        from dos.oracle import ShipVerdict
        def _v(p, ph):
            return ShipVerdict(plan=p, phase=ph, shipped=True, sha="abc1234", source="registry")
        out = PB.build_phase_rows([_row("IF", "IF4.1")], verify=_v)
        assert out[0].oracle_shipped is True
        assert out[0].oracle_source == "registry"
        assert out[0].oracle_sha == "abc1234"

    def test_verify_raise_is_failsafe(self):
        def _boom(p, ph):
            raise RuntimeError("oracle down")
        out = PB.build_phase_rows([_row("IF", "IF4.1", claimed=PS.CLAIMED_SHIPPED)], verify=_boom)
        assert out[0].oracle_shipped is False     # degrades, never crashes
        assert out[0].oracle_source == "none"

    def test_live_oracle_internal_raise_labels_source_none(self, tmp_path, monkeypatch):
        """A live oracle that raises INTERNALLY labels the row source="none", consistent
        with the boundary-raise path (review finding: the two failure modes must agree)."""
        cfg = default_config(tmp_path)
        from dos import oracle
        monkeypatch.setattr(oracle, "is_shipped",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("torn registry")))
        verify = PB._make_oracle_verify(cfg)
        out = PB.build_phase_rows([_row("IF", "IF4.1", claimed=PS.CLAIMED_SHIPPED)], verify=verify)
        assert out[0].oracle_shipped is False
        assert out[0].oracle_source == "none"

    def test_lane_join_attaches_live_chip(self):
        """A phase whose lane holds an ADVANCING lease shows that chip (join to dos top)."""
        states = (DT.LaneState(lane="apply", chip=DT.CHIP_ADVANCING),)
        out = PB.build_phase_rows([_row("IF", "IF6", lane="apply")],
                                  verify=lambda p, ph: False, lane_states=states)
        assert out[0].lane_chip == DT.CHIP_ADVANCING

    def test_free_lane_is_not_a_join_signal(self):
        states = (DT.LaneState(lane="apply", chip=DT.CHIP_FREE),)
        out = PB.build_phase_rows([_row("IF", "IF6", lane="apply")],
                                  verify=lambda p, ph: False, lane_states=states)
        assert out[0].lane_chip == ""   # a FREE lane contributes no chip

    def test_decision_join_attaches_gate(self):
        """A phase whose lane has a pending decision shows it (join to dos decisions)."""
        from dos.decisions import Decision, DecisionKind, ResolverKind
        dec = Decision(kind=DecisionKind.WEDGE, resolver_kind=ResolverKind.HUMAN,
                       lane="apply", reason_token="LANE_ALL_INFLIGHT", reason_text="x",
                       run_id="", age_seconds=1, source_path="")
        out = PB.build_phase_rows([_row("IF", "IF6", lane="apply")],
                                  verify=lambda p, ph: False, decisions=(dec,))
        assert out[0].decision_ref == "LANE_ALL_INFLIGHT"

    def test_no_lane_means_no_joins(self):
        states = (DT.LaneState(lane="apply", chip=DT.CHIP_ADVANCING),)
        out = PB.build_phase_rows([_row("IF", "IF6", lane="")],
                                  verify=lambda p, ph: False, lane_states=states)
        assert out[0].lane_chip == "" and out[0].decision_ref == ""


# ---------------------------------------------------------------------------
# THE FRESH-REPO FLOOR: dos plan works in a repo with no plans.
# ---------------------------------------------------------------------------


class TestFreshRepo:
    def test_snapshot_no_plans_renders_a_frame(self, tmp_path: Path):
        """A plain git repo with NO plan docs renders a frame: no phases, but real git
        activity in the strip. The whole-screen no-plan contract (the dos top floor)."""
        repo = _git_repo(tmp_path, commits=("first commit",))
        cfg = default_config(repo)
        frame = PB.snapshot(cfg, verify=lambda p, ph: False, now=NOW)
        assert frame.phases == ()
        assert any(c["subject"] == "first commit" for c in frame.activity)
        text = PB.render_frame_text(frame)
        assert "dos plan" in text
        assert "no plans declared" in text
        assert "RECENT COMMITS" in text

    def test_snapshot_reads_a_plan_and_fans_the_oracle(self, tmp_path: Path):
        repo = _git_repo(tmp_path)
        cfg = default_config(repo)
        plans = repo / "docs" / "_plans"
        plans.mkdir(parents=True)
        (plans / "if-plan.md").write_text(
            "### 1. IF IF4.1 — split · SHIPPED 2026-05-01 abc\n"
            "### 2. IF IF4.2 — ancestry\n",
            encoding="utf-8",
        )
        # Oracle says IF4.1 did NOT actually ship → that SHIPPED claim is an OVERCLAIM.
        frame = PB.snapshot(cfg, verify=lambda p, ph: False, now=NOW)
        by_phase = {p.phase: p for p in frame.phases}
        assert by_phase["IF4.1"].divergence == PB.DIV_OVERCLAIM
        assert by_phase["IF4.2"].divergence == PB.DIV_PENDING
        assert frame.summary()["divergent"] == 1
        assert frame.summary()["over_claims"] == 1

    def test_explicit_phase_rows_win_over_source(self, tmp_path: Path):
        """An explicit rows list (the no-schema escape hatch) is fanned over directly,
        ignoring any plan docs in the tree."""
        repo = _git_repo(tmp_path)
        cfg = default_config(repo)
        plans = repo / "docs" / "_plans"
        plans.mkdir(parents=True)
        (plans / "x-plan.md").write_text("### 1. DOCS D1 — ignore\n", encoding="utf-8")
        frame = PB.snapshot(cfg, verify=lambda p, ph: True,
                            rows=[_row("AUTH", "P2")], now=NOW)
        assert [(p.plan, p.phase) for p in frame.phases] == [("AUTH", "P2")]
        assert frame.plan_source == "explicit"

    def test_explicit_rows_label_is_explicit_even_with_source_flag(self, tmp_path: Path):
        """An explicit rows list rode in with a --source flag, but the rows did NOT come
        from that source — so the provenance label is "explicit", never the unused source
        name (review finding: don't claim a source that produced none of the shown rows)."""
        repo = _git_repo(tmp_path)
        cfg = default_config(repo)
        frame = PB.snapshot(cfg, verify=lambda p, ph: False,
                            rows=[_row("AUTH", "P2")], source_name="markdown", now=NOW)
        assert frame.plan_source == "explicit"

    def test_snapshot_does_not_create_state(self, tmp_path: Path):
        repo = _git_repo(tmp_path)
        cfg = default_config(repo)
        before = {p.name for p in repo.iterdir()}
        PB.snapshot(cfg, verify=lambda p, ph: False, now=NOW)
        assert {p.name for p in repo.iterdir()} == before  # read-only

    def test_to_dict_is_json_serializable(self, tmp_path: Path):
        repo = _git_repo(tmp_path)
        cfg = default_config(repo)
        frame = PB.snapshot(cfg, verify=lambda p, ph: False, now=NOW)
        json.dumps(frame.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# Renderers — pure, deterministic plain text.
# ---------------------------------------------------------------------------


class TestRenderers:
    def test_empty_phases_text(self):
        assert "no plans declared" in PB.render_phases_text(())

    def test_phases_tally_counts_divergence(self):
        rows = [
            PB.PhaseRow(plan="IF", phase="IF4.1", claimed_status=PS.CLAIMED_SHIPPED,
                        oracle_shipped=False, divergence=PB.DIV_OVERCLAIM),
            PB.PhaseRow(plan="IF", phase="IF4.2", claimed_status=PS.CLAIMED_OPEN,
                        oracle_shipped=False, divergence=PB.DIV_PENDING),
        ]
        text = PB.render_phases_text(tuple(rows))
        assert "1 DIVERGENT" in text and "1 over-claim" in text

    def test_frame_text_flags_divergence_in_footer(self):
        rows = (PB.PhaseRow(plan="IF", phase="IF4.1", claimed_status=PS.CLAIMED_SHIPPED,
                            oracle_shipped=False, divergence=PB.DIV_OVERCLAIM),)
        frame = PB.Frame(workspace="/w", now_iso="2026-06-01T12:00:00+00:00", phases=rows)
        text = PB.render_frame_text(frame)
        assert "DISAGREES with the oracle" in text

    def test_long_workspace_path_not_truncated(self):
        frame = PB.Frame(workspace="C:\\" + "x" * 120, now_iso="2026-06-01T12:00:00+00:00")
        head = PB.render_frame_text(frame).splitlines()[0]
        assert "x" * 120 in head


# ---------------------------------------------------------------------------
# The TUI floor — rich-absent / non-tty degrades to one plain frame, exit 0.
# ---------------------------------------------------------------------------


class TestTuiFloor:
    def test_once_prints_plain_frame_returns_zero(self, tmp_path, capsys):
        repo = _git_repo(tmp_path, commits=("seed",))
        cfg = default_config(repo)
        rc = TUI.run_plan(cfg, once=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "dos plan" in out and "RECENT COMMITS" in out

    def test_non_tty_is_the_floor(self, tmp_path, capsys):
        repo = _git_repo(tmp_path)
        cfg = default_config(repo)
        rc = TUI.run_plan(cfg, once=False)
        assert rc == 0
        assert "PHASES" in capsys.readouterr().out
