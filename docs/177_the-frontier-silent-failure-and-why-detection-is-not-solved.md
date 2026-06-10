# 177 — The frontier-silent failure, and why "detection" is not a solved thing

> **The one-line claim.** Running DOS's three byte-clean detectors across the full
> Gemini capability ladder (2.5-flash → 2.5-pro → 3-pro-preview) reproduces the
> "purchase vanishes on the frontier" scissors *cleanly* — but the right reading is
> NOT "the frontier model is safe," and NOT the over-simple "silent vs legible" split.
> It is: **capability does not remove failure, it REDISTRIBUTES it down a witness
> ladder.** The 203 confirmed frontier failures form a 2-D contingency table
> (terminating-belief × world-effect): as the model strengthens, mass drains out of the
> legible cells (loops / give-ups / error-walk-aways → the 3 detectors) and the
> confessed/asked cells (3 and 0 of 203 — the frontier model is almost never calibrated
> about its own failure) and concentrates in **confident-wrong-mutation** (95) and
> **abandoned-mid-action** (52) — cells *loud in the world-state, silent only in the
> trajectory*. Those are reachable by an unforgeable result-state witness (`verify()`,
> ~64–79%), a forgeable advisory judge (~19%), or nothing (~3%) — never by a trajectory
> grammar. Detection didn't get "solved"; the failure moved to the `verify()` rung.
> Model-agnostic mechanism; Toolathlon-specific percentages.

This doc is a measurement note + a foundational argument, **revised after a 6-axis
multi-agent carve + adversarial stress pass** (the first cut here was the same
two-bucket over-simplification the operator flagged). The measurement is the Gemini-only
cut of the docs/157 replay; the argument is the answer to *"as models get better,
benchmarks and use cases get harder — is it really a 'solved' thing, or does it just
happen to not make that mistake on this benchmark?"* — answered by **§3's taxonomy**,
not a single number.

---

## 1. The measurement (the Gemini ladder, $0 offline replay)

All three Gemini families are cached (`_data/gemini-*_{1,2,3}.jsonl`, 9 files, 972
trajectories, 920 oracle-labeled). The replay folds the three shipped byte-clean
detectors (`dangling_intent`, `tool_stream`, `terminal_error`) over the frozen
trajectories and joins to Toolathlon's THIRD-PARTY pass/fail oracle
(`task_status.evaluation`). Reproduce:

```bash
python -m benchmark.toolathlon.run_replay \
  --files gemini-3-pro-preview_{1,2,3}.jsonl gemini-2.5-pro_{1,2,3}.jsonl gemini-2.5-flash_{1,2,3}.jsonl \
  --no-download --by-model
```

The base-fail-rate column is the capability ladder, measured by the same oracle:

| model | base fail | dangling fire / lift | tool_stream fire / lift | terminal_error fire / lift |
|---|---|---|---|---|
| gemini-2.5-flash | **96.2%** | 5.0% / −2.5pp | 3.8% / −4.6pp | 1.9% / +3.8pp |
| gemini-2.5-pro | **87.9%** | 3.6% / +12.1pp | 3.2% / +12.1pp | 3.6% / +12.1pp |
| gemini-3-pro-preview | **63.2%** | **0.0% / —** | **0.0% / —** | 1.2% / −13.2pp |

(Normalized digest; the `--raw-digest` floor is byte-identical on this subset, so
the zeros are not a normalizer artifact. `lift = precision − base_fail_rate`; `—` =
no fires, undefined.)

The shape is sharp and monotone:

- **gemini-2.5-pro is the sweet spot.** Every detector fires at **100% precision**
  with **+12.1pp lift** and **zero false alarms**. When this model fails it fails in
  *structurally legible* ways — it loops, it stops mid-intent, it walks away from an
  error — and the grammars catch it perfectly.
- **gemini-2.5-flash inverts.** So weak (96% fail) that the base rate swamps the
  signal; the two narration/loop detectors go slightly net-harmful (false-alarm 8.3%
  = genuine eventual-consistency polling on the *few* tasks that still passed).
