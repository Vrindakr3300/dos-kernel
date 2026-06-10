"""Tier-0 theory sweep — map WHERE the BLOCK prize holds, for $0, before any live spend.

docs/144 §5 Phase 3 is the *live* experiment ("does the turn-preserving BLOCK flip the live
-9 pp positive?"). A live run answers it at ONE point in the recovery-dynamics space, at real
API cost. This harness answers a cheaper, more useful question FIRST, with no model call:

  **Over what region of the recovery-dynamics space does BLOCK beat DEFER and WARN — and
  where does it stop?**

That region is the load-bearing uncertainty. The simulator's `intervention_ab` already fixes
ONE point (`q_recover_block=0.85`, `q_recover_defer=0.75`, `mattered_rate=0.65`) and shows
BLOCK >> DEFER there. But the live run's recovery rates are unknown, so a single point is a
hunch. This sweep maps the decision boundary across the three load-bearing axes, so when the
live numbers land we KNOW which region we're in — and whether the result was expected:

  * **the recovery GAP** — `q_recover_block - q_recover_defer`. The whole §13.4 thesis is that
    a turn-PRESERVING BLOCK recovers MORE than a turn-SPENDING DEFER. How big must the gap be
    for BLOCK to win? (At gap=0, BLOCK still wins on cost alone — it is the cheaper rung — so
    the threshold being <=0 is the strong-prize signal.)
  * **mattered_rate** — the fraction of caught mints that feed a hidden verifier. The -9 pp is
    a LOW-mattered-rate artifact (most catches the verifier never checked). Where is the
    break-even where intervening at all starts to pay?
  * **mint_rate** (`p_mint_base`) — how cheap/error-prone the agent is. More mints -> more
    leverage for any intervention; a strong model (~0 mints) is the docs/143 "correctly does
    nothing" regime.

Everything here is FREE and instant (the simulator + the REAL `dos.intervention_eval.score`,
zero model calls), and it is the cheapest tier of the test ladder documented in
`THEORY_LADDER.md`: Tier 0 (this) -> Tier 1 (deterministic replay) -> Tier 2-4 (live, scaled).

Run:
    python -m benchmark.enterpriseops.intervention_theories                 # all sweeps
    python -m benchmark.enterpriseops.intervention_theories --sweep gap     # one axis
    python -m benchmark.enterpriseops.intervention_theories --tasks 1500 --seeds 5  # tighter
"""

from __future__ import annotations

import argparse
import statistics

from dos.intervention import InterventionPolicy
from dos.intervention_eval import score

from .intervention_ab import _build_cases
from .simulator import SimParams


# The three policies under test — the live A/B arms, as eval policies. (No-consult is the
# implicit baseline: net_task_delta 0 by construction — it never intervenes, so it neither
# prevents nor disrupts; every policy here is measured as a delta against that do-nothing.)
_DEFER = InterventionPolicy(on_high_confidence="DEFER", on_low_confidence="DEFER", ceiling="DEFER")
_WARN = InterventionPolicy(on_high_confidence="WARN", on_low_confidence="WARN", ceiling="WARN")
_BLOCK = InterventionPolicy()  # HIGH->BLOCK, LOW->WARN, ceiling=BLOCK (the §13 confidence-gated PEP)


def _score_point(seeds, n_tasks, params, *, mattered_rate, q_block, q_defer):
    """Mean (defer, warn, block) net_task_delta at one point of the dynamics space, paired
    across seeds (every policy sees the SAME generated corpus per seed)."""
    d_n, w_n, b_n = [], [], []
    for s in seeds:
        cases = _build_cases(
            s, n_tasks, params,
            mattered_rate=mattered_rate, q_recover_block=q_block, q_recover_defer=q_defer,
        )
        d_n.append(score(_DEFER, cases).net_task_delta)
        w_n.append(score(_WARN, cases).net_task_delta)
        b_n.append(score(_BLOCK, cases).net_task_delta)
    return statistics.mean(d_n), statistics.mean(w_n), statistics.mean(b_n)


def _winner(defer: float, warn: float, block: float) -> str:
    best = max(defer, warn, block)
    if block == best:
        return "BLOCK"
    if warn == best:
        return "WARN"
    return "DEFER"


