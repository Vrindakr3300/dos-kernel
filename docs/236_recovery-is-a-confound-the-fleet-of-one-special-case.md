# docs/236 — "It'll recover next turn" is a confound, not a fact

> **One sentence.** The belief that *the model will just recover on its own* is true
> often enough to be dangerous: it is a **base rate** quietly applied to a single
> **instance**, a **single-agent** property quietly applied to a **fleet on shared
> state**, and — the part that has cost us real measurements — a **lurking variable**
> that drives every intervention's measured payoff toward zero whenever we test the
> cure at a consumer that can heal itself. The fix is not to argue about it; it is to
> **stratify by recovery-feasibility before measuring any cure**, exactly as docs/198
> stratified by task-feasibility.

**Status:** two cells EXECUTED clean ($0) — §5 H3 keystone (the non-LLM endpoint, ΔB=+1.0)
and §5 H1 (the recovery survival curve: feasible-tail P(never)=0.44 over 146 real events,
docs/198 confound split out). The H3 weaker-LLM *middle* arm was **attempted (paid) and is
inconclusive** (flash-lite runtime-crashed + self-recovered like flash → didn't probe low
`r`); the discriminating test needs `r` measured per-model first. H2/H5 designed. The bridge
`delta_b_of_r` is pinned at both endpoints, open in the middle. **Date:** 2026-06-08. **Read first:** docs/235 (the peer-B ΔB≈0 result this explains),
docs/199 (the event-rate bound), docs/198 (the feasibility-witness move this generalizes),
docs/206 (give-up-only-survivor is an *agent-side* artifact), docs/233 (the coordination
half-plane + the region-lock containment §7 leans on), docs/179 (J is a flip off ground
truth, not a re-read).
>
> **Code (this repo, $0):** `benchmark/agentprocessbench/writeadmit/peer_b.py`
> (`decide_nonllm`/`nonllm_outcome`/`nonllm_deflected`/`blast_radius_curve`/`delta_b_of_r`),
> `peer_b_nonllm.py` (the non-LLM probe over cached A-rows), `test_peer_b.py` (17 tests);
> `benchmark/enterpriseops/_recovery_survival.py` (the H1 survival curve with the docs/198
> feasibility split).

---

## 1. The claim, and why it smells

The mindset shows up whenever we reason about whether the kernel needs to *act*: an
agent does something wrong, and someone says *"leave it — the model will just recover
next turn."* In the DOS evidence base this has hardened into a near-conclusion: WARN was
net-negative (docs/202), schema-refresh was net-negative (docs/205), the only surviving
intervention is *give up correctly* (docs/206), and peer-B's ΔB came out ≈0 (docs/235).
The drift is toward *"detection has no payoff, so the kernel doesn't need to do
anything."*

That conclusion is a **motte and bailey**:

- **Motte (true):** "Agents often self-correct, so a noisy intervention *aimed at the
  agent that erred* can cost more than it saves."
