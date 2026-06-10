# The supervisor's derived-claim concurrency budget — a limit you declare once, not lane-by-lane

> **The supervisor capped the achievable worker population at the count of
> statically pre-declared, pairwise-disjoint *concurrent* lanes. A workspace that
> runs the DYNAMIC-CLAIM model — where a lane is a HANDLE whose disjointness is
> enforced PER-PICK at acquire time, not by a fixed tree (the reference userland
> app's `concurrent=[]`, `exclusive=["orchestration","global"]` roster) — could
> therefore never reach a target above 1, no matter the hardware, unless the
> operator hand-enumerated N disjoint trees in `dos.toml [lanes]` up front. That
> contradicts the very model the workspace declared. This note adds one knob —
> `[supervise] max_concurrency` — that lets the operator declare a single
> concurrency BUDGET and have the supervisor ride it on a fungible auto-pick
> handle, leaving the authoritative per-pick disjointness exactly where it already
> lives: each worker's own `arbitrate` at its Step 0.**

A spec note in the family of [`99`](99_runtime-validation-the-self-stop-seam.md)
(the supervisor / SUP axis) and [`89`](89_a-lane-is-a-region-lock.md) (a lane is a
region-lock over a glob-set). It closes a mismatch between two designs DOS already
ships: the supervisor's STATIC admissibility (this note's §1) and the userland
dynamic-claim lane model (§2).

## 1. The bug: static admissibility vs a dynamic-claim roster

`supervise._admissible` computes the largest set of CONCURRENT lanes whose trees
are pairwise disjoint (`_tree.lane_trees_disjoint`). For the generic default
roster (`main` + `global`, both `**/*`) that is correctly 1. But it has a blind
spot:

- A workspace may declare **no concurrent lanes at all** (`concurrent = []`) and
  only exclusive lanes. Then `_admissible` returns 1 (an exclusive worker runs
  alone) — and `dos loop --target 8` returns `TARGET_UNREACHABLE`, naming the
  "fix" as *declare more disjoint concurrent lanes in `dos.toml [lanes]`*.

That advice is **wrong for the dynamic-claim model.** In that model (dos/119 in the
reference app) the work lanes (`apply` / `tailor` / `discovery` / …) are not
curated trees — they are HANDLES that each resolve, at acquire time, to the narrow
real footprint of the top pickable plan matching the token. Concurrency is gated by
tree-disjointness **of the per-pick claims**, computed by the worker's own
`arbitrate`, NOT by any pre-declared tree. So the roster legitimately holds many
concurrent workers without enumerating that many disjoint trees — the exact thing
`_admissible` demands. The supervisor was telling the operator to abandon their
declared model and hand-curate trees instead.

## 2. The fix: a budget that rides a fungible handle

The mechanism stays kernel, the number is config — the same mechanism/policy split
as every `[supervise]` knob (`target`, `count_spinning_as_alive`, `reap_stalled`,
`spin_halt_after_ms`). The new knob:

```toml
[supervise]
max_concurrency = 8     # the derived-claim budget; default absent = off
```

Semantics (all PURE in `supervise.supervise`, evidence gathered at the CLI boundary):

- **`max_concurrency` absent (default `None`)** → admissible is the static
  disjoint-tree count, **byte-for-byte today's behaviour**. No silent change.
- **`max_concurrency = N` set AND the roster carries ≥1 REPEATABLE lane** → the
  admissible ceiling is lifted to `max(static, N)`. A *repeatable* lane is a
  fungible auto-pick handle (`LaneLiveness.repeatable=True`): it holds NO fixed
  region, so the supervisor may emit MORE THAN ONE spawn onto it (one per
  synthesised slot, up to the budget), and the spawn walk never region-locks it.
- **An exclusive lane still caps the population at 1.** An exclusive worker runs
  alone — a budget can never let a second worker join it. (`repeatable` and
  `is_exclusive` are mutually exclusive, enforced in `LaneLiveness.__post_init__`.)
- The budget **never** raises the ceiling above its own value and **never** weakens
  the disjointness the arbiter enforces. It only stops `_admissible` from refusing
  a target the operator has explicitly budgeted for.

The load-bearing trust move: **the supervisor budgets the SLOT COUNT; the arbiter
gates each per-pick CLAIM.** This is not new latitude — the module docstring's
"spawn soundness floor" already says the supervisor's pick is "an advisory hint,
but an honest one" and the worker's own `arbitrate` at Step 0 is "the
authoritative gate." A repeatable handle simply makes that explicit: the
supervisor does not pretend to know the per-pick footprint; it trusts the gate
that does.

## 3. The CLI boundary: synthesising the handle for a dynamic-claim roster

`dos loop` gains `--max-concurrency N` (overrides `[supervise].max_concurrency`
for one run, the same way `--target` overrides the target). The evidence-gather
(`_supervise_evidence`), when a budget is active:

1. Marks each declared `autopick` (non-exclusive) lane `repeatable` — those are the
   workspace's own fungible handles.
2. Folds every live lease on a non-roster, non-exclusive lane (the dynamic-claim
   per-pick handles real workers hold) into the roster as a repeatable HELD lane,
   so live workers are counted alive against the budget.
3. Synthesises ONE free repeatable auto-pick handle (named `auto`) so the budget
   has a lane to ride even from an empty fleet.

With no budget, none of this runs — the roster is the declared lanes only.

## 4. Worked result (the reference job workspace)

```
$ dos loop --target 8 --json                     # no budget — the status quo
  verdict: TARGET_UNREACHABLE  admissible: 1  spawn: 1

$ dos loop --target 8 --max-concurrency 8 --json # one number, not 8 trees
  verdict: FILLING  admissible: 8  spawn: 8   (8× /dos-dispatch-loop --lane auto)
```

The operator declared a single concurrency limit and the supervisor reached it,
without abandoning the dynamic-claim lane model or pre-enumerating disjoint trees.

## 5. What this deliberately does NOT do

- **It does not weaken admission.** Each spawned worker still takes its own lane
  lease via `arbitrate` at Step 0; if two picks would collide, the arbiter refuses
  one — exactly as today. A budget of 8 is a *ceiling on slots offered*, never a
  guarantee 8 disjoint picks exist.
- **It does not auto-discover a "right" number.** `max_concurrency` is an operator
  budget, not a derived hardware probe. (A future note could derive a default from
  the RAM/slot pool the userland app already measures; that is a driver concern,
  out of this kernel knob's scope — the kernel takes the number, it does not guess
  it.)
- **It does not make exclusive lanes parallel.** Exclusivity is untouched; an
  exclusive lease still caps the whole population at 1.
