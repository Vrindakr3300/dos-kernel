"""Run the docs/143 §8 A/B ladder on the faithful simulator — R0 (react) vs R1 (dos_react
+ arg_provenance advisory nudge) — and prove the Integrity-slice bump is >=4pp, emergent,
and feasible-task-rate-neutral.

Usage:
    python -m benchmark.enterpriseops.run_ab                 # the headline A/B (3 seeds)
    python -m benchmark.enterpriseops.run_ab --sweep         # + the mechanism-driven sweeps
    python -m benchmark.enterpriseops.run_ab --tasks 2000    # bigger split for tighter CIs

Reports the per-verifier-type breakdown the audit demands (Integrity slice primary;
feasible-task rate is the kill-signal gate). Mean ± stdev over seeds, because the per-rung
delta is single-digit pp.
"""

from __future__ import annotations

import argparse
import statistics


from .simulator import ArmStats, SimParams, run_split


def _agg(stats: list[ArmStats], attr: str) -> tuple[float, float]:
    vals = [getattr(s, attr) for s in stats]
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, sd


def headline(n_tasks: int, seeds: list[int], params: SimParams) -> dict:
    r0s: list[ArmStats] = []
    r1s: list[ArmStats] = []
    for s in seeds:
        r0, r1 = run_split(s, n_tasks, params)
        r0s.append(r0)
        r1s.append(r1)

    i0_m, i0_sd = _agg(r0s, "integrity_rate")
    i1_m, i1_sd = _agg(r1s, "integrity_rate")
    f0_m, _ = _agg(r0s, "feasible_rate")
    f1_m, _ = _agg(r1s, "feasible_rate")

    tot_mut = sum(s.n_mutates for s in r0s)
    tot_min = sum(s.n_minted for s in r0s)
    tot_nudge = sum(s.n_nudged for s in r1s)
    tot_false = sum(s.n_false_nudges for s in r1s)
    tot_rec = sum(s.n_recovered for s in r1s)

    print("=" * 78)
    print(f"  EnterpriseOps-Gym simulated A/B — {n_tasks} tasks x {len(seeds)} seeds")
    print("  (the SAME dos.arg_provenance.classify_call the kernel ships runs in R1)")
    print("=" * 78)
    print(f"{'Metric':<34}{'R0 (react)':>14}{'R1 (dos_react)':>18}{'delta':>10}")
    print("-" * 78)
    print(f"{'Integrity slice (FK valid) %':<34}{i0_m:>11.2f}±{i0_sd:<2.1f}"
          f"{i1_m:>14.2f}±{i1_sd:<2.1f}{i1_m - i0_m:>+10.2f}")
    print(f"{'Feasible-task complete %':<34}{f0_m:>14.2f}  {f1_m:>16.2f}  {f1_m - f0_m:>+10.2f}")
    print("-" * 78)
    print(f"  mints generated (R0):       {tot_min}/{tot_mut} mutating FKs "
          f"({100.0*tot_min/max(1,tot_mut):.1f}%)")
    print(f"  nudges injected (R1):       {tot_nudge}  "
          f"(false-nudges on legit-derived: {tot_false})")
    print(f"  mints recovered by nudge:   {tot_rec}")
    print("=" * 78)

    delta = i1_m - i0_m
    feasible_drop = f0_m - f1_m
    gate = "PASS" if (delta >= 4.0 and feasible_drop <= 1.0) else "CHECK"
    print(f"  R1 GATE (Integrity +>=4pp AND feasible-rate not down >1pp): {gate}")
    print(f"    Integrity delta = {delta:+.2f}pp  |  feasible drop = {feasible_drop:+.2f}pp")
    print("=" * 78)
    return {
        "integrity_r0": i0_m, "integrity_r1": i1_m, "integrity_delta": delta,
        "feasible_r0": f0_m, "feasible_r1": f1_m, "feasible_drop": feasible_drop,
        "gate": gate,
        "false_nudges": tot_false, "recovered": tot_rec,
    }


def sweep(n_tasks: int, seeds: list[int]) -> None:
    """Prove the bump is MECHANISM-DRIVEN: monotone in catch-rate·q_recover, → 0 as
    q_recover → 0 (nudge ignored) or p_mint → 0 (no mints to catch)."""
    print("\n" + "#" * 78)
    print("  SWEEP — the bump must vanish when the mechanism cannot act")
    print("#" * 78)

    print("\n  (a) q_recover sweep  (nudge ignored at 0.0 -> bump -> 0):")
    print(f"  {'q_recover':>10}{'Integrity R0':>15}{'Integrity R1':>15}{'delta':>10}")
    for q in (0.0, 0.2, 0.4, 0.55, 0.7):
        p = SimParams(q_recover=q)
        d = []
        for s in seeds:
            r0, r1 = run_split(s, n_tasks, p)
            d.append((r0.integrity_rate, r1.integrity_rate))
        i0 = statistics.mean(x[0] for x in d)
        i1 = statistics.mean(x[1] for x in d)
        print(f"  {q:>10.2f}{i0:>15.2f}{i1:>15.2f}{i1 - i0:>+10.2f}")

    print("\n  (b) p_mint sweep  (no mints to catch at 0.0 -> bump -> 0):")
    print(f"  {'p_mint_base':>12}{'Integrity R0':>15}{'Integrity R1':>15}{'delta':>10}")
    for pm in (0.0, 0.1, 0.22, 0.35, 0.5):
        p = SimParams(p_mint_base=pm)
        d = []
        for s in seeds:
            r0, r1 = run_split(s, n_tasks, p)
            d.append((r0.integrity_rate, r1.integrity_rate))
        i0 = statistics.mean(x[0] for x in d)
        i1 = statistics.mean(x[1] for x in d)
        print(f"  {pm:>12.2f}{i0:>15.2f}{i1:>15.2f}{i1 - i0:>+10.2f}")

    print("\n  (c) horizon sweep  (deeper FK chains -> more decay, more catch surface):")
    print(f"  {'k_max':>8}{'Integrity R0':>15}{'Integrity R1':>15}{'delta':>10}")
    for km in (4, 8, 14, 22):
        p = SimParams(k_max=km)
        d = []
        for s in seeds:
            r0, r1 = run_split(s, n_tasks, p)
            d.append((r0.integrity_rate, r1.integrity_rate))
        i0 = statistics.mean(x[0] for x in d)
        i1 = statistics.mean(x[1] for x in d)
        print(f"  {km:>8}{i0:>15.2f}{i1:>15.2f}{i1 - i0:>+10.2f}")
    print("#" * 78)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tasks", type=int, default=690,
                    help="tasks per seed (default 690 = the public-split size)")
    ap.add_argument("--seeds", type=int, default=3, help="number of seeds (default 3)")
    ap.add_argument("--sweep", action="store_true", help="run the mechanism-driven sweeps")
    args = ap.parse_args(argv)

    seeds = list(range(1, args.seeds + 1))
    headline(args.tasks, seeds, SimParams())
    if args.sweep:
        sweep(args.tasks, seeds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
