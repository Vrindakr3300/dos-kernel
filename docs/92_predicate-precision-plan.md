# Predicate precision — a plan note (research area §1 → specced)

> **The kernel's claim-conflict test (`_tree.prefixes_collide`) is a deliberate
> *over*-approximation: it truncates a glob at its first `*` and so refuses some
> genuinely-disjoint pairs. This note specs the *more precise* predicate named in
> [`90_open-research-areas.md`](90_open-research-areas.md) §1 — and, unlike the
> value-aware picker ([`91`](91_value-aware-picker-plan.md)), it carries a sharp
> warning: this change is NOT sound-by-construction. It edits the single most
> load-bearing function in the kernel, the one every collision check stands on.
> Ship it only behind the adversarial pass §4 describes.**

A phased plan in the form of [`70`](70_stamp-convention-plan.md)–[`73`](73_admission-predicate-plan.md)
/ [`82`](82_liveness-oracle-plan.md) / [`91`](91_value-aware-picker-plan.md):
small, separately-testable slices. **Directional** — not yet in the
[`next-stage-plan`](next-stage-plan.md) table. It is the deepest of the open areas
because the same predicate, generalized to a non-path algebra, *is* the
capability-lattice.

One-line thesis: **a more precise conflict predicate is a drop-in at one pure seam
that can only REMOVE false refusals — but "can only remove false refusals" is a
property you must *prove*, not assume, because the failure mode is admitting a
real collision, and that corrupts shared state.**

---

## 0. What exists today (verified against the live code)

The kernel decides "can these two claims touch the same file?" with a path-prefix
nesting test, shared verbatim by every collision check so they cannot drift
(`_tree.prefixes_collide`, `_tree.py:41`; used by `lane_trees_disjoint`,
`lane_overlap`, and the self-modify guard):

- `norm_tree_prefix(p)` (`_tree.py:20`) truncates a glob at its **first `*`**:
  `agents/apply_*.py` → `agents/apply_`; a literal path keeps its full self
  (`src/foo.py` → `src/foo.py`); a leading glob (`**/*`, `*.py`) → the empty
  *universal* prefix `""`.
- `prefixes_collide(a, b)` → `a.startswith(b) or b.startswith(a)`.

**The over-approximation, made concrete (run against the code, not hypothesized):**

| Claim A | Claim B | Today | Truth | |
|---|---|---|---|---|
| `agents/apply_*.py` | `agents/apply_steps/helper.py` | **collide** | disjoint | `*` doesn't cross `/`; truncation to `agents/apply_` loses that — **FALSE CONFLICT** |
| `src/foo_*.py` | `src/foo_bar/baz.py` | **collide** | disjoint | same artifact — a flat-glob refused against a nested file |
| `src/foo_*.py` | `src/foo_bar.py` | collide | collide | `foo_*.py` *does* match `foo_bar.py` — correct |
| `src/api/` | `src/api/server.py` | collide | collide | dir prefix — correct |
| `src/api/` | `src/worker/` | disjoint | disjoint | correct |
| `src/foo.py` | `src/foo_helpers.py` | disjoint | disjoint | literal paths don't truncate — **already correct** (not the bug) |

So the imprecision is specifically a **glob-truncation artifact**: dropping the
post-`*` suffix and the no-cross-`/` semantics turns a narrow flat-glob into a
broad directory prefix. Two refinements recover most of it:

1. **`*` does not cross `/`.** `apply_*.py` matches `apply_one.py`, never
   `apply_steps/helper.py`.
2. **Keep the post-`*` suffix.** `*.py` vs `*.md` are disjoint; today both
   truncate to `""` (or a shared dir prefix) and may collide.

---

## 1. The soundness floor (sharper here than anywhere else)

