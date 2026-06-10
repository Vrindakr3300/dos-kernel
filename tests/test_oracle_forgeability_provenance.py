"""Forgeability grading of the grep rung (docs/118).

`phase_shipped` answers a ship on a rung it reports as `via`; the rungs split by
FORGEABILITY (can an agent that writes the commit fake the evidence?):

  * non-forgeable: `file-path` (the artefact/diff rung — a commit cannot lie
    about which files it touched), and `registry` (a `mark done` write).
  * forgeable: `direct` / `release-prefix` / `body-mention` / `hyg-slug` /
    `sub-phase-parent` — every one matches a phase token in the commit
    SUBJECT/BODY the agent authored.

`verify` used to flatten every grep rung to a single `source='grep'`, discarding
the `via` field at the oracle boundary, so `dos verify` rendered `(via grep)`
identically whether the ship stood on the diff or on a subject line the agent
typed. These tests pin the grading: the verdict now carries the raw `rung` and a
`source` graded `grep-artifact` (non-forgeable) vs `grep-subject` (forgeable),
WITHOUT changing the registry path, the no-evidence path, or the long-standing
injected-`grep_fallback` contract. It is advisory — the grade of the report
changes, never the moment of control (no write is mediated).
"""
from __future__ import annotations

from dos import oracle
from dos.oracle import ShipVerdict, _grade_grep_source, _restamp_grep_source


class TestGradeGrepSource:
    """`_grade_grep_source(via)` → the graded `source` label."""

    def test_file_path_is_artifact(self):
        # The one non-forgeable grep rung — the artefact/diff rung.
        assert _grade_grep_source("file-path") == "grep-artifact"

    def test_subject_body_rungs_are_subject(self):
        # Every rung that matched the agent-authored subject/body is forgeable.
        for via in (
            "direct",
            "release-prefix",
            "body-mention",
            "hyg-slug",
            "sub-phase-parent",
        ):
            assert _grade_grep_source(via) == "grep-subject", via

    def test_blank_or_unknown_falls_back_to_bare_grep(self):
        # A fallback that reported no rung must not be mis-graded to either side.
        assert _grade_grep_source("") == "grep"
        assert _grade_grep_source(None) == "grep"  # type: ignore[arg-type]
        assert _grade_grep_source("   ") == "grep"

    def test_unknown_rung_is_treated_as_forgeable(self):
        # A new subject-shaped rung we haven't allowlisted defaults to the SAFE
        # (forgeable) side — never silently graded as the trusted artefact rung.
        assert _grade_grep_source("some-future-subject-rung") == "grep-subject"

    def test_only_file_path_is_in_the_nonforgeable_set(self):
        # The allowlist is exactly {file-path} — the registry source is handled
        # elsewhere (it is not a grep rung). Lock the set so a careless addition
        # is a visible test change, not a silent trust widening.
        assert oracle._NONFORGEABLE_GREP_RUNGS == frozenset({"file-path"})


class TestRestampGrepSource:
    """`_restamp_grep_source(fb_source)` — what the oracle boundary re-stamps."""

    def test_graded_sources_are_preserved(self):
        assert _restamp_grep_source("grep-artifact") == "grep-artifact"
        assert _restamp_grep_source("grep-subject") == "grep-subject"

    def test_bare_grep_stays_bare(self):
        # The injected-stub contract: a fallback returning `source='grep'` reports
        # `'grep'` (never up-graded to a forgeability label it didn't claim).
        assert _restamp_grep_source("grep") == "grep"

    def test_blank_and_foreign_sources_stamp_bare_grep(self):
        assert _restamp_grep_source("") == "grep"
        assert _restamp_grep_source("registry") == "grep"  # not a grep- label
        assert _restamp_grep_source("anything") == "grep"


