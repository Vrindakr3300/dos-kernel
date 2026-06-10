"""TS — the stall-reader verdict + its eval (docs/145, the loop-economics axis).

`tool_stream.classify_stream` is `liveness.classify`'s sibling re-aimed off git onto the
in-process tool-result stream: a PURE verdict over already-gathered `(tool, args_digest,
result_digest)` steps. These tests pin the ladder on FROZEN streams (no live hashing, no
benchmark, no LLM) — the "testable with zero benchmark access" keystone — plus the §5a
honesty boundaries (env-result identity, never a satisfaction predicate), the poller
exemptions, the TOML on-ramp, and the eval harness's recovery/false-fire ledger.

The verdict ladder under test:
  1. ADVANCING — trailing identical-run < repeat_n (incl. empty/short/new-bytes).
  2. REPEATING — trailing run >= repeat_n and < stall_n (re-surface the value).
  3. STALLED   — trailing run >= stall_n (near-certainly doomed; BLOCK-eligible).
"""

from __future__ import annotations

import pytest

from dos import tool_stream, tool_stream_eval
from dos.tool_stream import (
    DEFAULT_POLICY,
    StreamPolicy,
    StreamState,
    StreamStep,
    StreamVerdict,
    ToolStream,
    classify_stream,
    policy_from_table,
)
from dos.tool_stream_eval import StreamCase, StreamEvalReport, score


# A small explicit policy so the tests read concretely: REPEATING at 3, STALLED at 5.
_POLICY = StreamPolicy(repeat_n=3, stall_n=5)


def _step(tool="get_incident", args="a1", result="r1") -> StreamStep:
    """A StreamStep with sensible defaults; override per test. `result=None` marks no result."""
    return StreamStep(tool_name=tool, args_digest=args, result_digest=result)


def _stream(*steps: StreamStep) -> ToolStream:
    return ToolStream(steps=tuple(steps))


def _repeat(n: int, **over) -> ToolStream:
    """A stream of `n` byte-identical steps (the canonical repeat run)."""
    return _stream(*[_step(**over) for _ in range(n)])


# ---------------------------------------------------------------------------
# 1. The three rungs, on frozen streams (the core litmus).
# ---------------------------------------------------------------------------


def test_empty_stream_is_advancing():
    """No steps → ADVANCING (too little has happened to accuse — the too-young floor)."""
    v = classify_stream(ToolStream(), _POLICY)
    assert v.state is StreamState.ADVANCING
    assert v.repeat_run == 0
    assert v.repeated_step is None


def test_short_run_below_repeat_is_advancing():
    """Two identical results, repeat_n=3 → still ADVANCING (the first re-check is benign)."""
    v = classify_stream(_repeat(2), _POLICY)
    assert v.state is StreamState.ADVANCING
    assert v.repeat_run == 2


def test_run_at_repeat_n_is_repeating():
    """Exactly repeat_n identical results → REPEATING, and names the repeated step."""
    v = classify_stream(_repeat(3), _POLICY)
    assert v.state is StreamState.REPEATING
    assert v.repeat_run == 3
    assert v.repeated_step is not None
    assert v.repeated_step.result_digest == "r1"


def test_run_at_stall_n_is_stalled():
    """stall_n identical results → STALLED (the BLOCK-eligible hard rung)."""
    v = classify_stream(_repeat(5), _POLICY)
    assert v.state is StreamState.STALLED
    assert v.repeat_run == 5


def test_run_between_repeat_and_stall_is_repeating():
    """A run of 4 (>=3, <5) is REPEATING, not yet STALLED."""
    v = classify_stream(_repeat(4), _POLICY)
    assert v.state is StreamState.REPEATING
    assert v.repeat_run == 4


def test_long_run_past_stall_stays_stalled():
    """A run well past stall_n stays STALLED (monotone — more repetition never de-escalates)."""
    v = classify_stream(_repeat(9), _POLICY)
    assert v.state is StreamState.STALLED
    assert v.repeat_run == 9


