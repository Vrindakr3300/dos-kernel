"""Tests for the distance adjudicator (`dos.drivers.similarity_judge:SimilarityJudge`).

This is the "fuzzy / close-enough matching" the kernel verdict deliberately refuses,
implemented where it is ALLOWED to live — the JUDGE rung (docs/76). The pinned
contract, in priority order:

  The byte-inequality floor (the load-bearing discipline):
    * NO evidence → ABSTAIN, never AGREE. The judge will not clear a claim off the
      agent's own narration (that would be the mirror-verifier trap, docs/141 §5a).
    * it scores `claim_text` against the EVIDENCE (un-authored bytes), never against
      `stated_reason` (narration) — proven by a case where narration matches the claim
      verbatim but evidence does not: the verdict must NOT be AGREE.

  Fail-to-abstain / advisory-only (the seam-wide safety property):
    * any scorer error → ABSTAIN via `run_judge` (never AGREE);
    * it returns a frozen `JudgeVerdict` and mutates nothing.

  The fuzzy match itself (the feature):
    * a high overlap with the evidence → AGREE;
    * a low overlap (evidence present, claim unsupported) → DISAGREE — a middling
      score is a real "unsupported" signal, not an "I can't tell";
    * the threshold is DATA (`$DOS_SIMILARITY_THRESHOLD`), and a wired embedding seam
      (`$DOS_SIMILARITY_CMD`) overrides the lexical scorer.

  Registration:
    * it is a discoverable `dos.judges` plugin (NOT a built-in), resolvable by name
      and satisfying the `Judge` protocol.
"""

from __future__ import annotations

import pytest

from dos.drivers import similarity_judge as sj
from dos.drivers.similarity_judge import SimilarityJudge
from dos.judges import Claim, Judge, JudgeVerdict, Stance, run_judge


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test runs against the pure lexical scorer at the default threshold unless
    it opts into an override — so no ambient `$DOS_SIMILARITY_*` leaks across tests."""
    monkeypatch.delenv(sj.ENV_SIMILARITY_CMD, raising=False)
    monkeypatch.delenv(sj.ENV_SIMILARITY_THRESHOLD, raising=False)


# ---------------------------------------------------------------------------
# The byte-inequality floor — the discipline that separates this from a mirror.
# ---------------------------------------------------------------------------

def test_no_evidence_abstains_never_agrees():
    """The load-bearing rule: with no un-authored bytes to score against, the judge
    ABSTAINS. It refuses to agree off the agent's own narration."""
    j = SimilarityJudge()
    # claim_text and stated_reason are identical (a perfect "self-match") — a mirror
    # judge would AGREE. This one has no EVIDENCE, so it must abstain.
    c = Claim("phase AUTH2 shipped", stated_reason="phase AUTH2 shipped", evidence=())
    v = run_judge(j, c, None)
    assert v.stance is Stance.ABSTAIN
    assert not v.agreed


def test_scores_against_evidence_not_narration():
    """The judge matches the claim against EVIDENCE, never against the narration.

    Here the narration echoes the claim verbatim (a mirror would AGREE), but the
    EVIDENCE is unrelated. The verdict must NOT be AGREE — narration is ignored."""
    j = SimilarityJudge()
    c = Claim(
        "the auth refactor landed and all tokens rotate hourly",
        stated_reason="the auth refactor landed and all tokens rotate hourly",  # mirror bait
        evidence=("git: commit 9f2a touched README.md only", "file: no auth/ changes"),
    )
    v = run_judge(j, c, None)
    assert v.stance is not Stance.AGREE  # narration was NOT used to clear it
    assert v.disagreed  # evidence is present but does not support the claim


def test_empty_claim_text_abstains():
    j = SimilarityJudge()
    v = run_judge(j, Claim("   ", evidence=("git: something",)), None)
    assert v.stance is Stance.ABSTAIN


# ---------------------------------------------------------------------------
# The fuzzy match — the actual feature.
# ---------------------------------------------------------------------------

def test_high_overlap_with_evidence_agrees():
    """A claim whose terms are near-verbatim witnessed by the evidence → AGREE."""
    j = SimilarityJudge()
    c = Claim(
        "phase AUTH2 shipped at commit 80d4f30",
        evidence=("SHIPPED docs/82 AUTH2 shipped at commit 80d4f30 (via grep)",),
    )
    v = run_judge(j, c, None)
    assert v.stance is Stance.AGREE
    assert "similarity" in v.why


def test_low_overlap_with_evidence_disagrees():
    """Evidence present but unrelated to the claim → DISAGREE (a middling/low score is
    a real 'unsupported' signal, not an abstain)."""
    j = SimilarityJudge()
    c = Claim(
        "the database migration completed successfully",
        evidence=("git: commit touched only docs/README.md",),
    )
    v = run_judge(j, c, None)
    assert v.stance is Stance.DISAGREE


