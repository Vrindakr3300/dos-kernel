"""Probe: is the DOS give-up gate's K parameter a TUNABLE PRECISION THRESHOLD on
AgentProcessBench? (docs/201 §4b — "K = number of repeated structured env-errors required
before the advisory early-halt fires".)

This is a SCRATCH instrument (the benchmark/ `_`-prefixed scratch convention). It modifies no
committed file. It REUSES the existing loader/detector — it imports
`Trajectory.step_tool_status` (the authoritative env-authored error channel) and reuses the
tool-identity walk pattern from `detector.first_unrecovered_env_error` (the env tool NAME is the
provenance key); it never re-derives the status logic.

TWO READINGS of "the gate reaches K":
  (A) CONSECUTIVE-SAME-TOOL: the longest run of consecutive errored ASSISTANT steps that all call
      the SAME tool identity >= K. (This is the literal loop-economics reading: the agent keeps
      re-calling the same tool and the env keeps erroring — `tool_stream`'s REPEATING pattern.)
  (B) CUMULATIVE: the total count of errored ASSISTANT steps in the trajectory >= K. (Looser: any
      K errors anywhere, no identity / no adjacency.)

For each K in {2,3,4,5} x {reading}:
  n_fired       = trajectories whose run/count reaches K
  n_hit_gold    = of those fired, how many also have a gold -1 divergence (first_negative_step != None)
  n_false_alarm = of FULLY CLEAN trajectories (no -1 step AND final_label != -1) that reach K
  precision         = n_hit_gold / n_fired
  recall            = n_hit_gold / (# trajectories with a gold -1 divergence)   [over the diverged pool]
  false_alarm_rate  = clean_reaching_K / clean_total

THE CLAIM UNDER TEST: as K rises, false_alarm_rate should drop monotonically toward 0.
THE HONESTY GATE (docs/198): if n_fired < 10 at a K, mark underpowered — that K's precision is NOISE.

Run: python3 -m benchmark._probe_k_cross_corpus_apb   (or python3 benchmark/_probe_k_cross_corpus_apb.py)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow `python3 benchmark/_probe_k_cross_corpus_apb.py` (script mode) by ensuring the repo root is
# importable, then import the EXISTING loader/detector — never reimplement the status channel.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from benchmark.agentprocessbench.dataset import Trajectory, load, STRUCTURED_CONFIGS

KS = (2, 3, 4, 5)


def _tools_at(traj: Trajectory, i: int) -> set:
    """The set of env-known tool names called at assistant message index `i`.

    This is the SAME tool-identity walk pattern used by detector.first_unrecovered_env_error
    (`tools_at`): the env tool NAME is the provenance key. We restrict to names present in
    tool_metrics so the identity is the env-authored one, not a free-text agent string.
    """
    msgs = traj.messages
    tm = traj.tool_metrics
    m = msgs[i] if 0 <= i < len(msgs) else {}
    return {
        ((tc.get("function", {}) or {}).get("name") or tc.get("name"))
        for tc in (m.get("tool_calls") or [])
        if ((tc.get("function", {}) or {}).get("name") or tc.get("name")) in tm
    }


def consecutive_same_tool_run(traj: Trajectory) -> int:
    """Longest run of CONSECUTIVE errored assistant steps (by step-order over the status channel)
    that share at least one common tool identity across the whole run.

    Reuses Trajectory.step_tool_status() (the authoritative env channel) for the error verdict and
    _tools_at (the detector's identity walk) for the same-tool gate. A "consecutive" run is over the
    ORDERED sequence of steps that have a tool status (errored ones extend the run, a success breaks
    it). The shared-tool constraint is the running intersection of tool identities; when it goes
    empty the run breaks and a new run starts from the current step.
    """
    status = traj.step_tool_status()
    ordered = sorted(status)  # assistant msg indices that issued an env-known tool call, in order
    best = 0
    cur_len = 0
    cur_common: set | None = None
    for idx in ordered:
        if status[idx] != "error":
            cur_len = 0
            cur_common = None
            continue
        my = _tools_at(traj, idx)
        if not my:
            # errored step with no env-known tool identity — cannot extend a same-TOOL run
            cur_len = 0
            cur_common = None
            continue
        if cur_len == 0 or cur_common is None:
            cur_len = 1
            cur_common = set(my)
        else:
            inter = cur_common & my
            if inter:
                cur_len += 1
                cur_common = inter
            else:
                # different tool -> the same-tool run breaks; start fresh at this step
                cur_len = 1
                cur_common = set(my)
        if cur_len > best:
            best = cur_len
    return best


def cumulative_errored_steps(traj: Trajectory) -> int:
    """Total count of errored assistant steps (no identity, no adjacency) — the looser reading."""
    status = traj.step_tool_status()
    return sum(1 for idx in status if status[idx] == "error")


def is_clean(traj: Trajectory) -> bool:
    """Fully clean = no -1 step AND final_label != -1 (the scoring.py clean definition + the task's)."""
    return not traj.negative_steps and traj.final_label != -1


def has_gold_divergence(traj: Trajectory) -> bool:
    return traj.first_negative_step is not None


def main() -> int:
    trajs = [t for t in load(configs=STRUCTURED_CONFIGS)]
    by_cfg: dict[str, int] = {}
    for t in trajs:
        by_cfg[t.config] = by_cfg.get(t.config, 0) + 1

    diverged_total = sum(1 for t in trajs if has_gold_divergence(t))
    clean_total = sum(1 for t in trajs if is_clean(t))

    # Precompute the per-trajectory metric under each reading once.
    consec = {id(t): consecutive_same_tool_run(t) for t in trajs}
    cumul = {id(t): cumulative_errored_steps(t) for t in trajs}

    def curve(metric: dict, reading_name: str) -> list[dict]:
        rows = []
        for K in KS:
            fired = [t for t in trajs if metric[id(t)] >= K]
            n_fired = len(fired)
            n_hit_gold = sum(1 for t in fired if has_gold_divergence(t))
            clean_reach = sum(1 for t in trajs if is_clean(t) and metric[id(t)] >= K)
            n_false_alarm = clean_reach
            precision = (n_hit_gold / n_fired) if n_fired else 0.0
            recall = (n_hit_gold / diverged_total) if diverged_total else 0.0
            far = (clean_reach / clean_total) if clean_total else 0.0
            rows.append(
                {
                    "reading": reading_name,
                    "K": K,
                    "n_fired": n_fired,
                    "n_hit_gold": n_hit_gold,
                    "n_false_alarm": n_false_alarm,
                    "precision": round(precision, 4),
                    "recall": round(recall, 4),
                    "false_alarm_rate": round(far, 6),
                    "underpowered": n_fired < 10,
                }
            )
        return rows

    consec_curve = curve(consec, "consecutive_same_tool")
    cumul_curve = curve(cumul, "cumulative")

    # K-distribution (the task's k_distribution shape): trajectories reaching K under each reading.
    consec_dist = {str(K): sum(1 for t in trajs if consec[id(t)] >= K) for K in KS}
    cumul_dist = {str(K): sum(1 for t in trajs if cumul[id(t)] >= K) for K in KS}

    # Monotonicity of false_alarm_rate (should be non-increasing in K).
    def mono(rows):
        fars = [r["false_alarm_rate"] for r in rows]
        return all(fars[i] >= fars[i + 1] for i in range(len(fars) - 1))

    out = {
        "corpus": "AgentProcessBench bfcl+tau2 (structured subsets)",
        "n_trajectories": len(trajs),
        "by_config": by_cfg,
        "diverged_total (gold -1 present)": diverged_total,
        "clean_total (no -1 AND final_label != -1)": clean_total,
        "k_distribution": {
            "consecutive_same_tool": consec_dist,
            "cumulative": cumul_dist,
        },
        "consecutive_same_tool_curve": consec_curve,
        "cumulative_curve": cumul_curve,
        "far_monotone_nonincreasing": {
            "consecutive_same_tool": mono(consec_curve),
            "cumulative": mono(cumul_curve),
        },
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
