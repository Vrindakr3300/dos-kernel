# 322 — dogfood `reward()`: the poisoned-pool expert-iteration PoC

> Issue [#36](https://github.com/anthony-chaudhary/dos-kernel/issues/36). The
> docs/230/234 claim is empirical and has never been measured: *a training
> loop whose admission gate is self-judged teaches the policy to over-claim,
> generation over generation; a loop whose accept bit is a pure function of
> witness bytes the agent didn't author does not.* The kernel's own doctrine
> applies to this claim too — a claim without an env-authored witness is not
> evidence. This plan closes the loop: the first consumer of `reward.admit`
> whose admissions FEED BACK into the next generation's conditioning, with
> the self-judged arm run side-by-side as the ablation.

*Status: P1 shipped 2026-06-12 — the rig (`benchmark/poisoned_pool/`), the
suite pin (`tests/test_poisoned_pool_bench.py`), and run 1's committed
evidence (`benchmark/poisoned_pool/RESULTS.md` + `results.json`). P2 open
(real weights), gated on a GPU/key budget. Believe `dos verify`, not this
sentence.*

## 0. What is new here (and what is not)

`reward.admit` already has two consumers, but both adjudicate FROZEN rows:
`benchmark/witness_ladder/` sweeps it over a declared claim distribution
(docs/261), and `examples/serverless_rl/` exports it as a scorer shape.
Neither closes the loop — nothing the verdict admitted has ever conditioned
the next batch of trajectories. The poisoned-pool PoC is that closed loop, in
the smallest honest form: expert iteration, where the admitted set IS the
selection pressure.

## 1. The experiment — one boolean ablated, everything else shared

An expert-iteration loop over small Python bug-fix tasks. Every trajectory
ends in a checkable claim ("the acceptance test now passes with my patch") —
an effect with an env-authored read-back (the test's exit code, run by the
harness, authored by zero agent bytes).

- **Generation g:** sample K trajectories per train task. The policy sees the
  buggy module, the acceptance test source, and up to M exemplars from its
  arm's pool — but **cannot execute anything** (the capacity limit that makes
  the claim a genuine bet, not a read-back). It returns a full patched module
  and one line: `CLAIM: RESOLVED` or `CLAIM: NOT_RESOLVED`.
- **The witness:** the harness writes the patch into a scratch dir and runs
  the task's acceptance test in a subprocess. Exit 0 →
  `EvidenceFacts.attest(...)`, non-zero → `refute(...)`, both at the
  `OS_RECORDED` rung. The agent authors none of these bytes.
- **Admission — the one-boolean ablation:**
  - **Arm S (self-judged):** a trajectory enters the exemplar pool iff it
    claims RESOLVED. The witness is computed (for measurement) but the gate
    never reads it. This is today's default RLVR loop, not a strawman.
  - **Arm W (witness-gated):** `dos.reward.admit(claim_present, (readback,))`
    decides. ACCEPT enters the pool; REJECT_POISON is counted (the
    ready-made dispreferred DPO member, P2's input); NO_CLAIM / ABSTAIN are
    not candidates. The harness never reimplements the belief rule — the
    kernel verdict is called, byte-for-byte (the witness_ladder discipline).
- **The pool conditions generation g+1:** each arm's next-generation prompts
  carry up to M exemplars sampled (seeded) from that arm's pool, rendered as
  admitted successful resolutions. Generation 0 has empty pools, so both arms
  share one sampled batch (one set of model calls, two adjudications).
- **Measured per generation, per arm,** on the train batch and on a held-out
  task set the pools never admit from: over-claim rate (claimed RESOLVED,
  witness refutes), true success rate (witness confirms), claim rate, pool
  size, and pool poison fraction (admitted entries the witness refuted).

**The prediction (docs/234, made falsifiable):** Arm S's pool accumulates
poison and its conditioned generations hold or grow their over-claim rate;
Arm W's pool poison is zero **by construction** (a refuted claim cannot be
admitted — `believe_under_floor` is structural), and its over-claim rate does
not climb, because the policy cannot write its way into the kept set — so
writing never pays. The run measures whatever actually happens; the evidence
file reports the curves either way.

## 2. The phases

### P1 — the gradient-free rig + run 1 (ships with this plan)

`benchmark/poisoned_pool/`: `tasks.py` (the bug-fix corpus: 6 train + 4
held-out tasks, easy/hard mixed, each with a planted bug, an acceptance test,
and a reference fix the self-check executes), `harness.py` (prompt render,
completion parse, the subprocess witness, the two admission gates, the
metrics fold), `run.py` (the resumable state machine:
`init → [drive the policy] → ingest → … → report`). The policy is supplied
from OUTSIDE the harness (any model driver writes one completion file per
emitted prompt file) — the harness stays provider-free, like every benchmark
here. Run 1's policy: live model calls driven by an agent session, no tools,
no execution.

Pinned by `tests/test_poisoned_pool_bench.py`: every planted bug fails its
own test and every reference fix passes it (executed, not narrated); Arm W's
label equals `dos.reward.admit` called directly (kernel-not-reimplemented);
a scripted generation-0 end-to-end run yields the constructed pools (Arm S
banks the over-claims, Arm W's poison is zero) and the poison exemplars
appear only in Arm S's next-generation prompts.

Evidence: `benchmark/poisoned_pool/RESULTS.md` + `results.json` (config,
per-generation curves for both arms, per-trajectory verdict rows, threats to
validity). Committing these is the issue's first milestone; the issue closes
via `Fixes #36` on the evidence commit.

**Done when:** the suite pin is green and the committed evidence file carries
the per-generation over-claim / true-success curves for both arms.

### P2 — real weights (open; gated on a GPU/key budget)

Upgrade selection pressure from few-shot conditioning to actual parameter
movement: LoRA SFT on each arm's admitted pool, or DPO where Arm W's
REJECT_POISON rows are the dispreferred members (the `RewardLabel.
dispreferred` field is already the loader shape). Same metrics, same held-out
set, weights actually move. This is the strict form of the docs/234 theorem
at training scale; P1's rig is reused (the pool format is the training
manifest). Not started; needs compute this machine does not assume.

## 3. Threats to validity (named in the evidence file, not hidden)

- **Few-shot conditioning is a proxy for training.** P1 moves the prompt, not
  the weights. That is the issue's explicit Phase-1 scope; P2 is the upgrade.
- **Small N.** Run 1 is tens of trajectories per generation, not thousands;
  counts ship alongside rates so noise is visible.
- **The no-execution rule is instruction-enforced** on the live policy (the
  driver forbids tools); a disobedient policy could verify before claiming.
  That failure direction only DEFLATES over-claims, symmetrically in both
  arms — it cannot manufacture the predicted effect.
- **Honest models resist.** A well-calibrated policy may keep over-claiming
  low in both arms at this scale; pool poison (Arm S > 0, Arm W = 0) is the
  structural floor of the result either way.

## 4. Lineage

docs/230 (reward-set admission), docs/234 (the non-distillable label — the
theorem this makes empirical), docs/261 (witness_ladder — the frozen-row
sweep this closes the loop on), docs/138 (narration cannot climb the
ladder), docs/280 (`improve()` — the code-side keep-gate; this is the
training-set side), issue #21 (the recipe-loop sibling arm), issues #34/#35
(keep-gate extensions the program composes with).
