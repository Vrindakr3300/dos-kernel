"""Replay-test the AgentHallu Tool-Use step-localizer on FROZEN fixtures — zero corpus/LLM access.

Two layers, the same shape as test_toolathlon_replay.py:
  * Pure unit tests over synthetic AgentHallu-shaped records pin the byte-clean behavior: the
    gold-step string/int coercion (the bug that bit during the build), the env-authored-response
    error scan, abstain-when-no-error, and the clean-trajectory false-alarm path.
  * A corpus-GATED test asserts the SSOT invariants only when the cloned AgentHallu corpus is present
    (so CI without the data still passes; the dataset is CC-BY-4.0 and not vendored).
"""

from __future__ import annotations

import pytest

from benchmark.agenthallu.dataset import Trajectory, gold_step
from benchmark.agenthallu.detector import (
    first_errored_response,
    first_structural_error,
    first_unrecovered_error,
    _step_errored,
)
from benchmark.agenthallu import scoring


def _traj(record: dict) -> Trajectory:
    from pathlib import Path

    return Trajectory(path=Path("synthetic.json"), framework="synthetic", record=record)


def _step(i: int, *, response=None) -> dict:
    return {
        "step": i,
        "role": "assistant",
        "content": None,
        "tool_calls": [{"name": "echo", "arguments": {}}],
        "tool_responses": response,
    }


# ---- gold-step coercion (the string "6" vs int 6 trap) -------------------------------------------

def test_gold_step_coerces_string_to_int():
    assert gold_step({"hallucination_step": "6"}) == 6
    assert gold_step({"hallucination_step": 6}) == 6


def test_gold_step_none_when_absent_or_unparseable():
    assert gold_step({}) is None
    assert gold_step({"hallucination_step": None}) is None
    assert gold_step({"hallucination_step": "n/a"}) is None


# ---- the detector reads ENV-authored responses, abstains otherwise -------------------------------

def test_fires_on_first_errored_env_response():
    rec = {
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "3",
        "history": [
            _step(1, response=["ok"]),
            _step(2, response=["done"]),
            _step(3, response=["Error: file not found"]),
            _step(4, response=["Error: again"]),
        ],
    }
    assert first_errored_response(_traj(rec)) == 3  # first errored step, not the second


def test_abstains_when_no_errored_response():
    rec = {
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "2",
        "history": [_step(1, response=["ok"]), _step(2, response=["fine"])],
    }
    # The semantic hallucination left no errored byte -> the detector abstains (never invents).
    assert first_errored_response(_traj(rec)) is None


def test_ignores_error_token_in_agent_authored_fields():
    # An "error" the AGENT wrote in content/tool_calls is NOT env-authored evidence -> no fire.
    rec = {
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "1",
        "history": [
            {
                "step": 1,
                "role": "assistant",
                "content": "I think this will error",
                "tool_calls": [{"name": "echo", "arguments": {"msg": "error error"}}],
                "tool_responses": None,
            }
        ],
    }
    assert first_errored_response(_traj(rec)) is None


def test_clean_trajectory_with_error_is_a_false_alarm():
    # A clean (non-hallucinated) run that happens to carry an errored-then-recovered response is
    # exactly the false-alarm the scorer must count, not hide.
    rec = {
        "is_hallucination": "false",
        "history": [_step(1, response=["Error: transient"]), _step(2, response=["recovered ok"])],
    }
    assert first_errored_response(_traj(rec)) == 1


# ---- scorer arithmetic on a tiny synthetic corpus ------------------------------------------------

def test_scorer_counts_exact_precision_and_false_alarm():
    hit = {
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "1",
        "history": [_step(1, response=["Error: boom"])],
    }
    miss = {  # fires on step 2 but gold is 1 -> fired, not exact
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "1",
        "history": [_step(1, response=["ok"]), _step(2, response=["Error: late"])],
    }
    clean_fp = {
        "is_hallucination": "false",
        "history": [_step(1, response=["Error: transient"])],
    }
    trajs = [_traj(hit), _traj(miss), _traj(clean_fp)]
    s = scoring.compute(trajs)["first_errored_response"]
    assert s.tool_use_total == 2
    assert s.fired == 2 and s.exact == 1
    assert s.precision == 0.5
    assert s.clean_total == 1 and s.clean_fired == 1
    assert s.false_alarm == 1.0


# ---- the structural error-CHANNEL floor (the precision fix, docs/166 §4b-ii) --------------------

def test_step_errored_fires_on_structured_error_key():
    # The env's structured error channel: a dict with a truthy error KEY.
    assert _step_errored(_step(1, response=['{"error": "No such directory"}']))
    # Python-repr (single-quote) responses need the ast fallback, not just json.loads.
    assert _step_errored(_step(1, response=["[{'error': 'mv: cannot move'}]"]))
    # Nested one level down is still seen.
    assert _step_errored(_step(1, response=['{"result": {"error": "denied"}}']))