# ---------------------------------------------------------------------------
# 2. The repeat-identity key — what counts as "the same".
# ---------------------------------------------------------------------------


def test_only_the_TRAILING_run_counts():
    """A repeat run earlier in the stream that was BROKEN does not fire — only the run ending
    at the latest step matters (the live 'is it stuck NOW?' question)."""
    s = _stream(
        _step(result="r1"), _step(result="r1"), _step(result="r1"),  # an old run of 3
        _step(result="r2"),                                          # broken by new bytes
        _step(result="r3"),                                          # the latest is unique
    )
    v = classify_stream(s, _POLICY)
    assert v.state is StreamState.ADVANCING
    assert v.repeat_run == 1


def test_different_result_bytes_break_the_run():
    """Same tool+args but the env returned DIFFERENT bytes → not a repeat (state advanced)."""
    s = _stream(_step(result="r1"), _step(result="r1"), _step(result="r2"))
    v = classify_stream(s, _POLICY)
    assert v.state is StreamState.ADVANCING
    assert v.repeat_run == 1


def test_different_args_are_not_a_repeat():
    """Same tool + same result digest but DIFFERENT args (reading two different rows that happen
    to digest-collide is excluded by the args component) → not a repeat run."""
    s = _stream(
        _step(args="rowA", result="r1"),
        _step(args="rowB", result="r1"),
        _step(args="rowC", result="r1"),
    )
    v = classify_stream(s, _POLICY)
    assert v.state is StreamState.ADVANCING


def test_different_tool_is_not_a_repeat():
    """Same args+result but a different tool name → not the same call → not a repeat."""
    s = _stream(
        _step(tool="get_incident", result="r1"),
        _step(tool="get_user", result="r1"),
        _step(tool="get_change", result="r1"),
    )
    v = classify_stream(s, _POLICY)
    assert v.state is StreamState.ADVANCING


def test_tool_name_is_casefolded_for_identity():
    """Tool-name identity is casefold (a DB echo may re-case) — Get_Incident == get_incident."""
    s = _stream(
        _step(tool="Get_Incident", result="r1"),
        _step(tool="get_incident", result="r1"),
        _step(tool="GET_INCIDENT", result="r1"),
    )
    v = classify_stream(s, _POLICY)
    assert v.state is StreamState.REPEATING


# ---------------------------------------------------------------------------
# 3. The fail-safe directions — None result, the §5a honest hole.
# ---------------------------------------------------------------------------


def test_none_result_latest_step_never_fires():
    """A latest step with no result (a call that errored/returned nothing) is never a repeat —
    'no result' is not 'the same result' (the fail-safe: when in doubt, not stalled)."""
    s = _stream(_step(result="r1"), _step(result="r1"), _step(result=None))
    v = classify_stream(s, _POLICY)
    assert v.state is StreamState.ADVANCING
    assert v.repeat_run == 1
    assert v.repeated_step is None


def test_none_result_in_the_middle_breaks_the_run():
    """A None-result step mid-stream breaks the run — the trailing run restarts after it."""
    s = _stream(
        _step(result="r1"), _step(result=None), _step(result="r1"), _step(result="r1"),
    )
    v = classify_stream(s, _POLICY)
    # trailing run is the two r1 after the None → 2 < repeat_n → ADVANCING
    assert v.state is StreamState.ADVANCING
    assert v.repeat_run == 2


def test_ignore_tools_exempts_a_known_poller():
    """A tool on `ignore_tools` is exempt at the source: a poll loop on it never fires REPEATING
    (the eventual-consistency safety valve — a host KNOWS this tool re-reads identically)."""
    pol = StreamPolicy(repeat_n=3, stall_n=5, ignore_tools=frozenset({"poll_status"}))
    s = _repeat(5, tool="poll_status")
    v = classify_stream(s, pol)
    assert v.state is StreamState.ADVANCING
    assert v.repeat_run == 1


