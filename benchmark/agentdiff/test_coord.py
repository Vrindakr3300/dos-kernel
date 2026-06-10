"""Tests for F3 — the coordination A/B on Agent-Diff (docs/245 STEP 5) — $0, no model.

Pins the three layers separately so each failure names its own seam:
  * the PURE compose algebra (full-object write-back; the lost-update mechanism) — no clone;
  * the kernel arbiter invariant (same-row serialized, disjoint-row admitted) — no clone;
  * the corpus-backed frozen A/B over the REAL assertion engine — skips without the clone,
    pinned to the current dataset revision (the same convention as test_gate's 224 pin).
"""
from __future__ import annotations

import pytest

from .coord import (
    CONVERGENT_BENIGN,
    LOST_UPDATE_PREVENTED,
    TRUE_CONFLICT,
    _pinned_where_key,
    arbiter_admits,
    change_set,
    classify_pair,
    compose_final,
    net_diff,
    original_row,
    row_region,
    write_back,
    _SENTINEL_ABSENT,
)


# --- the compose algebra (pure; the lost-update mechanism itself) ------------------------

def test_write_back_is_full_object_put():
    """A write-back is the agent's SNAPSHOT plus its own changes — every other field comes
    from the snapshot. This is the PUT semantics that makes a stale snapshot a lost update."""
    snap = {"id": "X", "f1": "old1", "f2": "old2"}
    assert write_back(snap, {"f2": "new2"}) == {"id": "X", "f1": "old1", "f2": "new2"}
    # exists:false drops the field entirely
    assert write_back(snap, {"f1": _SENTINEL_ABSENT}) == {"id": "X", "f2": "old2"}


def test_naive_compose_loses_first_writers_disjoint_field():
    """THE mechanism: B's write-back computed against the ORIGINAL row reverts A's field;
    the serialized compose (B re-derived post-A) keeps both."""
    orig = {"id": "X", "f1": "old1", "f2": "old2"}
    naive = compose_final(orig, {"f1": "A"}, {"f2": "B"}, serialized=False)
    serial = compose_final(orig, {"f1": "A"}, {"f2": "B"}, serialized=True)
    assert naive == {"id": "X", "f1": "old1", "f2": "B"}    # A's write silently reverted
    assert serial == {"id": "X", "f1": "A", "f2": "B"}      # both land


def test_convergent_same_value_writes_are_benign():
    """Two writers setting the SAME field to the SAME value lose nothing in either order."""
    orig = {"id": "X", "archived": False}
    naive = compose_final(orig, {"archived": True}, {"archived": True}, serialized=False)
    serial = compose_final(orig, {"archived": True}, {"archived": True}, serialized=True)
    assert naive == serial == {"id": "X", "archived": True}


def test_net_diff_is_one_update_row_or_empty():
    orig = {"id": "X", "f": 1}
    assert net_diff("t", orig, {"id": "X", "f": 2})["updates"] == [
        {"__table__": "t", "before": {"id": "X", "f": 1}, "after": {"id": "X", "f": 2}}]
    empty = net_diff("t", orig, dict(orig))
    assert empty == {"inserts": [], "updates": [], "deletes": []}


def test_change_set_and_original_row_synthesis():
    """`expected_changes` -> the write; gold `from` -> the old value; placeholders else,
    always differing from the new value (so the engine sees a genuine change)."""
    a = {"diff_type": "changed", "entity": "channels",
         "where": {"channel_id": "C1"},
         "expected_changes": {"name": {"from": "alpha", "to": "beta"},
                              "is_archived": {"to": True},
                              "assignee": {"to": {"exists": False}},
                              "rank": {"to": {"eq": 2}}}}
    ch = change_set(a)
    assert ch["name"] == "beta" and ch["is_archived"] is True and ch["rank"] == 2
    assert ch["assignee"] is _SENTINEL_ABSENT
    orig = original_row(a["where"], a)
    assert orig["channel_id"] == "C1"
    assert orig["name"] == "alpha"            # the gold `from`
    assert orig["is_archived"] is False       # bool -> negation
    assert orig["rank"] == 3                  # number -> differs
    assert orig["assignee"] == "__orig_assignee__"  # was set; the write removes it


def test_pinned_where_key_accepts_row_selectors_rejects_predicates():
    """Row-pinned = every predicate bare-scalar or eq. Predicate regions and empty wheres
    name a SET of rows, not a row — excluded (the natural rate is a floor)."""
    assert _pinned_where_key({"identifier": {"eq": "ENG-1"}}) is not None
    assert _pinned_where_key({"channel_id": "C05ALPHA"}) is not None
    assert _pinned_where_key({}) is None
    assert _pinned_where_key({"is_dm": {"eq": True}}) is not None  # eq-pinned (still a selector)
    assert _pinned_where_key({"text": {"i_contains": "x"}}) is None
    assert _pinned_where_key({"id": {"in": ["a", "b"]}}) is None
    # eq on the SAME (entity, where) is what makes two tasks share a key; differing values differ
    assert (_pinned_where_key({"id": {"eq": "1"}}) != _pinned_where_key({"id": {"eq": "2"}}))


