"""Honesty tests for the FleetForge keystone (skill_adherence).

These are the Tier-0 deliverable: they prove the attribution instrument is sound
and that its FALSIFIERS fire, all at $0 (no model, no live tokens) — the gate that
must be green before any live tier spends a token. They mirror
`fleet_horizon/test_fleet_horizon.py`'s discipline: the win must vanish where
coordination is impossible, and the instrument must read only byte-clean fossils.

Run:  PYTHONPATH=src python -m pytest benchmark/fleetforge/test_fleetforge.py -q
"""
from __future__ import annotations

import inspect

from dos import lane_journal as lj

from benchmark.fleetforge import skill_adherence as sa
from benchmark.fleetforge.skill_adherence import (
    WriteFact, BankedClaim, classify_effort, classify_fleet, summarize,
)


# --- tiny fixture builders (the byte-clean fossils a real run would leave) ---

def _acquire(lane: str, loop_ts: str = "t") -> dict:
    return {"op": lj.OP_ACQUIRE, "lane": lane, "loop_ts": loop_ts, "lease": {"lane": lane}}


def _heartbeat(lane: str, loop_ts: str = "t") -> dict:
    return {"op": lj.OP_HEARTBEAT, "lane": lane, "loop_ts": loop_ts}


def _refuse(lane: str, cross_effort: bool = True) -> dict:
    return {"op": lj.OP_REFUSE, "lane": lane, "reason": "lane busy",
            "cross_effort": cross_effort}


def _release(lane: str, loop_ts: str = "t") -> dict:
    return {"op": lj.OP_RELEASE, "lane": lane, "loop_ts": loop_ts}


def _write(effort: str, phase: str, sha: str, order: int) -> WriteFact:
    return WriteFact(effort=effort, phase_id=phase, sha=sha, order=order)


# --- 1. a fully-adherent, value-capturing skill effort scores 1.0 -----------

def test_full_adherence_with_prevention_is_attributable():
    """An effort that ACQUIREd, HEARTBEAT, RELEASEd, banked only real commits, and
    had a collision REFUSEd scores full adherence and the outcome is attributable."""
    lane = "lane-00"
    journal = [_acquire(lane), _heartbeat(lane), _refuse(lane), _release(lane)]
    writes = [_write("effort-00", "E00.00", "aaaaaaa", 0)]
    banked = [BankedClaim("effort-00", "E00.00")]
    rec = classify_effort("effort-00", lane, journal=journal, writes=writes, banked=banked)
    assert rec.acquire_before_write is True
    assert rec.heartbeat is True
    assert rec.verify_before_bank is True
    assert rec.release is True
    assert rec.adherence_score == 1.0
    assert rec.collisions_prevented == 1
    assert rec.lies_banked == 0

    summ = summarize([rec])
    assert summ.attributable is True
    assert summ.coord_attributable is True


# --- 2. the prose-arm control CANNOT clear the attributable bar --------------

def test_prose_arm_no_arbitrate_is_not_attributable():
    """The control arm never calls a dos verb, so its WAL is EMPTY. Even if it
    banked work and (by luck) committed it all, the instrument must NOT credit the
    skills: no verbs fired, so `attributable` is False. This is the guard against
    crediting a delta to the skills that actually came from model luck."""
    lane = "lane-00"
    journal: list[dict] = []          # prose arm wrote NOTHING to the WAL
    writes = [_write("effort-00", "E00.00", "aaaaaaa", 0)]
    banked = [BankedClaim("effort-00", "E00.00")]   # it banked a real commit, by luck
    rec = classify_effort("effort-00", lane, journal=journal, writes=writes, banked=banked)
    assert rec.acquire_before_write is False
    assert rec.heartbeat is False
    assert rec.release is False
    # verify_before_bank is vacuously True (no lie banked), but that alone is < 0.5
    assert rec.adherence_score < 0.5

    summ = summarize([rec])
    # value looks captured (0 lies) but the verbs did NOT fire -> not attributable
    assert summ.attributable is False


