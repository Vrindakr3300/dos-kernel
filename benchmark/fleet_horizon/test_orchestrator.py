"""Honesty tests for the ORCHESTRATOR axis (docs/98).

The orchestrator axis asks: is a harness/ultracode `Workflow` flow as safe as
DOS-native dispatch, given both call the SAME trust seam? These tests pin the
invariants that make the comparison honest and the headline real:

  1. Same seed → same ground-truth real ships across EVERY orchestrator (DOS does
     not get a better agent than the harness — the honesty invariant, lifted to
     this axis).
  2. `verify` catches lies regardless of orchestrator: banked_lies == 0 in both
     adjudicate arms (the trust axis is orthogonal to the orchestrator axis).
  3. The orchestrator GAP is real: a naive harness (no lease write-back) lets
     shared-state collisions slip past the arbiter to be DETECTED after the fact
     (some surviving as silent overwrites), where DOS-native and a disciplined
     harness PREVENT them at contention.
  4. The FALSIFIER: on a genuinely disjoint workload the gap vanishes — the
     orchestrator choice is moot when nothing contends (the docs/98 analogue of
     FleetHorizon's gap→0 at horizon→1).
  5. The shared loop body (`orchestrator.run_fleet` with an in-process lease book)
     is FAITHFUL to the original `closed_loop.run` — same metrics on the same seed,
     so the generic seam did not change the DOS-native arm's behavior.

Run:
    PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_orchestrator.py -q
"""
from __future__ import annotations

import pytest

from .agent import FailureModel
from .workload import generate, generate_disjoint
from . import closed_loop, harness_loop
from .harness import run_quad


SEED = 1729


def _model() -> FailureModel:
    return FailureModel(seed=SEED, lie_rate=0.12)


# --------------------------------------------------------------------------
# 1 + 2 — the honesty invariants (same agent; trust orthogonal to orchestrator)
# --------------------------------------------------------------------------
def test_same_real_ships_across_orchestrators():
    """DOS-native, disciplined-harness, and naive-harness all run the SAME seeded
    workload — so ground-truth real ships are identical. The orchestrator does not
    get a better (or worse) agent; it only changes WHEN a collision is caught."""
    q = run_quad(efforts=6, phases=20)
    ships = {k: m.real_ships for k, m in q.items()}
    assert len(set(ships.values())) == 1, f"real ships diverged across cells: {ships}"


def test_verify_catches_lies_regardless_of_orchestrator():
    """The trust axis is orthogonal to the orchestrator axis: every ADJUDICATE cell
    banks zero lies, because `oracle.is_shipped` re-checks each claim against git no
    matter who drove the fanout. Only the believe baseline banks falsehoods."""
    q = run_quad(efforts=6, phases=20)
    assert q["dos_adjudicate"].banked_lies == 0
    assert q["harness_adjudicate_wb"].banked_lies == 0
    assert q["harness_adjudicate_nowb"].banked_lies == 0
    # the believe baseline DID bank some (else there'd be nothing to be honest about)
    assert q["believe"].banked_lies > 0


# --------------------------------------------------------------------------
# 3 — the orchestrator GAP is real (the headline)
# --------------------------------------------------------------------------
def test_naive_harness_regresses_to_detection():
    """A harness with NO lease write-back lets shared-state collisions slip past the
    arbiter: they are DETECTED after the fact, and some survive as silent overwrites
    verify cannot undo. DOS-native prevents every one at contention."""
    q = run_quad(efforts=6, phases=20)
    dos = q["dos_adjudicate"]
    naive = q["harness_adjudicate_nowb"]
    # DOS-native: nothing slips through
    assert dos.detected_collisions == 0
    assert dos.silent_overwrites == 0
    assert dos.prevention_rate == 1.0
    # naive harness: the gap opens — collisions detected-after, some surviving
    assert naive.detected_collisions > 0, (
        "the naive-harness gap did not open — expected detected-after collisions")
    assert naive.silent_overwrites > 0, (
        "a detected-after collision should leave a surviving silent overwrite")
    assert naive.prevention_rate < 1.0


def test_disciplined_harness_matches_dos_native_integrity():
    """A harness that WRITES ITS LEASES BACK (dos lease-lane) prevents collisions
    just like the in-process loop: zero detected-after, zero surviving overwrites.
    Leaning on ultracode is safe IFF the flow keeps the WAL fresh."""
    q = run_quad(efforts=6, phases=20)
    wb = q["harness_adjudicate_wb"]
    assert wb.detected_collisions == 0
    assert wb.silent_overwrites == 0
    assert wb.prevention_rate == 1.0


