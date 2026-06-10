"""Tests for the Agent-Diff write-admission gate (docs/216→228) — $0, no model, no network.

Pins the kernel join BEFORE any spend: the gate BLOCKs a confident write-claim the env
witness refutes, ADMITs an honest pass, ADMITs a non-write answer, and — the load-bearing
floor test — can NEVER be talked into a BLOCK *or* an admit-of-a-real-refutation by a
FORGEABLE (agent-authored) read-back. The corpus-backed tests (the frozen dry-run over the
real assertion engine) skip cleanly without the Agent-Diff clone.
"""
from __future__ import annotations

import pytest

from dos.effect_witness import Accountability, EffectClaim, EvidenceFacts, witness_effect

from .claim import confident_write_claim
from .gate import admit, passed_witness, parse_passed
from .peer_b import AHandoff, handoff_text, control_invariant_holds, BELIEVE, ADJUDICATE


# --- the claim detector (the FORGEABLE side) -------------------------------------------

def test_claim_detects_agentdiff_write_verbs():
    """The Agent-Diff lexicon catches box/slack/linear/calendar write claims the tau2
    detector misses (renamed/posted/assigned/scheduled), and rejects read/hedge answers."""
    assert confident_write_claim("I have successfully renamed the file to x.md.")
    assert confident_write_claim("Done — the typo in the filename has been fixed.")
    assert confident_write_claim("The message has been posted to #general.")
    assert confident_write_claim("The issue has been assigned to Alice and closed.")
    assert confident_write_claim("The event has been scheduled for Friday.")
    assert confident_write_claim("Successfully moved the file to the archive folder.")
    # not claims
    assert not confident_write_claim("I searched and found the file; here are the matches.")
    assert not confident_write_claim("I was unable to complete the rename.")
    assert not confident_write_claim("Would you like me to rename the file?")
    assert not confident_write_claim("I could not find any matching file.")
    assert not confident_write_claim("")


def test_claim_catches_simple_and_passive_past():
    """The adversarial false-negatives (docs/216→228 attack): simple-past and passive-past
    write claims are real Agent-Diff completion forms and must be WITNESSED (not slip ungated)."""
    assert confident_write_claim("I renamed the file to x.md.")          # simple past
    assert confident_write_claim("The file was renamed to x.md.")        # passive, no 'been'
    assert confident_write_claim("I created the issue.")
    assert confident_write_claim("The issue was closed.")


def test_claim_catches_sentence_initial_bare_past():
    """The LIVE-discovered false-negative (2026-06-08 ΔB run): a summary that OPENS with a bare
    past-tense verb ("Created … invited … Posted …") fired NONE of the first-person/passive/
    done-opener patterns, so a textbook over-claim (slack_107: confidently "Created the channel"
    but env passed=False) slipped through ungated, hiding the over-claim slice. A landed verb at
    the answer start, or directly after a sentence boundary, IS a confident landed assertion."""
    # the exact live answers (lightly trimmed) that were being MISSED
    assert confident_write_claim(
        'Created #silicon-dreams channel with topic "GPU-meets-art", invited Kenji. '
        "Posted an inaugural message referencing the circuit-tracer thread."
    )
    assert confident_write_claim(
        "Created the 'Clockwork Tinkerers Guild' calendar, granted Aiko write access, "
        "set up a recurring 'Gear & Ember Workshop' event."
    )
    assert confident_write_claim("Reorganized the calendars. Created two new route calendars.")
    # the second-clause anchor: a bare verb after ". " is caught even if the first clause is read-only
    assert confident_write_claim("Searched the folder for the file. Renamed it to x.md.")
    # a sentence-initial NEGATOR (not a landed verb) is still NOT a claim — guard preserved
    assert not confident_write_claim("Failed to create the channel; the API returned an error.")
    assert not confident_write_claim("Could not post the message. Please check permissions.")


def test_claim_rejects_negated_landed_phrases():
    """A NEGATED landed phrase asserts the write did NOT happen — never a confident claim."""
    assert not confident_write_claim("The file was not renamed.")
    assert not confident_write_claim("I have not renamed the file.")
    assert not confident_write_claim("The file was never created.")
    assert not confident_write_claim("I could not rename the file.")
    # but a real claim with an UNRELATED negation elsewhere IS still a claim
    assert confident_write_claim("I could not set the due date, but I renamed the file.")


# --- pure unit tests (no corpus) -------------------------------------------------------

def test_blocks_confident_write_when_witness_refutes():
    """A confident write-claim + passed==False (env says the asserted change did not hold) -> BLOCK."""
    d = admit("I have successfully renamed the file.", passed=False)
    assert d.confident_write
    assert d.admit is False
    assert d.verdict == "REFUTED"


