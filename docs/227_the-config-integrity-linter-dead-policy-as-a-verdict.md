# 227 — The config-integrity linter: dead policy as a verdict

> **G1 from the docs/189 Claude Code audit, built and consolidated.** Claude Code
> ships `shadowedRuleDetection.ts` (`detectUnreachableRules`): a static check that
> finds a permission *allow* rule made **unreachable** — dead code — by a more
> general *deny*/*ask* rule that precedes it. The docs/189 audit flagged this
> "genuinely new, small, and squarely in DOS's self-describing-registry ethos,"
> and verified DOS has no equivalent for its own registries. This doc is the lift.

## 0. The one-sentence version

A workspace declares its policy as **data** — the lane taxonomy and the reason
vocabulary in `dos.toml`. Data can be **internally inconsistent** in ways that are
*structurally detectable* without running anything: a lane that can never be
arbitrated, a lane that is both "runs in parallel" and "runs alone," a reference
to a lane that was never declared, a lane whose region is wholly **swallowed** by
another's. Each of these is **dead policy** — a declaration that looks active but
can never fire. The linter is the pure verdict that finds them, the
`detectUnreachableRules` analogue aimed at *DOS's* registries instead of CC's
permission rules.

## 1. Why this is a kernel verdict, not a CLI helper

The check is **byte-clean by construction**: its only input is the config the
operator authored (`LaneTaxonomy` + `ReasonRegistry`), never an agent's narration
and never the live world. It is a pure function — registry-in, findings-out — with
no I/O, no clock, no plan. That is the exact shape of every other kernel verdict
(`liveness.classify`, `productivity.classify`, `gate_classify`,
`overlap_eval`): **the I/O is gathered at the CLI boundary, the judgment lives in
a pure leaf** (the malloc-property the whole layering rests on). So it belongs in
`src/dos/`, tested on frozen fixtures, away from anything that needs a live
workspace to reproduce.

It also **consolidates logic that drifted into the CLI shell**. Today the partial
checks are scattered:

| Check | Where it lives today | Problem |
|---|---|---|
| lane declared but no tree | `cli.py::_treeless_lane_findings` (inline) | logic in the CLI shell, no leaf, untested in isolation |
| overlapping concurrent lanes | `supervise.py::overlapping_concurrent_lanes` | mis-homed — it is a *config-integrity* fact, not a *supervisor* one |
| contradictory concurrent ∩ exclusive | **nowhere** | a lane in both lists is silently honored |
| dangling autopick / alias target | **nowhere** | a typo'd autopick lane silently does nothing |
| a lane's region **swallowed** by another | **nowhere** (the closest, `overlapping_concurrent_lanes`, conflates it with incidental overlap) | the true `detectUnreachableRules` case |

The CLI helper layer is supposed to carry **no policy of its own** (CLAUDE.md
layer 3: "thin shells over the kernel that carry no policy"). `_treeless_lane_findings`
violates that — it *is* policy logic. The linter pulls it down into the kernel
where it belongs, and adds the four checks that have no home at all.

## 2. The findings — the closed vocabulary

A `Finding` is a typed record (kind enum + severity + subject + detail + fix),
not a bare string — the same `InterventionDecision` / `OverlapDecision` discipline
(a structured verdict a consumer can filter on, not prose it must re-parse). The
closed `LintKind` set:

1. **`LANE_WITHOUT_TREE`** *(error)* — a lane named in `[lanes].concurrent` or
   `[lanes].autopick` but with no `[lanes.trees]` entry. The disjointness algebra
   compares trees; a lane with no tree can be neither admitted concurrently
   (nothing to prove disjoint) nor refused for overlap — it is **un-arbitrable**.
   (Exclusive lanes are *exempt*: the arbiter admits an exclusive lane on liveness
   alone, never consulting a tree, so a treeless exclusive lane like `global` is
   correct, not a finding — the bug `_treeless_lane_findings` already learned.)
   Lifted verbatim from that helper.

2. **`LANE_BOTH_CONCURRENT_AND_EXCLUSIVE`** *(error)* — a lane declared in **both**
   `[lanes].concurrent` and `[lanes].exclusive`. Contradictory: concurrent means
   "runs in parallel iff disjoint," exclusive means "never runs alongside
   anything." A lane cannot be both. Which list wins is an arbiter-internal
   accident the operator should not depend on — declare the intent.

3. **`AUTOPICK_LANE_UNDECLARED`** *(warn)* — a lane in the `[lanes].autopick`
   walk order that appears in **neither** `concurrent` **nor** `exclusive`. The
   auto-pick walk steps through lanes looking for a free one; a lane that was never
   declared a real lane is a **dangling reference** — usually a typo — that
   silently contributes nothing to the walk.

4. **`ALIAS_TARGET_UNDECLARED`** *(warn)* — a `[lanes.aliases]` keyword pointing at
   a target lane that is declared nowhere. The alias routes a keyword to a lane
   that does not exist, so the keyword silently resolves to nothing (or, worse,
   to an `UNKNOWN_LANE` refuse at request time — a config bug surfaced late
   instead of at lint time).

5. **`LANE_REGION_SHADOWED`** *(warn)* — the true `detectUnreachableRules` case: a
   concurrent lane whose region is a **strict subset** of another concurrent
   lane's region. It can never be picked *independently* of its superset — any
   request that would take the narrow lane collides with the broad one, so the
   narrow lane is **structurally unreachable** as a distinct concurrency unit. (See
   §3 for why this is *distinct* from finding #5's cousin, the overlap pair.)

6. **`CONCURRENT_LANES_OVERLAP`** *(warn)* — two concurrent lanes whose regions
   **incidentally intersect** (share a prefix) without one swallowing the other.
   Only one of the pair can hold a worker at a time, so the supervisor's spawn
   *order* decides which fills (docs/210 §pivot). Re-homed from
   `supervise.overlapping_concurrent_lanes` (which `config_lint` now *calls* — one
   definition, no drift).

`ReasonRegistry` integrity is *mostly already enforced* at construction
(`__post_init__` rejects duplicate tokens; `ReasonSpec.__post_init__` rejects an
unknown category). The one residual registry check the linter adds:

7. **`REASON_SEE_ALSO_DANGLES`** *(info)* — a `ReasonSpec.see_also` pointer of the
   form `lane <name>` whose `<name>` is not a declared lane. The man-page cross-ref
   would dead-end. Lowest severity (a broken doc link, not a broken mechanism), and
   conservative: only the `lane <name>` shape is checked (other `see_also` targets —
   oracles, meta keys — are free-form prose the linter does not model).

## 3. The subtle one: shadow (subset) vs. overlap (intersection)

`_tree.lane_trees_disjoint(a, b)` returns `False` for *any* prefix collision — it
cannot tell "lane A's region is **wholly inside** lane B's" (A is dead) from "A and
B **incidentally share** a file or two" (both live, but order-sensitive). Those are
two different findings with two different fixes:

- **Shadow** (`src/api` ⊂ `src`): A is **unreachable**. The fix is *remove A* (or
  carve B so it no longer contains A). This is CC's `detectUnreachableRules`.
- **Overlap** (`src/api` ∩ `src/api_shared` via the `src/api` prefix): both lanes
  are real, but they cap each other at concurrency 1. The fix is *disjoin the
  trees* or *mark one exclusive*. This is docs/210's roster-order smell.

So the linter needs a **strict-subset** test the existing algebra does not provide.
The definition, pure and prefix-based (reusing `_tree.norm_tree_prefix` so it
folds case and truncates globs identically to every other collision check):

> Lane A's region is **swallowed by** lane B's region iff **every** normalized
> prefix in A collides with **some** prefix in B, **and** the reverse is not also
> true (B is not equally swallowed by A — that symmetric case is *identical
> regions*, reported as overlap, not shadow, since neither is "the smaller one").

Worked: A = `["src/api/**"]` → prefix `src/api/`; B = `["src/**"]` → prefix `src/`.
Every A-prefix (`src/api/`) starts-with a B-prefix (`src/`) → A ⊆ B. Not every
B-prefix starts-with an A-prefix (`src/` does not start with `src/api/`) → B ⊄ A.
**Strict subset → A is shadowed by B.** The empty/universal prefix (`**/*` → `""`)
swallows everything, so a concurrent lane sharing a roster with a universal-tree
concurrent lane is reported shadowed — correct, it can never be picked beside the
whole-repo lane. (A universal tree usually belongs in `exclusive`; that the linter
surfaces it is the point.)

This keeps the two findings clean: **shadow** (#5) fires on strict subset and means
*dead*; **overlap** (#6) fires on the remaining (non-subset) intersections and means
*order-sensitive*. A pair is reported by exactly one of the two, never both.

## 4. Severity — and why the linter is advisory

Three levels, ordered, so a consumer can gate on them:

- **error** — the config is *broken*: a lane that cannot be arbitrated, a
  contradiction. `dos doctor --check` exits non-zero (CI catches it).
- **warn** — the config is *suspect*: a dangling reference, a dead/shadowed lane,
  an order-sensitive roster. Surfaced; exit code is gated the same as today's
  `--check` findings (any finding ⇒ non-zero), but a host can choose to treat warns
  as advisory by reading the typed severity.
- **info** — a *cosmetic* nit (a dead doc link). Surfaced, never gates.

Like every DOS verdict, the linter **reports**; it never rewrites `dos.toml` and
never refuses a lease on its own. It is a `dos doctor` integrity rail and a
`dos lint`-style CI gate — the operator (or CI) decides what a finding *means*.
This is the docs/99 advisory floor applied to config: the kernel finds the dead
policy; it does not delete it.

## 5. The shape — pattern-faithful to the kernel

```python
class LintKind(str, enum.Enum):
    LANE_WITHOUT_TREE = "LANE_WITHOUT_TREE"
    LANE_BOTH_CONCURRENT_AND_EXCLUSIVE = "LANE_BOTH_CONCURRENT_AND_EXCLUSIVE"
    AUTOPICK_LANE_UNDECLARED = "AUTOPICK_LANE_UNDECLARED"
    ALIAS_TARGET_UNDECLARED = "ALIAS_TARGET_UNDECLARED"
    LANE_REGION_SHADOWED = "LANE_REGION_SHADOWED"
    CONCURRENT_LANES_OVERLAP = "CONCURRENT_LANES_OVERLAP"
    REASON_SEE_ALSO_DANGLES = "REASON_SEE_ALSO_DANGLES"

