"""Replay-test the AgentProcessBench boundary/floor instrument on FROZEN fixtures — no corpus/LLM.

Two layers, the same shape as test_agenthallu_replay.py:
  * Pure unit tests over synthetic AgentProcessBench-shaped records pin the byte-clean behavior: the
    step_labels str/int coercion (the AgentHallu trap), the tool_metrics.status alignment (the
    authoritative env channel, NOT a text scan), the status-channel localizer, the recovery gate, and
    the error-caused BOUNDARY classification.
  * A corpus-GATED test asserts the SSOT invariants only when the cached AgentProcessBench corpus is
    present (so CI without the data still passes; the dataset is MIT and not vendored).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.agentprocessbench.dataset import Trajectory
from benchmark.agentprocessbench.detector import (
    first_env_error,
    first_unrecovered_env_error,
)
from benchmark.agentprocessbench import scoring


def _traj(config: str, record: dict) -> Trajectory:
    return Trajectory(config=config, record=record)


def _assistant(tool: str) -> dict:
    return {"role": "assistant", "tool_calls": [{"function": {"name": tool}}]}


def _tool(content: str = "ok") -> dict:
    return {"role": "tool", "content": content}


# ---- step_labels str/int coercion (the AgentHallu "6" vs 6 trap) ---------------------------------

def test_step_labels_coerce_string_keys_and_values_to_int():
    t = _traj("bfcl", {"step_labels": {"3": 1, "5": "-1"}, "messages": [], "tool_metrics": {}})
    assert t.step_labels == {3: 1, 5: -1}
    assert t.first_negative_step == 5
    assert t.negative_steps == [5]


def test_first_negative_step_none_when_no_minus_one():
    t = _traj("bfcl", {"step_labels": {"1": 1, "2": 0}, "messages": [], "tool_metrics": {}})
    assert t.first_negative_step is None


# ---- the AUTHORITATIVE status channel (tool_metrics), not a text scan ----------------------------

def test_step_tool_status_reads_tool_metrics_not_text():
    # mkdir returns the TEXT "None" but tool_metrics says success -> must read success, not fire.
    # mv returns success text but tool_metrics says error -> must read error (text would miss it).
    rec = {
        "messages": [
            _assistant("mkdir"), _tool("None"),
            _assistant("mv"), _tool('{"current_working_directory": "x"}'),
        ],
        "tool_metrics": {
            "mkdir": [{"status": "success"}],
            "mv": [{"status": "error"}],
        },
        "step_labels": {},
    }
    status = _traj("bfcl", rec).step_tool_status()
    assert status[0] == "success"   # mkdir, despite "None" text
    assert status[2] == "error"     # mv, despite success-looking text


def test_step_tool_status_counts_per_tool_invocation_in_order():
    # ls called twice; the 2nd invocation errors. The k-th call must map to tool_metrics[name][k].
    rec = {
        "messages": [
            _assistant("ls"), _tool("a"),
            _assistant("ls"), _tool("b"),
        ],
        "tool_metrics": {"ls": [{"status": "success"}, {"status": "error"}]},
        "step_labels": {},
    }
    status = _traj("bfcl", rec).step_tool_status()
    assert status[0] == "success"
    assert status[2] == "error"


# ---- the localizers ------------------------------------------------------------------------------

def test_first_env_error_fires_on_first_errored_step():
    rec = {
        "messages": [
            _assistant("pwd"), _tool("/x"),
            _assistant("cd"), _tool("err"),
        ],
        "tool_metrics": {"pwd": [{"status": "success"}], "cd": [{"status": "error"}]},
        "step_labels": {"2": -1},
    }
    assert first_env_error(_traj("bfcl", rec)) == 2


def test_first_env_error_abstains_when_all_success():
    rec = {
        "messages": [_assistant("pwd"), _tool("/x")],
        "tool_metrics": {"pwd": [{"status": "success"}]},
        "step_labels": {},
    }
    assert first_env_error(_traj("bfcl", rec)) is None


def test_unrecovered_gate_suppresses_a_recovered_error():
    # cd errors at step 0, then a LATER cd succeeds -> recovered -> the gated detector abstains,
    # while the plain detector still fires (the trade-off the SSOT reports).
    rec = {
        "messages": [
            _assistant("cd"), _tool("err"),
            _assistant("ls"), _tool("ok"),
            _assistant("cd"), _tool("ok"),
        ],
        "tool_metrics": {
            "cd": [{"status": "error"}, {"status": "success"}],
            "ls": [{"status": "success"}],
        },
        "step_labels": {},
    }
    t = _traj("bfcl", rec)
    assert first_env_error(t) == 0            # plain fires on the first error
    assert first_unrecovered_env_error(t) is None  # gated: cd recovered later -> suppress


def test_unrecovered_gate_fires_on_a_terminal_error():
    rec = {
        "messages": [
            _assistant("ls"), _tool("ok"),
            _assistant("book"), _tool("err"),  # never retried -> terminal
        ],
        "tool_metrics": {"ls": [{"status": "success"}], "book": [{"status": "error"}]},
        "step_labels": {"2": -1},
    }
    assert first_unrecovered_env_error(_traj("bfcl", rec)) == 2


# ---- the BOUNDARY classification (the headline finding) ------------------------------------------

def test_error_caused_true_when_gold_coincides_with_env_error():
    rec = {
        "messages": [_assistant("cd"), _tool("err")],
        "tool_metrics": {"cd": [{"status": "error"}]},
        "step_labels": {"0": -1},
    }
    assert scoring._error_caused(_traj("bfcl", rec)) is True


def test_error_caused_false_for_a_silent_semantic_divergence():
    # The gold -1 sits on a step whose tool SUCCEEDED — the agent was wrong by LOGIC, no error byte.
    # This is the 73-89% silent majority the byte-clean detector is blind to BY DESIGN.
    rec = {
        "messages": [
            _assistant("get_user"), _tool("ok"),
            _assistant("transfer"), _tool("ok"),  # succeeds, but it was the wrong action
        ],
        "tool_metrics": {"get_user": [{"status": "success"}], "transfer": [{"status": "success"}]},
        "step_labels": {"2": -1},
    }
    assert scoring._error_caused(_traj("tau2", rec)) is False


def test_scorer_counts_boundary_and_floor():
    err_caused = {  # gold -1 on an errored step -> error-caused, detector hits it
        "messages": [_assistant("cd"), _tool("err")],
        "tool_metrics": {"cd": [{"status": "error"}]},
        "step_labels": {"0": -1},
    }
    silent = {  # gold -1 on a success step -> silent, not error-caused
        "messages": [_assistant("ok_tool"), _tool("ok")],
        "tool_metrics": {"ok_tool": [{"status": "success"}]},
        "step_labels": {"0": -1},
    }
    clean = {  # no -1 step, but its tool errors -> a false-alarm candidate
        "messages": [_assistant("cd"), _tool("err")],
        "tool_metrics": {"cd": [{"status": "error"}]},
        "step_labels": {"0": 1},
        "final_label": 1,
    }
    trajs = [_traj("bfcl", err_caused), _traj("bfcl", silent), _traj("bfcl", clean)]
    s = scoring.compute(trajs)["bfcl"]
    assert s.localizable == 2          # err_caused + silent both have a -1
    assert s.error_caused == 1         # only err_caused is error-caused (the boundary)
    assert s.slice_hit == 1            # detector localizes the error-caused one
    assert s.clean_total == 1 and s.clean_fired == 1  # fires on the clean errored run (false-alarm)


# ---- corpus-gated SSOT invariants ----------------------------------------------------------------

def test_corpus_invariants_when_present():
    try:
        scores = scoring.compute()
    except FileNotFoundError:
        pytest.skip("AgentProcessBench corpus not cached; skipping live-corpus invariants")
    assert scoring._invariants(scores) == []
    # The boundary headline: most divergences are SILENT (the byte-clean ceiling sits below the judge).
    for cfg in ("bfcl", "tau2"):
        assert scores[cfg].corpus_firsterracc < scoring.JUDGE_FIRSTERRACC
    # The floor is real on the error-caused slice.
    assert scores["bfcl"].slice_firsterracc >= 0.30
    assert scores["tau2"].slice_firsterracc >= 0.30
