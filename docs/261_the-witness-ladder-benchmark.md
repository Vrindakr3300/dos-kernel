# docs/261 — the Witness Ladder benchmark: value rises, then the witness runs out

> **Status:** PROTOTYPE BUILT (2026-06-09). A new $0 benchmark whose *independent
> variable is witness strength itself*. It drives the real kernel verdict
> (`dos.reward.admit`) over a task distribution stratified by the
> `Accountability` rung of each task's available witness, and plots one monotone
> curve. The same curve carries both halves of the DOS story: the rising arm is
> the **value** (poison purged where a non-forgeable witness exists), and the flat
> **abstain band** at the weak rung is the **growth edge** — quantified as a
> fraction of the distribution, and labelled with the witness that, if built,
> would convert it. Provenance: `benchmark/witness_ladder/` (harness + scorer +
> tests), registered in `benchmark/registry.py` as `witness_ladder`. Companion to
> the four-walls note (docs/204) and the fleet-figure (docs/256); it is the
> §3-wall (presence-not-goal) made into a measurement instead of a caveat.

## The one sentence

Every DOS benchmark we have asks *"given a checkable witness, does the gate pay
off?"* — and they all sit at a single fixed point on the witness-strength axis;
this benchmark makes that axis the variable, sweeps it, and shows that the
referee's value is a **monotone function of how unforgeable the available witness
is** — climbing to a hard ceiling at the rung where the only remaining witness is
one the agent itself authored, which the kernel refuses to believe.

## Why this is the missing benchmark

Read the existing six (`benchmark/_BENCH_MAP.md`) along one axis and a pattern
jumps out. Each one holds the witness *fixed* and varies something else:

| benchmark | the witness it uses | what it varies | the axis it is blind to |
|---|---|---|---|
| `fleet_horizon` | git ancestry (presence) | fleet size K, horizon | witness *strength* (one rung) |
| `agentdiff` / tau2 write-admit | env DB-hash / assertion engine | model tier, sample | witness *strength* (one rung) |
| `toolathlon` | third-party score | detector | witness *strength* (fixed corpus) |
| `agenthallu` / `agentprocessbench` | gold step label | dataset | witness *strength* (one rung) |
| `enterpriseops` | env state | intervention arm | witness *strength* (one rung) |

The four-walls note (docs/204) **names** the witness ladder —
W0 narration → W1 env-ack → W2 presence → W3 invariant — and calls §3
(presence-not-goal) the deepest wall, with the honest estimate that *~38% of
frontier goals reach no sound witness*. But that 38% is a **caveat in prose**, not
a curve any harness emits. No benchmark in the suite varies the rung. So the one
thing the whole four-walls framing turns on — *how far does the value go as the
witness weakens, and exactly where does it stop?* — has never been **plotted**.

That is the gap this fills. It is the §3 wall promoted from a footnote to an
instrument: instead of asserting "the witness runs out," it **measures where**, on
a distribution, with a number that moves when you add a witness.

## The mechanism — one kernel call, swept over a rung axis

The kernel already has the exact verdict this needs:
`dos.reward.admit(claim_present, readbacks) -> RewardLabel` (docs/230/234,
`src/dos/reward.py:247`). It takes

- `claim_present` — the host extractor's **forgeable** bit (did the trajectory
  claim "resolved/done"?), and
- `readbacks` — a tuple of `EvidenceFacts`, each carrying an `accountability`
  rung (`AGENT_AUTHORED` / `OS_RECORDED` / `THIRD_PARTY`, `src/dos/log_source.py:84`)
  and a `stance` (`ATTESTED` / `REFUTED` / `NO_SIGNAL`),

and returns one of `ACCEPT / REJECT_POISON / ABSTAIN / NO_CLAIM`, under the
load-bearing rule it inherits from `believe_under_floor`:

> ACCEPT ⟺ claim present **and a non-forgeable witness CONFIRMED**.
> REJECT_POISON ⟺ claim present **and a non-forgeable witness REFUTED**.
> ABSTAIN ⟺ claim present but **only a forgeable read-back, or no signal**.
> NO_CLAIM ⟺ no claim.

The crucial property for this benchmark: **`admit`'s verdict is a function of the
witness rung, holding the claim and the ground truth fixed.** A claim that is in
fact wrong yields `REJECT_POISON` when an `OS_RECORDED` witness refutes it, but
`ABSTAIN` when the only available read-back is `AGENT_AUTHORED` — *the same lie,
adjudicated differently because the witness is weaker.* That is the entire
benchmark in one sentence.

So the design is: take a distribution of (claim, ground-truth) pairs, and for each
**witness rung** `r`, ask the kernel to adjudicate every task *as if the strongest
available witness for it sat at rung r*. Sweep `r` from the floor up. Read off:

