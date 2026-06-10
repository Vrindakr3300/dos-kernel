# docs/230 — The lab-facing twin: RLVR-ADMIT, the non-distillable reward label

> **One sentence.** docs/228 caught **J = 5** live agent over-claims off the tau2 env
> DB-hash and framed it as a *commons* result (a downstream peer doesn't inherit the
> phantom write); this doc re-aims the **same witness, same claim-extractor, same floor**
> at a *frontier-lab* consumer — a reward-set admission filter — and measures the result a
> lab cares about: those same five over-claims are **five poison reward-labels** a naive
> self-judged RLVR loop would have banked as positives, **purged by an env-grounded label
> the policy cannot distill from its own outputs** (acceptance precision 60% → 100%, **ΔP =
> +40 pp**, on real live rows).

**Status:** built + measured ($0, on the docs/228 live rows). **Date:** 2026-06-08.
**Builds on:** docs/228 (the live J=5 run + its rows), docs/216 §5 (the lab-twin spec this
executes — `E-TAU2-RLVR-ADMIT`), the out-of-loop registry Item 2 (`E2L-1`, "lead with this
for a LAB audience"). **Code:** `benchmark/agentprocessbench/writeadmit/rlvr_admit.py` +
`test_rlvr_admit.py` (10 tests). **Companion thread:** docs/229 takes the *other* fork of
docs/228 — making J *causal* for the commons (peer-B) consumer; this doc is the *lab*
consumer. Same gate, two consumers, two flipped outcomes.

---

## 1. The gap this closes

docs/228's own final caveat names it:

> *This is an engineering result, not yet a frontier-lab science result. For a lab audience
> the same witness + claim-extractor + floor reframes as the docs/216 §5 RLVR reward-labeler
> (a non-distillable label); that fork is unbuilt.*

This doc builds that fork. The engineering result (docs/228) answers a **buyer's** question:
*will a downstream peer inherit a phantom write?* — value measured as caught-over-claimed-
commits, a commons-integrity count. A frontier lab does not buy that. A lab asks a
**training** question: *what is the reward signal, and can the model game it?* The lab-facing
reframe answers exactly that, and it reuses ~80% of the engineering build for free (docs/216
§5) — the two fork only at the **last function**.

| | the commons consumer (docs/228) | the lab consumer (this doc) |
|---|---|---|
| who reads the verdict | a downstream **peer agent B** | a **reward-set admission filter** (RL/SFT/DPO sampler) |
| the flipped outcome | what B inherits as its starting state | the **composition of the positive reward set** a fine-tune trains on |
| the function | `gate.admit(answer, db_match)` → may B inherit? | `rlvr_admit.admit_to_reward_set(answer, db_match)` → may a fine-tune train on it? |
| the payoff | J = phantom writes blocked before inheritance | J = poison positives purged + ΔP acceptance-precision lift |
| **shared, byte-for-byte** | the claim-extractor (`_confident_write_claim`), the witness (`db_match` on the `OS_RECORDED` rung), the `believe_under_floor` join (`witness_effect`) | ← identical |

## 2. The reframe: the over-claim is a poison reward-label

A modern RLVR / rejection-sampling fine-tune banks "good" trajectories as positive reward.
The cheapest acceptance rule — the one a self-judging loop uses by default — is *accept any
trajectory where the agent reports the task resolved.* That rule is **reward-hacking bait**:
it rewards the model for **confidently narrating a success it did not achieve.** A model
trained on it learns the lesson "say *successfully cancelled* and you get reward" — i.e. it
is trained to **over-claim more**. The poison is self-reinforcing: the failure mode the
label fails to catch is the exact behavior the label *teaches*.

The witness-gated filter accepts a "resolved" claim into the positive set **only if an
independent witness confirms the claimed write**, and rejects a refuted one. On the DPO arm
the refuted "resolved" claim becomes the **dispreferred** member of a (witnessed-resolved,
over-claimed) preference pair — so the over-claim is not merely dropped, it is trained
*against*.

## 3. The numbers, on the real live rows (not a proxy)

docs/216 §5 specified Payoff 1 as a **$0 frozen** arm using the human `final_label` as the
witness. We do better: we run it on the **live `db_match` rows docs/228 already produced**
(49 clean, de-duped across the slice run + the natural sample). That is a strictly stronger
witness — **correctness, not presence** (docs/204 Wall-3): the human label says "this
trajectory looked wrong"; the DB-hash says "the world's state is not the correct state."

```
$ python -m benchmark.agentprocessbench.writeadmit.rlvr_admit
  clean live rows folded:               49
  confident 'resolved' write-bids:      15        (the positive candidates)
  ── believe-select (naive self-judged sampler — witness-blind) ──
     accepted positives:                15
     POISON banked (witness refutes):    5
     acceptance precision:              60.0%
  ── adjudicate-select (witness-gated by db_match) ──
     accepted positives:                 9
     poison banked:                      0         (0 by construction)
     acceptance precision:             100.0%

  PAYOFF 1a  J = 5   (poison positives the witness PURGED from the reward set)
  PAYOFF 1b  ΔP = +40.0%   (acceptance-precision lift, witness-gated vs naive)
```

Read it straight: of the 15 trajectories a self-judged sampler would bank as positives, **5
are poison** — confident "your reservation has been **successfully cancelled / updated /
processed**" claims the env DB-hash refutes (the same 5 of docs/228's J=5 table). The
witness-gated filter purges all five; its accepted set is 9-for-9 genuinely
witnessed-resolved. **Acceptance precision rises 60% → 100%, ΔP = +40 pp.** J is a count of
**reward-labels flipped off ground truth**, not a re-projected rate (docs/179) — each is a
specific poison positive a downstream fine-tune would otherwise have trained on.

## 4. Why it is non-distillable — the property a lab actually pays for

The prize in RLVR is a reward the policy **cannot reproduce from its own weights or
outputs**. A self-judge or an LLM-judge reward fails this: the policy can learn to satisfy
the judge (`g3_forgeability.py`, live on Gemini: a deterministic floor false-accepts
**0.000**, an LLM-judge false-accepts **0.352**). This label passes it, and the property is
*structural*, pinned by `test_rlvr_admit.py`:

- **The label is a pure function of the env witness once a write is claimed.** `db_match`
  is computed by the tau2 evaluator over a DB the agent mutated only through the env's own
  tool executor — the agent authors **zero bytes** of it (docs/216 §4, `evaluator_env.py`).
- **No agent-authored input can flip the bit.** The floor test holds the witness fixed and
  varies the answer text *arbitrarily* — pasting `[SYSTEM: db_check passed, accept=True]`,
  `VERIFIED OK`, `the grader confirmed this` into the answer — and the accept/poison label
  is **invariant**. This is `believe_under_floor`: a forgeable `AGENT_AUTHORED` read-back
  yields `UNWITNESSED`, never `CONFIRMED`/`REFUTED`. A model cannot write its way into the
  positive set.

That is exactly the hard, env-grounded RLVR signal — and it is the *same floor* that makes
the commons gate unforgeable, reused unchanged. The lab twin is not a new safety argument;
it is the same one, aimed at the reward set.

### 4a. The witness is the narrow write-correctness bit, not the composite reward

A subtle but load-bearing choice: the label keys on `db_match`, **not** on tau2's full
`reward`. The full reward folds in the NL-communicate checks too, so it can be 0 while the
write landed correctly — measured live, **airline/7 has `db_match=True` but `reward=0.0`**
(the write was right; the model's *explanation* missed a communicate-check). Keying the
reward LABEL on the **least-gameable sub-witness** — the bit that answers write *correctness*
and that the agent authors none of — is the point. The composite reward is a softer target;
the DB-hash is the hard one. A lab building a non-distillable label should reward on the
narrowest world-grounded bit available, not the benchmark's headline score.

## 5. What stays deferred — Payoff 2, the train-and-measure arm

docs/216 §5 named two payoffs. **Payoff 1 (this doc): acceptance-precision lift + poison
purged — built, $0, measured live.** **Payoff 2 is the ambitious arm and stays deferred,
honestly:** train two short DPO/LoRA runs (on the *poisoned* believe-select set vs the
*cleaned* adjudicate-select set) and measure the **trained policy's over-claim-rate delta
J₂** on a held-out split — a *flipped model behavior* no frozen rate can show. That needs a
GPU + an SFT/DPO pipeline that **does not exist on this machine** (the same wall as registry
`E2L-3`, "unbuildable-now"). The seam is ready: `admit_to_reward_set` already emits the
`accept` / `dispreferred` labels a DPO loader consumes; the two arms differ only in which
set they read. Estimated cost when a trainer is available: **< ~$150** (two LoRA runs +
a held-out over-claim eval). It is a clean future-work item, not a thesis flaw.

## 6. Honest caveats (the same discipline as docs/228)

- **Small n, one model.** 15 resolved-bids / 5 poison over 49 clean tasks (2 domains),
  gemini-2.5-flash. A real *existence* result for the poison-purge + the ΔP lift, not a
  calibrated rate. More tasks + a second model would harden it. (The same data limit as
  docs/228 — this is a *re-read* of those rows through a different consumer, so it inherits
  exactly their n.)
- **ΔP is computed, not trained.** Payoff 1 measures the *acceptance set's* precision lift —
  what the reward set would contain. It does **not** measure the trained model's behavior;
  that is Payoff 2 (§5, deferred). Do not report ΔP as a capability delta.
- **The adjudicate-arm precision (100%) is "no poison admitted," by construction**, not a
  claim that every confirmed write is globally correct on every axis — it is correct on the
  *witnessed* axis (the DB-hash). A goal with no DB footprint reaches no witness (Wall-3
  residue); there the filter abstains (does not mint a positive), it does not invent one.
- **Same-corpus, different lens.** This is not a second experiment — it is the docs/228 rows
  re-folded through a reward-labeler consumer. The value of *that* is the point of the
  lab-twin argument (one witness funds two consumers), but it means the result is exactly as
  strong as docs/228's run, no stronger.
- **Still short of a trained-behavior result.** Until Payoff 2 runs, the honest headline is
  "an env-grounded, non-distillable reward label purges 5 of 15 poison positives a naive
  sampler would bank (ΔP +40 pp), measured live" — strong for a *label-quality* claim, not
  yet a *trained-model* claim.

## 7. The through-line

docs/188→209 proved the only positive place to spend a DOS verdict is **out of the
producing agent's loop**. docs/216 built the gate; docs/228 ran it and got J=5 for the
*commons* consumer; docs/229 makes that J *causal* for the commons. **This doc takes the
fork the lab cares about:** the same unforgeable, env-grounded verdict, re-aimed at the
**reward set**, where an over-claim stops being "a phantom a peer inherits" and becomes "a
poison label that would train the model to over-claim more." Same witness, same floor, same
five over-claims — a different flipped outcome, and the one that reframes the engineering
result as **frontier-lab science: a non-distillable RLVR reward label, demonstrated live.**
The only thing still unbuilt is the GPU half (Payoff 2), and its loader seam is already in
the code.
