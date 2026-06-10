"""firing_corpus — run the KERNEL's `dos.firing_label` fold over the frozen Toolathlon
corpus, and measure NET LIFT (docs/179 Phase 2, the offline corpus harvester).

> **This is the empirical proof of docs/179: the self-labeling fold, run over REAL
> labeled data, (a) reproduces the SSOT `additivity.py` per-detector confusion grid
> byte-for-byte — proving the kernel instrument is correct — and (b) shows NET LIFT:
> the union of detectors catches strictly more oracle-failures than the best single
> detector, at a bounded false-alarm cost. "More data → more signal," measured.**

The honesty check this module must pass (the docs/179 design law)
================================================================

The docs/179 law: a fold mints new ground truth only by joining two
INDEPENDENTLY-AUTHORED facts. On a live DOS run that is (detector firing) × (git
ancestry). On this OFFLINE replay there is no git — so what is the independent
ground truth, and is the join still real (not circular)?

  * The **firing** is authored by the detector reading ENV bytes: `tool_stream`
    hashes the tool-result bytes, `terminal_error` reads the final-text/tool status,
    `dangling` reads the stop cue. None of them sees the task outcome.
  * The **label** is the third-party `passed` column — the Toolathlon task
    evaluator's verdict, authored by the BENCHMARK HARNESS running the task's own
    checker, NOT by the detector and NOT by the agent. It is the legitimate
    git-minted-outcome STAND-IN on a replay: an outcome fact the judged agent did
    not author and the detector never read.

So the join (firing × oracle) is genuinely two independently-authored facts — the
same shape as (firing × git) live. It is NOT circular: the detector's decision and
the oracle's decision are computed from disjoint inputs. (The fiction would be
synthesizing the oracle FROM the firing; we do the opposite — the oracle is the
pre-existing `passed` column, and the firing is the pre-existing `*_fired` column.)

What "the git-minted columns of a TraceFrame" become here
=========================================================

`firing_label.label_one` reads a `TraceFrame`'s git-minted columns
(verified/residual/commits). `corpus_frame` maps the oracle label onto those columns
honestly:

  * `passed == False` → a frame with one PENDING step, 0 verified, 0 commits → a
    run that declared work and git-confirmed NONE of it → `TRUE_POSITIVE` if fired.
  * `passed == True`  → a frame with one VERIFIED step → git-confirmed progress →
    `FALSE_ALARM` if fired.
  * `passed` absent   → a frame with no intent + no commits → `UNVERIFIABLE`
    (the unlabeled rows `additivity.py` also excludes — refuse, don't guess).

`ground_truth.source = "oracle"` is stamped on every frame so a reader never mistakes
the replay label for a real git mint. The OUTCOME counts (TP/FP) are real either way
— they are precisely `additivity.py`'s `fired_fail`/`fired_pass`, which is why
`cross_validate` can assert byte-equality against the SSOT.

Run it
======

    python -m benchmark.toolathlon.firing_corpus            # the net-lift summary
    python -m benchmark.toolathlon.firing_corpus --check    # assert == additivity.py SSOT (exit 1 on drift)
    python -m benchmark.toolathlon.firing_corpus --json     # the full machine-readable result
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from dos.firing_label import (
    DetectorFiring,
    LabelOutcome,
    LabelSummary,
    label_firings,
)
from dos.trace import StepRow, TraceFrame

from benchmark.toolathlon.additivity import (
    PAIR,
    TRIO,
    _truthy,
    compute as additivity_compute,
    load_rows,
)

_HERE = Path(__file__).resolve().parent
_DEFAULT_ROWS = _HERE / "_results" / "replay_all_rows.csv"

# The detectors whose `*_fired` columns the corpus carries (additivity's TRIO order).
DETECTORS = TRIO  # ("dangling", "tool_stream", "terminal_error")


# --------------------------------------------------------------------------- the adapter
def _run_id(row: dict) -> str:
    """A stable per-trajectory id for the firing↔frame join. The corpus keys a run by
    (model_run, task_name) — additivity.py's dedup key — so we reuse it verbatim."""
    return f"{row['model_run']}::{row['task_name']}"


