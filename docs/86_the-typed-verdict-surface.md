# The typed-verdict surface — one ABI for adjudication, extendable by others, proven on the bench

> **DOS already ships four near-identical verdicts behind four hand-wired verbs. The
> next move is not a fifth verb — it is naming the *contract* the four almost share, so
> anyone can add a verdict the way you add a device driver, and proving the contract by
> using its first new instances to make FleetHorizon measure the failure modes it
> already simulates but does not yet adjudicate.**

This note closes the arc of [`84`](183_how-much-does-this-lean-on-git.md) (git is
necessary-not-sufficient; the verdict carries its provenance rung) and
[`85`](85_extending-the-verifiable-surface.md) (extend by economics, not coverage; three
moves, one four-gate test; scope-fidelity specced). Those two answered *what* to verify
and *whether the gap is a problem*. This one answers the structural question underneath:
**what is the general, typed, OS-style surface that makes adjudication extendable by
others — and how does that abstraction *directly* solve an urgent benchmark problem
rather than floating free of it.**

The honest tension this note holds, stated up front because it is the whole design
constraint: a *general extensible surface* and a *direct fix to the urgent FleetHorizon
proof* sound like opposite priorities — one abstract, one concrete. They are the **same
move**, and §3 is the proof: the abstraction is exactly the refactor that turns the
benchmark from a 2-of-5 believed-vs-adjudicated A/B into a full-failure-space one.

A theory + spec note (family of [`79`](79_primitives-not-features.md),
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md), [`84`](183_how-much-does-this-lean-on-git.md),
[`85`](85_extending-the-verifiable-surface.md)); no litmus, not in `next-stage-plan`. §1
is an extraction of a shape already in the tree; §2–§4 are buildable, not built.

---

## 1. The latent ABI: `classify(Evidence, Policy) -> Verdict[V]`

Look at what the kernel already ships, side by side. The shape is *almost* identical and
quietly drifting:

| Verb | Module | Returns | Verdict value | Provenance | Pure classify? |
|---|---|---|---|---|---|
| `verify()` | `oracle` | `ShipVerdict` | `shipped: bool` | `source: "registry"\|"grep"\|"none"` | core is pure; git read at boundary |
| `liveness()` | `liveness` | `LivenessVerdict` | `verdict: Liveness` (3-enum) | `reason` + echoed `evidence` | **yes** — `classify(ev, policy)` |
| `gate` | `gate_classify` | `Verdict` (enum) | typed enum | reason | yes |

They want to be the same thing and aren't quite: `ShipVerdict` uses `shipped: bool` +
`source`; `LivenessVerdict` uses `verdict: Enum` + `reason` + `evidence`. The
[`liveness.py`](../src/dos/liveness.py) docstring even *writes out* the sibling table —
`arbitrate(req, leases, cfg)`, `loop_decide.decide(state, outcome)`,
`liveness.classify(evidence, policy)` — as one family. The extraction this note proposes
is to make that family a **named contract** instead of a coincidence:

```
Evidence   (frozen, caller-GATHERED, no I/O inside)        — the facts, decoupled from how they're read
Policy     (frozen, dos.toml-declarable, defaults GENERIC) — the thresholds, "mechanism is kernel, knobs are config"
classify(Evidence, Policy) -> Verdict[V]                   — PURE: no subprocess, no file, no clock
Verdict[V] { verdict: V (CLOSED enum) ; reason: str ;       — the typed answer + why
             provenance: Rung ; evidence }  + to_dict()     — which rung answered + the JSON/MCP seam
gather(...) -> Evidence                                     — the ONLY I/O, at the CLI boundary (the git_delta pattern)
```

This single contract **fuses the three kernel design laws into one type**:
- *typed verdict over binary gate* → `verdict: V` is a closed enum, never a bare bool;
- *evidence over narrative* → `Evidence` is gathered from artifacts, never the agent's claim;
- *the give lives in provenance* ([`76`](76_flexible-goals-and-verification.md)) → `provenance: Rung` names which signal answered, ordered by accountability ([`85 §1`](85_extending-the-verifiable-surface.md)); `Policy` is the which-signals/threshold seam. The *adjudication* (the `classify` body) stays fixed and mechanical.

**The OS analogy, made precise.** This is the **syscall ABI for a typed adjudicated
answer about ground-truth state.** `verify` / `liveness` / `scope` / `acceptance` /
`identity` are all `Verdict[V]` instances with different `V`, different `Evidence`,
different rung-ladders — the way `read`/`write`/`stat` are all syscalls with different
arguments over one calling convention. The closed enum `V` is the verb's *verdict
vocabulary*; the rung-ladder is its *provenance*; the policy is its *threshold seam*.

