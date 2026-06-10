# 273 — Property-based testing: pinning the kernel's invariants, not its examples

> **The kernel is a pile of pure `classify(evidence, policy) -> verdict` functions
> with strong algebraic laws. Example tests pin a finite set of points on each
> law; a property test pins the law.**

## Status

> **Status:** Phase 1 SHIPPED — `hypothesis` added as a dev dep; **eight**
> `tests/test_prop_*.py` modules (44 property tests) pin the load-bearing invariants
> of the purest kernel verdicts (efficiency, productivity, breaker, the overlap
> soundness floor, reward non-forgeability, the tree disjointness algebra, the
> reconcile fail-closed-on-the-claim law, and the cooldown anti-churn fold). Each
> property is sourced from a law already written in the module's own docstring, so
> the test *checks the claim the code makes about itself* across thousands of
> generated inputs instead of a handful of hand-picked ones. Both security cores (the
> overlap floor; reward non-forgeability) were **proved out** — injecting the
> regression each guards makes the property fail and shrink to the minimal
> reproducer; the same prove-out was done for reconcile (a claim closing an unshipped
> unit) and cooldown (a unit-filter leak).

## Why this, why now

The job repo (the reference userland app) already runs **33 files** of
property-based tests under a `tests/test_invariants_*.py` family — symmetry,
reflexivity, idempotence, forward-only monotonicity, bounded counters. DOS, the
substrate those tests' subject was lifted from, had **zero**. That is backwards:
DOS is the *better* target. Its whole design rule is

> every verdict is a PURE `classify(evidence, policy)`; I/O is gathered at the CLI
> boundary, never inside the verdict

(CLAUDE.md, layer 1). A pure total function over a typed input domain is the
textbook shape for property-based testing — no fixtures to stand up, no I/O to
mock, no clock to freeze. And every one of these functions already *states its
laws in prose* in its own docstring. Those prose laws are exactly what an
example-based test under-pins: `test_efficiency.py` checks that `work=0,
tokens=2000 -> WASTEFUL`; it does **not** check that *for all* `tokens >=
min_tokens`, `work=0 -> WASTEFUL`. The first is a point; the second is the law the
docstring actually claims. Property testing closes that gap.

This matters more for DOS than for an ordinary library because DOS's laws are
**safety properties**, not conveniences. "A swappable overlap scorer can only
refuse-MORE, never admit a collision" and "a forgeable read-back can never
manufacture an ACCEPT" are the security core (the litmus tests in CLAUDE.md). A
safety property is precisely a `∀`-claim — "there is *no* input for which the bad
thing happens" — and the only test shape that goes after a `∀`-claim by trying to
break it is a property test with a generator aimed at the adversarial corner. An
example test that picks three hostile inputs proves three points; Hypothesis tries
hundreds and *shrinks* any counterexample to the minimal reproducer.

## The pattern (lifted from the job repo, kept identical)

```python
import pytest
hypothesis = pytest.importorskip("hypothesis")          # degrade if dep absent
from hypothesis import given, settings, strategies as st

@given(work=st.integers(0, 10**6), tokens=st.integers(0, 10**7))
@settings(max_examples=300, deadline=None)
def test_more_work_never_worsens_the_verdict(work, tokens):
    ...
```

- `pytest.importorskip("hypothesis")` — the suite must stay green for a contributor
  who ran a bare `pip install -e .` without `[dev]`. (`hypothesis` is in `[dev]`,
  beside `pytest`/`ruff`/`mypy` — it is test-time only and never touches the
  near-stdlib kernel dependency set, the same discipline as every other extra.)
- `deadline=None` — these are pure functions, but a cold-import first example on a
  loaded machine can trip Hypothesis's default per-example deadline; the verdicts
  have no time component to measure, so the deadline is noise.
- One file per *cohesion target*, named `test_prop_<module>.py`, sitting beside the
  existing `test_<module>.py` example suite. The example suite pins the named
  cases + the CLI/JSON surface; the property suite pins the algebra. They are
  complementary, not a replacement — a property test that says "monotone" still
  wants an example test that says "this exact input → WASTEFUL with this reason
  string."

## The invariant catalog (what each module *claims*, now *checked* ∀)

The properties are not invented; each is quoted from the module's own docstring or
the CLAUDE.md litmus row, so the test verifies the code against the claim the code
makes about itself.

