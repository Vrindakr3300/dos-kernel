"""The farm-wide concurrency budget, driven through the kernel's picker path.

WHY THIS IS PYTHON, NOT A `dos arbitrate` LINE (the honesty note playbook 09
states in prose): the `class_budgets` gate bites only inside the bare auto-pick
walk over a host-supplied `auto_pick_order` ladder — the (lane, kind, tree)
slot list a real host (or the picker driver) feeds the kernel. The generic
`dos arbitrate` CLI produces no such ladder, so a class budget never fires from
a copy-paste CLI line (issue #97's scoping finding; `tests/test_concurrency_
class.py` pins why). This 30-line harness IS that host: it feeds the slot
ladder + the `burn-in` budget and shows the (N+1)th chamber refused with
CLASS_BUDGET_EXHAUSTED — the same `arbiter.arbitrate(...)` the picker calls.

Run:  python farm_budget_demo.py     (from this workspace dir; needs `dos-kernel`)
"""

from __future__ import annotations

from dos import arbiter

# The lab has THREE chambers but power/thermal headroom for only TWO campaigns
# at once. The host feeds the slot ladder; the "burn-in" class budget caps it.
# Trees are pairwise-disjoint, so the ONLY thing that can refuse a grab is the
# budget — never a file-tree collision. (This is exactly the picker shape the
# generic CLI does not produce.)
LADDER = [
    ("chamber-1", "burn-in", ["benches/chamber-1/**"]),
    ("chamber-2", "burn-in", ["benches/chamber-2/**"]),
    ("chamber-3", "burn-in", ["benches/chamber-3/**"]),
]
BUDGETS = {"burn-in": 2}


def _lease(lane: str, tree: list[str]) -> dict:
    return {"lane": lane, "lane_kind": "burn-in", "tree": tree,
            "loop_ts": "20260614T1200Z"}


def run_demo() -> dict:
    """Three sequential bare grabs under budget=2. Returns the three decisions
    so a test can assert the headline property without scraping stdout."""
    # Grab 1 — empty farm → admit chamber-1.
    d0 = arbiter.arbitrate(
        requested_lane="", requested_kind="", requested_tree=[],
        auto_pick_order=LADDER, class_budgets=BUDGETS, live_leases=[])

    # Grab 2 — chamber-1 live, still under budget → admit chamber-2.
    live1 = [_lease("chamber-1", ["benches/chamber-1/**"])]
    d1 = arbiter.arbitrate(
        requested_lane="", requested_kind="", requested_tree=[],
        auto_pick_order=[LADDER[1], LADDER[2]], class_budgets=BUDGETS,
        live_leases=live1)

    # Grab 3 — chamber-1 AND chamber-2 live, budget 2 full → REFUSE.
    live2 = [_lease("chamber-1", ["benches/chamber-1/**"]),
             _lease("chamber-2", ["benches/chamber-2/**"])]
    d2 = arbiter.arbitrate(
        requested_lane="", requested_kind="", requested_tree=[],
        auto_pick_order=[LADDER[2]], class_budgets=BUDGETS, live_leases=live2)

    return {"grab1": d0, "grab2": d1, "grab3": d2}


if __name__ == "__main__":
    d = run_demo()
    print(f"GRAB 1: {d['grab1'].outcome:8} lane={d['grab1'].lane}  "
          f"{d['grab1'].reason}")
    print(f"GRAB 2: {d['grab2'].outcome:8} lane={d['grab2'].lane}  "
          f"{d['grab2'].reason}")
    print(f"GRAB 3: {d['grab3'].outcome:8}           {d['grab3'].reason}")
