"""H1 (docs/236 §5) — the recovery SURVIVAL CURVE over cached natural runs, with censoring.

THE QUESTION
------------
"The model will just recover next turn." H1 measures the actual recovery distribution that
slogan asserts. For every tool-error event in the cached natural trajectories, we ask: how
many subsequent steps until the SAME tool succeeds again (recovery), or never (censored)?

    P_recovered(k) = fraction of error events whose tool succeeds again within k more steps
    TAIL MASS      = fraction that NEVER recover before the trajectory ends  (= P(never))

THE CONFOUND THIS CONTROLS (the docs/236 point, in miniature)
-------------------------------------------------------------
A trajectory that ENDS while a tool is still failing did not "fail to recover" — it ran out
of room. Counting those as eventual-recoveries inflates the recovery rate (right-censoring).
So a never-recovered event is reported as CENSORED, never folded into P_recovered as if the
agent would have fixed it given more turns. The tail mass is the honest "it did NOT recover."

WHY THIS GROUNDS THE THESIS
---------------------------
The recovery rate `r` here is the same `r` the analytic bridge `delta_b_of_r` uses: the
non-LLM endpoint (docs/236 §5 H3, ΔB=+1.0) is the r=0 corner, the capable LLM (docs/235,
ΔB≈0) is the high-r corner. A tail mass well above 0 means "it'll recover" is simply false
for that fraction of events — and each such event poisons a downstream consumer that cannot
self-heal (the §7 blast radius). $0: reads only the cached `live_results_natural_ab/*` rows.

The recovery operationalization (same-tool-succeeds-later) and the error/ok classifiers are
the SAME ones `_verify_recovers.py` uses — env-authored result bytes, the sound witness.

USAGE
-----
    python _recovery_survival.py [--arm none|rewind_natural|all] [--max-k 12] [--json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from dos_react import _is_struct_error, _result_text, _is_blocked_result  # noqa: E402


def _is_err(tr: dict) -> bool:
    return _is_struct_error(_result_text(tr)) and not _is_blocked_result(tr)


def _is_ok(tr: dict) -> bool:
    return (not _is_blocked_result(tr)) and (not _is_struct_error(_result_text(tr)))


def _runs(glob_pat: str):
    for f in sorted(glob.glob(glob_pat)):
        try:
            d = json.loads(open(f, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            continue
        for r in (d.get("runs") or []):
            yield r


@dataclass
class ErrorEvent:
    tool: str
    ttr: Optional[int]   # steps until same tool next succeeds; None == censored (never)


@dataclass
class SurvivalResult:
    arms: list[str]
    n_runs: int
    n_error_events: int
    recovered: int                 # ttr is not None
    censored: int                  # ttr is None (never recovered before trajectory end)
    tail_mass: float               # censored / n_error_events  (CONFOUNDED — see feasible_tail)
    p_recovered_by_k: dict         # k -> cumulative P(recovered within k steps)
    median_ttr: Optional[int]
    # --- the docs/198 FEASIBILITY SPLIT (the confound this doc would otherwise commit) ---
    walled_tools: list[str] = field(default_factory=list)   # >=N errors, 0 successes anywhere
    n_infeasible_events: int = 0   # error events on a walled tool (recovery was NEVER possible)
    n_feasible_events: int = 0     # the rest — where recovery WAS possible
    feasible_recovered: int = 0
    feasible_tail_mass: float = 0.0  # the HONEST "P(never recover | recovery was possible)"
    by_tool: dict = field(default_factory=dict)   # tool -> (events, recovered, tail_mass, walled)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _collect_events(glob_pats: list[str]) -> tuple[list[ErrorEvent], int, dict, dict]:
    """Returns (error events, n_runs, per-tool error count, per-tool ok count).

    The per-tool ok/err counts feed the WALLED (infeasible) detector — a tool that errors
    many times and NEVER succeeds anywhere in the corpus is infeasible, not un-recovered.
    """
    events: list[ErrorEvent] = []
    n_runs = 0
    err_ct: dict[str, int] = defaultdict(int)
    ok_ct: dict[str, int] = defaultdict(int)
    for pat in glob_pats:
        for r in _runs(pat):
            n_runs += 1
            trs = r.get("tool_results") or []
            for i, tr in enumerate(trs):
                t = str(tr.get("tool_name", ""))
                if not t:
                    continue
                if _is_ok(tr):
                    ok_ct[t] += 1
                    continue
                if not _is_err(tr):
                    continue
                err_ct[t] += 1
                # time-to-recovery: steps until the SAME tool next succeeds
                ttr = None
                for j in range(i + 1, len(trs)):
                    if str(trs[j].get("tool_name", "")) == t and _is_ok(trs[j]):
                        ttr = j - i
                        break
                events.append(ErrorEvent(tool=t, ttr=ttr))
    return events, n_runs, dict(err_ct), dict(ok_ct)


def measure(arms: list[str], max_k: int = 12, walled_min: int = 5) -> SurvivalResult:
    pats = [os.path.join(_HERE, "live_results_natural_ab", a, "results_*.json") for a in arms]
    events, n_runs, err_ct, ok_ct = _collect_events(pats)
    n = len(events)
    recovered = [e for e in events if e.ttr is not None]
    censored = n - len(recovered)
    tail = (censored / n) if n else 0.0

    # cumulative P(recovered within k steps), k = 1..max_k
    p_by_k = {}
    for k in range(1, max_k + 1):
        hit = sum(1 for e in recovered if e.ttr is not None and e.ttr <= k)
        p_by_k[k] = round(hit / n, 4) if n else 0.0

    ttrs = sorted(e.ttr for e in recovered)
    median = ttrs[len(ttrs) // 2] if ttrs else None

    # --- docs/198 feasibility split: WALLED = errors >= walled_min AND 0 successes anywhere.
    # `create_filter` (docs/198, 0/579 corpus-wide) is the canonical member; its 0% recovery
    # is INFEASIBILITY, not un-recovery, and folding it into the tail would re-commit the
    # exact polluted-denominator error this whole doc cites docs/198 to avoid.
    walled = sorted(t for t, c in err_ct.items() if c >= walled_min and ok_ct.get(t, 0) == 0)
    walled_set = set(walled)
    feas = [e for e in events if e.tool not in walled_set]
    infeas = n - len(feas)
    feas_rec = sum(1 for e in feas if e.ttr is not None)
    feas_tail = ((len(feas) - feas_rec) / len(feas)) if feas else 0.0

    by_tool = {}
    grp = defaultdict(list)
    for e in events:
        grp[e.tool].append(e)
    for tool, evs in grp.items():
        rec = sum(1 for e in evs if e.ttr is not None)
        by_tool[tool] = {
            "events": len(evs),
            "recovered": rec,
            "tail_mass": round((len(evs) - rec) / len(evs), 4) if evs else 0.0,
            "walled": tool in walled_set,
        }
    return SurvivalResult(
        arms=arms, n_runs=n_runs, n_error_events=n,
        recovered=len(recovered), censored=censored, tail_mass=round(tail, 4),
        p_recovered_by_k=p_by_k, median_ttr=median,
        walled_tools=walled, n_infeasible_events=infeas, n_feasible_events=len(feas),
        feasible_recovered=feas_rec, feasible_tail_mass=round(feas_tail, 4),
        by_tool=by_tool,
    )


def _render(res: SurvivalResult) -> str:
    L = []
    L.append("=" * 72)
    L.append("H1 recovery SURVIVAL CURVE (docs/236 sec.5) -- censored, $0")
    L.append("=" * 72)
    L.append(f"  arms                   {', '.join(res.arms)}")
    L.append(f"  runs folded            {res.n_runs}")
    L.append(f"  tool-error events      {res.n_error_events}")
    L.append(f"  recovered (same tool)  {res.recovered}")
    L.append(f"  CENSORED (never)       {res.censored}   <- did NOT recover before trajectory end")
    L.append("-" * 72)
    L.append(f"  raw tail P(never)      {res.tail_mass:.4f}   (CONFOUNDED by infeasible thrash -- do not cite)")
    L.append("  --- docs/198 feasibility split (the honest read) ---")
    L.append(f"  walled/infeasible      {len(res.walled_tools)} tools, {res.n_infeasible_events} events "
             f"(recovery was NEVER possible)")
    if res.walled_tools:
        L.append(f"    {', '.join(res.walled_tools[:8])}{' ...' if len(res.walled_tools) > 8 else ''}")
    L.append(f"  FEASIBLE events        {res.n_feasible_events}   recovered {res.feasible_recovered}")
    L.append(f"  FEASIBLE TAIL P(never) {res.feasible_tail_mass:.4f}   <- 'it'll recover' FALSE this often "
             f"WHEN recovery was possible")
    L.append(f"  median steps-to-recover {res.median_ttr}")
    L.append("-" * 72)
    L.append("  P(recovered within k steps):")
    for k, p in res.p_recovered_by_k.items():
        bar = "#" * int(round(p * 40))
        L.append(f"    k<={k:<2}  {p:.4f}  {bar}")
    L.append("-" * 72)
    L.append("  worst tools by error-event count (events / recovered / tail):")
    worst = sorted(res.by_tool.items(), key=lambda kv: -kv[1]["events"])[:10]
    for tool, s in worst:
        flag = "  WALLED(infeasible)" if s.get("walled") else ""
        L.append(f"    {tool:34} {s['events']:4}  rec={s['recovered']:4}  tail={s['tail_mass']:.2f}{flag}")
    L.append("=" * 72)
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="H1 recovery survival curve (docs/236 §5) — $0.")
    ap.add_argument("--arm", default="all", choices=["none", "rewind_natural", "all"],
                    help="which cached natural arm(s) to fold (default all)")
    ap.add_argument("--max-k", type=int, default=12, help="max steps for the survival curve")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the table")
    args = ap.parse_args(argv)

    arms = ["none", "rewind_natural"] if args.arm == "all" else [args.arm]
    res = measure(arms, max_k=args.max_k)
    print(json.dumps(res.as_dict(), indent=2) if args.json else _render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
