# 145 — The loop-economics axis: a stall reader that moves success UP without minting

> **Status:** the kernel leaf + its eval + the operator surface are **SHIPPED** (2026-06-04);
> only the consumer wiring + the live experiment ladder (§6 R3/R4) remain. `src/dos/tool_stream.py`
> (`classify_stream` → ADVANCING/REPEATING/STALLED) + `src/dos/tool_stream_eval.py`
> (recovered-rate / false-resurface-rate) + the `dos tool-stream-eval` CLI verb + the
> `[tool_stream]` config seam (`SubstrateConfig.stream_policy` + a `dos doctor` row) + 44 tests
> (`test_tool_stream.py` 34 + `test_tool_stream_cli.py` 10) are built, green, and exported from
> `dos`. What remains: the `dos_react` consumer fold (accumulate the `(tool, args_digest,
> result_digest)` stream + attach the re-surface WARN) and the paired EnterpriseOps-Gym run (§6).
> Motivated by a structural gap docs/143/144 left open, surfaced by a multi-lens ideation sweep
> (5 generators → 19 candidate mechanisms → adversarial doctrine-refutation → synthesis, 2026-06-04).
>
> **One line.** docs/143's `arg_provenance` and docs/144's intervention ladder are both
> *prevent-down* mechanisms on the **Integrity** slice, and both **vanish on a strong model**
> (a model that reads-before-it-writes mints nothing → the detector catches nothing → zero
> gain). The next net-lift axis is the one neither doc built: **loop economics** — a cheap
> model on a long horizon *thrashes* (re-reads the same row, polls for eventual consistency,
> loops to a `max_iterations` timeout with the task half-done), and the paper's own headline
> is that success **decays monotonically with horizon** (~35 %@4 steps → <20 %@16). A
> **stall reader** that detects byte-identical repeated tool results and **re-surfaces the
> env-authored value the agent already holds** can convert a doomed re-read loop into a
> *finished* task on the **same budget** — the first DOS lever on this benchmark that moves
> success **UP** (adds a correct finishing step) rather than only preventing a wrong one, and
> the first whose value **does not depend on the model minting**.
>
> **Lineage.** docs/143 §5 finding 3 ("the liveness sensor must be rewired … this is unbuilt
> and load-bearing") is the call for this leaf. docs/143 §7 rank-2 ("`tool_loop`
> ProgressEvidence reader … survives as a cost instrument, not a truth claim") named it but
> scoped it to *cost only*; this plan argues the cost instrument has a **success** edge that
> §7 under-credited, **because freed budget lets a thrashing agent finish.** docs/144 is the
> actuation discipline this rides (the stall reader's intervention is a WARN/BLOCK on the
> same ladder). The byte-inequality axiom (docs/141) is what makes it honest. `churn`
> (`decide_coalesce`) is the consecutive-identical-run-length *pattern* lifted off git onto
> the tool stream. `liveness.classify` is the sibling this leaf mirrors (a PURE verdict,
> evidence gathered at the boundary).

---

## 0. The two facts that reframe the problem (verified in-tree, 2026-06-04)

The ideation sweep's most useful output was a **state-of-the-code correction** — two facts
that change what "build" means here, both checked against the source before this plan:

1. **The intervention ladder is already shipped and consumer-wired.** `src/dos/intervention.py`
   ships the full closed `OBSERVE < WARN < BLOCK < DEFER` vocabulary, `choose_intervention`,
   `assess_confidence` (HIGH/LOW/NONE), `synthetic_corrective_result` (the turn-preserving
   BLOCK payload, with the `dos_blocked` anti-laundering exclusion), the refuse-LESS-only
   `InterventionPolicy` (validated TWICE — at construction and against the ladder in hand),
   and `intervention_eval.py` + a `dos intervention-eval` CLI + three test files. And
   `benchmark/enterpriseops/dos_react.py` **consumes all four rungs** (the `DOS_INTERVENTION`
   env knob, `choose_intervention(verdict, policy)`, the BLOCK→`synthetic_corrective_result`
   branch, the `dos_blocked` corpus exclusion). So docs/144 Phases 1–2 are **done**; docs/144
   Phase 3 — the load-bearing *live A/B that flips the −9 pp positive* — is the one pending
   experiment, and it needs **no new code**, only a run.

2. **The tool-stream stall reader genuinely does not exist.** A grep for
   `tool_stream` / `repetition` / `result_digest` over `src/dos/*.py` returns nothing.
   `liveness.classify` is git/journal-keyed only; there is no reader over the *in-process
   tool-result stream*. This is the **one real greenfield kernel leaf** in the whole survivor
   set — and docs/143 finding 3 already flagged it load-bearing and unbuilt.

This reframes the deliverable: **the cheapest win is a run of already-built mechanism; the
one genuinely new mechanism is a single pure leaf on an axis neither prior doc built.**

---

## 1. Why the docs/143/144 baseline has a structural ceiling (the gap this fills)

State the ceiling honestly, because it is what this plan must clear:

- `arg_provenance` asks **"did the model MINT this id, or RESOLVE it?"** Its value is bounded
  by the **minting rate**. On the live `gemini-3-flash` run that rate was **zero** — the model
  reads its FK ids first (Integrity is, per the paper's Table 7, agents' *strongest* class) —
  so the detector correctly caught nothing and added nothing. The simulator's +11 pp lives
  only on a *cheap minting* agent; the gain **shrinks to 0 as the model improves at reading.**
- docs/144's intervention ladder makes that same verdict *bind more cheaply* (BLOCK preserves
  the turn that DEFER spent). It is a strictly better way to act on the `arg_provenance`
  verdict — but it acts on **the same verdict**, so it inherits the same ceiling: nothing to
  enforce when nothing is minted.

