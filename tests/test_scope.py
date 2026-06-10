"""SCF — the scope-fidelity verdict + the pure classifier (docs/85 §4, docs/86).

`scope.classify` is the footprint sibling of `verify`: a PURE verdict over an
already-gathered touched-file set and a declared lane tree, the same shape as
`liveness.classify`. These tests pin the ladder on FROZEN evidence (no git, no
config read) and the family invariants (purity, no-plan degradation, the
conservative empty-tree stance, shared-infra tolerance).

The verdict ladder under test:

  1. IN_SCOPE     — every touched file inside the lane tree (or empty diff, or
                    only tolerated shared-infra spill).
  2. SCOPE_CREEP  — the lane IS touched AND so is genuine out-of-tree spill.
  3. WRONG_TARGET — nothing touched is inside the lane tree (non-empty diff), OR
                    the lane declares no tree (unknown blast radius).
"""

from __future__ import annotations

import json

import pytest

from dos import scope
from dos.scope import Scope, ScopePolicy, ScopeEvidence, classify


def _ev(touched, tree=("effort-03/",), lane="lane-03") -> ScopeEvidence:
    """A ScopeEvidence with the bench's effort-subtree shape; override per test."""
    return ScopeEvidence(touched_files=frozenset(touched), lane_tree=tuple(tree), lane=lane)


# ---------------------------------------------------------------------------
# 1. The three rungs, on frozen evidence (the core litmus).
# ---------------------------------------------------------------------------


def test_wholly_contained_is_in_scope():
    """Every touched file under the lane's declared prefix → IN_SCOPE."""
    v = classify(_ev(["effort-03/mod_1.txt", "effort-03/sub/mod_2.txt"]))
    assert v.verdict is Scope.IN_SCOPE
    assert set(v.in_scope_files) == {"effort-03/mod_1.txt", "effort-03/sub/mod_2.txt"}
    assert v.out_of_scope_files == ()


def test_partial_overrun_is_scope_creep():
    """Touched the lane AND files outside it → SCOPE_CREEP (a superset of scope).

    The North-star case: a phase stamped lane-03 that really did touch its own
    subtree but ALSO reached `effort-07/` (another effort's lane) — the silent
    cross-lane stomp SCF exists to catch.
    """
    v = classify(_ev(["effort-03/mod_1.txt", "effort-07/mod_9.txt"]))
    assert v.verdict is Scope.SCOPE_CREEP
    assert v.in_scope_files == ("effort-03/mod_1.txt",)
    assert "effort-07/mod_9.txt" in v.out_of_scope_files
    assert "outside it" in v.reason


def test_total_miss_is_wrong_target():
    """NONE of the touched files in the lane tree → WRONG_TARGET (claim vs
    footprint disagree entirely — the most severe rung)."""
    v = classify(_ev(["effort-07/mod_9.txt", "effort-09/mod_2.txt"]))
    assert v.verdict is Scope.WRONG_TARGET
    assert v.in_scope_files == ()
    assert set(v.out_of_scope_files) == {"effort-07/mod_9.txt", "effort-09/mod_2.txt"}


def test_empty_footprint_is_in_scope():
    """An empty diff creeps on nothing → IN_SCOPE (the benign floor, mirrors
    liveness returning a verdict for 0 commits rather than erroring)."""
    v = classify(_ev([]))
    assert v.verdict is Scope.IN_SCOPE
    assert "nothing to judge" in v.reason


# ---------------------------------------------------------------------------
# 2. The no-plan / generic rail + the conservative empty-tree stance.
# ---------------------------------------------------------------------------


def test_generic_tree_matches_everything():
    """The GENERIC lane tree `("**/*",)` normalizes to the empty prefix, which is
    a prefix of every path → everything IN_SCOPE. This is the no-plan floor: a
    repo that declared no lanes has no scope to violate (the `test_verify_no_plan`
    sibling)."""
    v = classify(_ev(["anywhere/at/all.py", "shared/x.txt"], tree=("**/*",), lane="main"))
    assert v.verdict is Scope.IN_SCOPE


def test_empty_tree_is_wrong_target_not_in_scope():
    """An EMPTY lane tree is an UNKNOWN blast radius, not a zero one — the
    `_tree.lane_trees_disjoint` conservative stance. A non-empty diff against an
    undeclared lane is WRONG_TARGET (we cannot certify containment), never a free
    pass."""
    v = classify(_ev(["effort-03/mod_1.txt"], tree=(), lane="undeclared"))
    assert v.verdict is Scope.WRONG_TARGET
    assert "no tree" in v.reason or "unknown blast radius" in v.reason
    # An empty tree with an EMPTY diff is still IN_SCOPE — nothing to judge wins
    # first (the empty-footprint rung short-circuits before the tree check).
    assert classify(_ev([], tree=(), lane="undeclared")).verdict is Scope.IN_SCOPE