def _oracle(row: dict) -> Optional[bool]:
    """The third-party oracle label, or None when the row is unlabeled (the
    additivity.py rule: passed not in {True,False} → excluded, never guessed)."""
    p = str(row.get("passed"))
    if p == "True":
        return True
    if p == "False":
        return False
    return None


def corpus_frame(run_id: str, oracle: Optional[bool]) -> TraceFrame:
    """Map a third-party oracle label onto a `TraceFrame`'s git-minted columns. PURE.

    The honest stand-in (see module docstring): the OUTCOME is the oracle's, stamped
    `source="oracle"` so it is never mistaken for a git mint. `firing_label.label_one`
    then reads it through the SAME ladder it uses on a real frame:
      * oracle False → 1 PENDING step, 0 verified, 0 commits → TRUE_POSITIVE if fired.
      * oracle True  → 1 VERIFIED step → FALSE_ALARM if fired.
      * oracle None  → no intent, no commits → UNVERIFIABLE.
    """
    if oracle is None:
        # No intent, no commits → label_one returns UNVERIFIABLE (refuse to judge).
        return TraceFrame(run_id=run_id, found=True, has_intent=False, steps=(), commits=())
    if oracle is True:
        steps = (StepRow(step_id="oracle", state="VERIFIED",
                         verified_sha="o" * 10, verified_via="oracle"),)
        return TraceFrame(run_id=run_id, found=True, has_intent=True, steps=steps, commits=())
    # oracle is False — declared work, git-confirmed none.
    steps = (StepRow(step_id="oracle", state="PENDING"),)
    return TraceFrame(run_id=run_id, found=True, has_intent=True, steps=steps, commits=())


def firings_from_rows(rows: Iterable[dict], detectors: tuple = DETECTORS) -> tuple[DetectorFiring, ...]:
    """One `DetectorFiring` per (row, detector that fired). PURE over the row dicts.

    The firing's `identity` is the run_id+detector so two reads of the same row don't
    double-count (each row is already one trajectory). `signal` is the detector's
    recorded state where available (`tool_stream_state`), else the detector name."""
    out: list[DetectorFiring] = []
    for r in rows:
        rid = _run_id(r)
        for det in detectors:
            if not _truthy(r.get(f"{det}_fired", "")):
                continue
            if det == "tool_stream":
                signal = str(r.get("tool_stream_state") or "REPEATING")
            else:
                signal = det.upper()
            out.append(DetectorFiring(
                run_id=rid, detector=det, signal=signal,
                step_index=int(r.get("n_tool_steps") or 0),
                identity=f"{rid}:{det}",  # one firing per (run, detector)
            ))
    return tuple(out)


# --------------------------------------------------------------------------- the result
@dataclass(frozen=True)
class DetectorLift:
    """One detector's confusion grid through the KERNEL fold (the additivity DetectorSlice twin)."""

    detector: str
    true_positives: int
    false_alarms: int

    @property
    def fired(self) -> int:
        return self.true_positives + self.false_alarms

    @property
    def precision(self) -> Optional[float]:
        return self.true_positives / self.fired if self.fired else None

    def to_dict(self) -> dict:
        return {
            "detector": self.detector,
            "true_positives": self.true_positives,
            "false_alarms": self.false_alarms,
            "precision": self.precision,
        }


