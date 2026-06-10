# docs/233 — The coordination payoff, measured live: the arbiter prevents real clobbers

> **One sentence.** docs/228 measured the referee-OVER-CLAIMS payoff (a gate blocks
> over-claimed writes before a peer inherits them, J=5); this measures the *other* value
> half-plane — referee-BETWEEN-AGENTS — by running two live Gemini agents into a genuine
> lost-update conflict on a shared tau2 reservation and showing the **arbiter prevents 6
> real clobbers** the naive flow lets through, witnessed by the env DB-hash.

**Status:** executed. **Date:** 2026-06-08. **Spend:** ~$1.5 (24 live agent runs over
8 conflict pairs, gemini-2.5-flash). **Provenance:** every number is a read-off from
`benchmark/agentprocessbench/writeadmit/live_results_coord/` (gitignored), folded by
`coord_loop.py`. **Read first:** docs/228 (the write-admission payoff, the sibling),
docs/190 (the coordination *rate*: ≥5 concurrent same-file collisions @10s, which this
pairs with a *payoff*), docs/209 registry Item 4 (the spec), the four walls docs/204 §1
(fleet-of-one — why coordination value is a *plurality* phenomenon).

---

## 1. The two value half-planes, and why this is the second one

DOS has two orthogonal value axes (the horizon-keeper memory, docs/204):

- **Referee OVER TIME** — distrust one agent's *claim* about what it did. docs/228 measured
  it: an out-of-loop write-admission gate caught **J=5** over-claims off the env DB-hash.
- **Referee BETWEEN AGENTS** — serialize *concurrent* writes so one agent's effect doesn't
  silently overwrite another's. docs/190 measured the *rate* this happens (collisions per
  1k writes); it never measured the **payoff** (corruptions actually prevented). That gap
  is this doc.

The two share a witness discipline — the **gold DB-hash**, which the agent authors zero
bytes of (docs/138) — but they distrust different things: docs/228 distrusts a *narration*,
this distrusts a *race*.

---

## 2. The conflict, and the composition primitive

A genuine **lost update**: two agents read the same entity, each computes a change against
that read, and the second write lands without incorporating the first. Realized on tau2's
airline domain:

- **A1's task:** "cancel reservation R."
- **A2's task:** "add one extra checked bag to reservation R."

