# Re-occurrence is not regression — the terminal-transition invariant

> **The distrust notes so far all guard the *space* axis: a worker's "done" is
> content, so adjudicate against the git fossil, not the sentence
> ([`108`](108_the-cheap-lie-and-the-narration-taxonomy.md)); a recalled
> self-report is an unverified agent ([`103`](103_memory-is-an-unverified-agent.md));
> a `STEP_CLAIMED` without a `STEP_VERIFIED` is not-done
> ([`107`](107_resumable-work-and-the-intent-ledger.md)). This note names the same
> kernel move on the *time* axis. When a system counts how often a cause has
> occurred to decide whether *a prior fix failed* — "this regressed", "the fix
> didn't hold", "RECURRENCE ×N" — it is making a claim about a **terminal
> transition** (the cause was closed, then re-opened). Keying that claim on the
> raw *occurrence* count instead of the *close→reopen* transition is the cheap
> lie's temporal twin: it reads a still-open, never-resolved condition as a
> failed repair. The invariant: **a recurrence/regression counter must key on the
> terminal/closed transition, not the open event.****

A theory note in the family of [`108`](108_the-cheap-lie-and-the-narration-taxonomy.md)
(content-vs-fossil), [`103`](103_memory-is-an-unverified-agent.md) (the frozen
self-report), [`107`](107_resumable-work-and-the-intent-ledger.md) (the
`STEP_CLAIMED`/`STEP_VERIFIED` asymmetry), and [`102`](102_when-to-trust-an-agent.md)
(structure-not-content, before-not-after, cheap-to-detect). Like `108` it
**carries no litmus and ships no module** — it is a *reading* of what the kernel
already does, plus the one boundary it draws so a future verdict-leaf doesn't get
it wrong. The contribution is a *named axis* (time/recurrence) and a *worked field
instance* (a real host bug, dated and diagnosed) on a regress every prior note in
the family handled correctly without naming it as one thing.

---

## 1. The thesis: a "didn't hold" claim is a claim about a transition

A fleet accumulates signals that *re-fire*: a lane wedges on the same cause
across runs; a defect is logged again; a finding routes a second time. Two very
different things can be true when a signal re-fires:

