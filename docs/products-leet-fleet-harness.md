# leet — a fleet-first coding harness built verification-first

> *Vision / design note, 2026-06-14. Imagination exercise — no lease taken, no
> kernel touched, nothing committed by this note's authoring. It synthesizes the
> best of three lineages: **DOS** (this kernel — the trust substrate), **Dispatch**
> (the job-dir / run-dir orchestration half the reference userland app proved,
> docs/140, docs/207), and the **2025–26 agent-harness state of the art** (Claude
> Code agent teams, Hermes' provider-agnostic core + two-tier hooks, the
> worktree/container/microVM isolation consensus, the conductor pattern of
> docs/98). It is a product sketch, not a committed plan; every load-bearing claim
> points at an existing doc or a measured result.*

## 0. The one-sentence pitch

> **leet is the first coding harness whose loop is a closed-loop controller, not an
> agent with a verifier stapled to its exhaust** — it runs a fleet of agents on one
> repo, admits each agent's writes through a file-tree lease *before* the write, and
> can never let any agent (or the orchestrator itself) declare "done" on its own
> say-so. The agents are the plant; **leet is the controller** (docs/333).

Every other harness in 2026 is the other machine: an agent loop with a grader bolted
on at the seams the loop happened to expose (the tool-return and the end-of-run).
That is a *fork, not a spectrum* (docs/333 §4) — and leet is built on the far side of
it from the first type.

---

## 1. Why now — the whitespace the field left open

The landscape as of mid-2026 (surveyed, sourced) converges on two patterns and
leaves two holes. The holes are exactly DOS's two primitives.

**What everyone ships:**

- **Isolation by worktree / container / microVM.** Cursor (8 parallel agents, local
  worktrees + cloud Ubuntu VMs), Sculptor (one Docker container per Claude Code
  agent), Container-use (Dagger: fresh container + git branch per agent over MCP),
  Conductor / Crystal / Claude Squad (worktree-per-agent desktop apps), Devin
  (per-task cloud DevBox), Codex / Jules (per-task cloud sandbox). Isolation is a
  **solved, commoditized** layer.
- **Verification by test-execution + CI-as-judge + human PR review.** The SWE-bench
  lineage made "run the PR's tests" the standard oracle; products externalize the
  merge gate to existing CI + a human. LLM-as-judge (Amp's *Oracle* review subagent;
  eval-time trajectory grading) is an *advisory* rung, not a hard gate.

**The two holes — and the measured fact that they bite:**

1. **No pre-work, file-tree-level admission primitive.** Claude Code agent teams say
   it in their own docs: *"Two teammates editing the same file leads to overwrites.
   Break the work so each teammate owns a different set of files."* That is
   **partition-and-hope** — collision *avoidance* by manual decomposition, plus a
   file-locked *task* list (task-level mutex, never file-tree-level). Nobody answers
   *"may these two workers run concurrently, given their globs?"* as a decision made
   **before** the write. DOS does: `arbitrate`/`lease` over tree-disjointness, and
   the cost of *not* having it is measured — a naive cross-process fan-out's
   collision-prevention **collapses to 0% the moment contention appears (fleet ≥ 4)**
   and the gap **grows monotonically with fleet size** (docs/98 §4.1). Coordination
   overhead grows ~quadratically with agent count, which is why every product caps at
   "start with 3–5 agents." A real admission primitive is what lets the fleet grow
   past that wall safely.

2. **No git-evidence-grounded "did it actually happen?" — verification is
   self-report or test-output.** Test-green proves *the tests the author wrote*
   passed — including the case where the author (increasingly an agent optimizing for
   green) deleted the assertions and wrote `fix: tests pass`. The orchestrator's own
   `completed` is itself an unverified self-report: **32% of real fan-out subagents
   fold a harness-authored `429` error *string* as a finished "finding"** while the
   tool reports `completed` (docs/197 §2, independently reproduced at 31.2% over 4,698
   transcripts). No surveyed third-party tool ships an equivalent of `verify` /
   `commit_audit` — a verdict read from **git ancestry and the commit-vs-diff
   relation**, authored by bytes the agent could not write.

