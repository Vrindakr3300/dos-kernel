"""Probe: is the DOS give-up gate's K an actually-TUNABLE precision threshold on AgentHallu?

docs/201 §4b frames K as "the number of repeated structured env-errors required before the advisory
early-halt fires" — a knob that should trade RECALL for PRECISION as it rises (require more error
evidence before firing → fewer fires, but each fire more likely a real divergence).

This probe asks that question against the AgentHallu attribution corpus (693 trajectories: 443
hallucinated + 250 clean), under TWO honest readings of "the agent reached K repeated env-errors":

  READING A — consecutive_same_tool: the longest run of CONSECUTIVE steps that are all env-errored
      AND share at least one env tool identity. This is the give-up gate's actual key (tool_stream
      docs/145: consecutive-identical-tool thrash). The give-up gate fires when this run length >= K.

  READING B — cumulative: the TOTAL count of env-errored steps anywhere in the trajectory. A looser
      reading (errors need not be consecutive or same-tool) — included so the curve is not declared
      degenerate on a single, possibly-too-strict reading.

Both readings are byte-clean: they fold ONLY env-authored tool_responses (via `_step_errored`) and
the env tool IDENTITY (via `_step_tools`), never the agent's narration. Same provenance line as
detector.py / first_unrecovered_error.

THE HONESTY GATE (docs/198, the feasibility-witness scar): a precision curve drawn over an EMPTY
denominator is noise dressed as a result. So for every K we report n_fired FIRST, and any K with
n_fired < 10 is flagged underpowered=true — NOT reported as a finding. The verdict is driven by the
denominator, not by whatever ratio happens to fall out of a 2-trajectory sample.

Reuses the committed loader + detector untouched:
    from benchmark.agenthallu.dataset  import load, Trajectory
    from benchmark.agenthallu.detector import _step_errored, _step_tools, first_unrecovered_error

Run:  python3 -m benchmark._probe_k_cross_corpus_ah
"""

from __future__ import annotations

import json
from typing import Optional

from benchmark.agenthallu.dataset import Trajectory, load
from benchmark.agenthallu.detector import (
    _step_errored,
    _step_tools,
    first_unrecovered_error,
)

KS = (2, 3, 4, 5)
UNDERPOWERED_FLOOR = 10  # n_fired below this is noise (docs/198 honesty gate)


# ---------------------------------------------------------------------------------------------------
# The two byte-clean K-readings. Each maps a trajectory -> the max "error-evidence depth" reached.
# ---------------------------------------------------------------------------------------------------

def consecutive_same_tool_run(traj: Trajectory) -> int:
    """Longest run of CONSECUTIVE env-errored steps sharing >=1 common env tool identity.

    This is the give-up gate's key (tool_stream consecutive-thrash). A run extends only while every
    step in it is errored AND the running intersection of tool identities stays non-empty — i.e. the
    SAME tool keeps erroring in a row. Returns the max such run length (0 if no errored step)."""
    best = 0
    run_len = 0
    run_tools: Optional[set] = None
    for step in traj.history:
        if _step_errored(step):
            tools = _step_tools(step)
            if run_len == 0:
                run_len = 1
                run_tools = set(tools)
            else:
                shared = (run_tools & tools) if run_tools is not None else set()
                if shared:
                    run_len += 1
                    run_tools = shared
                else:
                    # errored, but a DIFFERENT tool — start a fresh same-tool run here
                    run_len = 1
                    run_tools = set(tools)
            best = max(best, run_len)
        else:
            run_len = 0
            run_tools = None
    return best


def cumulative_errored(traj: Trajectory) -> int:
    """Total count of env-errored steps anywhere in the trajectory (looser reading)."""
    return sum(1 for step in traj.history if _step_errored(step))


# ---------------------------------------------------------------------------------------------------
# The K-precision curve, per reading.
# ---------------------------------------------------------------------------------------------------

