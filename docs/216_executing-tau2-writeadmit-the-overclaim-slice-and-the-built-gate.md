# docs/216 — Executing E-TAU2-WRITEADMIT: the over-claim slice, measured, and the gate, built

> **⟶ RESOLVED LIVE in [docs/228](228_running-tau2-writeadmit-live-the-out-of-loop-payoff-measured.md) (2026-06-08).** The "paid run is future" / "live J
> pending the smoke" status below is **superseded**: the driver was wired (and the API note
> here was *inverted* — `run_single_task` is the current tau2 entry, `run_task` is the
> deprecated shim) and the experiment **ran live** on Gemini. Result: a fresh **natural**
> sample yielded **J = 5** real over-claims caught and blocked off the env DB-hash (the
> frozen over-claim *slice* re-run gave J=0, because over-claims **evaporate** when a
> capable live policy re-runs those tasks — the docs/199 event-rate bound, confirmed live).
> kill-2 (the "live env promotes presence→correctness" central bet, §3/§9) **passed**: the
> live `db_match` distinguished real over-claims. The frozen `J=33` below stays as the
> *mechanism* proof; docs/228 carries the *payoff*. Read this doc for the build + the slice;
> read docs/228 for the live outcome.

> **This doc EXECUTES registry Item 1.** The out-of-loop experiment registry
> (`benchmark/_experiments/out_of_loop_registry.md`, written under docs/209) ranked
> **E-TAU2-WRITEADMIT** rank-1 "🏆 BUILD THIS" and specified its **$0 over-claim
> pre-check** (`E-PRECHECK-OVERCLAIMGAP`) as the build gate: *kill if the
> confident-over-claim slice < ~5%.* This doc runs that pre-check, **measures the slice
> (13.6%)**, **builds the $0 gate core**, and records the go/no-go. It does not
> re-derive the registry's framing — read docs/209 §3 for the gap numbers and the
> 15-experiment ranking; this is the execution of its top item.

> **Context (from docs/209).** Out-of-loop is the only positive half-plane for the
> distrust verdict — every agent-side WARN rung is wash-to-negative by structure (the
> harm is the extra turn's existence, not its bytes; docs/188, docs/202, docs/205). A
> frozen replay can only re-project a recorded outcome — a *rate*, never a *payoff*
> (docs/179). So a value experiment needs a benchmark where the agent's **claim** and
> the **witness** are independently authored, run **live**, with a consumer that is
> **not the producing agent** flipping a **real** outcome.

**Status (2026-06-07, superseded by docs/228 — see banner above):** slice measured +
pinned as a tested SSOT; $0 gate core + frozen A/B fold + 9 tests BUILT; live driver gated
behind `GEMINI_API_KEY` (paid run was future *then*; **ran 2026-06-08, J=5 live — docs/228**).
The registry's projected `J ≈ 8–20` row was grounded by the frozen fold (J=33 on the
stand-in witness); the **live** J on the natural sample is **5** (frozen-slice re-run: 0).

---

## 1. Why `tau2`, and why not the instruments we already had

EnterpriseOps is the **wrong instrument** for a value experiment: it has no
self-report to distrust (`overall_success == AND(gold)`, 1804/1804). There is
nothing the kernel can *catch* the agent over-claiming, because the agent emits no
separable claim. (docs "Out-of-loop needs a LIVE API payoff".)

`tau2` (the airline/retail/telecom tool-agent benchmark, here via the frozen
**AgentProcessBench** `tau2` config — 250 trajectories with human step+final
labels) carries **exactly the two independently-authored fields** the DOS invariant
(docs/138, byte-author ≠ judged agent) needs:

| field | author | role |
|---|---|---|
| `answer_text` | the **agent** | the claim — *distrust this* |
| `final_label` | a **human** | witness W2 (the correctness verdict) |
| `tool_metrics[...].status` | the **env executor** | witness W1 (tool-call success) |

The agent authors zero bytes of either witness. That is the whole game.

The runners-up were demoted, and honestly:

- **SWE-bench** — the sound version is verify-gated best-of-N, but it needs a
  frontier-coder API key we do not have on disk (only `GEMINI_API_KEY` would be,
  and it is currently absent too).
