"""Graph the FleetHorizon A/B — the monotonicity curves, made visual.

A table proves the gap; a curve *shows* it. This module collects the sweep into
structured points and renders them three ways, in increasing fidelity and
decreasing availability:

  1. **CSV** (always — stdlib) → `*.csv` next to the script, for any external
     plotter (Excel, gnuplot, a notebook). The honest, portable artifact.
  2. **ASCII charts** (always — stdlib) → printed to the terminal, matching the
     harness's text aesthetic, so you ALWAYS see the shape even with no deps.
  3. **PNG charts** (only if `matplotlib` is importable) → `*.png` files, the
     persuasive artifacts for a doc/slide. DOS's kernel is PyYAML-only and this
     benchmark is a consumer (the `examples/` boundary), so matplotlib is NEVER a
     hard dependency — its absence degrades to (1)+(2), never an error.

The four charts (each one of the operator's two axes × the two sweep variables):

  A. integrity edge vs HORIZON   — DOS verified/$ edge climbs with horizon (and
                                    dips below 1.0 at short horizon — the falsifier)
  B. collisions prevented vs FLEET — strictly a fleet phenomenon (0 at fleet=1)
  C. human-review FRACTION vs FLEET — open 100% flat; closed low+flat (the Faros lever)
  D. loaded-cost divergence vs HORIZON — open true-cost diverges; closed stays linear

Run:
    PYTHONPATH=src python -m benchmark.fleet_horizon.plot
    PYTHONPATH=src python -m benchmark.fleet_horizon.plot --out-dir build/
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .harness import run_cell


# ---------------------------------------------------------------------------
# Data collection — pure: returns lists of points. Rendering is separate.
# ---------------------------------------------------------------------------

HORIZONS = (1, 3, 8, 20, 40)
FLEETS = (1, 2, 4, 8, 12)


def collect() -> dict:
    """Run the two sweeps once; return all series as plain dicts of lists.

    Kept separate from rendering so the SAME data feeds CSV, ASCII, and PNG (no
    chance of three renderers disagreeing about the numbers)."""
    horizon_rows = []
    for h in HORIZONS:
        o, c = run_cell(efforts=6, phases=h)
        edge = (c.defect_adjusted_verified_per_dollar /
                o.defect_adjusted_verified_per_dollar
                if o.defect_adjusted_verified_per_dollar else 0.0)
        horizon_rows.append({
            "horizon": h,
            "lies_caught": c.caught_lies,
            "overwrites_prevented": c.refused_writes,
            "open_defect_debt": o.defect_debt,
            "dos_edge": round(edge, 3),
            "open_true_cost": o.defect_adjusted_cost,
            "closed_true_cost": c.defect_adjusted_cost,
            "open_verified_velocity_$": round(o.verified_velocity_per_dollar, 4),
            "closed_verified_velocity_$": round(c.verified_velocity_per_dollar, 4),
        })

    fleet_rows = []
    for f in FLEETS:
        o, c = run_cell(efforts=f, phases=20)
        fleet_rows.append({
            "fleet": f,
            "lies_caught": c.caught_lies,
            "overwrites_prevented": c.refused_writes,
            "open_review_fraction": round(o.human_review_fraction, 4),
            "closed_review_fraction": round(c.human_review_fraction, 4),
            "open_defect_debt": o.defect_debt,
        })
    return {"by_horizon": horizon_rows, "by_fleet": fleet_rows}


# ---------------------------------------------------------------------------
# (1) CSV — always.
# ---------------------------------------------------------------------------

def write_csv(data: dict, out_dir: Path) -> list[Path]:
    written = []
    for name, rows in data.items():
        if not rows:
            continue
        path = out_dir / f"fleet_horizon_{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# (2) ASCII charts — always (stdlib). Horizontal bars + a tiny line sparkline.
# ---------------------------------------------------------------------------

_BLOCKS = " ▁▂▃▄▅▆▇█"


def _bar(value: float, vmax: float, width: int = 40) -> str:
    if vmax <= 0:
        return ""
    n = int(round((value / vmax) * width))
    return "█" * n


def _sparkline(values: list[float]) -> str:
    lo, hi = min(values), max(values)
    if hi == lo:
        return _BLOCKS[4] * len(values)
    out = []
    for v in values:
        idx = int(round((v - lo) / (hi - lo) * (len(_BLOCKS) - 1)))
        out.append(_BLOCKS[idx])
    return "".join(out)


def render_ascii(data: dict) -> str:
    L: list[str] = []
    H = data["by_horizon"]
    F = data["by_fleet"]

    L.append("=" * 72)
    L.append("FleetHorizon — the gap, drawn (ASCII; PNGs alongside if matplotlib present)")
    L.append("=" * 72)

    # A. DOS edge vs horizon (the headline monotonicity)
    L.append("\n[A] DOS verified/$ edge vs HORIZON (fleet=6) — climbs as the horizon grows")
    L.append("    (a value <1.00 means DOS costs MORE — the honest short-horizon falsifier)")
    emax = max(r["dos_edge"] for r in H)
    for r in H:
        marker = "  ← DOS overhead" if r["dos_edge"] < 1.0 else ""
        L.append(f"    h={r['horizon']:>3}  {r['dos_edge']:>5.2f}x |{_bar(r['dos_edge'], emax)}{marker}")
    L.append(f"    spark: {_sparkline([r['dos_edge'] for r in H])}  (h={HORIZONS[0]}→{HORIZONS[-1]})")

    # B. collisions prevented vs fleet (fleet phenomenon)
    L.append("\n[B] silent overwrites PREVENTED vs FLEET (horizon=20) — 0 at fleet=1")
    omax = max(r["overwrites_prevented"] for r in F) or 1
    for r in F:
        z = "  ← nothing to collide with" if r["overwrites_prevented"] == 0 else ""
        L.append(f"    n={r['fleet']:>3}  {r['overwrites_prevented']:>4} |{_bar(r['overwrites_prevented'], omax)}{z}")

    # C. human-review fraction vs fleet (the velocity lever)
    L.append("\n[C] human-review FRACTION vs FLEET (horizon=20) — open must review ALL")
    for r in F:
        ob = _bar(r["open_review_fraction"], 1.0, 20)
        cb = _bar(r["closed_review_fraction"], 1.0, 20)
        L.append(f"    n={r['fleet']:>3}  open  {r['open_review_fraction']:>5.0%} |{ob}")
        L.append(f"          closed {r['closed_review_fraction']:>5.0%} |{cb}")

    # D. loaded/true-cost divergence vs horizon
    L.append("\n[D] TRUE cost (spend+defect debt) vs HORIZON (fleet=6) — open diverges")
    cmax = max(max(r["open_true_cost"], r["closed_true_cost"]) for r in H) or 1
    for r in H:
        L.append(f"    h={r['horizon']:>3}  open   {r['open_true_cost']:>7.0f} |{_bar(r['open_true_cost'], cmax)}")
        L.append(f"          closed {r['closed_true_cost']:>7.0f} |{_bar(r['closed_true_cost'], cmax)}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# (3) PNG charts — only if matplotlib is importable.
# ---------------------------------------------------------------------------

def render_png(data: dict, out_dir: Path) -> list[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")          # headless — no display needed
        import matplotlib.pyplot as plt
    except Exception:
        return []                       # graceful: CSV+ASCII already emitted

    H = data["by_horizon"]
    F = data["by_fleet"]
    written: list[Path] = []

    # one 2×2 figure — the four charts on one persuasive sheet
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle("FleetHorizon — believed (open) vs adjudicated (closed), same fleet & seed",
                 fontsize=13, fontweight="bold")

    # A. DOS edge vs horizon
    ax = axes[0][0]
    xs = [r["horizon"] for r in H]
    ax.plot(xs, [r["dos_edge"] for r in H], "o-", color="#2b8a3e", linewidth=2)
    ax.axhline(1.0, color="#888", linestyle="--", linewidth=1)
    ax.fill_between(xs, [r["dos_edge"] for r in H], 1.0,
                    where=[r["dos_edge"] >= 1.0 for r in H], alpha=0.15, color="#2b8a3e")
    ax.set_title("A. DOS verified/$ edge vs horizon\n(climbs with horizon; <1 = DOS overhead)")
    ax.set_xlabel("horizon (phases per effort)")
    ax.set_ylabel("closed ÷ open  (defect-adjusted verified/$)")
    ax.grid(alpha=0.3)

    # B. collisions prevented vs fleet
    ax = axes[0][1]
    xf = [r["fleet"] for r in F]
    ax.bar(xf, [r["overwrites_prevented"] for r in F], color="#1971c2", alpha=0.8)
    ax.set_title("B. silent overwrites prevented vs fleet\n(0 at fleet=1 — a fleet phenomenon)")
    ax.set_xlabel("fleet size (concurrent efforts)")
    ax.set_ylabel("overwrites the arbiter prevented")
    ax.grid(alpha=0.3, axis="y")

    # C. human-review fraction vs fleet
    ax = axes[1][0]
    ax.plot(xf, [r["open_review_fraction"] for r in F], "o-", color="#e8590c",
            linewidth=2, label="open (believe)")
    ax.plot(xf, [r["closed_review_fraction"] for r in F], "s-", color="#2b8a3e",
            linewidth=2, label="closed (DOS)")
    ax.set_title("C. human-review fraction vs fleet\n(the Faros-paradox lever)")
    ax.set_xlabel("fleet size (concurrent efforts)")
    ax.set_ylabel("share of 'done' that needed a human")
    ax.set_ylim(0, 1.05)
    ax.legend()
    ax.grid(alpha=0.3)

    # D. true-cost divergence vs horizon
    ax = axes[1][1]
    ax.plot(xs, [r["open_true_cost"] for r in H], "o-", color="#e8590c",
            linewidth=2, label="open (spend+defect debt)")
    ax.plot(xs, [r["closed_true_cost"] for r in H], "s-", color="#2b8a3e",
            linewidth=2, label="closed (no debt)")
    ax.set_title("D. true cost vs horizon\n(open diverges as lies compound)")
    ax.set_xlabel("horizon (phases per effort)")
    ax.set_ylabel("fully-loaded cost")
    ax.legend()
    ax.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    combined = out_dir / "fleet_horizon_charts.png"
    fig.savefig(combined, dpi=120)
    plt.close(fig)
    written.append(combined)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Graph the FleetHorizon A/B sweeps")
    ap.add_argument("--out-dir", default=str(Path(__file__).parent / "build"),
                    help="where CSV/PNG land (default: benchmark/fleet_horizon/build)")
    ap.add_argument("--no-png", action="store_true", help="skip PNG even if matplotlib is present")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Collecting sweep data (drives the real kernel — a minute or two)...")
    data = collect()

    csvs = write_csv(data, out_dir)
    print(f"\nCSV → {', '.join(str(p) for p in csvs)}")

    print()
    print(render_ascii(data))

    if not args.no_png:
        pngs = render_png(data, out_dir)
        if pngs:
            print(f"\nPNG → {', '.join(str(p) for p in pngs)}")
        else:
            print("\n(matplotlib not installed — CSV + ASCII only. "
                  "`pip install matplotlib` for PNG charts.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
