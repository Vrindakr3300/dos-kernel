# 160 — SOTA positioning: the trained-classifier comparison, the arbiter neighbors, and where this goes

> **Three questions came off the docs/158 audit: (1) is the trained-classifier baseline (the
> "98% accuracy" silent-failure paper) even a fair comparison to DOS's near-free detector? (2) can we
> run the arbitration neighbors (Limen, CodeCRDT) on the same data? (3) where does this go — it feels
> early, and ANY lift on a frontier model is impressive. This doc answers all three from the code and
> a runnable head-to-head: the classifier is a different deployment regime (labels-required) that does
> NOT beat the zero-training detector on the scoreboard that matters; the arbiter neighbors are not
> runnable on this data because they solve a different axis (they compare to DOS's *arbiter*, not its
> *detector*); and the forward path is the live re-read (a fresh third-party witness), which is the
> only byte-clean way to a large frontier lift.**

**Status:** analysis + one new runnable module (`benchmark/toolathlon/classifier_baseline.py`, the
head-to-head; durable ledger `_results/classifier_comparison.md`). No kernel change. Every number is
reproduced from the frozen `replay_all_rows.csv` (7,116 records, 6,862 labeled, 76.2% base fail).

**Lineage.** Companion to `docs/157` (the replay), `docs/158` (the `terminal_error` detector),
`docs/159` (the naive-baseline stress test + the lift-not-recall scoreboard) and `docs/114` §D (the
prior-art SOTA map this operationalizes). Inherits the byte-clean / mirror-verifier doctrine from
`docs/141` / `docs/143 §5a` and the ORACLE→JUDGE→HUMAN ladder from `docs/86`.

---

## 1. The trained classifier is a different REGIME — and labels are the non-starter

The most-cited neighbor is **"Detecting Silent Failures in Multi-Agentic AI Trajectories"** (arXiv
2511.04032, 2026): a **trained** classifier (XGBoost / SVDD) over ~16 trajectory features, reporting
**~98% accuracy / 99.8% precision** on its own datasets (stock-market traces, research-writing
traces). At face value that dwarfs `terminal_error`'s +18.8pp lift. The face value is misleading, and
the reason is the **deployment regime**, not the score:

| | DOS detector (`terminal_error`) | trained classifier (2511.04032) |
|---|---|---|
| training data | **none** | a **labeled** failure corpus, per domain |
| fit step | **none** — one deterministic pass per trace | gradient/boosting fit; must be re-fit per domain |
| honest scoring | the number IS the result (no split) | **only valid held-out** (a classifier scored in-sample is meaningless) |
| new task, no labels | **runs** | **cannot run** |
| bytes read | env-authored only (byte-clean) | trajectory structure the agent partly authors → **mirror-verifier risk** (docs/143 §5a) |
| failure mode under adaptation | stays honest (env emits the cue) | degrades when the model trains against the features |

**The labels requirement is the non-starter for the comparison.** The task DOS targets is *catch a
failure on a task you have never seen* — and on a novel task you have, by definition, no labeled
failure set to fit a classifier on. A method that needs a labeled training corpus is not competing for
the same job as a method that needs nothing. Comparing their headline numbers directly is a category
error: the classifier's 98% is bought with exactly the asset (per-domain labels) whose absence is the
whole problem. You can call that "a stronger result in a setting DOS does not address," but you cannot
call it "beats DOS at detecting silent failures in the wild."

## 2. Run it anyway — fairly — and it does NOT beat the near-free detector

To make the contrast concrete rather than rhetorical, `classifier_baseline.py` trains the
2511.04032-style classifier **on our corpus**, scored **held-out (k-fold)**, on the **same lift /
false-alarm scoreboard** docs/159 established (the only scoreboard a detector you *act on* may use).
Pure-Python logistic regression — the regime contrast, not the last F1 point, is what's measured.

Faithful setup (`--structure-only`: trajectory structure alone, no DOS flags as features — the actual
2511.04032 input):