def test_classify_pair_truth_table():
    """The class is a pure function of the engine's four verdicts."""
    assert classify_pair(True, True, True, True) == CONVERGENT_BENIGN
    assert classify_pair(False, True, True, True) == LOST_UPDATE_PREVENTED
    assert classify_pair(True, False, True, True) == LOST_UPDATE_PREVENTED
    assert classify_pair(False, False, True, True) == LOST_UPDATE_PREVENTED
    assert classify_pair(False, True, False, True) == TRUE_CONFLICT
    assert classify_pair(False, False, False, False) == TRUE_CONFLICT


# --- the kernel arbiter invariant (the byte-same call as tau2's coord_loop) --------------

def test_arbiter_serializes_same_row_admits_disjoint():
    """The coordination floor on the Agent-Diff region grammar: a second concurrent lease on
    the SAME entity row is REFUSED; a lease on a DIFFERENT row is ADMITTED. The same invariant
    `coord_loop.smoke_synthetic` pins for tau2 reservations — one kernel, two environments."""
    region = row_region("linear", "issues", "ENG-1")
    held = [{"lane": region[0], "kind": "keyword", "tree": region, "owner": "agent-1"}]
    assert arbiter_admits(region, held) is False                  # serialized
    other = row_region("linear", "issues", "ENG-2")
    assert arbiter_admits(other, held) is True                    # disjoint, concurrent
    # cross-service rows never collide either
    far = row_region("slack", "channels", "C05ALPHA")
    assert arbiter_admits(far, held) is True


# --- corpus-backed: the frozen A/B over the REAL assertion engine ------------------------

def _clone_or_skip():
    from .dataset import agentdiff_root
    try:
        agentdiff_root()
    except FileNotFoundError:
        pytest.skip("Agent-Diff clone not on disk (external sibling clone)")


def test_natural_contention_exists_in_the_task_distribution():
    """The F2-STEP-1 question on the second benchmark: independent tasks NATURALLY pin the
    same changed row (GO), at a rate comparable to tau2's 2.35%. Pinned to the current
    dataset revision (the test_gate 224-pin convention)."""
    _clone_or_skip()
    from .coord import natural_contention
    rep = natural_contention("test")
    assert rep.verdict == "GO"
    assert rep.n_colliding_pairs == 4
    assert len(rep.sites) == 2
    # the two known natural sites: issue ENG-1 (linear) and channel C05ALPHA (slack)
    assert any("ENG-1" in s for s in rep.sites)
    assert any("C05ALPHA" in s for s in rep.sites)


def test_frozen_coord_ab_prevents_the_natural_lost_updates():
    """THE F3 RESULT: over every naturally-contending pair, the naive compose silently
    reverts a landed write (the production engine REFUTES the reverted task), the
    arbiter-serialized compose lands BOTH (engine confirms), and the kernel refused every
    2nd concurrent same-row lease while admitting every disjoint control. J=3 with one
    convergent pair correctly classified benign — no TRUE_CONFLICT on this revision."""
    _clone_or_skip()
    from .coord import frozen_coord_ab
    res = frozen_coord_ab("test")
    assert len(res.pairs) == 4
    assert res.j_total == 3
    assert res.n_lost_update == 3
    assert res.n_benign == 1
    assert res.n_true_conflict == 0
    assert res.all_serialized is True          # every contended pair refused-then-serialized
    assert res.all_disjoint_admitted is True   # the refuse-MORE-only floor: no tax on disjoint
    # every J row is engine-adjudicated: serial confirms BOTH tasks' changes landed
    for p in res.pairs:
        if p.j:
            assert p.serial_a_passed and p.serial_b_passed
            assert not (p.naive_a_passed and p.naive_b_passed)
            assert p.arbiter_serialized


def test_train_split_classifier_refuses_to_inflate_j():
    """The train split is DOMINATED by same-field conflicts (two tasks renaming the same
    Box file to different targets) — serialization orders them but cannot land both gold
    specs, so the engine-driven classifier scores them TRUE_CONFLICT, J=0. J counts only
    what serialization provably recovers (2 of 30), and the arbiter floor still holds on
    every pair. Pinned to the current dataset revision."""
    _clone_or_skip()
    from .coord import frozen_coord_ab
    res = frozen_coord_ab("train")
    assert res.contention.verdict == "GO"
    assert len(res.contention.sites) == 12
    assert len(res.pairs) == 30
    assert res.j_total == 2
    assert res.n_true_conflict == 28
    assert res.all_serialized is True
    assert res.all_disjoint_admitted is True
    # the honest direction: a TRUE_CONFLICT never contributes to J
    assert all(p.j == 0 for p in res.pairs if p.classification == TRUE_CONFLICT)


def test_engine_names_the_lost_update_in_its_own_failure_text():
    """Forensic provenance: the refutation carries the ENGINE's failure string (e.g.
    'priority did not change (before=3.0, after=3.0)') — the witness, not this harness,
    names what was lost."""
    _clone_or_skip()
    from .coord import frozen_coord_ab
    res = frozen_coord_ab("test")
    lost = [p for p in res.pairs if p.classification == LOST_UPDATE_PREVENTED]
    assert lost and all(p.naive_failures for p in lost)
    assert any("did not change" in f for p in lost for f in p.naive_failures)
