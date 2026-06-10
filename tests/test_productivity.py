"""PRD — the productivity verdict + the pure classifier (docs/212).

`productivity.classify` is `liveness`'s lateral sibling: a PURE trend verdict over
a list of per-step work deltas the caller already has. Where `liveness` asks "did
state move *at all* since start?" (a single since-start count), PRD asks "is the
work-per-step rate *fading*?" (a trend over the recent deltas) — the diminishing-
returns gate lifted from Claude Code's own loop (`tokenBudget.ts` `checkTokenBudget`).

These tests pin the ladder on FROZEN histories (no clock, no I/O — productivity is
timeless) and the no-plan rail through the real CLI.

The verdict ladder under test:

  1. PRODUCTIVE  — fewer than `min_steps` steps (too little trend to judge).
  2. STALLED     — the most recent step landed 0 work (flat-lined).
  3. DIMINISHING — `steps >= min_steps` AND the last two deltas BOTH under `floor`.
  4. PRODUCTIVE  — a recent step cleared the floor / the low rate is not sustained.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import productivity
from dos.productivity import (
    Productivity,
    ProductivityPolicy,
    WorkHistory,
    classify,
)

# A policy with an explicit, readable floor (100 work units) and the default
# 3-step minimum, so the tests read concretely.
_POLICY = ProductivityPolicy(min_steps=3, floor=100)


# ---------------------------------------------------------------------------
# The pure-classifier ladder, on frozen histories.
# ---------------------------------------------------------------------------


def test_too_little_history_is_productive():
    """Fewer than min_steps steps → PRODUCTIVE (withhold the accusation)."""
    # Two steps, both tiny — but only two steps, so there is no trend to judge.
    v = classify(WorkHistory.of([10, 5]), _POLICY)
    assert v.verdict is Productivity.PRODUCTIVE
    assert "not enough history" in v.reason


def test_empty_history_is_productive():
    """No steps at all → PRODUCTIVE (nothing to judge, no problem yet)."""
    v = classify(WorkHistory.of([]), _POLICY)
    assert v.verdict is Productivity.PRODUCTIVE


def test_sustained_low_rate_is_diminishing():
    """>= min_steps AND last two deltas both under floor → DIMINISHING.

    The CC `isDiminishing` rule: enough steps, and a SUSTAINED low rate.
    """
    # 5 steps; the run was productive early (800, 600, 300) then faded (40, 12).
    v = classify(WorkHistory.of([800, 600, 300, 40, 12]), _POLICY)
    assert v.verdict is Productivity.DIMINISHING
    assert "diminishing returns" in v.reason
    # The reason names the two load-bearing deltas (prior then last).
    assert "40 then 12" in v.reason


def test_one_recent_step_over_floor_is_productive():
    """A single recent step clearing the floor keeps the run PRODUCTIVE.

    The multi-signal AND: even with a tiny last step, a prior step over the floor
    means the low rate is NOT sustained — one quiet step is a blip, not a fade.
    """
    # Last step tiny (12) but the prior cleared the floor (250) → not sustained.
    v = classify(WorkHistory.of([800, 600, 300, 250, 12]), _POLICY)
    assert v.verdict is Productivity.PRODUCTIVE


def test_last_step_over_floor_is_productive():
    """A recent big step keeps it PRODUCTIVE even after small ones."""
    # The run dipped (40, 30) then recovered (500) → the last step cleared the floor.
    v = classify(WorkHistory.of([40, 30, 500]), _POLICY)
    assert v.verdict is Productivity.PRODUCTIVE


def test_zero_most_recent_step_is_stalled():
    """The most recent step landing 0 work → STALLED (flat-lined), not DIMINISHING.

    A zero is the operator's clearest "it stopped" signal — named distinctly from a
    merely-fading-but-nonzero rate.
    """
    v = classify(WorkHistory.of([800, 50, 0]), _POLICY)
    assert v.verdict is Productivity.STALLED
    assert "flat-lined" in v.reason


def test_zero_takes_precedence_over_diminishing():
    """An exact flat-line is STALLED even when the trend would also be DIMINISHING."""
    # Last two deltas (10, 0) are both under floor → would be DIMINISHING, but the
    # zero last step makes it the more precise STALLED.
    v = classify(WorkHistory.of([800, 60, 10, 0]), _POLICY)
    assert v.verdict is Productivity.STALLED


def test_diminishing_needs_the_min_step_count():
    """Both recent deltas under floor but < min_steps → still PRODUCTIVE.

    Pins the trend-length guard: a short fading sequence is not yet judged.
    """
    # Two steps, both under floor — but min_steps is 3, so no DIMINISHING yet.
    v = classify(WorkHistory.of([40, 12]), _POLICY)
    assert v.verdict is Productivity.PRODUCTIVE


def test_exactly_min_steps_can_be_diminishing():
    """At exactly min_steps with both recent deltas under floor → DIMINISHING."""
    v = classify(WorkHistory.of([300, 40, 12]), _POLICY)
    assert v.verdict is Productivity.DIMINISHING


# ---------------------------------------------------------------------------
# Structural guarantees.
# ---------------------------------------------------------------------------


def test_classify_is_pure(monkeypatch):
    """`classify` makes NO I/O — no clock, no file, no subprocess.

    Productivity is timeless: unlike `liveness` it does not even read an age, so
    banning the clock proves the verdict is a pure fold over the sequence.
    """
    import builtins
    import time as _time

    def _boom(*a, **k):  # pragma: no cover - only fires on a violation
        raise AssertionError("classify must not perform I/O")

    monkeypatch.setattr(_time, "time", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    # A representative call still returns a verdict with the clock/open banned.
    v = classify(WorkHistory.of([800, 600, 300, 40, 12]), _POLICY)
    assert v.verdict is Productivity.DIMINISHING


def test_verdict_to_dict_round_trips_history():
    """`to_dict` carries the verdict AND the trend (the legible-distrust shape)."""
    v = classify(WorkHistory.of([800, 600, 300, 40, 12]), _POLICY)
    d = v.to_dict()
    assert d["verdict"] == "DIMINISHING"
    assert d["history"]["deltas"] == [800, 600, 300, 40, 12]
    assert d["history"]["step_count"] == 5
    assert d["history"]["last_delta"] == 12
    assert d["history"]["prior_delta"] == 40
    # The dict is JSON-serializable (the --output json contract).
    assert json.loads(json.dumps(d, sort_keys=True)) == d


def test_to_dict_handles_short_history():
    """last/prior deltas are None when the history is too short to have them."""
    assert classify(WorkHistory.of([])).to_dict()["history"]["last_delta"] is None
    one = classify(WorkHistory.of([5])).to_dict()["history"]
    assert one["last_delta"] == 5
    assert one["prior_delta"] is None


def test_policy_rejects_negative_thresholds():
    with pytest.raises(ValueError):
        ProductivityPolicy(min_steps=-1)
    with pytest.raises(ValueError):
        ProductivityPolicy(floor=-1)


def test_history_rejects_negative_deltas():
    """A work delta is a non-negative quantity of work done."""
    with pytest.raises(ValueError):
        WorkHistory.of([100, -5, 50])


def test_history_freezes_a_list_to_a_tuple():
    """A list passed at the boundary is frozen — no shared-mutable field."""
    h = WorkHistory.of([1, 2, 3])
    assert isinstance(h.deltas, tuple)
    assert h.step_count == 3


def test_default_policy_matches_cc_constants():
    """The generic defaults are the CC `tokenBudget.ts` values (3 steps / 500)."""
    p = ProductivityPolicy()
    assert p.min_steps == 3
    assert p.floor == 500


def test_degenerate_min_steps_below_two_never_indexes_off_the_end():
    """A pathological min_steps<2 policy is safe (the prior-delta guard).

    A one-step history can only be PRODUCTIVE or STALLED — never DIMINISHING, which
    needs a prior delta. The guard treats the missing prior as above-floor.
    """
    p = ProductivityPolicy(min_steps=1, floor=100)
    # One small step: passes the (tiny) min_steps, last under floor, but no prior →
    # the prior guard makes it NOT diminishing → PRODUCTIVE.
    assert classify(WorkHistory.of([10]), p).verdict is Productivity.PRODUCTIVE
    # One zero step → STALLED (the flat-line rung wins regardless of min_steps).
    assert classify(WorkHistory.of([0]), p).verdict is Productivity.STALLED


# ---------------------------------------------------------------------------
# The CLI verb (`dos productivity`) — the boundary + the verdict-is-exit-code.
# ---------------------------------------------------------------------------


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_productivity_cli_diminishing_exit_code(tmp_path: Path):
    """`dos productivity --deltas …` → DIMINISHING is exit 3 (the verdict IS the code)."""
    r = _run_cli(
        "productivity", "--deltas", "800,600,300,40,12", "--floor", "100",
        cwd=tmp_path,
    )
    assert r.returncode == 3, r.stderr
    assert "DIMINISHING" in r.stdout


def test_productivity_cli_productive_exit_zero(tmp_path: Path):
    """A still-productive run → exit 0 (ADVANCING's success-is-0 idiom)."""
    r = _run_cli(
        "productivity", "--deltas", "40,30,500", "--floor", "100",
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "PRODUCTIVE" in r.stdout


def test_productivity_cli_stalled_exit_code(tmp_path: Path):
    """A flat-lined run → STALLED is exit 4."""
    r = _run_cli("productivity", "--deltas", "800,50,0", cwd=tmp_path)
    assert r.returncode == 4, r.stderr
    assert "STALLED" in r.stdout


def test_productivity_cli_json(tmp_path: Path):
    """`--json` emits the verdict object with the trend echoed."""
    r = _run_cli(
        "productivity", "--deltas", "800,600,300,40,12", "--floor", "100", "--json",
        cwd=tmp_path,
    )
    assert r.returncode == 3, r.stderr
    obj = json.loads(r.stdout)
    assert obj["verdict"] == "DIMINISHING"
    assert obj["history"]["deltas"] == [800, 600, 300, 40, 12]


def test_productivity_cli_no_plan(tmp_path: Path):
    """The no-plan rail: runs in a bare dir with NO git, NO plan, NO journal.

    Productivity needs nothing but the deltas — the strongest no-plan floor of any
    verdict (it does not even read git, unlike `liveness`).
    """
    # tmp_path is an empty directory — not even a git repo.
    r = _run_cli("productivity", "--deltas", "300,40,12", "--floor", "100", cwd=tmp_path)
    assert r.returncode == 3, r.stderr
    assert "DIMINISHING" in r.stdout
    # No state was created (read-only, no-I/O verdict).
    assert not (tmp_path / ".dos").exists()


def test_productivity_cli_empty_deltas_is_productive(tmp_path: Path):
    """No deltas at all → PRODUCTIVE (nothing to judge), exit 0."""
    r = _run_cli("productivity", "--deltas", "", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "PRODUCTIVE" in r.stdout


def test_productivity_cli_rejects_bad_deltas(tmp_path: Path):
    """A non-numeric delta is a contract error (exit 2), never read as a verdict."""
    r = _run_cli("productivity", "--deltas", "300,oops,12", cwd=tmp_path)
    assert r.returncode == 2
    assert "error" in r.stderr.lower()
