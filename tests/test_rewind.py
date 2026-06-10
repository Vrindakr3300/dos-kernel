"""Tests for `dos.rewind` — the conversation-rewind verdict (docs/164 F1.5).

These pin the four §6 litmus tests for the F1.5 conversation-rewind axis, plus the
intent-ledger checkpoint extension's back-compatibility. Everything here is a PURE
replay test on frozen `TurnRef` / `SuspendCheckpoint` / `FireVerdict` fixtures — no
live loop, no I/O, no network/LLM — the `liveness` / `resume` / `completion` posture.
The fixture idiom mirrors `test_completion.py` (`_state` / `_anc`): small builders
over frozen data, one assertion cluster per litmus.

The four litmus (docs/164 §6):
  (1) Rewind is to a MINTED anchor — `rewind_to_turn == checkpoint.turn_index` ONLY
      when the live turn at that index digests to `checkpoint.transcript_digest`; a
      mismatch (or a missing checkpoint) is UNANCHORED, rewinds to -1.
  (2) The no-good note carries verdict + env bytes, NEVER a generated critique —
      there is no free-form `str` param; an AGENT_AUTHORED excerpt is filtered out;
      an unknown token kind cannot render.
  (3) The loop terminates on GROUND TRUTH — REWIND fires only on DIVERGED /
      THRASHING / STARVED; CONVERGING / RESUMABLE → NO_REWIND.
  (4) Subtraction-only — `dropped_turns` is exactly the indices strictly after the
      anchor; the note's bytes ⊆ (rendered tokens ∪ env excerpt).
"""

from __future__ import annotations

import dataclasses

from dos import rewind as rw
from dos import intent_ledger as il
from dos.rewind import (
    Rewind,
    TurnRef,
    FireVerdict,
    EnvExcerpt,
    NoGoodNote,
    RewindPlan,
    build_no_good_note,
    digest_turn,
    rewind_plan,
)
from dos.intent_ledger import SuspendCheckpoint, LedgerState
from dos.resume import Resume
from dos.completion import Convergence
from dos.log_source import Accountability
from dos.rewind_tokens import (
    VerdictToken,
    BASE_REWIND_TOKENS,
    KIND_DIVERGED,
    KIND_VERIFY_NOT_SHIPPED,
    KIND_TOOL_STREAM_REPEATING,
)


# ── fixtures ────────────────────────────────────────────────────────────────
def _turns(*labels: str) -> tuple[TurnRef, ...]:
    """A transcript as DATA: each turn's index + the kernel's digest of its bytes."""
    return tuple(TurnRef(i, digest_turn(lbl)) for i, lbl in enumerate(labels))


def _checkpoint_at(turns: tuple[TurnRef, ...], idx: int) -> SuspendCheckpoint:
    """A minted checkpoint that MATCHES the live turn at `idx` (a valid anchor)."""
    digest = next(t.digest for t in turns if t.index == idx)
    return SuspendCheckpoint(turn_index=idx, transcript_digest=digest, present=True)


_DIVERGED = FireVerdict.from_resume(Resume.DIVERGED)
_THRASHING = FireVerdict.from_convergence(Convergence.THRASHING)
_STARVED = FireVerdict.from_convergence(Convergence.STARVED)
_CONVERGING = FireVerdict.from_convergence(Convergence.CONVERGING)
_RESUMABLE = FireVerdict.from_resume(Resume.RESUMABLE)


# ══════════════════════════════════════════════════════════════════════════
# Litmus 1 — rewind is to a MINTED anchor, never an agent-claimed turn.
# ══════════════════════════════════════════════════════════════════════════


def test_rewind_target_is_the_minted_checkpoint():
    """A matching checkpoint + a ground-truth fire → REWIND to checkpoint.turn_index."""
    turns = _turns("t0", "t1", "t2", "t3")
    cp = _checkpoint_at(turns, 1)
    plan = rewind_plan(turns, cp, _DIVERGED)
    assert plan.verdict is Rewind.REWIND
    assert plan.rewind_to_turn == cp.turn_index == 1
    # echoed so the consumer truncates to a kernel-stamped anchor.
    assert plan.transcript_digest == cp.transcript_digest


def test_digest_mismatch_is_unanchored_rewinds_to_nothing():
    """A checkpoint whose digest does NOT match the live turn → UNANCHORED, -1.

    The agent (or a successor) rewrote history under the checkpoint; the kernel
    refuses to rewind to a turn it did not stamp."""
    turns = _turns("t0", "t1", "t2")
    bad = SuspendCheckpoint(turn_index=1, transcript_digest=digest_turn("DIFFERENT"),
                            present=True)
    plan = rewind_plan(turns, bad, _DIVERGED)
    assert plan.verdict is Rewind.UNANCHORED
    assert plan.rewind_to_turn == -1
    assert plan.dropped_turns == ()


