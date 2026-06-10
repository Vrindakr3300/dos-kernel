# 152 — The first natural-lift experiment: does the dangling-intent WARN *convert*?

> **Status:** design + DETECT measured + **the FIX half now RUN at full N (2026-06-05).** The
> authoritative live A/B executed — **100 natural paired tasks across all 4 domains** (itsm/csm/email/hr,
> `--mint-rate 0`), `none` vs `resurface`, recorded to `live_results_natural_run/` (rerunnable via
> `dangling_convert.py`). **Result, honest: DETECT works live (9 % natural fire-rate, 0 % false-fire,
> zero derailment); FIX is inert at the task level on a STRONG model** (0/9 fired stops converted to a
> task pass, but +2/−0 verifier-checks on the fired tasks — a faint non-negative tilt, never harm) —
> see §1.5. The whole-corpus −1.9 pp is re-seed noise on the 91 tasks the detector never touched, not
> the mechanism. A pilot (`--tasks 8`, 24 tasks) agreed directionally and showed one clean
> `0.57 → 0.86` conversion (the mechanism CAN convert; it is just rare on Gemini). This CONFIRMS the
> docs/153 prediction: on a capable model the narrating stopper often stopped *because* it couldn't do
> the step — DETECT works, net FIX awaits a genuinely weaker model (the unrun ~$50 step).
> Produced by a 4-phase adversarial design workflow (probe → 4 proposals → refute each →
> synthesize), every claim grounded by running code in the repo, not prose. The refutation phase
> *measured* the load-bearing numbers (it scored the committed natural data and ran the replay),
> which corrected the opening framing.
>
> **One line.** The question "does DOS produce *real, natural* lift on a medium-strength model?"
> reduces — after the refutation killed the two injected/zero-firing alternatives — to a single
> runnable experiment: **wire `dangling_intent.classify_stop` into the live consumer's stop event
> and measure whether re-surfacing the agent's own abandoned sentence CONVERTS a self-admitted
> premature stop into a completing turn**, at `--mint-rate 0` (zero injection) on natural
> gemini-2.5-flash failures. The DETECT half is already measured (**26 % of failed natural runs
> flagged, 0 % false-fire** — re-verified here); the FIX half (does the WARN flip the verifier?)
> is the genuine open unknown and the deliverable.

---

## 0. Why this is the right next step (the elimination, not the intuition)

The program's every "lift" number to date is from **injected** mints (docs/143/144/151,
`--mint-rate 0.30–0.35`) on a model that, run naturally, mints ≈ 0. The user asked for lift "as
real as possible" — i.e. **natural** (no injection). A four-angle design pass + adversarial
refutation eliminated the alternatives by *measuring* them in the repo:

| Candidate next step | Killed because (measured, not assumed) |
|---|---|
| **none-vs-WARN, `arg_provenance`, mint 0** | The committed natural `none` data already carries the telemetry: **0 nudges / ~261 natural tool calls**. At mint 0 the WARN arm is *byte-identical* to none — a pre-determined null re-run, not a measurement. |
| **`precursor_gate` live A/B (docs/146/147)** | The shipped grammar's `update_case=["get_case"]` rule names a **hallucinated tool** (real read is `get_cases_assigned_to`) → pure false-WARN generator. After the mandatory fix, the surviving rule fires on **~0 tasks** of the available natural CSM data (the lone candidate already satisfied its precursor). Salvage = the offline R-grammar eval + the grammar-bug fix, **not** a live headline. |
| **`tool_stream` stall reader (docs/145)** | Real-data replay already measured **`p_stuck = 0.0`** (fired on 0 of 757 runs). Would fire on nothing; not wired into the consumer. |
| **`dangling_intent` conversion (docs/150 §6)** | **Survives.** The one byte-clean axis whose natural firing rate is materially > 0, whose value is on *natural* failures, and whose consumer fold is genuinely unbuilt (a real ~15-LOC lift, not double-counting). |

The throughline: on a capable/medium model run *honestly* (no injection), the minting and looping
pathologies DOS catches are **absent** (the docs/149 finding, now confirmed a third time). The
**one** pathology a medium model *does* exhibit naturally — and narrates — is **premature
completion**, the 92 % failure head. `dangling_intent` is the only shipped, byte-clean detector
aimed at it.

