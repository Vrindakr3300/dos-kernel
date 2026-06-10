# The orchestrator is a driver — ultracode and DOS-dispatch as comparable arms

> **DOS already splits *mechanism* (the trust syscalls) from *policy* (the loop
> around them). The orchestrator — the thing that fans out the work — is just
> another policy. So a harness/ultracode `Workflow` and DOS-native dispatch are
> two drivers of the *same* trust seam, and they can be measured against each
> other on one workload.**

This note is the **orchestrator axis** companion to
[`81`](81_velocity-economics-and-the-fleet-benchmark.md). Where `81` adds a second
*metric* axis (velocity) to the integrity A/B, this adds a second *structural*
axis: **who drives the fanout.** It answers a question an operator actually has —
*"can I lean on the Claude Code harness's `Workflow` tool (or any external
orchestrator) for the fanout, instead of DOS's own dispatch/loop, and keep the
trust guarantees?"* — and it ships the instrument that measures the answer rather
than asserting it.

The short version: **yes, for the fanout — but the one trust property that rides
on DOS *owning* the loop is collision-prevention, and it survives the swap only if
the foreign orchestrator writes its lane leases back to a shared, durable channel.**
DOS now ships that channel (`dos lease-lane`), and the benchmark now measures
exactly what is lost when an orchestrator skips it.

---

## 1. The frame — mechanism is already separate from the orchestrator

`CLAUDE.md`'s layering contract and [`79`](79_primitives-not-features.md) make one
rule: the kernel is the pure syscalls (`verify`/`refuse`/`arbitrate`/`liveness`),
and *what to do after a verdict* — replan, re-dispatch, fan out, soak — is **host
workflow, not kernel.** The reference dispatch (`dos-dispatch` skill), the
dispatch-loop, and the supervisor (`dos loop`) are DOS's *own* orchestration
policy occupying that slot. They are not the kernel; they are one driver of it.

A harness `Workflow` (the Claude Code tool whose primitives are
`agent()`/`parallel()`/`pipeline()`, informally "ultracode") is **another driver
of the same slot.** Nothing in the contract privileges DOS's own loop — the
kernel "never assumes it lives in the repo it serves," reads its policy from the
injected `SubstrateConfig`, and exposes every syscall over a zero-coupling MCP
surface (`80`). So a foreign orchestrator calling `dos verify`/`dos arbitrate` at
the seam is a *first-class, anticipated* consumer, not a hack.

The proof this already works is in the benchmark, not just the prose:
[`benchmark/fleet_horizon/closed_loop.py`](../benchmark/fleet_horizon/closed_loop.py)
is a **foreign for-loop** (not the dispatch skill) driving the real kernel at the
seam — and it preserves every trust property.
[`open_loop.py`](../benchmark/fleet_horizon/open_loop.py) is an orchestrator that
*skips* the seam — and loses all of them. The orchestrator axis simply makes that
contrast a measured variable instead of two fixed arms.

---

## 2. What is genuinely separable, and the one thing that is not

Audit the orchestration surface against the trust syscalls and it cleaves cleanly:

| DOS orchestration piece | Verdict | The trust property at stake |
|---|---|---|
| `verify()` / `oracle.is_shipped` at the bank step | **KEEP** | Non-self-report "done": shipped iff a real commit closes the phase. Any orchestrator must route the bank decision through it or it re-acquires the lie. Pure — a harness calls it via the CLI/MCP with zero DOS orchestration. |
| `arbitrate()` lane admission | **KEEP** | **Collision-PREVENTION**: serializes writes to intersecting file-sets so two cannot both land. This is the one property that depends on someone *holding the leases it reasons over* and *honoring the refuse*. |
| `gate` typed verdict | **HYBRID** | Evidence-over-narrative: the verdict is derived from git/stamp dispositions, not prose. A harness *branches* on the exit code; it must not re-derive the verdict from prose. |
| `loop_decide.decide()` | **HYBRID** | Distrust of a self-reported ship (`UNMEASURED_SHIPPED` stalls a claimed-but-unmeasured ship). The harness can own the loop body; the *stop decision* should stay the kernel's. |
| the fanout itself ("launch each pick as its own agent") | **REPLACE — with one constraint** | **None intrinsic** — pure scheduling. This is exactly what a harness `parallel()`/`pipeline()` does best. The constraint: it is replaceable only as *fanout that still passes each write through `arbitrate` and honors the refuse* — never as a free `parallel()` that just co-runs agents and hopes. |
| dispatch Steps 0/2/5 (config read, snapshot, archive), `dos top`, `dos decisions` | **REPLACE** | None — config read, rendering, read-only projection. (Archive must record the *verify* verdict, not the claim.) |