- **gemini-3-pro-preview is invisible to the loop/narration detectors.**
  `dangling_intent` and `tool_stream` fire **0 times in 321 trajectories**.
  `terminal_error` fires 4× and is net-negative (2 TP / 2 FP).

A naïve read of row 3 is "the detectors are obsolete on the frontier." That read is
**wrong**, and the rest of this doc is why.

---

## 2. The anatomy of a frontier failure (the probe)

The frontier model still **fails 63.2% of the time** (203 / 321 confirmed fails). If
the detectors fire ~0 yet the model fails constantly, the failures must have a
DIFFERENT shape. `benchmark/toolathlon/_probe_frontier_silent.py` characterizes them
(read-only, $0, offline). The result:

```
# gemini-3-pro-preview: 203 confirmed-FAIL, 118 confirmed-PASS

  SILENT (no structured env error ANYWHERE in the run) : 169 / 203 = 83.3%
  had a structured env error somewhere                 :  34 / 203 = 16.7%
     of those, the model CONTINUED past the last error :  34  (worked past it)
  dangling_intent ABSTAINed (acted after last narration):  20 / 203 =  9.9%

  terminal narration tone:
     no_success_claim : 131 / 203 = 64.5%
     claims_success   :  72 / 203 = 35.5%   ← confidently wrong
```

The first-pass observation — **83.3%** — is that the environment **never reported an
error anywhere in the run.** The model called well-formed tools, got well-formed
results, narrated a coherent (often success-claiming) summary, and stopped. (This
"silent" share is the right *first* cut but a coarse one — §3 decomposes it into the
2-D belief × world-effect table; read 83.3% as "no env-error channel fired," not as a
single mechanism.) Sample terminal narrations of these silent fails (oracle says FAIL):

> *"The quiz 'Classic Art History Questions' has been **successfully created**... the
> four multiple-choice questions have been added."*
> *"I have **successfully completed and submitted** all of them for you."*
> *"I have **successfully completed the tasks**. 1. Identified Missing Assignments..."*

These are not loops. They are not dangling intents (the model acted, then stopped —
`results_after_turn > 0`). They are not walked-away-from errors (the env emitted no
error). **They are confidently-wrong well-formed answers** — 35–54% of all 203 fails
claim success in their final text while having failed the oracle (the band is
lexicon-sensitive: 72 fails match docs/177's narrow success-cue list, 109 a broad
one; *don't* cite a point estimate).

This is the first crux. **There is no in-trace byte-clean signal for "the agent did a
well-formed wrong thing."** Every byte in the trace — narration, tool args, env
results — is consistent with success. The only witness that the task failed is the
benchmark's FINAL-STATE oracle (`evaluation/main.py` diffs the actual end state of
Canvas/Notion/the filesystem against gold). DOS's three detectors read the
*trajectory*; this class is invisible in the trajectory by construction.

But "silent = confidently-wrong" is itself **still too coarse** — and §3 below is the
correction. 38% of these fails have *no final text at all* (not confident — abandoned),
the writers split into wrong-mutation vs failed-to-act vs opaque-exec, and the witness
that catches each differs. The two-bucket "silent vs legible" model collapsed a
multi-dimensional space into one residual. The rest of this doc carves it properly.

> **A measurement caveat that governs every count below.** The 203 are 203
> fail-*runs* but only **83 distinct tasks** (53 failed in all 3 runs). Effective
> independent-n ≈ 83; treat per-class run-counts as *runs*, never as 203 independent
> observations. Counts are sourced from `_probe_frontier_silent.py` +
> `_frontier_contingency.txt` (committed, reproducible).

---

## 3. The real taxonomy: two axes, not one bucket

