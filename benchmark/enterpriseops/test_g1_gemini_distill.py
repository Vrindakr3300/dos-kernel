"""Tests for the G1 gym->TrajectoryStep adapter (docs/206 §5b).

Pin: (1) the claim signal is the model's NARRATION (a real producer self-report),
NOT the gold flag; (2) a verifier maps to a labeled step with the gold pass as the
label; (3) the silent-failure case (narration asserts success, gold verifier fails)
is detected — the distrust gap G1 reads; (4) model_response as list/str both flatten.
"""
from __future__ import annotations

from .g1_gemini_distill import _as_text, _assert_success, steps_from_run, summary


def test_as_text_handles_str_and_blocks():
    assert _as_text("done") == "done"
    assert "hello" in _as_text([{"type": "text", "text": "hello"}, "world"])
    assert _as_text(None) == ""


def test_assert_success_reads_narration():
    assert _assert_success("All records successfully created.") is True
    assert _assert_success("I was unable to complete the update.") is False
    assert _assert_success("") is False
    # list form (content blocks)
    assert _assert_success([{"text": "Task completed successfully"}]) is True


def test_step_label_is_gold_not_narration():
    run = {
        "model_response": "Successfully completed all objectives.",  # asserts success
        "tools_used": ["a", "b"],
        "tool_results": [1, 2],
        "verification_results": {
            "Verify state": {"passed": 0, "total": 1},     # gold says FAIL
            "Verify user": {"passed": 1, "total": 1},       # gold says pass
        },
    }
    steps = steps_from_run(run, session="s", base_step=0)
    assert len(steps) == 2
    by = {s.phase_id.split(":")[1]: s for s in steps}
    assert by["Verify state"].really_committed is False     # label = gold, not the word
    assert by["Verify state"].claimed_shipped is True        # the model asserted success
    assert by["Verify state"].is_caught_lie is True          # asserted, goal failed = the gap
    assert by["Verify user"].really_committed is True
    assert by["Verify user"].is_caught_lie is False


def test_summary_counts_silent_failures():
    run = {
        "model_response": "Done — everything is set up.",
        "tools_used": ["a"],
        "tool_results": [1],
        "verification_results": {
            "v1": {"passed": 0, "total": 1},
            "v2": {"passed": 0, "total": 1},
            "v3": {"passed": 1, "total": 1},
        },
    }
    steps = steps_from_run(run, session="s", base_step=0)
    s = summary(steps)
    assert s["verifier_steps"] == 3
    assert s["goal_achieved"] == 1
    assert s["goal_failed"] == 2
    assert s["silent_failures"] == 2     # asserted success, 2 goals failed
