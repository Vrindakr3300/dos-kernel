# docs/198 — The feasibility witness, and "give-up-correctly" as the real value

> **The livelock line went off the rails by asking the wrong question: "can DOS make
> the agent SUCCEED on this loop?" — measured against a denominator polluted with
> INFEASIBLE tasks. Once you split the population with a byte-clean *feasibility
> witness*, the picture resolves: on WALLED tasks the value is GIVE-UP-CORRECTLY
> (early-halt, measured-positive), on CURABLE tasks conversion is genuinely UNTESTED
> (every prior A/B drowned the signal by mixing the two). The thing that gets DOS back
> on track is the split, not another cure.**

Status: **MEASURED CORRECTION + buildable direction.** Supersedes the "detection-only,
conversion refuted" conclusion of [[docs/194]] (which §0.0 now corrects in place).
Instruments: `benchmark/enterpriseops/feasibility_witness.py` (both reads, $0).
Parent: [[docs/194]], [[docs/172]]/[[docs/175]] (the rewind line), [[docs/191]] (the
proactive non-agent-denominator lens — give-up-correctly is one), [[docs/177]] (frontier
silent-failure → verify() rung).

---

## §0 — The category error (what was off)

Three workflows over two sessions concluded the dominant natural agent-loop is
"schema-blindness, uncurable in-loop, detection-only." The operator's "this still seems
off" was right. **Every cure was scored on the agent's pass-rate against a denominator
that contained INFEASIBLE tasks** — and you cannot, even in principle, make an agent
succeed at an infeasible task. The "refuted" verdicts (rewind −3, block −6, abandon
"refuted") were measuring conversion where conversion is impossible.

The proof is one number: the dominant "thrash" tool **`create_filter` succeeds 0 times
out of 579 calls across all 7 arms** (0/278 in the natural A/B alone) — never, by any
model or intervention. Its schema requires all ~9 `criteria` fields present and
non-empty; the user task ("filter on sender only") cannot be expressed under it. The
agents *correctly diagnose the fix* (`"from should be 'from' not 'from1'; size expects an
integer"`) and **still fail**, then conclude the task is infeasible. It is a WALL, not a
loop the agent is fumbling.

> **→ docs/236 reuses this exact wall, one axis over.** When docs/236 measured the *recovery*
> distribution ("does the model recover next turn?"), the naive tail said "never recovers 72%
> of the time" — but **half those events were `create_filter`**, whose 0% recovery is *this
> wall*, not un-recovery. Folding them in would have re-committed the polluted-denominator
> error this doc is about. The same `feasibility_witness` split (walled = many errors, 0
> successes anywhere) recovers the honest number: on *feasible* errors "it'll recover" is
> still false ~44%. So the split applies to **recovery measurement**, not just **cure
> measurement** — a fact-shaped reuse, not a metaphor.

---

## §1 — The feasibility witness (the missing first question)

The distinction that should have come before any cure, and is byte-clean:

> **A thrashing tool is WALLED iff it has 0 successful (non-error) results ANYWHERE in
> the corpus; CURABLE iff the same tool succeeds on some run.** The witness is
> ENV-AUTHORED — a non-error tool result is the gym's own reply — so the agent cannot
> forge that some *other* run got a clean result. (Pure presence-of-evidence, the
> `precursor_gate`/`arg_provenance` provenance shape.)

Measured (`feasibility_witness.py`, natural A/B, all arms):

| tool | ok | err | verdict |
|---|---|---|---|
| `create_filter` | **0** | 278 | **WALLED — infeasible** |
| `update_vacation_settings` | 20 | 84 | CURABLE |
| `update_hr_case` | 35 | 17 | CURABLE |
| `create_label` | 88 | 6 | CURABLE |
| `get_user_using_name` | 115 | 8 | CURABLE |
| `create_new_hr_case` | 36 | 7 | CURABLE |
| … | | | (all others CURABLE) |

**`create_filter` is the *only* WALLED tool — and it dominated the thrash counts.** So
the "dominant natural livelock" the prior work obsessed over was overwhelmingly the one
tool no cure could ever convert. Mixing it into the conversion denominator is what
produced "every cure is wash-to-negative."

