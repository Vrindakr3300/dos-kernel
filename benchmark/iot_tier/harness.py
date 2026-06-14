"""The model-tier recoverability sweep — fold the REAL gate over each tier, emit the curve.

Per tier: generate the synthetic corpus (synth.py) -> fold the SHIPPED weak-model gate
(`weak_model_gate.gate_fraction`, the exact validated enrichment logic) -> collect the deduped,
enrichment-filtered DOS-recoverable fraction. Emits an ASCII curve (always-on), `--json` for
machines, and an IN-BAND FALSIFIER that exits non-zero if the docs/153 §1 prediction is violated:

  (a) the frontier tier reproduces the gemini null (recoverable < 15%) — the instrument self-test;
  (b) the curve is NON-MONOTONE — it rises above frontier at the middle then COLLAPSES at iot.

If (b) failed (a flat or monotone curve), the model is wrong and the run says so loudly — the
honest kill, not a silent pass. This is a CALIBRATED SIMULATION: the corpora are synthetic, the
detectors are real; the falsifier that would replace the calibration with a measurement is the
docs/153 Stage-0 ~$50 real IoT-corpus run (see README.md).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.enterpriseops.weak_model_gate import gate_fraction, THRESHOLD
from benchmark.iot_tier import synth
from benchmark.iot_tier.tiers import LADDER


def run_sweep(n_runs: int = 400, seed: int = 1729) -> list[dict]:
    """Fold the real gate over each tier's synthetic corpus. Returns one row per tier."""
    rows = []
    for tier in LADDER:
        corpus = synth.generate_corpus(tier, n_runs=n_runs, seed=seed)
        res = gate_fraction(corpus["runs"], synth.TASK_TEXT, model=tier.name)
        rows.append({
            "tier": tier.name,
            "model_class": tier.model_class,
            "per_task_fail_rate": tier.per_task_fail_rate,
            "n_fail": res.n_fail,
            "n_pass": res.n_pass,
            "recoverable_frac": res.frac,
            "recoverable": res.recoverable,
            "unreachable": res.unreachable,
            "fail_fires": res.fail_fires,
            "pass_fires": res.pass_fires,
            "enriched": res.enriched,
            "note": tier.note,
        })
    return rows


def _peak_and_collapse(rows: list[dict]) -> tuple[int, int]:
    """Index of the peak (max recoverable_frac) and the iot/last tier (the collapse end)."""
    fracs = [r["recoverable_frac"] for r in rows]
    peak = max(range(len(fracs)), key=lambda i: fracs[i])
    return peak, len(rows) - 1


def check_falsifier(rows: list[dict]) -> list[str]:
    """Return a list of violated predictions (empty == the prediction held)."""
    violations = []
    by_name = {r["tier"]: r for r in rows}
    # (a) frontier reproduces the gemini null
    fr = by_name.get("frontier")
    if fr and fr["recoverable_frac"] >= THRESHOLD:
        violations.append(
            f"frontier self-test FAILED: recoverable {fr['recoverable_frac']:.0%} "
            f">= {THRESHOLD:.0%} threshold (expected the gemini null < 15%)")
    # (b) non-monotone: a peak strictly above frontier, AND iot strictly below the peak
    peak_i, last_i = _peak_and_collapse(rows)
    frontier_frac = rows[0]["recoverable_frac"]
    peak_frac = rows[peak_i]["recoverable_frac"]
    iot_frac = rows[last_i]["recoverable_frac"]
    if not (peak_frac > frontier_frac):
        violations.append(
            f"curve is FLAT/monotone-down: peak {peak_frac:.0%} not above frontier "
            f"{frontier_frac:.0%} (docs/153 predicted a rise at the middle)")
    if not (iot_frac < peak_frac):
        violations.append(
            f"NO collapse: iot {iot_frac:.0%} not below peak {peak_frac:.0%} "
            f"(docs/153 §1 predicted the can-do-when-nudged collapse)")
    return violations


def _bar(frac: float, width: int = 28) -> str:
    n = int(round(frac * width))
    return "#" * n + "-" * (width - n)


def render_ascii(rows: list[dict], violations: list[str]) -> str:
    peak_i, last_i = _peak_and_collapse(rows)
    out = []
    out.append("=" * 78)
    out.append("  IOT_TIER — DOS recoverable-failure fraction across the model-size ladder")
    out.append("  (calibrated SIM: synthetic corpora, REAL shipped detectors via the gate fold)")
    out.append("=" * 78)
    out.append(f"  {'tier':<9} {'model class':<24} recoverable-fraction (deduped, enriched)")
    for i, r in enumerate(rows):
        tag = ""
        if i == peak_i and r["recoverable_frac"] > rows[0]["recoverable_frac"]:
            tag = "  <- PEAK"
        if i == last_i and r["recoverable_frac"] < rows[peak_i]["recoverable_frac"]:
            tag = "  <- COLLAPSE"
        bar = _bar(r["recoverable_frac"])
        out.append(f"  {r['tier']:<9} {r['model_class']:<24} {bar} {r['recoverable_frac']:>4.0%}{tag}")
    # the threshold guide line
    thr_pos = int(round(THRESHOLD * 28))
    guide = " " * (9 + 1 + 24 + 1) + " " * thr_pos + "|"
    out.append(guide)
    out.append(" " * (9 + 1 + 24 + 1) + " " * max(0, thr_pos - 4) + f"{THRESHOLD:.0%} threshold")
    out.append("-" * 78)
    out.append("  Per tier — detector enrichment (SIGNAL counts toward recoverable; NOISE excluded):")
    for r in rows:
        flags = " ".join(f"{k}:{'S' if r['enriched'][k] else 'N'}" for k in ("mint", "loop", "dangle")
                         ) if "dangle" in r["enriched"] else \
                " ".join(f"{k}:{'S' if r['enriched'][k] else 'N'}" for k in r["enriched"])
        out.append(f"    {r['tier']:<9} n_fail={r['n_fail']:<4} {flags}   unreachable={r['unreachable']}")
    out.append("-" * 78)
    if violations:
        out.append("  FALSIFIER TRIPPED — the docs/153 §1 prediction did NOT hold on this corpus:")
        for v in violations:
            out.append(f"    ! {v}")
    else:
        out.append("  Prediction HELD: frontier reproduces the null; the curve rises then collapses.")
        out.append("  Reading: DOS's lift is largest on the MIDDLE model, not the weakest — the IoT")
        out.append("  tier's failures migrate into silent-stops DOS owns 0% of (docs/153 §1/§4).")
    out.append("  CALIBRATED SIM. The measurement that replaces these assumptions is the docs/153")
    out.append("  Stage-0 ~$50 real IoT-corpus run (sub-3B model -> dos_react -> the same gate fold).")
    out.append("=" * 78)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="DOS recoverable-fraction sweep across the model-size ladder")
    ap.add_argument("--runs", type=int, default=400, help="synthetic runs per tier (default 400)")
    ap.add_argument("--seed", type=int, default=1729, help="generation seed (deterministic)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the ASCII curve")
    args = ap.parse_args(argv)

    rows = run_sweep(n_runs=args.runs, seed=args.seed)
    violations = check_falsifier(rows)

    if args.json:
        print(json.dumps({"threshold": THRESHOLD, "rows": rows,
                          "falsifier_violations": violations,
                          "prediction_held": not violations}, indent=2))
    else:
        print(render_ascii(rows, violations))

    # In-band falsifier: a tripped prediction is a non-zero exit (the honest loud kill).
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
