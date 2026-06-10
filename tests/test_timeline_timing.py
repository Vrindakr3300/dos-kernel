"""Tests for the per-stage timing surface in dos.timeline.

Covers the timing additions (duration column + slowest flag + batch rollup)
without needing a real chained-run dir: the pure helpers (`_fmt_dur`,
`_percentile`, `_render_stage_timing`) are tested directly, and the
single-run rendering is tested on a hand-built Timeline.
"""

from __future__ import annotations

from pathlib import Path

from dos import timeline as T


# ---- _fmt_dur ------------------------------------------------------------


def test_fmt_dur_none_is_blank():
    assert T._fmt_dur(None) == ""


def test_fmt_dur_seconds_under_90():
    assert T._fmt_dur(0) == "0s"
    assert T._fmt_dur(45.4) == "45s"
    assert T._fmt_dur(89) == "89s"


def test_fmt_dur_minutes_at_and_over_90s():
    # 90s crosses into minutes formatting.
    assert T._fmt_dur(90) == "1.5m"
    assert T._fmt_dur(510) == "8.5m"
    assert T._fmt_dur(1800) == "30.0m"


# ---- _percentile ---------------------------------------------------------


def test_percentile_empty_is_zero():
    assert T._percentile([], 50) == 0.0


def test_percentile_single_value():
    assert T._percentile([7.0], 50) == 7.0
    assert T._percentile([7.0], 90) == 7.0


def test_percentile_nearest_rank():
    vals = [80, 495, 510, 520, 600]
    assert T._percentile(vals, 50) == 510
    assert T._percentile(vals, 90) == 600
    assert T._percentile(vals, 0) == 80


# ---- _render_stage_timing ------------------------------------------------


def test_render_stage_timing_empty():
    out = T._render_stage_timing({})
    assert "no timed stages" in out


def test_render_stage_timing_sorts_by_median_desc():
    timing = {
        "child1": [("r1", 510.0), ("r2", 495.0), ("r3", 520.0)],
        "child2": [("r4", 1800.0), ("r5", 1500.0)],
    }
    out = T._render_stage_timing(timing)
    lines = [ln for ln in out.splitlines() if ln.strip().startswith(("child1", "child2"))]
    # child2 (median 1500) must sort above child1 (median 510).
    assert lines[0].strip().startswith("child2")
    assert lines[1].strip().startswith("child1")


def test_render_stage_timing_names_slowest_run():
    timing = {"child1": [("r1", 100.0), ("r2", 600.0), ("r3", 200.0)]}
    out = T._render_stage_timing(timing)
    # The slowest-run drill-in pointer must name r2 (the 600s run).
    assert "r2" in out


# ---- single-run render ---------------------------------------------------


def _stage_timeline() -> T.Timeline:
    t = T.Timeline(run_ts="20260101T000000Z", run_dir=T._repo() / "x")
    T._add(t, "invoke", "upper", "ok", "args=--scope CD")
    T._add(t, "child1", "child1", "halt", "dur=8.5m stop=BLOCKED", duration_s=510.0)
    T._add(t, "child2", "child2", "info", "not launched")  # no duration
    return t


def test_render_text_has_time_column_and_slowest_flag():
    out = T.render_text(_stage_timeline())
    assert "time" in out  # header column present
    assert "8.5m" in out  # child1 duration rendered
    assert "◀ slowest" in out  # slowest flag on the only timed stage
    # marker stage (invoke) has no duration → no glyph clutter on its row
    assert "timed stages: 1" in out


def test_render_text_no_timed_stages_omits_summary():
    t = T.Timeline(run_ts="20260101T000000Z", run_dir=T._repo() / "x")
    T._add(t, "invoke", "upper", "ok", "args=--scope CD")
    T._add(t, "gate", "upper", "miss", "no verdict")
    out = T.render_text(t)
    assert "◀ slowest" not in out  # nothing to flag
    assert "timed stages:" not in out  # summary suppressed when no timing


def test_render_json_exposes_duration_s():
    import json

    t = _stage_timeline()
    payload = json.loads(T.render_json(t))
    by_stage = {s["stage"]: s for s in payload["stages"]}
    assert by_stage["child1"]["duration_s"] == 510.0
    assert by_stage["child2"]["duration_s"] is None
    assert by_stage["invoke"]["duration_s"] is None


# ---- _stage_duration_s (marker-stage timing from orchestration-timings) ----


def _timeline_with_orch(spans: list[dict]) -> T.Timeline:
    t = T.Timeline(run_ts="20260101T000000Z", run_dir=T._repo() / "x")
    t.orchestration_timings = {"subsystem": "dispatch", "spans": spans}
    return t


def test_stage_duration_none_when_no_orchestration_timings():
    t = T.Timeline(run_ts="20260101T000000Z", run_dir=T._repo() / "x")
    # The previously-always-None behaviour must hold for runs that predate the
    # tracer (no orchestration-timings.json → no marker durations).
    assert T._stage_duration_s(t, "gate") is None


def test_stage_duration_reads_matching_span_ms_to_s():
    t = _timeline_with_orch([
        {"step": "packet", "elapsed_ms": 1200.0},
        {"step": "gate", "elapsed_ms": 3400.0},
    ])
    assert T._stage_duration_s(t, "gate") == 3.4
    assert T._stage_duration_s(t, "packet") == 1.2


def test_stage_duration_none_for_unmatched_stage():
    t = _timeline_with_orch([{"step": "packet", "elapsed_ms": 1200.0}])
    # A stage with no matching span stays None — never a misleading 0.0.
    assert T._stage_duration_s(t, "oracle") is None


def test_stage_duration_sums_repeated_spans():
    # A stage entered more than once accumulates.
    t = _timeline_with_orch([
        {"step": "oracle", "elapsed_ms": 500.0},
        {"step": "oracle", "elapsed_ms": 700.0},
    ])
    assert T._stage_duration_s(t, "oracle") == 1.2


def test_stage_duration_tolerates_malformed_spans():
    t = _timeline_with_orch([
        {"step": "gate", "elapsed_ms": "not-a-number"},
        {"step": "gate", "elapsed_ms": 1000.0},
        "not-a-dict",
    ])
    # The bad value is skipped; the good one still counts.
    assert T._stage_duration_s(t, "gate") == 1.0
