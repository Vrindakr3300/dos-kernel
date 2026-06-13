"""The honest baseline kernel — correct, unoptimized, the tree the loop starts from.

A correct stable softmax, written the slow obvious way (a Python loop with a
redundant second pass and per-element function-call overhead). It stands in for
the compiled baseline a generated kernel is asked to beat. It is NUMERICALLY
CORRECT — it does the max-subtraction — so it passes the numerics witness; it is
just slow, leaving real headroom for an honest optimization.
"""

from __future__ import annotations

import math
from typing import List, Sequence


def baseline_kernel(rows: Sequence[Sequence[float]]) -> List[List[float]]:
    """Stable softmax, the slow way: two explicit passes + per-call math.exp."""
    out: List[List[float]] = []
    for row in rows:
        m = row[0]
        for x in row:  # explicit max pass
            if x > m:
                m = x
        exps = []
        for x in row:  # explicit exp pass
            exps.append(math.exp(x - m))
        total = 0.0
        for e in exps:  # explicit sum pass
            total += e
        out.append([e / total for e in exps])
    return out
