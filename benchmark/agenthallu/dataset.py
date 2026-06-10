"""Loader for the AgentHallu corpus (arXiv 2601.06818), the $0 hallucination-attribution replay.

AgentHallu ships 693 agent trajectories (443 hallucinated + 250 clean) across 7 frameworks, each
with a per-step GOLD label (`hallucination_step`, 1-indexed) + category/sub-category. The data is
CC-BY-4.0 and lives in a sibling clone of https://github.com/liuxuannan/AgentHallu — we never
re-distribute it; we read it in place and score against it OFFLINE (zero LLM / network calls), the
same economics as the Toolathlon-Trajectories replay (docs/166 §4).

The corpus root is resolved (in order): $AGENTHALLU_ROOT, then ../AgentHallu/AgentHallu relative to
this repo. A record is one trajectory JSON.

  python -m benchmark.agenthallu.dataset            # print a one-line corpus summary

KEY SCHEMA FACT (verified on disk, the kind of thing that bites): `hallucination_step` is a STRING
("6"), while each `history[i]["step"]` is an INT (6). Always coerce via `gold_step()` — comparing
the raw string to the int silently never matches and reads as "detector found nothing."
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent


def corpus_root() -> Path:
    """The AgentHallu data dir (the inner one holding the 7 framework folders)."""
    env = os.environ.get("AGENTHALLU_ROOT")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates += [
        _REPO.parent / "AgentHallu" / "AgentHallu",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError(
        "AgentHallu corpus not found. Clone https://github.com/liuxuannan/AgentHallu next to this "
        "repo (so ../AgentHallu/AgentHallu exists), or set $AGENTHALLU_ROOT to its data dir."
    )


def gold_step(record: dict) -> Optional[int]:
    """The 1-indexed gold first-divergence step as an INT, or None (clean / unlabeled)."""
    v = record.get("hallucination_step")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Trajectory:
    path: Path
    framework: str
    record: dict

    @property
    def is_hallucination(self) -> bool:
        return str(self.record.get("is_hallucination")).strip().lower() == "true"

    @property
    def category(self) -> Optional[str]:
        return self.record.get("hallucination_category")

    @property
    def subcategory(self) -> Optional[str]:
        return self.record.get("hallucination_subcategory")

    @property
    def is_tool_use(self) -> bool:
        return "Tool-Use" in str(self.category or "")

    @property
    def gold(self) -> Optional[int]:
        return gold_step(self.record)

    @property
    def history(self) -> list:
        return self.record.get("history") or []


def load(root: Optional[Path] = None) -> Iterator[Trajectory]:
    """Yield every trajectory under the corpus, sorted by (framework, filename) for determinism."""
    root = root or corpus_root()
    for path in sorted(root.glob("*/*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        yield Trajectory(path=path, framework=path.parent.name, record=rec)


def _summary() -> str:
    trajs = list(load())
    hall = [t for t in trajs if t.is_hallucination]
    tool = [t for t in hall if t.is_tool_use]
    return (
        f"AgentHallu: {len(trajs)} trajectories "
        f"({len(hall)} hallucinated / {len(trajs) - len(hall)} clean), "
        f"{len(tool)} Tool-Use. root={corpus_root()}"
    )


if __name__ == "__main__":
    print(_summary())
