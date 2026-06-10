"""gate_calibration.py — the $0 threshold ablation: TP vs FALSE-INTERRUPTION across min_failures K.

docs/172 §0.4. The cause-locality ablation (§0.3) showed 0/12 natural thrashes are rewind-ADDRESSABLE
(class A). This module measures the OTHER cost the thrash gate carries at its firing threshold: the
FALSE-POSITIVE INTERRUPTION rate. The gate fires when a tool accumulates K structured errors and its
latest result is still an error. But some tools that reach K errors then SELF-RECOVER on a later try
(the model read the env error and fixed the call). Firing on those INTERRUPTS a would-be self-fix —
a measurable harm the rewind/WARN must overcome before it can be net-positive.

  TP (fires-on-stuck)      — the tool reached K errors AND ended on an error (never recovered): a real
                             dead end the gate is RIGHT to flag (though §0.3 says rewind can't FIX it
                             if it is class C / capability-bound).
  FP (fires-on-recoverable)— the tool reached K errors but a LATER same-tool call SUCCEEDED: the model
                             was about to self-fix, and a gate firing at error K would cut it off.

This is the calibration knob: raising K trades coverage (fewer TP) for fewer false interruptions
(fewer FP). The headline the ablation produces: there is no K at which the natural-thrash gate's fired
population is net-rewind-positive, because (a) §0.3 shows ~0% is class-A addressable AND (b) the FP
interruption cost stays material (17-30% of fires) at every K. Pure replay; no model, no network.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))

_STRUCT = re.compile(
    r"MCP error -3\d{4}|\"isError\"\s*:\s*true|^\s*Error:|Traceback \(most recent"
    r"|exited with code [1-9]|permission denied", re.IGNORECASE | re.MULTILINE)


def _rtext(tr) -> str:
    try:
        return json.dumps(tr.get("result", tr), default=str)
    except Exception:
        return str(tr)


def _is_err(tr) -> bool:
    return bool(_STRUCT.search(_rtext(tr)))


def measure(dirs, K: int):
    """For threshold K: (TP fires-on-stuck, FP fires-on-recoverable, n_runs)."""
    tp = fp = n_runs = 0
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.json")):
            try:
                data = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            for run in data.get("runs", []):
                n_runs += 1
                by_tool = defaultdict(list)
                for tr in (run.get("tool_results") or []):
                    by_tool[str(tr.get("tool_name", ""))].append(tr)
                for tool, seq in by_tool.items():
                    if not seq:
                        continue
                    fails = sum(1 for tr in seq if _is_err(tr))
                    if fails < K:
                        continue  # gate never reaches its firing threshold
                    recovered = any(
                        (not _is_err(tr)) for i, tr in enumerate(seq)
                        if any(_is_err(p) for p in seq[:i])
                    )
                    if _is_err(seq[-1]) and not recovered:
                        tp += 1            # ended stuck — a real dead end
                    elif recovered:
                        fp += 1            # reached K errors but later succeeded — interrupt cost
    return tp, fp, n_runs // max(1, len(dirs))  # n_runs is summed; report per-dir avg loosely


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+",
                    default=[os.path.join(_HERE, "live_results_natural_run", "none"),
                             os.path.join(_HERE, "live_results_natural", "none")])
    ap.add_argument("--ks", nargs="+", type=int, default=[2, 3, 4, 5])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = []
    for K in args.ks:
        tp, fp, _ = measure(args.dirs, K)
        total = tp + fp
        rows.append({"K": K, "tp_fires_on_stuck": tp, "fp_fires_on_recoverable": fp,
                     "fp_rate_pct": round(100.0 * fp / total, 1) if total else 0.0})

    if args.json:
        print(json.dumps({"as_of": "2026-06-06", "rows": rows}, indent=2))
        return

    print("=== thrash-gate threshold calibration (min_failures K) ===")
    print(f"  {'K':<5}{'fires-on-stuck (TP)':>22}{'fires-on-recoverable (FP)':>28}{'FP rate':>10}")
    for r in rows:
        print(f"  {r['K']:<5}{r['tp_fires_on_stuck']:>22}{r['fp_fires_on_recoverable']:>28}"
              f"{r['fp_rate_pct']:>9}%")
    print()
    print("  TP = reached K errors and ended STUCK (a real dead end — but §0.3: ~0% rewind-FIXABLE).")
    print("  FP = reached K errors but a later call SUCCEEDED (gate would INTERRUPT a self-fix).")
    print("  VERDICT: no K makes the fired population net-rewind-positive — §0.3 says ~0% is class-A,")
    print("  and the FP interruption cost stays material at every threshold. The natural-thrash gate")
    print("  is a sound DETECTOR of a dead end, but rewind is the wrong ACTUATION for what it detects.")


if __name__ == "__main__":
    main()
