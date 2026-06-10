"""docs/179 #3 — `dos.fleet_roll`: fold a root_id tree of run digests into ONE verdict.

An HONEST AGGREGATOR (0 new labels): it batches N already-adjudicated `StatusDigest`s
into one fleet headline + per-branch breakdown. The tests pin: (a) the two disjoint
verdict enums (Liveness / Resume) collapse to one worst-first FleetState; (b) a single
DIVERGED branch dominates a sea of COMPLETE (the worst-first headline); (c) the
per-branch grouping is spawn-lineage DISPLAY only; (d) absent descendants surface as
first-class UNKNOWN, never silently dropped.
"""

from __future__ import annotations

from dos import fleet_roll as fr
from dos.fleet_roll import (
    ADVANCING,
    COMPLETE,
    DIVERGED,
    SPINNING,
    UNKNOWN,
    fleet_roll,
    fleet_state_of,
)
from dos.liveness import Liveness, LivenessVerdict, ProgressEvidence
from dos.resume import Resume, ResumePlan
from dos.status import StatusDigest, status_digest
from dos.intent_ledger import LedgerState


def _ev():
    return ProgressEvidence(run_started_ms=0, now_ms=1000, commits_since_start=0)


def _live(state: Liveness) -> LivenessVerdict:
    return LivenessVerdict(verdict=state, reason=f"{state.value} (test)", evidence=_ev())


def _resume(state: Resume, run_id="RID-x") -> ResumePlan:
    return ResumePlan(verdict=state, reason=f"{state.value} (test)", run_id=run_id)


def _digest(run_id, *, live=Liveness.ADVANCING, resume=None) -> StatusDigest:
    """A digest: a LIVE run passes resume=None (governed by liveness); a STOPPED run
    passes a Resume state (governed by the terminal resume verdict)."""
    return status_digest(
        run_id=run_id,
        ledger_state=LedgerState(run_id=run_id),
        liveness_verdict=_live(live),
        resume_plan=(_resume(resume, run_id) if resume is not None else None),
    )


# ==========================================================================
# fleet_state_of — the two-enum collapse.
# ==========================================================================
def test_live_run_governed_by_liveness():
    assert fleet_state_of(_digest("R", live=Liveness.SPINNING)) == SPINNING
    assert fleet_state_of(_digest("R", live=Liveness.ADVANCING)) == ADVANCING


def test_stopped_run_governed_by_resume():
    """A run with a resume verdict is governed by it, NOT its (now stale) liveness."""
    d = _digest("R", live=Liveness.ADVANCING, resume=Resume.DIVERGED)
    assert fleet_state_of(d) == DIVERGED
    d2 = _digest("R", live=Liveness.SPINNING, resume=Resume.COMPLETE)
    assert fleet_state_of(d2) == COMPLETE


# ==========================================================================
# fleet_roll — the worst-first headline.
# ==========================================================================
def test_one_diverged_branch_dominates_a_sea_of_complete():
    """The headline is the WORST FleetState across the tree: a single DIVERGED run
    makes the whole fleet DIVERGED, even amid many COMPLETE runs."""
    digests = [_digest(f"R{i}", resume=Resume.COMPLETE) for i in range(11)]
    digests.append(_digest("R-bad", resume=Resume.DIVERGED))
    roll = fleet_roll(digests, root_id="ROOT")
    assert roll.worst_status == DIVERGED
    assert not roll.all_clean


def test_all_complete_is_clean():
    digests = [_digest(f"R{i}", resume=Resume.COMPLETE) for i in range(5)]
    roll = fleet_roll(digests, root_id="ROOT")
    assert roll.worst_status == COMPLETE
    assert roll.all_clean


def test_counts_reason_is_worst_first():
    digests = [
        _digest("a", resume=Resume.COMPLETE),
        _digest("b", resume=Resume.COMPLETE),
        _digest("c", live=Liveness.SPINNING),
        _digest("d", resume=Resume.DIVERGED),
    ]
    roll = fleet_roll(digests, root_id="ROOT")
    # worst-first: DIVERGED before SPINNING before COMPLETE
    assert roll.rollup.reason.index("DIVERGED") < roll.rollup.reason.index("SPINNING")
    assert roll.rollup.reason.index("SPINNING") < roll.rollup.reason.index("COMPLETE")


# ==========================================================================
# per-branch breakdown — spawn-lineage DISPLAY grouping.
# ==========================================================================
def test_branch_breakdown_groups_by_spawn_parent():
    digests = [
        _digest("c1", resume=Resume.COMPLETE),
        _digest("c2", resume=Resume.DIVERGED),
        _digest("c3", resume=Resume.COMPLETE),
    ]
    parent = {"c1": "P1", "c2": "P1", "c3": "P2"}
    roll = fleet_roll(digests, root_id="ROOT", parent_of=parent.get)
    branches = {b.parent_id: b for b in roll.branches}
    assert set(branches) == {"P1", "P2"}
    # P1 holds the DIVERGED child → that branch's worst is DIVERGED (the failing subtree).
    assert branches["P1"].worst_status == DIVERGED
    assert branches["P2"].worst_status == COMPLETE


def test_no_parent_map_means_no_branches_but_still_rolls():
    digests = [_digest("a", resume=Resume.COMPLETE)]
    roll = fleet_roll(digests, root_id="ROOT")
    assert roll.branches == ()
    assert roll.worst_status == COMPLETE


# ==========================================================================
# absent descendants — first-class UNKNOWN, never silently dropped.
# ==========================================================================
def test_absent_descendant_surfaces_as_unknown():
    digests = [_digest("present", resume=Resume.COMPLETE)]
    roll = fleet_roll(digests, root_id="ROOT", absent=["missing-1"])
    assert "missing-1" in roll.absent
    # the absent run is a first-class UNKNOWN row in the rollup (anti-drift)
    keys = {it.key: it for it in roll.rollup.items}
    assert "missing-1" in keys
    assert keys["missing-1"].status == UNKNOWN
    assert keys["missing-1"].absent is True


def test_empty_fleet_rolls_clean():
    roll = fleet_roll([], root_id="ROOT")
    assert roll.worst_status is None
    assert roll.all_clean  # nothing to act on


# ==========================================================================
# to_dict — the --json A2A contract.
# ==========================================================================
def test_to_dict_round_trips_the_headline():
    roll = fleet_roll(
        [_digest("a", resume=Resume.DIVERGED), _digest("b", resume=Resume.COMPLETE)],
        root_id="ROOT", parent_of={"a": "P", "b": "P"}.get,
    )
    d = roll.to_dict()
    assert d["root_id"] == "ROOT"
    assert d["worst_status"] == DIVERGED
    assert d["schema"] == fr.FLEET_ROLL_SCHEMA
    assert d["branches"][0]["parent_id"] == "P"
