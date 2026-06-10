# docs/201 — The full-corpus re-score, and the give-up-correctly arm

> **The livelock line's conclusions were scored on a subset 5–25× smaller than the
> corpus that was actually sitting on disk. Re-run on the full 240-runs/arm natural
> A/B (480 runs), the picture sharpens decisively: a confirmed same-tool thrash is
> *empirically disjoint from task success* — no winning run on the corpus ever
> reaches even two structured errors on a single tool — so the load-bearing value
> is GIVE-UP-CORRECTLY (early-halt), and it is verifiably sound at K≥3 *run-locally,
> with no corpus knowledge*. That is the one deployable, byte-clean lever the whole
> line was circling. Conversion on the curable slice stays OPEN-but-underpowered;
> the schema-refresh mechanism ([[docs/200]]) is constrained, not refuted, by the
> "tool recovers 10/11, task succeeds 0/11" fact.**

Status: **MEASURED CORRECTION + a buildable, verified-sound arm.** Re-scores
[[docs/198]] (the feasibility split) and [[docs/194]] (the livelock) on the full
corpus; constrains the two concurrent siblings [[docs/199]] (the curable-slice
live A/B) and [[docs/200]] (the schema-refresh forcing function) with corpus-scale
power facts they were written without. Every number below comes from a `$0` python
run over the real corpus
(`benchmark/enterpriseops/live_results_natural_ab/{none,rewind_natural}/results_*.json`,
240 runs/arm, 480 total) using the byte-clean `dos_react` grammar; reproduce with
`python feasibility_witness.py --ks 2 3 4 5` and the `_probe_*`/`_verify_*` scratch
instruments named inline. Produced by a 28-agent divide-and-verify workflow
(`wf_dbb0b712`), every load-bearing claim adversarially re-run over the real files.

Parent: [[docs/198]], [[docs/194]], [[docs/177]] (the frontier→verify() decay
ceiling), [[docs/144]] (the advisory intervention ladder the halt rides),
[[docs/99]] (the actuation boundary — propose, never kill).

---

## §0 — What was off: a subset, not the corpus

docs/194/198 were scored on `n≈47–98` runs and concluded "conversion refuted /
detection-only," then corrected (docs/198 §0.0) to "give-up-correctly on the walled
slice; conversion untested on the curable slice." Both were measured on a *slice* of
what was on disk. The natural A/B directory actually holds **240 runs per arm (480
total)** — `none` and `rewind_natural`, every run a distinct task (239 distinct
prompts/arm; 158 prompts paired across arms at n=1 each; `_verify_corpus_pairing.py`).
Re-running on the full corpus does not overturn the corrected headline — it
**hardens** it and exposes a sharper deployability boundary than docs/198 drew.

---

## §1 — The headline: a confirmed thrash is disjoint from success

On the `none` arm (240 files, **22/240 = 9.2% task-success** — the task is brutally
hard), a **run-local** give-up gate — "first tool to reach K structured env-errors,
the Kth still erroring" — fires on **23 runs at K=2, and 0 of them succeed at the
task.** False-abandon (a fired run that nonetheless wins) is **0.000 at every K in
{2,3,4,5}** (fires 23 / 15 / 13 / 9; `feasibility_witness.py`).

This is stronger than docs/198 §2's framing ("there are no winning `create_filter`
runs to kill"). The deeper structural fact (`_probe_track1.py`, `_verify_killer.py`):

> **No task-winner anywhere on the `none` arm reaches even 2 structured errors on any
> single tool.** The max single-tool error count over all 22 winners is ≤1. The
> histogram of max-tool-error over the 220 non-empty runs is
> `{0:142, 1:55, 2:8, 3:2, 4:4, 5:1, ≥6:8}` — and *every* run with a ≥2-error tool is
> a task-failure.

