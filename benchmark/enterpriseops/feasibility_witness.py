"""feasibility_witness — the missing distinction: is a thrashing tool WALLED or CURABLE? (docs/198)

docs/194 §0.0 CORRECTION. The prior livelock line scored every cure against a contaminated
denominator: it tested "can DOS make the agent succeed?" on tasks that are INFEASIBLE
(create_filter: 0 successes / 278 errors in the natural A/B — the tool's schema demands all ~9
criteria fields non-empty, so "filter on sender only" cannot be expressed). You cannot cure an
infeasible task; measuring conversion there was a category error, and it produced every "refuted"
verdict (rewind −3, block −6, abandon "refuted").

This module computes the distinction that should have come FIRST:

  * FEASIBILITY WITNESS — a tool is WALLED iff it has 0 successful (non-error) results ANYWHERE in
    the corpus; CURABLE iff the same tool succeeds on some run (proving a path exists). The witness
    is ENV-AUTHORED (a non-error tool result is the gym's own reply), so it is byte-clean — the
    agent cannot forge that some OTHER run got a clean result.

  * CORRECTED ABANDON SCORE — early-halt cost-aversion, re-scored on the HONEST denominator. The
    prior abandon_counterfactual.py counted a "non-error tool result later" as self-recovery and
    so called abandon refuted (false-abandon 0.33-0.42). But a transient non-error on a run that
    STILL FAILS THE TASK is not recovery. Re-scored on overall_success: false-abandon = "abandon
    would have halted a run that actually SUCCEEDS at the task." On this corpus that is 0 at every
    K (there are no winning create_filter runs to kill), so abandon PASSES its pre-registered kill
    (FA < 0.10 AND net tokens saved > 0) — it is the SURVIVING value, not the refuted one.

Both reads are $0 (the recorded corpus, no Gemini / no gym), BENCHMARK-side (imports dos_react for
the BYTE-IDENTICAL struct-error grammar — the same-signal discipline, one-way arrow, never kernel).

    python feasibility_witness.py                      # both reads, all arms + the natural A/B
    python feasibility_witness.py --ks 2 3 4
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from dos_react import _is_struct_error, _result_text, _is_blocked_result  # noqa: E402


def _is_err(tr) -> bool:
    return _is_struct_error(_result_text(tr)) and not _is_blocked_result(tr)


def _est_tokens(obj) -> int:
    try:
        return len(json.dumps(obj, default=str)) // 4
    except (TypeError, ValueError):
        return len(str(obj)) // 4


def _runs(arm_glob):
    for f in sorted(glob.glob(arm_glob)):
        try:
            r = (json.load(open(f, encoding="utf-8")).get("runs") or [{}])[0]
        except Exception:
            continue
        yield f, r


def feasibility_witness(corpus_glob):
    """Per tool: (successes, errors). WALLED = 0 successes anywhere; CURABLE = has a success.
    A success is a non-error, non-blocked tool result (env-authored — the byte-clean witness)."""
    ok = defaultdict(int)
    err = defaultdict(int)
    for _f, r in _runs(corpus_glob):
        for tr in (r.get("tool_results") or []):
            t = str(tr.get("tool_name", ""))
            if not t:
                continue
            if _is_err(tr):
                err[t] += 1
            elif not _is_blocked_result(tr):
                ok[t] += 1
    tools = sorted(set(ok) | set(err), key=lambda x: -err.get(x, 0))
    return [(t, ok.get(t, 0), err.get(t, 0)) for t in tools]


def corrected_abandon(none_glob, ks):
    """Re-score early-halt on the TASK-SUCCESS denominator. Fire = first tool to reach K errors
    (Kth still erroring). false_abandon = the run's overall_success is True (we'd kill a winner).
    tokens_saved = char/4 over the result tail after the fire. Returns {k: stats}."""
    runs = [(f, r, r.get("tool_results") or []) for f, r in _runs(none_glob)]
    runs = [(f, r, trs) for f, r, trs in runs if trs]
    out = {}
    for k in ks:
        fired = false_abandon = tok_saved = 0
        for _f, r, trs in runs:
            cnt = defaultdict(int)
            fire_idx = None
            for i, tr in enumerate(trs):
                if _is_err(tr):
                    cnt[str(tr.get("tool_name", ""))] += 1
                    if cnt[str(tr.get("tool_name", ""))] >= k:
                        fire_idx = i
                        break
            if fire_idx is None:
                continue
            fired += 1
            if r.get("overall_success"):       # the HONEST false-abandon: halted a WINNING run
                false_abandon += 1
            for j in range(fire_idx + 1, len(trs)):
                tok_saved += _est_tokens(trs[j].get("result"))
        out[k] = {
            "fired": fired,
            "false_abandon": false_abandon,
            "fa_rate": (false_abandon / fired) if fired else 0.0,
            "tokens_saved": tok_saved,
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"))
    ap.add_argument("--ks", type=int, nargs="+", default=[2, 3, 4])
    ap.add_argument("--min-err", type=int, default=5, help="only show tools with >= this many errors")
    args = ap.parse_args(argv)

    # ---- READ 1: the feasibility witness, over the WHOLE A/B (all arms) ----
    all_glob = os.path.join(args.out, "*", "results_*.json")
    witness = feasibility_witness(all_glob)
    print("=" * 78)
    print("  FEASIBILITY WITNESS — is a thrashing tool WALLED or CURABLE? (docs/198)")
    print(f"  corpus: {all_glob}")
    print("=" * 78)
    print(f"  {'tool':<30}{'ok':>6}{'err':>6}   verdict")
    print("-" * 78)
    walled = []
    for t, ok, er in witness:
        if er < args.min_err:
            continue
        if ok == 0:
            v = "WALLED (0 success anywhere — INFEASIBLE)"
            walled.append(t)
        elif ok >= er * 0.2:
            v = "CURABLE (has successes — a path exists)"
        else:
            v = "mostly-walled"
        print(f"  {t:<30}{ok:>6}{er:>6}   {v}")
    print("-" * 78)
    print(f"  WALLED tools (conversion is a category error here): {walled or '(none)'}")
    print("  => A/B any CONVERSION cure on the CURABLE tools ONLY; on WALLED tools the")
    print("     only honest value is GIVE-UP-CORRECTLY (early-halt). Testing a cure on a")
    print("     WALLED tool produces a false 'refuted' (you cannot convert the unwinnable).")

    # ---- READ 2: the CORRECTED abandon score (task-success denominator) ----
    none_glob = os.path.join(args.out, "none", "results_*.json")
    ab = corrected_abandon(none_glob, args.ks)
    print()
    print("=" * 78)
    print("  EARLY-HALT (ABANDON), RE-SCORED on the TASK-SUCCESS denominator (docs/194 §0.0)")
    print("  false-abandon = abandon would halt a run that ACTUALLY SUCCEEDS (not a transient)")
    print("=" * 78)
    print(f"  {'K':>3}{'fired':>8}{'false-abandon':>15}{'FA-rate':>9}{'tokens saved':>14}")
    print("-" * 78)
    passes = []
    for k in args.ks:
        s = ab[k]
        if s["fa_rate"] < 0.10 and s["tokens_saved"] > 0:
            passes.append(k)
        print(f"  {k:>3}{s['fired']:>8}{s['false_abandon']:>15}{s['fa_rate']:>9.3f}{s['tokens_saved']:>14}")
    print("-" * 78)
    print("  PRE-REGISTERED KILL (docs/194 §5): ship iff EXISTS K: FA-rate<0.10 AND saved>0")
    if passes:
        best = min(passes)  # cheapest K that clears
        print(f"  -> PASSES at K={passes}. Early-halt is the SURVIVING value (cheapest K={best}:")
        print(f"     FA {ab[best]['fa_rate']:.3f}, {ab[best]['tokens_saved']} tokens saved). The prior")
        print(f"     'refuted' verdict was a denominator artifact (counted illusory tool-level")
        print(f"     'recovery' on runs that still FAILED the task). Corrected: SHIP it (cheap tier).")
    else:
        print("  -> still fails on the success denominator → genuinely detection-only.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
