"""claim_extract — what (plan, phase) did an agent CLAIM it shipped? (docs/134 §2.1)

The crux of the runtime binding: a `Stop` hook is handed a *transcript*, but the
truth syscall (`verify`) wants `(plan, phase)`. This module is that bridge — it
reads what an agent *asserted* it finished, so the hook can check each assertion
against git. It does NOT verify anything; it only extracts the *claims* to be
verified (the oracle does the verifying).

Three rungs, strongest-first, mirroring the oracle's own evidence ladder:

  1. **MARKER** (strongest, opt-in): the agent ended a unit with a machine line
     ``DOS-CLAIM: <plan> <phase>``. Lifted byte-exactly. This is where the
     operator's literal "@verify-style marker" lives — the agent *declaring what
     to check*, not a directive DOS executes.
  2. **FRONTMATTER** (structural): a skill whose frontmatter declares
     ``dos.plan``/``dos.phase`` makes the claim known without parsing prose. That
     rung lives at the hook boundary (the firing skill is known there), exposed
     here as ``claim_from_frontmatter`` so both paths return the same ``Claim``.
  3. **HEURISTIC** (weakest, ABSTAINING): absent a marker, scan a "shipped/landed
     /done <ID>" sentence for an explicit plan/phase-shaped token. This rung's
     ONLY failure mode is a *missed* claim (the agent then stops unverified — the
     safe direction); it must NEVER fabricate a `(plan, phase)`, because a
     `verify` run against a hallucinated claim would make the verifier itself the
     unreliable narrator it exists to catch (docs/103, inward).

The load-bearing rule, stated once: **abstain, never invent.** Free prose ("I'm
done", "shipped the auth work") yields NO claim — there is no way to know the
plan/phase *identifiers* from prose without inventing them, so the heuristic only
fires on an explicit ID-shaped token and is marked low-confidence. A design that
pretends prose alone is enough is hand-waving (docs/134 §2.1).

Shape follows ``liveness.classify`` / ``git_delta``: the **pure** extractor
(``extract_claims(text, policy) -> list[Claim]``) operates on already-read text;
the **boundary reader** (``assistant_text_from_transcript``) does the file/JSON
I/O at the call site, never inside the pure core. The transcript-parsing
convention (``message.content`` list of blocks, text from ``block["text"]``)
mirrors ``scripts/trajectory_audit.py`` so the two readers cannot drift.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


# The explicit marker an agent (or skill) emits to declare a verifiable claim.
# Byte-exact, anchored at a line start (after optional list/quote markup) so a
# mention *inside* prose ("emit a DOS-CLAIM: line") is not mistaken for a real
# one — only a line that IS the marker counts.
_MARKER_RE = re.compile(
    r"""^[ \t>*\-]*           # optional leading markup (blockquote, list bullet)
        DOS-CLAIM:[ \t]+      # the literal marker
        (?P<plan>[^\s]+)      # plan token (no whitespace)
        [ \t]+
        (?P<phase>[^\s]+)     # phase token (no whitespace)
        [ \t]*$               # nothing else on the line
    """,
    re.VERBOSE | re.MULTILINE,
)

# A plan/phase-shaped identifier for the HEURISTIC rung: an uppercase-led token
# of LETTERS then DIGITS (AUTH2, FQ390, DLA3) — the shape this codebase's phases
# actually take. Deliberately narrow: it will MISS a lowercased or prose-only
# claim (safe — abstain) rather than guess. It never matches a bare English word
# (no digits) so "done" / "shipped" alone yield nothing.
_PHASE_TOKEN_RE = re.compile(r"\b([A-Z][A-Z_]*[A-Z])(\d+)\b")

# The completion verbs that gate the heuristic rung — the phase-shaped token must
# sit in a sentence that actually CLAIMS completion, not merely mentions the id.
_COMPLETION_HINT_RE = re.compile(
    r"\b(shipped|landed|completed|finished|done|merged)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Claim:
    """One (plan, phase) an agent claimed shipped, plus how we know.

    ``rung`` is ``marker`` › ``frontmatter`` › ``heuristic`` (strongest-first),
    the same provenance discipline as the oracle's ``source`` tag. ``raw`` is the
    text the claim was lifted from (the marker line, or the sentence), for an
    auditable trail. ``confident`` is False only for the heuristic rung — a
    caller may choose to treat a low-confidence claim as advisory.
    """

    plan: str
    phase: str
    rung: str
    raw: str = ""

    @property
    def confident(self) -> bool:
        return self.rung in ("marker", "frontmatter")

    def to_dict(self) -> dict:
        return {
            "plan": self.plan,
            "phase": self.phase,
            "rung": self.rung,
            "raw": self.raw,
            "confident": self.confident,
        }


def claim_from_frontmatter(plan: str | None, phase: str | None) -> list[Claim]:
    """The FRONTMATTER rung: a skill declared (dos.plan, dos.phase).

    Returns a single-element list when both are present, else empty. Pure — the
    hook reads the frontmatter at the boundary and passes the two strings in.
    """
    plan = (plan or "").strip()
    phase = (phase or "").strip()
    if plan and phase:
        return [Claim(plan=plan, phase=phase, rung="frontmatter",
                      raw=f"dos.plan={plan} dos.phase={phase}")]
    return []


def extract_claims(text: str, *, allow_heuristic: bool = True) -> list[Claim]:
    """The PURE extractor: claims an agent asserted, strongest rung first.

    Operates on already-read assistant text (the boundary reader hands it over).
    No I/O. Deterministic. Deduplicates on (plan, phase), keeping the strongest
    rung. ``allow_heuristic=False`` restricts to the byte-exact MARKER rung — the
    fail-closed posture a strict caller wants (only act on what the agent
    explicitly declared).

    Returns ``[]`` when nothing is confidently extractable — the abstain floor.
    """
    if not text:
        return []

    out: dict[tuple[str, str], Claim] = {}

    # Rung 1 — the byte-exact marker. Strongest; always honored.
    for m in _MARKER_RE.finditer(text):
        plan, phase = m.group("plan"), m.group("phase")
        out[(plan, phase)] = Claim(plan=plan, phase=phase, rung="marker",
                                   raw=m.group(0).strip())

    if not allow_heuristic:
        return list(out.values())

    # Rung 3 — the abstaining heuristic. Only fires when a phase-SHAPED token
    # (AUTH2) sits in a sentence that also carries a completion verb. This never
    # invents an id from prose: no ID-shaped token ⇒ no claim. A token already
    # captured by the marker rung is not downgraded.
    for line in text.splitlines():
        if not _COMPLETION_HINT_RE.search(line):
            continue
        for tok in _PHASE_TOKEN_RE.finditer(line):
            phase = tok.group(0)            # e.g. "AUTH2"
            plan = tok.group(1)             # the letter stem, e.g. "AUTH"
            key = (plan, phase)
            if key in out:
                continue                    # don't shadow a stronger rung
            out[key] = Claim(plan=plan, phase=phase, rung="heuristic",
                             raw=line.strip())

    return list(out.values())


# ---------------------------------------------------------------------------
# Boundary I/O — the transcript reader. NOT pure (reads a file); kept here so the
# extractor's caller has one home for the read, the git_delta discipline.
# ---------------------------------------------------------------------------
def _text_blocks(content: object) -> list[str]:
    """Pull text from a message `content` (a str, or a list of typed blocks).

    Mirrors scripts/trajectory_audit.py so the two transcript readers can't drift.
    """
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        texts: list[str] = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text", "")
                if isinstance(t, str) and t:
                    texts.append(t)
        return texts
    return []


def assistant_text_from_transcript(path: str, *, last_turns: int = 1) -> str:
    """Read the text of the last N assistant turn(s) from a transcript JSONL.

    The Stop hook is told to verify "what the agent just claimed," so we read the
    *tail* — the final assistant turn(s) — not the whole session (an earlier,
    superseded claim must not re-trigger). Returns the concatenated text, or ``""``
    on any read/parse failure (the no-crash floor: a missing/garbled transcript
    yields no claims, the agent stops unverified — the safe direction).
    """
    if last_turns < 1:
        last_turns = 1
    try:
        lines = _read_lines(path)
    except OSError:
        return ""

    # Collect assistant-turn texts in order, then keep the last N.
    turns: list[str] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        blocks = _text_blocks(msg.get("content"))
        if blocks:
            turns.append("\n".join(blocks))

    if not turns:
        return ""
    return "\n".join(turns[-last_turns:])


def _read_lines(path: str) -> list[str]:
    """Read a transcript file's lines (split out so a test can monkeypatch I/O)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.readlines()
