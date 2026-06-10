"""Turn results.json into the audit tables + the quality-per-dollar verdict.

Produces markdown printed to stdout (piped into REPORT.md by the caller). All
numbers come from results.json — the per-run result envelopes and the hidden
oracle verdicts. Nothing here is hand-entered.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load() -> dict:
    return json.loads((HERE / "results.json").read_text(encoding="utf-8"))


def fnum(x, nd=3, dollar=False):
    if x is None:
        return "—"
    s = f"{x:.{nd}f}"
    return ("$" + s) if dollar else s


def by_model_family(records):
    """{(model, family): {n, passed, cost, turns, wall}}"""
    agg = defaultdict(lambda: {"n": 0, "passed": 0, "cost": 0.0, "turns": 0,
                                "wall": 0.0, "cost_n": 0, "turns_n": 0})
    for r in records:
        k = (r["model"], r["family"])
        a = agg[k]
        a["n"] += 1
        a["passed"] += 1 if r.get("passed") else 0
        if r.get("total_cost_usd") is not None:
            a["cost"] += r["total_cost_usd"]; a["cost_n"] += 1
        if r.get("num_turns") is not None:
            a["turns"] += r["num_turns"]; a["turns_n"] += 1
        if r.get("wall_s") is not None:
            a["wall"] += r["wall_s"]
    return agg


def main() -> int:
    d = load()
    recs = d["records"]
    models = d["models"]
    fams = d["families"]
    agg = by_model_family(recs)

    out = []
    P = out.append

    P("## 1. Per-benchmark results — Fable 5 vs Opus 4.8\n")
    P(f"Completed **{d['completed_runs']}/{d['planned_runs']}** planned runs "
      f"(spent **${d['total_spent_usd']:.2f}** of the ${d['budget_usd']:.0f} "
      f"ceiling). Stopped early on budget: **{d['stopped_early_on_budget']}**.\n")

    fam_label = {"swe": "SWE-bench-Verified-shaped (hidden pytest oracle)",
                 "term": "Terminal-Bench-shaped (hidden command oracle)"}
    for fam in fams:
        P(f"\n### {fam_label.get(fam, fam)}\n")
        P("| Model | Solved | Pass-rate | Total $ | $/solved | Avg turns | Avg wall (s) |")
        P("|---|---|---|---|---|---|---|")
        for m in models:
            a = agg.get((m, fam))
            if not a or a["n"] == 0:
                continue
            pr = a["passed"] / a["n"] if a["n"] else 0
            cps = (a["cost"] / a["passed"]) if a["passed"] else None
            at = (a["turns"] / a["turns_n"]) if a["turns_n"] else None
            aw = (a["wall"] / a["n"]) if a["n"] else None
            P(f"| {m} | {a['passed']}/{a['n']} | {pr:.0%} | "
              f"{fnum(a['cost'], 2, True)} | {fnum(cps, 3, True)} | "
              f"{fnum(at, 1)} | {fnum(aw, 0)} |")

    # Overall
    P("\n### Overall (both families)\n")
    P("| Model | Solved | Pass-rate | Total $ | $/solved | Avg turns | Avg wall (s) |")
    P("|---|---|---|---|---|---|---|")
    overall = {}
    for m in models:
        n = sum(a["n"] for (mm, _), a in agg.items() if mm == m)
        p = sum(a["passed"] for (mm, _), a in agg.items() if mm == m)
        c = sum(a["cost"] for (mm, _), a in agg.items() if mm == m)
        tn = sum(a["turns"] for (mm, _), a in agg.items() if mm == m)
        tnn = sum(a["turns_n"] for (mm, _), a in agg.items() if mm == m)
        w = sum(a["wall"] for (mm, _), a in agg.items() if mm == m)
        overall[m] = dict(n=n, p=p, c=c, cps=(c/p if p else None))
        pr = p / n if n else 0
        P(f"| {m} | {p}/{n} | {pr:.0%} | {fnum(c,2,True)} | "
          f"{fnum(c/p if p else None,3,True)} | {fnum(tn/tnn if tnn else None,1)} | "
          f"{fnum(w/n if n else None,0)} |")

    # 2. quality-per-dollar verdict
    P("\n## 2. $/solved-task and the quality-per-dollar verdict\n")
    if "fable" in overall and "opus" in overall:
        f, o = overall["fable"], overall["opus"]
        P(f"- **Fable 5**: solved {f['p']}/{f['n']} at "
          f"{fnum(f['cps'],3,True)}/solved-task (total {fnum(f['c'],2,True)}).")
        P(f"- **Opus 4.8**: solved {o['p']}/{o['n']} at "
          f"{fnum(o['cps'],3,True)}/solved-task (total {fnum(o['c'],2,True)}).")
        if f["cps"] and o["cps"]:
            ratio = f["cps"] / o["cps"]
            P(f"- **Cost ratio (Fable $/solved ÷ Opus $/solved): {ratio:.2f}×.**")
        dpass = f["p"] - o["p"]
        P(f"- **Quality delta (Fable − Opus solved): {dpass:+d} tasks** "
          f"out of {f['n']} attempted each.")

    # 3. per-task disagreement table (where they differ)
    P("\n## 3. Per-task outcomes (where the models disagree is the signal)\n")
    by_task = defaultdict(dict)
    for r in recs:
        by_task[r["task"]][r["model"]] = r
    P("| Task | Family | Fable | Opus | Fable $ | Opus $ | Fable t | Opus t |")
    P("|---|---|---|---|---|---|---|---|")
    for task in sorted(by_task):
        row = by_task[task]
        fr = row.get("fable", {})
        orr = row.get("opus", {})
        def mk(r):
            if not r:
                return "—"
            return "✅" if r.get("passed") else "❌"
        fam = (fr or orr).get("family", "")
        P(f"| {task} | {fam} | {mk(fr)} | {mk(orr)} | "
          f"{fnum(fr.get('total_cost_usd'),3,True)} | "
          f"{fnum(orr.get('total_cost_usd'),3,True)} | "
          f"{fr.get('num_turns','—')} | {orr.get('num_turns','—')} |")

    # disagreements summary
    fable_only = [t for t in by_task if by_task[t].get("fable", {}).get("passed")
                  and not by_task[t].get("opus", {}).get("passed")]
    opus_only = [t for t in by_task if by_task[t].get("opus", {}).get("passed")
                 and not by_task[t].get("fable", {}).get("passed")]
    both = [t for t in by_task if by_task[t].get("fable", {}).get("passed")
            and by_task[t].get("opus", {}).get("passed")]
    neither = [t for t in by_task if not by_task[t].get("fable", {}).get("passed")
               and not by_task[t].get("opus", {}).get("passed")]
    P(f"\n- **Both solved:** {len(both)} — {', '.join(both) or '(none)'}")
    P(f"- **Fable only:** {len(fable_only)} — {', '.join(fable_only) or '(none)'}")
    P(f"- **Opus only:** {len(opus_only)} — {', '.join(opus_only) or '(none)'}")
    P(f"- **Neither:** {len(neither)} — {', '.join(neither) or '(none)'}")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