> **A more precise predicate may only turn `collide → disjoint` for pairs that are
> *genuinely* disjoint. It may NEVER turn `collide → disjoint` for a pair that can
> touch the same file.** A false *conflict* (today's behavior) costs *forgone
> concurrency* — safe, just slow. A false *disjoint* (the failure mode of getting
> precision wrong) costs *admitting two writers to the same bytes* — the exact
> corruption the arbiter exists to prevent. **The asymmetry is total: stay
> conservative when unsure.**

Two structural consequences:

- **The empty / leading-glob corner is sacred.** `_tree.py:52` documents a *fixed
  bug*: `**/*` normalizes to `""` and must collide with *everything*. Any rewrite
  must preserve that — a more precise matcher that regresses a whole-repo glob to
  "matches nothing" reintroduces the two-agents-over-the-whole-repo hole the
  current code closed (pinned by `TestWholeRepoTreeCollision` in
  `tests/test_arbiter.py`). This is the first place a precision change goes wrong.
- **Unknown-shape inputs stay collide.** If a tree entry is something the matcher
  can't confidently decide (an exotic glob, a brace expansion, a `**` in the
  middle), it must fall back to **collide**, never disjoint — the conservative
  default, same spirit as `lane_trees_disjoint` treating an empty tree as *not*
  disjoint (`_tree.py:63`).

This is why §1 was ranked *second* in [`90`](90_open-research-areas.md) (deepest,
sharp floor) and §3 *first* (sound-by-construction): there is no structural trick
that makes a precision change safe. The safety has to be *earned* by tests.

---

## 2. Phases

### Phase 1 — a precise, conservative glob-intersection predicate (kernel)

Add `globs_can_overlap(a: str, b: str) -> bool` to `_tree.py`: **True iff some
concrete path could match both globs.** Decidable for the glob vocabulary the
kernel actually sees (`*`, `?`, literal segments, a leading/trailing `**`); for
anything outside that vocabulary it returns **True** (conservative fallback).

- Segment-wise matching: split both on `/`, compare segment-by-segment, where a
  segment-glob like `apply_*` is matched against a literal segment with
  `fnmatch`-style semantics, and `*` is confined to one segment (the no-cross-`/`
  fix). Differing segment counts with no `**` ⇒ cannot overlap ⇒ disjoint.
- Preserve the suffix: `*.py` vs `*.md` differ in the final segment's literal
  tail ⇒ disjoint.
- `**` (if/where supported) spans segments ⇒ widen conservatively.

This is a *pure* function with the exact signature shape of `prefixes_collide`, so
it can be unit-tested in total isolation before it is wired into anything.

**Tests (this phase ships ONLY the function + its table):** every row of the §0
table; the suffix cases (`*.py`/`*.md`); the `**/*`-collides-with-everything
invariant; exotic-glob ⇒ conservative True; symmetry (`f(a,b) == f(b,a)`); and a
**differential** test that asserts the new function is a strict *subset* of the old
one's collisions on a generated corpus — i.e. it only ever *removes* collisions,
never adds.

> **Caveat — the differential test is necessary, not sufficient.** "Subset of the
> old collisions" proves the new predicate never refuses *more* than today; it does
> NOT prove the collisions it *dropped* were genuinely disjoint. That requires the
> materialized-path oracle of §4 (for every dropped pair, check no concrete path
> matches both). So even this "safe" Phase-1 function is only *trustworthy* once the
> §4 oracle runs against its `disjoint` verdicts — do not ship it as correct on the
> differential test alone. This is the concrete reason Phase 1 is specced here but
> deliberately **not** landed in the same breath as the function's first draft (the
> contrast with [`91`](91_value-aware-picker-plan.md)'s sound-by-construction P1,
> which *was* landed immediately).

### Phase 2 — wire it behind the existing seam, default OFF (kernel)

`prefixes_collide` is called by three things (`lane_trees_disjoint`,
`lane_overlap._shared_count`, the self-modify guard). Do **not** swap the
definition. Instead make precision **opt-in**:

- Route the collision check through a single indirection that defaults to the
  *current* `prefixes_collide` and can be switched to `globs_can_overlap` by a
  config flag (a `dos.toml [lanes] precise_overlap = true`, read back through
  `SubstrateConfig` the same way `[liveness]` windows are).
- Default OFF ⇒ the entire existing suite is byte-identical (the regression guard,
  exactly as `rank_key=None` was for §3). A workspace opts in to the precision.

**Why opt-in and not a swap:** this function underpins the self-modify guard and
the whole-repo collision fix. A silent precision change that regressed either is a
*security*-adjacent failure (two agents editing the kernel, or the whole repo). Gating
it behind a flag means the conservative default ships forever and precision is a
*choice* a workspace makes with its eyes open — and it gives the differential
corpus (Phase 1) and the adversarial pass (§4) a clean A/B.

