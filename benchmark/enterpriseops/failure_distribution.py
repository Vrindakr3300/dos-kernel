"""Measure the REAL failure distribution on recorded gemini-3-flash trajectories (docs/149).

The operator's discipline, made runnable: *don't manufacture a fake failure to make a DOS
mechanism look useful — measure what real models actually get wrong, and sort by what DOS can
help with.* This folds over the recorded `verification_results` (the gym's hidden-SQL verifier
outcomes — recorded ground truth, the non-forgeable final-state oracle) and buckets every FAILED
check by the shape of its SQL assertion, so the priority question is answered by measurement, not
assumption. Pure replay (the `replay_recall` / `replay_stall` sibling): no model calls, no DB, no
Docker — the L1-safe path (docs/148).

The headline (docs/149): ~83 % of real failed checks are MISSING ROW (expected 1, got 0) — the
action never happened, i.e. Premature Completion, the one mode DOS structurally cannot own here
(both `completion` inputs are forgeable, §5a). The mechanisms DOS *can* own (minted IDs → 0 real,
loops → 0 real) attack the small tail. This script is how that claim stays honest + re-measurable.
"""

from __future__ import annotations

import glob
import json
import sys
from collections import Counter


def _runs(d):
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    if isinstance(d, dict):
        return d.get("runs") if isinstance(d.get("runs"), list) else [d]
    return []


def _shape(query: str, expected, actual) -> str:
    """Bucket a failed check by the shape of its SQL assertion — the failure-mode fingerprint."""
    q = (query or "").lower()
    try:
        exp_i = int(expected)
        act_i = int(actual)
    except (TypeError, ValueError):
        exp_i = act_i = None
    if exp_i is not None and act_i is not None:
        if exp_i >= 1 and act_i == 0:
            return "MISSING ROW (expected >=1, got 0 -- the action never happened)"
        if act_i > exp_i:
            return "EXTRA ROWS (expected fewer -- a side-effect / over-action)"
    if "join" in q or "_id" in q:
        return "FK / RELATION (a link missing or wrong)"
    return "WRONG VALUE (a field set to the wrong value)"


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "benchmark/enterpriseops/live_results"
    files = glob.glob(f"{folder}/**/*.json", recursive=True)

    n_runs = n_fail = total_checks = failed_checks = 0
    shapes = Counter()
    examples = {}
    failed_run_callcounts = []

    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for r in _runs(d):
            vr = r.get("verification_results")
            if not isinstance(vr, dict):
                continue
            n_runs += 1
            vs = r.get("verification_summary", {}) or {}
            total_checks += int(vs.get("total", 0) or 0)
            failed_checks += int(vs.get("failed", 0) or 0)
            if r.get("overall_success") is False:
                n_fail += 1
                failed_run_callcounts.append(len(r.get("tool_results") or []))
            for name, chk in vr.items():
                if not (isinstance(chk, dict) and chk.get("passed") is False):
                    continue
                b = _shape(chk.get("query", ""), chk.get("expected"), chk.get("actual"))
                shapes[b] += 1
                examples.setdefault(b, (str(name)[:38], (chk.get("query", "") or "")[:88]))

    tot = sum(shapes.values())
    print("=" * 80)
    print("  REAL failure distribution on recorded gemini-3-flash trajectories (docs/149)")
    print("  (the gym's recorded verification_results -- non-forgeable final-state ground truth)")
    print("=" * 80)
    fr = (100 * failed_checks / total_checks) if total_checks else 0.0
    print(f"  scored runs: {n_runs}  | overall FAILED: {n_fail}")
    print(f"  checks: {total_checks} total, {failed_checks} failed ({fr:.1f}% per-check fail rate)")
    if failed_run_callcounts:
        c = sorted(failed_run_callcounts)
        med = c[len(c) // 2]
        print(f"  failed-run tool-call counts: median {med}, range {c[0]}-{c[-1]} "
              f"(vs ~9 avg required steps -> stops at ~half the work)")
    print("-" * 80)
    print("  FAILED-CHECK distribution by shape (the priority signal):")
    for b, n in shapes.most_common():
        pct = (100 * n / tot) if tot else 0.0
        print(f"    {n:>3} ({pct:4.1f}%)  {b}")
        ex = examples[b]
        print(f"             e.g. [{ex[0]}] {ex[1]}")
    print("-" * 80)
    print("  READING (docs/149): the dominant failure is the model doing too LITTLE (missing row =")
    print("  premature completion) -- the one mode DOS cannot own cleanly here (forgeable inputs,")
    print("  the §5a trap). The clean ownable DOS slice is the small over-action tail (precursor_gate).")
    print("=" * 80)


if __name__ == "__main__":
    main()
