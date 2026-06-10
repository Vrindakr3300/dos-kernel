"""Verdict-journal — the durable verdict WAL + its pure folds (docs/262).

Pins the lateral-sibling-of-`lane_journal` contract: a `record()` round-trips
through `read_all`/`read_events`; the pure `rollup`/`for_run` folds reduce a frozen
event list with no disk; the reader is torn-tail tolerant and keeps a non-trailing
corrupt line as a `_CORRUPT` sentinel; `record()` is FAIL-SOFT (a bad path returns
False, never raises); and `for_run` never fabricates an attribution by time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dos import verdict_journal as vj
from dos.verdict_journal import (
    SCHEMA_FAMILY,
    SOURCE_KERNEL,
    SOURCE_SENSOR,
    VerdictEvent,
    count_corrupt,
    for_run,
    read_all,
    read_events,
    record,
    rollup,
    tail,
)


@pytest.fixture()
def journal(tmp_path, monkeypatch) -> Path:
    """Point the verdict journal at an isolated tmp file via the env override.

    The env override is re-read every call (`_journal_path`), so setting it here
    redirects both the module functions and anything that resolves through them —
    the lane-journal test idiom.
    """
    p = tmp_path / "verdict-journal.jsonl"
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH", str(p))
    return p


# ---------------------------------------------------------------------------
# The record + the round-trip.
# ---------------------------------------------------------------------------


def test_record_appends_schema_tagged_jsonl(journal):
    """record() writes one JSONL line, schema-family-tagged, with the verdict fields."""
    ok = record(VerdictEvent(syscall="liveness", verdict="STALLED",
                             run_id="RID-1", detail={"age_min": 42}))
    assert ok is True
    assert journal.exists()
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["schema_family"] == SCHEMA_FAMILY
    assert rec["schema_version"] == vj.VERDICT_JOURNAL_SCHEMA
    assert rec["syscall"] == "liveness"
    assert rec["verdict"] == "STALLED"
    assert rec["run_id"] == "RID-1"
    assert rec["detail"] == {"age_min": 42}
    assert rec["source"] == SOURCE_KERNEL
    # The recorder stamped ts + a 1-based seq.
    assert rec["ts"]
    assert rec["seq"] == 1


def test_record_stamps_monotonic_seq(journal):
    """Successive records get increasing seqs (max existing + 1)."""
    record(VerdictEvent(syscall="verify", verdict="SHIPPED"))
    record(VerdictEvent(syscall="verify", verdict="NOT_SHIPPED"))
    record(VerdictEvent(syscall="efficiency", verdict="WASTEFUL"))
    seqs = [e.seq for e in read_events(journal)]
    assert seqs == [1, 2, 3]


def test_read_events_round_trips_a_verdict_event(journal):
    """read_events decodes back into VerdictEvents preserving every field."""
    ev = VerdictEvent(syscall="reward", verdict="REJECT_POISON", run_id="RID-9",
                      lane="src", subject="claim#3",
                      detail={"witness": "refute"}, source=SOURCE_SENSOR)
    record(ev)
    got = read_events(journal)
    assert len(got) == 1
    g = got[0]
    assert g.syscall == "reward"
    assert g.verdict == "REJECT_POISON"
    assert g.run_id == "RID-9"
    assert g.lane == "src"
    assert g.subject == "claim#3"
    assert g.detail == {"witness": "refute"}
    assert g.source == SOURCE_SENSOR


def test_tail_returns_last_n(journal):
    for i in range(5):
        record(VerdictEvent(syscall="verify", verdict=f"V{i}"))
    last2 = tail(2, journal)
    assert [r["verdict"] for r in last2] == ["V3", "V4"]
    # n<=0 returns all.
    assert len(tail(0, journal)) == 5


# ---------------------------------------------------------------------------
# Fail-soft — observability must never crash the observed syscall.
# ---------------------------------------------------------------------------


def test_record_is_fail_soft_on_unwritable_path(tmp_path, monkeypatch):
    """A path that cannot be written (a file where a dir must be) returns False,
    never raises — the notify.send_safely contract."""
    # Make the *parent* a file, so mkdir(parents=True) of the journal dir fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    bad = blocker / "sub" / "verdict-journal.jsonl"
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH", str(bad))
    # Must NOT raise; must report failure.
    assert record(VerdictEvent(syscall="verify", verdict="SHIPPED")) is False


def test_read_all_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH",
                       str(tmp_path / "nope.jsonl"))
    assert read_all() == []
    assert read_events() == []


# ---------------------------------------------------------------------------
# Torn-tail tolerance + the corrupt sentinel (the lane-journal reader posture).
# ---------------------------------------------------------------------------


def test_read_all_tolerates_torn_final_line(journal):
    """A half-written FINAL line (crash mid-append) is skipped — 'didn't happen'."""
    record(VerdictEvent(syscall="verify", verdict="SHIPPED"))
    # Append a torn final line (no newline, invalid json).
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write('{"syscall": "liveness", "verd')  # truncated
    got = read_all(journal)
    assert len(got) == 1  # only the intact first record
    assert got[0]["verdict"] == "SHIPPED"