- **J(r)** = poison positives purged = count of `REJECT_POISON` at rung `r` (the
  wrong-but-claimed writes the gate refuses to admit). This is the value number,
  identical in kind to docs/228's J.
- **admit-precision(r)** = of everything ACCEPTed at rung `r`, the fraction
  genuinely true (the docs/230 Payoff-1 number).
- **abstain-band(r)** = fraction of *claim-bearing* tasks that land in `ABSTAIN`
  at rung `r` — the tasks for which a witness at rung `r` is **too weak to rule**.
  At the floor rung this band is the docs/204 §3 wall, made into a fraction.

Holding the claim/ground-truth distribution fixed and sweeping only the rung
isolates the witness as the cause — the benchmark's analogue of the
fleet-of-one falsifier (value must vanish where the mechanism is absent): here,
**value must vanish at the `AGENT_AUTHORED` floor**, because the kernel refuses to
believe an agent-authored witness *by construction* (`believe_under_floor`). If
J(floor) were ever > 0 the benchmark would be unsound — it would mean the gate
acted on a forgeable byte. (The prototype asserts this; see the test plan.)

## The curve — and why it is the whole DOS thesis on one chart

```
 J (poison purged)
   |                                  ____________  THIRD_PARTY
   |                            _____/              (cloud trail, CI, ledger)
   |                      _____/  OS_RECORDED
   |                _____/        (exit code, DB-hash)
   |          _____/
   |    _____/
 0 |___/__________________________________________
   |   AGENT_AUTHORED        rung →
   |   (the floor — value is 0 BY CONSTRUCTION)
   |
   '----  the height here = the §3 wall = the GROWTH FRONTIER
          (every task abstaining at the floor is a unit of demand
           for a new witness driver)
```

The left end of this curve is **where DOS grows into**; the right end is **DOS's
measured value**. They are the same curve. That is why this is *the* throughline
benchmark and not just another arm:

1. **It shows the value** without overclaiming it. The rising arm is real,
   measured, and already grounded by the live results — docs/228 (tau2 J=15 off
   the DB-hash, an `OS_RECORDED` rung) and docs/233 (coordination J=6) are
   *single points* on this curve. The benchmark's contribution is to show they sit
   on a **monotone trend in witness strength**, not isolated anecdotes.

2. **It shows where DOS grows** without hand-waving. The abstain band is not a
   confession — it is a **work-list**. Each abstaining task carries the reason
   `"present claim but no accountable witness"`; grouped by *what witness it
   wants*, the band becomes a ranked roadmap: build the content-diff rung, the
   invariant rung, the provider-ledger driver — and re-run to watch the band
   shrink and J climb. The benchmark is a **roadmap generator**, which is exactly
   the "where can DOS grow into" half of the goal, operationalized.

3. **It is honest by the same discipline the kernel preaches.** The benchmark
   reports the rung that answered and abstains where none does — it applies the
   kernel's own rule to the measurement of the kernel. (Contrast a recall-style
   scoreboard that would score the floor abstains as "misses" and make DOS look
   broken; docs/159 already rejected recall as the wrong scoreboard.)

## What growth looks like, concretely (the roadmap the band generates)

The abstain band at the floor decomposes into named, buildable witnesses — this is
the docs/192 world-state ladder re-read as a backlog. Each row is a DOS **driver**
(an `EvidenceSource`, outside the kernel), and the benchmark measures the band it
would close:

| witness driver (an `EvidenceSource`) | rung | abstain class it converts | exists today? |
|---|---|---|---|
| git-ancestry presence (`verify`) | W2 / floor-plus | "a file changed" claims | **yes** (`dos.phase_shipped`) |
| env DB-hash / assertion engine | W3 `OS_RECORDED` | state-invariant claims (money/inventory/reservations) | **yes** (tau2, Agent-Diff drivers) |
| **content-diff rung** | W3 `OS_RECORDED` | "the value is *right*" claims (not just "changed") | **no — growth target** |
| **invariant / tamper-evident-gold rung** | W3 `THIRD_PARTY` | "the property holds" claims | **no — growth target** |
| provider ledger (Stripe, cloud trail) | W3 `THIRD_PARTY` | external-effect claims (different principal) | **driver-shaped, unbuilt** |
| (irreducible) | — | judgment/quality/taste claims | **never — punts to JUDGE/HUMAN** |

