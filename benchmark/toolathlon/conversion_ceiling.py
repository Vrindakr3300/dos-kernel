"""The $0 offline CONVERSION-CEILING estimator — an UPPER BOUND on the pass-rate lift a DOS
WARN re-surface could buy, computed from the frozen trajectories with zero API spend.

WHY THIS EXISTS (the gate it answers)
=====================================
The replay (docs/157) measures DETECT, not FIX: a detector fires on a frozen run, but the run
already ended, so there is no lift number. A paid live A/B would measure FIX — but it costs money
and the prior A/Bs (docs/144) found the real lift is small (WARN +4.2pp at best, BLOCK/DEFER
near-zero or negative). Before spending again we want a CEILING: *what is the most a perfect WARN
could possibly buy on THIS corpus?* If the ceiling is tiny, a paid A/B is not worth running; if a
particular model has real headroom, that is where to aim the spend.

This is a **ceiling, NOT a prediction.** It assumes every "recoverable" fire converts fail->pass,
which a real WARN will NEVER achieve — docs/144's live A/B converted a *fraction* of even the
WARN-winning arm. Read `max_lift_pp` as "you cannot possibly beat this," never as "you will get
this." The real lift is a FRACTION of the ceiling (docs/144 measured WARN realizing roughly a
quarter-to-a-third of its theoretical reach on the tasks where it mattered).

WHAT MAKES A FIRE "RECOVERABLE" (the load-bearing definition)
=============================================================
A detector fire is RECOVERABLE iff a WARN could plausibly convert fail->pass — which requires that
the value the agent needed was ALREADY in its own trajectory and it just failed to USE it. A WARN
re-surfaces bytes the agent already holds; it authors no new step and no plan (the docs/143 −9pp
lesson made structural). So a fire is recoverable ONLY when re-presenting an already-present value
could unblock the next step:

  * tool_stream REPEATING/STALLED — the agent re-issued the SAME (tool, args, result) triple N
    times, so the result is in hand. RECOVERABLE iff that repeated result is USABLE DATA: non-empty,
    not an error envelope, not a "tool not found" resolution failure, not a "no output" null, not an
    eventual-consistency "still converting" poll. The honest split: ~half of tool_stream fires are
    the agent looping on an ERROR the env keeps returning (status-400/404, a Python traceback, a
    missing tool) — re-surfacing "you already got status 400" cannot help, the error is the wall, so
    those are NOT recoverable. Only a loop over genuinely usable bytes is.

  * dangling_intent — the agent stopped saying "I still need to X". A WARN ("you said you still
    need X, and no tool ran after — continue") buys one more turn. RECOVERABLE iff the trajectory
    shows the prerequisite for X was plausibly satisfied — heuristic: at least one USABLE
    (non-error) env-authored tool result landed earlier in the run, so the agent had something to
    act on and a nudge could let it finish.

  * terminal_error — the agent stopped on an unresolved structured env error. Default NON-recoverable
    (conservative): the error IS the wall, and a WARN re-surfacing the error cannot remove it. (We
    do NOT credit "a prior alternative success exists" here — that would be the planner lever DOS
    forfeits by doctrine, and it would inflate the ceiling on the weakest evidence. So
    terminal_error contributes ZERO recoverable fires; stated plainly so the ceiling stays honest.)

THE SAFE DIRECTION (why the usable-data grammar is deliberately broad)
======================================================================
This is an UPPER bound, so the conservative error is to UNDER-count recoverable fires (a lower
ceiling). The usable-data grammar is therefore deliberately broad — it rejects a result on any
error/4xx/5xx/no-output/poll shape, even at the risk of rejecting a genuine payload that merely
*contains* the word "error" (e.g. `{"error": null}` in a still-converting poll). Over-rejecting only
LOWERS the ceiling, which is the honest direction for an upper bound: we would rather under-state
the headroom than over-promise it. A fire we are unsure about is counted as NOT recoverable.

PROVENANCE / BYTE-CLEANLINESS
=============================
Recoverability reads ENV-AUTHORED result bytes only (the gym MCP server produced them; the judged
agent did not) by a FIXED, content-blind grammar — the same §5a provenance line `tool_stream`
rides. The agent cannot forge which of its repeated results count as "usable", so the verdict is
provenance-of-an-env-authored-value, never a forgeable satisfaction predicate.

  python -m benchmark.toolathlon.conversion_ceiling            # print the per-model + corpus ceiling
  python -m benchmark.toolathlon.conversion_ceiling --json     # the full result as JSON
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from dos.tool_stream import DEFAULT_POLICY as TS_POLICY, StreamPolicy, ToolStream, classify_stream

from .dataset import DEFAULT_CACHE, iter_trajectories
from .trajectory import (
    Trajectory,
    _digest,
    _is_local_noop_tool,
    _tool_msg_name,
    is_struct_error,
    normalize_result_bytes,
)
from .replay import run_row, traj_tool_steps

_HERE = Path(__file__).resolve().parent
_DEFAULT_ROWS = _HERE / "_results" / "replay_all_rows.csv"


# ---------------------------------------------------------------------------
# The usable-data grammar: is an ENV-authored result a value a WARN could re-surface to UNBLOCK?
# ---------------------------------------------------------------------------
#
# Broad on purpose (the safe direction for an upper bound — see the module note). Rejects a result
# if it is empty, a structured error envelope (the tight `is_struct_error` grammar), OR matches one
# of the looser error/no-output/poll shapes below. Each rejection only LOWERS the ceiling.
_NOT_USABLE = re.compile(
    r"not found in agent"           # MCP tool-resolution failure ("Tool X not found in agent ...")
    r"|not available|no such tool|unknown tool"
    r"|error executing"             # python-execute soft error ("Error executing Python code: ...")
    r"|error running tool"          # MCP gateway soft error ("Error running tool excel-...: ...")
    r"|\btraceback\b|\bexception\b"
    r"|expecting value"             # JSON-decode failure in an executor result
    r"|no console output produced"  # executor ran but produced no usable output
    r"|return code:\s*[1-9]"        # non-zero process exit
    r'|"status"\s*:\s*[45]\d\d'     # an HTTP 4xx/5xx envelope returned as the result
    r"|\bstatus\b.{0,12}\bconverting\b"  # an eventual-consistency 'still converting' poll (not data)
    r"|\bfailed\b|\berror\b",       # loose substrings — over-broad on purpose (lowers the ceiling)
    re.IGNORECASE,
)


def is_usable_result(content: Optional[str]) -> bool:
    """True iff an ENV-authored tool result is USABLE DATA — a value a WARN could re-surface to
    unblock the next step. PURE. Rejects empty / error-envelope / tool-not-found / no-output /
    still-converting-poll results. Deliberately broad (over-rejection lowers the ceiling, the safe
    direction for an upper bound)."""
    c = content or ""
    if not c.strip():
        return False
    if is_struct_error(c):
        return False
    if _NOT_USABLE.search(c):
        return False
    return True


# ---------------------------------------------------------------------------
# The repeated-step result: map a tool_stream fire back to the env bytes the agent looped on.
# ---------------------------------------------------------------------------
def _peak_repeated_result(traj: Trajectory, policy: StreamPolicy = TS_POLICY) -> Optional[str]:
    """The raw ENV-authored result content of the step the run REPEATED on (the value the agent had
    in hand and looped over), or None if the run never repeated. Folds `classify_stream` over every
    growing prefix to find the PEAK repeat (the same peak semantics `tool_stream_peak` uses), then
    maps the peak `repeated_step.result_digest` back to a `tool` message's content.

    PURE given the trajectory. Reuses the exact digest pipeline `to_tool_stream` uses
    (`normalize_result_bytes` -> `_digest`) so the mapping is byte-faithful to what fired."""
    steps = traj_tool_steps(traj)
    best = None
    for i in range(1, len(steps) + 1):
        v = classify_stream(ToolStream(steps=tuple(steps[:i])), policy)
        if v.repeated_step is not None and (best is None or v.repeat_run > best.repeat_run):
            best = v
    if best is None or best.repeated_step is None:
        return None
    target = best.repeated_step.result_digest
    for m in traj.messages:
        if m.get("role") != "tool":
            continue
        c = str(m.get("content", ""))
        if _digest(normalize_result_bytes(c)) == target:
            return c
    return None


def _has_prior_usable_result(traj: Trajectory) -> bool:
    """True iff at least one USABLE (non-error) ENV-authored, non-local-noop tool result landed in
    the run — the dangling-recoverability prerequisite ("the agent had something to act on"). PURE."""
    for m in traj.messages:
        if m.get("role") != "tool":
            continue
        if _is_local_noop_tool(_tool_msg_name(m, traj.messages)):
            continue
        if is_usable_result(str(m.get("content", ""))):
            return True
    return False


# ---------------------------------------------------------------------------
# Per-trajectory recoverability: does ANY fire on this run admit a plausible WARN conversion?
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FireRecoverability:
    """Whether each detector fired on a run, and whether that fire is RECOVERABLE (a WARN could
    plausibly convert fail->pass because the needed value was already in the trajectory)."""

    tool_stream_fired: bool
    tool_stream_recoverable: bool
    dangling_fired: bool
    dangling_recoverable: bool
    terminal_error_fired: bool
    terminal_error_recoverable: bool  # always False (terminal_error is non-recoverable by re-surface)

    @property
    def any_fired(self) -> bool:
        return self.tool_stream_fired or self.dangling_fired or self.terminal_error_fired

    @property
    def any_recoverable(self) -> bool:
        return (
            self.tool_stream_recoverable
            or self.dangling_recoverable
            or self.terminal_error_recoverable
        )


def classify_recoverability(traj: Trajectory) -> FireRecoverability:
    """Classify a trajectory's detector fires + whether each is recoverable by a WARN re-surface.

    PURE given the trajectory (the caller did the JSONL I/O). The fires themselves come from
    `run_row` (the SSOT detector fold, so this can never drift from the durable rows); the
    recoverability overlay reads the env-authored result bytes by the fixed usable-data grammar."""
    row = run_row(traj)
    ts_fired = bool(row.tool_stream_fired)
    di_fired = bool(row.dangling_fired)
    te_fired = bool(row.terminal_error_fired)

    ts_recoverable = False
    if ts_fired:
        ts_recoverable = is_usable_result(_peak_repeated_result(traj))

    di_recoverable = False
    if di_fired:
        di_recoverable = _has_prior_usable_result(traj)

    return FireRecoverability(
        tool_stream_fired=ts_fired,
        tool_stream_recoverable=ts_recoverable,
        dangling_fired=di_fired,
        dangling_recoverable=di_recoverable,
        terminal_error_fired=te_fired,
        terminal_error_recoverable=False,  # non-recoverable by re-surface (conservative, documented)
    )


# ---------------------------------------------------------------------------
# Per-model + corpus ceiling.
# ---------------------------------------------------------------------------
@dataclass
class ModelCeiling:
    """One model's conversion-ceiling row.

      n_tasks            — labeled runs (passed True/False; None excluded, never guessed).
      pass_rate          — capability proxy = passes / n_tasks.
      fires              — labeled runs where ANY detector fired (deduped per run).
      recoverable_fires  — fired runs that are ALSO oracle-FAILED AND admit a plausible WARN
                           conversion (the value was already in the trajectory). A fire on a PASSED
                           run cannot lift the pass-rate (already a pass), so it is excluded.
      max_lift_pp        — recoverable_fires / n_tasks * 100 — the UPPER BOUND on pass-rate lift if
                           EVERY recoverable fire converted. A ceiling, never a prediction.
    """

    model: str
    n_tasks: int = 0
    passes: int = 0
    fires: int = 0
    recoverable_fires: int = 0
    # per-detector recoverable tallies (deduped per run, FAILED runs only) — the diagnostic split
    ts_recoverable: int = 0
    di_recoverable: int = 0
    te_recoverable: int = 0

    @property
    def pass_rate(self) -> float:
        return self.passes / self.n_tasks if self.n_tasks else 0.0

    @property
    def fire_rate(self) -> float:
        return self.fires / self.n_tasks if self.n_tasks else 0.0

    @property
    def max_lift_pp(self) -> float:
        return 100.0 * self.recoverable_fires / self.n_tasks if self.n_tasks else 0.0

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "n_tasks": self.n_tasks,
            "pass_rate_pct": round(100.0 * self.pass_rate, 2),
            "fires": self.fires,
            "fire_rate_pct": round(100.0 * self.fire_rate, 2),
            "recoverable_fires": self.recoverable_fires,
            "recoverable_by_detector": {
                "tool_stream": self.ts_recoverable,
                "dangling": self.di_recoverable,
                "terminal_error": self.te_recoverable,
            },
            "max_lift_pp": round(self.max_lift_pp, 2),
        }


@dataclass
class CeilingResult:
    """The whole conversion-ceiling result — per-model rows + the corpus ceiling."""

    models: list = field(default_factory=list)  # list[ModelCeiling], capability-ascending
    n_records: int = 0
    n_labeled: int = 0

    @property
    def corpus_n_tasks(self) -> int:
        return sum(m.n_tasks for m in self.models)

    @property
    def corpus_fires(self) -> int:
        return sum(m.fires for m in self.models)

    @property
    def corpus_recoverable_fires(self) -> int:
        return sum(m.recoverable_fires for m in self.models)

    @property
    def corpus_ceiling_pp(self) -> float:
        n = self.corpus_n_tasks
        return 100.0 * self.corpus_recoverable_fires / n if n else 0.0

    def best_regime(self) -> Optional["ModelCeiling"]:
        """The model with the most fix-headroom: highest recoverable_fires, requiring a non-trivial
        fire-rate (>= 5% of its tasks fire) so a one-off lucky catch on a low-fire model does not win.
        Ties broken by max_lift_pp then recoverable_fires."""
        eligible = [m for m in self.models if m.fire_rate >= 0.05 and m.recoverable_fires > 0]
        pool = eligible or [m for m in self.models if m.recoverable_fires > 0]
        if not pool:
            return None
        return max(pool, key=lambda m: (m.recoverable_fires, m.max_lift_pp))

    def to_dict(self) -> dict:
        best = self.best_regime()
        return {
            "n_records": self.n_records,
            "n_labeled": self.n_labeled,
            "corpus": {
                "n_tasks": self.corpus_n_tasks,
                "fires": self.corpus_fires,
                "recoverable_fires": self.corpus_recoverable_fires,
                "ceiling_pp": round(self.corpus_ceiling_pp, 2),
            },
            "best_regime": best.model if best else None,
            "models": [m.to_dict() for m in self.models],
        }


def compute_ceiling(
    trajectories: Iterable[Trajectory],
) -> CeilingResult:
    """Fold the recoverability classifier over every trajectory into the per-model + corpus ceiling.

    Pure over the (already-parsed) trajectories. A run is LABELED iff its oracle label is True/False;
    an unlabeled run (passed None) is excluded from every count, never guessed (the replay.py rule).
    A fire only counts toward `recoverable_fires` if the run is oracle-FAILED — a fire on a PASSED
    run cannot lift the pass-rate (the run already passed), so crediting it would be dishonest.
    """
    by_model: dict[str, ModelCeiling] = {}
    n_records = 0
    n_labeled = 0
    for traj in trajectories:
        n_records += 1
        if traj.passed is None:
            continue  # unlabeled — excluded, never guessed
        n_labeled += 1
        mc = by_model.setdefault(traj.model, ModelCeiling(model=traj.model))
        mc.n_tasks += 1
        if traj.passed:
            mc.passes += 1
        rec = classify_recoverability(traj)
        if rec.any_fired:
            mc.fires += 1
        # recoverable fires only count on FAILED runs (a fire on a pass cannot lift the pass-rate)
        if traj.passed is False:
            if rec.any_recoverable:
                mc.recoverable_fires += 1
            # per-detector diagnostic split (deduped per run is not meaningful across detectors;
            # these are independent per-detector tallies for the headroom breakdown)
            if rec.tool_stream_recoverable:
                mc.ts_recoverable += 1
            if rec.dangling_recoverable:
                mc.di_recoverable += 1
            if rec.terminal_error_recoverable:
                mc.te_recoverable += 1
    models = sorted(by_model.values(), key=lambda m: (m.pass_rate, m.model))
    return CeilingResult(models=models, n_records=n_records, n_labeled=n_labeled)


# ---------------------------------------------------------------------------
# Load the corpus (offline, from the cached JSONL).
# ---------------------------------------------------------------------------
def load_cached_corpus(cache_dir: Path = DEFAULT_CACHE) -> Iterable[Trajectory]:
    """Stream every trajectory from the cached `_data/*.jsonl` (offline; no download). Deterministic
    file order (sorted) so the fold is reproducible."""
    for path in sorted(cache_dir.glob("*.jsonl")):
        yield from iter_trajectories(path)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def _print_summary(s: CeilingResult) -> None:
    print(
        f"# {s.n_records:,} records · {s.n_labeled:,} labeled · {len(s.models)} models"
    )
    print(
        "# CEILING = an UPPER BOUND. Assumes EVERY recoverable fire converts fail->pass — a real "
        "WARN achieves only a FRACTION (docs/144: ~1/4-1/3 of its reach on tasks where it mattered)."
    )
    print()
    hdr = (
        f"{'model':<26} {'pass%':>6} {'tasks':>6} {'fires':>6} {'fire%':>6} "
        f"{'recov':>6} {'(ts/di/te)':>11} {'max_lift_pp':>12}"
    )
    print(hdr)
    print("-" * len(hdr))
    for m in s.models:
        print(
            f"{m.model:<26} {100*m.pass_rate:6.1f} {m.n_tasks:6d} {m.fires:6d} "
            f"{100*m.fire_rate:6.1f} {m.recoverable_fires:6d} "
            f"{m.ts_recoverable:>3}/{m.di_recoverable:>2}/{m.te_recoverable:>2}  "
            f"{m.max_lift_pp:12.2f}"
        )
    print("-" * len(hdr))
    print(
        f"{'CORPUS':<26} {'':>6} {s.corpus_n_tasks:6d} {s.corpus_fires:6d} {'':>6} "
        f"{s.corpus_recoverable_fires:6d} {'':>11} {s.corpus_ceiling_pp:12.2f}"
    )
    best = s.best_regime()
    print()
    if best is not None:
        print(
            f"BEST A/B TARGET: {best.model} — {best.recoverable_fires} recoverable fires "
            f"(fire-rate {100*best.fire_rate:.1f}%), ceiling {best.max_lift_pp:.2f}pp. "
            f"This is where a paid A/B has the most headroom."
        )
    print(
        f"CORPUS CEILING: at most +{s.corpus_ceiling_pp:.2f}pp pass-rate lift if EVERY recoverable "
        f"fire converted. The real lift will be a FRACTION of this — do not overclaim."
    )


def main(argv: Optional[list] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 trap (Windows console)
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="directory of cached _data/*.jsonl trajectories (offline; no download)",
    )
    ap.add_argument("--json", action="store_true", help="print the full CeilingResult as JSON")
    args = ap.parse_args(argv)

    if not args.cache.exists() or not any(args.cache.glob("*.jsonl")):
        ap.error(
            f"no cached trajectories under {args.cache} — run run_replay.py --all to populate _data/"
        )

    s = compute_ceiling(load_cached_corpus(args.cache))

    if args.json:
        print(json.dumps(s.to_dict(), indent=2))
        return 0

    _print_summary(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
