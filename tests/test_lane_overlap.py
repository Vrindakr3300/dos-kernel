"""Regression tests for the lane-tree overlap algebra (`dos.lane_overlap`) and
the shared prefix-collision helper (`dos._tree.prefixes_collide`).

The bug these pin: a leading-glob tree entry (`**/*`, `*.py`) normalizes to the
EMPTY prefix `""`. The old `_shared_count` filtered the empty prefix out, so the
broadest possible tree (the whole repo) read as "shares nothing" and
`overlap_verdict` called two `**/*` lanes "fully disjoint" — admitting two agents
editing the entire repo concurrently, the exact collision the arbiter exists to
prevent. The sibling `_tree.lane_trees_disjoint` handled the same input correctly
(NOT disjoint); the two disagreed, and the unsafe one was on the live arbiter path.

These tests fail on the pre-fix code and pass after, and they pin the empty prefix
== universal prefix semantics so the two helpers can never drift apart again.
"""
from __future__ import annotations

from dos._tree import (
    prefixes_collide,
    lane_trees_disjoint,
    tree_disjoint_from_all_live,
)
from dos.lane_overlap import overlap_verdict, Verdict


# ── the shared prefix-collision helper ──────────────────────────────────────
class TestPrefixesCollide:
    def test_empty_collides_with_empty(self):
        # Two whole-repo globs both normalize to "" — they maximally overlap.
        assert prefixes_collide("", "") is True

    def test_empty_collides_with_anything(self):
        # The empty (universal) prefix matches every path, both directions.
        assert prefixes_collide("", "engine/") is True
        assert prefixes_collide("engine/", "") is True

    def test_distinct_prefixes_do_not_collide(self):
        assert prefixes_collide("engine/", "charts/") is False

    def test_nested_prefixes_collide(self):
        assert prefixes_collide("engine/", "engine/loader.py") is True


# ── the overlap verdict — the live arbiter path ─────────────────────────────
class TestOverlapVerdictWholeRepo:
    def test_two_whole_repo_globs_refuse(self):
        # THE BUG: this returned ADMIT_DISJOINT ("fully disjoint") before the fix.
        ov = overlap_verdict(["**/*"], ["**/*"])
        assert ov.admissible is False
        assert ov.verdict == Verdict.REFUSE_OVERLAP

    def test_whole_repo_vs_narrow_refuses_both_directions(self):
        assert overlap_verdict(["**/*"], ["engine/**"]).admissible is False
        assert overlap_verdict(["engine/**"], ["**/*"]).admissible is False

    def test_star_dot_py_is_also_universal(self):
        # `*.py` also truncates to "" — any leading-glob is the universal prefix.
        assert overlap_verdict(["*.py"], ["*.py"]).admissible is False

    def test_genuinely_disjoint_narrow_trees_still_admit(self):
        # Regression guard: the fix must not over-refuse honestly-disjoint lanes.
        ov = overlap_verdict(["engine/**"], ["charts/**"])
        assert ov.admissible is True
        assert ov.verdict == Verdict.ADMIT_DISJOINT

    def test_heavy_overlap_still_refuses(self):
        # Unchanged by the fix (no empty prefix involved): 100% shared > 33%.
        assert overlap_verdict(["engine/**"], ["engine/loader.py"]).admissible is False

    def test_soft_overlap_still_admits(self):
        # One shared prefix out of four requested = 25% ≤ 33% → soft admit.
        ov = overlap_verdict(
            ["a/x.py", "b/y.py", "c/z.py", "engine/k.py"], ["engine/**"]
        )
        assert ov.admissible is True
        assert ov.verdict == Verdict.ADMIT_SOFT


