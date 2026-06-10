# docs/245 — Proving the referee at fleet scale: from existence to rate-and-compounding

> **One sentence.** We have two live *existence* results — an out-of-loop referee blocks real
> over-claims (J=15/258, docs/228/232) and prevents real lost-update clobbers (J=6/8,
> docs/233) — both off a non-forgeable witness; this plan is how to turn them into a
> *fleet-scale* result: a real many-agent fleet, on a natural (not constructed) collision
> stream, where the payoff is measured not as "events prevented" but as **compounding
> corruption averted**, the only number that actually scales.

**Status:** plan. **Date:** 2026-06-08. **Reads on:** docs/228 + docs/232 (the over-claim
payoff + cross-model hardening), docs/233 (the coordination payoff), docs/209 (the registry
+ the rate-vs-payoff law), docs/204 §1 (the fleet-of-one wall — value is a *plurality*
phenomenon), `benchmark/fleet_horizon/` (the harness that already scales N×M but with a
*simulated* witness). Memory: `project-dos-horizon-keeper-k1-measured` (the compounding
q^N frame), `project-dos-coordination-payoff-measured`, `project-dos-216-live-payoff-measured`.

---

## 1. What we have, stated as a skeptic would attack it

The results are real and live, but a fleet skeptic raises four specific objections, and
naming them sharply is the whole plan:

| # | the result | the skeptic's objection | what it bounds |
|---|---|---|---|
| O1 | over-claim gate, J=15/258, 2 models | "one agent + a *hypothetical* peer — you never ran the peer" | the fleet is **implicit** |
| O2 | coordination, J=6/8 pairs | "N=2, and you *constructed* the collision" | **N=2 + designed conflict** |
| O3 | both on tau2 | "one benchmark, one domain (airline/retail)" | **single environment** |
| O4 | J = "events prevented" | "an event prevented is a *rate*; what's the dollar?" | **rate, not compounding** |

The deepest is **O4**, and it is also the biggest opportunity. The fleet thesis
(`project-dos-horizon-keeper-k1-measured`) is that fleet errors **compound**: a clobbered or
over-claimed write is not one lost event — it is a *poisoned input* every downstream agent
then builds on, so uncaught error grows like `q^N` over a dependency chain of depth N. We
have measured *one event blocked*. We have **not** measured *the cascade that one block
prevented*. That cascade is the number that scales — and it is the number a buyer feels.

---

## 2. The bridge that already exists (and the half it's missing)

`benchmark/fleet_horizon/` already does the hard scaling work — and this is the key asset:

- It runs **N efforts × M phases** as a real closed loop with a real lane journal, and
  measures **overwrites-prevented** (104 collisions refused in the headline cell) and the
  **monotone shape**: value rises in horizon×fanout and goes to **0 at fleet/horizon = 1**
  (the docs/204 §1 falsifier, pinned by a test). That shape *is* the fleet-scale signature.
- **But its witness is simulated.** The agents are a deterministic `FailureModel` with a
  `lie_rate`; "did the write land" is a coin, not a real env DB-hash. So it proves the
  *coordination mechanism scales* but not that *real agents* trip it at a real rate.

My live work (docs/228/233) is the exact complement: **real agents + a real non-forgeable
witness**, but only N=2 / implicit-peer. **The fleet-scale proof is the marriage of the
two:** put the live agent + the real DB-hash witness *into* the N×M harness, so the harness's
scaling machinery now drives a stream of *real* collisions and over-claims and counts the
payoff off *ground truth*.

```
   fleet_horizon harness         docs/228+233 live work          the fleet-scale proof
   ─────────────────────         ──────────────────────          ─────────────────────
   N×M scale ✓                   live agents ✓                   N×M scale ✓
   monotone-shape ✓              real DB-hash witness ✓          live agents ✓
   overwrites-prevented ✓        rate-vs-payoff discipline ✓     real witness ✓
   SIMULATED witness ✗     +     N=2 / implicit fleet ✗     =    natural collision stream ✓
                                                                 compounding measured ✓ (the new part)
```

---

## 3. The plan — four experiments, each kills one objection