class Severity(str, enum.Enum):
    ERROR = "error"; WARN = "warn"; INFO = "info"

@dataclass(frozen=True)
class Finding:
    kind: LintKind
    severity: Severity
    subject: str        # the lane / reason / alias the finding is about
    detail: str         # one line: what is wrong
    fix: str            # one line: how to fix it

def lint_lanes(taxonomy) -> tuple[Finding, ...]: ...
def lint_reasons(registry, *, known_lanes) -> tuple[Finding, ...]: ...
def lint(taxonomy, registry) -> tuple[Finding, ...]:   # both, sorted by severity
    ...
```

`lint()` returns findings sorted **error → warn → info**, then by kind, then by
subject — a stable order so the report and the test fixtures are deterministic
(the `overlap_eval` / `lane_overlap` ordering discipline).

**No host names** (Law 1): the linter reads `concurrent`/`exclusive`/`autopick`/
`trees`/`aliases` — generic taxonomy fields — and never a lane *name* like `apply`
or `src`. Pinned by `test_vendor_agnostic_kernel`'s existing sweep plus a
finding-text check (no finding string hardcodes a lane).

## 6. The CLI seam

`dos doctor --check` already computes a `findings: list[str]` and gates its exit
code on it. The linter slots in there: gather `cfg.lanes` + `cfg.reasons` at the
boundary, call `config_lint.lint(...)`, render each `Finding` to the existing
string-finding line (kind + subject + detail + fix). The scattered helpers
(`_treeless_lane_findings`, `_overlapping_concurrent_lane_findings`) are **replaced
by** the leaf (their logic now lives in `config_lint`, faithfully); `dos doctor`'s
behavior on the existing two checks is byte-unchanged (the same lines, same exit
code), proven by the existing `test_stamp_doctor` / treeless-lane tests staying
green.

A dedicated `dos lint` verb (thin alias for the lane+reason rail of
`doctor --check`, JSON-able for CI) is the natural operator surface — the same
"verb's exit code IS the verdict" contract every kernel syscall CLI follows
(`dos lint` exits 0 clean / 1 on any error-or-warn finding).

## 7. Why this is durable

The risk of dead policy **grows with the registries**. As a workspace adds lanes,
aliases, reasons, and as the `judges` / `overlap_policies` / `predicates` plugin
seams (docs/113/135) widen the declarable surface, the chance of a shadowed lane or
a dangling reference rises monotonically. A pure, tested integrity verdict that
catches it at config-write time — before a typo'd autopick lane silently drops a
whole concurrency topic, before a shadowed lane wastes an operator's afternoon — is
exactly the kind of small, generic, increasingly-load-bearing cog DOS is built
from. It is the self-describing registry *checking itself*: the DOS doctrine
(distrust the declaration, verify it against a sound rule) turned on the config.

## 8. What this is NOT

- **Not** a permission-rule linter — DOS has no permission-rule allow-list surface
  (the CC home for `detectUnreachableRules`). The *lift* is the **shape** (find
  unreachable declared policy), aimed at DOS's actual registries (lanes/reasons).
- **Not** a `dos.toml` *schema* validator — `LaneTaxonomy.from_table` /
  `reasons.specs_from_table` already reject malformed TOML loudly at load. The
  linter checks *semantic* integrity of a *well-formed* config (a lane that parses
  fine but can never fire), the layer above schema.
- **Not** an enforcement action — it reports findings; it never edits config or
  refuses a lease (the advisory floor, §4).

---

*Provenance: G1 from docs/189 (CC `shadowedRuleDetection.ts:193-234`,
`detectUnreachableRules`, verified absent in DOS on 2026-06-06). Consolidates
`cli.py::_treeless_lane_findings` + `supervise.overlapping_concurrent_lanes` into
a pure leaf and adds the four checks with no prior home. The strict-subset shadow
test is new; the overlap test reuses the existing `_tree` prefix algebra.*
