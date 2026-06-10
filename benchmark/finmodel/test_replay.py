"""Pins the $0 replay measurement — the committed RESULTS.md numbers, recomputed from disk.

These are the falsifiable-prediction assertions: 0% false-refute on the clean corpus, and a
measurable (here total) detect slice per forgery class. If a future edit to the engine or the
corpus moved either, this reddens — the witness re-derives the headline from `run_replay`,
never trusts the prose in RESULTS.md.
"""
from __future__ import annotations

from .gate import CLEAN, FABRICATED_BALANCE, PLUG_BALANCE, STATIC_VALUE
from .replay import run_replay


def test_zero_false_refute_on_clean_corpus():
    """THE PREDICTION: a clean, auditable model is NEVER false-refuted."""
    report = run_replay()
    clean = report.by_label(CLEAN)
    assert clean.n_blocked == 0, f"false-refuted {clean.n_blocked}/{clean.n} clean models"
    assert clean.false_refute == 0.0


def test_each_forgery_class_is_detected():
    """Each injected forgery class is BLOCKED — a measurable detect slice (here the whole
    synthesized slice, 8/8 per class)."""
    report = run_replay()
    for cls in (STATIC_VALUE, FABRICATED_BALANCE, PLUG_BALANCE):
        c = report.by_label(cls)
        assert c.n == 8 and c.n_blocked == 8, (cls, c.to_dict())
        assert c.detect_recall == 1.0


def test_headline_denominator_and_totals():
    report = run_replay()
    d = report.to_dict()
    assert d["total_models"] == 32
    h = d["headline"]
    assert h["n_forged"] == 24 and h["n_forged_blocked"] == 24
    assert h["n_clean"] == 8 and h["n_clean_blocked"] == 0
    assert h["overall_detect_recall"] == 1.0
    assert h["false_refute_on_clean"] == 0.0


def test_results_md_stamp_matches_committed_numbers():
    """The committed RESULTS.md must carry the same headline the replay produces now — guards
    against a stale summary (the docs/277 'don't headline a number the rung no longer makes')."""
    import pathlib
    p = pathlib.Path(__file__).with_name("RESULTS.md")
    text = p.read_text(encoding="utf-8")
    assert "24/24 forged blocked" in text
    assert "0/8 clean blocked" in text
    assert "dos-bench-stamp:" in text