def test_missing_checkpoint_is_unanchored():
    """No checkpoint minted at SUSPEND → UNANCHORED even with a real stop signal."""
    turns = _turns("t0", "t1")
    plan = rewind_plan(turns, SuspendCheckpoint.absent(), _DIVERGED)
    assert plan.verdict is Rewind.UNANCHORED
    assert plan.rewind_to_turn == -1


def test_checkpoint_index_with_no_live_turn_is_unanchored():
    """A checkpoint naming an index that no live turn occupies → UNANCHORED."""
    turns = _turns("t0", "t1")  # indices 0, 1
    cp = SuspendCheckpoint(turn_index=7, transcript_digest=digest_turn("ghost"),
                           present=True)
    plan = rewind_plan(turns, cp, _DIVERGED)
    assert plan.verdict is Rewind.UNANCHORED
    assert plan.rewind_to_turn == -1


def test_unanchored_still_builds_the_no_good_note():
    """UNANCHORED proposes no truncation but STILL surfaces the verdict+env evidence."""
    turns = _turns("t0", "t1")
    env = EnvExcerpt("Traceback: KeyError", Accountability.OS_RECORDED)
    plan = rewind_plan(turns, SuspendCheckpoint.absent(), _DIVERGED,
                       verdict_tokens=(VerdictToken(KIND_DIVERGED),), env_excerpt=env)
    assert plan.verdict is Rewind.UNANCHORED
    assert plan.no_good_note.env_excerpt is not None
    assert len(plan.no_good_note.tokens) == 1


# ══════════════════════════════════════════════════════════════════════════
# Litmus 2 — the no-good note carries verdict + env bytes, NEVER a critique.
# ══════════════════════════════════════════════════════════════════════════


def test_note_has_no_free_form_str_field():
    """STRUCTURAL: NoGoodNote exposes NO free-form `str` field a caller could fill
    with generated prose. Its only fields are tokens (closed `(kind, payload)`), an
    optional EnvExcerpt, and the registry. This is the §6 lock — the absence is the
    enforcement."""
    str_fields = [
        f.name for f in dataclasses.fields(NoGoodNote)
        if f.type is str or f.type == "str"
    ]
    assert str_fields == [], (
        f"NoGoodNote must carry no free-form str field (found {str_fields}); the "
        f"§6 contract is that the note's only bytes are rendered tokens + a "
        f"floor-gated env excerpt, never a caller-supplied critique"
    )
    # And there is no `critique`/`advice`/`message` field by any name.
    names = {f.name for f in dataclasses.fields(NoGoodNote)}
    assert names == {"tokens", "env_excerpt", "registry"}
    assert not (names & {"critique", "advice", "message", "text", "note", "explanation"})


def test_build_no_good_note_signature_has_no_critique_param():
    """The builder takes ONLY tokens + an env excerpt (+ the registry kw). There is no
    parameter through which model-generated prose could reach a note byte."""
    import inspect
    params = set(inspect.signature(build_no_good_note).parameters)
    assert params == {"tokens", "env_excerpt", "registry"}
    # Same for the verdict function's note-building knobs.
    rp_params = set(inspect.signature(rewind_plan).parameters)
    assert "verdict_tokens" in rp_params and "env_excerpt" in rp_params
    assert not (rp_params & {"critique", "advice", "message", "explanation"})


def test_agent_authored_excerpt_is_filtered_out():
    """An AGENT_AUTHORED excerpt (a generated critique) is STRUCTURALLY filtered — the
    floor's safe-direction no-op (`evidence.believe_under_floor` framing)."""
    critique = EnvExcerpt("you should have used a try/except", Accountability.AGENT_AUTHORED)
    note = build_no_good_note((VerdictToken(KIND_DIVERGED),), critique)
    assert note.env_excerpt is None  # filtered
    # The critique bytes appear NOWHERE in the rendered note.
    rendered = "\n".join(note.render_lines())
    assert "try/except" not in rendered
    assert "you should" not in rendered


def test_os_recorded_and_third_party_excerpts_attach():
    """The F0 env Traceback (env-authored) attaches — both non-forgeable rungs cross
    the floor. The env-excerpt half of the litmus (the `dos_react.py:201` instance)."""
    for rung in (Accountability.OS_RECORDED, Accountability.THIRD_PARTY):
        env = EnvExcerpt("Traceback (most recent call last):\n  KeyError: 'x'", rung)
        note = build_no_good_note((), env)
        assert note.env_excerpt is not None
        assert "Traceback" in "\n".join(note.render_lines())


