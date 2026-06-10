"""E2 — the decontamination-lift experiment (docs/206 §5).

E1 proved the verdict is a *non-distillable label*. E2 asks the value question a lab
pays for: **does filtering a training corpus by `verify()` produce a measurably more
honest model?** — i.e. if you keep only really-landed steps and drop the
self-narrated "successes," does a model that imitates the filtered corpus *over-claim
less* than one trained on the unfiltered self-report?

The naive form (SFT a real model) needs a GPU. This is the falsifiable core that
needs none: a **contamination-propagation simulation, calibrated to E1's real
numbers.** The mechanism that makes decontamination work-or-fail is fully determined
by the data, so we can measure it directly and — the actual deliverable — find the
CONDITION under which filtering pays.

THE MODEL
---------
A worker faces tasks drawn from CONTEXTS. In context k a real success lands with
probability `p_real[k]`. A worker IMITATES a training corpus: it learns, per context,
`P(emit a success-claim | context)` by counting how often the corpus claimed success
there, then emits accordingly. Its **over-claim rate** = of the success-claims it
emits, the fraction that are fabricated (no real landing) when grounded against
truth.

CONTAMINATION
-------------
The unfiltered corpus contains fabricated successes (claimed shipped, git says no) at
rate `r` (E1 measured ~0.18-0.21). The KEY knob is `c` in [0,1] — how
context-CORRELATED the contamination is:
  * c = 0: fabrication is spread uniformly across contexts. Filtering only lowers the
    base claim-rate everywhere by the same factor → the learned POLICY is unchanged in
    shape → decontamination is the boring null (moves base rate, not behavior).
  * c = 1: fabrication concentrates in the HARD contexts (low `p_real`) — exactly
    where the agent is tempted to fake it. The unfiltered corpus teaches "claim
    success even here"; the filter strips those rows, teaching "don't." Filtering
    teaches a genuinely different per-context policy → real decontamination.

THE FILTER
----------
  * UNFILTERED: train on every row, a "success" is the worker's CLAIM (self-report).
  * ADMITTED (verify-filtered): train only on rows where the commit really landed
    (the kernel verdict) — the fabricated rows are removed before any gradient.

THE RESULT
----------
Over-claim rate of the imitator, ADMITTED vs UNFILTERED, swept over `c`. The curve
is the deliverable: the gap is ~0 at c=0 (filtering can't fix uniform noise) and
grows with c (filtering pays exactly when the lie is context-correlated, which is the
realistic regime — agents fake the hard steps). This says to a lab: verify()-filtering
your RL/SFT corpus removes over-claiming *to the degree the over-claiming is
where-it's-hard*, and that degree is measurable.

Pure stdlib (the kernel is near-stdlib). Deterministic from `seed`. Run:
    PYTHONPATH=src python -m benchmark.fleet_horizon.decontam
    PYTHONPATH=src python -m benchmark.fleet_horizon.decontam --contam-rate 0.20 --n 4000
"""
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass


# E1-measured defaults (real commit-claim corpus, 2026-06-07): fabrication rate among
# claimed-successes ~0.18-0.21; we default to 0.20. The per-context real-success
# spread is the part E1's slice was too context-poor to measure, so it is the swept
# knob, not a measured constant — stated honestly in docs/206.
E1_CONTAM_RATE = 0.20


@dataclass(frozen=True)
class DecontamResult:
    correlation: float          # c: how context-correlated the contamination is
    contam_rate: float          # r: overall fabrication rate among claimed successes
    overclaim_unfiltered: float # over-claim rate of the self-report-trained imitator
    overclaim_admitted: float   # over-claim rate of the verify-filtered imitator
    base_claim_unfiltered: float
    base_claim_admitted: float

    @property
    def lift(self) -> float:
        """The decontamination lift: how much LESS the filtered imitator over-claims."""
        return self.overclaim_unfiltered - self.overclaim_admitted


def _make_contexts(n_ctx: int, rng: random.Random) -> list[float]:
    """`p_real[k]` — per-context probability a genuine success lands. Spread across
    easy (high) and hard (low) contexts so correlation has something to bite on."""
    return [rng.uniform(0.1, 0.95) for _ in range(n_ctx)]


