"""Figures for the Toolathlon $0-replay study (docs/157).

Renders the per-model story the corpus headline hides — the whole point is that
`dangling_intent prec=98% / lift+21.9pp` is a Simpson's-paradox aggregate, and the
*honest* picture is per-model. Reads ONLY the durable artifact
`_results/replay_all.json` (the aggregate + per-model confusion grids); writes PNG +
SVG to `_results/` (gitignored). Zero network, zero LLM — regenerate in <1s.

Capability x-axis = **base pass-rate on Toolathlon** (1 - base_fail_rate), derived
from the SAME third-party oracle that scores the detectors. We deliberately do NOT
import an external leaderboard: the honest in-data capability proxy is "how many
tasks did this model pass," and a reviewer can audit it from this file alone.

    python -m benchmark.toolathlon.viz
    python -m benchmark.toolathlon.viz --json path/to/replay_all.json --out-dir DIR

Figures:
  fig1_purchase_vs_capability   the HEADLINE — fire-rate & precision-lift vs capability,
                                showing purchase decaying to ~0 on the frontier.
  fig2_per_model_grid           per-model fire / precision / false-alarm / lift bars
                                (the table the corpus number averages over).
  fig3_simpson                  cumulative corpus precision/lift as models are added
                                worst-first — how few models carry the headline.
  fig4_confusion                per-detector confusion squares (fired-fail / fired-pass /
                                quiet-fail / quiet-pass) as a recall/precision picture.
  fig5_lift_vs_recall           the "why doesn't the big lift carry over?" answer — precision
                                (carries, ~flat-high) vs recall (collapses to 0 on the frontier) on
                                one capability axis. Different questions: the headline quotes
                                precision-lift; the ceiling is recall.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless; no display
import matplotlib.pyplot as plt
import numpy as np

_HERE = Path(__file__).resolve().parent
_DEFAULT_JSON = _HERE / "_results" / "replay_all.json"
_DEFAULT_OUT = _HERE / "_results"

DETECTORS = ("dangling_intent", "tool_stream")
_COLOR = {"dangling_intent": "#2563eb", "tool_stream": "#d97706"}  # blue / amber
_PASS = "#16a34a"  # green
_FAIL = "#dc2626"  # red
_GREY = "#9ca3af"


# ----------------------------------------------------------------------------- io
def load(json_path: Path) -> dict:
    with json_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _models_by_capability(data: dict) -> list[str]:
    """Models sorted by Toolathlon pass-rate (least capable first).

    pass_rate = 1 - base_fail_rate; ties broken by name for determinism.
    """
    rows = []
    for model, dets in data["by_model"].items():
        # base_fail_rate is identical across detectors for a model (same oracle);
        # read it off whichever detector is present.
        any_det = next(iter(dets.values()))
        fail = any_det["base_fail_rate"]
        rows.append((1.0 - fail, model))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [m for _, m in rows]


def _pct(x: float | None) -> float:
    return float("nan") if x is None else 100.0 * x


# --------------------------------------------------------------- fig 1 (headline)
def fig_purchase_vs_capability(data: dict, out_dir: Path) -> Path:
    models = _models_by_capability(data)
    cap = np.array([100.0 * (1.0 - next(iter(data["by_model"][m].values()))["base_fail_rate"]) for m in models])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    fig.suptitle(
        "DOS detector PURCHASE decays to ~0 as model capability rises\n"
        "Toolathlon $0 replay · 22 models · third-party-scored · x = Toolathlon pass-rate (capability proxy)",
        fontsize=12, fontweight="bold",
    )

    # left: fire-rate vs capability
    axL = axes[0]
    for det in DETECTORS:
        fr = np.array([_pct(data["by_model"][m][det]["fire_rate"]) for m in models])
        axL.scatter(cap, fr, s=46, color=_COLOR[det], label=det, alpha=0.85, zorder=3, edgecolor="white", linewidth=0.6)
        # trend line (least squares; purely visual)
        if np.isfinite(fr).sum() >= 2:
            b, a = np.polyfit(cap, fr, 1)
            xs = np.array([cap.min(), cap.max()])
            axL.plot(xs, a + b * xs, color=_COLOR[det], lw=1.3, ls="--", alpha=0.7, zorder=2)
    axL.set_xlabel("model capability →  (Toolathlon task pass-rate, %)")
    axL.set_ylabel("detector fire-rate (% of runs)")
    axL.set_title("Fires concentrate on the WEAK models")
    axL.grid(True, alpha=0.25)
    axL.legend(frameon=False, fontsize=9)
    # annotate the loudest + the silent frontier
    _annotate_extremes(axL, cap, [_pct(data["by_model"][m]["dangling_intent"]["fire_rate"]) for m in models], models)

    # right: precision-lift vs capability (only where the detector fired)
    axR = axes[1]
    axR.axhline(0, color=_GREY, lw=1, zorder=1)
    for det in DETECTORS:
        lift = np.array([_pct(data["by_model"][m][det]["lift_over_base"]) for m in models])
        fired = np.array([data["by_model"][m][det]["fired"] for m in models])
        mask = fired > 0
        axR.scatter(
            cap[mask], lift[mask],
            s=30 + 8 * np.sqrt(fired[mask]),  # area ~ #fires
            color=_COLOR[det], label=f"{det} (size ∝ #fires)", alpha=0.8,
            zorder=3, edgecolor="white", linewidth=0.6,
        )
    axR.set_xlabel("model capability →  (Toolathlon task pass-rate, %)")
    axR.set_ylabel("precision LIFT over base-fail-rate (pp)")
    axR.set_title("Where it DOES fire, lift is +; silent on the frontier")
    axR.grid(True, alpha=0.25)
    axR.legend(frameon=False, fontsize=8, loc="lower right")

    fig.text(
        0.5, 0.005,
        "DETECT not FIX (frozen trajectories). Frontier models (claude-4.5-sonnet/opus·gpt-5.1·gemini-3-pro·deepseek-3.2) fire ≈0 → no purchase where lift would be leaderboard-citable.",
        ha="center", fontsize=8, color="#444",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.93))
    return _save(fig, out_dir, "fig1_purchase_vs_capability")


def _annotate_extremes(ax, xs, ys, models, k=2):
    ys = np.array(ys, dtype=float)
    order = np.argsort(np.nan_to_num(ys, nan=-1))
    for idx in list(order[-k:]):  # loudest
        if ys[idx] > 0:
            ax.annotate(models[idx], (xs[idx], ys[idx]), fontsize=7.5, color="#333",
                        xytext=(4, 3), textcoords="offset points")


# ----------------------------------------------------------- fig 2 (per-model grid)
def fig_per_model_grid(data: dict, out_dir: Path) -> Path:
    models = _models_by_capability(data)
    y = np.arange(len(models))
    fig, axes = plt.subplots(1, 4, figsize=(15, 8.5), sharey=True)
    fig.suptitle(
        "Per-model breakdown — the table the corpus headline averages over\n"
        "(models ordered least→most capable, top→bottom)",
        fontsize=12, fontweight="bold",
    )

    panels = [
        ("fire_rate", "fire-rate (%)", True),
        ("oracle_confirmed_precision", "precision (%)", True),
        ("false_alarm_rate", "false-alarm (%)", True),
        ("lift_over_base", "lift over base (pp)", True),
    ]
    h = 0.38
    for ax, (key, title, as_pct) in zip(axes, panels):
        for i, det in enumerate(DETECTORS):
            vals = []
            for m in models:
                v = data["by_model"][m][det][key]
                vals.append(_pct(v) if as_pct else (float("nan") if v is None else v))
            vals = np.array(vals, dtype=float)
            off = (i - 0.5) * h
            ax.barh(y + off, np.nan_to_num(vals), height=h, color=_COLOR[det],
                    alpha=0.85, label=det, zorder=3)
            # mark "did not fire / undefined" cells with a tick at 0
            for j, v in enumerate(vals):
                if np.isnan(v):
                    ax.plot(0, y[j] + off, marker="|", color=_GREY, ms=7, zorder=4)
        if key == "lift_over_base":
            ax.axvline(0, color=_GREY, lw=1, zorder=1)
        ax.set_title(title, fontsize=10)
        ax.grid(True, axis="x", alpha=0.25)
        ax.invert_yaxis()

    axes[0].set_yticks(y)
    axes[0].set_yticklabels(models, fontsize=8)
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.text(0.5, 0.008, "grey tick at 0 = detector never fired on that model (precision/lift undefined, not zero).",
             ha="center", fontsize=8, color="#444")
    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    return _save(fig, out_dir, "fig2_per_model_grid")


# ------------------------------------------------------------- fig 3 (Simpson view)
def fig_simpson(data: dict, out_dir: Path) -> Path:
    """Cumulative corpus precision/lift as models are folded in worst-first.

    Shows how the 98%/+21.9pp headline is carried by a few high-fire models, not
    the population. We accumulate raw confusion counts (the honest way to pool).
    """
    models = _models_by_capability(data)  # least capable (highest fail) ... but we want
    # worst-DETECTOR-first to show concentration; order by #fires descending.
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.0))
    fig.suptitle(
        "How few models carry the corpus headline (Simpson's-paradox view)\n"
        "cumulative pooled precision & lift as models are added most-fires-first",
        fontsize=12, fontweight="bold",
    )

    for ax, det in zip(axes, DETECTORS):
        order = sorted(models, key=lambda m: data["by_model"][m][det]["fired"], reverse=True)
        cum_ff = cum_fp = 0
        cum_fail = cum_n = 0
        xs, prec, lift, labels = [], [], [], []
        added_fire = 0
        for k, m in enumerate(order, 1):
            d = data["by_model"][m][det]
            cum_ff += d["fired_fail"]
            cum_fp += d["fired_pass"]
            cum_fail += d["oracle_failed"]
            cum_n += d["labeled"]
            added_fire += d["fired"]
            fired = cum_ff + cum_fp
            p = (cum_ff / fired) if fired else float("nan")
            base = (cum_fail / cum_n) if cum_n else float("nan")
            xs.append(k)
            prec.append(100.0 * p if fired else float("nan"))
            lift.append(100.0 * (p - base) if fired else float("nan"))
            labels.append(m)
        ax.plot(xs, prec, "-o", color=_COLOR[det], ms=4, label="pooled precision %", zorder=3)
        ax.plot(xs, lift, "-s", color="#7c3aed", ms=4, label="pooled lift pp", zorder=3)
        ax.axhline(0, color=_GREY, lw=1)
        # mark where 90% of all fires are accounted for
        total_fire = sum(data["by_model"][m][det]["fired"] for m in models)
        run = 0
        for k, m in enumerate(order, 1):
            run += data["by_model"][m][det]["fired"]
            if total_fire and run >= 0.9 * total_fire:
                ax.axvline(k, color="#444", ls=":", lw=1)
                ax.annotate(f"90% of all fires\nby model #{k}", (k, ax.get_ylim()[0]),
                            fontsize=7.5, color="#444", xytext=(3, 14), textcoords="offset points")
                break
        ax.set_title(det, fontsize=10)
        ax.set_xlabel("# models pooled (most-fires-first) →")
        ax.set_ylabel("cumulative %  /  pp")
        ax.grid(True, alpha=0.25)
        ax.legend(frameon=False, fontsize=8, loc="center right")
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return _save(fig, out_dir, "fig3_simpson")


# ----------------------------------------------------------- fig 4 (confusion grid)
def fig_confusion(data: dict, out_dir: Path) -> Path:
    fig, axes = plt.subplots(1, len(DETECTORS), figsize=(11, 4.6))
    fig.suptitle(
        "Corpus confusion: high precision, ~2% recall (the EOG ceiling, third-party-confirmed)",
        fontsize=12, fontweight="bold",
    )
    for ax, det in zip(np.atleast_1d(axes), DETECTORS):
        d = data["detectors"][det]
        grid = np.array([[d["fired_fail"], d["fired_pass"]],
                         [d["quiet_fail"], d["quiet_pass"]]], dtype=float)
        # color by row-normalized intensity but annotate raw counts
        norm = grid / grid.sum()
        ax.imshow(norm, cmap="Blues", vmin=0, vmax=norm.max())
        cells = [["TP  fired·fail", "FP  fired·pass"],
                 ["FN  quiet·fail", "TN  quiet·pass"]]
        for r in range(2):
            for c in range(2):
                ax.text(c, r, f"{cells[r][c]}\n{int(grid[r, c]):,}",
                        ha="center", va="center", fontsize=10,
                        color="white" if norm[r, c] > norm.max() * 0.55 else "#111")
        ax.set_xticks([0, 1]); ax.set_xticklabels(["oracle FAIL", "oracle PASS"], fontsize=9)
        ax.set_yticks([0, 1]); ax.set_yticklabels(["DOS fired", "DOS quiet"], fontsize=9)
        prec = 100.0 * d["oracle_confirmed_precision"]
        rec = 100.0 * d["recall_of_failures"]
        fa = 100.0 * d["false_alarm_rate"]
        ax.set_title(f"{det}\nprec {prec:.0f}% · recall {rec:.1f}% · false-alarm {fa:.1f}%", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return _save(fig, out_dir, "fig4_confusion")


# ------------------------------------------- fig 5 (why the lift doesn't carry over)
def fig_lift_vs_recall(data: dict, out_dir: Path) -> Path:
    """The direct answer to 'if the lift is so big, why doesn't it carry over?'

    Two questions get conflated in the headline. PRECISION ("when it fires, is it right?") is high
    AND carries across capability — that is the +22pp lift. RECALL ("of all failures, how many does
    it catch?") is tiny AND collapses to 0 on the frontier — that is the ceiling. Plotting both on
    one capability axis makes the split legible: the big number is the flat-high line, the ceiling
    is the line that dives to zero. They are not in tension; they answer different questions.
    """
    models = _models_by_capability(data)
    cap = np.array([100.0 * (1.0 - next(iter(data["by_model"][m].values()))["base_fail_rate"]) for m in models])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    fig.suptitle(
        "Why the +22pp lift does NOT carry over: PRECISION carries, RECALL collapses\n"
        "two different questions — the headline quotes precision-lift; the ceiling is recall",
        fontsize=12, fontweight="bold",
    )
    for ax, det in zip(axes, DETECTORS):
        prec = np.array([_pct(data["by_model"][m][det]["oracle_confirmed_precision"]) for m in models])
        rec = np.array([_pct(data["by_model"][m][det]["recall_of_failures"]) for m in models])
        fired = np.array([data["by_model"][m][det]["fired"] for m in models])
        # precision only defined where it fired
        pm = fired > 0
        ax.scatter(cap[pm], prec[pm], s=44, color=_PASS, label="precision: 'when it fires, right?' (CARRIES)",
                   zorder=3, edgecolor="white", linewidth=0.6)
        ax.scatter(cap, rec, s=44, color=_FAIL, marker="v",
                   label="recall: 'of failures, caught?' (COLLAPSES)", zorder=3, edgecolor="white", linewidth=0.6)
        # trend for recall (the collapsing one)
        if np.isfinite(rec).sum() >= 2:
            b, a = np.polyfit(cap, rec, 1)
            xs = np.array([cap.min(), cap.max()])
            ax.plot(xs, a + b * xs, color=_FAIL, lw=1.3, ls="--", alpha=0.7, zorder=2)
        ax.axhline(100 * data["detectors"][det]["base_fail_rate"], color=_GREY, lw=1, ls=":",
                   label=f"base-fail {100*data['detectors'][det]['base_fail_rate']:.0f}% (precision floor)")
        ax.set_ylim(-4, 108)
        ax.set_xlabel("model capability →  (Toolathlon pass-rate, %)")
        ax.set_ylabel("%")
        ax.set_title(det, fontsize=10)
        ax.grid(True, alpha=0.25)
        ax.legend(frameon=False, fontsize=7.5, loc="center right")
    fig.text(
        0.5, 0.005,
        "Precision high+flat = the big lift, and it generalizes. Recall ~2% and sloping to 0 on the frontier = the ceiling. "
        "A fire is rare but trustworthy; the failures it can SEE shrink to zero as models get strong (they fail silently).",
        ha="center", fontsize=8, color="#444",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.9))
    return _save(fig, out_dir, "fig5_lift_vs_recall")


# --------------------------------------------- fig 6 (terminal_error additivity, docs/158)
#
# This figure draws EVERY number from `additivity.compute()` — the single source of truth (the same
# function the claims ledger and the test suite consume) — so it can NOT drift from the asserted
# prose. "Frontier" is therefore exactly `additivity.FRONTIER_PASS_RATE` (a data-derived capability
# cut: pass-rate ≥ 0.30, the strongest ~8 models), NOT a hand-listed model set. The honest framing
# baked into the SSOT: on that frontier the pair is NOT blind (it already catches some), so
# terminal_error is ADDITIVE there (+`frontier_te_netnew` the pair missed), never "first to reach
# the frontier" — the over-claim a stale draft made.


def fig_trio_additivity(rows_csv: Path, out_dir: Path) -> "Path | None":
    """The docs/158 result: terminal_error raises UNION recall and is ADDITIVE on the frontier.

    Left: union recall pair (dangling+tool_stream) vs trio (+terminal_error). Right: terminal_error's
    net-new catches, split frontier vs non-frontier. All counts come from `additivity.compute()` so
    the figure stays locked to the claims ledger + the test suite. Returns None if the CSV is absent.
    """
    if not rows_csv.exists():
        return None
    from .additivity import compute, load_rows

    st = compute(load_rows(rows_csv))
    nF = st.n_failed
    if nF == 0:
        return None
    pair_rec = 100.0 * st.pair.recall
    trio_rec = 100.0 * st.trio.recall
    nn = st.te_netnew_total            # 75: terminal_error catches the pair missed, corpus-wide
    nf = st.te_netnew_frontier         # 9:  of those, how many on frontier (pass-rate ≥ cut)

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))
    fig.suptitle(
        "terminal_error raises union recall and is ADDITIVE on the frontier (docs/158)\n"
        "the agent stopped on an env failure it never fixed — byte-clean, +30% relative recall",
        fontsize=12, fontweight="bold",
    )
    # left: union recall pair vs trio
    axL = axes[0]
    vals = [pair_rec, trio_rec]
    bars = axL.bar(["pair\n(dangling+tool_stream)", "trio\n(+ terminal_error)"], vals,
                   color=[_GREY, _PASS], zorder=3, width=0.6)
    for b, v in zip(bars, vals):
        axL.text(b.get_x() + b.get_width() / 2, v + 0.08, f"{v:.2f}%", ha="center", fontsize=11, fontweight="bold")
    axL.set_ylabel("union recall of failures (%)")
    axL.set_title(f"union recall: {pair_rec:.2f}% → {trio_rec:.2f}%  (n_fail={nF})", fontsize=10)
    axL.grid(True, axis="y", alpha=0.25)
    axL.set_ylim(0, max(vals) * 1.25)
    # right: net-new catches, frontier split (frontier = additivity.FRONTIER_PASS_RATE)
    axR = axes[1]
    axR.bar(["net-new catches"], [nn - nf], color=_COLOR["tool_stream"], label="non-frontier model", zorder=3, width=0.5)
    axR.bar(["net-new catches"], [nf], bottom=[nn - nf], color="#7c3aed", label="FRONTIER model", zorder=3, width=0.5)
    axR.text(0, nn + 1, f"{nn} net-new\n({nf} on frontier)", ha="center", fontsize=10, fontweight="bold")
    axR.set_ylabel("failures caught that the pair MISSED")
    axR.set_title(f"terminal_error catches what the pair missed —\n"
                  f"incl. +{nf} on the frontier (additive: the pair already caught {st.frontier_pair_tp} there)",
                  fontsize=10)
    axR.set_ylim(0, nn * 1.3)
    axR.legend(frameon=False, fontsize=9, loc="upper right")
    axR.grid(True, axis="y", alpha=0.25)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return _save(fig, out_dir, "fig6_trio_additivity")


# --------------------------------------------------------------------------- save
def _save(fig, out_dir: Path, stem: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}.png"
    svg = out_dir / f"{stem}.svg"
    fig.savefig(png, dpi=150)
    fig.savefig(svg)
    plt.close(fig)
    return png


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 trap
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", type=Path, default=_DEFAULT_JSON, help="aggregate replay JSON")
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT, help="where to write figures")
    args = ap.parse_args(argv)

    if not args.json.exists():
        ap.error(f"no aggregate JSON at {args.json} — run run_replay.py --all ... --out first")
    data = load(args.json)

    written = [
        fig_purchase_vs_capability(data, args.out_dir),
        fig_per_model_grid(data, args.out_dir),
        fig_simpson(data, args.out_dir),
        fig_confusion(data, args.out_dir),
        fig_lift_vs_recall(data, args.out_dir),
    ]
    # fig6 reads the durable rows CSV (per-run flags), not the aggregate JSON
    rows_csv = args.json.parent / "replay_all_rows.csv"
    f6 = fig_trio_additivity(rows_csv, args.out_dir)
    if f6 is not None:
        written.append(f6)
    print(f"# {data['n_records']} records · {len(data['by_model'])} models")
    for p in written:
        print(f"wrote {p.relative_to(_HERE.parent.parent) if _HERE.parent.parent in p.parents else p}")
        print(f"      {p.with_suffix('.svg').name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
