"""Test the LIVE-results adapter on FROZEN synthetic dirs — zero benchmark/network/LLM access.

`live_adapter` is the only new I/O for the docs/160 live run: it re-keys a downloaded task dir
(`traj_log.json` + `eval_res.json` + `status.json`) into the dataset-shaped record the docs/157
`trajectory.parse_record` already understands, so the SAME detectors score a live run unchanged.
These tests build tiny on-disk fixtures with `tmp_path` and assert the re-key + the skip discipline,
mirroring `test_toolathlon_replay.py`'s "pure over a parsed record" keystone.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.toolathlon.live_adapter import (
    iter_live_trajectories,
    live_record,
)
from benchmark.toolathlon.replay import dangling_fired, tool_stream_fired


def _write_task(
    results_dir: Path,
    task: str,
    *,
    messages,
    eval_pass=None,
    status_eval=None,
    write_traj=True,
):
    """Lay down a synthetic live task dir under <results_dir>/finalpool/<task>/."""
    td = results_dir / "finalpool" / task
    td.mkdir(parents=True, exist_ok=True)
    if write_traj:
        (td / "traj_log.json").write_text(
            json.dumps({"messages": messages, "key_stats": {}}), encoding="utf-8"
        )
    if eval_pass is not None:
        (td / "eval_res.json").write_text(
            json.dumps({"pass": eval_pass, "failure": "" if eval_pass else "x"}),
            encoding="utf-8",
        )
    if status_eval is not None:
        (td / "status.json").write_text(
            json.dumps({"preprocess": "done", "running": "done", "evaluation": status_eval}),
            encoding="utf-8",
        )
    return td


def test_live_record_rekeys_eval_pass_to_task_status(tmp_path):
    td = _write_task(tmp_path, "t", messages=[{"role": "user", "content": "hi"}], eval_pass=False)
    rec = live_record(td)
    assert rec["task_name"] == "t"
    assert rec["task_status"] == {"evaluation": False}  # pass:false -> evaluation:false
    assert isinstance(rec["messages"], list)


def test_live_record_prefers_eval_res_over_status(tmp_path):
    # eval_res.pass wins when both present (it is the verifier's own bool).
    td = _write_task(
        tmp_path, "t", messages=[{"role": "user", "content": "hi"}], eval_pass=True, status_eval=False
    )
    assert live_record(td)["task_status"]["evaluation"] is True


def test_live_record_falls_back_to_status_evaluation(tmp_path):
    td = _write_task(tmp_path, "t", messages=[{"role": "user", "content": "hi"}], status_eval=True)
    assert live_record(td)["task_status"]["evaluation"] is True


def test_live_record_none_when_no_trajectory(tmp_path):
    # a task whose download errored before traj_log.json -> skipped, never guessed.
    td = _write_task(tmp_path, "t", messages=[], eval_pass=False, write_traj=False)
    assert live_record(td) is None


def test_iter_skips_dirs_without_trajectory(tmp_path):
    _write_task(tmp_path, "good", messages=[{"role": "user", "content": "hi"}], eval_pass=False)
    _write_task(tmp_path, "broken", messages=[], eval_pass=False, write_traj=False)
    names = {tj.task_name for tj in iter_live_trajectories(tmp_path)}
    assert names == {"good"}  # broken (no traj) is dropped


def test_detectors_run_unchanged_over_a_live_dir(tmp_path):
    # dangling: terminal turn admits open work, nothing env-authored acts after -> fires.
    msgs = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": "I still need to finish writing the output file next."},
    ]
    _write_task(tmp_path, "dangle", messages=msgs, eval_pass=False)
    # tool_stream: identical (tool,args,result) triple repeated -> fires.
    rep = [
        {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "ls", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "same"},
        {"role": "assistant", "tool_calls": [{"id": "2", "function": {"name": "ls", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "2", "content": "same"},
        {"role": "assistant", "tool_calls": [{"id": "3", "function": {"name": "ls", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "3", "content": "same"},
    ]
    _write_task(tmp_path, "loop", messages=rep, eval_pass=False)

    by_name = {tj.task_name: tj for tj in iter_live_trajectories(tmp_path)}
    assert dangling_fired(by_name["dangle"]) is True
    assert tool_stream_fired(by_name["loop"]) is True
