"""Tests for the F2 STEP 1 natural-collision predictor (docs/245).

Deterministic — uses synthetic task-like objects, never the live tau2 load (which is
slow and may be absent in CI). Pins the entity extraction + the GO/KILL verdict logic
+ the contention-site ordering that feeds the live run.
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from types import SimpleNamespace

from benchmark.agentprocessbench.writeadmit.natural_collisions import (
    NaturalCollisionReport, task_entities,
)


def _task(tid, *entity_ids, arg="reservation_id"):
    """A minimal stand-in for a tau2 Task: id + evaluation_criteria.actions whose
    arguments name reservation ids."""
    actions = [SimpleNamespace(arguments={arg: e}) for e in entity_ids]
    ec = SimpleNamespace(actions=actions)
    return SimpleNamespace(id=tid, evaluation_criteria=ec)


def test_task_entities_extracts_reservation_ids():
    t = _task("7", "ABC123", "XYZ999")
    assert task_entities(t) == {"ABC123", "XYZ999"}


def test_task_entities_empty_when_no_actions():
    t = SimpleNamespace(id="1", evaluation_criteria=SimpleNamespace(actions=[]))
    assert task_entities(t) == set()
    t2 = SimpleNamespace(id="2", evaluation_criteria=None)
    assert task_entities(t2) == set()


def test_task_entities_reads_confirmation_id_too():
    t = _task("3", "CONF1", arg="confirmation_id")
    assert task_entities(t) == {"CONF1"}


def _measure_synthetic(tasks) -> NaturalCollisionReport:
    """Re-derive the report off synthetic tasks WITHOUT importing tau2 (mirrors
    measure()'s pure core)."""
    ent_by_task = {str(t.id): task_entities(t) for t in tasks}
    naming = {tid: ents for tid, ents in ent_by_task.items() if ents}
    pairs = list(itertools.combinations(naming.items(), 2))
    colliding = [(a, b) for (a, ea), (b, eb) in pairs if ea & eb]
    rate = (len(colliding) / len(pairs)) if pairs else 0.0
    by_entity = defaultdict(set)
    for tid, ents in naming.items():
        for e in ents:
            by_entity[e].add(tid)
    contended = {e: sorted(ts) for e, ts in by_entity.items() if len(ts) >= 2}
    return NaturalCollisionReport(
        domain="synthetic", n_tasks=len(tasks), n_tasks_naming_entity=len(naming),
        n_entity_naming_pairs=len(pairs), n_naturally_colliding_pairs=len(colliding),
        natural_pairwise_rate=round(rate, 4), n_contended_entities=len(contended),
        contention_sites=contended, verdict="GO" if contended else "KILL",
    )


def test_go_when_two_tasks_share_an_entity():
    tasks = [_task("a", "R1"), _task("b", "R1"), _task("c", "R2")]
    rep = _measure_synthetic(tasks)
    assert rep.verdict == "GO"
    assert rep.n_contended_entities == 1
    assert rep.contention_sites["R1"] == ["a", "b"]
    # 3 entity-naming pairs (a-b, a-c, b-c); only a-b collides
    assert rep.n_entity_naming_pairs == 3
    assert rep.n_naturally_colliding_pairs == 1


def test_kill_when_no_entity_shared():
    tasks = [_task("a", "R1"), _task("b", "R2"), _task("c", "R3")]
    rep = _measure_synthetic(tasks)
    assert rep.verdict == "KILL"
    assert rep.n_contended_entities == 0
    assert rep.n_naturally_colliding_pairs == 0


def test_contention_degree_counts_distinct_tasks():
    # R1 touched by 3 distinct tasks -> a degree-3 contention site.
    tasks = [_task("a", "R1"), _task("b", "R1"), _task("c", "R1"), _task("d", "R2")]
    rep = _measure_synthetic(tasks)
    assert rep.contention_sites["R1"] == ["a", "b", "c"]
    # pairs among {a,b,c,d}: 6; colliding (share R1): a-b,a-c,b-c = 3
    assert rep.n_naturally_colliding_pairs == 3
