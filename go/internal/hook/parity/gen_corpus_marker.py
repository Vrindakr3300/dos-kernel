#!/usr/bin/env python3
"""Generate the GHF marker differential parity corpus (the keep-alive wait-marker budget).

The `marker` decider is the Go port of `dos.loop_decide.wait_marker_budget` +
`cli.cmd_hook_marker`. Unlike posttool (whose state is an in-memory step list), marker's
ONLY state is an integer count read from the per-session disk tally — so the BYTE
contract worth pinning differentially is the pure decision for a given (prior_count,
max_markers): the allow/refuse bit, AND the EXACT bytes emitted on each branch:

  * allow  → `{"decision": "block", "reason": <full held-open prose>}` (json.dumps sort_keys)
  * refuse → "" (an empty Stop output is CC's "allow stop")

This corpus is the in-memory twin of the live budget sequence: it walks a budget from
0 up past the cap, capturing the expected emitted stdout at each prior_count, computed
through the SAME path the live hook runs (`wait_marker_budget` + the cmd_hook_marker
block-reason wrapping). The Go `parity_marker_test.go` recomputes each case via
`waitMarkerBudget` + `markerBlockReason` and asserts byte-equality — the marker arm of
the GHF differential gate. The disk round-trip (record→count) is covered separately by
the Go unit tests + the Python marker_sensor tests; this isolates the dialect bytes.

Run: python gen_corpus_marker.py > corpus_marker.jsonl
"""
from __future__ import annotations

import json
import sys

from dos.loop_decide import wait_marker_budget


def _block_reason(verdict_reason: str) -> str:
    """The full block message cmd_hook_marker emits on the allow path (cli.py) — the
    operator-facing continuation prose. Kept in sync with `cmd_hook_marker`'s `reason`
    local; the Go `markerBlockReason` must match these exact bytes."""
    return (
        f"DOS wait-marker budget: {verdict_reason}. The keep-alive turn is held "
        f"open; continue waiting on the background task's completion signal rather "
        f"than re-polling. (This block is withdrawn once the budget is spent, at "
        f"which point you should end the turn and let the task-notification re-invoke "
        f"you.)"
    )


def _expected_stdout(prior_count: int, max_markers: int) -> str:
    """The EXACT bytes cmd_hook_marker prints for one decision: the block dialect on
    allow (json.dumps sort_keys, matching pyJSONDumps), or "" on refuse (allow stop)."""
    decision = wait_marker_budget(prior_count, max_markers)
    if not decision.allow:
        return ""
    payload = {"decision": "block", "reason": _block_reason(decision.reason)}
    return json.dumps(payload, sort_keys=True)


def case(name: str, max_markers: int, prior_counts: list[int]) -> dict:
    steps = []
    for prior in prior_counts:
        decision = wait_marker_budget(prior, max_markers)
        steps.append({
            "prior_count": prior,
            "max_markers": max_markers,
            "expected_allow": decision.allow,
            "expected_carry": decision.markers_emitted,
            "expected_reason": decision.reason,
            "expected_stdout": _expected_stdout(prior, max_markers),
        })
    return {"name": name, "steps": steps}


def build() -> list[dict]:
    cases = []
    # The default per-run cap (4): a budget walked from fresh (0) up past the cap.
    # 0..3 allow (block, turn held open); 4..5 refuse (allow stop).
    cases.append(case("default-cap-4-walk", 4, [0, 1, 2, 3, 4, 5]))
    # A tight cap of 1: the very first marker is the last one allowed.
    cases.append(case("tight-cap-1", 1, [0, 1, 2]))
    # A wider cap of 8 (an operator override): allow through 7, refuse at 8.
    cases.append(case("wide-cap-8-boundary", 8, [6, 7, 8]))
    return cases


def main() -> int:
    for c in build():
        sys.stdout.write(json.dumps(c, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
