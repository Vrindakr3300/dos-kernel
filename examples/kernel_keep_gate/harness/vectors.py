"""Mint test vectors AFTER the candidate is frozen — the candidate authors zero bytes.

The docs/138 invariant for kernel verification: the inputs a candidate is
checked and timed on must be authored by the environment, never by the
candidate. If the candidate could see (or influence) the test vectors, it could
special-case them — return a precomputed answer for the exact rows it will be
graded on, or pick a magnitude range where its numeric shortcut happens to pass.

So the minter:

  * runs only AFTER the candidate module is frozen (the host calls `mint()` once
    the candidate's source is committed and unreadable-to-itself in the gather
    step),
  * is SEEDED by the environment, not the candidate — the candidate has no
    channel to the seed,
  * deliberately includes a **large-magnitude** band. A candidate that skips the
    softmax max-subtraction passes on the small-magnitude rows a weak benchmark
    would mint and FAILS here — this is how the gate reproduces KernelBench's
    "insufficient seed variation / weak baseline" exploit class as a check.

The large band is chosen ABOVE the float64 `exp` overflow point (~709): the
stable reference subtracts the row max first, so `exp(x - max) <= 1` never
overflows and the answer is exact; the unstable shortcut computes `exp(x)` on a
raw logit > 709, which overflows to `inf`, and `inf / inf` is `nan` — a
numerically wrong output the tight tolerance witness rejects. Without a band
this wide, softmax is robust to machine precision at any magnitude (the ratio
is mathematically identical) and the shortcut would slip through — which is
exactly the "the test set was too weak to expose the hack" failure the gate
exists to prevent. A real GPU host mints far more rows; the shape is what
matters for the pin.
"""

from __future__ import annotations

import random
from typing import List


def mint(seed: int, n_rows: int = 64, width: int = 16) -> List[List[float]]:
    """Mint `n_rows` logit rows, env-seeded, spanning small AND overflow-large magnitudes.

    Half the rows are drawn from a tame [-2, 2] band (where a numeric shortcut
    can hide) and half from a wide [-900, 900] band that crosses the float64
    `exp` overflow point. On the wide band a softmax that skips the
    max-subtraction overflows to inf/nan while the stable reference stays exact —
    so the wide band is the adversarial half the gate needs to expose a
    "looks correct on easy inputs" candidate.
    """
    rng = random.Random(seed)  # env-authored seed; the candidate has no channel to it
    rows: List[List[float]] = []
    for i in range(n_rows):
        if i % 2 == 0:
            band = 2.0
        else:
            band = 900.0  # above the float64 exp-overflow point (~709)
        rows.append([rng.uniform(-band, band) for _ in range(width)])
    return rows
