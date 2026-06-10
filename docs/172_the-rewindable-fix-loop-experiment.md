# 172 — The rewindable FIX loop: a falsifiable experiment a frontier lab would care about

> *Dated design — written 2026-06-05. All numbers below are dated observations on
> the EnterpriseOps-Gym corpus as it stood on that day, not eternal truths. The
> companion doc-number `171` was taken by a concurrent agent (read-loop proof), so
> this lands at `172`.*

> **2026-06-06 UPDATE — the framework pivot (read §0.2 FIRST), adversarially verified.**
> The operator challenged the premise: *"is minting errors the right framework even?
> improve the model more closely relative to state-of-the-art concerns."* The data
> agrees the mint framework is artificial — AND the §3.5 governing result already
> **REFUTED** rewind on the mint regime (the "rewind livelock": when the dead end is
> an upstream *omission*, backjumping reproduces the same error). So the pivot is built
> on a **disproof, not a win**: the natural-thrash axis (§0.2/§9) re-asks the question
> on the agent's OWN dead-ending. A 4-agent adversarial verify-workflow (2026-06-06)
> stress-tested the pivot and forced three corrections now folded in: **(1)** it found
> + I fixed TWO real byte/anchor defects (a reflected-input echo leak; a mint-path
> anchor-to-error bug — both now pinned by tests); **(2)** the natural axis **also
> decays on strong models** by the same docs/170 monotone argument — it relocates the
> "artificial trigger" objection but KEEPS "weak-model-only," so it is **NOT more
> SOTA-relevant in the LIFT sense**; **(3)** the dominant natural thrash (`create_filter`
> required-field omissions, 9/12) is by the doc's OWN §3.5 taxonomy an UPSTREAM
> OMISSION — the exact class rewind was proven to **livelock** on. The pivot's durable
> value is therefore narrow: a **mint-free, byte-clean DETECT/PLACEMENT signal** (proven
> at $0) on the agent's natural dead-ending; whether it CONVERTS is pessimistically
> predicted to fail on the majority omission-class (§9). The only live conversion data
> so far (smoke n=4) points the WRONG way (rewind 58.3% < none 75% verifier-pass) — the
> §3.5 direction. docs/175 reached the same natural-failure instinct independently
> (Toolathlon). Read §0.0/§3.5 (the refutation) BEFORE reading the pivot as a win.*

## 0.2 The framework pivot: mint injection is artificial; natural fail-thrash is the SOTA question

