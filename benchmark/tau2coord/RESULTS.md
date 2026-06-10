# tau2coord — the docs/233 coordination payoff, ported across τ²-bench domains

> **Headline: the DOS arbiter prevents J = 8/8 lost-update clobbers across two
> τ²-bench domains (airline + retail), off the τ²-bench DB-hash — deterministic
> ($0) — and J = 8/8 again with live headless `claude -p` agents producing the
> effects. A re-run wrapper prevents ~0 of these (each agent's own check already
> passed).**
>
> Measured 2026-06-09 at `d8d050e`. `python -m benchmark.tau2coord.coord
> --deterministic` (the $0 core) and `python -m benchmark.tau2coord.live_claude`
> (the live headless-Claude confirm arm).

This is a **port**, not a new claim. It carries the already-measured docs/233
coordination win (naive agents corrupt a shared τ²-bench reservation DB; the
arbiter with a semantic effect-lease region prevents it → J = 6/8, later J = 9/10)
onto τ²-bench's **deterministic-DB-state** grading and **two** of its domains, and
swaps the live agent from Gemini to **headless `claude -p` sessions**.

## What is and isn't being claimed (the concession comes first)

τ²-bench already grades each task with a **deterministic DB-state check** — a
sound, non-forgeable witness. So on **single-agent** verification, **DOS adds
nothing**: the env's own check already catches a single agent that lies about
what it did. We concede that outright. (The single-agent intervention hop is
*also* recovery-gated and mildly harmful to act on — ΔB = −50% in the live
value-add study — so we do not re-litigate it here.)

The value is the **fleet** case the deterministic check *and* a re-run wrapper
cannot reach: **two agents on one shared τ²-bench DB**. A check can read *true*
when agent A looks and *false* when A writes, because agent B changed the state in
between — TOCTOU lifted onto world state. Each agent's *own* check passes, so a
re-run wrapper (which just re-executes a single agent and re-checks) prevents ~0.
The arbiter is the only thing that serializes the contended region.

> **J = lost-update clobbers PREVENTED, off the DB-hash neither agent authors.
> NOT tasks-won.** (docs/233 discipline.)

## The mechanism (ported one-for-one from `writeadmit/coord_loop.py`)

A **conflict pair** = two agents targeting one entity:

- **A1** issues the **cancel**-shaped mutation (cancel the reservation / order).
- **A2** issues a **stale** mutation computed against the entity's *pre-cancel*
  state (add a bag / change the shipping address).

Three arms, all read off `env.get_db_hash()`:

| Arm | What it is | Result |
|---|---|---|
| **NAIVE** | A1 then A2 replayed blind on one shared DB, arrival order, no coordination. A2's call was computed before A1's cancel. | the clobber |
| **SERIAL** | the arbiter's outcome: A1 lands, A2 **re-derives** against post-A1 state, sees the cancel, and coherently no-ops. == the A1-only state. | the correct state |
| **ARBITER** | would `dos.arbiter.arbitrate` refuse A2's concurrent lease on `<collection>/<id>` while A1 holds it? | refuses → serialize |

The **key→region mapper** the docs/233 registry flagged as "the hard part" is one
line: a DB entity is a path-region `reservations/4WQ150`, `orders/#W5918442`, so
two agents on the same entity produce overlapping trees and the arbiter refuses the
second. No new arbiter machinery.

### Two clobber signatures — the port surfaced a second one

Porting from airline-only to airline + retail revealed that τ²-bench lost updates
take **two** shapes, and a sound port must catch **both**:

1. **Incoherent-merge** (airline): A2's stale `update_reservation_baggages` *lands*
   on the reservation A1 already cancelled → the naive composite hash **differs**
   from the clean serial hash. A cancelled reservation that nonetheless carries a
   modified bag count = a corrupted state.
   - Witnessed: pair `4WQ150` → naive `039555b56b9e` ≠ serial `bacecb3b4601`.
2. **Dropped-write** (retail): A2's stale `modify_pending_order_address` *errors*
   on the order A1 already cancelled → A2 applied 0 in the composite though it
   applied 1 alone → its work silently vanishes (the classic lost update). The
   hashes here are **equal** (naive == A1-only == serial), so the hash metric alone
   misses it; the `solo_applied > naive_applied` count catches it.
   - Witnessed: pair `#W5918442` → naive == serial `d10d0dcb1a28`, but
     `a2_solo_applied = 1 > a2_naive_applied = 0`.

A clobber = signature (1) **OR** (2). In **both**, the arbiter prevents it
identically by refusing A2's concurrent lease and forcing the serial outcome.