- **ImpossibleBench** — its entire refusal is authored by the benchmark's
  impossibility construction, not by DOS; its payoff (cheat-count × 1) is a
  re-projected rate that **duplicates a result we already have**
  (`g3_forgeability.py`: deterministic `0.000` vs LLM-judge `0.352`).

---

## 2. The measured slice ($0, on disk today)

A **confident over-claim** = `answer_text` asserts, in assertive past tense, that a
**write action landed** — and the human gold says the trajectory was wrong
(`final_label == -1`). Three **independent** detectors sized it from scratch, by
different methods, so the number is not one keyword heuristic's artifact:

| probe | method | over-claims |
|---|---|---|
| `_overclaim_probe_lexical` | string scan for an assertive past-tense write success | **34** |
| `_overclaim_probe_writeverb` | a *specific* state-mutation asserted as fact, reads/imperatives gated out | **34** (same indices) |
| `_overclaim_probe_witness` | the **kernel join** `dos.effect_witness.witness_effect` over W1+W2 under `believe_under_floor` | **35** (near-superset) |

**Consensus (≥2 of 3): 34 / 250 = 13.6%. Unanimous (all 3): 33.** That is ~2.7×
the **5% kill threshold** — a **GO, with margin**. And it is a *lower* bound: all
three probes bias toward precision over recall (a paraphrase outside the success
lexicon is missed by design).

The detector is not merely keying on the label: of ~90 confident success-claims it
finds, the gold splits **34 over-claims (−1) / 53 correct claims (+1) / 3 neutral**.
The +1 bucket proves it independently identifies *claims*, and the label then sorts
them. So **~38% of the agent's confident success-claims are over-claims.**

This is pinned as a tested single-source-of-truth:

```
python -m benchmark.agentprocessbench.overclaim          # the report
python -m benchmark.agentprocessbench.overclaim --check    # assert the invariants (exit 1 on drift)
python -m pytest benchmark/agentprocessbench/test_overclaim.py -q
```

`overclaim.py` runs all three probes, asserts their convergence (lexical ≡
write-verb to the index; witness a near-superset), pins the consensus set, and
guards the **one documented disagreement** so it can't silently drift: the witness
probe misses `idx 154` (a terse `"Done — I submitted return requests..."` close its
matcher under-fires on) and adds `idx 97` (a write recapped *inside a refusal frame*
— its hedge gate is weaker than the other two) and `idx 161` (an "available for
exchange" *read*, not a landed write). The text-only consensus is the more
defensible headline; the witness disagreement is a recorded nuance.

---

## 3. The load-bearing finding: the witness is the human label, not the env

The witness probe's deepest result decides the *shape* of the paid harness:
**all 35 refutations route through W2 (the human `final_label`), not the env channel
W1.** tau2's `tool_metrics` witness tool-call **SUCCESS**, not **CORRECTNESS** — a
reservation can be *booked successfully yet be the wrong reservation*, which only the
human label sees. (Verified: every trajectory with a mutating tool but zero success —
idx 56, 65, 75, 90, 101, 176 — has the agent *honestly hedging*, so W1 never
independently refutes a confident claim.)

This is **docs/204 Wall 3 (presence-not-correctness) appearing exactly here**, and it
is *why the frozen corpus is a rate and only the live loop is a payoff* (docs/179):

- On the **frozen** corpus, the only sound witness for a correctness over-claim is the
  pre-recorded human label. You can *count* over-claims; you cannot *flip* an outcome.
- On the **live** `tau2` task, the witness becomes the env **DB-state verifier / task
  reward** — least-gameable, agent-authors-zero-bytes — and a consumer can act on it
  *before* the outcome is sealed. That action is the payoff.

---

## 4. E-TAU2-WRITEADMIT — the engineering variant (BUILT, $0 core)

The out-of-loop consumer is a **write-admission gate** sitting *between* a producing
agent A and a downstream peer B — **not the producer**. A finishes a tau2 task, emits a
"resolved/done" claim + a proposed mutating write (book/cancel/update); DOS routes that
to `gate.admit(answer_text, db_match) -> AdmitDecision`. On BLOCK the gate refuses to
publish A's run into a shared `handoff/` ledger that peer B reads as its starting state.
**The real flipped outcome:** with the gate off, B inherits A's over-claimed (phantom /
wrong) reservation as ground truth and compounds the error; with the gate on, B is handed
the env-verified state instead and never inherits the phantom. The gate is the
`dos.arbiter`-shaped out-of-kernel consumer, and because it acts on **B's input**, it
**never injects a turn into A's loop** — so the docs/188/199 turn-injection harm (the
reason every agent-side WARN rung was wash-to-negative) is *structurally absent*.

