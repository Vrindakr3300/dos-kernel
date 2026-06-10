# Curable-conversion firing-precision — independent corpus analysis (2026-06-06)

Corpus: `live_results_curable_schema_ab/` — 88 rep-aligned pairs (11 tasks × 8 reps),
`none` vs `schema_refresh`. Cross-checked the committed verdict (`0cac947`) independently
(`/tmp/_xcheck*.py`, byte-clean dos_react grammar).

## The verdict reproduces exactly
- none arm: **7/88** task-success. schema_refresh arm: **2/88**. Net = **−5**.
- Cure fired on **77/88** runs (the gate is very loose).
- Rep-aligned paired flips: **help=2, hurt=7, NET=−5** (both0=79).

## The harm is NOT spread — it is 2 tasks
The 7 "hurt" flips (none PASSED → refresh FAILED, cure fired on all 7) come from exactly
**2 distinct tasks**:
- `task_20251211_054846` (email) — 3 reps
- `task_20260106_054515` (email) — 4 reps
Both thrash **`update_vacation_settings`** (a CURABLE tool, KIND=SCHEMA).
The 2 "help" flips are 1 task: `task_20251219_111447` (itsm), tool `add_new_user`.

## The mechanism (from trace inspection, `/tmp/_xcheck4.py`)
- **HELP** (`add_new_user`): 4 straight errors, no interleaved progress, cure fires at
  n_fail=2, agent **acts on the env corrective and completes the whole multi-step task**
  (add_new_user→group→members). Textbook conversion.
- **HARM** (`update_vacation_settings`): in the `none` arm the agent thrashes the one hard
  tool **while interleaving successful OTHER-tool work** and eventually self-recovers /
  completes enough of the multi-part task to pass. When the cure fires at n_fail=2, the
  forcing directive **redirects the agent to tunnel on the thrashing tool** — it often gets
  that one tool to `ok` but **truncates the rest of the multi-part task** (cured traces are
  ~6–8 calls vs 17 in none). Harm = **attention hijack on a multi-tasking agent**, not
  additive noise.

## The precision lever is NOT buildable — the divergence is DOWNSTREAM of the fire (corrected)
Two byte-clean fire-time discriminators tested, both fail:

**(a) `ok_other` (interleaved progress before fire).** would-PASS ∈{1,3}; would-FAIL ∈{0..5}.
Fully overlapping; no separation.