def test_unknown_token_kind_is_not_renderable():
    """A token whose kind is not in the registry cannot render — it is dropped by the
    builder (so a note never carries un-templated bytes) AND raises if rendered
    directly. A generated critique has no registered kind to ride."""
    bogus = VerdictToken("GENERATED_ADVICE", {"text": "use try/except"})
    # Dropped by the builder (un-renderable → no un-forged bytes).
    note = build_no_good_note((bogus,))
    assert note.tokens == ()
    assert note.render_lines() == ()
    # And rendering it directly through the registry raises (no kernel template).
    import pytest
    with pytest.raises(ValueError):
        BASE_REWIND_TOKENS.render(bogus)


def test_token_renders_from_kernel_template_not_caller_string():
    """A token's bytes come from the registry's KERNEL-owned template over structured
    fields the kernel computed — the agent supplies neither the template nor a field
    sentence (only a sha / count / turn)."""
    t = VerdictToken(KIND_VERIFY_NOT_SHIPPED, {"sha": "abc123"})
    assert BASE_REWIND_TOKENS.render(t) == "verify = NOT_SHIPPED @ abc123"
    t2 = VerdictToken(KIND_TOOL_STREAM_REPEATING, {"count": "4", "turn": "9"})
    assert BASE_REWIND_TOKENS.render(t2) == "tool_stream = REPEATING ×4 @ turn 9"
    # A token payload value that is a sentence is still just SUBSTITUTED into the
    # kernel's template — it cannot replace the template itself.
    assert "NOT_SHIPPED @" in BASE_REWIND_TOKENS.render(
        VerdictToken(KIND_VERIFY_NOT_SHIPPED, {"sha": "anything"})
    )


def test_payload_coerced_to_strings_no_callable_smuggling():
    """A token payload is coerced to str→str — a caller cannot smuggle a callable /
    nested structure into a field slot that a template would __str__ into prose."""
    t = VerdictToken(KIND_VERIFY_NOT_SHIPPED, {"sha": 12345})
    assert t.payload == {"sha": "12345"}
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in t.payload.items())


# ══════════════════════════════════════════════════════════════════════════
# Litmus 3 — the loop terminates on GROUND TRUTH, not a self-report.
# ══════════════════════════════════════════════════════════════════════════


def test_diverged_fires_rewind():
    """`Resume.DIVERGED` (git ancestry moved past the resume point) → REWIND."""
    turns = _turns("t0", "t1", "t2")
    plan = rewind_plan(turns, _checkpoint_at(turns, 0), _DIVERGED)
    assert plan.verdict is Rewind.REWIND


def test_thrashing_and_starved_fire_rewind():
    """`Convergence.THRASHING`/`STARVED` (the residual has no fixpoint) → REWIND."""
    turns = _turns("t0", "t1", "t2")
    cp = _checkpoint_at(turns, 0)
    assert rewind_plan(turns, cp, _THRASHING).verdict is Rewind.REWIND
    assert rewind_plan(turns, cp, _STARVED).verdict is Rewind.REWIND


def test_converging_and_resumable_yield_no_rewind():
    """A NON-stop fire (CONVERGING / RESUMABLE) → NO_REWIND: the loop continues, the
    transcript is untouched. The cap is on the ground-truth verdict, not 'I'm close'."""
    turns = _turns("t0", "t1", "t2")
    cp = _checkpoint_at(turns, 0)
    for fire in (_CONVERGING, _RESUMABLE,
                 FireVerdict.from_convergence(Convergence.INSUFFICIENT),
                 FireVerdict.from_resume(Resume.COMPLETE)):
        plan = rewind_plan(turns, cp, fire)
        assert plan.verdict is Rewind.NO_REWIND, fire
        assert plan.rewind_to_turn == -1


def test_no_rewind_even_with_valid_anchor():
    """A perfectly valid minted anchor does NOT cause a rewind when the fire is not a
    stop signal — the trigger is the ground-truth verdict, never anchor-presence."""
    turns = _turns("t0", "t1")
    cp = _checkpoint_at(turns, 1)  # a perfect anchor
    plan = rewind_plan(turns, cp, _CONVERGING)
    assert plan.verdict is Rewind.NO_REWIND
    # And the note is empty — nothing dead-ended to annotate.
    assert plan.no_good_note.tokens == ()
    assert plan.no_good_note.env_excerpt is None