def _generate_corpus(p_real: list[float], *, n: int, contam_rate: float,
                     correlation: float, rng: random.Random
                     ) -> list[tuple[int, bool, bool]]:
    """Generate (context, claimed_success, really_landed) rows.

    A row is sampled in a random context. With prob `p_real[k]` it's a genuine
    landing (claimed + landed). The remaining attempts may be FABRICATED — claimed
    success without a landing — at an overall rate `contam_rate`, distributed across
    contexts by `correlation`: c=0 uniform, c=1 concentrated in the hardest (lowest
    p_real) contexts. Honest attempts that simply fail (no claim) are also emitted so
    the corpus isn't all-claims.
    """
    n_ctx = len(p_real)
    # per-context fabrication WEIGHT: blend uniform (1) with hard-concentrated
    # (1 - p_real, so low-p_real contexts get more weight) by `correlation`.
    raw = [(1.0 - correlation) * 1.0 + correlation * (1.0 - p_real[k])
           for k in range(n_ctx)]
    wsum = sum(raw) or 1.0
    fab_w = [x / wsum for x in raw]   # normalized fabrication propensity per context

    rows: list[tuple[int, bool, bool]] = []
    for _ in range(n):
        k = rng.randrange(n_ctx)
        if rng.random() < p_real[k]:
            rows.append((k, True, True))            # genuine landing
        else:
            # a failed attempt. With a context-weighted chance it is FABRICATED as a
            # success; otherwise it is an honest non-claim. Scale the per-context fab
            # propensity to hit the global contam_rate on average.
            p_fab = min(1.0, contam_rate * n_ctx * fab_w[k])
            if rng.random() < p_fab:
                rows.append((k, True, False))        # fabricated success (the lie)
            else:
                rows.append((k, False, False))       # honest fail, no claim
    return rows


def _train_imitator(corpus: list[tuple[int, bool, bool]], n_ctx: int, *,
                    filtered: bool) -> list[float]:
    """Learn per-context P(emit success-claim | context) by counting.

    The imitator learns P(emit a success-claim | context). The denominator is always
    the number of ATTEMPTS in that context (the task happened regardless of how it was
    labeled) — the filter changes the NUMERATOR, not the denominator:

      UNFILTERED: a demonstration is "claim success" whenever the agent CLAIMED it
        (genuine landings + fabrications) → P(claim|k) absorbs the lie.
      ADMITTED (verify-filter): a fabricated row is a BAD demonstration that is
        removed from the success numerator (the kernel verdict overrides the
        self-report) → only genuine landings count as a success-claim, so P(claim|k)
        drops in exactly the contexts where fabrication was concentrated. The attempt
        still occurred, so it stays in the denominator (removing a bad label does not
        un-happen the task).
    """
    succ = [0] * n_ctx
    tot = [0] * n_ctx
    for k, claimed, landed in corpus:
        tot[k] += 1                       # every attempt counts in the denominator
        is_success = (landed if filtered else claimed)
        if is_success:
            succ[k] += 1
    return [(succ[k] / tot[k]) if tot[k] else 0.0 for k in range(n_ctx)]


def _overclaim_rate(policy: list[float], p_real: list[float], *,
                    n: int, rng: random.Random) -> tuple[float, float]:
    """Run the learned policy on fresh tasks; measure over-claim rate + base claim rate.

    The policy emits a success-claim in context k with prob `policy[k]`. Ground truth:
    the claim is REAL only with prob `p_real[k]` (the world doesn't care what the
    policy learned). Over-claim rate = P(claim is fabricated | policy claimed) =
    among emitted claims, the fraction the world would not actually have landed.
    """
    n_ctx = len(policy)
    claims = 0
    fabricated = 0
    for _ in range(n):
        k = rng.randrange(n_ctx)
        if rng.random() < policy[k]:
            claims += 1
            # the claim is genuine only at the real landing rate for this context
            if rng.random() >= p_real[k]:
                fabricated += 1
    overclaim = (fabricated / claims) if claims else 0.0
    base_claim = claims / n
    return overclaim, base_claim