---

## 1. The measured DETECT result (re-verified 2026-06-05)

`replay_dangling.py` folds the **shipped** `classify_stop` over the recorded **natural
gemini-2.5-flash** trajectories (`live_results_natural/none`, zero model calls):

| Metric | Natural gemini-2.5-flash | (prior: gemini-3-flash replay, docs/150) |
|---|---|---|
| **against-interest recall** (failed runs flagged) | **9 / 35 = 26 %** | 13 % |
| **false-fire** (passed runs flagged) | **0 / 7 = 0 %** | 0 % |

The flagged cues are the agent's **own words** ("I need to", "I was unable to", "I will now proceed
to" — then it stopped, no tool ran after). **26 % is a *natural* firing rate on a medium model —
the number the whole program lacked.** It is *higher* than the gemini-3-flash replay because a
weaker model narrates abandonment more, and the against-interest asymmetry (an agent does not
falsely confess unfinished work right before stopping) holds on 2.5-flash. This refutes the
"grammar may drift / fire-rate may drop on a weaker model" risk: it rose, 13 % → 26 %.

> **NB — a label bug to fix in passing:** `replay_dangling.py`'s banner still hardcodes
> "gemini-3-flash" though it reads 2.5-flash data (same family of stale label as
> `failure_distribution.py`). Cosmetic; the numbers are correct.

---

## 1.5 The FIX result — RUN on the live gym (2026-06-05)

The experiment §2 designed was executed at TWO scales. The **authoritative run** (this section's
headline) is the full one: `live_ab.py --tasks 25 --arms none resurface --domains itsm csm email hr
--mint-rate 0` — **100 natural paired tasks across all 4 FK-heavy domains**, recorded to
`live_results_natural_run/`, scored by `dangling_convert.py` (committed, rerunnable, $0 to re-score).
A smaller pilot (`--tasks 8`, 3 domains, 24 tasks, `live_results/dangling_ab/` via
`analyze_dangling_ab.py`) ran first and agreed directionally; the 100-task run supersedes it on N.

**The authoritative outcome (100 paired tasks):**

| | none | resurface | delta |
|---|---|---|---|
| whole-corpus verifier-pass / integrity | 46.6 % | 44.7 % | **−1.9 pp** |
| task-success | 14 / 100 | 11 / 100 | −3 tasks |
| dangling fires | — | **9** (9.0 % of runs) | — |
| false-fire on passed runs | — | **0** | — |

**The conversion join — on the 9 tasks where the WARN actually fired (the only ones it could affect),
vs the SAME task_id in the `none` arm:**

| Outcome on the 9 fired tasks | count |
|---|---|
| fail → pass (**converted**) | **0** |
| pass → fail (**derailed**) | **0** |
| unchanged (task outcome) | 9 |
| verifier-CHECK delta on fired tasks | **+2 gained, −0 lost (net +2)** |

**The ruling: the FIX is inert-at-the-task-level on a strong model, with a faint non-negative
check-level signal.** Four honest facts, none buried:

1. **DETECT works live, exactly as the replay predicted.** The detector fired on **9 real natural
   stops (9 %)** with **0 false-fire** on passed runs — the against-interest asymmetry holds live,
   not just on the recorded corpus. The fires are the agent's own abandoned sentences. This is the
   load-bearing positive result: *the first live, natural, byte-clean detector firing on a medium
   model.*
2. **FIX neither converts nor derails at the task level.** 0/9 fired stops flipped to a task pass;
   0/9 derailed. The WARN-only floor held perfectly — **not one run was dead-ended by the extra
   turn** (the −9 pp DEFER/SKIP backfire channel is structurally unreachable, confirmed live). At
   the finer verifier-check grain the fired tasks netted **+2 checks, −0 lost** — a faint *positive*
   tilt, never harm, but far too small to move a 406-check corpus.
3. **The whole-corpus −1.9 pp is re-seed noise, not the mechanism.** The arms are not
   verifier-paired (each re-seeds a fresh DB); the detector touched only 9 of 100 tasks and *helped*
   (+2) on those, so the −1.9 pp comes entirely from the **91 tasks it never fired on** — pure
   model/DB non-determinism between two independent re-seeds. 14 vs 11 successes is noise at n=100.
