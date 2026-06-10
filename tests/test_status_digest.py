"""Tests for the status digest — the pure fold (docs/120 Phase 1).

The load-bearing test is `test_claimed_field_absent_from_digest`: the digest's
whole point (docs/120 §3) is that it folds adjudicated verdicts into one fact and
*structurally cannot* surface a self-report — `claimed` is not a field of the output.
The rest pin the fail-closed assembly (no-intent → zero progress, never a raise) and
the pure-function discipline (no I/O, the `liveness.classify` idiom).
"""
from __future__ import annotations

import builtins
import subprocess
import time as _time

from dos.intent_ledger import LedgerState, VerifiedStep
from dos.liveness import DEFAULT_POLICY, Liveness, ProgressEvidence, classify
from dos.resume import Resume, ResumePlan
from dos.status import ProgressView, StatusDigest, status_digest


# ---------------------------------------------------------------------------
# Fixtures — real verdicts built the way the codebase builds them.
# ---------------------------------------------------------------------------

def _live() -> "object":
    """A real ADVANCING LivenessVerdict via the pure classifier (test_liveness idiom)."""
    return classify(
        ProgressEvidence(run_started_ms=1_000, now_ms=2_000, commits_since_start=1),
        DEFAULT_POLICY,
    )


def _ledger(**over) -> LedgerState:
    base = dict(run_id="RID-test")
    base.update(over)
    return LedgerState(**base)


# ---------------------------------------------------------------------------
# 1. The load-bearing invariant — `claimed` is absent by construction.
# ---------------------------------------------------------------------------

def test_claimed_field_absent_from_digest():
    """A claimed-but-unverified step is invisible: not counted, not in the output.

    The agent self-reported step `s1` shipped (`claimed`) but the kernel verified
    nothing. The digest must show 0 verified AND expose no `claimed` key anywhere —
    a consumer of `dos status --json` cannot read a self-report it is never handed.
    """
    state = _ledger(
        declared_steps=("s1",),
        claimed={"s1": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},  # self-report
        verified={},                                                # kernel minted nothing
    )
    d = status_digest(run_id="RID-test", ledger_state=state, liveness_verdict=_live())

    assert d.progress.verified_count == 0          # the claim did not count
    assert d.progress.declared_count == 1

    out = d.to_dict()
    assert "claimed" not in out                     # not at the top level
    assert "claimed" not in out["progress"]         # not in the progress view
    # The structural litmus: no field of the digest exposes the self-report.
    assert "deadbeef" not in repr(out)


def test_verified_count_tracks_verified_map():
    """verified_count is len(verified), independent of how many were claimed."""
    state = _ledger(
        declared_steps=("s1", "s2", "s3"),
        claimed={"s1": "c1", "s2": "c2", "s3": "c3"},   # claimed all three
        verified={                                       # kernel confirmed two
            "s1": VerifiedStep("s1", "c1", via="file-path"),
            "s2": VerifiedStep("s2", "c2", via="registry"),
        },
    )
    d = status_digest(run_id="RID-test", ledger_state=state, liveness_verdict=_live())
    assert d.progress.verified_count == 2
    assert d.progress.declared_count == 3
    assert d.progress.verified_steps == ("s1", "s2")     # sorted ids of the minted map


# ---------------------------------------------------------------------------
# 2. The resume field — None while live, the verdict once stopped.
# ---------------------------------------------------------------------------

def test_live_run_has_no_resume():
    """A running digest carries no resume verdict (resume is a stopped-run question)."""
    d = status_digest(
        run_id="RID-test", ledger_state=_ledger(goal="g"), liveness_verdict=_live()
    )
    assert d.resume is None
    assert d.to_dict()["resume"] is None


def test_stopped_complete_run_round_trips():
    """A COMPLETE resume verdict is carried and survives to_dict()."""
    plan = ResumePlan(
        verdict=Resume.COMPLETE,
        reason="residual empty",
        run_id="RID-test",
        verified=("s1", "s2"),
    )
    d = status_digest(
        run_id="RID-test",
        ledger_state=_ledger(goal="g", declared_steps=("s1", "s2")),
        liveness_verdict=_live(),
        resume_plan=plan,
    )
    assert d.resume is plan
    assert d.to_dict()["resume"]["verdict"] == "COMPLETE"


# ---------------------------------------------------------------------------
# 3. Fail-closed assembly — no intent → zero progress, never a raise.
# ---------------------------------------------------------------------------

def test_no_intent_is_fail_closed():
    """An empty/no-intent LedgerState yields a valid zero-progress fact, not an error."""
    state = _ledger()                       # no goal/plan/steps → has_intent is False
    assert state.has_intent is False        # (@property, not a method — docs/120 §11.0)

    d = status_digest(run_id="RID-test", ledger_state=state, liveness_verdict=_live())
    assert d.progress == ProgressView(verified_count=0, declared_count=0, verified_steps=())
    assert d.resume is None
    # It is still a serializable fact ("nothing declared, nothing verified").
    assert d.to_dict()["progress"]["verified_count"] == 0


def test_carries_liveness_verdict_verbatim():
    """The liveness verdict is folded in unchanged — the digest re-derives nothing."""
    lv = _live()
    d = status_digest(run_id="RID-test", ledger_state=_ledger(), liveness_verdict=lv)
    assert d.liveness is lv
    assert d.to_dict()["liveness"]["verdict"] == Liveness.ADVANCING.value


def test_region_defaults_empty_and_round_trips():
    """A run holding no lease has region (); a held region is carried as a tuple."""
    d0 = status_digest(run_id="RID-test", ledger_state=_ledger(), liveness_verdict=_live())
    assert d0.region == ()
    assert d0.to_dict()["region"] == []

    d1 = status_digest(
        run_id="RID-test",
        ledger_state=_ledger(),
        liveness_verdict=_live(),
        live_region=("src/dos/**",),
    )
    assert d1.to_dict()["region"] == ["src/dos/**"]


# ---------------------------------------------------------------------------
# 4. Purity — status_digest() touches no subprocess, no file, no clock.
# ---------------------------------------------------------------------------

def test_status_digest_is_pure(monkeypatch):
    """`status_digest()` makes no subprocess/file/clock call — the arbiter discipline.

    The four verdicts are gathered at the boundary and handed in; the fold itself is
    pure dataclass assembly. We poison the three I/O surfaces a verdict must never
    touch and assert a clean digest still comes back (the `test_classify_is_pure` idiom).
    """
    lv = _live()  # build the verdict BEFORE poisoning (its construction is the boundary's job)

    def _boom(*a, **k):  # pragma: no cover - only runs if purity is violated
        raise AssertionError("status_digest() performed I/O — it must be pure")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(_time, "time", _boom)

    state = _ledger(
        declared_steps=("s1",), claimed={"s1": "c1"},
        verified={"s1": VerifiedStep("s1", "c1", via="file-path")},
    )
    d = status_digest(run_id="RID-test", ledger_state=state, liveness_verdict=lv)
    assert isinstance(d, StatusDigest)
    assert d.progress.verified_count == 1
    # Exercise to_dict() under the poison too — serialization must not do I/O either.
    assert d.to_dict()["run_id"] == "RID-test"