leet's distinguishing claim is the one no competitor can copy without rebuilding
their trust model from scratch: **it does not believe its own agents — or its own
orchestrator.**

---

## 2. The three lineages, and exactly what leet keeps from each

### 2.1 From DOS — the trust kernel (the part that doesn't believe the agents)

leet does **not** reinvent the kernel; it *embeds* it and makes its verdicts the
spine of the control loop. The syscalls it leans on, by role in the loop:

| Kernel syscall | Role in leet's loop | Byte-author of the verdict |
|---|---|---|
| `arbitrate` / `lease` (+ `lease-lane` WAL write-back) | **Pre-effect admission** — may this agent take this lane now? | the live leases folded from the WAL + requested tree geometry |
| `verify` / `oracle.is_shipped` | **The bank step** — did `(plan,phase)` actually ship? | git ancestry + files-touched + run registry |
| `commit_audit` | **Per-commit honesty** — does the subject match its own diff? | the commit machinery (diff), not the message |
| `liveness` | **Is this run ADVANCING or just SPINNING/STALLED?** | git/journal delta + real heartbeat, never a clock |
| `productivity` / `efficiency` | **Loop-economics** — is per-step work fading? is work worth its tokens? | env-authored per-step deltas + provider-billed tokens |
| `completion` (residual = declared − verified) | **The stop condition** — is the residual empty against ground truth? | git-ancestry-verified progress, not the claim |
| `effect_witness` / `reward` | **Non-git effects + training-label admission** — did the world change as claimed? | the read-back witness (GET / state-diff / OS exit), not the agent |
| `resume` / `intent_ledger` | **Recovery** — a reaped worker proposes a re-entry SHA | git ancestry re-adjudicated, not the dead run's `STEP_CLAIMED` |
| `refuse(reason_class)` | **Every "no" is a typed, fixable token** from a closed vocabulary | the closed reason registry |
| `verify-result` (`result_state`) | **The fold-site catch** — is this subagent's terminal a harness-authored death? | `model=="<synthetic>"` (the harness stamps its own authorship) |

The kernel is **already** vendor-free, host-free, pure-`classify(evidence, policy)`,
reachable over CLI / MCP / `import dos` (the litmus tests of CLAUDE.md). leet is one
more **driver** of that seam — the conductor (docs/98). It is *anticipated*, not a
hack: "the orchestrator is a driver, and the trust kernel does not care which driver
runs" (docs/98 §5).

### 2.2 From Dispatch — the job-dir / run-dir orchestration half

Dispatch (the reference userland app DOS was lifted out of) proved the **other** half:
the durable orchestration spine that turns one pure verdict into a running fleet
(docs/140 §1 — 48 files consume the dispatch half). leet keeps its structure:

- **The run-dir is the unit of durable identity.** Every dispatched agent gets a
  `run_id`-keyed directory holding three durable surfaces (docs/116): the **lease WAL**
  (what region it holds), the **intent ledger** (`intent.jsonl` — declared extent +
  adjudicated progress, kept deliberately apart so *residual = declared − verified* is
  computable at every step), and the **run registry** row (status). This *is* the
  "job dir" concept generalized: a crash-safe, replayable, distrusted record of one
  unit of work. Every durable record carries a `durable_schema` tag (refuse-don't-guess
  on a newer kernel's record).
- **The loop-decide spine + the picker substrate.** The continue/stop/next-mode
  decision is the kernel's typed loop verdict, not inline prose (`dos gate` /
  `loop_decide.decide`): the breakers (`consecutive_unclear`, `dirty_zero`,
  `stale_stamp`), the iteration cap, the drained-twice signal. The picker
  (`enumerate` → `pickable` → `cooldown` → `pick_priority` → `reconcile`) decides *is
  there anything pickable, why-not, have I tried it, did the claim hold, what fresh
  unit first* — the anti-churn machinery that stops the 5.3%-ship re-pick storm
  (docs/207, `pick_priority` motivation).
