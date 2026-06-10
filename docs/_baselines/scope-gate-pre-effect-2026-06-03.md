# Baseline — the binding pre-effect scope gate (docs/102 §5)

**Frozen:** 2026-06-03 · **kernel:** dos 0.8.0 · **author:** lane-fluidity slice
(docs/102 §5 / docs/90 §1–§2). Measure-then-change (docs/37 DD4, the job repo's
data-trust discipline applied to a kernel change): freeze the pre-state so the
pre-effect gate can be shown to catch — *earlier* — exactly what the post-hoc
check caught *too late*.

## What the gate is

`dos.scope.gate` (this slice) is the **collision-PREVENTION** sibling of
`dos.scope.classify` (the pre-existing **collision-DETECTION** verdict). Same
containment algebra (`classify`), but it returns an ALLOW/REFUSE *decision* a
caller acts on at the edit boundary — a write outside the lane's declared tree is
**refused before it lands**, not recorded after. This closes the one place
docs/102 §5 found the kernel knowingly breaking its own trust law: the arbiter
admits two lanes on their *declared* trees at contention, but conformance was only
checked post-hoc — so two agents that each under-declare are admitted concurrently
and one silently clobbers the other (*"you cannot un-clobber"*).

## Pre-state (what existed BEFORE this slice)

1. **Kernel had no pre-effect refusal.** `scope.classify` is explicitly ADVISORY
   (`scope.py` docstring: *"It reports; it never reverts a commit or refuses a
   lease."*). Its only consumers were the FleetHorizon benchmark sink and the
   (un-wired) `verdict_cli` dispatcher. There was **no `gate()`** and no
   `dos scope-gate` CLI verb — nothing in the kernel turned the declared tree into
   a *binding* commitment at the write boundary.

2. **The job repo hand-rolled the fence.** `scripts/commit_broker.py` (CB1) — the
   single-writer commit broker, the one real edit chokepoint — already refused an
   out-of-lane diff pre-`git apply` (`OUT_OF_LANE`), but with its own
   `path_in_tree` loop, NOT the kernel verdict, and with a flat reason string that
   cannot distinguish a partial overrun from a total miss.

## The frozen numbers (the queryable artifact)

The cost of detection-after-the-fact is measured by FleetHorizon's prevented /
detected / **surviving-silent-overwrite** split (`benchmark/fleet_horizon/`,
docs/98 §4.1). These are the clobbers a binding pre-effect gate converts from
"detected after both branches exist" to "prevented at the write." Frozen from
`benchmark/fleet_horizon/RESULTS.txt` (re-captured kernel 0.6.0, 2026-06-02) and
the docs/98 §4.1 orchestrator sweep table:

**Headline cell — 8 efforts × 30 phases, shared_ratio=0.3:**

| arm | real ships | banked lies | prevented | detected | **surviving silent** |
|---|---:|---:|---:|---:|---:|
| DOS-native (in-process leases) | 205 | 0 | 100% | 0 | **0** |
| harness +writeback | 205 | 0 | 100% | 0 | **0** |
| harness NO writeback | 205 | 0 | 0% | 10 | **10** |

**Detected-after collisions growing with the fleet (no-writeback harness):**

| fleet | detected / surviving-silent |
|---:|---|
| 2 | 0 / 0 |
| 4 | 2 / 2 |
| 8 | 12 / 12 |
| 12 | 15 / 15 |

**The baseline claim:** every `surviving silent` overwrite above is an
under-declared write that landed because containment was only checked
*post-hoc*. The pre-effect gate's success metric is that a consumer that runs
`gate()` before the write (the broker, an edit-time hook, a foreign orchestrator)
**refuses that write** — turning a `surviving silent` into a `prevented`. The
gate does not change `real_ships` (it never blocks a contained write — proven by
`test_scope_gate.py::test_gate_allow_matches_classify_in_scope`).

## What this slice ships (the throughline)

- **Kernel:** `dos.scope.gate(evidence, policy) -> ScopeGate` (pure) + `dos
  scope-gate` CLI verb (ALLOW=0 / SCOPE_CREEP=5 / WRONG_TARGET=6). Tests:
  `tests/test_scope_gate.py`, `tests/test_scope_gate_cli.py`.
- **Job:** `scripts/commit_broker.py` routes its pre-apply fence through the
  kernel gate behind `JOB_COMMIT_BROKER_KERNEL_GATE` (default OFF → byte-identical;
  ON → the broker's refusal IS the kernel's binding verdict, with the typed
  SCOPE_CREEP / WRONG_TARGET distinction). Parity proven by
  `tests/test_commit_broker.py::test_kernel_gate_parity`.

## Monitor (TOMB-at-impl+monitor)

The CI invariant attached to this slice: `test_scope_gate.py` (the gate's
verdict→decision map + purity) and `test_commit_broker.py::test_kernel_gate_*`
(parity + the opt-in's byte-identical default). The gate is enablement-complete
the moment the broker can flip the flag on its one write path — which it can. The
research tail (general write-set prediction — the Calvin/OLLP reconnaissance
problem, docs/90 §1–§2) stays open and is explicitly NOT in this slice: the gate
enforces the *already-declared* tree, it does not predict the write-set.

## Re-measure

`cd dos && PYTHONPATH=src python -m benchmark.fleet_horizon.harness
--orchestrator-sweep` (git-per-phase, slow on Windows) regenerates the
prevented/detected/silent table. The shape (silent overwrites → 0 with the gate
engaged, growing monotonically without it) is the load-bearing, version-robust
claim.