Both are **prevent-down on Integrity**. Neither touches the benchmark's dominant pathology —
**horizon decay** — which the paper measures as a monotonic collapse with step count and
attributes to *strategic planning* (the +14–35 pp oracle-plan lever DOS forfeits by doctrine).

> **The wedge this plan drives:** not all of horizon decay is planning. A measurable slice is
> **loop economics** — a cheap model that *had* the right env-authored value but burned its
> remaining iterations re-reading / polling / looping until it timed out with the task
> half-finished. That slice is **not** a planning failure (the plan was fine; the agent just
> failed to *use* a value it already had), so it is **not** off-limits by the no-planner rule.
> And the signal that the agent is stuck is **byte-clean** — see §3.

---

## 2. The mechanism — `dos.tool_stream`, a stall reader over the in-process tool stream

A new **pure kernel leaf**, the `liveness.classify` sibling re-aimed off git onto the
tool-result stream:

```
classify_stream(ToolStream, StreamPolicy) -> StreamVerdict
```

- **`ToolStream`** — a frozen tuple of `StreamStep(tool_name, args_digest, result_digest)`
  triples, in call order. The digests are computed **at the consumer boundary** (the wrapper
  hashes each call's normalized args and its result bytes); the kernel **hashes nothing live**
  — data in, verdict out, the dos idiom (`liveness.classify`, `arg_provenance.classify_call`,
  `churn.decide_coalesce`).
- **`StreamVerdict`** — `ADVANCING / REPEATING / STALLED`, the `LivenessVerdict` three-valued
  shape:
  - **ADVANCING** — the recent window contains distinct `(tool, args, result)` triples; the
    stream is producing new env-authored bytes. No intervention.
  - **REPEATING** — the **same** `(tool, args, result_digest)` triple has recurred ≥ `repeat_n`
    consecutive times: the agent is re-issuing a call the env answers identically — *no new
    information is entering the loop.* This is the actionable rung.
  - **STALLED** — REPEATING past a harder threshold (`stall_n > repeat_n`), or the last
    `window` steps are all repeats of a small set: the loop is almost certainly doomed to
    time out. The hard rung (a host may opt a DEFER/cut to it; the default does not — see §4).
- **`StreamPolicy`** — `repeat_n` (default 3), `stall_n` (default 5), `window` (default 6),
  `ignore_tools` (a host's known-pollers allow-list). Mechanism is kernel; knobs are config
  (the `LivenessPolicy` / `ProvenancePolicy` seam), declarable in `dos.toml [tool_stream]`.

The verdict carries, for the consumer's WARN content, **which env-authored result repeated**
— the `result_digest` and the index of the first occurrence — so the wrapper can re-surface
*that exact prior result* (the bytes the agent already received), never a fabricated one.

This leaf reuses `churn.decide_coalesce`'s **consecutive-identical-run-length** logic —
`churn` coalesces N identical no-op archive commits; `tool_stream` flags N identical no-op
tool calls. Same shape, different stream (git history → tool stream), which is exactly the
`recurring_wedge`-vs-`wedge_reason` "different input, separate leaf" split the kernel already
uses.

---

## 3. Why it is byte-clean — the §5a survival argument, pressure-tested

This is the crux: does the stall reader survive the **mirror-verifier trap** (docs/141/143
§5a) where the obvious "is the agent making progress?" version does not? Walk the provenance
of each field, because that is the only honest test:

| Field of a `StreamStep` | Byte-author | Forgeable by the judged agent? |
|---|---|---|
| `tool_name`, `args_digest` | the **agent** (it chose the call) | yes — but we do not adjudicate on these alone |
| `result_digest` | the **gym MCP server** (it produced the result) | **no** — env-authored bytes |

The reader's only question is: **"is this env-authored `result_digest` byte-identical to one
the env already returned, N times in a row?"** That is **provenance-of-the-identity-of-
repeated-output** — a pure byte question about *env-authored* bytes. The agent did **not**
author the *identity* of its own repeated tool results; the gym did. So the signal cannot be
forged in the agent's favor:

- The dangerous version — **"is the agent making real progress / has it done the right thing
  yet?"** — is a **satisfaction predicate** the wrapper would author from agent-visible prose
  (forgeable). The stall reader **never asks it.** "The same bytes came back N times" is not
  "the agent is failing"; it is a measured fact about the env's outputs.
- It needs **no answer key, no held-out state, no oracle plan** — exactly like
  `arg_provenance` (provenance-of-a-string), and unlike every gate docs/143 §5a killed
  (completion / resume-mint / db-state-as-truth, all of which minted belief from a
  self-authored predicate dressed in an `OS_RECORDED` sticker).

> **The honest hole (named, not buried):** **eventual-consistency polling is a legitimate
> reason to re-read with the same result.** A task that correctly waits for an async write to
> land will produce identical reads until it lands — a true REPEATING that is *not* a stall.
> This is why the **intervention must be a WARN that re-surfaces the value, never a cut**
> (§4): re-presenting bytes the agent already has is harmless if the agent was right to wait
> (it ignores a value it does not yet need), and helpful if it was stuck (it gets the value it
> kept failing to use). A *cut* on a legitimately-polling task would be a feasible-task
> regression — the §3 kill-signal — so the default never cuts. The `ignore_tools` allow-list
> lets a host exempt known pollers from the reader entirely.

---

## 4. The intervention — re-surface, do not cut (the only safe success-UP move)

The stall reader rides docs/144's **already-shipped** ladder. The mapping, and why each rung:

- **REPEATING → WARN (the default).** Attach an advisory result that **re-surfaces the
  env-authored value the agent already received**: *"You have already called `get_incident`
  with these args 3×; it returned `assigned_to = user_42`, `state = closed`. That value is
  available — proceed to the next step."* The call still dispatches (the agent is informed
  without losing the turn — the docs/144 WARN doctrine that recovered the −9 pp). **It
  fabricates nothing**: the re-surfaced bytes are the env's own prior result, pulled from the
  corpus by `result_digest`, never a synthesized DB row (that would be a new forgeable surface
  — the exact `dos_blocked` re-poisoning the `synthetic_corrective_result` docstring already
  guards against).
- **STALLED → BLOCK (opt-in, ceiling-raised).** On the hard rung a host may opt the
  turn-preserving BLOCK: withhold the redundant re-read and return the prior result as the
  synthetic corrective (the agent gets the value it needs *and* an iteration back). Default
  ceiling stays at WARN for the stall reader — re-surfacing is enough, and a BLOCK on a
  legitimately-polling task withholds a read the agent needed.
- **Never DEFER, never an unconditional cut.** A cut *fails* the task it was trying to save;
  it is the failure mode this whole axis exists to avoid. The reader's job is to *unstick*,
  not to *stop*.

The confidence coupling (docs/144 §3) re-aims naturally: **STALLED is the high-confidence rung
(BLOCK-eligible), REPEATING is low-confidence (WARN-capped)** — the more consecutive
identical results, the more certain the loop is doomed, the stronger the (still
turn-preserving) intervention may be.

---

## 5. Where it lives (the layering — kernel stays pure, actuation stays consumer-side)

- **Kernel (mechanism) — NEW:** `src/dos/tool_stream.py`. The pure
  `classify_stream(ToolStream, StreamPolicy) -> StreamVerdict`, frozen dataclasses in/out, no
  I/O, names no host. The `liveness.classify` sibling. Reuses `churn`'s run-length pattern.
- **Kernel (eval) — NEW:** `src/dos/tool_stream_eval.py` + `dos tool-stream-eval`. The
  per-axis eval harness (the `judge_eval` / `overlap_eval` / `intervention_eval` discipline):
  a confusion grid over replayed tool streams (REPEATING/STALLED vs a labeled
  "was-actually-stuck") + **recovered-task rate** (stalls that a re-surface unstuck) +
  **false-resurface rate** (REPEATING fired on a legitimately-polling task). The instrument
  that makes the `repeat_n`/`stall_n` thresholds **calibratable from data**, per deployment.
- **Driver/config — ladder-data only:** the stall reader's intervention is the **existing**
  ladder. No new rung needed for WARN/BLOCK. (If a host wants a distinct stall-cut rung it
  adds it via `InterventionLadder.extend()` / `dos.toml [intervention]` — the data path, not a
  kernel edit.)
- **Consumer (benchmark-side) — `dos_react.py`:** accumulate the `(tool, args_digest,
  result_digest)` stream alongside the existing prior-results corpus; before/after each call,
  fold `classify_stream`; on REPEATING attach the re-surfacing WARN. One stream accumulator +
  one consult, the `arg_provenance` consult's sibling. **Imports `dos`, lives benchmark-side,
  never in the kernel** (the one-way arrow).

The litmus held: the kernel **recommends** (a verdict + a re-surface payload built from the
env's own prior bytes) and **scores** (the eval); it **never actuates** and **never
fabricates** a result. PDP, no PEP. The success-UP edge comes entirely from *re-presenting
env-authored bytes the agent already holds* — not from any new self-authored predicate.

---

## 6. The experiment ladder (cleanest-attribution-first; refines docs/143 §8)

One mechanism per rung, paired-seed, same model/tools/scorer, each gated on its target slice
**AND** feasible-task-rate-not-down (the §3 kill-signal). Pre-registered, falsifiable:

| Rung | The ONE change vs below | Target slice | Promote iff | **Pre-registered prediction (ESTIMATE)** |
|---|---|---|---|---|
| **R0** | `react` baseline, no consult | — | (control) | reference. |
| **R1** | `arg_provenance` **WARN-only** (shipped default) | Integrity (FK) | feasible-rate ≥ R0 | **+1 to +2 pp verifier-pass (Integrity); success −1 to 0 pp** — reproduces docs/144. |
| **R2** | `arg_provenance` → **BLOCK** (synthetic-corrective; docs/144's pending live A/B) | Integrity (FK) | feasible-rate ≥ R1 **and** success ≥ R1 | **+1 to +3 pp verifier-pass; success −1 to +1 pp** — BLOCK flips DEFER's −9 pp toward 0 (sim +0.40 swing over DEFER). **Falsified if success < R1 − 2 pp.** |
| **R3** | **`tool_stream` REPEATING → re-surfacing WARN** (the new leaf) | Task Completion + horizon (≥8-step tasks) | feasible-rate ≥ R2 **and** long-horizon success up | **+2 to +4 pp success on ≥8-step tasks; ~0 pp on ≤4-step; no Integrity regression.** **Falsified if ≥8-step success ≤ R2.** |
| **R4** | **STALLED → BLOCK** (re-surface + reclaim the iteration; ceiling raised) | Task Completion + cost | feasible-rate ≥ R3 **and** false-resurface < 2 % | **+0 to +2 pp marginal success; cost/failed-run down.** **Falsified if feasible-rate < R3 − 1 pp** (a cut on a poller). |

**Why this order.** R1/R2 first because they are the *banked* line — R1 is shipped, R2 is
docs/144's one pending run (no new code). R3 is the **load-bearing new experiment** — the only
rung exercising the new leaf, and the only one whose ceiling is *independent of minting*, so
it ships behind R2's clean confirmation to keep attribution clean. R4 is the marginal of
reclaiming the iteration, gated hardest on the poller false-resurface risk.

**The kill-signal, unchanged:** feasible-task regression at any rung → **STOP, ship the prior
rung.** Do not tune-and-continue on the test split.

---

## 7. The honest ceiling — is this bigger than docs/144's baseline?

**Yes, and for a structural reason, but the envelope is single-digit and the assumptions are
real caps.**

- **R2 (BLOCK):** realistic best case **+1 to +3 pp verifier-pass with success recovered to
  ≈ baseline** on a *cheap minting* model — better than R1 mainly by removing DEFER's −9 pp
  cost, not by catching more. **Cap:** the `arg_provenance` ceiling is the *minting rate*,
  which → 0 as the model improves. This is docs/144's number, banked.
- **R3 (the stall reader) is the genuine advance.** It is the **only** rung whose success edge
  is **independent of minting**: looping is a *separate* pathology that *every* cheap model
  exhibits and the paper shows decays monotonically with horizon. Realistic best case **+2 to
  +4 pp success on long-horizon tasks** — and in a field whose entire closed-source spread is
  ~9 pp, +4 pp is a multi-rank Pareto move. **It fires even on a strong model stuck on
  eventual consistency**, so unlike R1/R2 its value does not vanish when the model gets better
  at reading. **Cap:** it only fires where the agent *had* the env value and failed to use it —
  a real but bounded subset; re-surfacing a value the agent then still cannot act on yields
  nothing (that residue *is* planning, and is off-limits).
- **Aggregate honest ceiling: +3 to +6 pp net success/verifier-pass on a cheap runnable model,
  dominated by R3**, *if* (a) the cheap model loops on byte-identical reads at a measurable
  rate, (b) a re-surfacing WARN measurably unsticks it rather than being re-ignored, and (c)
  feasible-rate stays flat across every rung. **Do not promise > 40 % absolute** — nothing in
  the field reaches it, and the +14–35 pp strategic-planning lever is forfeited by doctrine.
  The claim is a few points of Pareto movement on a **new axis (loop economics)**, not a
  category win.

> **⚠ The sim built for this (`benchmark/enterpriseops/stall_sim.py`) proves the mechanism is
> EMERGENT, not its MAGNITUDE.** Assumption (a) above — the loop-rate `p_stuck` — has **no
> real-data anchor**, and the headline scales linearly with it: at the likely-real strong-model
> rate (`p_stuck≈0.05`) the sim shows **~+3 pp**; the larger numbers only appear at implausibly
> high loop-rates (the `--honest` sweep makes this explicit). The exact precedent: the
> arg_provenance sim said +11.3 pp Integrity, the **real `gemini-3-flash` run measured ~0 / ~+1 pp
> verifier-pass** (`RESULTS.md`) because a strong model doesn't mint — and a strong model probably
> doesn't thrash either. **The simulated magnitude is a guess; only the R3 gym run settles it.**
> Lead with the *emergence* and the *new axis*, never the sim's pp.
>
> **✅ MEASURED `p_stuck` = 0.0 on the recorded trajectories** (`replay_stall.py`, the
> deterministic L1-safe replay of the real `gemini-3-flash` corpus — the loop-economics analogue
> of `replay_recall.py`). Folding the shipped `classify_stream` over every recorded task's real
> `(tool, args_digest, result_digest)` stream: **757 runs scanned, 5 with tool calls (21 calls),
> longest byte-identical run = 1, reader fired on 0.** So on the real strong-model data the stall
> reader would have done **nothing** — the same null as arg_provenance (the model that reads-first
> neither mints *nor* loops). The measured delta is **~0 pp**, exactly as the sim's `p_stuck≈0`
> row predicts. CAVEAT: 5 tool-using runs is a *floor, not a stable estimate* — the recorded
> corpus is dominated by 0-tool-call runs, so a precise `p_stuck` needs a fresh multi-step run.
> But the floor is unambiguous: **zero loops observed on real strong-model trajectories.** The
> mechanism earns its keep on a *cheap, failing* agent (the sim's regime), not the recorded one.

The single most defensible sentence: **docs/143/144 harden the substrate against a cheap
agent that MINTS; this plan hardens it against a cheap agent that LOOPS — and looping, unlike
minting, does not disappear when the model improves, so it is the axis with the durable
edge.**

---

## 8. The honest non-goals

- **Not a planner.** The reader re-surfaces a value the agent *already has*; it never decides
  *what the agent should do next* (the off-limits +14–35 pp lever). Re-presenting env bytes ≠
  recommending a step.
- **Not a progress *predicate*.** It never asks "is the agent succeeding?" — only "did the
  env's bytes repeat?" The moment it judges progress it becomes the mirror-verifier (§3).
- **Not a cut.** The default never stops a run; a STALLED-BLOCK only withholds a *redundant
  re-read* and hands back the prior result. Killing a loop fails the task the reader exists to
  save.
- **Not mandatory.** The floor stays advisory (WARN); the BLOCK rung is opt-in per host, and
  the eval is what tells a host whether opting in pays (the `ignore_tools` allow-list and the
  false-resurface metric are the safety valves).

---

## 9. The DOS kernel changes implied (the operator invited "updates to DOS")

1. **SHIPPED pure leaf `src/dos/tool_stream.py`** — `classify_stream(ToolStream, StreamPolicy)
   -> StreamVerdict` (ADVANCING/REPEATING/STALLED). The missing `liveness.classify` sibling,
   re-aimed off git onto the in-process tool stream; reuses `churn`'s consecutive-identical
   run-length pattern. Pure, no I/O, names no host. Exported from `dos`; cross-logged in the
   CLAUDE.md kernel layer as `liveness`'s lateral sibling.
2. **SHIPPED eval `src/dos/tool_stream_eval.py` + `dos tool-stream-eval`** —
   `StreamCase`/`StreamEvalReport`/`score`: the recovery ledger (recovered-rate, fire-recall,
   false-resurface-rate, fire-precision, `net_positive`), plus the operator verb (`--cases` a
   `repeat`-or-`steps` JSONL corpus; `--repeat-n`/`--stall-n`/`--ignore-tools` sweep the
   thresholds against a fixed corpus; exit 0 iff net-positive — the `intervention-eval` CI gate
   inverted to the friendly direction). The per-axis eval-friendliness discipline
   (`judge_eval`/`overlap_eval`/`intervention_eval` sibling), now CLI-reachable. Demonstrated: a
   mixed corpus scores NET-NEGATIVE, and `--ignore-tools <poller>` flips it net-positive on the
   SAME corpus — the "calibrate the thresholds from data" instrument, runnable.
3. **SHIPPED `dos.toml [tool_stream]` seam** — `repeat_n`/`stall_n`/`ignore_tools` as
   closed-config-as-data (the `[liveness]`/`[intervention]` pattern): the reader
   `tool_stream.load_from_toml` + the `SubstrateConfig.stream_policy` field (`_layer`-loaded,
   OVERRIDE-on-present) + a `stall reader` row in `dos doctor` surfacing the active windows.
4. **No kernel change** for R1/R2/R4-actuation: the intervention ladder, BLOCK/synthetic-corrective,
   confidence gating, and `intervention_eval` already ship — those rungs are **runs and
   calibration**, not code. R4's STALLED-BLOCK is a *consumer* wiring of the existing ladder.

**So the entire kernel + operator surface for this axis is shipped; the one remaining piece is
the *consumer* `dos_react` fold (accumulate the `(tool, args_digest, result_digest)` stream +
attach the re-surface WARN) and the live EnterpriseOps-Gym run (§6 R3/R4).**

**Net:** exactly **one new pure leaf + its eval + one config seam**; everything else is
consumer runs against shipped mechanism. The kernel's no-planner / PDP-not-PEP / byte-author-
only doctrine stays intact by construction: the new leaf asks a pure provenance-of-identity
byte question, the actuation stays consumer-side, and the success-UP edge comes from
re-surfacing env-authored bytes the agent already holds — never a new self-authored predicate.

---

## 10. Methodological note — why "survivors: 0" was a false reading

The ideation workflow's refute phase suffered a **mass `StructuredOutput` failure** (the
schema-agent pairs returned no verdict, the documented `[[feedback-workflow-schema-agent-mass-
failure]]` failure mode), so the binary `survives = every(v.survives)` over an *empty* verdict
array collapsed **all 19 ideas to "killed"** — an artifact, not a verdict. The run was
salvaged because (a) the **ideation phase succeeded** (19 real candidates across 5 lenses) and
(b) the **synthesis agent ran independently of the broken gate**, re-verifying the codebase
in-tree — which is how the §0 state-of-the-code correction was caught. The two load-bearing
claims it rests on (the intervention ladder is shipped+wired; `tool_stream` does not exist)
were **re-verified by hand** before this plan committed to them. **Read the rung, not the bare
verdict** ([[feedback-grep-subject-self-certifies-phase]]); here the bare verdict ("0
survivors") was a silent-truncation-reads-as-failure inversion, and the real signal was in the
synthesis the gate didn't touch.

**Cross-refs:** the minting-rate ceiling this clears = docs/143 §5/§12 + `benchmark/
enterpriseops/RESULTS.md`; the actuation ladder it rides = docs/144 + `src/dos/intervention.py`;
the byte-inequality axiom that makes it honest = docs/141; the unbuilt-liveness-reader call =
docs/143 §5 finding 3; the run-length pattern lifted = `src/dos/churn.py`; the sibling it
mirrors = `src/dos/liveness.py`; the per-axis eval discipline = `judge_eval` / `overlap_eval` /
`intervention_eval`; the slice survey that placed this axis = docs/146; the **other** byte-clean
re-aim of the `arg_provenance` shape (provenance-of-a-precursor-presence, the policy/refusal
slices) = docs/147 — its lateral sibling, same `liveness.classify` mirror.
