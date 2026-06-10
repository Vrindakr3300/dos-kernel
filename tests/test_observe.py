"""`dos observe` — the verdict-journal projection (docs/262).

Pins the read-only-projection contract: `build_frame` reads the journal once,
applies the `--run`/`--syscall` filters, folds the rest, and renders deterministic
text. The fold + render are pure (the `decisions.collect_decisions` /
`timeline.build_timeline` test posture).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dos import observe
from dos import verdict_journal as vj
from dos.verdict_journal import VerdictEvent, record


@pytest.fixture()
def journal(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "verdict-journal.jsonl"
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH", str(p))
    return p


def _seed(journal):
    record(VerdictEvent(syscall="liveness", verdict="ADVANCING", run_id="RID-A"))
    record(VerdictEvent(syscall="liveness", verdict="STALLED", run_id="RID-A"))
    record(VerdictEvent(syscall="verify", verdict="SHIPPED", run_id="RID-A",
                        subject="docs/82::liveness"))
    record(VerdictEvent(syscall="efficiency", verdict="WASTEFUL", run_id="RID-B",
                        detail={"tokens": 5000, "work": 0}))


def test_build_frame_default_rollup(journal):
    """The bare frame folds the whole journal by syscall."""
    _seed(journal)
    frame = observe.build_frame()
    assert frame.rollup.total == 4
    assert frame.rollup.counts["liveness"] == {"ADVANCING": 1, "STALLED": 1}
    assert frame.rollup.counts["verify"] == {"SHIPPED": 1}
    assert frame.rollup.counts["efficiency"] == {"WASTEFUL": 1}
    assert frame.corrupt == 0


def test_build_frame_run_filter(journal):
    """--run filters to one run's events (the trace join)."""
    _seed(journal)
    frame = observe.build_frame(run="RID-B")
    assert frame.run == "RID-B"
    assert frame.rollup.total == 1
    assert [e.verdict for e in frame.events] == ["WASTEFUL"]


def test_build_frame_syscall_filter(journal):
    """--syscall filters to one dimension."""
    _seed(journal)
    frame = observe.build_frame(syscall="liveness")
    assert frame.rollup.total == 2
    assert all(e.syscall == "liveness" for e in frame.events)


def test_build_frame_by_dimension(journal):
    """--by folds on a different dimension (run_id here)."""
    _seed(journal)
    frame = observe.build_frame(by="run_id")
    assert frame.rollup.by == "run_id"
    # RID-A had 3 verdicts, RID-B had 1.
    assert sum(frame.rollup.counts["RID-A"].values()) == 3
    assert sum(frame.rollup.counts["RID-B"].values()) == 1


def test_render_rollup_text_lists_each_dimension(journal):
    _seed(journal)
    frame = observe.build_frame()
    txt = observe.render_rollup_text(frame)
    assert "4 verdict event(s) recorded" in txt
    assert "liveness" in txt and "ADVANCING=1" in txt and "STALLED=1" in txt
    assert "efficiency" in txt and "WASTEFUL=1" in txt


def test_render_history_text_shows_events_in_order(journal):
    _seed(journal)
    frame = observe.build_frame(run="RID-A")
    txt = observe.render_history_text(frame)
    # The three RID-A verdicts appear, with the verify subject + detail.
    assert "ADVANCING" in txt and "STALLED" in txt and "SHIPPED" in txt
    assert "docs/82::liveness" in txt
    # Ordered: ADVANCING precedes STALLED precedes SHIPPED (append order).
    assert txt.index("ADVANCING") < txt.index("STALLED") < txt.index("SHIPPED")


def test_empty_journal_renders_honest_nothing(journal):
    """An empty journal is a valid 'nothing recorded yet', not a crash."""
    frame = observe.build_frame()
    assert frame.rollup.total == 0
    txt = observe.render_rollup_text(frame)
    assert "no verdicts recorded yet" in txt


def test_frame_to_dict_round_trips(journal):
    _seed(journal)
    d = observe.build_frame(run="RID-A").to_dict()
    assert d["run"] == "RID-A"
    assert d["rollup"]["total"] == 3
    assert len(d["events"]) == 3