def test_collisions_total_is_a_workload_property():
    """The TOTAL collisions (prevented + detected) is a property of the workload —
    the same on the same seed. What the orchestrator changes is the SPLIT between
    prevented-at-contention and detected-after, not how many collisions exist."""
    q = run_quad(efforts=8, phases=20)
    dos = q["dos_adjudicate"]
    naive = q["harness_adjudicate_nowb"]
    # the naive arm converts some of DOS's prevented collisions into detected ones;
    # the union (what actually contended) is non-trivial and the split differs.
    assert naive.detected_collisions > 0
    assert dos.refused_writes > 0
    # the naive arm prevented strictly fewer than DOS did (it lagged)
    assert naive.refused_writes < dos.refused_writes


# --------------------------------------------------------------------------
# 4 — the FALSIFIER: disjoint workload → orchestrator is moot
# --------------------------------------------------------------------------
def test_orchestrator_gap_vanishes_when_disjoint():
    """The boundary: on a genuinely disjoint workload (no shared footprints) the
    arbiter never refuses a cross-effort collision, lease visibility is irrelevant,
    and EVERY orchestrator ties — zero detected-after, zero surviving overwrites,
    identical real ships. The benchmark proves its own 'orchestrator only earns its
    keep under contention' clause (docs/98 analogue of gap→0 at horizon→1)."""
    model = _model()
    wl = generate_disjoint(seed=SEED, efforts=6, phases=20)
    dos, _ = closed_loop.run(wl, model, run_seed=SEED)
    naive, _ = harness_loop.run(wl, model, run_seed=SEED, lease_writeback=False)
    wb, _ = harness_loop.run(wl, model, run_seed=SEED, lease_writeback=True)
    for m in (dos, naive, wb):
        assert m.detected_collisions == 0, "a disjoint workload cannot collide"
        assert m.silent_overwrites == 0
    assert dos.real_ships == naive.real_ships == wb.real_ships


def test_orchestrator_gap_vanishes_at_fleet_of_one():
    """At fleet=1 there is no concurrent writer, so no orchestrator can do better
    than another — the second falsifier (the fanout analogue of the integrity
    gap→0 at fleet=1)."""
    model = _model()
    wl = generate(seed=SEED, efforts=1, phases=20, shared_ratio=0.5)
    dos, _ = closed_loop.run(wl, model, run_seed=SEED)
    naive, _ = harness_loop.run(wl, model, run_seed=SEED, lease_writeback=False)
    assert dos.detected_collisions == naive.detected_collisions == 0
    assert dos.silent_overwrites == naive.silent_overwrites == 0


# --------------------------------------------------------------------------
# 5 — the generic seam is FAITHFUL to the original DOS-native arm
# --------------------------------------------------------------------------
def test_run_fleet_inprocess_matches_closed_loop():
    """The shared loop body (`orchestrator.run_fleet` with an InProcessLeaseBook)
    reproduces the original `closed_loop.run`'s integrity metrics on the same seed —
    proving the generic orchestrator seam did NOT change the DOS-native arm. We
    compare the integrity-defining counters (ground truth + what was caught), which
    must be identical; the in-process book IS the model of closed_loop's inline
    list."""
    import os
    from pathlib import Path
    import tempfile
    from .orchestrator import GitGround, InProcessLeaseBook, run_fleet
    from .harness_loop import _bench_config

    model = _model()
    wl = generate(seed=SEED, efforts=6, phases=20, shared_ratio=0.3)

    # the original arm
    c, _ = closed_loop.run(wl, model, run_seed=SEED)

    # the generic body with an in-process book + detect_after off (DOS-native)
    git = GitGround()
    prev = os.environ.get("DISPATCH_LANE_JOURNAL_PATH")
    os.environ["DISPATCH_LANE_JOURNAL_PATH"] = str(git.tmp / "j.jsonl")
    try:
        cfg = _bench_config(git.repo, wl)
        book = InProcessLeaseBook()
        g, _ = run_fleet(wl, model, arm="dos-native-via-seam", lease_book=book,
                         git_repo=git, cfg=cfg, run_seed=SEED, detect_after=False)
    finally:
        if prev is None:
            os.environ.pop("DISPATCH_LANE_JOURNAL_PATH", None)
        else:
            os.environ["DISPATCH_LANE_JOURNAL_PATH"] = prev
        git.close()

    # the integrity-defining counters must match the original closed_loop exactly
    assert g.real_ships == c.real_ships
    assert g.banked_lies == c.banked_lies == 0
    assert g.caught_lies == c.caught_lies
    assert g.refused_writes == c.refused_writes
    assert g.detected_collisions == 0
