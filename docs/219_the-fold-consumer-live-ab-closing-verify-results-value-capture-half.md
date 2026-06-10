# 219 — The fold-consumer live A/B: closing `verify-result`'s value-capture half

> **`dos verify-result` (docs/197 §7(1)) shipped a sound, byte-clean catch for a
> 31.8%-prevalence failure — the harness-authored `<synthetic>` death an ultracode
> `Workflow` folds as a "finding." Detection is done and re-measured. The binding
> constraint was never detection (docs/188/190: *detection SOLVED, value-capture is
> the open problem; change the CONSUMER not the threshold*). This doc designs the one
> thing docs/197 §9.1 named open and did not design: a LIVE A/B of a fold-CONSUMER
> that acts on exit 3. Its load-bearing claim is that this consumer is the rare one
> that can escape the docs/205 net-negative trap — because, unlike every active fix
> that perturbed PASSING runs, it fires only on a confirmed-DEAD child (work already
> and certainly lost), so re-dispatching the dead child's OWN unit is purely
> ADDITIVE and cannot perturb a healthy fold. That is also the docs/151 safe action
> verbatim: re-dispatch the dead child, never re-prompt the synthesizer.**

This is a mechanism/experiment design doc in the house style of
[`197`](197_how-dos-is-directly-useful-to-ultracode.md) (the fold-site frame it
extends), [`190`](190_coordination-measured-and-the-f3-gateability-split.md) (the
"$0 real-corpus measure, then a live A/B" shape), and
[`205`](205_growing-the-fix-story-the-curable-conversion-arm.md) (the fix-story
arm whose net-negative result is the foil this consumer must clear). It builds **on
top of** docs/197 — it does not restate it. Where 197 §7 proposed the catch and §9.1
declared the consumer "started but the live A/B genuinely open," this designs that
A/B: the arms, the metric, the safe-consumer spec, the confound controls, and the
dogfood-on-self option — plus the honest case that it might still lose, and how
we'd know.