- **Recurring / ongoing** — the same unresolved condition keeps surfacing. Nobody
  fixed it; it never stopped. ("This lane has wedged on a stale claim five times
  this week.")
- **Regressed / didn't-hold** — the condition was *resolved* and has come back. A
  fix shipped, the signal went quiet, and now it's loud again. ("The fix for this
  wedge landed in `abc123` and the wedge is back — the fix didn't hold.")

These read the same on the wire — *the cause fired again* — but they are
categorically different verdicts. "Recurring" routes the cause to a remediation
sweep so a human lands the structural fix. "Regressed" is a louder, scarier
claim: it asserts a *prior repair failed*, names the commit that was supposed to
fix it, and (rightly) escalates harder. The danger is the asymmetry of the
mistake. Calling a true regression merely "recurring" *under*-escalates — bad, but
quiet. Calling a never-resolved ongoing condition a "regression" *over*-escalates,
and does so **self-perpetuatingly**: a condition that by its nature never closes
(infrastructure collateral the fleet already auto-recovers, say) re-fires forever,
and every re-fire after the first climbs the severity ladder, claiming a fix
failed when no fix was ever attempted. The false-HIGH signal floods the very
priority surface the counter feeds, burying the real regressions under
manufactured ones. The counter *corrupts the thing it exists to rank.*

The fix is not a better count. It is the same category move the rest of the family
makes: **don't read the occurrence (content); key on the terminal transition
(structure).** A regression is, definitionally, a *close followed by a re-open*. So
a re-occurrence is a regression **iff a prior occurrence of this cause reached a
recorded terminal state** (closed / resolved / verified-fixed) before this one. An
occurrence whose priors never closed is ongoing, not regressed — full stop, no
escalation. The transition is the falsifiable fact; the raw count is narration
about it.

---

## 2. The taxonomy — re-occurrence, and the discriminator each kind needs

"The signal fired again" is not one event; it is three, and they do *not* share a
verdict. Conflating them is how a counter ends up escalating the common ongoing
case as if it were the rare regression.

| # | Re-occurrence | What actually happened | Honest verdict | Discriminator it needs |
|---|---|---|---|---|
| 1 | **ongoing** | the same condition never resolved; it keeps surfacing | RECURRING — route to a fix, at natural severity | distinct-run / distinct-occurrence count (no close needed) |
| 2 | **regressed** | a prior occurrence *closed*, then the cause re-opened | DIDN'T-HOLD — escalate; name the failed fix | a recorded **close** on a prior occurrence (the transition) |
| 3 | **churned** | the same occurrence re-emitted within one episode (no progress between) | NEITHER — dedup; it is one event seen twice | a stable occurrence key + a "since the last forward delta" reset |

The error the family already avoids elsewhere is **promoting #1 to #2**: counting
ongoing occurrences and reporting them as a failed fix. The discriminator that
separates them is a **close event**, and nothing cheaper substitutes for it — not
"it fired N times" (that is #1's signal, and #1 can fire unboundedly), not "it
fired recently" (recency is orthogonal to closure). Only "did a prior occurrence
*leave the resolved state*" answers "was there a fix to fail." This is exactly
[`108 §2.2`](108_the-cheap-lie-and-the-narration-taxonomy.md)'s move — the flake
and the lie collapse to one adjudicator *because git is the only discriminator that
separates them* — transposed onto time: the ongoing condition and the regression
collapse to one wire signal, and the **close transition is the only discriminator
that separates them.**

### 2.1 Why the count is the wrong key (the over-escalation engine)

A counter keyed on occurrences has an unbounded-climb failure mode that a counter
keyed on closes does not. An ongoing condition emits occurrence 1, 2, 3, … forever;
if "occurrence ≥ 2 ⇒ regressed", every occurrence after the first is a (false)
regression, and the severity only ratchets up. The counter has no fixed point: the
louder it gets, the more it re-fires, the louder it gets. Keying on the
*close→reopen* transition is self-limiting by construction — the count cannot
advance without a real closure between firings, and a closure is a discrete,
evidence-backed event (a resolved-and-pruned row, a verified-fixed phase) that an
unfixable ongoing condition simply never produces. The structure bounds the claim;
the count does not.

### 2.2 The symmetric trap — don't lose the close, either

The invariant cuts both ways, and the *upstream* half is load-bearing. If the
discriminator is "a prior occurrence closed," then **every path by which an
occurrence leaves the resolved state must record that close** — or a genuine
regression silently *under*-escalates (its prior close was never written, so the
re-open looks like a first occurrence). The discipline is therefore paired: the
*counter* keys on closes, **and** the *closer* records a close on every exit path
(resolved-and-pruned, expired, operator-struck — not just the one happy path). A
half-wired close-writer turns a correct counter into a silently-deaf one. The field
instance below got this right precisely because its close was written on *both* its
exit paths; that is what made the counter-side fix complete rather than half.

---

## 3. Where the kernel already obeys this — and the one boundary to hold

This note ships no code because **every DOS verdict leaf that counts already keys on
the transition, not the raw event.** Reading them as instances of the one invariant:

- [`noop_streak`](../src/dos/noop_streak.py) — the consecutive-no-op-turn budget
  **zeroes on a forward delta**. A run that makes progress and then stalls again does
  not inherit its old streak: the streak is "no-op turns *since the last forward
  delta*", i.e. keyed on the progress transition, not a raw turn tally. (The `>=`
  cap, not `>`, errs conservative — over-spending on a missed count is the failure
  it avoids, the mirror of over-escalating here.)
- [`improve`](../src/dos/improve.py) — `REGRESSED` is keyed on a **measured floor**
  (suite red or truth syscall dirty), and `consecutive_reverts` is a breaker count
  that **resets to zero on an accept**. A keep between two reverts is not "three
  reverts in a row" — the carried count keys on the kept/reverted *outcome*
  transition, never on raw attempt volume.
- [`efficiency_trend`](../src/dos/efficiency_trend.py) — a DEGRADING verdict requires
  **two consecutive** runs below a strictly-prior-median band, not a single dip and
  not a raw count of low runs. The sustained transition is the signal; one noisy run
  is not.
- [`intent_ledger`](../src/dos/intent_ledger.py) /
  [`resume`](../src/dos/resume.py) — replay treats a `STEP_CLAIMED` **without** a
  matching `STEP_VERIFIED` as not-done (fail-closed). "Done" is the verified
  transition; the claim alone is content, distrusted — `107`'s asymmetry, which this
  note's invariant is the temporal projection of.

The one boundary to **hold deliberately**: not every recurrence counter is a
regression counter, and the recurring-blocker fold
[`recurring_wedge`](../src/dos/recurring_wedge.py) is correctly on the *other* side
of this line. It counts **distinct runs a cause wedged across** and calls a cause
"recurring" at `>= min_recurrence` runs — an *occurrence* count with **no close
concept at all**. That is right, because its claim is taxonomy **#1 (ongoing)**, not
**#2 (regressed)**: it answers "is this structural blocker still wedging the fleet
across runs, worth a remediation sweep," and makes *no* assertion that a prior fix
failed. `BlockerHit` has no terminal-transition field because it needs none — adding
a close discriminator there would be wrong, not a fix. The invariant is therefore
**scoped to the claim, not the shape**: a counter over un-terminated occurrences is
*correct* for an ongoing/recurring verdict and *a bug* for a regressed/didn't-hold
verdict. Read the verb before the count. A future leaf that wants to emit
"DIDN'T-HOLD" — a true regression verdict, as opposed to `recurring_wedge`'s
"still-wedging" — is the one that owes its claim a close transition, and this note is
the contract it answers to.

---

## 4. The field instance — a host counter that promoted #1 to #2

The note is anchored, not abstract. A DOS host (the job-search fleet, the
longitudinal field site for the kernel) shipped a self-routing findings queue: a
self-improvement signal that re-fires routes a fresh row, and a row that gets
resolved is auto-closed and pruned. To make a fix-that-didn't-hold *louder*, the
router escalated a re-routed cause: if the cause had routed before, raise severity
to HIGH and stamp `RECURRENCE ×N — no fix commit was ever recorded.`

The recurrence counter keyed on the **raw prior-`open` count** — every prior routing
of the cause, regardless of whether any prior row ever closed. So any cause that
re-fires but **never closes** — quota-wall collateral the fleet's reaper/supervisor
already auto-recover, which is *not* a fixable code regression — false-escalated
**every** occurrence after the first to HIGH "the fix didn't hold," naming a fix that
never existed. Eight distinct never-closing causes produced nine live false-HIGH rows
in a 558-row queue, burying real regressions under manufactured ones: the
priority-surface-corrupting failure mode of §1, observed live. The router's own
docstring already stated the correct contract — "recurrence means the cause routes
again *after its prior row left the queue*" — but the code counted opens, not the
left-the-queue transition. Exactly the **promote-#1-to-#2** error this taxonomy
names.

The fix was the invariant: count only prior occurrences that carry a **recorded
close** (a resolved-and-pruned row writes one). An ongoing un-closed condition now
routes at natural severity; a genuinely closed-then-reopened cause still escalates
and names the failed fix's commit. And it was *complete* rather than half because the
host's closer already obeyed §2.2's symmetric half — it records a close on **both**
exit paths (auto-close-with-commit *and* maintenance-prune-without) — so a real
regression's prior close is never lost. One host counter had simply re-implemented,
incorrectly, a discrimination every kernel leaf in §3 already makes; the bug lived in
the surface that had drifted *out* of the kernel's verdict-leaf family, which is the
general lesson `108`'s "every narration-reading layer gets it wrong" predicts for
the temporal axis too.

---

## 5. The one-line takeaway

`108` says: *don't read "done" — ask git.* This note says the same on the time axis:
**don't read "it happened again" as "the fix failed" — ask whether it ever closed.**
A recurrence is content; a regression is a transition. Key the verdict on the
transition, write the close on every exit, and read the verb (ongoing vs
didn't-hold) before you trust the count.
