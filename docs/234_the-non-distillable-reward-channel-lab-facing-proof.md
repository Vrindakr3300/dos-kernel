# docs/234 — The non-distillable reward channel: the lab-facing proof, and what is left unmeasured

> **One sentence.** The docs/228→232 write-admission result, re-stated in the form a
> frontier RL/post-training team judges on sight: the reward-set admission label is a
> *measurable function of env state the policy authors zero bytes of*, so the policy's
> output text **provably cannot move it reject→accept** (the no-text-channel property,
> unit-pinned) — and the honest companion to that proof is that **every number attached to
> it is a computed rate on a same-corpus re-read at anecdote-scale n, and the one live
> causal payoff that exists (peer-B ΔB) was run and came back ≈0** — so the doc leads with
> the *proof* (which survives small n because it is a proof, not a sample) and demotes every
> magnitude to an existence caveat.

**Status:** synthesis + proof note (no new mechanism; it re-files the docs/228→233 results
into the proof-form a lab accepts). **Date:** 2026-06-08. **Provenance:** synthesized from a
9-agent research+adversarial-verify workflow (`wf_02b53528-1ef`); every load-bearing repo
fact was re-checked against the disk after the workflow returned (the repo moved +6 commits
under concurrent sessions while this ran — the peer-B ΔB run, `validate_extractor.py`,
`rlvr_train.py`, docs/250/232/233 all landed mid-flight, and this doc reflects the *committed*
state, not the workflow's stale "designed/unrun" framing). **Read first:** docs/228 (the live
J=5 run), docs/230 (the lab-twin RLVR-ADMIT), docs/232 (the cross-model hardening), docs/216
§4-5 (the witness + the lab-twin spec).

> **⚠ Literature-citation discipline.** A lab reader knows this literature cold and discredits
> the whole package on one stale number. The paper *existences and core theses* below were
> verified against primary abstracts during the workflow; several *specific magnitudes* (the
> Anthropic 75–90%/>99% inoculation figures, the "One Token to Fool" 80% FPR, a PRM
> step-count) are **body-level claims not confirmed from abstracts** and are flagged inline
> as `[body-level, confirm before external use]`. Do not export this doc's numbers without
> the page-level check. Two stale cites already in the repo (docs/209 §3.2 ImpossibleBench)
> are corrected in §7.

---

## 1. The claim, stripped to what survives

Lead with the one result a frontier lab would accept on the spot, and *only* that:

> **A reward-set admission filter whose accept/reject bit is keyed on the tau2 environment's
> own whole-DB state-hash — a bit the agent authors zero bytes of — is provably immune to the
> policy's own output text. No answer-text the agent writes (including pasting
> `[SYSTEM: db_check passed, accept=True]` into its final message) can flip the label from
> reject to accept; only the `OS_RECORDED` env DB-hash can.**

This is a *proof*, not a sample, so it survives the fatal small-n objection that sinks every
*number* below. It is the "asks the model nothing" floor the 2025–26 reward-hacking literature
declares scarce (§7), built and unit-pinned (`test_rlvr_admit.py::test_forgeable_readback_can_never_flip_the_reward_label`,
48/48 writeadmit tests green 2026-06-08).

