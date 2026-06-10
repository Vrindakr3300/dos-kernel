# Extending the verifiable surface — deeper before broader, and where the boundary belongs

> **The question is never "can we verify X" — almost always yes, at a cost. It is
> "is the trust boundary in the right place for what a lie there would cost." Every
> new oracle does not *remove* trust; it *relocates* it to a more accountable party.
> Extending DOS is choosing where to relocate, not chasing total coverage.**

[`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md)
established that `verify()` leans on git, that git is **necessary** (you cannot
distill the check into a claim-side model — the flake floor is irreducible) and
**not sufficient** (a clean `verify()` means *a commit of the right shape exists in
ancestry*, not *the work is real, correct, and complete*, and says nothing about the
non-git surface). It resolved the gap with a **typed verdict carrying its provenance
rung** (`source=` / `via=`), so the human triages by confidence instead of reading
everything at uniform suspicion.

This note answers the two questions that follow immediately: **how do you extend the
verifiable surface, and — the sharper one — is the gap really a *problem*?** The
answers, which the rest earns:

1. **Reframe coverage as economics (§1).** Verification is a graph of trust
   delegations; you never reach an un-trusted bottom. So extension is *risk-weighted*
   (verify where lies are likely *and* expensive), and oracles are ranked by *how
   accountable their referent is*, not a binary "forgeable / not."
2. **"Extend" is three different moves with three different homes (§2),** and only one
   is a kernel change. A single four-gate test sorts any candidate into
   kernel-verb / driver-oracle / not-a-thing.
3. **Mostly it is NOT a problem (§3)** — the boundary is the product, the flake floor
   caps the payoff, and most fleet work is git-shaped — *except* two real holes worth
   closing: the **forgeable floor rung** and the **missing scope-fidelity verb**.
4. **The worked example (§4):** the scope-fidelity verb, specced concretely as a pure
   classifier mirroring [`liveness.py`](../src/dos/liveness.py), reusing the
   [`_tree`](../src/dos/_tree.py) prefix algebra and the `[lanes]` trees the arbiter
   already consumes — *expand by composition, not new machinery.*

A theory + spec note in the family of [`79`](79_primitives-not-features.md),
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md), [`84`](183_how-much-does-this-lean-on-git.md);
it carries no litmus and is not in the `next-stage-plan` table. §4 is a buildable spec,
not yet built.

---

## 1. The reframe: coverage is the wrong axis; trust-relocation is the right one

The instinct behind "what else can we verify" is *coverage*: enumerate done-claims and
build an oracle for each. But trace any oracle to its root and it bottoms out in
trusting **someone**:

- a subject-grep trusts a string *the agent wrote*;
- "tests green at this SHA" trusts *the CI system*;
- "the service answers at version X" trusts *a health endpoint* (which the agent may
  control);
- "the payment settled" trusts *the processor's API*.

You never reach an un-trusted floor. A new oracle does not *eliminate* trust — it
**relocates the axiom** to a party you'd rather trust than the self-narrating agent.
That single observation reorganizes the whole question.

**Consequence A — rank oracles by the *accountability* of their referent, not a binary
"forgeable?".** Forgeability is a spectrum:

```
strongest  immutable third-party record    git content-hash; a registry image digest; a signed CI attestation
     │     mutable third-party state        a DB migration catalog; a cloud control-plane status
     │     a probe the agent doesn't own     an external health endpoint on infra the agent can't redeploy
weakest    a self-report dressed as evidence a probe of the agent's OWN service; a commit subject the agent typed
```

An "is it deployed?" oracle that hits *the agent's own service* sits at the bottom —
the agent controls the thing being asked. An **image digest in a third-party registry**
sits near the top. So "what to verify next" is guided by *where the most accountable
referent for this claim-type lives* — and a candidate whose only referent is a
self-report is not a verification, it is belief wearing evidence's clothes.

**Consequence B — extend where lies are both likely and expensive (risk-weighted, not
uniform).** The value of a new rung is, roughly:

> **value(rung) ≈ P(claim is false) × (downstream detonation cost if believed) −
> cost(rung)**

This is the same κ/break-even economics
[`81`](81_velocity-economics-and-the-fleet-benchmark.md) already sweeps for the fleet
A/B, pointed at *which oracle to build*. A silent lie about a **DB migration**
detonates as a prod incident (high P × high cost) — worth a rung. A lie about a **doc
typo** doesn't (low cost) — not worth one. Uniform "verify everything" ignores both
terms and burns rung-cost where no lie would have detonated.

---

## 2. "Extend" is three moves — and only one touches the kernel

Conflating these is the main error. "What else can we verify" decomposes into three
layers, each with a different home in the [`CLAUDE.md`](../CLAUDE.md) layering:

### (A) Deeper rungs on the *same* git artifact — **home: a host-declared predicate**

Strengthen `verify()` itself by climbing the existing ladder:

```
subject-grep → file-path overlap → diff CONTENT (changed the named symbols?) → BEHAVIORAL oracle (tests/build green at the SHA)
```

The behavioral oracle is the single biggest **complete → correct** jump (the
[`84 §3.3`](183_how-much-does-this-lean-on-git.md) ship≠correct gap). Crucially this is
**not a kernel change**: DOS already ships the *socket* — the host declares how strong
the completion predicate is. "A commit closing the phase exists" is weak; "the build is
green at that commit *and* it touches the phase's distinctive files" is strong. The
kernel adjudicates deterministically against whatever the host declared; *how close to
correct* is the host's dial.

### (B) New artifact oracles for the non-git surface — **home: the driver/seam**

The [`84 §3.4`](183_how-much-does-this-lean-on-git.md) surface git is blind to: CI/Checks
status, a deploy/runtime probe, a DB migration catalog, a package-registry digest, an
external side-effect keyed to an idempotency key. Each is the **same claim → evidence →
verdict schema** with a different fossil. None belongs *in* the kernel — each is a
specific system, so each is a **driver oracle plugged into the seam**, exactly as the
LLM judge (`drivers/llm_judge.py`) is a driver, not a syscall. A repo with the oracle
wired gets a stronger verdict; one without degrades honestly to `source="none"`.

### (C) New *sibling verbs* for distinct claim-types — **home: the kernel (sparingly)**

The genuinely-new mechanism. The distrust-primitive map ranks the candidates, each a
claim about *ground-truth state* with an *unforgeable, domain-free* referent:

| Verb | Distrusts the claim | Verdict | Status |
|---|---|---|---|
| `liveness()` | "I'm making progress" | `ADVANCING / SPINNING / STALLED` | **shipped** (docs/82 P1) |
| **scope-fidelity** | "I only touched what I claimed" | `IN_SCOPE / SCOPE_CREEP / WRONG_TARGET` | **the one worth building next (§4)** |
| acceptance | "done means the tests back it" | an `ACCEPTED` rung *above* `SHIPPED`, fed structured evidence | candidate (deepen verify, don't add a syscall) |
| identity | "this is new work" | `NOVEL / DUPLICATE / RESUMPTION` (run-id lineage) | candidate |
| journal-integrity | "the WAL I'm replaying is sound" | corrupt / sound | candidate (low glamour) |

### The four-gate test that sorts any candidate

Run any proposed extension through **claim → evidence → verdict** against four gates:

| Gate | Pass → | Fail → |
|---|---|---|
| 1. A claim about **ground-truth state**? | maybe kernel | taste/correctness → a **JUDGE** (advisory, driver) or a signal piped in |
| 2. Evidence **unforgeable by the agent**? | maybe kernel | it's belief, not verification → drop it |
| 3. **Domain-free**? | a kernel **verb** | a specific system → a **driver oracle** on the seam (move B) |
| 4. Verdict **mechanical / typed**? | a kernel **verb** | redesign, or make it advisory |

Gate 2 is the accountability spectrum (§1) applied: a deploy-probe of the agent's own
service *fails* it; a third-party registry digest *passes*. This test is the whole
discipline — it keeps the kernel from absorbing host policy — the standing caution from the prior-art
survey: *don't import machinery; DOS's design is ahead, the gap is proof and adoption,
not mechanism.*

---

## 3. Is it really a problem? Mostly no — with two precise exceptions

### Why mostly *not* a problem

1. **The boundary is the product, not the bug.** The kernel's job is to adjudicate
   *completeness against a declared predicate and report provenance* — not to natively
   know every external system. The non-git surface being kernel-unverified is the
   design line ([`79`](79_primitives-not-features.md), [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md)),
   and it is closed by *plugging oracles into the seam* (moves A/B) — which is
   **possible today**, a host wiring job, not a missing kernel feature. Growing the
   kernel to natively understand deploys/DBs/payments would *break the layering*; the
   honest move is a driver, and drivers already exist.
2. **The flake floor caps the payoff.** [`84 §2`](183_how-much-does-this-lean-on-git.md)
   proved an irreducible residue — work shape-identical to success that only ground
   truth distinguishes — so no number of rungs takes the human-judgment queue to zero.
   Verification has **diminishing returns against a hard floor**; "verify everything" is
   a mirage even in principle.
3. **Most fleet work is git-shaped.** For the actual target — a code fleet — the
   overwhelming majority of "done"s leave a commit. The exotic surfaces (calendars,
   money) are real but a minority of the core case, so their marginal rung-value (§1.B)
   is low.

### The two places it genuinely *is* a problem

1. **The floor rung is forgeable.** Subject-grep passes on
   `git commit --allow-empty -m "<stamp>"` ([`84 §3.1`](183_how-much-does-this-lean-on-git.md))
   — and that grep *is the default* path when `source="none"` (a foreign repo, no plan).
   Hardening the floor to demand **diff content / ≥N distinctive files**, not just a
   matching subject, is high-value and fully domain-free — kernel-grade hardening of
   something that ships today. (This is move A applied to the *weakest* rung rather than
   the strongest.)
2. **Scope-fidelity is missing, cheap, and domain-free.** The diff's blast radius vs the
   lane's declared tree is an **unforgeable artifact already in the repo**, and it is
   *the* check that makes a fleet safe: without it, agent A can stamp "phase 3" onto a
   ten-file diff that silently stomps agent B's lane — the same SHIPPED-stamp-drift
   disease (the *evidence-over-narrative* design law) one level up. Leaving it unbuilt is
   free verification left on the table. It is the one new *verb* worth the kernel change
   — specced next.

---

## 4. Worked example — the scope-fidelity verb

The discipline ([`79`](79_primitives-not-features.md): primitives not features;
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md): expand by composition) is to build
this as a **pure verdict that mirrors [`liveness.py`](../src/dos/liveness.py) exactly**
and **reuses the [`_tree`](../src/dos/_tree.py) prefix algebra the arbiter already
stands on** — not a new subsystem.

**The claim it distrusts:** *"the diff I'm stamping as `(plan, phase)` stays inside that
phase's declared lane."* `verify()` confirms *something* shipped under the stamp; it does
**not** confirm the diff's footprint matches the declared scope. An agent can stamp
`phase 3` onto an unrelated ten-file change.

**The evidence (unforgeable, already present):**
- **touched files** — the repo-relative paths the candidate commit(s) changed. A
  boundary read, `git diff --name-only <base>..<head>` (or `git show --name-only <sha>`),
  in the **`git_delta` mold**: the subprocess happens at the CLI boundary, the pure
  classifier receives the already-gathered `frozenset[str]`. The agent cannot forge which
  files a commit object touched.
- **declared tree** — the lane's path globs, read straight from
  `SubstrateConfig.lanes.trees[lane]` (the `[lanes]` table, WCR) — *the same tuples the
  arbiter's overlap algebra consumes*. No new config surface.

**The verdict ladder** (typed, three states, mutually exclusive — the `liveness` shape):

```
IN_SCOPE      every touched file falls under some declared prefix of the lane's tree.
SCOPE_CREEP   the lane's files are touched AND so are files outside the tree — a superset.
WRONG_TARGET  NONE of the touched files fall in the lane's tree — the stamp names a lane the diff didn't enter.
```

**The algebra — reuse `_tree`, do not reinvent.** A touched file `f` is *in* the tree
when `_tree.norm_tree_prefix(glob)` is a path-prefix of `f` for some glob in the lane
tree (the exact prefix test `lane_trees_disjoint` runs pairwise — here run
one-directionally, file-vs-tree). The classifier is then a partition:

```python
in_tree    = {f for f in touched if _in_any_prefix(f, lane_prefixes)}
out_tree   = touched - in_tree
if not touched:        IN_SCOPE      # an empty diff creeps on nothing (cf. liveness 0-commit floor)
elif not in_tree:      WRONG_TARGET  # touched only things outside the declared lane
elif out_tree:         SCOPE_CREEP   # touched the lane AND spilled outside it
else:                  IN_SCOPE      # wholly contained
```

The proposed module shape, field-for-field analogous to `liveness`:

```python
class Scope(str, enum.Enum):            # mirrors Liveness
    IN_SCOPE = "IN_SCOPE"; SCOPE_CREEP = "SCOPE_CREEP"; WRONG_TARGET = "WRONG_TARGET"

@dataclass(frozen=True)
class ScopePolicy:                       # mirrors LivenessPolicy — dos.toml [scope] later
    allow_shared_infra: bool = True      # tolerate config.py/__init__.py touches (the phase_shipped _SHARED_INFRA precedent)
    creep_tolerance: int = 0             # out-of-tree files allowed before SCOPE_CREEP (default strict)

@dataclass(frozen=True)
class ScopeEvidence:                     # mirrors ProgressEvidence — caller-gathered, no I/O inside
    touched_files: frozenset[str]        # `git diff --name-only`, gathered at the boundary
    lane_tree: tuple[str, ...]           # config.lanes.trees[lane] — the declared globs

@dataclass(frozen=True)
class ScopeVerdict:                      # mirrors LivenessVerdict — verdict + reason + echoed evidence + to_dict()
    verdict: Scope; reason: str; evidence: ScopeEvidence

def classify(ev: ScopeEvidence, policy: ScopePolicy = DEFAULT_POLICY) -> ScopeVerdict:
    """PURE — no subprocess, no file, no clock. Reuses dos._tree.norm_tree_prefix."""
```

**Properties it inherits from the family, by construction:**
- **No-plan discipline** (`test_verify_no_plan` sibling): with the generic lane tree
  `("**/*",)`, `norm_tree_prefix` truncates at the first `*` → prefix `""` → everything
  is `IN_SCOPE`. A repo that declared no lanes gets the honest "no scope to violate"
  answer, never a crash — exactly how `liveness` degrades to the commit floor.
- **Conservative on the unknown blast radius:** `_tree` already treats an *empty* tree as
  unknown-not-zero. Scope reuses that stance — an empty `lane_tree` with a non-empty diff
  resolves to `WRONG_TARGET` (we cannot certify containment against an undeclared lane),
  matching `lane_trees_disjoint`'s "empty → not disjoint → refuse."
- **Advisory, like `liveness`/`SPINNING`:** scope-fidelity *reports*; it does not refuse a
  lease or revert a commit. A `ScopePredicate` over ADM's conjunctive admission seam, or a
  `SCOPE_CREEP` row in the `dos decisions` queue, is a *separate* opt-in driver policy —
  the verdict and the admission decision stay different syscalls (the same line LVN holds).
- **Legible provenance:** the `reason` names the offending files (`stamped <lane> but
  touched go/internal/x.go, docs/y.md outside its tree`), so the operator sees not just
  `SCOPE_CREEP` but *which spill* — the RND/Axis-4 renderer seam, identical to
  `liveness`'s "0 commits, heartbeat 8m fresh."

**What it explicitly is NOT:** a correctness check. Scope-fidelity says the diff *landed
where the plan said*, never that the change is *good* — quality stays an advisory judge's
call (gate 1). It is the structural-footprint cousin of `verify`'s existence check, not a
reviewer.

---

## 5. What this note claims, and the recommendation

- **Does claim:** the extension question is *economics* (where to relocate trust),
  resolved by the risk-weighted rung-value and the accountability spectrum (§1); "extend"
  is three moves, only one of which is a kernel change, sorted by one four-gate test (§2);
  the gap is *mostly not a problem* because the boundary is the product and the flake
  floor caps the payoff (§3); and scope-fidelity is a clean, buildable, domain-free verb
  that reuses existing machinery (§4).
- **Does not claim:** that the kernel should absorb deploy/DB/payment oracles (those are
  drivers), that more rungs ever reach total coverage (the flake floor forbids it), or
  that scope-fidelity checks correctness (it checks footprint, not quality).
- **The recommendation — go deeper before broader.** A behavioral completion predicate on
  the existing git rung (move A) plus a CI/Checks oracle as a *reference driver* (move B)
  buys more honest "complete ≈ correct" than ten shallow oracles for rare surfaces. Then
  the one new *verb* worth the kernel change is **scope-fidelity** (move C / §4) — cheap,
  unforgeable, domain-free, and the thing that actually makes a fleet safe to run on
  shared state. Everything past that is subject to the §1 test: relocate trust only where
  a lie is both likely and expensive.

The honest meta-answer to "what else can we verify, or is it really a problem": **the gap
is real, bounded, and mostly the host's to close at the seam** — and the kernel's
contribution stays what [`84`](183_how-much-does-this-lean-on-git.md) named it: consult the
most accountable fossil available, and report which rung it stood on.

---

## References (the code and notes that ground each claim)

*The verb template and the algebra to reuse (§4):*
- [`src/dos/liveness.py`](../src/dos/liveness.py) — the pure-verdict shape scope-fidelity
  mirrors field-for-field (Enum verdict · frozen Policy with a `dos.toml` seam · frozen
  caller-gathered Evidence · frozen Verdict with `to_dict` · pure `classify`, no I/O).
- [`src/dos/_tree.py`](../src/dos/_tree.py) — `norm_tree_prefix` + `lane_trees_disjoint`:
  the prefix algebra (and the empty-tree-is-unknown stance) scope-fidelity reuses one-
  directionally.
- [`src/dos/git_delta.py`](../src/dos/git_delta.py) — the boundary-I/O reader pattern (the
  subprocess lives at the caller, the pure classifier gets a count/set) the touched-files
  gather follows.
- `dos.config.LaneTaxonomy.trees` (the `[lanes]` table, WCR) — the declared-scope source;
  the same per-lane globs the arbiter's overlap policy consumes.

*The frame and the boundary (§1–§3):*
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md) — the
  necessary-not-sufficient result and the typed-verdict-with-provenance resolution this
  note extends.
- [`81_velocity-economics-and-the-fleet-benchmark.md`](81_velocity-economics-and-the-fleet-benchmark.md)
  — the κ/break-even economics §1.B borrows for risk-weighted rung-value.
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) — the
  give lives in *provenance* + *which-signals*, never the adjudication: the law behind
  "new evidence enters as a rung/predicate, the verdict stays mechanical."
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md),
  [`79_primitives-not-features.md`](79_primitives-not-features.md) — expand by vocabulary +
  composition, not new machinery; the discipline §2's four-gate test enforces.
