"""Property-based proof of the path-prefix disjointness algebra (docs/273).

`dos._tree` is the file-tree algebra the overlap scorer rides on: `prefixes_collide`
(do two normalized path prefixes overlap?) and `lane_trees_disjoint` (are two trees
non-overlapping?). These carry algebraic laws — symmetry, reflexivity — that the
whole lane-arbitration soundness story depends on (an asymmetric collision test is
exactly the bug `lane_overlap`'s exact-glob fix closed: admit-one / refuse-the-other
guarantees a mutual wedge). This file pins those laws ∀.

The properties:
  * `TestPrefixCollide`   — symmetric + reflexive.
  * `TestDisjointness`    — symmetric; a non-empty tree is never disjoint from
    itself (the self-overlap floor that makes fleet=1 overwrite-prevention
    structurally 0, docs/204 §1).
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from dos._tree import (  # noqa: E402
    lane_trees_disjoint,
    norm_tree_prefix,
    prefixes_collide,
)

_segments = st.sampled_from(["agents", "playbooks", "src", "tests", "a", "b", "c"])


@st.composite
def _path(draw) -> str:
    n = draw(st.integers(min_value=1, max_value=4))
    return "/".join(draw(_segments) for _ in range(n))


_trees = st.lists(_path(), min_size=1, max_size=6)


class TestPrefixCollide:
    @given(a=_path(), b=_path())
    @settings(max_examples=500, deadline=None)
    def test_collide_is_symmetric(self, a, b):
        na, nb = norm_tree_prefix(a), norm_tree_prefix(b)
        assert prefixes_collide(na, nb) == prefixes_collide(nb, na), (
            f"prefix collision asymmetric: {a!r} vs {b!r}"
        )

    @given(p=_path())
    @settings(max_examples=300, deadline=None)
    def test_collide_is_reflexive(self, p):
        """A normalized non-empty prefix collides with itself — the floor that makes
        an exact-glob a hard collision in lane_overlap."""
        n = norm_tree_prefix(p)
        if n == "":
            return  # the universal empty prefix is handled separately by callers
        assert prefixes_collide(n, n)


class TestDisjointness:
    @given(a=_trees, b=_trees)
    @settings(max_examples=500, deadline=None)
    def test_disjoint_is_symmetric(self, a, b):
        """lane_trees_disjoint(A,B) == lane_trees_disjoint(B,A). An asymmetric
        disjointness test is the admit-one/refuse-the-other bug that guarantees a
        mutual wedge — symmetry forecloses it."""
        assert lane_trees_disjoint(a, b) == lane_trees_disjoint(b, a), (
            f"disjointness asymmetric: {a} vs {b}"
        )

    @given(tree=_trees)
    @settings(max_examples=300, deadline=None)
    def test_a_tree_is_never_disjoint_from_itself(self, tree):
        """A non-empty tree overlaps itself — the self-overlap floor. This is why
        overwrite-prevention at fleet=1 is structurally 0 (a single agent is never
        in conflict with itself): a lane cannot collide with a copy of its own
        region and be called disjoint."""
        # A tree with only universal-empty-prefix entries ('*.py' -> '') is the one
        # edge the prefix algebra treats specially; every other tree self-overlaps.
        if all(norm_tree_prefix(p) == "" for p in tree):
            return
        assert not lane_trees_disjoint(tree, list(tree)), (
            f"tree reported disjoint from itself: {tree}"
        )
