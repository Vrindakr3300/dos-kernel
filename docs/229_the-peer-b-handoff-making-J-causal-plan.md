# docs/229 — The peer-B handoff: making J *causal* (plan)

> **One sentence.** docs/228 measured **J = 5** as a *counted* inheritance
> (confident-write × witness-refuted × blocked); this plan turns J into a
> *causal outcome delta* by wiring a real downstream peer B that inherits what
> the gate published and measuring B's task success under the **believe** arm
> (B starts from A's claim) vs the **adjudicate** arm (B starts from the
> env-verified state) — so J stops being "the gate blocked 5 things" and becomes
> "blocking those 5 things measurably stopped the error from compounding."

**Status:** ✅ EXECUTED — see **docs/235** for the run + the result (ΔB ≈ 0 at a single
capable self-verifying hop, because the peer re-verifies the phantom; the cheap "trust-handoff"
lever ruled out; the payoff localized to a structurally-weaker / non-LLM / multi-hop consumer).
Two refinements landed vs this plan: (1) **same-task replay** replaced the bespoke
dependent-task design — B re-runs A's *own* task, so the dependent work *is* the task and no
follow-on needs authoring; (2) the §5 kill-2 (believe-arm self-recovery) became the **headline**,
not a footnote. **Date:** 2026-06-08. **Read first:** docs/235 (the executed result), docs/228 (the
live J=5 result this extends), docs/216 (the gate + frozen slice), docs/209 (why
out-of-loop is the only positive half-plane), docs/179 (J is a FLIP not a
re-projected rate — the fold-mints-data law this plan must honor).

---

## 1. The gap this closes

docs/228 is a real existence result: the gate caught and blocked five live
over-claims off the env DB-hash and admitted all nine honest writes, with the
`believe_under_floor` discipline making it structurally unforgeable. But read the
caveat in its own `live_loop.py` header:

> *A frozen replay cannot produce J (there is no peer B, no handoff ledger, no
> input-dependent second run in the corpus) — only a live loop flips an
> inheritance.*

The live loop flips a **counted** inheritance. `_report` computes
`J = confident-write × db_match==False × admit==False`, but **no second agent
ever actually runs on what the gate published.** The believe-vs-adjudicate split
— the entire thesis of the docs/188→209 arc — is *asserted arithmetically*, not
*measured causally*. The unanswered question is the one a skeptic asks first:

> *Granted the gate blocked 5 phantom writes. Does blocking them actually change
> a downstream outcome — or would peer B have recovered anyway?*

That is the difference between a **detection** result (docs/228 has it) and a
**value** result (the docs/188→209 arc keeps demanding it, because every
agent-side fix washed out — the proactive memory, docs/206). J is only a payoff
if a real B inherits the difference and its **task success rate moves**.

---

## 2. The feasibility finding (why this is buildable, not just sketchable)

The blocking question was: *can a tau2 task be seeded from a non-gold (mutated)
DB state, so peer B genuinely inherits A's end-state?* **Yes** — verified on the
`tau2-bench` clone, 2026-06-08:

- `Task.initial_state: Optional[InitialState]` (`data_model/tasks.py:586`) —
  *"used to set the initial state of the environment and of the orchestrator."*
- `run_single_task` → `_build_env_kwargs(config, task)` (`runner/batch.py:413`)
  threads the task's init into the env before the rollout.
- The telecom domain already **constructs `initialization_actions`
  programmatically** (`domains/telecom/tasks/manager.py:133` builds
  `initial_state["initialization_actions"]`; `:205-206` passes
  `initialization_data` + `initialization_actions` through). So seeding an env
  to an arbitrary pre-state via a list of tool-actions is a **supported,
  exercised path**, not a hack into private state.

