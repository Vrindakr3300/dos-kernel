"""Deterministic replay: measure the REAL loop-rate (p_stuck) on recorded gemini trajectories.

docs/145 + docs/148 §L1. The stall-reader sim's whole magnitude hinges on ONE unmeasured number:
`p_stuck` — how often a real agent loops on byte-identical tool results. This script measures it
*directly* on the recorded real `gemini-3-flash` trajectories (the `live_results/` corpus), by
folding the SHIPPED `dos.tool_stream.classify_stream` over each task's real `(tool, args_digest,
result_digest)` stream and counting how many tasks the reader would fire REPEATING/STALLED on.

This is the loop-economics analogue of `replay_recall.py` (which measures arg_provenance's real
precision/recall on the same trajectories). It is **variance-free and free**: no new model calls,
no DB mutation, no Docker — pure replay of recorded bytes (the L1-safe path, docs/148). It answers
the operator's question — "is the +17pp real?" — with a MEASUREMENT instead of a guessed `p_stuck`.

The honest reading: if this fires on ~5% of tasks, the sim's strong-model row (~+3pp) is the
honest ceiling; if it fires on ~0%, the real delta is ~0 (gemini-3-flash doesn't loop, the same
way it doesn't mint). The number it prints IS the real `p_stuck`, with its sample size stated.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys

from dos.tool_stream import StreamState, StreamStep, ToolStream, classify_stream


def _get_runs(d):
    """The recorded trajectories come in two shapes: a top-level list of runs (`_sample/`) or a
    dict with a `runs` key (`none/`). Normalize both to a list of run-dicts."""
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    if isinstance(d, dict):
        return d.get("runs") if isinstance(d.get("runs"), list) else [d]
    return []


def _digest(obj) -> str:
    """A stable digest of a value (args) or result bytes — the boundary hashing the kernel never
    does itself (it compares pre-computed digests). Canonical JSON so key order never matters."""
    try:
        s = json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def stream_of(run: dict) -> ToolStream:
    """Reconstruct the `(tool, args_digest, result_digest)` stream a task actually emitted, from
    its recorded `tool_results` — exactly what a `dos_react` stall-reader fold would have seen."""
    steps = []
    for tr in run.get("tool_results", []) or []:
        tool = str(tr.get("tool_name", ""))
        args_d = _digest(tr.get("arguments", {}) or {})
        # the env-authored result bytes (the gym MCP server wrote these — the agent did not)
        result = tr.get("result", None)
        res_d = None if result is None else _digest(result)
        steps.append(StreamStep(tool_name=tool, args_digest=args_d, result_digest=res_d))
    return ToolStream(steps=tuple(steps))


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "benchmark/enterpriseops/live_results"
    files = glob.glob(f"{folder}/**/*.json", recursive=True)

    n_tasks = n_with_calls = total_calls = 0
    n_repeating = n_stalled = 0
    longest_run = 0
    fired_examples = []

    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for run in _get_runs(d):
            n_tasks += 1
            stream = stream_of(run)
            if not stream.steps:
                continue
            n_with_calls += 1
            total_calls += len(stream.steps)
            # fold INCREMENTALLY (per step, as the real consumer would) — catch a loop the moment
            # it forms, not just at the final stream.
            task_fired = None
            for i in range(1, len(stream.steps) + 1):
                v = classify_stream(ToolStream(steps=stream.steps[:i]))
                longest_run = max(longest_run, v.repeat_run)
                if v.state is StreamState.STALLED:
                    task_fired = "STALLED"
                    break
                if v.state is StreamState.REPEATING and task_fired is None:
                    task_fired = "REPEATING"
            if task_fired == "STALLED":
                n_stalled += 1
            elif task_fired == "REPEATING":
                n_repeating += 1
            if task_fired and len(fired_examples) < 5:
                fired_examples.append((f.split("live_results")[-1][:48], task_fired))

    n_fired = n_repeating + n_stalled
    p_stuck = (n_fired / n_with_calls) if n_with_calls else 0.0

    print("=" * 78)
    print("  REAL loop-rate (p_stuck) on recorded gemini-3-flash trajectories")
    print("  (the SHIPPED dos.tool_stream.classify_stream, folded over real tool streams)")
    print("=" * 78)
    print(f"  trajectory runs scanned:        {n_tasks}")
    print(f"  runs WITH tool calls:           {n_with_calls}   ({total_calls} calls total)")
    print(f"  longest byte-identical run seen: {longest_run}")
    print(f"  runs the reader FIRED on:       {n_fired}  ({n_repeating} REPEATING, {n_stalled} STALLED)")
    print("-" * 78)
    print(f"  MEASURED p_stuck (fired / runs-with-calls) = {p_stuck:.3f}  ({100*p_stuck:.1f}%)")
    print("-" * 78)
    if n_with_calls < 30:
        print(f"  [!] SAMPLE TOO SMALL ({n_with_calls} runs with calls) — this is a FLOOR, not a")
        print(f"      stable estimate. The recorded corpus is mostly 0-tool-call runs; a real")
        print(f"      p_stuck needs a fresh multi-step run. Report this as 'not yet measurable'.")
    else:
        print(f"  Read against the sim: p_stuck~{p_stuck:.2f} => the sim's honest row is the one")
        print(f"  nearest this rate (--honest sweep). This is the REAL number, not a guess.")
    if fired_examples:
        print("  fired examples:")
        for ex, kind in fired_examples:
            print(f"    {kind:<10} {ex}")
    print("=" * 78)


if __name__ == "__main__":
    main()