**(b) K-threshold (raise the fire bar from K=2).** DECISIVE and corrects (a): using the EXACT
live gate (first tool to reach K errs, *latest still erroring*), the 7 would-PASS runs fire on
**0** at EVERY K from 2→8. They never fire *in the none arm* because they **self-recover**
(LATEST update_vacation_settings = OK; the gate's recovery clause correctly withholds). So at the
gate level there is nothing to suppress on the none-arm would-pass set — raising K only loses
would-fail targets (46→12 fires, all would-fail).

**The harm is a different-rollout effect, not a wrong-fire on a passing run.** The would-PASS
LABEL is the *none*-arm rollout of a task; the HARM happens in the *cure*-arm rollout of the SAME
task (re-seeded DB, temp=0.6 → stochastic). At the K=2 fire point those two rollouts are
**byte-identical** (2 errors on update_vacation_settings, in the hole). What differs is the
FUTURE: the none rollout self-recovers + finishes the multi-part task; the cure rollout obeys the
directive, fixes the one tool, and **STOPS before the remaining objectives**.

Smoking gun (`/tmp/_recover.py`), task_20251211 cure arm:
`uv_errs=2 LATEST_uv_OK=True cure_fired=1 → ok=FALSE` — the agent FIXED the thrashing tool
(local conversion succeeded!) but the TASK still failed: it made only 3 tool calls total vs the
none arm's 5+, never completing forwarding-removal / message-deletion / profile. **The directive's
"satisfy requirements BEFORE retrying" framing induced premature-stop / tunnel-vision: it converts
the local error and truncates the global multi-part task.**

## Why precision is structurally hard here (3 independent reasons)
1. **The divergence is in the future, not the present bytes.** "Will this rollout self-recover
   and finish, or will it stop?" is decided AFTER the fire point. A fire-time predicate can only
   read bytes up to the fire; the discriminating event hasn't happened yet. This is not a
   missing-signal problem, it is a causal-ordering one.
2. **The harm is goal-structured, and DOS can't read the goal.** The cure helps on
   single-objective tasks (`add_new_user`: fix the tool = finish the task) and hurts on
   multi-objective tasks (`update_vacation_settings` + forwarding + message + profile: fixing the
   tool ≠ finishing the task; the directive pulls focus off the rest). That split is the
   user_prompt / goal — the W3 goal-witness wall (docs/192). The env error stream is identical
   across the two; the kernel's byte-clean rung never sees the goal.
3. **n + concentration below any validation floor.** The harm-risk set is 7 runs = 2 tasks. Even
   if a signal existed, you could not validate it: suppressing 7 firings concentrated in 2 tasks
   is overfitting, and the same fingerprints recur throughout the 71 would-fail targets.

## The decisive structural fact (7-agent workflow `wf_29157dd5`, corroborated)
A 5-signal fan-out (corrective-kind / thrash-breadth / co-walled / specificity /
progress-before-fire) + adversarial verify, over a from-scratch re-derivation, returns **0
separators, 0 survivors** and the verdict `verdict-final-document-negative`. The crux it nails:

> **`would_pass_in_fire_set = 0`.** In the no-cure arm, thrashing a CURABLE tool K=2×
> un-recovered is **perfectly correlated with failure** (35/35 fire-set reps fail). So the gate
> is *already* 100% precise on its own arm — there is nothing for a precision gate to suppress.
>
> **The −7 harm is entirely CROSS-ARM.** All 7 hurt reps have `none_fires=False` — their *none*
> rollout **passed without ever thrashing** — yet the cure fired in the re-seeded *refresh*
> rollout (which did thrash). A "would-fail" gate computed at fire time is **structurally blind**
> to the harm, because the harmed runs are not in ANY fire set in the no-cure arm. This is the
> docs/188 **wash-by-structure** result, now for a POSITIVE cure: the harm is the intervention's
> EXISTENCE perturbing a paired-passing run, not a mis-aimed fire.

This UNIFIES with the trace-level finding above: "premature-stop on multi-part goals" is HOW the
injected turn breaks a passing rollout (agent-level); "would_pass=0, cross-arm" is WHY no
fire-time gate can prevent it (statistical-structure level). Same phenomenon, two altitudes.

## Bottom line
Firing-precision as "gate on a byte-clean would-fail signal" is **not realizable** — for THREE
reinforcing reasons: (1) **the gate is already 100% precise** in its own arm (would_pass=0), so
there is nothing to suppress; (2) **the harm is cross-arm** — it lands on runs that never thrash
without the cure, which no fire-time predicate can see (wash-by-structure); (3) at the agent level
the divergence (self-recover-and-finish vs obey-and-stop) is DOWNSTREAM of the fire and governed
by the multi-part task GOAL the kernel structurally cannot read (W3 wall). Every non-trivial gate
strictly DESTROYS would-fail recall (keep-SCHEMA −7, co-walled −7, breadth≥2 −29) for **0**
precision gain, pushing net BELOW −5. The net-negative verdict STANDS; the surviving fix is the
**negative one (give-up-correctly)**.

## Two honest salvages the analysis surfaces (neither is firing-precision)
- **Feasibility re-check on the LIVE cure — TESTED, and it is ALSO blocked by the wall.** The
  live cure fired **87×**, of which **16 (18%) landed on WALLED tools** (create_filter ×10,
  update_draft ×6) — tools the corpus-wide witness knows have 0 successes anywhere, so a
  schema-refresh can never convert them. That looks like free waste to remove. BUT: all 16 walled
  fires carry `kind=SCHEMA, schema_convertible=True` — actionable correctives, non-empty
  directives, **byte-INDISTINGUISHABLE per-run from genuinely curable tools** (`create_filter`
  *looks* curable: the env says "you're missing fields"; it is actually infeasible — docs/194).
  The ONLY thing that knows create_filter is walled is the **corpus-wide** feasibility witness (0
  successes across ALL runs), which a single LIVE run cannot compute. So there is **no byte-clean
  per-run signal** to suppress walled fires either — the hygiene fix would need a pre-computed
  walled denylist passed in as corpus-derived config, not a self-contained live verdict. Even the
  waste-removal is blocked by the same feasibility-is-corpus-knowledge wall.
- **Route the 7 co-walled infeasible would-fail runs to the surviving NEGATIVE give-up arm**
  (early-halt), where the corpus already supports them. That is the give-up lever, not conversion.

## The one lever that IS implied (form, not firing — a SEPARATE experiment)
The smoking gun points at a different knob than firing-precision: the HARM is the directive's
**"satisfy requirements BEFORE retrying" forcing framing**, which induces premature-stop. A
*passive* re-surface (advisory WARN: "the env reported these missing fields" with NO "before
retrying" / no forcing) might keep the +conversions without the tunnel-vision stop. That is a
CONTENT/FORM lever, testable only by a fresh live A/B (passive-WARN arm vs forcing arm vs none).
It does NOT rescue firing-precision; it is a different hypothesis about WHY the cure hurts.
