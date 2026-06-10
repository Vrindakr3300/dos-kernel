"""F2 STEP 1 ($0) — the NATURAL collision predictor that kills (or justifies) the
live fleet build.

docs/245 NEXT-B STEP 1. The live coordination A/B (`coord_loop.run_coord_live`) PINS
two agents to the same reservation id (`coord_loop.py:254`, "pinning both agents to
the same reservation id") — a CONSTRUCTED conflict, which is exactly objection O2
("your collisions are constructed, not natural"). Before spending ~$10 on the live
K-agent run, answer the $0 question off the REAL task distribution:

    do independent tau2 tasks NATURALLY target the same entity, and at what rate?

If NO task pair ever shares an entity, the live build is pointless → kill it. If they
do, the natural contention sites are the conflict pairs the live run should draw
from, and the natural pairwise rate is the empirical analogue of FleetHorizon's
hardcoded `shared_ratio` (the docs/243 Track A move, here on tau2 DB entities instead
of file paths).

THE WITNESS (the agent authors none of it): a task's GOLD ACTIONS
(`evaluation_criteria.actions`) name the entity each task touches via the
`reservation_id` argument — authored by the benchmark, not the agent. Two tasks that
name the same reservation are a natural contention site; the fraction of entity-naming
task pairs that share an entity is the natural pairwise collision rate.

MEASURED (airline, 2026-06-08): 50 tasks, 35 name an entity, 595 entity-naming pairs,
14 naturally collide → 2.35% natural pairwise rate; 18 entities touched by ≥2 distinct
tasks. A GO: collisions fall out of the distribution, not a pin.

$0, read-only — loads the task definitions, no model, no env mutation, no network.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict


def _ensure_tau2_importable() -> None:
    """Put tau2 on sys.path. Prefers TAU2_PATH, then the known local clone, then
    assumes it is already installed (the live harness's convention)."""
    candidates = []
    if os.environ.get("TAU2_PATH"):
        candidates.append(os.environ["TAU2_PATH"])
    candidates += [
        # Point TAU2_PATH at your tau2-bench checkout's `src/` (above). These are
        # generic home-relative / root-relative fallbacks; set the env var for any
        # other location.
        os.path.expanduser("~/work/tau2-bench/src"),
        "/work/tau2-bench/src",
    ]
    for c in candidates:
        if os.path.isdir(c) and c not in sys.path:
            sys.path.insert(0, c)
            return
    # else: assume importable as installed; the import will raise a clear error.


# the entity-naming arguments a tau2 task's gold actions can carry. A DB entity is a
# path-like region the arbiter leases (`reservations/<id>`), so two tasks naming the
# same id are a real contention site.
_ENTITY_ARGS = ("reservation_id", "confirmation_id")


def task_entities(task) -> set[str]:
    """The set of DB entities a task's GOLD ACTIONS touch — the unforgeable
    fingerprint of which region the task contends for (authored by the benchmark)."""
    ents: set[str] = set()
    ec = getattr(task, "evaluation_criteria", None)
    if ec is None:
        return ents
    for action in (getattr(ec, "actions", None) or []):
        args = getattr(action, "arguments", None) or {}
        if isinstance(args, dict):
            for key in _ENTITY_ARGS:
                if args.get(key):
                    ents.add(str(args[key]))
    return ents


@dataclass(frozen=True)
class NaturalCollisionReport:
    domain: str
    n_tasks: int
    n_tasks_naming_entity: int
    n_entity_naming_pairs: int
    n_naturally_colliding_pairs: int
    natural_pairwise_rate: float
    n_contended_entities: int  # entities touched by >=2 distinct tasks
    contention_sites: dict  # entity -> sorted task ids (the live-run conflict candidates)
    verdict: str  # GO | KILL
    note: str = ""


def measure(domain: str = "airline") -> NaturalCollisionReport:
    _ensure_tau2_importable()
    from tau2.run import get_tasks

    tasks = get_tasks(domain)
    ent_by_task = {str(t.id): task_entities(t) for t in tasks}
    naming = {tid: ents for tid, ents in ent_by_task.items() if ents}

    pairs = list(itertools.combinations(naming.items(), 2))
    colliding = [(a, b) for (a, ea), (b, eb) in pairs if ea & eb]
    rate = (len(colliding) / len(pairs)) if pairs else 0.0

    by_entity: dict[str, set[str]] = defaultdict(set)
    for tid, ents in naming.items():
        for e in ents:
            by_entity[e].add(tid)
    contended = {e: sorted(ts) for e, ts in by_entity.items() if len(ts) >= 2}

    verdict = "GO" if contended else "KILL"
    note = (
        "collisions fall out of the real task distribution (not pinned) — the live "
        "F2 run should draw its conflict pairs from contention_sites, killing O2."
        if contended else
        "NO entity is touched by >=2 tasks — the live fleet build cannot produce a "
        "NATURAL collision; kill it (or pick a domain whose tasks contend)."
    )
    return NaturalCollisionReport(
        domain=domain, n_tasks=len(tasks), n_tasks_naming_entity=len(naming),
        n_entity_naming_pairs=len(pairs), n_naturally_colliding_pairs=len(colliding),
        natural_pairwise_rate=round(rate, 4), n_contended_entities=len(contended),
        contention_sites=contended, verdict=verdict, note=note,
    )


def contended_reservation_ids(domain: str = "airline") -> list[str]:
    """The reservation ids the live coord run should use as NATURAL conflict pairs —
    the drop-in replacement for `coord_loop.run_coord_live`'s `res_ids[:pairs]` pin.
    Ordered by contention degree (most-contended first)."""
    report = measure(domain)
    return sorted(report.contention_sites, key=lambda e: -len(report.contention_sites[e]))


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="F2 STEP 1 — natural collision predictor ($0)")
    ap.add_argument("--domain", default="airline")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", type=int, default=20, help="show this many contention sites")
    args = ap.parse_args(argv)

    report = measure(args.domain)
    if args.json:
        print(json.dumps(asdict(report), indent=2))
        return 0 if report.verdict == "GO" else 1

    print(f"=== F2 STEP 1 — natural collision rate ({args.domain}) ===")
    print(f"  tasks                         {report.n_tasks}")
    print(f"  tasks naming an entity        {report.n_tasks_naming_entity}")
    print(f"  entity-naming task pairs      {report.n_entity_naming_pairs}")
    print(f"  NATURALLY colliding pairs     {report.n_naturally_colliding_pairs}")
    print(f"  natural pairwise rate         {report.natural_pairwise_rate:.2%}")
    print(f"  contended entities (>=2 tasks){report.n_contended_entities}")
    print(f"  VERDICT                       {report.verdict}")
    print(f"  {report.note}")
    if report.contention_sites:
        print(f"\n--- natural contention sites (the live-run conflict pairs) ---")
        ordered = sorted(report.contention_sites.items(), key=lambda kv: -len(kv[1]))
        for ent, ts in ordered[:args.show]:
            print(f"  {ent}: tasks {ts}")
    return 0 if report.verdict == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
