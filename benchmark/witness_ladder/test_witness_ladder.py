"""Tests pinning the witness_ladder prototype (docs/261).

The benchmark's whole claim is a monotone J curve over witness strength with a
ZERO value at the forgeable floor. These tests pin exactly that, plus the
load-bearing discipline that the harness does NOT reimplement the kernel verdict —
it calls `dos.reward.admit`, so its buckets must equal the kernel's directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

# benchmark/ on sys.path (matches the `python -m benchmark.witness_ladder.*` launch
# and the other benchmarks' test convention).
_BENCH = str(Path(__file__).resolve().parents[1])
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from witness_ladder.harness import (
    run_ladder, run_rung, _readback_at_rung, _rung_reaches, RUNG_AXIS,
)
from witness_ladder.workload import (
    Task, default_tasks, DEFAULT_MIX, BUILDABLE_WANTS, IRREDUCIBLE_WANTS,
    WANT_STATE_INVARIANT, WANT_JUDGE, WANT_PROVIDER_LEDGER, WANT_PRESENCE,
)

from dos import reward
from dos.evidence import EvidenceFacts
from dos.log_source import Accountability


# ---------------------------------------------------------------------------
# The headline curve.
# ---------------------------------------------------------------------------
def test_J_is_zero_at_the_forgeable_floor():
    """THE FALSIFIER: value vanishes at AGENT_AUTHORED. If the gate ever purged a
    poison off the forgeable floor, it would be acting on a byte the agent authored
    — the whole curve would be measuring a bug. J(floor) == 0 is structural."""
    res = run_ladder()
    floor = res.rungs[0]
    assert floor.rung == Accountability.AGENT_AUTHORED.value
    assert floor.J == 0
    assert floor.accept == 0           # nothing admitted on a forgeable witness either
    assert floor.abstain_band == 1.0   # every claim-bearing task abstains at the floor


def test_J_rises_monotonically_with_witness_strength():
    """The value arm: J never decreases as the witness gets less forgeable."""
    res = run_ladder()
    js = [r.J for r in res.rungs]
    assert js == sorted(js), f"J not monotone non-decreasing: {js}"
    assert js[0] == 0                  # floor
    assert js[-1] >= js[0] + 1         # strictly grows by the top rung (the distribution has poison)


def test_abstain_band_shrinks_as_witness_strengthens():
    """The growth edge closing: the abstain band is non-increasing up the ladder."""
    res = run_ladder()
    bands = [r.abstain_band for r in res.rungs]
    assert bands == sorted(bands, reverse=True), f"abstain band not non-increasing: {bands}"


def test_admit_precision_is_perfect_at_every_rung():
    """Floor discipline: an ACCEPT requires a non-forgeable CONFIRM, so every admit
    is genuinely true — precision is 1.0 at every rung (never admits an over-claim)."""
    res = run_ladder()
    for r in res.rungs:
        assert abs(r.admit_precision - 1.0) < 1e-9, (r.rung, r.admit_precision)
        # and concretely: no over-claim is ever ACCEPTed at any rung
        assert r.honest_true_admitted == r.accept


def test_top_rung_abstain_band_is_exactly_the_irreducible_slice():
    """The deep result: at the strongest deterministic rung, the ONLY remaining
    abstains are the irreducible (judge-only) tasks. DOS witnesses everything a
    deterministic witness can reach; the residue is the ORACLE->JUDGE->HUMAN ladder."""
    res = run_ladder()
    top = res.rungs[-1]
    assert set(top.abstain_by_want) <= IRREDUCIBLE_WANTS
    # every buildable want has been converted away by the top rung
    assert all(w not in top.abstain_by_want for w in BUILDABLE_WANTS)


# ---------------------------------------------------------------------------
# The roadmap (the "where DOS grows into" artifact).
# ---------------------------------------------------------------------------
def test_roadmap_separates_buildable_from_irreducible():
    res = run_ladder()
    rm = res.roadmap()
    assert rm["floor_rung"] == Accountability.AGENT_AUTHORED.value
    # the buildable band is non-empty (there is growth to do) and excludes judge
    assert rm["buildable_total"] > 0
    assert all(w in BUILDABLE_WANTS for w in rm["buildable_band"])
    # the irreducible band is exactly the judge tasks
    assert all(w in IRREDUCIBLE_WANTS for w in rm["irreducible_band"])
    # the floor band fully decomposes: buildable + irreducible == all claim-bearing abstains
    assert rm["buildable_total"] + rm["irreducible_total"] == res.rungs[0].abstain


def test_roadmap_total_matches_floor_abstain():
    """No abstaining task is lost from the roadmap: the decomposition is exhaustive."""
    res = run_ladder()
    rm = res.roadmap()
    floor = res.rungs[0]
    counted = sum(rm["buildable_band"].values()) + sum(rm["irreducible_band"].values())
    assert counted == floor.abstain == floor.claim_bearing  # all claims abstain at the floor


# ---------------------------------------------------------------------------
# The discipline: the harness CALLS the kernel, never reimplements it.
# ---------------------------------------------------------------------------
def test_harness_verdict_equals_the_kernel_directly():
    """For a refuting witness at each rung, the harness's bucketing must agree with
    a DIRECT `dos.reward.admit` call — proving the harness does not re-encode the
    belief rule. This is the kernel-not-reimplemented pin (the one-way-arrow's
    semantic half)."""
    # a present over-claim (claim true, effect false) with a refuting witness
    over = Task("x", claim_present=True, effect_true=False, wants_witness=WANT_STATE_INVARIANT)
    for rung in RUNG_AXIS:
        rb = _readback_at_rung(over, rung)
        direct = reward.admit(True, (rb,), claim_key="effect").verdict.value
        # run it through the harness fold for a single-task list and read the bucket
        rr = run_rung([over], rung)
        harness_verdict = (
            "ACCEPT" if rr.accept else
            "REJECT_POISON" if rr.reject_poison else
            "ABSTAIN" if rr.abstain else
            "NO_CLAIM"
        )
        assert harness_verdict == direct, (rung, harness_verdict, direct)
        # and the kernel's own floor law: a refute at the forgeable floor is NOT poison
        if rung == Accountability.AGENT_AUTHORED:
            assert direct == "ABSTAIN"
        else:
            assert direct == "REJECT_POISON"


def test_floor_refute_is_ignored_even_when_constructed():
    """Belt-and-braces on the floor law: even if a refuting read-back is constructed
    AT the AGENT_AUTHORED rung (not NO_SIGNAL), the kernel ignores it (it cannot
    move the bit). Proves the floor-J=0 result is the kernel's, not our modelling
    choosing NO_SIGNAL at the floor."""
    rb = EvidenceFacts.refute("forged", Accountability.AGENT_AUTHORED, subject="x",
                              detail="agent says it failed — forgeable, ignored")
    label = reward.admit(True, (rb,), claim_key="effect")
    assert label.verdict.value == "ABSTAIN"   # never REJECT_POISON off a forgeable byte
    assert label.poison is False


def test_rung_reaches_respects_strength_order():
    """The reachability model: a weaker rung cannot witness a stronger-witness want;
    a judge want is reachable by no deterministic rung."""
    assert not _rung_reaches(Accountability.AGENT_AUTHORED, WANT_STATE_INVARIANT)
    assert _rung_reaches(Accountability.OS_RECORDED, WANT_STATE_INVARIANT)
    assert _rung_reaches(Accountability.THIRD_PARTY, WANT_STATE_INVARIANT)
    # provider_ledger needs THIRD_PARTY; OS_RECORDED cannot reach it
    assert not _rung_reaches(Accountability.OS_RECORDED, WANT_PROVIDER_LEDGER)
    assert _rung_reaches(Accountability.THIRD_PARTY, WANT_PROVIDER_LEDGER)
    # judge is reachable by nothing deterministic
    for rung in RUNG_AXIS:
        assert not _rung_reaches(rung, WANT_JUDGE)


# ---------------------------------------------------------------------------
# Buckets are coherent (every task lands in exactly one verdict bucket).
# ---------------------------------------------------------------------------
def test_buckets_partition_the_distribution():
    res = run_ladder()
    for r in res.rungs:
        total = r.accept + r.reject_poison + r.abstain + r.no_claim
        assert total == res.n_tasks, (r.rung, total, res.n_tasks)
        # no_claim is rung-invariant (it never depends on the witness)
        assert r.no_claim == res.rungs[0].no_claim
        # claim_bearing + no_claim == n_tasks
        assert r.claim_bearing + r.no_claim == res.n_tasks


def test_over_claims_caught_is_bounded_by_total():
    res = run_ladder()
    for r in res.rungs:
        assert 0 <= r.over_claims_caught <= r.over_claims_total
        assert r.over_claims_caught == r.reject_poison   # only over-claims get refuted


def test_checks_block_reports_pass():
    res = run_ladder()
    ck = res.checks()
    assert ck["floor_J_is_zero"] is True
    assert ck["J_monotone_nondecreasing"] is True
    assert ck["precision_perfect"] is True


def test_distribution_is_deterministic():
    """No Math.random — the same mix builds the same tasks every time (reproducible)."""
    a = [t.task_id + str(t.claim_present) + str(t.effect_true) + t.wants_witness
         for t in default_tasks()]
    b = [t.task_id + str(t.claim_present) + str(t.effect_true) + t.wants_witness
         for t in DEFAULT_MIX.build()]
    assert a == b