The whole §1–§8 experiment rests on **mint injection** — artificially corrupting
foreign-key id args at rate 0.30 to *manufacture* the invented-ID failure mode that
`arg_provenance`/rewind detect. The doc itself half-admits the problem (§5: "on a
capable model the natural mint rate is 0/406 — DOS fires zero nudges, rewind is moot
by construction"), and §3.5 went further: the powered live A/B **disproved** the mint
rewind. The operator's challenge makes the framing explicit: **a data proof on the
mint regime proves something about an artificial regime a strong model never enters.**
The SOTA concern is not "can you catch an injected FK error" — it is "do agents
*naturally* dead-end, and can you back them out soundly (and WHEN does backjumping
livelock)?"

**The honest carry-over from §3.5 (the constraint the pivot must respect).** The mint
refutation's mechanism was the **rewind livelock**: rewinding helps only when the
corruption is *downstream accreted context*, and HURTS when the dead end is a
*symptom of an upstream omission* — because re-entering a clean prefix faithfully
*reproduces* the omission. This is not a mint-specific quirk; it is a property of the
failure's CAUSAL SHAPE. So the natural axis is not a fresh shot at a win — it is the
test of whether natural thrash is upstream-omission (→ livelock, rewind fails, like
the mint regime) or downstream-accreted (→ rewind could help). The early read is
sobering: the dominant natural thrash here is `create_filter` failing on
`criteria.from: is required` — an **upstream omission** (the agent omits a required
field and re-omits it). The §3.5 mechanism predicts the natural rewind will *also*
largely livelock on this class. The live A/B (§9) measures whether that prediction
holds, or whether a minority of natural thrash is accretion-type where it converts.

**The measurement that settles it** (the natural `none` corpus, 160 runs, NO
injection — `live_results_natural*/none`):

| Quantity (natural regime, mint-rate 0) | Value |
|---|---|
| task success (agents fail on their OWN) | **~14–17%** |
| tool calls hitting a STRUCTURED env error (`_is_struct_error`) | **~15–20%** |
| runs with ≥1 structured env error | **~25–38%** |
| **runs where the SAME tool fails ≥2× un-recovered (natural THRASH)** | **12 / 160 = 7.5%** |
| natural arg-provenance nudges (the mint detector, at mint 0) | **0** |

Two facts jump out. (1) The natural fail-thrash rate (**7.5%**) is *comparable to* the
artificial mint-thrash rate (~8% in the §2a replay) — but it arises from the agent's
own dead-ending, with **zero injection**. (2) The natural failures are **NOT
invented-FK-ID errors** (`arg_provenance` fires 0× at mint 0); they are malformed
calls the env rejects — e.g. `create_filter` re-issued with
`criteria.from: is required` / `negatedQuery: required field cannot be an empty
string`. So **rewind as originally wired (trigger = an arg-provenance BLOCK ≥2×)
would never fire naturally.** The mint regime detects a failure mode that essentially
never occurs on its own.

**The pivot (built 2026-06-06):** re-trigger the SUBTRACT off the **natural failure
stream** — the same tool producing a structured env error ≥2× un-recovered
(`Convergence.THRASHING` over the env's own errors) — with the gym's OWN error bytes
as the no-good note. This is *more* byte-clean than the mint version: there is no
injection at all, so the no-good note is purely THIRD_PARTY env bytes the agent did
not author. The rewind KERNEL needed no change — `rewind.rewind_plan` never depended
on minting or `arg_provenance`; it needs only a `FireVerdict` + a verified anchor +
an `EnvExcerpt`. Only the consumer-side trigger is new.

### What was built (2026-06-06, all tested)

| Surface | What | Where |
|---|---|---|
| `natural_thrash_gate(tool_results, tool)` | PURE: fires iff `tool` produced a `_is_struct_error` result ≥2× AND its latest is still an error (in the hole now). Reads only env-authored `tr['result']`. | `dos_react.py` |
| `_maybe_rewind_natural(...)` | the mint-free SUBTRACT: drives `rewind_plan` to the last-verified anchor, note = the gym's OWN error bytes (THIRD_PARTY). | `dos_react.py` |
| `_enact_rewind(...)` | the shared truncate-and-re-enter core (one byte-contract location for both the mint + natural triggers). | `dos_react.py` |
| **anchor bug fix** | the gym sets outer `success: True` on EVERY result **including `isError: true` failures** (measured 46/46) — so `_is_verified` now rejects a `_is_struct_error` result, or the natural rewind would anchor to a FAILED turn. | `dos_react.py` |
| `rewind_natural` live arm | `DOS_CONSULT=0 DOS_REWIND_NATURAL=1` — no mint, no arg_provenance, fires on the natural failure stream. Run at `--mint-rate 0`. | `live_ab.py` |
| 3 new unit tests | the gate fires/recovers correctly; the natural subtract is byte-clean; UNANCHORED floor holds. (5 pass total.) | `test_rewind_arm.py` |
| `natural_thrash_counterfactual.py` | the $0 tier-(a) replay over the natural corpus — uses the REAL kernel + gate logic, no re-implementation. | new |

### The $0 large-corpus proof (the placement half, settled)

`natural_thrash_counterfactual.py` over the 160 natural `none` runs (NO API spend,
NO injection):

| Metric | Value |
|---|---|
| natural runs replayed | **160** |
| natural fail-thrash runs found | **12 (7.5%)** |
| of those, fired **REWIND** | **12 / 12** (0 UNANCHORED, 0 NO_REWIND) |
| dead-end turns subtracted | **24** |
| no-good note byte-class | **typed token + the gym's OWN `❌ Invalid Tool Arguments` envelope (THIRD_PARTY)** — every one |
| thrashing tools | `create_filter` ×9, `update_send_as_alias`, `update_draft`, `link_knowledge_to_incident` |
| task success of the 12 thrash-runs under `none` | **0 / 12** |

This is the natural-axis analogue of §2a — the **placement** half, on the real
failure mode rather than an injected one: on every natural thrash the kernel found a
verified anchor (0 UNANCHORED — the anchor bug fix is validated: anchors land on
verified turns, never the failed turn despite the outer `success: True`), and the note
carries only the gym's own validation error. **But placement is NOT conversion, and
§3.5 is the warning here, not §2a.** The dominant thrash is `create_filter` failing on
`criteria.from: is required` — an **upstream omission**, exactly the causal shape §3.5
showed rewind *livelocks* on (re-entering a clean prefix reproduces the omitted field).
So the honest pre-registered prediction for the live arm (§9) is **pessimistic**:
subtraction likely does NOT convert this class, because the dead end is not downstream
accreted context — it is the agent re-omitting a required field it never learned to
supply. What the $0 proof DOES establish, durably: the mint-free trigger fires on real
natural dead-ending at a measurable rate (7.5%), with a byte-clean note, anchored
soundly — i.e. the *mechanism is wired correctly to the right regime*. Whether it
*helps* is the live question (§9), and the prior says probably not on omission-thrash.
**What it cannot show: whether the truncated agent then succeeds** — the conversion
half, which needs the live `rewind_natural` arm (running 2026-06-06).

## 0.3 The cause-locality ablation — what is an ACTUAL rewind issue (and what is not)

The §4 prune-vs-reorchestrate law says rewind helps only when the dead end's cause is
*downstream* of the anchor, and livelocks when it is *upstream*. But "upstream vs
downstream" is two buckets, and the natural corpus needs a **third**. `cause_locality.py`
subdivides every natural thrash (the 12 of 160) into three mutually-exclusive
cause-locality classes — by WHERE the fix-information lives relative to the surviving
prefix — and the result is the sharpest "actual issue vs not" statement in this doc:

| Class | What it is | Count (12 thrashes) | Can ANY rewind/restart help? |
|---|---|---|---|
| **A — recoverable-from-prefix** | the correct value WAS in an OK prefix result; the agent lost it in the dead-end tail | **0** | **YES** — the only rewind-addressable class |
| **B — upstream-omission** | the entity was never read; the agent is GUESSING (e.g. `link_knowledge_to_incident` fabricating `INC-000001/044/069/082`, no `find_incident` ever ran) | **1** | **NO** — rewind livelocks (re-hands the read-less prefix → re-guess); a *restart* might |
| **C — not-in-transcript** | a schema/format/constraint the model violates (`create_filter: criteria.from is required`, `negatedQuery cannot be empty`) — the fix is API knowledge in the model's WEIGHTS, in no tool result | **11** | **NO** — unreachable by rewind, restart, OR append; a model-capability gap |

**The verdict: 0/12 natural thrashes are rewind-addressable; 12/12 are not.** And the
dominant 11/12 are not even the upstream-*omission* class §3.5 is about — they are a
**model-capability gap**: gemini-2.5-flash does not know the gym tools' required-field
schemas and re-omits them. **No transcript surgery can supply knowledge that lives in
the weights, not the context.** This is the honest subdivision: the natural failure on
this benchmark is overwhelmingly a *capability/affordance* problem, and rewind (a
context-hygiene primitive) is **categorically the wrong instrument** for it. The right
instruments for class C are **tool-schema injection** (put the required-field list in the
tool description so the model stops omitting it) or a **binding PEP** (reject the
malformed call against the schema before dispatch) — neither is a rewind. Class B (1/12)
is the only one where a *different transcript move* (restart that re-reasons, or a
precursor-gate forcing the missing read, docs/147) could help; rewind cannot.

This is why the live `rewind_natural` conversion (§9) is predicted to be **≈ none**:
there is essentially nothing in the natural corpus for it to convert. The instrument is
sound and the trigger is byte-clean — but the *population it can act on is empty here*.
That is not a failure of the build; it is the measurement telling us the failure mode
this benchmark generates is upstream of where any rewind operates. (The classifier is
conservative toward B/C — class A requires a CONCRETE differing value in the prefix, not
a coincidental digit-substring match, which is what flips the `link_knowledge` case from
a false-A to its true B; so A=0 is a real floor, not a thresholding artifact.)

**The generalizable law this sharpens (the part a lab keeps):** a rewind/backjump
primitive's addressable population = the thrashes whose fix-datum is *in the truncatable
context*. Measure THAT before claiming a recovery primitive helps — most agent dead-ends
in a schema-rich tool environment are class C (capability) or class B (un-read entity),
not class A (lost-in-the-tail). The DOS-shaped move for C/B is not rewind; it is the
**precursor gate** (force the missing read, docs/147) and **schema-affordance injection**
— which DOS can also adjudicate, but as a different verb than the SUBTRACT.

## 0.4 The threshold ablation — the gate's false-INTERRUPTION cost (the second subdivision)

§0.3 settled WHAT the gate fires on (≈0% rewind-addressable). This subdivides the OTHER
cost: even as a pure DETECTOR, does firing at `min_failures = K` interrupt tools that
would self-recover? A tool that hits K structured errors and then *succeeds on a later
try* read the env error and fixed itself; firing at error K cuts that off. Measured over
the 160 natural runs (`gate_calibration.py`):

| K (`min_failures`) | fires-on-stuck (TP) | fires-on-recoverable (FP) | FP rate |
|---|---|---|---|
| **2** (default) | 14 | 6 | **30.0%** |
| 3 | 9 | 4 | 30.8% |
| 4 | 6 | 2 | 25.0% |
| 5 | 5 | 1 | **16.7%** |

Two sub-facts fall out, both load-bearing for "actual issue vs not":

1. **Schema errors self-recover 36% of the time** (9/25 (run,tool) pairs that hit a
   schema error later succeeded on that tool). So the env's `is required` message *is*
   partly actionable — the model sometimes parses it and fixes the call. That is the
   slice a WARN/re-surface (not a rewind) could amplify; it is also the slice a rewind
   *interrupts*.
2. **At the default K=2, 30% of fires are false interruptions** — the gate cuts a tool
   that was about to self-fix. Raising K to 5 drops that to 17% but shrinks coverage to
   5 fires (all still class C/B per §0.3). **There is no K at which the fired population
   is net-rewind-positive:** every threshold combines a material false-interruption cost
   with a ≈0% rewind-fixable true-positive set. This is the mechanistic reason the smoke
   pointed the wrong way (rewind 58.3% < none 75%) — the rewind was not merely failing to
   convert; it was *interrupting self-recoveries* on top of acting on unfixable cases.

**The clean separation this forces (DETECT vs ACTUATE):** the thrash gate is a *sound
detector* of a dead-ended tool — but on this benchmark the dead ends it detects are
either self-recovering (don't touch them), capability-bound (rewind can't fix them), or
un-read-entity guesses (rewind livelocks). So the honest design conclusion is: **keep the
detector, change the actuation.** For the self-recovering slice → OBSERVE (do nothing, the
docs/144 lesson). For the capability slice → schema-affordance injection. For the
un-read slice → a precursor gate (docs/147). The SUBTRACT (rewind) has *no* slice here
where it is the right move — which is the most precise form of the operator's question
answered: on this corpus, natural-thrash rewind is not an actual issue rewind fixes; it
is a detector whose correct actuation is everything-except-rewind.

## 0.5 The synthesis cross-tab — every trigger × every cause (the SUBTRACT has no home)

The natural failure can fire a SUBTRACT through **two** trigger surfaces, not one, and a
complete answer must ablate both. `trigger_population_xtab.py` cross-tabulates
TRIGGER × CAUSE over the 160 natural runs:

| Trigger | fires | class A (rewind-addressable) | class B (livelock) | class C (capability) |
|---|---|---|---|---|
| **BRANCH** (`natural_thrash`, same tool errors ≥2× — possibly *different* error bytes) | 12 | **0** | 1 | 11 |
| **LOOP** (`stall` → `tool_stream` STALLED, ≥5× *byte-identical*) | 2 | — | — | 1 error-loop + **1 success-spin** |
| **Σ rewind-addressable (class A, any trigger)** | | **0** | | |

The two triggers catch the **same** class-C capability gap presenting two ways — an
error-*branch* (the model varies the malformed call) or an error-*loop* (it repeats the
identical malformed call 13–29×, e.g. `update_send_as_alias: smtpMsa.port expected
integer got number`). Re-entering a clean prefix re-spawns the schema-ignorant call in
both. The **one** genuinely loop-hygiene case is a SUCCESS-spin (`list_send_as_aliases`
re-read unchanged 5×) — and even there the right actuation is WARN/re-surface (docs/145),
**not** a SUBTRACT. So across **both** trigger surfaces the rewind/subtract addressable
population is **0 of 14 fires.**

**The fully sub-divided verdict (the operator's question, answered exhaustively):**

```
natural dead-ends (this benchmark, gemini-2.5-flash)
├─ BRANCH (errors ≥2×)         12 ─┬─ A rewind-fixable        0   ← the ONLY rewind issue
│                                  ├─ B un-read/guess         1   → precursor gate (docs/147), not rewind
│                                  └─ C schema/capability    11   → schema injection / PEP, not rewind
└─ LOOP (byte-identical ≥5×)    2 ─┬─ error-loop (class C)    1   → schema injection, not rewind
                                   └─ success-spin            1   → WARN/re-surface (docs/145), not rewind
ACTUAL rewind issues: 0 / 14.  Every other cell has a DIFFERENT correct DOS verb.
```

This is the durable, transferable result — and it is *not* "rewind is bad." It is:
**a recovery primitive is only as useful as its addressable population, and you must
ablate the population by cause BEFORE attributing a delta to the mechanism.** On a
schema-rich tool benchmark with a weak model, that population for SUBTRACT is empty; the
mass sits in capability (C) and missing-precursor (B), each with its own non-rewind verb.
DOS's value here is the **sound, byte-clean DETECT** that lets you *route* each dead-end
to its correct verb — which is a stronger claim than any single mechanism's lift, and the
one that survives the §3.5 refutation and the §5 strong-model decay.

## 0. What changed since the MAP was drawn (read this first)

The brief that commissioned this doc described the rewind arm as *built as a pure
verdict but wired into nothing — no consumer, no evidence reader, no benchmark
arm, never run.* **That snapshot is already stale against the working tree.** As of
2026-06-05 the rewind axis is wired end-to-end and the cheap experiment already
runs:

| Surface | MAP said | Working tree on 2026-06-05 | Verified by |
|---|---|---|---|
| Pure verdict `rewind.rewind_plan` | built, 31 tests | built, 31 tests green | `pytest tests/test_rewind.py` → `31 passed` |
| `rewind_evidence.py` boundary reader | **does not exist** | **exists** (untracked) | `src/dos/rewind_evidence.py` head read |
| Tier-(a) $0 replay counterfactual | does not exist | **exists + runs** | `benchmark/enterpriseops/rewind_counterfactual.py` |
| `dos_react._maybe_rewind` consumer (truncate + re-enter) | does not exist | **exists**, `dos_react.py:479-583` | read |
| Escalation trigger (2nd block on a tool ⇒ rewind) | does not exist | **exists**, `dos_react.py:758-766` | read |
| `live_ab.py` `rewind` arm | does not exist | **exists**, `live_ab.py:72` | read |
| Arm unit test (no gym) | does not exist | **exists**, 2 pass | `pytest test_rewind_arm.py` → `2 passed` |
| **A scored live rewind result** | — | **does not exist** | no `live_results/rewind/` dir |

The one genuinely missing thing is **the live result itself.**

### 0.0 TWO LIVE RUNS DISAGREED — the more-powered one REFUTES (read §3.5, not the small run)

The experiment was run live **twice** on 2026-06-05, by two agents, and the runs
**disagreed in sign** — which is itself the diagnostic verdict: the effect is small
relative to noise, so the more-powered run governs. Both are recorded; neither is hidden.

| run | tasks | domains | mint | rewind − block | fired-run flip net | verdict |
|---|---|---|---|---|---|---|
| **A — POWERED (§3.5)** | **48** | **4 (itsm/csm/hr/email)** | 0.40 | **−3.4pp** | **−3 (4h/7h)** | **REFUTES** |
| B — small (ITSM only) | 20 | 1 | 0.30 | +6.2pp | +3 (3h/0h) | (favorable, but underpowered) |

**The governing result is A (§3.5): the thesis is DISPROVED on this regime.** Run A is
2.4× the tasks, 4 domains not 1, a higher mint rate, and *more* fired rewinds — and it
trips two kill conditions (rewind < block; negative fired-run flip). Run B (my ITSM-only
n=20) landed favorably (rewind > block, flip 3/0) but is exactly the small, single-domain
sample the §6 caveat and the runner's ±~5pp band warn against: **two opposite-sign results
on a sub-5pp effect is the signature of a noise-dominated measurement, and the larger
sample wins.** Run B is NOT a confirmation — it is one small contradicting draw, reported
for completeness, not as evidence the predictions held. The honest aggregate verdict is
§3.5's: **subtraction did not beat append; on a weak model whose dead end is an *upstream
omission*, backjumping to a clean prefix reproduces the same invented id (the rewind
livelock).** Run B's per-task data lives in docs/175 §8 with this same correction stated;
the Toolathlon OFFLINE result (docs/175 §3 — existence + disjointness of the class) is
unaffected by either live run and still stands.

### 0.1 The first live smoke caught a wiring bug (2026-06-05 22:42–22:46)

A first smoke (`--tasks 3 --arms none block rewind --domains itsm`) **ran to
completion** against real Gemini + the ITSM MCP container. It scored
none 64.3% / block 71.4% / **rewind 28.6%** verifier-pass — but **0 rewinds
fired** despite the rewind arm emitting 24 blocks, including
`add_child_incident` blocked **3×** in one run (a clear thrash that *should* have
triggered a subtract). So the rewind arm was, in that run, **byte-identical to
BLOCK plus a bug** — its 28.6% is pure small-N fresh-DB-seed noise (3 unpaired
tasks), not a rewind effect, and must not be read as one.

The bug, found by reading the run: `_maybe_rewind`'s anchor reader required a
`success` flag *inside the result payload*, but the gym wraps every result as
`tr["result"] = {"success": bool, "result": <payload>}` — the flag is at the
**outer** level. So every candidate anchor read as unverified → `UNANCHORED` →
the arm fell back to the BLOCK append every time. Fixed (`dos_react.py`
`_is_verified` now reads the outer `success`; `test_rewind_arm.py` updated to the
gym's real wrapper shape; `rewind_counterfactual.py` `_verified` aligned — its
6/6 replay numbers are unchanged because the recorded block arm also satisfied the
old `status` fallback). A corrected smoke was re-launched on 2026-06-05.

**This is the value of a live run:** the $0 replay (§2a) and the unit tests were
both green, yet the arm did nothing live — only a real run surfaced the
nesting-level mismatch. The honest status remains: **the experiment is ready and
now actually fires; it has not yet been run to a scored result on enough thrash
runs to measure conversion.** This doc is *"the gun is loaded and now actually
discharges; here is what to predict before reading the result, and the kill
condition that stops us rationalizing it after."*

This matters because the prior bimodal ruling (§5) is a strong prior *against* a
big lift, and an already-built arm is exactly the situation where motivated
reading is most dangerous. Pre-registration is the discipline.

---

## 1. The precise falsifiable question

> **On the EnterpriseOps-Gym mint-injection regime, does SUBTRACTING the dead-end
> turns on a thrash (rewind to the last kernel-verified anchor + re-enter with a
> byte-clean no-good note) recover more whole tasks than APPENDING a synthetic
> correction (BLOCK), and is it at least not worse than doing nothing (none) —
> i.e. does the rewind arm's paired verifier-pass / task-success rate land
> strictly above BLOCK's and at or above none's?**

- **Confirms the thesis** ("the failure was the append, not the detect"): rewind's
  paired verifier-pass rate sits **above the none baseline** (the do-nothing arm) by
  a margin that clears the corpus's ±~5pp noise band, AND **strictly above BLOCK**,
  which on the 2026-06-05 corpus sits dead-on none (+0.0pp). The mechanistic
  signature confirming it: on the runs where a rewind fired, the per-task
  verifier-flip net is **positive** (more help-flips than hurt-flips), inverting
  BLOCK's net −6 (7 help / 13 hurt).
- **Disproves the thesis**: rewind lands at or below BLOCK (subtraction is no better
  than append), OR rewind lands *below* none (subtraction is net-harmful like
  BLOCK), OR rewind never fires enough to measure (the thrash trigger is too rare on
  a real model to matter — the §5 "moot on a capable model" trap).

The question is deliberately **three-way** (none / block / rewind), not two-way,
because the prior ruling already established BLOCK ≈ none. Beating BLOCK alone
would be vacuous if rewind also fails to beat none. The load-bearing comparison is
**rewind vs none**; the **rewind vs block** comparison is what isolates "subtract
vs append" with the detector held identical.

---

## 2. The experiment in two tiers

Both tiers hold the detector **identical** across arms (same `DOS_CONSULT=1`,
`DOS_INTERVENTION=BLOCK`, same `DOS_MINT_RATE=0.30`, same `DOS_MINT_SEED`); the
*only* difference rewind introduces is `DOS_REWIND=1`, which changes what happens on
the **second** block of a tool (`dos_react.py:758`). The first block is identical to
BLOCK in every arm — only the re-block subtracts. This keeps the contrast clean: any
delta is attributable to *append-again vs subtract-on-thrash*, nothing else.

### Tier (a) — the $0 REPLAY counterfactual (already runnable)

`benchmark/enterpriseops/rewind_counterfactual.py` feeds the **real recorded
78-file block arm** through `rewind.py`'s **actual verdict logic** (no
re-implementation, `from dos.rewind import rewind_plan`). It maps each `tool_result`
to a `TurnRef`, marks a `dos_blocked` synthetic as a dead end, places the
`SuspendCheckpoint` at the last *verified* tool result before the first block on a
**thrashed** tool (blocked ≥2× ⇒ `Convergence.THRASHING`), and reads back
`rewind_to_turn` / `dropped_turns` / the byte-clean note.

**Result on 2026-06-05** (`python rewind_counterfactual.py --json`):

| Metric | Value |
|---|---|
| block files / runs parsed | 78 |
| thrash-runs found (a tool blocked ≥2×) | **6** |
| of those, fired REWIND | **6 / 6** (0 UNANCHORED, 0 NO_REWIND) |
| appended synthetic corrections **eliminated by subtract** | **18** |
| total transcript turns subtracted | **46** |
| task success of the 6 thrash-runs | **0 / 6** |

What Tier (a) **CAN** show, exactly and for free:
- The trigger **is reachable** on real data: 6 of the 78 block runs thrashed (a tool
  re-blocked), and on every one the kernel found a verified anchor to rewind to
  (0 UNANCHORED). The mechanism is not vacuous.
- The **subtraction magnitude**: rewind would have eliminated 18 of the appended
  synthetic corrections and removed 46 dead-end turns of accreted context — the
  precise quantity of "forged context" the BLOCK arm carried forward and the thesis
  says poisoned the downstream reasoning.
- The **note is byte-clean on real inputs**: every emitted no-good note is exactly a
  `VERIFY_NOT_SHIPPED` token over the unresolved id + the gym's own
  `blocked_unresolved_id` error excerpt (`THIRD_PARTY`). No prose, on real error
  bytes — the §6 contract holds outside the unit tests.
- A **ceiling sanity check**: all 6 thrash-runs were task-failures under BLOCK.
  Subtraction *cannot do worse than 0/6* on these exact runs, and any live re-run
  that converts even one is strictly additive on this slice.

What Tier (a) **CANNOT** show (the honest wall):
- **Whether the agent then succeeds.** Replay only proves *where* the anchor lands
  and *how much* is subtracted. It cannot replay the counterfactual *future* — a
  truncated transcript re-fed to Gemini produces *new* tokens we do not have on
  disk. Conversion is a live question, full stop.
- **n=6 is tiny.** Six thrash-runs is a placement demonstration, not a rate. It
  bounds the *firing frequency* (~8% of block runs thrash) and the *subtraction
  size*, nothing about task delta.

### Tier (b) — the LIVE A/B (replay + real Gemini, the conversion half)

Add the `rewind` arm to the existing live runner and run the same injected mints
through **none / block / rewind** on the live gym (4 healthy MCP containers, live
Gemini key, the gym's hidden SQL verifiers untouched):

```
python live_ab.py --tasks 55 --arms none block rewind \
    --domains itsm csm hr email --mint-rate 0.30 --mint-seed 42
```

The arm is already declared (`live_ab.py:72`) and enacted
(`dos_react._maybe_rewind`); this is a *run*, not a build. Scoring reuses the
committed `score_ab.py` (paired on `task_id`, verifier-pass = integrity rate since
every sampled verifier is `database_state`) so the result is directly comparable to
the 2026-06-05 four-arm baselines.

What Tier (b) **CAN** show:
- The **conversion** the replay cannot: paired verifier-pass and task-success for
  rewind vs none vs block on the same tasks, with the same noise treatment the prior
  A/B used (trust the lower-variance verifier-pass; report success% with its
  ±~5pp band).
- The **per-task verifier-flip decomposition** (`mattered_join.py`): rewind's
  help/hurt/net, directly against BLOCK's 7/13/−6 and WARN's 14/2/+12. This is the
  smoking-gun instrument that localizes *whether subtraction stops breaking
  downstream steps*.
- The **fire rate live**: how many runs actually thrash under a real model (the
  replay's ~8% is on the cheap-agent mint regime; the live rate is the real
  denominator).

What Tier (b) **CANNOT** show:
- **A clean per-task paired delta on success.** The arms re-seed a fresh DB per task
  (the DB state is irreversible), so they are not verifier-paired; small-N success%
  carries noise. The prior A/B's own caveat applies unchanged — read the aggregate
  verifier-pass, not the success% spread, as the verdict.
- **Anything about strong models.** This regime is gemini-2.5-flash with **injected**
  mints. On a capable model the natural mint rate is **0/406** (measurements.jsonl):
  DOS fires zero nudges, every arm collapses to baseline, and rewind — like every
  intervention — is **moot**. Tier (b) measures the cheap-agent regime *only*. It can
  corroborate the "lifts a weak model" direction; it **cannot** earn "≈ a stronger
  model" (§5).
- **Generalization past EnterpriseOps-Gym.** One gym, one failure family (invented
  foreign-key IDs). The thrash signature here is specifically "re-emit an invented
  id"; a different env's thrash may not map to the verified-anchor rule as cleanly.

---

## 3. The pre-registered prediction (stated BEFORE the live run)

Recorded 2026-06-05, before any scored rewind result exists, so it cannot be
cherry-picked after the fact. The thesis predicts:

**Tier (a) — already observed, locked as the placement baseline:**
- ✅ The trigger fires on real data (predicted: ≥1 thrash run with a verified
  anchor; **observed 6/6 fired REWIND**, 0 UNANCHORED).
- ✅ Subtraction eliminates real accreted context (predicted: appends_eliminated > 0;
  **observed 18 corrections / 46 turns**).
- ✅ Notes are byte-clean on real error bytes (predicted + observed).

**Tier (b) — the live prediction, the falsifiable core:**
- **P1 (the central claim):** rewind's paired verifier-pass lands **above none** by a
  margin clearing ±~5pp — concretely, **rewind ≥ ~45%** against the 2026-06-05 none
  baseline of **40.2%**. (The thesis says subtraction recovers the WARN-class lift
  that BLOCK forfeits; WARN already hit 46.4%, so a successful rewind should sit in
  the **44–47%** band.)
- **P2 (subtract beats append):** rewind's verifier-pass lands **strictly above
  BLOCK's 40.2%** — i.e. rewind − block **≥ +4pp**. If subtraction is the fix, the arm
  that subtracts must beat the arm that appends with the detector held identical.
- **P3 (the flip signature):** on fired-rewind runs, the verifier-flip net is
  **positive** (help > hurt), inverting BLOCK's −6. The mechanistic claim is that
  subtraction stops breaking downstream steps; the flip table is where that shows.
- **P4 (fire rate non-trivial but small):** rewind fires on **roughly 5–15%** of
  runs (the replay's ~8% ± the live model's lower natural mint behavior). If it fires
  on **<3%**, the effect is real but **immeasurable at n=55** and the run is
  underpowered — a *not-proven*, not a *disproven* (see §6).

**The honest hedge built into the prediction:** the prior ruling (§5) caps the
plausible magnitude. P1's ceiling is WARN's 46.4%, **not** a model-generation-sized
15–40pp jump. If rewind merely *matches* WARN (≈46%), that is a **win for the
thesis** (subtraction recovered the lift append destroyed) but **not** evidence for
"≈ a stronger model." The two claims are kept separate on purpose.

---

## 3.5. THE RESULT — the thesis is DISPROVED on this regime (run 2026-06-05)

The pilot ran to a scored result: **48 paired tasks × 4 domains (itsm/csm/hr/email),
mint-rate 0.40, gemini-2.5-flash, none/block/rewind, same injected mints.** It is a
clean **disproof** of the conversion thesis on this model and regime — recorded
against the pre-registration above, not rationalized after.

**The headline (vs the 4-arm baselines — note these are the n=48 mint-0.40 run, a
higher mint rate than the recorded 0.30 corpus, so the none baseline shifts to 49.2):**

| arm | success% | verifier-pass% | Δ vs none |
|---|---|---|---|
| none | 10.4 | 49.2 | (base) |
| block | 12.5 | 48.3 | −0.9 |
| **rewind** | **8.3** | **44.9** | **−4.3** |

**The flip microscope (`mattered_join.py`, the load-bearing instrument):**

| arm | caught-mint tasks | help-flips | hurt-flips | **net** |
|---|---|---|---|---|
| block | 19 | 6 | 4 | **+2** |
| **rewind** | 17 | 4 | 7 | **−3** |

**Both kill conditions fire (§6):**
- **KC#1 — subtract is no better than append.** rewind verifier-pass (44.9%) is
  **below** block (48.3%) by −3.4pp, far outside the +1pp band. The detector is held
  identical; the *only* change is append→subtract, and subtract is worse. "The
  failure was the append" is **false on this regime** — the failure was intervening
  at all in a way that disturbs the trace, and rewind disturbs it *more*.
- **KC#3 — the flip signature inverts the wrong way.** On caught-mint tasks rewind's
  flip net is **−3** (4 help / 7 hurt) — negative, and *worse* than BLOCK's +2. The
  prediction (P3) was that subtraction would invert BLOCK's negative to positive;
  instead subtraction went negative while append stayed mildly positive. The
  mechanistic claim — "subtraction stops breaking downstream steps" — is **refuted**:
  rewind broke *more* downstream steps than append.

### 3.5.1 WHY — the rewind LIVELOCK (the precise mechanism, the valuable part)

Only **4 runs** fired rewinds, but they fired **18 rewinds total** — one run rewound
**7 times**, another **5** — and **0/4 of those runs succeeded**. The flow of a
representative csm run (`contract_id` invented):

```
dos_block → dos_rewind(to 5, drop[6]) → dos_block → dos_rewind(to 5, drop[6,7]) →
dos_rewind(to 5, drop[6,7]) → dos_rewind(to 9, drop[]) → dos_rewind(to 9, drop[]) …
```

Two failure modes, both real:

1. **Re-entry reproduces the dead end.** The agent invented `contract_id` because it
   never *looked it up* — and that missing lookup lives in the prefix *before* the
   anchor. Truncating to the last-verified turn and re-entering with "contract_id
   never appeared" hands the agent back the *same* prefix that led it to invent the
   id, so it **re-emits the same invented id** and re-thrashes. Subtraction removed
   the dead-end turns but **not the cause** — the cause was an *omission* upstream,
   which a backjump to a clean prefix cannot supply. (This is exactly the KC#2
   mechanism §6 pre-registered: "the agent re-derives the same invented id from the
   surviving prefix and re-thrashes.")
2. **No-op rewind spin.** The thrash trigger (`block_count[tool] >= 2`) re-fires on
   **every** subsequent block once tripped — so a re-thrashing run spins out repeated
   rewinds, **5 of the 18 (27%) dropping nothing** (`dropped=[]`, the anchor already
   at the tail). That is a livelock *in the rewind mechanism itself* — the very
   accretion-spin rewind was meant to stop, reintroduced one level up. The trigger
   should cap at **once per thrash episode** (and escalate to a HALT/HUMAN rung on
   re-thrash), not fire per-block.

**The honest reading:** this is a *real disproof with a real cause*, not a noise
null. Subtraction alone is **insufficient** when the dead end's root cause is an
*upstream omission* rather than *downstream accreted context* — rewinding to a clean
prefix can faithfully *reproduce* the error. Rewind helps only when the corruption it
removes is the thing causing the loop; here the corruption (the invented id) is a
*symptom* of a missing read, and the read is gone after truncation too.

### 3.5.2 What still HELD (do not over-correct the disproof)

- **Placement (Tier a) is unaffected:** the $0 replay's 6/6 REWIND / 18 appends / 46
  turns stands — the kernel *can* place a valid anchor. The disproof is about
  *conversion*, exactly the split this doc drew.
- **The note stayed byte-clean live:** every one of the 18 live rewinds emitted only
  a `VERIFY_NOT_SHIPPED` token over a kernel-derived field + the gym's own error
  excerpt. No generated prose entered the trace — the §6 byte contract held under a
  real model. The mechanism that sank BLOCK (a synthetic *content* injection) was
  never the failure here; the failure was that **subtraction of a symptom doesn't
  supply a missing cause.**
- **The floor mostly held vs `none`:** rewind 44.9 vs none 49.2 is −4.3pp, but the
  arms are unpaired fresh-DB (the standing caveat); the *paired* evidence is the flip
  net (−3), which is the refutation. It did not catastrophically collapse — it
  quietly failed to convert and mildly disturbed the trace.

This is the **NOT-a-strong-model decay made concrete on a weak model**: even where DOS
*does* fire (24% thrash, well above the predicted 5–15%), subtraction did not convert
— corroborating the bimodal ruling's *direction* (interventions are wash-to-negative
on a capable-enough model whose stop is a can't-form-the-step) while *refuting* this
specific "subtract fixes it" mechanism.

---

## 4. The frontier-lab framing (REVISED by the result)

**Is there a result here a lab would care about?** Yes — but **not** the one §4
originally pre-registered (that prediction was refuted, §3.5). The lab-relevant
result is now the **disproof + its mechanism**: a clean, dated demonstration that
*subtraction alone does not convert*, with a precise reason (it removes a symptom,
not an upstream-omission cause, and re-entering a clean prefix can reproduce the
dead end). A negative result with a mechanism is more useful to a runtime team than
a noisy positive — it tells them *when* backjumping helps and when it livelocks.

**The durable-infra claim (survives model upgrades, near-free) — still standing, but
narrowed:** DOS supplies a *capability-orthogonal* recovery primitive — a
deterministic, byte-clean way to back a stuck loop out that authors nothing (the §6
byte contract **held live**: 18/18 rewinds emitted only kernel-derived tokens + the
env's own bytes, zero generated prose). That property is real and survives a
capability upgrade. **What the result narrows:** *backjumping is not automatically a
fix.* It converts only when the loop's corruption is **downstream accreted context**;
when the corruption is a **symptom of an upstream omission** (here: a skipped id
lookup), subtraction to a clean prefix faithfully *re-derives the same error*. The
lab-legible lesson is therefore conditional: **"subtract forged context" is sound
only when the forgery is what's causing the loop — diagnose the cause before you
choose append vs subtract vs supply-the-missing-read.** The 2026-06-05 data shows
*both* BLOCK (append, +2 flip net here / −6 on the 0.30 corpus) *and* rewind
(subtract, −3 flip net) are wash-to-negative on this model — which says the missing
rung is neither append nor subtract but **F3: supply the verified missing fact
(the looked-up id) at the write, gated** (docs/126 PEP). That is the result that
would actually move a lab: *the two cheap content-free interventions both fail here,
so the value is in the gated cause-supplying rung, not the loop-hygiene rung.*

**The lift claim (decays to ~0 on strong models):** "weak + DOS ≈ stronger model"
is the strong form, and the prior ruling already refuted its **magnitude**: 0.00pp
conversion ceiling on gpt-5 / gemini-3-pro / claude-4.5-sonnet, +2.40pp corpus-wide
max, vs ~15–40pp for a model generation (an order of magnitude short). Rewind does
**not** rescue this claim and this doc must not pretend it does. On a strong model
the natural mint rate is ~0, rewind fires ~never, and the lift is ~0 **by
construction** — exactly the decay docs/170 predicts. A live rewind win on
gemini-2.5-flash is a win *in the weak-model execution-substrate slice only*; it is
corroboration of the *direction* ("helps weak more"), never of the *equivalence*.

**The single cleanest result that would MOVE a lab (pre-registered — and REFUTED):**
> ~~On the live A/B, rewind beats both none and block on paired verifier-pass AND the
> fired-rewind runs show a positive verifier-flip net — inverting BLOCK's −6.~~
> **Refuted 2026-06-05 (§3.5): rewind 44.9% < block 48.3% < none 49.2%; fired-run
> flip net −3 (worse than BLOCK's +2). Subtraction did not convert; it livelocked.**

**The cleanest result that ACTUALLY emerged (the disproof a lab would care about):**
> **With the detector held identical, both content-free interventions fail to convert
> on a weak model: APPEND (block) and SUBTRACT (rewind) are each wash-to-negative
> (flip net +2 / −3), and rewind livelocks (18 rewinds across 4 runs, 27% no-ops,
> 0/4 success) because backjumping to a clean prefix reproduces an error whose cause
> is an upstream *omission*, not downstream accretion. The implication: the missing
> rung is not how-you-back-out (append vs subtract) but supply-the-verified-missing-
> fact at the write, gated (F3 / docs/126 PEP).**

That is the transferable design law, now *grounded in a null*: diagnose whether a
loop's corruption is accreted-context (subtract helps) or an upstream-omission
symptom (subtract reproduces it); the latter needs a *cause-supplying* rung, not a
*hygiene* rung. A lab running fanout learns *which* recovery move to reach for and
*when each fails* — more useful than a +3pp that the §5 prior would discount anyway.

That single result is clean because it (a) holds the detector fixed, isolating the
append-vs-subtract variable; (b) is grounded in the lab-legible BLOCK refutation
they can already see; and (c) makes a *mechanism* claim (loop hygiene), not a
capability claim — so it is robust to the §5 prior. It says: *"the way you back out
a stuck agent matters, and the sound way is to subtract forged context, not author
a fix."* That is a transferable design law for any agent-runtime team, independent
of which model they ship.

**What would NOT move a lab** (and we should not lead with it): a bare
"rewind > none by +3pp on injected mints with gemini-2.5-flash." Without the
block contrast and the flip signature it is just one more advisory-nudge delta in
the noise band, on an artificial mint regime, on a weak model — the §5 prior
already accounts for a small weak-only lift and a lab will (correctly) discount it.

---

## 5. The prior ruling this must not over-claim against (the guardrails)

Carried forward verbatim as constraints, so the framing above cannot drift:

- **Bimodal, not substitution.** Durable capability-orthogonal referee (near-free,
  survives upgrades) + a small **decaying** weak-model-only lift (~+4–6pp →
  **0.00pp** on strong models). Rewind lives in the *first* mode (the durable
  primitive) with a contribution to the *second* (a slice of the weak-model lift).
  It is **not** capability substitution.
- **Append already lost.** BLOCK (append) scored net −4/task; WARN (re-surface) won
  at +4.2pp (simulator) / +6.2pp (live). The live A/B already **refuted**
  author-and-believe. Rewind is the *subtract* sibling of the *re-surface* winner —
  the prediction (§3 P2) is that it beats append; it would be over-claiming to
  predict it beats WARN.
- **The Verifier Tax (2603.19328).** 94% interception → <5% safe success. DETECT does
  **not** auto-convert to task success. Rewind's whole reason to exist is that DETECT
  alone (BLOCK) didn't convert; but the tax warns that even a *better* intervention
  may convert weakly. P1's modest band (44–47%) respects this.
- **Cheap + big-lift are mutually exclusive** on present evidence (Weaver 2506.18203:
  closed a gen gap but at 10–128× compute or a trained cross-encoder). Rewind is
  cheap (pure verdict + a truncation); the prior says cheap buys a *small* lift. Do
  not predict a big one.
- **Dates are observations, not laws.** Every number here is "as of 2026-06-05 on
  EnterpriseOps-Gym." A model swap or a gym change moves them.

---

## 6. The honest kill condition

The "rewind-makes-it-safe" thesis is declared **FALSE** (on this gym, as of the run
date) under any one of these real-data outcomes from Tier (b), run at n ≥ 55 paired
tasks with the detector held identical across arms:

1. **Subtraction is no better than append.** rewind verifier-pass ≤ block
   verifier-pass **+ 1pp** (i.e. within noise of BLOCK's 40.2%). If subtract does not
   beat append with the detector identical, "the failure was the append" is
   **false** — the failure was the *detect-and-intervene-at-all* in this regime, and
   rewind inherits it.
2. **Subtraction is net-harmful.** rewind verifier-pass **< none − 1pp** (below the
   40.2% do-nothing baseline). If truncating + re-entering *lowers* task success
   below doing nothing, subtraction breaks the loop the way append did — the thesis is
   **dead**, not merely unproven. (Plausible mechanism to watch: truncation strands a
   `ToolMessage` without its `AIMessage` and langchain mis-replays, or the agent
   re-derives the same invented id from the surviving prefix and re-thrashes.)
3. **The flip signature inverts the wrong way.** On fired-rewind runs the
   verifier-flip net is **≤ 0** (hurt ≥ help). Even if the aggregate looks flat,
   a negative flip net means subtraction is *also* breaking downstream steps — the
   mechanism claim (loop hygiene) is **false** regardless of the aggregate.

**Explicitly NOT a kill (these are *not-proven*, not *disproven* — a power problem,
not a refutation):**
- rewind fires on **<3%** of runs ⇒ underpowered at n=55; the verdict is "needs more
  tasks or a higher mint rate to measure," not "false." Re-run at n≥150 or
  mint-rate 0.5 before concluding.
- rewind ≈ none (within ±1pp) **with a positive flip signature on fired runs** ⇒ the
  mechanism works where it fires but fires too rarely to move the aggregate; "real
  but sub-threshold on this model," the same honest verdict docs/152's dangling
  resurface earned at N=100 (0/9 converted). Report it as such, do not inflate it.

**The asymmetry is deliberate.** A null aggregate with a *positive* fired-run flip
is a power problem (report sub-threshold). A *negative* fired-run flip, or rewind
below none, is a **refutation** (the mechanism actively harms). The flip table is
what separates the two — which is exactly why §3 P3 pre-registers it.

---

## 7. SETTLED — the command that ran it, and what comes next

The thesis was settled by one live run (2026-06-05), reproducible as:

```
# from benchmark/enterpriseops, gym prereqs healthy (4 MCP containers + gemini.json)
python live_ab.py --tasks 12 --arms none block rewind \
    --domains itsm csm hr email --mint-rate 0.40 --mint-seed 42 \
    --out live_results_rewind_pilot
python mattered_join.py --out live_results_rewind_pilot --arms block rewind
```

**Verdict: the conversion thesis is REFUTED on gemini-2.5-flash / EnterpriseOps
mint-injection (§3.5).** rewind 44.9% < block 48.3% < none 49.2% (KC#1); fired-run
flip net −3 vs block +2 (KC#3). Mechanism: a rewind livelock — subtracting to a
clean prefix reproduces an upstream-omission error (the agent re-invents the same
id) and re-fires (27% no-op rewinds). Placement (Tier a) and the byte-clean note
both held; only *conversion* failed.

**What this earns, and the next move it implies.** The disproof is not "rewind is
useless" — it is "subtraction is the wrong rung for an *omission*-caused loop." The
two cheap content-free rungs (append/BLOCK, subtract/rewind) are both wash-to-
negative on this model, which points at **F3 — supply the verified missing fact (the
looked-up id) at the write, gated** (docs/126 PEP) — the one rung not yet built and
the only one that addresses an omission cause. The honest next experiment is an F3
arm (read-the-id-then-retry, gated on the read actually returning it), not a fourth
flavor of content-free nudge. Two cheaper fixes to the rewind arm itself, if it is
kept: cap the thrash trigger at **once per episode** (kill the 27% no-op spin) and
**escalate to HALT/HUMAN on re-thrash** rather than re-rewinding into the same hole.

The pre-registered predictions (§3) and kill conditions (§6) decided it — not a
post-hoc read. The result tables in §3.5 are the record.

---

## 9. The natural-axis live experiment (the mint-free conversion test, 2026-06-06)

§0.2 built the mint-free `rewind_natural` arm and settled the **placement** half
($0, 160 runs, 12 fired/12 anchored). This section is the **conversion** half: the
live `rewind_natural` vs `none` A/B at mint-rate 0, where the only thing that happens
is the agent's OWN natural fail-thrash triggers a SUBTRACT.

```
python live_ab.py --tasks 60 --arms none rewind_natural \
    --domains email csm hr itsm --mint-rate 0 --mint-seed 42 \
    --out live_results_natural_ab
```

### 9.1 The pre-registered prediction (stated 2026-06-06, BEFORE the scored result)

Recorded before the run scored, grounded in the §3.5 livelock mechanism + a structural
read of the 12 natural thrash cases. The §3.5 lesson is the prior: rewind helps on
*downstream accreted* corruption, livelocks on *upstream omission*. So I classified the
natural thrash failures by whether the repeated env error is **byte-identical** (the
agent re-emits the SAME omission — livelock-prone) or **varying** (the agent changes
its attempt across calls — possibly convergeable):

| natural thrash class | count | §3.5 prediction |
|---|---|---|
| SAME error repeated (e.g. `create_filter: criteria.from: is required` ×N) | **10 / 17 (59%)** | **LIVELOCK** — rewind reproduces the omission |
| VARYING error (e.g. `update_vacation_settings`: HTML-tag → epoch-timestamp) | **7 / 17 (41%)** | maybe convergeable — the agent is exploring, a clean prefix + the latest env error MIGHT help |

- **P-natural-1 (the central, pessimistic claim):** `rewind_natural` does **NOT**
  beat `none` on aggregate paired verifier-pass by a margin clearing ±~5pp — because
  the majority class (59%) is upstream-omission, which §3.5 showed livelocks. Predicted
  band: **rewind_natural ≈ none ± noise**, NOT a clean lift.
- **P-natural-2 (the mechanism claim that COULD survive even if the aggregate is flat):**
  on the VARYING-class fired runs, the per-task flip net is **non-negative** (rewind
  does not actively harm where the agent was already exploring), while on the SAME-class
  fired runs the flip is **≤ 0** (livelock). If the aggregate is null but the
  class-split shows varying ≥ 0 > same, that is the "real but sub-threshold, and only
  on the convergeable class" verdict — the honest docs/152 outcome, not a refutation.
- **P-natural-3 (fire rate):** `rewind_natural` fires on **~5–10%** of runs (the $0
  replay's 7.5% ± the live model's variance). <3% ⇒ underpowered at this N, not disproven.

**The honest kill condition (natural axis):** if `rewind_natural` verifier-pass lands
**below none − 1pp** with a negative flip net on BOTH classes, the natural rewind is
**refuted too** — the SUBTRACT is net-harmful regardless of the failure's causal shape,
and the whole rewind-as-FIX thesis is dead on this benchmark (mint AND natural). If it
lands at-or-above none with a positive varying-class flip, the durable claim narrows to:
*"a mint-free, byte-clean SUBTRACT helps on the ~40% of natural thrash that is
exploratory (varying), and correctly does no harm on the rest."* That is a far more
defensible — and SOTA-relevant — claim than the mint regime ever supported.

### 9.2 The live result — the build-up record (SUPERSEDED by §9.3's final paired number)

> *These are the partial scores captured AS the run filled in (email, then +csm+hr). They
> are retained because they show the firing-bug catch and the verdict converging — but the
> FINAL, sound result is §9.3's paired attribution (0 conversions / 0 flips on 20 paired
> fired tasks). Do not cite the §9.2 partial deltas as the result; cite §9.3.*

The first scored arm completed *after a firing-bug fix* (docs/172 §0.6: the natural gate
was dead code in the `DOS_CONSULT=0` branch the `rewind_natural` arm takes; before the fix
it fired **0×** despite 11/43 thrash runs — a false-confirmation trap caught by interim
analysis). The corrected arm fires correctly: **17/17 thrash runs fired** on the 49 email
runs. The paired email score (none vs rewind_natural, n=44 paired, **16 fires**):

| arm | verifier% | success% |
|---|---|---|
| none | 59.7 | 29.5 |
| **rewind_natural** | **57.2** | **29.5** |
| **Δ** | **−2.5pp** | **0.0pp** |

**Read against the prediction (P-natural-1, §9.1): CONFIRMED.** rewind_natural ≈ none —
the −2.5pp verifier delta is inside the corpus's ±~5pp noise band, and **success is
identical (29.5 = 29.5): zero conversion.** Every one of the 16–17 fires landed
`success=False` on a class-C schema thrash (`create_filter`, `update_vacation_settings`,
`create_draft`) — the §0.3/§0.5 verdict made live: the mechanism fires reliably, converts
nothing, because the addressable population is empty. The slight *negative* lean is the
§0.4 false-interruption cost showing up exactly where predicted.

The class-split flip table (P-natural-2) is **too small to read** at 16 fires (varying net
−2 from 1h/3hurt; same net +1 from 4h/3hurt) — single flips on a fresh-DB-reseeded,
stochastic arm are noise, and it does not cleanly match the predicted varying≥0>same split.
Honest call: **the aggregate (≈none, 0 conversion) is the signal; the flip cells are noise
at this N.** This is the docs/152 "real-but-sub-threshold where it fires, fires on the
wrong population to convert" outcome — NOT a refutation (the mechanism is sound and
byte-clean), and NOT a win (no lift). It is the precise empirical shape the cause-locality
ablation predicted: rewind has no home on this benchmark's natural failures.

### 9.3 FINAL — all 4 domains, the rigorous paired attribution (2026-06-06, run COMPLETE)

The full run scored (240 tasks/arm). The raw aggregate and the *clean paired* attribution
tell the same story, but only the second is trustworthy — and it is the headline:

**Raw aggregate (159 paired-by-id of 240, the imperfect overlap):**

| arm | verifier% | success% |
|---|---|---|
| none | 39.4 | 11.3 |
| rewind_natural | 40.4 | 11.9 |
| Δ | +0.9pp | +0.6pp |

Both deltas are deep inside the ±~5pp noise band, so this is ≈none — but the +0.6pp success
is **not** a rewind effect, and chasing it down is the load-bearing diligence. There were
**23 live fires, 1 task-success among them.** That 1 success (`link_knowledge_to_incident`,
itsm, passed 6/6) is on a task the `none` arm **never ran** (the arms only share 159/240
task-ids — the gym re-samples per arm, the runner's own "NOT verifier-paired" caveat). So it
has **no none counterfactual** and cannot be attributed to rewind.

**The clean paired attribution (the only sound number) — fired tasks BOTH arms ran:**

| metric (20 paired fired tasks) | value |
|---|---|
| rewind success | **0** |
| none success (same tasks) | **0** |
| help-flips (none-fail → rewind-pass) | **0** |
| hurt-flips (none-pass → rewind-fail) | **0** |

**On the 20 properly-paired tasks where rewind fired, it changed the outcome on ZERO of
them — identical to none (0), with zero flips in either direction.** This is the cleanest
possible confirmation of the §0.3/§0.5 prediction: the mechanism fires reliably (23 fires
on `create_filter` ×14, `update_vacation_settings` ×6, plus one each `modify_message` /
`create_new_hr_case` / `link_knowledge_to_incident`), and converts **nothing**, because
every fire lands on an unfixable class-C schema-capability gap (or a class-B un-read guess).
The +0.9/+0.6pp aggregate is an artifact of the 159/240 imperfect pairing, not an effect.

> **FINAL VERDICT (run complete):** the mint-free natural rewind ≈ none. On the only sound
> comparison (paired fired tasks) it is **0 conversions / 0 flips out of 20** — the empty
> addressable population, measured by direct paired count. The §9.1 prediction held in full;
> the §0.3 cause-locality ablation predicted it exactly. **Keep the DETECT (the trigger is
> sound + byte-clean + fires 23/23 on real thrash); the SUBTRACT is the wrong verb for what
> it detects on this benchmark — route to schema-injection (class C) / precursor-gate
> (class B) / WARN (spin) instead.** This is not a refutation of the mechanism (it is sound)
> and not a win (no lift) — it is the precise, exhaustively-ablated answer to "what is an
> actual rewind issue here": none of them.

## 8. Provenance of the numbers in this doc

- **the pilot disproof** (none 49.2 / block 48.3 / rewind 44.9 verifier-pass; success
  10.4 / 12.5 / 8.3; flip net block +2 [6h/4hurt] / rewind −3 [4h/7hurt]; 18 rewinds
  across 4 runs, 5 no-op, 0/4 success): `live_ab.py --tasks 12 --arms none block
  rewind --domains itsm csm hr email --mint-rate 0.40 --mint-seed 42 --out
  live_results_rewind_pilot` + `mattered_join.py --out live_results_rewind_pilot
  --arms block rewind`, run 2026-06-05. Output dir gitignored (re-derivable); the
  scored numbers live here.
- block-arm replay (6 thrash / 6 fired / 18 appends eliminated / 46 turns / 0-6
  success): `rewind_counterfactual.py --json`, run 2026-06-05 over
  `live_results/block/*.json` (78 files).
- four-arm baselines (none 40.2 / defer 42.2 / warn 46.4 / block 40.2 verifier-pass;
  none 10.3 / defer 12.8 / warn 15.4 / block 10.3 success; flips defer +7 / warn +12 /
  block −6): fresh re-parse via `score_ab.py` (paired n=78) and `RESULTS.md` /
  `THEORY_LADDER.md` / `measurements.jsonl`, all as of 2026-06-05. The recorded
  `live_results/_summary.json` is a **stale n=12 snapshot** — do not cite it; re-parse.
- 0/406 natural mint rate, 0.00pp strong-model conversion ceiling, +2.40pp corpus
  max: the prior bimodal ruling (docs/170, the weak-plus-substrate significance
  memory, strategy `a176816`).
- rewind kernel surface (31 tests, the three load-bearing properties, the
  `SuspendCheckpoint` additive extension): `src/dos/rewind.py`,
  `src/dos/rewind_tokens.py`, `src/dos/rewind_evidence.py`, `tests/test_rewind.py`.
- consumer wiring (`_maybe_rewind`, the 2nd-block escalation, the `rewind` arm):
  `benchmark/enterpriseops/dos_react.py:479-583,758-766`, `live_ab.py:72`,
  `test_rewind_arm.py` (2 pass). Launched once live on 2026-06-05 22:42
  (`_rewind_smoke.log`), no scored result yet.
