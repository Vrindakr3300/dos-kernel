"""test_stall_recovery_probe.py — pin the STALLED-class false-prune finding (docs/176 §6.2).

The probe's headline — the byte-identical STALLED slice carries a ~1/3 self-recovery
(false-prune) rate, so STALLED->prune stays WARN-first — is a load-bearing honesty claim. This
pins the probe's PURE logic (the self-recovery look-ahead + the analyze fold) on hand-built runs
so the finding can't silently regress, and pins the live-corpus number when the corpus is present
(skipped otherwise, so a kernel-only checkout stays green).

Run: PYTHONPATH=../../src python -m pytest benchmark/enterpriseops/test_stall_recovery_probe.py -q
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, "..", "..", "src"), _HERE):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

from stall_recovery_probe import analyze, _tool_succeeds_after, main  # noqa: E402


def _tr(tool, args, result):
    return {"tool_name": tool, "arguments": args, "result": result}


def _ok(payload):
    return {"success": True, "result": payload}


def _err(msg):
    return {"success": True, "result": {"isError": True, "error": msg}}


# ---------------------------------------------------------------------------
# analyze(): STALLED fire detection + the self-recovery look-ahead.
# ---------------------------------------------------------------------------
def test_true_dead_end_run():
    """5 byte-identical errors, the tool never succeeds → STALLED, NOT self-recovered (a correct
    prune target)."""
    run = {"tool_results": [_tr("create_filter", {"k": "from1"}, _err("from is required"))
                            for _ in range(5)],
           "overall_success": False}
    row = analyze(run)
    assert row is not None
    assert row["tool"] == "create_filter"
    assert row["self_recovered"] is False   # true dead-end


def test_false_prune_run_self_recovers():
    """5 byte-identical results then the SAME tool SUCCEEDS → STALLED fired, but self_recovered
    True → a FALSE prune (the agent escaped on its own; pruning would destroy that)."""
    steps = [_tr("update_vacation_settings", {"t": "bad"}, _err("must be epoch ms")) for _ in range(5)]
    steps.append(_tr("update_vacation_settings", {"t": "1700000000000"}, _ok({"updated": True})))
    run = {"tool_results": steps, "overall_success": True}
    row = analyze(run)
    assert row is not None
    assert row["self_recovered"] is True    # false prune


def test_no_stall_returns_none():
    """A run with no byte-identical 5-run never STALLs → analyze returns None (not a fire)."""
    run = {"tool_results": [_tr("read_row", {"id": i}, _ok({"n": i})) for i in range(6)]}
    assert analyze(run) is None


def test_self_recovery_lookahead_only_counts_after_fire():
    """A success BEFORE the fire point does not count as recovery; only a success strictly after
    the stall fire does (the discipline that makes the false-prune number honest)."""
    # success at idx 0, then 5 identical errors → the early success is NOT a recovery of the stall
    run = {"tool_results": [_tr("t", {"a": 1}, _ok({}))]
                           + [_tr("t", {"a": 2}, _err("boom")) for _ in range(5)]}
    # the stall is on args {a:2}; the tool "t" did succeed at idx 0 (before), but recovery must be
    # AFTER the fire — there is none after, so it is a true dead-end.
    assert _tool_succeeds_after(run, "t", after_idx=6) is False


# ---------------------------------------------------------------------------
# The live-corpus number (pinned when the recorded natural corpus is present).
# ---------------------------------------------------------------------------
_CORPUS = os.path.join(_HERE, "live_results_natural_ab", "none")


@pytest.mark.skipif(not os.path.isdir(_CORPUS),
                    reason="natural-thrash corpus not present — live-number pin skipped")
def test_live_corpus_false_prune_rate_does_not_clear_bar(capsys):
    """On the recorded gemini-2.5-flash natural corpus, the STALLED slice exists (non-zero fire)
    but its false-prune rate does NOT clear the <10% bar — so STALLED->prune stays WARN-first.
    Pinned so a corpus/threshold change that flips this is caught."""
    main(["--dir", _CORPUS, "--json"])
    import json
    out = json.loads(capsys.readouterr().out)
    s = out["summary"]
    assert s["stalled_fired"] >= 1, "the byte-identical STALLED slice should be non-empty"
    assert s["false_prune_rate"] >= 0.10, (
        f"false-prune {s['false_prune_rate']} unexpectedly cleared the bar — re-read docs/176 §6.2"
    )
    assert s["clears_kill_bar"] is False
