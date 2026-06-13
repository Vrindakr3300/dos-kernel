"""The honest-faster candidate — correct AND genuinely faster → KEEP.

The kind of optimization a generated kernel SHOULD produce: same numerics
(still stable — keeps the max-subtraction), but fewer passes and less per-call
overhead than the baseline. It is correct, so the numerics witness is green; it
is faster on the env clock, so `work > baseline_work`. The keep-gate KEEPs it —
the only candidate that earns the keep bit, and it earns it by actually doing
the work, not by narrating it.
"""

from __future__ import annotations

from math import exp
from typing import List, Sequence


def honest_faster_kernel(rows: Sequence[Sequence[float]]) -> List[List[float]]:
    """Stable softmax, optimized: single max via builtin, fused exp+sum, local `exp`."""
    out: List[List[float]] = []
    _exp = exp  # bind the name once — real per-call savings in CPython
    for row in rows:
        m = max(row)  # one C-level pass instead of the baseline's Python loop
        exps = [_exp(x - m) for x in row]  # one comprehension, no append loop
        total = sum(exps)  # one C-level reduction
        inv = 1.0 / total
        out.append([e * inv for e in exps])  # multiply by reciprocal, not divide
    return out