So the operator's instinct is right: **the fanout and the exact dispatch are
replaceable; the trust seam is not.** The subtle part is `arbitrate`. Unlike
`verify` (a stateless question a single agent can ask), `arbitrate`'s value is
*relational* — it refuses a write because it collides with **another lease that
must be visible**. DOS's own dispatch makes that visibility trivial: one process
threads the live-lease list forward. A harness `parallel()` whose branches are
separate processes has **no shared memory** — so without a durable channel, each
branch arbitrates against an empty view, both admit a colliding tree, and the
collision is **detected later by `verify`, not prevented at contention.** That is
strictly weaker, and it is the whole subtlety of the swap.

---

## 3. The fix: `dos lease-lane` — durable write-back over the *pure* arbiter

`arbitrate` is and must stay **pure** (state in, decision out, no I/O — the
property that makes a verdict replayable a year later). So the durability does
**not** go into `arbitrate`; it goes into a thin shell beside it:

```
dos lease-lane acquire --lane api --kind keyword --tree 'src/**' --owner wf-3
   # runs the PURE arbitrate against the live-lease set folded from the WAL;
   # on ACQUIRE, appends an ACQUIRE record to the lane-journal under a mutex.
   # exit 0 = acquire, 1 = refuse  (the verdict IS the exit code)
dos lease-lane live       # the live-lease set, reconstructed from the WAL (JSON)
dos lease-lane release --lane api --owner wf-3
```

This is the lock-manager half of **"harness = scheduler, DOS = lock-manager +
truth oracle."** A harness branch calls `dos lease-lane acquire` *before* it
writes; a sibling branch's next `acquire` folds the journal (the same channel
`dos lease-lane live` exposes) and sees the grant, so the colliding write is
refused at contention — recovering the in-process loop's guarantee across
processes. Implementation: [`src/dos/lane_lease.py`](../src/dos/lane_lease.py)
(the locked read-arbitrate-append; the arbiter is untouched), wired as
`dos lease-lane` in [`cli.py`](../src/dos/cli.py). It is a Layer-3 helper — a thin
shell over `arbiter` + `lane_journal`, naming no host, carrying no new admission
rule.

Live proof (separate OS processes, real git, real WAL): two writers contending on
`shared/config.txt` — the disciplined arm (`dos lease-lane` before each write)
lands **both** edits as their own commits (zero loss); the naive arm loses one to a
clobber. See
[`live_orchestrator_demo.py`](../benchmark/fleet_horizon/live_orchestrator_demo.py)
(`DOS_LIVE_DEMO=1`, no model tokens).

---

## 4. The benchmark: orchestrator × trust, and what it measures

The existing FleetHorizon A/B is *trust* (believe vs adjudicate). The new axis is
*orchestrator* (DOS-native dispatch vs harness/ultracode flow), crossed with it:

|  | believe | adjudicate |
|---|---|---|
| **DOS-dispatch** (in-process leases) | (A) ≈ `open_loop.py` | (B) = `closed_loop.py` |
| **harness-flow** (cross-process leases via the WAL) | (C) plain `agent({schema})` | **(D) NEW** |

