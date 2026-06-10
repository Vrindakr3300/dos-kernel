# docs/205 — Growing the fix story: the curable-conversion arm

> **The challenge (operator, 2026-06-06):** *"DOS's fix story is much weaker than
> its detect story. The one fix that survives every regime is the negative one —
> give-up-correctly (early-halt, 0% false-alarm). Telling a doomed loop to stop is
> robust; steering it to success is not, because the cure usually has nothing
> curable to act on."*
>
> **The answer this doc builds + verifies:** the fix story grows in exactly one
> place that survives adversarial verification — wire the byte-clean `schema_refresh`
> re-surface (docs/200) as a live arm and measure conversion on the **witness-gated
> curable slice**. That is the single unmeasured cell on a *sound* denominator. The
> positive fix is made robust by **riding the detection floor**: the same gate that
> early-halts a WALLED thrash instead re-surfaces the environment's own corrective on
> a CURABLE one.

Status: **Rank 1 + Rank 2 SHIPPED** (`29fd70c` + `d89a8ee`, 2026-06-06). The live
A/B that measures *whether it converts* is deferred (a concurrent session is actively
writing the gym corpus — see §6). Builds on [[docs/198]] (the feasibility split — do
it FIRST), [[docs/200]] (the byte-clean mechanism), [[docs/164]] (the never-author
rule), [[docs/199]] (the curable-slice experiment recipe).

---

## §1 — Why the fix story is structurally weaker than the detect story

This is not an accident of effort; it is a consequence of the one rule.

**DETECTION mints a verdict from bytes the agent did not author** — env error
envelopes, git ancestry, the WAL. It is grounded *by construction*: the thing it
reads is the thing it distrusts, authored by someone else.

**A CURE must change the run's trajectory**, and [[docs/164]]'s one rule forbids
DOS from *authoring* the change. So a positive fix can only EXIST when the
environment already stated the correction in its own bytes, and even then it must be
**re-surfaced, never generated**. That is a narrow window: the cure has something to
act on only where the env was diagnostic and the agent ignored it.

This is exactly why the only fix robust across regimes is the **negative** one
(give-up-correctly): *withholding spend authors nothing*, so it inherits detection's
groundedness. Early-halt is a detection verdict wearing an actuator. A positive fix
has no such free lunch.

**The corollary that sets the whole roadmap:** the fix story can grow ONLY where
three conditions hold simultaneously, and each must be *verified per move*:

1. **the corrective is env-authored** (one-rule clean — DOS re-surfaces, never mints);
2. **scoring is on the witness-gated CURABLE slice** with a pre-registered power gate
   (d≥6, n≥30) so the verdict is honest whether NET>0 or NET≈0 — never on a
   walled-polluted denominator (the [[docs/198]] category error);
3. **the mechanism is ADDITIVE re-surface** (append, return False — never subtract or
   substitute), so it is not the rewind livelock or the BLOCK substitution that
   already sank live ([[docs/172]] rewind 44.9 < none 49.2; [[docs/144]] BLOCK −4/task).

---

## §2 — The verified frontier (where the headroom actually is)

A 24-agent map → generate → adversarial-verify pass (`wf_bbabeafd-99a`) over the whole
fix-space killed 8 of 14 growth proposals and confirmed 6. The killed ones are named
in §5 so they are not re-proposed. The survivors collapse to one ranked layer.

The frontier, stated precisely:

- **Give-up-correctly (the negative fix) re-confirms** on an independent corpus
  (`live_results_curable_ab`, witness-gated): K=2 FA=**0.000**, **43.7k** tokens
  saved, 15 WALLED runs halted. Robust, as the operator said.
- **Curable-slice conversion (the positive fix) is GENUINELY UNTESTED**, not refuted.
  The partial live A/B has only n=19 curable-thrash, **d=1 discordant pair** — a sign
  test needs d≥6 for p<0.05. The cell is literally unmeasured.
- **The byte-clean curable mechanism existed but had never run live.** `schema_refresh.py`
  ([[docs/200]]) was a pure module with **zero references** outside its own module +
  test. The mechanism was designed, measured offline, and never wired.

**New finding (this doc): the schema-refresh ceiling REPLICATES across corpora.**
Of the curable thrashes, the fraction carrying an env-authored SCHEMA corrective the
agent ignored:

