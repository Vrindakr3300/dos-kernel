"""reindex + cross-project queries (docs/75_state-home-plan.md, Phase 4).

`dos reindex` is the projection-not-sync authority: the central store is DERIVED
from the live `.dos/` dirs, never the source of truth. These pin that deleting
the central index and reindexing reconstructs it, that a gone project is marked
stale (not crashed), idempotency, id-collision surfacing, and the read-only
`dos learn` aggregates.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dos import home
from dos.config import ENV_DOS_HOME, default_config, resolve_dos_home


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("DISPATCH_HOME", str(h))
    return h


def _seed_project(tmp_path: Path, name: str):
    (tmp_path / name).mkdir(parents=True, exist_ok=True)
    cfg = default_config(tmp_path / name)
    home.ensure_project_home(cfg)
    return cfg


class TestReindex:
    def test_rebuilds_projects_from_cards(self, tmp_path: Path, home_dir: Path):
        _seed_project(tmp_path, "p1")
        _seed_project(tmp_path, "p2")
        index = home_dir / "projects" / "index.jsonl"
        assert index.exists()
        index.unlink()  # blow away the central projection
        summary = home.reindex()
        assert summary["projects"] == 2  # reconstructed from the .dos/ cards
        pids = {r["project_id"] for r in home.read_jsonl(index)}
        assert len(pids) == 2

    def test_marks_stale_not_crash(self, tmp_path: Path, home_dir: Path):
        _seed_project(tmp_path, "p1")
        _seed_project(tmp_path, "gone")
        shutil.rmtree(tmp_path / "gone")  # the project's whole tree vanished
        summary = home.reindex()  # must not raise
        assert summary["stale"] == 1
        assert summary["active"] == 1

    def test_prune_drops_stale(self, tmp_path: Path, home_dir: Path):
        _seed_project(tmp_path, "p1")
        _seed_project(tmp_path, "gone")
        shutil.rmtree(tmp_path / "gone")
        summary = home.reindex(prune=True)
        assert summary["projects"] == 1  # the stale one was pruned from the rewrite

    def test_is_idempotent(self, tmp_path: Path, home_dir: Path):
        _seed_project(tmp_path, "p1")
        _seed_project(tmp_path, "p2")
        home.reindex(clock=lambda: 1_000_000_000_000)
        first = (home_dir / "projects" / "index.jsonl").read_text(encoding="utf-8")
        home.reindex(clock=lambda: 1_000_000_000_000)
        second = (home_dir / "projects" / "index.jsonl").read_text(encoding="utf-8")
        assert first == second  # byte-identical with a fixed clock

    def test_rebuilds_decisions_from_local_mirror(self, tmp_path: Path, home_dir: Path):
        cfg = _seed_project(tmp_path, "p1")
        home.append_decision(cfg, {
            "kind": "ARBITER_REFUSE", "resolver_kind": "HUMAN", "lane": "main",
            "reason_token": "", "reason_category": "", "run_ts": "",
            "resolution": {"action": "force_acquire", "lane": "main", "forced": True},
        })
        (home_dir / "decisions.jsonl").unlink()  # blow away central decisions
        home.reindex()
        central = home.read_jsonl(home_dir / "decisions.jsonl")
        assert len(central) == 1  # rebuilt from the project's local mirror
        assert central[0]["resolution"]["action"] == "force_acquire"


# ---------------------------------------------------------------------------
# --prune durability (the 2026-06-10 index-pollution audit, follow-through).
# Three properties: a pruned root leaves roots.log too (else the index∪roots.log
# union resurrects the row as `stale` on the very next plain reindex); a plain
# reindex still never touches roots.log; and a THROWAWAY row — an OS-temp-rooted
# workspace, alive on disk or not — is dropped when the prune targets the
# machine-default home (the retroactive twin of ensure_project_home's
# registration guard, same `_is_temp_root`, same override exemption).
# ---------------------------------------------------------------------------


class TestPruneDurability:
    def test_prune_compacts_roots_log(self, tmp_path: Path, home_dir: Path):
        _seed_project(tmp_path, "p1")
        _seed_project(tmp_path, "gone")
        shutil.rmtree(tmp_path / "gone")
        home.reindex(prune=True)
        kept = (home_dir / "projects" / "roots.log").read_text(encoding="utf-8")
        assert str((tmp_path / "p1").resolve()) in kept
        assert str((tmp_path / "gone").resolve()) not in kept

    def test_prune_survives_a_later_plain_reindex(self, tmp_path: Path, home_dir: Path):
        """The resurrection bug this pins shut: before roots.log compaction, a
        pruned project re-entered the index as `stale` on the next plain
        reindex, so `--prune` never actually stuck."""
        _seed_project(tmp_path, "p1")
        _seed_project(tmp_path, "gone")
        shutil.rmtree(tmp_path / "gone")
        home.reindex(prune=True)
        summary = home.reindex()  # plain — must not resurrect the pruned row
        assert summary["projects"] == 1
        assert summary["stale"] == 0

    def test_plain_reindex_never_rewrites_roots_log(self, tmp_path: Path, home_dir: Path):
        _seed_project(tmp_path, "p1")
        _seed_project(tmp_path, "gone")
        shutil.rmtree(tmp_path / "gone")
        roots_log = home_dir / "projects" / "roots.log"
        before = roots_log.read_text(encoding="utf-8")
        home.reindex()  # no prune: the durable spine stays byte-identical
        assert roots_log.read_text(encoding="utf-8") == before

    def test_prune_drops_a_throwaway_temp_root_even_while_alive(
        self, tmp_path: Path, monkeypatch
    ):
        """A retained pytest tmp dir stays 'alive' for days, so gone-from-disk
        is the wrong throwaway test — containment in the OS temp dir is (the
        2026-06-10 audit: 87 such dirs survived a plain `--prune` as fake
        'active' projects). Armed only for the machine-default home, exactly
        like the registration guard; the default resolution is steered into
        this test's tmp via XDG_DATA_HOME (the highest non-env rung on every
        platform) so the operator's real home is unreachable."""
        default_home = tmp_path / "xdg"
        monkeypatch.delenv(ENV_DOS_HOME, raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", str(default_home))
        store = default_home / "dos"
        fake_tmp = tmp_path / "os-temp"
        polluted = fake_tmp / "pytest-of-x" / "ws0"
        polluted.mkdir(parents=True)
        real = tmp_path / "real-proj"
        real.mkdir()
        # Seed BOTH as legacy rows via the explicit home= arg (the registration
        # guard exempts it), before the temp boundary is faked.
        home.ensure_project_home(default_config(polluted), home=store)
        home.ensure_project_home(default_config(real), home=store)
        monkeypatch.setattr(home.tempfile, "gettempdir", lambda: str(fake_tmp))
        # Sacrificial tripwire (fail HERE, never against the real home): the
        # default resolution must land inside this test's tmp before a PRUNING
        # reindex may run against it.
        assert resolve_dos_home() == store.resolve()

        summary = home.reindex(prune=True)

        assert summary["throwaway"] == 1
        rows = home.read_jsonl(store / "projects" / "index.jsonl")
        assert [r["root"] for r in rows] == [str(real.resolve())]
        kept = (store / "projects" / "roots.log").read_text(encoding="utf-8")
        assert str(real.resolve()) in kept
        assert str(polluted.resolve()) not in kept

    def test_throwaway_drop_disarmed_under_a_home_override(
        self, tmp_path: Path, home_dir: Path, monkeypatch
    ):
        """With DISPATCH_HOME redirected (the hermetic-test idiom), temp-rooted
        projects are legitimate and a prune must KEEP them — only gone roots
        leave."""
        monkeypatch.setattr(home.tempfile, "gettempdir", lambda: str(tmp_path))
        _seed_project(tmp_path, "p1")  # under the faked temp dir
        summary = home.reindex(prune=True)
        assert summary["throwaway"] == 0
        assert summary["projects"] == 1


class TestLearn:
    def _seed_decision(self, tmp_path, name, lane, category):
        cfg = _seed_project(tmp_path, name)
        home.append_decision(cfg, {
            "kind": "ARBITER_REFUSE", "resolver_kind": "HUMAN", "lane": lane,
            "reason_token": "", "reason_category": category, "run_ts": "",
            "resolution": {"action": "force_acquire", "lane": lane, "forced": True},
        })

    def test_wedge_hotspots_groups_by_project(self, tmp_path: Path, home_dir: Path):
        self._seed_decision(tmp_path, "hot", "main", "MISROUTE")
        cfg = _seed_project(tmp_path, "hot")  # second decision for the same project
        home.append_decision(cfg, {
            "kind": "ARBITER_REFUSE", "resolver_kind": "HUMAN", "lane": "other",
            "reason_token": "", "reason_category": "X", "run_ts": "rt2",
            "resolution": {"action": "force_acquire", "lane": "other", "forced": True},
        })
        self._seed_decision(tmp_path, "cold", "main", "MISROUTE")
        tally = home.learn("wedge-hotspots")
        assert tally[0]["group"] == "hot"
        assert tally[0]["count"] == 2

    def test_lane_refusals_groups_by_lane(self, tmp_path: Path, home_dir: Path):
        self._seed_decision(tmp_path, "a", "busy-lane", "X")
        self._seed_decision(tmp_path, "b", "busy-lane", "Y")
        self._seed_decision(tmp_path, "c", "quiet-lane", "Z")
        tally = home.learn("lane-refusals")
        assert tally[0]["group"] == "busy-lane"
        assert tally[0]["count"] == 2

    def test_oracle_calibration_groups_by_category(self, tmp_path: Path, home_dir: Path):
        self._seed_decision(tmp_path, "a", "l", "STALE_CLAIM")
        self._seed_decision(tmp_path, "b", "l", "STALE_CLAIM")
        tally = home.learn("oracle-calibration")
        assert tally[0]["group"] == "STALE_CLAIM"
        assert tally[0]["count"] == 2

    def test_unknown_axis_raises(self, tmp_path: Path, home_dir: Path):
        with pytest.raises(ValueError):
            home.learn("nonsense")

    def test_empty_store_returns_empty(self, tmp_path: Path, home_dir: Path):
        assert home.learn("lane-refusals") == []