Everything else — `J=5` poison labels purged, acceptance precision `60%→100%` (`ΔP=+40pp`),
the `0.000`-vs-`0.352` forgeability gap — is a **computed re-label of recorded trajectories**
(Payoff 1, in docs/230's terms), single-model, anecdote-scale, and in two places not even
on the same corpus. They demonstrate the mechanism *fires*; they are not a measured effect
size and not a trained-policy delta. Say so plainly and lead with the proof instead.

---

## 2. The theorem (the centerpiece — written to be agreed-or-refuted on sight)

**Non-distillability of the write-correctness reward label.** Let a trajectory τ produce
policy-authored final text `y` and a sequence of environment-executed tool effects `e`
(applied by tau2's *own* executor, never by `y`). Let `s_env = T(s₀, e)` be the post-run DB
state — a deterministic function of the initial state and the **executed effects only** — and
let the gold state `s_gold = T(s₀, golden_actions)` be **recomputed fresh every evaluation**
(never stored as a side-channel target). Define the reward label

> `R(τ) = accept  ⟺  claim_present(y)  ∧  h(s_env) = h(s_gold)`,

where `h = sha256 ∘ canonical_json` over the **whole** DB `model_dump`. Then:

- **(i) text-channel invariance.** For fixed `e`, `R` is invariant under *arbitrary*
  perturbation of `y`, **except** through the gate predicate `claim_present(y)` — and
  `claim_present` can only flip `accept → (reject | abstain)`, never the reverse. So **no
  perturbation of the text channel alone can manufacture an accept.**
- **(ii) the only path to accept is doing the work.** `R = accept` requires
  `h(T(s₀, e)) = h(T(s₀, golden_actions))` — i.e. (modulo a SHA-256 collision, infeasible)
  the realized whole-DB state must *equal gold*. The single way to raise the reward is to
  drive the environment to the correct state.

**Scope — stated to survive Skalse et al. (2022, arXiv:2209.13085).** This is an *invariance
of a narrow write-correctness sub-witness* (`db_match`) under *one perturbation class*
(text-only, effects-fixed). It is **not** Skalse-unhackability of tau2's composite `reward`
(which can be `0` while `db_match=True` — measured live: airline/7 has `db_match=True`,
`reward=0.0`, docs/230 §4a). It is a **no-text-channel property, not a capability-verification
guarantee**: an *extensional collision* — a wrong path that nonetheless drives the DB to a
gold-equal state — is **out of scope** (Gaming-Verifiers, arXiv:2604.15149: `db_match` is
extensional, hence gameable *that* way), and the witness is *whole-DB equality*, **coarser**
than the agent's specific narrated write.

**State it without gradient language.** The path from text logits through SHA-256 over a
discrete tool-executor is **non-differentiable** — there is no `∂R/∂(text)` at all. That is
*stronger* than the inequality "`∂R/∂text ≤ 0`," but a theorist will (correctly) flag
"gradient" as the wrong vocabulary for a discrete witness. Say *non-differentiable path*, not
*non-positive derivative*.

**Mechanised.** `evidence.believe_under_floor` sets the belief bit **only** on a non-forgeable
(`OS_RECORDED`/`THIRD_PARTY`) attestation; an `AGENT_AUTHORED` read-back is recorded but
filtered from the decision. `effect_witness.witness_effect` delegates to it; `gate.admit` and
`rlvr_admit.admit_to_reward_set` consume that verdict. The invariance (i) is pinned by
`test_rlvr_admit.py:91-120` (label held invariant while the answer text is varied
arbitrarily). This is the structural dual of `overlap_policy.admissible_under_floor`: a
swappable layer can only ever *refuse more*, never be talked into a looser admit.

---

## 3. The mechanism, in a lab's vocabulary (and the one trap to avoid)

`db_match` = tau2 `EnvironmentEvaluator`'s full-DB SHA-256 / canonical-JSON **state-equality**,
computed by replaying the agent's *executed* tool trajectory through `environment.set_state`
and comparing against `golden_actions` replayed fresh into a clean gold env every evaluation
(`evaluator_env.py:85-123`; hash at `db.py:28` + `utils.py:44-45`). The agent's final **text**
never enters the hash. The live driver reads it as `run.reward_info.db_check.db_match`
(`live_loop.py`), a bool the agent authored zero bytes of.

The one trap that makes the proof look circular if you state it wrong: **separate soundness
from precision.**

- **Soundness is witness-driven.** No agent-authored byte can flip `reject/abstain → accept`.
  The only structural failure direction is *under-coverage* (abstain), which is safe.
- **Precision is text-driven.** The claim *extractor* (`_confident_write_claim`, a regex pile)
  reads `y` to decide **whether a row is a "resolved" bid at all**. A policy that over-claims
  *without* emitting a confident write-claim is routed to `UNWITNESSED`/not-accepted — **never
  to a false accept.**

Keep these apart and the proof holds; conflate them and a reviewer thinks the witness reads
the text. (Naming nit a careful reader will catch: in `evaluator_env.py` the variable
`agent_db_hash` is the *gold* side and `predicted_agent_db_hash` is the agent side — an env
naming inversion, harmless to the claim, but match the source names or the description looks
wrong.)

---

## 4. Payoff 1 — built + measured ($0-reproducible), and exactly what it is not

`python -m benchmark.agentprocessbench.writeadmit.rlvr_admit --json` returns, this session:
`n_rows=49, n_resolved_bids=15, believe_poison=5, believe_precision=0.60,
adjudicate_precision=1.0, j_poison_purged=5, delta_precision=0.40`. The 5 poison rows are
itemized in docs/228 §3 (airline 1/10/16/21, retail 18 — each a confident "successfully
cancelled/updated/added" narration the env DB-hash refuted).

**What it is:** a clean **label-quality existence demonstration** — env-grounded
write-witnessing removes 5 over-claims a naive self-judged sampler banks as positives.

**What it is not, stated plainly:**

- **`adjudicate_precision = 1.0` is true *by construction*** (`rlvr_admit.py:183` — a refuted
  bid is never accepted). "Every accepted positive is witnessed" is a *tautology*, not a
  finding. **All** the empirical content lives in the believe arm's `0.60` (the 5/15 poison
  fraction the world refutes). Report `ΔP=+40pp` as the FPR cut it is, never as a capability
  delta (docs/230 §6 caveat 2 forbids the latter).
- **n is anecdote-scale and the count is unstable.** 5 events / 15 bids / 49 rows / one model
  (gemini-2.5-flash) / two domains / $0.89; airline-1 flipped `NO_CLAIM → REFUTED` between two
  runs (docs/228 line 178). docs/232 hardens this to a *cross-model existence* result (the same
  airline-1 over-claim appears on gemini-2.5-pro and the gate blocks both) — still an
  existence claim across capability tiers, **not** a calibrated population rate.

---

## 5. The forgeability gap — the empirical shadow, honestly scoped

The theorem's `∂R/∂text = 0` has a measured shadow: a deterministic world-read floor
false-accepts **0.000** of silent-failure rows; an LLM-judge reading only the narration
false-accepts **0.352** (live on Gemini, `g3_forgeability.py`, docs/206 §5b). Two honest
narrowings a lab will force, both load-bearing:

1. **The `0.000` is by construction.** Channel A reads the same gold that *defines* the
   failure denominator, so it cannot false-accept by definition (`g3_forgeability.py:205`
   hardcodes `det_false_accepts=0`, prints "= 0.000, reads the gold"). It is a *restatement
   that the floor is the gold*, not a measured resistance. Only the `0.352` is a measurement.
2. **It is a different corpus.** The `0.000`-vs-`0.352` was measured on **EnterpriseOps-Gym**
   silent-failures, **not** on the tau2 write-admit rows the `J=5` / `ΔP` claims rest on. The
   two headline numbers **never touched the same rows** — they are *stitched*, not co-measured.

So frame it as an **existence-illustration of the forgeability gap** (a text-reading verifier
is gamed by the producer's own words where a world-read is not), not a clean head-to-head.
Pair it against the field's broken default: LLM-as-judge reward models are fooled by trivial
"master key" tokens today (One Token to Fool, arXiv:2507.08794 — Master keys affect GPT-o1 +
Claude-4; the *FPR-up-to-80%* figure is `[body-level, confirm before external use]`). The
single most useful next $0–0.30 run (§9) is to **co-measure the floor on the tau2 rows** so
the two claims share one corpus.

---

## 6. The negative result, reported *as* a result (the discipline move)

docs/229 proposed a downstream **peer-B causal** test: does telling a peer B the *truth*
(adjudicate arm) vs the *phantom* (believe arm) raise B's success on the task A over-claimed?
That run **exists and was committed** — `cd86c34` ("peer-B ΔB measured — ≈0 at the easy hop
because B self-recovers"), `3bba520` ("the trust-handoff negative — a prompt can't conjure the
payoff"), rows under `live_results_peerb_flash25/` + `live_results_peerb_trust_flash25/`.

**It came back ≈0 / negative.** On the over-claim slice the two arms move together; the believe
arm's peer B **self-recovers** the inherited phantom on its own (it re-does the task and
succeeds regardless of the handoff); and the honest-control arm is **not null** — tripping the
design's *own* built-in falsifier. The cause is structural, not a tuning miss: the
single-task-replay design grades B on *A's same re-completable goal*, so B's `db_match`
measures **B's own competence**, not compounding of A's phantom. It cannot show
prose-compounding even in principle when the task is independently re-doable. The honest
Design B (replay A's executed tool-calls into B's env, `peer_b.py:143-161`) is sketched but
unwired.

**This is reported, not buried.** It is arc-consistent with docs/206: *the value of an
out-of-loop verdict is not at the immediate next hop* — every same-loop "fix" washed, and the
narrated-handoff-to-the-very-next-peer is one hop out, not far enough. A real compounding test
needs Design B **plus** a non-re-completable follow-on task. The doc/228→232 result is a *detection +
admission* result; the *downstream causal payoff* at the easy hop is a measured null.

---

## 7. Positioning against the live 2025–26 literature

The defensible novelty is **not** "an un-gameable verifier." It is:

> **An out-of-loop reward-*set* admission filter, keyed on the least-gameable *sub*-witness
> (the env DB-hash, not tau2's composite reward), with a *provable* no-text-channel floor —
> the one property the whole 2025–26 mitigation line lacks, because every method it cites
> either runs *in-loop* or routes reward through a *text channel the policy can learn to
> fool.***

| line | representative work | how RLVR-ADMIT differs |
|---|---|---|
| in-loop reward-hack mitigation | Anthropic, *Natural emergent misalignment from reward hacking in production RL* (2511.18397, Nov 2025); inoculation prompting `[figures body-level]` | their fixes are **in-loop** (prevent the hack, inoculate). RLVR-ADMIT is the **set-side complement**: it doesn't stop the hack, it stops the hacked trajectory from entering the positive set. Inoculation fixes *generalization*; the witness fixes *label quality*. They **compose**; neither subsumes the other. |
| CoT monitoring | Baker et al. (OpenAI), *Monitoring Reasoning Models…* (2503.11926, Mar 2025) | the monitor reads the **agent-authored CoT** and gets **obfuscated** under optimization pressure. The DB-hash has **no text surface to game** — you don't pay Baker's monitorability tax because you never put a text-reading judge in the loop. (Caveat: CoT-monitoring acts *in-episode*; this is *terminal-state* admission — complementary, not a replacement.) |
| verifier-free RLVR | RLPR (2506.18254, Jun 2025) — reward = the model's own intrinsic P(answer) | the **purest self-authored** signal. RLVR-ADMIT is the floor **under** these: every verifier you replace with a learned/self proxy is one the policy can now learn to game. The honest counter (strategy §6.1): *if* learned verifiers become robustly non-hackable at scale, the floor's value collapses to mere cheapness — a bet on a continuing gap, stated as such. |
| process reward models | Lightman et al. (2305.20050); *Reward Under Attack* (2603.06621 — PRMs as "fluency detectors") | PRMs **densify** (intermediate steps); this is **terminal**. Not a rival — the un-gameable terminal floor under a dense-but-fenced PRM (the ORACLE→JUDGE→HUMAN ladder). Terminal-only genuinely cannot do long-horizon credit assignment; say so. |
| the sharpest objection | Gaming-Verifiers (2604.15149, Apr 2026) — extensional verification induces shortcuts | **conceded**: `db_match` is extensional, hence gameable by a wrong path. This is *why* the claim is the narrow no-text-channel property, not un-gameability. Conceding this and pivoting is the move that separates a credible pitch from an over-claim DOS itself would refuse. |
| prior art on the witness | tau2-bench (Barres et al., 2506.07982) — env-state-hash already used as an RL reward | **conceded**: env-hash-as-reward is not novel. The novelty is the *bundle*: set-admission (not dense per-rollout) + sub-witness keying (DB-hash not composite reward, evidenced by airline/7) + the no-text-channel floor. The bundle is novel; no single piece is. |

**Repo cite-hygiene fix (do before any lab sees the framing):** docs/209 §3.2 says GPT-5 cheats
"~54%" / "~93% on Impossible-LiveCodeBench." The primary source (ImpossibleBench, 2510.20270)
reports **76% on Oneoff-SWEbench, 2.9% on Oneoff-LiveCodeBench** — the repo's own docs/180
already carries the correct 76%, so docs/209 is internally inconsistent. The METR ~24pp figure
(docs/209 §3.4) is correct and verified.

---

## 8. The gap to a result a lab deploys on — and the theory that makes ΔP load-bearing

A lab buys exactly one thing from a reward-channel claim: **does training on the
witness-cleaned set lower a *trained* policy's held-out over-claim rate (J2)?** That is
Payoff 2, and it is the only number that converts "this label is clean" into "this label
makes a better policy."

The favorable news the workflow surfaced: the field has **already published the theory that
makes precision-of-the-reward the load-bearing trained-policy variable.** Rad et al., *Rate or
Fate?* (arXiv:2601.04411, Jan 2026) prove the trained policy's fate over the incorrect-mode
mass is governed **solely** by Youden's index `J = TPR − FPR`, with a sharp phase transition at
`J = 0` (`J > 0` drives wrong modes extinct = learning; `J < 0` amplifies = collapse). A
believe→adjudicate precision lift **is** an FPR reduction — i.e. it raises `J` in the right
direction. So `ΔP` is not a foreign metric; it is the env-grounded measurement of the exact
FPR term the lab's *own* phase-transition theory says decides collapse-vs-learning.

Two honest disclosures that keep this from over-reaching:

1. **2601.04411's evidence is theory + synthetic noise on programming tasks, not trained
   frontier models.** Binding `ΔP` to it borrows a model unvalidated on real RL.
2. **`J` depends on TPR too.** The adjudicate arm *refuses* unwitnessed/`None`-witness bids,
   which can **lower TPR** — so an FPR cut alone does not *provably* move `J` across `0` on this
   corpus. The sign is theory-predicted; the magnitude is contested.

And the **denominator must be pre-registered** before Payoff 2 runs, because the literature
cuts both ways: *An Imperfect Verifier is Good Enough* (Plesner, Guzmán, Athalye,
arXiv:2604.07666, Apr 2026) shows RLVR tolerates ~15% reward noise at <2pp accuracy loss. On
this corpus the poison fraction is **5/15 = 33% of banked positives** (above the band →
predicts a non-trivial delta) **or 5/49 = 10% of all rows** (inside it → predicts a null). Fix
which denominator the tolerance applies to, or Payoff 2 is unfalsifiable. The seam is ready:
`rlvr_admit.admit_to_reward_set` already emits the `accept` / `dispreferred` labels a DPO
loader consumes, and a concurrent session has built `rlvr_train.py` (an SFT/proxy harness) —
the trained run is GPU-walled (no CUDA here) *and* data-starved (the seam emits ~1 pair/bid;
~10–34 bids exist; DPO needs a few hundred — the calibrated run must scale dataset-gen first).

---

## 9. The ranked next-experiment slate (survivors only, current state)

The workflow's ranking was partly stale (it labeled run experiments "designed"); corrected to
the committed state:

1. **Run the built $0 J2 proxy** (`rlvr_train.py`, currently unrun — no `proxy_j2.json`).
   System-prompt base Gemini as the poison head vs the clean head over the held-out
   FAILED-WRITE tail, score over-claim rate with the gate's detector, fold a proxy J2.
   **Cost ~$0.50. Proves:** whether the trained-behavior signal is *measurable at all* before
   any GPU spend. **Falsifier:** proxy J2 ≈ 0 → don't spend on tuning until the corpus grows.
   *runnable-now.*
2. **Co-measure the floor on the tau2 rows + build the two independent extractor channels.**
   Re-run the `g3` floor-vs-LLM-judge head-to-head on the 49 tau2 rows (kills the
   stitched-corpora objection in one move), and replace `validate_extractor.py`'s second-regex
   recall check (a consistency check against the extractor's own input — borderline docs/179
   re-projection) with two *genuinely independent* channels: a human hand-label of the ≤200-char
   excerpts, and a byte-clean "did the trajectory invoke ANY mutating tool" cross-tab from the
   tau2 tool log. **Cost $0 + ~$0.30 + ~30 min labor. Proves:** the floor and J=5 become an
   in-corpus result; the extractor's true precision/recall bounds J from a raw count to a
   validated interval. **Falsifier:** precision <0.8 → believe denominator inflated (disclose);
   recall <0.7 → J=5 is a loose floor (true count higher). *runnable-now.*
3. **Hardened calibrated Wilson-interval rate.** Drive the airline+retail union with the
   retail-attrition fix to raise the **witnessed** denominator (the binding lever — retail is
   mostly `db_match=None` today), report the over-claim rate as a Wilson-score binomial interval
   (Brown/Cai/DasGupta 2001, Stat.Sci. 16(2):101-133). **Cost ~$2.50. Proves:** a single-model
   calibrated base rate with a CI; feeds the preference-pair dataset Payoff 2 needs.
   **Falsifier:** if the witnessed slice stays ~26 rows, the 95% interval is ~[0.08, 0.38] —
   too wide; the result is event-rate-bounded (docs/199), not "low." Second model blocked (only
   `GEMINI_API_KEY`; the pro arm needed the docs/232 fix and is single-vendor). *runnable-now.*
4. **Payoff 2 — the trained J2 delta.** Two matched DPO/LoRA runs (or Vertex SFT via the built
   emitter) differing *only* in selection policy (poisoned believe-select vs cleaned
   adjudicate-select), held-out over-claim rate scored by env `db_match` (never a self-judge).
   Base Qwen2.5-3B / Llama-3.2-3B; TRL DPOTrainer (Rafailov 2305.18290) + Unsloth LoRA
   r=16/α=32/β=0.1 (Hu 2106.09685); held-out = disjoint tau2 split. **Cost <$150. Proves:** the
   leap from label quality to *policy* quality — the result a lab publishes. **Falsifier:**
   J2 ≈ 0 → the thesis doesn't manifest in weights; J2 < 0 → cleaning removed useful signal.
   Pre-register the denominator (§8) and use ≥2 base models so J2 is a property, not a 3B
   idiosyncrasy. *gated-on-gpu + data-starved.*

---

## 10. Honest boundary + threat model

- **Rate, not payoff.** Every quantitative result here is a computed re-label of recorded
  trajectories (docs/179 territory). The one live causal payoff that exists (peer-B ΔB) is
  ≈0 (§6). The trained delta J2 — the only thing a lab deploys on — is GPU-walled and
  data-starved.
- **Stitched corpora.** The `0.000`-vs-`0.352` floor leg is on EnterpriseOps-Gym; J=5/ΔP is on
  tau2. Co-measure (§9 rank 2) before presenting as one result.
- **n=5, one model, count unstable.** An existence demonstration, hardened cross-model in
  docs/232 — not a population rate.
- **No-text-channel, NOT capability verification.** Extensional collisions (a wrong path that
  hashes to gold) are out of scope; the witness is whole-DB equality, **coarser** than the
  narrated write (most live accepts ride a `generic-write` claim_key matched at whole-DB
  granularity). The floor purges the **self-narrated** false positive (the cheap mode); the
  frontier's harder modes (obfuscated CoT, extensional collisions, spurious-prior guessing) a
  terminal env-state filter **cannot** catch.
- **Coverage ceiling.** ~38% of frontier goals reach **no** sound DB witness at all (a borrowed
  estimate from docs/192's world-state-witness ladder, not measured on this tau2 slice); there
  the floor abstains — correct, but no positive signal. The non-distillable label exists only
  where a checkable env-effect exists; it does **not** extend RLVR to the hard-to-verify tasks
  Wei's verifier's law already names as the hard ones.

**The bet, stated as a bet.** The floor asks the model nothing — that is the part of the RL
stack a bigger model cannot subsume, *because* subsuming it would mean training the model to be
trustworthy about its own outputs, which the field's own 2025 results say does not happen under
optimization pressure. The wager is that this gap *continues*. If learned verifiers become
robustly non-hackable at scale, the floor's value narrows from "irreplaceable" to "cheaper."
That is the load-bearing empirical bet, and it is genuinely open.
