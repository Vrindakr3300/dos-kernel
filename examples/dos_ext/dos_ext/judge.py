"""A custom DOS judge — the adjudicator axis of hackability (Axis 6, `dos.judges`).

The JUDGE rung of DOS's trust ladder (ORACLE → JUDGE → HUMAN) is where you plug in
*your own* adjudicator for the claims the deterministic oracle could not settle. The
reference occupant is `dos.drivers.llm_judge:LlmJudge` (a model behind a provider
seam); this is the *other* end of the spectrum — a trivial, dependency-free heuristic
judge — to show that a `Judge` is just `rule(claim, config) -> JudgeVerdict` and needs
no model at all. A researcher copies this file, swaps the heuristic for their real
adjudicator (a debate, a learned verifier, a build/test runner), and registers it via a
`dos.judges` entry_point (see this package's `pyproject.toml`).

The disciplines (see `dos.judges`): a judge is **advisory-only** — it returns a verdict
and mutates nothing — and **fails to ABSTAIN, never to AGREE** (`dos.judges.run_judge`
converts a raise / a bad return into an abstain, so even a buggy judge can never
auto-clear a claim). Note the three-valued output: AGREE / DISAGREE / **ABSTAIN**.
Abstaining is a first-class, honorable answer — "I can't tell, ask a human" — and the
conservative default. A judge that guesses AGREE when unsure is the one failure mode the
whole seam exists to prevent (it is a false-clear, the dangerous cell `dos judge-eval`
measures).
"""

from __future__ import annotations

from dos.judges import Claim, JudgeVerdict


class KeywordJudge:
    """A zero-dependency heuristic judge: rule on a ship-style claim from evidence.

    NOT a serious adjudicator — a worked skeleton. The heuristic:

      * If the claim asserts a ship/completion ("shipped"/"done"/"complete"/"landed")
        and the evidence contains a commit-shaped line ("commit "/"sha"/a hex token),
        AGREE — the narration is backed by an artifact.
      * If it asserts a ship but the evidence is empty or explicitly says no commit
        ("no commit"/"not found"), DISAGREE — an unbacked "done" is exactly the lie
        the kernel distrusts.
      * Otherwise ABSTAIN — the heuristic has no opinion; route it to a human.

    Real judges replace the body of `rule`; the *shape* (and the abstain-when-unsure
    discipline) is what to copy. The heuristic is deliberately conservative: it only
    AGREES on a positive artifact match, so its false-clear rate stays low — the
    property `dos judge-eval` will score.
    """

    name = "keyword"

    _SHIP_WORDS = ("shipped", "done", "complete", "completed", "landed", "merged")
    _COMMIT_HINTS = ("commit ", "sha", "sha:", "git log")
    _NEGATIVE_HINTS = ("no commit", "not found", "no such", "missing", "absent")

    def rule(self, claim: Claim, config: object) -> JudgeVerdict:
        text = claim.claim_text.lower()
        ev_joined = " ".join(claim.evidence).lower()

        asserts_ship = any(w in text for w in self._SHIP_WORDS)
        if not asserts_ship:
            return JudgeVerdict.abstain(
                "claim is not a ship/completion assertion — the keyword heuristic "
                "has no rule for it; routing to a human."
            )

        if any(neg in ev_joined for neg in self._NEGATIVE_HINTS):
            return JudgeVerdict.disagree(
                "claim asserts completion but the evidence explicitly shows no "
                "artifact (e.g. 'no commit') — an unbacked 'done'."
            )
        if not claim.evidence:
            return JudgeVerdict.disagree(
                "claim asserts completion but NO evidence was gathered — an "
                "unbacked 'done' is the narration the kernel distrusts."
            )
        if any(h in ev_joined for h in self._COMMIT_HINTS) or _has_hex_token(ev_joined):
            return JudgeVerdict.agree(
                "claim asserts completion and the evidence carries a commit-shaped "
                "artifact backing it."
            )
        return JudgeVerdict.abstain(
            "claim asserts completion and evidence is present but not recognizably "
            "an artifact — the heuristic can't tell; routing to a human."
        )


def _has_hex_token(s: str) -> bool:
    """True if any whitespace-delimited token looks like a git short-sha (>=7 hex)."""
    for tok in s.split():
        t = tok.strip(".,;:()[]")
        if len(t) >= 7 and all(c in "0123456789abcdef" for c in t):
            return True
    return False


# A ready-made instance, so the entry_point can point at the class
# (`...:KeywordJudge`, which `dos` instantiates) or this object (`...:keyword`).
keyword = KeywordJudge()
