# docs/253 — F1-super-linear ran: the gate's payoff grows F^D, not D−1

> **One sentence.** F1 (docs/251) showed corruption reaches D−1 nodes down a single chain
> (linear); F1-super-linear runs the **fan-out tree** the fleet thesis is really about — every
> agent in a depth-D, fan-out-F dependency tree that touches the poisoned resource is corrupt
> under *believe* (F^D leaves), and the gate, blocking the root once, keeps **all** of them
> clean — so the prevented-corruption payoff is **super-linear (F^D), measured live**.

**Status:** executed. **Date:** 2026-06-08. **Spend:** ~$1.0 (≈40 live agent runs across two
tree sizes). **Provenance:** `benchmark/agentprocessbench/writeadmit/cascade_loop.py:run_fanout_live`
+ `live_results_fanout/fanout_d{2,3}_f2.json`. **Reads on:** docs/251 (F1, the linear chain
this extends — this is its NEXT-A), docs/245 (the fleet-scale plan), docs/204 §1 (the
fleet-of-one falsifier), `project-dos-horizon-keeper-k1-measured` (the q^N frame).

---

## 1. What was linear, and why the tree is the real claim

F1 (docs/251) handed a poison down a single **chain** A→B→C→D and found the payoff is **D−1**:
each downstream agent inherits the corrupt state and is blocked, so a depth-4 chain has 3
corrupt nodes the gate prevents. Honest, but **linear** — and the fleet thesis (docs/245 O4)
claims more: real fleets **branch**. One task spawns many subtasks, all sharing the same
context/resource, so a depth-D, fan-out-F dependency **tree** has **F^D** leaves, and a single
poisoned resource at the root sits upstream of *all* of them. The payoff of catching that one
over-claim should therefore be **F^D**, not D−1. F1-super-linear measures exactly that.

---

## 2. The setup (the fan-out tree, live)

Same poison as F1 (reservation R wrongly cancelled at the root), same entity-level witness (is
R still cancelled at a node's end?), same two arms (believe inherits the raw corrupt DB;
adjudicate inherits the gold DB the gate substitutes). The one change: instead of a single
chain, a **fan-out tree** — each node spawns `F` children, every node a **live Gemini agent**
acting on R. We run a live agent at every tree node and count the corrupt leaves (F^D of them).

---

## 3. The result — payoff = F^D

```
   depth D   leaves (F=2: F^D)   believe corrupt   adjudicate corrupt   PAYOFF   per-level (believe)
   ──────────────────────────────────────────────────────────────────────────────────────────────
     2             4                  4 / 4              0 / 4             4       lvl1 2/2, lvl2 4/4
     3             8                  8 / 8              0 / 8             8       lvl1 2/2, lvl2 4/4, lvl3 8/8
```

**Every leaf is corrupt under believe; the gate keeps every leaf clean under adjudicate.** The
payoff is **F^D — 4 at depth 2, 8 at depth 3** — against the chain's linear D−1 (1, 2) at the
same depths. The per-level counts show the spread is total: at every level, *all* F^d nodes
that depend on the poisoned reservation are corrupt. One over-claim caught at the root saves
the **whole tree**.

The contrast with the chain is the point:

| | chain (F1, docs/251) | tree (F1-super-linear, here) |
|---|---|---|
| structure | one line of agents | fan-out F=2 per node |
| payoff at D=2 | 1 | **4** |
| payoff at D=3 | 2 | **8** |
| growth | linear (D−1) | **super-linear (F^D)** |

---

## 4. The honest scope (what F^D here means, and does not)

This is the caveat that keeps the result truthful, and it is important:

- **This is BREADTH fan-out, not field-amplification.** "F^D corrupt" means *F^D agents each
  blocked by the shared poison* — every agent in the dependency tree that touches the cancelled
  reservation fails or stalls and leaves it corrupt. It is **not** one corrupt *value* mutating
  into many corrupt values. tau2's airline domain has **no clean derived-entity vector** for
  that (a corruption either blocks an agent or persists silently through its write; neither
  multiplies a value), and faking one would be dishonest. So the multiplier is the **fleet's
  branching topology**, not value mutation.
- **Why that is still the right fleet model.** A poisoned shared resource in a real fleet does
  not make agents "more wrong" — it makes *every agent that depends on it* fail, and that set
  grows F^D with how the fleet branches into subtasks. That is precisely the cost a referee at
  the root prevents. The breadth form is genuinely super-linear in depth (F^D vs D−1) and it is
  **un-constructed**: fan-out is how real fleets are organized, not a contrived collision.
- **The believe nodes are blocked, not amplifying** (inherited from F1): they give up on the
  poisoned task. So "F^D corrupt" is "the poison survived F^D stalled agents," the honest read.
- **Small, one model, one poison/fan-out.** F=2, depths 2–3, gemini-2.5-flash, the cancel
  poison. An existence result for the super-linear *shape*, not a calibrated F^D constant.
- **The fleet-of-one floor still holds** (docs/204 §1): at depth 0 (no downstream agent) the
  payoff is 0 — the value is a plurality phenomenon, exactly as the wall predicts.

---

## 5. What this settles, and the next step

It closes the headline half of the fleet-scale program (docs/245 O4): **the out-of-loop
referee's value grows super-linearly with the fleet, live.** The chain showed compounding is
real (D−1); the tree shows it scales with the fleet's branching (F^D). Together they are the
live, measured form of the q^N compounding claim the whole fleet thesis rested on — one
over-claim or clobber caught at the root is not one event saved, it is the **entire downstream
sub-fleet** kept clean.

**▶ THE NEXT STEP: F2 — the natural collision stream (docs/245 STEP 1+3).** Both F1 and
F1-super-linear *inject* the root poison (to keep the experiment cheap and deterministic). The
last open objection (docs/245 O2) is that the conflict is *constructed*. F2 closes it: run
K=4..16 live agents on *independently sampled* tau2 tasks against **one shared DB**, and let
the collisions fall out of the task distribution (two tasks that happen to touch the same
reservation collide on their own) — no pinning, no injection. The $0 half (predict the natural
collision rate from the task→entity map) gates the build. After F2, the only out-of-loop payoff
experiment still open is a second-benchmark port (F3) and the GPU-trained behavior delta.