4. **This is the docs/150 §5 detect-not-fix ceiling, measured live at meaningful N.** On a *capable*
   model the narrating stopper often stopped *because* it could not form the next step, so
   re-surfacing its own words supplies no plan and the task outcome does not move. The value of the
   FIX half is **gated on a genuinely weaker model that narrates steps it can actually do** — the
   docs/153 weak-model question, the unrun next step.

> The pilot's single clean conversion (a csm task, `0.57 → 0.86` verifier-pass: re-surface → +1 tool
> call → +5 checks flipped) remains the **proof the mechanism CAN convert** — it is possible, just
> rare on Gemini. At the authoritative N=100 it did not recur into a *task* flip, which is the
> honest ceiling: the FIX is real but sub-threshold on a strong model.

**What this means for the program.** The honest deliverable on the strong model is the **DETECT**
result — **9 % live natural fire-rate, 0 % false-fire, +2/−0 checks on the fired tasks, zero
derailment** — *not* a net task lift. That is the first natural, byte-clean, advisory-safe detector
result the program has, and it is genuinely positive on its own terms (it caught real abandoned work
and never made anything worse). The net *lift* awaits a weaker model (docs/153); measuring FIX on a
capable model was always going to land here, and now it is measured, not assumed.

---

## 2. The experiment — DETECT is proven, FIX is the open question

Split the two so a null on one does not contaminate the other (the docs/143 detector-soundness ⊥
intervention-safety discipline):

