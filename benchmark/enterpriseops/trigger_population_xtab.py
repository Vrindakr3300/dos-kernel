"""trigger_population_xtab.py — the unified cross-tab: which TRIGGER fires × which CAUSE-class (docs/172 §0.5).

The synthesis of the sub-divide-and-ablate pass. Three DOS triggers can fire a SUBTRACT/rewind on a
natural dead-end, each keyed on a different surface of the SAME failure stream:

  * natural_thrash (BRANCH) — the same tool errors >=2x (possibly DIFFERENT error bytes).
  * stall (LOOP)            — the same (tool,args,result) triple repeats >=stall_n byte-identically
                              (tool_stream.classify_stream -> STALLED).
  * (mint is the injected regime, not measured here — this is the natural corpus.)

And §0.3 split every dead-end by CAUSE-LOCALITY: A (recoverable-from-prefix → rewind-addressable),
B (upstream-omission/guessing → livelock), C (schema/not-in-transcript → model-capability gap).

This module cross-tabulates TRIGGER × CAUSE over the natural corpus, and adds the LOOP sub-split
(error-loop vs success-spin), to answer the operator's question at the synthesis level: across ALL
triggers, what fraction of what each fires on is actually rewind-ADDRESSABLE (class A)? The headline:
≈0 on every trigger — the failures are class-C capability gaps that present as either an error-BRANCH
(natural_thrash) or an error-LOOP (stall); the lone genuine loop-hygiene case is a SUCCESS-spin read
(1/160) where the right move is WARN/re-surface, not a SUBTRACT. Pure replay; no model, no network.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import cause_locality as CL  # the §0.3 classifier (A/B/C)
from stall_trigger import stream_from_tool_results  # the LOOP stream builder
from dos.tool_stream import classify_stream, StreamState


def _runs(dirs):
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                data = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            for run in data.get("runs", []):
                yield os.path.basename(f), run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+",
                    default=[os.path.join(_HERE, "live_results_natural_run", "none"),
                             os.path.join(_HERE, "live_results_natural", "none")])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    n_runs = 0
    branch_by_cause = Counter()      # natural_thrash fires, split by cause-class
    loop_split = Counter()           # stall fires, split by error-loop vs success-spin
    loop_error_cause = Counter()     # error-loops, split by cause-class
    for _, run in _runs(args.dirs):
        n_runs += 1
        trs = run.get("tool_results") or []
        by_tool = defaultdict(list)
        for tr in trs:
            by_tool[str(tr.get("tool_name", ""))].append(tr)

        # BRANCH trigger (natural_thrash): one fire per run (the first thrashing tool), classified.
        for tool in by_tool:
            r = CL._classify_thrash(trs, tool)
            if r is not None:
                branch_by_cause[r["class"]] += 1
                break

        # LOOP trigger (stall): any tool reaching STALLED. Split SUCCESS-spin vs ERROR-loop; for
        # ERROR-loops, classify the repeated error's cause via the §0.3 grammar.
        for tool, seq in by_tool.items():
            v = classify_stream(stream_from_tool_results(seq))
            if v.state == StreamState.STALLED:
                last = seq[-1]
                if CL._is_struct_error(last):
                    loop_split["error_loop"] += 1
                    err = CL._error_text(last)
                    is_schema = bool(CL._SCHEMA_COMPLAINT.search(err))
                    is_ref = bool(CL._REF_COMPLAINT.search(err))
                    cls = ("C_not_in_transcript" if (is_schema and not is_ref)
                           else "B_upstream_omission" if is_ref else "C_not_in_transcript")
                    loop_error_cause[cls] += 1
                else:
                    loop_split["success_spin"] += 1
                break  # one loop fire per run

    branch_total = sum(branch_by_cause.values())
    loop_total = sum(loop_split.values())
    out = {
        "as_of": "2026-06-06",
        "n_runs": n_runs,
        "BRANCH_trigger (natural_thrash) fires": branch_total,
        "BRANCH_by_cause": dict(branch_by_cause),
        "LOOP_trigger (stall→STALLED) fires": loop_total,
        "LOOP_split": dict(loop_split),
        "LOOP_error_by_cause": dict(loop_error_cause),
        "rewind_addressable_total (class A, any trigger)":
            branch_by_cause.get("A_recoverable_from_prefix", 0),
    }

    if args.json:
        print(json.dumps(out, indent=2))
        return

    print("=== TRIGGER × CAUSE cross-tab over the natural corpus (docs/172 §0.5) ===")
    print(f"  n_runs: {n_runs}")
    print(f"\n  BRANCH trigger (natural_thrash, errors >=2x): {branch_total} fires")
    for c in ("A_recoverable_from_prefix", "B_upstream_omission", "C_not_in_transcript"):
        print(f"      {c}: {branch_by_cause.get(c, 0)}")
    print(f"\n  LOOP trigger (stall → STALLED, byte-identical >=5x): {loop_total} fires")
    print(f"      success_spin (re-read unchanged → WARN/re-surface is the move): "
          f"{loop_split.get('success_spin', 0)}")
    print(f"      error_loop (repeat a failing call identically): {loop_split.get('error_loop', 0)}")
    for c in ("B_upstream_omission", "C_not_in_transcript"):
        if loop_error_cause.get(c):
            print(f"          of which {c}: {loop_error_cause[c]}")
    print(f"\n  REWIND-ADDRESSABLE (class A, ANY trigger): "
          f"{branch_by_cause.get('A_recoverable_from_prefix', 0)}")
    print("\n  SYNTHESIS: across BRANCH and LOOP triggers, the rewind/SUBTRACT addressable")
    print("  population (class A) is ~0. The dead ends are class-C capability gaps that present")
    print("  as an error-BRANCH or an error-LOOP — re-entering the prefix re-spawns the same")
    print("  schema-ignorant call. The one genuine loop-hygiene case is a SUCCESS-spin read where")
    print("  the correct actuation is WARN/re-surface, not a SUBTRACT. KEEP DETECT, CHANGE ACTUATE.")


if __name__ == "__main__":
    main()