```
                                  fire    prec    lift    recall  falarm   tp/fp
terminal_error  (DOS, 0-training) 1.2%   95.0%  +18.8pp   1.5%    0.2%    76/4
DOS trio (union, 0-training)      5.1%   92.6%  +16.4pp   6.2%    1.6%   323/26
trained clf — DEPLOYABLE point    0.0%  100.0%  +23.8pp   0.0%    0.0%     1/0    (fires once — no skill at low falarm)
trained clf — F1-OPTIMAL point  100.0%   76.2%   +0.0pp 100.0%   99.9%  5228/1632 (the base-rate mirage, docs/159)
trained clf — recall-MATCHED      1.1%   88.3%  +12.1pp   1.3%    0.6%    68/9
```

Three readings, each load-bearing:

- **F1-optimal collapses to the base rate.** The classifier's "best balanced" operating point is to
  predict *every run failed* (fire 100%, precision = the 76.2% base, **+0.0pp lift**). This is the
  exact recall mirage docs/159 named: on a 77%-fail benchmark, F1/accuracy reward the worthless
  `always-fail` control. The "98% accuracy" headline lives in this regime — accuracy on a high-base
  set is not skill.
- **At a deployable false-alarm ceiling the structural classifier has ~no skill** — it fires once.
  Trajectory structure (step count, run length, narration length) carries almost no *independent*
  failure signal on this corpus that you can act on without crying wolf.
- **Recall-matched to terminal_error, the trained classifier is strictly worse** — 88.3% vs 95.0%
  precision, +12.1 vs +18.8pp lift, 0.6% vs 0.2% false-alarm — *and it needed a labeled training set
  and a held-out split to get even that.* The zero-training detector wins on the metric that matters,
  for free.

And the tell, when you DO feed the classifier the DOS detector flags as features (the default mode):
its top weights become **`dangling_fired` (+0.32), `terminal_error_fired` (+0.19), `tool_stream_fired`
(+0.19)** — the pure structural features (`n_tool_steps` +0.02, `final_text_len` +0.06) are noise. The
classifier's only real signal is **re-deriving the DOS detectors it was handed.** It does not add a
new slice; it launders the deterministic ones through a model that now also needs labels.

**Could the classifier still be useful? Yes — as a JUDGE-rung driver, not a replacement.** This is the
right home for it in the DOS ladder (ORACLE → JUDGE → HUMAN, docs/86): a trained model is a
non-deterministic adjudicator that may rule on the residue the deterministic detectors ABSTAINED on,
**under the byte-clean floor**, advisory-only, fail-to-abstain. That is a `dos.judges` plugin
(`drivers/`), exactly like `llm_judge`. It is a **dryer add-on**, in your words — a thing you *can*
bolt on where labels happen to exist, never the load-bearing floor. The kernel stays zero-training;
the labeled classifier lives outside it, capped so it can only refuse-more, never authorize on its own.

## 3. The arbiter neighbors are NOT runnable on this data — different axis

The request to "run Limen on the data" surfaced a real category distinction worth pinning. **Limen**
(advisory write-leases over regions, mediated in-band at write-time) and **CodeCRDT** (lock-free CRDT
convergence) are neighbors of DOS's **`arbitrate()`**, not of its **detector**. Verified against
Limen's own scope doc: it has *"zero trajectory analysis, failure detection, or completion
verification"* — it coordinates **live** agents writing to shared state and *"cannot analyze frozen
trajectories after execution."* So there is nothing to run on the Toolathlon frozen traces: Limen
produces lease grants/refusals and an audit trail, not a pass/fail-of-a-finished-run verdict. There is
no precision/recall to compute. A "Limen on the data" benchmark would be inventing a comparison that
does not exist.

The honest arbiter-axis comparison (already in docs/114 §D, restated here so this doc is
self-contained):

- **Limen is AHEAD of DOS's arbiter on prevention.** It mediates the write in-band (a real PEP at the
  write moment); DOS's arbiter is a pure PDP that trusts the *declared* write-set at admission and
  *detects* collisions after, never *prevents* the write. On the "many agents, one repo, don't
  clobber" axis, Limen's in-band mediation is the stronger mechanism.
- **CodeCRDT may dominate leasing entirely** for pure parallelism (commuting edits converge, no lock
  needed) — but it is a lock-free coordination design, evaluated on speedup/convergence (up to 21%
  faster on some tasks, up to 39% slower on others), not on failure detection.