### F1 — Run the implicit peer (kills O1). *~$2, this week.*

docs/229 already shipped `peer_b.py` (the constructor) and found ΔB≈0 *at the easy hop*
because a strong peer self-recovers. The fleet-scale version is not "does one peer recover"
but **"does the corruption survive a *chain*"**: A over-claims → B inherits → B's output feeds
C → … Measure the **depth at which a believe-chain stays corrupted vs an adjudicate-chain**.
The prediction: believe-chains corrupt monotonically with depth (each hop has a chance to
launder *or* compound), adjudicate-chains are clean at the gate. This converts the
"hypothetical peer" into a measured **cascade-depth curve** — and it is the live form of the
`q^N` claim. Reuse `peer_b.py`; add a depth parameter; the witness is already the DB-hash.

### F2 — A natural collision stream, not a constructed one (kills O2). *$0 measure + ~$10 live.*

The docs/233 conflict was *pinned* (I forced two agents onto one reservation). The honest
fleet version draws collisions **naturally**: run K agents concurrently on *independently
sampled* tau2 tasks against **one shared DB**, and let the collision rate fall out of the task
distribution (two tasks that happen to touch the same user/reservation collide on their own).
- **$0 first:** the docs/190 measurement already did this on the *real fleet's git history*
  (≥5 concurrent same-file collisions @10s). Re-aim that exact measurement at the **tau2
  task-to-entity map** to predict the natural collision rate before spending — which task
  pairs share a reservation/user, at what frequency. That is the natural-rate denominator.
- **Live:** then run K=4..16 agents on the shared DB and count clobbers prevented off the
  DB-hash *without pinning anything*. This is the result a skeptic cannot call constructed.
  The `fleet_horizon` arbiter wiring (`dos lease-lane` across processes, already live in
  `live_orchestrator_demo`) is the substrate; swap its shell writers for live tau2 agents.

### F3 — A second environment (kills O3). *gated on a second benchmark with a state witness.*

The witness discipline is environment-agnostic — it needs only a tamper-evident state hash
the agent can't author. The survey (`project-dos-other-benchmarks-for-out-of-loop-payoff`)
already ranked candidates: **Agent-Diff** (state-diff witness), **WebArena-Verified**,
**OSWorld**, **BIRD** (SQL state), **TheAgentCompany** (a *native* multi-agent peer — the
ideal F2 host). Port `coord_loop`'s region mapper (`<entity>/<id>`) + `gate.admit` to one of
these; the gate/witness/floor are byte-identical, only the env adapter changes (the same
~80%-shared-adapter property docs/216 §5 noted). One port turns "single-benchmark" into
"two independent witnesses agree."

### F4 — Measure compounding, not events (kills O4 — the headline). *built on F1+F2.*

This is the one that makes it a *fleet* result rather than a bigger *single-agent* result.
Instead of reporting J (events prevented), report the **loaded cascade cost**:

```
  for a fleet of K agents over a dependency DAG of depth D:
    believe-arm    : corrupted_final_states  =  Σ over leaves reachable from any poisoned write
    adjudicate-arm : corrupted_final_states  =  0 at the gate (the poison never enters the DAG)
    PAYOFF (fleet)  =  believe_corrupted − adjudicate_corrupted   ← grows super-linearly in D
```

The number that scales is not "6 clobbers prevented" but "**6 clobbers prevented × the
fan-out each would have poisoned**." On a depth-D fan-out-F DAG, one prevented clobber at the
root saves up to `F^D` corrupted leaves. *That* is the curve to plot — payoff vs (K, D, F) —
and the `fleet_horizon` harness already produces exactly this shape for the simulated witness
(value monotone in horizon×fanout). F4 = re-run that sweep with the **live** witness from
F1/F2, and show the *same monotone shape holds for real agents on real ground truth*. The
deliverable figure: the docs/204 §1 falsifier curve (value→0 at fleet=1, rising with scale),
but every point now a live J off the DB-hash.

---

## 4. The honest order, and the cheapest decisive datum