def test_threshold_is_data_via_env(monkeypatch):
    """The agree-threshold is operator DATA, not a kernel constant: lowering it can
    flip a borderline DISAGREE to AGREE (and the verdict is still advisory)."""
    j = SimilarityJudge()
    c = Claim(
        "tokens rotate hourly",
        evidence=("config: token_rotation set; interval unspecified",),
    )
    # At the strict default this is unsupported.
    assert run_judge(j, c, None).stance is Stance.DISAGREE
    # An operator who wants looser matching declares it as data.
    monkeypatch.setenv(sj.ENV_SIMILARITY_THRESHOLD, "0.10")
    assert run_judge(j, c, None).stance is Stance.AGREE


def test_malformed_threshold_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(sj.ENV_SIMILARITY_THRESHOLD, "not-a-float")
    assert sj._threshold() == sj.DEFAULT_THRESHOLD


# ---------------------------------------------------------------------------
# The optional embedding seam — overrides the lexical scorer, never raises.
# ---------------------------------------------------------------------------

def test_embedding_seam_overrides_lexical_scorer(monkeypatch):
    """With `$DOS_SIMILARITY_CMD` wired, the semantic score drives the verdict.

    A claim/evidence pair with LOW lexical overlap is cleared because the (faked)
    embedding command reports high cosine — proving the seam takes precedence."""
    j = SimilarityJudge()
    c = Claim("users can log in", evidence=("git: authentication endpoint added"))
    # Lexically these barely overlap → would DISAGREE.
    assert run_judge(j, c, None).stance is Stance.DISAGREE
    # A python one-liner that ignores stdin and prints a high cosine.
    monkeypatch.setenv(sj.ENV_SIMILARITY_CMD, 'python -c "print(0.95)"')
    v = run_judge(j, c, None)
    assert v.stance is Stance.AGREE
    assert "embedding" in v.why


def test_embedding_seam_failure_falls_back_to_lexical(monkeypatch):
    """A broken embedding command (non-zero exit) returns None → the judge falls back
    to the lexical scorer rather than crashing or abstaining."""
    j = SimilarityJudge()
    c = Claim(
        "phase AUTH2 shipped at commit 80d4f30",
        evidence=("SHIPPED docs/82 AUTH2 shipped at commit 80d4f30 (via grep)",),
    )
    monkeypatch.setenv(sj.ENV_SIMILARITY_CMD, "exit 1")  # always fails
    v = run_judge(j, c, None)
    assert v.stance is Stance.AGREE  # lexical scorer still ran
    assert "lexical" in v.why


def test_embedding_seam_clamps_out_of_range(monkeypatch):
    """A provider that returns a cosine in [-1,1] (or noise) is clamped to [0,1] —
    it can never push the score past the bounds the threshold logic assumes."""
    assert sj._embedding_similarity.__doc__  # seam exists
    monkeypatch.setenv(sj.ENV_SIMILARITY_CMD, 'python -c "print(-0.5)"')
    assert sj._embedding_similarity("a", "b") == 0.0
    monkeypatch.setenv(sj.ENV_SIMILARITY_CMD, 'python -c "print(5.0)"')
    assert sj._embedding_similarity("a", "b") == 1.0
    monkeypatch.setenv(sj.ENV_SIMILARITY_CMD, 'python -c "print(\'garbage\')"')
    assert sj._embedding_similarity("a", "b") is None


# ---------------------------------------------------------------------------
# Fail-to-abstain / advisory-only — the seam-wide safety property.
# ---------------------------------------------------------------------------

def test_advisory_only_returns_frozen_verdict():
    j = SimilarityJudge()
    v = j.rule(Claim("x", evidence=("y",)), None)
    assert isinstance(v, JudgeVerdict)
    with pytest.raises(Exception):
        v._stance = Stance.AGREE  # frozen


def test_satisfies_judge_protocol_and_resolves_by_name(monkeypatch):
    """It is a discoverable plugin (not a built-in): satisfies the Judge protocol and
    resolves by name when registered under the entry-point group."""
    from dos import judges

    assert isinstance(SimilarityJudge(), Judge)  # runtime_checkable Protocol
    monkeypatch.setattr(
        judges, "_discover_entry_point_judges",
        lambda *, _stderr=None: [("similarity", SimilarityJudge())],
    )
    j = judges.resolve_judge("similarity")
    assert isinstance(j, SimilarityJudge)


def test_pure_lexical_scorer_is_bounded_and_deterministic():
    """The lexical scorer is pure, bounded [0,1], and symmetric on identical inputs."""
    assert sj._lexical_similarity("", "anything") == 0.0
    assert sj._lexical_similarity("anything", "") == 0.0
    s = sj._lexical_similarity("phase AUTH2 shipped", "phase AUTH2 shipped")
    assert s == 1.0
    mid = sj._lexical_similarity("phase AUTH2 shipped", "phase AUTH3 wedged")
    assert 0.0 < mid < 1.0