| corpus | curable-thrash runs | SCHEMA-convertible | rate |
|---|---|---|---|
| `live_results_natural_ab` (docs/200) | 17 | 13 | 76% |
| `live_results_curable_ab` (this doc, growing) | 63 | 47 | **75%** |

The 75–76% ceiling is **stable across two independent corpora at n=17 and n=63** — not
a small-n artifact. The remainder splits REFERENCE (NOT_FOUND → lookup, ~3%) / STATE
(already-exists → re-plan, ~17%) / OPAQUE (~5%), confirming the [[docs/200]] §2
kind-split discipline matters (folding REFERENCE/STATE into "schema" would re-commit
the category error one level down).

---

## §3 — Rank 1 (SHIPPED): the live curable-conversion arm

`d89a8ee`. The positive fix wired as a live arm — the counterpart to give-up-correctly.

**The wiring (no kernel change; all benchmark-side):**

- `benchmark/_arms.py` — add the arm `"schema_refresh": {"DOS_CONSULT": "0",
  "DOS_SCHEMA_REFRESH": "1"}` (CONSULT=0 so it rides the *post-dispatch ENV-failure
  stream* like `rewind_natural`, NOT a mint verdict) + `DOS_SCHEMA_REFRESH` in
  `ALL_DOS_KNOBS` (cleared between arms — the [[docs/152]] contamination fix).