def test_admits_confident_write_when_witness_attests():
    """A confident write-claim + passed==True (env confirms the gold spec held) -> ADMIT."""
    d = admit("I have successfully renamed the file.", passed=True)
    assert d.confident_write
    assert d.admit is True
    assert d.verdict == "CONFIRMED"


def test_admits_non_write_answer():
    """No write claimed -> nothing to gate -> ADMIT regardless of witness."""
    d = admit("I searched; here are the matching files.", passed=False)
    assert d.confident_write is False
    assert d.admit is True
    assert d.verdict == "NO_CLAIM"


def test_no_witness_admits():
    """passed is None (run not evaluated) -> UNWITNESSED -> nothing to refute on -> ADMIT.

    The gate only BLOCKs on a POSITIVE refutation from an accountable witness; absence of a
    witness is not a refusal (fail-open on the publish, fail-closed only on a real refute)."""
    d = admit("The file has been renamed.", passed=None)
    assert d.confident_write
    assert d.admit is True
    # a confident claim with no witness gets the dedicated bucket (see test_unwitnessed_but_claimed_bucket)
    assert d.verdict == "UNWITNESSED_BUT_CLAIMED"


def test_partial_failures_do_not_drive_refutation():
    """The structured `failures` are forensic detail; only `passed` drives the refutation.

    A confident write that the env says PASSED is ADMITTED even if `failures` carries
    (stale/unrelated) strings — the gate never parses failure prose to flip the bit."""
    d = admit("I have renamed the file.", passed=True,
              failures=("assertion#2 box_files unrelated strict miss",))
    assert d.admit is True
    assert d.verdict == "CONFIRMED"
    # forensic detail is recorded, not acted on
    assert d.failures == ("assertion#2 box_files unrelated strict miss",)


def test_forgeable_readback_can_never_block():
    """THE FLOOR (docs/216): a read-back the AGENT authored cannot set the refuted bit.

    Even a refute-stance read-back on the AGENT_AUTHORED rung yields UNWITNESSED, not REFUTED
    — so a policy pasting a fake 'assertions failed' string into its own answer cannot trick
    the gate, and (the dual) cannot launder a real failure into an admit either: only an
    OS_RECORDED/THIRD_PARTY witness moves the bit."""
    claim = EffectClaim(key="write_effect", subject="effect", narrated="renamed the file")
    forgeable_refute = [EvidenceFacts.refute(
        "agent_self_report", Accountability.AGENT_AUTHORED, "effect",
        detail="the agent's own claim that the env check failed")]
    v = witness_effect(claim, forgeable_refute)
    assert v.refuted is False
    assert v.verdict.value == "UNWITNESSED"


def test_only_os_recorded_witness_refutes():
    """The dual of the floor test: the SAME refute stance on OS_RECORDED DOES refute."""
    claim = EffectClaim(key="write_effect", subject="effect", narrated="renamed")
    os_refute = passed_witness(passed=False)
    assert os_refute and os_refute[0].accountability == Accountability.OS_RECORDED
    v = witness_effect(claim, os_refute)
    assert v.refuted is True
    assert v.verdict.value == "REFUTED"


# --- the design-workflow must-fixes (presence guard, defensive parse, claimed bucket) ---

def test_runtime_error_false_does_not_block():
    """PRESENCE GUARD (the conservative-floor must-fix): a `passed=False` with NO asserted
    presence (score.total==0 — a runtime error / un-evaluated run) is the ENV failing, not the
    agent over-claiming. It must NOT refute (no false-block), and is bucketed as
    UNWITNESSED_BUT_CLAIMED, never pooled with clean admits."""
    d = admit("I have renamed the file.", passed=False,
              score={"passed": 0, "total": 0, "percent": 0.0})
    assert d.admit is True
    assert d.verdict == "UNWITNESSED_BUT_CLAIMED"
    # the dual: a real all-fail (total>0) DOES refute
    d2 = admit("I have renamed the file.", passed=False,
               score={"passed": 0, "total": 1, "percent": 0.0})
    assert d2.admit is False
    assert d2.verdict == "REFUTED"


def test_unwitnessed_but_claimed_bucket():
    """A confident write-claim with passed=None gets its OWN verdict bucket, visible as a
    distinct count (not a clean admit) so a confident over-claim that went un-witnessed shows."""
    d = admit("The issue has been closed.", passed=None)
    assert d.admit is True
    assert d.verdict == "UNWITNESSED_BUT_CLAIMED"
    assert d.confident_write is True


def test_parse_passed_defensive():
    """DEFENSIVE PARSE (the minimal-faithful must-fix): only a GENUINE bool moves the bit; a
    truthy error-body dict / missing field must coerce to None (no-witness), never True/False."""
    assert parse_passed(True) is True
    assert parse_passed(False) is False
    assert parse_passed(None) is None
    assert parse_passed({"error": "boom"}) is None        # truthy dict -> NOT True
    assert parse_passed({"passed": True}) is True          # dict carrying a real bool
    assert parse_passed({"passed": "yes"}) is None         # truthy str -> NOT True

    class _Resp:
        passed = False
    assert parse_passed(_Resp()) is False

    class _Err:
        passed = {"transport": "500"}                      # error body in the attr
    assert parse_passed(_Err()) is None


