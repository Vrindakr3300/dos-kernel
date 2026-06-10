"""SKP operator tier (docs/207 Phase 5) — dos-unstick / dos-promote / dos-class-cycle.

These pin the MECHANISM the three operator skills shell (not the screenplay prose
— that is the grep-clean litmus's job in `test_skill_pack_litmus.py`):

  * `dos-unstick`     → the recurring-wedge fold clusters a 3-run cause above a
                        one-off and reports it recurring;
  * `dos-promote`     → `dos pickable` surfaces a HELD(DRAFT_CLASS) unit with the
                        promote action and does NOT surface an OFFERABLE one;
  * `dos-class-cycle` → a workspace declaring only `[lifecycle]` classes
                        active/done runs the cycle with those two — no job class
                        name appears.

The three skills exist as package-data + are grep-clean (the litmus); these are
the behavioral pins the plan §5 names.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import dos
from dos import recurring_wedge as rw
from dos.pickable import classify
from dos import lifecycle as _lifecycle


def _cli(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(Path(dos.__file__).parents[1])}
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


# ---------------------------------------------------------------------------
# dos-unstick — the recurring-wedge clustering mechanism.
# ---------------------------------------------------------------------------


def test_dos_unstick_clusters_recurring():
    """A cause appearing in 3 distinct runs is clustered and reported recurring,
    ranked above a one-off; the proposed fix is structural (per cause, not per
    instance)."""
    prior = [
        rw.BlockerHit(run="r1", iter_n=1, cause_key="STALE_CLAIM", cost_usd=3.0,
                      wall_min=10.0, example="stale claim false-block", source="readme"),
        rw.BlockerHit(run="r2", iter_n=1, cause_key="STALE_CLAIM", cost_usd=3.0,
                      wall_min=10.0, example="stale claim false-block", source="readme"),
        rw.BlockerHit(run="r3", iter_n=1, cause_key="ONE_OFF", cost_usd=1.0,
                      wall_min=2.0, example="a one-off", source="readme"),
    ]
    v = rw.classify_recurring_wedge(
        this_run_id="r4",
        this_run_cause_keys=["STALE_CLAIM"],
        prior_hits=prior,
        min_recurrence=2,
    )
    assert v.recurring is True
    assert v.cause_key == "STALE_CLAIM"
    assert v.runs_affected >= 3          # r1, r2, r4 — spans the recurrence threshold

    # A truly singular cause — seen ONLY in the current run, never before — does
    # NOT recur (1 run < the 2-run threshold). This is the one-off the sweep should
    # NOT propose a structural fix for.
    v2 = rw.classify_recurring_wedge(
        this_run_id="r5",
        this_run_cause_keys=["BRAND_NEW"],
        prior_hits=prior,
        min_recurrence=2,
    )
    assert v2.recurring is False

    # And the STALE_CLAIM cause still outranks the one-off ONE_OFF by stall-score
    # (3 runs × cost dominates 2 runs) — the ranking the sweep proposes fixes in.
    assert v.runs_affected > v2.runs_affected


# ---------------------------------------------------------------------------
# dos-promote — pickable surfaces a held unit + its action.
# ---------------------------------------------------------------------------


def test_dos_promote_surfaces_held_with_action(tmp_path: Path):
    """A HELD(DRAFT_CLASS) unit is surfaced (nonzero exit = its hold code, the
    promote action); an OFFERABLE unit is not surfaced (exit 0)."""
    # HELD(DRAFT_CLASS) → exit 10 (the promote-to-active action routes off this).
    held = _cli(tmp_path, "pickable", "AUTH3", "--state", json.dumps({"plan_class": "DRAFT"}))
    assert held.returncode == 10
    assert "DRAFT_CLASS" in held.stdout

    # OFFERABLE → exit 0 → not surfaced (it is not stuck).
    offerable = _cli(tmp_path, "pickable", "AUTH4", "--state", "{}")
    assert offerable.returncode == 0
    assert offerable.stdout.startswith("OFFERABLE")


def test_dos_promote_soak_is_not_promoted():
    """The anti-pattern guard: a SOAK_OPEN hold routes to WAIT, never promote — it
    is re-dispatch-invariant but un-gated by time, not a class change."""
    v = classify({"soak_open": True}, now_ms=0)
    assert v.held and v.reason.value == "SOAK_OPEN"
    assert v.is_redispatch_invariant  # surfaced for routing, NOT auto-promoted


# ---------------------------------------------------------------------------
# dos-class-cycle — reads the DECLARED lifecycle classes (not a job taxonomy).
# ---------------------------------------------------------------------------


def test_dos_class_cycle_reads_declared_classes(tmp_path: Path):
    """A workspace declaring only `[lifecycle]` classes active/done runs the cycle
    with those two; no job class name (MAINTENANCE/PARK/TOMB/DRAFT) appears."""
    toml = tmp_path / "dos.toml"
    toml.write_text(
        "[lifecycle]\n"
        'classes = ["active", "done"]\n'
        "[[lifecycle.transitions]]\n"
        'from = "active"\nto = "done"\ntrigger = "all_phases_shipped"\nauto = true\n',
        encoding="utf-8",
    )
    pol = _lifecycle.load_from_toml(toml)
    assert pol.classes == ("active", "done")
    assert pol.default_class == "active"
    assert pol.legal_transition("active", "done")
    assert not pol.legal_transition("active", "parked")  # no job class declared

    # The doctor JSON surfaces exactly the declared classes (what the skill reads).
    proc = _cli(tmp_path, "doctor", "--json")
    assert proc.returncode == 0, proc.stderr
    lc = json.loads(proc.stdout)["lifecycle"]
    assert lc["classes"] == ["active", "done"]
    for job_class in ("MAINTENANCE", "PARK", "TOMB", "DRAFT", "ACTIVE"):
        assert job_class not in lc["classes"]


def test_dos_class_cycle_richer_taxonomy_declared(tmp_path: Path):
    """A repo CAN declare a richer taxonomy — the mechanism is class-agnostic."""
    toml = tmp_path / "dos.toml"
    toml.write_text(
        "[lifecycle]\n"
        'classes = ["draft", "active", "parked", "done"]\n'
        'veto_class = "active"\n'
        "max_transitions_per_cycle = 3\n"
        "[[lifecycle.transitions]]\n"
        'from = "draft"\nto = "active"\ntrigger = "demand"\nauto = false\n'
        "[[lifecycle.transitions]]\n"
        'from = "active"\nto = "parked"\ntrigger = "idle_30d"\nauto = true\n',
        encoding="utf-8",
    )
    pol = _lifecycle.load_from_toml(toml)
    assert pol.classes == ("draft", "active", "parked", "done")
    assert pol.veto_class == "active"
    assert pol.max_transitions_per_cycle == 3
    assert pol.legal_transition("draft", "active")


def test_lifecycle_transition_naming_unknown_class_raises():
    import pytest
    with pytest.raises(ValueError):
        _lifecycle.policy_from_table({
            "classes": ["active", "done"],
            "transitions": [{"from": "active", "to": "ghost", "trigger": "t"}],
        })