@dataclass(frozen=True)
class NetLift:
    """The headline: union of detectors vs the best single detector — the 'more signal' number.

    `union_tp` is distinct oracle-failures caught by ANY detector (deduped by run);
    `best_single_tp` is the most any one detector caught. `net_new` is the failures the
    union catches that the best single misses — the lift the data-multiplier framing
    promised, measured on real labels."""

    n_failed: int
    n_passed: int
    per_detector: tuple[DetectorLift, ...]
    union_tp: int
    union_fp: int
    best_single_detector: str
    best_single_tp: int

    @property
    def net_new(self) -> int:
        return self.union_tp - self.best_single_tp

    @property
    def union_recall(self) -> Optional[float]:
        return self.union_tp / self.n_failed if self.n_failed else None

    @property
    def best_single_recall(self) -> Optional[float]:
        return self.best_single_tp / self.n_failed if self.n_failed else None

    @property
    def union_false_alarm(self) -> Optional[float]:
        return self.union_fp / self.n_passed if self.n_passed else None

    @property
    def recall_gain_pp(self) -> Optional[float]:
        if self.union_recall is None or self.best_single_recall is None:
            return None
        return 100.0 * (self.union_recall - self.best_single_recall)

    def to_dict(self) -> dict:
        return {
            "n_failed": self.n_failed,
            "n_passed": self.n_passed,
            "per_detector": [d.to_dict() for d in self.per_detector],
            "union_tp": self.union_tp,
            "union_fp": self.union_fp,
            "union_recall": self.union_recall,
            "union_false_alarm": self.union_false_alarm,
            "best_single_detector": self.best_single_detector,
            "best_single_tp": self.best_single_tp,
            "best_single_recall": self.best_single_recall,
            "net_new_over_best_single": self.net_new,
            "recall_gain_pp": self.recall_gain_pp,
        }


def harvest(rows: list, detectors: tuple = DETECTORS) -> NetLift:
    """Run the kernel `firing_label` fold over the corpus rows and compute net lift. PURE.

    Per detector: run label_firings on that detector's firings alone, count TP/FP via
    the kernel's LabelOutcome. Then the UNION: a run is a union-TP iff ANY detector
    labeled it TRUE_POSITIVE on that run (deduped by run_id) — the additivity.UnionSlice
    pooling, but computed through the kernel verdict rather than the raw boolean.
    """
    rows = list(rows)
    n_failed = sum(1 for r in rows if _oracle(r) is False)
    n_passed = sum(1 for r in rows if _oracle(r) is True)

    # frame_for is the boundary lookup: oracle label → corpus frame (cached by run_id).
    oracle_by_run = {_run_id(r): _oracle(r) for r in rows}
    frame_cache: dict[str, TraceFrame] = {}

    def frame_for(rid: str) -> TraceFrame:
        if rid not in frame_cache:
            frame_cache[rid] = corpus_frame(rid, oracle_by_run.get(rid))
        return frame_cache[rid]

    # Per-detector confusion via the kernel fold.
    per_detector: list[DetectorLift] = []
    # union sets: run_ids the kernel labeled TP / FP by ANY detector.
    union_tp_runs: set[str] = set()
    union_fp_runs: set[str] = set()
    for det in detectors:
        det_firings = firings_from_rows(rows, detectors=(det,))
        points = label_firings(det_firings, frame_for)
        tp = fp = 0
        for p in points:
            if p.outcome is LabelOutcome.TRUE_POSITIVE:
                tp += 1
                union_tp_runs.add(p.firing.run_id)
            elif p.outcome is LabelOutcome.FALSE_ALARM:
                fp += 1
                union_fp_runs.add(p.firing.run_id)
        per_detector.append(DetectorLift(detector=det, true_positives=tp, false_alarms=fp))

    best = max(per_detector, key=lambda d: d.true_positives)
    return NetLift(
        n_failed=n_failed,
        n_passed=n_passed,
        per_detector=tuple(per_detector),
        union_tp=len(union_tp_runs),
        union_fp=len(union_fp_runs),
        best_single_detector=best.detector,
        best_single_tp=best.true_positives,
    )


