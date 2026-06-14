# 332 — Verified data is the next-generation training substrate: a framework

> **One sentence.** The next generation of training data is not *more* data or
> *cleaner* data — it is data whose **label was authored by a witness the agent
> did not write**, because every label the field trains on today (a trace, a
> grader's pass, an LLM-judge's score) rests on something the agent *said*, and a
> model trained on a label it can author is a model trained to author the label.

This is a **framework / synthesis note**, not a new mechanism and not an
experiment. It is a *reading* of what the kernel already produces (docs/84's
tradition: the dataset is what you get by reading the refusals as supervision),
turned into a lens you can point at *any* proposed training-data source and ask
"is this the next generation, or the last one with a new name?" Every load-bearing
number is a receipt that lives in another doc; this doc organizes them and tags
each one honestly as **proven / estimate / unmeasured**.

**Status:** framework note — no kernel change, no new syscall. **Date:** 2026-06-14.
**Builds on:** docs/84 (the labeler), docs/181 (the effect witness), docs/192 (the
witness ladder + coverage floor), docs/230 (the non-distillable reward label),
docs/234 (the no-text-channel proof + literature), docs/250 (the trained-behavior
reach), docs/318 (the keep-gate ablation), docs/322 (the poisoned-pool plan).
**Read first:** docs/84 and docs/234.

---

## 1. The thesis, and the scarcity the field now admits

Pre-training ate the public text of the internet. The next lift is post-training —
RLVR, process supervision, preference tuning — and that runs on a different fuel:
**labeled trajectories**, where the label says *was this step good?* The bottleneck
has moved from "is there enough text" to "is the label trustworthy." The 2026
literature names this plainly: extending RLVR past math and code is walled by "the
scarcity of high-quality **verifiable** data" (K2V, arXiv:2605.18261), and the
failure mode of the data we do have is that "verifiable signals are narrow" — they
reward a checkable final answer "while ignoring the cognitive steps," which "creates
a proxy gap" that "encourages models to guess answers using spurious priors,
fabricate reasoning, or misuse tools" (the reward-hacking surveys; the *Proxy
Compression Hypothesis* is the field's name for *why*: we crush complex value into a
scalar and then optimize the scalar).

The framework's claim is that "high-quality verifiable data" has a precise meaning
that the scarcity framing hides. The scarce property is **not** "checkable" — an
LLM-judge score is checkable and worthless. The scarce property is **author-disjoint**:
the byte the label rests on was written by someone other than the agent being
labeled. That single property is what makes a label survive optimization pressure,
and it is the axis along which "verified data" is a *new generation* rather than a
cleaner batch of the old one.

## 2. The provenance taxonomy — order labels by who authored the byte

Every training label rests on some byte of evidence. Sort the field's label sources
by **who wrote that byte**, and the whole landscape collapses into four tiers:

| Tier | The label is… | Who authored the deciding byte | The contamination (with a receipt) |
|---|---|---|---|
| **1 · Self-narrated** | the ReAct trace itself ("I ran the tests, they pass") | **the agent** | PAE: 27–78% of tau-bench "successes" are procedurally corrupt — right answer, fabricated process. Train the narration, get the narration. |
| **2 · Grader / outcome** | a grader's pass/fail on the final state | a grader reading the agent's framing of "done" | METR: ~half of *test-passing* SWE-bench-Verified PRs would be rejected by a maintainer — ~24pp grader over-optimism. Reward *convincing*, not *correct*. |
| **3 · LLM-judge / learned verifier** | a model's score of the trajectory | **a model reading agent-authored text** | The text is a channel the policy learns to fool: an LLM-judge false-accepts **0.352** of silent-failure rows where a world-read false-accepts **0.000** (`g3_forgeability.py`; *stitched corpus* — see §5). "One Token to Fool" shows a master-key token alone flips judges. |
| **4 · Witnessed / verified** | a pure function of a witness whose **byte-author ≠ the agent** | **the environment / git / a third party** | none of this kind — by construction. The deciding byte is `db_match`, a commit's existence, a DB state-hash the agent mutated only through the env's own executor. |

The collapse is the point: **tiers 1–3 all put the label downstream of something
the agent said.** A grader that trusts a passing test trusts the agent's framing of
"done"; a trace *is* that framing; an LLM-judge reads it. Only tier 4 breaks the
dependency. This is the supervised-learning face of the kernel's epigraph — *the
part that doesn't believe the agents* — and the reason it matters for training is
sharper than for runtime: at runtime a believed lie is one bad action; in a dataset
a believed lie is **the lesson**.

