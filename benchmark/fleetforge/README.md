# FleetForge — the live-magnitude, skill-as-treatment coordination A/B

> **The benchmark that scores the DOS *skills*, not the syscalls — with real LLM
> agents, on the proven axis (coordination/velocity at horizon × fanout), on the
> *consumer's* denominator (collisions averted, review-hours skipped), and with a
> falsifier that drives the gap → 0 where coordination is impossible.**

Every prior DOS benchmark proved its half and left the same gap:

| Prior benchmark | Proved | Left open |
|---|---|---|
| **FleetHorizon** | the coordination *mechanism* (real kernel, real git, consumer denominators, falsifiers that fire) | **live magnitude** — agents are *simulated* (`lie_rate=0.12`); the unit-under-test is the *syscalls in a hand-coded loop*, never the **skills** |
| **EnterpriseOps-Gym / intervention ladder** | first live multi-arm A/B; WARN +6.2pp | single-agent, **defensive-lift denominator** (the dead axis) |
| **Toolathlon replay** | DETECT generalizes to a third-party oracle (98% precision) | DETECT-only, single-agent, **vanishes on strong models** |
| **Natural-thrash rewind** | PLACEMENT is sound; the causal-shape law | **conversion refuted** — agent-next-action rungs are wash-to-negative |

FleetForge closes **the one open gap**: the *live magnitude* of the coordination
win, with *real LLMs*, scored on the *consumer denominator*, with the *shipped
skills* (`dos-dispatch` / `dos-dispatch-loop` / `dos-supervise-loop`) as the
treatment. It was always deferred for one concrete reason — **no instrument
existed to attribute a live delta to the skill verbs rather than to model luck.**
That instrument (`skill_adherence.py`) is the keystone, and it is built first.

## What it does NOT do (the rails)

It honors every "must-not" from the prior-art ledger:

- **No agent-pass-rate headline.** Defensive lift is refuted on the frontier
  (0.00pp). Pass-rate is reported only as a co-variate that must stay flat.
- **No verdict routed back to the agent's next action** (block/substitute/rewind —
  all wash-to-negative). The value path is a *non-agent denominator* + a
  non-blocking surface.
- **No simulated headline.** Simulated agents are the falsifier-control only.
- **No win at N=1.** That is the falsifier regime; the gap must vanish there.
- **No detection re-proof.** Detection is solved; this measures captured value.
- **No mint from a self-authored predicate.** Ground truth is git ancestry / a
  real merge conflict — byte-author ≠ judged agent.

## The arms (same model, same workload, same seed — DOS gets no better agent)

| Arm | What it is |
|---|---|
| **A_prose** | the plausible plain orchestrator: fan out workers, **believe** the `{shipped}` self-report, write whenever, no `dos` verbs. WAL stays empty. |
| **B_workflow** | a *strong* non-DOS orchestrator (a Claude Code Workflow). Distinguishes "DOS skills win" from "any structure wins." *Smoke uses a believing proxy; the live B arm shells a real Workflow.* |
| **C_dos_skills** | the shipped `dos-dispatch` discipline: **arbitrate-before-write**, **verify-before-bank**, **lease + heartbeat the WAL**. This *is* the `fleet_horizon.closed_loop` kernel path, so arm C drives the **real kernel, no mocks**. |
| **D_sim** | the seeded `FailureModel` — falsifier-control only, anchors live magnitudes; **never** a headline. |

## The keystone: `skill_adherence.py` (the missing attribution instrument)

A **pure** join over two byte-clean, agent-**un**-forgeable fossils — the
lane-journal WAL (`lane_journal.read_all`) and the git commit log — that
reconstructs, per effort, whether the skill's mandated verbs actually fired:

- `acquire_before_write` — an ACQUIRE for the lane precedes the first write
- `heartbeat` — a HEARTBEAT kept the lease alive
- `verify_before_bank` — every banked phase has a **real git commit** (the fact
  the oracle reads — **not** the agent's "I verified" narration)
- `release` — a RELEASE/SCAVENGE closed the lane

joined to the **coordination outcome** the same fossils show (cross-effort REFUSEs
= collisions prevented; banked-with-no-commit = a lie that slipped). The output
tuple `adherence ⟂ outcome` is what makes a live delta **attributable**: it
**refuses to credit the skills** for a delta the WAL shows the verbs never produced
(the prose arm can't clear the bar). The structural invariant — *it reads only
WAL + git, never a self-report channel* — is pinned by a test.

## Two value axes, kept apart (a finding the falsifier forced)

Building the disjoint falsifier surfaced a **metric conflation in FleetHorizon's
raw `refused_writes`**: it counts both *cross-effort* collisions (real
coordination prevention) **and** *same-effort* serialization (an effort contending
with its own in-flight lease across the concurrency window). The latter fires
**even on a genuinely disjoint workload**, so the disjoint gap would *not* vanish
if you scored raw refuses. FleetForge therefore counts **only cross-effort
refuses** as coordination value, and separates two booleans:

- **`coord_attributable`** — cross-effort prevention captured + verbs fired. This
  is the coordination headline, and it **must vanish** on the disjoint / N=1
  falsifier.
- **`attributable`** (broad) — *any* value captured (prevention OR clean banking).
  Verify-value (catching a lie) is real at **any** N, so this can stay True at N=1
  — correctly; the two axes have different falsifier regimes.

## Measured smoke result (deterministic, $0)

```
                   banked  lies caught xeff_prev review_frac  adher coord_attr
C_dos_skills           15     0      1         3       0.067   1.00       True
A_prose                16     1      0         0       1.000   0.19      False
disjoint falsifier:    C_dos_skills xeff_prev=0  coord_attr=False   (gap vanishes ✓)
N=1 falsifier:         C_dos_skills xeff_prev=0  coord_attr=False   (gap vanishes ✓)
```

Arm C prevents cross-effort collisions **attributably** and banks **0** lies while
the prose arm banks the lie and must human-review **everything**; and the
coordination gap **provably vanishes** on both falsifiers.

## The decision-relevant datum the live tier will resolve

> Do **real** LLM fleets on shared state collide / over-claim at a **measurable**
> rate — and does the skill arm capture it **attributably**?

Either answer is banked: a nonzero, attributably-prevented rate = *small-lift-that-
grows* → run the powered curve; a clean ~0 rate on a tractable workload = the
honest *harmless / correctly-silent* frontier null (`docs/177`) → report it.

## Build tiers (cheapest decision-relevant datum first)

- **Tier 0 ($0, gates CI) — SHIPPED.** `skill_adherence.py` + `test_fleetforge.py`
  (9 tests): the instrument is sound, reads only WAL+git, and the falsifiers fire.
- **Tier 2 (smoke) — SHIPPED (deterministic).** `run_smoke.py` runs the 3-arm
  scaffold and prints the two-axis scoreboard. The **live** worker (real CLIs,
  `DOS_LIVE=1`) is the Tier-3 follow-up — it spends tokens and is non-deterministic,
  so it never gates CI (same discipline as `fleet_horizon/live_demo.py`).
- **Tier 3 (pilot).** Swap the seeded worker for a real `gemini-2.5-flash` / `claude
  -p` worker; paired reps + bootstrap CIs over a swept (fanout × horizon ×
  contention) grid; charge the skills' own token/latency overhead in
  `verified_velocity_per_$`.
- **Tier 4 (credibility).** A real GitHub repo graded by **its own CI** + git-diff
  lost-write detection (un-riggable third-party ground truth); a small frontier
  capability-orthogonality spot-check.

## Files

```
benchmark/fleetforge/
  __init__.py            # the package banner
  skill_adherence.py     # THE keystone: WAL+git adherence ⟂ outcome instrument (pure)
  run_smoke.py           # the Tier-2 3-arm smoke (deterministic default; DOS_LIVE opt-in)
  test_fleetforge.py     # Tier-0 honesty tests (instrument sound, falsifiers fire)
  README.md              # this file
```

Reuses `fleet_horizon`'s `metrics.py` (the consumer-denominator battery, scored by
the **same** code so no per-arm scoring tilts the A/B), `workload.py`
(`generate` + `generate_disjoint`), `closed_loop.py` (arm C's real-kernel
mechanism), and `open_loop.py` (the believing baselines). It consumes the kernel
from outside — the same boundary as `examples/` — and is **not** in the kernel
release gate (`testpaths=["tests"]`).

## Running

```bash
# Tier-0 honesty gate ($0)
PYTHONPATH=src python -m pytest benchmark/fleetforge/test_fleetforge.py -q

# Tier-2 smoke (deterministic, $0) — the gap should open on contention
PYTHONPATH=src python -m benchmark.fleetforge.run_smoke --efforts 4 --phases 4 --shared-ratio 0.5

# the falsifiers — the coordination gap MUST vanish
PYTHONPATH=src python -m benchmark.fleetforge.run_smoke --efforts 4 --phases 4 --disjoint
PYTHONPATH=src python -m benchmark.fleetforge.run_smoke --efforts 1 --phases 4

# the full JSON report (per-effort adherence rows + attribution)
PYTHONPATH=src python -m benchmark.fleetforge.run_smoke --json
```
