"""$0 VALIDATION of the docs/236 §5 keystone (ΔB(non-LLM)=+1.0) — replaces its two FIATS
with the REAL per-row env witness already on disk. No model, no network.

THE CRITIQUE THIS TESTS
-----------------------
peer_b_nonllm.measure() reports ΔB(non-LLM)=+1.0 on the 5-row flash over-claim slice. That
number rests on TWO assumptions baked into `peer_b.nonllm_outcome`, neither read from data:

  (A) believe -> PROCEED -> FAIL     assumes the inherited phantom is HARMFUL to B's task.
  (B) adjudicate -> REDO -> SUCCESS  assumes B's redo REACHES gold (the redo is feasible).

We have the live LLM peer-B run (`live_results_peerb_flash25`) which ran BOTH arms on these
exact tasks and read B's OWN db_match. So we can check both fiats against ground truth:

  * Fiat (B) is FALSE wherever NEITHER arm ever reached db_match=True (the task is not
    reachable-to-gold for this B — docs/198 infeasibility). Scoring adjudicate=SUCCESS there
    is counterfactually wrong.
  * Fiat (A) is FALSE wherever the BELIEVE arm itself reached db_match=True (the phantom was
    harmless / B punted to the same gold state). Scoring believe=FAIL there is wrong too.

The HONEST causal ΔB on the slice is read straight from the live arms:
    ΔB_real = mean[ success(adjudicate) - success(believe) ]   over the slice,
where success := (db_match is True), the env's own verdict. No fiat.

USAGE
    python -m benchmark.agentprocessbench.writeadmit._validate_keystone \
        --a-dir live_results_m1_flash25 --b-dir live_results_peerb_flash25
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# The summary prints a Δ glyph; force UTF-8 on a cp1252 Windows console so the tool is
# self-contained (no PYTHONIOENCODING needed). No-op where the stream is already UTF-8.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from peer_b import AHandoff  # noqa: E402


def _load(d):
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            r = json.loads(open(f, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            continue
        out[os.path.basename(f)] = r
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-dir", required=True, help="run_writeadmit A-row dir (the slice source)")
    ap.add_argument("--b-dir", required=True, help="live peer-B run dir (both arms, real db_match)")
    args = ap.parse_args(argv)

    a_rows = [r for r in _load(args.a_dir).values() if isinstance(r, dict) and not r.get("error")]
    overclaims = [AHandoff.from_row(r) for r in a_rows]
    overclaims = [a for a in overclaims if a.is_overclaim]

    b = _load(args.b_dir)

    print("=" * 92)
    print("KEYSTONE VALIDATION (docs/236 §5) — synthetic +1.0 vs the REAL live arms ($0)")
    print("=" * 92)
    print(f"  over-claim slice: {len(overclaims)} rows from {os.path.basename(args.a_dir)}")
    print(f"  {'task':<14}{'believe db':<13}{'adj db':<11}{'feasible?':<11}{'phantom-harmful?':<18}real-flip")
    print("  " + "-" * 88)

    n = 0
    real_flip = 0          # adjudicate succeeded AND believe failed, off the live witness
    synth_flip = 0         # what the non-LLM arm counts (always 1 per blocked over-claim)
    infeasible = 0         # neither arm reached gold (fiat B false)
    harmless = 0           # believe itself reached gold (fiat A false)
    for a in overclaims:
        bk = f"{a.domain}__{a.task_id}__believe.json"
        ak = f"{a.domain}__{a.task_id}__adjudicate.json"
        if bk not in b or ak not in b:
            print(f"  {a.domain+'/'+a.task_id:<14}(no live B-rows — skipped)")
            continue
        n += 1
        bdb = b[bk].get("db_match")
        adb = b[ak].get("db_match")
        bel_ok = bdb is True
        adj_ok = adb is True
        feasible = bel_ok or adj_ok
        if not feasible:
            infeasible += 1
        if bel_ok:
            harmless += 1
        flip = adj_ok and not bel_ok
        if flip:
            real_flip += 1
        synth_flip += 1  # the non-LLM arm scores every blocked over-claim as a deflection
        print(f"  {a.domain+'/'+a.task_id:<14}{str(bdb):<13}{str(adb):<11}"
              f"{('yes' if feasible else 'NO'):<11}{('yes' if not bel_ok else 'NO (punted/match)'):<18}"
              f"{'FLIP' if flip else '.'}")

    print("  " + "-" * 88)
    synth_dB = synth_flip / n if n else 0.0
    real_dB = real_flip / n if n else 0.0
    print(f"  non-LLM SYNTHETIC ΔB (peer_b_nonllm):  {synth_dB:+.2f}  ({synth_flip}/{n})  "
          f"<- both fiats applied")
    print(f"  REAL causal ΔB (live arms, db_match):  {real_dB:+.2f}  ({real_flip}/{n})  "
          f"<- env witness, no fiat")
    print("  " + "-" * 88)
    print(f"  rows where fiat-B (redo->gold) is FALSE (infeasible): {infeasible}/{n}")
    print(f"  rows where fiat-A (phantom harmful) is FALSE (believe already gold): {harmless}/{n}")
    print(f"  => honest upper bound on this slice = (feasible AND phantom-harmful) rows")
    honest_ub = sum(
        1 for a in overclaims
        if (f"{a.domain}__{a.task_id}__believe.json" in b and f"{a.domain}__{a.task_id}__adjudicate.json" in b)
        and not (b[f"{a.domain}__{a.task_id}__believe.json"].get("db_match") is True)  # phantom harmful
        and (b[f"{a.domain}__{a.task_id}__believe.json"].get("db_match") is True
             or b[f"{a.domain}__{a.task_id}__adjudicate.json"].get("db_match") is True)  # feasible
    )
    print(f"     honest upper bound = {honest_ub}/{n} = {(honest_ub/n if n else 0):.2f}  "
          f"(vs the claimed 1.00)")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
