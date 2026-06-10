# docs/255 — F2: the natural collision stream — the coordination payoff on REAL conflicts

> **Status:** RAN LIVE (2026-06-08). The docs/245 NEXT-B step (F2), executed.
> Closes objection O2 ("your collisions are constructed"). Companion to docs/251
> (F1 cascade-depth) and docs/253 (F1 super-linear fan-out); together they are the
> fleet-scale payoff trilogy. Numbers are from the live run, off the tau2 DB-hash —
> not memory.

## The one sentence

The coordination half of the fleet thesis — *a referee BETWEEN concurrent agents
prevents a clobber the naive flow lets through* — now has a payoff number measured
on a **natural** collision distribution (conflict pairs drawn from the real tau2 task
distribution, not pinned): **J = 4 of 6** natural conflict pairs produced a real
last-writer-wins clobber under the naive flow, and `dos.arbiter` prevented all four
by serializing the colliding lease, witnessed off the DB-hash the agents never
authored.

## Why this closes O2 (the "constructed conflict" objection)

The earlier coordination run (docs/233, `coord_loop`) measured the same payoff but
PINNED two agents to a hand-picked reservation. A reviewer's fair objection: *you
manufactured the collision; real fleets don't conflict that cleanly.* F2 STEP 1
(`natural_collisions.py`, docs/245 NEXT-B) answered the $0 precondition off the real
task distribution — each tau2 task's GOLD ACTIONS name the entity it touches
(`reservation_id`, authored by the benchmark, not the agent):

- 50 airline tasks, 35 name an entity, 595 entity-naming pairs, **14 naturally
  collide → 2.35% natural pairwise rate**;
- **18 entities are touched by ≥2 distinct tasks** — real contention sites (e.g.
  `WUNA5K`, `H8Q05L` each by 3 tasks; tasks 4 & 44 contend on 5 reservations).

**Verdict: GO** — collisions fall OUT of the distribution, not a pin. `coord_loop`
now draws its conflict pairs from `contended_reservation_ids()` (the 18 sites), and
the live log confirms it: `[F2] drawing 6 conflict pair(s) from 18 NATURAL contention
sites (not pinned) — kills O2.`

## The live result (J off the DB-hash)

Two live Gemini-2.5-flash agents per pair on a shared tau2 airline DB. A1 mutates the
reservation (cancels it); A2-naive, computed against the ORIGINAL state, replays a
stale mutation (adds a bag); the composed DB-hash is compared to the serialized hash.
J += 1 when the naive composition lost an edit (hashes diverge) — exactly the clobber
the arbiter, refusing the second concurrent lease on `reservations/<id>`, prevents.

| Pair | Reservation | natural site degree | naive clobbered? | J |
|---|---|---|---|---|
| 1 | WUNA5K | 3 tasks | **yes** | 1 |
| 2 | H8Q05L | 3 tasks | **yes** | 1 |
| 3 | 3RK2T9 | 3 tasks | no | 0 |
| 4 | 4OG6T3 | 2 tasks | **yes** | 1 |
| 5 | S61CZX | 2 tasks | no | 0 |
| 6 | NM1VX1 | 2 tasks | **yes** | 1 |
| | | | **4 clobbered** | **J = 4** |

**J = 4 / 6 (67%).** The clobber rate on the natural sites is *higher* than a random
pair would give — because these are precisely the entities multiple real tasks fight
over. The two J=0 pairs are honest: not every natural conflict composes destructively
on a given run (A2's effect happened not to drop A1's), and the benchmark reports them
rather than inflating J.

The witness is the DB-hash, a byte neither agent authored: the naive composition's
hash ≠ the serialized-correct hash IS the clobber, and the arbiter's serialization
reproduces the serialized hash. This is the docs/179 discipline (a FLIP off ground
truth, not a re-projected rate) and the docs/138 invariant (byte-author ≠ judged
agent) on the coordination half-plane.

## Where this sits in the fleet-scale program (docs/245)

```
  ✅ F1            (docs/251)  corruption COMPOUNDS under believe (depth D−1), 0 under adjudicate
  ✅ F1-superlinear(docs/253)  fan-out tree: F^D corrupt leaves under believe, 0 under adjudicate
  ✅ F2 STEP 1     (docs/245)  natural collision rate 2.35%, 18 sites — GO (O2's $0 precondition)
  ✅ F2 STEP 3     (THIS doc)  live J=4/6 on the NATURAL sites — O2 dead, payoff off the DB-hash
  ⏭ F4            (docs/245)  re-run the fleet_horizon monotone-shape sweep with the live witness;
                              plot payoff vs (K, D, F) — the headline fleet figure
     F3 (gated)               a second state-witness benchmark; show two witnesses agree
```

F2 is the last brick before F4 (the compounding/scaling headline). With F1 (it
compounds), F1-super-linear (it compounds F^D), and F2 (the collisions are natural and
the payoff is real), the three objections — "constructed conflict" (O2), "rate not
cascade" (O4, F1), "single contrived pair" — are answered off live ground truth. F4
marries the docs/243 Track A real `shared_ratio` (0.188) + this live J to the
`fleet_horizon` monotone-shape sweep, projecting payoff across fleet size.

## Honest scope

- **Flash, 6 pairs, airline only.** A larger K and a second domain (retail/telecom,
  which also have entity-naming tasks) would tighten the rate; this is the existence-
  and-naturalness result, not a population estimate. State the n on every number.
- **The two J=0 pairs are the honest tail** — a natural conflict need not clobber on
  every run; the value is that 4 of 6 did, off the hash.
- **DB-entity collisions, not file-path.** This is the tau2 analogue of docs/243
  Track A's file-path collisions (18.8% on the CC corpus). Two different witnesses
  (a DB-hash; git ancestry), both confirming natural contention is real — which is
  the F3 "two witnesses agree" direction.

---

*Provenance: `benchmark/agentprocessbench/writeadmit/coord_loop.py` (the live A/B,
GEMINI-gated, run logs gitignored) + `natural_collisions.py` (F2 STEP 1, the $0
predictor). The composition primitive + arbiter region mapper are docs/233; the
natural-distribution sourcing + the live J are this doc. Pairs with docs/190 (the
RATE) and docs/233 (the constructed payoff); this is the NATURAL payoff.*