class TestShipVerdictRung:
    """`ShipVerdict.rung` carries the raw rung and round-trips through `to_dict`."""

    def test_rung_defaults_empty_and_is_omitted_from_dict(self):
        v = ShipVerdict("RS", "RS1", True, sha="abc", source="grep")
        assert v.rung == ""
        assert "rung" not in v.to_dict()  # omitted when empty (back-compat shape)

    def test_rung_round_trips_when_present(self):
        v = ShipVerdict("RS", "RS1", True, sha="abc", source="grep-artifact",
                        rung="file-path")
        d = v.to_dict()
        assert d["rung"] == "file-path"
        assert d["source"] == "grep-artifact"

    def test_registry_verdict_has_no_rung(self):
        # A registry hit is non-forgeable by its own source; it carries no grep
        # rung, so `rung` stays empty and absent from the dict.
        v = ShipVerdict("RS", "RS1", True, sha="abc", source="registry")
        assert v.rung == ""
        assert "rung" not in v.to_dict()


class TestIsShippedGrading:
    """`is_shipped` surfaces the graded source + rung from the fallback."""

    @staticmethod
    def _empty_state() -> dict:
        return {"recently_completed": []}

    def test_artifact_rung_grades_to_grep_artifact(self):
        # A default-shaped fallback that resolved on the file-path rung yields a
        # non-forgeable `grep-artifact` source through the oracle boundary.
        def fb(plan, phase):
            return ShipVerdict(plan, phase, True, sha="dead", source="grep-artifact",
                               rung="file-path")

        v = oracle.is_shipped("RS", "RS1", state=self._empty_state(), grep_fallback=fb)
        assert v.shipped is True
        assert v.source == "grep-artifact"
        assert v.rung == "file-path"

    def test_subject_rung_grades_to_grep_subject(self):
        def fb(plan, phase):
            return ShipVerdict(plan, phase, True, sha="cafe", source="grep-subject",
                               rung="direct")

        v = oracle.is_shipped("RS", "RS1", state=self._empty_state(), grep_fallback=fb)
        assert v.shipped is True
        assert v.source == "grep-subject"
        assert v.rung == "direct"

    def test_injected_bare_grep_stub_still_reports_grep(self):
        # The long-standing contract (tests/test_oracle_and_loop.py): an injected
        # stub returning `source='grep'` must keep reporting `'grep'`, NOT be
        # re-graded. This is what `_restamp_grep_source`'s `grep-` guard preserves.
        def fb(plan, phase):
            return ShipVerdict(plan, phase, True, sha="deadbeef", source="grep")

        v = oracle.is_shipped("RS", "RS9", state=self._empty_state(), grep_fallback=fb)
        assert v.shipped is True
        assert v.source == "grep"

    def test_registry_hit_unaffected(self):
        # The registry path is real ship truth — it stays `source='registry'`,
        # never routed through the grep grading.
        state = {"recently_completed": [
            {"plan": "RS", "phase": "RS1", "status": "done", "commit_sha": "abc123"},
        ]}
        v = oracle.is_shipped("RS", "RS1", state=state,
                              grep_fallback=lambda p, ph: ShipVerdict(p, ph, False))
        assert v.shipped is True
        assert v.source == "registry"
        assert v.rung == ""


class TestBatchIsShippedGrading:
    """`batch_is_shipped` grades the same way as the single path."""

    def test_batch_preserves_graded_source_and_rung(self):
        def fb(misses):
            return {
                ("RS", "RS1"): ShipVerdict("RS", "RS1", True, sha="d1",
                                           source="grep-artifact", rung="file-path"),
                ("RS", "RS2"): ShipVerdict("RS", "RS2", True, sha="d2",
                                           source="grep-subject", rung="direct"),
            }

        out = oracle.batch_is_shipped(
            [("RS", "RS1"), ("RS", "RS2")],
            state={"recently_completed": []},
            grep_fallback=fb,
        )
        assert out[("RS", "RS1")].source == "grep-artifact"
        assert out[("RS", "RS1")].rung == "file-path"
        assert out[("RS", "RS2")].source == "grep-subject"
        assert out[("RS", "RS2")].rung == "direct"
