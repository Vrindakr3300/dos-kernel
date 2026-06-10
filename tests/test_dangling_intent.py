"""DI — the dangling-intent verdict (docs/150, the steelman of docs/149).

`dangling_intent.classify_stop` is the byte-clean DETECTION of the *narrating* premature stopper:
the agent's terminal turn admits an open obligation ("Now I need to allocate personnel…") AND no
env-authored tool result landed after it. PURE — every test hands in a frozen `StopEvidence`
(no LLM, no transcript file), so the verdict is exercised in isolation. These pin the three rungs,
the env-corroborator-wins-first discipline (the non-forgeable byte that kills the named-it-then-
did-it false positive), the against-interest grammar (keys on the first-person-future ENVELOPE,
never a domain noun), the resolved-guard suppression, and the fail-toward-done floor.

The discipline under test is the load-bearing crack in docs/149: a self-report of INCOMPLETENESS
is an admission against interest (the one self-report DOS believes — the resume.py residual rule),
so distrusting it is NOT the §5a mirror-verifier.
"""

from __future__ import annotations

import pytest

from dos import dangling_intent
from dos.dangling_intent import (
    DEFAULT_POLICY,
    Dangling,
    DanglingPolicy,
    DanglingVerdict,
    StopEvidence,
    classify_stop,
)


# A real-shaped terminal narration from the grounded example (docs/150): the agent says it still
# needs to allocate personnel, then stops.
_REAL_DANGLE = (
    'Lumina Healthcare has been successfully set up as an active customer account, and the '
    '"Lumina Implementation Coordination" support group has been created.\n\n'
    'Now, to allocate the appropriate internal personnel, I need to identify a manager and two '
    'non-managers with prior experience in installed base support.'
)


# ---------------------------------------------------------------------------
# 1. The three rungs.
# ---------------------------------------------------------------------------


def test_real_dangling_example_fires():
    """The grounded real stopped-early narration → DANGLING_INTENT, quoting the agent's own cue."""
    v = classify_stop(StopEvidence(final_turn_text=_REAL_DANGLE, results_after_turn=0))
    assert v.verdict is Dangling.DANGLING_INTENT
    assert v.is_dangling
    assert "need to" in v.matched_cue.lower()


def test_clean_done_narration_abstains():
    """A terminal turn with no future-intent marker (a real 'done' report) → ABSTAIN."""
    txt = ('All requested changes have been made: the account is active and the group is created '
           'with the three members assigned.')
    v = classify_stop(StopEvidence(final_turn_text=txt, results_after_turn=0))
    assert v.verdict is Dangling.ABSTAIN
    assert not v.is_dangling


def test_acted_after_the_intent_abstains():
    """THE ENV-AUTHORED CORROBORATOR: the agent named a step AND a tool ran after → ABSTAIN. The
    non-forgeable byte (a result exists only if a tool executed) kills the named-it-then-did-it
    false positive — checked BEFORE the cue, so it wins."""
    v = classify_stop(StopEvidence(final_turn_text=_REAL_DANGLE, results_after_turn=2))
    assert v.verdict is Dangling.ABSTAIN
    assert "landed after" in v.reason


# ---------------------------------------------------------------------------
# 2. The against-interest grammar — keys on the ENVELOPE, never a domain noun.
# ---------------------------------------------------------------------------


def test_various_future_intent_markers_fire():
    for txt in (
        "I still need to assign the members.",
        "Next, I will create the change request.",
        "I was unable to complete the membership step.",
        "The audit row remains to be added.",
    ):
        v = classify_stop(StopEvidence(final_turn_text=txt))
        assert v.verdict is Dangling.DANGLING_INTENT, txt


def test_does_not_fire_on_a_domain_noun_alone():
    """A turn mentioning the domain work but NOT in a first-person-future envelope → ABSTAIN. The
    knife-edge: keying on 'members'/'allocate' as content would be a planner; we never do."""
    txt = "The group now has members and the personnel allocation policy is documented."
    v = classify_stop(StopEvidence(final_turn_text=txt))
    assert v.verdict is Dangling.ABSTAIN


def test_resolved_guard_suppresses_a_completed_report():
    """'I needed to add members, which I have now done' is a COMPLETED report — must not fire."""
    txt = "I needed to add the members, which I have now done successfully."
    v = classify_stop(StopEvidence(final_turn_text=txt))
    assert v.verdict is Dangling.ABSTAIN


def test_task_independence_same_grammar_other_domain():
    """The verdict is invariant under task-swap — the proof it is not a planner. A totally different
    domain with the same envelope fires identically."""
    txt = "I have provisioned the VPC. Now I need to attach the security group and deploy the stack."
    v = classify_stop(StopEvidence(final_turn_text=txt))
    assert v.verdict is Dangling.DANGLING_INTENT


# ---------------------------------------------------------------------------
# 3. The fail-toward-done floor + tail scanning.
# ---------------------------------------------------------------------------


def test_empty_cue_set_abstains_everything():
    """An empty cue set → ABSTAIN-all (the fail-toward-done floor: no cues, no accusation)."""
    pol = DanglingPolicy(cues=())
    v = classify_stop(StopEvidence(final_turn_text=_REAL_DANGLE), pol)
    assert v.verdict is Dangling.ABSTAIN


def test_intent_in_the_middle_then_acts_in_text_is_not_terminal():
    """An open-intent marker far ABOVE the tail window (the turn continued past it) is not a
    *terminal* dangle when tail_chars clips it out — the signal is 'ended ON the admission'."""
    long = ("I need to create the group first. " + "Done. " * 200 +
            "All steps are complete and verified.")
    pol = DanglingPolicy(tail_chars=120)
    v = classify_stop(StopEvidence(final_turn_text=long), pol)
    assert v.verdict is Dangling.ABSTAIN


def test_tail_chars_zero_scans_whole_turn():
    pol = DanglingPolicy(tail_chars=0)
    long = "I need to create the group first. " + "x " * 500
    v = classify_stop(StopEvidence(final_turn_text=long), pol)
    assert v.verdict is Dangling.DANGLING_INTENT


def test_negative_tail_chars_rejected():
    with pytest.raises(ValueError):
        DanglingPolicy(tail_chars=-1)


def test_negative_results_rejected():
    with pytest.raises(ValueError):
        StopEvidence(final_turn_text="x", results_after_turn=-1)


# ---------------------------------------------------------------------------
# 4. The verdict shape.
# ---------------------------------------------------------------------------


def test_to_dict_shape():
    v = classify_stop(StopEvidence(final_turn_text=_REAL_DANGLE))
    d = v.to_dict()
    assert d["verdict"] == "DANGLING_INTENT"
    assert "matched_cue" in d and d["matched_cue"]
    assert "reason" in d


def test_state_enum_round_trips():
    assert str(Dangling.DANGLING_INTENT) == "DANGLING_INTENT"
    assert Dangling("ABSTAIN") is Dangling.ABSTAIN


def test_empty_text_abstains():
    v = classify_stop(StopEvidence(final_turn_text=""))
    assert v.verdict is Dangling.ABSTAIN
