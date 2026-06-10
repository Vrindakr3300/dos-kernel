# The overlap-policy seam — and an eval harness per axis

> **The kernel's most load-bearing scalar — the `1/3` soft-overlap ratio that
> decides whether two agents may write concurrently — is the one core verdict
> with no seam. This note opens it the way every other axis is open: a pure
> policy object behind a by-name resolver, with an unforgeable deterministic
> floor underneath it so a swappable scorer can only ever refuse *more*, never
> admit a collision. And it ships the instrument that makes the seam worth
> having to a researcher: `dos overlap-eval`, a number you can beat.**

This is the build-plan for the answer-shape that
[`90 §1`](90_open-research-areas.md) (predicate-conflict precision) and
[`90 §2`](90_open-research-areas.md) (the soft-overlap threshold) already
specified as *open research*. §2 names the deliverable almost verbatim:

> *"Replace the scalar compare in `overlap_verdict` with a policy object (the
> same 'mechanism is kernel, thresholds are config' split `liveness` already
> uses for its windows) — and a study that backtests candidate compatibility
> functions against a labeled corpus of concurrent runs, scored on detonations
> *missed* vs safe concurrency *forgone*."*

So nothing here is new ground; it is the *implementation* of mechanism docs/90
deliberately left as a stand-in. The two halves map cleanly:

- the **policy object** → the `OverlapPolicy` seam (§2 below),
- the **backtest study** → the `dos overlap-eval` instrument (§4 below).

---

## 1. The asymmetry this closes

DOS ships six hackability axes (`HACKING.md`): reasons, gate-verdicts,
predicates, renderers, workflow, judges. Five are *open* — you bring your own
implementation via `dos.toml` data, an entry-point plugin, or a driver, and
**never fork the package**. One is not: the **disjointness scorer**.

Concretely, the gap is two-part, and only the first part is already covered:

1. **Augmenting the rule is open (Axis 3, `dos.predicates`).** A researcher can
   register an admission predicate that *refuses more* — an import-graph check, a
   semantic-overlap check, a model-backed "these collide" check. Predicates
   compose conjunctively and can only refuse, so this is the safe direction and
   it works today.

