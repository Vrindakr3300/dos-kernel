"""docs/150/152 — the FIX measurement: did the dangling-intent re-surface CONVERT a stop?

The companion to the DETECT replay (`replay_dangling.py`). The live `resurface` arm re-surfaces
the agent's OWN abandoned sentence at its stop event (DOS_DANGLING=1, mint 0 — natural failures).
This joins it to the paired `none` arm and answers the docs/150 §6 deferred question:

  Of the runs where the dangling-intent WARN FIRED, how many flipped a verifier (or the whole task)
  that the SAME task failed in the `none` arm — i.e. did re-surfacing the agent's own words convert
  a self-admitted premature stop into completed work?

Three numbers, reported separately so DETECT stays clean even if FIX is null (the detector-soundness
⊥ intervention-safety discipline, docs/143):
  * fire-rate      — fraction of `resurface` runs whose abandoned sentence got re-surfaced.
  * conversion     — of the FIRED+paired tasks, the help/hurt verifier-flip vs the none baseline.
  * net delta      — aggregate success / verifier-pass, resurface vs none (the headline, low-var).

Run AFTER the live A/B:
  python dangling_convert.py --out live_results_natural_run --sample live_results_natural_run/_sample
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the live_ab --out root (holds none/ + resurface/)")
    ap.add_argument("--sample", default=None, help="the _sample dir (for the integrity slice)")
    args = ap.parse_args(argv)

    out = os.path.abspath(args.out)
    sample = os.path.abspath(args.sample) if args.sample else os.path.join(out, "_sample")

    from score_ab import load_arm, load_config_verifier_types, summarize

    vtypes = load_config_verifier_types(sample)
    none = load_arm(os.path.join(out, "none"), vtypes)
    resurf = load_arm(os.path.join(out, "resurface"), vtypes)

    paired = sorted(set(none) & set(resurf))
    if not paired:
        print("no paired task_ids between none/ and resurface/ — did both arms run?")
        return 1

    # 1. aggregate (no pairing) — the robust headline.
    print("=" * 78)
    print(f"  DANGLING-INTENT live A/B — {len(paired)} paired tasks  (mint 0, natural failures)")
    print("=" * 78)
    sn, sr = summarize(none, paired), summarize(resurf, paired)
    print(f"  {'arm':<12}{'success%':>10}{'verifier%':>11}{'integrity%':>12}"
          f"{'dangle%':>9}{'fires':>7}")
    print("-" * 78)
    for label, s in (("none", sn), ("resurface", sr)):
        print(f"  {label:<12}{s['success_rate']:>10.1f}{s['verifier_pass_rate']:>11.1f}"
              f"{s['integrity_rate']:>12.1f}{s.get('dangling_run_rate', 0.0):>9.1f}"
              f"{s.get('dangling_warns', 0):>7}")
    print("-" * 78)
    print(f"  NET Δ  success {sr['success_rate'] - sn['success_rate']:+.1f}pp   "
          f"verifier {sr['verifier_pass_rate'] - sn['verifier_pass_rate']:+.1f}pp   "
          f"integrity {sr['integrity_rate'] - sn['integrity_rate']:+.1f}pp")
    print("  (verifier%/integrity% are low-variance; trust them over success% at small N.)")

    # 2. the conversion join — on the FIRED tasks only, did the re-surface flip the outcome?
    fired = [t for t in paired if (resurf[t]["dos"] or {}).get("dangling_warns", 0) > 0]
    print("\n" + "-" * 78)
    print(f"  CONVERSION — of {len(fired)} tasks where the re-surface FIRED, vs the same task in none:")
    print("-" * 78)
    help_succ = hurt_succ = same = 0
    vhelp = vhurt = 0
    for t in fired:
        ns, rs = none[t], resurf[t]
        # task-level flip
        if rs["success"] and not ns["success"]:
            help_succ += 1
        elif ns["success"] and not rs["success"]:
            hurt_succ += 1
        else:
            same += 1
        # verifier-count delta (the finer signal)
        vhelp += max(0, rs["n_pass"] - ns["n_pass"])
        vhurt += max(0, ns["n_pass"] - rs["n_pass"])
    print(f"  task-level:  {help_succ} fail→pass (converted)   {hurt_succ} pass→fail (derailed)   "
          f"{same} unchanged")
    print(f"  verifier-level (on fired tasks): +{vhelp} checks gained,  -{vhurt} checks lost,  "
          f"net {vhelp - vhurt:+d}")
    conv = (100.0 * help_succ / len(fired)) if fired else 0.0
    print(f"  CONVERSION RATE = {help_succ}/{len(fired)} = {conv:.0f}% of fired stops converted to a "
          f"task pass")
    print("=" * 78)
    print("  READING (docs/150 §5): DETECT is proven (the fires are real, against-interest, 0% false-")
    print("  fire on passed runs). FIX = the conversion rate above — re-surfacing the agent's OWN")
    print("  sentence supplies NO plan, so it converts only the stop the model already knew how to")
    print("  finish. A low conversion at a healthy fire-rate IS the honest detect-not-fix ceiling.")
    print("=" * 78)

    summary = {
        "paired": len(paired),
        "none": sn, "resurface": sr,
        "fired": len(fired),
        "converted_fail_to_pass": help_succ,
        "derailed_pass_to_fail": hurt_succ,
        "conversion_rate_pct": conv,
        "verifier_checks_gained_on_fired": vhelp,
        "verifier_checks_lost_on_fired": vhurt,
    }
    with open(os.path.join(out, "_dangling_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