def test_read_all_keeps_nontrailing_corrupt_as_sentinel(journal):
    """A corrupt line that is NOT the last is a real integrity breach — kept as a
    _CORRUPT sentinel so an audit sees it, never silently dropped."""
    record(VerdictEvent(syscall="verify", verdict="SHIPPED"))
    # Inject a corrupt MIDDLE line, then a valid trailing one.
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write("NOT JSON AT ALL\n")
        fh.write(json.dumps({"schema_family": SCHEMA_FAMILY, "syscall": "verify",
                             "verdict": "NOT_SHIPPED"}) + "\n")
    raw = read_all(journal)
    assert any(r.get("op") == "_CORRUPT" for r in raw)
    assert count_corrupt(raw) == 1
    # read_events drops the sentinel (a corrupt line is not a verdict).
    evs = read_events(journal)
    assert all(e.verdict in ("SHIPPED", "NOT_SHIPPED") for e in evs)
    assert len(evs) == 2


# ---------------------------------------------------------------------------
# The pure folds — entries in, data out, NO disk (the replay/collect idiom).
# ---------------------------------------------------------------------------


def _events(*specs):
    """Build VerdictEvents from (syscall, verdict[, run_id]) tuples — no disk."""
    out = []
    for s in specs:
        syscall, verdict = s[0], s[1]
        run_id = s[2] if len(s) > 2 else ""
        out.append(VerdictEvent(syscall=syscall, verdict=verdict, run_id=run_id))
    return out


def test_rollup_by_syscall_counts_per_verdict():
    """rollup folds events into per-syscall {verdict: count}, no file needed."""
    evs = _events(
        ("liveness", "ADVANCING"), ("liveness", "ADVANCING"),
        ("liveness", "STALLED"),
        ("verify", "SHIPPED"), ("verify", "NOT_SHIPPED"),
    )
    r = rollup(evs)
    assert r.total == 5
    assert r.by == "syscall"
    assert r.counts["liveness"] == {"ADVANCING": 2, "STALLED": 1}
    assert r.counts["verify"] == {"NOT_SHIPPED": 1, "SHIPPED": 1}


def test_rollup_known_syscalls_sort_first():
    """Dimension order puts KNOWN kernel syscalls first, an unknown one last."""
    evs = _events(
        ("zzz_custom", "OK"),       # unknown → sorts to the tail
        ("verify", "SHIPPED"),      # known → head
        ("liveness", "ADVANCING"),  # known → head (before verify by KNOWN order)
    )
    r = rollup(evs)
    # liveness + verify (known) precede the unknown custom dimension.
    assert r.dimensions.index("liveness") < r.dimensions.index("zzz_custom")
    assert r.dimensions.index("verify") < r.dimensions.index("zzz_custom")


def test_rollup_by_verdict_dimension():
    """rollup(by='verdict') folds on the verdict token instead of the syscall."""
    evs = _events(
        ("liveness", "STALLED"), ("productivity", "STALLED"),
        ("verify", "SHIPPED"),
    )
    r = rollup(evs, by="verdict")
    assert r.counts["STALLED"] == {"STALLED": 2}
    assert r.counts["SHIPPED"] == {"SHIPPED": 1}


def test_rollup_carries_corrupt_tally():
    r = rollup(_events(("verify", "SHIPPED")), corrupt=3)
    assert r.corrupt == 3
    assert r.to_dict()["corrupt"] == 3


def test_for_run_slices_by_run_id_and_never_fabricates():
    """for_run returns only events carrying the exact run_id; an unattributed
    event (run_id='') is NEVER guessed onto a run (docs/118 fail-toward-no-match)."""
    evs = _events(
        ("verify", "SHIPPED", "RID-A"),
        ("liveness", "STALLED", "RID-B"),
        ("efficiency", "WASTEFUL", ""),   # unattributed
    )
    a = for_run(evs, "RID-A")
    assert [e.verdict for e in a] == ["SHIPPED"]
    # The unattributed event joins to NO run.
    assert for_run(evs, "") == [evs[2]]  # explicit "" matches the empty one only
    assert for_run(evs, "RID-A") and evs[2] not in for_run(evs, "RID-A")


def test_rollup_empty_is_zero_total():
    r = rollup([])
    assert r.total == 0
    assert r.dimensions == ()
    assert r.counts == {}


# ---------------------------------------------------------------------------
# from_record tolerance — an older/partial record decodes to defaults.
# ---------------------------------------------------------------------------


def test_from_record_tolerates_missing_fields():
    """A minimal record (older kernel) decodes with defaults, never raises."""
    ev = VerdictEvent.from_record({"syscall": "verify", "verdict": "SHIPPED"})
    assert ev.run_id == ""
    assert ev.lane == ""
    assert ev.detail == {}
    assert ev.source == SOURCE_KERNEL
    assert ev.seq == 0


def test_from_record_coerces_bad_detail_to_empty_dict():
    """A malformed non-dict detail becomes {} rather than crashing the reader."""
    ev = VerdictEvent.from_record(
        {"syscall": "verify", "verdict": "SHIPPED", "detail": "not-a-dict", "seq": "x"})
    assert ev.detail == {}
    assert ev.seq == 0  # unparseable seq → 0