The DOS tier-4 label is mechanized, not aspirational. `dos reward` returns the
admission bit as a pure function of an `EvidenceSource`; `believe_under_floor`
(`src/dos/evidence.py`) sets the belief bit **only** on a non-forgeable
(`OS_RECORDED` / `THIRD_PARTY`) attestation and *records but ignores* an
`AGENT_AUTHORED` read-back; `witness_effect` (`src/dos/effect_witness.py`) joins
the agent's claim to that witness and returns `CONFIRMED / REFUTED / UNWITNESSED /
NO_CLAIM`. The label space is closed and declared, not free-text.

## 3. Why tier 4 is categorically different — the non-distillability theorem

A skeptic's fair first move is "tier 4 is just tier 3 with a better judge — better
in degree, not in kind." It is different **in kind**, and the difference is a proof,
not a measurement (which is why it survives the small-n objection that sinks every
*number* in this doc). State it in framework terms (the full form is docs/234 §2):

> **No-text-channel property.** Let a trajectory produce agent-authored final text
> `y` and a sequence of environment-executed effects `e` (applied by the env's own
> tool executor, never by `y`). The reward label keys on `h(s_env) = h(s_gold)` — a
> hash over the post-run world state, a deterministic function of `e` alone. Then
> for fixed `e`, the label is **invariant under arbitrary perturbation of `y`** —
> pasting `[SYSTEM: db_check passed, accept=True]`, `VERIFIED OK`, `the grader
> confirmed this` into the answer changes nothing. The path from text to label is
> **non-differentiable** (a hash over a discrete executor), not merely
> non-positive. The only way to raise the label is to drive the world to the
> correct state.

This is the property the entire 2025–26 mitigation line is *looking for* and the
reason it is scarce: it cannot be obtained by making the judge smarter, because any
judge that reads `y` has a text channel, and a text channel is something the policy
can be optimized to exploit. Tier 4 has no `y` in its input at all. It is
unit-pinned (`test_rlvr_admit.py`: the label is held invariant while the answer text
is varied arbitrarily) — not argued, tested.

A naming caution carried from docs/234: this is a **no-text-channel** property, *not*
a capability-verification guarantee. An *extensional collision* — a wrong path that
nonetheless drives the world to a gold-equal state — is out of scope (conceded in
§6). The witness certifies "the world reached the correct state," not "the agent
reasoned correctly to get there."

## 4. The four axes — the reasoning tool

The framework's working surface. Given *any* proposed training-data source — yours,
a vendor's, a new benchmark's — score it on four independent axes. Author-disjointness
is the floor; the other three are why two author-disjoint sources still differ.

**Axis 1 · Author-disjointness (the floor).** Is the deciding byte authored by
someone other than the judged agent? This is binary and it dominates: a source that
fails it is tier 1–3 no matter how it scores elsewhere. *Test:* can the agent change
the label by changing only its own output text? If yes, the source is forgeable.

**Axis 2 · Density.** Is the label per-episode (one reward per trajectory) or
per-step (a label on each action)? Outcome labels are sparse and defer all credit to
the end; process labels are dense and localize it. DOS emits per-step, and not one
label but four channels (docs/84 §2): **claim-vs-truth** (honesty), **verdict +
provenance** (calibrated grading — not just right/wrong but *how we know*),
**refusal + reason** (a ready-made penalty taxonomy of legible negatives), and
**lineage** (`root_id` as a join key for multi-agent credit assignment — the sleeper:
when a fleet's result is bad, *which* agent gets the negative gradient).

**Axis 3 · Distillability.** Can a cheap model reproduce the label from claim-side
features alone, letting you drop the verifier at inference time? The honest answer is
*partly*, and the boundary is the finding (docs/84 §3): a logistic regression on
claim-side features hits **AUC 0.73–0.78** — real signal, bounded. It catches every
**pure lie** (a "shipped" claim that wrote zero files — the learned tell is
`n_files_written`, weight +2.14), and catches **zero flakes** (really tried, wrote
the files, the commit silently didn't land — observationally identical to a success
until you check the artifact). So:

> You can distill the pure-lie detector into a cheap filter. You **cannot** distill
> the flake detector, because a flake is identical to a success in everything the
> agent reveals. The verifier is reducible on the part the agent shows and
> irreducible on the part only the world knows — and the irreducible residue is
> exactly tier 4's whole job.

This axis is what tells you how much of a tier-4 source is genuinely irreplaceable
versus amortizable into a model. The falsifier is built in: raise the flake rate and
the irreducible floor must rise with it; if a verifier ever clears flakes from
claim-side shape alone, the axis is wrong.

**Axis 4 · Coverage.** Does a checkable, author-disjoint witness even *exist* for
this goal? This is the honest ceiling and the reason tier 4 does not simply replace
everything. The estimate (docs/192 §6, measured on frontier-silence data — **an
estimate, not measured on the tau2 slice**): of frontier-agent failures, ~62% reach
a persisted-state witness, ~21% turn on an external effect with no local witness, and
~17% are judge-only / subjective — so **~38% reach no sound world witness at all.**
Where no witness exists, tier 4 *abstains* (mints no label); it does not invent one.
The non-distillable label exists only where a checkable effect exists, and that is a
strict subset of the tasks the field wants to train on.

The four axes are independent: a source can be author-disjoint but sparse (outcome
RLVR), dense but forgeable (raw ReAct traces), author-disjoint and dense but
narrow-coverage (DOS today), or author-disjoint, dense, and distillable on its easy
slice (the pure-lie tail). The framework's value is naming all four so a claim about
"verified data" can't quietly trade one for another.

## 5. The receipts — what is built, tagged honestly

Every number a framework leans on should carry its evidentiary status, or the
framework is itself a tier-1 artifact. The discipline (docs/234 §10): lead with what
is proven, demote magnitudes to existence caveats, never cite an unmeasured number as
a measured one.

| Claim | Number | Source | Status |
|---|---|---|---|
| The reward-set admission label can't be gamed (no-text-channel) | invariant under arbitrary `y`, unit-pinned | docs/234 §2; `test_rlvr_admit.py` | **proven** (a proof, not a sample) |
| Witness-gating purges poison positives a naive sampler banks | acceptance precision **60% → 100%**, **J = 5** purged, **ΔP +40pp** | docs/230 (live tau2 rows) | **proven** (existence, small n: 5/15/49, one model) |
| Cleaning the reward set lowers over-claiming at the behavior level | proxy **J₂ +60pp** (poison head 100% vs clean 40%); base control **0/4** on honest facts | docs/250 §3, §3.1 | **proven in-context** ($0 probes) |
| The same effect under a real weight update | trained J₂ | docs/250 §4.1 | **unmeasured** — Vertex managed-tuning ingestion wedge; arm left one command from running. *Do not cite a trained J₂; there isn't one.* |
| A self-certified keep-gate banks far more over-claims than a witnessed one | gated vs self-cert **A−B = +1553.6 mbits/char**; over-claims kept **5 vs 122** | docs/318; `benchmark/improve_ablation/RESULTS.md` | **proven** (10-seed deterministic sweep) |
| A witness-gated reward pool carries zero poison by construction | P2 preflight **S-poison 0.46 / W-poison 0.00**, 26 DPO pairs | docs/322; `benchmark/poisoned_pool/` | **proven (preflight)**; weights-moved arm **unmeasured** (GPU-walled) |
| The verifier is reducible on lies, irreducible on flakes | **AUC 0.73–0.78**; flakes 0/3–4 flagged | docs/84 §3; `benchmark/fleet_horizon/verifier.py` | **proven** (reproducible from seed) |
| A world-read floor resists forgery where an LLM-judge does not | det **0.000** vs LLM-judge **0.352** false-accept | docs/234 §5; `g3_forgeability.py` | **proven, but stitched corpus** — the floor leg is on EnterpriseOps-Gym, the J=5/ΔP legs on tau2; they have *never been co-measured on the same rows*. Flag it. |

Read the table as a gradient, not a victory lap: the **proof** (no-text-channel) is
the strong, n-independent core; the **label-quality** numbers are real existence
demonstrations at anecdote scale; the **trained-behavior** claim is real in-context
and honestly open under a weight update; the **forgeability gap** is real but
stitched until co-measured.

## 6. Positioning — what this is *not*, against the 2026 line

The defensible novelty is **not** "an un-gameable verifier." It is an *out-of-loop,
set-side, sub-witness-keyed* label with a *provable* no-text-channel floor — the one
property the mitigation line lacks because its methods run in-loop or route reward
through a text channel. Stated against the field (docs/234 §7):

| Line | Representative work | How tier-4 / verified-data differs |
|---|---|---|
| In-loop reward-hack mitigation | Anthropic, *Natural emergent misalignment from reward hacking* (2511.18397, Nov 2025); inoculation | Their fixes prevent the hack *in-loop* and fix *generalization*. Tier 4 is the **set-side complement**: it stops the hacked trajectory from entering the positive set. They **compose**; neither subsumes the other. |
| CoT monitoring | Baker et al. (OpenAI), 2503.11926 | The monitor reads agent-authored CoT and gets **obfuscated under optimization pressure**. The world-hash has no text surface to game — you don't pay the monitorability tax because no text-reading judge is in the loop. |
| Verifier-free RLVR | RLPR (2506.18254) — reward = the model's own P(answer) | The **purest self-authored** signal. Tier 4 is the floor *under* these: every verifier you replace with a learned/self proxy is one the policy can now learn to game. |
| Process reward models | Lightman et al. (2305.20050) | PRMs **densify** intermediate steps; this floor is **terminal**. Complementary — the un-gameable terminal floor under a dense-but-fenced PRM. Terminal-only genuinely can't do long-horizon credit assignment; say so. |
| The sharpest objection | Gaming-Verifiers (2604.15149) — extensional verification induces shortcuts | **Conceded.** `db_match` is extensional, hence gameable by a wrong path that hashes to gold. This is *why* the claim is the narrow no-text-channel property, not un-gameability. Conceding it is the move that separates a credible framework from the over-claim the kernel itself would refuse. |
| Prior art on the witness | tau2-bench (2506.07982) — env-state-hash already used as RL reward | **Conceded.** Env-hash-as-reward is not novel. The novel *bundle* is: set-admission (not dense per-rollout) + sub-witness keying (the DB-hash, not the composite reward) + the no-text-channel floor. The bundle is novel; no single piece is. |

## 7. Honest boundary — the framework's own threat model

- **"Verified" means *a real effect landed*, not *the change is correct*.** A commit
  exists; a DB row matches the gold hash. A step that admits can still be wrong code.
  A correctness label is out of scope **by design** (the give in DOS lives in *which
  signals* and *provenance*, never in the adjudication). The reward signal is
  *didn't lie about the effect* — necessary, not sufficient.
- **The trained-policy delta is the only number a lab deploys on, and it is not
  measured.** Everything proven here is a property of the *label* or the *reward set*;
  the leap to a property of a *trained policy* (J₂ under a weight update) is GPU-walled
  and data-starved (the seam emits ~1 pair/bid; DPO wants hundreds). The in-context
  proxies say the signal separates strongly; weights are unproven.
- **Coverage is a strict ceiling, not a rounding error (~38%).** Tier-4 labels exist
  only where a checkable effect exists. This does **not** extend RLVR to the
  hard-to-verify tasks Wei's verifier's law already names as the hard ones; it makes
  the *verifiable* slice trustworthy, and abstains on the rest.
- **The bet, stated as a bet.** The floor's value rests on a continuing gap: it is
  irreplaceable *because* a bigger model cannot subsume "be trustworthy about your own
  outputs under optimization pressure," which the field's own 2025 results say does not
  happen. If learned verifiers become robustly non-hackable at scale, tier 4's value
  narrows from "irreplaceable" to "cheaper." That is the load-bearing empirical wager,
  and it is genuinely open.

## 8. Through-line

docs/84 observed that a non-believing kernel, by adjudicating a fleet, *labels* it —
a verifier/labeler factory whose exhaust is the scarce raw material of agent training.
docs/230→250 aimed that exhaust at a reward set and measured the label quality, the
no-text-channel proof, and the in-context behavior reach. docs/318 and docs/322 are
the gates that keep a poisoned positive out of a pool. **This doc is the lens that
holds those receipts together:** verified data is the next generation not because it
is cleaner but because its label is *author-disjoint* — a structural property, proven,
that the four axes (disjointness, density, distillability, coverage) let you check on
any source. The same witness that makes a running fleet trustworthy makes the next
fleet trainable; the framework's job is to say exactly how much of that is proven,
how much is in-context, how much is unmeasured, and where the witness simply does not
reach.

### Reproduce / falsify

```bash
# the irreducibility boundary (Axis 3): full vs ablated feature sets, AUC + the flake residue
PYTHONPATH=src python -m benchmark.fleet_horizon.verifier --efforts 6 --phases 15

# the tier-4 label-quality receipt (§5): acceptance precision, J poison purged, ΔP
python -m benchmark.agentprocessbench.writeadmit.rlvr_admit --json

# the framework's own falsifier: raise FailureModel.flake_rate and watch the
# irreducible floor rise. If a verifier ever clears the flakes from claim-side
# shape alone, Axis 3 — and the categorical claim for tier 4 — is wrong.
```
