"""The `workshop` reference driver + the generic `--driver` CLI loader.

Pins the contracts of DOS's copy-me host-policy template:

  1. `dos.drivers.workshop` is a self-contained lane-taxonomy driver (a
     `LaneTaxonomy` + a `workshop_config(workspace)` factory, the shape of
     `job_config`) — and its `frontend` / `backend` cluster lanes are provably
     tree-disjoint, so two build agents acquire them CONCURRENTLY while the
     `release` lane stays exclusive. The docs-prefix distinction trick
     (`docs/UI-*` vs `docs/SVC-*`, both under `docs/`) is the load-bearing
     teaching point.

  2. The CLI's `--driver <name>` is a GENERIC loader: it resolves
     `dos.drivers.<name>.<name>_config` BY CONVENTION with no hardcoded driver
     name, so the kernel/CLI names no host. `--job` is the back-compat alias for
     `--driver job`. A `dos.toml [lanes]` table still layers OVER the driver base.

The kernel itself must name no host — that litmus is checked elsewhere
(`test_vendor_agnostic_kernel`); here we only prove the driver + loader behave.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dos import arbiter
from dos._tree import lane_trees_disjoint, norm_tree_prefix
from dos.cli import _resolve_driver_config
from dos.drivers.workshop import WORKSHOP_LANE_TAXONOMY, workshop_config


CFG = workshop_config("C:/tmp/workshop-foreign")

_FE_TREE = list(WORKSHOP_LANE_TAXONOMY.tree_for("frontend"))
_BE_TREE = list(WORKSHOP_LANE_TAXONOMY.tree_for("backend"))
_REL_TREE = list(WORKSHOP_LANE_TAXONOMY.tree_for("release"))


def _lease(lane, kind, tree):
    return {"lane": lane, "lane_kind": kind, "tree": tree, "loop_ts": "20260531T1200Z"}


def _arb(**kw):
    kw.setdefault("config", CFG)
    kw.setdefault("requested_tree", [])
    kw.setdefault("live_leases", [])
    return arbiter.arbitrate(**kw)


class TestTaxonomyShape:
    def test_factory_returns_workshop_taxonomy(self):
        cfg = workshop_config("C:/tmp/workshop-foreign")
        assert cfg.lanes is WORKSHOP_LANE_TAXONOMY
        assert cfg.lanes.is_concurrent("frontend")
        assert cfg.lanes.is_concurrent("backend")
        assert cfg.lanes.is_exclusive("release")
        assert cfg.lanes.is_exclusive("global")

    def test_factory_binds_workspace_root(self, tmp_path: Path):
        cfg = workshop_config(tmp_path)
        assert cfg.paths.root == tmp_path.resolve()
        assert cfg.lanes is WORKSHOP_LANE_TAXONOMY

    def test_aliases_route_keywords_to_named_lanes(self):
        a = WORKSHOP_LANE_TAXONOMY.aliases
        assert a["ui"] == "frontend"
        assert a["web"] == "frontend"
        assert a["api"] == "backend"
        assert a["svc"] == "backend"
        assert a["service"] == "backend"
        assert a["ship"] == "release"
        assert a["deploy"] == "release"


class TestDocsPrefixDisjointness:
    """The load-bearing teaching point: two lanes both under `docs/` stay
    concurrency-safe because their globs normalize to distinct prefixes."""

    def test_docs_prefixes_normalize_distinct(self):
        # The load-bearing property is DISTINCTNESS, not the exact case: the two
        # globs must normalize to different prefixes so the lanes stay disjoint.
        # `norm_tree_prefix` case-FOLDS (so a case-insensitive FS can't admit two
        # lanes on one file — see _tree.py), but folding preserves distinctness:
        # `docs/ui-` != `docs/svc-`. The filename-prefix discrimination trick is
        # unaffected because it discriminates on the SPELLING, not the case.
        assert norm_tree_prefix("docs/UI-*") == "docs/ui-"
        assert norm_tree_prefix("docs/SVC-*") == "docs/svc-"
        assert norm_tree_prefix("docs/UI-*") != norm_tree_prefix("docs/SVC-*")

    def test_docs_only_trees_are_disjoint(self):
        # The docs halves alone are disjoint — neither normalized prefix is a
        # prefix of the other — so frontend's docs and backend's docs never
        # overlap despite sharing the `docs/` parent.
        assert lane_trees_disjoint(["docs/UI-*"], ["docs/SVC-*"])
        # ...and a BARE `docs/` would collide (the anti-pattern the trick avoids).
        assert not lane_trees_disjoint(["docs/UI-*"], ["docs/"])

    def test_cluster_trees_are_disjoint(self):
        assert lane_trees_disjoint(_FE_TREE, _BE_TREE)


class TestConcurrencyAdmission:
    def test_frontend_acquires_when_alone(self):
        d = _arb(requested_lane="frontend", requested_kind="cluster",
                 requested_tree=_FE_TREE)
        assert d.outcome == "acquire"
        assert d.lane == "frontend"

    def test_backend_acquires_alongside_live_frontend(self):
        """The crux: a live `frontend` lease must NOT block a `backend` request —
        their trees are disjoint, so both build agents run concurrently."""
        live = [_lease("frontend", "cluster", _FE_TREE)]
        d = _arb(requested_lane="backend", requested_kind="cluster",
                 requested_tree=_BE_TREE, live_leases=live)
        assert d.outcome == "acquire", d.to_dict()
        assert d.lane == "backend"

    def test_second_frontend_cluster_rescued_onto_free_backend(self):
        """A repeat `frontend` CLUSTER request while `frontend` is held is not a
        hard refuse: the arbiter falls through to auto-pick and rescues it onto
        the still-free, tree-disjoint `backend` cluster."""
        live = [_lease("frontend", "cluster", _FE_TREE)]
        d = _arb(requested_lane="frontend", requested_kind="cluster",
                 requested_tree=_FE_TREE, live_leases=live)
        assert d.outcome == "acquire"
        assert d.lane == "backend"
        assert d.auto_picked

    def test_both_clusters_busy_refuses(self):
        """When BOTH cluster lanes are held, a further cluster request has no free
        lane to rescue onto → refuse."""
        live = [_lease("frontend", "cluster", _FE_TREE),
                _lease("backend", "cluster", _BE_TREE)]
        d = _arb(requested_lane="frontend", requested_kind="cluster",
                 requested_tree=_FE_TREE, live_leases=live)
        assert d.outcome == "refuse"

    def test_keyword_same_lane_refused_directly(self):
        """A NON-cluster (keyword) request for a held lane refuses directly —
        only cluster requests get the auto-pick rescue."""
        live = [_lease("frontend", "keyword", _FE_TREE)]
        d = _arb(requested_lane="frontend", requested_kind="keyword",
                 requested_tree=_FE_TREE, live_leases=live)
        assert d.outcome == "refuse"

    def test_release_alone_acquires(self):
        """The exclusive `release` lane, requested with no other loop live,
        acquires — an exclusive lane admits on liveness, never tree-disjointness,
        so its whole-repo `**/VERSION` glob does not block it."""
        d = _arb(requested_lane="release", requested_kind="global",
                 requested_tree=_REL_TREE)
        assert d.outcome == "acquire"
        assert d.lane == "release"

    def test_release_held_blocks_a_build(self):
        """While the exclusive `release` lane is held, a build request refuses."""
        live = [_lease("release", "global", ["**/*"])]
        d = _arb(requested_lane="frontend", requested_kind="cluster",
                 requested_tree=_FE_TREE, live_leases=live)
        assert d.outcome == "refuse"


class TestGenericDriverLoader:
    def test_resolve_workshop_by_name(self):
        cfg = _resolve_driver_config("workshop", "C:/tmp/ws")
        assert cfg.lanes is WORKSHOP_LANE_TAXONOMY

    def test_resolve_job_by_name(self):
        """Proves the loader is generic, not workshop-only: it resolves `job`'s
        factory by the same `<name>_config` convention, naming no host in code."""
        cfg = _resolve_driver_config("job", "C:/tmp/job")
        # The job taxonomy is structural-only now (dos/119, dynamic-claim-space):
        # work lanes (apply/tailor/discovery) are handles that resolve to a
        # per-pick claim host-side, NOT curated kernel trees. `C:/tmp/job` has no
        # `dos.toml`, so this gets the structural FALLBACK literal — assert its
        # `orchestration` exclusive lane (proves it resolved the JOB taxonomy, NOT
        # the generic `main`/`global` default, whose exclusive set is `global`
        # only and which has no `orchestration`).
        assert "orchestration" in cfg.lanes.exclusive
        assert "main" not in cfg.lanes.concurrent  # the generic default has `main`; job does not
        # No work lane is a curated kernel tree any more (host-side dynamic claim):
        # neither the reaped host lane `apply` nor `orchestration` (exclusive lanes
        # carry no tree — they are admitted on liveness alone, not a region).
        assert not cfg.lanes.tree_for("apply")
        assert not cfg.lanes.tree_for("orchestration")

    def test_unknown_single_token_driver_raises_valueerror(self):
        try:
            _resolve_driver_config("nope_not_a_driver", ".")
        except ValueError as e:
            assert "nope_not_a_driver" in str(e)
            assert "dos.drivers.nope_not_a_driver" in str(e)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError for an unknown driver")

    def test_dotted_or_pathy_driver_name_rejected(self):
        """A driver name is a single module token: a dotted / path-traversal name
        is rejected up front as 'unknown' (both a safety surface AND avoids the
        ModuleNotFoundError.name-aliasing that would leak a raw traceback)."""
        for bad in ("foo.bar", "../evil", r"a\b"):
            try:
                _resolve_driver_config(bad, ".")
            except ValueError as e:
                assert "single module token" in str(e)
            else:  # pragma: no cover
                raise AssertionError(f"expected ValueError for driver name {bad!r}")

    def test_driver_without_factory_raises_valueerror(self):
        """A real module under dos.drivers that exposes no `<name>_config` factory
        (e.g. `llm_judge`) is a clear error, NOT silently treated as missing."""
        try:
            _resolve_driver_config("llm_judge", ".")
        except ValueError as e:
            assert "llm_judge_config" in str(e)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError for a factory-less driver")


def _doctor(*flags, workspace="."):
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "doctor", *flags, "--workspace", str(workspace)],
        capture_output=True, text=True,
    )


class TestCliDriverFlag:
    """The `--driver` flag's effect on the doctor taxonomy, tested against an
    ISOLATED empty workspace. The driver supplies the BASE taxonomy; a workspace's
    own `dos.toml [lanes]` would layer over it (proven separately in
    `TestDosTomlLayersOverDriver`), so these tests must NOT run against a repo that
    has a `dos.toml` — `--workspace .` did, which made them flake whenever the dev
    repo carried a scaffolded `dos.toml`. A bare tmp dir has no toml, so the driver
    base shows through cleanly."""

    @pytest.fixture
    def ws(self, tmp_path):
        # An isolated workspace with NO dos.toml — the driver/generic taxonomy is
        # what doctor reports, not a repo-root toml's lanes.
        return tmp_path

    def test_doctor_driver_workshop_lists_lanes(self, ws):
        proc = _doctor("--driver", "workshop", workspace=ws)
        assert proc.returncode == 0, proc.stderr
        assert "frontend, backend" in proc.stdout
        assert "release, global" in proc.stdout

    def test_job_flag_equals_driver_job(self, ws):
        """`--job` is the back-compat alias for `--driver job`: identical lanes."""
        a = _doctor("--job", workspace=ws)
        b = _doctor("--driver", "job", workspace=ws)
        assert a.returncode == 0 and b.returncode == 0
        # The alias equivalence is the contract: `--job` and `--driver job` load
        # the SAME taxonomy, so the doctor output is identical. (The job taxonomy
        # is de-clustered — `concurrent`/`autopick` empty, 2026-06-02 — so we assert
        # the equivalence + a still-true property, the exclusive lanes, rather than
        # a now-empty concurrent-lanes line.)
        assert a.stdout == b.stdout
        assert "orchestration, global" in a.stdout

    def test_no_flag_stays_generic_default(self, ws):
        """A no-flag invocation is unregressed — the generic `main` default."""
        proc = _doctor(workspace=ws)
        assert proc.returncode == 0, proc.stderr
        assert "main" in proc.stdout
        # the job/workshop concurrent lanes must NOT appear
        assert "apply, tailor" not in proc.stdout
        assert "frontend, backend" not in proc.stdout

    def test_unknown_driver_exits_2(self, ws):
        proc = _doctor("--driver", "bogus_not_a_driver", workspace=ws)
        assert proc.returncode == 2
        assert "unknown driver" in proc.stderr


class TestDosTomlLayersOverDriver:
    def test_toml_lanes_win_over_driver_base(self, tmp_path: Path):
        """A workspace's `dos.toml [lanes]` table REPLACES the driver-supplied base
        taxonomy — proving `--driver` plugs into the four-table readback as the
        base, not as a bypass of it."""
        (tmp_path / "dos.toml").write_text(
            "[lanes]\n"
            'concurrent = ["alpha"]\n'
            'exclusive = ["global"]\n'
            'autopick = ["alpha"]\n'
            "\n[lanes.trees]\n"
            'alpha = ["alpha/**/*"]\n'
            'global = ["**/*"]\n',
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, "-m", "dos.cli", "doctor",
             "--driver", "workshop", "--workspace", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        # The TOML's `alpha` lane wins; the driver's frontend/backend are gone.
        assert "alpha" in proc.stdout
        assert "frontend, backend" not in proc.stdout
