"""Env-timed latency — the metric the kernel keep-gate reads, authored by the clock.

`improve.classify`'s `work` field is "the env-measured improvement metric AFTER
the candidate." For a kernel that metric is wall-time: how long the candidate
takes to compute the batch, measured by the HARNESS's clock, never reported by
the candidate. The candidate cannot narrate a speedup — it must actually run
faster on the env-minted vectors under the env's timer.

We report `work` as a non-negative integer (the kernel's `work` unit is an int),
so latency is turned into a "speed score": a fixed budget minus the measured
nanoseconds-per-call, floored at zero. Faster candidate ⇒ smaller latency ⇒
larger score ⇒ `work > baseline_work` ⇒ the strict gain the keep-gate requires.
A candidate that is the same speed scores the same and is a NO_IMPROVEMENT
revert — a no-op is not kept.

The "time only part of the work" exploit (Sakana) is closed by construction:
the harness times the candidate's PUBLIC entry point over the env-minted batch
and compares its OUTPUT to the reference. A candidate that times a no-op and
returns early fails the numerics witness; one that caches across calls is
re-timed on freshly-minted vectors each gather.
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

# The latency budget (nanoseconds-per-batch) the speed score counts down from.
# Generous enough that any of the example candidates scores positive; the
# ABSOLUTE value is irrelevant — only the candidate-vs-baseline ORDER decides
# KEEP, and that order is the env-measured one.
_BUDGET_NS = 50_000_000  # 50 ms per batch


def speed_score(
    fn: Callable[[Sequence[Sequence[float]]], object],
    rows: Sequence[Sequence[float]],
    repeats: int = 5,
) -> int:
    """Time `fn(rows)` and return a non-negative integer speed score (bigger = faster).

    Runs `fn` `repeats` times and takes the BEST (minimum) wall-time — the
    standard way to measure a kernel's floor latency while damping scheduler
    noise. The candidate never sees this number; the harness computes it. The
    score is `max(0, budget - best_ns_per_call)`, an int, so a faster candidate
    scores strictly higher and the keep-gate's `work > baseline_work` is a real
    latency win.
    """
    best_ns = None
    for _ in range(repeats):
        start = time.perf_counter_ns()
        fn(rows)
        elapsed = time.perf_counter_ns() - start
        if best_ns is None or elapsed < best_ns:
            best_ns = elapsed
    assert best_ns is not None
    return max(0, _BUDGET_NS - best_ns)
