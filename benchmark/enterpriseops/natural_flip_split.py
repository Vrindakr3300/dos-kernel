"""natural_flip_split.py — the docs/172 §9 class-split flip table for the natural rewind A/B.

The §3.5 livelock mechanism predicts rewind helps on DOWNSTREAM-ACCRETED corruption and livelocks
on UPSTREAM-OMISSION. So the natural rewind's effect should split by whether the agent's repeated
env error is byte-IDENTICAL (same omission, livelock-prone) or VARYING (exploratory, maybe
convergeable). This scorer joins `none` vs `rewind_natural` per task and, for every run where the
natural rewind FIRED, computes the verifier-flip net SPLIT by that class — the P-natural-2 instrument.

A flip is per-verifier vs the none baseline on the SAME task: FALSE->TRUE = helped, TRUE->FALSE = hurt.
CAVEAT (same as mattered_join.py): arms re-seed a fresh DB and the model is stochastic, so a single
flip can be noise — trust the AGGREGATE net per class across many fired runs, not any one flip.

    python natural_flip_split.py --out live_results_natural_ab
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
sys.path.insert(0, _HERE)

_STRUCT = re.compile(
    r"MCP error -3\d{4}|\"isError\"\s*:\s*true|^\s*Error:|Traceback \(most recent"
    r"|exited with code [1-9]|permission denied", re.IGNORECASE | re.MULTILINE)


def _tid(path):
    return os.path.basename(path).replace("results_oracle__", "").replace(".json", "")


def _load(arm_dir):
    return {_tid(f): f for f in glob.glob(os.path.join(arm_dir, "results_*.json"))}


def _run0(path):
    try:
        return (json.load(open(path, encoding="utf-8")).get("runs") or [{}])[0]
    except Exception:
        return {}


def _verifiers(run):
    vr = run.get("verification_results") or {}
    return {k: bool(v.get("passed")) for k, v in vr.items() if isinstance(v, dict)}


def _rtext(tr):
    try:
        return json.dumps(tr.get("result", tr), default=str)
    except Exception:
        return str(tr)


def _rewind_fired(run):
    """The natural rewind fired iff a dos_rewind event with kind=='natural' is in the flow."""
    for e in (run.get("conversation_flow") or []):
        if isinstance(e, dict) and e.get("type") == "dos_rewind" and e.get("kind") == "natural":
            return e.get("tool_name")
    # fallback: dos_arg_provenance.rewinds > 0
    if (run.get("dos_arg_provenance") or {}).get("rewinds", 0) > 0:
        return "?"
    return None


def _thrash_class(run, tool):
    """SAME (byte-identical repeated error -> omission/livelock) vs VARYING (exploratory)."""
    msgs = []
    for tr in (run.get("tool_results") or []):
        if str(tr.get("tool_name", "")) != tool:
            continue
        txt = _rtext(tr)
        if _STRUCT.search(txt):
            m = re.search(r'"text":\s*"([^"]{0,120})', txt)
            msgs.append((m.group(1) if m else txt)[:60])
    if len(msgs) < 2:
        return "unknown"
    return "same" if len({m for m in msgs}) == 1 else "varying"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"))
    args = ap.parse_args(argv)

    none = _load(os.path.join(args.out, "none"))
    rew = _load(os.path.join(args.out, "rewind_natural"))
    common = sorted(set(none) & set(rew))

    by_class = defaultdict(lambda: {"runs": 0, "help": 0, "hurt": 0})
    fired_total = 0
    for t in common:
        r_rew = _run0(rew[t])
        tool = _rewind_fired(r_rew)
        if tool is None:
            continue
        fired_total += 1
        cls = _thrash_class(r_rew, tool) if tool != "?" else "unknown"
        vn = _verifiers(_run0(none[t]))
        va = _verifiers(r_rew)
        by_class[cls]["runs"] += 1
        for k in set(vn) & set(va):
            if not vn[k] and va[k]:
                by_class[cls]["help"] += 1
            elif vn[k] and not va[k]:
                by_class[cls]["hurt"] += 1

    print("=" * 76)
    print("  NATURAL REWIND — class-split flip table (docs/172 §9 P-natural-2)")
    print(f"  paired tasks={len(common)}  natural rewinds fired={fired_total}")
    print("=" * 76)
    print(f"  {'class':<12}{'fired runs':>12}{'help-flips':>12}{'hurt-flips':>12}{'net':>8}")
    print("-" * 76)
    for cls in ("varying", "same", "unknown"):
        d = by_class.get(cls)
        if not d or d["runs"] == 0:
            continue
        net = d["help"] - d["hurt"]
        print(f"  {cls:<12}{d['runs']:>12}{d['help']:>12}{d['hurt']:>12}{net:>+8}")
    print("-" * 76)
    print("  PREDICTION (§9 P-natural-2): varying net >= 0 (no harm where exploratory),")
    print("  same net <= 0 (upstream-omission livelock). CAVEAT: small-N, single flips are noise.")
    print("=" * 76)


if __name__ == "__main__":
    main()
