"""The harness/ultracode arm — a foreign orchestrator driving the SAME trust seam.

This is the orchestrator-axis counterpart to `closed_loop.py`. Where `closed_loop`
is the DOS-native dispatch (one process, leases threaded in memory), this models a
harness/ultracode `Workflow` that fans out concurrent units which do NOT share
memory and coordinate ONLY through the durable lane-journal WAL (`dos lease-lane`).

Both arms call the identical kernel at the seam (`arbiter.arbitrate`,
`oracle.is_shipped`) over the identical workload + seeded failure model + real git
repo — so any measured difference is purely the orchestrator's (the honesty
invariant, lifted to this axis). The single variable is the **lease-visibility
model** and its `writeback` discipline (see `orchestrator.JournalLeaseBook`):

  * `lease_writeback=True`  — the disciplined harness: each unit writes its grant
    back to the WAL (calls `dos lease-lane acquire`) BEFORE doing work, so a sibling
    sees it and a collision is PREVENTED at contention — identical safety to the
    in-process DOS-native loop. Cell (D) reaches the in-process arm's integrity.

  * `lease_writeback=False` — the naive harness: it runs `agent({schema})` in
    `parallel()` and forgets the lease, so siblings arbitrate against a stale WAL,
    BOTH admit a colliding tree, and the collision is only DETECTED after both
    commit (a `detected-collision`, and a surviving `silent-overwrite` verify
    cannot undo). This quantifies exactly what the convenience costs.

The arm therefore answers the operator's question directly: leaning on
ultracode/Workflow for the fanout is safe **iff** the flow writes its leases back;
without that discipline it silently regresses from collision-prevention to
collision-detection. The `dos lease-lane` verb is what makes `writeback=True`
achievable in a real cross-process flow.
"""
from __future__ import annotations

import os
import dataclasses
from pathlib import Path
from typing import Callable

from dos.config import SubstrateConfig, LaneTaxonomy, default_config

from . import metrics
from .agent import FailureModel
from .metrics import Event, Metrics
from .orchestrator import (
    GitGround, JournalLeaseBook, run_fleet,
)
from .trajectory import TrajectoryStep
from .workload import Workload


def _bench_config(repo: Path, workload: Workload) -> SubstrateConfig:
    """A SubstrateConfig whose lane taxonomy = the fleet's efforts.

    Identical to `closed_loop._bench_config` (each effort is a keyword/cluster lane
    over its private subtree + the shared area), so the two arms arbitrate the same
    domain — the kernel never names these lanes, they are pure config data.
    """
    lane_trees = {e.lane: (f"{e.name}/", "shared/") for e in workload.efforts}
    lanes = tuple(e.lane for e in workload.efforts)
    taxonomy = LaneTaxonomy(
        concurrent=lanes, autopick=lanes, exclusive=(), trees=lane_trees)
    base = default_config(workspace=repo)
    return dataclasses.replace(base, lanes=taxonomy)


def run(workload: Workload, model: FailureModel, *, run_seed: int,
        kappa: float = metrics.DEFAULT_KAPPA,
        review_mu: float = metrics.DEFAULT_REVIEW_MU,
        lease_writeback: bool = True,
        sink: Callable[[TrajectoryStep], None] | None = None,
        ) -> tuple[Metrics, list[Event]]:
    """Run the harness/ultracode arm (cross-process leases via the WAL).

    `lease_writeback` is the orchestrator-discipline knob (see module docstring).
    The return shape matches `closed_loop.run` so the harness/tests treat the arms
    uniformly. `detect_after` is enabled exactly when `lease_writeback` is off — a
    lagging lease book is the only way a collision slips past the arbiter to be
    caught post-hoc.
    """
    git = GitGround()
    # the WAL the cross-process branches share — isolated to this run's temp tree.
    journal_path = git.tmp / "lane_journal.jsonl"
    prev_env = os.environ.get("DISPATCH_LANE_JOURNAL_PATH")
    os.environ["DISPATCH_LANE_JOURNAL_PATH"] = str(journal_path)
    try:
        cfg = _bench_config(git.repo, workload)
        book = JournalLeaseBook(journal_path=journal_path, writeback=lease_writeback)
        arm = f"harness-flow{'(+wb)' if lease_writeback else '(no-wb)'}"
        return run_fleet(
            workload, model, arm=arm, lease_book=book, git_repo=git, cfg=cfg,
            run_seed=run_seed, kappa=kappa, review_mu=review_mu,
            detect_after=not lease_writeback, sink=sink)
    finally:
        if prev_env is None:
            os.environ.pop("DISPATCH_LANE_JOURNAL_PATH", None)
        else:
            os.environ["DISPATCH_LANE_JOURNAL_PATH"] = prev_env
        git.close()