def test_multiple_tree_prefixes_union():
    """A lane owning several globs is the UNION of their prefixes — a file under
    any one is in scope (the bench's `(effort-NN/, shared/)` lane shape)."""
    ev = _ev(["effort-03/a.txt", "shared/resource_0.txt"],
             tree=("effort-03/", "shared/"), lane="lane-03")
    v = classify(ev)
    assert v.verdict is Scope.IN_SCOPE
    assert set(v.in_scope_files) == {"effort-03/a.txt", "shared/resource_0.txt"}


def test_glob_truncated_at_star():
    """A glob is truncated at the first `*` (reusing `_tree.norm_tree_prefix`), so
    `agents/apply_*.py` covers `agents/apply_foo.py`."""
    ev = _ev(["agents/apply_tailor.py"], tree=("agents/apply_*.py",), lane="apply")
    assert classify(ev).verdict is Scope.IN_SCOPE
    # ...but a sibling outside the truncated prefix is out.
    ev2 = _ev(["agents/discovery.py"], tree=("agents/apply_*.py",), lane="apply")
    assert classify(ev2).verdict is Scope.WRONG_TARGET


# ---------------------------------------------------------------------------
# 3. Shared-infra tolerance + creep tolerance (the policy seam).
# ---------------------------------------------------------------------------


def test_shared_infra_spill_tolerated_by_default():
    """A footprint that touches the lane plus ONLY hub files (`config.py`,
    `__init__.py`) is IN_SCOPE by default — those are touched by nearly every
    change and are never a phase's distinctive deliverable (the `phase_shipped`
    shared-infra judgement, restated)."""
    ev = _ev(["effort-03/mod_1.txt", "effort-03/__init__.py", "config.py"])
    v = classify(ev)
    assert v.verdict is Scope.IN_SCOPE
    # config.py is outside effort-03/ but tolerated; it's reported, not counted.
    assert "config.py" in v.out_of_scope_files
    assert "not counted as creep" in v.reason


def test_shared_infra_not_tolerated_when_policy_off():
    """With `allow_shared_infra=False`, the same hub-file spill IS creep."""
    ev = _ev(["effort-03/mod_1.txt", "config.py"])
    v = classify(ev, ScopePolicy(allow_shared_infra=False))
    assert v.verdict is Scope.SCOPE_CREEP


def test_creep_tolerance_absorbs_small_spill():
    """`creep_tolerance=1` lets a single genuine out-of-tree file pass as
    IN_SCOPE; a second one tips it to SCOPE_CREEP."""
    one = _ev(["effort-03/a.txt", "effort-07/x.txt"])
    assert classify(one, ScopePolicy(creep_tolerance=1)).verdict is Scope.IN_SCOPE
    two = _ev(["effort-03/a.txt", "effort-07/x.txt", "effort-09/y.txt"])
    assert classify(two, ScopePolicy(creep_tolerance=1)).verdict is Scope.SCOPE_CREEP


def test_policy_rejects_negative_tolerance():
    with pytest.raises(ValueError):
        ScopePolicy(creep_tolerance=-1)


# ---------------------------------------------------------------------------
# 4. Purity + the json/renderer seam.
# ---------------------------------------------------------------------------


def test_classify_is_pure(monkeypatch):
    """`classify()` makes no subprocess/file/clock call — the arbiter discipline
    that lets SCF be replay-tested on frozen fixtures (the liveness invariant)."""
    import builtins
    import subprocess
    import time as _time

    def _boom(*a, **k):  # pragma: no cover - only runs if purity is violated
        raise AssertionError("classify() performed I/O — it must be pure")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(_time, "time", _boom)

    # Exercise every rung under the poison so none secretly does I/O.
    assert classify(_ev(["effort-03/a.txt"])).verdict is Scope.IN_SCOPE
    assert classify(_ev(["effort-03/a.txt", "effort-07/x.txt"])).verdict is Scope.SCOPE_CREEP
    assert classify(_ev(["effort-07/x.txt"])).verdict is Scope.WRONG_TARGET
    assert classify(_ev([])).verdict is Scope.IN_SCOPE
    assert classify(_ev(["x.txt"], tree=())).verdict is Scope.WRONG_TARGET


def test_verdict_to_dict_round_trips_evidence():
    """`--output json` payload carries the verdict, the spill, AND the driving
    evidence so the operator sees not just SCOPE_CREEP but which files (legible
    distrust). JSON-serialisable for the renderer seam."""
    v = classify(_ev(["effort-03/a.txt", "effort-07/x.txt"]))
    d = v.to_dict()
    assert d["verdict"] == "SCOPE_CREEP"
    assert "effort-07/x.txt" in d["out_of_scope_files"]
    assert d["evidence"]["lane"] == "lane-03"
    assert "effort-03/" in d["evidence"]["lane_tree"]
    json.dumps(d)


def test_windows_paths_normalized():
    """Backslash paths normalize to forward slashes so the prefix test matches the
    `_tree` normalization (the verdict must not depend on the caller's OS)."""
    ev = ScopeEvidence(
        touched_files=frozenset({"effort-03\\mod_1.txt"}),
        lane_tree=("effort-03/",), lane="lane-03",
    )
    assert classify(ev).verdict is Scope.IN_SCOPE