def test_empty_fire_yields_no_rewind():
    """A FireVerdict with neither signal set is non-firing → NO_REWIND."""
    turns = _turns("t0", "t1")
    plan = rewind_plan(turns, _checkpoint_at(turns, 0), FireVerdict())
    assert plan.verdict is Rewind.NO_REWIND


# ══════════════════════════════════════════════════════════════════════════
# Litmus 4 — subtraction-only (the F1.5-below-F2 property).
# ══════════════════════════════════════════════════════════════════════════


def test_dropped_turns_are_exactly_those_after_the_anchor():
    """`dropped_turns` is EXACTLY the indices strictly after `rewind_to_turn` — pure
    subtraction (removes context, adds none)."""
    turns = _turns("t0", "t1", "t2", "t3", "t4")
    cp = _checkpoint_at(turns, 2)
    plan = rewind_plan(turns, cp, _DIVERGED)
    assert plan.verdict is Rewind.REWIND
    assert plan.dropped_turns == (3, 4)
    # The anchor turn and everything before it are RETAINED (not dropped).
    assert 2 not in plan.dropped_turns
    assert all(i > 2 for i in plan.dropped_turns)


def test_rewind_to_last_turn_drops_nothing():
    """Rewinding to the final turn excises no turns (there is nothing after it)."""
    turns = _turns("t0", "t1", "t2")
    plan = rewind_plan(turns, _checkpoint_at(turns, 2), _DIVERGED)
    assert plan.verdict is Rewind.REWIND
    assert plan.dropped_turns == ()


def test_note_bytes_are_subset_of_tokens_and_env_only():
    """The note's total bytes ⊆ (registry-rendered tokens ∪ env excerpt) — nothing the
    model authored survives the rewind. The subtraction-only invariant, byte-level."""
    turns = _turns("t0", "t1", "t2")
    cp = _checkpoint_at(turns, 0)
    tokens = (VerdictToken(KIND_DIVERGED),
              VerdictToken(KIND_VERIFY_NOT_SHIPPED, {"sha": "facade1"}))
    env = EnvExcerpt("Traceback: ValueError", Accountability.THIRD_PARTY)
    plan = rewind_plan(turns, cp, _DIVERGED, verdict_tokens=tokens, env_excerpt=env)

    lines = plan.no_good_note.render_lines()
    # Every line is either a kernel-rendered token, the kernel header, or the env body.
    rendered_tokens = {BASE_REWIND_TOKENS.render(t) for t in tokens}
    allowed = set(rendered_tokens)
    allowed.add(f"env error excerpt [{env.accountability.value}]:")
    allowed.add(env.text)
    for line in lines:
        assert line in allowed, f"un-accounted note byte: {line!r}"


# ══════════════════════════════════════════════════════════════════════════
# Purity — same inputs → same output (no I/O, no clock, no hidden state).
# ══════════════════════════════════════════════════════════════════════════


def test_verdict_is_pure_deterministic():
    """`rewind_plan` is a pure function: identical inputs → identical output."""
    turns = _turns("t0", "t1", "t2", "t3")
    cp = _checkpoint_at(turns, 1)
    tokens = (VerdictToken(KIND_DIVERGED),)
    env = EnvExcerpt("Traceback", Accountability.OS_RECORDED)
    a = rewind_plan(turns, cp, _DIVERGED, verdict_tokens=tokens, env_excerpt=env)
    b = rewind_plan(turns, cp, _DIVERGED, verdict_tokens=tokens, env_excerpt=env)
    assert a.to_dict() == b.to_dict()
    assert a.verdict is b.verdict
    assert a.dropped_turns == b.dropped_turns


def test_digest_turn_is_stable_and_byte_keyed():
    """The anchor digest is a stable hash of the turn bytes — the kernel is the author
    (str and bytes inputs of the same content agree)."""
    assert digest_turn("hello") == digest_turn(b"hello")
    assert digest_turn("a") != digest_turn("b")
    assert len(digest_turn("x")) == 64  # sha256 hex


def test_plan_to_dict_round_trips_the_shape():
    """`RewindPlan.to_dict` is the --json shape (the `ResumePlan.to_dict` idiom)."""
    turns = _turns("t0", "t1")
    plan = rewind_plan(turns, _checkpoint_at(turns, 0), _DIVERGED,
                       verdict_tokens=(VerdictToken(KIND_DIVERGED),))
    d = plan.to_dict()
    assert d["verdict"] == "REWIND"
    assert d["rewind_to_turn"] == 0
    assert "no_good_note" in d and "lines" in d["no_good_note"]


# ══════════════════════════════════════════════════════════════════════════
# intent_ledger — the checkpoint extension (additive, back-compatible).
# ══════════════════════════════════════════════════════════════════════════