- **The supervisor as PID-1.** Keep a target population of worker loops alive across
  the lane roster: spawn on demand, **reap only provably-STALLED leases**, and
  **surface (never kill) a SPINNING worker** — the `supervise()` verdict, carried out
  by the loop, never decided by it (the `dos-supervise-loop` shape).

### 2.3 From the 2025–26 harness state of the art

The synthesis that makes leet *usable*, not just *correct*:

- **Agent teams (Claude Code), upgraded.** Keep the shared task list with
  dependencies + auto-unblock, the mailbox, the teammate-from-subagent reuse, the
  plan-approval gate, the team-lifecycle hooks (`TeammateIdle`, `TaskCreated`,
  `TaskCompleted` — each able to exit-2 *block a transition and feed back*). leet's
  upgrade: the task list's **claim is a file-tree lease, not just a file lock**, and
  `TaskCompleted` is **refused by `verify`**, not by a teammate's say-so. This is the
  exact seam Claude Code leaves advisory.
- **Hermes' two ideas worth stealing.** (1) A **provider-agnostic agent core fronted
  by many I/O surfaces** (CLI / gateway / API / cron / batch) — leet's controller is
  model- and host-agnostic, exactly as the kernel is. (2) The **two-tier hook model**:
  in-process trusted lifecycle hooks vs. filesystem-installed hooks with a *different
  trust level*. leet sharpens this into the trust law: an in-process hook authored by
  the same weights as the agent is **co-resident** and closes no loop (docs/333 §5,
  the locality trap); a hook whose verdict is a kernel syscall reading git is
  grounded. **Locality is a first-class trust coordinate**, tracked, not assumed.
- **Isolation is a swappable backend, not a religion.** Worktree (cheap, local,
  shared dep env), container (Sculptor-style, isolated deps), or cloud microVM
  (Devin/Codex-style, full OS) — leet treats the isolation layer as a driver behind
  one `Workspace` seam (the OpenHands `LocalWorkspace`↔`DockerWorkspace` swap, done
  right). The kernel's verdicts are identical across all three, because they read git
  + the WAL, not the sandbox.

---

## 3. The architecture — a control loop with the agent as the plant inside it

The inversion of docs/333 §4.2, made concrete. **The loop is not the thing the
verifier observes; the verifier is the thing the loop is built around.**

```
                         ┌──────────────────────────────────────────────┐
                         │                 leet conductor                │
                         │        (the controller — docs/98 driver)      │
                         └──────────────────────────────────────────────┘
                                            │
        ┌──────────────┬────────────────────┼────────────────────┬──────────────┐
        ▼              ▼                     ▼                     ▼              ▼
   PICK (picker)   ADMIT (arbitrate)   DISPATCH (Workspace)   STEER (verdicts)   BANK (verify)
   enumerate→      lease the tree      worktree | container   liveness /         residual =
   pickable→       BEFORE the write,   | microVM driver,      productivity /     declared −
   cooldown→       WAL write-back      run_id-keyed run-dir   completion         VERIFIED
   pick_priority   (docs/98 §3)        + intent ledger        between steps      (commit_audit
                                                              (docs/333 §3)       at the bank)
        │              │                     │                     │              │
        └──────────────┴─────── every edge passes through a kernel verdict ───────┴──────────┘
                                            │
                              ┌─────────────┴─────────────┐
                              │   the embedded DOS kernel   │
                              │  pure classify(evidence,…)  │
                              └─────────────────────────────┘
```

### 3.1 The loop, step by step (and why each step is pre-effect)

1. **PICK.** The picker substrate produces the next fresh unit (never-attempted first,
   then LRU among attempted — `pick_priority`), gated by `pickable` (HELD units
   surface their typed `HoldReason`) and `cooldown` (the cross-run memory that breaks
   the re-pick storm). *Output: a unit + its declared extent.*

2. **DECLARE.** The unit's **declared extent is written to the intent ledger before
   step one** — into a distrusted `run_id`-keyed `intent.jsonl`. This is the
   load-bearing move of docs/333 §4.2: the plan is *the committed predicate the work
   is steered toward*, recorded **before the agent can game the check**. A loop not
   built to record declared-extent up front has nothing to subtract verified-progress
   from, so its only stop condition is budget. leet records it first.

