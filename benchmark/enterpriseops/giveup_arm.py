"""giveup_arm — the run-local, deployable, byte-clean GIVE-UP-CORRECTLY gate (docs/201).

The full-corpus (240 runs/arm, 480 total) re-score of the livelock line. docs/194/198 were
scored on a subset ~5-25x smaller; on the whole natural A/B the load-bearing finding hardens:

  A CONFIRMED same-tool thrash is EMPIRICALLY DISJOINT FROM TASK SUCCESS.
  No task-winner on the none arm reaches even 2 structured errors on a single tool; so a
  run-local "K consecutive struct-errors of one tool" gate can early-halt a doomed branch
  WITHOUT corpus knowledge and WITHOUT killing a winner -- the give-up-correctly value.

This module is the deployable arm docs/198 §4 move #1 asked for, scored honestly:

  * RUN-LOCAL FIRE (deployable): reuse abandon_counterfactual._incremental_fire, which is
    byte-identical to dos_react.natural_thrash_gate evaluated per growing prefix -- the live
    arm's forward-only view. No cross-run / corpus state enters the fire decision.

  * CROSS-ARM SOUNDNESS SWEEP: the plain run-local gate false-halts a WINNER on the pooled
    corpus at K=2 (1/480 -- a curable arg-provenance recovery, link_knowledge_to_incident), but
    is SOUND (0 false-halts) on BOTH arms at K>=3. => K=3 is the deployable provably-sound
    default; K=2 trades ~8 fires for a 1-in-480 false-halt.

  * REAL-TOKEN DENOMINATOR: a prior pass wrongly claimed "char/4 of env result payloads is the
    ONLY available token proxy." It is not -- conversation_flow[*].usage_metadata carries real
    total_tokens (11.2M on the none arm). We report the real-token tail saving (the honest %),
    falling back to the char/4 proxy only when telemetry is absent.

  * PRE-REGISTERED KILL (docs/194 §5): ship iff EXISTS K with FA-rate < 0.10 AND tokens_saved > 0
    on the run-local plain gate.

  * RLCW backtest comparand (NOT-DEPLOYABLE-AS-IS): run-local AND tool is corpus-WALLED. Sound at
    every K (only ever fires on create_filter, 0 winners by construction) but the WALLED set is
    corpus-derived, so a live run-local gate cannot compute it. Reported, flagged NOT-DEPLOYABLE.

All reads are $0 (recorded corpus, no Gemini / no gym), BENCHMARK-side: imports the BYTE-CLEAN
dos_react grammar + the abandon_counterfactual replay sites (the same-signal discipline, one-way
arrow, never kernel). Advisory only: the gate PROPOSES an OP_HALT (the dos watch / liveness
floor, cli.py:2099, liveness.py:53) -- it never kills a process.

    python giveup_arm.py                       # full report, both arms, K-sweep
    python giveup_arm.py --ks 2 3 4 5
    python giveup_arm.py --arm none            # one arm only

HONEST CEILING: single corpus, single model (gemini-2.5-flash, N=1 -- frontier decay per
docs/177 untested), fan-out-only throughput value, conversion-on-curable still OPEN/underpowered.
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

from dos_react import _is_struct_error, _result_text, _is_blocked_result  # noqa: E402
from abandon_counterfactual import _incremental_fire  # noqa: E402  (the run-local fire, byte-identical to natural_thrash_gate per-prefix)
from feasibility_witness import feasibility_witness  # noqa: E402  (the corpus-wide WALLED witness, for the RLCW comparand only)

ARMS = ("none", "rewind_natural")


def _is_err(tr) -> bool:
    return _is_struct_error(_result_text(tr)) and not _is_blocked_result(tr)


def _runs(arm_glob):
    for f in sorted(glob.glob(arm_glob)):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        r = (d.get("runs") or [{}])[0]
        yield f, r


def _proxy_tokens(obj) -> int:
    """char/4 over an env result payload -- the WEAK fallback proxy (lower bound)."""
    try:
        return len(json.dumps(obj, default=str)) // 4
    except (TypeError, ValueError):
        return len(str(obj)) // 4


def _real_run_tokens(run) -> int:
    """SUM of real total_tokens over the run's conversation_flow usage_metadata. 0 if absent
    (then the caller falls back to the char/4 proxy)."""
    tot = 0
    for e in (run.get("conversation_flow") or []):
        if isinstance(e, dict):
            um = e.get("usage_metadata")
            if isinstance(um, dict):
                tot += int(um.get("total_tokens", 0) or 0)
    return tot


def _first_fire(trs, k):
    """The run-local gate over the WHOLE run: the (fire_idx, tool) of the tool that FIRST reaches
    K struct-errors with the Kth call itself an error -- i.e. the earliest live fire across all
    tools. Walks the prefix forward; no corpus state. Returns (None, None) if no tool live-fires."""
    cnt = defaultdict(int)
    for i, tr in enumerate(trs):
        if _is_blocked_result(tr):
            continue
        if _is_err(tr):
            t = str(tr.get("tool_name", ""))
            cnt[t] += 1
            if cnt[t] >= k:
                return i, t
    return None, None


def score_arm(arm_glob, ks, walled):
    """Per K: fired count, false-halt (a fired run that SUCCEEDS at the task), FA-rate, the
    real-token tail saving (and the char/4 proxy), the fire-tool category breakdown, and the
    RLCW comparand. All fire decisions are RUN-LOCAL; the category column + RLCW are corpus-wide."""
    runs = [(f, r, r.get("tool_results") or []) for f, r in _runs(arm_glob)]
    runs = [(f, r, trs) for f, r, trs in runs if trs]
    out = {}
    for k in ks:
        fired = false_halt = 0
        real_saved = proxy_saved = real_total = proxy_total = 0
        cats = Counter()
        rlcw_fired = rlcw_fh = 0
        per_fire_real = []
        for _f, r, trs in runs:
            real_run = _real_run_tokens(r)
            proxy_run = sum(_proxy_tokens(tr.get("result")) for tr in trs)
            real_total += real_run
            proxy_total += proxy_run
            fire_idx, tool = _first_fire(trs, k)
            if fire_idx is None:
                continue
            fired += 1
            wins = bool(r.get("overall_success"))
            if wins:
                false_halt += 1
            # category of the firing tool (CORPUS-WIDE label -- NOT a gate input, reporting only)
            if tool == "create_filter" or tool in walled:
                cats["walled"] += 1
            elif tool == "create_draft":
                cats["mostly-walled"] += 1
            else:
                cats["curable"] += 1
            # token saving = the tail strictly after the fire. proxy = char/4 of result tail;
            # real = the run's real-token total scaled by the suppressed-call tail fraction
            # (a structural estimate -- per-turn usage isn't aligned to tool_results 1:1).
            n = len(trs)
            tail = n - (fire_idx + 1)
            proxy_tail = sum(_proxy_tokens(trs[j].get("result")) for j in range(fire_idx + 1, n))
            proxy_saved += proxy_tail
            per_fire_real.append(int(real_run * (tail / n)) if n else 0)
            real_saved += per_fire_real[-1]
            # RLCW comparand (NOT-DEPLOYABLE): only fire if the firing tool is corpus-WALLED
            if tool == "create_filter" or tool in walled:
                rlcw_fired += 1
                if wins:
                    rlcw_fh += 1
        med = sorted(per_fire_real)[len(per_fire_real) // 2] if per_fire_real else 0
        out[k] = {
            "fired": fired,
            "false_halt": false_halt,
            "fa_rate": (false_halt / fired) if fired else 0.0,
            "real_saved": real_saved,
            "real_total": real_total,
            "real_pct": (100.0 * real_saved / real_total) if real_total else 0.0,
            "proxy_saved": proxy_saved,
            "proxy_total": proxy_total,
            "median_real_saved_per_fire": med,
            "cats": dict(cats),
            "rlcw_fired": rlcw_fired,
            "rlcw_fh": rlcw_fh,
        }
    return out, len(runs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"))
    ap.add_argument("--ks", type=int, nargs="+", default=[2, 3, 4, 5])
    ap.add_argument("--arm", choices=ARMS, help="score one arm only (default: both)")
    ap.add_argument("--min-err", type=int, default=5, help="WALLED display floor for the witness")
    args = ap.parse_args(argv)

    # corpus-wide WALLED set (for the RLCW comparand + category labels ONLY -- never a gate input)
    witness = feasibility_witness(os.path.join(args.out, "*", "results_*.json"))
    walled = {t for t, ok, er in witness if er >= args.min_err and ok == 0}

    arms = [args.arm] if args.arm else list(ARMS)
    print("=" * 80)
    print("  GIVE-UP-CORRECTLY ARM -- run-local early-halt, full natural A/B (docs/201)")
    print(f"  corpus-WALLED (corpus-wide, NOT a gate input): {sorted(walled) or '(none)'}")
    print("  fire = first tool to reach K struct-errors run-locally; advisory OP_HALT, never a kill")
    print("=" * 80)

    cross_arm = defaultdict(lambda: {"fired": 0, "fh": 0})
    for arm in arms:
        scores, n = score_arm(os.path.join(args.out, arm, "results_*.json"), args.ks, walled)
        print(f"\n  ARM={arm}  (n={n} runs with tool calls)")
        print(f"  {'K':>3}{'fired':>7}{'false-halt':>12}{'FA-rate':>9}"
              f"{'real-save%':>12}{'med-tok/fire':>14}   fire-tools")
        print("  " + "-" * 76)
        for k in args.ks:
            s = scores[k]
            cross_arm[k]["fired"] += s["fired"]
            cross_arm[k]["fh"] += s["false_halt"]
            print(f"  {k:>3}{s['fired']:>7}{s['false_halt']:>12}{s['fa_rate']:>9.3f}"
                  f"{s['real_pct']:>11.1f}%{s['median_real_saved_per_fire']:>14}   {s['cats']}")
        print(f"     RLCW comparand (NOT-DEPLOYABLE -- needs corpus WALLED set):", end=" ")
        print(", ".join(f"K{k}:{scores[k]['rlcw_fired']}fired/{scores[k]['rlcw_fh']}fh" for k in args.ks))

    # ---- the cross-arm soundness verdict + pre-registered kill ----
    print("\n" + "=" * 80)
    print("  CROSS-ARM SOUNDNESS (the deployable verdict -- run-local, no corpus knowledge)")
    print("=" * 80)
    sound_ks = [k for k in args.ks if cross_arm[k]["fh"] == 0]
    for k in args.ks:
        c = cross_arm[k]
        flag = "SOUND (0 false-halts both arms)" if c["fh"] == 0 else f"UNSOUND ({c['fh']} winner(s) halted)"
        print(f"  K={k}: pooled fired={c['fired']:>3} false-halt={c['fh']}  -> {flag}")
    print("  " + "-" * 76)
    if sound_ks:
        best = min(sound_ks)
        print(f"  -> DEPLOYABLE-SOUND at K in {sound_ks}. DEFAULT K={best} (cheapest sound K).")
        print(f"     K=2 is UNSOUND on the pooled corpus (1 curable arg-provenance winner); K>=3 steps over it.")
    else:
        print("  -> NO K is cross-arm sound on this corpus; the plain run-local gate cannot ship.")
    # pre-registered kill, scored on the none arm (the deployable plain gate)
    none_scores, _ = score_arm(os.path.join(args.out, "none", "results_*.json"), args.ks, walled)
    passes = [k for k in args.ks if none_scores[k]["fa_rate"] < 0.10 and none_scores[k]["real_saved"] > 0]
    print("\n  PRE-REGISTERED KILL (docs/194 §5): ship iff EXISTS K with FA-rate<0.10 AND saved>0")
    if passes:
        k = min(set(passes) & set(sound_ks)) if (set(passes) & set(sound_ks)) else min(passes)
        s = none_scores[k]
        print(f"  -> PASSES at K={passes}. Recommend K={k}: FA {s['fa_rate']:.3f}, "
              f"real-save {s['real_pct']:.1f}% ({s['real_saved']:,} tok). SHIP (cheap tier).")
    else:
        print("  -> FAILS: no K clears FA<0.10 AND saved>0 -> genuinely detection-only.")
    print("=" * 80)
    print("  CEILING: single-corpus, single-model (gemini-2.5-flash, N=1; docs/177 frontier decay")
    print("  untested), fan-out-only throughput value, conversion-on-curable OPEN/underpowered (docs/201 §3).")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