> **▶ PROGRESS (2026-06-10): ALL FOUR OBJECTIONS NOW HAVE A MEASURED ANSWER.** F1
> [docs/251](251_f1-the-cascade-runs-corruption-compounds-the-gate-stops-it.md) +
> [docs/253](253_f1-super-linear-the-fanout-tree-payoff-grows-f-to-the-d.md) (compounding live,
> F^D super-linear); F2 [docs/255](255_f2-the-natural-collision-stream-coordination-payoff-on-real-conflicts.md)
> (natural collisions, J=4/6 live off the DB-hash); F4
> [docs/256](256_f4-the-headline-fleet-figure-payoff-vs-k-d-f.md) (the headline payoff-vs-(K,D,F)
> figure); F3 [docs/287](287_f3-the-second-witness-agent-diff-coordination-two-witnesses-agree.md)
> (the coordination A/B ported to Agent-Diff: J=3/4 natural pairs off the production
> AssertionEngine, byte-same kernel call — two witnesses agree). Remaining lift on F3 is the
> gated LIVE arm (two live agents + the Agent-Diff Docker backend), if a skeptic demands it.

```
  ✅ STEP 2 (~$1.5)  F1 — the cascade-depth curve. DONE (docs/251): believe corrupt=D−1,
                     adjudicate=0; state corruption is not self-healed (docs/236 confirmed).
  ✅ NEXT-A (~$1.0)  F1-super-linear — the fan-out tree. DONE (docs/253): every leaf corrupt
                     under believe (F^D: 4 at depth 2, 8 at depth 3), 0 under adjudicate.
                     The payoff is SUPER-LINEAR (F^D vs D−1), live. (Honest scope: BREADTH
                     fanout — F^D agents BLOCKED by the shared poison, the correct fleet model,
                     not field-amplification; tau2 has no clean value-multiply vector.)
  ✅ STEP 1+3        F2 — natural collision rate 2.35% (18 sites, GO), then live J=4/6 on the
                     NATURAL sites (docs/255). O2 dead: collisions fall out of the distribution.
  ✅ STEP 4          F4 — the monotone-shape sweep with the measured parameters; payoff vs
                     (K, D, F) = 0 at K=1, rising super-linearly (docs/256). The headline figure.
  ✅ STEP 5 (frozen) F3 — ported to Agent-Diff (docs/287): natural rate 1.90% (2 sites, GO),
                     J=3/4 lost updates prevented off the PRODUCTION AssertionEngine, arbiter
                     serialized every contended pair / admitted every disjoint control, kernel
                     call byte-identical. Two witnesses agree. (Live arm gated: backend + key.)
```

STEP 2 (F1) was the most decisive cheap datum and it **passed**: corruption compounds under
believe and is gated to zero under adjudicate, so the fleet thesis is live-confirmed at the
mechanism level. (Had it *not* compounded — peers self-recovering even at depth 4 — that would
have been the program's most important negative result, reshaping the pitch to "prevent the
cascades a *weak or non-LLM* consumer can't recover from"; `project-dos-peer-b-deltaB-measured`
shows that endpoint is where ΔB opens. Instead, the *state* form compounds with capable agents
too.) The remaining steps SCALE the confirmed picture; NEXT-A sharpens it from linear to F^D.

---

## 5. What this proves, and the line it must not cross

**Proves:** that the two live existence results (docs/228/233) are not artifacts of small N or
a constructed conflict — that on a *real, scaled, naturally-colliding* fleet the same
deterministic referee, off the same non-forgeable witness, prevents corruption whose cost
**grows with fleet scale**, exactly where in-loop fixes fail. That is the fleet-scale form of
the paper's thesis.

**The line:** every number stays off a witness the agent cannot author (the docs/138
invariant). Scaling must not smuggle in a believe-the-agent shortcut — e.g. F4's cascade cost
must be read off the DB-hash at each node, never off an agent's "I recovered" self-report.
And the monotone-shape result keeps its own falsifier: **value must still go to 0 at fleet=1**
(docs/204 §1). A fleet-scale claim that doesn't vanish at fleet-of-one is measuring an
artifact, not coordination.
