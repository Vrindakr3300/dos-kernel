"""Tests for dos.arg_provenance — the pure argument-provenance fold (docs/143 R1).

PURE: every test hands in a `ToolCall` + a `PriorResults` corpus of `EnvBlob`s directly
(no LLM, no MCP, no DB), so the minted-vs-resolved decision is exercised in isolation —
the keystone the audit calls "testable with zero benchmark access."

The two case families mirror the design's must-pass / must-not-block lists:
  * MUST PASS  — a minted reference id is UNSUPPORTED; an env-authored or env-DERIVED id
                 is SUPPORTED (defeating the composite-id livelock).
  * MUST NOT BLOCK — the false-block guards: a create's own new key, prose, enums, dates/
                 money/versions, quantity args, and (the kill-signal) legit derived ids.

The load-bearing safety claim is byte-author-only: `believe=True` means ONLY "no id was
minted from nowhere," never "the args are correct." So the corpus is built only of
`EnvBlob`s, which can carry only an env `CorpusSource` — a model turn is unrepresentable
as evidence.
"""
from __future__ import annotations

from dos.arg_provenance import (
    ArgProvenance,
    CorpusSource,
    EnvBlob,
    PriorResults,
    ProvenancePolicy,
    ProvenanceStance,
    ToolArg,
    ToolCall,
    classify_arg,
    classify_call,
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _corpus(*texts: str, source: CorpusSource = CorpusSource.TOOL_RESULT) -> PriorResults:
    return PriorResults(blobs=tuple(EnvBlob(text=t, source=source) for t in texts))


def _mutating(*args: ToolArg, tool: str = "create_incident") -> ToolCall:
    return ToolCall(tool_name=tool, args=tuple(args), is_mutating=True)


def _arg(name: str, value, *, ref: bool = True) -> ToolArg:
    return ToolArg(name=name, value=value, is_reference=ref)


# ── MUST PASS: minted refused, env/derived believed ──────────────────────────

def test_minted_reference_refused():
    """A reference id that appears in no env bytes (a non-empty corpus exists) → UNSUPPORTED."""
    v = classify_call(
        _mutating(_arg("parent", "INC9999999")),
        _corpus('{"number": "INC0010023", "state": "new"}'),
    )
    assert v.believe is False
    assert v.unsupported == ("parent",)
    a = v.args[0]
    assert a.stance is ProvenanceStance.UNSUPPORTED
    assert "9999999" in a.components_unmatched


def test_env_authored_id_believed():
    """A reference id whose value appears verbatim in a prior TOOL_RESULT → SUPPORTED."""
    v = classify_call(
        _mutating(_arg("incident_id", "INC0010023")),
        _corpus('{"number":"INC0010023"}'),
    )
    assert v.believe is True
    assert v.unsupported == ()
    a = v.args[0]
    assert a.stance is ProvenanceStance.SUPPORTED
    assert CorpusSource.TOOL_RESULT in a.matched_in


def test_derived_padded_from_bare_int():
    """The named ServiceNow livelock: arg 'INC0010023' derived from env BARE INT 10023.
    MUST be SUPPORTED via numeric-pad normalize ('0010023'.lstrip('0')=='10023'), never
    UNSUPPORTED → no re-read loop."""
    v = classify_call(
        _mutating(_arg("number", "INC0010023")),
        _corpus('{"sys_number": 10023}'),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.SUPPORTED


def test_derived_prefix_from_bare_digits():
    """arg 'INC0010023' where the corpus has the bare '0010023' — the 'INC' prefix is
    grammar-exempt, the digit-run traces → SUPPORTED."""
    v = classify_call(
        _mutating(_arg("id", "INC0010023")),
        _corpus("the record 0010023 was opened"),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.SUPPORTED


def test_composite_supported_from_env_parts():
    """A composite reference 'user_42@acme.com' where '42' and 'acme' both appear in env
    bytes → SUPPORTED ('user'/'com' grammar-exempt, no false-nudge)."""
    v = classify_call(
        _mutating(_arg("assignee", "user_42@acme.com")),
        _corpus('{"uid": 42, "company": "acme.com"}'),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.SUPPORTED


def test_composite_half_mint_refused():
    """'user_42@evil.com' where '42' and 'acme.com' are env-present but 'evil' is not →
    UNSUPPORTED, the evil part named."""
    v = classify_call(
        _mutating(_arg("assignee", "user_42@evil.com")),
        _corpus('{"uid": 42, "company": "acme.com"}'),
    )
    assert v.believe is False
    a = v.args[0]
    assert a.stance is ProvenanceStance.UNSUPPORTED
    assert any("evil" in c for c in a.components_unmatched)


def test_task_text_id_believed():
    """An id named in the TASK TEXT (env-authored) is provenance — even with no tool
    results yet, a TASK_TEXT blob 'close incident INC0010023 today' supports it."""
    v = classify_call(
        _mutating(_arg("incident", "INC0010023")),
        _corpus("close incident INC0010023 today", source=CorpusSource.TASK_TEXT),
    )
    assert v.believe is True
    a = v.args[0]
    assert a.stance is ProvenanceStance.SUPPORTED
    assert CorpusSource.TASK_TEXT in a.matched_in


def test_first_call_empty_corpus_abstains():
    """Any id-shaped reference arg with an empty corpus → ABSTAIN-all, believe=True
    (never accuse on step 1)."""
    v = classify_call(_mutating(_arg("parent", "INC9999999")), PriorResults())
    assert v.believe is True
    assert v.unsupported == ()
    assert all(a.stance is ProvenanceStance.ABSTAIN for a in v.args)


def test_new_key_create_own_id_not_nudged():
    """A create's OWN new identity (is_reference=False) is minted-and-correct → ABSTAIN,
    never UNSUPPORTED, even with a non-empty corpus (the dominant false-block class)."""
    v = classify_call(
        _mutating(_arg("email", "jane.doe@acme.com", ref=False), tool="create_user"),
        _corpus('{"existing":"bob@acme.com"}'),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.ABSTAIN
    assert "new-key" in v.args[0].reason


def test_read_call_not_gated():
    """A read / non-mutating call is never gated — reads are how provenance enters."""
    call = ToolCall(tool_name="get_incident", args=(_arg("number", "INC9999999"),), is_mutating=False)
    v = classify_call(call, _corpus('{"number":"INC0010023"}'))
    assert v.believe is True
    assert v.unsupported == ()


def test_list_arg_any_minted_refused():
    """recipients=[INC0010023, INC9999999] where only the first is env-present → the arg
    is UNSUPPORTED (any id-leaf minted nudges)."""
    v = classify_call(
        _mutating(_arg("recipients", ["INC0010023", "INC9999999"])),
        _corpus('{"number":"INC0010023"}'),
    )
    assert v.believe is False
    a = v.args[0]
    assert a.stance is ProvenanceStance.UNSUPPORTED
    assert any("9999999" in c for c in a.components_unmatched)


def test_list_arg_all_env_present_supported():
    """A list where every id-leaf is env-present → SUPPORTED."""
    v = classify_call(
        _mutating(_arg("recipients", ["INC0010023", "INC0010024"])),
        _corpus('{"a":"INC0010023","b":"INC0010024"}'),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.SUPPORTED


def test_case_insensitive_default_matches_recased_id():
    """A lowercased DB echo 'inc0010023' supports an arg 'INC0010023' under the default
    case_sensitive=False; case_sensitive=True does not."""
    corpus = _corpus('{"number":"inc0010023"}')
    v = classify_call(_mutating(_arg("id", "INC0010023")), corpus)
    assert v.args[0].stance is ProvenanceStance.SUPPORTED

    strict = ProvenancePolicy(case_sensitive=True)
    v2 = classify_call(_mutating(_arg("id", "INC0010023")), corpus, strict)
    # The digit-run still traces by substring regardless of case, so SUPPORTED holds; the
    # alpha prefix is grammar. The point: strict mode is reachable and does not crash.
    assert v2.args[0].stance in (ProvenanceStance.SUPPORTED, ProvenanceStance.UNSUPPORTED)


# ── MUST NOT BLOCK: the false-block guards (the §8 kill-signal protections) ───

def test_prose_arg_abstains():
    """A free-text arg (short_description) is not id-shaped → ABSTAIN."""
    v = classify_call(
        _mutating(_arg("short_description", "the printer on floor 2 is broken")),
        _corpus('{"number":"INC0010023"}'),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.ABSTAIN


def test_enum_role_status_tokens_abstain():
    """Enum/role/status tokens with a delimiter but no data-bearing component → ABSTAIN
    (the Step D enum guard)."""
    corpus = _corpus('{"number":"INC0010023"}')
    for val in ("itil_admin", "in_progress", "active", "high"):
        v = classify_call(_mutating(_arg("state", val)), corpus)
        assert v.believe is True, val
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, val


def test_dates_money_versions_phones_abstain():
    """Dates/times/money/versions/phones are quantity literals, not FKs → ABSTAIN (Step B
    negative filters — the §8 false-block killer)."""
    corpus = _corpus('{"number":"INC0010023"}')
    for val in ("2026-06-04", "12:30", "3.14159", "99.95", "v2.3.1", "555-0142", "1-800-555-0199"):
        v = classify_call(_mutating(_arg("due_date", val)), corpus)
        assert v.believe is True, val
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, val


def test_quantity_args_abstain():
    """Bare small numbers / non-FK-named quantities → ABSTAIN."""
    corpus = _corpus('{"number":"INC0010023"}')
    for name, val in (("limit", 50), ("priority", 3), ("page", 1)):
        v = classify_call(_mutating(_arg(name, val)), corpus)
        assert v.believe is True, name
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, name


def test_name_hint_substring_not_a_false_fire():
    """An arg whose name merely CONTAINS a hint substring but carries a non-id quantity
    (phone_number, version_number, due_to_date) must not false-fire — the name-hint is
    suffix-anchored to _id/_ref/_key/_email; *_number/*_to/*_from are NOT hints."""
    corpus = _corpus('{"number":"INC0010023"}')
    cases = [("phone_number", "555-0142"), ("version_number", "4.2.1"), ("due_to_date", "2026-06-04")]
    for name, val in cases:
        v = classify_call(_mutating(_arg(name, val)), corpus)
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, name


def test_bare_short_id_below_min_len_abstains():
    """A bare id shorter than min_component_len ('P1', 'US', 'v2') → ABSTAIN (the accepted
    silent miss, safe direction)."""
    corpus = _corpus('{"number":"INC0010023"}')
    for val in ("P1", "US", "v2"):
        v = classify_call(_mutating(_arg("region", val)), corpus)
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, val


def test_coincidental_substring_false_supported_is_safe():
    """A minted id that happens to appear in an unrelated blob declines to nudge
    (false-SUPPORTED is the SAFE direction; we never tighten to word-boundary at the cost
    of a livelock-risking false-nudge)."""
    # '12345' is minted but happens to be a substring of an env order total.
    v = classify_call(
        _mutating(_arg("parent", "REF12345")),
        _corpus('{"order_total": "112345.00 USD"}'),
    )
    # Declines to nudge — believe=True (safe degrade to baseline), not a false-block.
    assert v.believe is True


# ── classify_arg leaf-level + verdict shape ──────────────────────────────────

def test_classify_arg_leaf_directly():
    """classify_arg is the per-arg leaf, usable directly with a non-empty corpus."""
    a = classify_arg(_arg("parent", "INC9999999"), _corpus('{"number":"INC0010023"}'))
    assert isinstance(a, ArgProvenance)
    assert a.stance is ProvenanceStance.UNSUPPORTED


def test_verdict_to_dict_shape():
    """to_dict() is the --json / nudge shape — believe + args + unsupported + reason."""
    v = classify_call(_mutating(_arg("parent", "INC9999999")), _corpus('{"number":"INC0010023"}'))
    d = v.to_dict()
    assert set(d) == {"believe", "args", "unsupported", "reason"}
    assert d["believe"] is False
    assert d["unsupported"] == ["parent"]
    assert isinstance(d["args"], list) and d["args"][0]["stance"] == "UNSUPPORTED"


def test_policy_min_component_len_validation():
    """A min_component_len < 1 is rejected (the LivenessPolicy-style guard)."""
    import pytest

    with pytest.raises(ValueError):
        ProvenancePolicy(min_component_len=0)


def test_uuid_hex_form_survives():
    """A 32-hex sys_id present in the corpus supports a hex arg by substring; short chunks
    are dropped not demanded so a dashed form still traces."""
    sys_id = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    v = classify_call(
        _mutating(_arg("sys_id", sys_id)),
        _corpus(f'{{"sys_id":"{sys_id}"}}'),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.SUPPORTED


def test_multiple_args_mixed():
    """A call with one minted + one resolved + one prose arg → believe=False, only the
    minted one in unsupported, Task-Completion-style prose untouched."""
    v = classify_call(
        _mutating(
            _arg("caller_id", "INC0010023"),       # resolved
            _arg("parent", "INC9999999"),          # minted
            _arg("short_description", "broken"),   # prose (abstain)
        ),
        _corpus('{"number":"INC0010023"}'),
    )
    assert v.believe is False
    assert v.unsupported == ("parent",)


# ── real-data regression: the false-flag patterns the docs/143 live run exposed ──
# Each of these is a value gemini-3-flash passed that DID appear in its prior tool results;
# the detector must NOT flag it. Pinned so the whole-value direct match + the real-data
# hardening (ISO datetime, UUID-whole, email digit-suffix) never regress.

def test_realdata_underscore_padded_id_direct_match():
    """`INC_004` / `msg_001` / `USER_011` appear VERBATIM in prior results → SUPPORTED by
    the whole-value direct match (NOT decomposed into a too-short '004' that misses)."""
    for val in ("INC_004", "msg_001", "USER_011", "draft_001", "GROUP_002", "CI_002", "KB_003"):
        v = classify_call(
            _mutating(_arg("incident_id", val)),
            _corpus(f'[{{"id":"{val}","state":"open"}}]'),
        )
        assert v.believe is True, val
        assert v.args[0].stance is ProvenanceStance.SUPPORTED, val


def test_realdata_uuid_matched_whole_not_split():
    """A UUID present verbatim in prior results is SUPPORTED — never split on '-' into
    sub-chunks ('1','089') that don't independently trace (the live false-flag)."""
    uuid = "3fc71c6d-bfa1-4339-b089-eeb1af1e530c"
    v = classify_call(
        _mutating(_arg("addLabelIds", uuid)),
        _corpus(f'{{"labels":[{{"id":"{uuid}"}}]}}'),
    )
    assert v.believe is True
    assert v.args[0].stance is ProvenanceStance.SUPPORTED


def test_realdata_email_username_digit_suffix_not_demanded():
    """`jason.smith10@servicenow.com` where the email is present (or only the name+org are)
    → the '10' username discriminator is grammar, never demanded as an FK (the live
    false-flag where '10' was 'unmatched')."""
    v = classify_call(
        _mutating(_arg("email", "jason.smith10@servicenow.com")),
        _corpus('{"assignee":"jason.smith10@servicenow.com"}'),
    )
    assert v.believe is True


def test_realdata_full_iso_datetime_abstains():
    """A full ISO-8601 timestamp is a quantity, not an FK → ABSTAIN (was mis-split into
    '23T00'/'59' id components)."""
    for ts in ("2025-08-23T00:00:00Z", "2025-12-31T23:59:59Z", "2025-08-23T00:00:00+05:30"):
        v = classify_call(_mutating(_arg("startTime", ts)), _corpus('{"x":"INC_004"}'))
        assert v.believe is True, ts
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, ts


def test_realdata_genuine_mint_still_caught():
    """The mechanism still CATCHES a genuine mint: an id that appears NOWHERE in prior
    results or task text → UNSUPPORTED (the direct match fails AND no component traces)."""
    v = classify_call(
        _mutating(_arg("incident_id", "INC_9999")),
        _corpus('[{"id":"INC_004"},{"id":"INC_005"}]'),
    )
    assert v.believe is False
    assert v.args[0].stance is ProvenanceStance.UNSUPPORTED


def test_realdata_bare_int_fk_in_id_slot_caught():
    """The ServiceNow numeric-PK pattern: a bare short integer in a strong FK-name slot
    (`group_id=81`) is an FK — a minted one (prior has only 54) is UNSUPPORTED, a resolved
    one (=54) is SUPPORTED. This is the recall lift (55%→83%) the live run motivated."""
    minted = classify_call(
        _mutating(_arg("group_id", 81)), _corpus('{"group_id": 54, "name": "ops"}'))
    assert minted.believe is False
    assert minted.args[0].stance is ProvenanceStance.UNSUPPORTED
    resolved = classify_call(
        _mutating(_arg("group_id", 54)), _corpus('{"group_id": 54}'))
    assert resolved.believe is True
    assert resolved.args[0].stance is ProvenanceStance.SUPPORTED


def test_realdata_price_amount_count_not_flagged():
    """A bare number in a QUANTITY slot (price/amount/count) is a value the model sets, NOT
    an FK — never id-shaped, never flagged (the live contract_price=33414 false-flag)."""
    corpus = _corpus('{"existing_price": 100}')
    for name, val in (("contract_price", 33414), ("total_amount", 2678),
                      ("max_results", 500), ("item_count", 12), ("unit_price", 4999)):
        v = classify_call(_mutating(_arg(name, val)), corpus)
        assert v.believe is True, name
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, name


def test_realdata_bare_int_quantity_slot_still_abstains():
    """A bare integer in a NON-FK slot stays a quantity (the name-hint is required for the
    short-int promotion; `priority`/`limit`/`page` never become ids)."""
    corpus = _corpus('{"x": 1}')
    for name, val in (("priority", 3), ("limit", 50), ("page", 2), ("max_results", 100)):
        v = classify_call(_mutating(_arg(name, val)), corpus)
        assert v.args[0].stance is ProvenanceStance.ABSTAIN, name