3. **ADMIT.** `dos lease-lane acquire` runs the **pure** `arbitrate` against the live
   leases folded from the WAL, and on grant appends an ACQUIRE record under a mutex
   (docs/98 §3). Two agents may run **iff** their trees are disjoint beyond the
   threshold; a colliding write is **refused at contention**, not detected after.
   `overlap_policy.admissible_under_floor` guarantees a swappable scorer can only
   refuse-*more* — a buggy or hostile policy degrades to the prefix floor, never
   admits a collision. *This is the step the entire field skips.*

4. **DISPATCH.** The unit launches into an isolated `Workspace` (the swappable
   isolation driver), in its own run-dir. The agent works. It narrates freely —
   narration is read but **demoted at the door to a hint that must clear a
   non-forgeable checkpoint** (docs/333 §4.2).

5. **STEER — the part no bolt-on can do.** *Between* steps, not at the end, the
   conductor reads the kernel's verdicts as the **feedback term of the controller**
   (docs/333 §1, §3):
   - `liveness` — ADVANCING / SPINNING / STALLED from the git/journal delta. A
     SPINNING wave is surfaced, not awaited to a partial barrier.
   - `productivity` / `efficiency` — is per-step work fading? is a runaway agent
     burning 10× its work in tokens? Surface it before it bankrupts the run.
   - `completion` — `CONVERGING` (residual shrinking, keep steering) vs `THRASHING`
     (residual oscillates, no fixpoint — **stop steering, surface a decision**). A
     controller that corrects a thrashing plant forever is itself a failure mode
     (docs/333 §3.3).
   - `verify-result` at every fan-out fold — partition any subagent whose terminal is
     a harness-authored `<synthetic>` death into a DEAD bucket, **count it in the
     denominator, refuse to fold it** (docs/197 §7). The 32% silent-death hole closes.

   The verdict is **not a grade — it is an error vector with a confidence grade**:
   `INCOMPLETE` carries the *residual* (re-dispatch the unfinished set, not a fresh
   pass); `SCOPE_CREEP` names *which file the diff escaped into*; a refusal is a
   *typed cause*; `source=` carries the forgeability of the reading so the controller
   knows the *confidence* of each correction (docs/333 §3).

6. **BANK.** The unit ships only when `verify` reads the commit from git ancestry and
   `commit_audit` confirms the subject matches its own diff. The agent's "✅ done" is
   `AGENT_AUTHORED` — the forgeable floor; it can never, by itself, move the verdict
   to belief (docs/197). For non-git effects, `effect_witness` + `believe_under_floor`
   demand an independently-authored read-back. **`TaskCompleted` is refused until the
   witness corroborates** — the `dos-goal-gate` shape, productized as the *default*
   loop.

7. **STOP.** The loop terminates on **residual-empty-against-ground-truth**, not on
   budget (docs/333 §4.3). When the controller has gone blind (`ABSTAIN` / `source=none`)
   or stopped converging (`THRASHING`), it **takes its hands off the wheel and surfaces
   a decision to a human** — the actuation boundary (docs/99), the conservative
   default that routes the irreversible turn to a person.

### 3.2 The completion certificate — the user-visible artifact nobody ships

Every banked unit emits a **completion certificate**: `{claim, witness, source,
verdict}`. "Are we done?" stops being a vibe and becomes a verdict with a **source
field** — `registry | grep | none` — so a thin "I think it's done" can never
masquerade as a strong "git proves it shipped." The most expensive failure in
agentic coding — the confident false "done" you discover three turns later — is
killed by construction.

---

## 4. What makes leet a *fork*, not a better-tuned competitor

The three things a controller needs are **architecture-time decisions** — you either
threaded them through from the first type or you cannot retrofit them (docs/333 §4.3):

