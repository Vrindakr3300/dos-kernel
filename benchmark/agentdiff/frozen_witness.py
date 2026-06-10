"""The FROZEN witness — the env-authored verdict for the $0 dry-run, NO Docker / NO model.

The whole point of the docs/228 arc is that the correctness witness is authored by the ENV,
not the agent. Agent-Diff's witness is `AssertionEngine.evaluate(diff)` — a structured
`{passed, failures, score}` over the OBSERVED diff vs the GOLD assertion spec. Crucially, the
assertion engine is a near-stdlib leaf (it imports only `logging` + stdlib), so we can run
the REAL engine over a SYNTHETIC diff with no database and no backend process. The frozen
witness is therefore not a stand-in for the verdict logic — it IS the production assertion
engine; only the *diff it judges* is synthesized rather than computed from live DB snapshots.

Two synthetic diffs per task model the two run outcomes the gate cares about:

  * OVER-CLAIM run  = an EMPTY diff. The agent claimed "done" but nothing landed. Verified
    (frozen_witness_test): the real assertion engine returns passed=False for ALL 224 tasks
    on an empty diff — every write assertion "expected at least 1 match but got 0". This is
    the witness REFUTING every over-claimed write — the slice J is counted on.
  * HONEST run      = a GOLD-SATISFYING diff reconstructed from the spec's eq-predicates.
    Returns passed=True where the spec is eq-only (the clean control); on regex/contains/
    multi-predicate specs the reconstruction is partial, so `simulate_honest` reports whether
    it actually achieved a pass (the dry-run uses only the cleanly-passing subset for the
    honest control, and ALL tasks for the over-claim slice).

The agent authors ZERO bytes of either path here — the diff is synthesized by THIS module
(a deterministic JUDGE, the actor-witness split) and the verdict is the env's own engine.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .dataset import BenchTask, agentdiff_root


# --- the env assertion engine, imported from the Agent-Diff backend clone ---------------

def _assertion_engine_cls():
    """Import the REAL `AssertionEngine` from the Agent-Diff backend clone (near-stdlib leaf).

    Done lazily + path-injected so this module imports at $0 when the clone is absent (the
    pure claim/gate tests must run without it). Raises FileNotFoundError (caught as a skip)
    when the clone is not on disk.

    NB: imported as `src.platform.…` from the backend ROOT, NOT `platform.…` from
    `backend/src` — the backend's package root is `src` (its own modules say
    `from src.platform.isolationEngine …`), and importing a bare `platform` package would
    collide with Python's stdlib `platform` module (which is already imported under pytest and
    would shadow it). Anchoring on `src.` sidesteps the collision.
    """
    backend_root = agentdiff_root() / "backend"
    if not (backend_root / "src").exists():
        raise FileNotFoundError(f"Agent-Diff backend src not found: {backend_root / 'src'}")
    p = str(backend_root)
    if p not in sys.path:
        sys.path.insert(0, p)
    from src.platform.evaluationEngine.assertion import AssertionEngine  # type: ignore
    return AssertionEngine


@dataclass(frozen=True)
class WitnessResult:
    """The env-authored verdict over one (synthetic or live) diff — Agent-Diff's witness.

    `passed`/`failures`/`score` mirror the SDK's `TestResultResponse` exactly, so the gate's
    witness-wrapping is identical whether the diff is frozen-synthetic or live-from-DB.
    """
    passed: bool
    failures: tuple[str, ...]
    score: dict[str, Any]

    @classmethod
    def from_eval(cls, result: dict[str, Any]) -> "WitnessResult":
        return cls(
            passed=bool(result.get("passed", False)),
            failures=tuple(result.get("failures", []) or []),
            score=dict(result.get("score", {}) or {}),
        )


def evaluate_diff(gold_spec: dict[str, Any], diff: dict[str, Any], *, strict: bool = False) -> WitnessResult:
    """Run the REAL assertion engine over a diff → the env-authored `WitnessResult`.

    `strict=False` by default: a frozen-synthetic honest diff carries only the asserted
    fields, so strict (no-extra-changed-fields) would spuriously fail it. The live run uses
    whatever strictness the task spec declares.
    """
    AssertionEngine = _assertion_engine_cls()
    spec = {**gold_spec}
    if "strict" not in spec:
        spec["strict"] = strict
    return WitnessResult.from_eval(AssertionEngine(spec).evaluate(diff))


# --- synthetic diffs --------------------------------------------------------------------

_EMPTY_DIFF: dict[str, list] = {"inserts": [], "updates": [], "deletes": []}


def overclaim_diff() -> dict[str, list]:
    """The OVER-CLAIM run's observed diff: empty. The agent claimed done; nothing landed.

    Verified to fail the assertion engine for all 224 tasks (every write assertion needs ≥1
    matching row). Domain-free — a single empty diff models the canonical over-claim for any
    task, which is exactly the failure mode the gate exists to catch.
    """
    return {"inserts": [], "updates": [], "deletes": []}


def honest_diff(gold_spec: dict[str, Any]) -> dict[str, list]:
    """Reconstruct a GOLD-SATISFYING diff from the spec's eq-predicates (the honest control).

    Builds one diff row per assertion that satisfies its `where` (eq preds) and
    `expected_changes` (eq `to`). Faithful for eq-only specs; partial for regex/contains/
    multi-op specs (those are reported by `simulate_honest` as not-cleanly-passing).
    """
    inserts: list[dict] = []
    updates: list[dict] = []
    deletes: list[dict] = []
    for a in gold_spec.get("assertions", []) or []:
        ent = a.get("entity")
        dt = a.get("diff_type")
        row: dict[str, Any] = {}
        for key, pred in (a.get("where", {}) or {}).items():
            if isinstance(pred, dict) and "eq" in pred:
                row[key] = pred["eq"]
            elif not isinstance(pred, dict):
                row[key] = pred
        if dt == "added":
            r = dict(row); r["__table__"] = ent; inserts.append(r)
        elif dt == "removed":
            r = dict(row); r["__table__"] = ent; deletes.append(r)
        elif dt == "changed":
            before = dict(row)
            after = dict(row)
            for fld, chg in (a.get("expected_changes", {}) or {}).items():
                to = chg.get("to") if isinstance(chg, dict) else chg
                if isinstance(to, dict) and "eq" in to:
                    after[fld] = to["eq"]
                else:
                    after[fld] = "__SIMULATED_NEW__"
                before[fld] = "__SIMULATED_OLD__"
            updates.append({"__table__": ent, "before": before, "after": after})
    return {"inserts": inserts, "updates": updates, "deletes": deletes}


def simulate_overclaim(task: BenchTask) -> WitnessResult:
    """The env verdict on the canonical over-claim (empty diff) for one task — should REFUTE."""
    return evaluate_diff(task.gold_spec, overclaim_diff())


def simulate_honest(task: BenchTask) -> WitnessResult:
    """The env verdict on the reconstructed gold-satisfying diff — passes for eq-only specs."""
    return evaluate_diff(task.gold_spec, honest_diff(task.gold_spec))