This means peer B's starting world is **controllable as data**: hand B an
`initial_state` whose `initialization_actions` reproduce A's *claimed* end-state
(believe arm) or the *env-verified* end-state (adjudicate arm). The handoff is a
first-class tau2 object, which keeps the experiment inside the seam DOS already
respects (state-in / outcome-out; the kernel never reads B's bytes either).

---

## 3. Two designs — pick the cleaner causal contrast

There are two ways to make B's outcome *depend* on whether A's write was real.
They measure slightly different things; the plan builds **Design A first** (it is
the tighter, lower-confound contrast) and keeps **Design B** as the richer
follow-on.

### Design A — the *dependent-task* contrast (recommended first)

Don't reconstruct a phantom DB at all. Instead, give B a task whose **correct
completion presupposes A's write landed**, and vary only **what B is told about
the starting state**:

- **believe arm:** B's `initial_state` asserts A's claim as true (e.g. message
  history / a system note: *"reservation Q69X3R has been cancelled"*) — the
  literal thing a peer inherits when it trusts A's published "done."
- **adjudicate arm:** B's `initial_state` carries the **gate's verdict** instead
  — for a BLOCKED (refuted) write, the env-verified truth (*"the cancellation did
  NOT complete; the reservation is still active"*); for an ADMITTED write, the
  same as believe (the gate changed nothing, correctly).

Then run B live and read **B's own `db_match`** (its task's env witness). The
measured quantity:

```
ΔB = success_rate(B | adjudicate) − success_rate(B | believe)
```

over the tasks where A over-claimed (the 5 REFUTED rows) and, as a control, over
the tasks where A was honest (the 9 CONFIRMED rows — ΔB should be ≈0 there,
because the gate published the same state in both arms). The headline is:
**on the over-claim tasks, does B do better when the gate corrected the handoff?**
This is J re-expressed as a *downstream outcome*, not a count.

**Why A first:** it isolates the one variable that matters — *the truthfulness of
the inherited claim* — and uses tau2's own evaluator as B's witness, so the
result is ground-truthed on both ends (A's write by db_match, B's outcome by
db_match) with no human label anywhere. It is the cleanest possible expression of
"compounding error, prevented."

### Design B — the *replayed-DB* contrast (richer, more confounded)

Actually seed B's env to A's mutated DB (via `initialization_actions` that replay
A's executed tool-calls) vs the gold DB, and give B a **follow-on task in the same
account** (a second mutation that builds on the first). This measures real
compounding through the database, not through a narrated note — but it adds
confounds (B's task is now a different task; the DB-replay fidelity must be
verified). Build it only if Design A shows a signal worth deepening.

---

## 4. The build order (each step gated, $0 until the live step)

Mirror docs/216's discipline — prove the mechanics at $0, then spend.

1. **`peer_b.py` — the handoff ledger + arm constructor ($0, pure).** A function
   `handoff(a_row, arm) -> InitialState` that, given one A-run's cached row
   (`db_match`, `admit`, `answer_excerpt`, `claim_key`) and an arm, returns the
   `initial_state` for B. believe = assert A's claim; adjudicate = assert the
   gate's verdict (gold truth on a BLOCK, A's claim on an ADMIT). Pure, unit-
   tested against hand-written A-rows — **no model.** This is the docs/179
   fold: it mints B's starting belief by joining A's claim × the gate verdict,
   two independently-authored facts.
2. **The B-task map ($0).** For each of the 14 confident-write A-tasks from
   docs/228 (5 REFUTED + 9 CONFIRMED), define B's dependent task (Design A): the
   minimal follow-on whose success requires A's write. Start with the airline
   over-claims (4 of the 5) — cancellations/updates have clean dependent tasks
   ("now rebook / now refund the cancelled reservation").
3. **Frozen A/B dry-run ($0).** Run `peer_b.handoff` over the cached A-rows and
   print the *intended* arm contrast (which B-tasks get which `initial_state`),
   asserting the control invariant: on every CONFIRMED row, believe and
   adjudicate produce the **same** `initial_state` (the gate is a no-op when A is
   honest — a structural check that ΔB's control arm is ≈0 by construction).
4. **Live B run (PAID, gated on `GEMINI_API_KEY`).** Drive B live under both arms
   on the 14 tasks (28 rollouts; ~$0.40 at the docs/228 $0.014/task rate).
   Resumable per-`(task, arm)` JSON cache, same as `run_writeadmit`. Read B's
   `db_match` per arm.
5. **`_report_causal` — the ΔB fold.** Print `success_rate(B|believe)`,
   `success_rate(B|adjudicate)`, ΔB on the over-claim slice and on the honest
   control slice, with the per-task table (B-task, arm, B's db_match). The
   headline number is **ΔB on the over-claim slice**.

---

## 5. What would kill it (state the falsifiers up front, docs/216 §5 discipline)

- **kill-1 — ΔB ≈ 0 on the over-claim slice.** If B succeeds (or fails) at the
  same rate whether or not it inherited the phantom, then *blocking the write did
  not prevent a downstream failure* — J is a true detection but not a measured
  payoff *at this handoff*. That is a real, publishable negative (it would say:
  the value of blocking is not in the immediate next task; look further
  downstream, or the recovery is cheap). **Do not bury it** — it is the docs/206
  pattern (every active fix washed) and must be reported if it occurs.
- **kill-2 — believe-arm B recovers on its own.** A capable B may *re-verify* the
  inherited claim (call `get_reservation_details`, notice it is still active) and
  self-correct — erasing ΔB. This is the docs/199 event-rate bound striking
  again, one layer out. Mitigation: measure it, don't engineer against it; a B
  that recovers is a finding about *how much* the gate buys over a self-checking
  peer (possibly little — which is itself the honest answer the arc keeps
  surfacing). Report ΔB *with* the believe-arm self-recovery rate.
- **kill-3 — the handoff note is not how a real peer inherits.** Design A injects
  A's claim as a *narrated* `initial_state`, not a mutated DB. If a skeptic says
  "a real peer reads the DB, not a note," Design A under-measures. That is why
  Design B (replayed DB) exists — but A is the honest *first* measurement of the
  *narrated*-handoff case, which is exactly how an LLM fleet passes work today
  (one agent's summary becomes the next agent's context). Label it as the
  narrated-handoff result, not the DB-handoff result.
- **kill-4 — n is tiny (14 tasks, one model).** Same caveat as docs/228 §5; this
  plan inherits it. ΔB on 5 over-claim tasks is an existence/direction result, not
  a rate. Hardening (the §6 prerequisite) widens A's slice first so B has more
  over-claims to inherit.

---

## 6. Prerequisite: harden docs/228 first (cheap, do before §4)

The peer-B fold rides on A's over-claim slice, which is currently 5 tasks. Two
$0–$8 steps make the whole thing sturdier and should land **before** the live B
run:

1. **Two models + full task sets ($≈8).** Re-run `run_writeadmit --sample`
   across the full airline+retail sets on gemini-2.5-flash **and** a second model
   (Sonnet or gemini-3-pro), fixing the 7-task retail 5xx attrition (longer
   backoff / cap `max_steps` on the longest dialogues). Report A's J as a
   **calibrated rate with a CI**, not just the existence count. Cost is *not* the
   constraint ($0.014/task; the $30 budget is barely touched) — the 5xx attrition
   is. This widens A's over-claim slice so B inherits more than 5.
2. **Validate the claim-extractor against ground truth ($0 — reuses the cached
   run logs).** The load-bearing weak link is `_confident_write_claim` (a
   hand-tuned regex pile in `_overclaim_probe_witness.py`); its live **recall**
   (over-claims it *misses* → J is a floor, true J could be higher) and
   **precision** (honest answers it falsely tags confident-write → inflates the
   believe denominator) are **unmeasured live**. Cross-tab `confident_write`
   (regex) × `db_match` (witness) over every clean A-run already cached, and
   hand-audit the `db_match==False & confident_write==False` cell to estimate the
   miss rate. This is free and is the single check that could move J *up* or
   expose a soundness gap in the headline.

---

## 7. The through-line

docs/188→209 proved *by elimination* that the only positive place to spend a DOS
verdict is out of the producing agent's loop, and docs/228 *demonstrated* the
gate catching real over-claims live off ground truth. But docs/228's J is a
**counted** inheritance — the second agent that gives the count its meaning never
ran. This plan runs it: a real peer B inherits what the gate published, and its
**task success becomes the measurement**. If ΔB is positive on the over-claim
slice, the docs/188→209 arc has its first *causal* out-of-loop payoff — not "the
gate blocked 5 things," but "blocking them made the next agent measurably more
right." If ΔB is ≈0, that is the honest, arc-consistent negative (the value is not
at the immediate next hop), and it tells us exactly where to look next. Either
way, J stops being arithmetic and becomes an outcome.