So the gate cannot land on a winner at any K≥2 *by structural separation*, not by a
lucky threshold. And crucially, **FA=0 is not a walled-only artifact**: at K=2, **13
of the 23 fires are on corpus-CURABLE or mostly-walled tools, and 0/13 succeed**
(`cats = {walled:10, curable:11, mostly-walled:2}`). A confirmed K=2 thrash predicts
task-doom *even on a tool that succeeds elsewhere* — the same fact docs/198 §3.1
reported as "tool recovers, task fails."

---

## §2 — The deployability boundary (sharper than docs/198 drew it)

docs/198 §2 proposes "fire harder when the thrashing tool is WALLED in the
run/corpus," treating run-local and corpus knowledge as interchangeable. **They are
not**, and the distinction is the whole story for what can ship:

- **The corpus-wide WALLED/CURABLE witness is NOT a run-local gate input.** At the K=2
  fire point, *every* fired tool has 0 prior in-run successes — a corpus-CURABLE fire
  is byte-identical to a corpus-WALLED one from inside one run (`_verify_runlocal_soundness.py`).
  The witness's discriminating signal ("0 successes across all 480 runs") needs
  persisted fleet state; the run-local half ("0 successes *so far this run*") does not
  discriminate a wall from a not-yet-recovered curable tool. **The feasibility witness
  is a scheduler/corpus asset, not a per-run gate input.**

- **Consequently the plain run-local gate is unsound at K=2 on the pooled corpus.** It
  false-halts exactly **1 genuine winner** across all 480 runs (`_probe_witness2.py`,
  independently `_verify_witness_claim.py`): the `rewind_natural`
  `link_knowledge_to_incident` run that errored twice on wrong incident-ids
  (`INC-000001`, `INC-000044` → `RESOURCE_NOT_FOUND`), then resolved the real id via
  `find_incident_by_number` (→ `INC_001`), retried, and **succeeded** (`overall_success=True`).
  This is the canonical curable arg-provenance recovery the run-local "0-successes-so-far"
  signal cannot tell from a wall.

- **But K≥3 restores soundness with no corpus knowledge.** The identical plain
  run-local gate shows **false-halt = 0 on BOTH arms at K=3 and K=4** (none 15/0, 13/0;
  rewind 16/0, 10/0; `_probe_winner_thrash.py`, `_verify_armspecific.py`). The one
  winner that thrashes only reaches K=2, so K=3 steps over it. **K=3 is the deployable
  provably-sound threshold; K=2 trades ~8 extra fires for a 1-in-480 false-halt.**

- **The corpus-walled-guarded variant (RLCW)** — fire iff run-local-K AND tool ∈
  corpus-WALLED — is sound at *every* K on both arms (it only ever fires on
  `create_filter`, which has 0 winners by construction), but its `t in WALLED` test is
  corpus-derived, so it is **NOT-DEPLOYABLE-AS-IS** until a persisted fleet-WALLED table
  exists. It is a backtest comparand, not a live gate.

The witness display also hides a third category: `create_draft` is `2 ok / 22 err`
("mostly-walled"), and the WALLED set at `err>0` is actually four tools
(`create_filter`, `create_send_as_alias`, `update_draft`, `update_send_as_alias`) —
only `create_filter` clears the `min_err≥5` display floor (`feasibility_witness.py:122`).
Immaterial to FA (all four have 0 winners), but the binary witness collapses it, and a
deployable gate that fires on `create_draft` run-locally is *sound* (0 false-halts) and
costs ~0 conversions (its 2 successes are a single double-counted task,
`_verify_create_draft_claim.py`).

---

## §3 — Conversion on the curable slice: still un-answerable at 240/arm

This **constrains [[docs/199]] and [[docs/200]]**, both written before the corpus-scale
power facts:

- The curable-thrash slice — runs with a ≥2-error thrash on a corpus-CURABLE tool — is
  **12 (none) / 11 (rewind)** under the natural reading, **0 task-success on the none
  arm, 1 on rewind** (`_probe_conversion.py`, `_verify_curable_conversion_adv.py`). This
  corrects the prior loose "15."