# --- 3. a banked lie is caught from GIT GROUND TRUTH, not self-report --------

def test_banked_lie_caught_from_git_not_claim():
    """An effort banks a phase that has NO real git commit. Regardless of what the
    agent claimed, the instrument reads git ground truth: the banked phase has no
    matching WriteFact -> lies_banked=1 -> verify_before_bank rung did NOT fire."""
    lane = "lane-00"
    journal = [_acquire(lane), _heartbeat(lane), _release(lane)]
    writes: list[WriteFact] = []                      # NOTHING was actually committed
    banked = [BankedClaim("effort-00", "E00.00")]     # but the arm banked it as shipped
    rec = classify_effort("effort-00", lane, journal=journal, writes=writes, banked=banked)
    assert rec.lies_banked == 1
    assert rec.verify_before_bank is False
    # the lie is the dominant signal even though three other verbs fired
    summ = summarize([rec])
    assert summ.lies_total == 1


# --- 4. FALSIFIER: N=1 / nothing-to-prevent -> not attributable --------------

def test_falsifier_no_collisions_is_not_attributable_on_empty_work():
    """At N=1 (or any disjoint workload) there is no peer to collide with: the WAL
    has an ACQUIRE/HEARTBEAT/RELEASE but ZERO refuses, and if the lone effort banked
    NOTHING there is no captured value. The instrument must report the gap as ~0 —
    `attributable` False — because there was no coordination value to capture. If it
    reported a skill win here, it would be rigged."""
    lane = "lane-00"
    journal = [_acquire(lane), _heartbeat(lane), _release(lane)]   # disciplined...
    writes: list[WriteFact] = []                                   # ...but no work
    banked: list[BankedClaim] = []
    rec = classify_effort("effort-00", lane, journal=journal, writes=writes, banked=banked)
    assert rec.adherence_score == 1.0          # the verbs DID fire (high adherence)
    assert rec.collisions_prevented == 0       # but there was nothing to prevent
    summ = summarize([rec])
    # high adherence, ZERO captured value -> the COORDINATION gap must be ~0
    assert summ.coord_attributable is False
    # and with nothing banked there is no verify value either, so broad is False too
    assert summ.attributable is False


def test_falsifier_disjoint_fleet_prevents_nothing():
    """A genuinely disjoint fleet: every effort leases its own lane, writes its own
    files, no REFUSE ever recorded. Adherence is high across the fleet, but
    prevention_total is 0 — the coordination gap vanishes, as it must on
    `workload.generate_disjoint`. (The structural analogue of FleetHorizon's
    test_orchestrator_gap_vanishes_when_disjoint.)"""
    lanes = {f"effort-{i:02d}": f"lane-{i:02d}" for i in range(4)}
    journal: list[dict] = []
    writes: list[WriteFact] = []
    banked: list[BankedClaim] = []
    for i, (eff, lane) in enumerate(lanes.items()):
        journal += [_acquire(lane), _heartbeat(lane), _release(lane)]
        writes.append(_write(eff, f"E{i:02d}.00", f"sha{i:04d}", i))
        banked.append(BankedClaim(eff, f"E{i:02d}.00"))
    recs = classify_fleet(journal=journal, writes=writes, banked=banked, lanes=lanes)
    summ = summarize(recs)
    assert summ.prevention_total == 0          # nothing collided -> nothing prevented
    assert summ.mean_adherence == 1.0          # the verbs still fired everywhere
    # THE coordination falsifier: zero cross-effort prevention -> coord gap vanishes.
    assert summ.coord_attributable is False
    # (verify value can still be real — zero lies on banked work — so the BROAD
    # attributable may be True; that is correct, the two axes are kept apart.)


# --- 5b. the conflation the falsifier EXPOSED: same-effort refuses != coord ---

