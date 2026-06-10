# docs/256 — F4: the headline fleet figure — payoff vs (K, D, F)

> **Status:** BUILT (2026-06-08). The docs/245 F4 step — the headline figure the
> whole fleet-scale program was built to produce. No new live spend: it JOINS three
> already-measured live results (docs/243 Track A, docs/255 F2, docs/253
> F1-super-linear) into one curve and projects it across fleet size K, cascade depth
> D, and fan-out F. The cascade exponent is the measured F^D, not an assumption.
> Provenance: `benchmark/fleet_horizon/fleet_payoff_surface.py` (+ `plot_payoff_surface.py`,
> `test_fleet_payoff_surface.py`). Closes objection O4 ("J is a rate, not compounding")
> at the figure level — it shows the rate *as* the cascade it loads.

## The one sentence

The out-of-loop referee's payoff is not a flat rate of events prevented; it is the
**expected corrupted downstream leaves it prevents across a fleet** — quadratic in
the fleet size K (the pair count), super-linear in the cascade depth D (each
prevented clobber loads F^D leaves), and **zero at a fleet of one** — and this
figure plots that surface entirely from numbers measured live off the tau2 DB-hash
and this repo's own git history, never from a self-report.

## What F4 is — a join, not a new experiment

F1, F1-super-linear, and F2 each measured one live number. F4 spends nothing new;
it *marries* them. Three inputs, every one read off bytes the agents did not author:

| input | what it is | live value (as of 2026-06-08) | source |
|---|---|---|---|
| `shared_ratio` | the collision **surface** — fraction of concurrent agent pairs that touch a shared write region | **≈0.19** (245 of ~1280 pairs, 251 sessions) | docs/243 Track A, off git ancestry + CC timestamps |
| `clobber_fraction` | fraction of those collisions that are a real last-writer-wins **hazard** | **0.23** corpus rate · **0.67** (4/6) tau2 natural-sites | docs/243 (rate) · docs/255 F2 (live DB-hash) |
| `cascade_load` | leaves saved per prevented clobber at a depth-D fan-out-F root | **F^D** (measured 4 @ D2, 8 @ D3 for F=2) | docs/253 F1-super-linear, off the DB-hash |

The composition is plain arithmetic over them:

```
  clobbers_prevented(K) = C(K,2) · shared_ratio · clobber_fraction
  cascade_load(D, F)    = F^D                         # D=0 → 1 (the bare event)
  payoff(K, D, F)       = clobbers_prevented(K) · cascade_load(D, F)
```

`payoff(K, D, F)` is the **expected corrupted leaves the referee prevents** across a
fleet of K agents whose work branches D deep with fan-out F. The kernel's measured
sensitivity is 1.0 (it refuses every real collision, docs/243), so every colliding
pair that is a hazard is serialized — the expectation is the count prevented, not an
upper bound.

## The figure

Two panels (`plot_payoff_surface.py` → `build/fleet_payoff_surface.png`; the same
data also lands as CSV and an always-on ASCII rendering, so the shape shows with no
matplotlib):

- **A. corrupted leaves prevented vs fleet size K**, at the live-measured cell
  (D=3, F=2, so the cascade load is F^D = 8). Two lines bound a band: the
  conservative corpus clobber rate (0.23) and the tau2 natural-sites rate (0.67,
  from F2). The curve starts at **0 at K=1** — the fleet-of-one floor (docs/204 §1)
  — and climbs to **≈173 (conservative) to ≈505 (natural)** corrupted leaves
  prevented at a 32-agent fleet.
- **B. the cascade lift**: payoff vs K for several (D, F) cells. Each extra level of
  depth multiplies the whole curve by F — the F^D loading made visible. At a 32-agent
  fleet the same collision rate is worth ≈22 prevented events at depth 0, ≈173 at
  depth 3, ≈347 at depth 4.

The headline slice, conservative edge, at (D=3, F=2):

```
   K     pairs   clobbers prevented   LEAVES prevented (×F^D=8)
   1        0          0.00                   0.00      ← fleet-of-one floor
   2        1          0.04                   0.35
   4        6          0.26                   2.10
   8       28          1.22                   9.78
  16      120          5.24                  41.92
  32      496         21.66                 173.25
```

## Why this is the number that closes O4

