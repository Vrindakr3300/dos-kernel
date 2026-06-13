"""The numerically-authoritative reference — computed where the candidate can't read it.

The kernel under test stands in for a GPU kernel: a compute function the
generated candidate claims to make faster while staying numerically correct.
The TASK here is a small, precision-sensitive numeric kernel — a softmax over a
batch of logit rows — chosen because it has the exact property KernelBench's
reward hacks exploit: a **precision-dominated output** where a candidate can be
"close enough" under a loose tolerance while being numerically wrong (e.g.
skipping the max-subtraction that makes softmax stable, or returning a uniform
distribution that happens to be near the reference when the logits are flat).

The reference is the float64, numerically-stable computation. The keep-gate
runs it in a context the candidate cannot read or cache from (a fresh process /
worktree in production; here, a function the candidate module never imports and
the harness never writes to disk where the candidate could glob it). The
candidate is graded against THIS, never against its own copy of it — closing
the "reference-output caching" exploit Sakana and Recursive both report.
"""

from __future__ import annotations

import math
from typing import Sequence


def reference_softmax(row: Sequence[float]) -> list[float]:
    """The stable, float64 reference softmax for one logit row.

    Stable = subtract the row max before exponentiating (the standard trick that
    keeps `exp` from overflowing and is what a *correct* kernel must also do).
    A candidate that skips this is numerically wrong on large-magnitude logits
    even though it looks fine on the small ones a weak test set would mint —
    exactly the precision-dominated failure the gate must catch.
    """
    m = max(row)
    exps = [math.exp(x - m) for x in row]
    total = sum(exps)
    return [e / total for e in exps]


def reference_batch(rows: Sequence[Sequence[float]]) -> list[list[float]]:
    """Apply the reference to a batch of rows — the authoritative output."""
    return [reference_softmax(row) for row in rows]
