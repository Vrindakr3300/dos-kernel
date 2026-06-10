"""stall_recovery_probe — does the byte-identical STALLED class self-recover? (docs/176 §6.2)

docs/191 measured the WHOLE natural-thrash population and found it uncurable in-loop (the
dominant class is varying-arg schema-blindness; even cost-aversion abandon fails its kill at
false-abandon ≈ 0.33). But docs/191's gate keyed on "K consecutive same-tool ERRORS" — the
ERROR-shaped trigger — which conflates the varying-branch majority with the byte-identical-LOOP
minority. THIS probe isolates the slice the docs/176 §6.1 STALLED trigger actually targets: runs
where the kernel `tool_stream.classify_stream` fires STALLED on a BYTE-IDENTICAL
`(tool, args, result)` run — and asks the only question that decides whether an in-loop prune is
net-positive on this slice: **does the stalled tool SELF-RECOVER after the fire point?**

A self-recovery is a FALSE-PRUNE: the agent escaped the byte-loop on its own, so subtracting it
destroyed productive work (the docs/191 false-abandon lesson, applied to the STALLED slice). A
non-recovery is a TRUE dead-end the prune correctly subtracts.

$0 / deterministic — pure replay of recorded `live_results_natural_ab/none` (gemini-2.5-flash),
no model / DB / Docker. Re-runnable; point --dir at any recorded none-arm corpus. The number it
prints is the STALLED-class false-prune rate, with its (small) sample size stated honestly.

The honest reading (as of the 2026-06-06 corpus, n=127 runs / 115 with calls):
  * STALLED fires on 3 runs (a 5.2% byte-identical loop rate — small but NON-zero, a distinct
    slice from the uncurable schema-blindness branch).
  * 2/3 are true dead-ends (create_filter, never recovers, overall_success=False) — a correct
    prune target.
  * 1/3 self-recovers (update_vacation_settings succeeds later) — a false prune.
  => false-prune ≈ 0.33, the SAME floor docs/191 found for the broader abandon gate. So even the
     byte-identical STALLED slice does NOT clear a <10% false-fire bar on this corpus → the
     STALLED→prune actuation must stay WARN-first / opt-in, not a default cut. (A prune is less
     destructive than an abandon — it truncates+retries rather than killing — but 1/3 is still
     too high to default-cut.)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "..", "..", "src")
if os.path.isdir(_SRC):
    sys.path.insert(0, _SRC)

from dos.tool_stream import StreamState, StreamStep, ToolStream, classify_stream  # noqa: E402


def _digest(obj) -> str:
    try:
        s = json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def _get_runs(d):
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    if isinstance(d, dict):
        return d.get("runs") if isinstance(d.get("runs"), list) else [d]
    return []


def _steps(run):
    out = []
    for tr in run.get("tool_results", []) or []:
        res = tr.get("result", None)
        out.append(StreamStep(
            tool_name=str(tr.get("tool_name", "")),
            args_digest=_digest(tr.get("arguments", {}) or {}),
            result_digest=None if res is None else _digest(res),
        ))
    return out


def _tool_succeeds_after(run, tool_name, after_idx) -> bool:
    """Does `tool_name` produce a NON-error success result at any tool_result strictly after
    `after_idx`? The self-recovery look-ahead (the docs/191 false-abandon discipline). Reads the
    ENV-authored result envelope only (never agent narration)."""
    trs = run.get("tool_results", []) or []
    for tr in trs[after_idx:]:
        if str(tr.get("tool_name", "")) != tool_name:
            continue
        r = tr.get("result", {})
        if not isinstance(r, dict):
            continue
        inner = r.get("result", r) if isinstance(r, dict) else {}
        is_err = isinstance(inner, dict) and (
            inner.get("isError") or "error" in str(inner).lower()[:48]
            or str(inner.get("status", "")).lower().find("error") >= 0
        )
        if r.get("success") is True and not is_err:
            return True
    return False


def analyze(run):
    """Return the STALLED-fire datum for one run, or None if it never STALLED (incremental fold)."""
    steps = _steps(run)
    fire_i = None
    for i in range(1, len(steps) + 1):
        if classify_stream(ToolStream(tuple(steps[:i]))).state is StreamState.STALLED:
            fire_i = i
            break
    if fire_i is None:
        return None
    stalled_tool = steps[fire_i - 1].tool_name
    recovered = _tool_succeeds_after(run, stalled_tool, fire_i)
    return {
        "tool": stalled_tool,
        "fire_at": fire_i,
        "total_calls": len(steps),
        "overall_success": bool(run.get("overall_success")),
        "self_recovered": recovered,   # True => a FALSE prune (the agent escaped on its own)
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(_HERE, "live_results_natural_ab", "none"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    files = glob.glob(os.path.join(args.dir, "**", "*.json"), recursive=True)
    n_runs = n_with_calls = 0
    fired = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for run in _get_runs(d):
            n_runs += 1
            if run.get("tool_results"):
                n_with_calls += 1
            row = analyze(run)
            if row is not None:
                row["file"] = os.path.basename(f)
                fired.append(row)

    n_fired = len(fired)
    n_false = sum(1 for r in fired if r["self_recovered"])
    n_true = n_fired - n_false
    fa_rate = (n_false / n_fired) if n_fired else 0.0

    summary = {
        "dir": args.dir,
        "runs": n_runs,
        "runs_with_calls": n_with_calls,
        "stalled_fired": n_fired,
        "stalled_fire_rate": round(n_fired / n_with_calls, 4) if n_with_calls else 0.0,
        "true_dead_ends": n_true,
        "false_prunes_self_recovered": n_false,
        "false_prune_rate": round(fa_rate, 4),
        "kill_bar": 0.10,
        "clears_kill_bar": fa_rate < 0.10 and n_fired > 0,
    }

    if args.json:
        print(json.dumps({"summary": summary, "fired": fired}, indent=2))
        return

    print("=" * 74)
    print("  STALLED-class self-recovery probe (docs/176 §6.2) — the false-prune rate")
    print("=" * 74)
    for k, v in summary.items():
        print(f"  {k:30} {v}")
    print("-" * 74)
    for r in fired:
        verdict = "FALSE-PRUNE (self-recovered)" if r["self_recovered"] else "true dead-end"
        print(f"  STALLED@{r['fire_at']:<3} {r['tool']:<26} success={r['overall_success']!s:<5} "
              f"calls={r['total_calls']:<3} -> {verdict}")
    print("-" * 74)
    if not summary["clears_kill_bar"]:
        print("  VERDICT: does NOT clear the <10% false-prune bar → STALLED->prune stays")
        print("  WARN-first / opt-in, never a default cut (the docs/191 lesson, this slice).")
    else:
        print("  VERDICT: clears the bar → a default STALLED->prune is defensible on this corpus.")
    print("=" * 74)


if __name__ == "__main__":
    main()
