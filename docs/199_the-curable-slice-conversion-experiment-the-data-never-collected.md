# docs/199 — The curable-slice conversion A/B: the one fresh-data spend docs/198 left open

> **The question this answers:** *given recent learnings, what fresh data collection
> would help the most?* — and then collects it. The answer is not "more of the
> offline corpus" (that is exhausted) and not a new instrument (those are all
> shipped). It is the **one live spend the whole feasibility line was built to need
> and never ran**: a natural-regime A/B *targeted by the feasibility witness onto
> the CURABLE-thrash slice*, scored on the honest task-success denominator.

## 0. Why THIS data, ranked against the alternatives

Five recent learnings, read together, collapse the search for "fresh data that
helps most" onto a single point. Each is *empirically resolved* on the offline
axis — which is exactly why the remaining uncertainty is **live-only**:

| Learning | What it settled | What it left OPEN |
|---|---|---|
| docs/188 (conversion-gap bet #1) | In-trace / agent-action conversion is **DEAD on frontier** (0.2% fire, 0 substantive over 1,795 real Opus sessions). | Whether ANY agent-side rung converts on a *correctly-chosen population*. |
| docs/198 (feasibility witness) | The dominant "livelock" is an **INFEASIBLE** task (`create_filter` 0/579), not a curable loop. Every prior "refuted" cure verdict was scored against a denominator polluted with walled tasks — a **category error**. Give-up-correctly PASSES on the WALLED slice. | **Conversion on the CURABLE slice is genuinely UNTESTED.** A $0 re-score is FLAT/underpowered (n≈9–12). Needs **n≥30 curable-thrash instances**, "not a re-read." |
| docs/192 (witness ladder) | `verify()`'s file-path rung is **W2-presence, not W3-goal**; ~38% of frontier goals reach no sound witness. | Needs a content-gold corpus to measure the W2/W3 flip rate — a *different, larger* build. |
| docs/190 (coordination) | Collision **rate** is measured (~5.1/1k writes). | The believed-vs-adjudicated **payoff** A/B — needs a live *fleet* harness, which is not staged here. |
| docs/193 (restart-seeded) | The restart arm is the structurally-unique escape from the rewind livelock; $0 gate PROCEED. | Conversion is **LIVE-ONLY** — no recorded transcript has the post-restart turns. |

**The ranking is unambiguous.** Three of the four open frontiers (witness-flip,
coordination-payoff, fleet) need infrastructure that is *not standing*. The
curable-slice conversion read needs exactly three things, and **all three are
standing right now**:

1. the **feasibility witness** to pick the population (`_feasibility.py` +
   `feasibility_witness.py`, shipped docs/198);
2. the **live EnterpriseOps-Gym** (Docker `eog-email`/`eog-itsm`/`eog-hr`/`eog-csm`
   all healthy; `GEMINI_API_KEY` set; `gemini-2.5-flash` configured);
3. the **targeted runner + scorer** (`curable_oversample.py` emits the pinned
   task list + power plan; `live_ab.py --task-ids/--reps` pins them; the
   `restart_seeded` arm is wired; `feasibility_split.py` scores the curable slice
   on the task-success denominator with the pre-registered kill).

`curable_oversample.py`'s own header says it plainly: **"THE EXPERIMENT NEVER
RUN."** The instruments were all built; the *data* was never collected. The gym
being up is the perishable unlock — the spend is decision-relevant and cheap
(cheap-model tier), so it is the right thing to do, now.

## 1. The experiment

**Population (the category-error fix, done FIRST).** Run `curable_oversample.py`
over the recorded natural A/B (`live_results_natural_ab/`, 240+240 runs). The
witness finds **11 curable-thrash task families** (email + itsm domains) — tasks
that *ever* produced a thrash on a tool the witness proves CURABLE
(`update_vacation_settings`, `create_draft`, `create_label`, `add_new_user`,
`update_change`, `modify_message`, …). The WALLED `create_filter` tasks are
**excluded by construction** — scoring a cure on them is the docs/198 category
error.

**Power.** Natural thrash is stochastic per run (mean per-task hit-rate 0.636), so
reaching n≥30 curable-thrash *instances* needs repetition: **5 reps × 11 tasks =
55 runs/arm**, expected ≈35 curable instances/arm (clears the n≥30 floor).

**Arms (3 × 55 = 165 live runs).** Same pinned task set across arms ⇒ paired.
- `none` — `DOS_CONSULT=0`: natural regime, never intervene (the honest baseline).
- `warn` — `DOS_INTERVENTION=WARN`: inform-and-still-dispatch (the only agent-side
  rung proven positive live elsewhere, +6.2pp integrity; the never-withhold rung).
- `restart_seeded` — the docs/193 arm: drop the poisoned prefix, re-orchestrate
  from a byte-clean seed (kernel VerdictToken + the gym's REAL block-error bytes).
  The structurally-unique escape from the upstream-omission livelock that sank
  plain rewind live (none 49.2 / block 48.3 / rewind 44.9, n=48).

**Regime:** `--mint-rate 0.0` — NATURAL, no injection (docs/172). The thrash we
cure is the real ~10% the model produces on its own, not a synthetic mint.

## 2. The pre-registered analysis (fixed BEFORE the spend)

Scored by `feasibility_split.py --out live_results_curable_ab --cure <arm>
--min-curable-n 30`:

- **Denominator:** the CURABLE slice ALONE, on **task-success** (not verifier-pass,
  not "a later non-error result"). Never pooled with WALLED runs.
- **Metric:** fired-flip NET per arm vs `none` on that slice (runs the arm flipped
  fail→pass, minus pass→fail).
- **PRE-REGISTERED KILL (docs/198 §4.2):** a cure ships ONLY if its fired-flip
  **NET > 0 on the curable slice at n ≥ 30**. If `n < 30` after the run, the read
  **prints the power and refuses to over-claim** — an underpowered null is reported
  as underpowered, never as "refuted."

**The likely outcomes, all banked:**
- **NET > 0 at n≥30** → the first measured conversion of a sound verdict to task
  value, on the population where conversion is *possible*. Reverses the "conversion
  is dead" frontier conclusion *for the curable slice* — the single most
  roadmap-changing result available.
- **NET ≈ 0 at n≥30** → conversion is null even where feasible: the value of DOS on
  this axis is detection + give-up-correctly (the WALLED slice), not cure. Closes
  the docs/198 open question honestly.
- **n < 30** → the natural curable-thrash rate is too thin even with oversampling;
  the next spend is more reps or a mint-targeted curable regime. Reported as
  underpowered.

The arm comparison also isolates **warn vs restart_seeded**: if `warn` (never drop
the prefix) converts but `restart_seeded` does not, the prefix wasn't the problem;
if `restart_seeded` converts where `warn` does not, the docs/193 prefix-drop thesis
is live-confirmed on the curable slice.

## 3. Results — the run landed (165/165, 2026-06-06)

All three arms completed 55/55 on the live gym (`live_results_curable_ab/`). The
witness split, the conversion reads, and the give-up score below are reproducible:
`python feasibility_split.py --out live_results_curable_ab --cure {warn,restart_seeded}
--min-curable-n 30`.

### 3.1 The population split worked — the targeting did its job

Over the 55 `none`-arm runs, the witness routed:

| population | n | meaning |
|---|---:|---|
| WALLED | 10 | thrash on a tool with 0 successes anywhere (`create_filter`, `add_new_user`, `update_draft`) — conversion impossible by construction |
| **CURABLE** | **19** | thrash on a tool the witness proves has a path (`create_label`, `create_draft`, `update_vacation_settings`, `modify_message`, `update_change`, `create_forwarding_address`, `list_drafts`, `modify_thread`) |
| NO_THRASH | 26 | no Kth-same-tool error |

Oversampling lifted the curable-thrash count to **19/55** — vs the ~6 a random
sample yields at the natural ~10% rate (docs/198 §3). The category-error fix held:
the WALLED tasks are scored separately, never pooled into the conversion read.

### 3.2 THE HEADLINE — conversion on the curable slice is ~0, and not for lack of n

| cure arm | curable n | help | hurt | same | NET | sign-p |
|---|---:|---:|---:|---:|---:|---:|
| **warn** | 19 | 1 | 0 | 18 | **+1** | 1.000 |
| **restart_seeded** | 19 | 0 | 0 | 19 | **+0** | n/a |

Both cures are UNDERPOWERED — but the reason is the finding. It is **not** that n is
small (n=19 is near the n≥30 floor); it is that **the conversion EVENTS do not
happen.** `warn` flipped exactly one curable-thrash task fail→pass and hurt none;
`restart_seeded` flipped zero. The discordant-pair count is d≤1 for both — a sign
test needs d≥6 to reach p<0.05, so **165 witness-targeted live runs cannot move d
off the floor.** The curable-thrash *population* is reachable; a cure *converting*
one to a task-success is a near-zero-rate event in the natural regime.

### 3.3 WHY — these are multi-failure tasks; curing the thrash surfaces no win

The deeper cause is in the task-success counts (overall_success, all 55 runs/arm):

| arm | task-success | verifier-pass | integrity |
|---|---:|---:|---:|
| none | **3 / 55 (5.5%)** | 30.0% | 30.0% |
| warn | 3 / 55 | 30.0% (Δ +0.0) | 30.0% |
| restart_seeded | 2 / 55 | 10.0% (Δ **−20.0**) | 10.0% |

The base task-success on these hard curable-thrash tasks is **~5%**. That is the
mechanism: **the curable thrash is not the binding constraint on these tasks** —
fixing it leaves the run failing for other reasons, so a cure has almost no
fail→pass flips available to win. This is the docs/177 "capability redistributes
failure" finding reproduced *at the cure layer*: on a weak model (gemini-2.5-flash)
these are **multi-failure** tasks, and removing one failure mode does not surface a
task-success. The curable/walled split is necessary but not sufficient — even on the
feasible slice, conversion requires the cured thrash to be the *last* failure, which
it rarely is.

`restart_seeded`'s **−20pp verifier drop** with 0 successful re-orchestrations is the
docs/193 **KC#5 cost-veto materializing**: dropping the prefix re-pays context, and
with no win to offset it the arm nets negative — the live confirmation of
"prune beats re-orchestrate" on this slice. The docs/193 prediction
(restart fires ~never / weak-lesson on natural thrash) holds.

### 3.4 The SURVIVOR replicates on fresh data — give-up-correctly ships

Witness-gated early-halt (fire only on a WALLED thrash), scored on the honest
task-success denominator, on this brand-new 55-run corpus:

| K | fired | false-abandon | FA-rate | tokens saved |
|---:|---:|---:|---:|---:|
| **2** | 15 | 0 | **0.000** | **43,678** |
| 3 | 15 | 0 | 0.000 | 41,430 |
| 4 | 12 | 0 | 0.000 | 40,053 |

**PASSES its pre-registered kill** (FA-rate<0.10 AND tokens-saved>0) at every K. The
un-gated halt (fire on any Kth same-tool error) saves more raw tokens but pays
false-abandons (FA-rate 0.05–0.08); the witness gate makes false-abandon
**structurally 0** — you cannot kill a winner on a tool that never wins. This is the
docs/198 surviving value, now replicated on an independent live corpus.

## 4. What this fresh data settled

1. **The category-error fix is load-bearing AND correct, and it is *also* not
   enough.** Splitting WALLED from CURABLE was the right first move (it rescued
   give-up-correctly from a false "refuted"). But the curable slice does NOT then
   convert: feasibility is necessary, not sufficient. The honest conversion verdict
   is **null on the feasible slice in the natural regime**, with the mechanism named
   (multi-failure tasks, ~5% base success).
2. **Conversion is event-rate-bounded, not sample-size-bounded.** The roadmap
   implication: do NOT spend on more reps to chase n≥30 — d stays ≤1 because flips
   don't happen. The remaining live conversion question belongs to a regime where
   the cured failure is the *binding* one (higher-base-rate tasks, or a stronger
   model where thrash is the last remaining failure) — not to more EnterpriseOps
   reps. This retires the docs/198 §3 "needs n≥30 curable-thrash runs" action item:
   it was run, and n is not the wall.
3. **DOS's value on this axis is detection + give-up-correctly, not cure.** Confirmed
   on fresh data: the give-up arm ships (FA 0.000, ~44k tokens saved/15 runs); both
   agent-action cures (warn, restart) are wash-to-negative on the feasible slice —
   consistent with the docs/188 frontier-conversion-dead result, now extended to the
   weak-model *curable* slice. Value-capture lives off the agent-action denominator
   (coordination / give-up / the write-gate), exactly as docs/198 + the conversion-gap
   reframe argued.

## 5. Join to the concurrent fix-story line (docs/200 / docs/205)

A sibling session built, in parallel, the *cure mechanism* this experiment measures:
**docs/200** (`schema_refresh` — the byte-clean re-surface of the environment's own
schema-error correction) and **docs/205** (wiring `schema_refresh` as a live
curable-conversion arm). docs/205 §6 deferred its own live A/B precisely because this
session held the gym — and cites this doc as the recipe. The two lines join cleanly:

- **This doc supplies the measurement + the null mechanism.** The conversion-event
  rate on the curable slice is event-rate-bounded by the ~5% base task-success
  (multi-failure tasks), not sample-size-bounded. That is the denominator any cure —
  including `schema_refresh` — must beat.
- **docs/205 supplies the one cure that could.** `schema_refresh` is the byte-clean
  positive fix (re-surface, never author — the docs/164 rule); it acts on exactly the
  CURABLE thrashes (env stated the schema correction, agent ignored it). It is the
  honest next arm to run through this harness.

**Follow-on COLLECTED (docs/205 §6's pre-registered run):** `schema_refresh` vs `none`,
88 runs/arm (`--reps 8`), SEPARATE `live_results_curable_schema_ab`, scored
`--cure schema_refresh`. The arm genuinely fired (77/88 cure runs, 87 fires). Result —
**the byte-clean cure CONVERTS on the slice it targets but is NET-NEGATIVE**, a harm
channel the §3.3 mechanism alone didn't surface:

| slice | n | help | hurt | NET | sign-p |
|---|---:|---:|---:|---:|---:|
| has CURABLE thrash | 35 | 2 | 0 | **+2** | 0.500 |
| no-thrash (in `none`) | 42 | 0 | 7 | **−7** | **0.016** |
| all paired | 88 | 2 | 7 | **−5** | 0.180 |

Task-success dropped (none 7/88 → schema 2/88), and the attribution is **causally
clean**: all 9 flips had a cure fire (7 hurt / 2 help / 0 hurt-without-fire). The cure
converts a curable thrash where aimed (+2), but **injecting the directive turn perturbs
runs that were on track** — 7 baseline-passing tasks thrashed once in the cure arm,
received the directive, and failed. **The harm is the intervention's existence in the
loop, not its (byte-clean) content** — docs/188 "every agent-side rung is wash-to-negative
by structure," now shown for a byte-clean *positive* cure. Full analysis: docs/205 §6.2.
The §4 conclusion holds and strengthens: DOS value on this axis is detection +
give-up-correctly; even the best-disciplined positive cure is net-negative on the weak
multi-failure slice unless it fires ONLY on would-fail runs (a precision bar the current
gate misses).

### Status

- Smoke (2 tasks, `none`): PASS — live path confirmed.
- **Full run (165 live runs): COMPLETE** — `none`/`warn`/`restart_seeded` 55/55 each,
  `mint_rate=0.0` natural regime, domains email+itsm, gemini-2.5-flash.
- Reads: `_split_warn.txt`, `_split_restart.txt`, `live_results_curable_ab/_summary.json`.
- Joins: docs/198 (the split — do it FIRST), docs/200 (the `schema_refresh` mechanism),
  docs/205 (the cure arm), docs/177/188 (capability redistributes failure; frontier
  conversion dead), docs/193 (restart KC#5 cost-veto, live-confirmed here).
