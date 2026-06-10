"""abandon_counterfactual — the CORRECTED $0 replay for early-halt cost-aversion (docs/194 §5).

docs/194 kills every in-loop CONVERSION cure for the dominant natural thrash (schema-blindness:
create_filter wrong-key / update_vacation_settings wrong-type — unwinnable by an advisory
byte-clean cure). The one surviving value is EARLY-HALT COST-AVERSION for the cheap-model fleet
tier: on a confirmed same-tool error livelock, HALT and reap, banking tokens-averted — NOT
agent pass-rate.

But the adversarial verify (docs/194 §1, candidate 3) found the prior abandon $0 gate LIED: it
fired on the FULL post-hoc stream (0/13 false-abandon) while the LIVE arm fires INCREMENTALLY
(at the first Kth same-tool error) and **42% of fired runs SELF-RECOVER later** (the tool
succeeds at call 5-6 after failing at 1-2). The full-stream gate cannot see its own failure
mode. This replay fixes that, exactly per docs/194 §5:

  * INCREMENTAL gate — fire at the first call where `tool_name` has reached K structured errors
    AND the latest result is still an error (the live `natural_thrash_gate` site, dos_react:1056,
    replayed over GROWING prefixes, not the whole stream).
  * K-SWEEP — K in {2,3,4}. The natural recovery window extends to call 5-6, so K=2 (the current
    live default) over-fires; K>=3 is the candidate.
  * WITHIN-TOOL-RECOVERY look-ahead — a fire is a FALSE-ABANDON iff the SAME tool returns a
    NON-error result anywhere AFTER the fire point in the (un-halted) none run. This is the 42%
    the old gate hid.
  * NET-TOKENS-AVERTED — averted-tail tokens MINUS the tokens of successful tail calls destroyed.
    A char/4 proxy over the env result payloads (the restart_arm.estimate_window_tokens rule);
    the RELATIVE quantity is what the pre-registration needs.

PRE-REGISTERED KILL CRITERION (docs/194 §5): ship the abandon arm only if EXISTS K with
false_abandon_rate < 0.10 AND net_tokens_averted > 0. If no K clears it, cost-aversion is ALSO
refuted and the honest output is "detection-only, no actuation" for this class.

This is BENCHMARK-side (imports `dos_react` for the BYTE-IDENTICAL struct-error grammar — the
"same signal not a look-alike" discipline; one-way arrow, never kernel) and $0 (reads the
recorded corpus, no Gemini / no gym). Run:

    python abandon_counterfactual.py                       # default corpus + K-sweep {2,3,4}
    python abandon_counterfactual.py --ks 2 3 4 5 --out live_results_natural_ab
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

# BYTE-IDENTICAL grammar reuse — the live gate's own struct-error detector + result-text +
# block-synthetic guard. Importing them (not re-implementing) is what makes this replay's fire
# condition the SAME signal as dos_react.natural_thrash_gate, not a parallel look-alike.
from dos_react import _is_struct_error, _result_text, _is_blocked_result  # noqa: E402


def _est_tokens(obj) -> int:
    """char/4 proxy for the tokens a tool-result payload costs (the restart_arm rule). The
    ledger needs the RELATIVE quantity (averted vs destroyed), and char/4 preserves the ordering.
    """
    try:
        return len(json.dumps(obj, default=str)) // 4
    except (TypeError, ValueError):
        return len(str(obj)) // 4


def _own_calls(tool_results, tool_name):
    """The (index, entry) pairs for `tool_name`, excluding DOS BLOCK synthetics (the corpus is the
    plain `none` arm, so there are none — the guard mirrors natural_thrash_gate for safety)."""
    return [(i, tr) for i, tr in enumerate(tool_results)
            if str(tr.get("tool_name", "")) == tool_name and not _is_blocked_result(tr)]


def _incremental_fire(tool_results, tool_name, k):
    """The LIVE incremental gate, replayed: the index of the call at which `tool_name` FIRST
    reaches its Kth structured error AND that latest call is itself an error. Returns the
    tool_results index of that firing call, or None if `tool_name` never live-fires at K.

    This walks the stream forward (the live arm's view: it only sees the prefix so far), counting
    this tool's structured errors; it fires the instant the count hits K on a call whose own
    result is an error — exactly natural_thrash_gate's (n_fail >= K AND latest-is-error) test, but
    evaluated at each prefix instead of once on the whole stream.
    """
    err_count = 0
    for i, tr in enumerate(tool_results):
        if str(tr.get("tool_name", "")) != tool_name or _is_blocked_result(tr):
            continue
        is_err = _is_struct_error(_result_text(tr))
        if is_err:
            err_count += 1
            if err_count >= k:
                return i  # fire here: Kth error reached, and THIS call is the error
    return None


def _recovers_after(tool_results, tool_name, fire_idx):
    """WITHIN-TOOL-RECOVERY look-ahead: does `tool_name` return a NON-error result anywhere AFTER
    `fire_idx` in the un-halted run? True ⇒ the live abandon would have KILLED the agent before
    its own recovery (a FALSE-ABANDON). This is the 42% the full-stream gate hid."""
    for i, tr in enumerate(tool_results):
        if i <= fire_idx:
            continue
        if str(tr.get("tool_name", "")) != tool_name or _is_blocked_result(tr):
            continue
        if not _is_struct_error(_result_text(tr)):
            return True
    return False


def _tail_token_ledger(tool_results, fire_idx):
    """Net tokens the abandon AVERTS at `fire_idx`: the whole tail (calls strictly after fire_idx)
    would not be paid → averted; but any SUCCESSFUL (non-error) call in that tail is productive
    work DESTROYED → subtracted. Returns (averted_total, destroyed_success). Net = averted -
    destroyed."""
    averted = 0
    destroyed = 0
    for i, tr in enumerate(tool_results):
        if i <= fire_idx:
            continue
        t = _est_tokens(tr.get("result"))
        averted += t
        if not _is_struct_error(_result_text(tr)) and not _is_blocked_result(tr):
            destroyed += t
    return averted, destroyed


def _run0(path):
    try:
        return (json.load(open(path, encoding="utf-8")).get("runs") or [{}])[0]
    except Exception:
        return {}


def _thrash_tools(tool_results, k):
    """The tools that LIVE-fire at K in this run (reach K struct errors with the Kth still
    erroring). Returns {tool_name: fire_idx} — the first such tool by fire index is the one the
    live arm would actually halt on (it halts the first time any tool fires)."""
    fires = {}
    for tool_name in {str(tr.get("tool_name", "")) for tr in tool_results if tr.get("tool_name")}:
        idx = _incremental_fire(tool_results, tool_name, k)
        if idx is not None:
            fires[tool_name] = idx
    return fires


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"),
                    help="the A/B dir; reads <out>/none")
    ap.add_argument("--ks", type=int, nargs="+", default=[2, 3, 4],
                    help="the K values (consecutive-error threshold) to sweep")
    args = ap.parse_args(argv)

    none_dir = os.path.join(args.out, "none")
    files = sorted(glob.glob(os.path.join(none_dir, "results_*.json")))
    if not files:
        print(f"no none-arm runs under {none_dir}", file=sys.stderr)
        return 2

    runs = []
    for f in files:
        r = _run0(f)
        trs = r.get("tool_results") or []
        if trs:
            runs.append((os.path.basename(f), r, trs))

    print("=" * 84)
    print("  ABANDON COST-AVERSION — corrected incremental $0 replay (docs/194 §5)")
    print(f"  corpus: {none_dir}   runs-with-calls: {len(runs)}")
    print("  gate: live-incremental (fire at first Kth same-tool struct error, latest=error)")
    print("  false-abandon: SAME tool returns a non-error result AFTER the fire point")
    print("=" * 84)
    header = (f"  {'K':>3}{'fired runs':>12}{'false-abandon':>15}"
              f"{'FA-rate':>9}{'net tok averted':>17}{'gross averted':>15}{'destroyed':>11}")
    print(header)
    print("-" * 84)

    summary = {}
    for k in args.ks:
        fired = 0
        false_abandon = 0
        net_averted = 0
        gross_averted = 0
        destroyed_total = 0
        fired_detail = []
        for name, r, trs in runs:
            fires = _thrash_tools(trs, k)
            if not fires:
                continue
            # the live arm halts the FIRST time any tool fires → take the min fire index
            tool_name, fire_idx = min(fires.items(), key=lambda kv: kv[1])
            fired += 1
            recovered = _recovers_after(trs, tool_name, fire_idx)
            if recovered:
                false_abandon += 1
            averted, destroyed = _tail_token_ledger(trs, fire_idx)
            gross_averted += averted
            destroyed_total += destroyed
            net_averted += (averted - destroyed)
            fired_detail.append((name, tool_name, fire_idx, recovered, averted - destroyed))
        fa_rate = (false_abandon / fired) if fired else 0.0
        summary[k] = {
            "fired": fired, "false_abandon": false_abandon, "fa_rate": fa_rate,
            "net_averted": net_averted, "gross_averted": gross_averted,
            "destroyed": destroyed_total, "detail": fired_detail,
        }
        print(f"  {k:>3}{fired:>12}{false_abandon:>15}{fa_rate:>9.2f}"
              f"{net_averted:>17}{gross_averted:>15}{destroyed_total:>11}")

    print("-" * 84)
    # the pre-registered kill criterion (docs/194 §5)
    survivors = [k for k, s in summary.items() if s["fa_rate"] < 0.10 and s["net_averted"] > 0]
    print("  PRE-REGISTERED KILL (docs/194 §5): ship abandon iff EXISTS K with")
    print("    false_abandon_rate < 0.10  AND  net_tokens_averted > 0")
    if survivors:
        best = max(survivors, key=lambda k: summary[k]["net_averted"])
        print(f"  -> SURVIVES at K={survivors}  (best K={best}: "
              f"FA-rate {summary[best]['fa_rate']:.2f}, net averted {summary[best]['net_averted']}).")
        print(f"     Cost-aversion SHIPS (cheap-model fleet tier) at K={best}. Owns: decays on")
        print(f"     frontier (docs/177), 0 at N=1 (throughput needs fanout).")
    else:
        print("  -> NO K CLEARS IT. Cost-aversion is ALSO refuted on this corpus.")
        print("     Honest output for the schema-blindness class: DETECTION-ONLY, no actuation.")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