def k_curve(trajs: list[Trajectory], depth_fn) -> dict:
    """For each K in KS: who reaches K, of those who is hallucinated (gold != None), and how many of
    the 250 clean reach K (the false-alarm). precision = hit / fired; recall = hit / 443;
    false_alarm_rate = clean_reaching_K / 250."""
    hall = [t for t in trajs if t.is_hallucination]
    clean = [t for t in trajs if not t.is_hallucination]
    n_hall = len(hall)
    n_clean = len(clean)

    # gold != None among hallucinated is the "true-positive-ish" target; clean reaching K is the FA.
    depth_hall = [(t, depth_fn(t)) for t in hall]
    depth_clean = [(t, depth_fn(t)) for t in clean]

    rows = []
    for k in KS:
        # "fired" = ANY trajectory reaching K (hallucinated OR clean) — the gate is label-blind.
        hall_reach = [t for (t, d) in depth_hall if d >= k]
        clean_reach = [t for (t, d) in depth_clean if d >= k]
        n_fired = len(hall_reach) + len(clean_reach)
        # n_hit_gold: of the hallucinated reachers, how many carry a gold step (the attribution label).
        n_hit_gold = sum(1 for t in hall_reach if t.gold is not None)
        n_false_alarm = len(clean_reach)
        precision = (n_hit_gold / n_fired) if n_fired else 0.0
        recall = (n_hit_gold / n_hall) if n_hall else 0.0
        fa_rate = (n_false_alarm / n_clean) if n_clean else 0.0
        rows.append(
            {
                "K": k,
                "n_fired": n_fired,
                "n_hall_reach": len(hall_reach),
                "n_clean_reach": n_false_alarm,
                "n_hit_gold": n_hit_gold,
                "n_false_alarm_on_clean": n_false_alarm,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "false_alarm_rate": round(fa_rate, 4),
                "underpowered": n_fired < UNDERPOWERED_FLOOR,
            }
        )
    return {"n_hall": n_hall, "n_clean": n_clean, "rows": rows}


def monotone_fa_drops(rows: list[dict]) -> bool:
    """Does false_alarm_rate monotonically NON-INCREASE as K rises? (the docs/201 §4b claim)."""
    fas = [r["false_alarm_rate"] for r in rows]
    return all(b <= a for a, b in zip(fas, fas[1:]))


def k_distribution(trajs: list[Trajectory], depth_fn) -> dict:
    """How many trajectories (ALL 693) reach each K under this reading — the raw denominator."""
    depths = [depth_fn(t) for t in trajs]
    return {str(k): sum(1 for d in depths if d >= k) for k in KS}


def main() -> int:
    trajs = list(load())
    n_total = len(trajs)
    n_hall = sum(1 for t in trajs if t.is_hallucination)
    n_clean = n_total - n_hall

    readings = {
        "consecutive_same_tool": consecutive_same_tool_run,
        "cumulative": cumulative_errored,
    }

    out = {
        "corpus": (
            f"AgentHallu (arXiv 2601.06818, CC-BY-4.0): {n_total} trajectories "
            f"({n_hall} hallucinated / {n_clean} clean), scored offline $0."
        ),
        "n_total": n_total,
        "n_hall": n_hall,
        "n_clean": n_clean,
        "underpowered_floor": UNDERPOWERED_FLOOR,
        "readings": {},
    }

    for name, fn in readings.items():
        curve = k_curve(trajs, fn)
        dist_all = k_distribution(trajs, fn)
        out["readings"][name] = {
            "k_distribution_all_693": dist_all,
            "monotone_false_alarm_drop": monotone_fa_drops(curve["rows"]),
            "rows": curve["rows"],
        }

    # Cross-check vs the orchestrator's already-measured numbers.
    out["orchestrator_crosscheck"] = {
        "consecutive_same_tool_all_693": out["readings"]["consecutive_same_tool"][
            "k_distribution_all_693"
        ],
        "cumulative_all_693": out["readings"]["cumulative"]["k_distribution_all_693"],
        "orchestrator_claimed_consecutive": {"2": 13, "3": 2},
        "orchestrator_claimed_cumulative": {"2": 37, "3": 10, "4": 3, "5": 3},
    }

    # Sanity anchor: the recommended localizer's headline (precision 83.8% / FA 1.2% at K=1) — this
    # probe must not contradict the committed detector.
    tu = [t for t in trajs if t.is_hallucination and t.is_tool_use]
    clean = [t for t in trajs if not t.is_hallucination]
    fued_clean_fa = sum(1 for t in clean if first_unrecovered_error(t) is not None)
    out["anchor_first_unrecovered_error_k1"] = {
        "tool_use_total": len(tu),
        "clean_fired": fued_clean_fa,
        "clean_total": len(clean),
        "false_alarm_rate": round(fued_clean_fa / len(clean), 4) if clean else 0.0,
    }

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