### `efficiency.classify` — `test_prop_efficiency.py`
- **Monotone in work** (fixed tokens): raising `work` never moves the verdict to a
  *worse* tier (WASTEFUL→COSTLY→EFFICIENT is the order). Source: the ratio ladder
  in the docstring.
- **Monotone in tokens** (fixed nonzero work): raising `tokens` never moves the
  verdict to a *better* tier. Same ratio, inverted.
- **Floor=0.0 ⟹ COSTLY is unreachable** — only WASTEFUL / EFFICIENT. The
  "default floor disabled" claim, the one that stops a unit mismatch manufacturing
  a false COSTLY (docs/263; docs/235 slice-must-have-power).
- **WASTEFUL ⟺ `tokens >= min_tokens AND work == 0`** — the unit-independent,
  always-free half of the verdict, as an iff over the whole domain.
- **Total + closed** — `classify` always returns one of the three enum members and
  never raises on any non-negative `(work, tokens)`.

### `productivity.classify` — `test_prop_productivity.py`
- **Young-and-alive guard** — fewer than `min_steps` deltas ⟹ PRODUCTIVE, *for
  any* delta values. The "withhold the accusation" claim.
- **DIMINISHING needs both recent steps low** — if either of the last two deltas
  clears the floor, the verdict is not DIMINISHING. The `lastDelta AND priorDelta`
  conjunction lifted from CC's `isDiminishing`.
- **Prefix-invariance of the tail** — appending the same final two deltas to two
  different long histories yields the same verdict (the verdict reads only
  `deltas[-1]`/`deltas[-2]` past the length gate). Catches a regression that starts
  reading the whole list.
- **Total + closed** over any non-negative delta tuple.

### `breaker` (record_failure / record_success / classify) — `test_prop_breaker.py`
This is the *stateful* one — a two-counter machine with explicit transition laws,
the classic Hypothesis `RuleBasedStateMachine` target.
- **`consecutive` monotone within a failure run; reset to 0 by any success** —
  `record_success` zeroes consecutive; `record_failure` increments it.
- **`total` never decreases** — neither success nor failure ever lowers it (the
  flapping-detector invariant: a success must not erase cumulative history).
- **OPEN latches under `total`** — once `total >= max_total`, no sequence of
  successes can return the verdict to CLOSED (a path that failed 20× is unreliable
  forever). Contrast: a *consecutive*-only trip CAN be healed by a success.
- **Trips on EITHER rung** — OPEN ⟺ `consecutive >= max_consecutive OR total >=
  max_total` (with disabled rungs excluded), checked as an iff against a recomputed
  oracle over random count pairs.
- **`record_failure` is replay-deterministic** — same start counts + same policy ⟹
  same transition (purity).

### `overlap_policy.admissible_under_floor` — `test_prop_overlap_soundness.py`
**The security core.** The CLAUDE.md litmus: *a swappable overlap scorer can only
refuse-MORE, never admit a collision.*
- **No policy admits past the floor** — for *any* `OverlapPolicy` drawn from a
  family of adversarial scorers (always-admit, over-ratio, raises, returns garbage,
  returns a foreign type) and *any* pair of generated trees,
  `admissible_under_floor(...).admissible` implies `floor_decision(...).admissible`.
  i.e. `net_admit ⟹ floor_admit`. The dangerous cell is structurally unreachable.
- **A stricter policy can refuse what the floor admits** — the safe direction is
  *reachable* (so the AND is real, not vacuous): an always-refuse policy turns a
  floor-admit into a refuse.
- **`prefix` policy under the floor == bare `overlap_verdict`** — the
  behavior-preserving litmus, as a property over generated tree pairs (the default
  path must not have drifted).
- **`overlap_verdict` is exact-glob symmetric** — identical glob on both sides ⟹
  REFUSE_EXACT_GLOB regardless of direction (the asymmetry-kills-wedge fix, ∀).

### `reward.admit` — `test_prop_reward_nonforgeability.py`
**The other security core.** The CLAUDE.md / docs/234 non-distillability claim: *a
forgeable read-back can never manufacture an ACCEPT; the verdict is invariant under
arbitrary narrated text.*
- **Narration-invariance** — for fixed `readbacks` and fixed `claim_present`, the
  verdict is identical under *any* generated `narrated` string. The agent cannot
  write its way to ACCEPT.
