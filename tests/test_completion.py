"""Tests for `dos.completion` — the live completion verdict (docs/117).

These are the §7 acceptance gates of docs/117, plus the convergence verdict's own
tests. Everything here is a PURE replay test on a frozen `LedgerState` +
`AncestryFacts` (or a synthetic residual-size history) — no live loop, no I/O — the
`liveness`/`resume` posture. The fixture idiom (`_state` / `_anc`) is the same one
`test_resume_reachability.py` uses, because `completion.classify` *is*
`resume.resume_plan` re-framed forward (docs/117 §5.1), so its inputs are identical.
"""
from __future__ import annotations

from dos import completion as cm
from dos import resume as rz
from dos.intent_ledger import LedgerState, VerifiedStep
from dos.resume import AncestryFacts


_C1, _C2, _C3 = "c1aaaaa", "c2bbbbb", "c3ccccc"


def _state(
    *, run_id="RID-K", declared=("s1", "s2"), verified=None, claimed=None,
    goal="g", start_sha=_C1, unreadable_newer=False, corrupt_lines=0,
) -> LedgerState:
    """A LedgerState with `verified` given as {step: sha} (wrapped in VerifiedStep on a
    non-forgeable `via`) and `claimed` as {step: sha} — the distrusted self-reports."""
    vmap = {sid: VerifiedStep(sid, sha, via="file-path") for sid, sha in (verified or {}).items()}
    return LedgerState(
        run_id=run_id, goal=goal, start_sha=start_sha,
        declared_steps=tuple(declared),
        verified=vmap,
        claimed=dict(claimed or {}),
        unreadable_newer=unreadable_newer,
        corrupt_lines=corrupt_lines,
    )


def _anc(*, in_ancestry=(), verified_steps=(), diverged=False) -> AncestryFacts:
    """The boundary facts: which SHAs git has, which steps were RE-ADJUDICATED as
    verified at read (the authority — not the stored `via`), and lane-divergence."""
    return AncestryFacts(
        shas_in_ancestry=frozenset(in_ancestry),
        steps_verified_at_read=frozenset(verified_steps),
        lane_advanced_past_resume=diverged,
    )


# ==========================================================================
# Gate 1 — a loop can stop because it FINISHED (the headline gate).
# ==========================================================================


def test_all_declared_verified_is_complete():
    """Every declared step verified on a non-forgeable, in-ancestry rung → COMPLETE."""
    state = _state(declared=("s1", "s2"), verified={"s1": _C1, "s2": _C2})
    anc = _anc(in_ancestry=(_C1, _C2), verified_steps=("s1", "s2"))
    v = cm.classify(state, anc)
    assert v.state is cm.Completion.COMPLETE
    assert v.state.is_done
    assert v.residual == ()
    assert v.verified == ("s1", "s2")
    assert v.fraction_done == 1.0


def test_complete_maps_from_resume_complete():
    """The forward verdict agrees with the backward one: where resume says COMPLETE,
    completion says COMPLETE (the §5.1 mapping, pinned)."""
    state = _state(declared=("s1",), verified={"s1": _C1})
    anc = _anc(in_ancestry=(_C1,), verified_steps=("s1",))
    assert rz.resume_plan(state, anc).verdict is rz.Resume.COMPLETE
    assert cm.classify(state, anc).state is cm.Completion.COMPLETE


# ==========================================================================
# Gate 2 — a CLAIMED-but-unverified step BLOCKS completion (inherited from
# resume.py:282; re-pinned at the completion surface).
# ==========================================================================


def test_claimed_but_unverified_step_is_incomplete():
    """Declares 5, CLAIMS all 5, but git confirms only 3 → INCOMPLETE, 2-step residual,
    NEVER COMPLETE. This is the whole point: 'I'm done' is not believed."""
    declared = ("s1", "s2", "s3", "s4", "s5")
    state = _state(
        declared=declared,
        verified={"s1": _C1, "s2": _C2, "s3": _C3},
        claimed={"s4": "deadbee", "s5": "feedf00"},  # narrated done, never landed
    )
    anc = _anc(in_ancestry=(_C1, _C2, _C3), verified_steps=("s1", "s2", "s3"))
    v = cm.classify(state, anc)
    assert v.state is cm.Completion.INCOMPLETE
    assert v.residual == ("s4", "s5")          # the claimed-but-unverified stay owed
    assert v.verified == ("s1", "s2", "s3")
    assert not v.state.is_done


def test_a_forged_via_does_not_count_toward_completion():
    """A STEP_VERIFIED whose step was NOT re-adjudicated at read (absent from
    steps_verified_at_read) is NOT done — the docs/107 §5 / docs/103 fix, inherited.
    Even though the ledger *stores* s2 as verified, the boundary didn't confirm it."""
    state = _state(declared=("s1", "s2"), verified={"s1": _C1, "s2": _C2})
    # git has both SHAs, but the boundary only RE-ADJUDICATED s1 (s2's record is a
    # forged hint pointing at a real-but-unrelated commit).
    anc = _anc(in_ancestry=(_C1, _C2), verified_steps=("s1",))
    v = cm.classify(state, anc)
    assert v.state is cm.Completion.INCOMPLETE
    assert v.residual == ("s2",)