class TestExactGlobFloor:
    """The 2026-06-01 TM↔tailor mutual-wedge regression.

    A priority plan-lane (TM: 8 entries, 6 of them private `tests/test_*`
    files) shared exactly `agents/tailor_*.py` with a live `tailor` cluster
    lease. Under the ratio test alone that scored 2/8 = 25 % ≤ 33 % → SOFT
    ADMIT, while the reverse direction (tailor 2/3 = 67 %) refused — an
    asymmetry that *guaranteed* a wedge: TM started, then the tailor loop's
    `/next-up` refused against TM's now-live lease. The exact-glob floor makes
    an identical-glob collision a hard refuse in BOTH directions.
    """

    TM = [
        "agents/tailor_*.py", "agents/tailor_steps/__init__.py",
        "job_search/skill_alignment.py", "scripts/audit_tm0_baseline.py",
        "tests/test_draft_step.py", "tests/test_extract_align_step.py",
        "tests/test_tailor_pipeline_composer.py",
        "tests/test_tailor_steps_protocol.py",
    ]
    TAILOR = ["agents/tailor_*.py", "agents/tailor_steps/", "templates/"]

    def test_identical_glob_refuses_despite_low_ratio(self):
        # THE BUG: 2/8 = 25 % ≤ 33 % would SOFT-ADMIT under the ratio alone.
        ov = overlap_verdict(self.TM, self.TAILOR)
        assert ov.admissible is False
        assert ov.verdict == Verdict.REFUSE_EXACT_GLOB

    def test_refusal_is_symmetric(self):
        # The asymmetry (admit one direction, refuse the other) is what
        # guaranteed the wedge — both directions must now refuse.
        fwd = overlap_verdict(self.TM, self.TAILOR)
        rev = overlap_verdict(self.TAILOR, self.TM)
        assert fwd.admissible is False
        assert rev.admissible is False
        assert fwd.verdict == rev.verdict == Verdict.REFUSE_EXACT_GLOB

    def test_reason_names_the_colliding_glob(self):
        ov = overlap_verdict(self.TM, self.TAILOR)
        assert "agents/tailor_*.py" in ov.reason

    def test_incidental_subsumption_still_soft_admits(self):
        # The legit narrow-keyword case the module was loosened for: a specific
        # file falling UNDER a cluster's broad glob (prefix subsumption, NOT an
        # identical glob) must still admit. No exact-glob equality here.
        workday = (
            ["playbooks/ats/workday.yaml", "playbooks/ats/workday_login.md"]
            + [f"tests/test_workday_{i}.py" for i in range(9)]
            + ["agents/apply_workday.py", "agents/apply_workday_forms.py",
               "job_search/workday_x.py", "docs/workday.md", "config/workday.yaml"]
        )
        apply_cluster = [
            "agents/apply_*.py", "agents/apply_backends/",
            "playbooks/ats/", "job_search/apply_core/",
        ]
        ov = overlap_verdict(workday, apply_cluster)
        assert ov.admissible is True
        assert ov.verdict == Verdict.ADMIT_SOFT

    def test_whole_repo_globs_take_ratio_path_not_exact_floor(self):
        # Two `**/*` both normalize to the universal "" prefix; that is handled
        # by the ratio path (REFUSE_OVERLAP), NOT the exact-glob floor — the
        # empty prefix is deliberately excluded from exact-glob equality.
        ov = overlap_verdict(["**/*"], ["**/*"])
        assert ov.verdict == Verdict.REFUSE_OVERLAP

    def test_identical_narrow_glob_pair_refuses_exact(self):
        # The old doctest case `apply_*.py` vs itself: now classified as the
        # more-specific REFUSE_EXACT_GLOB (still non-admissible).
        ov = overlap_verdict(["agents/apply_*.py"], ["agents/apply_*.py"])
        assert ov.admissible is False
        assert ov.verdict == Verdict.REFUSE_EXACT_GLOB


class TestOverlapAgreesWithDisjointness:
    """The two helpers that both answer "do these trees collide" must agree — the
    drift that let one call `**/*` disjoint while the other called it overlapping
    is the root cause, so pin agreement on the everything-tree."""

    PAIRS = [
        (["**/*"], ["**/*"]),
        (["**/*"], ["engine/**"]),
        (["engine/**"], ["charts/**"]),
        (["engine/**"], ["engine/loader.py"]),
        (["agents/tailor_*.py", "x/a.py"], ["agents/tailor_*.py", "y/b.py"]),
    ]

    def test_admissible_iff_disjoint_or_soft(self):
        for a, b in self.PAIRS:
            ov = overlap_verdict(a, b)
            disjoint = lane_trees_disjoint(a, b)
            # If the trees are NOT disjoint, the only admissible verdict is a
            # soft-overlap (a small shared fraction). A FULLY-disjoint verdict
            # must never disagree with `lane_trees_disjoint`.
            if ov.verdict == Verdict.ADMIT_DISJOINT:
                assert disjoint is True, (a, b, "overlap says disjoint, _tree disagrees")
            if not disjoint:
                assert ov.verdict != Verdict.ADMIT_DISJOINT, (a, b)


