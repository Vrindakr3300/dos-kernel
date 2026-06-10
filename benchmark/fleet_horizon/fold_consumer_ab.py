"""fold_consumer_ab — the docs/219 fold-consumer A/B, runnable form (mechanism + measured-grounded sim).

> **docs/219 designs a live A/B of a fold-CONSUMER that re-dispatches a dead child's
> own unit. The LIVE A/B cannot be run on demand — a `<synthetic>` death happens only
> when the account is actually rate-limited, which we don't control. So this is the
> runnable form, in the FleetHorizon synthetic tradition (`measure_real_collisions`
> §): (1) the arm-B CONSUMER as real, testable code (the artifact the live A/B would
> deploy), and (2) an A/B-by-construction whose recovery dynamics are sampled from the
> MEASURED recovery-gap distribution (`measure_fold_recovery.py`, 2026-06-07), so the
> realized recovered-rate it predicts is grounded in real wave structure, not an
> invented model.**

Honest status (the docs/204/190 line): a simulation measures a RATE under a model, not
the live PAYOFF. What is real here: the consumer logic (arm B), and the recovery-time
distribution it is exercised against (resampled from the 1,732 real deaths). What is
modeled: the per-unit intrinsic-success bit and the arm-C perturbation probability.
So this SETTLES the mechanism ("does arm B recover what arm A drops, without touching
a healthy fold?") and PREDICTS the realized recovery rate under measured waves; it does
NOT settle the live payoff (token cost, real task-success on retry) — that is the live
run docs/219 §4 still owes.

Three arms (docs/219 §4), scored on a ground-truth-by-construction fan-out:
  A — baseline `.filter(Boolean)`: a death's non-null error string is BANKED as a
      "finding" (laundered); a real negative is also banked. The status quo.
  B — witness-routed re-dispatch: classify each child (in prod: `dos verify-result`);
      on DEAD, re-dispatch THAT child's unit with backoff (up to K); count un-recovered
      deaths in the denominator (refused, not laundered). The hypothesis.
  C — re-prompt synthesizer (NEGATIVE CONTROL): on DEAD, inject a correction into
      synthesis instead of re-dispatching — modeled as the docs/151 perturbation that
      degrades a HEALTHY sibling's contribution w.p. `perturb_p`. The known −9pp shape.

Run ($0, no network, deterministic seed):

    python benchmark/fleet_horizon/fold_consumer_ab.py
    python benchmark/fleet_horizon/fold_consumer_ab.py --json
    python benchmark/fleet_horizon/fold_consumer_ab.py --backoff-sec 60 --max-retries 5
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# The MEASURED recovery-gap distribution (measure_fold_recovery.py, 2026-06-07,
# 1,732 real harness-deaths). Anchors are (seconds, cumulative-fraction); we
# log-interpolate within each segment so the sampled times reproduce the measured
# percentiles (median 31s, 65.5% ≤60s, 82.5% ≤5m, 88.6% ≤30m, 99.9% ≤1h).
# ---------------------------------------------------------------------------
_RECOVERY_CDF = [
    (1.0, 0.0),
    (31.1, 0.50),     # measured median
    (60.0, 0.655),
    (300.0, 0.825),
    (1800.0, 0.886),
    (3600.0, 0.999),
    (21600.0, 1.0),   # tail cap (6h); 0 deaths never-recovered in the corpus
]


def _sample_recovery_sec(rng: random.Random) -> float:
    """Draw an account-recovery delay (death → account healthy) from the measured CDF.

    The faithful realized model: how long after a death until a re-dispatch COULD land
    clean. Log-interpolated within the measured segments."""
    u = rng.random()
    for (t0, c0), (t1, c1) in zip(_RECOVERY_CDF, _RECOVERY_CDF[1:]):
        if u <= c1:
            if c1 == c0:
                return t0
            frac = (u - c0) / (c1 - c0)
            # log-interpolate the time (waiting times are heavy-tailed)
            return math.exp(math.log(t0) + frac * (math.log(t1) - math.log(t0)))
    return _RECOVERY_CDF[-1][0]


# ---------------------------------------------------------------------------
# The arm-B CONSUMER — the real logic the live A/B would deploy.
# ---------------------------------------------------------------------------
@dataclass
class RetryPolicy:
    """The backoff schedule arm B re-dispatches a dead child under."""

    backoff_sec: float = 60.0
    max_retries: int = 5
    exponential: bool = True  # 1x, 2x, 4x … ; else constant backoff each retry

    def attempt_times(self) -> list[float]:
        """Cumulative elapsed time at each retry attempt (t after the initial death)."""
        out, t, step = [], 0.0, self.backoff_sec
        for _ in range(self.max_retries):
            t += step
            out.append(t)
            if self.exponential:
                step *= 2
        return out


def consumer_recovers(recovery_sec: float, policy: RetryPolicy) -> tuple[bool, float]:
    """Arm B's core decision, as pure logic: given that the account heals at
    `recovery_sec` after the death, does a re-dispatch under `policy` land a clean
    window within budget? Returns (recovered, total_wait_sec).

    In production the DEAD classification is `dos verify-result` (exit 3); here the
    death is injected, so we model only the re-dispatch timing against the measured
    account-heal time. A retry 'lands clean' iff its elapsed time ≥ recovery_sec."""
    for t in policy.attempt_times():
        if t >= recovery_sec:
            return True, t
    return False, policy.attempt_times()[-1] if policy.attempt_times() else 0.0


# ---------------------------------------------------------------------------
# Part 1 — the realized recovery rate vs. backoff (pure account dynamics, measured).
# ---------------------------------------------------------------------------
def recovery_sweep(rng: random.Random, n: int, backoffs: list[float], ks: list[int]) -> list[dict]:
    """For each (backoff, K), the fraction of deaths a re-dispatch recovers a clean
    window for, sampling recovery times from the MEASURED distribution. This is the
    realized version of docs/219 §5a's ceiling: the ceiling says 'a window existed';
    this says 'a window existed within K retries at this backoff'."""
    # pre-sample recovery times once so every policy sees the same deaths (paired).
    rec = [_sample_recovery_sec(rng) for _ in range(n)]
    rows = []
    for b in backoffs:
        for k in ks:
            pol = RetryPolicy(backoff_sec=b, max_retries=k)
            recovered = 0
            waits = []
            for r in rec:
                ok, w = consumer_recovers(r, pol)
                if ok:
                    recovered += 1
                    waits.append(w)
            waits.sort()
            rows.append({
                "backoff_sec": b,
                "max_retries": k,
                "recovered_frac": recovered / n if n else 0.0,
                "median_wait_sec": (waits[len(waits) // 2] if waits else None),
            })
    return rows


# ---------------------------------------------------------------------------
# Part 2 — the A/B-by-construction (arms A/B/C on a ground-truth fan-out).
# ---------------------------------------------------------------------------
@dataclass
class ABResult:
    arm: str
    deliverables: int          # real deliverables that reached synthesis
    laundered_findings: int    # deaths banked AS findings (the silent pollution) — arm A
    refused_counted: int       # deaths correctly counted/refused (not laundered) — arm B
    perturbed_lost: int        # healthy deliverables degraded by the intervention — arm C
    note: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


def run_ab(
    rng: random.Random,
    units: int,
    death_rate: float,
    neg_rate: float,
    policy: RetryPolicy,
    perturb_p: float,
) -> dict:
    """One ground-truth-by-construction fan-out, scored under all three arms.

    Each unit is, by construction: a real-negative (a genuine 'no' to KEEP) w.p.
    `neg_rate`, else intrinsically-deliverable. Its initial run DIES w.p. `death_rate`
    (the measured 31.8%). We KNOW the truth, so we can score each arm exactly."""
    # construct the units + their initial-run fate
    truth = []  # (is_deliverable, died_initial, recovery_sec)
    for _ in range(units):
        is_deliv = rng.random() >= neg_rate
        died = rng.random() < death_rate
        rec = _sample_recovery_sec(rng) if died else 0.0
        truth.append((is_deliv, died, rec))

    n_deaths = sum(1 for _, d, _ in truth if d)
    # the achievable ceiling: intrinsically-deliverable units (whether or not they died first)
    ceiling = sum(1 for d, _, _ in truth if d)

    # Arm A — .filter(Boolean): a death's error string is non-null → banked as a finding.
    a_deliv = sum(1 for is_d, died, _ in truth if is_d and not died)
    a_laundered = n_deaths  # every death is banked as a "finding"
    arm_a = ABResult("A_filter_boolean", a_deliv, a_laundered, 0, 0,
                     "deaths laundered as findings; lost deliverables silently dropped")

    # Arm B — witness-routed re-dispatch: on DEAD, re-dispatch the unit with backoff.
    b_deliv = a_deliv
    b_refused = 0
    for is_d, died, rec in truth:
        if not died:
            continue
        recovered, _ = consumer_recovers(rec, policy)
        if recovered and is_d:
            b_deliv += 1          # recovered a real deliverable
        else:
            b_refused += 1        # un-recovered (or a real negative) → counted, NOT laundered
    arm_b = ABResult("B_witness_redispatch", b_deliv, 0, b_refused, 0,
                     "dead children re-dispatched; un-recovered deaths counted (not laundered)")

    # Arm C — re-prompt synthesizer (NEGATIVE CONTROL): each death triggers an injection
    # that degrades a HEALTHY sibling's deliverable w.p. perturb_p (the docs/151 harm).
    healthy_deliv = [i for i, (is_d, died, _) in enumerate(truth) if is_d and not died]
    perturbed = 0
    available = set(healthy_deliv)
    for _ in range(n_deaths):
        if not available:
            break
        if rng.random() < perturb_p:
            victim = rng.choice(tuple(available))
            available.discard(victim)
            perturbed += 1
    c_deliv = a_deliv - perturbed
    arm_c = ABResult("C_reprompt_synthesizer", c_deliv, n_deaths, 0, perturbed,
                     "intervention perturbs passing siblings (the −9pp shape); deaths still laundered")

    return {
        "units": units,
        "deaths": n_deaths,
        "achievable_deliverable_ceiling": ceiling,
        "arms": [arm_a.to_dict(), arm_b.to_dict(), arm_c.to_dict()],
        "headline": {
            "arm_A_deliverables": arm_a.deliverables,
            "arm_B_deliverables": arm_b.deliverables,
            "arm_C_deliverables": arm_c.deliverables,
            "B_recovered_over_A": arm_b.deliverables - arm_a.deliverables,
            "B_recovered_frac_of_lost": (
                (arm_b.deliverables - arm_a.deliverables) / max(1, ceiling - arm_a.deliverables)
            ),
            "C_lost_vs_A": arm_a.deliverables - arm_c.deliverables,
            "A_laundered_findings": arm_a.laundered_findings,
            "B_laundered_findings": arm_b.laundered_findings,
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="The docs/219 fold-consumer A/B (mechanism + measured-grounded sim). "
                    "$0, deterministic.")
    ap.add_argument("--units", type=int, default=10000, help="fan-out size for the A/B-by-construction")
    ap.add_argument("--death-rate", type=float, default=0.318, help="measured harness-death rate")
    ap.add_argument("--neg-rate", type=float, default=0.15, help="fraction of units that are genuine negatives (kept)")
    ap.add_argument("--backoff-sec", type=float, default=60.0)
    ap.add_argument("--max-retries", type=int, default=5)
    ap.add_argument("--perturb-p", type=float, default=0.5,
                    help="arm C: prob an injection degrades a healthy sibling (docs/151 harm)")
    ap.add_argument("--seed", type=int, default=219)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    # Make output codepage-independent (Windows consoles default to cp1252, which can't
    # encode the em-dash / minus glyphs below). Best-effort; older streams may lack it.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    rng = random.Random(args.seed)
    policy = RetryPolicy(backoff_sec=args.backoff_sec, max_retries=args.max_retries)

    sweep = recovery_sweep(
        random.Random(args.seed + 1), n=20000,
        backoffs=[30.0, 60.0, 300.0, 900.0],
        ks=[1, 3, 5],
    )
    ab = run_ab(rng, args.units, args.death_rate, args.neg_rate, policy, args.perturb_p)

    if args.json:
        print(json.dumps({"recovery_sweep": sweep, "ab": ab,
                          "params": vars(args)}, indent=2, sort_keys=True))
        return 0

    print("=== fold-consumer A/B (docs/219) — measured-grounded sim, 2026-06-07 distribution ===")
    print()
    print("PART 1 — realized recovery rate vs. backoff (resampled from the MEASURED gaps):")
    print(f"  {'backoff':>8} {'K':>3} {'recovered':>10} {'median wait':>12}")
    for r in sweep:
        mw = r["median_wait_sec"]
        mws = (f"{mw/60:.1f}m" if mw and mw >= 60 else (f"{mw:.0f}s" if mw else "n/a"))
        print(f"  {r['backoff_sec']:>7.0f}s {r['max_retries']:>3} "
              f"{100*r['recovered_frac']:>9.1f}% {mws:>12}")
    print()
    h = ab["headline"]
    print(f"PART 2 — A/B-by-construction ({ab['units']} units, {ab['deaths']} deaths, "
          f"ceiling {ab['achievable_deliverable_ceiling']} deliverables):")
    print(f"  arm A (.filter Boolean)   : {h['arm_A_deliverables']:>6} deliverables, "
          f"{h['A_laundered_findings']} deaths LAUNDERED as findings")
    print(f"  arm B (witness re-dispatch): {h['arm_B_deliverables']:>6} deliverables "
          f"(+{h['B_recovered_over_A']} recovered = {100*h['B_recovered_frac_of_lost']:.1f}% of lost), "
          f"{h['B_laundered_findings']} laundered")
    print(f"  arm C (re-prompt synth)    : {h['arm_C_deliverables']:>6} deliverables "
          f"(−{h['C_lost_vs_A']} vs A — the perturbation harm), still launders {ab['deaths']}")
    print()
    print("read: B ADDS recovered deliverables and launders ZERO (it counts un-recovered")
    print("deaths in the denominator); C drops BELOW A (it perturbs passing siblings). The")
    print("safety is structural (B never touches a healthy fold); the recovered FRACTION is")
    print("the realized number the live A/B (docs/219 §4) must still confirm with real tokens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
