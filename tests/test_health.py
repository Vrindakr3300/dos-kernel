"""Tests for the pre-dispatch lane-health gate (`dos.health`).

The incident these pin (2026-06-01): a `/dispatch-loop` auto-picked a lane and
burned ~$9 / ~40 min launching a full `/dispatch` child only to discover two
blockers knowable at second zero — (1) the lane's last 8 runs all failed on the
same renderer sidecar-drop, and (2) the lane structurally overlapped a live
sibling lease. `lane_health` is the gate that catches both BEFORE the launch.
"""
from __future__ import annotations

from dos.health import (
    HealthAction,
    RunRecord,
    collect_lane_history,
    lane_health,
    parse_archive_subject,
)


def _blocker(ts: str, cause: str, ordinal: int = 0, verdict: str = "ERROR") -> RunRecord:
    return RunRecord(ts, verdict, cause, ordinal, f"archive {ts} — {cause}")


def _ship(ts: str) -> RunRecord:
    return RunRecord(ts, "SHIPPED", "clean ship", 0, f"archive {ts} — shipped")


# ── the overlap path (priority 1) ───────────────────────────────────────────
class TestOverlapBlock:
    TAILOR_LEASE = {
        "lane": "tailor", "lane_kind": "cluster", "loop_ts": "20260601T204136Z",
        "tree": ["agents/tailor_*.py", "agents/tailor_steps/", "templates/"],
    }
    TM_TREE = [
        "agents/tailor_*.py", "agents/tailor_steps/__init__.py",
        "job_search/skill_alignment.py", "scripts/audit_tm0_baseline.py",
    ]

    def test_tm_over_tailor_is_overlap_block(self):
        # THE INCIDENT: TM auto-picked while tailor lease live → guaranteed wedge.
        v = lane_health(
            "TM", lane_tree=self.TM_TREE, live_leases=[self.TAILOR_LEASE],
            history=[], own_lease_ts="20260601T204326Z",
        )
        assert v.action == HealthAction.OVERLAP_BLOCK
        assert v.overlap_lane == "tailor"
        assert "tailor" in v.reason

    def test_overlap_beats_history(self):
        # Even with a recurring-blocker history, overlap is the higher-priority
        # route (starting into an overlap is the worse failure).
        hist = [_blocker("20260601T204326Z", "renderer sidecar drop", 6)]
        v = lane_health(
            "TM", lane_tree=self.TM_TREE, live_leases=[self.TAILOR_LEASE],
            history=hist, own_lease_ts="20260601T204326Z",
        )
        assert v.action == HealthAction.OVERLAP_BLOCK

    def test_own_lease_never_self_blocks(self):
        own = {**self.TAILOR_LEASE, "lane": "TM", "loop_ts": "MINE"}
        v = lane_health(
            "TM", lane_tree=self.TM_TREE, live_leases=[own],
            history=[], own_lease_ts="MINE",
        )
        assert v.action == HealthAction.PROCEED

    def test_same_lane_not_treated_as_overlap(self):
        # A lease on the SAME lane is the arbiter's concern, not an overlap.
        sibling = {**self.TAILOR_LEASE, "lane": "TM", "loop_ts": "OTHER"}
        v = lane_health(
            "TM", lane_tree=self.TM_TREE, live_leases=[sibling],
            history=[], own_lease_ts="MINE",
        )
        assert v.action == HealthAction.PROCEED

    def test_disjoint_lease_proceeds(self):
        disjoint = {
            "lane": "discovery", "lane_kind": "cluster", "loop_ts": "D",
            "tree": ["agents/discovery_*.py", "go/internal/ui/"],
        }
        v = lane_health(
            "TM", lane_tree=self.TM_TREE, live_leases=[disjoint],
            history=[], own_lease_ts="MINE",
        )
        assert v.action == HealthAction.PROCEED

    def test_unknown_blast_radius_lease_proceeds(self):
        # A lease with an empty tree is the arbiter's unknown-blast-radius case;
        # the health gate does not block on it.
        empty = {"lane": "x", "lane_kind": "keyword", "loop_ts": "E", "tree": []}
        v = lane_health(
            "TM", lane_tree=self.TM_TREE, live_leases=[empty],
            history=[], own_lease_ts="MINE",
        )
        assert v.action == HealthAction.PROCEED


