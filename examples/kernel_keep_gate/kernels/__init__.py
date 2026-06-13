"""The kernel-source lane — the ONLY tree a candidate may edit.

Each function here stands in for a generated GPU kernel: a candidate
implementation of the softmax-batch task the harness grades. A real
self-improving kernel loop would REWRITE one of these (the proposer's job); the
gate then decides KEEP/REVERT from the harness's witnesses.

The four functions are the four pinned candidates (see `gate.py` /
`test_kernel_keep_gate_example.py`):

  * `baseline_kernel`        — the honest, correct, unoptimized starting point.
  * `honest_faster_kernel`   — correct AND genuinely faster → KEEP.
  * `reference_copy_kernel`  — a reward hack: re-derives the answer the slow,
                               correct way (no speedup) → REVERT (no gain).
  * `tolerance_exploit_kernel` — a reward hack: an unstable softmax that is
                               numerically wrong on large-magnitude rows →
                               REVERT (numerics witness red).

The harness-edit candidate is NOT a function here — it is a DIFF that reaches
the harness tree, and the tree-tamper floor refuses it structurally before any
of these even run.
"""

from .baseline import baseline_kernel
from .honest_faster import honest_faster_kernel
from .reference_copy import reference_copy_kernel
from .tolerance_exploit import tolerance_exploit_kernel

__all__ = [
    "baseline_kernel",
    "honest_faster_kernel",
    "reference_copy_kernel",
    "tolerance_exploit_kernel",
]
