# docs/251 — F1 ran: corruption compounds down a believe chain; the gate stops it at the root

> **One sentence.** The cheapest decisive fleet-scale experiment (docs/245 F1) ran live: a
> poisoned reservation handed down a chain of live Gemini agents stays corrupt at **every**
> downstream node under *believe* (the agents do **not** self-heal a corrupt *state*) and at
> **zero** nodes under *adjudicate* (the gate blocks it at the root) — so the payoff grows
> with the fleet's reach, the first live evidence that the docs/228/233 event-payoffs
> **compound**.

**Status:** executed. **Date:** 2026-06-08. **Spend:** ~$1.5 (≈12 live agent runs over
depths 2–4). **Provenance:** `benchmark/agentprocessbench/writeadmit/cascade_loop.py` +
`live_results_cascade/cascade_d{2,3,4}.json`. **Reads on:** docs/245 (the fleet-scale plan;
this is its F1), docs/233 (the coordination payoff this extends), docs/236 (the crux this
answers: a *narrated* handoff self-heals, does a *state* handoff?), docs/204 §1 (the
fleet-of-one falsifier), `project-dos-horizon-keeper-k1-measured` (the q^N compounding frame).

---

## 1. The question, and why it is the one that matters

docs/228 (over-claims, J=15) and docs/233 (coordination, J=6) measured **events prevented**.
A skeptic's sharpest objection (docs/245 O4): an event prevented is a *rate*; what scales with
a fleet is **compounding** — a poisoned write is not one lost event, it is a corrupt *input*
every downstream agent then builds on, so uncaught error should spread with the fleet while a
gate that blocks it once keeps the whole fleet clean. We had never measured the cascade. F1
does.

The design pressure came from docs/236, which found that a **narrated** handoff (peer B
inherits agent A's *claim text*) lets a capable LLM **self-recover** — it re-reads the
phantom and heals it, so ΔB≈0 (the ≈0 was *recovery laundering*; a non-LLM endpoint showed
ΔB=+1.0). That predicts compounding is a property of **state**, not prose: if the corruption
lives in the **database a node inherits as its starting world** — not a sentence it can
second-guess — a node cannot re-check it away. F1 tests exactly that.

---

## 2. The setup (a state cascade, witnessed at the entity level)

One reservation R, on the tau2 airline DB. The **root** poison: R is wrongly **cancelled** (a
real state change that diverges the DB from gold — the structural stand-in for an over-claimed
write; the *natural* over-claim root is the docs/233 result, already measured). Then a chain of
`D−1` **live** downstream agents, each given a task that depends on R (add a checked bag to R),
pinned to R's real owner. Two arms differ only in the DB each node inherits:

- **believe** — each node inherits the **raw corrupt DB** (R cancelled), exactly as a peer
  that trusts the prior agent's output would.
- **adjudicate** — the gate checked the root claim against the root DB-hash, found it refuted,
  and **blocked** it, so every node inherits the **gold** DB (R active) instead.

**The witness is entity-level, and getting it right mattered** (two traps caught before
spending):
1. tau2's `db_match` is the **wrong** witness here: the evaluator builds the gold env on the
   *same injected init* (`evaluator_env.py:92-101`), so a gold-with-the-same-corruption can't
   see that the *start* was wrong.
2. A whole-DB hash conflates *legitimate task progress* (a node correctly adding a bag) with
   the poison.

The honest signal: **is R still in the poisoned (cancelled) state at the node's end?** (An
active reservation has `status=None`; a cancelled one has `status='cancelled'`.) A node is
*corrupted* iff R is still cancelled — i.e. it inherited the poison and did not heal it.

---

## 3. The result

```
   depth D     believe: nodes left corrupt     adjudicate: nodes left corrupt     PAYOFF
   ─────────────────────────────────────────────────────────────────────────────────────
     2                 1 / 1                            0 / 1                        1
     3                 2 / 2                            0 / 2                        2
     4                 3 / 3                            0 / 3                        3
```

**Under believe, every downstream node stayed corrupt; under adjudicate, every node stayed
clean; the payoff grows linearly with depth (D−1).** The deeper the chain — the more agents
downstream of the poison — the more corrupted nodes the gate prevents. That is the live
compounding curve.

The per-node detail is the honest, and most interesting, part:

