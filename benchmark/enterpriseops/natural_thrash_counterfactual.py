"""natural_thrash_counterfactual.py — $0 replay: where would the NATURAL rewind have SUBTRACTED?

docs/172. The mint-injection regime (docs/143/rewind_counterfactual.py) MANUFACTURES the invented-FK-ID
failure mode that arg_provenance/rewind detect; on a capable model the natural mint rate is ~0, so it
is moot (the §5 prior). The operator's challenge (2026-06-06): *is minting the right framework, vs SOTA
concerns?* The answer the data gives is NO — and this replay is the proof on the NATURAL regime.

It feeds the REAL recorded `none`-arm trajectories (NO injection — the agent fails on its OWN) through
the SAME kernel verdict logic the live natural arm uses (`from dos.rewind import rewind_plan` +
`natural_thrash_gate` + `_is_struct_error`, imported from dos_react — no re-implementation). For each run
it asks: did some tool NATURALLY thrash (produce a STRUCTURED env error >=2× un-recovered)? If so, where
would the kernel place the rewind anchor (the last VERIFIED, non-error tool result), how many dead-end
turns does the subtract excise, and what byte-clean no-good note (the gym's OWN error bytes, THIRD_PARTY)
would it re-enter with.

What this CAN show ($0, exact, on a large corpus): the NATURAL fire rate (no minting), the anchor
placement on real data (0 UNANCHORED = the mechanism is not vacuous), the subtraction magnitude (real
accreted dead-end context the agent carried forward), and that the note is byte-clean on REAL natural
error bytes. What it CANNOT show: whether the agent then SUCCEEDS (that needs the live arm — the
conversion half). This is the DETECT/PLACEMENT half; live_ab.py --arms rewind_natural is the CONVERSION half.

CONSERVATIVE BY DESIGN (the verify-wf logic-parity finding): this replay UNDER-counts fires vs the live
arm, never over-counts. Two safe-direction divergences: (1) it records at most ONE fire per run (one
thrash_tool, then returns), while the live arm is one-shot PER TOOL and can fire on a 2nd thrashing tool;
(2) it selects a thrash_tool only if that tool's LAST result over the WHOLE run is still an error (a
future-information peek that SUPPRESSES fires the live prefix-gate would make). Measured: replay ~7 vs
live ~9-11 on the 100-run corpus. The headline fire count here is a conservative FLOOR on the live count,
and for the fires it DOES count, anchor/trigger placement matched the live arm 100% (0 mismatches).

Pure replay of recorded JSON — no model calls, no network. Point --dir at any `none` arm folder.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_DOS_SRC = os.path.join(_HERE, "..", "..", "src")
if os.path.isdir(_DOS_SRC):
    sys.path.insert(0, _DOS_SRC)

# import the REAL kernel verdict + the REAL gate/grammar (no re-implementation)
from dos.rewind import rewind_plan, TurnRef, FireVerdict, EnvExcerpt, digest_turn, Rewind  # noqa: E402
from dos.intent_ledger import SuspendCheckpoint  # noqa: E402
from dos.completion import Convergence  # noqa: E402
from dos.log_source import Accountability  # noqa: E402
from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED  # noqa: E402

# The byte-clean grammar + helpers are the SAME ones the live arm uses — import them off dos_react so
# the replay and the live run can never drift (the rewind_counterfactual.py "use the real logic" rule).
from dos_react import _is_struct_error, _result_text, _is_blocked_result, natural_thrash_gate  # noqa: E402


def _is_verified(tr) -> bool:
    """Last-known-good = a real result that is NOT a structured error. The gym sets outer
    success=True even on isError results, so reject struct-errors FIRST (the dos_react fix)."""
    if _is_blocked_result(tr):
        return False
    if _is_struct_error(_result_text(tr)):
        return False
    r = tr.get("result", {})
    if not isinstance(r, dict):
        return False
    if r.get("success") is True:
        return True
    inner = r.get("result", {})
    if isinstance(inner, dict):
        if inner.get("success") is True:
            return True
        st = str(inner.get("status", "")).lower()
        if st and "error" not in st and "blocked" not in st:
            return True
    return False


def analyze_run(run: dict) -> dict | None:
    """Apply the natural-thrash rewind to one recorded `none` run. None if no natural thrash."""
    trs = [tr for tr in (run.get("tool_results") or []) if not _is_blocked_result(tr)]
    if not trs:
        return None
    # Which tool naturally thrashed? (a tool with a struct-error result >=2x, latest still an error).
    failc = Counter()
    for tr in trs:
        if _is_struct_error(_result_text(tr)):
            failc[str(tr.get("tool_name", ""))] += 1
    thrash_tool = None
    for tn, c in failc.items():
        if c < 2:
            continue
        own = [tr for tr in trs if str(tr.get("tool_name", "")) == tn]
        if own and _is_struct_error(_result_text(own[-1])):
            thrash_tool = tn
            break
    if thrash_tool is None:
        return None

    # Confirm via the REAL gate (the same one the live arm fires on) — over the prefix ending at the
    # tool's 2nd failure, mirroring the live trigger point (it fires the moment the 2nd failure lands).
    fail_positions = [i for i, tr in enumerate(trs)
                      if str(tr.get("tool_name", "")) == thrash_tool
                      and _is_struct_error(_result_text(trs[i]))]
    trigger_idx = fail_positions[1]  # the 2nd failure of the thrashed tool
    prefix = trs[: trigger_idx + 1]
    gate = natural_thrash_gate(prefix, thrash_tool)
    if gate is None:
        return None
    n_fail, env_excerpt = gate

    # Place the anchor at the last VERIFIED turn strictly before the trigger (last-known-good).
    anchor_idx = -1
    for i in range(trigger_idx - 1, -1, -1):
        if _is_verified(prefix[i]):
            anchor_idx = i
            break

    turns = tuple(
        TurnRef(i, digest_turn(json.dumps(
            {"t": tr.get("tool_name"), "s": str(tr.get("result"))[:64]}, sort_keys=True)))
        for i, tr in enumerate(prefix)
    )
    if anchor_idx >= 0:
        cp = SuspendCheckpoint(turn_index=anchor_idx,
                               transcript_digest=turns[anchor_idx].digest, present=True)
    else:
        cp = SuspendCheckpoint.absent()

    tokens = (VerdictToken(KIND_VERIFY_NOT_SHIPPED,
                           {"sha": f"{thrash_tool}=failed-{n_fail}x-unrecovered"}),)
    env = EnvExcerpt(env_excerpt, Accountability.THIRD_PARTY)  # the gym's OWN error bytes
    plan = rewind_plan(turns, cp, FireVerdict.from_convergence(Convergence.THRASHING),
                       verdict_tokens=tokens, env_excerpt=env)

    return {
        "thrash_tool": thrash_tool,
        "n_tool_results": len(trs),
        "natural_failures_of_tool": n_fail,
        "trigger_idx": trigger_idx,
        "anchor_idx": anchor_idx,
        "verdict": plan.verdict.value,
        "rewind_to_turn": plan.rewind_to_turn,
        "dropped_turns": list(plan.dropped_turns),
        "turns_subtracted": len(plan.dropped_turns),
        "no_good_note": list(plan.no_good_note.render_lines()),
        "overall_success": bool(run.get("overall_success")),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(_HERE, "live_results_natural_run", "none"),
                    help="a `none`-arm result folder (no mint injection)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.dir, "*.json")))
    results = []
    n_runs = 0
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for run in d.get("runs", []):
            n_runs += 1
            r = analyze_run(run)
            if r is not None:
                r["file"] = os.path.basename(f)
                results.append(r)

    rewinds = [r for r in results if r["verdict"] == Rewind.REWIND.value]
    total_sub = sum(r["turns_subtracted"] for r in rewinds)
    summary = {
        "as_of": "2026-06-06",
        "dir": args.dir,
        "n_files": len(files),
        "n_runs": n_runs,
        "natural_thrash_runs_found": len(results),
        "natural_thrash_rate_pct": round(100.0 * len(results) / n_runs, 1) if n_runs else 0.0,
        "rewind_fired": len(rewinds),
        "unanchored": sum(1 for r in results if r["verdict"] == Rewind.UNANCHORED.value),
        "no_rewind": sum(1 for r in results if r["verdict"] == Rewind.NO_REWIND.value),
        "total_dead_end_turns_subtracted": total_sub,
        "thrash_run_success": f"{sum(1 for r in results if r['overall_success'])}/{len(results)}",
    }

    if args.json:
        print(json.dumps({"summary": summary, "runs": results}, indent=2))
        return

    print("=== NATURAL fail-thrash counterfactual on the REAL none arm (no minting, 2026-06-06) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\n=== per-natural-thrash-run (where SUBTRACT would have fired, mint-free) ===")
    for r in results:
        print(f"\n  {r['file']}")
        print(f"    thrash on {r['thrash_tool']}  natural_failures={r['natural_failures_of_tool']}  "
              f"success={r['overall_success']}")
        print(f"    verdict={r['verdict']}  anchor=turn {r['anchor_idx']}  "
              f"dropped={r['dropped_turns']}  subtracted={r['turns_subtracted']}")
        if r["no_good_note"] and r["verdict"] != "NO_REWIND":
            print("    no-good note (byte-clean, the gym's OWN error bytes — re-entered, not appended):")
            for line in r["no_good_note"]:
                print(f"      | {line}")


if __name__ == "__main__":
    main()
