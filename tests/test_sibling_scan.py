"""Tests for dos.sibling_scan — the three pure concurrency verdicts.

PURE: every test passes frozen evidence in (a RunDirState with a precomputed
`has_terminal_marker` bool, a clock via `now_epoch`/`now_ts`, caller-supplied
lane trees) and asserts the verdict. No filesystem, no clock read, no host
marker literal — the kernel half of the host's tests/test_detect_orphan_child.py
+ tests/test_dispatch_lane.py sibling-scan cases.
"""
from __future__ import annotations

from dos.sibling_scan import (
    ForeignCollisionVerdict,
    OrphanStatus,
    RunDirState,
    classify_foreign_collision,
    classify_run_dir,
    classify_sibling_scan,
    scan_for_orphan,
)

NOW = 1_000_000.0


# --- orphan sweep ----------------------------------------------------------


def test_orphan_live_child_no_terminal_marker():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=False,
                     log_mtime_epoch=NOW - 5)
    r = classify_run_dir(st, now_epoch=NOW)
    assert r.status is OrphanStatus.ORPHAN
    assert r.needs_adoption is True


def test_terminal_child_reached_closeout():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=True,
                     log_mtime_epoch=NOW - 5)
    assert classify_run_dir(st, now_epoch=NOW).status is OrphanStatus.TERMINAL


def test_dead_child_no_marker_stale_log():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=False,
                     log_mtime_epoch=NOW - 600)
    assert classify_run_dir(st, now_epoch=NOW).status is OrphanStatus.DEAD


def test_clean_current_iteration_own_child():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=False,
                     log_mtime_epoch=NOW - 5, is_current_iteration=True)
    assert classify_run_dir(st, now_epoch=NOW).status is OrphanStatus.CLEAN


def test_clean_run_dir_with_no_log_yet():
    st = RunDirState(ts="20260518T1928Z", log_present=False)
    assert classify_run_dir(st, now_epoch=NOW).status is OrphanStatus.CLEAN


def test_foreign_live_when_ts_not_in_owned_set():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=False,
                     log_mtime_epoch=NOW - 5)
    r = classify_run_dir(st, now_epoch=NOW, loop_owned_ts={"20260518T2000Z"})
    assert r.status is OrphanStatus.FOREIGN_LIVE
    assert r.needs_adoption is False


def test_orphan_when_ts_is_in_owned_set():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=False,
                     log_mtime_epoch=NOW - 5)
    r = classify_run_dir(st, now_epoch=NOW, loop_owned_ts={"20260518T1928Z"})
    assert r.status is OrphanStatus.ORPHAN


def test_no_owned_set_degrades_to_orphan():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=False,
                     log_mtime_epoch=NOW - 5)
    assert classify_run_dir(st, now_epoch=NOW).status is OrphanStatus.ORPHAN


def test_empty_owned_set_means_every_live_dir_is_foreign():
    st = RunDirState(ts="20260518T1928Z", has_terminal_marker=False,
                     log_mtime_epoch=NOW - 5)
    r = classify_run_dir(st, now_epoch=NOW, loop_owned_ts=set())
    assert r.status is OrphanStatus.FOREIGN_LIVE


def test_sweep_separates_orphans_foreign_and_summary():
    dirs = [
        RunDirState(ts="A", has_terminal_marker=False, log_mtime_epoch=NOW - 5),
        RunDirState(ts="B", has_terminal_marker=False, log_mtime_epoch=NOW - 5),
        RunDirState(ts="C", has_terminal_marker=True, log_mtime_epoch=NOW - 5),
    ]
    sweep = scan_for_orphan(dirs, now_epoch=NOW, loop_owned_ts={"A"})
    assert sweep.has_orphan and sweep.has_foreign_live
    assert [o.ts for o in sweep.orphans] == ["A"]
    assert [f.ts for f in sweep.foreign_live] == ["B"]
    assert "ADOPT: A" in sweep.summary and "FOREIGN: B" in sweep.summary


def test_sweep_empty_is_clean():
    sweep = scan_for_orphan([], now_epoch=NOW)
    assert not sweep.has_orphan
    assert sweep.summary == "no child run-dirs to scan — clean"


def test_dict_evidence_coerced():
    r = classify_run_dir(
        {"ts": "D", "has_terminal_marker": True}, now_epoch=NOW)
    assert r.status is OrphanStatus.TERMINAL


# --- foreign-collision verdict --------------------------------------------


def _lookup(table):
    return lambda lane: table.get(lane)