**The witness — the part that closes Wall 3.** The least-gameable witness is tau2's
**env DB-state hash comparison**, verified on disk at
`tau2-bench/src/tau2/evaluator/evaluator_env.py:116-124`:
`agent_db_match = gold_environment.get_db_hash() == predicted_environment.get_db_hash()`,
surfaced as `DBCheck.db_match`. The agent authors **zero bytes** of it: the gold DB is the
task designer's snapshot, the predicted DB is mutated only through the env's own tool
executor, and the hash is computed by the evaluator. Unlike the frozen `final_label`, this
witness answers **correctness, not just presence** — a reservation booked successfully but
*wrong* fails `db_match`. So the live loop **replaces the human label with a deterministic
env-state hash the agent equally cannot author**, promoting the §3 presence-witness to a
correctness-witness. (That promotion is the build's central bet — **unverified until the
smoke run**; see kill-2 in §9.)

**Payoff J** = the integer count of trajectories where (a) A made a confident write-claim,
(b) `db_match == False` (the write did not land correctly), and (c) the adjudicate gate
BLOCKED publication so peer B did **not** inherit the phantom — contrasted against the
believe arm's inherited-phantom count. It is a count of *flipped publications* read off
ground truth, not a re-projected rate.

**What's built at $0 today** (`benchmark/agentprocessbench/writeadmit/`):