- **Forgeable floor never grants ACCEPT** — if every read-back is `AGENT_AUTHORED`
  (the forgeable floor), `admit` never returns ACCEPT, *whatever* their stance
  (even all-ATTESTED). It ABSTAINs.
- **ACCEPT ⟹ a non-forgeable ATTESTED witness existed** — over random witness
  populations, the accept bit implies at least one `OS_RECORDED`/`THIRD_PARTY`
  read-back with stance ATTESTED. The contrapositive of the floor rule.
- **`claim_present=False ⟹ NO_CLAIM`** regardless of read-backs; **REJECT_POISON ⟹
  a non-forgeable witness REFUTED**.

### `_tree` disjointness algebra — `test_prop_tree.py`
The path-prefix algebra under the overlap scorer.
- **`prefixes_collide` is symmetric** — `collide(a,b) == collide(b,a)` ∀ paths.
- **`prefixes_collide` is reflexive** — a normalized non-empty prefix collides with
  itself.
- **Disjointness is symmetric** — `lane_trees_disjoint(A,B) == lane_trees_disjoint(B,A)`.
- **A tree is never disjoint from itself** (when non-empty) — the self-overlap
  floor that makes `fleet=1` overwrite-prevention structurally 0 (docs/204 §1).

### `reconcile.reconcile` — `test_prop_reconcile.py`
The kernel's "don't believe the agents" thesis in one pure function (docs/168 §3):
the agent's `claimed_done` *never* closes a unit; only the oracle's git verdict does.
- **VERIFIED ⟺ `oracle_shipped`** — closure is a function of the ORACLE alone, ∀;
  the claim is irrelevant to whether the unit leaves the residual.
- **The claim cannot close an unshipped unit** (the safety law) — with
  `oracle_shipped=False` the verdict is *never* VERIFIED whatever the agent claims; a
  true claim → QUIET_INCOMPLETE *with a flag* (loud, never a silent drop), an honest
  non-claim → HONEST_OPEN *unflagged*.
- **The full 2×2 truth table** as an exhaustive property, inputs echoed back.

### `cooldown.cooldown_verdict` — `test_prop_cooldown.py`
The cross-run memory that breaks the re-pick storm — a PURE, fail-open fold over
`OP_ATTEMPT` records (a cooldown is a HINT, so the safe direction is always
re-pickable). docs/207 §3b.
- **Unit isolation** — the verdict for a unit depends ONLY on that unit's records;
  adding any number of *other* units' attempts never changes it. (A missing
  unit-filter would falsely hold an un-attempted unit on another's churn.)
- **Time-window boundary** — `RECENTLY_ATTEMPTED ⟺ now_ms < wall` where
  `wall = last_attempt + window(outcome)`; strict `<`, so a far-past `now` is always
  CLEAR.
- **Recency determines** — only the most recent attempt's wall matters, so the
  verdict is invariant under the history's order.
- **SHIPPED pre-screen** — a SHIPPED most-recent attempt is always CLEAR (the unit
  moved; cooldown moot), regardless of timing.
- **Fail-open** — empty / all-garbage history → CLEAR; never raises (observability,
  not a correctness gate).

## What this is NOT

- **Not a replacement for the example suites.** Properties pin laws; examples pin
  the named regressions, the reason strings, and the CLI/JSON surface. Both stay.
- **Not a new kernel module.** This is test-tier only (`tests/` + a `[dev]` dep). It
  imports `dos`; nothing under `src/dos/` imports it — the one-way arrow, like the
  release scripts and the MCP server.
- **Not fuzzing for crashes.** The generators are typed to the verdict's *valid*
  input domain (non-negative counts, well-formed trees). The point is to falsify a
  stated *law*, not to feed garbage past `__post_init__`. (The "policy returns
  garbage" generator in the soundness suite is the one deliberate exception — there
  the law *is* "garbage degrades to the floor," so garbage is in-domain.)

## Dogfood check

Per CLAUDE.md "DOS on DOS": this work touches only `tests/` and `docs/` and
`pyproject.toml`'s `[dev]` extra — three disjoint top-level regions, none of them
`src/dos/`'s running path, so it is not a `SELF_MODIFY` / `global`-lane hazard. The
proof the properties hold is the suite going green; the proof *this doc* is honest
is `dos verify` reading it from git ancestry once committed, not this
`> **Status:**` sentence taken at its word.
