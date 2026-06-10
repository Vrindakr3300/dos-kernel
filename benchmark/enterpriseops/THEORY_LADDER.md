# The intervention test ladder — cheap theories first, scale to live last

> **Paper writeup:** `docs/151_intervention-ladder-live-study.md` is the self-contained
> methodology + results paper for this study (abstract → design → results → conclusion). This
> file is the operational companion (how to run each tier + the step-by-step "what the live run
> did" + the flip-robustness check).

docs/144 §5 Phase 3 asks: *does the turn-preserving BLOCK flip the live −9 pp positive?* A
live A/B answers it at one point, at real API cost. This ladder answers the **theories
underneath it cheaply first**, so a live run *confirms a prediction* instead of being the
first data point. Each tier is strictly cheaper than the next; climb only as far as the
question needs.

| Tier | What it is | Cost | Command | Answers |
|---|---|---|---|---|
| **0** | **Theory sweep** — the simulator + the real `intervention_eval`, swept over the recovery-dynamics parameters | **$0, ~seconds** | `python -m benchmark.enterpriseops.intervention_theories` | *Under what assumptions does BLOCK beat the baseline?* Maps the decision boundary. |
| **0b** | **Fixed-point A/B** — the simulator at one tuned point | $0, ~seconds | `python -m benchmark.enterpriseops.intervention_ab` | BLOCK vs DEFER vs WARN at `intervention_ab`'s parameters. |
| **1** | **Deterministic replay** — re-score recorded real trajectories, no new model calls | $0 (needs prior run artifacts) | `python -m benchmark.enterpriseops.replay_recall --results <dir>` | Detector precision/recall on REAL data, variance-free. |
| **2** | **Live smoke** — 2–3 real tasks, all arms, 1 seed | ~1–2 min, **cents** | `live_ab.py --tasks 3` (see below) | *Does the live pipeline run end-to-end?* First real signal. |
| **3** | **Live pilot** — ~10–15 tasks, all arms | ~10–20 min, ~$1–2 | `live_ab.py --tasks 12` | A directional live delta. |
| **4** | **Live full** — ~55 tasks like docs/143 | ~1 hr, ~$5–10 | `live_ab.py --tasks 55` | A publishable per-arm result with CIs. |

**Rule:** read Tier 0 *before* spending on Tier 2+. It tells you which recovery region makes
BLOCK win, so the live numbers either confirm or surprise — both informative, neither blind.

---

## What Tier 0 already told us (2026-06-04) — the honest, load-bearing finding

Run: `python -m benchmark.enterpriseops.intervention_theories --tasks 600 --seeds 3`.

**The real baseline to beat is WARN, not DEFER — and under the simulator's irreversibility
model, BLOCK does NOT beat WARN except when most catches actually matter to the verifier.**

| Sweep | Finding |
|---|---|
| **recovery gap** (q_block − q_defer) | Even at block-recovery **1.00** vs defer **0.75** (a huge +0.25 gap), BLOCK stays **−0.055** while WARN is **0.000**. BLOCK beats DEFER everywhere, but **never overtakes WARN** at `mattered_rate=0.65`. The recovery gap alone does not buy the prize. |
| **mattered_rate** | The crossover is here: BLOCK beats WARN only once `mattered_rate ≳ 0.80` (BLOCK +0.023 at 0.80, +0.162 at 0.95). At the docs/143-observed *low* mattered-rate (most catches the verifier never checked), even turn-preserving BLOCK is net-negative — preventing a write that didn't matter still isn't free. |
| **mint rate** | BLOCK's margin over DEFER is stable across agent cheapness; the absolute deltas scale with the number of fired cases, but the WARN-wins picture holds. |

### Why this matters (and what it corrects)

`intervention_ab`'s headline "**BLOCK beats DEFER by +0.40**" is TRUE but compares BLOCK to
the *wrong* baseline. DEFER is the −9 pp loser DOS already abandoned; the docs/143 **live
winner was WARN** (−1.8 pp ≈ 0). Against *that* baseline, the simulator says BLOCK is a win
**only in the high-mattered-rate regime**. The turn-preserving synthetic-result is cheaper
than a skip, but on an irreversible DB a WARN that lets a non-verifier-checked mint land
costs nothing either — so BLOCK's prevention only pays when the prevented write would have
failed a check.

### The precise question the live run must answer

The simulator's `mattered_rate` and the BLOCK-vs-WARN recovery *asymmetry* are **assumptions**.
The live gym measures them for real:

1. **What is the real `mattered_rate`?** (Of caught mints, how many feed a hidden SQL
   verifier?) docs/143 suggests it is *low* — which is the WARN-wins regime.
2. **Does turn-preserving BLOCK recover better than the simulator's model assumes?** The
   simulator caps BLOCK-recovery as a parameter; the live model may do markedly better (a
   real corrective observation on the same turn may beat a parameterized `q_recover_block`),
   which is the one way BLOCK could win even at a low mattered-rate. **This is the actual
   prize hypothesis** — and it is exactly what the simulator *cannot* settle, so it is what a
   live run is *for*.

So the live run is not "confirm BLOCK wins" — Tier 0 shows that is not the simulator's
prediction at the likely mattered-rate. It is: **measure the real mattered-rate and the real
BLOCK-vs-WARN recovery asymmetry, and see whether the live recovery dynamics exceed the
simulator's pessimism.** A null result (WARN remains the best default) is itself a publishable,
honest finding — it would say the docs/143 WARN-only fix is not just good but *optimal*, and
the BLOCK machinery is the safety valve for the high-stakes-effect regime, not the default.

---

## Tier 2–4 live runner (setup, once)

The gym is cloned at `benchmark/enterpriseops/enterpriseops-gym/`. One-time setup:

```bash
cd benchmark/enterpriseops/enterpriseops-gym
uv sync --extra google                       # gym deps + the Gemini provider
cp -r conf.example conf                       # configs
unzip -o gym_dbs.zip                          # seed databases
# conf/llm/gemini.json: {"llm_provider":"google","llm_model":"gemini-3-flash-preview",
#                        "llm_api_key":"<from dos/.env GEMINI_API_KEY>","temperature":0.0}
# docker pull + run the 4 FK-heavy domain MCP servers (itsm 8006, csm 8001, email 8004, hr 8008)
```

Then the tiered live A/B (same injected mints across arms; `--tasks` is the only scale knob):

```bash
DOS_MINT_INJECT_RATE=0.30 DOS_MINT_SEED=42 \
  python live_ab.py --tasks 3   --arms none defer warn block   # Tier 2 smoke
  python live_ab.py --tasks 12  --arms none defer warn block   # Tier 3 pilot
  python live_ab.py --tasks 55  --arms none defer warn block   # Tier 4 full
```

The arm knob is the kernel env seam already in `dos_react.py`:
`none` = `DOS_CONSULT=0`; `defer` = `DOS_INTERVENTION=DEFER`; `warn` = `DOS_INTERVENTION=WARN`
(the docs/143 baseline); `block` = `DOS_INTERVENTION=BLOCK` (the prize). Scoring is the gym's
own hidden SQL verifiers, untouched.

---

## What the live run actually DID, step by step (the experiment in plain terms)

For each of the 80 sampled tasks, in each of the 4 arms, the runner did this:

1. **Seed a fresh DB.** `live_ab.py` posts the task's seed SQL to the domain's Docker MCP
   server → a clean, isolated database for this run (so arms never contaminate each other).
2. **Run the agent loop.** gemini-2.5-flash drives the gym's ReAct loop over the real MCP
   tools — read records, then mutate them — exactly as the gym intends.
3. **Inject the SAME mints (the controlled perturbation).** Before each *mutating* tool call,
   with prob `--mint-rate`, `dos_react._maybe_inject_mint` takes an id the agent had correctly
   resolved and **corrupts it into a minted-looking one** (right shape, wrong digits). A stable
   per-task seed means every arm gets the *identical* corruptions — so the only thing that
   differs between arms is the intervention.
4. **Consult the kernel.** `dos.arg_provenance.classify_call` folds over the env-authored
   bytes the agent has seen and returns a verdict: was each id RESOLVED (its bytes appear in a
   prior tool result / the task) or MINTED (invented)?
5. **Act per the arm** (`dos.intervention.choose_intervention` → the rung):
   - `none` — inject, *don't even consult*; the minted call dispatches and corrupts the DB
     (the weak-model baseline).
   - `WARN` — append a "[DOS] that id looks invented" note to the agent's context, **then
     dispatch the call anyway**. Informs, never withholds.
   - `DEFER` — **skip** the call and re-prompt; the agent spends its turn re-resolving.
   - `BLOCK` — **withhold** the real call and feed back a *synthetic* "id unresolved; use a
     read tool" result in its place; the agent gets a correction on the same turn, the
     mutation never lands.
6. **Score with the gym's hidden SQL verifiers, untouched.** After the agent finishes, the gym
   runs its expert-authored SQL against the *final DB state* (e.g. `SELECT COUNT(*) FROM
   drafts WHERE id='draft_001'` → expect 0). We change none of this — it is the non-forgeable
   oracle. Each arm's verifier-pass% is the fraction of those checks that passed.

So the live run measures **the real effect on a shared DB of each way of acting on the same
sound verdict** — the docs/144 §13 question, on ground truth instead of a simulator.

## Does the result hold WITHOUT the "flip" analysis? (the robustness check)

There are two independent ways to read the run, and they agree — so the verdict does **not**
depend on the per-task flip methodology:

- **Aggregate (NO flip, NO pairing)** — just sum each arm's passed/total verifiers across all
  its runs. This is the rawest signal; it never compares a task against the baseline.
  > `none 39.9% · DEFER 41.9% · WARN 46.0% · BLOCK 40.2%` verifier-pass.
  > **WARN wins (+6.1pp), BLOCK ~neutral (+0.3pp), DEFER +2.0pp.**
- **Per-task verifier-FLIP (`mattered_join.py`)** — for each caught-mint task, compare each
  verifier against the same task in the `none` arm: FALSE→TRUE = the catch *helped*, TRUE→FALSE
  = the disruption *hurt*. This does NOT change the verdict; it **explains** it:
  > WARN 14 help / 2 hurt (net +12); **BLOCK 7 help / 13 hurt (net −6).**

**The "flip" is the microscope, not the verdict.** The headline — WARN optimal, BLOCK neutral,
the §13.4 prize falsified — stands on the plain aggregate alone (recompute it any time with the
`analyze_live.py` SCORES block, or the no-pairing one-liner in this repo's history). The flip
decomposition only adds the *mechanism*: BLOCK is neutral-not-helpful because withholding the
call (even with a synthetic substitute) breaks ~6× more downstream steps than WARN's
inform-and-dispatch. Remove the flip analysis entirely and the conclusion is unchanged; you
just lose the *why*.

## Read order / cross-index

- **`intervention_theories.py`** — Tier 0, the $0 sweep (the prediction).
- **`intervention_ab.py`** — the simulator A/B (BLOCK vs DEFER vs WARN at one fixed point).
- **`live_ab.py`** — the live runner (Tiers 2–4).
- **`analyze_live.py`** — the unified live report (mechanism stats + aggregate scores).
- **`mattered_join.py`** — the per-task flip decomposition (the *why*, the live mattered-rate).
- **`RESULTS.md` → "⚑ THE LIVE INTERVENTION A/B"** — the written-up findings.
- **`docs/144_the-intervention-ladder-and-its-eval.md`** — the design + the status verdict.
- **`replay_recall.py`** — Tier 1, the variance-free detector precision/recall.