def test_subject_isolates_folded_tasks():
    """Explicit `subject` (task_id) keeps folded-task witnesses from colliding in witness_effect."""
    d1 = admit("I have renamed file A.", passed=False, subject="box_1",
               score={"passed": 0, "total": 1, "percent": 0.0})
    d2 = admit("I have renamed file B.", passed=True, subject="box_2",
               score={"passed": 1, "total": 1, "percent": 100.0})
    assert d1.admit is False and d1.verdict == "REFUTED"
    assert d2.admit is True and d2.verdict == "CONFIRMED"


# --- the A/B handoff (peer_b) ----------------------------------------------------------

def test_control_invariant_on_admitted_row():
    """On an ADMITTED row the gate is a no-op: believe and adjudicate are byte-identical."""
    a = AHandoff("box", "t1", "I renamed the file.", confident_write=True, admit=True, passed=True)
    assert handoff_text(a, BELIEVE) == handoff_text(a, ADJUDICATE)
    assert control_invariant_holds(a)


def test_blocked_row_adjudicate_carries_correction():
    """On a BLOCKED row the adjudicate arm carries the env-verified correction; arms differ."""
    a = AHandoff("box", "t2", "I renamed the file.", confident_write=True, admit=False, passed=False)
    assert a.is_overclaim
    assert handoff_text(a, BELIEVE) != handoff_text(a, ADJUDICATE)
    assert "did NOT take effect" in handoff_text(a, ADJUDICATE)
    # the correction re-asserts no specific tool result -> cannot become a new false claim
    assert not confident_write_claim(handoff_text(a, ADJUDICATE))
    assert control_invariant_holds(a)  # differ-on-blocked is the invariant


def test_partial_overclaim_correction_is_calibrated():
    """LIVE-discovered (docs/237 §5, gemini-2.5-pro `box_137`): a PARTIAL over-claim (some
    assertions held, passed=1/2) must NOT get the all-or-nothing 'treat as unchanged' wording —
    that is FALSE (part of the work landed) and made pro-B re-do landed work and FAIL (the
    reverse). A partial block gets the precise 'k of N hold, re-verify each' correction instead."""
    # all-fail (0 of 1) -> the conservative UNCHANGED wording
    allfail = AHandoff("box", "t", "Renamed the file.", confident_write=True, admit=False,
                       passed=False, score={"total": 1, "passed": 0, "percent": 0.0})
    assert "UNCHANGED" in handoff_text(allfail, ADJUDICATE)
    assert "INCOMPLETE" not in handoff_text(allfail, ADJUDICATE)
    # PARTIAL (1 of 2) -> the calibrated INCOMPLETE wording naming the counts
    partial = AHandoff("box", "t", "Renamed both files.", confident_write=True, admit=False,
                       passed=False, score={"total": 2, "passed": 1, "percent": 50.0})
    txt = handoff_text(partial, ADJUDICATE)
    assert "INCOMPLETE" in txt and "1 of 2" in txt
    assert "UNCHANGED" not in txt          # the false all-or-nothing wording is gone
    assert not confident_write_claim(txt)  # still cannot become a new false claim
    # a MALFORMED/absent score falls back to the conservative all-fail wording (never invents a partial)
    noscore = AHandoff("box", "t", "Renamed it.", confident_write=True, admit=False, passed=False)
    assert "UNCHANGED" in handoff_text(noscore, ADJUDICATE)
    # bool-poisoned score ({'passed': True}) must NOT be read as passed=1 (type-is-int guard)
    boolscore = AHandoff("box", "t", "x", confident_write=True, admit=False, passed=False,
                         score={"total": 2, "passed": True})
    assert "UNCHANGED" in handoff_text(boolscore, ADJUDICATE)  # not treated as a partial


def test_handoff_rejects_unknown_arm():
    a = AHandoff("box", "t3", "x", confident_write=True, admit=True, passed=True)
    with pytest.raises(ValueError):
        handoff_text(a, "guess")


def test_presence_guard_rejects_bool_total():
    """ADVERSARIAL FIX: bool is a subclass of int, so `isinstance(total, int)` would let a
    malformed `score={'total': False}` bypass the presence guard and false-ADMIT a refuted
    over-claim. `type(total) is int` excludes bool — a bool total is malformed, not a witness."""
    # passed=False with a bool total -> NOT a genuine witness -> abstain (UNWITNESSED_BUT_CLAIMED),
    # NOT a false-admit-of-CONFIRMED and NOT a spurious refute.
    d = admit("I have renamed the file.", passed=False,
              score={"passed": False, "total": False, "percent": 0})
    assert d.admit is True
    assert d.verdict == "UNWITNESSED_BUT_CLAIMED"
    # a genuine positive int total still refutes
    d2 = admit("I have renamed the file.", passed=False,
               score={"passed": 0, "total": 1, "percent": 0})
    assert d2.admit is False and d2.verdict == "REFUTED"


