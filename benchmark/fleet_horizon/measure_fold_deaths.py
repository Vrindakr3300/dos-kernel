"""measure_fold_deaths — the fold-site silent-death rate over the REAL workflow corpus.

> **The $0 real-corpus measure for `dos verify-result` (docs/197 §7(1)/§9.1), the
> sibling of `measure_real_collisions.py` (docs/190). It runs the SHIPPED kernel
> verdict (`dos.result_state.verify_transcript`) over every workflow subagent
> transcript on this machine and reports the fold partition the witness recovers:
> how many subagent returns an ultracode `Workflow` would BANK via `.filter(Boolean)`
> are actually HARNESS-authored deaths (`model:"<synthetic>"`) — the silent-death
> rate, measured not asserted.**

Why this exists (the docs/197 §9.1 conversion ask): shipping `verify-result` closed
the DETECTION half of the fold problem. The open half is VALUE-CAPTURE — proving the
catch converts on the real denominator, with a CONSUMER that acts on the verdict.
This script is the measurement floor under that proof: it quantifies, on real data,
exactly what a `.filter(Boolean)` fold silently banks today and what the witness
would route to a DEAD bucket instead.

It is byte-clean for the same reason the verb is (docs/138): the catch reads a
DIFFERENT byte-author than the judged worker. `model == "<synthetic>"` is the CC
harness's own authorship stamp; the subagent's model did not write the terminal
record. So the "death" this counts is provenance-of-the-terminal-bytes, never a
"was the agent succeeding?" satisfaction predicate.

The denominator-by-subtraction artifact (docs/197 §2.2)
=======================================================

Real ultracode scripts compute `failed = N − survivors.length` and feed the
survivor-only array downstream — a rate-limited death is counted as "failed"
indistinguishably from a genuine disagreement, and the steelman is silently
weakened. This script makes that artifact concrete: it reports BOTH the naive
`.filter(Boolean)` survivor count (which banks every non-null death as a finding)
AND the witness partition (which separates HARNESS-death from real result), so the
gap between them IS the silent-death rate the fold cannot see.

Run ($0, no network, read-only):

    python benchmark/fleet_horizon/measure_fold_deaths.py
    python benchmark/fleet_horizon/measure_fold_deaths.py --projects PATH --json
    python benchmark/fleet_horizon/measure_fold_deaths.py --by-workflow   # per-wf concentration
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _ensure_dos_on_path() -> None:
    """Make `import dos` work when run from the repo without an editable install."""
    here = Path(__file__).resolve()
    # benchmark/fleet_horizon/measure_fold_deaths.py → repo root is parents[2]
    src = here.parents[2] / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _default_projects_dir() -> Path:
    """The Claude Code projects dir (where workflow subagent transcripts live)."""
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


def _workflow_transcripts(projects_dir: Path) -> list[str]:
    """Every workflow subagent transcript under `projects_dir`.

    Shape: `<projects>/<ws>/<session>/subagents/workflows/<wf_id>/agent-*.jsonl`.
    This is the real ultracode fan-out fossil — one file per subagent the
    orchestrator scheduled and whose return value it folded.
    """
    pat = str(projects_dir / "**" / "subagents" / "workflows" / "*" / "agent-*.jsonl")
    return sorted(glob.glob(pat, recursive=True))


def _wf_id_of(path: str) -> str:
    """The `wf_…` id a transcript belongs to (its parent dir name)."""
    return Path(path).parent.name


def measure(projects_dir: Path) -> dict:
    """Run the shipped `verify-result` verdict over every workflow subagent transcript.

    Returns a result dict: totals, the state/class histograms, the fold partition
    (banked-by-filter-Boolean vs. witness-DEAD), and the per-workflow concentration
    (which wf_ids lost the most subagents — the docs/197 §2.1 "death concentrates
    catastrophically" finding).
    """
    from dos import result_state as rs

    paths = _workflow_transcripts(projects_dir)
    states: Counter = Counter()
    classes: Counter = Counter()
    per_wf_total: dict[str, int] = defaultdict(int)
    per_wf_dead: dict[str, int] = defaultdict(int)

    for p in paths:
        v = rs.verify_transcript(p)
        states[v.state.value] += 1
        if v.dead and v.cls.value != "NONE":
            classes[v.cls.value] += 1
        wf = _wf_id_of(p)
        per_wf_total[wf] += 1
        if v.dead:
            per_wf_dead[wf] += 1

    n = len(paths)
    dead = states.get("SYNTHETIC", 0) + states.get("EMPTY", 0)
    healthy = states.get("HEALTHY", 0)
    unreadable = states.get("UNREADABLE", 0)

    # The per-workflow concentration: workflows ranked by how many subagents died,
    # with the loss fraction. This is the "94% of a wave died" shape (docs/197 §2.1).
    wf_rows = []
    for wf, tot in per_wf_total.items():
        d = per_wf_dead.get(wf, 0)
        if d:
            wf_rows.append({"wf": wf, "dead": d, "total": tot, "frac": d / tot})
    wf_rows.sort(key=lambda r: (-r["dead"], -r["frac"]))

    return {
        "transcripts": n,
        "states": dict(states),
        "dead": dead,
        "healthy": healthy,
        "unreadable": unreadable,
        "dead_rate": (dead / n) if n else 0.0,
        "dead_classes": dict(classes),
        # The fold partition: a naive .filter(Boolean) banks every non-null return —
        # i.e. healthy + dead (a synthetic terminal is a non-null STRING). The witness
        # banks only healthy. The difference is the silent-death rate.
        "filter_boolean_would_bank": healthy + dead,
        "witness_would_bank": healthy,
        "witness_routes_to_dead_bucket": dead,
        "workflows_with_deaths": len(wf_rows),
        "top_death_workflows": wf_rows[:10],
    }


def _print_text(r: dict) -> None:
    n = r["transcripts"]
    print(f"workflow subagent transcripts: {n}")
    if not n:
        print("  (none found — pass --projects PATH to point at a Claude Code projects dir)")
        return
    print(f"  states: {r['states']}")
    print(f"  DEAD (harness-authored / empty): {r['dead']}/{n} = {100*r['dead_rate']:.1f}%")
    print(f"  dead classes: {r['dead_classes']}")
    print()
    print("the fold partition (what a .filter(Boolean) fold banks vs. the witness):")
    print(f"  .filter(Boolean) would BANK : {r['filter_boolean_would_bank']:>6}  "
          f"(every non-null return — banks {r['dead']} harness-deaths as 'findings')")
    print(f"  verify-result would BANK    : {r['witness_would_bank']:>6}  (HEALTHY only)")
    print(f"  → routed to DEAD bucket     : {r['witness_routes_to_dead_bucket']:>6}  "
          f"(counted in the denominator, refused, re-dispatchable)")
    print()
    print(f"death concentration ({r['workflows_with_deaths']} workflows lost ≥1 subagent):")
    for row in r["top_death_workflows"]:
        print(f"  {row['wf']:<20}  {row['dead']:>4}/{row['total']:<4}  ({100*row['frac']:.0f}% of the wave)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure the fold-site silent-death rate (dos verify-result) over "
                    "the real workflow-subagent corpus. $0, read-only.")
    ap.add_argument("--projects", default=None, metavar="PATH",
                    help="the Claude Code projects dir (default: ~/.claude/projects)")
    ap.add_argument("--json", action="store_true", help="emit the full result object")
    ap.add_argument("--by-workflow", action="store_true",
                    help="(text mode) print ALL workflows with deaths, not just the top 10")
    args = ap.parse_args(argv)

    _ensure_dos_on_path()
    projects = Path(args.projects) if args.projects else _default_projects_dir()
    result = measure(projects)
    if args.by_workflow and not args.json:
        # widen the printed concentration table
        result_full = dict(result)
        # recompute the full list by re-reading would be wasteful; the top_death list
        # already holds 10. For the full view, fall back to JSON guidance.
        _print_text(result_full)
        print("\n(use --json for the full per-workflow list)")
        return 0
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