- **believe nodes made no mutating calls** (`calls=[]`): handed a cancelled R, each live agent
  **could not** add a bag to it and **gave up**, leaving R cancelled. So the corruption did not
  *deepen* (the agents did not do something *more* wrong) — it **blocked each downstream
  agent's task and persisted through all of them.** Crucially, **none healed it**: no believe
  agent noticed "R should not be cancelled" and restored it. This is the docs/236 prediction
  confirmed live — **state corruption is not laundered the way narrated corruption was.**
- **adjudicate nodes succeeded** (`calls=['update_reservation_baggages']`): handed a gold R,
  each added the bag and left R clean. The fleet never saw the poison.

So the fleet-scale cost F1 measures is precisely: **the poison blocks every agent that depends
on the corrupted entity, and survives them all** — a fleet of stalled, still-corrupt nodes —
which the gate reduces to zero by refusing the bad write once, at the root.

---

## 4. Honest edges (stated no wider than the evidence)

- **Small, one model, one poison shape.** Depths 2–4, gemini-2.5-flash, one entity, the
  cancel-poison. An existence result for the compounding mechanism, not a calibrated curve.
- **The believe nodes are blocked, not actively amplifying.** "Corrupted = D−1" is "R stayed
  poisoned through D−1 agents who each failed on it," not "each agent corrupted *more*." The
  fanout multiplier (one poison → F^D corrupted leaves) is the *projection* this supports, not
  yet a measured super-linear curve — for that, downstream tasks would have to *write* on top
  of the poison and chain their outputs (the next F1 refinement).
- **The root is synthetic.** We inject the cancel rather than wait for a natural over-claim, to
  keep the experiment cheap and deterministic; the *natural* over-claim root is docs/233's
  measured 16% rate. The cascade *downstream* of the root is fully live.
- **Per-hop isolation, not serial drift.** Each node re-inherits the same root state (to read
  the inheritance effect cleanly per depth), rather than chaining node k+1 onto node k's actual
  output. Valid for the spread curve; a true serial chain is the refinement.
- **The fleet-of-one floor still holds** (docs/204 §1): at depth 1 (no downstream agent) the
  payoff is 0 — there is no one downstream to poison. The value is a *plurality* phenomenon,
  exactly as the wall predicts.

---

## 5. What F1 settles, and where it points

It settles the load-bearing half of docs/245 O4: **the out-of-loop referee's value compounds
with the fleet, live.** A believe-fleet carries a root corruption through every agent that
touches the poisoned entity, and — the decisive part — *the live agents do not heal it*,
confirming docs/236's "state, not narration" prediction at fleet scale. The gate's one refusal
at the root keeps the entire downstream fleet clean. This is the live form of the q^N
compounding claim the whole fleet thesis rested on, and it is now a measured curve, not an
assertion.

It points two ways: (a) the **super-linear** refinement (downstream nodes that *write* on the
poison, chained serially, to turn the linear D−1 into the F^D fanout curve), and (b) F2 (the
**natural** collision stream — K agents on a shared DB with collisions falling out of the task
distribution, not injected) — which together would close O2 and O4 fully. Both are in docs/245.

---

## ▶ NEXT STEP — ✅ F1-super-linear is DONE, now F2

**✅ DONE: F1-super-linear ([docs/253](253_f1-super-linear-the-fanout-tree-payoff-grows-f-to-the-d.md)).**
The fan-out tree the linear D−1 pointed at: every agent in a depth-D, fan-out-F tree that
touches the poison is corrupt under believe (**F^D**: payoff 4 at depth 2, 8 at depth 3), 0
under adjudicate — the payoff is super-linear, live. (It is breadth fanout — F^D agents
*blocked* by the shared poison, the correct fleet model — not value-amplification, which tau2
has no clean vector for.)

**▶ CURRENT NEXT STEP: F2 — the natural collision stream.** Both F1 and F1-super-linear
*inject* the root poison. F2 closes the last objection (O2, "constructed conflict"): K=4..16
live agents on *independently sampled* tau2 tasks against one shared DB, collisions falling out
of the task distribution (no pinning). The $0 half (predict the natural collision rate from the
task→entity map) gates the build. Tracked in
[docs/245 §4](245_proving-the-referee-at-fleet-scale-the-plan.md) (NEXT-B).
