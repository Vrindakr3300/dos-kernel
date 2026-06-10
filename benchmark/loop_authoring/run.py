"""CLI — `python -m benchmark.loop_authoring.run`.

Step 1 (free, no spend): generate a corpus of realistic trajectories by walking
the kernel's transition relation, score the SIMULATED prose arm against the kernel
ground truth, and print the detector + payoff + fleet-multiplier headline.

⚠ The Step-1 `d` is a DEMONSTRATION OF THE MACHINERY AND THE FORMULA, not a
measured divergence rate — the simulated prose drop-rates are assumptions (see
prose_arm.py's honesty boundary). The real `d` comes from the live arm (Step 2)
and captured logs (Step 3). The banner re-states this so a reader of the output
cannot mistake the simulated figure for a measurement.

Examples:
  python -m benchmark.loop_authoring.run                      # default mix, 500 trajectories
  python -m benchmark.loop_authoring.run --stress --n 2000    # tilt to hard rungs, more power
  python -m benchmark.loop_authoring.run --faithful           # identity test: must print d=0
  python -m benchmark.loop_authoring.run --json               # machine-readable
"""

from __future__ import annotations

import argparse
import json

from benchmark.loop_authoring.generate import OutcomeMix, generate_corpus
from benchmark.loop_authoring.prose_arm import DropRates, SimulatedProseDecider
from benchmark.loop_authoring.score import Pricing, score_corpus


_BANNER = (
    "loop_authoring — docs/260 Step 1 (SIMULATED prose arm, FREE).\n"
    "  The reference is loop_decide.decide (pure, 101-case-pinned) — NOT a model.\n"
    "  ⚠ This d is a MACHINERY+FORMULA demo on ASSUMED drop-rates, not a measured\n"
    "    divergence rate. Real d := the live arm (Step 2) + captured logs (Step 3)."
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loop_authoring")
    ap.add_argument("--n", type=int, default=500, help="number of trajectories")
    ap.add_argument("--seed", type=int, default=0, help="base RNG seed")
    ap.add_argument("--horizon", type=int, default=40, help="max ticks per trajectory")
    ap.add_argument("--gate-mode", default="hard", choices=["hard", "soft", "drive"])
    ap.add_argument("--stress", action="store_true", help="tilt mix to the hard rungs")
    ap.add_argument(
        "--faithful",
        action="store_true",
        help="perfect prose applier (all drop-rates 0) — identity test, must give d=0",
    )
    ap.add_argument("--drop-seed", type=int, default=7, help="seed for the prose simulator")
    ap.add_argument(
        "--fleet",
        default="1,4,8,16,32",
        help="comma-separated K values for the fleet multiplier",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    mix = OutcomeMix.stress() if args.stress else OutcomeMix()
    corpus = generate_corpus(
        args.n, base_seed=args.seed, mix=mix, gate_mode=args.gate_mode, horizon=args.horizon
    )
    drops = DropRates.faithful() if args.faithful else DropRates()
    decider = SimulatedProseDecider(drops=drops, seed=args.drop_seed)
    pricing = Pricing()
    score = score_corpus(corpus, decider, pricing)

    k_values = [int(x) for x in args.fleet.split(",") if x.strip()]
    fleet = score.fleet(k_values, horizon=args.horizon)

    if args.json:
        print(
            json.dumps(
                {
                    "banner": "docs/260 Step 1 simulated — d is a machinery demo, not a measurement",
                    "n_trajectories": score.n_trajectories,
                    "total_ticks": score.total_ticks,
                    "total_divergences": score.total_divergences,
                    "d": round(score.d, 5),
                    "gross_usd": round(score.gross_usd, 2),
                    "net_usd": round(score.net_usd, 2),
                    "per_trajectory_net_usd": round(score.per_trajectory_net_usd, 2),
                    "divergence_by_kind": score.divergence_by_kind,
                    "divergence_by_rung": score.divergence_by_rung,
                    "fleet": fleet,
                    "stress": args.stress,
                    "faithful": args.faithful,
                },
                indent=2,
            )
        )
        return 0

    print(_BANNER)
    print()
    print(f"  trajectories      {score.n_trajectories}")
    print(f"  total ticks       {score.total_ticks}")
    print(f"  divergences       {score.total_divergences}")
    print(f"  d (per-tick)      {score.d:.4f}   (prose decision != kernel decision)")
    print()
    print("  divergence by kind:")
    for kind, n in sorted(score.divergence_by_kind.items(), key=lambda x: -x[1]):
        print(f"    {kind:<22} {n}")
    print()
    print("  divergence by the rung the KERNEL turned on (which prose drops most):")
    for rung, n in sorted(score.divergence_by_rung.items(), key=lambda x: -x[1]):
        print(f"    {rung:<28} {n}")
    print()
    print(f"  net wasted spend   ${score.net_usd:,.0f} over {score.n_trajectories} single loops")
    print(f"                     ${score.per_trajectory_net_usd:,.2f} per loop")
    print()
    print("  FLEET MULTIPLIER (the headline — saving GROWS with K):")
    print(f"    {'K':>4}  {'P(some loop wrong/round)':>26}  {'E[wasted $ over horizon]':>26}")
    for row in fleet:
        print(
            f"    {row['K']:>4}  {row['p_some_loop_wrong_per_round']:>26}  "
            f"  ${row['expected_wasted_usd_over_horizon']:>22,.2f}"
        )
    if args.faithful and score.d != 0.0:
        print("\n  ✗ IDENTITY TEST FAILED: faithful prose should give d=0.")
        return 1
    if args.faithful:
        print("\n  ✓ identity test: faithful prose reproduces the kernel exactly (d=0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
