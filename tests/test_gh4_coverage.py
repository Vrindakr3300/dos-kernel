"""GH4 commit-coverage predicates — pure ship-stamp / footprint matching (MQ3X P1).

Pins the three lifted predicates on frozen evidence (no git, no fs): the four
``claim_covered`` resolution branches, the CRS3 plan-doc-only surface, and the
permissive subject stamp-match. These are the kernel half of the job adapter's
GH4 post-commit auto-stamp; the impure siblings stay job-side by design.
"""
from __future__ import annotations

from dos.gh4_coverage import (
    FANOUT_TS_RE,
    STAMP_PATTERNS_GENERIC,
    claim_covered,
    coverage_is_plandoc_only,
    subject_matches_stamp,
)


class TestClaimCovered:
    def test_empty_committed_is_never_covered(self):
        assert claim_covered({"path_glob": "agents/*.py"}, [], "docs/x.md") is False

    def test_explicit_path_glob_match(self):
        entry = {"path_glob": "agents/apply_*.py"}
        assert claim_covered(entry, ["agents/apply_dispatch.py"], None) is True
        assert claim_covered(entry, ["job_search/score.py"], None) is False

    def test_explicit_path_glob_normalizes_backslashes(self):
        entry = {"path_glob": "agents\\apply_*.py"}
        assert claim_covered(entry, ["agents/apply_now.py"], None) is True

    def test_explicit_files_exact_and_dir_prefix(self):
        entry = {"files": ["agents/apply_now.py", "docs/_audits/"]}
        assert claim_covered(entry, ["agents/apply_now.py"], None) is True
        assert claim_covered(entry, ["docs/_audits/run-1/report.md"], None) is True
        assert claim_covered(entry, ["agents/other.py"], None) is False

    def test_fanout_archive_bundle_branch_3a(self):
        entry = {"dispatched_by": "fanout-20260604T010203Z"}
        assert claim_covered(
            entry, ["docs/_fanout_runs/20260604T010203Z/README.md"], None) is True
        # different TS -> not covered
        assert claim_covered(
            entry, ["docs/_fanout_runs/20260101T000000Z/README.md"], None) is False

    def test_plan_doc_edit_branch_3b(self):
        entry = {"dispatched_by": "next-up-2026-06-04-1"}
        assert claim_covered(entry, ["docs/62_x-plan.md"], "docs/62_x-plan.md") is True
        assert claim_covered(entry, ["docs/other.md"], "docs/62_x-plan.md") is False

    def test_no_footprint_no_plandoc_is_uncovered(self):
        assert claim_covered({"dispatched_by": "next-up-x"}, ["a/b.py"], None) is False


class TestCoverageIsPlandocOnly:
    def test_plandoc_only_when_only_3b_matches(self):
        # commit touched ONLY the plan doc; no stronger footprint
        entry = {"dispatched_by": "next-up-2026-06-04-1"}
        assert coverage_is_plandoc_only(
            entry, ["docs/crs-plan.md"], "docs/crs-plan.md") is True

    def test_not_plandoc_only_when_glob_also_matches(self):
        entry = {"path_glob": "agents/*.py"}
        assert coverage_is_plandoc_only(
            entry, ["docs/crs-plan.md", "agents/crs.py"], "docs/crs-plan.md") is False

    def test_not_plandoc_only_when_files_also_match(self):
        entry = {"files": ["agents/crs.py"]}
        assert coverage_is_plandoc_only(
            entry, ["docs/crs-plan.md", "agents/crs.py"], "docs/crs-plan.md") is False

    def test_not_plandoc_only_when_fanout_bundle_also_matches(self):
        entry = {"dispatched_by": "fanout-20260604T010203Z"}
        assert coverage_is_plandoc_only(
            entry,
            ["docs/crs-plan.md", "docs/_fanout_runs/20260604T010203Z/x.md"],
            "docs/crs-plan.md") is False

    def test_false_when_plan_doc_not_in_commit(self):
        entry = {"dispatched_by": "next-up-x"}
        assert coverage_is_plandoc_only(
            entry, ["agents/x.py"], "docs/crs-plan.md") is False

    def test_false_when_no_plan_doc(self):
        assert coverage_is_plandoc_only({}, ["docs/x.md"], None) is False


class TestSubjectMatchesStamp:
    def test_empty_subject_never_matches(self):
        assert subject_matches_stamp("", "crs") is False

    def test_plan_prefix_forms(self):
        assert subject_matches_stamp("crs: ship CRS3", "crs") is True
        assert subject_matches_stamp("docs/crs: ship", "crs") is True
        assert subject_matches_stamp("crs/ship", "crs") is True
        assert subject_matches_stamp("docs/crs-plan: ship", "crs") is True

    def test_plan_token_anywhere(self):
        assert subject_matches_stamp("docs/git-hygiene: GH4 — stamp", "gh4") is True

    def test_generic_stamp_patterns(self):
        assert subject_matches_stamp("chore(working-tree): wip", "") is True
        assert subject_matches_stamp("docs/fanout: archive", "") is True
        assert subject_matches_stamp("docs/dispatch: archive", "") is True
        assert subject_matches_stamp("docs/_fanout_runs/x", "") is True

    def test_unrelated_subject_no_match(self):
        assert subject_matches_stamp("refactor: unrelated change", "crs") is False

    def test_uses_only_first_line(self):
        # plan token only in body line -> still no match (subject = first line)
        assert subject_matches_stamp("refactor: x\n\nbody mentions crs3", "crs") is False


class TestConstants:
    def test_fanout_ts_re_shape(self):
        assert FANOUT_TS_RE.match("fanout-20260604T010203Z")
        assert not FANOUT_TS_RE.match("next-up-2026-06-04")

    def test_stamp_patterns_count(self):
        assert len(STAMP_PATTERNS_GENERIC) == 4