def test_ignore_tools_is_casefolded():
    """The ignore-list match is casefold, like the identity key."""
    pol = StreamPolicy(repeat_n=3, stall_n=5, ignore_tools=frozenset({"Poll_Status"}))
    v = classify_stream(_repeat(4, tool="poll_status"), pol)
    assert v.state is StreamState.ADVANCING


def test_a_non_ignored_tool_still_fires_with_an_ignore_list_present():
    """An ignore-list exempts only its members — other tools still fire normally."""
    pol = StreamPolicy(repeat_n=3, stall_n=5, ignore_tools=frozenset({"poll_status"}))
    v = classify_stream(_repeat(3, tool="get_incident"), pol)
    assert v.state is StreamState.REPEATING


# ---------------------------------------------------------------------------
# 4. Policy validation + the TOML on-ramp.
# ---------------------------------------------------------------------------


def test_repeat_n_must_be_positive():
    with pytest.raises(ValueError):
        StreamPolicy(repeat_n=0)


def test_stall_n_must_be_at_least_repeat_n():
    """STALLED is strictly more repetition than REPEATING — stall_n < repeat_n is incoherent."""
    with pytest.raises(ValueError):
        StreamPolicy(repeat_n=4, stall_n=3)


def test_stall_n_equal_to_repeat_n_is_allowed():
    """stall_n == repeat_n collapses the two rungs (every fire is STALLED) — legal, if extreme."""
    pol = StreamPolicy(repeat_n=3, stall_n=3)
    v = classify_stream(_repeat(3), pol)
    assert v.state is StreamState.STALLED


def test_default_policy_thresholds():
    """The shipped generic defaults: REPEATING at 3, STALLED at 5."""
    assert DEFAULT_POLICY.repeat_n == 3
    assert DEFAULT_POLICY.stall_n == 5
    assert classify_stream(_repeat(3)).state is StreamState.REPEATING
    assert classify_stream(_repeat(5)).state is StreamState.STALLED


def test_policy_from_empty_table_is_default():
    assert policy_from_table({}) == DEFAULT_POLICY


def test_policy_from_table_reads_all_knobs():
    pol = policy_from_table({"repeat_n": 2, "stall_n": 4, "ignore_tools": ["poll", "wait"]})
    assert pol.repeat_n == 2
    assert pol.stall_n == 4
    assert pol.ignore_tools == frozenset({"poll", "wait"})


def test_policy_from_table_accepts_a_single_ignore_string():
    pol = policy_from_table({"ignore_tools": "poll_status"})
    assert pol.ignore_tools == frozenset({"poll_status"})


def test_policy_from_table_raises_on_bad_value():
    """A malformed declaration fails loudly at load (via StreamPolicy.__post_init__)."""
    with pytest.raises(ValueError):
        policy_from_table({"repeat_n": 5, "stall_n": 2})


# ---------------------------------------------------------------------------
# 5. The verdict shape — to_dict (the renderer/json seam).
# ---------------------------------------------------------------------------


def test_to_dict_repeating_carries_the_repeated_step():
    v = classify_stream(_repeat(3), _POLICY)
    d = v.to_dict()
    assert d["state"] == "REPEATING"
    assert d["repeat_run"] == 3
    assert d["repeated_step"]["result_digest"] == "r1"
    assert d["repeated_step"]["tool_name"] == "get_incident"


def test_to_dict_advancing_has_null_repeated_step():
    d = classify_stream(ToolStream(), _POLICY).to_dict()
    assert d["state"] == "ADVANCING"
    assert d["repeated_step"] is None


def test_state_enum_round_trips_as_token():
    assert str(StreamState.REPEATING) == "REPEATING"
    assert StreamState("STALLED") is StreamState.STALLED


# ---------------------------------------------------------------------------
# 6. The eval harness — recovery / false-fire ledger.
# ---------------------------------------------------------------------------


def _case(stream, *, stuck, polling, recovered=False, label="") -> StreamCase:
    return StreamCase(
        stream=stream, actually_stuck=stuck, legit_polling=polling,
        recovered_if_fired=recovered, label=label,
    )