def test_suspend_entry_records_the_conversation_checkpoint():
    """`suspend_entry(checkpoint=...)` writes the two additive fields beside the git
    `resume_sha` — the SAME SUSPEND record carries both axes."""
    cp = SuspendCheckpoint(turn_index=3, transcript_digest=digest_turn("t3"), present=True)
    e = il.suspend_entry(reason="park", resume_sha="deadbeef", checkpoint=cp)
    assert e["checkpoint_turn"] == 3
    assert e["transcript_digest"] == digest_turn("t3")
    # the git axis is byte-for-byte untouched.
    assert e["resume_sha"] == "deadbeef"


def test_suspend_entry_without_checkpoint_writes_no_fields():
    """An OLD-style suspend (no checkpoint) writes neither additive field — a kernel
    too old to know them reads the record back unchanged (back-compat)."""
    e = il.suspend_entry(reason="park", resume_sha="deadbeef")
    assert "checkpoint_turn" not in e
    assert "transcript_digest" not in e


def test_replay_folds_checkpoint_onto_ledger_state():
    """`replay` folds the checkpoint onto `LedgerState.suspend_checkpoint`, leaving the
    git-axis `suspend_resume_sha` byte-for-byte as it was."""
    cp = SuspendCheckpoint(turn_index=2, transcript_digest=digest_turn("t2"), present=True)
    entries = [
        il.intent_entry(goal="g", start_sha="aaaa", declared_steps=["s1", "s2"]),
        il.suspend_entry(reason="park", resume_sha="cafe1234", checkpoint=cp),
    ]
    st = il.replay(entries)
    assert st.suspended is True
    assert st.suspend_checkpoint.present is True
    assert st.suspend_checkpoint.turn_index == 2
    assert st.suspend_checkpoint.transcript_digest == digest_turn("t2")
    # git axis still reads its own field.
    assert st.suspend_resume_sha == "cafe1234"


def test_replay_old_suspend_folds_to_absent_checkpoint():
    """An older kernel's SUSPEND (no checkpoint fields) folds to an ABSENT checkpoint —
    never a guessed one. The additive-evolution zero."""
    entries = [
        il.intent_entry(goal="g", start_sha="aaaa", declared_steps=["s1"]),
        il.suspend_entry(reason="park", resume_sha="cafe1234"),  # no checkpoint
    ]
    st = il.replay(entries)
    assert st.suspended is True
    assert st.suspend_checkpoint.present is False
    assert st.suspend_checkpoint.turn_index == -1


def test_default_ledger_state_has_absent_checkpoint():
    """A LedgerState with no SUSPEND has an absent checkpoint (the honest default)."""
    st = LedgerState(run_id="RID")
    assert st.suspend_checkpoint.present is False


def test_fresh_intent_clears_a_prior_checkpoint():
    """A later INTENT re-opens a parked run — it clears `suspend_checkpoint` exactly as
    it clears `suspended` / `suspend_resume_sha` (the run is live again)."""
    cp = SuspendCheckpoint(turn_index=1, transcript_digest=digest_turn("t1"), present=True)
    entries = [
        il.intent_entry(goal="g", start_sha="aaaa", declared_steps=["s1"]),
        il.suspend_entry(reason="park", resume_sha="cafe", checkpoint=cp),
        il.intent_entry(goal="g2", start_sha="bbbb", declared_steps=["s1"]),  # re-open
    ]
    st = il.replay(entries)
    assert st.suspended is False
    assert st.suspend_checkpoint.present is False


def test_schema_version_unchanged_by_the_additive_field():
    """The checkpoint extension is ADDITIVE — `INTENT_LEDGER_SCHEMA` stays 1."""
    assert il.INTENT_LEDGER_SCHEMA == 1
    cp = SuspendCheckpoint(turn_index=0, transcript_digest=digest_turn("t0"), present=True)
    e = il.suspend_entry(checkpoint=cp)
    assert e["schema"]["version"] == 1


def test_checkpoint_from_record_tolerates_missing_and_malformed_turn():
    """`SuspendCheckpoint.from_record` is tolerant: no digest → absent; a malformed
    turn index with a real digest degrades the index to -1 but keeps the anchor."""
    assert SuspendCheckpoint.from_record({}).present is False
    assert SuspendCheckpoint.from_record({"checkpoint_turn": 5}).present is False  # no digest
    cp = SuspendCheckpoint.from_record({"checkpoint_turn": "not-an-int",
                                        "transcript_digest": "abc"})
    assert cp.present is True
    assert cp.turn_index == -1
    assert cp.transcript_digest == "abc"