| Decision | Bolt-on (every 2026 competitor) | leet (verification-first) |
|---|---|---|
| **Ground-truth channel** | scraped from the agent's narration (the only thing its loop exposes) | a first-class input — git ancestry, the diff footprint, the OS exit code, the lease WAL — read directly, narration demoted at the door |
| **Work extent** | no notion of it → stop condition can only be *budget* | declared into the intent ledger before step one → stop is *residual-empty* |
| **Admission** | post-effect seams only (tool-return is the write it observes) | a **pre-effect** lease gate at the write chokepoint, before prevention is impossible |
| **Verdict shape** | a bit (`pass`/`fail`) at the end | an error vector with a confidence grade, between steps |
| **Native failure** | *silent compounding* (`pⁿ` error rides forward unchecked) | a *surfaced decision* (the controller knows when it's blind or thrashing) |

> *Bolt-on:* an agent loop, with a verifier reading the narration it happens to
> expose. *Foundation:* a control loop, with the agent as the plant inside it. **The
> two are not the same machine tuned differently — they are open-loop and closed-loop,
> and on a long horizon that is the only distinction that survives** (docs/333 §4.3).

---

## 5. The honest limits — what leet does *not* buy (the docs/333 §5 discipline, kept)

A design note that only stated the thesis would itself be the self-report leet exists
to refuse. The holes, named:

1. **Conformance, never correctness.** The controller steers the agent onto its
   *declared course*; whether the course was *worth steering* is a judge's or a
   human's call. Rice's theorem forecloses a mechanical "is this *good*?" oracle. So
   the **plan being a real pre-commitment is load-bearing, not bureaucratic** — a
   sloppy declared extent steers precisely toward the wrong place.

2. **Tree-disjointness is necessary, not sufficient.** Two agents editing disjoint
   files can still break each other through a shared interface (a signature one
   changes that the other calls). The lease is a *file-tree* lock, not a *semantic*
   one. The honest leet ships a second adjudication layer (interface/contract
   witnessing) **or states the limit openly** rather than implying a guarantee it
   doesn't have. (docs/330's joint-merge floor — re-witness the combined tree — is the
   research direction here.)

3. **The cheap lie is priced up, not abolished.** A `--allow-empty` commit on the
   right SHA still satisfies the forgeable grep-subject rung; only the file-path rung
   is non-forgeable. Verification raises the forgery cost from "a sentence" to "a
   reachable artifact of the right shape" — strictly stronger, hardenable
   rung-by-rung, but the sensor has a noise floor. The honest move is to **grade the
   reading (`source=`), not pretend it's clean.**

4. **leet decides; it does not enact (PDP, no PEP).** The kernel computes the heading
   honestly; *acting* on it — stopping the run, re-dispatching, killing the spinner —
   is the conductor's, and a wrong auto-correction is contained by routing the
   irreversible turn to a human. "Verification steers" is precise: it *computes* the
   heading; the controller still has to be wired to act on it, and that wiring is
   leet's responsibility and risk. The arbiter's guarantee covers **declared** regions
   only — nothing in the kernel confines a worker's *actual* writes; that confinement
   is the isolation backend's job (worktree/container/microVM), which is why isolation
   stays a real layer, not a formality.

5. **The co-resident verifier trap.** If the signal that corrects the agent is
   generated by the *same weights on the same box*, the loop is closed back onto the
   plant and the steering law is violated silently. leet makes **locality a tracked
   trust coordinate** — a foundation-built harness can, where a bolt-on inherits
   whatever box the agent runs on.

