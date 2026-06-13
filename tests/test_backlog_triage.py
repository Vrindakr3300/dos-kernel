"""Pin the backlog triage oracle (`scripts/backlog_triage.py`, docs/315).

The deterministic floor under "work the backlog": every open issue folds into
exactly one disposition from a closed set, the offerable rows are ordered
(priority tier → ready bias → freshness → FIFO), and a recorded attempt makes
the kernel's own cooldown fold hold the unit. These tests pin the PURE core
with synthetic issues — no `gh`, no network — plus one journal round-trip.

The conservative directions pinned here are load-bearing:
  * T1 detection UNDER-matches (literal path substring only; empty set → off).
  * Freshness reorders WITHIN a priority tier, never across one.
  * NEEDS_PLAN is OFFERABLE (the design half of the backlog is work, not noise).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backlog_triage.py"
_spec = importlib.util.spec_from_file_location("backlog_triage", _HELPER_PATH)
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)

# A synthetic guard surface — the classifier takes surfaces as a PARAMETER, so
# no real guarded path needs to appear anywhere in this file.
_SURFACES = ("src/kernel_core/admission.py", "src/kernel_core/arbiter_core.py")


def _issue(number, title="t", labels=(), body=""):
    return {
        "number": number,
        "title": title,
        "labels": sorted(labels),
        "body": body,
        "updated_at": "",
    }


# ---------------------------------------------------------------------------
# classify_issue — one disposition per issue, precedence pinned.
# ---------------------------------------------------------------------------


def test_human_only_is_operator_gated():
    row = bt.classify_issue(_issue(1, labels=["human-only", "ready"]))
    assert row["disposition"] == bt.OPERATOR_GATED
    assert row["work_kind"] == "operator"


def test_t1_surface_in_body_is_gated_and_names_the_file():
    row = bt.classify_issue(
        _issue(2, body="the fix edits src/kernel_core/admission.py directly"),
        t1_surfaces=_SURFACES,
    )
    assert row["disposition"] == bt.T1_GATED
    assert "src/kernel_core/admission.py" in row["reason"]


def test_t1_matches_backslash_paths_too():
    row = bt.classify_issue(
        _issue(3, body=r"see src\kernel_core\admission.py"), t1_surfaces=_SURFACES
    )
    assert row["disposition"] == bt.T1_GATED


def test_t1_under_matches_empty_set_and_unrelated_text():
    assert bt.classify_issue(_issue(4, body="edit anything"), t1_surfaces=())[
        "disposition"] == bt.READY
    # A basename alone must NOT fire — literal relative path only.
    row = bt.classify_issue(_issue(5, body="touch admission.py"), t1_surfaces=_SURFACES)
    assert row["disposition"] == bt.READY


def test_human_only_outranks_t1():
    row = bt.classify_issue(
        _issue(6, labels=["human-only"], body="src/kernel_core/admission.py"),
        t1_surfaces=_SURFACES,
    )
    assert row["disposition"] == bt.OPERATOR_GATED


def test_cooling_holds_before_design_split():
    cooling = {7: {"until_ms": 123, "reason": "tried recently"}}
    row = bt.classify_issue(_issue(7, labels=["design"]), cooling=cooling)
    assert row["disposition"] == bt.COOLING
    assert row["until_ms"] == 123


def test_design_without_plan_is_needs_plan_and_offerable():
    row = bt.classify_issue(_issue(8, labels=["design"]))
    assert row["disposition"] == bt.NEEDS_PLAN
    assert row["work_kind"] == "write-plan"
    assert row["disposition"] in bt.OFFERABLE


def test_design_with_plan_is_ready_execute_plan():
    row = bt.classify_issue(_issue(9, labels=["design"]), planned_numbers=frozenset({9}))
    assert row["disposition"] == bt.READY
    assert row["work_kind"] == "execute-plan"


def test_plain_issue_is_ready_code():
    row = bt.classify_issue(_issue(10, labels=["bug"]))
    assert row["disposition"] == bt.READY
    assert row["work_kind"] == "code"


# ---------------------------------------------------------------------------
# Ordering — priority tier first; freshness only WITHIN a tier; FIFO last.
# ---------------------------------------------------------------------------


def test_priority_tier_map():
    assert bt.priority_tier(["priority:high"]) == 0
    assert bt.priority_tier(["priority:medium"]) == 1
    assert bt.priority_tier([]) == 2
    assert bt.priority_tier(["priority:low"]) == 3
    # The minimum wins when several are present.
    assert bt.priority_tier(["priority:low", "priority:high"]) == 0


def _rows(*issues, **kw):
    return [bt.classify_issue(i, **kw) for i in issues]


def test_order_priority_beats_freshness():
    rows = _rows(
        _issue(11, labels=["priority:medium", "ready"]),
        _issue(12, labels=["priority:high", "ready"]),
    )
    # 12 was attempted (stale), 11 never — priority must still win.
    queue = bt.order_queue(rows, {12: 1_000})
    assert [r["number"] for r in queue] == [12, 11]


def test_order_ready_bias_within_tier():
    rows = _rows(_issue(13, labels=[]), _issue(14, labels=["ready"]))
    queue = bt.order_queue(rows, {})
    assert [r["number"] for r in queue] == [14, 13]


def test_order_freshness_within_tier_never_attempted_first_then_lru():
    rows = _rows(
        _issue(15, labels=["ready"]),
        _issue(16, labels=["ready"]),
        _issue(17, labels=["ready"]),
    )
    # 15 tried most recently, 16 tried long ago, 17 never tried.
    queue = bt.order_queue(rows, {15: 2_000, 16: 1_000})
    assert [r["number"] for r in queue] == [17, 16, 15]


def test_order_fifo_tie_break():
    rows = _rows(_issue(19, labels=["ready"]), _issue(18, labels=["ready"]))
    queue = bt.order_queue(rows, {})
    assert [r["number"] for r in queue] == [18, 19]


def test_order_excludes_held_rows():
    rows = _rows(
        _issue(20, labels=["ready"]),
        _issue(21, labels=["human-only"]),
    )
    queue = bt.order_queue(rows, {})
    assert [r["number"] for r in queue] == [20]


# ---------------------------------------------------------------------------
# latest_attempts — the journal fold the freshness key reads.
# ---------------------------------------------------------------------------


def test_latest_attempts_folds_newest_and_skips_foreign_units():
    recs = [
        {"unit_id": "issue-30", "attempted_at_ms": 100},
        {"unit_id": "issue-30", "attempted_at_ms": 300},
        {"unit_id": "AUTH3", "attempted_at_ms": 999},
        {"unit_id": "issue-bad", "attempted_at_ms": 1},
        {"unit_id": "issue-31", "attempted_at_ms": "garbled"},
    ]
    assert bt.latest_attempts(recs) == {30: 300}


# ---------------------------------------------------------------------------
# triage + exit codes — the verdict IS the exit code.
# ---------------------------------------------------------------------------


def test_exit_codes():
    assert bt.queue_exit_code([]) == bt.EXIT_EMPTY
    ready = bt.classify_issue(_issue(40, labels=["ready"]))
    gated = bt.classify_issue(_issue(41, labels=["human-only"]))
    assert bt.queue_exit_code([gated]) == bt.EXIT_ALL_GATED
    assert bt.queue_exit_code([ready, gated]) == bt.EXIT_WORK_AVAILABLE


def test_triage_counts_and_queue():
    issues = [
        _issue(50, labels=["ready"]),
        _issue(51, labels=["design"]),
        _issue(52, labels=["human-only"]),
    ]
    result = bt.triage(issues)
    assert result["counts"] == {bt.READY: 1, bt.NEEDS_PLAN: 1, bt.OPERATOR_GATED: 1}
    assert [r["number"] for r in result["queue"]] == [50, 51]
    assert result["exit_code"] == bt.EXIT_WORK_AVAILABLE


def test_render_names_the_top_pick():
    result = bt.triage([_issue(60, title="fix the gate", labels=["ready"])])
    text = bt.render(result)
    assert "NEXT PICK → #60" in text
    assert "fix the gate" in text


# ---------------------------------------------------------------------------
# normalize_issue — the gh row flattening.
# ---------------------------------------------------------------------------


def test_normalize_issue_flattens_label_objects():
    row = bt.normalize_issue(
        {"number": 70, "title": "x", "labels": [{"name": "ready"}, {"name": "bug"}],
         "body": None, "updatedAt": "2026-06-12T00:00:00Z"}
    )
    assert row["labels"] == ["bug", "ready"]
    assert row["body"] == ""


def test_body_names_existing_plan():
    assert bt.body_names_existing_plan("see docs/315 for the plan", {315})
    assert not bt.body_names_existing_plan("see docs/999", {315})
    assert not bt.body_names_existing_plan("", {315})


# ---------------------------------------------------------------------------
# The journal round-trip — a recorded attempt holds the unit via the kernel's
# own cooldown fold (the integration the whole script exists to enable).
# ---------------------------------------------------------------------------


def test_recorded_attempt_round_trips_into_cooldown(tmp_path):
    from dos import lane_journal as lj
    from dos.cooldown import DEFAULT_COOLDOWN_POLICY, CooldownState, cooldown_verdict

    journal = tmp_path / "lane-journal.jsonl"
    entry = lj.attempt_entry("issue-77", outcome="drained", lane="backlog")
    lj.append(entry, journal)

    # Gather exactly as the script's boundary does (ts → attempted_at_ms).
    rows = []
    import datetime as dt
    for rec in lj.read_all(journal):
        if str(rec.get("op") or "") != "ATTEMPT":
            continue
        ts = str(rec.get("ts") or "")
        d = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        rows.append({**rec, "attempted_at_ms": int(d.timestamp() * 1000)})
    assert rows, "the attempt must be readable back from the journal"

    now_ms = rows[0]["attempted_at_ms"] + 60_000  # one minute later
    v = cooldown_verdict("issue-77", rows, now_ms=now_ms, policy=DEFAULT_COOLDOWN_POLICY)
    assert v.state is CooldownState.RECENTLY_ATTEMPTED

    # And the freshness fold demotes it below fresh work.
    assert bt.freshness_key(77, bt.latest_attempts(rows)) > bt.freshness_key(78, {})


# ---------------------------------------------------------------------------
# CLI replay mode — no gh, no journal writes; the verdict is the exit code.
# ---------------------------------------------------------------------------


def test_cli_replay_mode_json(tmp_path):
    # Hermetic journal (via _triage_json): a real recorded attempt on #80/#81
    # would otherwise hold the row COOLING and flip the exit code — the replay
    # verdict must be a function of the input alone.
    issues = [
        {"number": 80, "title": "a", "labels": [{"name": "ready"}], "body": "",
         "updatedAt": ""},
        {"number": 81, "title": "b", "labels": [{"name": "human-only"}], "body": "",
         "updatedAt": ""},
    ]
    data = _triage_json(tmp_path, issues)
    assert [r["number"] for r in data["queue"]] == [80]
    assert data["counts"][bt.OPERATOR_GATED] == 1


def _triage_json(tmp_path, issues):
    """Run the CLI in replay mode with an ISOLATED journal, return parsed JSON.
    Isolating `DISPATCH_LANE_JOURNAL_PATH` keeps the cooldown fold from holding
    a synthetic issue number that happens to carry a real recorded attempt —
    the pin must be a function of the input alone, not the host journal."""
    import os
    f = tmp_path / "issues.json"
    f.write_text(json.dumps(issues), encoding="utf-8")
    env = {**os.environ, "DISPATCH_LANE_JOURNAL_PATH": str(tmp_path / "lj.jsonl")}
    proc = subprocess.run(
        [sys.executable, str(_HELPER_PATH), "--issues-json", str(f), "--json",
         "--root", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(_HELPER_PATH.parents[1]), env=env,
    )
    assert proc.returncode == bt.EXIT_WORK_AVAILABLE, proc.stderr
    return json.loads(proc.stdout)


def test_one_way_body_cite_is_needs_plan_not_execute_plan(tmp_path):
    """#124: a `design` issue whose body cites an existing plan that does NOT
    reference the issue back is NEEDS_PLAN — a one-way mention is citation-as-
    evidence (e.g. reporting the colliding plan), not the issue's own plan."""
    (tmp_path / "docs").mkdir()
    # docs/306 exists but names some OTHER issue, not #80.
    (tmp_path / "docs" / "306_some-plan.md").write_text(
        "# 306 — a plan that owns #99\n", encoding="utf-8")
    issues = [{"number": 80, "title": "reports a collision with docs/306",
               "labels": [{"name": "design"}],
               "body": "see docs/306 — the plan this issue collides with",
               "updatedAt": ""}]
    data = _triage_json(tmp_path, issues)
    row = next(r for r in data["queue"] if r["number"] == 80)
    assert row["disposition"] == bt.NEEDS_PLAN
    assert row["work_kind"] == "write-plan"


def test_two_way_handshake_is_execute_plan(tmp_path):
    """#124: the same body cite types as execute-plan once the plan references
    the issue back — the intersection, the sound signal."""
    (tmp_path / "docs").mkdir()
    # docs/306 now references #80 back — the handshake closes.
    (tmp_path / "docs" / "306_some-plan.md").write_text(
        "# 306 — the plan for #80\n", encoding="utf-8")
    issues = [{"number": 80, "title": "design: the thing docs/306 plans",
               "labels": [{"name": "design"}],
               "body": "the plan is docs/306",
               "updatedAt": ""}]
    data = _triage_json(tmp_path, issues)
    row = next(r for r in data["queue"] if r["number"] == 80)
    assert row["disposition"] == bt.READY
    assert row["work_kind"] == "execute-plan"


def test_cli_record_attempt_requires_outcome():
    proc = subprocess.run(
        [sys.executable, str(_HELPER_PATH), "--record-attempt", "5"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(_HELPER_PATH.parents[1]),
    )
    assert proc.returncode == bt.EXIT_CONTRACT_ERROR
    assert "--outcome" in proc.stderr