Both target the same reservation R. The user identity in each task is **pinned to R's real
owner** — otherwise a correct agent refuses to mutate a stranger's reservation and the
conflict never fires (a silent-J=0 trap caught before spending: reservation 4WQ150 belongs
to *chen_jackson_3290*, not the base task's *Emma Kim*).

**The composition primitive** (verified on `tau2-bench`): an agent's *effect* is its
tool-call sequence; tau2's env applies a tool-call against its in-memory DB via
`make_tool_call`. So two agents' effects compose onto one shared DB by replaying both. The
DB-hash of the composed env is ground truth.

The faithful **two arms** require running A2 *twice*:

```
  A1  ── live ──▶  cancels R                    ── capture A1's calls, build post-A1 DB
  A2-naive  ── live, ORIGINAL DB ──▶  adds a bag to R   (its call is STALE — computed before A1)
  A2-serial ── live, POST-A1 DB injected ──▶  sees R already cancelled  (the arbiter's outcome)
       (injected via task.initial_state.initialization_data.agent_data = A1's DB dump)

  NAIVE  hash = replay [A1's calls, A2-naive's calls] on one DB   (blind compose)
  SERIAL hash = replay [A1's calls, A2-serial's calls] on one DB  (A2 re-derived after A1)
```

This is the **causal** element (the same docs/229 asks of write-admit): A2 genuinely
*behaves differently* when it sees A1's commit — it does not blindly repeat its stale write.

---

## 3. The result — J = 6 over 8 conflict pairs

```
        R          A1                 A2-naive (stale)        A2-serial (post-A1)   clobber  J
  ───────────────────────────────────────────────────────────────────────────────────────────
  4WQ150   cancel_reservation   update_reservation_baggages   (none)                  yes    1
  JP6LYC   cancel_reservation   update_reservation_baggages   (none)                  yes    1
  JW6LEQ   cancel_reservation   update_reservation_baggages   (none)                  yes    1
  PGAGLM   cancel_reservation   update_reservation_baggages   (none)                  yes    1
  UUN48W   cancel_reservation   update_reservation_baggages   (none)                  yes    1
  V5XFMY   cancel_reservation   update_reservation_baggages   (none)                  yes    1
  VAAOXJ   cancel_reservation   (none — agent declined)       (none)                  no     0   ← honest negative
  1OWO6T   (none)               (none)                        update_reservation_bag  no     0   ← variance, not a clobber
  ───────────────────────────────────────────────────────────────────────────────────────────
  arbiter serialized (refused the 2nd concurrent lease): 8/8        TOTAL J = 6
```

In the **6 canonical clobbers**: A1 cancels R; A2-naive — never having seen the cancel —
adds a bag to R, and the blind naive compose applies *both* → a **corrupted** DB (a cancelled
reservation carrying a freshly-added bag). A2-serial, seeing R already cancelled, correctly
makes **no** mutation → coherent state. The naive and serialized DB-hashes differ; the
arbiter, refusing A2's concurrent lease on `reservations/R`, produces the serialized
(correct) state. **That prevented corruption is J.**

The two non-clobbers are the honest part:

- **VAAOXJ — the falsifier working.** A2 *declined* to add the bag (no stale write occurred),
  so there is nothing to clobber and J correctly stays 0. No conflict, no payoff — exactly as
  it should read.
- **1OWO6T — an over-count caught and removed.** Here A1 did nothing and A2-*serial* mutated
  *more* than A2-naive (pure run-to-run variance in the live policy). An earlier, symmetric
  J definition (`naive_hash != serial_hash`) wrongly flagged this as a clobber. The corrected,
  **directional** definition — a clobber requires the naive 2nd-agent to apply a stale write
  the serialized 2nd-agent did *not* — drops it to J=0. **The live run took J from a reported
  7 to an honest 6.** (The fix: `coord_loop.coordinate`, committed; the $0 smoke pins it.)

---

## 4. The key→region mapper — the "hard part" was one line

The registry flagged "N agents on the same DB needs a key→region mapper" as the hard lift.
It is trivial: a DB entity is a **path-like region string** `reservations/<id>`, so two
agents touching the same reservation produce overlapping `requested_tree`s and the existing
`_tree.prefixes_collide` refuses the second — no new arbiter machinery. The $0 smoke
(`coord_loop --smoke`) pins the invariant: a 2nd agent on the *same* reservation is refused
(serialized); on a *different* reservation it is admitted (concurrent). 8/8 pairs serialized
in the live run.

---

## 5. Honest caveats

- **Small n, one model, one conflict shape.** J=6 over 8 pairs, gemini-2.5-flash,
  cancel-vs-add-bag. A real existence result (the arbiter prevents genuine live clobbers,
  witnessed by ground truth), not a calibrated rate. Other conflict shapes (update-vs-update,
  double-book) and a second model would harden it.
- **The conflict is constructed, the agents are live.** We *pin* both agents to the same
  reservation (the structural conflict is designed); *how* each agent acts — which tool, which
  args, whether it declines — is the live policy's own decision. So the clobber is real agent
  behavior on a designed contention, not a natural-traffic collision rate (that is docs/190's
  job — pair the two).
- **J counts state CORRUPTION, not wasted effort.** If a stale write *errors* harmlessly on
  the changed entity (no state change), it is not a clobber under this J even though the agent
  wasted a turn. This is the conservative, defensible choice — J is "a corruption the arbiter
  prevented," read off the hash.
- **Run-to-run variance is real** (pair 1OWO6T) and is *why* the directional J definition
  matters — report J as a property of a distribution of rollouts, not a per-pair label.
- **This is a buyer/operator coordination result**, not a frontier-lab science result — "why a
  shared DB is the case worktree isolation can't cover" (the docs/204 §1 plurality point; at
  fleet=1 there is nothing to collide with).

---

## 6. The through-line

Pair this with docs/228 and the picture is symmetric: the **same DB-hash witness** grounds
both DOS value half-planes, now both measured live, both as a *payoff* (not a rate):

| | distrust target | consumer | live payoff |
|---|---|---|---|
| docs/228 | an agent's **claim** (over-claim) | a downstream **peer**'s inherited state | **J=5** over-claims blocked |
| docs/233 | a **race** (concurrent write) | the **shared DB** + the clobbered peer | **J=6** clobbers prevented |

And docs/190 supplies the *rate* this coordination conflict occurs in real traffic (≥5
concurrent same-file collisions @10s), which §5 says to report **alongside** — never instead
of — this payoff. Rate says *how often*; payoff says *what was saved when the referee acted*.
Both, labeled apart, off ground truth.