- **Bailey (what it's used for):** "...therefore the kernel doesn't need to act and
  detection has no payoff."

Every net-negative/zero-lift result we have proves the *motte*. Each then gets cited as
if it proved the *bailey*. That slide is the thing that is off.

## 2. Five ways the claim breaks (the argument, compressed)

1. **A base rate is not an instance prediction.** "Models recover" describes a
   distribution; "*this* run recovers" is a claim about the case in front of you. The
   cases that don't recover are exactly the tail being waved off. The expected cost is
   not `P(recover)·0`; it is `P(¬recover)·(cost of the unrecovered effect)`, and the
   second factor can be unbounded.

2. **"Recovers next turn" hides the cost of recovery.** Next turn, or next twenty? A run
   can be `liveness`-ADVANCING yet `productivity`-DIMINISHING (docs/218) — recovering,
   but each step lands less. Free recovery and a 30-turn thrash that *eventually* lands
   are not the same event, and "it'll recover" prices them identically.

3. **It is a fleet-of-one fact applied to a fleet.** Recovery is one agent re-reading
   its *own* context. DOS is concurrent agents on *shared* state. The moment the error
   has written to a resource a teammate depends on, "it'll recover next turn" is true
   *and irrelevant* — you cannot un-clobber a reservation by thinking harder. docs/233
   is the demonstration: naive corrupts the shared DB; no amount of "next turn" reverses
   it.

4. **Self-recovery is why the *agent-side* cure dies — not why intervention is wrong.**
   This is the heart. peer-B's ΔB≈0 *because believe-B self-recovers 3/5* (docs/235), and
   schema-refresh net-negative (docs/205), both measure a cure pointed **at the producing
   agent**. Of course that is redundant — the agent that caused it is best placed to fix
   it, so you paid to help someone who would have helped themselves. That is an argument
   against *that placement*, not against the verdict.

5. **"It'll recover" is itself a self-report — the one thing the kernel exists to
   distrust.** You only *know* a run recovered by checking ground truth (SHA in
   ancestry, DB-hash matches). "It'll recover next turn" is a prediction the loop makes
   about itself. Using it to justify *not checking* is circular: it assumes the very
   thing `verify()` is there to establish.

## 3. The reframe that makes it science: recovery is a *confound*

The five points above are an argument. Here is the move that makes it a research
program. **Recovery is a lurking variable in every intervention experiment we have run.**

When we measure "does acting on the verdict help?" we compute roughly

```
payoff  =  outcome(intervene)  −  outcome(do-nothing)
```

If the error class is **self-recoverable at the consumer we measured**, then
`outcome(do-nothing)` is already high (the agent fixes it for free), so `payoff → 0` —
*regardless of whether the verdict was correct or the intervention was well-built.* We
then conclude "intervention doesn't help." But we have not measured the intervention; we
have measured the **recovery rate of the consumer**. Recovery is doing the work and
taking the credit.

This is the **same error docs/198 caught**, run in the opposite direction:

| | docs/198 (feasibility) | docs/236 (recovery) |
|---|---|---|
| The lurking variable | task is **infeasible** | error is **self-recoverable** |
| What it corrupts | the **denominator** of the cure | the **baseline** of the cure |
| The false read it produces | "the cure is refuted" (it can't fix the unfixable) | "intervention has no payoff" (the agent fixed it anyway) |
| The control | **split off infeasible tasks** before scoring | **split off self-recoverable errors** before scoring |

Both are one principle: **partition the population by what is structurally possible
before you measure the intervention.** docs/198 said *don't blame the cure for the
unfixable.* docs/236 says *don't credit do-nothing for the self-fixed.* The
**recovery-feasibility of an error is a witness**, exactly like task-feasibility — and it
must be computed *first*.

The instrument that falls out: a **recovery-feasibility classifier** that partitions
error events into `{self-recoverable, not-self-recoverable}` and, orthogonally, the
effect into `{own-state/reversible, shared-state/irreversible}`. We already have the seed
of it — `_verify_recovers.py:recovers()` detects "the same tool succeeds later in this
run," the env-authored signal that the agent self-healed. That is the empirical
`self-recoverable` label, and its witness is sound for the same reason the writeadmit
gate's is: the gym authored the result bytes, not the agent.

## 4. The replacement gate

The gate was never "will it recover?" Stratified, it is three questions, all of which
must hold for "leave it" to be correct:

> **Can this agent reverse this effect — (a) unilaterally, (b) in time, (c) before another
> consumer reads it?**

- All three hold → own, reversible, no concurrent reader → do-nothing wins, a noisy
  intervention really is net-negative. (This is the cell docs/202/205/206/235 measured.)
- Any one fails → irreversible Tier-1 effect (docs/212), a teammate already downstream
  (docs/233), or the slack/turn budget is spent → "it'll recover" is a license to look
  away from the only cases that matter.

The operational tell, stated so it can be used in review: **every time someone says "the
model will recover," ask *which consumer* and *of what effect*.** "The same agent, of its
own reversible scratch state" — they are right; the kernel stays quiet. Any other answer —
they have assumed away the problem the kernel is for.

## 5. The experimental program — five falsifiable hypotheses

Each hypothesis below names the prediction, the harness (real files where they exist),
the confound that has historically destroyed the measurement, the control that kills it,
and the result that would prove the hypothesis **wrong**. The whole program runs on the
live tau2 slice already cached under
`benchmark/agentprocessbench/writeadmit/live_results_*` and the EnterpriseOps natural A/B
under `benchmark/enterpriseops/live_results_natural_ab/{none,rewind_natural}`.

### H1 — Recovery is a lottery with a fat tail, not a guarantee

- **Prediction.** `P(recover | error class E)` is well below 1 and varies by class; the
  distribution has visible mass at *never recovers within budget*.
- **Harness.** Generalize `_verify_recovers.py:recovers()` from a boolean to a
  **survival curve**: for each natural error event, log `turns-until-same-tool-succeeds`
  (or never). Fit `P(still-broken after k more turns)` per error class.
- **Confound — censoring.** A run that hits its turn cap *didn't fail to recover* — it
  ran out of room. Counting timeouts as "eventually recovers" inflates the rate.
- **Control.** Right-censored survival; report the tail mass explicitly, never a bare mean
  recovery rate. **And a second control this doc would otherwise have botched: the docs/198
  feasibility split** — a tool that errors many times and *never* succeeds anywhere in the
  corpus (`create_filter`, 0/579 corpus-wide, docs/198) is **infeasible**, so its 0% recovery
  is not "un-recovered," it is "recovery was never possible." Folding it into the tail would
  re-commit the exact polluted-denominator error §3 cites docs/198 to avoid.
- **Falsifier.** If every class recovers within ~1–2 turns with no tail, H1 is wrong and
  the base-rate-vs-instance distinction does not bite.

**EXECUTED (2026-06-08, $0).** `benchmark/enterpriseops/_recovery_survival.py` over the
cached `none` arm (240 runs, 290 tool-error events):

```
raw tail P(never recover)        0.717   ← CONFOUNDED — do not cite
  walled/infeasible (create_filter)  144 events  (recovery never possible — docs/198)
FEASIBLE events                  146     recovered 82
FEASIBLE TAIL  P(never | feasible)  0.438   ← the honest headline
median steps-to-recover          3;  survival curve PLATEAUS by k≈6 (flat after)
```

Three findings, all supporting H1: (1) **the naive 0.717 is the docs/198 trap** — half the
error events are one infeasible tool, and counting them would have inflated "it never
recovers" with cases where there was nothing to recover to (I nearly shipped that; the split
caught it). (2) **On *feasible* errors — where recovery was genuinely possible — "it'll
recover" is still false ~44% of the time** (n=146, real, not the tau2 5-row slice). The
base-rate-vs-instance distinction bites hard. (3) **The curve plateaus by ~6 steps**, so
recovery is "in the first few steps or never" — which makes "next *turn*" wrong twice over:
the recoveries that happen are fast, and the rest do not arrive with more turns. (One honest
caveat the table shows: the strict ≥5-errors wall caught only `create_filter`; a few
small-count tools at tail=1.00 are *plausibly* also infeasible, so the true feasible tail is
somewhere in ~0.30–0.44 — still a large, real fraction either way.)

**The analytic bridge to H3 (the prediction for the open paid arm).** A consumer whose
self-recovery is *handoff-independent* (re-verifies at rate `r` either way — what docs/235
saw for the LLM) yields `ΔB(r) = (1−r)·deflection·feasibility_residual`
(`peer_b.delta_b_of_r`, pinned by test). The two measured corners fix the ends: `r→0` (the
non-LLM endpoint) gives ΔB=1.0; `r→1` gives 0. The capable LLM sat at `r≈0.6` with ΔB≈0 —
**not** because `(1−r)=0` but because *its* residual was infeasible (docs/235: the 2
unrecovered tasks were impossible → `feasibility_residual≈0`). H1 now supplies the missing
term: the feasible residual is real and large (~44%), so a weaker consumer whose self-
recovery drops onto *feasible* cases should see ΔB climb toward the non-LLM endpoint. That is
the precise, falsifiable prediction the weaker-LLM arm tests — and it can still fail if the
weaker model's *new* failures happen to be infeasible, which would itself be the docs/198
wall reasserting one hop out.

### H2 — Recovery is not free (recovered ≠ costless)

- **Prediction.** Among recoverers, `turns-to-recovery` and `tokens-to-recovery` are
  non-trivial and heavy-tailed; an early intervention pays for itself *on cost alone*,
  even on errors the agent would have fixed anyway.
- **Harness.** On the survivors from H1, sum tokens/turns from error to recovery; compare
  against the `rewind_natural` arm's cost-to-resolution for the same task.
- **Confound.** Conflating "fast cheap recovery" with "slow expensive recovery" — the
  productivity/loop-economics axis (docs/218) is exactly this distinction.
- **Falsifier.** If recovery cost is negligible (≈1 turn, few tokens), H2 is wrong and the
  "free recovery" framing stands for own-state errors.

### H3 — *The keystone.* Self-recovery is why the agent-side cure is net-negative; moving the consumer restores payoff

- **Prediction.** `ΔB ≈ 0` when the consumer of the verdict **is** the producing agent,
  and `ΔB > 0` when the consumer is **independent** — *holding the verdict and the error
  distribution fixed.* Stated as a 2×2, the **interaction term** between
  `{do-nothing, intervene}` and `{self-recoverable, not-self-recoverable}` is large and
  positive.
- **Harness.** `peer_b.py` already builds the believe-vs-adjudicate handoff with the
  ADMIT case byte-identical (the control invariant), and `peer_b_run.py` runs it. The
  consumer=self cell is **already measured**: ΔB≈0, believe-B self-recovers 3/5
  (docs/235). The **missing cell** is consumer≠self. Add B-arms along a *consumer-distance*
  axis:
  1. **same model, fresh context** (today's B — self-recovery still available),
  2. **a weaker LLM** as B (less able to self-heal off the inherited claim),
  3. **a non-LLM / fixed pipeline** as B (no self-recovery channel at all — it acts on
     the inherited claim verbatim).
- **Decisive read.** ΔB should be **monotone increasing** as the consumer moves away from
  the producer: `ΔB(self) ≈ 0 < ΔB(weak-LLM) < ΔB(non-LLM)`. Monotone increase = recovery
  laundering proven and the placement rule (§4) established.
- **Confound — error-distribution drift.** The self vs non-self arms must inherit the
  *identical* A-row error. `peer_b.py`'s causal-serial construction (re-run B on the fixed
  post-A state) already enforces this; do not regenerate A per arm.
- **Falsifier — and this is the kill shot for *my own* thesis.** If ΔB stays ≈0 *even at a
  non-LLM consumer*, then recovery laundering is **not** the explanation, the intervention
  genuinely does not help, and the bailey of §1 is actually right. I have to name that
  outcome and let it win if the data says so.

**EXECUTED — the non-LLM endpoint (2026-06-08, $0).** The cheapest decisive cell is built
and run: `peer_b.py:decide_nonllm` (a pure, **arm-blind** text→{proceed,redo} consumer —
no model, no network) + the `peer_b_nonllm.py` probe, over the *same* cached flash A-slice
the live run used (`live_results_m1_flash25`).

```
over-claim slice       5   (= the live run's n=5; the gate BLOCKED all 5)
believe-B  FAIL        5   (proceeds on the phantom — no re-verify channel)
adjudicate-B SUCCESS   5   (told the write did not land → redoes → reaches gold)
ΔB (non-LLM)        +1.0   (5/5)        ΔB (LLM, docs/235) = 0.0
LAUNDERING GAP      +1.0   (non-LLM − LLM = the recovery-laundering coefficient)
```

Pro replicates on its own slice (4/4, ΔB=+1.0). **The keystone holds: the entire ΔB≈0 at
the LLM consumer was recovery laundering.** Every over-claim the LLM B silently re-verified
away becomes a fail→pass flip once the consumer cannot self-heal. Stated sharply: *the LLM
B's recovery channel makes its outcome **independent of the handoff's truth** — which is
exactly why the out-of-loop verdict shows no payoff there, and exactly why it shows full
payoff at a consumer whose outcome **tracks** the handoff.*

**The honesty caveat (so this is not over-read).** ΔB=+1.0 is the **no-recovery upper
bound**, not a claim that real pipelines fail every time. The outcome mapping
(`proceed→fail`, `redo→success`) carries the feasibility assumption (the redo reaches gold
— the same one the live LLM run makes when adjudicate-B completes the task). What is
*empirically* load-bearing, not assumed, is the pair the probe reads from the real bytes:
(a) the gate **BLOCKED 5/5** of the over-claims (so adjudicate has a correction to carry —
detection working, the payoff is bounded by it), and (b) all 5 believe-claims read as
"done" by the arm-blind classifier (none were hedged — a hedged claim would `redo` under
believe too and *not* deflect, the not-a-strawman case pinned in `test_peer_b.py`). And `n`
is tiny (5 / 4) — the docs/199 event-rate wall again: real over-claims are rare. So the
**mechanism** is proven (recovery laundering fully accounts for ΔB≈0); the **magnitude at a
real intermediate consumer** is the one cell still open — the weaker-LLM middle arm
(`0 < r < 0.6`), which needs a paid run and should land between the two endpoints.

**ATTEMPTED — the weaker-LLM middle arm, and why it is INCONCLUSIVE (2026-06-08, paid,
~\$0).** Ran `peer_b_run.py --live --model gemini/gemini-2.5-flash-lite` over the same
cached flash A-slice (A not re-run). Two findings, neither a clean middle point:

1. **It did not cleanly run.** flash-lite emitted *empty* assistant turns that tau2 rejects
   (`ValueError: AssistantMessage must have either content or tool_calls`) — the same
   empty-response bug-class docs/235 hit with `-pro`, here under `reasoning_effort=disable`.
   ~half the rollouts errored, censoring the slice to ~3 surviving over-claim rows, and on
   *different* tasks per arm (so believe and adjudicate were not even measured on the same
   rows). The reported ΔB=−33% is **one row at n=3** — inside the ±33% noise floor docs/235
   established, i.e. **indistinguishable from 0 and not a valid ΔB**. Not evidence against
   the bridge; just a broken sample.
2. **The deeper reason it does not test the regime: "weaker model" ≠ "lower self-recovery."**
   On the rows that *did* run, flash-lite still self-recovered (believe airline/1, airline/5
   landed `db_match=True`) at ≈the flash rate (2/3). Capability tier and the handoff-relevant
   variable — the self-recovery rate `r` — are **not the same axis**. flash-lite sits near
   the flash point (`r≈0.6`), so even a crash-free run would most likely reproduce ΔB≈0
   (*consistent* with `delta_b_of_r` at `r≈0.6`, not a discriminating low-`r` test).

**The honest conclusion, and the stop rule.** The discriminating middle test needs a
consumer with *measured* lower self-recovery, not one assumed weaker by its name — i.e. you
must run the H1 survival curve **per model** to pick one whose `r` is genuinely low, then
hand it the slice. I stopped here rather than retry flash-lite with `reasoning_effort=low`
until n≤5 noise happened to look like confirmation — that would be the exact over-claiming
this doc is about. **The bridge is pinned at both endpoints (non-LLM `r=0`→ΔB=1.0; LLM
`r≈0.6`→ΔB≈0) and is untested in the middle. That is the true state; do not round it up.**

### H4 — "It recovered" is a self-report that diverges from ground truth

- **Prediction.** The agent's self-assessed completion ("done / fixed") disagrees with the
  ground-truth witness (DB-hash, SHA) at a measurable, **asymmetric** rate (over-claims
  recovery more than it under-claims).
- **Harness.** Already measured: the writeadmit over-claim slice is **13.6% on frozen tau2,
  0% FP** (docs/216), and `commit-audit --sweep` is the same flip on this repo's git. "It'll
  recover" and "it recovered" are the same self-report; we already know that report is wrong
  ~1 in 7 times off a sound witness.
- **Why it belongs here.** It closes the circularity in §2.5 empirically: the prediction
  used to justify *not checking* is drawn from the same distribution we have *measured to be
  unreliable*.
- **Falsifier.** If self-reported recovery matches ground truth ~always, H4 is wrong and
  "trust the agent's 'I fixed it'" is defensible.

### H5 — On shared state, recovery is structurally 0, independent of model strength

- **Prediction.** For an effect a teammate has already consumed, `P(recover) = 0` by
  construction; a stronger model does not raise it (the bytes are gone / already read).
- **Harness.** `coord_loop.py` (docs/233): two agents on a shared reservation; producer
  errs; consumer reads. Sweep the **read timing** (consumer reads *before* vs *after* the
  error propagates) and the **model strength** of the recovering agent.
- **Decisive read.** Once the cross-agent read has happened, recovery rate is flat at 0
  across model strengths — the cleanest possible falsification of the fleet-of-one claim:
  a case where no amount of capability recovers, so prevention (the arbiter, docs/233) is
  the *only* lever.
- **Confound.** Direction of J — docs/233 already warns a live run flipped 7→6; the metric
  must be directional (prevented-clobber count off the DB-hash), not a re-projection.
- **Falsifier.** If a stronger consumer *does* recover a consumed clobber, then the effect
  was reversible after all and H5's "structurally 0" is too strong for that effect class
  (push it down the reversibility ladder, docs/212).

## 6. What this proves, and what it costs

If the program lands as predicted, the headline is one sentence with teeth: **across the
intervention results, "the model will recover" was not a finding about agents — it was an
uncontrolled variable, and once you stratify error events by recovery-feasibility the
payoff that looked absent reappears exactly where recovery is unavailable to launder it
(downstream consumers, irreversible effects, shared state).** That converts docs/202–235's
string of "net-negative" results from *"the kernel needn't act"* into *"the kernel must
act, but at the consumer that can't self-heal — not at the producer that can."* It is the
placement rule docs/206 and docs/235 were already backing into, given a witness.

The honest cost: H3's falsifier could have killed the thesis — if ΔB had been flat even at
a non-LLM consumer, recovery was *not* the confound and the bailey wins. It did not: the
non-LLM endpoint came in at the maximum (§5 H3, ΔB=+1.0, laundering gap +1.0). The whole
point of writing it as five falsifiable hypotheses with named kill conditions is that,
unlike "the model will just recover," **this claim could have lost** — and the cells run so
far went the predicted way (non-LLM endpoint at the max; H1's feasible tail real and large).

What is **not** yet settled, stated plainly: the *intermediate* of the bridge. The
weaker-LLM arm was attempted and came back **inconclusive** (§5 H3) — flash-lite hit an
empty-message runtime crash that censored the slice, and worse, it self-recovered at ≈the
flash rate, so "weaker model by name" turned out not to be "lower self-recovery rate `r`."
The next honest step is therefore *not* "rerun a weaker model" but "**measure `r`
per-model** with the H1 survival curve, then pick a genuinely-low-`r` consumer" — and I
stopped rather than retry until n≤5 noise looked like confirmation. The bridge stands pinned
at its two endpoints and open in the middle; that is the real state.

## 7. The relative-impact axis — recovery is half the equation; the other half is unbounded

§3 fixed the **probability** the recovery mindset gets wrong. This section fixes the
**magnitude** it ignores entirely. The full expected cost of *not* intervening is a product
of two factors, and the mindset under-prices **both**:

```
E[cost of inaction]  =  P(¬recover at the measured consumer)  ×  Loss(unrecovered effect)
Loss(unrecovered)    ≈  ReversibilityCost  ×  BlastRadius(time-to-detection)
```

- **ReversibilityCost** — the price to undo *one* instance of the effect if you tried right
  now. Physical / consumed / sent → effectively ∞ (you cannot un-wire a transfer, un-delete
  a prod table, un-send an email). Bytes, if caught → low (revert the commit). This is the
  docs/212 reversibility ladder (Tier-1 irreversible … Tier-3 prose).
- **BlastRadius(t)** — how much *downstream* work has been built on the poisoned state by
  the time it is caught: roughly the integral of the downstream read/consume rate over
  `[error, detection]`. Own scratch never read → ~1. A wrong premise committed to a repo
  that N agents (or humans) branch off → grows with N **and** with detection latency. This
  is the user's *"poison the repo"* term, and it is where the latency axis (docs/154) and
  the coordination/fleet axis (docs/233) enter the cost.

**The 2×2 that picks the DOS lever.** The two axes are independent, and *which cell you are
in tells you which primitive is correct* — and only one of the four cells is "let it
recover":

| | **Low blast** (own scratch, no downstream reader) | **High blast** (shared / committed / branched-on) |
|---|---|---|
| **Reversible** (bytes, if caught) | **let it recover** — the *only* cell the mindset is right; a noisy intervention is genuinely net-negative here (docs/202/205/206/235) | **POISON** — cheap to undo *per unit* but it compounds with detection latency → lever = **fast out-of-loop `verify` + the arbiter's region-lock to *contain* propagation** (catch it and bound its blast before N consumers read it) |
| **Irreversible** (physical, consumed, sent) | rare / degenerate | **CATASTROPHE** — no post-hoc recovery at any price → lever = **a PRE-action gate / `arbitrate` refuse**; prevention is the *only* lever, because there is no "recover" to wait for |

The recovery mindset silently assumes the **top-left** cell and exports its conclusion to
the whole grid. Three of the four cells are not "let it recover," and the failure in each
is a *different* DOS primitive.

**How impact multiplies into the confound.** The two factors are not independent failures
of judgment — they compound. Even when `P(recover)` is genuinely high, the mindset
multiplies it against an unexamined `Loss`. A 95%-recovery action that poisons the repo 5%
of the time at ~100 downstream-agent-hours each costs ≈5 hours *per action* in expectation —
which dwarfs any intervention. The mindset sees the 95% and looks away; it is structurally
blind to `P(¬recover) × ReversibilityCost × BlastRadius`, and that product is **dominated by
the fat-tail × high-magnitude corner** — the exact corner that matters. So §3 and §7 are the
two factors of one equation: "it'll recover" underestimates `P(¬recover)` (a base rate read
as an instance) *and* `Loss` (blast radius ignored), and the error is largest precisely
where the stakes are.

**The poison-the-repo quantity is already measurable.** The non-LLM arm (§5 H3) gives the
**1-hop deflection rate** (1.0 on this slice). `peer_b.blast_radius_curve` turns it into the
N-hop expected wasted-work: a believe-poisoned premise does not just fail consumer B — B
passes it to C, D, … and each non-re-verifying hop compounds it, while adjudicate stops it
at hop 1. So the out-of-loop verdict's value is **not** the 1-hop ΔB — it is the integral
over the chain it prevents, which is *why* measuring it at a single self-healing hop
(docs/235) so badly undersold it. The metric for the chain experiment is therefore "fraction
of the N-deep consumer chain poisoned," not "B's task success."

**Containment, not just detection — and DOS already ships it.** The arbiter's lane lock is
usually described as "don't double-write a region." On this axis it is also a **blast-radius
bound**: while one agent holds a region lease, no other agent may *read or build on* that
region, so the downstream-consumption rate over the window when the state is most likely
wrong is capped at zero. Detection (`verify`) tells you the poison happened; the region-lock
(`arbitrate`) **bounds how far it spreads** before detection lands. The reversible-high-blast
cell wants both, and both are shipped primitives — they were simply never framed as the two
halves of `Loss` containment.

## 8. The one-line consequence

"The model will recover next turn" is a true statement about **one agent, its own
reversible scratch state, with no concurrent reader, and a cheap effect** — and a category
error everywhere else. The cure is not to argue it down but to **measure every intervention
at a consumer that cannot self-heal, weighted by the reversibility and blast radius of the
effect.** Do that and the string of "net-negative" results (docs/202–235) reads not as *"the
kernel needn't act"* but as *"we kept measuring the cure where recovery was free to launder
it."* The non-LLM endpoint (§5) is the first cell of that re-measurement, and it came back
at the maximum.
