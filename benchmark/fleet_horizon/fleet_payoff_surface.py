"""fleet_payoff_surface.py — F4: the headline fleet figure (docs/256).

THE STEP (docs/245 F4, the headline): F1/F1-super-linear/F2 each measured one
LIVE number off the tau2 DB-hash; F4 MARRIES them into the figure the whole
fleet-scale program was built to produce — *expected corrupted downstream leaves
the out-of-loop referee prevents, as a function of fleet size K, cascade depth D,
and fan-out F*. No new live spend: this is the JOIN of three already-measured live
results, projected across (K, D, F).

The three live inputs (every one read off bytes the agents did not author):

  shared_ratio    — the collision SURFACE: fraction of concurrent agent pairs that
                    touch a shared write region. Mined by docs/243 Track A over THIS
                    repo's own concurrent CC fleet (git ancestry + CC timestamps,
                    the byte-author != judge witness). Live today: ~0.19.
  clobber_fraction— fraction of those collisions that are a real last-writer-wins
                    HAZARD (not a serialized hand-off). Two honest edges:
                      * the corpus RATE projection (docs/243): ~0.23 (conservative);
                      * the live tau2 natural-sites J (docs/255, F2): 4/6 ≈ 0.67
                        (the rate on the entities multiple real tasks fight over).
                    We carry BOTH as a band; the headline defaults to the
                    conservative corpus rate so the figure never over-claims.
  cascade_load    — F^D: leaves saved per prevented clobber at a depth-D fan-out-F
                    root. Measured LIVE by docs/253 (F1-super-linear): F=2 gave 4
                    corrupt leaves at D=2 and 8 at D=3 under believe, 0 under
                    adjudicate — exactly F^D. So one clobber prevented at a fan-out
                    root is not one event saved; it is F^D downstream leaves.

The headline composition:

    clobbers_prevented(K) = C(K,2) * shared_ratio * clobber_fraction
    cascade_load(D, F)    = F**D                       # D=0 -> 1 (the bare event)
    payoff(K, D, F)       = clobbers_prevented(K) * cascade_load(D, F)

  payoff(K,D,F) is the EXPECTED CORRUPTED LEAVES the referee prevents across a
  fleet of K agents whose work branches D deep with fan-out F. It is the number
  that scales with the fleet — quadratic in K (the pair count), super-linear in D
  (the cascade), and it VANISHES at the fleet-of-one floor (K=1 -> 0 pairs -> 0),
  the docs/204 §1 falsifier the whole program is pinned to.

This module is PURE: it reads the live profile (via the Track A bridge, which
shells git + reads the corpus but makes no model calls) ONCE at the boundary, then
the surface is plain arithmetic over it. The cascade exponent is a measured fact,
not a tunable thumb on the scale — F4 plots what F1/F2/F1-super-linear already
proved, it does not re-assume it.

Read-only. Emits the surface as structured data (for the plotter + the doc); no
new live spend, no state mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field

from benchmark.fleet_horizon.real_collisions_from_track_a import (
    RealCollisionProfile, build_profile,
)


# ---------------------------------------------------------------------------
# The live-measured cascade load (docs/253, F1-super-linear). These are the
# OBSERVED corrupt-leaf counts off the DB-hash, not an assumption — F=2 produced
# exactly F^D (4 at D=2, 8 at D=3). We keep the measured points so the surface
# can be cross-checked against ground truth, and use F^D as the closed form the
# measurement confirmed.
# ---------------------------------------------------------------------------

# (depth, fanout) -> measured corrupt leaves under BELIEVE (docs/253 live run).
MEASURED_CASCADE = {
    (2, 2): 4,   # live_results_fanout/fanout_d2_f2.json
    (3, 2): 8,   # live_results_fanout/fanout_d3_f2.json
}

# The live F2 natural-clobber rate (docs/255): 4 of 6 natural-site pairs clobbered.
F2_NATURAL_CLOBBER_J = (4, 6)


def cascade_load(depth: int, fanout: int) -> int:
    """Leaves downstream of a poisoned fan-out root — F^D, the docs/253 result.

    D=0 (no downstream agent) -> 1: a prevented clobber is then just the one
    event, no sub-fleet under it. This is the cascade-loading multiplier the
    headline applies to every prevented clobber. F=1 (a chain, not a tree) gives
    1 at every depth — the degenerate no-branching case (the linear F1, docs/251,
    counts D-1 BLOCKED nodes, a different quantity than the leaf count here)."""
    if depth < 0 or fanout < 1:
        raise ValueError("depth must be >= 0 and fanout >= 1")
    return fanout ** depth


def concurrent_pairs(k: int) -> int:
    """C(K,2) — the concurrent agent pairs at fleet size K. 0 at K<=1 (the
    fleet-of-one floor: a single agent collides with no one)."""
    return k * (k - 1) // 2 if k > 1 else 0


def clobbers_prevented(profile: RealCollisionProfile, k: int, *,
                       clobber_fraction: float | None = None) -> float:
    """Expected real destructive clobbers the arbiter serializes at fleet size K.

    = C(K,2) * shared_ratio * clobber_fraction. The kernel sensitivity is measured
    1.0 (it refuses every real collision, docs/243), so every colliding pair that
    is a hazard is prevented — the expectation is the count the referee prevents.
    `clobber_fraction` defaults to the profile's conservative corpus rate; pass the
    F2 live rate (4/6) for the natural-sites edge of the band."""
    cf = profile.clobber_fraction if clobber_fraction is None else clobber_fraction
    return concurrent_pairs(k) * profile.shared_ratio_real * cf


def payoff(profile: RealCollisionProfile, k: int, depth: int, fanout: int, *,
           clobber_fraction: float | None = None) -> float:
    """THE headline number: expected corrupted downstream LEAVES the out-of-loop
    referee prevents across a fleet of K agents branching D deep with fan-out F.

    payoff = clobbers_prevented(K) * cascade_load(D, F). Quadratic in K, super-
    linear in D, and 0 at K=1 (no pair) — the live-grounded fleet-scaling curve."""
    return clobbers_prevented(profile, k, clobber_fraction=clobber_fraction) \
        * cascade_load(depth, fanout)


@dataclass(frozen=True)
class PayoffPoint:
    fleet_size: int
    depth: int
    fanout: int
    concurrent_pairs: int
    clobbers_prevented_conservative: float   # corpus clobber rate (docs/243)
    clobbers_prevented_natural: float        # F2 live tau2 rate (docs/255)
    cascade_load: int                        # F^D leaves per clobber (docs/253)
    leaves_prevented_conservative: float     # the headline, conservative edge
    leaves_prevented_natural: float          # the headline, natural-sites edge


@dataclass(frozen=True)
class PayoffSurface:
    """The full (K, D, F) surface + the live profile it was projected from."""
    profile: dict
    fleets: tuple[int, ...]
    depths: tuple[int, ...]
    fanouts: tuple[int, ...]
    points: tuple[PayoffPoint, ...]
    as_of: str
    measured_cascade_checks: dict = field(default_factory=dict)
    note: str = (
        "F4 headline (docs/256): expected corrupted downstream LEAVES the out-of-"
        "loop referee prevents = C(K,2)*shared_ratio*clobber_fraction * F^D. Three "
        "LIVE inputs joined: shared_ratio + clobber_fraction (docs/243 Track A, off "
        "git ancestry), the natural clobber J=4/6 (docs/255 F2, off the tau2 DB-"
        "hash), and the cascade load F^D (docs/253 F1-super-linear, measured 4@D2 "
        "8@D3). Conservative edge uses the corpus clobber rate; natural edge uses "
        "the F2 tau2 rate. Payoff is 0 at K=1 (fleet-of-one floor, docs/204 §1)."
    )


def build_surface(
    profile: RealCollisionProfile, *,
    fleets: tuple[int, ...] = (1, 2, 4, 8, 16, 32),
    depths: tuple[int, ...] = (0, 1, 2, 3, 4),
    fanouts: tuple[int, ...] = (1, 2, 3),
    as_of: str = "",
) -> PayoffSurface:
    """Project the live profile across the (K, D, F) grid — the headline surface."""
    natural_cf = F2_NATURAL_CLOBBER_J[0] / F2_NATURAL_CLOBBER_J[1]
    points: list[PayoffPoint] = []
    for k in fleets:
        for d in depths:
            for f in fanouts:
                load = cascade_load(d, f)
                cons = clobbers_prevented(profile, k)
                nat = clobbers_prevented(profile, k, clobber_fraction=natural_cf)
                points.append(PayoffPoint(
                    fleet_size=k, depth=d, fanout=f,
                    concurrent_pairs=concurrent_pairs(k),
                    clobbers_prevented_conservative=round(cons, 4),
                    clobbers_prevented_natural=round(nat, 4),
                    cascade_load=load,
                    leaves_prevented_conservative=round(cons * load, 4),
                    leaves_prevented_natural=round(nat * load, 4),
                ))

    # Cross-check the closed form against the live measurement: F^D must
    # reproduce the docs/253 observed corrupt-leaf counts exactly.
    checks = {
        f"d{d}_f{f}": {
            "measured_corrupt_leaves": observed,
            "closed_form_F^D": cascade_load(d, f),
            "agrees": observed == cascade_load(d, f),
        }
        for (d, f), observed in MEASURED_CASCADE.items()
    }

    return PayoffSurface(
        profile=asdict(profile),
        fleets=fleets, depths=depths, fanouts=fanouts,
        points=tuple(points), as_of=as_of, measured_cascade_checks=checks,
    )


def headline_slice(surface: PayoffSurface, *, depth: int, fanout: int) -> list[PayoffPoint]:
    """The single curve the headline figure leads with: payoff vs fleet size K at
    a fixed (D, F). Defaults in the doc use the live-measured (D=3, F=2) cell."""
    return [p for p in surface.points if p.depth == depth and p.fanout == fanout]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="F4 (docs/256): the headline fleet payoff surface — leaves "
                    "prevented vs (K, D, F), joined from the live F1/F2 results")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--use-git", action="store_true",
                    help="git-witness CLOBBER vs SERIALIZED in the profile (slower, sounder)")
    ap.add_argument("--auto-exclude-self", action="store_true",
                    help="exclude this live session from the corpus (reproducible self-witness guard)")
    ap.add_argument("--as-of", default="",
                    help="dating stamp for the profile (e.g. 2026-06-08)")
    ap.add_argument("--fleets", default="1,2,4,8,16,32",
                    help="comma-separated fleet sizes K")
    ap.add_argument("--depths", default="0,1,2,3,4",
                    help="comma-separated cascade depths D")
    ap.add_argument("--fanouts", default="1,2,3",
                    help="comma-separated fan-outs F")
    ap.add_argument("--slice-depth", type=int, default=3,
                    help="(D,F) cell for the headline 1-D slice (default D=3)")
    ap.add_argument("--slice-fanout", type=int, default=2,
                    help="(D,F) cell for the headline 1-D slice (default F=2)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    def _ints(s: str) -> tuple[int, ...]:
        return tuple(int(x) for x in s.split(",") if x.strip())

    exclude: set[str] = set()
    if args.auto_exclude_self:
        from benchmark.fleet_trajectory.corpus import detect_self_sid
        sid = detect_self_sid()
        if sid:
            exclude.add(sid)
            print(f"[self-witness guard] excluding {sid}", flush=True)

    profile = build_profile(
        args.repo, exclude_sids=exclude, use_git=args.use_git, as_of=args.as_of)
    surface = build_surface(
        profile, fleets=_ints(args.fleets), depths=_ints(args.depths),
        fanouts=_ints(args.fanouts), as_of=args.as_of,
    )

    if args.json:
        print(json.dumps({
            "surface": {
                **{k: v for k, v in asdict(surface).items() if k != "points"},
                "points": [asdict(p) for p in surface.points],
            }
        }, indent=2))
        return

    # human-readable: the live inputs, the cascade cross-check, the headline slice.
    p = profile
    print("=" * 76)
    print("F4 — the headline fleet payoff surface (docs/256)")
    print("=" * 76)
    print(f"\nLive inputs (off bytes the agents did not author):")
    print(f"  shared_ratio (collision surface) : {p.shared_ratio_real}   "
          f"[Track A, {p.n_sessions} sessions, {p.shared_region_pairs}/{p.concurrent_pairs} pairs]")
    print(f"  clobber_fraction (corpus rate)   : {p.clobber_fraction}   [docs/243 RATE projection]")
    print(f"  clobber_fraction (tau2 natural)  : {F2_NATURAL_CLOBBER_J[0]}/{F2_NATURAL_CLOBBER_J[1]} "
          f"= {F2_NATURAL_CLOBBER_J[0]/F2_NATURAL_CLOBBER_J[1]:.3f}   [docs/255 F2, off the DB-hash]")
    print(f"  kernel sensitivity / specificity : {p.kernel_sensitivity} / {p.kernel_specificity}")
    print(f"  cascade load                     : F^D   [docs/253 F1-super-linear, measured]")

    print(f"\nCascade cross-check (closed form F^D vs the docs/253 live measurement):")
    for k, c in surface.measured_cascade_checks.items():
        ok = "OK" if c["agrees"] else "MISMATCH"
        print(f"  {k}: measured {c['measured_corrupt_leaves']} leaves, F^D = "
              f"{c['closed_form_F^D']}  [{ok}]")

    sl = headline_slice(surface, depth=args.slice_depth, fanout=args.slice_fanout)
    print(f"\nHEADLINE slice — corrupted LEAVES prevented vs fleet size "
          f"(D={args.slice_depth}, F={args.slice_fanout}, load=F^D={cascade_load(args.slice_depth, args.slice_fanout)}):")
    print(f"  {'K':>4}  {'pairs':>6}  {'clobbers prevented':>20}  {'LEAVES prevented':>26}")
    print(f"  {'':>4}  {'':>6}  {'cons / natural':>20}  {'cons / natural':>26}")
    for pt in sl:
        print(f"  {pt.fleet_size:>4}  {pt.concurrent_pairs:>6}  "
              f"{pt.clobbers_prevented_conservative:>8.2f} / {pt.clobbers_prevented_natural:>7.2f}  "
              f"{pt.leaves_prevented_conservative:>11.2f} / {pt.leaves_prevented_natural:>10.2f}")
    print(f"\n  (K=1 is the fleet-of-one floor: 0 pairs -> 0 payoff, docs/204 §1.)")
    print(f"\n{surface.note}")


if __name__ == "__main__":
    main()
