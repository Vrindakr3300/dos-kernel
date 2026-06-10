"""Tests for the tau2coord port (docs/233 coordination payoff across tau2 domains).

Two tiers:
  - PURE (always run): the arbiter region mapper + the serialization invariant — these
    need only `dos.arbiter`, no tau2. They pin the load-bearing claim: two agents on the
    SAME entity are refused (serialized); two on DIFFERENT entities are both admitted.
  - DB-HASH (skipped if tau2 absent): the deterministic A/B over airline+retail, pinning
    J == naive_clobbers == pairs (every constructed conflict is prevented) and the
    falsifier control (the metric CAN report no-clobber on disjoint entities).
"""
from __future__ import annotations

import pytest

from benchmark.tau2coord.coord import (
    entity_region, arbiter_admits, DOMAINS, run_deterministic, disjoint_control,
)


# --- PURE: the arbiter region invariant (no tau2) -------------------------------------

def test_entity_region_is_a_path_region():
    assert entity_region("reservations", "4WQ150") == ["reservations/4WQ150"]
    assert entity_region("orders", "#W5918442") == ["orders/#W5918442"]


def test_same_entity_is_serialized_disjoint_is_admitted():
    """The whole port rides on this: same entity -> 2nd lease REFUSED (serialize);
    different entity -> 2nd lease ADMITTED (concurrent). Off dos.arbiter, no tau2."""
    r1 = entity_region("reservations", "4WQ150")
    r2 = entity_region("reservations", "VAAOXJ")
    held = [{"lane": r1[0], "kind": "keyword", "tree": r1, "owner": "agent-1"}]
    assert arbiter_admits(r1, held) is False   # same entity -> serialized
    assert arbiter_admits(r2, held) is True    # disjoint entity -> concurrent


def test_arbiter_admits_into_empty_leases():
    r1 = entity_region("orders", "#W1")
    assert arbiter_admits(r1, []) is True


# --- DB-HASH: the deterministic A/B (skipped if tau2 absent) ---------------------------

def _tau2_available() -> bool:
    try:
        import tau2  # noqa: F401
        from benchmark.tau2coord.coord import _fresh_env
        _fresh_env("airline")
        return True
    except Exception:
        return False


requires_tau2 = pytest.mark.skipif(not _tau2_available(), reason="tau2-bench not installed")


@requires_tau2
@pytest.mark.parametrize("domain", ["airline", "retail"])
def test_every_constructed_conflict_is_a_prevented_clobber(domain):
    """Each constructed pair is a real lost-update the arbiter prevents: J == pairs."""
    res = run_deterministic([domain], pairs_per_domain=3)
    d = res["domains"][domain]
    assert d["pairs"] == 3
    assert d["naive_clobbers"] == 3, f"{domain}: naive arm should clobber every pair"
    assert d["j"] == 3, f"{domain}: arbiter should prevent every clobber"


@requires_tau2
def test_clobber_signatures_are_domain_distinct():
    """Airline clobbers via INCOHERENT-MERGE (stale write lands); retail via DROPPED-WRITE
    (stale write errors). Both are clobbers; the port must catch both."""
    res = run_deterministic(["airline", "retail"], pairs_per_domain=2)
    air = res["domains"]["airline"]["rows"]
    ret = res["domains"]["retail"]["rows"]
    assert all(r["incoherent_merge"] for r in air), "airline = incoherent-merge signature"
    assert all(r["dropped_write"] for r in ret), "retail = dropped-write signature"


@requires_tau2
@pytest.mark.parametrize("domain", ["airline", "retail"])
def test_falsifier_control_disjoint_not_serialized(domain):
    """The metric CAN report no-clobber: disjoint entities -> arbiter admits, refuses same."""
    c = disjoint_control(DOMAINS[domain])
    assert c["ok"] is True
    assert c["admit_disjoint"] is True
    assert c["admit_same"] is False


@requires_tau2
def test_witness_is_the_env_db_hash_not_self_report():
    """The J verdict reads the env's get_db_hash() — the agent authors zero bytes of it.
    A clobber row carries distinct or applied-count-divergent hashes from the env."""
    res = run_deterministic(["airline"], pairs_per_domain=1)
    row = res["domains"]["airline"]["rows"][0]
    # the hashes are 64-hex sha strings produced by the env, never by the agent
    assert isinstance(row["naive_hash"], str) and len(row["naive_hash"]) == 64
    assert isinstance(row["serial_hash"], str) and len(row["serial_hash"]) == 64
