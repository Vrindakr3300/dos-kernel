"""docs/179 Phase 2 — the corpus harvester proof: the kernel fold reproduces the SSOT
AND shows net lift on the real Toolathlon labels.

Two load-bearing assertions:
  1. cross_validate(): the KERNEL `firing_label` fold's per-detector + union confusion
     grid is byte-equal to `additivity.py` (the validated SSOT). If they match, the
     kernel instrument is correct — the net-lift number it reports is trustworthy.
  2. NET LIFT: the union of detectors catches strictly MORE oracle-failures than the
     best single detector — the docs/179 "more data → more signal" claim, measured.

These run on the FROZEN corpus (`_results/replay_all_rows.csv`), zero network/LLM.
They are skipped (not failed) if the CSV is absent, so a checkout without the data
artifact still has a green suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROWS = Path(__file__).resolve().parent / "_results" / "replay_all_rows.csv"
pytestmark = pytest.mark.skipif(not _ROWS.exists(), reason="frozen corpus CSV not present")


def _rows():
    from benchmark.toolathlon.additivity import load_rows
    return load_rows(_ROWS)


def test_kernel_fold_reproduces_additivity_ssot_exactly():
    """The kernel firing_label fold == additivity.py SSOT (per-detector + union).
    This is the proof the kernel instrument is a correct re-implementation."""
    from benchmark.toolathlon.firing_corpus import cross_validate
    problems = cross_validate(_rows())
    assert problems == [], "kernel fold diverged from additivity SSOT:\n" + "\n".join(problems)


def test_net_lift_is_positive_on_real_labels():
    """The union of detectors catches strictly MORE failures than the best single —
    the docs/179 net-lift claim, on third-party oracle labels."""
    from benchmark.toolathlon.firing_corpus import harvest
    lift = harvest(_rows())
    assert lift.union_tp > lift.best_single_tp, (
        f"NO net lift: union {lift.union_tp} <= best single "
        f"{lift.best_single_detector} {lift.best_single_tp}")
    assert lift.net_new > 0
    assert lift.recall_gain_pp is not None and lift.recall_gain_pp > 0


def test_union_is_deduped_by_run_not_summed():
    """The union TP is distinct runs caught by ANY detector (deduped), so it is < the
    sum of per-detector TP (overlaps counted once) and > the max single — the honest
    pooling additivity.UnionSlice uses, reproduced through the kernel."""
    from benchmark.toolathlon.firing_corpus import harvest
    lift = harvest(_rows())
    sum_tp = sum(d.true_positives for d in lift.per_detector)
    assert lift.best_single_tp < lift.union_tp <= sum_tp


def test_unlabeled_rows_are_unverifiable_not_guessed():
    """A row with no oracle label maps to an UNVERIFIABLE frame (no intent/commits) —
    the firing is counted but never labeled TP or FP (refuse, don't guess). So the
    judgeable denominator excludes them, matching additivity's labeled-only rule."""
    from dos.firing_label import LabelOutcome, label_one
    from benchmark.toolathlon.firing_corpus import corpus_frame, _run_id
    from dos.firing_label import DetectorFiring

    frame = corpus_frame("R::t", None)  # oracle absent
    firing = DetectorFiring(run_id="R::t", detector="tool_stream", signal="STALLED")
    assert label_one(firing, frame).outcome is LabelOutcome.UNVERIFIABLE


def test_oracle_label_is_independent_of_the_firing():
    """The honesty check: the frame's ground truth is the ORACLE column, stamped
    source-independent — a PASS frame yields FALSE_ALARM and a FAIL frame yields
    TRUE_POSITIVE for the SAME firing, proving the label comes from the oracle, not
    the detector (not circular)."""
    from dos.firing_label import DetectorFiring, LabelOutcome, label_one
    from benchmark.toolathlon.firing_corpus import corpus_frame

    firing = DetectorFiring(run_id="R::t", detector="tool_stream", signal="STALLED")
    assert label_one(firing, corpus_frame("R::t", False)).outcome is LabelOutcome.TRUE_POSITIVE
    assert label_one(firing, corpus_frame("R::t", True)).outcome is LabelOutcome.FALSE_ALARM
