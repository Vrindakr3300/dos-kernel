"""Deterministic tests for shared/exclusive lock modes (`dos.lock_modes`).

What these pin (the `docs/114` §A1 fix, as mechanism not prose): the sound,
boolean lock-compatibility relation (Gray 1975) that recovers read-concurrency
WITHOUT the ⅓ ratio's unsound write-window. Three load-bearing properties:

  1. The compat matrix is the Gray relation: only SHARED↔SHARED is compatible.
  2. The relation is SYMMETRIC — the exact property the ⅓ ratio provably lacked
     (the 2026-06-01 TM↔tailor asymmetric wedge that one direction admitted and
     the other refused). A compatibility relation is symmetric by definition.
  3. `region_conflict` reduces write↔write to ZERO-tolerance intersection (the
     sound `ratio_max = 0` predicate) and adds concurrency ONLY on provably-safe
     read/read — so it can only ever refuse-MORE than the ⅓ rule on writes.

These are pure-function tests (list+enum in, bool out) — no I/O, no fixtures —
the same discipline as `test_lane_overlap`.
"""
from __future__ import annotations

import itertools

from dos.lock_modes import (
    DEFAULT_MODE,
    LockMode,
    modes_compatible,
    region_conflict,
)
from dos.lane_overlap import overlap_verdict


# ── the compatibility matrix (Gray 1975) ────────────────────────────────────
class TestModesCompatible:
    def test_shared_shared_is_compatible(self):
        # Two readers over the same region coexist — the whole point of S-mode.
        assert modes_compatible(LockMode.SHARED, LockMode.SHARED) is True

    def test_anything_with_exclusive_conflicts(self):
        # A write lock is incompatible with every other holder, both directions.
        assert modes_compatible(LockMode.SHARED, LockMode.EXCLUSIVE) is False
        assert modes_compatible(LockMode.EXCLUSIVE, LockMode.SHARED) is False
        assert modes_compatible(LockMode.EXCLUSIVE, LockMode.EXCLUSIVE) is False

    def test_relation_is_symmetric(self):
        # THE property the ⅓ ratio lacked: compat(a,b) == compat(b,a) for every
        # pair. A lock-compatibility relation is symmetric by definition; this is
        # what kills the asymmetric-wedge class of bug structurally.
        for a, b in itertools.product(LockMode, repeat=2):
            assert modes_compatible(a, b) == modes_compatible(b, a)

    def test_matrix_is_total(self):
        # Every (mode, mode) pair has a defined verdict — no KeyError reachable on
        # the admission hot path.
        for a, b in itertools.product(LockMode, repeat=2):
            assert isinstance(modes_compatible(a, b), bool)

    def test_default_mode_is_exclusive(self):
        # A lane with no declared mode is a write lock — reproduces DOS's
        # pre-S-mode behavior byte-for-byte (opting into SHARED is the only widen).
        assert DEFAULT_MODE is LockMode.EXCLUSIVE


# ── region_conflict: regions × modes ────────────────────────────────────────
class TestRegionConflict:
    def test_two_readers_same_region_do_not_conflict(self):
        # The concurrency the ⅓ hack reached for — now SOUND: same region, both
        # SHARED → compatible → no conflict.
        assert region_conflict(
            ["docs/**"], LockMode.SHARED, ["docs/**"], LockMode.SHARED
        ) is False

    def test_writer_vs_reader_same_region_conflicts(self):
        # A write lock over a region a reader holds is a conflict, both directions.
        assert region_conflict(
            ["docs/**"], LockMode.EXCLUSIVE, ["docs/**"], LockMode.SHARED
        ) is True
        assert region_conflict(
            ["docs/**"], LockMode.SHARED, ["docs/**"], LockMode.EXCLUSIVE
        ) is True

    def test_two_writers_same_region_conflict(self):
        # Write↔write over an intersecting region — the case the ⅓ rule could
        # dilute to admit; here it is always a conflict.
        assert region_conflict(
            ["src/dos/arbiter.py"], LockMode.EXCLUSIVE,
            ["src/dos/arbiter.py"], LockMode.EXCLUSIVE,
        ) is True

    def test_disjoint_regions_never_conflict(self):
        # No shared prefix → cannot touch the same file → no conflict, whatever
        # the modes (even X vs X).
        for a, b in itertools.product(LockMode, repeat=2):
            assert region_conflict(["src/a/**"], a, ["src/b/**"], b) is False

    def test_partial_overlap_writers_conflict_at_any_ratio(self):
        # THE §A1 soundness fix: a narrow file under a broad glob shares ONE
        # prefix. Under the ⅓ rule a tree padded with private files could score
        # ≤⅓ and SOFT-ADMIT; under zero-tolerance write-locking it conflicts.
        req = ["src/api/x.py", "priv/a.py", "priv/b.py", "priv/c.py"]  # 1/4 share
        lease = ["src/api/**"]
        # ⅓ rule admits this (1/4 = 25% ≤ 33%)...
        assert overlap_verdict(req, lease).admissible is True
        # ...but two writers MUST conflict on the shared src/api file:
        assert region_conflict(
            req, LockMode.EXCLUSIVE, lease, LockMode.EXCLUSIVE
        ) is True

    def test_partial_overlap_readers_do_not_conflict(self):
        # The flip side: the SAME partially-overlapping regions are safe to share
        # when BOTH are read locks — concurrency recovered soundly.
        req = ["src/api/x.py", "priv/a.py", "priv/b.py", "priv/c.py"]
        lease = ["src/api/**"]
        assert region_conflict(
            req, LockMode.SHARED, lease, LockMode.SHARED
        ) is False

    def test_writeshare_never_looser_than_zero_tolerance_intersection(self):
        # The core invariant: for any pair of trees, two EXCLUSIVE lanes conflict
        # IFF the regions intersect at all (the sound ratio_max=0 predicate). So
        # write-locking is never looser than zero-tolerance — only read/read adds
        # concurrency.
        cases = [
            (["a/**"], ["a/x.py"]),       # nested → intersect
            (["a/**"], ["b/**"]),         # disjoint
            (["a/x.py"], ["a/x.py"]),     # identical
            (["**/*"], ["anything/z"]),   # universal glob intersects everything
        ]
        for req, lease in cases:
            xx = region_conflict(req, LockMode.EXCLUSIVE, lease, LockMode.EXCLUSIVE)
            # The deterministic intersection oracle, computed independently:
            from dos._tree import lane_trees_disjoint
            intersects = not lane_trees_disjoint(req, lease)
            assert xx is intersects, (req, lease)

    def test_empty_tree_defers_to_caller(self):
        # An empty (unknown) tree yields "no provable conflict" here; the
        # unknown-blast-radius REFUSE is the caller's job (DisjointnessPredicate),
        # exactly as for overlap_verdict. This pins that contract.
        assert region_conflict([], LockMode.EXCLUSIVE, ["a/**"], LockMode.EXCLUSIVE) is False
        assert region_conflict(["a/**"], LockMode.EXCLUSIVE, [], LockMode.EXCLUSIVE) is False


# ── JSON / WAL round-trip (str-valued enum) ─────────────────────────────────
class TestLockModeSerialization:
    def test_mode_is_str_valued(self):
        # str-valued so a mode persists to a WAL record / dos.toml field as its
        # lowercase name with no custom codec — same convention as Verdict.
        assert LockMode.SHARED == "shared"
        assert LockMode.EXCLUSIVE == "exclusive"
        assert LockMode("shared") is LockMode.SHARED
        assert LockMode("exclusive") is LockMode.EXCLUSIVE
