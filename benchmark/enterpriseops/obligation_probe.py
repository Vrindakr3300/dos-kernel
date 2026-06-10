"""Probe: is there a BYTE-CLEAN detection signal for premature completion? (steelman of docs/149)

docs/149 concluded DOS cannot own the 92% premature-completion failure because the completion verdict's
inputs (declared, verified) are both forgeable. This probe ARGUES THE OPPOSITE empirically: a real
stopped-early run had the ENV-AUTHORED prompt say "allocate the appropriate internal personnel" and the
ENV-RECORDED call stream show no membership call ever fired -- both halves env-authored, neither the
agent's rubric. So the question is measurable, not just arguable.

THE BYTE-CLEAN SIGNAL (no planner, no satisfaction predicate):
  For each ENV-AUTHORED imperative verb in the task prompt that maps -- by a FIXED, task-INDEPENDENT
  verb->tool-stem table (NOT per-task reasoning) -- to a write tool, did ANY call whose name carries that
  stem appear in the ENV-RECORDED call stream? An env-stated obligation verb with no matching call is a
  byte-clean "the env asked for X and no X-call fired" -- provenance of (env prompt bytes) vs (env-recorded
  call stream), never "is the DB correct" (the forgeable predicate docs/143 §5a kills).

THE HONEST CAVEATS this probe MEASURES (not hides):
  * RECALL on real failed runs (how much of the 92% it could advisory-flag).
  * FALSE-FIRE on real SUCCESSFUL runs -- the decisive test: if it fires on successes too, it is detecting
    task COMPLEXITY, not PREMATURITY, and is noise. A safe signal fires far more on failures than successes.
  * The verb->stem table is the load-bearing honesty: it is fixed here (env-schema-shaped verbs), NOT
    derived per-task. If a real build needed per-task prose reasoning to map verbs, it would be a PLANNER
    and DEAD. This crude table is the floor; the question is whether a schema-derived table is both safe
    AND high-recall.

This is a PROBE, not a shipped mechanism -- it measures whether the steelman of docs/149 has legs on real
data, the way failure_distribution.py measured the failure shape. Pure replay (no model/DB/Docker).
"""

from __future__ import annotations

import glob
import json
import re
import sys

# A FIXED, task-INDEPENDENT imperative-verb -> tool-name-stem table. Derived from the env's write-verb
# vocabulary (the same shape dos_react's is_mutating_tool stems use), NOT from any task's prose. This is
# the line between byte-clean (a fixed table) and planner (per-task reasoning) -- kept deliberately small
# and crude so it is auditable; a real build would derive it from the gym tool SCHEMAS, still task-independent.
VERB_TO_STEM = {
    "allocate": "member", "assign": "assign", "add": "add", "create": "create",
    "establish": "create", "notify": "notif", "send": "send", "link": "link",
    "transition": "transition", "update": "update", "remove": "remove",
    "deactivate": "deactiv", "reactivate": "reactiv", "relocate": "reloc", "move": "move",
}


def _runs(d):
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    if isinstance(d, dict):
        return d.get("runs") if isinstance(d.get("runs"), list) else [d]
    return []


def unmet_obligations(prompt: str, tools_used) -> list:
    """The env-imperative verbs present in the prompt for which NO matching-stem call fired. PURE byte
    comparison: env prompt bytes vs env-recorded call stream, via the fixed table."""
    p = (prompt or "").lower()
    used = " ".join(tools_used or []).lower()
    present = [v for v in VERB_TO_STEM if re.search(r"\b" + v, p)]
    return [v for v in present if VERB_TO_STEM[v] not in used]


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "benchmark/enterpriseops/live_results"
    files = glob.glob(f"{folder}/**/*.json", recursive=True)

    fail_flag = fail_tot = ok_flag = ok_tot = 0
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        top = d if isinstance(d, dict) else {}
        prompt = top.get("benchmark_config", {}).get("user_prompt", "") or ""
        for r in _runs(d):
            if r.get("overall_success") is None:
                continue
            unmet = unmet_obligations(prompt, r.get("tools_used"))
            if r.get("overall_success") is False:
                fail_tot += 1
                fail_flag += 1 if unmet else 0
            else:
                ok_tot += 1
                ok_flag += 1 if unmet else 0

    recall = (100 * fail_flag / fail_tot) if fail_tot else 0.0
    false_fire = (100 * ok_flag / ok_tot) if ok_tot else 0.0
    prec = (fail_flag / (fail_flag + ok_flag)) if (fail_flag + ok_flag) else 0.0

    print("=" * 80)
    print("  BYTE-CLEAN premature-completion DETECTION probe (steelman of docs/149)")
    print("  signal: env-prompt imperative verb with NO matching-stem call in the env-recorded stream")
    print("=" * 80)
    print(f"  FAILED runs flagged:  {fail_flag:>3}/{fail_tot:<3}  = {recall:.0f}%  (RECALL over the failures)")
    print(f"  SUCCESS runs flagged: {ok_flag:>3}/{ok_tot:<3}  = {false_fire:.0f}%  (FALSE-FIRE -- the decisive test)")
    print(f"  precision (flagged that really failed): ~{100*prec:.0f}%  [base-rate inflated; small n]")
    print("-" * 80)
    if false_fire >= 25:
        print("  READING: false-fire is HIGH -- this crude table partly detects task COMPLEXITY, not just")
        print("  prematurity. NOT deployment-safe as-is (the 660:30 backfire). But recall is far above the")
        print("  ~0 docs/149 implied -> a byte-clean signal EXISTS; the open question is a SAFE table +")
        print("  WARN-only/fail-toward-done discipline. docs/149's 'fully unbuildable' claim is too strong.")
    else:
        print("  READING: false-fire is low AND recall is high -> a genuinely safe byte-clean detector;")
        print("  docs/149's 'DOS cannot own completion' is OVERTURNED for the DETECTION (advisory) claim.")
    print("  (Caveat: small success sample. The honest verdict needs the safe-table + a bigger corpus.)")
    print("=" * 80)


if __name__ == "__main__":
    main()