def test_foreign_collision_none_when_no_foreign():
    r = classify_foreign_collision(foreign=[], my_tree=["a/**"], lane_tree_lookup=_lookup({}))
    assert r.verdict is ForeignCollisionVerdict.NONE


def test_foreign_collision_safe_when_disjoint():
    r = classify_foreign_collision(
        foreign=[("ts1", "tailor")], my_tree=["apply/**"],
        lane_tree_lookup=_lookup({"tailor": ["tailor/**"]}))
    assert r.verdict is ForeignCollisionVerdict.SAFE_CONCURRENT


def test_foreign_collision_when_trees_overlap():
    r = classify_foreign_collision(
        foreign=[("ts1", "apply2")], my_tree=["apply/**"],
        lane_tree_lookup=_lookup({"apply2": ["apply/sub/**"]}))
    assert r.verdict is ForeignCollisionVerdict.COLLISION
    assert r.colliding_ts == "ts1"


def test_foreign_collision_exclusive_lane_always_collides():
    r = classify_foreign_collision(
        foreign=[("ts1", "global")], my_tree=["apply/**"],
        lane_tree_lookup=_lookup({}))
    assert r.verdict is ForeignCollisionVerdict.COLLISION


def test_foreign_collision_unknown_tree_refuses():
    r = classify_foreign_collision(
        foreign=[("ts1", "mystery")], my_tree=["apply/**"],
        lane_tree_lookup=_lookup({}))   # mystery -> None -> empty
    assert r.verdict is ForeignCollisionVerdict.COLLISION


def test_foreign_collision_unknown_own_tree_refuses():
    r = classify_foreign_collision(
        foreign=[("ts1", "tailor")], my_tree=[],
        lane_tree_lookup=_lookup({"tailor": ["tailor/**"]}))
    assert r.verdict is ForeignCollisionVerdict.COLLISION


# --- un-leased sibling scan ------------------------------------------------

NOW_TS = 2_000_000.0
POOL = ["apply", "tailor", "discovery"]


def _sib(ts, lane, *, scope="cluster/keyword", completed=False, fresh=True):
    return {
        "ts": ts, "lane": lane, "scope": scope, "completed": completed,
        "newest_log_mtime": NOW_TS - (60 if fresh else 100_000),
    }


def test_sibling_clear_when_none_live():
    r = classify_sibling_scan(
        siblings=[], leased_ts=set(), invoked_bare=True, now_ts=NOW_TS,
        free_lane_pool=POOL)
    assert r.verdict == "clear"


def test_sibling_leased_one_ignored():
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts={"S1"}, invoked_bare=True,
        now_ts=NOW_TS, free_lane_pool=POOL)
    assert r.verdict == "clear"


def test_sibling_stale_one_ignored():
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply", fresh=False)], leased_ts=set(),
        invoked_bare=True, now_ts=NOW_TS, free_lane_pool=POOL)
    assert r.verdict == "clear"


def test_bare_loop_reroutes_off_sibling_lane():
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts=set(), invoked_bare=True,
        now_ts=NOW_TS, free_lane_pool=POOL)
    assert r.verdict == "reroute"
    assert "apply" not in r.free_lanes
    assert set(r.free_lanes) == {"tailor", "discovery"}


def test_exclusive_sibling_stops():
    r = classify_sibling_scan(
        siblings=[_sib("S1", "global", scope="global")], leased_ts=set(),
        invoked_bare=True, now_ts=NOW_TS, free_lane_pool=POOL)
    assert r.verdict == "stop"


def test_scoped_loop_stops_without_disjointness_proof():
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts=set(), invoked_bare=False,
        now_ts=NOW_TS, free_lane_pool=POOL)
    assert r.verdict == "stop"


def test_scoped_loop_cleared_by_disjoint_trees():
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts=set(), invoked_bare=False,
        now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["discovery/**"],
        sibling_tree_lookup=lambda lane: {"apply": ["apply/**"]}.get(lane))
    assert r.verdict == "clear"


def test_bare_loop_no_free_lane_stops():
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts=set(), invoked_bare=True,
        now_ts=NOW_TS, free_lane_pool=["apply"])
    assert r.verdict == "stop"


def test_exclusive_sibling_sorts_first():
    """An exclusive sibling wins the verdict even when a cluster sibling is also live."""
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply"), _sib("S2", "global", scope="global")],
        leased_ts=set(), invoked_bare=True, now_ts=NOW_TS, free_lane_pool=POOL)
    assert r.verdict == "stop"
    assert r.sibling_ts == "S2"