The last row is the principled floor: some fraction is *irreducibly* a judgment
call (docs/204 §3's 17% judge-only), and the benchmark's value is that it
**separates the buildable band from the irreducible one** — so the roadmap is
finite, not a treadmill. That separation is itself a result: it bounds how much of
the §3 wall is engineering vs. how much is the ORACLE→JUDGE→HUMAN ladder doing its
job.

## Provenance discipline (so the curve is trustworthy)

- **The kernel is not reimplemented.** The harness imports `dos.reward.admit` and
  `dos.evidence.EvidenceFacts` and calls them; it does not re-encode the
  belief rule. Pinned by a test that constructs a floor-rung refuting witness and
  asserts the harness's verdict equals the kernel's directly (`benchmark/` is the
  consumer side; the one-way arrow holds, `tests/test_bench_layering.py`).
- **The $0 prototype uses a *synthetic* claim/ground-truth distribution** with a
  declared, auditable mix (honest-true / honest-false / over-claim), the same way
  `fleet_horizon` drives the real kernel over a simulated workload. The witness
  rung is the swept variable; the distribution is the fixed substrate. This is a
  **rate**, not a payoff (docs/179) — and the doc says so. The payoff arm is live
  (P2 below), reusing the tau2 / Agent-Diff witnesses already standing.
- **The floor-abstain falsifier is asserted, not assumed.** J(AGENT_AUTHORED) == 0
  is a test, because if the gate ever purged on a forgeable byte the whole curve
  would be measuring a bug, not the kernel.

## Phased plan

**P1 — the $0 prototype (DONE, this commit).** `benchmark/witness_ladder/`:
`harness.py` (sweep `admit` over the rung axis on a synthetic distribution; folds
J / precision / abstain-band per rung; the `checks()` block computes the
monotonicity + floor-falsifier falsifiers and the `roadmap()` block the
buildable-vs-irreducible decomposition), `workload.py` (the declared
claim/ground-truth mix, as counts not coin-flips), `__init__.py`, and
`test_witness_ladder.py` (14 tests). Registered in `benchmark/registry.py` so
`python -m benchmark._run run witness_ladder` runs the cheapest free cell. Emits
the curve as JSON + an always-on ASCII rendering (matplotlib soft-dep, the
`fleet_payoff_surface` idiom). Output: the monotone J(r) curve + the abstain band
+ the roadmap table (abstain-by-wanted-witness).

**P2 — the live witness-rung sweep ($, reuse standing infra).** Replace the
synthetic distribution with real trajectories whose ground truth is read from an
actual non-forgeable witness, and *down-cast* the witness rung to sweep it:
- take the tau2 write-admit corpus (docs/228) — its DB-hash is a real
  `OS_RECORDED` witness — and the Agent-Diff corpus (docs/237, `THIRD_PARTY`-ish
  assertion engine);
- for each task, adjudicate it three times: once with the real witness
  (`OS_RECORDED`/`THIRD_PARTY`), once with the witness *masked to `AGENT_AUTHORED`*
  (simulating "only the agent's own narration is available"), once with *no
  read-back* (`NO_SIGNAL`). The J that survives at the strong rung and **collapses
  to 0 at the masked floor** is the live, causal version of the prototype curve.
- This needs no new live model spend beyond what docs/228/237 already cached — it
  is a **re-fold** of existing rows under different witness rungs (the docs/232
  re-fold-don't-trust-the-cached-bit law applies: re-derive `admit` per rung).

**P3 — the growth drivers (the band-closing experiments).** Build the two unbuilt
witnesses the roadmap names and measure the band they convert:
- **content-diff rung** — an `EvidenceSource` that reads the actual blob diff (not
  just "a commit touched the path") and attests/refutes against an expected value
  where a tamper-evident gold exists. Converts "changed" → "right" for the W3
  state slice. This directly lowers the §3 wall (docs/204 §3's stated fix).
- **invariant rung** — an `EvidenceSource` over a tamper-evident property check
  (a DB constraint, a typed postcondition). Re-run the P2 sweep with these drivers
  registered and report `Δ(abstain-band)` and `ΔJ` — the benchmark's headline
  growth number: *how much of the wall did building this witness remove?*

**P4 — fold into the headline figure (optional).** The witness-ladder curve is the
*per-task* complement of the fleet figure's *per-fleet* curve (docs/256). A
prevented poison at the strong rung is one root whose F^D cascade docs/256 already
prices. Joining them gives a 2-D surface: payoff vs. (witness strength × fleet
depth) — the full "where DOS pays" map. No new spend; a join, like F4.

## The honest frame (so this is not oversold)

This benchmark does **not** claim DOS witnesses correctness everywhere — it claims
the opposite, precisely: the value is real and monotone *up to the rung where a
non-forgeable witness exists*, and **zero below it by construction**. The abstain
band is the §3 wall, and the prototype's job is to make that wall a measurable,
shrinkable number rather than a caveat. "Where DOS grows" is not a promise that the
band goes to zero — the irreducible judge-only slice stays at HUMAN — it is a
*finite, ranked* list of witnesses whose construction is measured to move J. That
separation (buildable band vs. irreducible floor) is the result. The line, as
always: report the rung that answered; abstain where none does — including when
measuring ourselves.