# --------------------------------------------------------------------------- cross-validation
def cross_validate(rows: list, detectors: tuple = DETECTORS) -> list:
    """Assert the KERNEL fold reproduces the SSOT additivity.py confusion grid exactly.

    Returns a list of mismatch messages (empty == the kernel instrument is correct).
    This is the load-bearing proof: if the kernel's per-detector TP/FP match
    additivity's `fired_fail`/`fired_pass` byte-for-byte, then the kernel fold is a
    correct re-implementation of the SSOT lift metric, and the net-lift number it
    reports is trustworthy (not a parallel, possibly-buggy computation)."""
    fails: list[str] = []
    kernel = {d.detector: d for d in harvest(rows, detectors).per_detector}
    ssot = additivity_compute(rows).detectors
    for det in detectors:
        k = kernel[det]
        s = ssot[det]
        if k.true_positives != s.fired_fail:
            fails.append(f"{det}: kernel TP {k.true_positives} != additivity fired_fail {s.fired_fail}")
        if k.false_alarms != s.fired_pass:
            fails.append(f"{det}: kernel FP {k.false_alarms} != additivity fired_pass {s.fired_pass}")
    # Union TP must match additivity's trio union TP (the net-lift denominator's numerator).
    trio = additivity_compute(rows).trio
    kr = harvest(rows, detectors)
    if kr.union_tp != trio.tp:
        fails.append(f"union: kernel union_tp {kr.union_tp} != additivity trio.tp {trio.tp}")
    if kr.union_fp != trio.fp:
        fails.append(f"union: kernel union_fp {kr.union_fp} != additivity trio.fp {trio.fp}")
    return fails


# --------------------------------------------------------------------------- main
def _print_summary(lift: NetLift) -> None:
    print(f"# firing_label over the Toolathlon corpus — {lift.n_failed:,} oracle-FAIL, "
          f"{lift.n_passed:,} oracle-PASS")
    print("# (the join is firing × third-party oracle — two independently-authored facts, docs/179)")
    print()
    print("per-detector (through the KERNEL fold):")
    for d in lift.per_detector:
        pr = f"{100*d.precision:.1f}%" if d.precision is not None else "n/a"
        print(f"  {d.detector:<16} {d.true_positives:>4} TP / {d.false_alarms:>3} FP · precision {pr}")
    print()
    ur = f"{100*lift.union_recall:.2f}%" if lift.union_recall is not None else "n/a"
    bsr = f"{100*lift.best_single_recall:.2f}%" if lift.best_single_recall is not None else "n/a"
    uf = f"{100*lift.union_false_alarm:.2f}%" if lift.union_false_alarm is not None else "n/a"
    print(f"NET LIFT (the 'more signal' number):")
    print(f"  best single   : {lift.best_single_detector} — {lift.best_single_tp} TP, recall {bsr}")
    print(f"  union of {len(lift.per_detector)}    : {lift.union_tp} TP, recall {ur}, false-alarm {uf}")
    print(f"  NET-NEW       : +{lift.net_new} failures the union catches that the best single MISSES "
          f"(+{lift.recall_gain_pp:.2f}pp recall)")


def main(argv: Optional[list] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=Path, default=_DEFAULT_ROWS, help="durable per-run rows CSV")
    ap.add_argument("--check", action="store_true",
                    help="assert the kernel fold == additivity.py SSOT; exit 1 on drift")
    ap.add_argument("--json", action="store_true", help="print the full NetLift as JSON")
    args = ap.parse_args(argv)

    if not args.rows.exists():
        ap.error(f"no rows CSV at {args.rows} — run run_replay.py --all ... --rows-out first")

    rows = load_rows(args.rows)
    lift = harvest(rows)

    if args.json:
        import json
        print(json.dumps(lift.to_dict(), indent=2))
        return 0

    _print_summary(lift)

    if args.check:
        problems = cross_validate(rows)
        if problems:
            print("\nCROSS-VALIDATION FAILURES (kernel fold != additivity SSOT):", file=sys.stderr)
            for p in problems:
                print(f"  ✗ {p}", file=sys.stderr)
            return 1
        print("\nkernel firing_label fold reproduces the additivity.py SSOT exactly ✓")
        if lift.net_new <= 0:
            print(f"  ⚠ NO net lift: the union adds {lift.net_new} over the best single detector",
                  file=sys.stderr)
            return 1
        print(f"  NET LIFT confirmed: +{lift.net_new} net-new catches, +{lift.recall_gain_pp:.2f}pp recall ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