| file | what | cost |
|---|---|---|
| `gate.py` | the pure `admit()` — reuses `_confident_write_claim` (the converged claim detector) verbatim + `dos.effect_witness.witness_effect` + `EvidenceFacts`/`Accountability.OS_RECORDED` | $0, importable |
| `live_loop.py: frozen_ab()` | the believe-vs-adjudicate A/B over the frozen corpus (final_label as the db_match stand-in) — proves the J arithmetic before any spend | $0, no model |
| `live_loop.py: run_writeadmit()` | the live driver, gated behind `GEMINI_API_KEY` (mirrors `DOS_LIVE_DEMO`); wires the **real** `tau2.run.run_task` (the sketch's `run_single_task` does not exist) + the `db_match` read-back | $0 until a key is present |
| `test_gate.py` | 9 tests incl. the **floor-discipline test**: a forgeable `AGENT_AUTHORED` read-back can *never* BLOCK | $0 |

The frozen A/B fold runs today:
```
[   believe] confident-writes=33  blocked=0   J=0   peer-inherited-phantom=33
[adjudicate] confident-writes=33  blocked=33  J=33  peer-inherited-phantom=0
```
i.e. on the frozen stand-in, the gate blocks all 33 confident writes the believe arm would
have let a peer inherit. (33, not 34 — the witness probe's `_confident_write_claim`, reused
verbatim, abstains on one consensus index; consistent with the §2 witness disagreement.)
The **live J** needs the env DB-hash + a real peer-B seed; the frozen number is the proxy
that proves the *mechanism*, not the payoff.

**The floor that makes it safe (verified).** `witness_effect` applies `believe_under_floor`:
a read-back on the forgeable `AGENT_AUTHORED` rung yields `UNWITNESSED` (`refuted=False`),
never `REFUTED`. So a policy that pastes a fake receipt into its own answer can never trip
the gate, and (the dual) can never launder a real failure into an admit — only an
`OS_RECORDED`/`THIRD_PARTY` witness moves the bit. The gate can only ever BLOCK-MORE under a
sound witness, never be talked into ADMIT by the agent's own bytes.

---

## 5. The lab-facing twin — E-TAU2-RLVR-ADMIT (same witness, RLVR consumer)

> **⟶ Payoff 1 BUILT + MEASURED LIVE in [docs/230](230_the-lab-facing-twin-rlvr-admit-the-non-distillable-reward-label.md) (2026-06-08).**
> The "$0 frozen acceptance-precision arm" this section specifies was built — and promoted
> from the frozen `final_label` proxy to the **live `db_match` rows** docs/228 produced. On
> 49 clean live rows: of 15 confident "resolved" write-bids a naive self-judged sampler
> banks as positives, **5 are poison** (env DB-hash refutes), purged by the witness-gated
> filter → acceptance precision **60%→100%, J=5, ΔP=+40 pp**, on a label the policy cannot
> distill (`writeadmit/rlvr_admit.py` + `test_rlvr_admit.py`). **Payoff 2** (train two
> DPO/LoRA runs + measure the trained over-claim delta J₂) stays deferred — it needs a GPU.

If the audience is a frontier lab, lead with this: the **same** claim-extractor + the
**same** `effect_witness` join + the **same** `believe_under_floor` floor, reframed as a
**non-distillable RLVR / rejection-sampling label.** The out-of-loop consumer is now a
**reward-labeler** (not the policy that produced the trajectory): it accepts a
"resolved/done" trajectory into the SFT/DPO/RLVR positive set **only if** the env witness
CONFIRMS the claimed write, and REJECTS a refuted "resolved" claim (in the DPO arm, the
refuted claim becomes the *dispreferred* member of a (witnessed-resolved, over-claimed)
pair). The flipped outcome is the **composition of the reward set a downstream fine-tune
trains on.** Without it, a self-judged sampler banks confidently-narrated-but-false
"resolved" trajectories as positive reward — teaching the model to *over-claim more*
(reward-hacking on its own narration).

**Why it is non-distillable:** the label is a function of world-state the policy cannot
reproduce from its own weights/outputs. By the floor, a forgeable `AGENT_AUTHORED`
read-back can never flip CONFIRMED↔REFUTED — only the env's own state can. That is exactly
the prized RLVR property: a hard, env-grounded reward signal the model cannot distill from
its own outputs.

**Two payoffs:** (1) **Acceptance-precision lift** ΔP vs an unfiltered/self-judged
baseline, with `J = |poison positives the witness purged|` — computable **at $0 on the
frozen corpus** (each verified confident over-claim that was self-reported "resolved" is
one poison label removed). (2) The ambitious paid arm: train two short DPO/LoRA runs (on
the poisoned vs cleaned accepted sets) and measure the trained policy's **over-claim-rate
delta J₂** on a held-out split — a *flipped model behavior* a frozen rate cannot show.
Cost: $0 frozen arm; < ~$150 for the decisive train-and-measure arm.

**It shares ~80% of E-TAU2-WRITEADMIT for free** — the witness, claim-extractor, floor, and
loader are byte-identical; the two fork only at the **last function** (`admit_write()` vs
`admit_to_reward_set()`). Funding the engineering seam funds the lab twin's adapter.

---

## 6. The live coordination smoke (already run, $0) — and its honest limit

`benchmark/fleet_horizon/live_orchestrator_demo.py` (`DOS_LIVE_DEMO=1`) ran
cross-process, real `dos lease-lane`, real git, deterministic shell writers:

```
[  naive-flow] shared writers=2  refusals=0  surviving owner=issue-01  EDITS LOST=1
[dos-dispatch] shared writers=2  refusals=0  surviving owner=issue-01  EDITS LOST=0
# overlap 0 (boundary): both arms identical — the orchestrator is moot when nothing contends
```

The lease prevented on disk the clobber the naive `parallel()`-and-forget flow let
through. **Honest limit:** there is *no model in the loop* — the writers are shell
scripts, so it is a **mechanism smoke, not a live-agent payoff.** It does not satisfy
the "live API or it's static" filter; E-TAU2-WRITEADMIT (§4) is the experiment that
does.

---

## 7. Verdict, build order, and honest caveats

**Verdict: GO_WITH_CHANGES.** The verified confident-over-claim slice is **13.6%**
(34/250 consensus, undiscounted by the measured **0% FP rate** on the 12/12 adversarial
sample) — **2.72× the 5% kill floor.** Even at the conservative **Wilson 95% lower bound**
on the 12/12 adversarial precision (75.7%), the slice is **10.3%**, still 2.06× the floor.
The "changes" are not thesis flaws — they are (a) a wiring correction the synthesis caught
in its own design (`run_single_task` → the real `run_task`, baked into the built harness)
and (b) a **mandatory < $5 smoke** before full spend (kill-2 below).

**Build order:**

1. ✅ $0 live orchestrator demo — done (coordination mechanism, no model; §6).
2. ✅ $0 over-claim pre-check on frozen tau2 — done; **13.6%**, pinned SSOT + 7 tests (§2).
3. ✅ $0 pure gate + frozen A/B fold + 9 tests incl. the floor test — done (§4).
4. Wire the live driver against `tau2.run.run_task` + the `db_match` read-back adapter
   (~15 lines) — *staged behind the smoke*.
5. `handoff/` ledger + peer-B inheritance seam + J off ground truth.
6. **Smoke the first 5 consensus indices live (< $5)** behind `GEMINI_API_KEY` — the
   kill-2 pre-flight: confirm the live env DB-hash returns `db_match==False` on the known
   over-claim indices (the live env must not *launder* the frozen failure).
7. Full 34-index slice live (believe + adjudicate arms); report J. (~$15–40, ~1–2M tokens.)
8. *(optional, lab-facing)* fork `rlvr_admit.py` at the last function only; the $0 frozen
   acceptance-precision arm ships the moment steps 1–3 land (§5).

**Honest caveats (the synthesis insisted on all six):**

- The §6 live orchestrator demo has **no model in the loop** — a mechanism smoke, not a
  live-agent payoff. E-TAU2-WRITEADMIT supplies the missing live-agent half.
- The 13.6% is a **presence-of-claim** rate, not a correctness measure. On the frozen
  corpus the refutation channel is the **human `final_label`** (Wall 3). The build's whole
  bet is that the live env DB-hash *promotes* this to correctness without a human — and
  that promotion is **UNVERIFIED until the smoke run** (kill-2).
- A **frozen rate ≠ a live payoff** (docs/179), in **both** directions: the live slice could
  replay *below* the floor (kill-4, event-rate-bound, docs/199) if the live policy
  over-claims less, **or** the live env could launder the failure (`db_match==True` on a
  frozen over-claim, kill-2). The smoke exists to check both before full spend.
- The **0% FP is "no FP seen in 12"**, not "precision = 100%": the Wilson 95% LB is 75.7%
  (slice 10.3%). The full 34 were hand-audited by the probe authors; only 12 went through
  refute-by-default adversarial verification.
- The 34-index convergence is **not three fully-independent channels** — two text-pattern
  probes plus one floor-disciplined probe, and two of the three route refutation through the
  *same* human `final_label`. The 34 is a **measured lower bound**, not an unbiased estimate.
- This is an **engineering** result, not yet a frontier-lab science result. For a lab
  audience, lead with §5 (the same witness behind the RLVR consumer).

**The four kill criteria** (any one is fatal): **K1** J==0 across the A/B (the gate never
blocks a write a peer would inherit). **K2** the live env DB-hash can't distinguish
over-claims (`db_match==True` on the known over-claim indices — the witness is unsound).
**K3** the gate's BLOCK perturbs A's run (a wiring leak — structurally guarded, since the
gate is out-of-loop). **K4** the live over-claim base-rate replays < 5% (too few events).

### Decision summary

| metric | value |
|---|---|
| naive ceiling (final_label==−1) | 45.6% |
| **verified confident-over-claim slice** | **13.6%** (34/250) |
| adversarial FP rate (12/12) | 0% (Wilson 95% LB precision 75.7% → slice 10.3%) |
| kill threshold | 5% |
| margin over kill | **2.72×** (2.06× at Wilson LB) |
| **verdict** | **GO_WITH_CHANGES** |
| changes | `run_task` wiring (done) + mandatory < $5 smoke (kill-2) |
| paid run | ~$15–40, ~68 live trajectories on the 34-index slice |