def test_eval_recovers_a_stuck_stream_that_fires():
    """A genuinely-stuck stream the policy fires on AND that recovers → recovered_rate 1.0."""
    cases = [_case(_repeat(4), stuck=True, polling=False, recovered=True)]
    rep = score(_POLICY, cases)
    assert rep.n_stuck == 1
    assert rep.n_fired == 1
    assert rep.n_recovered == 1
    assert rep.recovered_rate == pytest.approx(1.0)
    assert rep.false_resurface_rate == 0.0
    assert rep.net_positive is True


def test_eval_false_resurface_on_a_legit_poller():
    """A legit-polling stream the policy ALSO fires on counts in the dangerous cell."""
    cases = [_case(_repeat(4), stuck=False, polling=True, recovered=False)]
    rep = score(_POLICY, cases)
    assert rep.n_polling == 1
    assert rep.n_fired_polling == 1
    assert rep.false_resurface_rate == pytest.approx(1.0)
    assert rep.recovered_rate == 0.0
    assert rep.net_positive is False  # 0 recovered, 1 false fire


def test_eval_timid_policy_never_fires_scores_zero_recovery():
    """A policy with a huge repeat_n never fires → recovered_rate 0 (the timid-policy floor)."""
    timid = StreamPolicy(repeat_n=99, stall_n=100)
    cases = [_case(_repeat(4), stuck=True, polling=False, recovered=True)]
    rep = score(timid, cases)
    assert rep.n_fired == 0
    assert rep.recovered_rate == 0.0
    assert rep.fire_recall == 0.0


def test_eval_ignore_tools_suppresses_a_false_fire():
    """Putting the poller on ignore_tools moves a false-fire stream OUT of the fired cell — the
    instrument that proves the allow-list pays."""
    pol = StreamPolicy(repeat_n=3, stall_n=5, ignore_tools=frozenset({"poll_status"}))
    cases = [_case(_repeat(4, tool="poll_status"), stuck=False, polling=True)]
    rep = score(pol, cases)
    assert rep.n_fired_polling == 0
    assert rep.false_resurface_rate == 0.0


def test_eval_invariant_firing_ledger_within_fired():
    """The firing-cell counts never exceed n_fired, and recovered <= fired_stuck (the pinned
    one-pass invariant — counts cannot drift from the firing total)."""
    cases = [
        _case(_repeat(4), stuck=True, polling=False, recovered=True),    # fired, stuck, recovered
        _case(_repeat(4), stuck=False, polling=True),                    # fired, polling
        _case(_repeat(2), stuck=True, polling=False, recovered=True),    # NOT fired (run 2 < 3)
        _case(ToolStream(), stuck=False, polling=False),                 # advancing, nothing
    ]
    rep = score(_POLICY, cases)
    assert rep.n == 4
    assert rep.n_fired_stuck + rep.n_fired_polling <= rep.n_fired + rep.n_fired  # both <= n_fired
    assert rep.n_fired_stuck <= rep.n_fired
    assert rep.n_fired_polling <= rep.n_fired
    assert rep.n_recovered <= rep.n_fired_stuck
    # the run-2 stuck case did NOT fire, so it is not recovered
    assert rep.n_fired == 2
    assert rep.n_recovered == 1


def test_eval_report_to_dict_shape():
    cases = [_case(_repeat(4), stuck=True, polling=False, recovered=True)]
    d = score(_POLICY, cases).to_dict()
    assert d["n"] == 1
    assert d["grid"]["stuck"] == 1
    assert d["firing"]["recovered"] == 1
    assert "recovered_rate" in d["rates"]
    assert "false_resurface_rate" in d["rates"]
    assert d["net_positive"] is True


def test_eval_empty_cases_is_all_zero_no_div_by_zero():
    rep = score(_POLICY, [])
    assert rep.n == 0
    assert rep.recovered_rate == 0.0
    assert rep.false_resurface_rate == 0.0
    assert rep.net_positive is False