- **The corpus is short by 13–88 paired curable-thrash tasks.** A paired McNemar test
  with base 0/12 and 0 hurt-flips needs ≥6 help-flips for two-sided p<0.05; expecting 6
  flips needs ~25 tasks at an optimistic 20% conversion, ~50 at 10%, ~100 at 5%. Current
  power at the 12-task slice is **<7% even if true conversion were 20%**
  (`_verify_power.py`). **docs/199's "n≥30" target is itself underpowered** for any
  realistic conversion rate.
- The `rewind_natural` arm **already fired real live conversion attempts** on its
  curable-thrash runs (the corpus contains genuine re-orchestrated post-rewind turns) and
  won 0–1/11 — so the blocker is sample size, not "the next turns are missing"
  (`_verify_rewind_conversion_power.py`). The one rewind win is **not causally
  attributable** (arms re-seed independent DBs; the won task is not even present in the
  none arm).
- docs/198 §3.1's load-bearing mechanism reproduces at full n: among none curable-thrash
  runs the thrashing tool **recovers in 10/11 yet the task succeeds 0/11**
  (`_verify_198_mechanism.py`). The cleaner, powered form (the per-slice 0/11 is
  base-rate-consistent): across all 240 runs, thrash-and-recover = 0% success and
  thrash-and-NOT-recover = 0% success (identical), vs no-thrash 10.1%
  (`_verify_198_confound.py`). **Recovery of the tool does not move task-success.**

The consequence for **[[docs/200]]** (the schema-refresh forcing function): its premise
is that re-surfacing the env's own correction converts a curable thrash. The data says
the curable thrash *already recovers the tool 10/11 times on its own* and the task still
fails 0/11 — so making the env correction un-ignorable buys a tool-call success that
does not buy a *task* success. docs/200's mechanism is **byte-clean and correctly
scoped** (it never authors the schema), but it is constrained to a sub-class where the
thrashed tool is the *binding* constraint — and on this corpus the thrash is a *symptom*
of a multi-goal hard task, not the binding constraint. Not refuted (it was never powered
either), but the prior should be set against task-level conversion, exactly as docs/199's
own A/B is now pre-registered to expect.

---

## §4 — The regime call

