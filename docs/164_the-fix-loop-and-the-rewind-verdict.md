# docs/164 — The FIX loop and the rewind verdict

> **DETECT-not-FIX is a *current* boundary, not a law of the substrate. This doc
> draws the principled path across it — without the kernel ever becoming a
> contestant it was built to referee.**

Status: **design** (mechanism plan, not a build). The lowest two rungs (F0/F1)
are mostly *assembly* over primitives already on disk; F3 is the prize and needs
the docs/126 PEP. Nothing here proposes the kernel author content it then
believes — the one move the live data already refuted.

---

## 0. The boundary, stated honestly first

DOS today is a DETECT substrate: `verify`/`liveness`/`refuse`/`arbitrate` report,
they do not act (a sound PDP with no PEP, docs/114). The single time the kernel
crossed into authoring a *correction* — the docs/144 intervention ladder's
`BLOCK` + `synthetic_corrective_result` — the **live 4-arm A/B measured it
net-negative**: on the EnterpriseOps-Gym integrity slice (gemini-2.5-flash, 80
tasks/arm) `BLOCK` scored **+0.0pp — dead on the do-nothing baseline, the worst
intervening arm — because it broke ~6× more downstream steps than it fixed**
(`WARN` +6.2pp won; `mattered_join.py`: WARN 14-help/2-hurt = net +12, BLOCK
7-help/**13-hurt** = net −6 flips). A synthetic substitution *is* a real
plan-disruption. (These are the *live* integrity-slice figures from docs/144 /
`benchmark/enterpriseops/RESULTS.md`; an earlier draft of this doc quoted the
simulator's `+0.4`/`11-hurt` numbers — a different quantity. Corrected here.)

That result is not a defect to patch. **It is the load-bearing constraint of this
whole doc.** It tells us exactly where the line is: the instant DOS authors a
correction and feeds it into the agent's stream as if true, the referee has
become a player, and it corrupts the thing it was protecting. So "use DOS for
FIX" can never mean "DOS writes the patch." It must mean something narrower,
grounded, and durable.

**Magnitude caveat (carry it everywhere):** none of this makes a model smarter.
The FIX loop raises the *reliability* of extracting a correct artifact from a
flawed run. It is worth a lot at horizon × fanout and ~nothing on a single short
task with a capable model — the same regime-dependence as every DOS verdict
(value → 0 at N=1, docs/136).

---

## 1. The one rule that sorts the space

> **DOS may FIX only by replaying or constraining un-forgeable bytes it did not
> author. The instant a fix requires *generating* the correction, DOS hands it to
> a JUDGE (model) or HUMAN and *gates* the result at the write — it never
> author-and-believes.**

This is not a new axiom. It is the existing forgeability ladder
(`evidence.believe_under_floor`, byte-author ≠ judged agent, docs/138/141)
**re-aimed from the input side (what claim do I believe?) to the output side
(what correction may I author?)**. The same invariant — the kernel never trusts
bytes the judged agent could have forged — governs both. A correction the kernel
*generates* is, by definition, bytes the system authored about its own success:
the forgeable rung. So it cannot be believed; it can only be *gated*.

---

## 2. The FIX ladder (F0–F3)

Four rungs, lowest trust-cost to highest. The ordering is by **who authors the
fix bytes**, which is the only thing that matters under §1.

| Rung | What DOS does | Who authors the fix bytes | Trust cost | Status on disk |
|---|---|---|---|---|
| **F0 Re-surface** | Hand the agent back its *env's own error bytes* + the clearable wall (tool + error) | the environment (un-forged) | ~zero — it is evidence, not a claim | **SHIPPED** — `terminal_error_gate` (`benchmark/enterpriseops/dos_react.py:231`, docs/163) |
| **F1 Replay / rewind-and-retry** | Re-dispatch the `resume` **residual** from the non-forgeable re-entry SHA; re-run a deterministic step | the original plan (un-forged) | low — no new content minted | substrate SHIPPED (`resume.resume_plan`, `intent_ledger.OP_SUSPEND`); the re-dispatch *loop* is unbuilt |
| **F1.5 Rewind-conversation (backjump + no-good)** | Roll the *transcript* back to a checkpoint turn, dropping the turns that led into the failed branch; re-enter with a **no-good note** = the kernel's typed verdict + the env's own error bytes | env + kernel **verdict** (un-forged) — **never a generated critique** | low — it *removes* forged context, it does not add content | substrate SHIPPED (the same `OP_SUSPEND` anchor, re-aimed at `(turn_index, transcript_digest)`; `convergence.THRASHING` caps it); the conversation-axis loop is unbuilt |
| **F2 Constrain-and-reissue** | Refuse the bad effect, hand back a *typed constraint* (tool + error + lane), **never a solution** | kernel — **structure only, never content** | medium — **this is exactly where BLOCK went negative** | SHIPPED but **measured harmful** as substitution → the lesson is *constrain, don't substitute* |
| **F3 Adjudicated correction** | A JUDGE (model) or HUMAN proposes the patch; DOS **gates it at the write** (runs the verdicts before it lands) | model / human (forgeable) → rides ORACLE→JUDGE→HUMAN under the floor | high — needs the **PEP** | DESIGNED, unbuilt (docs/126 apply-gate) |

### F0 — Re-surface (shipped)

`terminal_error_gate(tool_results)` already does the safe minimum: on a
closing-window structured env error it re-surfaces **the env's own error excerpt
+ the failing tool name** as a `HumanMessage`, one-shot, opt-in
(`DOS_TERMINAL_ERROR`). The discipline is pinned by a test where the agent says
"All done!" but the nudge carries *only the Traceback bytes* — **never
`response.content`** (`dos_react.py:201`, the §5a byte-inequality line). F0 is FIX
at trust-cost ~zero because the correction is the un-forged environment talking,
not the kernel inventing.

The recovery counterfactual (docs/162) proves F0 has a real target: **71/76
`terminal_error` catches (93%) hit a wall that is demonstrably *clearable***
(`local-python-execute` Tracebacks dominate, 92% recoverable elsewhere in the
corpus). So a catch is not "this failed" — it is *"this failed at a clearable
wall; here is the tool and the error,"* which is precisely what a re-surface can
act on. (Honest bound: recoverable-*somewhere* is an upper bound on per-catch
fixability, not "71 fixes available.")

### F1 — Replay / rewind-and-retry (substrate shipped; loop unbuilt)

`resume.resume_plan(LedgerState, AncestryFacts, policy)` already returns a
**residual** (declared steps minus `STEP_VERIFIED` steps, with any
claimed-but-unverified step staying *in* the residual — fail-closed) and a
**non-forgeable re-entry SHA** (minted over git ancestry, never the dead run's
`STEP_CLAIMED` self-report). F1 is the loop that consumes them: re-dispatch the
residual from the re-entry SHA. No content is minted — DOS replays the *plan's*
declared work, not its own invention. This is the rung where **rewind** lives
(§3).

### F1.5 — Rewind-conversation (the second rewind axis; substrate shipped, loop unbuilt)

F1 rewinds the **git state**. There is a second thing a failed attempt can leave
corrupted, and F1 leaves it untouched: **the conversation itself.** When a fix
attempt fails, the turns that walked into the dead end *stay in the agent's
context* — and the agent keeps reasoning from a transcript that still contains its
own abandoned approach.

**A caution on the evidence first (don't overclaim what the live data shows).**
The docs/144 `BLOCK` arm landed dead on the do-nothing baseline (+0.0pp,
7-help/13-hurt = net −6 flips), and it is tempting to read that as proof of the
accretion problem. It is *not* — and conflating the two would be the exact
self-serving evidence this kernel exists to catch. BLOCK lost because it
**substituted a fabricated tool-result on the same turn**
(`dos_react.py:625-652`, "turn PRESERVED"; `RESULTS.md:264`: "substituting a
synthetic tool-result derails the steps that depended on it"). That is
*substitution* harm — F2's "constrain, don't substitute" territory — measured on
a single-turn intervention, **not** a measurement of dead-end-turn accretion
across a multi-attempt loop. So the BLOCK result motivates F2; it does **not**
prove F1.5. The honest case for conversation-rewind rests on *orthogonality*, not
on that datum: it is a **distinct axis** F1's git-rewind cannot reach (state can
be clean while the trace is poisoned), and the accretion failure mode it targets —
a loop re-reading its own abandoned approach across retries — is **plausible but
as yet UNMEASURED**; the P4 fix-eval (§5) is what would ground it.

What F1.5 *does* contribute, independent of that caveat: **the honest version of
"make the bad turn stop hurting" is not to paper over it with a fabricated result
— it is to excise the bad turns.** That is conversation-rewind: subtract the
dead-end context rather than append a correction to it.

**The formal term is backtracking — specifically *backjumping with no-good
learning*, not chronological backtracking.** The distinction is the whole design.
Chronological backtracking is dumb: it rolls the transcript back one turn and
re-explores, which on a deterministic-ish agent walks *straight back into the same
dead end* — an infinite loop. Backjumping with no-good learning rolls back to the
*decision* that caused the failure and **records why the branch failed so it is
never retried**. DOS already ships both halves of the no-good machinery:

- **The rewind anchor** is the same `intent_ledger.OP_SUSPEND` primitive F1 uses
  (`intent_ledger.py:84`), re-aimed: instead of (or alongside) a
  `suspend_resume_sha` (`intent_ledger.py:287`), the SUSPEND records a
  `(turn_index, transcript_digest)` checkpoint. The transcript digest is the
  non-forgeable anchor — the kernel rewinds to a checkpoint *it* stamped, never to
  a turn the agent claims it was at (the §6 "rewind is to a minted SHA" litmus,
  lifted to the conversation axis).
- **The no-good** is `completion.convergence` → **`THRASHING`**
  (`completion.py:314`): "|residual| failed to decrease for `max_nonconverging`
  rounds — surface, don't burn budget." THRASHING *is* the "you have backjumped
  into the same hole — stop" verdict. Without it, conversation-rewind is just
  chronological backtracking and it loops. With it, the loop is capped on ground
  truth, exactly as the git-rewind loop is (§3).

**The note is the safety-critical part, and it is byte-clean by construction.**
On rewind, the agent re-enters with a *no-good annotation*, and that annotation may
carry **only un-forged bytes**: (a) the kernel's own typed verdict tokens
(`DIVERGED`; `verify = NOT_SHIPPED at <sha>`; `tool_stream = REPEATING ×4 at turn
N`) — a refusal is the one thing the kernel may author (docs/82) — **plus** (b) the
*environment's* own error excerpt, the F0 re-surface bytes (`dos_react.py:201`, the
Traceback-not-`response.content` line). Both authors are not the judged agent, so
both cross the floor (`evidence.believe_under_floor`, docs/138/141). What the note
may **never** carry is a *generated* explanation of why the branch failed — "you
should have used a try/except" is a fabricated correction, the forgeable rung, and
it belongs to F3 behind the gate. **The no-good carries the verdict and the wall,
never the advice.** That single line is what keeps F1.5 below the
author-and-believe boundary that sank `BLOCK`.

Why F1.5 sits *below* F2 in trust cost: it authors nothing. F2 hands back a
kernel-authored *constraint* (structure — legitimate, but it is the kernel
speaking about what to do next). F1.5 only *removes* turns and re-attaches bytes
two non-agent authors already wrote. Subtracting forged context is structurally
safer than adding even well-formed structure — that ordering is an argument from
*who authors the bytes*, the §1 rule, and it stands on its own. (It is NOT
licensed by the live BLOCK datum: BLOCK lost by *substituting* a fabricated
result, which is the case *for* F2-as-constraint over F2-as-substitution — it says
nothing about F1.5 vs F2. The trust-cost ordering here is a structural claim, not
a measured one.)

### F2 — Constrain-and-reissue (shipped, but the trap is named)

`choose_intervention` + `synthetic_corrective_result` exist
(`intervention.py:604/669`). The live data says: a kernel-authored *solution*
substituted into the stream is net-harmful. The surviving F2 move is therefore
**constrain, don't substitute** — refuse the bad effect and hand back a *typed
constraint* ("retry tool X, which hit error E, within lane L"), which is
*structure the kernel may author* (a refusal is the kernel's own legitimate
speech, docs/82), not *content* (a fabricated tool result, which is a claim about
the world the kernel has no standing to make). The `dos_blocked: True`
anti-laundering stamp (`intervention.py:706`) is the existing guard that a
synthetic payload can't masquerade as a real env result; F2-as-constraint keeps
that guard and drops the fabricated *answer*.

### F3 — Adjudicated correction (the prize, unbuilt)

The frontier is *not* a fix-generator — every model already generates fixes. It
is the **gate that verifies a generated fix against ground truth before it
lands**: the docs/126 apply-gate PEP. A model (a `dos.judges` driver, e.g.
`llm_judge`) or a human proposes the patch; DOS runs the existing verdicts *at
the write moment* (diff-escape check, disjointness floor, `verify` against
ancestry) and the patch lands **only if it passes**. The fix is forgeable, so it
rides ORACLE→JUDGE→HUMAN under the deterministic floor — advisory-proposed,
floor-gated, never author-and-believed. This is the single most valuable
FIX-direction build because **it is what makes a generated correction safe
without DOS authoring it.** It is also the "give DOS a PEP" 10× move
(docs/114/security-10x-100x).

---

## 3. FIX is a loop — and rewind is what makes the loop safe

A single fix attempt is a coin flip. The value is in the **loop**, and the loop
is a DOS control loop built from verbs already on disk:

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  CHECKPOINT  →  attempt FIX  →  VERIFY  →  decide                 │
  │   (SUSPEND)      (F0–F3)        (oracle)   (loop_decide +         │
  │       ↑                            │         convergence)         │
  │       └────── REWIND on regression ┘   (DIVERGED / THRASHING)     │
  └──────────────────────────────────────────────────────────────────┘
```

Each arrow is a shipped primitive:

- **CHECKPOINT** = `intent_ledger.OP_SUSPEND` + its recorded `suspend_resume_sha`
  (`intent_ledger.py:84/331/526`). Before a fix attempt, the ledger records a
  non-forgeable re-entry SHA. *This is the rewind anchor, and it already exists.*
- **attempt FIX** = whichever rung (F0 re-surface / F1 residual replay / F3 gated
  patch).
- **VERIFY** = `oracle.is_shipped` / `terminal_error_gate` / a fresh world-read
  (the docs/158 §6 live post-hoc re-read — the strongest grounding rung, a fresh
  THIRD_PARTY byte). The verify reads **ground truth, not the agent's "fixed it
  now."**
- **decide / loop** = `loop_decide.decide` + `completion.convergence`
  (`completion.py:365`): CONVERGING / **THRASHING** / STARVED. THRASHING =
  "|residual| failed to strictly decrease for `max_nonconverging` rounds — surface,
  don't burn budget" — the *built-in "stop flailing" verdict* the fix-loop needs.

### Why rewind is the deep part (not "source-correct once")

Without rewind, every failed fix attempt **accretes corruption**: attempt 2
builds on attempt 1's half-applied mess, and you can no longer distinguish a real
fix from compounding damage. The naïve fix-loop *diverges*.

DOS already ships the verdict that makes rewind principled: **`Resume.DIVERGED`**
(`resume.py:69`) — *"ground truth moved past the resume point in a way the
residual can't cleanly graft onto → REFUSE, raise a decision."* That is exactly
the rewind trigger. The safe fix-loop:

1. **SUSPEND** → mint re-entry SHA `S₀`.
2. Attempt fix → new HEAD `S₁`.
3. **VERIFY** against ground truth (never self-report).
4. **Pass + residual shrank** → mint `STEP_VERIFIED`, checkpoint forward,
   continue.
5. **Fail, or `resume_plan` → `DIVERGED`** (the fix made it worse — moved past
   where the residual grafts) → **REWIND to `S₀`** (`git reset` to the minted
   re-entry SHA; the residual is *unchanged*), then retry with a tighter F2
   constraint or escalate to JUDGE/HUMAN.
6. **`convergence` caps the loop**: THRASHING (churning, no new low) → stop and
   surface; STARVED (flat residual) → escalate; never burn the budget convincing
   itself it's close.

**The elegance: rewind is a `git reset` to a SHA the kernel minted on the
non-forgeable rung, and the residual is *invariant* across the rewind** — it is
`declared − verified`, and a rewound attempt verified nothing, so the residual is
byte-for-byte what it was before the attempt. So the loop can run
fix→verify→rewind→fix **without ever trusting the agent's account of whether the
last attempt helped**: git ancestry says whether state advanced, `DIVERGED` says
when to throw an attempt away, `convergence` says when to stop. *Same distrust
axiom — applied to the loop instead of the claim.*

### Two things get rewound, not one

The REWIND arrow above has **two axes**, and they compose. The git-state axis
(F1) rolls `HEAD` back to the minted SHA; the conversation axis (F1.5) rolls the
*transcript* back to the minted `(turn_index, transcript_digest)` checkpoint and
re-attaches the no-good note. They share one anchor (`OP_SUSPEND` records both),
one trigger (`DIVERGED` / THRASHING), and one invariant (the residual is
unchanged because a rewound attempt verified nothing). The reason to name them
separately: **a fix loop that rewinds git but not the conversation still
accretes** — the next attempt reasons from a transcript that remembers the dead
end. (This accretion mode is plausible but *unmeasured* — see the F1.5 caveat
above; it is NOT what the docs/144 BLOCK arm measured, which was single-turn
substitution harm.) Rewinding *both* is what makes the attempt genuinely fresh:
clean
tree, clean trace, plus a no-good that says "branch from turn N is forbidden, here
is the verdict and the wall." Backjumping with no-good learning, where the no-good
is two non-agent authors' bytes.

---

## 4. What DOS uniquely contributes to FIX (vs. "just let the agent retry")

An agent retries on its own. The three grounded things it *cannot* do — and DOS
adds — are:

1. **Attribution** — *which* wall, *which* tool, *which* claim was false. A blind
   retry doesn't know what to retry. DOS hands it the failing tool + the un-forged
   error (the docs/162 counterfactual proved the target real: 93% clearable walls).
2. **A non-forgeable re-entry point** — the fix resumes from *adjudicated*
   progress (`STEP_VERIFIED` over git ancestry), never the dead attempt's
   `STEP_CLAIMED` self-report. Without this, "rewind" is just trusting the agent
   about where it was.
3. **A loop-termination verdict grounded in ground truth** — `DIVERGED` (this
   attempt regressed) and THRASHING (the loop is flailing) come from git/residual,
   not from the agent saying "I think I'm close." This is what stops the fix-loop
   from running forever or convincing itself it succeeded.

DOS does not make the model a better patch-writer. It makes the *loop around the
patch-writer* honest, bounded, and rewindable.

---

## 5. Phases (smallest-trust-cost first)

- **P1 — F1 rewind-and-retry loop (assembly, no new verdict).** Wire
  SUSPEND→attempt→`oracle.is_shipped`→`resume_plan`→(continue | rewind-on-DIVERGED)
  →`convergence`-capped, as a *consumer-side* loop (the kernel stays advisory;
  the loop is the host building on the verbs, docs/82 line). Eval: does the loop
  recover a residual without accreting a DIVERGED attempt? The hard parts (the
  non-forgeable checkpoint, the divergence verdict, the thrash cap) are *already
  built* — this is integration + an eval harness.
- **P1.5 — F1.5 rewind-conversation (assembly over the same anchor).** Extend the
  `OP_SUSPEND` record with a `(turn_index, transcript_digest)` checkpoint; on
  `DIVERGED`/THRASHING, truncate the transcript back to it and re-enter with the
  no-good note (kernel verdict tokens + the F0 env excerpt). Consumer-side, like
  P1 — the kernel stays advisory; the host owns the transcript. Eval: does
  rewinding the *conversation* (not just git) cut the accreted-context regression
  the docs/144 `BLOCK` arm exhibited? This is the move the live result argues for
  (subtract forged context) versus the move it refuted (append a synthetic
  answer).
- **P2 — F2-as-constraint.** Replace any remaining "synthetic *answer*" path with
  "typed *constraint*"; keep the `dos_blocked` anti-laundering. Eval against the
  docs/144 mattered-join: does constrain-don't-substitute avoid BLOCK's net −6
  hurt-flips (its +0.0pp dead-on-baseline result)?
- **P3 — F3 apply-gate PEP (docs/126).** The prize: a model/human-authored fix
  gated at the write. This is its own plan (docs/126); the FIX-loop is its
  consumer. Until P3, FIX stays at F0/F1 — replay and re-surface only, no
  generated correction lands.
- **P4 — `dos fix-eval` (the per-axis instrument).** Net-task-delta of the loop
  (recovered-residual rate, false-rewind rate **on both axes** — a git rewind that
  threw away real progress, or a conversation rewind that discarded a turn the run
  actually needed — and thrash-cap firing rate) — the
  `intervention_eval`/`overlap_eval`/`judge_eval` friendliness instrument, so the
  loop is *measured* not asserted (the docs/159 lift+false-alarm scoreboard, never
  recall alone).

---

## 6. The litmus tests (so the boundary can't silently drift)

- **No author-and-believe.** No FIX rung may inject kernel-*generated* content
  into the agent's stream as a true result. F0 carries env bytes; F1 replays the
  plan; F2 carries a constraint (structure); F3 gates a model/human patch behind
  the floor. A grep for a synthetic *answer* (not a constraint, not env bytes)
  fed back as believed should find nothing outside the gated F3 path. The
  `terminal_error_gate` test (agent says "All done!", nudge carries only the
  Traceback) is the F0 instance of this litmus.
- **Rewind is to a minted anchor — on both axes.** The git-rewind target is
  always a re-entry SHA on the non-forgeable rung (`STEP_VERIFIED` /
  `suspend_resume_sha`), never a HEAD the agent claimed. The conversation-rewind
  target (F1.5) is always a `(turn_index, transcript_digest)` checkpoint the
  kernel stamped at `OP_SUSPEND`, never a turn the agent claims it was at. A
  rewind to a `STEP_CLAIMED` SHA — or to an un-stamped turn — is the bug.
- **The no-good note carries verdict + env bytes, never a generated critique.**
  F1.5's re-entry annotation may contain only the kernel's own typed verdict
  tokens and the environment's own error excerpt (the F0 bytes). A grep of a
  rewind note for *generated* prose explaining the failure (anything authored by
  the model, not the kernel-verdict vocabulary and not an env excerpt) should find
  nothing — that path is F3, gated. This is the F1.5 instance of the
  no-author-and-believe litmus.
- **The loop terminates on ground truth.** Stop conditions are `DIVERGED` /
  THRASHING / STARVED / COMPLETE — all computed from git ancestry + residual,
  never from a self-reported "I'm done / I'm close."
- **FIX stays advisory until the PEP.** Until docs/126 lands, no generated
  correction *lands* — the loop proposes (residual re-dispatch, re-surface) and a
  human/host applies. F3 is the only rung that *enacts* a generated fix, and only
  through the gate.

---

## 7. Provenance / cross-refs

- docs/144 — intervention ladder; the **live BLOCK = +0.0pp (worst arm), 7-help /
  13-hurt = net −6 flips** result that is this doc's load-bearing constraint.
- docs/162 — the recovery knob + the **71/76 clearable-wall** counterfactual (F0's
  target).
- docs/163 — the shipped `terminal_error → WARN` gate (F0).
- docs/107 — `resume` / intent-ledger (the residual + re-entry SHA + `DIVERGED` +
  `OP_SUSPEND` — the rewind substrate, on **both** the git axis and the F1.5
  conversation axis: the same anchor re-aimed at a `(turn_index,
  transcript_digest)` checkpoint).
- docs/117 — `completion.convergence` (THRASHING/STARVED — the loop cap).
- docs/126 — the apply-gate PEP (F3 — the prize).
- docs/114 / security-10x-100x — PDP-with-no-PEP; "give DOS a PEP" as the 10× move.
- docs/136 — the four closed loops; value monotone in horizon × fanout, → 0 at N=1.
