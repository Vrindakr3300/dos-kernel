# 149 — The real failure distribution sorts the priorities (measured, not assumed)

> **⚠ Update (docs/150): this doc's strong claim is CRACKED.** The §3 conclusion below — "DOS
> structurally cannot own premature completion because both completion inputs are forgeable" — was
> **over-generalized**: narration is forgeable toward *"I'm done"* but NOT toward *"I still need to
> X"* (an admission against interest, the one self-report DOS already believes). docs/150 built +
> measured a byte-clean detector (`dangling_intent`) of the **narrating** premature stopper: 13 %
> recall, 0 % false-fire on the recorded corpus. This doc's *empirical core survives* (the **silent**
> stopper dominates the 92 % and stays out of reach), but "DOS owns none of it" is refuted. Read §3
> as "the obvious `completion` design fails," not "the space is empty."
>
> **Status:** measured finding (2026-06-04). Not a build plan — an *empirical re-prioritization*.
> The operator's instruction was the right one: **don't manufacture a fake failure (injected
> loops/mints) to make a DOS mechanism look useful — measure what real models actually get wrong,
> and sort by what DOS can genuinely help with.** This doc does exactly that, on the recorded real
> `gemini-3-flash` trajectories (`live_results/`, the gym's own `verification_results`), with zero
> new model calls, DB mutation, or Docker — pure replay of recorded ground truth.
>
> **One line.** **~92 % of real failed checks are "an action never happened" (the model stopped
> before completing the required steps)** — Premature Completion, the *one* failure mode DOS
> structurally cannot own (it is the scope/planning problem, forfeit by doctrine). The failures
> DOS *can* own cleanly (minted IDs → `arg_provenance`, byte-identical loops → `tool_stream`) are
> the ones this real model **barely exhibits** (measured `p_stuck = 0`, ~0 real mints). The honest
> conclusion: on a *capable* model, DOS's loop-level distrust verdicts are near-null, because a
> capable model's failures are *upstream of* the execution substrate DOS guards.

---

## 0. The method — let recorded ground truth, not a simulator, set the priorities

Every recorded trajectory carries `verification_results` — the gym's **hidden-SQL verifier
outcomes per check** (the real, non-forgeable final-state oracle), plus `verification_summary`
and `overall_success`. That is recorded ground truth about what the real model got wrong. So the
priority question — *which real failure should DOS attack?* — is answerable by **mining the
recorded failures**, not by assuming a failure and simulating a fix.

Measured over the recorded corpus (`live_results/**`), via the committed, re-runnable
`benchmark/enterpriseops/failure_distribution.py`:

- **40 scored runs · 39 failed overall · 155 checks · 107 failed → a 69 % per-check failure rate.**
- Failed runs made a **median 5 tool calls** (range 0–19; six made *zero*) against tasks that
  average ~9 required steps — i.e. the model is stopping at **roughly half** the required work.

---

## 1. The real failed-check distribution (by failure shape)

Each failed check classified by the *shape* of its SQL assertion (expected vs actual):

| Rank | Failure shape | % of failed checks | The named paper failure mode |
|---|---|---|---|
| **1** | **MISSING ROW** — `expected ≥1, got 0`: the action **never happened** | **91.6 %** | **Premature Completion Hallucination** |
| 2 | **FK / RELATION** — a link missing or wrong | 5.6 % | (partial: Incorrect ID Resolution) |
| 3 | **EXTRA ROWS** — a side-effect that should not exist | 2.8 % | (over-action / missing refusal) |

> **The dominant failure, by a 5× margin, is the model doing too LITTLE — it declares done and
> stops with the required rows never written.** The tool-call histogram confirms it: this is not
> "did the wrong thing," it is "stopped before doing the thing." That is Premature Completion, the
> paper's named mode (§4.4), and the paper's own headline: success decays with horizon because the
> model gives up early on long tasks.

---

## 2. Sorting the DOS mechanisms by REAL impact (the honest re-rank)

Map each failure to whether DOS has a **byte-clean** mechanism (one that survives the §5a
mirror-verifier trap), and weight by the *measured* frequency:

| DOS mechanism | Targets | Real frequency on this model | Honest impact |
|---|---|---|---|
| **`completion` (docs/117)** | premature stop (the ~92 %) | **dominant** | **High target — but the gate is a MIRROR-VERIFIER here (see §3). DOS cannot own it cleanly.** |
| **`arg_provenance` (docs/143)** | minted IDs (subset of WRONG VALUE) | **~0** (model resolves its FKs) | Real but near-null on a capable model. Shipped. |
| **`tool_stream` (docs/145)** | byte-identical loops | **0** (measured `p_stuck = 0`) | Real but **absent** on this model. Shipped. |
| **`precursor_gate` (docs/147)** | acted-without-prereq / over-action (the ~3 %) | small | Real but rare; the cleanest of the survivors for *this* slice. |
| `intervention` (docs/144) | how hard to enforce ANY verdict | meta | Only matters once a verdict fires; ~0 fire here. |

**The uncomfortable, honest result:** the mechanisms DOS can own cleanly attack the **~8 % tail**
(wrong-value + over-action), and the **~92 % head** (premature completion) is the one DOS
**structurally cannot** own, because both inputs its verdict needs are forgeable on this benchmark
(§3). On a capable model, *the execution-substrate failures DOS guards are not where the model
fails.* The model fails *upstream*, at planning/scope — the +14–35 pp lever DOS forfeits by
doctrine (docs/143 §9).

---

## 3. Why `completion` is a mirror-verifier HERE (the §5a trap, restated on real data)

`completion.classify` computes `residual = declared − verified` (via `resume.resume_plan`). On
this benchmark **both halves are forgeable by the judged agent**:

- **`declared`** — the task's required-step set. The agent would have to declare it, *from
  agent-visible prose* — the `UNDERDECLARED` hole (docs/117 Gap-B). An agent that under-declares
  its own scope reports `residual = ∅` and "completes" early. Forgeable-in-its-favor.
- **`verified`** — there is **no env-authored per-step checkpoint** on this benchmark; the only
  "I finished step N" signal is the agent's own narration / its decision to stop calling tools.
  Agent-authored → forgeable.

So a `completion` gate here would mint `COMPLETE`/`INCOMPLETE` from a predicate the agent authored
— the exact mirror-verifier docs/143 §5a killed, and worse: a false "INCOMPLETE, continue" on a
task the model *correctly* finished early coaxes a **side-effecting write** that trips the
zero-side-effect checks (the benchmark's worst-scored axis, the −9 pp backfire). **The ~92 % head
is not a DOS-shaped target on this benchmark — it is the planning problem wearing a completion
costume.** Naming that honestly is the finding.

What *would* make it DOS-shaped is the missing ingredient docs/143 §5a already named: **an
env-authored checkpoint** (a read-probe whose *predicate* is not agent-authored). The gym does not
expose one to a fair agent, so the clean version is unbuildable here without crossing the
legitimacy line.

---

## 4. So what IS the real, honest next step?

Not "inject loops to make `tool_stream` measurable" (a fake failure). Not "wire `completion`" (a
mirror-verifier here). The measured distribution points three honest directions, in priority order:

1. **Report the null honestly and stop overclaiming the loop/mint axes.** On a capable model both
   are ~0; that is the docs/143 ceiling, now confirmed twice (mints ~0, loops 0). The mechanisms
   are *correct insurance* for a *cheap/failing* agent — which is a real deployment, just not this
   recorded one. Lead every claim with the measured frequency.

2. **The cleanest real DOS slice on this data is the ~3 % over-action tail → `precursor_gate`**
   (docs/147, the other agent's build): "did a mutating call fire without its mandated precursor?"
   is byte-clean (call-stream provenance, not a satisfaction predicate) and maps to the EXTRA-ROWS
   / zero-side-effect failures. Small, but *real and ownable*. This is where the next live A/B
   budget should go, not the stall reader.

3. **The ~92 % head needs an env-authored checkpoint to be DOS-shaped at all.** Absent one, it is
   out of scope by doctrine (it is planning). The only honest DOS contribution to it is
   *negative*: a `completion`-style gate must REFUSE to fire on a forgeable residual (the
   `UNDERDECLARED` floor) rather than coax a side-effecting continue — i.e. DOS's value on the
   dominant failure is **declining to make it worse**, not fixing it. That is a real, if humble,
   contribution, and it is the docs/99 advisory-floor doctrine applied to the completion gate.

---

## 5. The throughline (what this measurement teaches)

DOS distrusts the **execution substrate** — did this id resolve, did this call repeat, did the
mandated precursor fire. The recorded data says a *capable* model rarely fails there; it fails
**upstream**, at strategy and scope, which DOS forfeits by design. So:

> **The honest market for DOS's loop-level distrust verdicts is the cheap/failing agent, not the
> capable one — and the recorded benchmark runs a capable one.** That is not a defect in the
> mechanisms; it is the measured boundary of where they apply. The discipline the operator
> enforced — *don't fake a failure to look useful, sort by real impact* — is what surfaced it. The
> mechanisms stay shipped as correct insurance; the claims get sorted by measured frequency; and
> the next real-data budget goes to the one clean ownable slice (`precursor_gate`, the ~3 % tail),
> not the axis with the prettiest simulator.

**Cross-refs:** the measured loop-rate null = `replay_stall.py` + docs/145 §7; the measured mint
null = `RESULTS.md` (docs/143); the §5a mirror-verifier trap this re-applies = docs/141 + docs/143
§5a; the completion verdict + its `UNDERDECLARED` forgeability hole = docs/117 + `src/dos/completion.py`;
the clean ownable slice = docs/147 (`precursor_gate`); the advisory-floor doctrine §4.3 leans on =
docs/99. The recorded ground truth = `live_results/**/verification_results`.