**The honest scope boundary — not everything unifies, and forcing it would be the
over-abstraction error.** The ABI is for the **epistemic** syscalls: the ones that
answer *"is this claim about ground-truth state true?"* (`verify`, `liveness`, `scope`,
`acceptance`, `identity`). `arbitrate()` and `spawn/reap` share the *classify shape*
(state-in → typed-out, pure) but their output is an **effect decision** (acquire/refuse)
or an **identity record**, not a *belief about the world* — they are cousins, not members
([`84`](183_how-much-does-this-lean-on-git.md)'s "git-dependence is concentrated in the
epistemic half" is the same cut). The typed-verdict surface generalizes the epistemic
half; it must not swallow the effect/identity half, or it becomes a god-type that means
nothing. Drawing that line *is* part of getting the abstraction right.

---

## 2. Extendable by others — the registry, the seams, and the guard

A general shape is worthless for "buildable by others" if adding a verdict still means
editing the kernel. Today it does: `cli.py` hand-wires every verb (`cmd_verify`,
`cmd_liveness`, … each a `cmd_X` + `add_parser` + `set_defaults`). OS-style
extensibility needs three things, two of which DOS already has the pattern for:

1. **A verdict registry (the missing piece).** `dos.verdicts.register(spec)` (or a
   `dos.verdicts` entry-point group), so a third party ships a module implementing the
   §1 contract — `Evidence`, `Policy`, `classify`, `gather`, a verdict name — and gets,
   *without editing the kernel*: a `dos <verb>` CLI subcommand, a row type in the
   `dos decisions` queue, and an MCP tool. This is the **verb analogue of the data
   registries the kernel already ships** — `[reasons]` (`ReasonRegistry`), `[lanes]`
   (`LaneTaxonomy`), `[stamp]` (`StampConvention`). DOS already lets you declare your
   *vocabulary* as data; this lets you declare your *verdict* as a plugin. The
   decisions-queue is the payoff multiplier: it is a projection over kernel verdicts, so
   every registered verdict *automatically* gains an operator surface — register
   `scope`, and `SCOPE_CREEP` rows appear in the queue with zero queue code.

2. **The policy seam (already shipped).** `dos.toml [<verb>]` — the exact pattern
   `[liveness]` established (`grace_ms`/`spin_ms` read back through `SubstrateConfig`).
   Every registered verdict declares its thresholds as data, defaults generic.

3. **The provenance ladder as per-verdict data (already the shape).** A third party's
   oracle declares *its own* rungs, ordered by referent accountability ([`85 §1`](85_extending-the-verifiable-surface.md)):
   a deploy-verdict might ladder `registry-digest > control-plane-status > self-probe`.
   `verify`'s `registry > grep > none` is just one instance.

**The guard that keeps the registry from becoming a free-for-all** is the
[`85 §2`](85_extending-the-verifiable-surface.md) four-gate test, enforced at
registration: a verdict may register **iff** it (1) answers a claim about ground-truth
state, (2) reads evidence unforgeable by the agent, (3) is domain-free, (4) returns a
mechanical typed verdict. Fail (1) → it's a JUDGE (advisory, `drivers/llm_judge.py`),
not a verdict. Fail (3) → it's a driver oracle on the seam, not a kernel verb. This is
what stops the OS-extensibility surface from drifting into the policy-enforcement
firewall DOS deliberately is **not** (the standing prior-art caution: *don't import
machinery; the design is ahead, the gap is proof and adoption*). The registry is open;
the contract is strict. That combination — **open set of verbs, closed shape per verb**
— is the same "closed-enum-as-data" hackability pattern [`HACKING.md`](HACKING.md)
already documents, lifted from vocabularies to verdicts.

---

## 3. The direct bench proof — adjudicating the failure modes FleetHorizon already simulates

Here is where the abstraction earns its place against an urgent problem instead of
floating. The FleetHorizon failure model
([`agent.py`](../benchmark/fleet_horizon/agent.py)) already simulates a **full space** of
failure modes — and the trajectory record only adjudicates **two of them.** This is a
measured gap in the flagship proof artifact, and the typed-verdict surface closes it
*with data the benchmark already generates.*

What the simulation already produces, per step:

| Failure mode | Already simulated? | Already a typed verdict in `TrajectoryStep`? |
|---|---|---|
| **lie** (claim shipped, no commit) | yes (`lie_rate`) | **yes** — `verdict_shipped` / `is_caught_lie` |
| **flake** (tried, commit silently failed) | yes (`flake_rate`) | yes — folds into `verdict_shipped` (the irreducible residue, [`84 §2`](183_how-much-does-this-lean-on-git.md)) |
| **write collision** (two efforts, shared file) | yes (`shared_ratio` + `interleave`) | **yes** — `arbiter_outcome` |
| **scope reach** (footprint exceeds the effort's lane) | **yes** — `Phase.touches` reaches `shared/` beyond `effort-NN/`; `Effort.lane` is the declared subtree | **NO** — banked silently |
| **thrash / spin** (busy-wait, no progress) | **yes** — `Worker.will_thrash()` | **NO** — banked silently |

The last two rows are the gap. The benchmark *generates the inputs* — an effort's
declared scope is `Effort.lane` / its `effort-NN/` subtree
([`workload.py`](../benchmark/fleet_horizon/workload.py)), and a thrash step is a
no-commit step — but the trajectory has no `verdict_in_scope` and no `verdict_advancing`,
so a fleet that **believes** its workers is silently eating scope-creep and spin that the
A/B never scores. **That understates DOS's edge**: the open loop banks *more* corruption
than the benchmark currently counts.

**The fix is the typed-verdict surface's first two new instances, wired into the trajectory:**

- `verdict_in_scope: Scope` — `scope.classify` (the [`85 §4`](85_extending-the-verifiable-surface.md) spec) over `Claim.wrote_files` vs the effort's declared tree. A phase whose footprint spills outside `effort-NN/` without leasing the shared lane is `SCOPE_CREEP`; the open loop banks it, the closed loop refuses it at contention.
- `verdict_advancing: Liveness` — `liveness.classify` over the thrash signal (a thrash run is `commits_since_start == 0` with a fresh heartbeat → `SPINNING`). The open loop pays for the spin silently; the closed loop surfaces it to the decisions queue.

The payoff is three concrete benchmark upgrades, each a *direct* answer to the urgent
"is the proof complete" question:

1. **The believed-vs-adjudicated delta widens to the full failure space.** The A/B stops
   being "ship-lies + collisions caught" and becomes "ship-lies + flakes + collisions +
   scope-creep + spin caught" — the honest total of what a non-believing kernel removes.
   The headline `verified-velocity-per-$` and `human-review-fraction` ([`81`](81_velocity-economics-and-the-fleet-benchmark.md))
   both move further DOS-positive because the open loop's silent bill is now *counted*.
2. **The distillation experiment becomes multi-label.** Today
   [`verifier.py`](../benchmark/fleet_horizon/verifier.py) asks one irreducibility
   question: *can a claim-side model predict `really_committed`?* With the new verdict
   columns it asks three — *can it predict scope-violation? spin?* — each a separate
   falsifiable headline. Some may be *more* distillable than ship-truth (a scope
   violation has a footprint shape); some less. Either way the benchmark gains
   falsifiable results it cannot produce today, which is exactly what a flagship proof
   needs.
3. **It stays honest under the benchmark's own invariant.** *Same agent, same seed.* The
   new verdicts adjudicate the **same simulated run** the A/B already scores — they do
   not give DOS a better worker, they count dimensions that were previously banked
   silently. The [`81 §3`](81_velocity-economics-and-the-fleet-benchmark.md) honesty
   discipline (gap → 0 as horizon → 1; break-even κ swept not picked) carries to the new
   columns unchanged: at `efforts=1` there is no lane to creep across and no concurrent
   spin to surface, so the new deltas vanish exactly where the others do.

So the general surface is not gold-plating deferred until "after the benchmark." It **is**
the benchmark fix: the only clean way to add `scope` and `liveness` columns to the
trajectory *without* hand-coding two more bespoke adjudicators is to put them on the one
contract — and once they are on it, the registry (§2) makes the *next* dimension someone
else wants to measure a plugin, not a benchmark fork.

---

## 4. Build order — deeper before broader, prove at each rung, generalize last

The sequence is chosen so **every step ships a bench-visible win before the abstraction
is fully general** — the resolution of the §0 tension in execution form, and the same
"deeper before broader" call as [`85 §5`](85_extending-the-verifiable-surface.md):

1. **Extract the `Verdict` contract from what exists — no behavior change.** Refactor
   `liveness` + `oracle` to share one `Verdict[V]` base (give `ShipVerdict` a `.verdict:
   Ship` enum view alongside its existing `shipped: bool`, so job's re-export shims and
   every current caller keep working). Pure mechanical lift; the suite stays green. *Win:
   the laws become one type; zero risk.*
2. **Build `scope` as the first NEW verdict on the contract** (the [`85 §4`](85_extending-the-verifiable-surface.md)
   spec — pure `classify`, reuse [`_tree`](../src/dos/_tree.py), `dos scope` CLI verb).
   *Win: the missing fleet-safety verb ships; the contract is proven on a second-from-new
   instance.*
3. **Wire `scope` + `liveness` into `TrajectoryStep`** (§3). *Win: the urgent one — the
   benchmark measures 4 failure dimensions, the believed-vs-adjudicated story gets
   honest-er and stronger, the distillation experiment goes multi-label.*
4. **Add the registry last** (§2), once ≥2 new instances prove the shape is real. *Win:
   the OS-extensibility payoff — third parties add verdicts without touching the kernel;
   the decisions queue and MCP server inherit them for free.*

Generalizing *last* is deliberate: a registry built before there are two real instances
to generalize from is the classic over-abstraction trap (importing machinery ahead of
need — the standing prior-art caution). Steps 1–3 are concrete and bench-justified; step 4 is the generalization
that only pays once the pattern is demonstrated — and by then FleetHorizon is the
evidence that it works.

**Honest risks:**
- *The `ShipVerdict` bool→enum harmonization touches downstream shims.* Mitigated by
  keeping `shipped: bool` as a property over the enum — additive, not a break. Real cost,
  bounded.
- *Over-generalizing the contract to cover `arbitrate`/`spawn`.* Guard: the §1 epistemic
  boundary — the Verdict surface is for *beliefs about ground truth*, never *effect
  decisions*. Cousins stay cousins.
- *Registry-as-attack-surface.* Guard: the §2 four-gate registration check — open set of
  verbs, closed shape per verb; advisory-not-enforcing stays a registration invariant
  (the `--force` litmus, [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md)).

---

## 5. What this note claims

- **Does claim:** the four kernel verdicts already *almost* share one `classify(Evidence,
  Policy) -> Verdict[V]` ABI (§1); making it a named, registrable contract is the
  OS-style "buildable by others" surface (§2); and that abstraction is *identical* to the
  refactor that closes FleetHorizon's measurement gap — it adjudicates the scope-creep and
  spin the benchmark already simulates but banks silently (§3). The build order proves a
  bench win at each rung and generalizes last (§4).
- **Does not claim:** that all syscalls unify (the effect/identity half is a cousin, not a
  member, §1); that the registry should ship before two instances prove the shape (§4);
  or that any of this is built — §1 is an extraction, §2–§4 are a buildable spec.
- **The one-liner:** *don't add a fifth verb — name the contract the four share, let
  others register the sixth, and prove the contract by making the benchmark measure the
  whole failure space it already pretends not to see.*

---

## References

*The shape to extract (§1):*
- [`src/dos/liveness.py`](../src/dos/liveness.py) — the canonical `classify(Evidence,
  Policy) -> Verdict` instance and the sibling-table docstring this note promotes to a
  contract.
- `src/dos/oracle.py` (`ShipVerdict`: `shipped` + `source` + `to_dict`) and
  `src/dos/gate_classify.py` (`Verdict` enum) — the two instances that drifted from the
  shape and would be harmonized onto it.
- [`src/dos/git_delta.py`](../src/dos/git_delta.py) — the `gather()`-at-the-boundary
  pattern (I/O outside the pure verdict).

*The extensibility seams (§2):*
- `src/dos/{reasons,stamp}.py` + `dos.config.LaneTaxonomy` — the data-registry pattern
  (`[reasons]`/`[stamp]`/`[lanes]`) the verdict registry is the verb-analogue of.
- `src/dos/cli.py` (the hand-wired `cmd_*` + `add_parser` dispatch) — what the registry
  replaces for verdict verbs.
- [`HACKING.md`](HACKING.md) — closed-enum-as-data; this lifts it from vocabularies to verdicts.

*The bench proof (§3):*
- [`benchmark/fleet_horizon/agent.py`](../benchmark/fleet_horizon/agent.py) — the failure
  model: `lie_rate`/`flake_rate`/`thrash_rate` simulate the full space.
- [`benchmark/fleet_horizon/workload.py`](../benchmark/fleet_horizon/workload.py) —
  `Effort.lane` / `Phase.touches`: the declared-scope and footprint inputs scope-fidelity
  reads, already present.
- [`benchmark/fleet_horizon/trajectory.py`](../benchmark/fleet_horizon/trajectory.py) —
  `TrajectoryStep`: the `(features ⟂ label ⟂ verdict+provenance)` record the new verdict
  columns extend.
- [`benchmark/fleet_horizon/verifier.py`](../benchmark/fleet_horizon/verifier.py) — the
  distillation experiment that goes multi-label once the new verdict columns exist.

*The frame (§0–§4):*
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md),
  [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) — the
  arc this completes; the four-gate test (§2 guard) and scope-fidelity spec (§3) live in 85.
- [`76`](76_flexible-goals-and-verification.md), [`79`](79_primitives-not-features.md),
  [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) — the give-lives-in-provenance law, the
  primitives-not-features discipline, and the expand-by-composition stance the ABI honors.
