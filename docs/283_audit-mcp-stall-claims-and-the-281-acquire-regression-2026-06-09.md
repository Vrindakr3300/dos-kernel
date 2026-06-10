# docs/283 — Audit: the MCP-stall root-cause claims, and a real regression the audit surfaced

> **Status:** AUDIT → **FIXED**.
> Date: 2026-06-09. Triggered by an operator goal asking to verify the "the `dos_verify` MCP call hung but the substrate is sound" claim against ground truth.
>
> **⚠ UPDATE (same day):** the regressing change was committed (`e69b636`)
> by a concurrent session and **shipped in release v0.18.1** (`70be1a3`, "phantom
> lane-lease self-heal") **while `test_coord_demo_k4_serializes_writes` was red on the
> committed mainline.** The finding below was written when the change was still
> uncommitted WIP; it became a *shipped* regression — "the red regression gate did
> not block a release."
>
> **✅ RESOLVED (same day):** the fix (option #2 below) landed — `acquire()`'s
> contention read reverts to the structural fold (`live_leases(config)`), while the
> long-lived admission hook (`pretool_sensor.py:306`) KEEPS `expire_dead=True` (its
> docs/281 self-heal is unaffected). There were exactly two `expire_dead=True` call
> sites; only `acquire()`'s — the one inside the serialization mutex — was wrong.
> `test_coord_demo_k4_serializes_writes` is now deterministic green (3/3), and the
> example + lease + arbiter + admission + hook suites (186 tests) stay green. The
> substrate IS now sound — by the suite, not by assertion. Released as the next
> scoped version.

## What was claimed

> "A live `dos_verify` MCP call hung — but the underlying syscall (`oracle.is_shipped`) is ~50 ms in-process / ~0.3 s via CLI, no git lock. The stall is the stdio-transport round-trip, not the kernel. The substrate is sound; don't block a session on a live MCP round-trip — the CLI is the deterministic ground truth."

This is exactly the genre of self-narration the kernel is built **not** to believe, so every clause was checked against a measurement or a test rather than taken at its word.

## Claim-by-claim verdict (measured, not narrated)

| Claim | Verdict | Evidence |
|---|---|---|
| `is_shipped` ≈ 50 ms in-process | ✅ **TRUE** | measured **48.0 ms/call** (5-call mean, warm), `oracle.is_shipped('docs/82_…','liveness')` → `shipped=True source=grep-subject` |
| `is_shipped` ≈ 0.3 s via CLI | ✅ **TRUE** | measured **332 ms** wall (`dos verify --workspace . docs/82_… liveness`) |
| "no git lock" in the syscall | ⚠️ **IMPRECISE** | the oracle DOES shell `git show`/`git log` (`oracle.py:516`, `:1355`, `:1522`) — each with a `timeout=`. On this **multi-session-hot tree** a peer's `git commit` transiently holds `.git/index.lock`, and those subprocesses *can* block on it. docs/282 itself names this as the real trigger. So "no git lock" is true for the *steady state*, not the *contended* case — and the contended case is the whole reason a deadline is needed. |
| "the stall is the transport, not the kernel" | ✅ **TRUE (for the verify path)** | CLI + in-process both finish fast; the hang was the unbounded MCP tool body. The docs/282 fix (already in the working tree) wraps each tool in a wall-clock deadline → typed `STALLED`. |
| "the substrate is sound" | ❌ **FALSE as stated** | the full kernel suite is **not green** right now: a real regression (below) reddens `test_hermes_integration_example.py::test_coord_demo_k4_serializes_writes`. The *verify substrate* is sound; the *tree as a whole* is not. |

**Net:** the MCP-stall diagnosis is essentially correct and the docs/282 fix is the right shape (tested, 36/36 MCP tests green incl. 5 new deadline tests). But "the substrate is sound" over-generalizes from one healthy syscall to the whole tree — and the whole tree currently has a green-suite regression that the audit found by actually running `pytest`, not by trusting the claim.

## The regression the audit surfaced (the real finding)

Running `python -m pytest tests/ -x` reproducibly fails at:

```
tests/test_hermes_integration_example.py::test_coord_demo_k4_serializes_writes
  LOST UPDATES on slot '42'     naive = 3   guarded = 1     # expected guarded = 0
  acquired = 2–3 (non-deterministic)                         # expected exactly 1
  refused  = 1–2                                             # expected 3
```

(A *second* test, `test_drivers_watchdog.py::test_discover_tracked_runs_from_live_leases`, flaked once in an early run but **passes in isolation and in the alphabetical prefix** — that one is the known hot-tree WAL flake, not a logic break.)

### Controlled A/B — the cause is the uncommitted `lane_lease.py` change

`src/dos/lane_lease.py` carries **+111 uncommitted lines**: the docs/281 Defect-1 fix (`_lease_is_dead` / `_expire_dead` + `live_leases(config, *, expire_dead=False)`). Stashing *only* that file and re-running the demo:

| Tree state | demo result (3 runs) |
|---|---|
| **clean HEAD** (lane_lease.py stashed) | `rc=0  acquired=1  refused=3  guarded=0` — deterministic, **passes** |
| **+ uncommitted lane_lease.py** | `rc=1  acquired=2–3  refused=1–2  guarded=1` — non-deterministic, **fails** |

So the docs/281 fix, as written, **introduced a serialization regression**.

### The mechanism (proven, not guessed)

The single load-bearing line is the new contention read in `acquire()`:

```python
# src/dos/lane_lease.py — acquire()
live = live_leases(config, expire_dead=True) + extra   # was: live_leases(config) + extra
```

The intent is right (docs/281: a crashed worker's phantom lease must not block a fresh acquire). But `expire_dead=True` runs `_lease_is_dead` over the contention set, and signal **(b)** is *"dead PID on this host → drop the lease."* In the coordination demo each guarded agent shells its **own short-lived child `dos lease-lane acquire` process** (`hermes_adapter.acquire_lease` → `_run_dos`), which:

1. journals its ACQUIRE stamped with **its own child PID** + this host, then
2. **returns and the child process exits.**

When a *peer* agent's child then runs the `expire_dead=True` contention read, it `proc_delta.probe`s the sibling's **already-exited** PID → `alive=False` → the still-logically-held region is judged **dead** and elided → the peer **acquires the same region** → both `book()` → a **lost update**. Single-threaded acquire is fine (I instrumented it: a fresh lease with a live PID survives, `live(expire_dead=True)=1`); the misfire needs the concurrent, **process-per-agent** race the demo creates.

### Why this matters

This is the canonical TOCTOU the kernel exists to prevent, now living **inside DOS's own coordination guarantee** — and the worked example (`examples/hermes_integration/`, docs/278) is the witness that caught it, exactly as designed ("a claim isn't shipped until a witness pins it"). The PID-liveness signal conflates *"the process that wrote the journal line has exited"* with *"the lease is abandoned"* — false when leases are held by ephemeral processes whose effect (the booking) outlives the process.

## Recommended fix (for the docs/281 author — not applied here)

The audit is read-only; this is the design steer, not a landed change:

1. **Do not apply PID-liveness (signal b) inside the acquire contention read for a same-host lease whose holder process can legitimately have exited.** A lease's PID being gone is only *confidently* abandonment when the lease's own lifecycle says the holder should still be running (a heartbeat is overdue). Gate signal (b) behind the **TTL/heartbeat** rung (signal a), or require *both* (overdue heartbeat AND dead PID), so a fresh lease whose journaling subprocess exited is never reaped.
2. Alternatively, keep `expire_dead=True` for the **admission-hook read** (the docs/281 target — long-lived interactive sessions, where a dead PID + no fresh tool activity really is a phantom) but **leave `acquire()`'s contention read on the structural fold** (`expire_dead=False`), so the durable serialization the demo relies on is unchanged. The phantom-lane hook bug and the acquire race want *different* live-set views; coupling them through one `expire_dead` flag is what broke serialization.
3. Whatever the fix: **`test_coord_demo_k4_serializes_writes` is the regression gate** — it must be green (deterministic `guarded=0`, `acquired=1`, `refused=3`) before the docs/281 change is committed. It already encodes the property; it just needs to pass.

## One-line takeaway

The MCP-stall story checks out and its fix is sound — but "the substrate is sound" was the one unverified clause, and running the suite (instead of believing it) surfaced a real serialization regression in the docs/281 fix: applying dead-PID expiry inside the acquire contention read double-books a region when leases are held by short-lived processes. The kernel's own worked example caught it — and the change still shipped in v0.18.1 with the regression gate red. **Don't certify "sound" from one fast syscall; let the suite be the witness — including at release.**