# ── case-insensitivity (the case-insensitive-FS false-ADMIT) ────────────────
class TestCaseInsensitiveCollision:
    """On a case-insensitive FS (Windows, DOS's primary platform) `core/x.py` and
    `Core/X.py` are ONE file. The case-sensitive prefix compare judged them disjoint,
    so two lanes editing one real file both got a lease — a false-ADMIT → concurrent
    writes → corruption. `norm_tree_prefix` now case-folds at the shared chokepoint,
    so every collision check (overlap + disjointness + self-modify) closes at once."""

    def test_same_file_different_case_is_not_disjoint(self):
        assert lane_trees_disjoint(["core/engine/run.py"], ["Core/Engine/run.py"]) is False
        assert lane_trees_disjoint(["core/**"], ["Core/**"]) is False

    def test_same_file_different_case_is_not_admissible(self):
        ov = overlap_verdict(["core/engine/run.py"], ["Core/Engine/run.py"])
        assert ov.verdict != Verdict.ADMIT_DISJOINT
        assert ov.admissible is False, "two lanes on one file (case-variant) must not both admit"

    def test_folding_preserves_genuine_distinctness(self):
        # Folding must NOT collapse genuinely-different sibling regions: the
        # workshop driver's filename-prefix trick (discriminating on SPELLING, not
        # case) must survive — `docs/UI-*` and `docs/SVC-*` stay disjoint.
        assert lane_trees_disjoint(["docs/UI-*"], ["docs/SVC-*"]) is True
        assert overlap_verdict(["docs/UI-*"], ["docs/SVC-*"]).admissible is True


class TestTreeDisjointFromAllLive:
    """`tree_disjoint_from_all_live` — the shared "can this region run alongside
    EVERY live sibling" predicate the lane arbiter's FQ-449 selection filter and the
    sibling-scan escape both stand on. Conservative-by-design: every *unknown* maps
    to "cannot prove disjoint → not safe" (False), mirroring `lane_trees_disjoint`'s
    empty-tree posture. An empty live set is vacuously disjoint (True)."""

    REQ = ["agents/apply_*.py"]

    @staticmethod
    def _lookup(mapping):
        return lambda lane: mapping.get(lane)

    def test_no_live_siblings_is_vacuously_disjoint(self):
        assert tree_disjoint_from_all_live(
            requested_tree=self.REQ, live=[],
            sibling_tree_lookup=self._lookup({})) is True

    def test_all_disjoint_is_true(self):
        live = [{"lane": "tailor"}, {"lane": "discovery"}]
        lookup = self._lookup({"tailor": ["agents/tailor_*.py"],
                               "discovery": ["job_search/scoring.py"]})
        assert tree_disjoint_from_all_live(
            requested_tree=self.REQ, live=live, sibling_tree_lookup=lookup) is True

    def test_any_overlap_is_false(self):
        live = [{"lane": "tailor"}, {"lane": "apply2"}]
        lookup = self._lookup({"tailor": ["agents/tailor_*.py"],
                               "apply2": ["agents/apply_phases.py"]})  # overlaps REQ
        assert tree_disjoint_from_all_live(
            requested_tree=self.REQ, live=live, sibling_tree_lookup=lookup) is False

    def test_empty_or_missing_lane_is_false(self):
        # A sibling with no lane name → unknown blast radius → not provably disjoint.
        assert tree_disjoint_from_all_live(
            requested_tree=self.REQ, live=[{"lane": ""}],
            sibling_tree_lookup=self._lookup({})) is False

    def test_unresolved_tree_is_false(self):
        # The lane resolves to None (lookup miss) → unknown → not safe.
        assert tree_disjoint_from_all_live(
            requested_tree=self.REQ, live=[{"lane": "mystery"}],
            sibling_tree_lookup=self._lookup({})) is False

    def test_lookup_that_raises_is_treated_as_unresolved(self):
        def boom(lane):
            raise RuntimeError("resolver exploded")
        assert tree_disjoint_from_all_live(
            requested_tree=self.REQ, live=[{"lane": "x"}],
            sibling_tree_lookup=boom) is False