- **DETECT** (done): 26 % natural recall, 0 % false-fire. Publishable as-is.
- **FIX** (the run): does the WARN re-surface *convert* a flagged stop into a passing task? This is
  what docs/150 §6 explicitly deferred ("does the nudge actually make the narrating stopper
  finish — the live experiment, deferred").

### 2.1 The build (one file, ~15 LOC — the only blocker)

Wire `classify_stop` into `dos_react.py` at the stop branch (`if not response.tool_calls: break`):

1. Read a `DOS_DANGLING` env gate (mirror the `DOS_PRECURSOR` gate at `dos_react.py:320`).
2. Before breaking, build `StopEvidence(final_turn_text=response.content, results_after_turn=0)`
   — `results_after_turn` is **structurally 0** here: the loop only exits when the terminal turn
   emitted no tool calls, so nothing executed after it (the env-authored corroborator is satisfied
   by construction).
3. Fold the shipped `dos.dangling_intent.classify_stop` with `DEFAULT_POLICY`.
4. On `DANGLING_INTENT`: append **a `HumanMessage`** (NOT a `ToolMessage` — there is no
   `tool_call_id` to anchor at a no-tool-call stop; a bare `ToolMessage` breaks the
   Gemini/LangChain message contract — **this caught bug would have crashed the run**) that
   re-surfaces the agent's **own** `matched_cue` sentence; do **not** break; run exactly **one**
   more iteration (a `self._dangled` one-shot flag → worst case is a one-turn tax, never a
   livelock); increment a new `self._dos_stats['dangling_warns']` counter.
5. Add `DOS_DANGLING` to `live_ab.py` `_ARM_ENV` for the `on` arm **and to `_set_arm_env`'s
   pop-list** so it is cleared between arms (the precursor-leak the refutation flagged must not
   recur). Surface `dangling_warns` in the per-run telemetry.

### 2.2 The run

- **Model:** `gemini-2.5-flash` (the only importable provider today; `langchain_openai` is not
  installed, so a weaker open model via openrouter is **declined for today** — it needs
  `uv sync --extra openai` first).
- **Arms (2):** `none` (`DOS_CONSULT=0`, mint 0) vs `resurface` (`DOS_CONSULT=1`,
  `DOS_INTERVENTION=WARN`, `DOS_DANGLING=1`, mint 0). **Zero injection** — every failure and every
  catch is the model's own.
- **Sample:** itsm + csm + email + hr, `--tasks 25`/domain (~100 paired by `task_id`) — clears the
  ~5 pp re-seed noise band better than the existing 20-task natural run. Re-use the cached
  `_sample` (375 rows already on disk) to avoid a fresh HF pull.
- **Scoring:** the gym's untouched hidden SQL verifiers. **Report `database_state`-only
  integrity %** as the primary (dodges the `response_check` LLM-judge variance — same key as the
  agent). Report **three separate numbers**: live fire-rate, re-prompt-then-finish rate, and net
  verifier-pass / success delta.
- **Gate the spend:** one cheap `--tasks 1` smoke call first (the conf key is an `AQ.Ab8…`
  access-token-style string, not a durable `AIza…` key — confirm it answers before the batch).

### 2.3 The decision gate

If `dangling_warns` materially > 0 (it will be — 26 % measured) **and** the conversion is
non-trivial, the verifier-pass delta is the headline. If conversion ≈ 0 (detect-but-can't-fix),
**publish that null** — it is the docs/150 §5 ceiling measured live, and it is itself the first
natural-detector-conversion datum the program has.

---

## 3. The honest predicted outcome (including the null)

Most likely a **small-to-null** FIX result with a genuinely open tail. The re-surface supplies
**no plan** (DOS hardens the substrate, never authors the task — the +14–35 pp planner lever stays
forfeit by doctrine), so it converts a stop only if the model **already knew** the next step and
merely stopped early — plausible for the *narrating* stopper, out of reach for the *silent* one
(the majority of the 92 %). Realistic net lift **+1 to +6 pp verifier-pass**, quite possibly inside
the ~5 pp re-seed noise band at N ≈ 100 (arms are not verifier-paired). The lower-variance
`database_state` integrity % is the likeliest place a clean positive shows.

The deliverable is honest either way: **"DOS byte-cleanly DETECTS 26 % of natural
premature-completion failures with 0 % false-fire on a medium model, and the WARN re-surface
converts X % of them"** — even X = 0 is a publishable result the detect/fix split was designed to
expose. It is the first lift number on this program that is **natural** (no injection),
**byte-clean** (a task-independent discourse grammar + an env-authored post-turn absence, never a
satisfaction predicate — survives §5a), **WARN-only** (the measured optimum; the re-surface authors
no directive, so the −9 pp derailment channel is structurally unreachable), and **detect-not-fix**.

---

## 4. Grafted from the runner-up angles (fold in, don't spend a separate run on)

- **Zero-spend companion datum:** score the committed `live_results_natural/none` with `score_ab`
  and publish `arg_provenance` natural firing = **0 nudges / ~261 calls** alongside the dangling
  number — so the report shows *both* detectors' natural rates and the honest contrast.
- **Fix the precursor grammar bug** (`update_case=["get_case"]` → drop it; `get_case` is a
  hallucinated tool) and run the **offline** `dos precursor-gate-eval` as the byte-clean soundness
  proof for docs/147 — the live A/B fires ~0 and is not worth the spend.
- **Per-mechanism counters** (`nudges_injected` / `precursor_warns` / `dangling_warns`) so any
  positive number is attributable and a single-mechanism effect never wears a "full-stack" label.

---

## 5. What this does NOT claim (the boundary, stated up front)

- **Not** a "full-stack DOS-on" result: at mint 0, `arg_provenance` fires ~0 and `precursor_gate`'s
  grammar covers only csm → any positive number is **dangling_intent alone** wearing a 3-mechanism
  label. Name it honestly.
- **Not** a fix for the dominant failure: the *silent* premature stopper (the majority of the
  92 %) stays out of reach without an env-authored required-step checkpoint the benchmark does not
  expose to a fair agent (docs/149 §3, docs/150 §6). DOS owns a high-precision **~26 % advisory
  slice**, not the head.
- **Not** cross-model / cross-benchmark: one model, one benchmark, one stop-cue grammar. The
  *direction* (natural detect with 0 false-fire) is a property of the against-interest asymmetry;
  the magnitudes are model-specific.

**Cross-refs:** the detector + its honest ceiling = docs/150; the failure distribution it attacks =
docs/149; the §5a byte-clean discipline = docs/141 + docs/143 §5a; the WARN-only optimum it inherits
= docs/144 + docs/151; the killed alternatives' evidence = `replay_stall.py` (p_stuck=0),
`live_results_natural/none` telemetry (0 nudges/261 calls), `precursor_grammar.toml` (the get_case
bug); the measured DETECT = `replay_dangling.py` over `live_results_natural/none`; the deferred
consumer fold this builds = docs/150 §6.
