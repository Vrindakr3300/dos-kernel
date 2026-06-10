"""The Agent-Diff bench dataset reader — PURE, $0, no network (reads a local JSONL clone).

Each record in `datasets/agent-diff-bench/{test,train}.jsonl` is one write-heavy task:

  question  : the agent's PROMPT (e.g. "fix the typo in the filename …")
  answer    : the GOLD assertion spec, a JSON string — the WITNESS TARGET the env's
              AssertionEngine compares the observed diff against. The agent authors ZERO
              bytes of it (the task author wrote it). Shape:
                {"assertions":[{"diff_type":"changed","entity":"box_files",
                  "where":{"id":{"eq":"3266469077"}},
                  "expected_changes":{"name":{"to":{"eq":"…"}}}}],
                 "ignore_fields":{"global":[…]}}
  test_id   : stable id (e.g. "box_145")
  service   : slack | linear | box | calendar
  operation_type : e.g. "search+U" (search + Update) — the write families ('U'pdate /
                   'C'reate / 'D'elete present ⟺ this is a mutating task)
  info      : a JSON string with seed_template / impersonate_user_id / eval_type / tools_required

The reader does NOT depend on the Agent-Diff backend or SDK — it only parses the JSONL, so
the frozen dry-run and the unit tests run with no Docker, no DB, no model.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional


# The default location of the Agent-Diff sibling clone. Overridable via env so the bench is
# not hard-wired to one machine (the SubstrateConfig "resolve against a root, never __file__"
# discipline, applied to an external dataset): the default points at a sibling clone of this
# repo (../agent-diff), derived from this file's location, never a hardcoded machine path.
_DEFAULT_AGENTDIFF_ROOT = str(Path(__file__).resolve().parents[2].parent / "agent-diff")
_ENV_ROOT = "AGENT_DIFF_ROOT"
_DATASET_REL = ("datasets", "agent-diff-bench")

# The write-operation letters in `operation_type` (e.g. "search+U", "C", "search+U+D").
# Presence of ANY of these ⟺ the task mutates state ⟺ a confident "done" is a WRITE claim.
_WRITE_OPS = frozenset({"C", "U", "D"})


def agentdiff_root() -> Path:
    """The Agent-Diff clone root (env override › default). Raises if absent."""
    root = Path(os.environ.get(_ENV_ROOT, _DEFAULT_AGENTDIFF_ROOT))
    if not root.exists():
        raise FileNotFoundError(
            f"Agent-Diff clone not found at {root!r} (set {_ENV_ROOT} to override). "
            "The dataset is an external sibling clone; the gate/A/B tests skip without it."
        )
    return root


def dataset_dir() -> Path:
    """The `datasets/agent-diff-bench` dir under the clone root."""
    d = agentdiff_root().joinpath(*_DATASET_REL)
    if not d.exists():
        raise FileNotFoundError(f"Agent-Diff dataset dir not found: {d}")
    return d


@dataclass(frozen=True)
class BenchTask:
    """One write-heavy bench task — the prompt + the GOLD assertion spec (witness target).

    `gold_spec` is the parsed `answer` (the assertion spec). `is_write_task` is True iff the
    operation_type names a mutating op (C/U/D) — the only tasks a confident "done" can
    OVER-claim a write on. Read-only tasks ("search", retrieval) cannot be over-claimed as a
    write, so the gate is a no-op on them (the `NO_CLAIM` path in `gate.py`).
    """
    test_id: str
    service: str
    question: str
    gold_spec: dict[str, Any]
    operation_type: str
    task_horizon: Optional[int] = None
    info: dict[str, Any] = field(default_factory=dict)
    split: str = ""

    @property
    def is_write_task(self) -> bool:
        """True iff operation_type names any of C/U/D — a mutating task."""
        return any(tok in _WRITE_OPS for tok in self.operation_type.replace("+", " ").split())

    @property
    def expected_entities(self) -> tuple[str, ...]:
        """The distinct entities the gold spec asserts on (e.g. ('box_files',)) — the
        env-authored set of tables a correct run must touch."""
        seen: list[str] = []
        for a in self.gold_spec.get("assertions", []) or []:
            ent = a.get("entity")
            if ent and ent not in seen:
                seen.append(ent)
        return tuple(seen)

    @property
    def n_assertions(self) -> int:
        return len(self.gold_spec.get("assertions", []) or [])


def _parse_maybe_json(value: Any) -> Any:
    """The dataset stores `answer`/`info` as JSON STRINGS; tolerate already-parsed dicts."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, dict):
        return value
    return {}


def _row_to_task(row: dict[str, Any], split: str) -> BenchTask:
    info = _parse_maybe_json(row.get("info", {}))
    horizon = row.get("task_horizon")
    return BenchTask(
        test_id=str(row.get("test_id", "")),
        service=str(row.get("service", "")),
        question=str(row.get("question", "")),
        gold_spec=_parse_maybe_json(row.get("answer", {})),
        operation_type=str(row.get("operation_type", "")),
        task_horizon=int(horizon) if isinstance(horizon, (int, float)) else None,
        info=info if isinstance(info, dict) else {},
        split=split,
    )


def iter_tasks(split: str = "test") -> Iterator[BenchTask]:
    """Yield every `BenchTask` in a split ('test' | 'train'). Reads the local JSONL clone."""
    if split not in ("test", "train"):
        raise ValueError(f"unknown split {split!r}; expected 'test' or 'train'")
    path = dataset_dir() / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"split file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield _row_to_task(json.loads(line), split)


def load_tasks(split: str = "test") -> list[BenchTask]:
    """Eager list of `iter_tasks`."""
    return list(iter_tasks(split))
