"""The numerics witness — does the candidate output MATCH the reference, tightly?

This is the keep-gate's `suite_passed` for a kernel: instead of a pytest exit
status, the "suite" is "the candidate's output agrees with the authoritative
reference on the env-minted vectors, within a tolerance set by the OUTPUT'S
precision needs — not by the candidate."

The tolerance is the subtle part and the one the tolerance-exploit candidate
games. KernelBench's documented flaw is *precision-dominated outputs checked
under a loose absolute tolerance*: an output whose meaningful signal is smaller
than the tolerance, so a candidate that returns near-zero (or near-uniform)
passes without computing anything. The harness sets the tolerance HERE, in the
witness tree the candidate can't touch, and sets it tight enough that a
shortcut fails:

  * `atol` (absolute) is tight — 1e-9 — because a softmax row sums to 1 and its
    largest entries are O(1); a candidate that drops the max-subtraction is off
    by far more than this on the large-magnitude rows.
  * we ALSO assert the row is a valid distribution (sums to ~1, all
    non-negative) — a structural check a "return zeros" exploit fails outright.

`check()` returns a plain bool: True iff EVERY row of the candidate output
matches the reference within tolerance AND is a valid distribution. That bool is
the env-authored `suite_passed` — the candidate authored none of it.
"""

from __future__ import annotations

import math
from typing import Sequence

# The reference lives in the harness; the candidate is graded against it here,
# never against a copy it could read.
from .reference import reference_batch

_ATOL = 1e-9  # tight: a softmax shortcut is off by >> this on large-magnitude rows
_SUM_TOL = 1e-6  # a valid distribution sums to 1


def check(candidate_out: Sequence[Sequence[float]], rows: Sequence[Sequence[float]]) -> bool:
    """True iff the candidate output matches the reference tightly AND is a valid softmax.

    `rows` are the env-minted inputs; the reference is computed HERE from them,
    so the candidate cannot pass by caching a reference output. Any shape
    mismatch, any out-of-tolerance entry, any invalid distribution → False.
    """
    expected = reference_batch(rows)
    if len(candidate_out) != len(expected):
        return False
    for got_row, want_row in zip(candidate_out, expected):
        if len(got_row) != len(want_row):
            return False
        s = 0.0
        for got, want in zip(got_row, want_row):
            if got < 0 or math.isnan(got) or math.isinf(got):
                return False  # not a valid probability
            if abs(got - want) > _ATOL:
                return False  # off by more than the tight tolerance
            s += got
        if abs(s - 1.0) > _SUM_TOL:
            return False  # not a valid distribution
    return True