def test_same_effort_refuse_is_not_coordination_value():
    """A REFUSE the WAL tags `cross_effort=False` is same-effort serialization (an
    effort contending with its OWN in-flight lease on its next phase) — NOT a
    coordination collision. The instrument must NOT count it as prevention. This is
    the metric-conflation FleetForge's disjoint falsifier surfaced in FleetHorizon's
    raw `refused_writes` (which fires even on a genuinely disjoint workload)."""
    lane = "lane-00"
    journal = [_acquire(lane), _heartbeat(lane),
               _refuse(lane, cross_effort=False),   # self-serialization, not coord
               _refuse(lane, cross_effort=False),
               _release(lane)]
    rec = classify_effort("effort-00", lane, journal=journal, writes=[], banked=[])
    assert rec.collisions_prevented == 0      # same-effort refuses are NOT counted
    # one genuine cross-effort refuse DOES count:
    journal2 = journal + [_refuse(lane, cross_effort=True)]
    rec2 = classify_effort("effort-00", lane, journal=journal2, writes=[], banked=[])
    assert rec2.collisions_prevented == 1


# --- 5. INVARIANT: the instrument reads only WAL+git, never self-report ------

def test_instrument_signature_has_no_self_report_channel():
    """STRUCTURAL pin of the byte-author-not-the-judged-agent line: the classify
    functions take ONLY (journal entries, WriteFacts from git, BankedClaims the arm
    recorded). There is NO parameter named for an agent claim / narration / tool-log
    / 'shipped' self-report. If someone adds a `claim=`/`narration=`/`self_report=`
    channel, this test fails — the instrument must never consult the agent's word."""
    forbidden = {"claim", "claims", "narration", "self_report", "selfreport",
                 "report", "shipped_claim", "agent_says", "told"}
    for fn in (classify_effort, classify_fleet):
        params = set(inspect.signature(fn).parameters)
        assert not (params & forbidden), f"{fn.__name__} gained a self-report channel: {params & forbidden}"

    # And the WriteFact carries git facts (sha/order), the BankedClaim carries the
    # arm's accounting (effort/phase only) — neither carries a 'claimed_shipped' /
    # 'verdict' the model authored.
    wf_fields = {f.name for f in __import__("dataclasses").fields(WriteFact)}
    assert "claimed_shipped" not in wf_fields and "verdict" not in wf_fields
    bc_fields = {f.name for f in __import__("dataclasses").fields(BankedClaim)}
    assert "claimed_shipped" not in bc_fields and "verdict" not in bc_fields


# --- 6. SCAVENGE counts as release (reaped, not dangling) --------------------

def test_scavenge_counts_as_release():
    """A lane the supervisor REAPed (SCAVENGE) is released-equivalent: the loop ended
    (was reaped), not left dangling. The release rung fires on RELEASE or SCAVENGE."""
    lane = "lane-00"
    journal = [_acquire(lane), {"op": lj.OP_SCAVENGE, "lane": lane, "loop_ts": "t"}]
    rec = classify_effort("effort-00", lane, journal=journal, writes=[], banked=[])
    assert rec.release is True


# --- 7. per-verb partial adherence (the ablation signal) --------------------

def test_partial_adherence_arbitrate_but_no_verify():
    """A model that arbitrates+heartbeats+releases but banks a lie (verify rung did
    not fire) scores 3/4 — the per-verb vector a single-verb-ablation arm isolates."""
    lane = "lane-00"
    journal = [_acquire(lane), _heartbeat(lane), _release(lane)]
    writes: list[WriteFact] = []
    banked = [BankedClaim("effort-00", "E00.00")]   # banked, but no commit -> lie
    rec = classify_effort("effort-00", lane, journal=journal, writes=writes, banked=banked)
    assert rec.acquire_before_write and rec.heartbeat and rec.release
    assert rec.verify_before_bank is False
    assert rec.adherence_score == 0.75
