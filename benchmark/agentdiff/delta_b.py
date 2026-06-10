"""The LIVE causal ΔB runner for Agent-Diff (docs/228→229) — the out-of-loop payoff.

WHAT FROZEN COULD NOT MEASURE
-----------------------------
`live_loop.frozen_ab` proves the gate BLOCKS the right rows (a synthetic over-claim, the
real assertion engine refuting it) — but a frozen replay has no SECOND run, so it cannot
produce a CAUSAL ΔB. This module is that second run: a downstream peer B that ACTUALLY
re-executes off whatever the gate published, under two arms, so the difference in B's
success rate is a real flipped inheritance, not a re-projected rate.

THE CAUSAL CHAIN per task (docs/229 §1, Design A):
  1. run A live           → ARow (the forgeable claim + the env witness `passed`)
  2. gate.admit(claim, passed, score)  → AdmitDecision (BLOCK iff confident write × refuted)
  3. AHandoff.from_row    → the distilled handoff (claim + gate decision)
  4. THE OVER-CLAIM SLICE = rows where A made a confident write the env REFUTED (is_overclaim)
  5. on that slice, run peer B TWICE against a FRESH GOLD env (same start state both arms):
       believe    — B inherits A's raw claim  (handoff_text(a, BELIEVE))
       adjudicate — B inherits the gate verdict (handoff_text(a, ADJUDICATE): on a BLOCKED
                    over-claim, the env-verified correction — "the prior write did NOT land")
  6. ΔB = success(B|adjudicate) − success(B|believe) on the over-claim slice.

A positive ΔB is the causal payoff: telling B the truth (the prior write failed) makes B more
likely to succeed than letting B inherit the lie. ΔB≈0 is the honest, arc-consistent negative
(docs/229: at the EASY hop believe-B SELF-RECOVERS — it re-checks state and fixes the phantom
anyway, so the correction buys nothing; the payoff localizes to a weaker/multi-hop consumer).
Either way the number is MEASURED, not assumed.

COST + RESUMABILITY
-------------------
PAID (Gemini + the backend). Resumable: A-rows are cached to `<out_dir>/a_rows.jsonl` and the
per-arm B-rows to `<out_dir>/b_<arm>.jsonl`, keyed by test_id, so a re-run skips completed
work. A token-budget guard stops cleanly before overspending (an over-budget stop is a partial
result, never a crash). The harness emits a compact PROGRESS line per task for a Monitor.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .dataset import BenchTask, load_tasks
from .gate import admit, AdmitDecision
from .live_agent import ARow, run_a_task
from .peer_b import AHandoff, handoff_text, BELIEVE, ADJUDICATE, ARMS


# A rough per-task token estimate (ReAct loop ~ a few k tokens/task), used only for the budget
# guard's coarse stop — the real spend is whatever Gemini bills. Deliberately conservative.
_APPROX_TOKENS_PER_TASK = 6000


@dataclass
class DeltaBResult:
    """The live ΔB measurement over a run."""
    model: str
    n_tasks: int
    n_confident_write: int        # A-runs that made a confident write-claim
    n_overclaim: int              # confident write × env-refuted (the slice)
    n_blocked: int                # gate BLOCKs (== n_overclaim by construction of the gate)
    b_success_believe: int        # peer-B successes on the slice under believe
    b_success_adjudicate: int     # peer-B successes on the slice under adjudicate
    delta_b: int                  # adjudicate − believe (the causal payoff, in tasks)
    n_b_runs: int                 # how many B-runs actually executed (2 × slice, minus errors)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_jsonl(path: Path) -> dict[str, dict]:
    """Load a cache file keyed by test_id (last write wins). Missing file → empty."""
    out: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = str(row.get("test_id", ""))
            if tid:
                out[tid] = row
    return out


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _gate_for_row(row: ARow) -> AdmitDecision:
    """Run the write-admission gate on one A-row (the docs/228 join)."""
    return admit(
        row.answer_excerpt or "",
        passed=row.passed,
        subject=row.test_id,
        failures=row.failures,
        score=row.score,
    )


def _select_tasks(split: str, sample: Optional[int], services: Optional[tuple[str, ...]]) -> list[BenchTask]:
    """Write tasks for the run: optionally filtered by service, deterministically capped.

    Over-claims occur on the HARDER write tasks (longer horizon / more assertions), so we sort
    by descending difficulty (assertion count, then horizon) before the cap — concentrating the
    paid budget where the over-claim slice is most likely to be non-empty (docs/228: a capable
    live policy makes easy over-claims evaporate; the slice lives in the hard tail).
    """
    tasks = [t for t in load_tasks(split) if t.is_write_task]
    if services:
        tasks = [t for t in tasks if t.service in services]
    tasks.sort(key=lambda t: (t.n_assertions, t.task_horizon or 0), reverse=True)
    if sample is not None and sample < len(tasks):
        tasks = tasks[:sample]
    return tasks


def run_delta_b(
    *,
    model: str = "gemini-2.5-flash",
    split: str = "test",
    sample: Optional[int] = 20,
    services: Optional[tuple[str, ...]] = None,
    out_dir: str = "benchmark/agentdiff/live_results",
    budget_tokens: Optional[int] = None,
    max_iterations: int = 30,
    base_url: str = "http://localhost:8000",
    api_key: str = "local",
) -> DeltaBResult:
    """Run the live believe-vs-adjudicate ΔB measurement. Returns the causal payoff.

    Drives A live over the selected write tasks, gates each, then on the over-claim slice runs
    peer B under both arms against a fresh gold env. Resumable + budget-guarded.
    """
    from agent_diff import AgentDiff  # lazy: needs the SDK on path

    if not os.environ.get("GEMINI_API_KEY"):
        return DeltaBResult(model=model, n_tasks=0, n_confident_write=0, n_overclaim=0,
                            n_blocked=0, b_success_believe=0, b_success_adjudicate=0,
                            delta_b=0, n_b_runs=0, notes="no GEMINI_API_KEY — set it + run the backend on :8000")

    out = Path(out_dir)
    a_cache_path = out / "a_rows.jsonl"
    b_cache = {arm: out / f"b_{arm}.jsonl" for arm in ARMS}
    a_cache = _load_jsonl(a_cache_path)
    b_done = {arm: _load_jsonl(b_cache[arm]) for arm in ARMS}

    client = AgentDiff(base_url=base_url, api_key=api_key)
    tasks = _select_tasks(split, sample, services)
    print(f"PROGRESS delta-b-start model={model} split={split} write_tasks={len(tasks)} "
          f"sample={sample} out={out_dir}", flush=True)

    spent_tokens = 0

    def over_budget() -> bool:
        return budget_tokens is not None and spent_tokens >= budget_tokens

    # --- Phase 1: run A live over every selected write task, gate each ----------------------
    a_rows: list[ARow] = []
    overclaim_tasks: list[tuple[BenchTask, AHandoff]] = []
    for i, task in enumerate(tasks):
        if task.test_id in a_cache:
            row = ARow(**{k: v for k, v in a_cache[task.test_id].items()
                          if k in ARow.__dataclass_fields__})
            row.failures = tuple(row.failures)
        else:
            if over_budget():
                print(f"PROGRESS budget-stop phase=A spent~{spent_tokens} tok", flush=True)
                break
            row = run_a_task(client, task, model=model, max_iterations=max_iterations)
            spent_tokens += _APPROX_TOKENS_PER_TASK
            _append_jsonl(a_cache_path, row.to_dict())
        a_rows.append(row)

        decision = _gate_for_row(row)
        a = AHandoff(service=row.service, test_id=row.test_id,
                     claim_text=row.answer_excerpt, confident_write=decision.confident_write,
                     admit=decision.admit, passed=row.passed, score=row.score)
        flag = "OVERCLAIM" if a.is_overclaim else ("WRITE" if decision.confident_write else "noclaim")
        print(f"PROGRESS A {i+1}/{len(tasks)} {row.test_id} passed={row.passed} "
              f"claim={decision.confident_write} admit={decision.admit} [{flag}]"
              + (f" ERR={row.error[:60]}" if row.error else ""), flush=True)
        if a.is_overclaim:
            overclaim_tasks.append((task, a))

    n_conf = sum(1 for r in a_rows if _gate_for_row(r).confident_write)
    n_over = len(overclaim_tasks)
    # the gate blocks exactly the over-claim slice (confident write × refuted): n_blocked == n_over.
    n_blocked = sum(1 for _t, a in overclaim_tasks if not a.admit)
    print(f"PROGRESS phase-A-done confident_write={n_conf} overclaim_slice={n_over} "
          f"blocked={n_blocked}", flush=True)

    # --- Phase 2: on the over-claim slice, run peer B under BOTH arms -----------------------
    b_success = {BELIEVE: 0, ADJUDICATE: 0}
    n_b_runs = 0
    for j, (task, a) in enumerate(overclaim_tasks):
        for arm in ARMS:
            tid = task.test_id
            if tid in b_done[arm]:
                br = b_done[arm][tid]
                if bool(br.get("passed")):
                    b_success[arm] += 1
                n_b_runs += 1
                continue
            if over_budget():
                print(f"PROGRESS budget-stop phase=B spent~{spent_tokens} tok", flush=True)
                break
            context = handoff_text(a, arm)
            b_row = run_a_task(client, task, model=model, max_iterations=max_iterations,
                               inherited_context=context)
            spent_tokens += _APPROX_TOKENS_PER_TASK
            rec = b_row.to_dict()
            rec["arm"] = arm
            _append_jsonl(b_cache[arm], rec)
            if b_row.passed is True:
                b_success[arm] += 1
            n_b_runs += 1
            print(f"PROGRESS B[{arm}] {j+1}/{n_over} {tid} passed={b_row.passed}"
                  + (f" ERR={b_row.error[:60]}" if b_row.error else ""), flush=True)
        else:
            continue
        break  # propagated budget-stop from the inner loop

    delta = b_success[ADJUDICATE] - b_success[BELIEVE]
    result = DeltaBResult(
        model=model, n_tasks=len(a_rows), n_confident_write=n_conf, n_overclaim=n_over,
        n_blocked=n_blocked, b_success_believe=b_success[BELIEVE],
        b_success_adjudicate=b_success[ADJUDICATE], delta_b=delta, n_b_runs=n_b_runs,
        notes=("over-claim slice empty — a capable live policy did not over-claim on this "
               "sample; widen the sample or pick a harder split" if n_over == 0 else ""),
    )
    print(f"PROGRESS delta-b-done overclaim={n_over} "
          f"B_believe={b_success[BELIEVE]} B_adjudicate={b_success[ADJUDICATE]} "
          f"DELTA_B={delta}", flush=True)
    (out / "delta_b_result.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return result