The over-simplification was carving by **"does a trajectory grammar happen to fire?"**
(a yes/no on DOS's current detectors). The right carve is by **"what KIND of wrongness
is this, and what witness would be SOUND against it?"** — because that is what tells
you whether DOS can ever touch it, and with which rung. Six independent carvings
(epistemic state / world-effect / pipeline-stage / detector-blindspot / witness-needed
/ task-shape), each adversarially stress-tested for MECE-violations and — critically —
for **mislabeled witness soundness** (a class that claims a byte-clean witness while
secretly reading the agent's own narration is the docs/138 §5a violation), converged
on a **2-dimensional** structure. The flat "silent bucket" was hiding a contingency
table.

### 3.1 The primary axis — TERMINATING BELIEF (what state did the run end in?)

| belief at end | n / 203 | what it is |
|---|---|---|
| **CLAIM/ASSERT done** | ~109 (broad) / ~72 (narrow) | reached a terminating belief of *success*; narrated completion, no hedge |
| **PLAIN stop** | ~16 | final text, neutral/descriptive, no success claim and no hedge |
| **ABANDONED** (no final text) | **78 (38.4%)** | reached *no* terminating belief — ended on a tool result or an empty assistant turn |
| **CONFESSED stuck** | **3** | final text hedges ("couldn't find", "unable") |
| **ASKED the user** | **0** | deferred to a human |

The frontier model is **almost never calibrated about its own failure**: 3 confessions
and 0 asks out of 203. It either confidently asserts done or runs out without a word.
This is a *metacognition* fact the "silent" label erased — and it matters because the
confessed/asked classes (the only ones with an in-trace distress cue) are **empty**,
while their cue would be **forgeable anyway** (it lives in agent-authored narration).

### 3.2 The secondary axis — WORLD EFFECT (what did the run do to the world?)

| effect | n / 203 | witness consequence |
|---|---|---|
| **WROTE** (≥1 mutation) | 162 | verify() diffs the artifact vs gold |
| **NO_MUTATION but task required one** | ≥22 | verify() trivially: world unchanged when it must change |
| **OPAQUE_EXEC** (only a python/shell executor ran) | ~26 | effect *not in the trace bytes* — verify() is the only classifier |
| **READ-only / no-effect** | ~19 | no end-state to diff → judge or gold-key |

### 3.3 The contingency table (the structure no two-bucket model can express)

Crossing the two axes over all 203 fails (`_frontier_contingency.txt`):

```
                WROTE   NO_MUTATION(req)   READ/unk    TOTAL
CLAIM_SUCCESS    95          3               11         109
PLAIN_STOP       15          0                1          16
ABANDONED        52         19                7          78
TOTAL           162         22               19         203
```

The joints the flat bucket destroyed are the populated cells:

- **CLAIM_SUCCESS × WROTE = 95 (47%)** — the flagship frontier failure: *confidently
  wrong/partial mutation.* The world was changed in a well-formed way, the env never
  objected, the artifact is wrong-or-incomplete (56% of writers made ≥3 mutations — a
  partial-completion signature). Every trace byte is success-consistent. Witness:
  **result-state verify(), and nothing less.**
- **ABANDONED × WROTE = 52 (26%)** — acted, then ran out without narrating. Witness:
  verify() on the half-built artifact. (No truncation flag exists — see §3.5.)
- **ABANDONED × NO_MUTATION = 19 (9%)** — gave up before acting on a write-task.
  Witness: verify() trivially (world unchanged). The *easiest* sound catch.
- **CLAIM_SUCCESS × (NO_MUTATION + READ) = 14** — claimed success having never acted.
  A pure **narration-vs-state contradiction**: the sharpest verify() win, and the
  cleanest proof that no narration-reader is sound (it would believe the false claim).

### 3.4 The witness ladder, with the real coverage fractions

Folding the secondary axis into a witness map (the actionable output — which rung
catches what, with the adversary's corrections applied):

| witness rung | catches | ~share | byte-clean? | DOS status |
|---|---|---|---|---|
| **A. in-trace byte-clean (shipped)** | the 2 fails that still loop / walk-from-error | **2 / 203 (1%)** | yes (env-authored) | shipped — vanishing on frontier |
| **A′. in-trace, NEW mechanism** | non-terminal unrecovered error (~30, partial) + semantic-repeat run-length (~3) | small | yes | `needs_new_mechanism` |
| **B. result-state verify()** | all WROTE/NO_MUTATION/OPAQUE-EXEC concrete-artifact fails | **~130–160 (64–79%)** | yes (world-authored end-state) | `needs_verify` — **the roadmap** |
| **C. semantic judge (advisory)** | read-only / open-deliverable fails with no canonical end-state | ~19–39 | **no — forgeable** | `judge` rung, fail-to-abstain |
| **D. gold-key / human** | irreducible subjective-quality residue | ~3–5 | no | `unreachable` (ABSTAIN) |

### 3.5 What the multi-agent pass got WRONG (and I verified)

The adversarial reviews killed three tempting-but-false refinements — recorded so no
one rebuilds them:

1. **There is NO byte-clean truncation witness for the 78 ABANDONED runs.** The
   epistemic carve claimed a harness-authored "max-iters / finish_reason" signal makes
   abandonment byte-clean-catchable. **Falsified by direct check:** the records carry
   no termination-cause field (keys are `agent_cost/completion_time/config/…`), and
   **0 of 78** abandoned runs end on an unanswered (pending) tool_call — so even the
   fallback "structural truncation fingerprint" doesn't exist in this data. The 78
   ABANDONED runs are **verify()-only** (for the 51 that wrote) or witness-less (for
   read-only abandons). Abandonment is *real and distinct*, but it is **not** a new
   byte-clean detector opportunity here.
2. **The volatile-field normalizer slice is EMPTY on the frontier.** Of 52
   same-call/different-result consecutive pairs, **0** collapse under the normalizer;
   raw and normalized `tool_stream` fire identically (both 0). "Tune the in-trace
   detectors' recall" is *refuted* as a frontier strategy — the repeats that exist are
   genuine content diffs (semantic repeats, §A′), not churning timestamps.
3. **The four-way "task_shape" split is not MECE and not witness-distinct.** Its three
   concrete-artifact shapes (multi-write / precision-fill / cross-source-join) are
   **witness-identical** (all `result_state_verify`), 87/203 satisfy ≥2 of its gates,
   and its clean partition came from a hidden hand-classifier. The surviving cut is
   *binary*: **verify-reachable (concrete artifact, ~79%) vs judge-only (open/subjective
   deliverable, ~21%)** — task shape predicts the *witness rung*, not the in-trace
   mechanism. Keep that binary; drop the four-way.

---

## 4. The foundational answer: detection is not "solved," the failure MOVED

Here is the model-agnostic claim, stated carefully so it does not over-reach.

**What the three detectors actually catch is a SHAPE of failure, not a model's
weakness.** Specifically:

- `tool_stream` catches **looping** — the same `(tool, args, result)` recurring.
- `dangling_intent` catches **premature stop** — narrating a next step, then halting.
- `terminal_error` catches **walking away from a reported env error.**

All three are *structural distress signatures*. A weaker model emits them often
(it loops, it gives up, it ignores errors). **A stronger model emits them less —
not because it stops failing, but because it fails more COMPETENTLY.** Its failures
become well-formed: it confidently does the wrong thing, with no loop, no give-up,
no error envelope. The capability gain converts *legible* failures into *silent*
ones. The detectors' fire-rate going to zero on the frontier is therefore measuring
the model's **competence at failing quietly**, not its correctness.

So the answer to *"is it solved, or does it just not make that mistake here?"* is the
third option neither phrasing names:

> **The frontier model does not stop making mistakes — it stops making the KIND of
> mistake that leaves a trajectory-readable trace.** Detection of *those* shapes
> generalizes (it catches them on every model that emits them); but the *share of
> failures that emit them* shrinks as capability rises, because competence pushes
> failures into the result-state-only classes of §3.3 (confident wrong-mutation,
> abandoned-mid-write, failed-to-act). "Detection is solved" confuses "this grammar
> reads this shape perfectly" with "this grammar reads ALL failure." It never could
> read the result-state classes — and those are exactly the ones that grow with
> capability.

The taxonomy makes the mechanism precise. **Capability moves probability mass DOWN the
contingency table and toward the verify()-only cells.** A weak model spreads its
failures across the legible classes (it loops → `tool_stream`; it gives up mid-intent
→ `dangling_intent`; it ignores an error → `terminal_error`) *and* the confessed/asked
classes (it admits doubt). A strong model concentrates its failures in **CLAIM_SUCCESS
× WROTE** and **ABANDONED × WROTE** — the cells with an unforgeable witness (the
end-state) but **no in-trace one.** The detectors' fire-rate → 0 is the table's top-left
(legible) and bottom (confessed) cells emptying as the bottom-right (confident
wrong-mutation) fills. That is a *redistribution*, not a disappearance — which is why
"silent" was the wrong word: the failure is loud in the *world-state*, silent only in
the *trajectory*.

This is why the result is a **scissors**, and why no single benchmark run closes it:
the model where these detectors have *purchase* (mid-tier, 2.5-pro: +12pp, 100%
precision) is not the model where a leaderboard-citable correctness lift would matter
(the frontier, 3-pro, where they fire zero). The two blades move apart as models
improve.

### Why "harder benchmarks track capability" makes this WORSE, not better

The operator's instinct — *as models get better, use cases get harder* — sharpens the
argument. Toolathlon is already a hard, long-horizon, real-SaaS benchmark, and
gemini-3-pro still fails 63% of it. The failures are *near-misses by a competent
agent*: it did most of a multi-step task and got one final-state detail wrong, while
narrating success. As benchmarks get harder to keep pace with stronger models, the
**modal failure stays in the CLAIM_SUCCESS × WROTE cell** — because a competent agent
on a hard task fails by subtle wrongness, not by looping or crashing. The legible-
failure detectors keep working on whatever legible failures remain, but the *fraction*
they can touch keeps shrinking. **The detection frontier and the capability frontier do
not converge; they diverge.**

---

## 5. What this implies for DOS (the design consequence, not a defeat)

This is not "DOS detection is useless on strong models." Four things follow, and
they are the honest roadmap, consistent with the existing track record (docs/138,
the byte-author ≠ judged-agent invariant; docs/158, the frontier-silent finding;
the frontier-lift refutation in `[[project-dos-frontier-lift-axis]]`):

1. **The byte-clean in-trace detectors are correctly scoped to the LEGIBLE failure
   class, and they are sound there.** 100% precision on 2.5-pro is the proof. Do not
   try to stretch a trajectory grammar to read the result-state classes — that is the
   "satisfaction predicate" the §5a line forbids (any in-trace "is the answer right?"
   reader is forgeable, because the agent authors the bytes that would make it look
   right). The confident-wrong-mutation failure is trajectory-silent *precisely because
   the trace is agent-consistent*; class **B_SILENT_WELLFORMED_WRONG** is the limit case
   — the agent even *read its own write back* and the read agreed, because re-deriving
   your own bytes is consistency, not grounding. A trajectory reader cannot soundly call
   it, not even with a self-check.

2. **The silent class is reachable ONLY by an out-of-trace, byte-unforgeable
   witness — which is the rest of DOS, not these three detectors.** The benchmark's
   own final-state oracle IS that witness (it diffs real end-state, which the agent
   cannot forge). DOS's analogue is `verify()` against an unforgeable artifact (git
   ancestry, the ship-stamp, an env-authored end-state digest) — the ORACLE rung, not
   the in-flight detector rung. The lesson: **the silent frontier failure is a
   `verify()` problem, not a `liveness`/`tool_stream` problem.** The closed loop needs
   a *result-state* witness, not a *trajectory* witness, on strong models. This is the
   `[[project-dos-frontier-lift-axis]]` finding restated from the detector side: on
   strong models the value is in coordinating + verifying the RESULT, not in
   in-flight distress-sniffing.

3. **There is ONE real in-trace mechanism left to build, and it is small (A′).** The
   adversary confirmed exactly one byte-clean extension with residual purchase: a
   *non-terminal* error variant (drop `terminal_error`'s closing-window constraint,
   keep its same-operation recovery check — the docs/162 knob) catches the unrecovered
   subset of the ~30 *error-then-worked-past* fails; plus a *semantic-repeat run-length*
   counter (same-`(tool,args)`-intent ≥4× with different result bytes) catches the ~3
   pagination/navigation loops byte-equality correctly misses. Both are env-authored
   and sound. Everything else the carvings proposed as a new in-trace detector was
   **refuted**: no truncation flag exists for the 78 abandoned runs (§3.5.1), and the
   normalizer slice is empty (§3.5.2). So the in-trace backlog is ~33 fails, not the
   silent majority — don't oversell it.

4. **The dominant ~64–79% is a verify() problem — the result-state rung — and the
   detector line's honest market is the WEAK/MID tier and the FLEET.** The
   CLAIM_SUCCESS/ABANDONED × WROTE/NO_MUTATION/OPAQUE-EXEC mass is reachable ONLY by an
   out-of-trace, byte-unforgeable witness: the actual end-state, which the agent cannot
   forge. That is what Toolathlon's `evaluation/main.py` diffs and what DOS's `verify()`
   is (git ancestry / ship-stamp / an env-authored end-state digest). **The frontier fix
   is a result-state witness, not a fourth trajectory grammar** — the
   `[[project-dos-frontier-lift-axis]]` finding from the detector side. And the
   trajectory detectors keep their purchase exactly where the legible classes are large:
   the weak/mid tier and the fleet, where closed-loop economics matter
   (`[[project-dos-closed-loop-control]]`). The frontier single-agent is the *worst*
   case for them; report it as such, never hope past it.

---

## 6. The honest boundaries

- **DETECT, not FIX.** Frozen trajectories ⇒ no intervention ⇒ no lift number. This
  doc measures *what the failures are made of*, not whether a WARN would convert them
  (the live-A/B question, refuted on this regime in docs/172/175).
- **203 fail-RUNS, ~83 distinct TASKS.** Effective independent-n ≈ 83 (53 tasks failed
  all 3 runs). The contingency cells are *runs*; treat them as such. The *mechanism*
  (capability redistributes failure toward the verify()-only cells) is the
  model-agnostic claim; the *percentages* are Toolathlon-specific and lexicon-sensitive
  (the CLAIM_SUCCESS share is 35–54% depending on the cue list).
- **The witness ladder fractions carry ±8-run boundary wobble.** The verify-vs-judge
  split turns on "does an unforgeable end-state exist to diff?", a *task* property; the
  read/mutate classification (degraded by opaque executors) and the success-cue lexicon
  move counts by a handful. The *joints* (which cells are populated, which rung is
  sound) are sharp; the cell *counts* are estimates.
- **A class with NO sound witness is a finding, not a gap.** The ~3–5 subjective /
  gold-defined-quality fails (class D) have no byte-clean witness and no abstention-
  disciplined judge can soundly close them — DOS's correct behavior is to ABSTAIN, not
  manufacture a forgeable verdict. The honest taxonomy *names* this residue rather than
  folding it into a "verify() catches everything" overclaim.

---

## 7. The takeaway in one paragraph

The most powerful Gemini model fails the most-real benchmark 63% of the time, and DOS's
three byte-clean trajectory detectors fire essentially zero — but "silent vs legible"
was a cartoon. The real structure is a **2-D contingency table** (terminating-belief ×
world-effect): the failures redistribute, with capability, out of the legible cells
(loops → `tool_stream`, give-ups → `dangling_intent`, error-walk-aways →
`terminal_error`) and the confessed/asked cells (3 and 0 of 203 — the frontier model is
almost never calibrated about its own failure) into **CLAIM_SUCCESS × WROTE** (95, the
confident wrong-mutation) and **ABANDONED × WROTE** (52, the run-out-mid-action). Those
cells are *loud in the world-state and silent only in the trajectory* — so they are
reachable by an unforgeable result-state witness (verify(), ~64–79%), a forgeable
advisory judge (~19%), or nothing (~3%), but never by a trajectory grammar, because the
trace is agent-consistent by construction (class B is the limit: a self-consistent
read-back confirms the agent's own wrong bytes). The model-agnostic consequence:
**capability does not remove failure, it moves it down the witness ladder — toward the
result-state rung — so the frontier's failures are a `verify()` problem, the mid/weak
tier and the fleet are the trajectory-detectors' market, and exactly one small in-trace
mechanism (the non-terminal-error + semantic-repeat reader, ~33 fails) is left to
build.** "Solved" was never the right frame; the frontier moved the failure to where
these particular eyes don't look — and the taxonomy says precisely which other eyes do.