**The 2×2 honestly collapses, and the collapse is itself the finding.** In the
*believe* column nobody calls `arbitrate`, so "in-process vs cross-process lease
visibility" has no call site to manifest — arm (A) and (C) produce the same ledger.
Run the believe column once as a control; the real experiment is **B vs D**. That
reduction *is* a result: **trust is the dominant axis; the orchestrator is a
second-order effect that only modulates how well the seam is fed (lease freshness),
never whether the verdict is correct.**

The instrument (no kernel change — consumes the kernel from outside, like the rest
of `benchmark/`):

- The orchestrator is a **pluggable driver** behind one shared loop body
  ([`orchestrator.py:run_fleet`](../benchmark/fleet_horizon/orchestrator.py)). The
  only thing the two drivers vary is the **lease-visibility model** — a `LeaseBook`
  seam with two implementations: `InProcessLeaseBook` (DOS-native, instant
  visibility) and `JournalLeaseBook` (harness-flow, shared only through the real
  WAL, with a `writeback` discipline knob).
  [`harness_loop.py`](../benchmark/fleet_horizon/harness_loop.py) is the harness
  arm; `closed_loop.py` stays the canonical DOS-native arm, and a test pins that
  `run_fleet` with the in-process book reproduces it exactly (the seam changed
  nothing).
- The **discriminator metric** is the prevented-vs-detected split: `refused_writes`
  (prevented at contention) vs the new `detected-collision` event (caught after the
  fact because the lease book lagged), with `prevention_rate` the headline. A
  detected-after collision can leave a surviving `silent-overwrite` that `verify`
  cannot undo — *you cannot un-clobber after the fact*.
- The **honesty invariants** (the same discipline, lifted to this axis, pinned in
  [`test_orchestrator.py`](../benchmark/fleet_horizon/test_orchestrator.py)): same
  seed → identical `real_ships` across every orchestrator (DOS gets no better
  agent), and `banked_lies == 0` in *both* adjudicate arms (`verify` catches lies
  regardless of who drove the fanout — the trust axis is orthogonal).

### 4.1 The measured result (`harness.py --orchestrator-sweep`, seed 1729)

Reproducible: `PYTHONPATH=src python -m benchmark.fleet_horizon.harness --orchestrator-sweep`.

**Prevented / detected / surviving-silent, as the fleet grows (horizon=20, shared_ratio=0.3):**

| fleet | DOS-native | harness +writeback | harness NO writeback |
|---:|---|---|---|
| 2 | 0 / 0 / 0 | 38 / 0 / 0 | 0 / **0** / **0** |
| 4 | 31 / 0 / 0 | 76 / 0 / 0 | 0 / **2** / **2** |
| 8 | 70 / 0 / 0 | 152 / 0 / 0 | 0 / **12** / **12** |
| 12 | 115 / 0 / 0 | 228 / 0 / 0 | 0 / **15** / **15** |

The naive harness's gap (detected-after collisions, each leaving a surviving silent
overwrite) **grows monotonically with the fleet**, exactly where contention bites.
DOS-native and the disciplined (write-back) harness prevent every collision
(`prevention_rate = 100%`); the naive harness's prevention **collapses to 0% the
moment contention appears** (fleet ≥ 4).

> *Why the disciplined harness shows MORE refusals than DOS-native (e.g. 152 vs 70
> at fleet 8): the durable WAL has no TTL-expiry, so a lease lingers until an
> explicit release where the in-process list drops it when its in-flight window
> elapses. The journal-backed arm is therefore MORE conservative — it over-refuses,
> which is safe (over-serialization never loses data). It is a faithful property of
> a durable cross-process channel, not a bug; a host that wants the tighter
> in-process behavior adds lease TTLs to the WAL fold.*

**Headline cell (8 efforts × 30 phases, shared_ratio=0.3):**