6. **Witness coverage is a strict subset.** Git-effect deliverables (~20% of a typical
   fan-out's subagents even touch `git commit`); pure-text research workers produce no
   git/WAL spine, so `liveness` and the *strong* form of `completion` read
   ADVANCING-then-STALLED with no discrimination, and `resume` is `UNRESUMABLE` over an
   empty ledger. leet's answer is the same as the whole DOS thesis: **be honest where
   you cannot witness** (`ABSTAIN`, routed to a human) — a sensor that fabricates a
   reading when blind is worse than no sensor (docs/333 §3.4).

These limits do not weaken the design; they **locate** it. leet is the controller for
exactly the cell where a long horizon turns a small per-step error into a silent
catastrophe and reading the plant's own narration closes no loop — and it concedes
the rest out loud.

---

## 6. What I'd build first (the wedge)

Mapped onto the products-brainstorm portfolio, leet **is** products #1 + #2 fused —
"an adjudicated harness that scales to a fleet" — the most defensible "Claude Code
2.0" pitch on the table because the distinguishing claim is one no competitor can copy
without rebuilding their trust model from scratch.

**The shippable wedge, in order:**

1. **The single-agent adjudicated loop (DECLARE → STEER → BANK).** Shippable *today*
   on the hooks that already exist in this repo: `dos hook stop` refused until `verify`
   or an `effect_witness` read-back corroborates the claimed effect (`dos-goal-gate`),
   plus `verify-result` at the fold and the completion certificate per turn. This
   needs **no new kernel code** — it is a conductor over shipped verdicts.

2. **The fleet admission layer (PICK → ADMIT → DISPATCH).** `dos lease-lane`
   write-back before every write (the one verb that recovers cross-process
   collision-prevention, docs/98 §3), the picker substrate for fresh-unit ordering,
   the supervisor as PID-1. This is where leet leaves the pack: a fleet that grows
   past the 3–5-agent coordination wall **because the admission decision is real**, not
   partition-and-hope.

3. **The data exhaust as a moat (Provenance, brainstorm #3).** Every leet trajectory
   is `attempt → witness adjudication → outcome label` with a **non-distillable** label
   (`reward` — a belief bit set only by bytes the agent didn't author). As models get
   better at gaming their own metrics, that property *appreciates with capability
   instead of eroding* — the deepest moat, monetized into the one market (RL/training)
   that structurally values it, needing no two-sided marketplace to bootstrap.

The sequencing respects the one constraint that recurs in every thread — **witness
coverage**: build in deterministic-witness domains first (code, git-effects), and let
the softer domains arrive as `ABSTAIN`-honest later, where *"I can't witness this, and
I'll say so"* is itself the feature.

---

## 7. The name

**leet** — `git` is to source control what leet is to agent fleets: the boring,
deterministic substrate everything else settles against. Lowercase, like `git`,
`make`, `dos`. The thesis it carries in four words:

> **TCP/IP made unreliable *links* carry reliable data. leet makes unreliable
> *actors* produce trustable effects** — by being the part of the fleet that does not
> believe the agents, wired in from the first type as the controller, not bolted on
> as a grader.

---

## See also

- [`333_verification-as-steering-and-the-verification-first-harness.md`](333_verification-as-steering-and-the-verification-first-harness.md)
  — the control-theory frame and the foundation-vs-bolt-on fork; leet *is* the §4.2
  machine.
- [`98_the-orchestrator-is-a-driver.md`](98_the-orchestrator-is-a-driver.md) — the
  conductor-is-a-driver thesis + the measured collision-prevention collapse; leet is
  one driver of the kernel seam.
- [`197_how-dos-is-directly-useful-to-ultracode.md`](197_how-dos-is-directly-useful-to-ultracode.md)
  — the fold-site trust gap + `verify-result`; leet's STEER step closes it by
  construction.
- [`140_the-userland-app-adjudicates-dispatch-not-truth.md`](140_the-userland-app-adjudicates-dispatch-not-truth.md)
  — the Dispatch/job-dir half + the dispatch-vs-truth adoption boundary leet crosses
  by design.
- [`116_the-durable-commons-and-the-constrained-a2a-problem.md`](116_the-durable-commons-and-the-constrained-a2a-problem.md)
  / [`120_the-status-digest-a-folded-fact-for-a-fleet.md`](120_the-status-digest-a-folded-fact-for-a-fleet.md)
  — the run-dir's three durable surfaces + the fail-closed status digest.
- [`207_dispatch-workflow-extraction-and-the-pickable-substrate-completion.md`](207_dispatch-workflow-extraction-and-the-pickable-substrate-completion.md)
  — the picker substrate (enumerate → pickable → cooldown → pick_priority → reconcile).
- [`products-brainstorm.md`](products-brainstorm.md) — leet = products #1 + #2 fused,
  with #3 (Provenance) as the data moat.
