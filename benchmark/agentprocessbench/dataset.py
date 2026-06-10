"""Loader for AgentProcessBench (RUCBM, arXiv 2603.14465) — the $0 popular-bench boundary replay.

AgentProcessBench ships 1,000 agent trajectories (4 configs × 250: `bfcl` / `tau2` / `gaia_dev` /
`hotpotqa`) with 8,509 HUMAN per-step labels (`step_labels {message_idx: +1/0/-1}`, 89.1% IAA), drawn
from four POPULAR benchmarks. It is MIT and lives in a sibling clone of
https://huggingface.co/datasets/LulaCola/AgentProcessBench — we never re-distribute it; we read a
cached copy in place and score it OFFLINE (zero LLM / network calls), the same economics as the
AgentHallu and Toolathlon replays (docs/174).

WHY THIS CORPUS, AND THE BOUNDARY IT MEASURES (docs/174):
The gold `step_labels` rate task EFFECTIVENESS (+1 advances progress / 0 neutral / -1 incorrect or
counterproductive), NOT tool-execution errors. A `-1` can sit on a `status:success` step where the
agent chose wrong LOGIC — which a byte-clean detector is blind to BY DESIGN. The firsthand probe
measured the consequence: only ~11% (bfcl) / 27% (tau2) of gold first-divergences coincide with an
env error, so the byte-clean ceiling on first-error localization is ~11-27% vs the LLM-judge's
published 65.8% FirstErrAcc. So this corpus is NOT a "match the judge" target — it is a precise
BOUNDARY measurement (where the deterministic ORACLE rung ends and the JUDGE rung must take over) plus
a deterministic FLOOR on the error-caused slice. That boundary IS the result.

THE LOAD-BEARING SCHEMA ALIGNMENT (verified on disk — the kind of thing that silently bites):
  * `step_labels` keys are MESSAGE INDICES pointing at ASSISTANT messages (the ones with tool_calls).
  * the tool RESULT for a labeled assistant step is the FOLLOWING `tool` message (idx + 1).
  * `tool_metrics[tool_name]` is an ORDERED list of per-call status dicts; the k-th invocation of a
    tool maps to `tool_metrics[name][k]`. `status` ('success'/'error') is the AUTHORITATIVE
    env-authored error channel — the message-text `content` can read "None" on a success, so a
    text-only `{"error":...}` scan UNDER-counts (tau2 flags errors in status, not always in text).

  python -m benchmark.agentprocessbench.dataset            # print a one-line corpus summary
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent

CONFIGS = ("bfcl", "tau2", "gaia_dev", "hotpotqa")
# The structured-function-calling subsets where the env authors a real error channel (the method's
# home). The free-text web-QA subsets (gaia_dev/hotpotqa) carry few/no structured error keys — the
# scorer reports them but they are not the headline (docs/174 K3).
STRUCTURED_CONFIGS = ("bfcl", "tau2")


def corpus_root() -> Path:
    """The AgentProcessBench cache dir (holding `<config>.json`, one per config).

    Resolved in order: $AGENTPROCESSBENCH_ROOT, then ../AgentProcessBench relative to this repo.
    Each `<config>.json` is a JSON list of trajectory records (the HF
    dataset dumped once with `datasets.load_dataset(..., split="test")`).
    """
    env = os.environ.get("AGENTPROCESSBENCH_ROOT")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates += [
        _REPO.parent / "AgentProcessBench",
    ]
    for c in candidates:
        if c.is_dir() and any((c / f"{cfg}.json").exists() for cfg in CONFIGS):
            return c
    raise FileNotFoundError(
        "AgentProcessBench cache not found. Dump it once with `datasets.load_dataset("
        "'LulaCola/AgentProcessBench', cfg, split='test')` for each of "
        f"{CONFIGS} into <root>/<cfg>.json (so ../AgentProcessBench/bfcl.json exists), or set "
        "$AGENTPROCESSBENCH_ROOT to that dir."
    )


def _loads(v: object) -> object:
    """The HF JSON columns arrive as either a parsed object or a JSON string — coerce to the object."""
    return json.loads(v) if isinstance(v, str) else v


@dataclass(frozen=True)
class Trajectory:
    config: str
    record: dict

    @property
    def messages(self) -> list:
        return _loads(self.record.get("messages")) or []

    @property
    def tool_metrics(self) -> dict:
        tm = _loads(self.record.get("tool_metrics"))
        return tm if isinstance(tm, dict) else {}

    @property
    def step_labels(self) -> dict:
        """{message_index(int): +1/0/-1}. Keys are coerced to int (they arrive as JSON string keys —
        the AgentHallu str/int trap, pinned by a test)."""
        raw = _loads(self.record.get("step_labels"))
        if not isinstance(raw, dict):
            return {}
        out = {}
        for k, v in raw.items():
            try:
                out[int(k)] = int(v)
            except (TypeError, ValueError):
                continue
        return out

    @property
    def final_label(self) -> Optional[int]:
        v = self.record.get("final_label")
        return int(v) if isinstance(v, int) else None

    @property
    def is_structured(self) -> bool:
        return self.config in STRUCTURED_CONFIGS

    @property
    def negative_steps(self) -> list[int]:
        """The message indices the human gold marked -1 (incorrect/counterproductive), sorted."""
        return sorted(i for i, v in self.step_labels.items() if v == -1)

    @property
    def first_negative_step(self) -> Optional[int]:
        """The gold FIRST-divergence message index (the FirstErrAcc target), or None if no -1."""
        neg = self.negative_steps
        return neg[0] if neg else None

    def step_tool_status(self) -> dict:
        """Map each ASSISTANT-message index to the env-authored status of its tool call(s).

        Walks messages in order, counting per-tool invocations, and looks up
        `tool_metrics[name][k].status` for the k-th call of each tool. Returns {assistant_msg_idx:
        "error"|"success"|...}. A step is "error" iff ANY of its tool calls returned a non-success
        status — the authoritative env channel (NOT a text scan). PURE over the loaded record.
        """
        tm = self.tool_metrics
        counters: dict[str, int] = {}
        out: dict[str, object] = {}
        for i, m in enumerate(self.messages):
            if m.get("role") != "assistant":
                continue
            statuses = []
            for tc in (m.get("tool_calls") or []):
                name = (tc.get("function", {}) or {}).get("name") or tc.get("name")
                if not name or name not in tm:
                    continue
                k = counters.get(name, 0)
                counters[name] = k + 1
                calls = tm[name]
                if isinstance(calls, list) and k < len(calls):
                    statuses.append(calls[k].get("status"))
            if statuses:
                out[i] = "error" if any(s and s != "success" for s in statuses) else "success"
        return out


def load(root: Optional[Path] = None, configs: Optional[tuple] = None) -> Iterator[Trajectory]:
    """Yield every trajectory under the cache, for the given configs (default all four)."""
    root = root or corpus_root()
    for cfg in (configs or CONFIGS):
        path = root / f"{cfg}.json"
        if not path.exists():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for rec in rows:
            yield Trajectory(config=cfg, record=rec)


def _summary() -> str:
    trajs = list(load())
    by_cfg = {}
    for t in trajs:
        by_cfg.setdefault(t.config, 0)
        by_cfg[t.config] += 1
    labeled = sum(len(t.step_labels) for t in trajs)
    return (
        f"AgentProcessBench: {len(trajs)} trajectories {dict(by_cfg)}, "
        f"{labeled} per-step gold labels. root={corpus_root()}"
    )


if __name__ == "__main__":
    print(_summary())
