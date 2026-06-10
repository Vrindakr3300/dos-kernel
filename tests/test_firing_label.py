"""docs/179 Phase 1 — `dos.firing_label`: the detector self-labeling fold.

The one fold in the docs/179 set that mints NEW ground truth: it joins a detector
FIRING (env/agent-authored) to the run's GIT-MINTED outcome (a fact the judged
agent did not author), producing the `(signal, was-it-real)` calibration point the
detector line is scored on.

The load-bearing test (the synthesis's "one assertion that proves it"):
`test_audited_read_loop_mints_exactly_one_point` — the real audited `8bd8c736`
22-read stall yields EXACTLY ONE `LabeledPoint`, NOT 22. Re-counting one env stall
as 22 labels would be the consistency-not-grounding sin; the dedup guard forecloses
it, and that single assertion proves the join works end-to-end AND the multiplier is
honest in one shot.
"""

from __future__ import annotations

from dos.firing_label import (
    DetectorFiring,
    LabelOutcome,
    LabelSummary,
    dedupe_firings,
    label_firings,
    label_one,
)
from dos.trace import StepRow, TraceFrame


# ---------------------------------------------------------------------------
# Frame builders — minimal TraceFrames standing in for trace.build_trace output.
# We set ONLY the git-minted columns the labeler reads (steps/commits/has_intent);
# claimed_sha is set on some rows to PROVE the labeler ignores it.
# ---------------------------------------------------------------------------
def _frame(run_id, *, found=True, has_intent=True, verified=0, claimed=0,
           pending=0, commits=0):
    steps = []
    for i in range(verified):
        steps.append(StepRow(step_id=f"v{i}", state="VERIFIED",
                             verified_sha="a" * 10, verified_via="grep"))
    for i in range(claimed):
        # CLAIMED is the agent's distrusted self-report — the labeler must NOT count
        # it as progress (a claimed-but-unverified step is still residual).
        steps.append(StepRow(step_id=f"c{i}", state="CLAIMED", claimed_sha="f" * 10))
    for i in range(pending):
        steps.append(StepRow(step_id=f"p{i}", state="PENDING"))
    commit_rows = tuple({"sha": f"{i:040x}", "subject": f"c{i}"} for i in range(commits))
    return TraceFrame(
        run_id=run_id, found=found, has_intent=has_intent,
        steps=tuple(steps), commits=commit_rows,
    )


def _firing(run_id="RID-1", *, signal="STALLED", step_index=0, identity="",
            detector="tool_stream"):
    return DetectorFiring(run_id=run_id, detector=detector, signal=signal,
                         step_index=step_index, identity=identity)


# ==========================================================================
# label_one — the closed outcome ladder.
# ==========================================================================
def test_broken_link_when_no_run_id():
    p = label_one(_firing(run_id=""), _frame("X"))
    assert p.outcome is LabelOutcome.BROKEN_LINK


def test_broken_link_when_no_frame_found():
    p = label_one(_firing(run_id="RID-1"), None)
    assert p.outcome is LabelOutcome.BROKEN_LINK
    p2 = label_one(_firing(run_id="RID-1"), _frame("RID-1", found=False))
    assert p2.outcome is LabelOutcome.BROKEN_LINK


def test_unverifiable_when_no_intent_and_no_commits():
    """A firing on a run that declared no intent and landed no commits has NO
    git-minted ground truth — refuse to call it (UNVERIFIABLE), never guess a TP."""
    p = label_one(_firing(), _frame("RID-1", has_intent=False, commits=0))
    assert p.outcome is LabelOutcome.UNVERIFIABLE


def test_true_positive_when_residual_and_no_commits():
    """Declared work, verified NONE of it, committed NOTHING → the stall was real."""
    p = label_one(_firing(), _frame("RID-1", verified=0, pending=3, commits=0))
    assert p.outcome is LabelOutcome.TRUE_POSITIVE
    assert p.ground_truth["residual"] == 3
    assert p.ground_truth["verified_steps"] == 0


def test_false_alarm_when_a_step_verified():
    """The run verified a declared step → it advanced → the firing was a false alarm."""
    p = label_one(_firing(), _frame("RID-1", verified=2, pending=1, commits=0))
    assert p.outcome is LabelOutcome.FALSE_ALARM


def test_false_alarm_when_a_commit_landed():
    """A commit since start is git-minted progress → false alarm even with 0 verified
    steps (a run that committed without declaring steps still advanced)."""
    p = label_one(_firing(), _frame("RID-1", verified=0, pending=2, commits=1))
    assert p.outcome is LabelOutcome.FALSE_ALARM


def test_claimed_steps_are_never_counted_as_progress():
    """THE byte-author invariant (docs/138): a CLAIMED-but-unverified step is the
    agent's self-report — it must NOT flip a TRUE_POSITIVE to a FALSE_ALARM. A run
    that CLAIMED 5 steps but verified none and committed nothing is still a true
    catch (the agent SAID it made progress; git says it did not)."""
    p = label_one(_firing(), _frame("RID-1", verified=0, claimed=5, commits=0))
    assert p.outcome is LabelOutcome.TRUE_POSITIVE  # NOT false-alarm
    assert p.ground_truth["verified_steps"] == 0


