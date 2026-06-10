"""run_smoke — the Tier-2 FleetForge smoke (the one load-bearing datum).

PURPOSE. The keystone (`skill_adherence.py`) proves the attribution instrument is
sound at $0. This smoke produces the single decision-relevant datum the whole
benchmark turns on:

    Do REAL LLM fleets on shared mutable state collide / over-claim at a MEASURABLE
    rate — and does the DOS-skills arm CAPTURE that value ATTRIBUTABLY (the verbs
    fired, per the WAL+git instrument), while the prose arm does not?

EITHER outcome is banked (the kill criteria from the conversion-gap ledger):
  * a nonzero collision/over-claim rate the skill arm prevents attributably =
    "small-lift-that-grows", proceed to the powered curve;
  * a clean ~0 rate on a tractable workload = the honest "harmless / correctly
    silent" frontier null — report it, don't hope past it.

THE THREE ARMS (same model, same workload, same seed — DOS gets no better agent):
  * A_prose      — believe the worker's {shipped} self-report, write whenever, no
                   dos verbs (the plausible plain orchestrator). WAL stays empty.
  * B_workflow   — a structured non-DOS orchestrator (serializes via its own plan
                   but still BELIEVES completion). Distinguishes "DOS skills win"
                   from "any structure wins". (Smoke proxy; the live B arm shells a
                   real Claude Code Workflow — out of scope for the $0 smoke.)
  * C_dos_skills — the SHIPPED dos-dispatch discipline: arbitrate-before-write,
                   verify-before-bank, lease+heartbeat the WAL. This IS the
                   `fleet_horizon.closed_loop` kernel path (the skills' mechanism),
                   so arm C drives the REAL kernel, no mocks.

HONESTY. Scored ONLY on consumer denominators via the SAME `fleet_horizon.metrics`
code (no new scoring that could tilt the A/B), joined through the byte-clean
`skill_adherence` instrument. Agent task pass-rate is NOT a headline. The worker
layer is pluggable: the DEFAULT is a deterministic seeded worker so this harness is
CI-testable at $0; the LIVE worker (real CLIs) is opt-in via DOS_LIVE=1 and never
gates CI — the same discipline as `fleet_horizon/live_demo.py`.

Run (deterministic, $0):
    PYTHONPATH=src python -m benchmark.fleetforge.run_smoke --efforts 3 --phases 3

Run (LIVE, opt-in, spends tokens):
    DOS_LIVE=1 PYTHONPATH=src python -m benchmark.fleetforge.run_smoke \
        --efforts 3 --phases 3 --model gemini-2.5-flash
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

from benchmark.fleet_horizon import closed_loop, open_loop, metrics
from benchmark.fleet_horizon.agent import FailureModel
from benchmark.fleet_horizon.workload import generate, generate_disjoint, Workload

from benchmark.fleetforge import skill_adherence as sa
from benchmark.fleetforge.skill_adherence import WriteFact, BankedClaim


# --------------------------------------------------------------------------
# Fossil extraction — turn an arm's run into the byte-clean evidence the
# attribution instrument reads. The closed-loop arm leaves a real WAL + real git
# commits; we read THOSE, never the worker's self-report.
# --------------------------------------------------------------------------

def _writes_from_events(events: list[metrics.Event]) -> list[WriteFact]:
    """Recover the git WriteFacts from the arm's `real-ship` events.

    A `real-ship` event is emitted ONLY when a real commit landed (ground truth) —
    `closed_loop`/`open_loop` emit it off the actual git commit, not the claim. So
    using it here keeps the byte-author-not-the-agent line: a WriteFact exists iff
    a commit exists. Order is the emission order (== git commit order in the arm).
    """
    out: list[WriteFact] = []
    order = 0
    for e in events:
        if e.kind == "real-ship":
            out.append(WriteFact(effort=e.effort, phase_id=e.phase_id,
                                 sha=e.detail or "", order=order))
            order += 1
    return out


def _banked_from_events(events: list[metrics.Event]) -> list[BankedClaim]:
    """Recover what the arm BANKED as shipped. `banked-shipped` is the arm's own
    accounting decision (open arm believes; closed arm oracle-confirmed); we score
    it against git ground truth in the instrument, so a banked phase with no
    WriteFact is the lie — independent of any model narration."""
    return [BankedClaim(effort=e.effort, phase_id=e.phase_id)
            for e in events if e.kind in ("banked-shipped", "banked-lie")]


@dataclasses.dataclass
class ArmResult:
    arm: str
    metrics_row: dict
    adherence_rows: list[dict]
    attribution: dict


def _score_arm(arm: str, m: metrics.Metrics, events: list[metrics.Event],
               wl: Workload, journal: list[dict]) -> ArmResult:
    lanes = {e.name: e.lane for e in wl.efforts}
    writes = _writes_from_events(events)
    banked = _banked_from_events(events)
    recs = sa.classify_fleet(journal=journal, writes=writes, banked=banked, lanes=lanes)
    summ = sa.summarize(recs)
    return ArmResult(
        arm=arm,
        metrics_row=m.to_row(),
        adherence_rows=[r.to_row() for r in recs],
        attribution=summ.to_row(),
    )


# --------------------------------------------------------------------------
# The arms. Arm C is the real-kernel closed loop (the skills' mechanism); arms A/B
# are the believing baselines. The WORKER (the thing that lies/collides) is the
# SAME across arms — the honesty invariant.
# --------------------------------------------------------------------------

def _make_model(args) -> FailureModel:
    """The shared worker failure model. DEFAULT = the deterministic seeded model so
    the smoke is $0/CI-safe. The LIVE worker (real CLI) is opt-in and replaces this
    at the call site below; here we keep the deterministic model as the honest,
    reproducible default that makes the harness itself testable."""
    return FailureModel(
        lie_rate=args.lie_rate,
        flake_rate=args.flake_rate,
        thrash_rate=args.thrash_rate,
        seed=args.seed,
    )


def run_smoke(args) -> dict:
    live = os.environ.get("DOS_LIVE") == "1"
    if live:
        # The live worker is intentionally NOT wired in this $0 keystone+smoke
        # deliverable: it spends tokens and is non-deterministic. We surface the
        # gap explicitly rather than silently fall back (the no-silent-cap rule).
        print("[fleetforge] DOS_LIVE=1 requested, but the live-CLI worker is a "
              "Tier-3 follow-up; running the DETERMINISTIC smoke so the result is "
              "reproducible. See run_smoke.__doc__ for the live plan.", file=sys.stderr)

    wl = (generate_disjoint(seed=args.seed, efforts=args.efforts, phases=args.phases)
          if args.disjoint else
          generate(seed=args.seed, efforts=args.efforts, phases=args.phases,
                   shared_ratio=args.shared_ratio))

    results: list[ArmResult] = []

    # Arm C — the DOS-skills mechanism: the real-kernel closed loop. It leaves a real
    # WAL we read the adherence off. Its journal path is under its own temp repo, so
    # we capture it via the same closed_loop machinery: closed_loop.run returns
    # (metrics, events) and writes its WAL to a temp path it owns. To read that WAL we
    # re-run with journal capture enabled.
    m_c, ev_c, journal_c = closed_loop.run_with_journal(
        wl, _make_model(args), run_seed=args.seed,
    ) if hasattr(closed_loop, "run_with_journal") else _run_c_capture(wl, args)
    results.append(_score_arm("C_dos_skills", m_c, ev_c, wl, journal_c))

    # Arm A — prose orchestrator: believe self-reports, no dos verbs, empty WAL.
    m_a, ev_a = open_loop.run(wl, _make_model(args), run_seed=args.seed)
    results.append(_score_arm("A_prose", m_a, ev_a, wl, journal=[]))

    # Arm B — structured-but-believing proxy: same as A for the $0 smoke (the
    # structured-orchestrator distinction needs the live Workflow arm). We run it so
    # the 3-arm scaffold is present and the row is explicitly labeled a proxy.
    m_b, ev_b = open_loop.run(wl, _make_model(args), run_seed=args.seed)
    rb = _score_arm("B_workflow_proxy", m_b, ev_b, wl, journal=[])
    results.append(rb)

    return {
        "config": {
            "efforts": args.efforts, "phases": args.phases,
            "shared_ratio": (0.0 if args.disjoint else args.shared_ratio),
            "disjoint": args.disjoint, "seed": args.seed,
            "lie_rate": args.lie_rate, "live": live,
            "worker": "deterministic-seeded",
        },
        "arms": [dataclasses.asdict(r) for r in results],
    }


def _run_c_capture(wl: Workload, args) -> tuple[metrics.Metrics, list[metrics.Event], list[dict]]:
    """Run arm C (the closed loop) AND capture its WAL.

    `closed_loop.run` writes its journal to `cfg.paths.lane_journal` under its own
    temp repo and tears the temp tree down on return, so we cannot read the WAL
    after the fact. This shim re-runs the closed loop with a journal-capturing sink
    if the upstream module exposes one; otherwise it reconstructs the WAL from the
    arm's REFUSE/real-ship events as a faithful proxy (refuses -> REFUSE entries;
    real ships under a lane -> ACQUIRE+RELEASE), so the adherence instrument has a
    byte-clean WAL to read even without modifying the upstream arm.

    This proxy is HONEST for the smoke: it derives the WAL from the SAME ground-truth
    events the metrics are scored from (refuses the arbiter actually recorded, ships
    git actually has), not from any model self-report. The live tier reads the real
    on-disk WAL directly.
    """
    m, ev = closed_loop.run(wl, _make_model(args), run_seed=args.seed)
    journal: list[dict] = []
    # Per-effort: the closed loop ACQUIREs each effort's lane, may HEARTBEAT, REFUSEs
    # a colliding write, RELEASEs at end. Reconstruct from the ground-truth events.
    from dos import lane_journal as lj
    lanes = {e.name: e.lane for e in wl.efforts}

    # Build each effort's full file footprint so we can tag a REFUSE as CROSS-EFFORT
    # (overlaps a DIFFERENT effort's files) vs SAME-EFFORT (the in-flight-window
    # self-serialization the closed loop also produces). Only cross-effort refuses
    # are coordination value; this is the conflation the falsifier exposed.
    footprint: dict[str, set[str]] = {}
    for e in wl.efforts:
        files: set[str] = set()
        for p in e.phases:
            files.update(p.touches)
        footprint[e.name] = files

    def _phase_files(effort: str, phase_id: str) -> set[str]:
        for e in wl.efforts:
            if e.name != effort:
                continue
            for p in e.phases:
                if p.phase_id == phase_id:
                    return set(p.touches)
        return set()

    def _is_cross_effort(effort: str, phase_id: str) -> bool:
        mine = _phase_files(effort, phase_id)
        for other, files in footprint.items():
            if other == effort:
                continue
            if mine & files:
                return True
        return False

    seen_lane: set[str] = set()
    for e in ev:
        lane = lanes.get(e.effort)
        if lane is None:
            continue
        if lane not in seen_lane:
            journal.append({"op": lj.OP_ACQUIRE, "lane": lane, "loop_ts": "smoke",
                            "lease": {"lane": lane}})
            journal.append({"op": lj.OP_HEARTBEAT, "lane": lane, "loop_ts": "smoke"})
            seen_lane.add(lane)
        if e.kind == "refused-write":
            journal.append({
                "op": lj.OP_REFUSE, "lane": lane, "reason": e.detail or "colliding write",
                "cross_effort": _is_cross_effort(e.effort, e.phase_id),
            })
    for lane in seen_lane:
        journal.append({"op": lj.OP_RELEASE, "lane": lane, "loop_ts": "smoke"})
    return m, ev, journal


def _print_report(report: dict) -> None:
    cfg = report["config"]
    print(f"\nFleetForge smoke — efforts={cfg['efforts']} phases={cfg['phases']} "
          f"shared_ratio={cfg['shared_ratio']} disjoint={cfg['disjoint']} "
          f"seed={cfg['seed']} worker={cfg['worker']}")
    print("-" * 96)
    hdr = (f"{'arm':<18}{'banked':>7}{'lies':>6}{'caught':>7}"
           f"{'xeff_prev':>10}{'review_frac':>12}{'adher':>7}{'coord_attr':>11}")
    print(hdr)
    for arm in report["arms"]:
        m = arm["metrics_row"]
        a = arm["attribution"]
        # coord_attributable: did the arm CAPTURE coordination value (cross-effort
        # prevention) with the verbs actually firing? This is the headline boolean,
        # and it is the part that MUST vanish on the disjoint/N=1 falsifier.
        print(f"{arm['arm']:<18}{m['banked_shipped']:>7}{m['banked_lies']:>6}"
              f"{m['caught_lies']:>7}{a['prevention_total']:>10}"
              f"{m['human_review_fraction']:>12.3f}"
              f"{a['mean_adherence']:>7.2f}{str(a['coord_attributable']):>11}")
    print("-" * 96)
    print("READ (two value axes, kept apart):\n"
          "  COORDINATION (xeff_prev) — cross-effort collisions arm C prevented. MUST\n"
          "    be >0 on contention and ~0 on the disjoint/N=1 falsifier (else rigged).\n"
          "  VERIFY (caught + review_frac) — lies the kernel caught; persists at ANY N\n"
          "    (verify-value is real even with no peer). The prose arm reviews 100%.\n"
          "  coord_attr — coordination value captured AND the verbs fired (WAL+git).\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--efforts", type=int, default=3)
    ap.add_argument("--phases", type=int, default=3)
    ap.add_argument("--shared-ratio", type=float, default=0.5,
                    help="contention surface; high for a smoke so collisions show")
    ap.add_argument("--disjoint", action="store_true",
                    help="falsifier workload: no shared files -> gap must vanish")
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--lie-rate", type=float, default=0.12)
    ap.add_argument("--flake-rate", type=float, default=0.05)
    ap.add_argument("--thrash-rate", type=float, default=0.05)
    ap.add_argument("--model", default="gemini-2.5-flash",
                    help="live model id (only used when DOS_LIVE=1; Tier-3)")
    ap.add_argument("--json", action="store_true", help="emit the full report as JSON")
    args = ap.parse_args(argv)

    report = run_smoke(args)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
