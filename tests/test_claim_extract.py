"""claim_extract — the verify-on-stop claim bridge (docs/134 §2.1).

The crux component: a Stop hook gets a transcript, the oracle wants (plan, phase).
These pin the three rungs and — the load-bearing property — the abstain-never-
invent floor: free prose must yield NO claim, because a verify run against a
fabricated (plan, phase) would make the verifier itself the unreliable narrator
(docs/103, inward).
"""

from __future__ import annotations

import json

from dos import claim_extract as ce


# ---------------------------------------------------------------------------
# Rung 1 — the byte-exact marker.
# ---------------------------------------------------------------------------
def test_marker_rung_lifts_plan_and_phase():
    claims = ce.extract_claims("I did the work.\nDOS-CLAIM: AUTH AUTH2\ndone")
    assert len(claims) == 1
    c = claims[0]
    assert (c.plan, c.phase, c.rung, c.confident) == ("AUTH", "AUTH2", "marker", True)


def test_marker_must_be_its_own_line_not_a_prose_mention():
    # a mention of the marker INSIDE prose must NOT be lifted as a real claim
    claims = ce.extract_claims("remember to emit a DOS-CLAIM: line like AUTH AUTH2")
    assert claims == []


def test_marker_tolerates_leading_list_and_quote_markup():
    for prefix in ("- ", "* ", "> ", "  "):
        claims = ce.extract_claims(f"{prefix}DOS-CLAIM: FQ FQ390")
        assert [(c.plan, c.phase) for c in claims] == [("FQ", "FQ390")]


def test_multiple_markers_dedupe_on_plan_phase():
    text = "DOS-CLAIM: A A1\nDOS-CLAIM: A A1\nDOS-CLAIM: B B2"
    claims = ce.extract_claims(text)
    keys = sorted((c.plan, c.phase) for c in claims)
    assert keys == [("A", "A1"), ("B", "B2")]


# ---------------------------------------------------------------------------
# Rung 2 — frontmatter-bound.
# ---------------------------------------------------------------------------
def test_frontmatter_rung_needs_both_plan_and_phase():
    assert [(c.plan, c.phase, c.rung) for c in ce.claim_from_frontmatter("AUTH", "AUTH2")] \
        == [("AUTH", "AUTH2", "frontmatter")]
    assert ce.claim_from_frontmatter("AUTH", None) == []
    assert ce.claim_from_frontmatter(None, "AUTH2") == []
    assert ce.claim_from_frontmatter("", "") == []


def test_frontmatter_claim_is_confident():
    (c,) = ce.claim_from_frontmatter("AUTH", "AUTH2")
    assert c.confident is True


# ---------------------------------------------------------------------------
# Rung 3 — the abstaining heuristic. THE SAFETY-CRITICAL RUNG.
# ---------------------------------------------------------------------------
def test_heuristic_off_by_default():
    # default extract_claims keeps heuristic ON for library callers, but the
    # explicit fail-closed call (allow_heuristic=False) yields ONLY marker rungs
    text = "I shipped AUTH2 today"
    assert ce.extract_claims(text, allow_heuristic=False) == []


def test_heuristic_fires_on_explicit_token_plus_completion_verb():
    claims = ce.extract_claims("I shipped AUTH2 today", allow_heuristic=True)
    assert len(claims) == 1
    c = claims[0]
    assert (c.plan, c.phase, c.rung, c.confident) == ("AUTH", "AUTH2", "heuristic", False)


def test_heuristic_NEVER_invents_from_pure_prose():
    # The load-bearing safety property: no ID-shaped token ⇒ no claim, EVEN with a
    # completion verb. "All done!" must not become a (plan, phase).
    for prose in (
        "All done! Everything works.",
        "I finished the auth endpoint and it's shipped.",
        "Completed the migration successfully.",
        "Done.",
    ):
        assert ce.extract_claims(prose, allow_heuristic=True) == [], prose


def test_heuristic_requires_completion_verb_not_bare_token():
    # an ID-shaped token with NO completion verb is just a mention → no claim
    assert ce.extract_claims("see AUTH2 for context", allow_heuristic=True) == []


def test_marker_is_not_downgraded_by_heuristic():
    # when both a marker and a heuristic-shaped sentence name the same phase, the
    # stronger (marker) rung wins — no duplicate, no downgrade
    text = "DOS-CLAIM: AUTH AUTH2\nyes I shipped AUTH2"
    claims = ce.extract_claims(text, allow_heuristic=True)
    assert len(claims) == 1
    assert claims[0].rung == "marker"


# ---------------------------------------------------------------------------
# The boundary reader (transcript I/O).
# ---------------------------------------------------------------------------
def _write_transcript(tmp_path, *turns):
    """Write a JSONL transcript; each turn is (role, text)."""
    p = tmp_path / "transcript.jsonl"
    lines = []
    for role, text in turns:
        rec = {"type": role, "message": {"role": role,
               "content": [{"type": "text", "text": text}]}}
        lines.append(json.dumps(rec))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def test_reader_pulls_last_assistant_turn(tmp_path):
    path = _write_transcript(
        tmp_path,
        ("assistant", "early turn\nDOS-CLAIM: OLD OLD1"),
        ("user", "ok"),
        ("assistant", "final turn\nDOS-CLAIM: NEW NEW1"),
    )
    text = ce.assistant_text_from_transcript(path, last_turns=1)
    # only the LAST assistant turn — a superseded earlier claim must not re-fire
    claims = ce.extract_claims(text, allow_heuristic=False)
    assert [(c.plan, c.phase) for c in claims] == [("NEW", "NEW1")]


def test_reader_can_widen_to_more_turns(tmp_path):
    path = _write_transcript(
        tmp_path,
        ("assistant", "DOS-CLAIM: A A1"),
        ("user", "ok"),
        ("assistant", "DOS-CLAIM: B B1"),
    )
    text = ce.assistant_text_from_transcript(path, last_turns=2)
    keys = sorted((c.plan, c.phase) for c in ce.extract_claims(text, allow_heuristic=False))
    assert keys == [("A", "A1"), ("B", "B1")]


def test_reader_ignores_non_assistant_and_tool_blocks(tmp_path):
    p = tmp_path / "t.jsonl"
    recs = [
        {"type": "user", "message": {"role": "user",
         "content": [{"type": "text", "text": "DOS-CLAIM: USER USER1"}]}},
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "tool_use", "name": "Bash", "input": {}},
                     {"type": "text", "text": "DOS-CLAIM: REAL REAL1"}]}},
    ]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    text = ce.assistant_text_from_transcript(str(p), last_turns=5)
    claims = ce.extract_claims(text, allow_heuristic=False)
    # the user-turn marker is ignored; the assistant text block is read
    assert [(c.plan, c.phase) for c in claims] == [("REAL", "REAL1")]


def test_reader_missing_file_returns_empty_not_crash():
    # the fail-safe floor: a missing transcript yields no claims (agent stops)
    assert ce.assistant_text_from_transcript("/no/such/file.jsonl") == ""


def test_reader_garbled_lines_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        "not json at all\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "text", "text": "DOS-CLAIM: OK OK1"}]}})
        + "\n{ broken json\n",
        encoding="utf-8",
    )
    text = ce.assistant_text_from_transcript(str(p), last_turns=5)
    assert [(c.plan, c.phase) for c in ce.extract_claims(text, allow_heuristic=False)] \
        == [("OK", "OK1")]


def test_empty_text_yields_no_claims():
    assert ce.extract_claims("") == []
    assert ce.extract_claims("   \n  \n") == []