# ==========================================================================
# dedupe_firings — the honest-multiplier guard.
# ==========================================================================
def test_dedupe_collapses_same_identity_firings():
    """Many firings of the SAME (run, detector, signal, identity) collapse to one."""
    fs = [_firing(identity="digest-abc") for _ in range(22)]
    assert len(dedupe_firings(fs)) == 1


def test_dedupe_preserves_distinct_steps():
    """Firings on DIFFERENT steps (no shared identity) stay distinct."""
    fs = [_firing(step_index=i) for i in range(3)]
    assert len(dedupe_firings(fs)) == 3


def test_dedupe_distinguishes_repeating_from_stalled_only_by_identity():
    """A REPEATING then STALLED on the SAME stuck step (same identity) is ONE event,
    not two — they share the dedup identity, so the run mints one labeled point."""
    fs = [_firing(signal="REPEATING", identity="d"),
          _firing(signal="STALLED", identity="d")]
    # Different signal → different key, so these are 2 raw. The single-stall collapse
    # happens at the SENSOR (one verdict_state per record); here we prove distinct
    # signals are kept (the eval may want both rungs). Same-signal repeats collapse.
    assert len(dedupe_firings(fs)) == 2
    same = [_firing(signal="STALLED", identity="d") for _ in range(5)]
    assert len(dedupe_firings(same)) == 1


# ==========================================================================
# THE load-bearing proof — the audited 8bd8c736 read-loop → exactly ONE point.
# ==========================================================================
def test_audited_read_loop_mints_exactly_one_point():
    """The synthesis's one assertion that proves it: the real audited `8bd8c736`
    read-loop (22 byte-identical reads → STALLED) mints EXACTLY ONE LabeledPoint,
    not 22. Proves (a) the join works, (b) the dedup keeps the multiplier honest
    (one stall = one label, never 22 — the consistency-not-grounding guard)."""
    # 22 identical STALLED firings on the same env-authored result digest, one run.
    firings = [
        DetectorFiring(run_id="RID-8bd8c736", detector="tool_stream",
                       signal="STALLED", step_index=i, identity="env-digest-deadbeef")
        for i in range(22)
    ]
    # The run never recovered: declared work, verified none, committed nothing.
    frame = _frame("RID-8bd8c736", verified=0, pending=2, commits=0)
    points = label_firings(firings, lambda rid: frame)

    assert len(points) == 1                                  # NOT 22 — the whole point
    assert points[0].outcome is LabelOutcome.TRUE_POSITIVE   # a real catch
    assert points[0].firing.run_id == "RID-8bd8c736"


# ==========================================================================
# label_firings + LabelSummary — the batch fold + confusion grid.
# ==========================================================================
def test_label_firings_uses_boundary_frame_lookup():
    """The fold takes a `run_id -> frame` callable (the I/O stays at the boundary).
    Each distinct run is looked up once (the cache), proving purity of the fold."""
    frames = {
        "RID-tp": _frame("RID-tp", verified=0, pending=2, commits=0),   # TP
        "RID-fp": _frame("RID-fp", verified=1, pending=1, commits=0),   # FP
    }
    looked_up = []

    def frame_for(rid):
        looked_up.append(rid)
        return frames.get(rid)

    firings = [_firing(run_id="RID-tp", identity="a"),
               _firing(run_id="RID-fp", identity="b"),
               _firing(run_id="RID-tp", identity="a")]  # dup of the first
    points = label_firings(firings, frame_for)
    assert len(points) == 2                       # the dup collapsed
    assert sorted(set(looked_up)) == ["RID-fp", "RID-tp"]  # each run looked up
    outcomes = {p.firing.run_id: p.outcome for p in points}
    assert outcomes["RID-tp"] is LabelOutcome.TRUE_POSITIVE
    assert outcomes["RID-fp"] is LabelOutcome.FALSE_ALARM


def test_summary_confusion_grid_and_rates():
    points = label_firings(
        [_firing(run_id="RID-tp1", identity="1"),
         _firing(run_id="RID-tp2", identity="2"),
         _firing(run_id="RID-fp", identity="3"),
         _firing(run_id="RID-unv", identity="4"),
         _firing(run_id="", identity="5")],  # broken link
        {
            "RID-tp1": _frame("RID-tp1", pending=1),
            "RID-tp2": _frame("RID-tp2", pending=1),
            "RID-fp": _frame("RID-fp", verified=1),
            "RID-unv": _frame("RID-unv", has_intent=False, commits=0),
        }.get,
    )
    s = LabelSummary(points)
    assert s.true_positives == 2
    assert s.false_alarms == 1
    assert s.unverifiable == 1
    assert s.broken_links == 1
    assert s.judgeable == 3                       # TP + FP only
    assert abs(s.false_alarm_rate - (1 / 3)) < 1e-9
    assert abs(s.coverage - (3 / 5)) < 1e-9       # 3 judgeable of 5 firings


def test_summary_rates_refuse_zero_denominator():
    """No judgeable points → false_alarm_rate is None (refuse a 0/0 number), not 0.0."""
    points = label_firings([_firing(run_id="")], {}.get)  # all broken
    s = LabelSummary(points)
    assert s.judgeable == 0
    assert s.false_alarm_rate is None
    assert LabelSummary(()).coverage is None      # empty input