2. **Replacing the baseline scorer is sealed.** The baseline
   `lane_overlap.overlap_verdict` — the `1/3` prefix-ratio — is hardcoded inside
   `DisjointnessPredicate`. A researcher who wants a *different baseline*
   (size-weighted, risk-weighted, AST-granularity, a learned predictor — exactly
   `90 §2`'s candidate list) cannot swap it without editing the kernel. There is
   no `OverlapPolicy` protocol, no `dos.overlap_policies` group, no
   unshadowable floor — the judge seam's whole apparatus, absent here.

And — the friendliness gap — there is **no `dos overlap-eval`**. The judge seam
ships `dos judge-eval`, which turns "plug in an adjudicator" into "*measure*
whether yours is better" (a false-clear rate against a labelled set). That
fourth element is what makes a seam research-grade rather than merely
extensible: it produces a *number*. Disjointness — the single most consequential
verdict in the kernel, and the one `90` explicitly flags as a calibrated guess —
ships no such instrument. You cannot calibrate the elbow `90 §2` calls "honest
engineering, not a theory" because there is nothing to calibrate *against*.

## 2. The seam — `OverlapPolicy`

A pure policy object, the drop-in `90 §2` specified. It answers the same
question `overlap_verdict` answers — *may these two known trees coexist?* — and
returns the same typed `OverlapDecision`, so it is a true substitution at the one
seam every collision check already routes through (`DisjointnessPredicate`).

```python
@runtime_checkable
class OverlapPolicy(Protocol):
    name: str
    def overlaps(self, requested_tree, lease_tree, config) -> OverlapDecision: ...
```

- **`name`** — what `dos doctor` lists and `dos overlap-eval --policy <name>`
  selects (the judge/predicate idiom).
- **`overlaps`** — handed the two known trees + read-only `config`, returns an
  `OverlapDecision` (the existing `lane_overlap` type, unchanged). A policy MAY do
  I/O *inside* `overlaps` (call a model, read an import graph) **iff it lives in a
  driver** — the JUDGE-rung allowance. A pure policy (data/predicate-grade) does
  not. Either way, discovery I/O happens at the call boundary, never inside the
  verdict (`active_overlap_policy`).

The default policy is **`PrefixOverlapPolicy`** — a verbatim wrap of today's
`overlap_verdict`. With no `dos.toml [overlap]` and no plugin, the kernel resolves
this one and behavior is **byte-for-byte identical** to today (the load-bearing
litmus: the entire existing arbiter/overlap suite stays green through the seam,
exactly as `DisjointnessPredicate` itself proved when ADM routed the arbiter
through `run_predicates`).

### The empty-tree asymmetry stays in the kernel, NOT in the policy

`DisjointnessPredicate` owns the empty-tree rules (empty lease ⇒ admit; empty
request vs known lease ⇒ refuse; both empty ⇒ admit). Those are **soundness
invariants about unknown blast radius**, not *scoring* — so they stay in the
predicate and a policy is only ever consulted on the **both-known** path. A
plugin author cannot weaken the unknown-blast-radius refusal because they never
see that case. This is the same division `liveness` uses: the *windows* are
policy, but "no evidence ⇒ not ADVANCING" is kernel.

## 3. The soundness floor — structural, not trusted

This is the security-load-bearing core, and it is built so the safety does **not
depend on the policy behaving**. The rule, the admission analogue of the judge
seam's fail-to-ABSTAIN and the predicate seam's conjunctive-only:

> **A resolved `OverlapPolicy` may turn an ADMIT into a REFUSE. It may never
> turn a REFUSE into an ADMIT relative to the unforgeable prefix floor.**

Mechanism: the kernel computes the **deterministic prefix-disjointness floor**
(`PrefixOverlapPolicy`, the unforgeable lower bound — pure path algebra, no
provider, no I/O) *and* the resolved policy, then takes the **conjunction on the
admit direction**:

```
admit  ⟺  floor.admissible  AND  policy.admissible
```

So:

- A policy that says **refuse** when the floor says admit → **refuse** (the floor
  yields to the stricter voice — catching a semantic collision paths missed; the
  safe, *more*-refusing direction).
- A policy that says **admit** when the floor says refuse → **refuse** (the floor
  wins; the dangerous cell — admitting a prefix-colliding pair — is
  *structurally unreachable*, because the floor is ANDed in and the floor is not
  the plugin's to compute).
- A policy that **raises**, or returns a non-`OverlapDecision` → treated as
  "no admit," so admission falls back to the floor verdict alone (fail-closed,
  the predicate-seam posture; a buggy/hostile policy degrades to *today's*
  behavior, never to a looser one).

The worst a buggy or hostile policy can do is **refuse pairs the floor would
admit** — a visible, safe-direction loss of concurrency an operator notices at
once (`dos doctor` lists the active policy; `dos overlap-eval` quantifies its
safe-concurrency-forgone rate), never a collision. The `--force` operator
override remains the one and only thing that overrules a refusal, exactly as for
the disjointness refuse today.

**Why a floor and not just "trust the policy like a predicate?"** Because a
predicate can *only* refuse (the type has no force-admit). An `OverlapPolicy`,
by contrast, returns a *verdict that includes admit* — it is replacing the
baseline scorer, not adding a refuse-only voice. The moment "admit" is
expressible, the type alone no longer guarantees the safe direction. The
deterministic floor restores the guarantee structurally: admit is the **AND** of
the plugin's admit and the kernel's own unforgeable admit, so the plugin's admit
is necessary-but-not-sufficient. This is precisely the
[`76`](76_flexible-goals-and-verification.md) design law — *flexibility lives in
which-signals and provenance, never in the adjudication's safe direction* —
applied to admission: a researcher gets to change *what counts as overlap* (the
signal), but cannot change *which way the verdict fails* (the adjudication).

This also honors `90 §1`'s hard soundness floor verbatim — *"a more precise
predicate may only remove false refusals; if it ever admits a pair that can
corrupt shared state, it has broken the arbiter"* — except we get it for free:
the floor makes "admits a true [prefix] conflict" unreachable rather than
relying on the plugin author to preserve it. (Nuance: the floor is the *prefix*
lower bound, so a policy that wants to admit a pair the prefix rule over-refuses
— `90 §1`'s `agents/apply_*.py` vs `agents/apply_steps/…` false-conflict — is
the legitimate `90 §1` precision goal and is **not** served by AND-ing in the
prefix floor, which would re-refuse it. That case is handled separately in §3.1.)

### 3.1 The precision direction — removing a false refusal needs a different floor

`90 §1` wants the *opposite* move from `90 §2`: not "refuse more" but "stop
over-refusing genuinely-disjoint globs." AND-ing the prefix floor in (§3) blocks
that, because the prefix floor is the very thing producing the false refusal.

The resolution keeps soundness without freezing precision: the floor that is
ANDed in is the **decidable soundness lower bound**, and the prefix rule is only
*one* such bound. A more precise pure predicate (true glob-set intersection — see
[`92`](92_predicate-precision-plan.md)) is *also* a sound lower bound, and a
**stricter** one (it refuses a subset of what prefixes refuse, never a superset).
So a precision policy attaches by **declaring which sound floor it stands on**:

- Default floor = `PrefixOverlapPolicy` (today).
- A policy may opt into `GlobIntersectionFloor` (docs/92, when built) — a
  *provably-stricter* decidable bound — as its floor. The kernel still AND-s a
  floor in; it is just a tighter one the policy proved sound.

A policy may **never** run with *no* floor, and may never nominate a floor that
is not a kernel-provided, proven-sound lower bound. So precision (`90 §1`) and
tolerance (`90 §2`) are both reachable, and neither can reach "admit a true
conflict" — the soundness floor is *a* sound bound, selectable among the kernel's
proven set, never absent and never plugin-authored. (Phase 1 ships only the
prefix floor; the glob-intersection floor lands with docs/92. Until then a
precision policy that needs sub-prefix admits is `--force`-only, the honest
current state.)

## 4. The instrument — `dos overlap-eval` (the friendliness lever)

The chosen north star (the AskUserQuestion answer): **an eval harness per axis is
what turns DOS from "a thing you adopt" into "a thing you do research *on*."**
`dos judge-eval` proved the pattern; this is its admission twin, and the direct
realization of `90 §2`'s "backtest study."

Input: a labelled corpus of concurrent-pair outcomes, one per line —

```jsonl
# overlap-cases.jsonl — ground truth is whether running these two trees
# concurrently ACTUALLY corrupted shared state / produced a merge conflict.
# (truth from artifacts — git merge result, a detonation log — NEVER from a policy.)
{"tree_a": ["agents/apply_*.py"], "tree_b": ["agents/apply_steps/h.py"], "collided": false}
{"tree_a": ["src/api/**"],        "tree_b": ["src/api/routes.py"],       "collided": true}
```

Output: the confusion grid + two rates that are the exact pair `90 §2` asks to
score on —

- **false-admit rate** — of the pairs the policy *admitted*, the fraction that
  actually `collided`. This is the dangerous cell (the admission analogue of the
  judge's false-clear): a non-empty cell means the policy admitted a real
  collision. **Exit code is the verdict:** `0` if this cell is empty, `1` if not,
  so a CI gate fails on any leak. (Note: against the *prefix floor* this cell is
  always empty for prefix-colliding pairs by §3; it becomes informative for a
  policy whose admit set extends past the prefix floor under a stricter floor,
  §3.1 — i.e. exactly where a precision policy could go wrong.)
- **safe-concurrency-forgone rate** — of the pairs that did *not* collide, the
  fraction the policy *refused*. This is `90 §2`'s "safe concurrency forgone" and
  the cost a stricter policy pays; it is the *safe-direction* failure, so it is
  the exit-code-`0` quality knob, not a gate.

And, for the system picture (mirroring `judge_eval.compose_deterministic_first`),
an **economic line** honoring `90 §2`'s economic floor: the right scalar is never
admit-rate but **verified-velocity-per-$** ([`81`](81_velocity-economics-and-the-fleet-benchmark.md))
— a looser threshold that raises throughput must be charged the *loaded*
merge-conflict cost, not the raw one. `dos overlap-eval` reports
admit-rate *and* the detonation cost it bought, so a researcher optimizes the
loaded metric, not the seductive raw one.

```bash
dos overlap-eval --policy prefix       --cases overlap-cases.jsonl          # baseline (the 1/3 ratio)
dos overlap-eval --policy import-graph --cases overlap-cases.jsonl --json   # your plugin, machine-readable
```

This is what makes the `1/3` constant *falsifiable*. Today it is a number two
data points justified; with the harness it is a number a researcher can **beat
on a corpus, with evidence** — and the kernel ships the scoreboard, not just the
field.

## 5. Attachment — the three implementations, on the existing layer cake

The user's framing ("a model or a driver or other implementations") maps exactly
onto DOS's three attachment models (`HACKING.md`), at three points on the
flexibility geometry:

| Implementation | Attaches via | Purity | Precedent |
|---|---|---|---|
| **Data** — a different ratio, a size-weight, a small-file allowlist | `dos.toml [overlap]` | pure (kernel reads a number) | `[stamp]`, `[reasons]` |
| **Pure policy** — AST/import-graph disjointness, glob-set intersection | a `dos.overlap_policies` entry-point plugin | pure (no I/O in the verdict) | `BudgetGuard` (`dos.predicates`) |
| **A model** — learned / embedding similarity scorer | a **driver** (`dos.drivers.*`) | I/O *inside* the verdict allowed | `LlmJudge` — *this exact pattern for the JUDGE rung* |

The key unification: **a "model that scores overlap" is the JUDGE pattern applied
to admission instead of verification.** The kernel already knows how to make a
non-deterministic adjudicator safe (the four judge disciplines); for admission
the load-bearing one is fail-closed-toward-refuse, which §3's floor enforces
structurally. So this seam is not a new safety regime — it is the judge seam's
safety, re-aimed at the admit verdict, with a deterministic floor doing the job
fail-to-ABSTAIN does for judges.

```toml
# dos.toml — data attachment (the floor stays the prefix rule; only the
# scalar/shape the default policy uses changes)
[overlap]
ratio_max = 0.25          # override the 1/3 elbow (still ANDed under the prefix floor)
# size_weighted = true    # (roadmap) weight overlap by claim size, 90 §2

# pyproject.toml — code attachment (a stricter scorer; pure → entry-point,
# model-backed → a driver the kernel points to but never imports)
[project.entry-points."dos.overlap_policies"]
import-graph = "your_plugin.overlap:ImportGraphPolicy"
```

`pip install your_plugin`; `dos doctor` lists it under **overlap policy**; nothing
in the `dos` package changes — the one-way arrow every other axis obeys.

## 6. Why this is the right "friendly to all researchers" move

Three reasons, in priority order:

1. **It opens the axis where researchers most legitimately disagree.** Reasons,
   renderers, and even judges are *adopt-and-go* surfaces. Disjointness is where a
   monorepo team (import-graph), an ML team (feature-table writes, paths
   irrelevant), and a prose fleet (section-level locks in one file) have *genuinely
   different ground truth* about what "overlap" means. Freezing the `1/3` ratio in
   the mechanism layer implicitly assumes a file-path-shaped, code-shaped world.
   The seam un-assumes it without widening the kernel.

2. **It ships a number, not just a hook.** The eval-harness-per-axis principle:
   the strongest pull for a researcher is not "you *can* plug in" but "you can
   *measure* whether yours is better, and the kernel ships the scoreboard." `dos
   judge-eval` already does this for one axis; `dos overlap-eval` extends it to the
   most consequential one. The roadmap this opens (§7) is to give *every* open
   seam its eval.

3. **It pays a debt the kernel already booked.** `90 §1`/`§2` flagged precisely
   this scalar as a deliberate stand-in for a research problem and named the
   answer-shape. Building it is not scope creep; it is closing an
   already-documented open area with the exact object that doc specified —
   strengthening the "the kernel deliberately shipped the simple correct version
   first, and named where the better one goes" story that makes DOS legible to a
   paper.

## 7. The broader arc — an eval per axis

`dos overlap-eval` is the second instrument (after `dos judge-eval`). The
friendliness thesis generalizes: **every open seam should ship the instrument
that scores a contribution to it.** The candidates, each grounded in an existing
open-research section:

- **`dos predicate-eval`** — false-conflict rate + admission-hot-path cost for an
  admission predicate (`90 §1`'s two numbers, exactly).
- **`dos pick-eval`** — auto-pick competitive ratio + starvation/fairness +
  verified-throughput-per-$ for a `rank_key` / pick policy (`90 §3`).
- **`dos liveness-eval`** — false-STALLED vs missed-hang for a liveness window
  policy against a labelled corpus of runs that did/didn't hang (`90 §5`).

Each is the same shape: a labelled corpus, a confusion grid, a dangerous-cell
rate that is the exit code, and a safe-direction quality knob. The seam makes a
verdict *swappable*; the eval makes the swap *evaluable*. Shipping both for an
axis is what invites a researcher to do work *on* DOS rather than merely *with*
it — and is the cheapest durable widening of who finds the substrate relevant.

---

## Build order (Phase 1, this note's scope)

1. `OverlapPolicy` protocol + `PrefixOverlapPolicy` (byte-for-byte default) +
   `resolve_overlap_policy` + `dos.overlap_policies` discovery + the **prefix
   floor AND** in `DisjointnessPredicate`. Pure; resolved at the call boundary.
2. `dos.toml [overlap]` data table (`ratio_max`), folded onto the base like
   `[stamp]`.
3. `dos overlap-eval` (the instrument) + `dos doctor` lists the active policy.
4. A copy-me `ImportGraphPolicy`-shaped example in `examples/dos_ext/`.
5. **Adversarial review of §3's floor** (a security-load-bearing build — prove no
   policy can admit past the floor) + full suite green + `HACKING.md` Axis-7 row.

Out of scope (named, not built): the `GlobIntersectionFloor` (§3.1, lands with
docs/92), size/risk-weighted default shapes (`90 §2` candidates — data seam
reserved), and the other three evals in §7.
