"""The $0 replay measurement — DETECT recall per forgery class + FALSE-REFUTE on clean models.

This is the whole deliverable docs/277 §6 #2 calls for: a labeled corpus + the gate's measured
recall/false-refute over a stated denominator, NO paid run needed. It runs the gate over
`dataset.labeled_corpus()` and folds the verdicts against the GROUND-TRUTH labels (we injected
the forgeries, so the labels are exact).

  * DETECT recall (per class) = fraction of forged models of that class the gate BLOCKED. The
    falsifiable prediction: a measurable slice flagged at each class.
  * FALSE-REFUTE             = fraction of CLEAN models the gate (wrongly) BLOCKED. The
    prediction: 0% on the clean, auditable corpus.

Every model carries the SAME confident completion claim (clean and forged), so the claim side
is held constant — the recompute witness is the only thing that separates a blocked forgery
from an admitted clean model. That is the point: the verdict rides the NON-FORGEABLE recompute,
never the (identical) narration.

Run: `python -m benchmark.finmodel.replay [--json]`. Prints a per-class table + the headline
recall/false-refute and exits 0 (the measurement is the artifact; there is no pass/fail gate).
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field

from .dataset import labeled_corpus
from .gate import CLEAN, admit


@dataclass(frozen=True)
class ClassResult:
    forgery: str            # the ground-truth class ("" -> clean), labeled CLEAN in output
    n: int                  # denominator: models of this class
    n_blocked: int          # how many the gate BLOCKED (admit=False)
    n_no_claim: int         # how many were not gated (no confident claim) — 0 here by construction

    @property
    def label(self) -> str:
        return CLEAN if not self.forgery else self.forgery

    @property
    def detect_recall(self) -> float:
        """For a FORGED class: fraction BLOCKED (recall). For CLEAN: not meaningful (see
        false_refute)."""
        return self.n_blocked / self.n if self.n else 0.0

    @property
    def false_refute(self) -> float:
        """For the CLEAN class: fraction wrongly BLOCKED. For a forged class: 0 by definition
        (a block is correct there)."""
        return self.n_blocked / self.n if self.n else 0.0

    def to_dict(self) -> dict:
        return {
            "class": self.label,
            "n": self.n,
            "n_blocked": self.n_blocked,
            "n_no_claim": self.n_no_claim,
            "rate": round(self.n_blocked / self.n, 4) if self.n else 0.0,
        }


@dataclass(frozen=True)
class ReplayReport:
    per_class: tuple[ClassResult, ...]
    total: int

    def by_label(self, label: str) -> ClassResult:
        for c in self.per_class:
            if c.label == label:
                return c
        raise KeyError(label)

    def to_dict(self) -> dict:
        clean = next((c for c in self.per_class if c.label == CLEAN), None)
        forged = [c for c in self.per_class if c.label != CLEAN]
        n_forged = sum(c.n for c in forged)
        n_forged_blocked = sum(c.n_blocked for c in forged)
        return {
            "total_models": self.total,
            "per_class": [c.to_dict() for c in self.per_class],
            "headline": {
                "overall_detect_recall": round(n_forged_blocked / n_forged, 4) if n_forged else 0.0,
                "false_refute_on_clean": round(clean.false_refute, 4) if clean else None,
                "n_forged": n_forged,
                "n_forged_blocked": n_forged_blocked,
                "n_clean": clean.n if clean else 0,
                "n_clean_blocked": clean.n_blocked if clean else 0,
            },
        }


def run_replay() -> ReplayReport:
    """Fold the gate's verdicts over the labeled corpus into per-class detect/false-refute."""
    n: dict[str, int] = defaultdict(int)
    blocked: dict[str, int] = defaultdict(int)
    no_claim: dict[str, int] = defaultdict(int)

    corpus = labeled_corpus()
    for lm in corpus:
        label = lm.forgery or CLEAN
        n[label] += 1
        d = admit(lm.answer, lm.model, subject=lm.model.name or "model")
        if not d.admit:
            blocked[label] += 1
        if d.verdict == "NO_CLAIM":
            no_claim[label] += 1

    # Stable order: clean first, then forged classes alphabetically.
    labels = [CLEAN] + sorted(l for l in n if l != CLEAN)
    per_class = tuple(
        ClassResult(forgery="" if lab == CLEAN else lab, n=n[lab],
                    n_blocked=blocked[lab], n_no_claim=no_claim[lab])
        for lab in labels
    )
    return ReplayReport(per_class=per_class, total=len(corpus))


def _format_table(report: ReplayReport) -> str:
    lines = []
    lines.append(f"{'class':<22}{'n':>5}{'blocked':>9}{'rate':>8}   interpretation")
    lines.append("-" * 78)
    for c in report.per_class:
        rate = c.n_blocked / c.n if c.n else 0.0
        if c.label == CLEAN:
            interp = f"FALSE-REFUTE = {rate:.1%}  (prediction: 0%)"
        else:
            interp = f"DETECT recall = {rate:.1%}"
        lines.append(f"{c.label:<22}{c.n:>5}{c.n_blocked:>9}{rate:>8.2f}   {interp}")
    h = report.to_dict()["headline"]
    lines.append("-" * 78)
    lines.append(
        f"OVERALL: detect recall {h['overall_detect_recall']:.1%} "
        f"({h['n_forged_blocked']}/{h['n_forged']} forged blocked); "
        f"false-refute {h['false_refute_on_clean']:.1%} "
        f"({h['n_clean_blocked']}/{h['n_clean']} clean blocked)"
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="finmodel $0 replay — recall + false-refute per forgery class")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)
    report = run_replay()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