---

## §2 — Give-up-correctly: the value on WALLED tasks (the survivor)

On a WALLED task the agent will fail no matter what, so the only honest value is to
**stop burning tokens early and report a clean reason** — the `dos halt` / `liveness`
self-stop / decisions-queue machinery already shipped. This is the **abandon** candidate
docs/194 §3.1 *killed* — and that kill was itself the category error.

**The corrected re-score** (`feasibility_witness.py` READ 2). The prior abandon replay
counted a "non-error tool result later" as self-recovery (false-abandon 0.33–0.42). But
a transient non-error on a run that **still fails the task** is not recovery: of the 10
"recoveries" it counted, **0 actually succeeded at the task.** Re-scored on the honest
**task-success denominator** (false-abandon = "abandon would halt a run that actually
SUCCEEDS"):

| K | fired | false-abandon | FA-rate | tokens saved |
|---|---|---|---|---|
| 2 | 23 | **0** | **0.000** | 33 132 |
| 3 | 15 | **0** | **0.000** | 22 557 |
| 4 | 13 | **0** | **0.000** | 21 448 |

**It PASSES its own pre-registered kill (FA < 0.10 AND saved > 0) at every K** — never
halts a winning run (there are none to halt on the walled population) and saves a third
of the tokens. *Early-halt cost-aversion is the surviving value, not the refuted one.*
The honest scope (unchanged from docs/194 §4): this is a **cheap-model fleet-tier $-saver**
— it decays on the frontier (docs/177: frontier fails go silent, off the error channel)
and is 0 at N=1 (throughput needs fanout). But on the cheap-model tier where most fleet
spend lives, it is real and measured.

The give-up verdict can be sharpened with the witness itself: **fire EARLIER and harder
when the thrashing tool is WALLED** (0 successes in the run's own history / the workspace
corpus) — an infeasible-tool signal that is strictly env-authored.

---

## §3 — Conversion on the curable class: still OPEN, NOT rescued (the honest read)

The prior A/Bs that "refuted" conversion fired across the whole population, so the WALLED
`create_filter` failures (unconvertible by construction) confounded the magnitude. But a
first $0 re-score on the curable-only slice (none vs `rewind_natural`, natural A/B, the
two arms with runs here) does **NOT** rescue conversion — and saying so is the discipline:

| slice | tasks | help | hurt | net |
|---|---|---|---|---|
| all paired (incl. non-thrash) | 159 | 27 | 21 | **+6** |
| WALLED-only thrash (`create_filter`) | 12 | 3 | 3 | **+0** |
| has a CURABLE thrash | 9 | 2 | 3 | **−1** |

The thrash cells are **n≈9–12 — far too small to be significant** (the ±band swamps
±1–3). So the honest claim is *not* "conversion works once you exclude walled tasks." It
is: (a) the walled tasks contribute **net +0**, confirming you cannot convert the
unwinnable (as expected); (b) the curable thrash slice is **flat-to-slightly-negative and
underpowered** — conversion there is **genuinely untested** by `rewind`/subtract, neither
shown nor refuted. The one positive datum remains the held-value class (`tool_stream`
REPEATING WARN +6.2pp), a *different* curable sub-class (the agent stopped using a value it
holds), not the malformed-arg thrash.

### §3.1 — WHY the curable thrash also doesn't convert (the mechanism, measured)

Pushing past the n problem, the *dynamics* are decisive and explain the flat result. Of the
**15** `none` runs with a CURABLE-tool thrash: the thrashing tool **recovers** (returns a
non-error later) in **11/15** — yet the **task succeeds in 0/15**. So even on a tool that
demonstrably *can* succeed, a thrash co-occurs with task failure regardless of whether the
tool itself unsticks. The thrash is a **symptom of a hard task, not a local recoverable
hiccup** — unsticking the tool call does not unstick the task.

And the failures are genuinely distributed, not just walled-subgoal bleed: on curable-thrash
runs, failed verifiers are **19 "something else" vs 4 about a filter** — the binding
difficulty is spread across diverse unmet sub-goals, not one infeasible rider. Even at
**per-VERIFIER** granularity (25 verifiers compared, finer than 9 runs), `rewind` on curable
thrashes is **net −1** (2 help / 3 hurt). So `rewind`/subtract is refuted on the curable
slice too — now at three granularities (per-run, per-verifier, per-goal) — and for a
*principled* reason: subtraction edits the transcript, but the curable thrash's cause is
**task difficulty**, which the transcript edit doesn't touch. This is the curable-class
analogue of the walled lesson: the binding constraint is upstream of the rung's lever.

So the real next experiment stands, but its result is unknown: re-run WARN / resurface /
restart **filtered to CURABLE-tool thrashes, at n ≥ 30**, scoring fired-flip net on that
slice alone. With only `none` and `rewind_natural` recorded here (n=9 curable thrashes),
the question cannot be settled on the current corpus — it needs more curable-thrash runs,
not a re-read.

---

## §4 — The buildable next step (back on track)

Two moves, both $0-first, both benchmark-side (disjoint lane), no kernel edit required:

1. **SHIP early-halt as a give-up-correctly arm, gated by the feasibility witness.**
   The verdict already passes at K=2 ($0, §2). The new code is the *witness gate* (fire
   the halt when the thrashing tool is WALLED in the run/corpus) + the K threshold — both
   policy. Kernel primitive already exists (`dos halt`/`supervise` reap). Honest scope:
   cheap-model tier.

2. **The ONE untested lever: WARN (non-withholding) on the curable slice — but with a
   high prior against it.** `rewind`/subtract is now refuted on the curable slice too (§3.1,
   three granularities), for the principled reason that the thrash is a *task-difficulty*
   symptom the transcript edit can't touch. The only conversion lever NOT yet refuted is
   the non-withholding WARN re-surface (the +6.2pp held-value winner) — but those arms
   aren't in this corpus, and §3.1 sets a high prior against it converting the *malformed-arg*
   thrash (re-surfacing a value doesn't make a hard task easy). So the honest #2 is: generate
   curable-tool-thrash runs for none vs **WARN** (not rewind — refuted), n ≥ 30 on the curable
   slice, **pre-registered to likely-NULL** given §3.1; a positive there would be a genuine
   surprise worth the spend, a null confirms in-loop conversion is dead for the malformed-arg
   class and the value is entirely give-up-correctly (#1). **Do #1 first (proven $0). Treat #2
   as a falsification run, not a hopeful one.**

---

## §5 — Does this contaminate prior docs?

Yes, and the correction is honest, not silent:
- **docs/194** — §0.0 correction note added in place (the "conversion refuted / detection-
  only" headline is downgraded to "true on the WALLED slice; untested on the curable
  slice; abandon mis-scored").
- **docs/172 / 175** (rewind −3, block −6) — their refutations were measured on the mixed
  population. They are not *wrong* (rewind does livelock on upstream-omission), but their
  magnitude is confounded by the walled tasks. A one-line pointer to this doc suffices;
  the rewind-livelock *mechanism* finding stands.
- The **abandon refutation** (docs/194 §3.1) — directly corrected here: it PASSES on the
  honest denominator.

---

## §6 — The honest ceiling

- **Give-up-correctly:** real, measured-positive, but cheap-model-tier only (decays on
  the frontier where failures go silent — docs/177). A $-saver, not a capability lift.
- **Conversion on the curable slice:** `rewind`/subtract is **refuted there too** (§3.1,
  3 granularities) because the curable thrash is a *task-difficulty* symptom (tool recovers
  11/15, task succeeds 0/15) — not a transcript-editable hiccup. The ONLY untested lever is
  non-withholding WARN, and §3.1 sets a high prior against it. The honest expectation is
  that in-loop conversion of the malformed-arg thrash is **dead**; a WARN run is a
  falsification test, not a hope. The held-value WARN +6.2pp remains the lone positive, on a
  *different* sub-class (looping on a value already held, not a hard task).
- **The durable contribution** is the **feasibility witness** itself: a byte-clean,
  env-authored split of "loop I can help" from "wall I should quit" that every future
  loop-intervention experiment must apply BEFORE scoring conversion — or it will keep
  re-measuring the same category error.
