"""dos.drivers.similarity_judge — the DISTANCE adjudicator (outside the kernel line).

Why this exists (read `docs/76` first — the flexibility geometry)
=================================================================

The kernel's truth surface is **byte-exact on purpose**: `verify()` asks "is this
*identical* to an un-forgeable effect?" and `tool_stream` asks "did the env return
the *byte-identical* result N times?" — both measured facts no agent can forge in its
own favor. The recurring operator question is "why so rigid — what about *fuzzy* /
*distance-based* matching, where 'close enough' counts?"

The answer the layering contract gives (CLAUDE.md, `docs/76`): flexibility is welcome,
but it moves UP, out of the kernel verdict and into a **JUDGE driver** — because a
distance *threshold* is a tunable dial, and a tunable dial deciding "is this claim
true?" is exactly the forgeable knob the kernel is built to NOT have
(`flexibility-geometry`: "Anti-pattern ruled out: a `confidence: float` ... INSIDE the
kernel"). So this driver is where "close enough" is allowed to live:

  * It runs ONLY on the residue the deterministic oracle ABSTAINED on (deterministic-
    first is the composition's job — `judge_eval.compose_deterministic_first` /
    `decisions._resolver_for` hand a judge only what the oracle could not settle).
  * It is **advisory-only** — it returns a `JudgeVerdict`, mutates nothing.
  * It **fails to ABSTAIN, never to AGREE** — below threshold, no evidence, or any
    error punts to a human; it can never auto-clear a claim by being uncertain.

The byte-inequality discipline, kept (the load-bearing subtlety)
================================================================

A naive "similarity judge" is a TRAP: if it scored the agent's `claim_text` against the
agent's own `stated_reason` (narration), it would be re-deriving the agent's OWN bytes —
**consistency, not grounding** (the [[consistency-is-not-grounding]] / mirror-verifier
disease, docs/141 §5a). Two strings the same author wrote being similar proves nothing.

So the comparison here is **structural, not against narration**: it scores `claim_text`
distance against the `Claim.evidence` tuple — the forgery-resistant, *env/git-authored*
bytes the kernel gathered (`Claim`'s docstring: "git lines, file state, a diff"). And it
**ABSTAINS when there is no evidence** — it will not agree off narration alone. The
distance is fuzzy; the *thing it is fuzzy against* is still un-authored by the judged
agent. That is the whole trick: flexibility on the MATCH, never on the PROVENANCE.

Purity & the optional embedding seam
====================================

The default scorer is **pure stdlib** — `difflib.SequenceMatcher`, a normalized
token-overlap ratio — so the package ships with ZERO new dependency and the judge is
always usable (the near-stdlib-kernel discipline, applied to a driver). A heavier
semantic scorer (sentence-embeddings cosine) is reachable through ONE guarded seam,
`_embedding_similarity`, gated on `$DOS_SIMILARITY_CMD` — the same env-configured,
never-raises provider shape as `llm_judge._call_provider`. With no command wired the
seam returns None and the judge falls back to the lexical scorer; it never hard-depends
on an embedding library. The coupling lives in the operator's env, not the code.

Register it under the `dos.judges` entry-point group (it is discoverable, not a
built-in — only the `abstain` baseline is unshadowable):

    [project.entry-points."dos.judges"]
    similarity = "dos.drivers.similarity_judge:SimilarityJudge"
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess


# The env var naming an OPTIONAL embedding-similarity command. It must read two
# texts on stdin separated by a NUL byte (\x00) and write a single float in [0,1]
# (cosine similarity) on stdout. With it unset the judge uses the pure-stdlib
# lexical scorer — so this is a strict ENHANCEMENT seam, never a dependency.
ENV_SIMILARITY_CMD = "DOS_SIMILARITY_CMD"

# The env var overriding the default agree-threshold (a float in [0,1]). The
# threshold is DATA, declared by the operator — never a constant baked into a
# kernel verdict. Default below.
ENV_SIMILARITY_THRESHOLD = "DOS_SIMILARITY_THRESHOLD"

# The default agree-threshold. Deliberately HIGH (0.82): a judge that clears a
# claim is the one dangerous outcome the seam guards, so "close enough to agree"
# must mean *very* close. Below this AND above the abstain-floor → DISAGREE; below
# the abstain-floor with usable evidence → still DISAGREE (low overlap = unsupported);
# the ABSTAIN cases are "no evidence to score against" and "scorer errored," never
# "the score was middling" — a middling score is a real DISAGREE signal, not an
# I-can't-tell.
DEFAULT_THRESHOLD = 0.82


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    """Lowercased word tokens of `text` — the unit the lexical scorer compares.

    Pure. Casefolded so 'AUTH2' and 'auth2' match; `\\w+` drops punctuation/quoting
    so a claim and an evidence line that differ only in formatting still score high.
    """
    return _TOKEN_RE.findall(text.casefold())


def _lexical_similarity(claim_text: str, evidence_blob: str) -> float:
    """A pure-stdlib similarity in [0,1] between a claim and the evidence blob.

    Two cheap, forgery-irrelevant signals, maxed (the claim is "supported" if EITHER
    the wording lines up OR the claim's tokens are largely present in the evidence):

      * `difflib.SequenceMatcher` ratio over the casefolded raw strings — catches
        near-verbatim phrasing (a claim quoted back by a git line / file state).
      * token-recall — the fraction of the claim's distinct tokens that appear in the
        evidence's token set — catches a claim whose key terms are all witnessed even
        if the surrounding prose differs.

    Both are symmetric-enough and bounded [0,1]; `max` is the right combinator because
    either kind of match is sufficient evidence of support. PURE — no I/O, no clock.
    """
    if not claim_text or not evidence_blob:
        return 0.0
    seq = difflib.SequenceMatcher(None, claim_text.casefold(), evidence_blob.casefold()).ratio()
    claim_toks = set(_tokens(claim_text))
    if not claim_toks:
        return seq
    ev_toks = set(_tokens(evidence_blob))
    recall = len(claim_toks & ev_toks) / len(claim_toks)
    return max(seq, recall)


def _embedding_similarity(claim_text: str, evidence_blob: str) -> float | None:
    """The OPTIONAL semantic-similarity seam. Returns cosine in [0,1], or None.

    Honors `$DOS_SIMILARITY_CMD` (a shell command reading `claim\\x00evidence` on
    stdin, writing one float on stdout). Never raises — any failure (command unset,
    missing, timeout, non-zero exit, unparseable output) returns None so the caller
    falls back to the lexical scorer. This is the ONE place a heavier model is
    touched; keeping it a single guarded seam is what lets the package ship with zero
    embedding dependency while still allowing an operator to wire one in by env var
    (the exact `llm_judge._call_provider` discipline, re-aimed at a similarity score).
    """
    cmd = os.environ.get(ENV_SIMILARITY_CMD)
    if not cmd:
        return None
    try:
        payload = (claim_text + "\x00" + evidence_blob).encode("utf-8")
        p = subprocess.run(
            cmd, shell=True, input=payload, capture_output=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    out = (p.stdout or b"").decode("utf-8", errors="replace").strip()
    try:
        val = float(out.split()[0]) if out else None
    except (ValueError, IndexError):
        return None
    if val is None:
        return None
    # Clamp into [0,1] — a provider that returns a cosine in [-1,1] (or noise) can
    # never push the score past the bounds the threshold logic assumes.
    return max(0.0, min(1.0, val))


def _threshold() -> float:
    """The agree-threshold, read from `$DOS_SIMILARITY_THRESHOLD` or the default.

    A malformed value falls back to the default rather than crashing — the threshold
    is operator data, and a typo should degrade safely, not take down adjudication.
    """
    raw = os.environ.get(ENV_SIMILARITY_THRESHOLD)
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        val = float(raw)
    except ValueError:
        return DEFAULT_THRESHOLD
    return max(0.0, min(1.0, val))


class SimilarityJudge:
    """A DISTANCE-based occupant of the JUDGE rung — a `dos.judges.Judge`.

    Rules on a generic `Claim` by scoring how well its `claim_text` matches the
    forgery-resistant `evidence` (NOT the agent's narration — that would be a mirror).
    Fuzzy on the match, strict on the provenance, advisory-only, fail-to-abstain:

      * **no evidence** → ABSTAIN. It refuses to agree off narration alone — the
        byte-inequality floor (you cannot confirm a claim with the claimant's bytes).
      * score **≥ threshold** → AGREE (the claim is near-verbatim witnessed by the
        evidence). The one clearing verdict, reachable only on a high, *measured*
        overlap with un-authored bytes.
      * score **< threshold** (with evidence present) → DISAGREE (the evidence does
        not support the claim). A middling score is a real "unsupported" signal, not
        an "I can't tell."

    The threshold is DATA (`$DOS_SIMILARITY_THRESHOLD`, default 0.82), never a knob
    inside a kernel verdict. The scorer is pure stdlib by default; an embedding scorer
    is an opt-in env seam (`$DOS_SIMILARITY_CMD`). With nothing wired it is fully
    usable — it just uses the lexical scorer — so it is always safe to register and
    `dos judge-eval`.
    """

    name = "similarity"

    def rule(self, claim, config):
        from dos.judges import JudgeVerdict

        # The byte-inequality floor: with no evidence there are no un-authored bytes
        # to score against. Agreeing here would mean believing the agent's own
        # narration — the mirror-verifier trap. ABSTAIN (route to a human).
        evidence = tuple(claim.evidence or ())
        if not evidence:
            return JudgeVerdict.abstain(
                "no evidence to score the claim against — a distance judge will not "
                "agree off narration alone (that would re-derive the agent's own "
                "bytes); routing this claim to a human.",
            )

        claim_text = (claim.claim_text or "").strip()
        if not claim_text:
            return JudgeVerdict.abstain(
                "empty claim_text — nothing to match against the evidence; abstaining.",
            )

        evidence_blob = "\n".join(evidence)
        threshold = _threshold()

        # Prefer the semantic seam if wired; else the pure lexical scorer. The seam
        # never raises (it returns None on any failure), so this never needs a guard.
        embedded = _embedding_similarity(claim_text, evidence_blob)
        if embedded is not None:
            score = embedded
            scorer = "embedding"
        else:
            score = _lexical_similarity(claim_text, evidence_blob)
            scorer = "lexical"

        detail = f"{scorer} similarity {score:.3f} vs threshold {threshold:.2f}"
        ev = (f"similarity: {detail}",)

        if score >= threshold:
            return JudgeVerdict.agree(
                f"claim is witnessed by the evidence ({detail}) — near-verbatim match "
                f"to un-authored bytes the agent did not write.",
                evidence=ev,
            )
        return JudgeVerdict.disagree(
            f"claim is NOT supported by the evidence ({detail}) — the gathered "
            f"un-authored bytes do not match the assertion.",
            evidence=ev,
        )