# ── the recurring-blocker history path (priority 2) ──────────────────────────
class TestRecurringBlockerRoute:
    def test_three_same_cause_blockers_route_unstick(self):
        hist = [
            _blocker("20260601T2003Z", "renderer .prompts.json sidecar drop"),
            _blocker("20260601T2002Z", "renderer sidecar drop preflight refuse"),
            _blocker("20260601T2001Z", "renderer-sidecar-drop OC4 refuse"),
        ]
        v = lane_health("apply", lane_tree=["agents/apply_*.py"],
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.ROUTE_UNSTICK
        assert v.cause_key == "renderer_sidecar_drop"
        assert v.blocker_runs == 3

    def test_recurrence_ordinal_trips_even_with_one_matched_run(self):
        # The "6th-consecutive" ordinal is itself a recurrence signal — one run
        # carrying it should route even if the window only captured that one.
        hist = [_blocker("20260601T2003Z",
                         "on 6th-consecutive renderer sidecar drop", ordinal=6)]
        v = lane_health("TM", lane_tree=["agents/tailor_*.py"],
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.ROUTE_UNSTICK
        assert v.cause_key == "renderer_sidecar_drop"

    def test_below_threshold_proceeds(self):
        hist = [
            _blocker("20260601T2002Z", "stale claim false block"),
            _blocker("20260601T2001Z", "ship oracle false positive"),
        ]
        # two DIFFERENT causes, neither reaching 3 → proceed
        v = lane_health("apply", lane_tree=["agents/apply_*.py"],
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.PROCEED

    def test_recovered_lane_proceeds(self):
        # A shipping run NEWER than the blockers means the lane recovered — the
        # stale blocker history must not false-route.
        hist = [
            _ship("20260601T2100Z"),
            _blocker("20260601T2000Z", "renderer sidecar drop", ordinal=6),
            _blocker("20260601T1900Z", "renderer sidecar drop", ordinal=5),
            _blocker("20260601T1800Z", "renderer sidecar drop", ordinal=4),
        ]
        v = lane_health("apply", lane_tree=["agents/apply_*.py"],
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.PROCEED

    def test_soak_gated_cause_routes_replan(self):
        hist = [
            _blocker("20260601T2003Z", "auth lane soak-gated through 2026-06-05", verdict="BLOCKED"),
            _blocker("20260601T2002Z", "soak-gated, nothing dispatchable", verdict="BLOCKED"),
            _blocker("20260601T2001Z", "soak window not yet open", verdict="BLOCKED"),
        ]
        v = lane_health("auth", lane_tree=["agents/auth_*.py"],
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.ROUTE_REPLAN

    def test_empty_history_proceeds(self):
        v = lane_health("apply", lane_tree=["agents/apply_*.py"],
                        live_leases=[], history=[], own_lease_ts="X")
        assert v.action == HealthAction.PROCEED
        assert v.should_proceed is True


# ── the post-STOP-respawn guard (priority 2) ─────────────────────────────────
def _stop_unstick(ts: str, reason_class: str = "APPLY_LANE_BLOCKED_MESH") -> RunRecord:
    """A realistic /dispatch-loop STOP archive that routed to /unstick."""
    subj = (f"docs/dispatch-loop: archive {ts} — 2 iters (1 dispatch, 1 replan), "
            f"0 picks; STOP recurring BLOCKED ({reason_class}) → /unstick")
    return RunRecord(ts, "", subj.split("—", 1)[1].strip(), 0, subj)


def _stop_replan_only(ts: str) -> RunRecord:
    """A STOP that routed only to /replan (stamp-drift halt) — must NOT trip the
    post-STOP-respawn /unstick guard."""
    subj = (f"docs/dispatch-loop: archive {ts} — 3 iters, 0 picks; "
            f"STOP recurring STALE_STAMP_LANE_DRAINED → /replan")
    return RunRecord(ts, "", subj.split("—", 1)[1].strip(), 0, subj)


def _operator_action(ts: str) -> RunRecord:
    subj = f"fix(apply): land mesh predicate operator-action: clears APPLY_LANE STOP {ts}"
    return RunRecord(ts, "", subj, 0, subj)


class TestPostStopRespawn:
    APPLY_TREE = ["agents/apply_*.py"]

    def test_first_respawn_after_stop_unstick_routes_unstick(self):
        # THE DOOM-LOOP: a STOP→/unstick is the newest meaningful event and the
        # loop is respawning the lane anyway. Trip on the FIRST respawn.
        hist = [_stop_unstick("20260602T155843Z", "APPLY_LANE_POST_UNSTICK_STOP_RESPAWN")]
        v = lane_health("apply", lane_tree=self.APPLY_TREE,
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.ROUTE_UNSTICK
        assert v.cause_key == "post_stop_respawn_no_operator_action"
        assert v.blocker_runs == 1
        assert "STOP" in v.reason

    def test_ship_newer_than_stop_clears_it(self):
        # A shipping run AFTER the STOP means the lane recovered → proceed.
        hist = [_ship("20260602T160000Z"),
                _stop_unstick("20260602T155843Z")]
        v = lane_health("apply", lane_tree=self.APPLY_TREE,
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.PROCEED

    def test_operator_action_newer_than_stop_clears_it(self):
        # An explicit operator-action commit AFTER the STOP answers the directive.
        hist = [_operator_action("20260602T160000Z"),
                _stop_unstick("20260602T155843Z")]
        v = lane_health("apply", lane_tree=self.APPLY_TREE,
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.PROCEED

    def test_stop_routed_to_replan_only_does_not_trip_unstick_guard(self):
        # A /replan-only STOP is a stamp-drift halt; the post-STOP /unstick guard
        # must not fire (it would mis-route a self-healing drift to /unstick).
        # One such record alone → falls through to PROCEED (below recurring thr).
        hist = [_stop_replan_only("20260602T154047Z")]
        v = lane_health("discovery", lane_tree=["agents/discovery_*.py"],
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.PROCEED

    def test_overlap_still_beats_post_stop_respawn(self):
        # Priority 1 (overlap) must still win over priority 2 (post-STOP).
        tailor_lease = {
            "lane": "tailor", "lane_kind": "cluster", "loop_ts": "20260601T204136Z",
            "tree": ["agents/apply_*.py"],  # collides with APPLY_TREE
        }
        hist = [_stop_unstick("20260602T155843Z")]
        v = lane_health("apply", lane_tree=self.APPLY_TREE,
                        live_leases=[tailor_lease], history=hist, own_lease_ts="MINE")
        assert v.action == HealthAction.OVERLAP_BLOCK

    def test_stop_then_older_blockers_still_post_stop_not_recurring(self):
        # A STOP→/unstick newest, with older same-cause blockers behind it: the
        # post-STOP rule (priority 2) fires first, before the recurring rule.
        hist = [
            _stop_unstick("20260602T1600Z", "APPLY_LANE_BLOCKED_MESH"),
            _blocker("20260602T1500Z", "apply lane blocked mesh", verdict="BLOCKED"),
            _blocker("20260602T1400Z", "apply lane blocked mesh", verdict="BLOCKED"),
        ]
        v = lane_health("apply", lane_tree=self.APPLY_TREE,
                        live_leases=[], history=hist, own_lease_ts="X")
        assert v.action == HealthAction.ROUTE_UNSTICK
        assert v.cause_key == "post_stop_respawn_no_operator_action"

    def test_real_archive_subject_parses_and_trips(self):
        # End-to-end: a verbatim in-the-wild STOP subject through the parser.
        subject = ("docs/dispatch-loop: archive 20260602T155843Z — 2 iters "
                   "(1 dispatch, 1 replan), 0 picks; STOP recurring BLOCKED "
                   "(APPLY_LANE_POST_UNSTICK_STOP_RESPAWN) → /unstick")
        rec = parse_archive_subject(subject, "apply")
        assert rec is not None
        assert rec.is_stop_with_unstick is True
        v = lane_health("apply", lane_tree=self.APPLY_TREE,
                        live_leases=[], history=[rec], own_lease_ts="X")
        assert v.action == HealthAction.ROUTE_UNSTICK


# ── the I/O wrapper: archive-subject parsing ─────────────────────────────────
class TestParseArchiveSubject:
    def test_parses_per_dispatch_verdict(self):
        s = ("docs/dispatch: archive 20260601T204054Z — next-up-2026-06-01-12 "
             "→ verdict=ERROR, child2 OC4-refused (.prompts.json sidecar drop, "
             "8th recurrence)")
        r = parse_archive_subject(s, "")
        assert r is not None
        assert r.run_ts == "20260601T204054Z"
        assert r.verdict == "ERROR"
        assert r.recurrence_ordinal == 8
        assert r.is_blocker

    def test_parses_dispatch_loop_lane(self):
        s = ("docs/dispatch-loop: archive 20260601T204326Z — 1 iter "
             "(1 dispatch, 0 replan), 0 picks shipped (TM lane; child1 picked "
             "TM5 but verdict=ERROR on 6th-consecutive renderer sidecar-drop)")
        r = parse_archive_subject(s, "TM")
        assert r is not None
        assert r.verdict == "ERROR"
        assert r.recurrence_ordinal == 6

    def test_lane_filter_rejects_other_lane(self):
        s = ("docs/dispatch-loop: archive 20260601T204020Z — 1 iter, 0 picks "
             "shipped (EV lane; renderer dropped sidecar 7th-consecutive)")
        assert parse_archive_subject(s, "TM") is None
        assert parse_archive_subject(s, "EV") is not None

    def test_non_archive_returns_none(self):
        assert parse_archive_subject("docs/findings-queue: FQ-423 …", "") is None

    def test_collect_respects_window_and_order(self):
        lines = [
            "aaa111 docs/dispatch: archive 20260601T2005Z — x → verdict=ERROR a",
            "bbb222 docs/dispatch: archive 20260601T2004Z — x → verdict=ERROR b",
            "ccc333 docs/findings-queue: noise",
            "ddd444 docs/dispatch: archive 20260601T2003Z — x → verdict=SHIPPED c",
        ]
        recs = collect_lane_history("", git_log_lines=lines, window=2)
        assert len(recs) == 2
        assert recs[0].run_ts == "20260601T2005Z"  # newest-first preserved
        assert recs[1].run_ts == "20260601T2004Z"