Early-stopping ("give-up-correctly") is a **scheduler value, not a per-run capability
lift**: re-budget the doomed branch's tokens to a sibling. It creates value on the
walled + curable-but-task-hard structured-error populations, purely as cost/throughput
aversion. The honest token denominator (a verifier refuted the "char/4 is the only
proxy" premise): the corpus *does* carry real telemetry —
`conversation_flow[*].usage_metadata` on 240/240 none files, summing to **11.2M
total_tokens** (`_verify_token_denom.py`). On the real denominator the K=2 give-up
saving is **~14.9%** (structural tail-fraction), larger than the 9.4% result-payload
proxy, because spend is dominated by the growing per-turn input/cache context each
suppressed tail-turn would re-pay.

**Honest ceiling.** Single corpus; single model (N=1 on the model axis — all 480 files
are `google/gemini-2.5-flash`); docs/177 shows the structured-error signal decays on the
frontier (a sibling detector fired 0/321 on Gemini-3-pro); the value is ~0 at N=1
(throughput needs fan-out, and the corpus is one serial agent per run). Conversion on the
curable slice is **OPEN, not refuted** — it was never powered, and docs/199's planned
spend is the right (if itself underpowered) next move.

---

## §4a — What K is, and the two-clocks reading of "delta"

**What K means.** K is the **patience knob**: the gate fires the instant *one tool*
accumulates **K structured env-errors in a single run with the K-th call still
erroring** (the agent is in the hole right now, not recovered). It is the only
free parameter of the run-local give-up gate. Lower K = less patient (fire sooner,
catch more doomed branches, but risk halting a branch that would have recovered);
higher K = more patient (wait for stronger evidence of a wall, fire less, save
fewer tokens). The corpus turns this abstract trade into a concrete cliff:

| K | pooled fired | winners halted | verdict | none-arm real-token save |
|---|---|---|---|---|
| **2** | 47 | **1** | **UNSOUND** (halts a curable arg-provenance recovery) | 14.9% |
| **3** | 31 | 0 | **SOUND** (cross-arm) | 13.0% |
| 4 | 23 | 0 | sound | 12.3% |
| 5 | 16 | 0 | sound | 11.1% |

The single winner that K=2 kills is a real recovery (`link_knowledge_to_incident`
errored twice on wrong incident-ids, then resolved the id and succeeded). It only
ever reaches **2** same-tool errors, so **K=3 steps over it** — that is the entire
reason K=3 is the default. The price of the extra patience is small and monotone:
~8 fewer fires (47→31) and ~2 percentage points of saving (14.9%→13.0%). **K is the
dial that buys soundness with patience**, and on this corpus the sound setting is
cheap.

**The two clocks — why "is there a delta yet?" has two answers.** The line carries
two *different* measurements, and they scale completely differently:

1. **The give-up (early-halt) value is a WITHIN-RUN decision and is ALREADY
   powered.** Its "delta" is not a between-arms success difference — it is
   *tokens-not-spent* on a branch the same corpus shows is doomed (a confirmed
   thrash → 0% task-success, structurally disjoint from the 22 winners). That is a
   single-population fact measured over **all 220 non-empty none runs** and it does
   not need a second arm or more data to be real: at K=3 it fires on 15 runs,
   halts 0 winners, and averts **~13% of real fleet tokens** (1.44M of 11.2M).
   More data would tighten the FA confidence band (the soundness claim rests on
   "0 winners in 22" — Wilson-95 upper ≈ 0.14, so "provably 0" should read "0
   observed, ≤14% with 95% confidence"), but the *direction and magnitude already
   show*.

2. **The conversion (cure) value is a BETWEEN-ARMS comparison and is NOT yet
   showing — and 240/arm is still too small to make it show.** Here is the actual
   delta picture on the full corpus (`giveup_arm`/`_probe_conversion`, pairing by
   `benchmark_config.user_prompt`):

   | slice | n (paired) | help-flips | hurt-flips | net delta |
   |---|---|---|---|---|
   | all paired tasks | 158 | 27 | 21 | **+6 (noise)** |
   | **CURABLE-thrash only** | **13** | **0** | **0** | **+0** |

   On the slice that matters — paired tasks that thrash a *curable* tool — **all 13
   both-fail; there are zero discordant pairs**, so a McNemar/sign test has *nothing
   to test*. This is not "conversion refuted"; it is "the experiment has n=13 where
   it needs far more."

**What larger data size would make a conversion delta appear?** The power
arithmetic (two-sided McNemar, base 0 hurt-flips, needs ≥6 help-flips for p<0.05):

| true conversion rate | paired curable-thrash tasks for E[6 flips] | for 80% power |
|---|---|---|
| 30% | ~20 | ~25 |
| 20% | ~30 | ~39 |
| 10% | ~60 | ~78 |
| 5% | ~120 | ~157 |

So at a *plausible* cheap-model conversion rate (5–10%), you need **~60–157 paired
curable-thrash tasks** — the current corpus (13) is **short by ~47–107**. Crucially,
because curable thrashes are only ~5% of runs, harvesting them at the natural rate
would need **~1,000–3,000 total runs**; the efficient path is **oversampling** —
pre-select tasks known to thrash a curable tool and run *those* (this is exactly
what docs/199's `curable_oversample.py` does). And note the deeper ceiling §3
already established: even with that data, the cure has to beat the fact that the
curable thrash **recovers the tool 10/11 times on its own yet the task still fails
0/11** — the binding constraint is task difficulty, not the tool call, so the
expected conversion rate is low and the required n is therefore at the **large
(~150-task) end**. **docs/199's "n≥30" target is itself only powered for a ~20%+
conversion rate** — optimistic for this class.

The one-line implication: **give-up-correctly is the value you can bank today
(within-run, powered, ~13% token save at sound K=3); conversion is the value that
is still un-measured and needs a deliberately-oversampled ~150-task curable A/B
before any delta could appear.**

---

## §4b — K is a tunable error threshold: the literature, the prior art, the novelty

K is not an ad-hoc counter — it is the **operating point of a one-sided sequential
detector under an asymmetric cost.** Sweeping K traces a discrete
operating-characteristic curve (§4a's table), and the K=2→K=3 step is a near-vertical
ROC segment: you buy full specificity (false-abandon 1→0) for ~34% of the fires.
Two literature/prior-art sweeps (a 26-agent workflow `wf_a61a3f8a` + a dedicated
online prior-art search, each citation adversarially verified) place this precisely.

**The honest deflation (state this first, loud).** Mechanically, the K-gate is a
**circuit breaker on a single tool, lifted to the agent loop** — the OPEN-trip half of
the Circuit Breaker pattern (Nygard, *Release It!*, 2007) without the half-open recovery
probe, and equivalently the run-local loop-guard cutoff (`max_iterations`, ">N invalid
actions") shipped by agent frameworks for years. The counter is **not novel**, and any
framing that implies a likelihood-ratio statistic — "an SPRT" (Wald 1945), "a CUSUM"
(Page 1954), "a Neyman–Pearson test" — is an **overclaim** the claims-pass must block:
there is no LLR increment, no parametric regimes, no reset; it is a uniform +1 count of
one event type. It inherits the *framing* (threshold ⇄ ARL/false-alarm tradeoff,
asymmetric loss, abstention-under-reject-cost à la Chow 1970) but never the *optimality
guarantee*.

**The verified-real literature home** (citations that survived adversarial check):
the **decision-threshold / operating-point** vocabulary (Fawcett, *An introduction to ROC
analysis*, 2006; cost-sensitive operating-point selection, Provost & Fawcett 2001) is the
correct, non-overclaiming home; **fail-fast / circuit-breaker** (Shore, *IEEE Software*,
2004; Nygard 2007) is the mechanism's everyday name; **budgeted early-stop schedulers**
(Successive Halving/Hyperband, Karnin 2013 / Li et al. 2018; Median Stopping Rule, Vizier,
Golovin 2017) and **tail-at-scale cancellation** (Dean & Barroso, *CACM*, 2013) name the
*reallocation* half — but only as a contrast (they rank a graded learning-curve; DOS has a
binary env-error channel and no mid-run reward).

**Prior art — the result is INCREMENTAL, and the novelty boundary is narrow but real.**
The *detection mechanism* (consecutive/cumulative same-tool error → halt) is unambiguously
prior art: OpenClaw's result-aware loop detection (`(tool,args,result)` recurrence with
threshold escalation) is a near-exact independent twin, and `maxConsecutiveToolErrors`-style
guards are folklore. A *token-saving from early-halting doomed agent runs* is also already
reported — **BAGEN** ("Are LLM Agents Budget-Aware?", arXiv 2026: "28–64% on failed
trajectories"), **AgentStop** (arXiv 2026: 15–20% energy), and **"Runaway is Ashamed, But
Helpful"** (EMNLP 2025 Findings, arXiv:2505.17616: agent early-exit with a measured
step-vs-success tradeoff). What is **unclaimed in the literature** (the three narrow deltas
the paper claims, and only these):
1. **Byte-clean / env-authored provenance** — every academic early-exit peer keys off the
   agent's self-judgment, logprobs, or an LLM verifier; none frames the stop signal as
   deliberately *self-report-free* so the judged agent cannot forge its own halt-count.
2. **Zero task-success cost** — prior work explicitly *trades* accuracy for the saving
   (Runaway "slightly reduces success"; AgentStop "<5% drop"); the **0-success-cost** result
   (at the sound K) is the most defensible novelty.
3. **The measured separability law** — "a K-thrash run has ~0 success probability, so the
   halt is free" is, as far as the searches show, not crisply stated anywhere; the closest
   (a TDS blog, "90.8% of retries target permanent errors") is a deterministic simulation,
   not a real-agent fleet measurement.

**Do NOT claim novelty on the mechanism.** The defensible cell is the *combination*:
circuit-breaker decision object + ROC operating-point tuning + un-forgeable provenance +
measured class-disjointness justifying a model-free *sound* threshold. Each ingredient is
old; the cell is not. (Recorded in the paper as §8.1, a walled cross-benchmark subsection —
the EnterpriseOps numbers are NOT in the Toolathlon SSOT tables.)

---

## §4c — The zero-accuracy-cost claim, PROVEN cross-benchmark (and the naive gate DISPROVEN)

The "0 winners halted" claim was the weakest link: one corpus, one model, 45 pooled
winners (Wilson-95 upper 0.079). The fix is replication on a **second benchmark with a
full capability ladder**, and it lands decisively. Instrument:
`benchmark/giveup_cross_benchmark.py` ($0, + `test_giveup_cross_benchmark.py`, 5 green;
figure `benchmark/toolathlon/_results/fig_giveup_cross_benchmark.png`).

**Toolathlon carries both fields the gate needs, already byte-clean.** The
`additivity.py` SSOT (`_results/replay_all_rows.csv`, **22 models × 108 tasks = 7,116
runs, 1,634 winners**) has per-run `passed` (the third-party label), `tool_stream_run`
(the repeat run-length), and `terminal_error_fired` (env-error presence) — so the
false-abandon test runs with the canonical grammar, no reimplementation, **including the
frontier models EnterpriseOps lacked** (claude-4.5-opus, gemini-3-pro, gpt-5.1, o3,
grok-4).

**The headline (the error-gated gate DOS ships):**

| benchmark | winners | gate | K=3 false-abandons | Wilson-95 upper |
|---|---|---|---|---|
| EnterpriseOps | 45 | error-gated | **0** | 0.079 |
| **Toolathlon** | **1,634** | **error-gated** | **0** | **0.0023** |

Zero accuracy cost **replicates on a harder, frontier-spanning benchmark**, and the
confidence bound tightens **34×** (0.079 → 0.0023). Per-model, the error-gated gate halts
**0 winners on every one of the 22 models** — strong and weak alike — directly answering
the docs/177 frontier-decay worry *for the false-abandon (specificity) axis* (the
sensitivity/fire-rate still decays on the frontier; see ceiling below).

**The other half — the naive gate is DISPROVEN (the falsification the user asked for):**
a gate that fires on **raw `(tool,args,result)` repetition** (no error-gating) **false-
abandons real winners**: 18 at K=2, **6 at K=3**, 4 at K=4, 3 at K=5. *All* of them are
**grok-4 runs that repeat WITHOUT erroring** (`term_err=False`) — legitimate
eventual-consistency polling / re-reads that succeed. So:

> **The error-gating is the load-bearing discipline, not an incidental detail.** "Repeated
> tool call → halt" is *unsound* (kills pollers); "repeated tool **ERROR** → halt" is sound
> (0/1,634). The cross-benchmark test proves the gate DOS ships AND falsifies the naive
> variant a reviewer would reach for first. This is the byte-clean provenance line (the
> env authored the *error*, not just the repeat) doing real work.

**Honest ceiling (unchanged in spirit, sharpened).** This is the **specificity** axis —
"when it fires, does it ever kill a winner?" — and that is now strongly proven (0/1,679
winners across both benchmarks, 22+ models). It says **nothing** about **sensitivity**:
on Toolathlon the error-gated gate *fires* on only ~1 run at K=2 and 0 at K≥3, because
Toolathlon agents rarely thrash a tool with repeated *structured* errors the way the
EnterpriseOps `create_filter` wall does — so the *token-saving* is benchmark-dependent and
the frontier fire-rate decay (docs/177) is untouched. The proven claim is precise: **the
error-gated give-up gate is accuracy-free wherever it fires; how often it fires (and thus
how much it saves) is what varies by benchmark and model.**

---

## §4d — Cross-corpus boundary: the K-knob corroborates only where the thrash occurs

§4c proved zero accuracy cost on the two corpora that have a task-win label
(Toolathlon, EnterpriseOps). The obvious next move — replicate the §4b "K is a tunable
error threshold" claim on a *third* and *fourth* benchmark — was probed and **does not
land as a corroboration; it lands as a boundary**, which is the more honest (and more
useful) result. The two candidates, AgentProcessBench and AgentHallu, carry a gold
divergence label and an env-error channel but, unlike Toolathlon/EnterpriseOps, are
**short attribution traces with no task-win label**. So "zero accuracy cost" (never halt a
*winner*) is *uncomputable* there — there is no winner to halt — and forcing it would
manufacture a result on an absent denominator (the docs/198 category error). What *is*
computable is whether K behaves as a precision knob against the gold *divergence* label.
Instruments (both `$0`, offline, zero network/LLM calls, reusing the existing byte-clean
loaders/detectors untouched): `benchmark/_probe_k_cross_corpus_apb.py`
(AgentProcessBench bfcl+tau2, 500 trajectories) and `benchmark/_probe_k_cross_corpus_ah.py`
(AgentHallu, 693 trajectories).

**The shipped gate keys on a *consecutive-same-tool* error run reaching K — and on both
short corpora that key's firing denominator is near-empty above K=2:**

| corpus | trajs | consecutive-same-tool fires at K=2/3/4/5 | powered (n≥10) above K=2? |
|---|---|---|---|
| AgentProcessBench (bfcl+tau2) | 500 | **13 / 0 / 0 / 0** | no — empty |
| AgentHallu | 693 | **13 / 2 / 1 / 1** | no — 1–2-sample artifacts |

The trajectories simply *end* before any one tool can rack up three consecutive
structured errors — the long-horizon thrash the gate detects does not occur in a short
attribution trace. So **no tunable precision curve can be drawn for the gate's own grammar
above K=2 on either corpus**; every K≥3 point (precision 1.0, false-alarm 0.0) is computed
on ≤2 trajectories and is noise, not a finding. (Both adversarial verifiers confirmed the
denominators are honestly flagged and the per-corpus verdicts match what the n supports.)

**The one place the property survives off the long-horizon regime is a *looser* reading —
*cumulative* errored steps on a tool rather than a consecutive run.** On AgentProcessBench
that variant is powered at every K and behaves exactly as an operating-point dial:

| reading (APB bfcl+tau2) | K=2 | K=3 | K=4 | K=5 |
|---|---|---|---|---|
| fires (n) | 90 | 37 | 22 | 18 |
| false-alarm (of 165 clean) | 11.5% | 0.6% | 0.0% | 0.0% |
| precision (of fired) | 78.9% | 97.3% | 100% | 100% |
| recall (of 327 diverged) | 21.7% | 11.0% | 6.7% | 5.5% |

False-alarm falls monotonically toward zero while precision rises — the §4b operating
curve, on an independent benchmark. On AgentHallu even the cumulative reading is sparse
(n = 37 / 10 / 3 / 3), with only two powered points before it goes underpowered at K≥4.
But the cumulative variant is **not the grammar the shipped gate uses**, so it corroborates
the *abstract* §4b claim ("K is a tunable error-threshold operating point") **without**
corroborating the shipped consecutive-same-tool gate.

> **The bounded conclusion.** The K-as-precision-knob / zero-accuracy-cost property of §4c
> is a property of **long-horizon task-completion loops**, where a single tool can
> confirmedly thrash (Toolathlon's `create_filter`-class walls, EnterpriseOps's
> curable-tool thrash) — and is **degenerate on short attribution corpora**, where the
> gate's key fires on a near-empty denominator and any K≥3 point is noise. This does not
> weaken §4c; it **bounds the give-up-correctly gate to the long-horizon task-completion
> fleets DOS targets**, and explicitly refuses to manufacture a corroboration on a sparse
> denominator — the docs/174 "the boundary IS the result" move, applied to K. The §4c tail
> already foreshadowed this ("Toolathlon agents rarely thrash a tool the way the
> EnterpriseOps `create_filter` wall does"); §4d is the systematic, two-corpus confirmation
> with honest n's at every K.

---

## §5 — BUILD SPEC: the give-up-correctly arm

A **run-local, deployable, byte-clean** advisory early-halt gate, scored on the recorded
natural A/B. Benchmark-side only — **no kernel edit**. Built as
`benchmark/enterpriseops/giveup_arm.py` (the `benchmark` concurrent lane, disjoint from
`src/dos`; the one-way arrow — it imports the public `dos_react` grammar, never kernel
internals).

**Riding primitive (already shipped, advisory floor).** The gate *proposes* a stop; it
never kills. It maps to the watchdog's `OP_HALT` proposal (`cli.py:2099` — `dos watch`
records an `OP_HALT` on the WAL and echoes a stop command for a driver/operator to
execute, the docs/99 actuation boundary; it never signals a process) routed to the
`decisions.py` `LIVENESS` source (`decisions.py:84`). The advisory floor is
`liveness.SPINNING` (`liveness.py:53` — "reports; never kills a process or refuses a
lease"). PDP-only by default; opt-in actuation, riding the docs/144 ladder.

**Signal grammar — reuse, do not reimplement.** Byte-identical to
`dos_react.natural_thrash_gate` (`dos_react.py:314`): a tool has thrashed iff it produced
`_is_struct_error(_result_text(tr)) and not _is_blocked_result(tr)` on ≥K of its calls
*and its latest result is itself such an error* (still in the hole). The replay site is
`abandon_counterfactual._incremental_fire` (`abandon_counterfactual.py:73`), verified
byte-identical to `natural_thrash_gate` over growing prefixes.

**Inputs (both run-local).** (1) per-tool struct-error counter over THIS run's prefix;
(2) a run-local feasibility *proxy* — "0 successful results of this tool so far in this
run" — recorded explicitly as the **weaker** substitute for the corpus WALLED witness
(it cannot tell a wall from a not-yet-recovered curable tool; §2).

**Fire rule + K.** Fire on the run-local counter alone (plain-RL). Default **K=3** — §2
proves plain-RL at K=2 false-halts 1 winner on the pooled corpus, while K≥3 is
empirically sound on both arms with no corpus knowledge. Expose `--k` and sweep {2,3,4,5}.
Ship RLCW (AND corpus-WALLED) only as a `NOT-DEPLOYABLE` backtest comparand.

**Emits.** An advisory halt proposal carrying the env's own latest error bytes (already
`_redact_reflected_input`-stripped of agent-authored value): a `LIVENESS`/`OP_HALT`-shaped
record for the `dos decisions` queue and the supervisor reap proposal — never a kill.

**Pre-registered kill (the docs/194 §5 criterion).** Ship iff EXISTS K with FA-rate < 0.10
AND tokens-saved > 0 on the run-local plain-RL gate. Current corpus: **PASSES** at
K∈{2,3,4,5}, FA-rate 0.000 on the none arm (0.042 at K=2 on rewind → choose K=3 for
cross-arm soundness), real-token saving ~14.9% at K=2.

**Measure.** Deployable (run-local): fired count, FA-rate (post-hoc, `overall_success` as
scoring oracle only), real-token tail-saving (report `usage_metadata` total, not just the
char/4 proxy), per-K sweep. Backtest-only (corpus-wide, labelled NOT-DEPLOYABLE): the
WALLED/CURABLE/mostly-walled fire breakdown and the RLCW soundness contrast. **Mandatory
caveats on any value claim:** single-corpus, single-model (gemini-2.5-flash, N=1 —
frontier decay per docs/177 untested), fan-out-only throughput value, conversion-on-curable
still OPEN/underpowered.