# ==========================================================================
# Gate 3 — INDETERMINATE on an unsound fold (the floor; never assert done).
# ==========================================================================


def test_no_intent_is_indeterminate():
    """No INTENT record → resume.UNRESUMABLE → completion.INDETERMINATE (no declared
    extent to close against; refuse to call it done)."""
    state = LedgerState(run_id="RID-K")  # nothing declared
    v = cm.classify(state, _anc())
    assert v.state is cm.Completion.INDETERMINATE
    assert not v.state.is_done


def test_too_new_schema_is_indeterminate():
    """A record this kernel is too OLD to read soundly → INDETERMINATE, never COMPLETE
    (the durable_schema §6 floor, restated forward)."""
    state = _state(declared=("s1",), verified={"s1": _C1}, unreadable_newer=True)
    anc = _anc(in_ancestry=(_C1,), verified_steps=("s1",))
    v = cm.classify(state, anc)
    assert v.state is cm.Completion.INDETERMINATE


# ==========================================================================
# Gate 4 — DIVERGED ground truth is still INCOMPLETE (work remains), with the
# divergence preserved in the reason.
# ==========================================================================


def test_diverged_is_incomplete_and_says_so():
    """Residual non-empty AND the lane advanced past the resume point → INCOMPLETE
    (not done), and the reason mentions the divergence so the operator sees it."""
    state = _state(declared=("s1", "s2"), verified={"s1": _C1})
    anc = _anc(in_ancestry=(_C1,), verified_steps=("s1",), diverged=True)
    assert rz.resume_plan(state, anc).verdict is rz.Resume.DIVERGED
    v = cm.classify(state, anc)
    assert v.state is cm.Completion.INCOMPLETE
    assert v.residual == ("s2",)
    assert "advanced past" in v.reason.lower() or "diverg" in v.reason.lower()


# ==========================================================================
# Gate 5 — completion needs NO plan (the verify-no-plan invariant, extended).
# ==========================================================================


def test_freeform_goal_no_steps_is_incomplete_not_crash():
    """A free-form goal with no enumerated steps still gets a sound verdict from the
    floor — INCOMPLETE with the goal as the single residual unit (resume's free-form
    path), never an error and never a false COMPLETE."""
    state = _state(declared=(), goal="do the thing", start_sha=_C1)
    anc = _anc(in_ancestry=(_C1,))
    v = cm.classify(state, anc)
    assert v.state is cm.Completion.INCOMPLETE
    assert v.residual == ("do the thing",)
    assert v.fraction_done is None       # no step denominator for a free-form goal


# ==========================================================================
# Gate 6 — the verdict serializes (the --json shape).
# ==========================================================================


def test_to_dict_round_trips():
    state = _state(declared=("s1", "s2"), verified={"s1": _C1, "s2": _C2})
    anc = _anc(in_ancestry=(_C1, _C2), verified_steps=("s1", "s2"))
    d = cm.classify(state, anc).to_dict()
    assert d["state"] == "COMPLETE"
    assert d["is_done"] is True
    assert d["residual"] == []
    assert d["declared"] == ["s1", "s2"]
    assert d["fraction_done"] == 1.0


# ==========================================================================
# The convergence verdict (docs/117 §5.2 / Gap C) — over a history of |residual|.
# ==========================================================================


def test_convergence_catches_thrashing():
    """A residual that oscillates and never strictly decreases → THRASHING (the §7
    gate: (4,3,4,3) → THRASHING)."""
    v = cm.convergence((4, 3, 4, 3))
    assert v.state is cm.Convergence.THRASHING
    assert v.state.should_surface


def test_convergence_recognizes_a_shrinking_residual():
    """A monotonically shrinking residual → CONVERGING (the §7 gate: (8,5,3,1) →
    CONVERGING)."""
    v = cm.convergence((8, 5, 3, 1))
    assert v.state is cm.Convergence.CONVERGING
    assert not v.state.should_surface


def test_convergence_reaching_zero_is_converging():
    """A residual that hits 0 is CONVERGING regardless of path — the static COMPLETE
    is the authority on done-ness; convergence never calls a finished loop THRASHING."""
    assert cm.convergence((3, 1, 0)).state is cm.Convergence.CONVERGING


def test_convergence_flat_nonempty_is_starved():
    """A residual stuck flat and non-empty → STARVED (no churn, no progress) — distinct
    from THRASHING's oscillation."""
    v = cm.convergence((5, 5, 5, 5))
    assert v.state is cm.Convergence.STARVED
    assert v.state.should_surface


def test_convergence_too_few_rounds_is_insufficient():
    """Fewer than 2 rounds → INSUFFICIENT (no trend yet); never a stop signal."""
    assert cm.convergence(()).state is cm.Convergence.INSUFFICIENT
    assert cm.convergence((7,)).state is cm.Convergence.INSUFFICIENT
    assert not cm.convergence((7,)).state.should_surface