- **DOS's differentiator is the UNION, not the lease**: verify + arbitrate + liveness +
  structured-refusal as one untrusting referee. The lease alone is not novel and Limen does it better.

So: the detector axis (this benchmark) and the arbiter axis (Limen/CodeCRDT) do not share a
scoreboard. The fair, runnable head-to-head for `terminal_error` is the trained classifier (§2); the
fair comparison for `arbitrate()` is a *live* multi-writer collision study against Limen — a different
experiment, a different harness, not the Toolathlon replay.

## 4. Where this goes — early, and a frontier lift is the prize

The detector line is early, and that cuts in DOS's favor: on a third-party-scored frontier benchmark,
**any byte-clean lift on the strongest models, with zero training, is hard to come by** — the trained
classifier could not produce one at a deployable false-alarm rate (§2), and the forgeable narration
readers degrade on deployment (docs/158 §5). So the bar to "novel and real" is low *because* the honest
constraint is strict. The roadmap, ranked by significance-per-honesty:

1. **The live post-hoc re-read (Tier B, the real prize — docs/158 §6).** After a run, re-query the
   app for each extracted claim (re-read the file, re-fetch the form, re-list the sent emails) and
   compare against a **fresh third-party byte**. This is `derived_witness` / `believe_under_floor`
   with a THIRD_PARTY operand fetched on demand — the *same epistemics as Toolathlon's own oracle*. It
   is the ONLY byte-clean route to a large recall gain on the dominant frontier failure
   (confidently-wrong *content*, no in-trace error). Cost is the live-env spend (≈$170–1.8K, the
   docs/157 HANDOFF Phase-4 number) — the same spend as the live A/B, and the same answer to the
   "run it on fresh Gemini" ask. DOS-specific value = **attribution** (which claim was false), which
   the pass/fail oracle does not give.

2. **The recovery-knob follow-up (docs/159 §4b).** `tight-no-recovery` nearly doubles `terminal_error`
   recall (1.5% → 2.9%) at 0.7% false-alarm — and surfaces a real phenomenon: runs that hit an env
   error a later same-tool call *nominally recovered*, yet still failed final-state. The recovery was
   false reassurance. Worth a read of those cases and a confidence knob (the docs/144 ladder shape:
   conservative default, aggressive opt-in).

3. **The classifier as a `dos.judges` driver (§2).** If a host has labels, ship the trained model as a
   JUDGE-rung plugin under the deterministic floor — advisory, fail-to-abstain, never authorizing. The
   eval harness already exists (`judge_eval`). This makes the "stronger offline number" available
   *safely* to hosts that can afford labels, without the kernel ever depending on them.

4. **More env-authored in-trace signals (the cheap tier).** `error_streak`, `required-precursor-read
   missing` (docs/147 already shipped a precursor gate), cross-tool set reconciliation — each a small
   additive slice on the §5 scoreboard. Diminishing returns vs (1), but $0.

**The honest framing for publication:** DOS is the only system that catches a confidently-wrong
frontier failure **byte-clean and zero-training** from a frozen trace, and the one offline competitor
(a trained classifier) needs per-domain labels and still does not beat it on the deployable scoreboard.
The large remaining gain is the live re-read — which is the benchmark's own oracle rung — and that
boundary (where an in-flight advisory substrate ends and a final-state verifier begins) is the result,
not a gap to paper over.

## 5. Bottom line

- The trained classifier is a **different regime** (labels-required, held-out-only, mirror-verifier
  risk); on our corpus, scored fairly, it **does not beat** the zero-training detector and mostly
  re-derives it. It belongs **under** DOS as a JUDGE-rung driver, not beside it as a rival.
- Limen / CodeCRDT compare to DOS's **arbiter**, not its detector, and are **not runnable** on frozen
  traces; on their own axis Limen is ahead on prevention, and DOS's contribution is the integration.
- The forward path with the biggest, still-byte-clean payoff is the **live post-hoc re-read** — the
  same spend as a fresh-model run, the only route to a large frontier lift, and the natural next
  experiment after this $0 replay.
