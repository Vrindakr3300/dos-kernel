"""An example `dos.overlap_policies` plugin occupant — deliberately tiny.

A real replacement scorer would read an import graph or a model; this one
only compares final path components. It is here to show the SHAPE — the
`name` token, the `overlaps(requested_tree, lease_tree, config)` method, the
typed `OverlapDecision` return — and the one law that makes a third-party
scorer safe to plug in at all: whatever this policy answers, the kernel ANDs
it under the unforgeable prefix floor, so it can only ever refuse MORE than
the floor, never admit a collision past it.

Illustrative, not smart: two globs that share a basename (`src/web/**` vs
`src/worker/**` both end in `**`) read as a collision here. Stricter-than-
needed is the SAFE direction — the conformance suite checks exactly that.
"""

from __future__ import annotations

from dos.lane_overlap import OverlapDecision, Verdict


def _basenames(tree: list[str]) -> set[str]:
    return {p.rstrip("/").split("/")[-1] for p in tree if p.strip()}


class BasenameOverlapPolicy:
    """Refuse when any entry of the two trees shares a final path component;
    admit otherwise."""

    name = "basename"

    def overlaps(
        self, requested_tree: list[str], lease_tree: list[str], config: object
    ) -> OverlapDecision:
        shared = _basenames(requested_tree) & _basenames(lease_tree)
        if shared:
            return OverlapDecision(
                Verdict.REFUSE_OVERLAP,
                len(shared),
                len(requested_tree),
                f"basename collision: {sorted(shared)[:3]}",
            )
        return OverlapDecision(
            Verdict.ADMIT_DISJOINT, 0, len(requested_tree), "no shared basenames"
        )
