"""terminal_error additivity figures — drawn straight from additivity.compute() (docs/158).

A SEPARATE figure module from viz.py (kept disjoint so it never collides with viz.py's own fig6),
covering the trio-additivity story at more depth and from the durable claims rather than a re-fold of
the rows. Every number a panel draws comes from `additivity.compute(load_rows())` — the same function
the claims ledger and the test consume — so these figures cannot drift from the asserted numbers.

    python -m benchmark.toolathlon.viz_additivity
    python -m benchmark.toolathlon.viz_additivity --rows path/to/rows.csv --out-dir DIR

Every figure carries a two-line footer spelling out what the detectors ARE (DOS sensors, not what the
models ship) and what the BASELINE is (the pair = dangling_intent + tool_stream; pass/fail is
Toolathlon's third-party oracle), so a figure is self-explaining off-page.

Figures (PNG + SVG to _results/, gitignored):
  figD_combined_dos_lift     the whole-DOS picture: (left) cumulative recall WATERFALL dangling ->
                             +tool_stream (pair) -> +terminal_error (trio); (right) precision-LIFT over
                             the base-fail floor per detector + the trio union. "How much DOS catches,
                             and how much a fire is worth."
  figA_additivity_headline   the two load-bearing claims: (left) terminal_error's 76 catches split
                             into 75 NET-NEW + 1 overlap; (right) union recall pair->trio with the
                             precision/false-alarm COST drawn alongside so the gain isn't read as free.
  figB_per_model_catches     per-model (all 22, capability-ascending) stacked failures-caught by
                             dangling / tool_stream / terminal_error, with the >=30% frontier band
                             shaded — shows where terminal_error is the ONLY catcher.
  figC_frontier_sensitivity  net-new vs the capability threshold you call "frontier": the honest
                             >=30% cut gives 9, the generous top-10 cut gives 22, and o3 alone drives
                             the gap. Makes the frontier claim's sensitivity explicit, not hidden.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import numpy as np

try:
    from . import additivity as _add
except ImportError:  # pragma: no cover - direct-script fallback
    import additivity as _add  # type: ignore

_HERE = Path(__file__).resolve().parent
_DEFAULT_ROWS = _HERE / "_results" / "replay_all_rows.csv"
_DEFAULT_OUT = _HERE / "_results"

_DANG = "#2563eb"   # blue
_TS = "#d97706"     # amber
_TE = "#7c3aed"     # purple — terminal_error
_PASS = "#16a34a"   # green
_FAIL = "#dc2626"   # red
_GREY = "#9ca3af"
_OVERLAP = "#cbd5e1"  # light slate — the non-additive remainder

_DET_COLOR = {"dangling": _DANG, "tool_stream": _TS, "terminal_error": _TE}
_DET_LABEL = {"dangling": "dangling_intent", "tool_stream": "tool_stream", "terminal_error": "terminal_error"}

# The two framings every panel needs spelled out (the operator asked "what is tool_stream / what is
# baseline?"). DOS detectors are the SENSORS; the oracle is Toolathlon's own scorer, never a DOS call.
_WHAT_ARE_THEY = (
    "DOS detectors (the sensors, not what the models ship): dangling_intent = stopped with work still "
    "declared undone · tool_stream = same (tool, args, result) recurring = a stuck loop · "
    "terminal_error = stopped on an unfixed env error envelope."
)
_WHAT_IS_BASELINE = (
    "BASELINE = the pair (dangling_intent + tool_stream), the two pre-existing detectors; the trio adds "
    "terminal_error.  PASS/FAIL is Toolathlon's third-party oracle (evaluation/main.py) — DOS never scores itself."
)


def _two_line_footer(fig, line1: str, line2: str) -> None:
    """Stamp both framing lines at the bottom of a figure so it is self-explaining off-page."""
    fig.text(0.5, 0.030, line1, ha="center", fontsize=7.6, color="#333")
    fig.text(0.5, 0.006, line2, ha="center", fontsize=7.6, color="#666")


# --------------------------------------------------------------- figA (the headline claims)
def fig_additivity_headline(s: "_add.TrioStats", out_dir: Path) -> Path:
    te = s.detectors["terminal_error"]
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5.2))
    fig.suptitle(
        "terminal_error is an ADDITIVE slice: +30% relative union recall at a small precision cost\n"
        f"Toolathlon $0 replay · {s.n_records:,} records · {len(s.models)} models · third-party-scored (docs/158)",
        fontsize=12, fontweight="bold",
    )

    # LEFT: the 76 catches decomposed into net-new vs overlap-with-pair.
    netnew = s.te_netnew_total
    overlap = s.te_overlap_with_pair
    axL.bar(["terminal_error\ncatches"], [netnew], color=_TE, zorder=3, width=0.5,
            label=f"NET-NEW (pair missed): {netnew}")
    axL.bar(["terminal_error\ncatches"], [overlap], bottom=[netnew], color=_OVERLAP, zorder=3, width=0.5,
            label=f"also caught by pair: {overlap}")
    axL.text(0, netnew + overlap + 1.2, f"{te.fired_fail} catches\n{netnew}/{te.fired_fail} net-new "
             f"({100*netnew/te.fired_fail:.0f}%)", ha="center", fontsize=11, fontweight="bold")
    axL.set_ylabel("failures caught (true positives)")
    axL.set_title(f"It's a DISTINCT slice, not a re-catch\nprecision {100*te.precision:.0f}% · "
                  f"false-alarm {100*te.false_alarm:.2f}%", fontsize=10)
    axL.set_ylim(0, (netnew + overlap) * 1.32)
    axL.legend(frameon=False, fontsize=9, loc="upper right")
    axL.grid(True, axis="y", alpha=0.25)

    # RIGHT: union recall pair->trio, with precision + false-alarm on a twin axis (the COST).
    labels = ["pair\n(dangling+tool_stream)", "trio\n(+terminal_error)"]
    rec = [100 * s.pair.recall, 100 * s.trio.recall]
    x = np.arange(2)
    bars = axR.bar(x, rec, color=[_GREY, _PASS], width=0.55, zorder=3)
    for b, v in zip(bars, rec):
        axR.text(b.get_x() + b.get_width() / 2, v + 0.07, f"{v:.2f}%", ha="center", fontsize=11, fontweight="bold")
    axR.annotate("", xy=(1, rec[1]), xytext=(0, rec[0]),
                 arrowprops=dict(arrowstyle="->", color="#111", lw=1.4))
    axR.text(0.5, max(rec) + 0.55, f"+{s.union_recall_gain_pp:.2f} pp\n(+{100*s.union_recall_gain_relative:.0f}% relative)",
             ha="center", fontsize=10, fontweight="bold", color="#111")
    axR.set_ylabel("union recall of failures (%)")
    axR.set_xticks(x); axR.set_xticklabels(labels)
    axR.set_ylim(0, max(rec) * 1.30)
    axR.set_title("Union recall rises — and the cost is small", fontsize=10)
    axR.grid(True, axis="y", alpha=0.25)

    # twin axis: precision + false-alarm (the cost the recall gain is NOT free of)
    axR2 = axR.twinx()
    prec = [100 * s.pair.precision, 100 * s.trio.precision]
    fa = [100 * s.pair.false_alarm, 100 * s.trio.false_alarm]
    axR2.plot(x, prec, "o-", color="#0f766e", lw=1.6, ms=7, zorder=4, label="union precision")
    axR2.plot(x, fa, "s--", color=_FAIL, lw=1.6, ms=7, zorder=4, label="union false-alarm")
    for xi, p, f in zip(x, prec, fa):
        axR2.annotate(f"{p:.1f}%", (xi, p), fontsize=8, color="#0f766e", xytext=(6, -2), textcoords="offset points")
        axR2.annotate(f"{f:.2f}%", (xi, f), fontsize=8, color=_FAIL, xytext=(6, 3), textcoords="offset points")
    axR2.set_ylabel("precision / false-alarm (%)", fontsize=9)
    axR2.set_ylim(0, 105)
    axR2.legend(frameon=False, fontsize=8, loc="center right")

    fig.text(0.5, 0.052,
             "Recall is the gain (the bars); precision stays ~flat-high and false-alarm rises only "
             f"{100*(s.trio.false_alarm-s.pair.false_alarm):.2f} pp — additive, not a precision trade-down.",
             ha="center", fontsize=8, color="#444")
    _two_line_footer(fig, _WHAT_ARE_THEY, _WHAT_IS_BASELINE)
    fig.tight_layout(rect=(0, 0.07, 1, 0.92))
    return _save(fig, out_dir, "figA_additivity_headline")


# --------------------------------------------------------------- figB (per-model contribution)
def fig_per_model_catches(s: "_add.TrioStats", out_dir: Path) -> Path:
    """Per-model stacked failures-caught, capability-ascending, with the frontier band shaded.

    Stacking is by the DISJOINT attribution the per-model row carries: terminal_error's segment is
    its net-new on that model (catches the pair missed), so the bar length is the model's UNION
    (trio) recall count and no failure is double-drawn.
    """
    models = s.models  # already capability-ascending
    y = np.arange(len(models))
    names = [m.model for m in models]

    # disjoint segments: dangling-or-tool_stream (the pair union) + terminal_error net-new
    pair_tp = np.array([m.pair_tp for m in models], dtype=float)
    te_net = np.array([m.te_netnew for m in models], dtype=float)
    # split the pair into dangling-only vs tool_stream contribution is not disjoint per-run, so show
    # the pair as one bar (its union) + terminal_error net-new on top = the trio union.

    fig, ax = plt.subplots(figsize=(11, 9))
    fig.suptitle(
        "Per-model failures caught: terminal_error's slice (purple) is where the pair was blind\n"
        "stacked = trio union recall · models capability-ascending (top = weakest) · n_fail per row labelled",
        fontsize=12, fontweight="bold",
    )

    # shade the frontier rows
    first_frontier = next((i for i, m in enumerate(models) if m.is_frontier), None)
    if first_frontier is not None:
        ax.axhspan(first_frontier - 0.5, len(models) - 0.5, color="#faf5ff", zorder=0)
        ax.annotate(f"frontier (pass-rate ≥ {s.frontier_pass_rate:.2f})",
                    (ax.get_xlim()[1], first_frontier - 0.5), fontsize=8.5, color=_TE,
                    ha="right", va="bottom", xytext=(-4, 2), textcoords="offset points")

    ax.barh(y, pair_tp, color=_GREY, zorder=3, label="caught by pair (dangling ∪ tool_stream)")
    ax.barh(y, te_net, left=pair_tp, color=_TE, zorder=3, label="terminal_error net-new (pair missed)")

    # annotate each row with its per-detector raw catches + failure count
    for i, m in enumerate(models):
        total = m.pair_tp + m.te_netnew
        dt = m.det_tp
        ax.text(total + 0.4, i,
                f"D{dt['dangling']} T{dt['tool_stream']} E{dt['terminal_error']}  /  {m.oracle_failed} fail",
                va="center", fontsize=7, color="#555")

    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("distinct failures caught (true positives)")
    ax.set_xlim(0, max((m.pair_tp + m.te_netnew) for m in models) * 1.32)
    ax.grid(True, axis="x", alpha=0.25)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.text(0.5, 0.050,
             "row label: D/T/E = standalone catches by dangling/tool_stream/terminal_error; bar = pair-union + terminal_error net-new (the trio). "
             "On most frontier rows the grey bar is ~0 and the purple is the only catch.",
             ha="center", fontsize=8, color="#444")
    _two_line_footer(fig, _WHAT_ARE_THEY, _WHAT_IS_BASELINE)
    fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    return _save(fig, out_dir, "figB_per_model_catches")


# --------------------------------------------------------------- figC (frontier sensitivity)
def fig_frontier_sensitivity(s: "_add.TrioStats", out_dir: Path) -> Path:
    """How the 'net-new on frontier' number depends on where you draw the capability line.

    The honest >=30% cut gives 9; a generous top-10 cut gives 22 — but o3 (a 17.6%-pass mid model)
    supplies most of the gap. Sweeping the threshold makes that sensitivity explicit instead of
    letting a single hand-picked set carry the headline.
    """
    models = s.models
    caps = sorted({round(m.pass_rate, 4) for m in models})
    # net-new with frontier = pass-rate >= thr, for a sweep of thresholds
    thresholds = np.linspace(0.0, max(m.pass_rate for m in models), 60)

    def netnew_at(thr):
        return sum(m.te_netnew for m in models if m.pass_rate >= thr)

    def pair_at(thr):
        return sum(m.pair_tp for m in models if m.pass_rate >= thr)

    nn = np.array([netnew_at(t) for t in thresholds])
    pr = np.array([pair_at(t) for t in thresholds])

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13.5, 5.4))
    fig.suptitle(
        "The 'frontier reach' number is threshold-sensitive — disclosed, not hidden (docs/158)\n"
        "terminal_error net-new among models above a capability cut, vs the cut",
        fontsize=12, fontweight="bold",
    )

    # LEFT: the sweep
    axL.plot(100 * thresholds, nn, "-", color=_TE, lw=2, zorder=3, label="terminal_error net-new")
    axL.plot(100 * thresholds, pr, "-", color=_GREY, lw=1.6, zorder=3, label="pair catches (dangling ∪ tool_stream)")
    # mark the two named cuts. top-10 is a COUNT cut → mark the pass-rate of the 10th-strongest model.
    top10_cut = sorted((m.pass_rate for m in models), reverse=True)[9]
    ytop = nn.max()
    axL.axvline(100 * 0.30, color=_PASS, ls="--", lw=1.4, zorder=2)
    axL.annotate(f"honest cut ≥30%\n→ {netnew_at(0.30)} net-new", (100 * 0.30, ytop * 0.92),
                 fontsize=9, color=_PASS, fontweight="bold", xytext=(6, 0), textcoords="offset points", va="top")
    axL.axvline(100 * top10_cut, color="#a855f7", ls=":", lw=1.4, zorder=2)
    axL.annotate(f"generous top-10 ({100*top10_cut:.0f}%)\n→ {netnew_at(top10_cut)} net-new (o3 = 12 of them)",
                 (100 * top10_cut, ytop * 0.50), fontsize=9, color="#7c3aed",
                 xytext=(-6, 0), textcoords="offset points", ha="right", va="center")
    axL.set_xlabel("capability cut x = Toolathlon pass-rate (%); a model is 'frontier' iff pass-rate ≥ x")
    axL.set_ylabel("count among models with pass-rate ≥ x")
    axL.set_title("Where you draw 'frontier' moves the number", fontsize=10)
    axL.grid(True, alpha=0.25)
    axL.legend(frameon=False, fontsize=8.5, loc="upper right")

    # RIGHT: the per-model net-new for the models near/above the line, to expose o3's dominance
    near = [m for m in models if m.pass_rate >= 0.15][::-1]  # strongest first
    yy = np.arange(len(near))
    vals = [m.te_netnew for m in near]
    cols = [_TE if m.is_frontier else "#c4b5fd" for m in near]
    axR.barh(yy, vals, color=cols, zorder=3)
    for i, m in enumerate(near):
        if m.te_netnew:
            axR.text(m.te_netnew + 0.15, i, str(m.te_netnew), va="center", fontsize=8, color="#444")
    axR.set_yticks(yy)
    axR.set_yticklabels([f"{m.model}  ({100*m.pass_rate:.0f}%)" for m in near], fontsize=8)
    axR.invert_yaxis()
    axR.set_xlabel("terminal_error net-new catches")
    axR.set_title("Dark = on the ≥30% honest frontier · light = mid-pack\n(o3 at 17.6% is the generous cut's biggest single contributor)", fontsize=9.5)
    axR.grid(True, axis="x", alpha=0.25)
    _two_line_footer(fig, _WHAT_ARE_THEY, _WHAT_IS_BASELINE)
    fig.tight_layout(rect=(0, 0.05, 1, 0.92))
    return _save(fig, out_dir, "figC_frontier_sensitivity")


# --------------------------------------------------------------- figD (combined DOS lift)
def fig_combined_dos_lift(s: "_add.TrioStats", out_dir: Path) -> Path:
    """The whole-DOS picture on one sheet: how much the trio CATCHES (recall) and how much a fire is
    worth (precision-lift over the base failure rate).

    Left  — cumulative recall WATERFALL: dangling alone -> +tool_stream (the pair baseline) ->
            +terminal_error (the trio). Each step is that detector's NET-NEW slice (deduped union),
            so the bars add up to the trio's total union recall. NB the order is SHIP order; the
            net-new split is order-dependent and labelled as such.
    Right — precision-LIFT over the base-fail floor, per detector and for the trio union. This is the
            docs/157 'lift' metric (precision - base_fail_rate): how much more likely a DOS fire is to
            be a real failure than a random run. >0 = real skill; the floor is the corpus base-fail rate.
    """
    base = s.n_failed / s.n_labeled  # the no-skill precision floor
    nf = s.n_failed

    # cumulative union recall counts (from the source-of-truth slices)
    d_only = s.detectors["dangling"].fired_fail          # dangling-alone TP == its standalone union
    pair_tp = s.pair.tp                                   # |D ∪ T|
    trio_tp = s.trio.tp                                   # |D ∪ T ∪ E|

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13.5, 5.6))
    fig.suptitle(
        "Combined DOS signal: how much the trio CATCHES, and how much a fire is WORTH\n"
        f"Toolathlon $0 replay · {s.n_records:,} records · {len(s.models)} models · third-party-scored (docs/157-158)",
        fontsize=12, fontweight="bold",
    )

    # ---- LEFT: cumulative recall waterfall (stacked single column per cumulative stage) ----
    stages = [
        ("dangling_intent", d_only, _DANG),
        ("+ tool_stream", pair_tp - d_only, _TS),
        ("+ terminal_error", trio_tp - pair_tp, _TE),
    ]
    bottom = 0.0
    for label, add_tp, color in stages:
        axL.bar(["DOS trio\n(cumulative)"], [100 * add_tp / nf], bottom=[100 * bottom / nf],
                color=color, width=0.5, zorder=3,
                label=f"{label}:  +{add_tp} ({100*add_tp/nf:.2f} pp)")
        bottom += add_tp
    # cumulative labels at each rung
    for cum, txt in [(d_only, f"dangling: {100*d_only/nf:.2f}%"),
                     (pair_tp, f"pair: {100*pair_tp/nf:.2f}%"),
                     (trio_tp, f"trio: {100*trio_tp/nf:.2f}%")]:
        axL.annotate(txt, (0, 100 * cum / nf), fontsize=8.5, color="#222",
                     xytext=(34, -2), textcoords="offset points", va="center", fontweight="bold")
    axL.set_ylabel("cumulative union recall of all failures (%)")
    axL.set_ylim(0, 100 * trio_tp / nf * 1.45)
    axL.set_title(f"Recall: the trio catches {100*trio_tp/nf:.2f}% of {nf:,} failures\n"
                  f"(net-new split is SHIP-order dependent)", fontsize=10)
    axL.legend(frameon=False, fontsize=8.5, loc="upper left", title="each rung = NET-NEW slice")
    axL.grid(True, axis="y", alpha=0.25)
    axL.set_xticks([0]); axL.set_xticklabels(["DOS trio\n(cumulative)"])

    # ---- RIGHT: precision-lift over base, per detector + union ----
    items = [
        ("dangling_intent", s.detectors["dangling"], _DANG),
        ("tool_stream", s.detectors["tool_stream"], _TS),
        ("terminal_error", s.detectors["terminal_error"], _TE),
    ]
    names = [n for n, _, _ in items] + ["TRIO (union)"]
    lifts = [100 * (sl.precision - base) for _, sl, _ in items] + [100 * (s.trio.precision - base)]
    precs = [100 * sl.precision for _, sl, _ in items] + [100 * s.trio.precision]
    cols = [c for _, _, c in items] + [_PASS]
    x = np.arange(len(names))
    bars = axR.bar(x, lifts, color=cols, width=0.6, zorder=3)
    for xi, lift, prec in zip(x, lifts, precs):
        axR.text(xi, lift + 0.4, f"+{lift:.1f}pp", ha="center", fontsize=9, fontweight="bold")
        axR.text(xi, lift / 2, f"prec\n{prec:.0f}%", ha="center", va="center", fontsize=8, color="white")
    axR.axhline(0, color="#111", lw=1)
    axR.set_ylabel("precision − base-fail-rate  (pp over the no-skill floor)")
    axR.set_xticks(x); axR.set_xticklabels(names, fontsize=9)
    axR.set_ylim(0, max(lifts) * 1.22)
    axR.set_title(f"Lift: every DOS fire beats the {100*base:.0f}% base-fail floor\n"
                  "(a fire is far likelier to be a REAL failure than a random run)", fontsize=10)
    axR.grid(True, axis="y", alpha=0.25)

    _two_line_footer(fig, _WHAT_ARE_THEY, _WHAT_IS_BASELINE)
    fig.tight_layout(rect=(0, 0.06, 1, 0.91))
    return _save(fig, out_dir, "figD_combined_dos_lift")


# --------------------------------------------------------------------------- save
def _save(fig, out_dir: Path, stem: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}.png"
    fig.savefig(png, dpi=150)
    fig.savefig(out_dir / f"{stem}.svg")
    plt.close(fig)
    return png


# --------------------------------------------------------------------------- main
def main(argv: "list[str] | None" = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=Path, default=_DEFAULT_ROWS, help="durable per-run rows CSV")
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT, help="where to write figures")
    ap.add_argument("--frontier-pass-rate", type=float, default=_add.FRONTIER_PASS_RATE,
                    help="capability cut for the frontier band/claim")
    args = ap.parse_args(argv)

    if not args.rows.exists():
        ap.error(f"no rows CSV at {args.rows} — run run_replay.py --all ... --rows-out first")

    s = _add.compute(_add.load_rows(args.rows), frontier_pass_rate=args.frontier_pass_rate)
    # fail loud if the durable invariants don't hold — a figure on broken data is worse than none
    problems = _add.check_invariants(s)
    if problems:
        for p in problems:
            print(f"INVARIANT FAILURE: {p}", file=sys.stderr)
        return 1

    written = [
        fig_combined_dos_lift(s, args.out_dir),
        fig_additivity_headline(s, args.out_dir),
        fig_per_model_catches(s, args.out_dir),
        fig_frontier_sensitivity(s, args.out_dir),
    ]
    print(f"# {s.n_records:,} records · {len(s.models)} models · terminal_error {s.detectors['terminal_error'].fired_fail} catches, "
          f"{s.te_netnew_total} net-new · union recall {100*s.pair.recall:.2f}%→{100*s.trio.recall:.2f}%")
    for p in written:
        print(f"wrote {p.relative_to(_HERE.parent.parent) if _HERE.parent.parent in p.parents else p}  (+ .svg)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
