"""Tests for the advisory prose calibration check (`scripts/claims_lint.py`).

This is DOS dev tooling, not a kernel module — it operates *on* the docs, the same
one-way arrow as `release_context.py` / `trajectory_audit.py`. The suite pins the two
properties that make the lint trustworthy rather than noisy:

  * it FLAGS the narrow high-signal classes (marketing hype, unhedged proof words,
    contempt toward other work);
  * it does NOT flag the PROTECTED vocabulary — the kernel's typed verdicts, honest
    self-critical verdicts about DOS's own bets, and mechanism invariants stated as
    such. Softening those would make the docs less honest; a lint that flagged them
    would be ignored.

It is advisory by construction: it exits 0 and edits nothing (a PDP, not a PEP, the
same posture as the kernel).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# Import the script-under-test by path (it is not an installed package).
_HELPER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "claims_lint.py"
_spec = importlib.util.spec_from_file_location("claims_lint", _HELPER_PATH)
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)


def _scan_text(tmp_path: Path, text: str) -> list[dict]:
    f = tmp_path / "doc.md"
    f.write_text(text, encoding="utf-8")
    return cl.scan_file(f)


def _classes(hits: list[dict]) -> set[str]:
    return {h["class"] for h in hits}


# ── it flags the real targets ───────────────────────────────────────────────
class TestFlagsOverclaim:
    def test_marketing_superlative(self, tmp_path):
        hits = _scan_text(tmp_path, "DOS is a revolutionary, game-changing substrate.")
        assert "marketing" in _classes(hits)

    def test_unhedged_proof_word(self, tmp_path):
        hits = _scan_text(tmp_path, "This definitively settles the question.")
        assert "proof" in _classes(hits)

    def test_smoking_gun(self, tmp_path):
        hits = _scan_text(tmp_path, "The smoking gun is the missing commit.")
        assert "proof" in _classes(hits)

    def test_contempt(self, tmp_path):
        hits = _scan_text(tmp_path, "Their approach is cargo-cult engineering.")
        assert "contempt" in _classes(hits)

    def test_strongest_signal_in_the_field(self, tmp_path):
        hits = _scan_text(tmp_path, "The strongest measured signal in the field is X.")
        assert "proof" in _classes(hits)


# ── it leaves the PROTECTED vocabulary alone (the load-bearing carve-out) ────
class TestProtectedVocabularyNotFlagged:
    def test_typed_verdicts(self, tmp_path):
        text = "The verdict is SHIPPED, NOT_SHIPPED, SPINNING, REFUSE, or ABSTAIN."
        assert _scan_text(tmp_path, text) == []

    def test_honest_self_critical_verdicts(self, tmp_path):
        # KILLED / REFUTED / "net loss" about DOS's own bet are honesty, not hype.
        text = "The rank-1 bet was KILLED; the hypothesis is REFUTED — a net loss on the arc."
        assert _scan_text(tmp_path, text) == []

    def test_mechanism_invariant_absolutes(self, tmp_path):
        # "never double-books", "byte-clean", "non-forgeable" are mechanism claims.
        text = (
            "The arbiter never double-books a lane; the verdict is byte-clean and "
            "non-forgeable because it rides git ancestry."
        )
        assert _scan_text(tmp_path, text) == []

    def test_polysemous_technical_words(self, tmp_path):
        # The words that made the first cut noisy — all legitimate technical usage.
        text = (
            "Cold-start dominates CI storms; the disruption-cost ordering is documented, "
            "and a non-disruptive BLOCK is the prize."
        )
        assert _scan_text(tmp_path, text) == []


# ── structural behaviour ────────────────────────────────────────────────────
class TestStructure:
    def test_skips_fenced_code(self, tmp_path):
        text = "Intro.\n```\nrevolutionary game-changing definitively\n```\nOutro."
        # The hype words live only inside the fence → no hits.
        assert _scan_text(tmp_path, text) == []

    def test_reports_line_numbers(self, tmp_path):
        text = "clean line\na revolutionary claim\nclean again"
        hits = _scan_text(tmp_path, text)
        assert len(hits) == 1
        assert hits[0]["line"] == 2

    def test_main_is_advisory_exit_zero(self, tmp_path, capsys):
        # Even with a flagged doc, main() returns 0 — advisory, never a gate.
        f = tmp_path / "hype.md"
        f.write_text("A revolutionary, game-changing breakthrough.", encoding="utf-8")
        rc = cl.main([str(f)])
        assert rc == 0

    def test_clean_corpus_exit_zero(self, tmp_path):
        f = tmp_path / "calm.md"
        f.write_text("The arbiter serializes lane effects deterministically.", encoding="utf-8")
        rc = cl.main([str(f)])
        assert rc == 0
