"""parse_phase_labels — the subject->normalized-phase-id primitive (DOS leaf).

Mirrors bench tests/test_next_context.py::TestPhaseLabels byte-for-byte:
the same 6 example groups + prose-negative + None-safe cases. This is the
contract bench's _phase_labels shim delegates to (Phase E push-up).
"""

import pytest
from dos.stamp import parse_phase_labels


class TestPhaseLabels:
    @pytest.mark.parametrize("subject, expected", [
        ("v25.10: SGLang-Metrics P3 landing (65709c7)", ["P3"]),
        ("exec-sweep Slack streaming P4.6 done", ["P4.6"]),
        ("L3 busy-device Phase 1c proof + test", ["P1c"]),
        ("blktrace P6 local test fixture", ["P6"]),
        ("Phase 2 kickoff", ["P2"]),
        ("lowercase p3 normalizes to upper", ["P3"]),
    ])
    def test_extracts_expected(self, subject, expected):
        assert parse_phase_labels(subject) == expected

    @pytest.mark.parametrize("subject, expected", [
        ("exec-sweep P3b.2 dispatch", ["P3b.2"]),
        ("L3 busy-device Phase 3b.2 proof", ["P3b.2"]),
        ("serve P5.1 then P3.4 wrap-up", ["P3.4", "P5.1"]),
    ])
    def test_extracts_subphase_forms(self, subject, expected):
        assert parse_phase_labels(subject) == expected

    @pytest.mark.parametrize("subject, expected", [
        ("close out all remaining P0s", ["P0"]),
        ("Phase 1s rolled forward", ["P1"]),
        ("P0s closed, P1c still open", ["P0", "P1c"]),
    ])
    def test_strips_plural_artifact(self, subject, expected):
        assert parse_phase_labels(subject) == expected

    def test_multiple_labels_sorted_deduped(self):
        out = parse_phase_labels("bundle P4 and P1c plus P4 again and Phase 2")
        assert out == ["P1c", "P2", "P4"]

    @pytest.mark.parametrize("subject", [
        "fix typo in readme",
        "refactor Python helper for clarity",
        "bump GPT-3 reference link",
        "PR cleanup: drop dead code",
        "",
    ])
    def test_ignores_non_matches(self, subject):
        assert parse_phase_labels(subject) == []

    def test_none_subject_is_safe(self):
        assert parse_phase_labels(None) == []