def test_step_errored_fires_on_raised_error_prose_prefix():
    # A tool that THREW, prefixing its response — the env's raised-error prose channel.
    assert _step_errored(_step(1, response=["Error during execution: bad arg"]))
    assert _step_errored(_step(1, response=["Traceback (most recent call last): ..."]))


def test_step_errored_ignores_error_word_in_legitimate_data():
    # The breadth bug the structural floor fixes: an error WORD sitting in legitimate env response
    # DATA (a file's content, a search result) is NOT the env's error channel -> no fire.
    assert not _step_errored(_step(1, response=['{"current_directory_content": ["error_log.txt"]}']))
    assert not _step_errored(_step(1, response=['{"summary": "the permission system has no errors"}']))
    # An empty error channel (falsy value) is the channel present but unused -> not an error.
    assert not _step_errored(_step(1, response=['{"error": null}']))
    assert not _step_errored(_step(1, response=['{"error": ""}']))


def test_first_structural_error_localizes_the_error_channel_step():
    rec = {
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "2",
        "history": [
            _step(1, response=['{"current_directory_content": ["error_log.txt"]}']),  # WORD, not channel
            _step(2, response=['{"error": "command not found"}']),                     # the channel
        ],
    }
    # The broad scan would false-fire on step 1's "error_log.txt"; the structural floor skips it.
    assert first_errored_response(_traj(rec)) == 1
    assert first_structural_error(_traj(rec)) == 2


# ---- the unrecovered-error gate (the recommended precision point) --------------------------------

def _tool_step(i: int, tool: str, *, response=None) -> dict:
    return {
        "step": i,
        "role": "assistant",
        "content": None,
        "tool_calls": [{"name": tool, "arguments": {}}],
        "tool_responses": response,
    }


def test_first_unrecovered_error_suppresses_a_recovered_transient():
    # A transient error the agent recovers from (same tool returns clean bytes later) must NOT fire:
    # the cd typo errors at step 1, then a later cd returns a clean result -> recovered, abstain.
    rec = {
        "is_hallucination": "false",
        "history": [
            _tool_step(1, "cd", response=['{"error": "cd: document: No such directory"}']),
            _tool_step(2, "ls", response=['{"current_directory_content": ["documents"]}']),
            _tool_step(3, "cd", response=['{"current_working_directory": "documents"}']),  # recovery
        ],
    }
    assert first_unrecovered_error(_traj(rec)) is None
    # The structural floor (no recovery gate) still fires on the transient — that is its 11% FA cost.
    assert first_structural_error(_traj(rec)) == 1


def test_first_unrecovered_error_fires_on_a_terminal_error():
    # A terminal error — the same tool never returns a clean response afterward -> fire (the divergence).
    rec = {
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "2",
        "history": [
            _tool_step(1, "ls", response=['{"current_directory_content": ["a.txt"]}']),
            _tool_step(2, "book_flight", response=['{"error": "Booking not found"}']),  # never retried
        ],
    }
    assert first_unrecovered_error(_traj(rec)) == 2


def test_first_unrecovered_error_abstains_when_no_error_channel():
    # A semantic divergence that left no errored env byte -> the detector abstains (never invents).
    rec = {
        "is_hallucination": "true",
        "hallucination_category": "Tool-Use Hallucination",
        "hallucination_step": "1",
        "history": [_tool_step(1, "post_tweet", response=['{"id": "tw_001"}'])],
    }
    assert first_unrecovered_error(_traj(rec)) is None


# ---- corpus-gated SSOT invariants ----------------------------------------------------------------

def test_corpus_invariants_when_present():
    try:
        scores = scoring.compute()
    except FileNotFoundError:
        pytest.skip("AgentHallu corpus not cloned; skipping live-corpus invariants")
    assert scoring._invariants(scores) == []
    s = scores["first_errored_response"]
    assert s.tool_use_total == 103
    assert s.exact_rate > scoring.SOTA_TOOLUSE  # beats the frontier on the hardest slice
    # The precision point: the false-alarm floor is cut ~29× (35.2% -> 1.2%) for 4 fewer exact-hits,
    # and still beats SOTA. This is the headline of docs/166 §4b-ii.
    b = scores["first_unrecovered_error"]
    assert b.false_alarm < 0.05 < s.false_alarm  # the cut is real and large
    assert b.exact_rate > scoring.SOTA_TOOLUSE   # the benefit survives the cut
    assert b.precision >= 0.75                   # the precision claim
