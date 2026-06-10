# Ground-truth trajectories — the kernel as a training-data instrument

> **A fleet running under the kernel emits, per step, the one tuple agent
> training is starved for: what the worker *claimed*, what *actually happened*,
> and how we *know* — with the claim and the truth held rigidly apart.**

[`79_primitives-not-features.md`](79_primitives-not-features.md) argues the
syscalls are deliberately small so a space opens *above* them;
[`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
argues every syscall is a kind of *no*. This note points one of those
above-the-kernel spaces at a concrete consumer: **the data exhaust of a fleet
that is not believed is exactly the supervision signal you need to train the
next fleet to lie less — and, more surprisingly, it tells you precisely *which
part of the referee can be distilled away and which part is irreducible.***

The thesis in one line: **the kernel does not just adjudicate a fleet; by
adjudicating it, the kernel *labels* it — and a per-step ground-truth label that
is not the agent's own word is the scarce raw material of agent training.**

This is not a new syscall and not a kernel change. It is a *reading* of what
`verify()` / `arbitrate()` / `spawn` already produce, made concrete by an
experiment in [`benchmark/fleet_horizon/`](../benchmark/fleet_horizon/) that you
can run and falsify.

---

## 1. The data everyone trains on is contaminated at the source

Agent-training data comes in two flavors, and the repo's own field record
(the calibration note in [`agent.py`](../benchmark/fleet_horizon/agent.py)) says
both are poisoned the same way:

| Flavor | What the label is | The contamination |
|---|---|---|
| **Outcome-labeled** (one reward / trajectory) | a grader's pass/fail on the final state | METR: ~half of *test-passing* SWE-bench-Verified PRs would be **rejected** by a maintainer — a ~24pp grader over-optimism. Train on it and you reward *convincing*, not *correct*. |
| **Self-narrated** (the ReAct trace *is* the data) | the agent's own "I ran the tests, they pass" | PAE: 27–78% of tau-bench "successes" are **procedurally corrupt** — right answer, fabricated process. Train on the narration and you train the narration. |

Both reduce to one failure: **the label is downstream of something the agent
said.** A grader that believes a passing test believes the agent's framing of
"done"; a trace is the agent's framing by definition. This is reward hacking
baked into the dataset before any policy gradient is taken — the supervised
analogue of the exact thing [`CLAUDE.md`](../CLAUDE.md)'s epigraph names: *the
part that doesn't believe the agents.*

A non-believing kernel produces neither flavor. Per adjudicated step it produces:

```
(claim-side features)  →  (ground-truth label)   ⟂   (verdict + provenance)
   what a believer            really_committed,          oracle.is_shipped():
   could observe              checkable by hand          shipped / source-rung
```

The label is **`really_committed`** — did a real commit land — derived by
[`oracle.is_shipped`](../src/dos/oracle.py) against a **real git repo**, never
from the worker's `{shipped: true}`. In the benchmark it is literally checkable
with `git log` in the temp repo (`README.md` §honesty). That is the rare part:
**a dense, per-action label that is not the agent's word and not a human's
after-the-fact guess.**

One actual record from a dump (`verifier.py --dump`), a **caught lie** — the
worker claimed shipped, the kernel found no commit:

```json
{"claimed_shipped": true, "claimed_sha": "fake0001093a", "n_files_written": 2,
 "touches_shared": false, "is_rework": false,        ← FEATURES (believer-observable)
 "really_committed": false, "real_sha": "",          ← LABEL (git ground truth)
 "verdict_shipped": false, "verdict_source": "grep",  ← VERDICT + provenance rung
 "is_caught_lie": true, "arbiter_outcome": "acquire", "refusal_reason": "",
 "run_id": "RID-1KT1…", "root_id": "RID-1KT1…", "effort": "effort-02", "phase_id": "E02.00"}
```

The features say "looks done" (`claimed_shipped: true`, two files); the label
says otherwise (`really_committed: false`); the verdict records *how we caught
it* (`source: grep` — no commit found). A believer trains on the first line; DOS
hands you all three, aligned.

---

## 2. Four channels, four supervision signals

The closed loop already constructs every field below at the moment it
adjudicates each phase; [`trajectory.py`](../benchmark/fleet_horizon/trajectory.py)
captures them as a `TrajectoryStep` instead of letting `score()` collapse them
to scalars. Each channel is a distinct training signal:

| Channel | Kernel source | What it trains |
|---|---|---|
| **Claim vs. truth** | `Claim.claimed_shipped` vs `.really_committed` | **Honesty reward** — *did the stated outcome match reality?* The single most load-bearing label in agent alignment, and here it is per-step, not per-episode. |
| **Verdict + provenance** | `ShipVerdict{shipped, source}` (`registry`/`grep`/`none`) | **Calibrated grading** — not just right/wrong but *how we know*. A reward model trained on the rung learns to distrust the signals an agent can fake (self-report) and trust the ones it cannot (ancestry). The `docs/76` rung-ladder, as features. |
| **Refusal + reason** | `arbiter.arbitrate → decision.reason`, the closed `ReasonRegistry` | **Legible negative examples** — every refused write is a labeled "don't, *and here is the class of why*" (collision / self-modify / scope). A ready-made penalty taxonomy / action-mask. |
| **Lineage + journal** | `RunId{run_id, parent_id, root_id}` + the `lane_journal` WAL | **Multi-agent credit assignment** — `root_id` is a join key; you attribute a downstream defect to the exact upstream step, instead of timestamp-grepping the causal tree. |

The fourth is the sleeper. **Multi-agent credit assignment is open** — when a
fleet collaborates and the result is bad, which agent's action gets the negative
gradient? The correlation spine ([`run_id.py`](../src/dos/run_id.py)) was built
to debug crashes, but a sortable, lineage-carrying, append-only decision log is
*exactly* the structure that problem needs. Same structure, two uses — not a
coincidence: both are "reconstruct who actually did what across unreliable
narrators."

---

## 3. The experiment: how much of the referee can you distill away?

A pitch could stop at §2. The honest question is sharper, and falsifiable: **if
the kernel's verdict is a good label, can a cheap model learn to reproduce it
from the claim-side features alone — letting you drop the referee at inference
time — or is the git check irreducible?**

[`verifier.py`](../benchmark/fleet_horizon/verifier.py) runs it. Generate a
FleetHorizon trajectory (the closed loop, real git repo), split train/test, fit
a dependency-free logistic regression to predict `really_committed` from
**claim-side features only** (what the worker said + how many files it wrote +
whether it reached shared state + rework), and score on the held-out test set.
Two numbers, both honest, plus an **ablation** that removes `sha_looks_real` — a
simulation artifact (the sim tags fabricated shas with a `fake` prefix; a real
fleet would never hand you a forgeable tell), so the ablated number is the one
that means anything.

Result (lie_rate 0.12, seed 1729; the ablated row is the honest one):

```
6 efforts × 15 phases            accuracy   base rate   lift     AUC
  full (with sha tell)           1.000      0.733       +0.267   1.000   ← artifact: ignore
  ablated (honest)               0.900      0.733       +0.167   0.776
     weights: n_files_written +2.14,  touches_shared −0.38,  claimed_shipped 0.0

8 efforts × 30 phases            accuracy   base rate   lift     AUC
  full (with sha tell)           1.000      0.887       +0.113   1.000   ← artifact: ignore
  ablated (honest)               0.950      0.887       +0.062   0.731
     weights: n_files_written +2.30,  touches_shared −1.30,  claimed_shipped 0.0
```

Claim-side shape carries **real signal** (AUC 0.73–0.78 ≫ 0.5) — but bounded, at
both scales. The breakdown is the actual finding, and it is identical across
cells. Among test-set steps that claimed shipped but **never really committed**:

```
                                  6×15        8×30
PURE LIES   (0 files written)     5 / 5       5 / 5   flagged   ← learnable from shape
FLAKES      (files written, fail) 0 / 3       0 / 4   flagged   ← shape-IDENTICAL to a real ship
```

The weight `n_files_written = +2.14` *is* the learned tell: a lie that writes
nothing is detectable from the claim alone, and the model finds it. But a
**flake** — really tried, wrote the files, the commit silently didn't land —
emits the *same* claim and the *same* files as a success. There is no claim-side
feature that separates them. **Only git knows.** (`claimed_shipped` gets weight
0.0 because every attempt claims shipped — a constant, correctly useless. That it
fell out to zero is a small proof the features carry no label leak.)

So the result is neither "distillation works" nor "it fails." It is a **precise
irreducibility boundary**:

> **You can distill the pure-lie detector into a cheap inference-time filter. You
> cannot distill the flake detector, because a flake is observationally identical
> to a success until you check the artifact. The referee is reducible on the part
> the agent reveals and irreducible on the part only the world knows.**

That is the strong result *for* DOS, and it falls out of the data rather than
being asserted: the kernel earns its place not because lies are hard to spot —
some are trivial — but because **the residue that survives a learned filter is
exactly the residue that requires distrusting the claim against ground truth**,
which is the kernel's whole job (the standing rule: never distrust judgment,
always distrust *claims of completion*). Raise the flake rate and the
irreducible floor rises with it; that monotonicity is the falsifier — if a
verifier ever cleared the flakes from claim-side shape alone, the thesis would be
wrong.

---

## 4. What this is, and (honestly) what it is not yet

The discipline that keeps the benchmark honest (`README.md` §honesty) applies
double here, because "training data" is an easy place to over-claim.

**What it is today: a verifier/labeler factory.** The labels are real, dense, and
per-step, and the experiment shows they are partially learnable with a hard,
characterizable floor. That is genuinely useful — it is the dataset you want for
training a **process reward model** (a PRM that scores intermediate steps), and
the closed-loop arm is structurally a *process-verified-trajectory generator*: a
trajectory whose every intermediate claim was `verify`-confirmed against ground
truth, which the open-loop arm **cannot** produce because it believes the claims.
The gap between the arms *is* the contamination rate, made per-step.

**What it is not yet: a policy-gradient environment.** The worker is a seeded
`FailureModel`, not a policy — a lie is a coin-flip at `lie_rate`, not a learned
behavior. So today's data trains a *reward/verifier* model well and is **useless
for training the policy** — there is no interesting behavior to imitate. The
honest framing: *the kernel is a labeler here, not a gym.* The seam to change
that already exists and is small — swap `Worker.attempt`'s coin-flip for a real
`claude -p` call and keep the kernel as the reward source; the closed loop
already drives the *real* kernel against a *real* git repo, so only the worker is
simulated.

**Two scope lines that must not blur:**

- **"Ground truth" = "a commit exists," not "the commit is correct."** The
  honesty label is real; a correctness label is out of scope, by design
  (the flexibility geometry of [`76`](76_flexible-goals-and-verification.md): the
  give lives in *which signals* and *provenance*, never in the adjudication —
  distrust completion, not judgment). A `verify`-confirmed ship can still be wrong
  code. The reward signal
  is *didn't lie about shipping* — necessary, not sufficient.
- **Simulated failure rates ≠ a real fleet's distribution.** Fixed lie/flake
  rates are right for stress-testing a verifier and for proving the
  irreducibility boundary; they are not a substitute for on-policy data.

---

## 5. Why it belongs in this repo's story

This is the training-data face of two things already argued here.
[`78_typed-outcome-adoption-plan.md`](78_typed-outcome-adoption-plan.md)
calls the reason vocabulary *DOS's `tsconfig.json`*; pointed at an ML pipeline,
**reasons-as-labels** is that same idea — a closed, declared vocabulary is a
ready-made label space. And it deepens
[`81_velocity-economics-and-the-fleet-benchmark.md`](81_velocity-economics-and-the-fleet-benchmark.md):
the FleetHorizon instrument was built to measure *believed-vs-adjudicated
verified-velocity-per-$* (the unpublished quadrant in the prior-art survey).
This note observes a **second artifact sitting inside the same instrument** — the
adjudicated arm is also a clean-trajectory generator — and a second, arguably
larger claim: the kernel does not only make a running fleet trustworthy; *its
exhaust makes the next fleet trainable, and tells you exactly how much of the
kernel you could ever hope to amortize into a model and how much you must keep.*

It also sharpens the [`79`](79_primitives-not-features.md) thesis with a concrete
"after done" example: nobody added a *training-data feature* to the kernel. The
per-step label, the provenance rung, the refusal taxonomy, and the lineage join
were all already there — the dataset is what you get by *reading* the four
refusals as supervision, exactly the kind of build-above-the-primitive the small
syscalls were kept small to permit.

---

### Reproduce / falsify

```bash
# the distillation experiment (one closed-loop pass, full vs. ablated feature sets)
PYTHONPATH=src python -m benchmark.fleet_horizon.verifier --efforts 6 --phases 15

# the falsifier: raise the flake rate and watch the irreducible floor rise
#   (edit FailureModel.flake_rate, or sweep efforts/phases — the flake residue
#    must never be learnable from claim-side shape alone)
PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_trajectory.py -q
```

The trajectory dump (`trajectory.py`) is a faithful projection of the SAME run
the A/B scores — passing a `sink` to `closed_loop.run` changes no scoring and no
kernel call, it only observes — so the labels in the dataset are the labels in
the headline table, by construction. One honest scope note: the *training signal*
(features + label + verdict) is fully reproducible from the seed, but the
`run_id`/`root_id` lineage fields are minted per run (a correlation spine mints
unique ids by design), so two dumps of the same seed match on everything a
trainer learns from and differ only on those per-run identifiers.
