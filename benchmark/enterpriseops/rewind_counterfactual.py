"""rewind_counterfactual.py — $0 replay: what would SUBTRACT (rewind) have done where BLOCK APPENDED?

docs/171 (the rewindable-FIX-loop thesis). The docs/144 live A/B refuted author-and-believe:
BLOCK (`synthetic_corrective_result`, APPENDED to the stream) scored net -4/task — it broke ~5x
more downstream steps than it fixed. The thesis under test: the failure was the APPEND, not the
detect. rewind.py SUBTRACTS the dead-end turns (truncate the transcript to a kernel-minted anchor,
re-enter with a byte-clean no-good note) instead of appending. This replay measures, on the REAL
recorded block-arm trajectories, the counterfactual difference — using `rewind.py`'s ACTUAL verdict
logic, no re-mocking.

What this CAN show ($0, exact): on every recorded block run, where the kernel WOULD have placed the
rewind anchor (the last verified tool result before the first invented-ID block), how many appended
corrections the subtract eliminates, and the byte-clean no-good note it would have re-entered with.
What this CANNOT show: whether the agent then SUCCEEDS — that needs live re-dispatch (see live_ab.py
--arms rewind). This is the DETECT/PLACEMENT half; the live A/B is the CONVERSION half.

The anchor rule (the honest mapping from a tool stream to rewind.py's inputs):
  * Each tool_result is a "turn" (index = position, digest = sha of its bytes).
  * A BLOCK synthetic correction (dos_blocked:True, status blocked_unresolved_id) marks a dead end.
  * The rewind ANCHOR is the last tool_result BEFORE the first block in a thrash-run that VERIFIED
    (a real success result, not a synthetic) — the last-known-good state. That is the minted
    SuspendCheckpoint; everything after it (the invented-ID attempts + the appended corrections) is
    `dropped_turns`.
  * The FIRE is convergence.THRASHING when a tool is blocked >=2 times in a run (the agent re-entered
    the same hole — the ground-truth loop-cap), else resume.DIVERGED is not applicable (no git axis
    here) so a single block is NOT a rewind trigger (the loop is still advancing).
  * The NO-GOOD NOTE carries ONLY: (a) a VERIFY_NOT_SHIPPED token over the unresolved id (a structured
    field the kernel computed, never prose) + (b) the env's own blocked_unresolved_id error excerpt
    (THIRD_PARTY — the gym authored it, not the agent). This is byte-for-byte what rewind.py emits.

Pure replay of recorded JSON — no model calls, no network. Rerunnable: point --dir at any block arm.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# import the REAL kernel verdict (no re-implementation)
_HERE = os.path.dirname(os.path.abspath(__file__))
_DOS_SRC = os.path.join(_HERE, "..", "..", "src")
if os.path.isdir(_DOS_SRC):
    sys.path.insert(0, _DOS_SRC)

from dos.rewind import (  # noqa: E402
    rewind_plan, TurnRef, FireVerdict, EnvExcerpt, digest_turn, Rewind,
)
from dos.intent_ledger import SuspendCheckpoint  # noqa: E402
from dos.completion import Convergence  # noqa: E402
from dos.log_source import Accountability  # noqa: E402
from dos.rewind_tokens import VerdictToken, KIND_VERIFY_NOT_SHIPPED  # noqa: E402


def _is_synth(tr) -> bool:
    if not isinstance(tr, dict):
        return False
    if tr.get("dos_blocked"):
        return True
    r = tr.get("result")
    return isinstance(r, dict) and r.get("dos_blocked")


def _inner(tr) -> dict:
    r = tr.get("result", {})
    return r.get("result", r) if isinstance(r, dict) else {}


def _verified(tr) -> bool:
    """A real (non-synthetic) tool result that succeeded — a last-known-good turn.

    The gym wraps every result as tr["result"] = {"success": bool, "result": <payload>, ...}, so
    the success flag is at the OUTER level, not inside the payload. (The live arm's first cut read
    the payload and never saw success=True → every anchor UNANCHORED → no rewind ever fired; the
    live smoke caught it. This reader matches the fixed live `_is_verified` exactly.)"""
    if _is_synth(tr):
        return False
    r = tr.get("result", {})
    if not isinstance(r, dict):
        return False
    if r.get("success") is True:
        return True
    inner = r.get("result", {})
    if isinstance(inner, dict):
        if inner.get("success") is True:
            return True
        st = str(inner.get("status", "")).lower()
        if st and "error" not in st and "blocked" not in st:
            return True
    return False


def _turn_bytes(tr) -> str:
    """Stable bytes for a tool_result turn (tool + args + a result summary)."""
    return json.dumps({"t": tr.get("tool_name"), "a": tr.get("arguments"),
                       "s": _inner(tr).get("status")}, sort_keys=True)


def analyze_run(run: dict) -> dict | None:
    """Apply rewind.py to one recorded block run. Returns the counterfactual, or None if no thrash."""
    trs = run.get("tool_results", []) or []
    # find blocks and which tool each is on
    blocks = [(i, tr.get("tool_name")) for i, tr in enumerate(trs) if _is_synth(tr)]
    if not blocks:
        return None
    # THRASH = a tool blocked >=2 times => convergence.THRASHING => a rewind trigger.
    from collections import Counter
    tool_block_counts = Counter(name for _, name in blocks)
    thrash_tools = {t for t, c in tool_block_counts.items() if c >= 2}
    if not thrash_tools:
        return None  # single block on each tool — loop still advancing, NO_REWIND (honest)

    # the first block index on a thrashed tool
    first_block_idx = min(i for i, name in blocks if name in thrash_tools)
    # anchor = last VERIFIED turn strictly before the first block (last-known-good)
    anchor_idx = -1
    for i in range(first_block_idx - 1, -1, -1):
        if _verified(trs[i]):
            anchor_idx = i
            break

    # build rewind.py inputs from the REAL stream
    turns = tuple(TurnRef(i, digest_turn(_turn_bytes(tr))) for i, tr in enumerate(trs))
    if anchor_idx >= 0:
        cp = SuspendCheckpoint(turn_index=anchor_idx,
                               transcript_digest=turns[anchor_idx].digest, present=True)
    else:
        cp = SuspendCheckpoint.absent()  # no verified state to rewind to -> UNANCHORED (honest)

    fire = FireVerdict.from_convergence(Convergence.THRASHING)

    # the no-good note: structured token over the unresolved id + the env's own error bytes
    first_block_tr = trs[first_block_idx]
    binner = _inner(first_block_tr)
    unresolved = binner.get("unresolved") or []
    unresolved_args = ",".join(u.get("arg", "?") for u in unresolved) or "id"
    env_err = str(binner.get("error", "references id(s) that never appeared"))[:200]
    tokens = (VerdictToken(KIND_VERIFY_NOT_SHIPPED, {"sha": f"{unresolved_args}=never-appeared"}),)
    env = EnvExcerpt(env_err, Accountability.THIRD_PARTY)  # gym authored it, not the agent

    plan = rewind_plan(turns, cp, fire, verdict_tokens=tokens, env_excerpt=env)

    return {
        "thrash_tools": sorted(thrash_tools),
        "n_tool_results": len(trs),
        "n_blocks_appended": len(blocks),
        "first_block_idx": first_block_idx,
        "anchor_idx": anchor_idx,
        "verdict": plan.verdict.value,
        "rewind_to_turn": plan.rewind_to_turn,
        "dropped_turns": list(plan.dropped_turns),
        # the SUBTRACT vs APPEND delta: appends carried forward vs turns subtracted
        "appends_eliminated": sum(1 for i in plan.dropped_turns if _is_synth(trs[i])),
        "turns_subtracted": len(plan.dropped_turns),
        "no_good_note": list(plan.no_good_note.render_lines()),
        "overall_success": bool(run.get("overall_success")),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(_HERE, "live_results", "block"))
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.dir, "*.json")))
    results = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for run in d.get("runs", []):
            r = analyze_run(run)
            if r is not None:
                r["file"] = os.path.basename(f)
                results.append(r)

    rewinds = [r for r in results if r["verdict"] == Rewind.REWIND.value]
    total_appends_elim = sum(r["appends_eliminated"] for r in rewinds)
    total_turns_sub = sum(r["turns_subtracted"] for r in rewinds)

    summary = {
        "as_of": "2026-06-05",
        "dir": args.dir,
        "n_files": len(files),
        "thrash_runs_found": len(results),
        "rewind_fired": len(rewinds),
        "unanchored": sum(1 for r in results if r["verdict"] == Rewind.UNANCHORED.value),
        "no_rewind": sum(1 for r in results if r["verdict"] == Rewind.NO_REWIND.value),
        "appended_corrections_eliminated_by_subtract": total_appends_elim,
        "total_turns_subtracted": total_turns_sub,
        "thrash_run_success": f"{sum(1 for r in results if r['overall_success'])}/{len(results)}",
    }

    if args.json:
        print(json.dumps({"summary": summary, "runs": results}, indent=2))
        return

    print("=== rewind counterfactual on the REAL block arm (as of 2026-06-05) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\n=== per-thrash-run (what SUBTRACT would have done where BLOCK APPENDED) ===")
    for r in results:
        print(f"\n  {r['file']}")
        print(f"    thrash on {r['thrash_tools']}  blocks_appended={r['n_blocks_appended']}  "
              f"success={r['overall_success']}")
        print(f"    verdict={r['verdict']}  anchor=turn {r['anchor_idx']}  "
              f"dropped={r['dropped_turns']}  appends_eliminated={r['appends_eliminated']}")
        if r["no_good_note"] and r["verdict"] != "NO_REWIND":
            print(f"    no-good note (byte-clean, re-entered instead of appending):")
            for line in r["no_good_note"]:
                print(f"      | {line}")


if __name__ == "__main__":
    main()