| | real ships | banked lies | prevention | detected | surviving silent |
|---|---:|---:|---:|---:|---:|
| DOS-native | 205 | 0 | 100% | 0 | 0 |
| harness +writeback | 205 | 0 | 100% | 0 | 0 |
| harness NO writeback | 205 | 0 | **0%** | **10** | **10** |

Identical `real_ships` and zero `banked_lies` across all three confirm the honesty
invariants; the naive harness alone regresses.

### 4.2 The honest falsifier (where every orchestrator ties)

A **genuinely disjoint workload** (`workload.generate_disjoint` — every phase's
footprint pairwise-disjoint, no shared pool): the arbiter never refuses a
cross-effort write, lease visibility is irrelevant, and **all three arms tie** —
`detected = 0`, `silent = 0`, identical `real_ships = 99`. The orchestrator axis's
gap → 0 where nothing contends, exactly as FleetHorizon's integrity gap → 0 at
horizon → 1. The benchmark proves its own boundary.

> Note the falsifier needs a *truly* disjoint workload, not `generate(shared_ratio=0)`
> — the latter still has within-effort birthday collisions on `randrange` file names,
> and same-lane self-serialization, both of which the arbiter legitimately refuses.
> The orchestrator-invariant quantity is `detected-collision` + surviving
> `silent-overwrite` (the *cross-effort shared-state* gap), not the raw refusal
> count, which includes that same-lane serialization equally in every arm.

---

## 5. Bottom line

- **Leaning on ultracode/`Workflow` for the fanout is a genuine win** when the
  workload is **disjoint** — independent efforts with non-intersecting footprints,
  run once and verified. There the harness's `parallel()`/`pipeline()` *is* the
  better orchestrator (it owns cadence and the subprocess hands cleanly), and the
  only DOS piece you still need is `dos verify` at the bank step so you don't
  believe self-reports. The disjoint falsifier (§4.2) is exactly this regime — name
  it as the win, not a loss.

- **It silently loses a trust property** the moment efforts **contend on a shared
  region** *and* the flow does not write its leases back: collision-PREVENTION
  degrades to collision-DETECTION-after-the-fact (and some collisions survive as
  silent overwrites verify cannot undo, §4.1). The loss is invisible in a demo
  (last-write-wins looks like success) and detonates downstream as the hand-merge
  the silent overwrite became (the bill `81` §2.2 prices).

- **The fix is one verb, already shipped:** `dos lease-lane`. A harness that calls
  it before each write recovers the in-process loop's guarantee — cell (D) reaches
  DOS-native integrity (§4.1, the `+writeback` column). So the honest
  recommendation is: **harness owns the fanout and the cadence; DOS owns the truth
  oracle (`verify`) and the lock manager (`arbitrate` via `dos lease-lane`); a flow
  that skips the write-back is trading a real, measurable safety property for
  convenience, and the sweep quantifies the trade.**

The deepest point is the one the 2×2 collapse makes: **the orchestrator is a
driver, and the trust kernel does not care which driver runs.** That is the
substrate thesis (`79`) seen from one rung up — not just "mechanism is the kernel,
the loop is policy," but "*two different loops, one external, are comparable on the
same kernel, and the kernel's guarantees are a property of the seam calls, not the
loop.*"

## See also

- [`81`](81_velocity-economics-and-the-fleet-benchmark.md) — the velocity axis; the
  cost model (human-review fraction, conflict κ) this note's metrics reuse.
- [`79`](79_primitives-not-features.md) — why remediation/orchestration is host
  concern and the syscalls stay small (the rung this note sits one above).
- [`89`](89_the-lane-is-a-region-lock.md) — `arbitrate` as a region-lock; the
  primitive `dos lease-lane` adds durability to.
- [`80`](80_mcp-server-surface.md) — the zero-coupling surface a non-Python
  orchestrator calls the seam through.
- [`benchmark/fleet_horizon/README.md`](../benchmark/fleet_horizon/README.md) — the
  instrument; the orchestrator arm is documented there too.