def sweep_gap(seeds, n_tasks, params) -> None:
    """Hold defer-recovery fixed at the live ~0.75; vary block-recovery from below it to far
    above. Reports the GAP at which BLOCK overtakes WARN (the advisory floor) — the threshold
    the live run must clear. BLOCK already beats DEFER at every gap (cheaper rung)."""
    print("\n## Sweep 1 - the recovery GAP (q_recover_block - q_recover_defer)")
    print("   defer-recovery fixed at 0.75 (the live 48/64); mattered_rate=0.65")
    print(f"   {'q_block':>8}{'gap':>7}{'DEFER':>9}{'WARN':>9}{'BLOCK':>9}  winner  BLOCK>WARN?")
    q_defer = 0.75
    crossed = None
    for q_block in (0.55, 0.65, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00):
        d, w, b = _score_point(seeds, n_tasks, params,
                               mattered_rate=0.65, q_block=q_block, q_defer=q_defer)
        gap = q_block - q_defer
        win = _winner(d, w, b)
        bw = "yes" if b > w else "no"
        if crossed is None and b > w:
            crossed = gap
        print(f"   {q_block:>8.2f}{gap:>+7.2f}{d:>+9.3f}{w:>+9.3f}{b:>+9.3f}  {win:<7} {bw}")
    if crossed is not None:
        print(f"   -> BLOCK overtakes WARN once block-recovery exceeds defer by ~{crossed:+.2f}.")
        print(f"     The live run needs block-recovery >= ~{0.75 + crossed:.2f} for the strong prize.")
    else:
        print("   -> BLOCK never overtook WARN in this range (prevention < disruption here).")


def sweep_mattered(seeds, n_tasks, params) -> None:
    """Vary the fraction of caught mints that feed a verifier. The -9 pp is a low-mattered
    artifact; this finds the break-even where intervening starts to pay, per policy."""
    print("\n## Sweep 2 - mattered_rate (fraction of catches the verifier actually checks)")
    print("   q_block=0.85, q_defer=0.75 (the intervention_ab fixed point)")
    print(f"   {'matter':>8}{'DEFER':>9}{'WARN':>9}{'BLOCK':>9}  winner")
    for mr in (0.10, 0.25, 0.40, 0.55, 0.65, 0.80, 0.95):
        d, w, b = _score_point(seeds, n_tasks, params,
                               mattered_rate=mr, q_block=0.85, q_defer=0.75)
        print(f"   {mr:>8.2f}{d:>+9.3f}{w:>+9.3f}{b:>+9.3f}  {_winner(d, w, b)}")
    print("   -> low mattered_rate is the -9 pp regime (most catches buy nothing); BLOCK's")
    print("     edge over DEFER is that its wasted disruption is CHEAPER, not absent.")


def sweep_mint(seeds, n_tasks, base_params) -> None:
    """Vary how mint-prone the agent is (p_mint_base). A strong model (~0) is the docs/143
    'correctly does nothing' regime; a cheap agent is where the points are."""
    print("\n## Sweep 3 - mint rate p_mint_base (agent cheapness / FK-error rate)")
    print("   q_block=0.85, q_defer=0.75, mattered_rate=0.65")
    print(f"   {'p_mint':>8}{'cases':>7}{'DEFER':>9}{'WARN':>9}{'BLOCK':>9}  winner")
    for pm in (0.02, 0.04, 0.06, 0.10, 0.16, 0.24):
        params = SimParams(p_mint_base=pm)
        # count cases at this rate (one seed) so the reader sees the denominator move.
        n_cases = len(_build_cases(seeds[0], n_tasks, params,
                                   mattered_rate=0.65, q_recover_block=0.85, q_recover_defer=0.75))
        d, w, b = _score_point(seeds, n_tasks, params,
                               mattered_rate=0.65, q_block=0.85, q_defer=0.75)
        print(f"   {pm:>8.2f}{n_cases:>7}{d:>+9.3f}{w:>+9.3f}{b:>+9.3f}  {_winner(d, w, b)}")
    print("   -> as the agent mints more, every intervention's leverage grows; BLOCK scales")
    print("     best because it adds prevention WITHOUT adding the DEFER turn-tax.")


_SWEEPS = {"gap": sweep_gap, "mattered": sweep_mattered, "mint": sweep_mint}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tasks", type=int, default=800, help="tasks per seed (default 800)")
    ap.add_argument("--seeds", type=int, default=3, help="number of seeds (default 3)")
    ap.add_argument("--sweep", choices=sorted(_SWEEPS), default=None,
                    help="run one axis only (default: all three)")
    args = ap.parse_args(argv)
    seeds = list(range(1, args.seeds + 1))
    params = SimParams()
    print("=" * 78)
    print(f"  Tier-0 THEORY SWEEP — {args.tasks} tasks x {args.seeds} seeds, FREE (no model)")
    print("  scored through the SAME dos.intervention_eval the kernel ships")
    print("=" * 78)
    to_run = [args.sweep] if args.sweep else list(_SWEEPS)
    for name in to_run:
        _SWEEPS[name](seeds, args.tasks, params)
    print("\n" + "=" * 78)
    print("  Read this BEFORE spending on a live run: it tells you which recovery region")
    print("  makes BLOCK win, so the live numbers confirm a prediction, not a hunch.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
