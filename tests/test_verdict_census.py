"""The verdict-usage census — per-verb invocation counts + the never-fired list (issue #20).

Pins issue #20's done-condition: running the census prints per-verb counts and a
never-fired list, the orphan set is reproducible from the two telemetry logs, and
the verb universe is DERIVED (a new CLI verb joins the denominator without a
hand-list edit). The folds are pure (the `observe` / `efficiency_trend` test
posture); only `build_census` touches disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dos import verdict_census as vc
from dos import verdict_journal as vj
from dos.verdict_journal import VerdictEvent, record


# ---------------------------------------------------------------------------
# The pure folds — records in, counts out, no disk.
# ---------------------------------------------------------------------------


def test_fold_counts_splits_the_two_sources():
    events = [
        VerdictEvent(syscall="verify", verdict="SHIPPED"),
        VerdictEvent(syscall="verify", verdict="NOT_SHIPPED"),
        VerdictEvent(syscall="liveness", verdict="ADVANCING"),
    ]
    obs = [{"verb": "pretool"}, {"verb": "pretool"}, {"verb": "stop"}]
    jc, oc = vc.fold_counts(events, obs)
    assert jc == {"verify": 2, "liveness": 1}
    assert oc == {"pretool": 2, "stop": 1}


def test_fold_reconciles_journal_and_cli_spelling():
    """`hook_exit` (journal) and `hook-exit` (CLI) fold into one bucket."""
    events = [VerdictEvent(syscall="hook_exit", verdict="BLOCK")]
    jc, _ = vc.fold_counts(events, [])
    assert jc == {"hook-exit": 1}


def test_census_orphan_is_verdict_bearing_and_silent():
    """A verdict-bearing verb with zero count is an orphan; a fired one is not;
    a never-fired NON-verdict verb is expected-silent, not an orphan."""
    universe = ["verify", "notify", "observe"]  # verify+notify bear verdicts; observe doesn't
    c = vc.census(universe, journal_counts={"verify": 3}, observation_counts={})
    by_verb = {r.verb: r for r in c.rows}
    assert by_verb["verify"].fired and not by_verb["verify"].is_orphan
    assert by_verb["notify"].is_orphan          # verdict-bearing, never fired
    assert not by_verb["observe"].is_orphan     # projection, silence by design
    assert "notify" in c.orphans
    assert "observe" in c.never_fired and "observe" not in c.orphans


def test_census_counts_a_verb_fired_in_either_log():
    universe = ["pretool", "verify"]
    c = vc.census(universe, journal_counts={"verify": 2},
                  observation_counts={"pretool": 5})
    by_verb = {r.verb: r for r in c.rows}
    assert by_verb["pretool"].total == 5 and by_verb["pretool"].observation == 5
    assert by_verb["verify"].total == 2 and by_verb["verify"].journal == 2
    assert c.total_invocations == 7
    assert c.never_fired == ()


def test_census_keeps_a_seen_verb_absent_from_the_universe():
    """A real firing of a verb the CLI introspection didn't surface is never
    dropped — it appears as a row, non-verdict-bearing unless declared."""
    c = vc.census(["verify"], journal_counts={},
                  observation_counts={"memory_recall": 4})
    verbs = {r.verb for r in c.rows}
    assert "memory_recall" in verbs
    assert next(r for r in c.rows if r.verb == "memory_recall").total == 4


# ---------------------------------------------------------------------------
# The derived universe + the drift pin.
# ---------------------------------------------------------------------------


def test_census_verbs_are_derived_from_the_cli_registry():
    """The universe is the live subparser set — `census` itself is in it, proving
    the derivation ran (not a hand-list)."""
    verbs = vc.census_verbs()
    assert "census" in verbs
    assert "verify" in verbs and "observe" in verbs
    assert len(verbs) > 50  # the whole CLI surface, not a curated few


def test_verdict_bearing_superset_of_known_syscalls():
    """Drift pin: every journal syscall is verdict-bearing here, so a new one
    cannot silently drop out of the orphan denominator. `hook_exit` is mapped to
    its CLI spelling for the comparison."""
    for s in vj.KNOWN_SYSCALLS:
        assert s in vc.VERDICT_BEARING, f"{s} missing from VERDICT_BEARING"


def test_issue_20_orphans_are_verdict_bearing():
    """The hand-audited orphan set from issue #20 is verdict-bearing, so the
    census flags each as an orphan when it never fires."""
    issue_orphans = ["notify", "reward", "breaker", "resume", "improve",
                     "reconcile", "productivity", "enumerate"]
    for o in issue_orphans:
        assert o in vc.VERDICT_BEARING, f"{o} should be a verdict-bearing verb"


# ---------------------------------------------------------------------------
# The boundary read — both logs, the done-condition integration.
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_logs(tmp_path, monkeypatch):
    """An isolated verdict journal + observation log, both wired via env/path."""
    vpath = tmp_path / "verdict-journal.jsonl"
    opath = tmp_path / "observations.jsonl"
    monkeypatch.setenv("DISPATCH_VERDICT_JOURNAL_PATH", str(vpath))
    return vpath, opath


def test_build_census_folds_both_logs_and_reproduces_the_orphan_finding(two_logs, monkeypatch):
    vpath, opath = two_logs
    # Verdict journal: verify fired, but the issue's orphan set is silent.
    record(VerdictEvent(syscall="verify", verdict="SHIPPED"))
    record(VerdictEvent(syscall="verify", verdict="NOT_SHIPPED"))
    # Observation log: the hooks fired (the dominant real traffic).
    from dos import hook_observation as ho
    for _ in range(3):
        ho.append(ho.observation_entry("pretool", "passthrough"), path=opath)
    ho.append(ho.observation_entry("stop", "block"), path=opath)

    c = vc.build_census(observation_path=opath)
    by_verb = {r.verb: r for r in c.rows}
    # Per-verb counts, folded across both logs.
    assert by_verb["verify"].total == 2
    assert by_verb["pretool"].total == 3
    assert by_verb["stop"].total == 1
    assert c.total_invocations == 6
    # The done-condition: the hand-audited orphan set is reproducible — every one
    # is in the never-fired orphan list because none of them fired.
    for o in ("notify", "reward", "breaker", "resume", "improve",
              "reconcile", "productivity", "enumerate"):
        assert o in c.orphans
    # verify fired, so it is NOT an orphan.
    assert "verify" not in c.orphans


def test_build_census_surfaces_journal_corruption(two_logs):
    vpath, opath = two_logs
    record(VerdictEvent(syscall="verify", verdict="SHIPPED"))
    # A non-trailing corrupt line becomes a _CORRUPT sentinel the census tallies.
    with open(vpath, "a", encoding="utf-8") as fh:
        fh.write("{not json}\n")
    record(VerdictEvent(syscall="liveness", verdict="ADVANCING"))
    c = vc.build_census(observation_path=opath)
    assert c.corrupt == 1


# ---------------------------------------------------------------------------
# Rendering — deterministic text + JSON round-trip.
# ---------------------------------------------------------------------------


def test_render_text_names_orphans_and_counts():
    c = vc.census(["verify", "notify"], journal_counts={"verify": 3},
                  observation_counts={})
    txt = vc.render_text(c)
    assert "verdict-usage census" in txt
    assert "verify" in txt and "3" in txt
    assert "ORPHANS" in txt and "notify" in txt


def test_render_json_round_trips():
    c = vc.census(["verify"], journal_counts={"verify": 1}, observation_counts={})
    data = json.loads(vc.render_json(c))
    assert data["total_invocations"] == 1
    assert any(r["verb"] == "verify" and r["total"] == 1 for r in data["rows"])
