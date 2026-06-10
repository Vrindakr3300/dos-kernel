"""Tests for dos.intervention — the typed actuation ladder + confidence gating (docs/143 §13).

PURE: every test hands in a frozen `ProvenanceVerdict` (or builds a ladder/policy) directly
and reads a `choose_intervention` decision back — no LLM, no MCP, no consumer. The contract:

  * the ladder is a CLOSED, strictly-ordered set (dup token AND dup rank both raise);
  * the cost order is OBSERVE < WARN < BLOCK < DEFER — BLOCK below DEFER because BLOCK
    PRESERVES the turn (the measured −9pp lesson; this supersedes §13.1's prose order);
  * `actuates()` reads the `dispatches` DATA (a host rung is bucketed by data, not name);
  * confidence keys on the (len(checked)==1 and len(unmatched)==1) scalar shape; everything
    else (composite / container / one-of-many-missing) is LOW — the safe under-intervene
    direction; `matched_in` is NOT read (it is grammar-polluted);
  * the policy rejects every inverted / dead-letter combination at construction (refuse-
    LESS-only is structural);
  * a clean (believe=True) call is OBSERVE, NOT floored up to a spurious WARN;
  * the synthetic corrective result carries `dos_blocked` and never leaks the raw minted
    value as a top-level field (the anti-laundering shape).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dos.arg_provenance import (
    ArgProvenance,
    CorpusSource,
    ProvenanceStance,
    ProvenanceVerdict,
)
from dos.intervention import (
    BASE_INTERVENTIONS as L,
    DEFAULT_POLICY,
    Confidence,
    Intervention,
    InterventionDecision,
    InterventionLadder,
    InterventionPolicy,
    InterventionSpec,
    assess_confidence,
    choose_intervention,
    load_from_toml,
    specs_from_table,
    synthetic_corrective_result,
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _arg(name, stance, checked, unmatched, matched_in=()):
    return ArgProvenance(
        arg_name=name, value_repr="x", stance=stance, id_shaped=True, is_reference=True,
        matched_in=tuple(matched_in), components_checked=tuple(checked),
        components_unmatched=tuple(unmatched), reason="",
    )


def _verdict(args, believe=None, unsupported=None):
    if unsupported is None:
        unsupported = tuple(a.arg_name for a in args if a.stance is ProvenanceStance.UNSUPPORTED)
    if believe is None:
        believe = not unsupported
    return ProvenanceVerdict(believe=believe, args=tuple(args),
                             unsupported=tuple(unsupported), reason="")


def _high_verdict():
    """A whole-value-absent scalar mint (one component, unmatched) → HIGH."""
    return _verdict([_arg("parent", ProvenanceStance.UNSUPPORTED, ("9999999",), ("9999999",))])


def _low_verdict():
    """A composite where one of two components missed → LOW."""
    return _verdict([_arg("ref", ProvenanceStance.UNSUPPORTED,
                          ("0010023", "acme"), ("acme",), matched_in=(CorpusSource.TOOL_RESULT,))])


def _clean_verdict():
    return ProvenanceVerdict(believe=True, args=(), unsupported=(), reason="")


# ── the vocabulary + the ladder ───────────────────────────────────────────────
def test_intervention_members_str_valued_and_round_trip():
    # str-valued so a CLI token / JSON / env var round-trips without a lookup table.
    for member in (Intervention.OBSERVE, Intervention.WARN, Intervention.BLOCK, Intervention.DEFER):
        assert isinstance(member, str)
        assert member.value == member.name
        assert str(member) == member.value
        assert Intervention(member.value) is member


def test_confidence_members_str_valued_and_round_trip():
    for member in (Confidence.HIGH, Confidence.LOW, Confidence.NONE):
        assert isinstance(member, str)
        assert str(member) == member.value
        assert Confidence(member.value) is member


def test_intervention_str_roundtrip():
    assert str(Intervention.WARN) == "WARN"
    assert L.get("warn") is L.get(Intervention.WARN)
    assert L.get("warn").key == "WARN"


def test_base_ladder_four_rungs_expected_ranks():
    # Ranks gapped by 10 so a host can insert a custom rung between any two.
    assert L.rank_of("OBSERVE") == 0
    assert L.rank_of("WARN") == 10
    assert L.rank_of("BLOCK") == 20
    assert L.rank_of("DEFER") == 30
    assert set(L.tokens()) == {"OBSERVE", "WARN", "BLOCK", "DEFER"}


# ── InterventionSpec.__post_init__ guards ───────────────────────────────────────
def test_spec_empty_token_raises():
    with pytest.raises(ValueError, match="non-empty"):
        InterventionSpec("", rank=0, summary="", actuation="", dispatches=True)
    with pytest.raises(ValueError, match="non-empty"):
        InterventionSpec("   ", rank=0, summary="", actuation="", dispatches=True)


def test_spec_negative_rank_raises():
    with pytest.raises(ValueError, match="rank must be >= 0"):
        InterventionSpec("X", rank=-1, summary="", actuation="", dispatches=True)


def test_spec_returns_synthetic_with_dispatches_true_raises():
    # returns_synthetic means the real call was WITHHELD + replaced, so it cannot also
    # dispatch — the contradiction is rejected at construction.
    with pytest.raises(ValueError, match="dispatches must be False"):
        InterventionSpec("X", rank=5, summary="", actuation="", dispatches=True,
                         returns_synthetic=True)


def test_spec_key_normalizes_case_and_whitespace():
    assert InterventionSpec("  warn  ", rank=5, summary="", actuation="", dispatches=True).key == "WARN"


def test_ladder_closed_set_dup_token_raises():
    with pytest.raises(ValueError):
        L.extend([InterventionSpec("WARN", rank=99, summary="", actuation="", dispatches=True)])


def test_ladder_dup_rank_raises():
    with pytest.raises(ValueError):
        InterventionLadder(specs=(
            InterventionSpec("A", rank=5, summary="", actuation="", dispatches=True),
            InterventionSpec("B", rank=5, summary="", actuation="", dispatches=True),
        ), default_token="A")


def test_ladder_default_unknown_raises():
    with pytest.raises(ValueError):
        InterventionLadder(specs=(
            InterventionSpec("A", rank=0, summary="", actuation="", dispatches=True),
        ), default_token="NOPE")


def test_extend_returns_new_ladder_original_unchanged():
    # extend() is the one way to add a rung; the original is a value, never mutated.
    extended = L.extend([InterventionSpec("NUDGE", rank=15, summary="s", actuation="a", dispatches=True)])
    assert extended is not L
    assert "NUDGE" in extended.tokens()
    assert "NUDGE" not in L.tokens()
    assert set(L.tokens()) == {"OBSERVE", "WARN", "BLOCK", "DEFER"}


def test_extend_colliding_rank_raises():
    with pytest.raises(ValueError):
        L.extend([InterventionSpec("NUDGE", rank=10, summary="", actuation="", dispatches=True)])


def test_by_rank_strictly_increasing():
    ordered = L.by_rank()
    ranks = [s.rank for s in ordered]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert [s.key for s in ordered] == ["OBSERVE", "WARN", "BLOCK", "DEFER"]


def test_block_cheaper_than_defer():
    """Pins the measured-order-supersedes-§13.1 decision so a later editor does not revert it.
    BLOCK preserves the turn; DEFER spends it (the live −9pp), so BLOCK ranks below DEFER."""
    assert L.rank_of("BLOCK") < L.rank_of("DEFER")
    assert L.disruption_cost("BLOCK") < L.disruption_cost("DEFER")


def test_escalate_deescalate_clamped():
    assert L.escalate("BLOCK").key == "DEFER"
    assert L.escalate("DEFER").key == "DEFER"          # top clamp
    assert L.de_escalate("OBSERVE").key == "OBSERVE"   # bottom clamp
    assert L.de_escalate("DEFER").key == "BLOCK"


def test_clamp_into_window():
    # DEFER clamped into [WARN, BLOCK] lands on the ceiling; OBSERVE rises to the floor;
    # an in-window rung is unchanged.
    assert L.clamp("DEFER", floor="WARN", ceiling="BLOCK").key == "BLOCK"
    assert L.clamp("OBSERVE", floor="WARN", ceiling="BLOCK").key == "WARN"
    assert L.clamp("WARN", floor="WARN", ceiling="BLOCK").key == "WARN"


def test_clamp_inverted_picks_ceiling():
    """An inverted window (floor more disruptive than ceiling) fails toward LESS disruptive."""
    assert L.clamp("DEFER", floor="WARN", ceiling="OBSERVE").key == "OBSERVE"
    assert L.clamp("DEFER", floor="BLOCK", ceiling="OBSERVE").key == "OBSERVE"


def test_dispatches_synthetic_coherence():
    for s in L.specs:
        if s.returns_synthetic:
            assert not s.dispatches, f"{s.key}: returns_synthetic must imply not dispatches"
    assert L.get("BLOCK").returns_synthetic is True
    assert sum(1 for s in L.specs if s.returns_synthetic) == 1   # exactly BLOCK
    assert L.get("OBSERVE").dispatches and L.get("WARN").dispatches
    assert not L.get("DEFER").dispatches and not L.get("BLOCK").dispatches


def test_actuates_is_data_driven():
    assert L.actuates("DEFER") and L.actuates("BLOCK")
    assert not L.actuates("WARN") and not L.actuates("OBSERVE")
    # a host-added rung is bucketed by its `dispatches` DATA, not its name
    host = L.extend([InterventionSpec("QUARANTINE", rank=25, summary="", actuation="",
                                      dispatches=False)])
    assert host.actuates("QUARANTINE") is True
    host2 = L.extend([InterventionSpec("ANNOTATE", rank=5, summary="", actuation="",
                                       dispatches=True)])
    assert host2.actuates("ANNOTATE") is False


def test_disruption_cost_normalized():
    assert L.disruption_cost("OBSERVE") == 0.0
    assert L.disruption_cost("DEFER") == 1.0
    costs = [L.disruption_cost(s.key) for s in L.by_rank()]
    assert costs == sorted(costs)   # monotone in rank
    assert costs == [0.0, 10 / 30, 20 / 30, 30 / 30]


def test_disruption_cost_unnormalized_is_raw_rank():
    assert L.disruption_cost("WARN", normalized=False) == 10.0
    assert L.disruption_cost("DEFER", normalized=False) == 30.0


def test_returns_synthetic_helper():
    assert L.returns_synthetic("BLOCK") is True
    for t in ("OBSERVE", "WARN", "DEFER"):
        assert L.returns_synthetic(t) is False


def test_unknown_token_dispatches_false_actuates_true_conservative():
    # An unknown rung withholds the call (the reasons.is_refusal fail-closed analogue):
    # dispatches False, actuates True, returns_synthetic False — conservative by construction.
    assert L.dispatches("MYSTERY") is False
    assert L.actuates("MYSTERY") is True
    assert L.returns_synthetic("MYSTERY") is False


def test_default_is_warn_and_informs():
    assert L.default().token == "WARN"
    assert L.default().dispatches is True


def test_rank_of_unknown_raises():
    with pytest.raises(KeyError):
        L.rank_of("NOPE")


# ── confidence extraction ──────────────────────────────────────────────────────
def test_assess_confidence_high_scalar():
    assert assess_confidence(_high_verdict()) is Confidence.HIGH


def test_assess_confidence_low_composite():
    assert assess_confidence(_low_verdict()) is Confidence.LOW


def test_assess_confidence_container_is_low():
    """A container/multi-component arg (3+ checked, the cross-leaf superset) → LOW (the safe
    direction; we cannot prove whole-value absence from a superset)."""
    v = _verdict([_arg("payload", ProvenanceStance.UNSUPPORTED,
                       ("a1", "b2", "c3"), ("a1", "b2", "c3"))])
    assert assess_confidence(v) is Confidence.LOW


def test_assess_confidence_one_element_container_reads_high():
    """A DEGENERATE one-element container collapses to the single-component scalar shape
    (the verdict does not preserve scalar-vs-1-list), and IS a whole-value mint → HIGH. The
    adversarial-review BUG-3 resolution: the logic is correct (HIGH→BLOCK is the turn-
    preserving escalation), the docstring was the thing that overclaimed 'container → LOW'."""
    v = _verdict([_arg("parents", ProvenanceStance.UNSUPPORTED, ("9999999",), ("9999999",))])
    assert assess_confidence(v) is Confidence.HIGH


def test_assess_confidence_none_on_believe():
    assert assess_confidence(_clean_verdict()) is Confidence.NONE


def test_assess_confidence_none_on_empty_unsupported_even_if_not_believe():
    # The NONE branch fires on `believe OR not unsupported` — an empty unsupported tuple
    # means nothing was minted, so OBSERVE-only regardless of the believe flag.
    v = ProvenanceVerdict(believe=False, args=(), unsupported=(), reason="no minted arg")
    assert assess_confidence(v) is Confidence.NONE


def test_assess_confidence_supported_args_do_not_count_toward_high():
    # Only UNSUPPORTED args are inspected; a SUPPORTED scalar is skipped, so a verdict whose
    # only FIRED arg is LOW stays LOW (the SUPPORTED scalar must not falsely mint HIGH).
    supported = _arg("ok", ProvenanceStance.SUPPORTED, ("0010023",), ())
    low = _arg("ref", ProvenanceStance.UNSUPPORTED, ("0010023", "acme"), ("acme",))
    assert assess_confidence(_verdict([supported, low])) is Confidence.LOW


def test_assess_confidence_matched_in_irrelevant():
    """A HIGH-shape arg with NON-EMPTY matched_in (grammar pollution) STILL reads HIGH — the
    `not matched_in` conjunct was dropped, else HIGH would never fire."""
    v = _verdict([_arg("parent", ProvenanceStance.UNSUPPORTED, ("9999999",), ("9999999",),
                       matched_in=(CorpusSource.TOOL_RESULT,))])
    assert assess_confidence(v) is Confidence.HIGH


def test_assess_confidence_any_high_arg_makes_call_high():
    """Multi-arg aggregation: one HIGH arg + one LOW arg → HIGH (escalate to the strongest)."""
    high = _arg("parent", ProvenanceStance.UNSUPPORTED, ("9999999",), ("9999999",))
    low = _arg("ref", ProvenanceStance.UNSUPPORTED, ("0010023", "acme"), ("acme",))
    assert assess_confidence(_verdict([high, low])) is Confidence.HIGH
    # order-independent: a single HIGH arg anywhere escalates the whole call.
    assert assess_confidence(_verdict([low, high])) is Confidence.HIGH


# ── the policy validation (refuse-LESS-only is structural) ──────────────────────
def test_policy_rejects_inverted_low_high():
    with pytest.raises(ValueError):
        InterventionPolicy(on_high_confidence="WARN", on_low_confidence="BLOCK")


def test_policy_rejects_none_over_low():
    with pytest.raises(ValueError):
        InterventionPolicy(on_none="BLOCK", on_low_confidence="WARN")


def test_policy_rejects_floor_over_ceiling():
    with pytest.raises(ValueError):
        InterventionPolicy(floor="DEFER", ceiling="WARN")


def test_policy_rejects_floor_over_on_low_confidence():
    """BUG-1 (adversarial review): a `floor` more disruptive than `on_low_confidence` would
    silently escalate a LOW mint past its declared rung via the clamp — refuse-LESS-only's
    floor axis. Must be rejected at construction."""
    with pytest.raises(ValueError, match="floor"):
        InterventionPolicy(on_high_confidence="BLOCK", on_low_confidence="WARN",
                           floor="BLOCK", ceiling="BLOCK")


def test_floor_never_escalates_a_low_verdict_past_its_rung():
    """The behavioral counterpart of the above: with a valid policy, a LOW verdict resolves to
    `on_low_confidence`, NOT floored up — the floor is a genuine lower bound, never an
    escalator (the BUG-1 guarantee, end-to-end through choose_intervention)."""
    low = _low_verdict()
    d = choose_intervention(low, InterventionPolicy())  # floor=WARN, on_low=WARN
    assert d.intervention is Intervention.WARN
    assert L.rank_of(d.intervention.value) <= L.rank_of("WARN")


def test_policy_rejects_dead_letter_rung():
    with pytest.raises(ValueError):
        InterventionPolicy(on_high_confidence="DEFER", ceiling="BLOCK")


def test_policy_rejects_unknown_rung():
    with pytest.raises(ValueError):
        InterventionPolicy(on_high_confidence="NOPE")


def test_default_policy_constructs():
    p = InterventionPolicy()
    assert (p.on_high_confidence, p.on_low_confidence, p.on_none) == ("BLOCK", "WARN", "OBSERVE")
    assert (p.floor, p.ceiling) == ("WARN", "BLOCK")
    assert DEFAULT_POLICY == p


def test_policy_valid_escalated_constructs():
    # The opt-in turn-spending posture: raise the ceiling to DEFER and map a high-confidence
    # mint onto it. A VALID, deliberately-disruptive policy.
    p = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="WARN",
                           on_none="OBSERVE", floor="WARN", ceiling="DEFER")
    assert p.ceiling == "DEFER" and p.on_high_confidence == "DEFER"


# ── choose_intervention (the confidence-gated map) ──────────────────────────────
def test_choose_high_confidence_blocks():
    d = choose_intervention(_high_verdict())
    assert d.intervention is Intervention.BLOCK and d.confidence is Confidence.HIGH


def test_choose_low_confidence_warns():
    d = choose_intervention(_low_verdict())
    assert d.intervention is Intervention.WARN and d.confidence is Confidence.LOW


def test_choose_none_is_observe_not_floored():
    """A believe=True call → OBSERVE, NOT floored up to a spurious WARN (the clean-call fix)."""
    d = choose_intervention(_clean_verdict())
    assert d.intervention is Intervention.OBSERVE and d.confidence is Confidence.NONE


def test_choose_defer_only_when_ceiling_raised():
    """DEFER is unreachable under the default ceiling=BLOCK; opt-in by raising the ceiling."""
    assert choose_intervention(_high_verdict()).intervention is not Intervention.DEFER
    opt_in = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="WARN",
                                ceiling="DEFER")
    assert choose_intervention(_high_verdict(), opt_in).intervention is Intervention.DEFER


def test_choose_high_under_raised_ceiling_is_defer_with_high_confidence():
    # With the ceiling raised to DEFER and on_high=DEFER, a HIGH mint reaches the
    # turn-spending rung — carrying the right confidence.
    opt_in = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="WARN",
                                ceiling="DEFER")
    d = choose_intervention(_high_verdict(), opt_in)
    assert d.intervention is Intervention.DEFER and d.confidence is Confidence.HIGH


def test_choose_decision_carries_confidence_unsupported_and_cost():
    d = choose_intervention(_high_verdict())
    assert isinstance(d, InterventionDecision)
    assert d.confidence is Confidence.HIGH
    assert d.unsupported == ("parent",)
    assert d.disruption_cost == L.disruption_cost("BLOCK")   # matches ladder arithmetic
    assert d.rung.key == "BLOCK"


def test_choose_low_decision_cost_matches_warn():
    assert choose_intervention(_low_verdict()).disruption_cost == L.disruption_cost("WARN")


# ── refuse-LESS-only is enforced on the ACTUAL ladder, not just BASE (docs/144 review) ──
def _reordered_ladder():
    """A rank-reordered ladder where BLOCK(5) ranks BELOW WARN(10) — the adversarial shape.

    Admitted by InterventionLadder.__post_init__ (unique tokens + unique ranks); it only
    reorders the relative cost of named base rungs, which the ladder validation does not
    forbid. This is the ladder the docs/144 adversarial review passed as choose_intervention's
    third arg to void the construction-time order check.
    """
    return InterventionLadder(default_token="WARN", specs=(
        InterventionSpec("OBSERVE", 0, "", "", dispatches=True),
        InterventionSpec("BLOCK", 5, "", "", dispatches=False, returns_synthetic=True),
        InterventionSpec("WARN", 10, "", "", dispatches=True),
        InterventionSpec("DEFER", 30, "", "", dispatches=False),
    ))


def test_policy_validate_against_rejects_reordered_ladder():
    """A policy valid on BASE is REJECTED by validate_against on a ladder that reorders it.

    On BASE, on_high=BLOCK(20) >= on_low=WARN(10) is fine; on the reordered ladder
    BLOCK(5) < WARN(10), so on_low=WARN is now MORE disruptive than on_high=BLOCK —
    refuse-LESS-only is violated and validate_against must raise (the second, load-bearing
    check the construction-time one cannot perform)."""
    policy = InterventionPolicy(on_high_confidence="BLOCK", on_low_confidence="WARN",
                                on_none="OBSERVE", floor="OBSERVE", ceiling="DEFER")
    policy.validate_against(L)  # safe on BASE — no raise
    with pytest.raises(ValueError, match="refuse-LESS-only"):
        policy.validate_against(_reordered_ladder())


def test_choose_intervention_fails_safe_on_reordered_ladder():
    """THE CLOSED HOLE (docs/144 adversarial review, severity medium): a rank-reordered ladder
    passed as choose_intervention's third arg must NOT let a LOW mint resolve harder than a
    HIGH one. choose_intervention re-validates the policy against the ACTUAL ladder and, on a
    refuse-LESS-only break, degrades to the ladder default (advisory-never-raise) — so the
    guarantee holds for the ladder IN USE, not merely for BASE."""
    adv = _reordered_ladder()
    policy = InterventionPolicy(on_high_confidence="BLOCK", on_low_confidence="WARN",
                                on_none="OBSERVE", floor="OBSERVE", ceiling="DEFER")
    hd = choose_intervention(_high_verdict(), policy, ladder=adv)
    ld = choose_intervention(_low_verdict(), policy, ladder=adv)
    # the invariant on the ACTUAL ladder: LOW is never more disruptive than HIGH.
    assert adv.rank_of(ld.rung.key) <= adv.rank_of(hd.rung.key)
    # both degrade to the ladder default (WARN), and say WHY (fail-safe, not a silent escalate).
    assert hd.rung.key == "WARN" and ld.rung.key == "WARN"
    assert "fail-safe" in hd.reason and "fail-safe" in ld.reason


def test_choose_intervention_safe_ladder_unaffected_by_the_fix():
    """The fix is a no-op on a well-ordered ladder: BASE still gives HIGH→BLOCK, LOW→WARN."""
    assert choose_intervention(_high_verdict()).rung.key == "BLOCK"
    assert choose_intervention(_low_verdict()).rung.key == "WARN"


def test_choose_decision_to_dict():
    d = choose_intervention(_high_verdict())
    out = d.to_dict()
    assert out["intervention"] == "BLOCK" and out["confidence"] == "HIGH"
    assert out["rung"] == "BLOCK"
    assert out["dispatches"] is False and out["returns_synthetic"] is True
    assert out["unsupported"] == ["parent"]
    assert out["disruption_cost"] == round(L.disruption_cost("BLOCK"), 4)
    assert isinstance(out["reason"], str) and out["reason"]


# ── the synthetic corrective result (#4a; anti-laundering) ───────────────────────
def test_synthetic_result_no_raw_value_leak():
    """The payload carries dos_blocked, status==blocked_unresolved_id, reports unresolved by
    arg-NAME + unresolved COMPONENT tokens, includes the read-tool hint, and never echoes the
    raw minted VALUE as a standalone top-level field (the §13.4 / §5a anti-laundering shape —
    otherwise a BLOCK'd id would re-enter the corpus and teach the detector to TRUST the very
    id it blocked)."""
    v = _high_verdict()
    sr = synthetic_corrective_result(v, "create_incident", read_tool_hint="get_incident")
    assert sr["dos_blocked"] is True
    assert sr["status"] == "blocked_unresolved_id"
    assert sr["unresolved"] == [{"arg": "parent", "unresolved_components": ["9999999"]}]
    assert "create_incident" in sr["error"] and "create_incident" in sr["remediation"]
    assert "get_incident" in sr["remediation"]   # the read-tool hint path is included
    # ANTI-LAUNDERING: no standalone top-level field equals the raw minted value, and the
    # value never appears as a top-level KEY (which a corpus harvester would flatten in).
    minted = "9999999"
    for k, val in sr.items():
        if k == "unresolved":
            continue  # the value is ALLOWED inside the unresolved-components prose only
        assert val != minted, f"top-level field {k!r} leaks the minted id verbatim"
        assert k != minted, "the minted id appears as a top-level KEY (corpus-bindable)"
    assert "value_repr" not in sr
    assert sr.get("id") != minted and sr.get("value") != minted


def test_synthetic_result_no_hint_omits_parenthetical():
    sr = synthetic_corrective_result(_high_verdict(), "create_incident")
    # with no hint, the remediation does not dangle an empty "(e.g. )" clause
    assert "(e.g." not in sr["remediation"]


def test_synthetic_result_only_unsupported_args_summarized():
    # a SUPPORTED arg alongside an UNSUPPORTED one is NOT listed — the corrective targets the
    # minted id only, never the good one.
    supported = _arg("caller_id", ProvenanceStance.SUPPORTED, ("0010023",), ())
    v = ProvenanceVerdict(believe=False, unsupported=("parent",), reason="mixed",
                          args=(supported, _high_verdict().args[0]))
    sr = synthetic_corrective_result(v, "create_incident")
    assert [m["arg"] for m in sr["unresolved"]] == ["parent"]


def test_synthetic_result_is_pure_dict():
    v = _high_verdict()
    a = synthetic_corrective_result(v, "t")
    b = synthetic_corrective_result(v, "t")
    assert isinstance(a, dict) and a == b   # deterministic, no I/O


# ── the dos.toml on-ramp ────────────────────────────────────────────────────────
def test_toml_on_ramp_absent_returns_base(tmp_path):
    assert load_from_toml(tmp_path / "nope.toml") is L


def test_toml_on_ramp_no_table_returns_base(tmp_path):
    p = tmp_path / "dos.toml"
    p.write_text("[reasons]\n", encoding="utf-8")
    assert load_from_toml(p) is L


def test_specs_from_table_missing_rank_raises():
    with pytest.raises(ValueError, match="missing required `rank`"):
        specs_from_table({"NUDGE": {"summary": "no rank here"}})


def test_specs_from_table_non_table_body_raises():
    with pytest.raises(ValueError, match="must be a table"):
        specs_from_table({"NUDGE": "not a table"})


def test_toml_on_ramp_valid_extends(tmp_path):
    p = tmp_path / "dos.toml"
    p.write_text(
        "[intervention.QUARANTINE]\nrank = 25\nsummary = \"hold\"\n"
        "actuation = \"sideline\"\ndispatches = false\n",
        encoding="utf-8",
    )
    ladder = load_from_toml(p)
    assert ladder.is_known("QUARANTINE")
    assert ladder.actuates("QUARANTINE") is True          # dispatches=false → actuates
    assert ladder.rank_of("QUARANTINE") == 25
    assert {"OBSERVE", "WARN", "BLOCK", "DEFER"} <= set(ladder.tokens())
    # it slots between BLOCK and DEFER by rank
    assert [s.key for s in ladder.by_rank()] == ["OBSERVE", "WARN", "BLOCK", "QUARANTINE", "DEFER"]


def test_toml_on_ramp_malformed_raises(tmp_path):
    p = tmp_path / "dos.toml"
    p.write_text("[intervention.BAD]\nsummary = \"no rank\"\n", encoding="utf-8")  # missing rank
    with pytest.raises(ValueError):
        load_from_toml(p)


def test_toml_on_ramp_colliding_rank_raises(tmp_path):
    # A rung re-using a base rank trips the ladder's strict-total-order guard at LOAD — a
    # malformed declaration fails loudly, not silently.
    p = tmp_path / "dos.toml"
    p.write_text("[intervention.NUDGE]\nrank = 10\n", encoding="utf-8")  # 10 collides with WARN
    with pytest.raises(ValueError):
        load_from_toml(p)


def test_toml_on_ramp_bom_written_file_is_read(tmp_path):
    # utf-8-sig strips a PowerShell-written BOM (the reasons.load_from_toml fix).
    p = tmp_path / "dos.toml"
    p.write_text("[intervention.NUDGE]\nrank = 15\n", encoding="utf-8-sig")
    assert load_from_toml(p).is_known("NUDGE")


# ── the layering litmus (kernel imports no host/driver/consumer) ─────────────────
def test_layer_litmus_no_host_import():
    """The kernel imports no host/driver/consumer. Checks IMPORT lines only — the module
    docstring legitimately NAMES `dos_react`/`enterpriseops` as the example consumer (that is
    the doctrine being explained), so a prose mention is fine; an actual import is not."""
    src = Path(__file__).resolve().parents[1] / "src" / "dos" / "intervention.py"
    import_lines = [
        ln for ln in src.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith(("import ", "from ")) and "import" in ln
    ]
    blob = "\n".join(import_lines)
    for forbidden in ("dos.drivers", "drivers", "job", "dos_react", "dos_mcp",
                      "scripts", "enterpriseops", "overlap", "judge"):
        assert forbidden not in blob, f"intervention.py imports must not name {forbidden!r}"
    # the only dos-internal import is dos.arg_provenance (a sibling kernel module)
    assert "from dos.arg_provenance import" in blob