O4 — the deepest skeptic objection (docs/245) — is that *J is a rate (events
prevented), not compounding*. F1 (docs/251) and F1-super-linear (docs/253) answered
it as a mechanism: corruption from one poisoned root reaches D−1 nodes down a chain
and F^D leaves down a tree, all blocked by one gate at the root. F4 answers it at the
**figure** level: it takes the *rate* (the live collision/clobber rate, K-scaled) and
multiplies it by the *cascade* (the live F^D leaf count) to produce the curve a
reader can hold — the payoff is the rate **as the cascade it loads**, and that curve
is super-linear in the fleet, not flat.

The cross-check that keeps it honest: the closed form F^D must reproduce the docs/253
live measurement exactly, and the module asserts it does (4 corrupt leaves at D=2, 8
at D=3 for F=2). The cascade exponent is a *measured fact* the figure plots, not a
tunable thumb on the scale. If F1-super-linear had measured a sub-F^D spread, this
figure would inherit it.

## Honest scope — what the figure is and is not

- **A projection of measured rates, not a fourth live run.** Every *input* is live
  (the collision surface off git, the natural clobber rate off the DB-hash, the
  cascade load off the DB-hash); the *surface* is their arithmetic join across
  (K, D, F). It is the honest successor to the rate projection in
  `real_collisions_from_track_a.py` — that one stopped at "expected clobbers"; F4
  loads each clobber by the F^D cascade the other live runs measured.
- **The band is real, and reported.** The conservative corpus clobber rate (0.23)
  and the tau2 natural-sites rate (0.67) differ by ≈2.9×. The headline defaults to
  the conservative edge so the figure never over-claims; the natural edge is the rate
  on precisely the entities multiple real tasks fight over (F2's 18 contention
  sites), which is the relevant rate when the fleet is contending, not the average.
- **F^D is BREADTH fan-out, not value amplification** (inherited from docs/253). "F^D
  leaves prevented" means F^D agents in the dependency tree each blocked by the shared
  poison — the fleet's branching topology — not one corrupt value mutating into many.
  tau2 has no clean value-multiply vector and faking one would be dishonest.
- **The corpus is non-stationary.** `shared_ratio` drifts as this repo's CC corpus
  grows (0.188 at docs/243, ≈0.19 today); state the n and the as-of on every number.
  The projection math is pinned exactly; the live input is re-measured each run.
- **The fleet-of-one floor is load-bearing.** Payoff is 0 at K=1 in every cascade
  cell — there is no pair to collide, so there is nothing for the referee to prevent,
  however deep the cascade would have been. A figure that did not vanish at K=1 would
  be measuring an artifact, not a fleet phenomenon (docs/204 §1).

## Where this sits in the fleet-scale program (docs/245)

```
  ✅ F1            (docs/251)  corruption COMPOUNDS under believe (chain, depth D−1), 0 under adjudicate
  ✅ F1-superlinear(docs/253)  fan-out tree: F^D corrupt leaves under believe, 0 under adjudicate
  ✅ F2            (docs/255)  natural collision stream: live J=4/6 off the DB-hash — O2 dead
  ✅ F4            (THIS doc)  THE HEADLINE — payoff vs (K, D, F), the live results joined into one curve
     F3 (gated)               a second state-witness benchmark (Agent-Diff): show two witnesses agree
```

With F4 the headline figure exists and rests on live ground truth at every input:
the four skeptic objections (O1 implicit-peer, O2 constructed-conflict, O3
single-benchmark, O4 rate-not-compounding) are answered — O4 now visibly, as the
curve that scales with the fleet. The one remaining out-of-loop payoff experiment is
the second-benchmark port (F3, Agent-Diff is already standing up locally), which
tests whether the *same* figure reproduces under a second, independent witness.

---

*Provenance: the join math + the surface in `fleet_payoff_surface.py`; the figure in
`plot_payoff_surface.py` (CSV always, ASCII always, PNG if matplotlib); the pinned
projection arithmetic in `test_fleet_payoff_surface.py`. Inputs: docs/243 Track A
(`real_collisions_from_track_a.py`, the collision surface off git), docs/255 F2
(`coord_loop.py`, the natural clobber J off the DB-hash), docs/253 F1-super-linear
(`cascade_loop.py:run_fanout_live`, the F^D cascade off the DB-hash). Framing from
docs/245 (the plan), docs/204 §1 (the fleet-of-one falsifier), and
`project-dos-horizon-keeper-k1-measured` (the q^N compounding frame this
operationalizes).*