## Results — deterministic ($0) arm

`python -m benchmark.tau2coord.coord --deterministic --domains airline,retail --pairs 4`

| domain | pairs | signature | NAIVE clobbers (baseline) | ARBITER-prevented **J** |
|---|---|---|---|---|
| airline | 4 | incoherent-merge | 4 | **4** |
| retail | 4 | dropped-write | 4 | **4** |
| **total** | **8** | — | **8** | **8** |

- **NAIVE baseline = 8 lost updates** — committed by the un-refereed arm; a re-run
  wrapper prevents none of them (each agent's own check passed).
- **J = 8 clobbers prevented** by the arbiter, off the τ²-bench DB-hash.

### Falsifier control (the metric can report J = 0)

The deterministic arm carries its own falsifier (docs/233's "J = 0 = the falsifier
working"): two agents on **different** entities must **not** be serialized.

| domain | admit_disjoint (expect True) | admit_same (expect False) | control |
|---|---|---|---|
| airline | True | False | ✅ |
| retail | True | False | ✅ |

`controls_ok = True` — the arbiter admits a disjoint lease and refuses only the
same-entity one, so the metric is **not** rigged to always report "prevented."

## Results — live headless-`claude -p` confirm arm

`python -m benchmark.tau2coord.live_claude --domains airline,retail --pairs 4`
(model `claude-haiku-4-5-20251001`)

Here the **agents are real headless `claude -p` sessions** (the docs/272 forge
pattern — the model named only in the shelled command, never imported). Each agent
is shown the entity's *current* state + a goal and **chooses** its τ²-bench tool
call (or declines). A1 and A2-naive read the **pre-cancel** state; A2-serial reads
the **post-A1** state. The model authors the *decision*; the env authors the
DB-hash that scores it. (Structural boilerplate the agent shouldn't invent —
`payment_id`, address fields, the `reason` enum — is normalized to known-valid
values; the **decision to act vs. decline** is left entirely to the model.)

| domain | pairs | NAIVE clobbers | ARBITER-prevented **J** | A2-serial behavior |
|---|---|---|---|---|
| airline | 4 | 4 | **4** | declined (saw the cancel) |
| retail | 4 | 4 | **4** | declined (saw the cancel) |
| **total** | **8** | **8** | **8** | **8/8 coherent re-derivations** |

The live finding worth its own line: in **every** serial pair, Claude — reading the
post-A1 state — **correctly declined** (no stale write). That is exactly the
coherent re-derivation the arbiter forces by serializing. The naive agent, reading
stale pre-A1 state, clobbered every time. The live numbers reproduce the
deterministic ones.

## The honest limit — which half-plane this closes

This is the **shared-mutable-state** half-plane, the one **isolation does not
close**:

- A pure **code-gen** fleet with provably-disjoint branches and CI as the merge
  gate is already covered by isolation — a git worktree sandboxes the *workspace*.
- A worktree does **not** sandbox the *world*. Two agents mutating one shared
  database, queue, filesystem, or external service share a blast radius no
  worktree contains. That is the case measured here, and the case the arbiter's
  region-lease is for.

Caveats (carried from docs/233): this is a **buyer/operator** result, not a
capability-frontier one; the conflict is **constructed** (A1 cancels, A2 mutates
the same entity) though the live arm's *decisions* are real model behavior; **n is
small** (8 deterministic + 8 live pairs, two domains, one small live model). The
claim is narrow and non-forgeable: **on a shared τ²-bench DB, a fleet of two agents
loses updates a re-run wrapper cannot prevent, and the arbiter prevents them —
measured off the DB-hash neither agent authors.**

## Reproduce

```bash
# $0 deterministic multi-domain A/B (the headline J, with the falsifier control)
python -m benchmark.tau2coord.coord --deterministic --domains airline,retail --pairs 4

# the regression guard (pure arbiter invariants always run; DB-hash tier skips if
# tau2-bench is absent)
python -m pytest benchmark/tau2coord/test_coord.py -q

# the live headless-claude confirm arm (resumable per-pair cache, gitignored)
python -m benchmark.tau2coord.live_claude --domains airline,retail --pairs 4
```

Provenance: ported from `benchmark/agentprocessbench/writeadmit/coord_loop.py`
(docs/233). See `[[project-dos-coordination-payoff-measured]]` (J = 6/8),
`[[project-dos-valueadd-coord-live-9of10]]` (J = 9/10), and
`[[project-dos-wall-fleet-of-one]]` (overwrites-prevented is 0 at fleet = 1 by
construction, real at fleet > 1) in the memory store.
