"""The fleet workload — N concurrent long-horizon efforts on shared state.

A *workload* is the thing both arms run. It is generated deterministically from a
seed so the open-loop and closed-loop arms execute the **same** work in the
**same** order with the **same** simulated failures — the honesty invariant
(`README.md` §honesty): DOS does not get a different agent, it gets the same
agent and a kernel that refuses to believe it.

Shape (the fleet × horizon geometry):

  * `efforts`  — N concurrent long-horizon "issues" (the fleet). Each is the unit
                 a single-PR benchmark would score in isolation; here they run at
                 once on one repo.
  * `phases`   — M sequential phases per effort (the horizon). Phase k+1 depends
                 on phase k landing — the long-horizon dependency that makes a
                 lie in phase k corrupt everything after it.
  * file tree  — each phase touches a set of files. Most files are private to an
                 effort, but a tunable `shared_ratio` of phases reach into a
                 SHARED area (`shared/…`) — that is where concurrent efforts
                 collide, the thing the arbiter is for.

Nothing here is DOS-specific: a workload is plain data. The arms decide what to
*do* with it (believe vs verify).
"""
from __future__ import annotations

import dataclasses
import random
from typing import Iterator


# A phase is one unit of work in an effort's horizon. `touches` is its file-tree
# footprint (paths relative to the repo root) — the arbiter reasons over these.
@dataclasses.dataclass(frozen=True)
class Phase:
    effort: str          # which effort this belongs to (e.g. "effort-03")
    index: int           # 0-based position in the effort's horizon
    phase_id: str        # the (plan, phase) key the oracle verifies, e.g. "E03.07"
    touches: tuple[str, ...]   # files this phase writes
    reaches_shared: bool       # True iff it writes into the shared area


@dataclasses.dataclass(frozen=True)
class Effort:
    name: str
    lane: str             # the lane this effort leases (its private subtree)
    phases: tuple[Phase, ...]


@dataclasses.dataclass(frozen=True)
class Workload:
    seed: int
    efforts: tuple[Effort, ...]
    shared_ratio: float

    @property
    def n_efforts(self) -> int:
        return len(self.efforts)

    @property
    def n_phases_each(self) -> int:
        return len(self.efforts[0].phases) if self.efforts else 0

    @property
    def total_phases(self) -> int:
        return sum(len(e.phases) for e in self.efforts)

    def all_phases(self) -> list[Phase]:
        return [p for e in self.efforts for p in e.phases]

    def phase_key(self, p: Phase) -> tuple[str, str]:
        """The (plan, phase) pair the oracle verifies — effort name + phase id."""
        return (p.effort, p.phase_id)


def generate(
    *,
    seed: int,
    efforts: int,
    phases: int,
    shared_ratio: float = 0.25,
    files_per_phase: int = 2,
) -> Workload:
    """Build a deterministic fleet workload.

    `shared_ratio` is the fraction of phases (across the fleet) that reach into
    the shared area — the collision surface. At `efforts=1` there is no one to
    collide with, so the shared reaches are harmless; the collision *cost* only
    materializes as the fleet widens, which is the monotonicity the benchmark
    is built to show.
    """
    rng = random.Random(seed)
    built: list[Effort] = []

    # A small pool of shared files every effort can reach into — the contended
    # resource. Kept small so wide fleets genuinely contend (realistic: shared
    # config, a registry file, a schema, a common util).
    shared_pool = [f"shared/resource_{i}.txt" for i in range(max(2, efforts // 2))]

    for e in range(efforts):
        effort_name = f"effort-{e:02d}"
        lane = f"lane-{e:02d}"          # each effort's private lane / subtree
        phase_list: list[Phase] = []
        for k in range(phases):
            # phase id like "E03.07" — the (plan, phase) key the oracle checks.
            phase_id = f"E{e:02d}.{k:02d}"
            reaches_shared = rng.random() < shared_ratio
            touches: list[str] = []
            # private files under the effort's own subtree
            for _ in range(files_per_phase):
                fid = rng.randrange(1000)
                touches.append(f"{effort_name}/mod_{fid}.txt")
            # sometimes also reach into the shared pool — the collision surface
            if reaches_shared and shared_pool:
                touches.append(rng.choice(shared_pool))
            phase_list.append(
                Phase(
                    effort=effort_name,
                    index=k,
                    phase_id=phase_id,
                    touches=tuple(touches),
                    reaches_shared=reaches_shared,
                )
            )
        built.append(Effort(name=effort_name, lane=lane, phases=tuple(phase_list)))

    return Workload(seed=seed, efforts=tuple(built), shared_ratio=shared_ratio)


def generate_disjoint(*, seed: int, efforts: int, phases: int,
                      files_per_phase: int = 2) -> Workload:
    """A GENUINELY pairwise-disjoint workload — the orchestrator-axis falsifier.

    `generate(shared_ratio=0)` is NOT collision-free: its private files are picked
    by `rng.randrange(1000)`, so two phases in one effort can land on the same file
    (a birthday collision the arbiter legitimately refuses). To prove the boundary
    claim — "when footprints are truly disjoint, the orchestrator choice is moot:
    a harness `parallel()` is exactly as safe as DOS-native dispatch" (docs/98) —
    we need a workload where NO two phases share a file at all. This builds that:
    every phase gets uniquely-numbered files under its own effort subtree, no shared
    pool, no repeats. The arbiter then never refuses, lease visibility is irrelevant,
    and every orchestrator produces a byte-identical ledger. Used by
    `test_orchestrator_gap_vanishes_when_disjoint`.
    """
    built: list[Effort] = []
    uid = 0
    for e in range(efforts):
        effort_name = f"effort-{e:02d}"
        lane = f"lane-{e:02d}"
        phase_list: list[Phase] = []
        for k in range(phases):
            touches = []
            for _ in range(files_per_phase):
                touches.append(f"{effort_name}/uniq_{uid:06d}.txt")
                uid += 1
            phase_list.append(Phase(
                effort=effort_name, index=k, phase_id=f"E{e:02d}.{k:02d}",
                touches=tuple(touches), reaches_shared=False))
        built.append(Effort(name=effort_name, lane=lane, phases=tuple(phase_list)))
    return Workload(seed=seed, efforts=tuple(built), shared_ratio=0.0)


def interleave(workload: Workload, *, seed: int) -> Iterator[Phase]:
    """Yield phases in a realistic CONCURRENT interleaving.

    A fleet does not run effort-00 to completion then effort-01; the efforts make
    progress concurrently, so phases from different efforts interleave on the
    shared timeline. We preserve each effort's *internal* order (phase k before
    k+1 — the horizon dependency) but interleave across efforts by a seeded
    round-robin-with-jitter. This interleaving is what puts two efforts' shared
    reaches adjacent in time — i.e. what creates the collision *window*.
    """
    rng = random.Random(seed ^ 0x5EED)
    # per-effort cursor into its phase list; preserves intra-effort order
    cursors = {e.name: 0 for e in workload.efforts}
    remaining = {e.name: list(e.phases) for e in workload.efforts}
    active = [e.name for e in workload.efforts]
    while active:
        # pick a random active effort, advance it one phase (jittered round-robin)
        name = rng.choice(active)
        idx = cursors[name]
        phases = remaining[name]
        if idx >= len(phases):
            active.remove(name)
            continue
        yield phases[idx]
        cursors[name] += 1
        if cursors[name] >= len(phases):
            active.remove(name)