def run_once(*, correlation: float, contam_rate: float = E1_CONTAM_RATE,
             n_ctx: int = 40, n_train: int = 4000, n_eval: int = 4000,
             seed: int = 1729) -> DecontamResult:
    """One decontamination measurement at a given contamination correlation."""
    rng = random.Random(seed)
    p_real = _make_contexts(n_ctx, rng)
    corpus = _generate_corpus(p_real, n=n_train, contam_rate=contam_rate,
                              correlation=correlation, rng=rng)
    pol_unf = _train_imitator(corpus, n_ctx, filtered=False)
    pol_adm = _train_imitator(corpus, n_ctx, filtered=True)
    # evaluate both on the SAME fresh task stream (seeded apart from training)
    oc_unf, bc_unf = _overclaim_rate(pol_unf, p_real, n=n_eval,
                                     rng=random.Random(seed ^ 0xE2))
    oc_adm, bc_adm = _overclaim_rate(pol_adm, p_real, n=n_eval,
                                     rng=random.Random(seed ^ 0xE2))
    return DecontamResult(
        correlation=correlation, contam_rate=contam_rate,
        overclaim_unfiltered=oc_unf, overclaim_admitted=oc_adm,
        base_claim_unfiltered=bc_unf, base_claim_admitted=bc_adm,
    )


def sweep(correlations: list[float], **kw) -> list[DecontamResult]:
    return [run_once(correlation=c, **kw) for c in correlations]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="E2 decontamination-lift: does verify()-filtering teach a more honest policy? (docs/206)")
    ap.add_argument("--contam-rate", type=float, default=E1_CONTAM_RATE,
                    help="fabrication rate among claimed successes (E1-measured ~0.20)")
    ap.add_argument("--n-ctx", type=int, default=40)
    ap.add_argument("--n", type=int, default=4000, help="train + eval sample size")
    ap.add_argument("--seed", type=int, default=1729)
    args = ap.parse_args(argv)

    cs = [0.0, 0.25, 0.5, 0.75, 1.0]
    results = sweep(cs, contam_rate=args.contam_rate, n_ctx=args.n_ctx,
                    n_train=args.n, n_eval=args.n, seed=args.seed)

    print("=" * 78)
    print("E2 — decontamination lift: verify()-filtered vs self-report-trained imitator")
    print("=" * 78)
    print(f"\nContamination rate r={args.contam_rate} (E1-measured ~0.18-0.21), "
          f"{args.n_ctx} contexts, n={args.n}")
    print("c = how CONTEXT-CORRELATED the fabrication is (0=uniform, 1=in the hard tasks)\n")
    print(f"{'c':>5} | {'over-claim UNFILTERED':>22} | {'over-claim ADMITTED':>20} | "
          f"{'LIFT':>8}")
    print("-" * 70)
    for r in results:
        print(f"{r.correlation:>5.2f} | {r.overclaim_unfiltered:>22.3f} | "
              f"{r.overclaim_admitted:>20.3f} | {r.lift:>+8.3f}")

    lift0 = results[0].lift
    lift1 = results[-1].lift
    print("\nReading (docs/206 §5 E2):")
    if abs(lift0) < 0.02 and lift1 > lift0 + 0.05:
        print("  -> CONFIRMED + CONDITIONED. At c=0 (uniform fabrication) filtering gives")
        print(f"     ~0 lift ({lift0:+.3f}) -- it cannot fix noise that is everywhere. As")
        print(f"     the lie concentrates in the HARD contexts (c->1) the lift grows to")
        print(f"     {lift1:+.3f}: the filter strips exactly the 'claim-success-even-here'")
        print("     rows, teaching a genuinely more honest per-context policy. So")
        print("     verify()-filtering pays TO THE DEGREE over-claiming is where-it's-hard")
        print("     -- which is the realistic regime (agents fake the steps they can't do).")
    elif lift1 <= lift0 + 0.02:
        print(f"  -> NULL: lift is flat ({lift0:+.3f} -> {lift1:+.3f}). On this calibration")
        print("     filtering only moves the base claim rate, not the policy shape. Report")
        print("     honestly; decontamination is not buying honesty here.")
    else:
        print(f"  -> MIXED: lift {lift0:+.3f} (c=0) -> {lift1:+.3f} (c=1). Inspect the curve.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