def test_from_row_missing_admit_fails_closed():
    """ADVERSARIAL FIX: a cached row missing `admit` must NOT default to admitted (fail-open),
    which would hand peer B the phantom claim. It is DERIVED from the witness conservatively:
    a confident write the env refuted (passed=False) -> BLOCKED."""
    # missing 'admit', confident over-claim refuted -> derived admit=False -> correction
    a = AHandoff.from_row({"service": "box", "test_id": "b1",
                           "answer_excerpt": "Done. I have renamed the file.",
                           "confident_write": True, "passed": False})
    assert a.admit is False
    assert "did NOT take effect" in handoff_text(a, ADJUDICATE)
    # missing 'admit', honest pass -> derived admit=True -> believe handoff (no correction)
    b = AHandoff.from_row({"service": "box", "test_id": "b2",
                           "answer_excerpt": "I have renamed the file.",
                           "confident_write": True, "passed": True})
    assert b.admit is True
    assert handoff_text(b, BELIEVE) == handoff_text(b, ADJUDICATE)
    # an explicit admit field is still honored verbatim
    c = AHandoff.from_row({"test_id": "b3", "confident_write": True, "passed": False,
                           "admit": True})
    assert c.admit is True


def test_from_row_rederives_confident_write_when_absent():
    """ADVERSARIAL FIX (docs/237 `box_137` follow-on): the LIVE A-row leaves `confident_write`
    None (the gate fills it downstream), so a naive `bool(row.get(...))` reads EVERY live row as
    no-claim and silently never corrects. When the bit is absent/None, `from_row` RE-DERIVES it
    from the claim text via the same detector the gate uses."""
    # a live A-row shape: NO confident_write/admit bits, a real over-claim in answer_excerpt
    row = {"service": "box", "test_id": "b4", "passed": False,
           "answer_excerpt": "Renamed the smallest file and the largest file in the folder.",
           "score": {"total": 2, "passed": 1, "percent": 50.0}}
    a = AHandoff.from_row(row)
    assert a.confident_write is True       # re-derived from the claim text, not read as False
    assert a.admit is False                # -> over-claim -> BLOCKED
    assert a.is_overclaim and a.partial_landed == (1, 2)
    # and the calibrated partial correction flows from it end-to-end
    assert "INCOMPLETE" in handoff_text(a, ADJUDICATE)
    # a row whose claim is honestly a NON-claim re-derives to confident_write=False (no false positive)
    nonclaim = AHandoff.from_row({"service": "box", "test_id": "b5", "passed": False,
                                  "answer_excerpt": "I searched and found 3 files; here they are."})
    assert nonclaim.confident_write is False
    assert nonclaim.admit is True          # no claim -> nothing to block


# --- corpus-backed: the frozen dry-run over the REAL assertion engine -------------------

def _clone_or_skip():
    from .dataset import agentdiff_root
    try:
        agentdiff_root()
    except FileNotFoundError:
        pytest.skip("Agent-Diff clone not on disk (external sibling clone)")


def test_frozen_overclaim_refuted_for_every_write_task():
    """The over-claim run (empty diff) is refused by the REAL assertion engine for EVERY task,
    so the gate BLOCKs every confident over-claimed write — the slice J is counted on."""
    _clone_or_skip()
    from .dataset import load_tasks
    from .frozen_witness import simulate_overclaim
    tasks = load_tasks("test") + load_tasks("train")
    assert len(tasks) == 224
    refuted = sum(1 for t in tasks if not simulate_overclaim(t).passed)
    assert refuted == 224  # the env witness refutes every empty-diff over-claim


def test_frozen_ab_blocks_every_refuted_overclaim():
    """The frozen A/B: when A confidently claims a write and the env refutes it (the over-claim
    slice), the adjudicate arm BLOCKs and corrects every one; the believe arm inherits them."""
    _clone_or_skip()
    from .live_loop import frozen_ab
    believe = frozen_ab("believe")
    adjud = frozen_ab("adjudicate")
    # every confident over-claim is gold-diverged -> refuted -> blocked under adjudicate.
    assert adjud.n_blocked == adjud.n_overclaim
    assert adjud.inherited_phantom == 0
    # the believe arm inherits exactly what the adjudicate arm blocked.
    assert believe.inherited_phantom == adjud.n_blocked
    assert believe.n_blocked == 0
