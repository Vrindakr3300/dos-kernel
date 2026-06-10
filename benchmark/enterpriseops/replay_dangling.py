"""Measure the dangling-intent detector on recorded trajectories (docs/150, the steelman of 149).

Folds the SHIPPED `dos.dangling_intent.classify_stop` over each recorded gemini-3-flash run's
terminal narration + post-turn execution delta, and joins to the gym's own `verification_results`
(recorded ground truth). Pure replay — no model calls, no DB, no Docker (the `failure_distribution`
/ `replay_stall` sibling, the L1-safe path, docs/148). It answers: does the byte-clean, planner-free,
admission-against-interest detector actually flag a real slice of the 92% premature-completion
failures, and does it stay quiet on passed runs?

Two numbers (the arg_provenance-eval discipline):
  * against_interest_recall = of FAILED runs, the fraction the detector flags (recall over the head).
  * false_fire_on_passed    = of PASSED runs, the fraction wrongly flagged (must be ~0 — a passed run
                              should rarely end on "I still need to…").

The detector reads the agent's OWN terminal sentence (distrusted on the against-interest axis — the
one self-report DOS believes) corroborated by the ENV-authored absence of any subsequent tool result.
This is DETECTION (advisory), never a fix; the recall is the narrating-stopper subset, not the head.
"""

from __future__ import annotations

import glob
import json
import sys

from dos.dangling_intent import StopEvidence, classify_stop


def _runs(d):
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    if isinstance(d, dict):
        return d.get("runs") if isinstance(d.get("runs"), list) else [d]
    return []


def _terminal_text(run: dict) -> str:
    """The agent's last authored narration. Prefer the explicit `model_response`; else the last
    `ai_message` in `conversation_flow` (the `claim_extract` boundary-reader convention)."""
    mr = run.get("model_response")
    if isinstance(mr, str) and mr.strip():
        return mr
    flow = run.get("conversation_flow") or []
    for entry in reversed(flow):
        if isinstance(entry, dict) and entry.get("type") in ("ai_message", "assistant"):
            c = entry.get("content")
            if isinstance(c, str) and c.strip():
                return c
    return ""


def _results_after_terminal(run: dict) -> int:
    """Count env-authored tool results that landed AFTER the terminal narration. In the recorded
    shape the terminal `model_response` is the last turn, so anything in the flow AFTER the last
    ai_message that is a tool_result counts. Conservatively 0 when the structure does not expose
    ordering (the common stop case: narration is last)."""
    flow = run.get("conversation_flow") or []
    last_ai = -1
    for i, entry in enumerate(flow):
        if isinstance(entry, dict) and entry.get("type") in ("ai_message", "assistant"):
            last_ai = i
    if last_ai < 0:
        return 0
    return sum(
        1 for entry in flow[last_ai + 1:]
        if isinstance(entry, dict) and entry.get("type") in ("tool_result", "tool")
    )


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "benchmark/enterpriseops/live_results"
    files = glob.glob(f"{folder}/**/*.json", recursive=True)

    fail_flag = fail_tot = ok_flag = ok_tot = 0
    examples = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for r in _runs(d):
            if r.get("overall_success") is None:
                continue
            ev = StopEvidence(
                final_turn_text=_terminal_text(r),
                results_after_turn=_results_after_terminal(r),
            )
            v = classify_stop(ev)
            flagged = v.is_dangling
            if r.get("overall_success") is False:
                fail_tot += 1
                fail_flag += 1 if flagged else 0
                if flagged and len(examples) < 4:
                    examples.append(v.matched_cue)
            else:
                ok_tot += 1
                ok_flag += 1 if flagged else 0

    recall = (100 * fail_flag / fail_tot) if fail_tot else 0.0
    false_fire = (100 * ok_flag / ok_tot) if ok_tot else 0.0

    print("=" * 80)
    print("  DANGLING-INTENT detector on recorded gemini-3-flash trajectories (docs/150)")
    print("  the SHIPPED dos.dangling_intent.classify_stop, folded over terminal narration")
    print("=" * 80)
    print(f"  FAILED runs flagged:  {fail_flag:>3}/{fail_tot:<3} = {recall:.0f}%  "
          f"(against_interest_recall over the ~92% head)")
    print(f"  PASSED runs flagged:  {ok_flag:>3}/{ok_tot:<3} = {false_fire:.0f}%  "
          f"(false_fire_on_passed -- must be ~0)")
    print("-" * 80)
    print("  READING (docs/150): this is the NARRATING premature-stopper -- the agent told on")
    print("  itself ('Now I need to...') and stopped. Byte-clean (the cue grammar is task-")
    print("  independent; the no-tool-result-after is env-authored), planner-free, WARN-only.")
    print("  It is DETECTION of a real slice docs/149 declared impossible -- not a FIX (no plan).")
    if examples:
        print("  flagged cues (the agent's own words):")
        for c in examples:
            print(f"    - {c!r}")
    print("=" * 80)


if __name__ == "__main__":
    main()