# --- bare-loop disjointness escape (2026-06-03) ----------------------------
# A BARE loop with a known auto-picked tree may run concurrently when that tree
# is provably disjoint from EVERY live sibling — mirroring the explicit-scope
# escape and the foreign-collision SAFE_CONCURRENT verdict. Before this, a bare
# loop rerouted unconditionally and (against a lane-less read-only sibling)
# never converged.

def test_bare_loop_cleared_by_disjoint_tree():
    """Bare loop with an auto-picked tree disjoint from the sibling → clear."""
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts=set(), invoked_bare=True,
        now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["discovery/**"],
        sibling_tree_lookup=lambda lane: {"apply": ["apply/**"]}.get(lane))
    assert r.verdict == "clear"
    assert "disjoint" in r.reason


def test_bare_loop_reroutes_when_tree_overlaps():
    """Bare loop whose auto-picked tree OVERLAPS a sibling → still reroute (today)."""
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts=set(), invoked_bare=True,
        now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["apply/sub/**"],
        sibling_tree_lookup=lambda lane: {"apply": ["apply/**"]}.get(lane))
    assert r.verdict == "reroute"


def test_bare_loop_reroutes_when_sibling_tree_unknown():
    """A sibling with no resolvable tree is unknown blast radius → not provably
    disjoint → reroute (conservative; the kernel never assumes empty==safe)."""
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply")], leased_ts=set(), invoked_bare=True,
        now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["discovery/**"],
        sibling_tree_lookup=lambda lane: None)   # tree never resolves
    assert r.verdict == "reroute"


def test_bare_loop_reroutes_when_sibling_lane_empty():
    """A lane-less sibling (empty lane) is unknown blast radius → reroute.
    (A read-only /replan sibling is filtered out UPSTREAM by the host, never
    waved through here on an empty tree.)"""
    r = classify_sibling_scan(
        siblings=[_sib("S1", "")], leased_ts=set(), invoked_bare=True,
        now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["discovery/**"],
        sibling_tree_lookup=lambda lane: ["apply/**"])
    assert r.verdict == "reroute"


def test_bare_loop_cleared_only_if_disjoint_from_ALL_live_siblings():
    """Disjoint from sibling[0] but OVERLAPS sibling[1] → must NOT clear.
    Checking only live[0] would corrupt the second sibling's handoff."""
    trees = {"apply": ["apply/**"], "tailor": ["tailor/**"]}
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply"), _sib("S2", "tailor")],
        leased_ts=set(), invoked_bare=True, now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["tailor/sub/**"],   # disjoint from apply, overlaps tailor
        sibling_tree_lookup=lambda lane: trees.get(lane))
    assert r.verdict == "reroute"


def test_bare_loop_cleared_when_disjoint_from_both_live_siblings():
    """Disjoint from every live sibling → clear, even with several siblings."""
    trees = {"apply": ["apply/**"], "tailor": ["tailor/**"]}
    r = classify_sibling_scan(
        siblings=[_sib("S1", "apply"), _sib("S2", "tailor")],
        leased_ts=set(), invoked_bare=True, now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["discovery/**"],
        sibling_tree_lookup=lambda lane: trees.get(lane))
    assert r.verdict == "clear"


def test_exclusive_sibling_dominates_even_with_disjoint_tree():
    """An exclusive sibling stops the loop regardless of tree disjointness —
    the exclusive check precedes the escape."""
    r = classify_sibling_scan(
        siblings=[_sib("S1", "global", scope="global")], leased_ts=set(),
        invoked_bare=True, now_ts=NOW_TS, free_lane_pool=POOL,
        requested_tree=["discovery/**"],
        sibling_tree_lookup=lambda lane: {"global": ["g/**"]}.get(lane))
    assert r.verdict == "stop"


def test_iter_index_numeric_tail():
    """MQ3X P2: iter-<n> dir-name sort key — numeric tail parses, non-numeric
    sorts last (10**9, never 0)."""
    from dos.sibling_scan import iter_index
    assert iter_index("iter-3") == 3
    assert iter_index("iter-12") == 12
    assert iter_index("iter-bogus") == 10**9
    assert iter_index("noisy") == 10**9
    # sorts correctly: malformed never masks the real highest
    names = ["iter-2", "iter-bad", "iter-10", "iter-1"]
    assert max(names, key=iter_index) == "iter-bad"  # non-numeric sorts last
    real = [n for n in names if iter_index(n) < 10**9]
    assert max(real, key=iter_index) == "iter-10"
