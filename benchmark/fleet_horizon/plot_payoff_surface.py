"""plot_payoff_surface.py — draw the F4 headline figure (docs/256).

The F4 surface (`fleet_payoff_surface.build_surface`) is the join of three LIVE
results into one number — expected corrupted leaves the referee prevents vs
(K, D, F). This module renders it the same three ways the sibling `plot.py` does,
in decreasing availability so the shape ALWAYS shows even with no deps:

  1. CSV (always, stdlib) — the portable artifact for any external plotter.
  2. ASCII (always, stdlib) — the headline curve + the cascade-load fan, printed.
  3. PNG (only if matplotlib) — the two persuasive panels for the doc/paper:
       (left)  payoff vs fleet K at the live-measured (D=3, F=2) cell, the two
               clobber-rate edges as a band — the super-linear fleet curve;
       (right) the cascade fan: payoff vs K for several (D, F), showing how the
               curve lifts as the fleet branches deeper/wider (the F^D loading).

DOS's kernel is PyYAML-only and this is a consumer (the examples/ boundary), so
matplotlib is NEVER a hard dependency — its absence degrades to CSV+ASCII.

Run:
    PYTHONPATH=src python -m benchmark.fleet_horizon.plot_payoff_surface
    PYTHONPATH=src python -m benchmark.fleet_horizon.plot_payoff_surface --out-dir build/
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .fleet_payoff_surface import (
    build_surface, cascade_load, headline_slice, PayoffSurface,
)
from .real_collisions_from_track_a import build_profile


# The headline (D, F) cell — the one F1-super-linear measured live (docs/253).
HEADLINE_DEPTH = 3
HEADLINE_FANOUT = 2

# The cascade fan: the (D, F) curves the right-hand panel overlays to SHOW the
# F^D lift. Each is a real cell of the measured cascade shape.
FAN_CELLS = ((0, 2), (1, 2), (2, 2), (3, 2), (4, 2))


# ---------------------------------------------------------------------------
# (1) CSV — always.
# ---------------------------------------------------------------------------

def write_csv(surface: PayoffSurface, out_dir: Path) -> list[Path]:
    path = out_dir / "fleet_payoff_surface.csv"
    rows = [
        {
            "fleet_size": p.fleet_size, "depth": p.depth, "fanout": p.fanout,
            "concurrent_pairs": p.concurrent_pairs,
            "cascade_load_F^D": p.cascade_load,
            "clobbers_prevented_conservative": p.clobbers_prevented_conservative,
            "clobbers_prevented_natural": p.clobbers_prevented_natural,
            "leaves_prevented_conservative": p.leaves_prevented_conservative,
            "leaves_prevented_natural": p.leaves_prevented_natural,
        }
        for p in surface.points
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return [path]


# ---------------------------------------------------------------------------
# (2) ASCII — always (stdlib).
# ---------------------------------------------------------------------------

def _bar(value: float, vmax: float, width: int = 44) -> str:
    if vmax <= 0:
        return ""
    return "█" * int(round((value / vmax) * width))


def render_ascii(surface: PayoffSurface) -> str:
    L: list[str] = []
    L.append("=" * 76)
    L.append("F4 — the headline fleet figure (docs/256): LEAVES the referee prevents")
    L.append("=" * 76)

    pr = surface.profile
    L.append(f"\nLive inputs joined (off bytes the agents did not author):")
    L.append(f"  shared_ratio={pr['shared_ratio_real']} (Track A, {pr['n_sessions']} sessions)  "
             f"clobber: corpus {pr['clobber_fraction']} / tau2-natural 0.667 (F2)  "
             f"cascade F^D (docs/253)")

    # Headline curve: payoff vs K at (D=3, F=2), the conservative edge.
    sl = headline_slice(surface, depth=HEADLINE_DEPTH, fanout=HEADLINE_FANOUT)
    load = cascade_load(HEADLINE_DEPTH, HEADLINE_FANOUT)
    L.append(f"\n[A] corrupted LEAVES prevented vs FLEET SIZE K  (D={HEADLINE_DEPTH}, F={HEADLINE_FANOUT}, "
             f"load=F^D={load})  — quadratic in K × F^D, the fleet-scaling headline")
    L.append("    (conservative corpus clobber-rate; the natural-sites rate is ~2.9× higher)")
    vmax = max((p.leaves_prevented_conservative for p in sl), default=1.0) or 1.0
    for p in sl:
        floor = "  ← fleet-of-one floor (no pair to collide)" if p.fleet_size <= 1 else ""
        L.append(f"    K={p.fleet_size:>3}  {p.leaves_prevented_conservative:>8.1f} "
                 f"|{_bar(p.leaves_prevented_conservative, vmax)}{floor}")

    # The cascade fan: at a fixed fleet, how payoff lifts with (D, F).
    fleet_for_fan = surface.fleets[-1]
    L.append(f"\n[B] the cascade LIFT at fleet K={fleet_for_fan}  — one prevented clobber "
             f"loads F^D leaves; the figure climbs as the fleet branches deeper")
    fan_vals = []
    for (d, f) in FAN_CELLS:
        pts = [p for p in surface.points if p.fleet_size == fleet_for_fan
               and p.depth == d and p.fanout == f]
        if pts:
            fan_vals.append(((d, f), pts[0].leaves_prevented_conservative))
    fmax = max((v for _, v in fan_vals), default=1.0) or 1.0
    for (d, f), v in fan_vals:
        L.append(f"    D={d} F={f} (F^D={cascade_load(d, f):>3})  {v:>8.1f} |{_bar(v, fmax)}")

    # The cascade cross-check (closed form vs the live measurement).
    L.append(f"\n[C] cascade cross-check — F^D reproduces the docs/253 live measurement:")
    for k, c in surface.measured_cascade_checks.items():
        ok = "OK" if c["agrees"] else "MISMATCH"
        L.append(f"    {k}: measured {c['measured_corrupt_leaves']} corrupt leaves, "
                 f"F^D={c['closed_form_F^D']}  [{ok}]")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# (3) PNG — only if matplotlib is importable.
# ---------------------------------------------------------------------------

def render_png(surface: PayoffSurface, out_dir: Path) -> list[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5.2))
    fig.suptitle(
        "F4 — the out-of-loop referee's payoff scales with the fleet (live-grounded)",
        fontsize=13, fontweight="bold")

    # LEFT: the headline curve — payoff vs K at (D=3, F=2), the two-edge band.
    sl = headline_slice(surface, depth=HEADLINE_DEPTH, fanout=HEADLINE_FANOUT)
    xs = [p.fleet_size for p in sl]
    cons = [p.leaves_prevented_conservative for p in sl]
    nat = [p.leaves_prevented_natural for p in sl]
    axL.plot(xs, cons, "o-", color="#1971c2", linewidth=2,
             label="corpus clobber rate (0.23, conservative)")
    axL.plot(xs, nat, "s--", color="#e8590c", linewidth=2,
             label="tau2 natural-sites rate (0.67, F2 live)")
    axL.fill_between(xs, cons, nat, alpha=0.12, color="#1971c2")
    load = cascade_load(HEADLINE_DEPTH, HEADLINE_FANOUT)
    axL.set_title(f"A. corrupted leaves prevented vs fleet size\n"
                  f"(D={HEADLINE_DEPTH}, F={HEADLINE_FANOUT}; load=F^D={load}; 0 at K=1)")
    axL.set_xlabel("fleet size K (concurrent agents)")
    axL.set_ylabel("expected corrupted leaves prevented")
    axL.legend(fontsize=8)
    axL.grid(alpha=0.3)

    # RIGHT: the cascade fan — payoff vs K for several (D, F), the F^D lift.
    colors = ["#adb5bd", "#74c0fc", "#4dabf7", "#1971c2", "#0b4884"]
    for (d, f), col in zip(FAN_CELLS, colors):
        pts = [p for p in surface.points if p.depth == d and p.fanout == f]
        pts = sorted(pts, key=lambda p: p.fleet_size)
        axR.plot([p.fleet_size for p in pts],
                 [p.leaves_prevented_conservative for p in pts],
                 "o-", color=col, linewidth=2,
                 label=f"D={d}, F={f}  (F^D={cascade_load(d, f)})")
    axR.set_title("B. the cascade lift\n(each prevented clobber loads F^D downstream leaves)")
    axR.set_xlabel("fleet size K (concurrent agents)")
    axR.set_ylabel("expected corrupted leaves prevented (conservative)")
    axR.legend(fontsize=8, title="cascade depth × fan-out")
    axR.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = out_dir / "fleet_payoff_surface.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return [out]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draw the F4 headline fleet payoff figure (docs/256)")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--use-git", action="store_true",
                    help="git-witness the profile (slower, sounder)")
    ap.add_argument("--auto-exclude-self", action="store_true",
                    help="exclude this live session from the corpus (reproducible)")
    ap.add_argument("--as-of", default="", help="dating stamp for the profile")
    ap.add_argument("--out-dir", default=str(Path(__file__).parent / "build"),
                    help="where CSV/PNG land (default: benchmark/fleet_horizon/build)")
    ap.add_argument("--no-png", action="store_true", help="skip PNG even if matplotlib is present")
    args = ap.parse_args(argv)

    exclude: set[str] = set()
    if args.auto_exclude_self:
        from benchmark.fleet_trajectory.corpus import detect_self_sid
        sid = detect_self_sid()
        if sid:
            exclude.add(sid)
            print(f"[self-witness guard] excluding {sid}", flush=True)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Building the live profile (Track A — reads the corpus + shells git)...")
    profile = build_profile(args.repo, exclude_sids=exclude, use_git=args.use_git, as_of=args.as_of)
    surface = build_surface(profile, as_of=args.as_of)

    csvs = write_csv(surface, out_dir)
    print(f"CSV → {', '.join(str(p) for p in csvs)}")

    print()
    print(render_ascii(surface))

    if not args.no_png:
        pngs = render_png(surface, out_dir)
        if pngs:
            print(f"\nPNG → {', '.join(str(p) for p in pngs)}")
        else:
            print("\n(matplotlib not installed — CSV + ASCII only. "
                  "`pip install matplotlib` for the PNG figure.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