- `benchmark/enterpriseops/dos_react.py` — read the knob in `__init__`; in
  `_post_dispatch_rewinds`, on the **same `natural_thrash_gate` trigger** as the
  rewind, **APPEND** the env's own corrective as a `[DOS]` forcing function
  (`schema_refresh.refresh_directive` over the **latest full error result** — not the
  gate's 200-char excerpt, the [[docs/200]] §5 conservative read). Placed BEFORE the
  rewind block; **additive** (returns False, never breaks/subtracts); one-shot/tool.

**Why it survived adversarial verification** (each checked against real code):

- **Byte-clean.** `refresh_directive` authors only the framing; every corrective byte
  is regex-parsed verbatim from the env's bytes by `extract_corrective`, and `raw` is
  redacted of the agent's reflected input (`_redact_reflected_input`). The one rule holds.
- **Not the rewind livelock, not BLOCK.** It is additive — the directive rides into
  the next turn alongside the *unchanged* history. It never subtracts (rewind's
  upstream-omission livelock) and never substitutes a synthetic result (BLOCK −4).
  [[docs/172]] found append > subtract live; this is the append form.
- **Cannot pollute the verdict.** `feasibility_split.conversion_on_curable` scores the
  CURABLE slice ALONE (WALLED excluded by `classify_run`), so even a sloppy gate's
  worst case is *wasted runs*, never a polluted result.

**Live-wiring proof:** `test_schema_refresh_live_wiring.py` drives the REAL
orchestrator (mock LLM thrashing a curable tool) and asserts the directive fires
additively with **zero subtracts** (`schema_refresh_warns=1, rewinds=0`, one-shot/tool).

---

## §4 — Rank 2 (SHIPPED): completing the curable-KIND lever taxonomy

`29fd70c`. The $0 pure-module prerequisite the verification surfaced.

**The bug it fixed:** `refresh_directive` was **degenerate** for the two non-SCHEMA
curable kinds. A REFERENCE (NOT_FOUND) or STATE (already-exists) corrective is
`actionable=True` so it did not early-return `""`, but `missing_required`/`constraints`
are empty for those kinds so *every body branch was skipped* — the agent got a generic
frame with NO env corrective. Verified live: `refresh_directive(extract_corrective(
"Change not found with identifier 'CHG_001'"), "update_change")` returned a frame with
the `CHG_001` id absent.

**The fix** kind-dispatches `refresh_directive`, completing the taxonomy:

| KIND | env grammar | the lever | what DOS authors |
|---|---|---|---|
| **SCHEMA** | `is required` / `expected type` / `must be <fmt>` | re-surface the field/type checklist | framing only |
| **REFERENCE** | `not found` / `NOT_FOUND` | route a LOOKUP (resolve the id, never re-send it) | framing + env's verbatim NOT_FOUND text |
| **STATE** | `already exists` / `conflict` | route a RE-PLAN (re-read state, never retry identical) | framing + env's verbatim conflict text |
| **OPAQUE** | no actionable detail | early-halt ([[docs/198]] §2) | nothing — returns `""` |

`extract_corrective` now redacts the agent's reflected-input echo from `raw` at
extraction (the `natural_thrash_gate`/`terminal_error` discipline), so the REFERENCE/
STATE branches — which embed `raw` verbatim — carry only the env's THIRD_PARTY message.
DOS still authors no replacement id, value, or corrected plan. The ceiling is
KIND-invariant under the redaction (47/2/11/3 at n=63). +3 tests, suite 14 green.

**Honest ceiling on Rank 2:** it makes the REFERENCE/STATE levers *exist*; it does not
promise they *convert*. The killed-proposal analysis (§5) found 92% of REFERENCE
thrashes had ALREADY issued a lookup and still thrashed (the id is hallucinated) — so
REFERENCE survives only as a folded branch in a combined arm, never standalone. And the
counts (REF n≈2, STATE n≈11 on the curable corpus) are far below d≥6 — these kinds can
never be powered as standalone arms on this corpus.

---

## §5 — The killed directions (do not re-propose)

The adversarial pass killed 8 proposals. The instructive ones, with the verified reason:

- **"Hybrid arm that rides an existing LIVE give-up floor."** FATAL on buildability:
  there is **no live give-up/OP_HALT path** in `dos_react.py`. `giveup_arm.py` is a $0
  OFFLINE corpus-replay scorer (its own docstring: "no Gemini / no gym ... never kills
  a process"). The FA=0/43.7k-token result was computed by replaying the recorded
  corpus, NOT a live floor a positive fix "rides on." Do not claim a live give-up floor
  until a live OP_HALT branch actually exists.
- **"Per-error-KIND give-up K"** and **"KIND-router via a maybe-schema-refresh method."**
  FATAL: every cited edit site (`_maybe_schema_refresh`, `self._giveup_k`,
  `_probe_hybrid_ceiling.py`) is fabricated — grep finds zero matches. Accurate
  *motivation* (the K=2 vs K=3 1.9pp gap is real) does not make a diff against
  nonexistent symbols buildable.
- **"Standalone zero-authorship REFERENCE-lookup arm."** FATAL on power +
  already-refuted-livelock: 13 REFERENCE instances corpus-wide (n≈2 curable), and 92%
  had already issued a lookup and still thrashed — the directive prescribes the action
  the agent already took (the upstream-omission livelock that sank rewind). The gym has
  no `tools/list` introspection, so the "0%-authorship" headline doesn't hold here.
- **"$0 re-score of recorded rewind/block/restart arms on the curable slice."** FATAL on
  unlock-empty: ran `conversion_on_curable` on every available arm — **d=0 discordant
  pairs in every one**. With d=0 nothing can ever be labeled genuinely-negative; the
  ledger mints zero new information. [[docs/199]] already routes to a fresh n≥30 live
  spend ("not a re-read") — which is Rank 1.
- **"$0 tool-binding-vs-difficulty decomposition to set the conversion prior."** FATAL
  on already-done: `_verify_198_confound.py` Q2 + `_probe_track4_decomp.py` + docs/201
  §4a already publish exactly this (recovery decoupled from success; the n~150 power
  table). Re-deriving committed results changes no decision.

**The pattern across the kills:** the most seductive fix proposals assume a *live floor*
(give-up actuation) that was only ever measured *offline*, or cite *fabricated edit
sites*. Before proposing a "wiring-only" growth, **grep the actual symbols and RUN the
existing instruments.**

---

## §6 — The live A/B (deferred, ready) + the lane note

The build is complete; the measurement is one run away. The pre-registered experiment
([[docs/199]] §2, scored by `feasibility_split.py --cure schema_refresh --min-curable-n 30`):

- **Arms:** `none` vs `schema_refresh`, paired across the 11 curable-thrash task
  families, `--reps 8 --domains email itsm --mint-rate 0.0` (natural regime).
- **Denominator:** the CURABLE slice ALONE, on task-success. WALLED excluded by construction.
- **Pre-registered kill:** ship iff fired-flip **NET > 0 at d≥6, n≥30**; report
  underpowered honestly otherwise.
- **Outcomes, all banked** (but see §6.1 — the concurrent run sharpened these): (a) NET>0
  reverses "every positive cure refuted" *for the curable slice* — the most
  roadmap-changing result available, BUT bounded by the multi-failure base rate (§6.1);
  (b) NET≈0 closes the conversion question honestly (DOS value = detection + give-up) —
  now the *expected* outcome given §6.1; (c) thrash too scarce → more reps — **retired by
  §6.1**: the concurrent run showed the limit is the conversion-event rate, not n.

**Why deferred (the lane discipline):** a concurrent session is actively writing the
gym corpus (`live_results_curable_ab` grew 41→55 `warn` runs *during this session*,
files written seconds apart; a sibling commit `19e47c7` landed on master mid-work). The
gym containers are shared; launching a competing live run into the same containers risks
DB/Docker contention and would corrupt the concurrent paired-arm structure. The
`schema_refresh` arm is registered and CLI-recognized; the next free-gym run (or the
concurrent session, which can now add `schema_refresh` to its `--arms`) collects it into
a *separate* `--out live_results_curable_schema_ab`.

---

## §6.1 — The concurrent measurement (the ceiling the schema_refresh arm must beat)

The concurrent session ran [[docs/199]]'s curable A/B (`5f07713`, 165 live runs:
`none`/`warn`/`restart_seeded`, 55 each, natural regime, gemini-2.5-flash, the 11
witness-targeted curable-thrash families). The result **sharpens the pre-registered
outcomes above** — read it before running the `schema_refresh` arm:

- **Conversion on the curable slice is ~0, and NOT for lack of n.** `warn` flipped
  1 (help 1 / hurt 0), `restart_seeded` flipped 0; d≤1 both. Crucially, **it is
  event-rate-bounded, not sample-size-bounded** — more reps will not raise d, because
  the flips do not happen.
- **The mechanism (the key refinement):** base task-success on these curable-thrash
  tasks is **~5% (3/55)** — they are **MULTI-FAILURE** tasks. Curing the thrash leaves
  the run failing for *other* reasons. This is [[docs/177]]'s "capability redistributes
  failure" reproduced *at the cure layer*: **feasibility is necessary, not sufficient.**
- **Give-up-correctly re-confirms on this fresh corpus** (the §2 numbers above are from
  this same run): K=2 FA 0.000, 43.7k saved, 15 WALLED halts.

**What this does to outcome (a).** The "NET>0 reverses every positive cure refuted"
headline is now bounded: even a byte-clean cure faces the ~5% multi-failure wall, so a
positive flip requires the **schema error to be the *binding* failure** on the task — not
merely present. The honest pre-registration for the `schema_refresh` arm is therefore:
**condition the curable slice further on single-binding-failure tasks** (the schema
thrash is the last remaining failure), or expect a null that is *event-rate-bounded, not
underpowered*. Do NOT chase n≥30 with more reps — [[docs/199]] §4 retired that action
item (n is not the wall; the event rate is). The schema_refresh arm is still worth
running — it is the one cure that *could* convert a binding schema failure, and it is the
last unmeasured cell — but its ceiling is the multi-failure base rate, not the 75–76%
corrective-presence ceiling. The two ceilings multiply: `P(convert) ≤ P(schema corrective
present) × P(schema failure is binding)`, and the second factor is what [[docs/199]]
measured small.

## §6.2 — The schema_refresh arm RAN — and it is NET-NEGATIVE (a harm channel §6.1 didn't predict)

The same concurrent session then ran THIS arm (`live_results_curable_schema_ab`, 176
live runs: `none` vs `schema_refresh`, 88 each, `--reps 8`, natural regime,
gemini-2.5-flash, same 11 families). Scored
`feasibility_split.py --cure schema_refresh --min-curable-n 30`. **The arm genuinely
fired: 77/88 cure runs fired at least one schema directive (87 total fires)** — the
`natural_thrash_gate` engaged on real Kth-same-tool errors, not on tool-name alone.

The §6.1 prediction (the cure *can* convert a binding schema failure) is **CONFIRMED on
the targeted slice** — and then **overturned at the net** by a harm channel §6.1 did not
model:

| slice | n | help | hurt | NET | sign-p |
|---|---:|---:|---:|---:|---:|
| has CURABLE thrash | 35 | 2 | 0 | **+2** | 0.500 |
| no-thrash (in `none`) | 42 | 0 | 7 | **-7** | **0.016** |
| all paired | 88 | 2 | 7 | **-5** | 0.180 |

Task-success **dropped: none 7/88 -> schema_refresh 2/88.** The attribution is
**causally clean** — of the 9 flips, **all 9 had a schema_refresh fire** (7 hurt /
2 help / 0 hurt-without-fire):

- **The cure works where it's aimed:** +2 curable-thrash conversions, both with a fire.
  The byte-clean re-surface does convert a curable thrash to a task-success.
- **But the fire itself is harmful more often than its content helps:** the 7 hurt runs
  are tasks that PASSED in `none`, thrashed (stochastically) in the cure arm, received
  the directive, and then FAILED — all 7 with a fire. The "no-thrash" label is the
  `none`-arm split; the cure fires per-arm, so a baseline-clean run that thrashes once
  in the cure arm gets perturbed by the extra forcing turn.

**THE FINDING (sharper than §6.1's ceiling argument):** the harm is not in *what* the
cure says (it is byte-clean, additive, advisory — all the docs/164/200 disciplines hold).
The harm is that **intervening AT ALL** — injecting an extra `HumanMessage` turn into a
running loop — perturbs runs that were on track, and on a weak multi-failure model that
costs more task-successes (-7) than the targeted conversion saves (+2). The cure's
*existence in the loop*, not its content, is the net-negative. This is the docs/188
"every agent-side rung is wash-to-negative by structure" result, reproduced for a
byte-clean POSITIVE cure on the feasible slice — the structure (a turn-injecting
intervention) dominates the byte-cleanliness.

**Consequence for the fix story:** the only fix robust across regimes remains the
NEGATIVE one (give-up-correctly — re-confirmed AGAIN on this 88-run none arm: K=2 FA
0.000, **59k tokens saved**, 18 WALLED halts). A positive cure must clear a higher bar
than "byte-clean + targeted": it must fire ONLY when the schema failure is the *binding*
one AND the run would otherwise fail — it must not fire on a run that would have passed.
That is a precision-of-firing requirement the current `natural_thrash_gate` (fires on any
Kth same-tool error) does not meet. The arm is measured; the verdict is **net-negative,
do not ship as-is** — the next lever is firing precision (gate on "would-fail", not
"thrashed"), not the directive bytes. Witness/reads: `_split_schema.txt`,
`live_results_curable_schema_ab/_summary.json`.

---

## §6.3 — The firing-precision lever is NOT buildable — the harm is cross-arm by structure

§6.2 named the next lever: gate on "would-fail," not "thrashed." This section runs that
investigation to ground, over the same 88-pair corpus, and the answer is **no — not for
lack of the right feature, but because the harm is structurally invisible to any
fire-time gate.** Three independent reads (a hand re-derivation `_precision_findings.md`,
a 7-agent / 5-signal fan-out `wf_29157dd5` with adversarial verify, and a K-sweep) all
converge on `verdict-final-document-negative`. Reads: `_precision_findings.md`,
`/tmp/_xcheck*.py`, `_precision_ground.py`.

**The decisive structural fact: `would_pass_in_fire_set = 0`.** A precision gate's only
job is to *withhold the cure from runs that would have passed*. But in the no-cure arm,
thrashing a CURABLE tool K=2× un-recovered is **perfectly correlated with task-failure**
(35/35 fire-set reps fail). The gate is already 100% precise on its own arm — there is
**nothing to suppress.** Every byte-clean fire-time signal tested — corrective-kind,
thrash-breadth, co-walled, corrective-specificity, progress-before-fire — has an *empty
would-pass column*, so each candidate yields precision-gain 0 while only destroying
would-fail recall (keep-SCHEMA −7, co-walled −7, breadth≥2 −29 of 35). No gate beats the
no-op.

**Why §6.2's "fire on would-fail" framing cannot reach the harm.** The −7 hurt reps have
`none_fires = False`: their *no-cure* rollout **passed without ever thrashing**. The harm
happens entirely in the *re-seeded cure rollout*, which thrashed (stochastically, temp
0.6) and got the directive. So the would-pass label lives in one rollout and the fire in
a *different* rollout of the same task — a fire-time gate computed on the failure stream
is **structurally blind** to a harm that originates on runs which never enter any fire
set without the cure. This is the [[docs/188]] wash-by-structure result again: the harm is
the intervention's *existence*, not a mis-aimed fire — and existence is not a thing a
firing gate can decline.

**The agent-level mechanism (the trace, why a passing rollout breaks).** Inspecting the
two harm tasks (`task_20251211_054846`, `task_20260106_054515`, both thrashing
`update_vacation_settings`): in the cure arm the agent *fixes the thrashing tool* — the
local conversion succeeds (`uv_errs=2, LATEST_uv_OK=True`) — **yet the task still fails**,
making 3 tool-calls vs the no-cure rollout's 5+, never completing the *other* objectives
(forwarding removal, message deletion, profile). The directive's "satisfy requirements
**before retrying**" framing induces **premature-stop / tunnel-vision**: it converts the
local error and truncates the multi-part task. The help task (`add_new_user`) is
single-objective — fix the tool *is* finish the task — so the same directive helps. The
discriminator is the **multi-part task GOAL**, which is the user prompt, not anything in
the env error stream — the W3 goal-witness wall ([[docs/192]]). The kernel's byte-clean
rung never sees it.

**Even the waste-removal hygiene fix is blocked by the same wall.** The live cure fired
87× including **16 (18%) on WALLED tools** (`create_filter` ×10, `update_draft` ×6) it can
never convert — apparent free waste to remove by re-checking feasibility. But all 16
walled fires carry `kind=SCHEMA, schema_convertible=True`: actionable correctives,
non-empty directives, **byte-indistinguishable per-run from genuinely curable tools**
(`create_filter` *looks* curable — the env says "you're missing fields" — but is
infeasible, [[docs/194]]). The only thing that knows it is walled is the **corpus-wide**
feasibility witness (0 successes across ALL runs), which a single live run cannot compute.
So suppressing walled fires would need a pre-computed denylist passed in as
corpus-derived config — not a self-contained live verdict. Feasibility is corpus
knowledge, not a present-run byte, at the cure site too.

**Verdict.** Firing-precision is not a lever here. The net-negative stands; the surviving
fix is the NEGATIVE one (give-up-correctly). The only positive hypothesis still standing
is a *different* knob — directive **form**, not firing: a passive advisory WARN (drop the
"before retrying" forcing) might keep the conversions without the premature-stop, testable
only by a fresh live A/B (passive-WARN vs forcing vs none). That is a content experiment,
not a rescue of firing-precision.

---

## §7 — The durable lesson

The fix story is weaker than the detect story for one reason that survived every
refutation: **detection reads bytes the agent did not author and is grounded by
construction; a cure must change the trajectory, and the one rule forbids authoring the
change — so a positive fix can only exist where the env already stated the correction,
and even then must be re-surfaced, never generated.** The negative fix
(give-up-correctly) is robust because withholding spend authors nothing — it is
detection wearing an actuator.

Therefore the fix story grows ONLY at the intersection of the three conditions (§1
corollary): env-authored corrective × witness-gated curable scoring × additive
re-surface. The `schema_refresh` arm is the first move that satisfies all three and is
buildable; it is the positive fix made robust by **riding the detection floor** — the
same gate, one branch early-halting the wall, the other re-surfacing the cure.

And the methodological half, generalized from the [[docs/198]] category error: never
score a cure on a denominator that mixes infeasible (walled) tasks with curable ones,
**and** never confuse a run-local kind-classifier (env grammar) with a feasibility
witness (cross-run success) — only the latter separates "the env said how to fix this"
from "this task is impossible." Before proposing a wiring-only growth, grep the symbols
and run the instruments: the seductive proposals assume a live floor that was only ever
measured offline.

§6.3 adds the third and sharpest instance of the same wall. A "fire only on would-fail"
gate sounds like a precision tuning, but the **would-fail vs would-recover divergence is
DOWNSTREAM of the fire** (a fire-time predicate reads the past; the divergence is the
future), and the harm lands **cross-arm** on runs that never thrash without the cure — so
no fire-time signal can reach it. The real discriminator is the multi-part task GOAL the
kernel structurally cannot read. The lesson compounds: not only can a cure not *author*
the correction, it cannot even *time itself* against the goal — both the "what to fix" and
the "whether to intervene at all" decisions need a goal witness the byte-clean rung does
not have. The fix story's ceiling is the goal-witness wall, reached from two sides.
