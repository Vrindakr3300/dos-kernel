"""Honesty test for measure_fold_deaths — the fold-site silent-death measure.

Pins the partition logic on a tiny fixture projects-dir with KNOWN synthetic +
healthy + empty transcripts, so the $0 real-corpus headline (docs/197 §9.1) rests
on a verified measure, not a one-off script. Run:

    PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_measure_fold_deaths.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

from . import measure_fold_deaths as mfd


def _wf_dir(projects: Path, ws="ws", session="sess", wf="wf_aaaa1111-bbb") -> Path:
    d = projects / ws / session / "subagents" / "workflows" / wf
    d.mkdir(parents=True, exist_ok=True)
    return d


def _synthetic(text="API Error: ... · Rate limited", api_status=429):
    rec = {
        "type": "assistant",
        "isApiErrorMessage": True,
        "message": {
            "model": "<synthetic>", "role": "assistant",
            "stop_reason": "stop_sequence", "stop_sequence": "",
            "content": [{"type": "text", "text": text}],
        },
    }
    if api_status is not None:
        rec["apiErrorStatus"] = api_status
    return rec


def _healthy(text="Here is my finding."):
    return {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-8", "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
        },
    }


def _write(d: Path, name: str, records: list[dict]) -> None:
    (d / name).write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_partition_counts_dead_vs_healthy(tmp_path):
    projects = tmp_path / "projects"
    d = _wf_dir(projects)
    # 2 dead (synthetic), 1 healthy, 1 empty (no assistant record).
    _write(d, "agent-1.jsonl", [_synthetic()])
    _write(d, "agent-2.jsonl", [_synthetic(text="You've hit your weekly limit", api_status=None)])
    _write(d, "agent-3.jsonl", [_healthy()])
    _write(d, "agent-4.jsonl", [{"type": "user", "message": {"role": "user", "content": []}}])

    r = mfd.measure(projects)
    assert r["transcripts"] == 4
    assert r["dead"] == 3            # 2 synthetic + 1 empty
    assert r["healthy"] == 1
    assert r["witness_routes_to_dead_bucket"] == 3
    # the artifact: a naive .filter(Boolean) banks ALL non-null returns (4), the
    # witness banks only the 1 healthy — the gap (3) is the silent-death rate.
    assert r["filter_boolean_would_bank"] == 4
    assert r["witness_would_bank"] == 1
    assert r["dead_classes"].get("RATE_LIMIT") == 1
    assert r["dead_classes"].get("USAGE_LIMIT") == 1


def test_death_concentration_ranks_workflows(tmp_path):
    projects = tmp_path / "projects"
    big = _wf_dir(projects, wf="wf_big-0001")
    small = _wf_dir(projects, wf="wf_small-002")
    for i in range(9):
        _write(big, f"agent-{i}.jsonl", [_synthetic()])
    _write(big, "agent-ok.jsonl", [_healthy()])      # big: 9/10 dead
    _write(small, "agent-1.jsonl", [_synthetic()])
    _write(small, "agent-2.jsonl", [_healthy()])     # small: 1/2 dead

    r = mfd.measure(projects)
    rows = r["top_death_workflows"]
    assert rows[0]["wf"] == "wf_big-0001"
    assert rows[0]["dead"] == 9 and rows[0]["total"] == 10
    assert r["workflows_with_deaths"] == 2


def test_empty_corpus_is_clean(tmp_path):
    r = mfd.measure(tmp_path / "nonexistent")
    assert r["transcripts"] == 0
    assert r["dead"] == 0
    assert r["dead_rate"] == 0.0
