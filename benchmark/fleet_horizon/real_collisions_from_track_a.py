"""real_collisions_from_track_a.py — feed the docs/244/245 fleet-scale harness a
REAL collision distribution, mined by docs/243 Track A, instead of a simulated one.

THE GAP (docs/244 §, the "rate is not a cascade" objection): the FleetHorizon
coordination magnitudes (velocity/$, human-review fraction, collisions-prevented
0@N=1 -> 104@N=8) are a proven MECHANISM, but every magnitude rides a SIMULATED
workload — `workload.generate` plants collisions with a HARDCODED `shared_ratio`
(0.25) and a hardcoded lie model. The sibling `measure_real_collisions.py` was meant
to ground the rate but is non-functional (it resolves a placeholder transcript dir
and returns 0 everything).

THE BRIDGE (this module): docs/243 Track A already mines the REAL collision
distribution off this repo's own concurrent CC fleet — and it WORKS (the corpus dir
is auto-derived, the kernel `overlap_verdict` is scored, CLOBBER vs SERIALIZED is
git-witnessed). So we lift Track A's measured numbers into the two parameters the
simulation stands in for:

    shared_ratio_real  = (concurrent pairs that share a write region)
                         / (all concurrent editing pairs)
                       — the empirical collision SURFACE the 0.25 default guessed.
    clobber_fraction   = (shared pairs that consequentially INTERLEAVED, no commit
                          between) / (shared pairs)
                       — the fraction of collisions that were a real last-writer-wins
                          HAZARD, not a serialized hand-off.

These calibrate `workload.generate(shared_ratio=...)` to the MEASURED surface, so the
docs/244 F-series scaling argument rests on a real distribution. docs/243 supplies the
data; docs/244 supplies the scaling — joined, not merged (the docs/243 §5 dovetail).

Read-only: it runs Track A (which reads the corpus + shells git) and emits a profile.
No model calls. Honors the frozen-snapshot + self-witness discipline (--before /
--auto-exclude-self) so the calibration is reproducible.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, asdict

from benchmark.fleet_trajectory.track_a import (
    concurrency_census, label_corpus, summarize as track_a_summarize,
)


@dataclass(frozen=True)
class RealCollisionProfile:
    """The measured collision distribution Track A mines — the calibration the
    fleet-scale simulation should use instead of its hardcoded guesses."""

    n_sessions: int
    concurrent_pairs: int
    shared_region_pairs: int
    clobber_pairs: int
    # the two parameters the simulation stands in for:
    shared_ratio_real: float       # collision SURFACE (vs the 0.25 default)
    clobber_fraction: float        # fraction of collisions that were a real hazard
    # the kernel's discrimination on the real distribution (the Track A headline):
    kernel_specificity: float | None   # admits safe parallelism (1.0 = no false-refuse)
    kernel_sensitivity: float | None   # refuses real collisions
    as_of: str
    frozen_before: str | None
    note: str = (
        "shared_ratio_real replaces workload.generate's hardcoded 0.25; the kernel "
        "specificity/sensitivity are measured off the REAL distribution (docs/243 "
        "Track A), so the docs/244 F-series scaling no longer rides a simulated "
        "collision surface. Multiply by N*(N-1)/2 concurrent pairs at fleet size N "
        "to project the absolute collision count the arbiter serializes."
    )


def build_profile(
    repo: str = ".", *, before: dt.datetime | None = None,
    exclude_sids: set[str] | None = None, use_git: bool = False, as_of: str = "",
) -> RealCollisionProfile:
    census = concurrency_census(before=before, exclude_sids=exclude_sids)
    labels = label_corpus(repo, use_git=use_git, before=before, exclude_sids=exclude_sids)
    summ = track_a_summarize(labels)

    cp = census["concurrent_editing_pairs"]
    sp = census["share_a_path"]
    shared_ratio = (sp / cp) if cp else 0.0
    shared_pairs = summ["pairs_with_shared_region"]
    clob = summ["clobber_pairs"]
    clobber_fraction = (clob / shared_pairs) if shared_pairs else 0.0

    return RealCollisionProfile(
        n_sessions=census["n_sessions"],
        concurrent_pairs=cp,
        shared_region_pairs=sp,
        clobber_pairs=clob,
        shared_ratio_real=round(shared_ratio, 4),
        clobber_fraction=round(clobber_fraction, 4),
        kernel_specificity=census["specificity_admit_disjoint"],
        kernel_sensitivity=census["sensitivity_refuse_shared"],
        as_of=as_of,
        frozen_before=before.isoformat() if before else None,
    )


def project_to_fleet_size(profile: RealCollisionProfile, n: int) -> dict:
    """Project the REAL collision RATE to a fleet of N concurrent agents — the
    docs/244 scaling step. The number of concurrent pairs grows as N*(N-1)/2; the
    measured shared_ratio is the fraction of those pairs that collide; the clobber
    fraction is how many are a real hazard. This is the RATE projection (an honest
    predecessor to the payoff A/B FleetHorizon runs), NOT a payoff claim."""
    pairs = n * (n - 1) // 2
    expected_collisions = pairs * profile.shared_ratio_real
    expected_clobbers = expected_collisions * profile.clobber_fraction
    return {
        "fleet_size": n,
        "concurrent_pairs": pairs,
        "expected_colliding_pairs": round(expected_collisions, 2),
        "expected_clobber_pairs": round(expected_clobbers, 2),
        "note": "RATE projection off the measured shared_ratio; the arbiter serializes "
                "every colliding pair (kernel sensitivity measured 1.0), preventing the "
                "clobbers. Dollar payoff is FleetHorizon's believed-vs-adjudicated A/B, "
                "not this projection.",
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from benchmark.fleet_trajectory.corpus import detect_self_sid, parse_ts

    ap = argparse.ArgumentParser(description="Feed Track A's real collision distribution into the fleet-scale harness")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--before", help="freeze cutoff ISO instant (reproducible snapshot)")
    ap.add_argument("--auto-exclude-self", action="store_true")
    ap.add_argument("--use-git", action="store_true", help="git-witness CLOBBER vs SERIALIZED (slower, sounder)")
    ap.add_argument("--as-of", default="", help="dating stamp for the profile")
    ap.add_argument("--project", type=int, action="append", default=[],
                    help="project the rate to a fleet of N agents (repeatable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    exclude = set()
    if args.auto_exclude_self:
        sid = detect_self_sid()
        if sid:
            exclude.add(sid)
            print(f"[self-witness guard] excluding {sid}", flush=True)
    before = parse_ts(args.before) if args.before else None

    profile = build_profile(
        args.repo, before=before, exclude_sids=exclude, use_git=args.use_git, as_of=args.as_of
    )
    out = {"profile": asdict(profile)}
    if args.project:
        out["projections"] = [project_to_fleet_size(profile, n) for n in args.project]
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