> **This doc argues both sides.** [§7](#7-steelman--the-strongest-case-against-running-this)
> steelmans the four objections that would sink it (it's just retry/backoff · the
> harness should own this · it'll go net-negative like every other cure · N is too
> small to prove anything).

---

## 1. The open question — detection is sufficient for a verdict, not for value

The fold problem has two halves and they have very different status:

- **Detection — SHIPPED and re-measured.** `result_state.verify_transcript(path)` +
  `dos verify-result` classify a subagent transcript's terminal record
  (`HEALTHY`/`SYNTHETIC`/`EMPTY`/`UNREADABLE`; `.dead`), gated on the unforgeable
  `model == "<synthetic>"` marker (broader than 429 — 43% of synthetic deaths are
  not 429). It is byte-clean: the catch reads a *different byte-author* (the CC
  harness's own stamp) than the judged worker.
- **Value-capture — OPEN.** docs/197 §9.1 is blunt: *"a new sound detector is
  necessary and not sufficient; the next unit of value is a CONSUMER, not a sharper
  verdict... **0/114** real workflow scripts call any `dos` verb, so the verb is
  inert until a consumer invokes it and acts on exit 3."* The conversion-gap
  (docs/188/190) is the standing law: **change the consumer, not the threshold.**

So the question this doc answers is not "can we catch the death?" (yes) but **"does
acting on the catch recover net-positive work on a real denominator?"** — and that
is an experiment, not an assertion.

---

## 2. What is already shipped (so this plan builds, not rebuilds)

A probe-first inventory, because the temptation is to re-propose what exists (the
docs/171/probe-before-build discipline). All three of these are LANDED:

| Surface | Module / verb | What it does | Status |
|---|---|---|---|
| Per-fold catch | `result_state.verify_transcript` / `dos verify-result` | classifies one transcript's terminal record; exit 3 = DEAD | SHIPPED (docs/197 §7(1), `f43db8d`) |
| Per-workflow aggregate | `coverage.classify_coverage` / `dos coverage` | folds N per-fold verdicts vs. a `--declared N` (independent of the survivor list) → FULL/UNDERFILLED/STARVED/…; `prompt_line` is the legible caveat fed INTO synthesis | SHIPPED (`acffb4a`) |
| Real-corpus measure | `benchmark/fleet_horizon/measure_fold_deaths.py` | runs the verdict over every `~/.claude/projects/**/subagents/workflows/*/agent-*.jsonl` and reports the fold partition | SHIPPED (docs/197 §9.1, `c449f76`) |

**The measure, re-run 2026-06-07 on this machine (fresh, dated — supersedes the
docs/197 §9.1 figure of 31.2%/4,698):**

```
workflow subagent transcripts: 5460
  states: {SYNTHETIC: 1732, HEALTHY: 3723, EMPTY: 5}
  DEAD (harness-authored / empty): 1737/5460 = 31.8%
  fold partition:
    .filter(Boolean) would BANK : 5460   (banks 1737 harness-deaths as 'findings')
    verify-result would BANK    : 3723   (HEALTHY only)
    → routed to DEAD bucket     : 1737   (counted, refused, re-dispatchable)
  death concentration: 80 workflows lost ≥1 subagent;
    wf_e5a61226-e18 475/595 (80%), wf_516412fb-5cc 168/178 (94%),
    wf_f9b0c9e5-af3 161/174 (93%), wf_152c7778-165 107/118 (91%) …
```

So the prevalence holds on a larger corpus, and the **concentration** (waves where
80–94% of a fan-out died together) is the load-bearing structural fact for the
experiment design below — the deaths are *bursty*, not i.i.d.

**The corrected premise (a staleness fix worth stating):** the strategy-side framing
that "the dogfood is buildable now" (dispatch-os-the-harness-reference-monitor §8)
is out of date — the dogfood *detection and measurement are built*. What is buildable
now is the **consumer A/B**, which is a different and harder thing.

---

## 3. Why this consumer can escape the net-negative trap (the key insight)

Every active fix DOS has measured went flat-to-net-negative: the WARN-frontier bet
(docs/188, 0.2% fire, 0 substantive), and — most relevantly — the docs/205 curable-
conversion cure, which **ran (176 runs) and was net-negative (−5 success)**: it
converted where aimed (+2) but the *fire perturbed baseline-passing runs* (−7,
p=0.016). docs/205's verdict: *the harm is the intervention's EXISTENCE in the loop
(turn-injection perturbs passing runs), not its byte-clean content; only the
NEGATIVE fix (give-up-correctly) survives.*

The fold-death consumer is structurally different on the one axis that caused that
harm, and the difference is the whole reason to run this:

> **The docs/205 cure fired on a *heuristic* ("this run thrashed"), so it could fire
> on a run that would have PASSED — and the act of firing perturbed it. The
> fold-death consumer fires only on a verdict that is *certain and terminal*: a
> `<synthetic>` death means that child produced NO deliverable, full stop. There is
> no passing run to perturb — the work is already lost. Re-dispatching the dead
> child's own unit is therefore purely ADDITIVE: it can only move a lost fold from
> "silently banked as a null/finding" to "recovered or still-lost." It never touches
> a HEALTHY fold.**

This is the same structural property that made `verify`-on-stop and give-up-correctly
the survivors: the safe consumer acts on a *non-forgeable, terminal* fact, not on a
predictive heuristic about a live run. The fold-death consumer is the *positive*
member of that safe class — the first active fix whose trigger cannot, by
construction, perturb a passing path. (If the A/B still shows no net gain, that is
itself a finding — see §6 — but it would be a *different* failure mode than docs/205's
turn-injection harm.)

And it is the docs/151 safe action exactly: **re-dispatch the dead child's own unit;
never re-prompt the synthesizer mid-plan** (the −9pp DEFER-shaped derail docs/151/143
measured). The synthesizer is downstream of the fold; perturbing it is the harm. The
child's own unit is upstream and already-failed; redoing it is recovery.

---

## 4. The experiment design

**Population.** Real ultracode workflows with a fan-out stage (`parallel()` /
`pipeline()`), drawn from the live corpus the measure already enumerates. The natural
dogfood is **DOS's own doc-writing / audit workflows**, which §2.3/§9.3 show exhibit
the pathology (a doc-writing wf died 4/6 yet reported `completed`). Dogfooding keeps
the loop fully in our control and needs no external party — the docs/207-style "DOS
on DOS" ritual, applied to the fold.

**Arms** (the consumer is the only thing that varies; the workload is fixed):

| Arm | The fold consumer | Expectation |
|---|---|---|
| **A — baseline** | `.filter(Boolean)` (today): a dead child's non-null error string is banked or silently subtracted | the status quo; deaths laundered into the denominator |
| **B — witness-routed re-dispatch** | run `verify-result` one line before `.filter(Boolean)`; on exit 3, route the child to a DEAD bucket and **re-dispatch that child's own unit** (bounded retries, with backoff for the rate-limit class) | the hypothesis: recovers lost deliverables, additive, no healthy-fold perturbation |
| **C — re-prompt synthesizer** *(negative control)* | on exit 3, inject a correction into the synthesis prompt (the docs/151 −9pp shape) | included to REPRODUCE the known derail and prove B's gain is from re-dispatch, not from "doing something" |

Arm C is deliberately the thing docs/151 already showed loses; running it confirms
the mechanism is the *re-dispatch*, not the intervention's mere presence — the
control docs/205 wished it had.

**The metric — deliverable completeness, not "success."** The headline is
**recovered-deliverable rate**: of the folds that were DEAD in arm A, how many produce
a real (HEALTHY) deliverable under arm B within the retry budget? Secondary:
end-to-end **synthesis completeness** (did the final synthesis see a full-quorum input
vs. a silently-subbed one — `coverage` FULL vs. STARVED), and **cost** (the re-dispatch
token spend vs. the value of the recovered work — the [docs/128](https://github.com/anthony-chaudhary/dos-strategy/blob/master/128_the-ultracode-economics-and-how-the-kernel-saves-spend.md) spend frame, now in `dos-strategy`). The
metric is presence-of-deliverable, NOT correctness of it (§6).

**The safe-consumer spec** (what arm B may and may not do):
- MAY: count the death in the denominator (`coverage` already does); re-dispatch the
  *child's own unit* with bounded retries; apply class-aware backoff (the death class
  is `RATE_LIMIT` 99% of the time — re-dispatch into the same rate-limit wave is
  futile, so back off past the wave, §5); feed the real `coverage.prompt_line` into
  synthesis so a sub-quorum fan-out is never laundered as full.
- MUST NOT: re-prompt the synthesizer mid-plan (arm C, the derail); kill or restart a
  HEALTHY child; treat UNREADABLE as DEAD (the fail-safe floor); fold a re-dispatched
  child without re-running `verify-result` on *its* terminal (no laundering the retry).

---

## 5. Confounds and controls

The 429 death is **exogenous and bursty**, which creates two confounds the design
must control or the A/B will mislead:

1. **The rate-limit wave.** The concentration data (§2: 80–94% of a fan-out dying
   together) means deaths arrive in correlated bursts driven by an account-wide
   rate limit, not per-child bad luck. A naive immediate re-dispatch hits the *same*
   wave and dies again — so arm B would look worthless for a reason that is about
   backoff timing, not about the consumer. **Control:** class-aware backoff (re-
   dispatch the `RATE_LIMIT` class only after a delay past the wave; measure
   recovered-rate as a function of backoff), and report wave-size alongside recovery
   so a futile-because-still-rate-limited result is not misread as "re-dispatch
   doesn't help."
2. **Selection toward terminal/observable runs.** Like firing_label's run-terminal
   bias (docs/179), the measure sees only completed workflow fossils. **Control:**
   restrict the A/B to workflows that ran to a terminal state in both arms; report
   the excluded in-flight count (the "no silent caps" rule).
3. **Spend confound.** Re-dispatch costs tokens; a "recovered work" win that costs
   more than the work is worth is not a win. **Control:** report recovered-deliverable
   rate AND net token cost; the verdict is the pair, not the rate alone (docs/128).

### 5a. The $0 de-risking measure (run 2026-06-07): the recovery window is short — arm B is predicted viable

Per docs/190's "measure the rate before you spend on the run,"
`benchmark/fleet_horizon/measure_fold_recovery.py` answers confound #1 (the wave)
directly from the **5,465** fossils on disk — reusing the SHIPPED `result_state`
verdict for the dead/healthy split and the `measure_real_collisions` timestamp
parser. For each of the **1,732** harness-deaths it measures the gap to the next
**account-wide HEALTHY** subagent completion — the minimum backoff a re-dispatch
(arm B) would need, since a `<synthetic>` limit is account-level and a healthy
completion *anywhere* proves it had lifted. The result is decisive and cuts FOR
arm B:

| Recovery window (death → next account-wide healthy completion) | Value |
|---|---|
| deaths measured | 1,732 |
| recovered eventually (in corpus) | **1,732 (100%)** — 0 never recovered |
| median gap | **31.1 s** |
| recovered within 60 s / 5 m / 30 m / 1 h | **65.5% / 82.5% / 88.6% / 99.9%** |
| p90 gap | 52 m |
| wave structure | 38 waves, max 279 deaths, **median wave duration ~12 s**, median wave-recovery ~51 s |

The read: **the rate-limit waves are soft and transient (median duration ~12 s,
recovery ~31 s), not account-level-hours.** So the §5 confound that could have killed
arm B — "re-dispatch hits the same wave / the account stays dead for hours" — is
*empirically small*: a modest backoff (≥1–5 min) would land a re-dispatch in a healthy
window for the large majority of deaths, and *every* death in the corpus eventually
had a healthy window. Arm B is predicted **viable, not futile.** This moves docs/219
from "designed" to "designed + the decisive de-risking measure run, strongly
positive" — the docs/190 "$0 measure → land the prediction → then spend on the run"
ladder, one rung up.

**The caveat that keeps it honest (and is exactly what the live A/B must still
settle).** This measures the *recoverability ceiling* — that a healthy window existed
when a re-dispatch could have landed — **not** the realized *recovered-deliverable
rate*. A re-dispatched unit might still fail for a reason unrelated to rate-limits (an
inherently hard task, a different error), and it carries the backoff latency + token
cost (§5 confound 3). So the measure says arm B is *not blocked by wave-futility*; it
does not say arm B *succeeds* — that gap (ceiling vs. realized) is precisely the §4
live A/B's job. The §3 structural-safety argument (it cannot perturb a healthy fold)
plus this short recovery window make the live A/B a **high-prior bet**, not a settled
result.

### 5b. The A/B-by-construction (run 2026-06-07): arm B recovers ~89% of lost work and launders none; arm C is the harm

The live A/B cannot be run on demand (a `<synthetic>` death needs a real rate-limit),
so `benchmark/fleet_horizon/fold_consumer_ab.py` is its runnable form (the FleetHorizon
synthetic tradition): the arm-B CONSUMER as real, tested code (`consumer_recovers` +
`RetryPolicy` — the logic the live A/B would deploy, where the DEAD gate is
`dos verify-result` in production), plus an A/B-by-construction whose recovery dynamics
are **sampled from the §5a measured gap distribution**. Two results.

**(1) Realized recovery vs. backoff** (the realized version of §5a's ceiling, now under
a finite retry budget):

| backoff × max-retries | recovered |
|---|---|
| 60 s × 3 / × 5 | 83.8% / **89.3%** |
| 5 m × 3 / × 5 | 91.3% / **100%** |
| 15 m × 3 | 99.9% |

A *modest* policy (60 s backoff, 5 retries) hits a clean window for ~89% of deaths; a
5-minute backoff recovers ~all. Ceiling (§5a: a window existed) and realized rate (§5b:
a window is hit within budget) agree — the waves do not block re-dispatch.

**(2) The three arms on a ground-truth fan-out** (10,000 units, 3,174 injected deaths
at the measured 31.8% rate, achievable ceiling 8,521 deliverables):

| Arm | Deliverables | Deaths laundered as "findings" |
|---|---|---|
| **A** — `.filter(Boolean)` (today) | 5,831 | **3,174** (all of them) |
| **B** — witness-routed re-dispatch | **8,229** (+2,398 = **89.1% of lost** recovered) | **0** |
| **C** — re-prompt synthesizer (control) | **4,208** (**−1,623 vs A**) | 3,174 |

This is the whole thesis in one table, demonstrated rather than asserted: **arm B is
purely additive — it recovers 89.1% of the silently-lost deliverables and launders
zero (it counts un-recovered deaths in the denominator instead of banking their error
strings as findings) — while arm C, the re-prompt, drops 1,623 *below* baseline by
perturbing passing siblings (the docs/151 −9pp shape, reproduced).** The B-vs-C gap is
the docs/205 lesson made visual: the safe consumer acts on the *dead* child (additive);
the unsafe one perturbs the *healthy* ones (harm). Pinned by `test_fold_consumer_ab.py`
— the invariants (B ≥ A, B-laundered = 0, C ≤ A) hold for every seed, by construction.

**Still the honest boundary (unchanged).** This is a simulation: it settles the
*mechanism* and predicts the realized recovery *rate* under measured waves; it does not
settle the live *payoff* — the real token cost of the re-dispatches, and whether a
re-run unit yields a *correct* (not merely present) deliverable (Wall §3). Those need
the live run §4 still owes. What is now established: arm B is structurally safe (§3),
the waves don't block it (§5a), the mechanism recovers what arm A drops (§5b), and arm
C is the harm to avoid. **The remaining unknown is realized payoff, not viability.**

---

## 6. Honest limits — what a positive result would and would not prove

- **Presence, not correctness.** A recovered child produces *a* deliverable; that the
  deliverable is *correct* is the Wall §3 ceiling `verify-result` never claims. The
  A/B proves the fold stops silently dropping work, not that the work is right. The
  honest headline is "fewer silently-lost deliverables," never "more correct
  syntheses."
- **It may still show no net gain — and that's a real finding.** If the rate-limit
  waves are wide enough that backoff can't recover within budget, arm B's recovered
  rate could be ~0 — not because the consumer is unsafe (it isn't; it never perturbs
  a healthy fold), but because the lost work is unrecoverable *while the account is
  rate-limited*. That would be a DIFFERENT result than docs/205's net-negative: there
  the fix did harm; here the fix is harmless but possibly futile. Distinguishing
  "harmless-and-helpful" from "harmless-but-futile" is the experiment's real job.
- **Advisory, still.** Arm B's re-dispatch runs in the *workflow's* code (the host),
  not the kernel — the kernel only supplies the exit-3 verdict. The PDP/PEP line
  (docs/114) holds: DOS reports DEAD; the workflow decides to re-dispatch.
- **The enumerator is benchmark-local.** `measure_fold_deaths.py`'s glob and
  `dos coverage`'s explicit-paths input both work, but there is no `dos coverage
  --workflow <wf_id>` that auto-enumerates a run's folds from the spine. Lifting that
  glob into a shared kernel boundary is a small, optional follow-on (it would let the
  A/B harness and the benchmark share one enumerator) — noted, not required for the
  A/B.

---

## 7. Steelman — the strongest case against running this

- **"This is just retry-with-backoff — you don't need a 'witness' for it."** Partly
  fair for the rate-limit class alone. But the witness is what makes retry *correct*:
  `.filter(Boolean)` cannot tell a dead child from a real negative, so a blind retry
  would also re-run genuine negatives (waste) and still launder the deaths it missed.
  The byte-clean `<synthetic>` gate is precisely what scopes the retry to confirmed
  deaths and nothing else. *Resolved: the verdict is the part that makes the retry
  safe and targeted; the retry is the consumer the verdict was missing.*
- **"The harness (ultracode/Claude Code) should own death-retry, not DOS."** Ideally
  yes — and if it does, DOS's job is done at the verdict. But today **0/114 scripts
  and the runtime itself do not** (docs/197 §2.2: no retry/backoff on the 429
  anywhere). DOS supplies the missing verdict in a portable form; whoever owns the
  loop can consume it. *Resolved: this is the conversion-gap answer — provide the
  verdict the consumer needs; the consumer can be the harness, a workflow stage, or
  the conductor.*
- **"Every active fix you've measured went net-negative; this will too."** The
  central objection, and §3 is the whole reply: those fixes fired on *heuristics* and
  perturbed *passing* runs; this fires on a *certain terminal* fact and touches only
  *already-lost* folds, so the docs/205 harm mechanism (turn-injection on a passing
  path) is structurally absent. It may be futile (§6) but it cannot do that harm.
  *Resolved: this is in the safe class with give-up-correctly, and is its positive
  member — the test is whether additive recovery beats backoff futility, not whether
  it perturbs.*
- **"N is too small — a few dogfood workflows won't prove anything."** Real risk at
  N=1-scale, the cluster's standing caveat. But the *denominator* is large and
  measured (1,737 deaths across 80 workflows), and the A/B's unit is the **fold**,
  not the workflow — a single multi-wave workflow contributes dozens of dead-fold
  trials. *Resolved: power the A/B on folds, not workflows; report per-fold recovery
  with the wave-size covariate, and treat the first run as a calibration of effect
  size, not a verdict (the docs/190 "$0 measure → live A/B" ladder).*

---

## 8. One-line synthesis

**`verify-result` made a 31.8%-prevalence silent fold-death visible and refusable;
the open work is a CONSUMER, and the fold-death consumer is the rare active fix that
can escape the net-negative trap — because it fires only on a confirmed-dead child
(work already lost), so re-dispatching that child's own unit is purely additive and
can never perturb a healthy fold, exactly the docs/151 safe action; the A/B's real
question is therefore not "does it harm?" (it structurally cannot) but "does additive
recovery beat rate-limit-wave futility?", measured per-fold on DOS's own workflows.**