### Phase 3 — measure the precision win (benchmark)

Reuse `benchmark/fleet_horizon`: the win is **more admitted concurrency at equal
safety**. With `precise_overlap` on, flat-glob lanes that today false-collide
become concurrent, so (under a budget cap — the same Phase-3 lever
[`91`](91_value-aware-picker-plan.md) had to add) more verified work lands per
dollar with **zero** new silent overwrites. The headline is *forgone-concurrency
recovered*, and the falsifier is built in: on a workload of purely
directory-granular lanes (no flat globs) the precise and conservative predicates
agree exactly and the gap is zero.

### Phase 4 — the adversarial pass (the gate, not optional)

Because this is not sound-by-construction, it does not ship on a green unit suite
alone. Before `precise_overlap` is documented as safe:

- An **adversarial search** for a false-disjoint: generate glob pairs (fuzzing
  segment counts, `*`/`?`/`**` placements, trailing slashes, dotfiles, case) and,
  for each pair the new predicate calls *disjoint*, **materialize candidate paths
  and check no concrete path matches both** (an oracle independent of the predicate
  under test). Any hit is a soundness break and blocks the phase.
- Cross-check against the three real callers: a corpus replay proving
  `lane_trees_disjoint`, `lane_overlap`, and the self-modify guard each get *no new
  admission* they shouldn't — especially the self-modify guard against the kernel's
  own `src/dos/**` tree.

Only after that pass does §2's flag get a green light in the docs.

---

## 3. Deliverables, by layer

| Layer | Deliverable | Litmus |
|---|---|---|
| **Kernel** (`_tree.py`) | `globs_can_overlap` (pure, conservative-on-unknown); a seam indirection; `[lanes] precise_overlap` flag | default OFF ⇒ suite byte-identical; new fn is a strict *subset* of old collisions (differential test); `**/*` still collides with everything |
| **Benchmark** | precise-vs-conservative A/B under a budget cap | forgone-concurrency-recovered headline + zero new overwrites + the no-flat-glob falsifier |
| **Verification** | the §4 adversarial false-disjoint search + 3-caller corpus replay | **gates** the "safe" claim; no false-disjoint may exist in the searched space |

---

## 4. Why this is *not* the one to do first (honest ordering)

[`90`](90_open-research-areas.md) ranks this second behind the picker, and this
note is the reason why, stated plainly:

- **No structural safety.** §3's picker could only reorder already-admitted lanes,
  so the worst case was a suboptimal-but-safe pick. Here the worst case is a
  corrupted repo. The safety must be *proven* (Phase 4), which is real work beyond
  the ~one-file kernel change.
- **It touches the blast-radius core.** `prefixes_collide` feeds the self-modify
  guard and the whole-repo collision fix — two of the kernel's load-bearing safety
  properties. That is exactly why Phase 2 is opt-in behind a flag rather than a
  swap.
- **But it is the deepest payoff.** It is the highest-precision lever (every
  collision check sharpens at once) *and* the prototype for the capability-lattice:
  get the path-glob algebra right behind a clean seam, and the lattice is
  "the same indirection over a richer algebra," not a new arbiter.

The build order that respects all of the above: **Phase 1 (the pure function +
differential test) is the safe, high-value slice to land first** — it adds a tested
capability and changes no behavior. Phases 2–4 (wire-behind-flag, measure, and the
adversarial gate) are where the care goes, and they ship together or not at all.

---

## See also

- [`90_open-research-areas.md`](90_open-research-areas.md) §1 — the area this
  specs; the §0 table here is the verified version of §1's example.
- [`89_the-lane-is-a-region-lock.md`](89_the-lane-is-a-region-lock.md) §3 — the
  predicate IS the lock-compatibility test; precision = a sharper compatibility
  function (the same framing that made §2's threshold a tunable, not a fudge).
- [`91_value-aware-picker-plan.md`](91_value-aware-picker-plan.md) — the sibling
  plan; contrast the soundness story (that one sound-by-construction, this one
  proven-by-adversarial-pass) and the shared budget-cap benchmark lever.
- `src/dos/_tree.py` (`norm_tree_prefix`, `prefixes_collide`),
  `tests/test_arbiter.py::TestWholeRepoTreeCollision` — the surface and the
  invariant any precision change must not regress.