def test_convergence_growing_residual_thrashes():
    """A residual that grows for the threshold rounds → THRASHING (worse than flat)."""
    v = cm.convergence((1, 2, 3, 4))
    assert v.state is cm.Convergence.THRASHING


def test_convergence_one_bad_round_is_not_yet_thrashing():
    """A single non-decreasing round inside an otherwise-improving trend does NOT trip
    THRASHING — the stop decision must be confident (≥ max_nonconverging rounds)."""
    # 10 → 8 → 9: one uptick, but only 1 non-decreasing transition, < default k=3.
    v = cm.convergence((10, 8, 9))
    assert v.state is not cm.Convergence.THRASHING


def test_convergence_window_bounds_the_trend():
    """Only the most-recent `window` rounds are judged — ancient history doesn't keep
    a now-thrashing loop looking healthy."""
    pol = cm.ConvergencePolicy(window=3, max_nonconverging=2)
    # early big drop, then stuck: with window=3 the trend read is (5,5,5)-ish stuck.
    v = cm.convergence((100, 5, 5, 5), pol)
    assert v.state in (cm.Convergence.STARVED, cm.Convergence.THRASHING)
    assert v.state.should_surface


# ==========================================================================
# Gate 7 — the scope rung (docs/117 Phase 4): distrust the DENOMINATOR.
# A COMPLETE residual + a scope source flagging under-declaration → UNDERDECLARED.
# With no scope verdicts (the default) classify is byte-identical to Phase 1.
# ==========================================================================


def test_no_scope_verdicts_is_byte_identical():
    """The opt-in floor: with no `scope_verdicts`, classify answers exactly as before
    Phase 4 — COMPLETE on an empty residual, UNDERDECLARED never emitted."""
    state = _state(declared=("s1", "s2"), verified={"s1": _C1, "s2": _C2})
    anc = _anc(in_ancestry=(_C1, _C2), verified_steps=("s1", "s2"))
    assert cm.classify(state, anc).state is cm.Completion.COMPLETE
    # explicit empty tuple is identical to the default.
    assert cm.classify(state, anc, scope_verdicts=()).state is cm.Completion.COMPLETE


def test_honest_scope_verdict_still_complete():
    """A source that confirms the extent honest does not change COMPLETE."""
    from dos.scope_source import ScopeVerdict
    state = _state(declared=("s1",), verified={"s1": _C1})
    anc = _anc(in_ancestry=(_C1,), verified_steps=("s1",))
    honest = ScopeVerdict(extent_honest=True, reason="whole job", source="plan")
    assert cm.classify(state, anc, scope_verdicts=(honest,)).state is cm.Completion.COMPLETE


def test_dishonest_scope_verdict_is_underdeclared():
    """THE Gap-B gate: residual empty (every declared step verified) BUT a scope
    source says the extent was under-declared → UNDERDECLARED, not COMPLETE."""
    from dos.scope_source import ScopeVerdict
    state = _state(declared=("s1", "s2"), verified={"s1": _C1, "s2": _C2})
    anc = _anc(in_ancestry=(_C1, _C2), verified_steps=("s1", "s2"))
    dishonest = ScopeVerdict(extent_honest=False, reason="2 phases omitted",
                             source="plan", missing=("s3", "s4"))
    v = cm.classify(state, anc, scope_verdicts=(dishonest,))
    assert v.state is cm.Completion.UNDERDECLARED
    assert v.state.is_done is False
    assert "s3" in v.reason and "s4" in v.reason  # the missing scope is surfaced
    assert v.residual == ()  # the DECLARED residual is still empty; it's the EXTENT that's wrong


def test_scope_only_consulted_when_residual_empty():
    """An INCOMPLETE run (non-empty residual) is INCOMPLETE regardless of scope — the
    scope rung only gates the COMPLETE branch (you don't ask 'was the extent honest?'
    about a run that isn't even done with what it declared)."""
    from dos.scope_source import ScopeVerdict
    state = _state(declared=("s1", "s2"), verified={"s1": _C1})  # s2 unverified → residual
    anc = _anc(in_ancestry=(_C1,), verified_steps=("s1",))
    dishonest = ScopeVerdict(extent_honest=False, reason="x", source="plan", missing=("s9",))
    v = cm.classify(state, anc, scope_verdicts=(dishonest,))
    assert v.state is cm.Completion.INCOMPLETE  # NOT UNDERDECLARED — residual gate is upstream


# ==========================================================================
# Purity — no I/O, no clock, no subprocess (the liveness/resume rule).
# ==========================================================================


def test_classify_is_pure_no_io(monkeypatch):
    """classify makes no subprocess/file/clock call — all evidence is handed in.
    We trip wires on the obvious I/O entry points and assert none fire."""
    import subprocess
    import time

    def _boom(*a, **k):  # pragma: no cover - only fires on a regression
        raise AssertionError("completion.classify must not perform I/O")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(time, "time", _boom)

    state = _state(declared=("s1",), verified={"s1": _C1})
    anc = _anc(in_ancestry=(_C1,), verified_steps=("s1",))
    assert cm.classify(state, anc).state is cm.Completion.COMPLETE
    assert cm.convergence((3, 2, 1)).state is cm.Convergence.CONVERGING
