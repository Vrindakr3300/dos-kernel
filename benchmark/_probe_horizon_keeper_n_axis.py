"""N-axis probe v2 — the $0 horizon-keeper measurement (dos-private/dispatch-os-the-horizon-keeper-at-k-equals-one.md §8).

Folds the REAL Claude Code session corpus (single-agent long-horizon traces, k=1
by construction) through the SHIPPED `dos.productivity.classify`.

v1 was an ARTIFACT and is discarded: an "earliest-ever crossing" fires the instant two
quiet turns appear (~always true near a session start), so it measured "did the run ever
dip" (≈always), not "did the work rate FADE over the horizon". The tell was a median
post-crossing fraction ~0.90 — the trigger landed in the first tenth of every session.

v2 fixes two things:
  1. END-ANCHORED signal. The horizon-keeper's reclaimable spend is the TRAILING run of
     consecutive sub-floor turns — the "still spinning at a low rate right where it
     stopped" tail a stop-when-unproductive gate would cut. Anchored at the session END,
     so early-session noise cannot inflate it. We ALSO report the shipped `classify`'s
     TERMINAL verdict on the trailing window, and require the two to agree (dogfood: the
     kernel verdict says DIMINISHING/STALLED at the end; the tail says how far it ran).
  2. COST vs WORK-RATE split. output_tokens/turn is the work-RATE signal (CC's floor=500
     unit) — the TRIGGER. The reclaimable BURN is priced in TOTAL tokens
     (input + cache_read + cache_creation + output) — the real cost. v1 wrongly priced
     burn in output tokens (a turn with 194 output read 21k cache).

Honesty disciplines (unchanged): sidechain + `<synthetic>` turns excluded; presence-not-
correctness (Wall §3 — this bounds reclaimable SPEND, never certifies the work was right);
a trailing low-rate tail can ALSO be legitimate completion work (final commit / summary),
so the tail spend is an UPPER BOUND on reclaimable — the true test (does the tail predict
a FAILED task?) needs the git-join, named as the follow-up, not claimed here.

Read-only. Emits text + JSON to stdout; writes nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dos.productivity import classify, WorkHistory, ProductivityPolicy, Productivity  # noqa: E402

PROJECTS = Path.home() / ".claude" / "projects"
POLICY = ProductivityPolicy()  # CC defaults: min_steps=3, floor=500 output tokens
HORIZON_FLOORS = [10, 20, 40, 80]
MIN_TAIL = 3  # a "fading tail" must be >= this many consecutive sub-floor turns (a sustained low rate, not one quiet final turn)


def turn_rows(path: Path):
    """Ordered (oldest->newest) per real main-thread model turn:
       (output_tokens, total_tokens, n_tool_use). Skips sidechain + synthetic + malformed."""
    rows = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return rows
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "assistant" or r.get("isSidechain"):
            continue
        msg = r.get("message") or {}
        if not isinstance(msg, dict) or msg.get("model") == "<synthetic>":
            continue
        u = msg.get("usage") or {}
        ot = u.get("output_tokens")
        if ot is None:
            continue
        total = (int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0))
                 + int(u.get("cache_creation_input_tokens", 0)) + int(ot))
        c = msg.get("content") or []
        n_tool = sum(1 for b in c if isinstance(b, dict) and b.get("type") == "tool_use") if isinstance(c, list) else 0
        # Dedup an adjacent double-logged turn: a streaming/retry re-record repeats the SAME
        # (output, total) pair. `total` includes cache_read, which grows monotonically across a
        # session, so two genuinely-distinct turns cannot share a total — an identical adjacent
        # total is the same turn twice. Skip it (else tail lengths inflate ~2x).
        if rows and rows[-1][0] == int(ot) and rows[-1][1] == total:
            continue
        rows.append((int(ot), total, n_tool))
    return rows


def trailing_spin_tail(out_deltas, tool_deltas, floor):
    """Length of the maximal SUFFIX of turns that are 'spinning' — low output AND low tool
    activity (output < floor AND <=1 tool_use). A tool-heavy terse turn is NOT spinning
    (it's doing work with curt narration), so it breaks the tail. End-anchored, so
    early-session noise cannot inflate it. 0 if the final turn is productive."""
    n = 0
    for ot, nt in zip(reversed(out_deltas), reversed(tool_deltas)):
        if ot < floor and nt <= 1:
            n += 1
        else:
            break
    return n


def terminal_verdict(out_deltas, policy, window=6):
    """The SHIPPED classify run on the trailing `window` turns — the kernel's own verdict
    about the END of the run (does it call the tail DIMINISHING/STALLED?)."""
    tail = out_deltas[-window:] if len(out_deltas) >= window else out_deltas
    return classify(WorkHistory.of(tail), policy).verdict


def analyze(sessions, policy, examples_sink=None):
    """A session 'FADED over the horizon' iff:
       (1) it has a spinning tail of >= MIN_TAIL turns (low-output AND low-tool at the end), AND
       (2) it had a PRODUCTIVE PREFIX — at least one supra-floor turn BEFORE that tail
           (it was working, then faded). Guard (2) excludes uniformly-quiet short sessions
           (the v2 confound where the tail was ~the whole session)."""
    per = {}
    for floor in HORIZON_FLOORS:
        elig = [s for s in sessions if len(s[0]) >= floor]
        n = len(elig)
        faded = 0
        term_dim = 0
        both = 0
        tail_lens = []
        reclaim_fracs = []
        reclaim_abs = []
        grabbed = 0
        agg_tail_tokens = 0       # total tokens in flagged spinning tails (numerator of the POOL)
        agg_all_tokens = 0        # total tokens across ALL eligible sessions (denominator of the POOL)
        for (out, tot, tool) in elig:
            agg_all_tokens += sum(tot)
            tlen = trailing_spin_tail(out, tool, policy.floor)
            tv = terminal_verdict(out, policy)
            is_term = tv in (Productivity.DIMINISHING, Productivity.STALLED)
            if is_term:
                term_dim += 1
            # productive-prefix guard: some turn before the tail cleared the floor
            prefix = out[:len(out) - tlen] if tlen else out
            had_productive_prefix = any(o >= policy.floor for o in prefix)
            is_faded = tlen >= MIN_TAIL and had_productive_prefix
            if is_faded:
                faded += 1
                tail_lens.append(tlen)
                tail_total = sum(tot[-tlen:])
                sess_total = sum(tot) or 1
                reclaim_fracs.append(tail_total / sess_total)
                reclaim_abs.append(tail_total)
                agg_tail_tokens += tail_total
                if is_term:
                    both += 1
                # grab a few mid-range examples to HAND-verify the tail looks like spinning
                if examples_sink is not None and floor == 40 and grabbed < 4 and 5 <= tlen <= 30:
                    examples_sink.append({
                        "session_turns": len(out),
                        "tail_len": tlen,
                        "reclaimable_frac": round(tail_total / sess_total, 3),
                        "tail_output_tokens_per_turn": out[-tlen:],
                        "tail_tool_calls_per_turn": tool[-tlen:],
                        "prefix_max_output": max(prefix) if prefix else None,
                    })
                    grabbed += 1
        per[floor] = {
            "eligible": n,
            "faded": faded,
            "faded_pct": _r(100 * faded / n) if n else None,
            "terminal_verdict_diminishing": term_dim,
            "terminal_pct": _r(100 * term_dim / n) if n else None,
            "faded_and_terminal_agree": both,
            "median_tail_len": _med(tail_lens),
            "p90_tail_len": _pct(tail_lens, 90),
            "median_reclaimable_frac": _med(reclaim_fracs),
            "p90_reclaimable_frac": _pct(reclaim_fracs, 90),
            "median_reclaimable_tokens": _med(reclaim_abs),
            "p90_reclaimable_tokens": _pct(reclaim_abs, 90),
            # the POOL: tokens in flagged tails / ALL tokens across eligible sessions —
            # the aggregate reclaimable-spend ceiling (sizes the prize; the per-session
            # medians don't). Still a rate + an UPPER BOUND, not payoff.
            "pool_tail_tokens": agg_tail_tokens,
            "pool_all_tokens": agg_all_tokens,
            "pool_reclaimable_pct": _r(100 * agg_tail_tokens / agg_all_tokens) if agg_all_tokens else None,
        }
    return per


def _r(x):
    return round(x, 1) if x is not None else None


def _med(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return round(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2, 4)


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return round(s[k], 4)


def main():
    files = sorted(PROJECTS.rglob("*.jsonl"))
    sessions = []
    empty = 0
    for f in files:
        rows = turn_rows(f)
        if not rows:
            empty += 1
            continue
        out = [r[0] for r in rows]
        tot = [r[1] for r in rows]
        tool = [r[2] for r in rows]
        sessions.append((out, tot, tool))

    counts = [len(s[0]) for s in sessions]
    examples = []
    report = {
        "corpus": {
            "jsonl_files": len(files),
            "sessions_with_real_turns": len(sessions),
            "skipped_no_real_turns": empty,
            "total_real_turns": sum(counts),
            "turns_median": _med(counts),
            "turns_p90": _pct(counts, 90),
            "turns_max": max(counts) if counts else 0,
        },
        "policy": {"min_steps": POLICY.min_steps, "floor_output_tokens": POLICY.floor, "min_tail": MIN_TAIL},
        "by_horizon": analyze(sessions, POLICY, examples_sink=examples),
        "examples_faded_tails": examples,
    }

    print("=" * 92)
    print("N-AXIS PROBE v2 — horizon-keeper reclaimable spend over the REAL k=1 session corpus")
    print("=" * 92)
    c = report["corpus"]
    print(f"corpus: {c['jsonl_files']} jsonl -> {c['sessions_with_real_turns']} sessions w/ real main-thread turns "
          f"({c['skipped_no_real_turns']} had none) | {c['total_real_turns']} turns | "
          f"per-session median {c['turns_median']}, p90 {c['turns_p90']}, max {c['turns_max']}")
    print(f"signal: TRIGGER = output_tokens/turn < {POLICY.floor} (CC unit); a 'fading tail' = >= {MIN_TAIL} "
          f"consecutive sub-floor turns at the END; BURN priced in TOTAL tokens (in+cache+out).")
    print()
    print(f"{'horizon>=':>9} {'elig':>6} {'faded':>6} {'faded%':>7} {'term-DIM%':>10} {'agree':>6} "
          f"{'medTail':>8} {'p90Tail':>8} {'medReclaim%':>12} {'p90Reclaim%':>12} {'POOL%':>7}")
    for fl in HORIZON_FLOORS:
        s = report["by_horizon"][fl]
        mf = s["median_reclaimable_frac"]
        pf = s["p90_reclaimable_frac"]
        print(f"{fl:>9} {s['eligible']:>6} {s['faded']:>6} "
              f"{str(s['faded_pct']):>7} {str(s['terminal_pct']):>10} {s['faded_and_terminal_agree']:>6} "
              f"{str(s['median_tail_len']):>8} {str(s['p90_tail_len']):>8} "
              f"{str(round(mf*100,1) if mf is not None else None):>12} "
              f"{str(round(pf*100,1) if pf is not None else None):>12} "
              f"{str(s['pool_reclaimable_pct']):>7}")
    print()
    print("POOL% = tokens in flagged spinning tails / ALL tokens across eligible sessions —")
    print("        the aggregate reclaimable ceiling (sizes the prize; still a rate + upper bound).")
    print()
    print(f"read: faded = sessions that had a productive PREFIX then ended in a spinning tail of >={MIN_TAIL}")
    print("        turns (low-output AND <=1 tool-use). term-DIM = the SHIPPED classify's verdict on the")
    print("        trailing window is DIMINISHING/STALLED (dogfood cross-check; 'agree' = both fire).")
    print("      medReclaim% = median fraction of TOTAL session tokens (in+cache+out) spent in that tail —")
    print("        an UPPER BOUND on what a stop-when-unproductive gate could reclaim (a tail may be")
    print("        legitimate completion work; the failed-task split needs the git-join, the follow-up).")
    print()
    print("--- example faded tails (horizon>=40) to HAND-VERIFY the tail is spinning, not working ---")
    for ex in report["examples_faded_tails"]:
        print(f"  session {ex['session_turns']} turns | tail {ex['tail_len']} turns = "
              f"{int(ex['reclaimable_frac']*100)}% of spend | prefix peak output {ex['prefix_max_output']}")
        print(f"    tail output/turn: {ex['tail_output_tokens_per_turn']}")
        print(f"    tail tools/turn:  {ex['tail_tool_calls_per_turn']}")
    print()
    print("JSON_BEGIN")
    print(json.dumps(report))
    print("JSON_END")


if __name__ == "__main__":
    main()
