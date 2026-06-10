"""natural_paired_attribution.py — the SOUND conversion number for the natural rewind A/B (docs/172 §9.3).

The raw score_ab aggregate over two arms is misleading here because the gym re-samples tasks per arm,
so the arms only share a SUBSET of task-ids (159/240 in the 2026-06-06 run). A success on a task only
one arm ran has no counterfactual and cannot be attributed to the mechanism. This script computes the
ONLY sound attribution: restrict to task-ids BOTH arms ran, find the ones where rewind FIRED, and
compare success to the none counterfactual on those exact tasks — reporting help-flips
(none-fail→rewind-pass) and hurt-flips (none-pass→rewind-fail). Zero flips = the mechanism fires but
changes no outcome = the empty-addressable-population verdict, measured by paired count (§0.3/§0.5).

    python natural_paired_attribution.py --out live_results_natural_ab
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))


def _tid(f):
    base = os.path.basename(f).replace("results_", "").replace(".json", "")
    return base.split("__")[-1]


def _run0(f):
    try:
        return (json.load(open(f, encoding="utf-8")).get("runs") or [{}])[0]
    except Exception:
        return {}


def _fired(run):
    """The fired tool name (natural or stall rewind), or None."""
    for e in (run.get("conversation_flow") or []):
        if isinstance(e, dict) and e.get("type") == "dos_rewind":
            return e.get("tool_name", "?")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"))
    ap.add_argument("--arm", default="rewind_natural")
    ap.add_argument("--baseline", default="none")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    base = {_tid(f): f for f in glob.glob(os.path.join(args.out, args.baseline, "*.json"))}
    arm = {_tid(f): f for f in glob.glob(os.path.join(args.out, args.arm, "*.json"))}
    paired = sorted(set(base) & set(arm))

    total_fires = sum(1 for f in arm.values() if _fired(_run0(f)))
    fired_unpaired_success = 0
    for t, f in arm.items():
        r = _run0(f)
        if _fired(r) and r.get("overall_success") and t not in base:
            fired_unpaired_success += 1

    fired_paired = 0
    r_succ = n_succ = help_flips = hurt_flips = 0
    fired_tools = Counter()
    for t in paired:
        rr = _run0(arm[t])
        ft = _fired(rr)
        if ft is None:
            continue
        fired_paired += 1
        fired_tools[ft] += 1
        rs = bool(rr.get("overall_success"))
        ns = bool(_run0(base[t]).get("overall_success"))
        r_succ += rs
        n_succ += ns
        if rs and not ns:
            help_flips += 1
        if ns and not rs:
            hurt_flips += 1

    print("=" * 72)
    print(f"  NATURAL REWIND — paired attribution ({args.arm} vs {args.baseline}), docs/172 §9.3")
    print("=" * 72)
    print(f"  arm tasks: {len(arm)}   baseline tasks: {len(base)}   PAIRED (shared id): {len(paired)}")
    print(f"  total live fires (arm): {total_fires}")
    print(f"  fires on UNPAIRED tasks that succeeded (NO counterfactual — not attributable): "
          f"{fired_unpaired_success}")
    print("-" * 72)
    print(f"  PAIRED fired tasks (both arms ran): {fired_paired}")
    print(f"    rewind success: {r_succ}    none success (same tasks): {n_succ}")
    print(f"    help-flips (none-fail → rewind-pass): {help_flips}")
    print(f"    hurt-flips (none-pass → rewind-fail): {hurt_flips}")
    print(f"    fired tools: {dict(fired_tools)}")
    print("-" * 72)
    net = help_flips - hurt_flips
    if fired_paired == 0:
        verdict = "no paired fires — cannot attribute"
    elif net == 0:
        verdict = (f"0 net flips on {fired_paired} paired fires — the mechanism fires but changes "
                   f"NO outcome (empty addressable population, §0.3/§0.5 confirmed by paired count)")
    elif net > 0:
        verdict = f"+{net} net help-flips on {fired_paired} paired fires — a real (if small) conversion"
    else:
        verdict = f"{net} net flips on {fired_paired} paired fires — net-harmful (livelock/interrupt)"
    print(f"  VERDICT: {verdict}")
    print("=" * 72)


if __name__ == "__main__":
    main()
