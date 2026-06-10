"""fleet-roll — fold a whole `root_id` tree of run digests into ONE fleet verdict (docs/179 #3).

> **An HONEST AGGREGATOR, not a label factory.** It folds N per-run `StatusDigest`s
> (each already adjudicated, docs/120) into one fleet headline + a per-branch
> breakdown. It mints ZERO new ground-truth labels — every digest it folds was
> already computable by `dos status <run_id>`; this batches them into one operator
> call. That honesty is load-bearing: re-counting the N already-adjudicated digests
> as "N new labels" would be the consistency-not-grounding sin (docs/179's design
> law). The data-multiplier in the docs/179 set is `firing_label`, not this.**

What it IS: the missing cross-run fold (docs/120 Phase 2-4 — no verb folds N runs
into one `FleetState` today). A fan-out spawns many runs under one `root_id` (the
`run_id` spine's tree). An operator wants one answer — "of the 12 runs under this
root, 9 COMPLETE, 2 SPINNING, 1 DIVERGED; the failing branch is run X under parent
Y" — instead of 12 separate `dos status` calls. This is that fold.

Two honest design constraints the review pinned, both obeyed here:

  1. **Two disjoint enums must collapse to ONE FleetState before folding.** A digest
     carries a `liveness` (`Liveness`: ADVANCING/SPINNING/STALLED) AND a `resume`
     (`Resume`: RESUMABLE/COMPLETE/DIVERGED/UNRESUMABLE, None while live). The
     worst-first rollup (`verdict_rollup`) ranks ONE status vocabulary, so each
     digest is collapsed to a single `FleetState` string FIRST (`fleet_state_of`),
     governed by the terminal `resume` verdict when the run has stopped, else by the
     live `liveness`. `verdict_rollup` then contributes only the worst-first `min`
     and the counts string — it interprets no status semantics.

  2. **Spawn-lineage ≠ logical dependency (the docs/179 corollary).** `parent_id` is
     the run that SPAWNED this one (a process edge), NOT "this run depends on that
     one." So the per-branch breakdown groups by spawn-parent for DISPLAY/attribution
     only ("which subtree is failing") — it NEVER gates a refusal or deprioritizes a
     lane on the strength of a parent→child edge. A failing child does not condemn its
     parent; the grouping is a lens, not a dependency verdict.

The I/O is the CALLER'S (the docs/179 review's corrected cost model): gathering the
N digests is N+1 `build_trace`-class reads + N liveness/resume evidence gathers at
the CLI boundary — `trace.build_trace(root).descendants` returns run_id STRINGS, not
digests, so the boundary must build a digest per descendant. `fleet_roll` itself is
PURE: digests in, `FleetRoll` out, zero I/O — the `status.status_digest` /
`verdict_rollup.rollup` posture.

⚓ Kernel discipline (the litmus): PURE Layer-1 leaf — imports only sibling kernel
modules (`status`, `verdict_rollup`) + stdlib, names no host/driver, carries no
policy (the severity order is a module constant, the closed-enum-as-data seam).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dos.status import StatusDigest
from dos.verdict_rollup import StatusRank, VerdictRollup, rollup

# The durable_schema floor (docs/116 §6): a FleetRoll is a record a dashboard / peer
# reads, so it carries a schema tag.
FLEET_ROLL_SCHEMA = 1


# ---------------------------------------------------------------------------
# The collapsed FleetState — the ONE worst-first vocabulary the rollup ranks.
# Smaller rank == more severe (the `verdict_rollup.StatusRank` convention: the worst
# is the `min`). The order interleaves the two source enums by operator severity.
# ---------------------------------------------------------------------------
DIVERGED = "DIVERGED"        # resume: ground truth moved past the resume point — needs a human
STALLED = "STALLED"          # liveness: no heartbeat, no commits — dead/hung
UNRESUMABLE = "UNRESUMABLE"  # resume: no intent / corrupt / too-new — cannot recover
SPINNING = "SPINNING"        # liveness: alive but state not moving
RESUMABLE = "RESUMABLE"      # resume: clean resume-point + residual — continue from here
ADVANCING = "ADVANCING"      # liveness: ground-truth state moved — healthy, in flight
COMPLETE = "COMPLETE"        # resume: every declared step verified — done
UNKNOWN = "UNKNOWN"          # a malformed/unreadable digest — refuse, don't optimism

# Worst-first severity order (smaller = worse). The fold's headline is the worst
# FleetState across the tree, so a single DIVERGED branch dominates a sea of COMPLETE.
# COMPLETE is the LEAST-severe (highest rank) — `verdict_rollup.all_clean` treats the
# max-rank status as "nothing to act on", so a fleet is clean iff every run COMPLETE.
# UNKNOWN (a malformed/unreadable digest) is a genuine problem and ranks SEVERE
# (just below DIVERGED), never "clean" — an unreadable run is not a finished run.
_FLEET_ORDER = {
    DIVERGED: 0,
    UNKNOWN: 1,
    STALLED: 2,
    UNRESUMABLE: 3,
    SPINNING: 4,
    RESUMABLE: 5,
    ADVANCING: 6,
    COMPLETE: 7,
}

# The rank handed to `verdict_rollup`: UNKNOWN is both the unrankable fallback and
# the "requested but absent" status (a descendant we expected but got no digest for).
FLEET_RANK = StatusRank(order=_FLEET_ORDER, unknown_status=UNKNOWN, absent_status=UNKNOWN)


def fleet_state_of(digest: StatusDigest) -> str:
    """Collapse one digest's two disjoint verdicts to a single FleetState string. PURE.

    A STOPPED run (it has a `resume` verdict) is governed by that terminal verdict —
    the resume verdict is the run's last word (COMPLETE/DIVERGED/RESUMABLE/UNRESUMABLE).
    A LIVE run (resume is None) is governed by its `liveness` (ADVANCING/SPINNING/
    STALLED). A digest whose verdict value is outside the known set degrades to
    UNKNOWN (the fail-safe — an unranked status never masquerades as the worst).
    """
    if digest.resume is not None:
        val = digest.resume.verdict.value
        return val if val in _FLEET_ORDER else UNKNOWN
    val = digest.liveness.verdict.value
    return val if val in _FLEET_ORDER else UNKNOWN


# ---------------------------------------------------------------------------
# The per-branch breakdown + the fleet roll.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BranchRoll:
    """One spawn-subtree's roll — the runs grouped under one spawn-parent (DISPLAY only).

    `parent_id` is the spawn edge the runs share (NOT a dependency edge — docs/179
    corollary). `subtree` is the worst-first rollup over that branch's FleetStates.
    The attribution ("which subtree is failing") is a lens for the operator, never a
    condemnation of the parent.
    """

    parent_id: str
    subtree: VerdictRollup

    @property
    def worst_status(self) -> Optional[str]:
        return self.subtree.worst_status

    def to_dict(self) -> dict:
        return {"parent_id": self.parent_id, "subtree": self.subtree.to_dict()}


@dataclass(frozen=True)
class FleetRoll:
    """The whole `root_id` tree folded into one fleet verdict + per-branch breakdown.

    `root_id` names the tree. `rollup` is the worst-first fold over EVERY run's
    FleetState (the headline + counts). `branches` is the per-spawn-parent breakdown
    (display attribution). `absent` lists descendants that were expected (in the
    lineage) but produced no digest — surfaced as a first-class UNKNOWN, never a
    silently-dropped row (the `verdict_rollup` anti-drift feature).
    """

    root_id: str
    rollup: VerdictRollup
    branches: tuple[BranchRoll, ...] = ()
    absent: tuple[str, ...] = ()
    schema: int = FLEET_ROLL_SCHEMA

    @property
    def worst_status(self) -> Optional[str]:
        """The single most-severe FleetState across the whole tree."""
        return self.rollup.worst_status

    @property
    def all_clean(self) -> bool:
        """True iff every run is COMPLETE (the least-severe rank) — nothing to act on."""
        return self.rollup.all_clean

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "root_id": self.root_id,
            "worst_status": self.worst_status,
            "all_clean": self.all_clean,
            "reason": self.rollup.reason,
            "rollup": self.rollup.to_dict(),
            "branches": [b.to_dict() for b in self.branches],
            "absent": list(self.absent),
        }


def _item(digest: StatusDigest):
    """A rollup item dict for one digest — its run_id keyed to its FleetState. PURE."""
    return {
        "key": digest.run_id,
        "status": fleet_state_of(digest),
        "reason": digest.liveness.reason if digest.resume is None else digest.resume.reason,
    }


def fleet_roll(
    digests,
    *,
    root_id: str = "",
    parent_of=None,
    absent=None,
) -> FleetRoll:
    """Fold a tree of run digests into one fleet verdict + per-branch breakdown. PURE.

    `digests` is any iterable of `StatusDigest` (gathered at the caller boundary, one
    per run in the tree). `root_id` names the tree (display). `parent_of` is an
    optional `run_id -> parent_id` map for the per-branch grouping (the spawn edge,
    display attribution only); when absent, no branch breakdown is produced (the
    top-level rollup still folds every run). `absent` is the run_ids that were in the
    lineage but produced no digest — surfaced as first-class UNKNOWN rows.

    Returns a `FleetRoll` whose top `rollup` is the worst-first fold over every run's
    FleetState. No I/O: the digests + the parent map are pre-gathered, the
    `verdict_rollup.rollup` / `status` posture.
    """
    digests = list(digests)
    absent = list(absent or ())
    items = [_item(d) for d in digests]

    top = rollup(items, rank=FLEET_RANK, label=f"fleet:{root_id or '?'}", absent=absent)

    branches: list[BranchRoll] = []
    if parent_of is not None:
        by_parent: dict[str, list[dict]] = {}
        for d in digests:
            pid = str(parent_of(d.run_id) or "")
            by_parent.setdefault(pid, []).append(_item(d))
        for pid in sorted(by_parent):
            sub = rollup(by_parent[pid], rank=FLEET_RANK, label=f"branch:{pid or '(root)'}")
            branches.append(BranchRoll(parent_id=pid, subtree=sub))

    return FleetRoll(
        root_id=root_id,
        rollup=top,
        branches=tuple(branches),
        absent=tuple(absent),
    )
