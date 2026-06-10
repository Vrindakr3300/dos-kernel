"""Read the per-arm live-run result dirs and report the DOS-mechanism stats + scores.

Beyond live_ab.py's success/verifier table, this pulls the `dos_arg_provenance` metadata
each dos_react run records (calls_seen / mints_injected / nudges_injected / blocks / defers /
observes) so we can see the MECHANISM, not just the outcome:

  * catch rate         — nudges_injected / mints_injected (the detector's live recall)
  * intervention mix   — blocks vs defers vs observes per arm (what the policy actually DID)
  * per-arm scores     — success / verifier-pass / integrity (joined from score_ab)

This is the read side of the THEORY_LADDER: it turns a finished live run into the numbers
the Tier-0 sweep said to watch. (mattered_rate — did a caught FK feed a verifier — needs a
deeper FK↔verifier join and is a follow-up; this reports what the result files carry today.)

    python analyze_live.py                       # reads ./live_results/<arm>/
    python analyze_live.py --out some/other/dir
"""

from __future__ import annotations

import argparse
import glob
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _arm_stats(arm_dir: str) -> dict:
    """Sum the dos_arg_provenance mechanism stats across a run dir's result files."""
    agg = {"calls_seen": 0, "mints_injected": 0, "nudges_injected": 0,
           "blocks": 0, "defers": 0, "observes": 0, "tasks": 0, "errored": 0}
    for f in glob.glob(os.path.join(arm_dir, "results_*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        agg["tasks"] += 1
        for run in d.get("runs", []):
            if run.get("error"):
                agg["errored"] += 1
            # dos_react records its mechanism stats as a TOP-LEVEL `dos_arg_provenance` key on
            # each run (not under result_metadata), so read it there.
            st = run.get("dos_arg_provenance") or {}
            for k in ("calls_seen", "mints_injected", "nudges_injected",
                      "blocks", "defers", "observes"):
                agg[k] += int(st.get(k, 0) or 0)
    return agg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results"))
    ap.add_argument("--arms", nargs="+", default=["none", "defer", "warn", "block"])
    args = ap.parse_args(argv)

    print("=" * 84)
    print("  LIVE-RUN MECHANISM REPORT — what the detector caught + what each policy DID")
    print("=" * 84)
    print(f"  {'arm':<7}{'tasks':>6}{'mut-calls':>10}{'mints':>7}{'nudges':>8}"
          f"{'catch%':>8}{'blocks':>8}{'defers':>8}{'observes':>9}{'err':>5}")
    print("-" * 84)
    for arm in args.arms:
        d = os.path.join(args.out, arm)
        if not os.path.isdir(d):
            continue
        s = _arm_stats(d)
        catch = (100.0 * s["nudges_injected"] / s["mints_injected"]) if s["mints_injected"] else 0.0
        print(f"  {arm:<7}{s['tasks']:>6}{s['calls_seen']:>10}{s['mints_injected']:>7}"
              f"{s['nudges_injected']:>8}{catch:>8.1f}{s['blocks']:>8}{s['defers']:>8}"
              f"{s['observes']:>9}{s['errored']:>5}")
    print("-" * 84)
    print("  catch% = nudges/mints (live detector recall). blocks/defers/observes = the")
    print("  intervention mix the policy enacted.")

    # --- the SCORE side, joined in: per-arm integrity/verifier delta vs the none baseline ---
    try:
        import sys
        sys.path.insert(0, _HERE)
        from score_ab import load_arm, load_config_verifier_types, summarize
        sample = os.path.join(args.out, "_sample")
        if os.path.isdir(sample):
            vtypes = load_config_verifier_types(sample)
            present = [a for a in args.arms if os.path.isdir(os.path.join(args.out, a))]
            data = {a: load_arm(os.path.join(args.out, a), vtypes) for a in present}
            paired = sorted(set.intersection(*[set(data[a]) for a in present])) if data else []
            if paired:
                base = summarize(data["none"], paired) if "none" in data else None
                bv = base["verifier_pass_rate"] if base else 0.0
                print("\n  SCORES (paired on %d task(s) all arms completed):" % len(paired))
                print(f"  {'arm':<8}{'success%':>9}{'verifier%':>11}{'integrity%':>12}"
                      f"{'i_total':>8}{'vΔ vs none':>12}")
                for a in present:
                    s = summarize(data[a], paired)
                    dv = "" if a == "none" else f"{s['verifier_pass_rate']-bv:>+12.1f}"
                    print(f"  {a:<8}{s['success_rate']:>9.1f}{s['verifier_pass_rate']:>11.1f}"
                          f"{s['integrity_rate']:>12.1f}{s['integrity_total']:>8}{dv}")
                print("  vΔ vs none = verifier-pass delta vs the injected-but-uncorrected arm.")
    except Exception as e:  # pragma: no cover - analysis convenience only
        print(f"  (score join skipped: {e})")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
