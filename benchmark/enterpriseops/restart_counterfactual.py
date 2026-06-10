"""restart_counterfactual.py — the $0 slice-sizing replay that GATES any live restart spend.

docs/176 §6 + the seeded-restart audit (2026-06-06). The whole differentiation of "clean restart
seeded with DOS knowledge" rests on a single UNMEASURED prediction (restart_arm.py:25-29): restart
beats rewind on the UPSTREAM-OMISSION slice, because re-reasoning the whole prefix is the only move
in {none, append, subtract, restart} that can escape an omission whose cause lives BEFORE the anchor.

But CONVERSION is live-only: restart discards the window and the next move is a FRESH LLM call on
[System, Human, (note?)] — no recorded transcript contains those re-orchestrated turns, so no $0 replay
can produce the success/failure. What a $0 replay CAN do — and what this module does — is decide whether
the live spend is even WORTH it, by sizing the slice and the cost the live A/B would inherit:

  (1) FIRE RATE — over every recorded run, how many would restart fire on? Restart's trigger is the
      SAME as rewind's: a tool BLOCKED a 2nd time (block_count >= 2 = convergence.THRASHING). We recover
      the per-tool block count from the recorded `dos_block` events (the kernel's own logged fires), then
      apply the REAL `restart_arm.restart_decision` (one-shot-per-tool cap and all) — no re-implementation.

  (2) THE SLICE — of the fired runs, how many are SAME (byte-identical repeated env error = upstream
      omission, livelock-prone, where restart is PREDICTED to win) vs VARYING (exploratory)? We reuse the
      byte-clean `natural_flip_split._thrash_class` (reads only env-authored error bytes, never narration).
      **The gate: if the SAME slice is < SLICE_FLOOR of thrash runs, STOP — the prediction has too small a
      testable population to justify ~480 live Gemini runs.**

  (3) THE COST — restart RE-PAYS the prefix rewind keeps warm. We compute the would-be discarded window
      (`messages[2:]`, i.e. every turn past [System, Human]) per fired run and run the REAL
      `restart_arm.estimate_window_tokens` over it (the same proxy the live arm's ledger uses for the no-gym
      test; the live arm reads real usage_metadata, but the RELATIVE prefix-re-pay quantity is what the
      cost veto KC#5 needs, and the char/4 proxy preserves it). This is the arithmetic the rewind replay
      (turns-only) could never produce — the cost half of docs/176 §4, made concrete on real data.

CONSERVATIVE BY DESIGN (the natural_thrash_counterfactual.py discipline): this UNDER-counts fires, never
over. We count a thrash only when the kernel ACTUALLY logged >= 2 blocks on a tool in the recorded run
(BLOCK-arm dirs have these; a `none` dir has zero dos_block events and reports a 0 fire rate — correct,
since restart's trigger is the block, and `none` never blocks). So point --dir at a CONSULT/BLOCK arm
(live_results/block, live_results_rewind_paired/block, …) to size restart's population.

What this CANNOT show: conversion (live-only, by construction). What it DECIDES: whether to spend at all.

Pure replay of recorded JSON — no model calls, no network. Read-only.

    python restart_counterfactual.py --dir live_results/block
    python restart_counterfactual.py --dir live_results_rewind_paired/block --slice-floor 0.15
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# reuse the REAL live-arm logic — no re-implementation, so the replay and the live run can never drift
from restart_arm import estimate_window_tokens, restart_decision  # noqa: E402
from natural_flip_split import _thrash_class as _env_thrash_class, _run0, _tid  # noqa: E402

SLICE_FLOOR_DEFAULT = 0.15  # docs/176 audit: below this, the SAME slice is too small to justify spend


def _block_thrash_class(run, tool):
    """SAME vs VARYING for the ARG-PROVENANCE / BLOCK regime, off the blocked-INVENTED-ID signature.

    The env-error `_STRUCT` classifier (`natural_flip_split._thrash_class`) was built for the NATURAL
    regime, where the GYM returns repeated real errors a restart could read. In the BLOCK arm the thrash
    is different in KIND: DOS intercepts the call BEFORE the gym runs it (arg_provenance refused an
    invented FK id), so there is no gym env-error to hash — the failure is recorded as the kernel's own
    `dos_block` event carrying `unsupported` (the id(s) that never appeared). The right SAME-vs-VARYING
    axis for THIS regime is over that id signature:

      * SAME (distinct id-sets == 1) — the agent re-invents the SAME missing id every block. That id was
        never looked up; the missing read lives UPSTREAM of any anchor → the rewind livelock class, where
        restart (drop-the-whole-prefix) is the predicted escape. (e.g. configuration_item_id ×2, group_id ×2.)
      * VARYING (distinct id-sets > 1) — the agent invents DIFFERENT ids across blocks (e.g.
        configuration_item_id → owner_id, parent_incident → child_incident). Exploratory; restart's
        prediction is silent here.

    Reads ONLY the kernel's logged `unsupported` field (byte-clean — the kernel authored it over the
    distrusted call, never the agent's narration). Returns 'unknown' if < 2 blocks carry id-sets.
    """
    id_sets = []
    for e in (run.get("conversation_flow") or []):
        if (isinstance(e, dict) and e.get("type") == "dos_block"
                and e.get("tool_name") == tool):
            ids = e.get("unsupported")
            if ids:
                id_sets.append(tuple(sorted(ids)))
    if len(id_sets) < 2:
        return "unknown"
    return "same" if len(set(id_sets)) == 1 else "varying"


def _thrash_class(run, tool):
    """Classify a thrash SAME/VARYING, regime-aware: block-id signature first (the BLOCK/arg-prov regime),
    falling back to the env-error grammar (the natural regime). A BLOCK-arm thrash is an invented-id block;
    a natural-arm thrash is a repeated gym error. We try the block signature first because this replay is
    pointed at CONSULT/BLOCK dirs; if the run has no id-bearing blocks, defer to the env-error classifier."""
    cls = _block_thrash_class(run, tool)
    if cls != "unknown":
        return cls
    return _env_thrash_class(run, tool)


def _blocks_per_tool(run):
    """Recover the per-tool block count from the kernel's OWN logged dos_block events.

    A `dos_block` conversation_flow event is the kernel's record that arg_provenance refused a tool call
    on a 2nd-class invented id (the BLOCK intervention). Counting them per tool reproduces the
    `_block_counts[tool_name]` the live loop maintains — restart's trigger reads exactly this counter.
    """
    c = Counter()
    for e in (run.get("conversation_flow") or []):
        if isinstance(e, dict) and e.get("type") == "dos_block":
            tn = e.get("tool_name")
            if tn:
                c[tn] += 1
    return c


def _discarded_window_turns(run):
    """The turns a restart would DISCARD = everything past [System, Human] in the recorded transcript.

    The live arm discards `messages[2:]` (restart_arm.py:237). The recorded `conversation_flow` is the
    transport-stable shadow of that message list: [system_message, user_message, <ai_message|tool_result|
    dos_*>...]. Drop the leading system+user (the 2 turns a restart KEEPS) and the rest is the prefix a
    restart re-pays. We pass the raw event dicts to estimate_window_tokens, which reads `content` off a
    dict (restart_arm.py:75-78), so an event with no `content` contributes its other text via str() — a
    stable per-run proxy for the re-paid prefix, which is all KC#5 needs.
    """
    cf = run.get("conversation_flow") or []
    # keep[0:2] = [System, Human]; discard the rest (the dead window restart re-orchestrates away)
    return cf[2:]


def _restart_fires(run):
    """Apply the REAL restart trigger to a recorded run. Returns the list of tools restart would fire on.

    One-shot-per-tool (the live cap, restart_arm.py:266): a tool fires at most once even if blocked 3+×.
    We walk the blocked tools and let `restart_decision` adjudicate each (restart_on=True so we measure the
    population the arm WOULD fire on), threading the already-restarted set exactly as the live loop does.
    """
    fires = []
    restarted = set()
    for tool, n in _blocks_per_tool(run).items():
        if restart_decision(
            restart_on=True,
            block_count=n,
            already_restarted_tools=restarted,
            tool_name=tool,
        ):
            fires.append(tool)
            restarted.add(tool)
    return fires


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True,
                    help="a CONSULT/BLOCK arm result dir (has dos_block events), e.g. live_results/block")
    ap.add_argument("--slice-floor", type=float, default=SLICE_FLOOR_DEFAULT,
                    help="STOP gate: min SAME-slice fraction of thrash runs to justify live spend")
    args = ap.parse_args(argv)

    arm_dir = args.dir if os.path.isabs(args.dir) else os.path.join(_HERE, args.dir)
    files = sorted(glob.glob(os.path.join(arm_dir, "results_*.json")))
    if not files:
        print(f"[restart_cf] no results_*.json under {arm_dir}", file=sys.stderr)
        return 2

    n_runs = 0
    n_thrash_runs = 0           # runs where restart would fire >= once
    fires_total = 0            # total restart events (a run can fire on >1 tool)
    by_class = Counter()        # same / varying / unknown over fired (tool, run) pairs
    repaid_tokens = []          # per fired-run prefix-token re-pay (the cost half)
    discarded_turns = []        # per fired-run discarded-turn count
    blocked_tool_hist = Counter()

    for f in files:
        run = _run0(f)
        if not run:
            continue
        n_runs += 1
        fires = _restart_fires(run)
        if not fires:
            continue
        n_thrash_runs += 1
        discarded = _discarded_window_turns(run)
        repaid = estimate_window_tokens(discarded)
        repaid_tokens.append(repaid)
        discarded_turns.append(len(discarded))
        for tool in fires:
            fires_total += 1
            blocked_tool_hist[tool] += 1
            by_class[_thrash_class(run, tool)] += 1

    same = by_class.get("same", 0)
    varying = by_class.get("varying", 0)
    unknown = by_class.get("unknown", 0)
    classified = same + varying  # 'unknown' = < 2 struct-errors recorded, not slice-able
    same_frac = (same / classified) if classified else 0.0
    med_repaid = sorted(repaid_tokens)[len(repaid_tokens) // 2] if repaid_tokens else 0
    med_turns = sorted(discarded_turns)[len(discarded_turns) // 2] if discarded_turns else 0

    print("=" * 78)
    print("  RESTART COUNTERFACTUAL — $0 slice-sizing (gates live spend)")
    print(f"  dir = {os.path.relpath(arm_dir, _HERE)}")
    print("=" * 78)
    print(f"  runs scanned ................ {n_runs}")
    print(f"  runs restart would FIRE on .. {n_thrash_runs}  "
          f"({(100*n_thrash_runs/n_runs if n_runs else 0):.1f}% fire rate)")
    print(f"  total restart events ........ {fires_total}  (one-shot-per-tool)")
    print("-" * 78)
    print(f"  {'slice':<14}{'fired':>8}   (the SAME slice is where restart is PREDICTED to beat rewind)")
    print(f"  {'same (omission)':<14}{same:>8}")
    print(f"  {'varying (explor)':<14}{varying:>8}")
    print(f"  {'unknown':<14}{unknown:>8}   (< 2 struct-errors recorded — not slice-able)")
    print("-" * 78)
    print(f"  SAME slice fraction (of classified) = {same_frac:.0%}   "
          f"[floor={args.slice_floor:.0%}]")
    print("-" * 78)
    print(f"  cost a live restart would re-pay (the KC#5 cost half):")
    print(f"    median discarded turns / fire ... {med_turns}")
    print(f"    median prefix tokens re-paid .... ~{med_repaid}  (char/4 proxy; live reads usage_metadata)")
    if blocked_tool_hist:
        top = ", ".join(f"{t}×{n}" for t, n in blocked_tool_hist.most_common(5))
        print(f"    top thrash tools ................ {top}")
    print("=" * 78)

    # THE GATE — the decisive $0 readout
    if n_thrash_runs == 0:
        print("  VERDICT: restart fires on ZERO recorded runs in this dir.")
        print("           (A `none`/no-block dir has no dos_block events — point --dir at a BLOCK arm.)")
        verdict_stop = True
    elif same_frac < args.slice_floor:
        print(f"  VERDICT: STOP — SAME slice {same_frac:.0%} < floor {args.slice_floor:.0%}.")
        print("           The upstream-omission population is too small to justify ~480 live runs.")
        print("           The prediction (restart > rewind on upstream cause) has too few testable cases.")
        verdict_stop = True
    else:
        print(f"  VERDICT: PROCEED — SAME slice {same_frac:.0%} >= floor {args.slice_floor:.0%}.")
        print(f"           {same} fired runs are upstream-omission = a testable population for the")
        print("           restart>rewind prediction. Land the wiring + run the live A/B + smoke.")
        verdict_stop = False
    print("  REMINDER: conversion is LIVE-ONLY — this sizes the slice + cost, never the win.")
    print("=" * 78)
    return 1 if verdict_stop else 0


if __name__ == "__main__":
    raise SystemExit(main())
