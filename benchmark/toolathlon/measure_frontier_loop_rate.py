"""measure_frontier_loop_rate.py — $0 offline measurement of the rank-1 kill-criterion.

docs/170 / the conversion-gap synthesis. The single load-bearing uncertainty under the two
top value-capture bets is: *does a FRONTIER model loop on identical (tool, args, result)
triples often enough for the proven-positive WARN re-surface rung to bank value, or is the
strong-model null (p_stuck=0.0%) the whole story?*

This script ANSWERS it on a real corpus — the operator's own Claude Code session
transcripts (`~/.claude/projects/<ws>/*.jsonl`), which are Opus-4.x / frontier-model
trajectories, not a weak gym model. It does so using the EXACT live-hook logic, no
re-implementation:

  * `posttool_sensor.step_from_event` — the real PostToolUse adapter (agent-authored
    args_digest + ENV-authored result_digest, the byte-clean §5a key).
  * `tool_stream.classify_stream`     — the real pure verdict (ADVANCING/REPEATING/STALLED).

Each transcript is parsed into ordered (tool_name, tool_input, tool_result) triples joined by
`tool_use_id` (the CC format: assistant.message.content[] tool_use blocks, user.message
.content[] tool_result blocks). Each triple is shaped into the SAME PostToolUse event dict the
live hook receives ({tool_name, tool_input, tool_response}) and fed through the real adapter +
verdict, accumulating per session exactly as the live `.dos/streams/<sid>.jsonl` accumulator
would. We record the verdict after EVERY step, so the reported fire is byte-identical to what
`dos hook posttool` would have emitted live.

The kill-criterion distinction (the synthesis's third caveat): a REPEATING/STALLED fire is only
a *reasoning-failure* win if it is NOT dominated by harness-driven background-task polling (the
2cd77e93 `.output`-poll class). So we CLASSIFY every fire: poll-ish tools (reading a
background-task .output, sleeping, waiting) vs substantive tools (a real re-issued read/search/
edit the model kept failing to use). Both numbers are reported; neither is hidden.

Pure replay of recorded JSON — no model calls, no network, no benchmark access. $0.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_DOS_SRC = os.path.join(_HERE, "..", "..", "src")
if os.path.isdir(_DOS_SRC):
    sys.path.insert(0, _DOS_SRC)

# the REAL live-hook logic — no re-implementation (the rewind_counterfactual "use the real
# logic" rule). step_from_event is the exact PostToolUse adapter; classify_stream the verdict.
from dos.posttool_sensor import step_from_event  # noqa: E402
from dos.tool_stream import ToolStream, StreamPolicy, StreamState, classify_stream  # noqa: E402

# A poll-ish fire is harness ergonomics, not a frontier reasoning loop (the kill-criterion
# distinction). We classify a fire as poll-ish if the repeated tool + its args look like a
# background-task / async-write wait. Heuristic over AGENT-authored args (a triage label, not a
# verdict input) — the verdict itself never reads this.
_POLL_TOOL_HINTS = ("sleep", "wait", "monitor")
_POLL_ARG_HINTS = (".output", "tasks/", "background", "run_in_background", "/tmp/claude")


def _is_pollish(tool_name: str, tool_input: dict) -> bool:
    tn = (tool_name or "").lower()
    if any(h in tn for h in _POLL_TOOL_HINTS):
        return True
    blob = json.dumps(tool_input, default=str).lower()
    return any(h in blob for h in _POLL_ARG_HINTS)


def _iter_tool_pairs(path: str):
    """Yield (tool_name, tool_input, tool_response, is_error) in call order for one transcript.

    Joins assistant tool_use blocks to user tool_result blocks by tool_use_id, emitting in the
    order the tool_use appeared (call order — what the live stream sees)."""
    uses = []  # ordered list of (id, name, input)
    results = {}  # tool_use_id -> (content, is_error)
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            msg = o.get("message") or {}
            content = msg.get("content")
            if t == "assistant" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        uses.append((b.get("id"), b.get("name"), b.get("input") or {}))
            elif t == "user" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results[b.get("tool_use_id")] = (
                            b.get("content"),
                            bool(b.get("is_error")),
                        )
    for tid, name, inp in uses:
        if not name:
            continue
        resp, is_err = results.get(tid, (None, False))
        yield name, inp, resp, is_err


def _result_bytes(resp):
    """The env-authored result content as the posttool sensor would see it.

    CC tool_result.content is a str OR a list of {type:text,text:...} blocks. Normalize to the
    text the env produced (the bytes the model received) — matching what a live PostToolUse
    `tool_response` carries."""
    if resp is None:
        return None
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        parts = []
        for b in resp:
            if isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or json.dumps(b, default=str))
            else:
                parts.append(str(b))
        return "\n".join(parts)
    return json.dumps(resp, default=str)


def analyze_session(path: str, policy: StreamPolicy) -> dict | None:
    """Replay one transcript through the real adapter+verdict. None if it had no tool calls."""
    steps = []
    fire = None  # the first REPEATING/STALLED verdict + its context
    peak_state = StreamState.ADVANCING
    peak_run = 1
    n_calls = 0
    last_pair = None
    for name, inp, resp, is_err in _iter_tool_pairs(path):
        n_calls += 1
        # Shape the SAME PostToolUse event the live hook receives. is_error → no result key,
        # so step_from_event maps it to result_digest=None (the fail-safe break) — matching the
        # live posttool contract that an errored call carries no comparable result.
        event = {"tool_name": name, "tool_input": inp}
        rb = None if is_err else _result_bytes(resp)
        if rb is not None:
            event["tool_response"] = rb
        step = step_from_event(event)
        if step is None:
            continue
        steps.append(step)
        v = classify_stream(ToolStream(tuple(steps)), policy)
        if v.repeat_run > peak_run:
            peak_run = v.repeat_run
            peak_state = v.state
        elif v.state == StreamState.STALLED and peak_state != StreamState.STALLED:
            peak_state = v.state
        if v.state in (StreamState.REPEATING, StreamState.STALLED) and fire is None:
            rs = v.repeated_step
            fire = {
                "state": v.state.value,
                "repeat_run": v.repeat_run,
                "tool": rs.tool_name if rs else name,
                "step_index": len(steps),
                "pollish": _is_pollish(name, inp),
            }
        last_pair = (name, inp)
    if n_calls == 0:
        return None
    # peak across the whole session (the strongest verdict reached at any point)
    return {
        "file": os.path.basename(path),
        "n_tool_calls": n_calls,
        "n_steps": len(steps),
        "peak_state": peak_state.value,
        "peak_run": peak_run,
        "fired": fire is not None,
        "fire": fire,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    default_dir = os.path.expanduser(r"~/.claude/projects/<project>")
    ap.add_argument("--dir", default=default_dir, help="a CC project transcript dir (*.jsonl)")
    ap.add_argument("--recursive", action="store_true",
                    help="also include sub-agent/workflow transcripts (**/*.jsonl) — the FULL fleet")
    ap.add_argument("--repeat-n", type=int, default=3)
    ap.add_argument("--stall-n", type=int, default=5)
    ap.add_argument("--min-calls", type=int, default=1,
                    help="ignore sessions with fewer than this many tool calls")
    ap.add_argument("--ignore-tools", default="",
                    help="comma list of poller tools to exempt from the verdict (e.g. Bash)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-fires", action="store_true", help="print every fired session")
    args = ap.parse_args(argv)

    ignore = frozenset(t.strip() for t in args.ignore_tools.split(",") if t.strip())
    policy = StreamPolicy(repeat_n=args.repeat_n, stall_n=args.stall_n, ignore_tools=ignore)

    if args.recursive:
        files = sorted(f for f in glob.glob(os.path.join(args.dir, "**", "*.jsonl"), recursive=True)
                       if os.path.basename(f) != "journal.jsonl")  # journal.jsonl is the WAL, not a transcript
    else:
        files = sorted(glob.glob(os.path.join(args.dir, "*.jsonl")))
    sessions = []
    for f in files:
        r = analyze_session(f, policy)
        if r is not None and r["n_tool_calls"] >= args.min_calls:
            sessions.append(r)

    fired = [s for s in sessions if s["fired"]]
    stalled = [s for s in sessions if s["peak_state"] == StreamState.STALLED.value]
    pollish_fires = [s for s in fired if s["fire"] and s["fire"]["pollish"]]
    substantive_fires = [s for s in fired if s["fire"] and not s["fire"]["pollish"]]
    fire_tools = Counter(s["fire"]["tool"] for s in fired if s["fire"])

    summary = {
        "as_of": "2026-06-06",
        "dir": args.dir,
        "policy": {"repeat_n": args.repeat_n, "stall_n": args.stall_n,
                   "ignore_tools": sorted(ignore)},
        "n_session_files": len(files),
        "n_sessions_with_tools": len(sessions),
        "n_sessions_fired": len(fired),
        "fire_rate_pct": round(100.0 * len(fired) / len(sessions), 1) if sessions else 0.0,
        "n_sessions_stalled": len(stalled),
        "stall_rate_pct": round(100.0 * len(stalled) / len(sessions), 1) if sessions else 0.0,
        "fires_pollish": len(pollish_fires),
        "fires_substantive": len(substantive_fires),
        "substantive_fire_rate_pct": round(100.0 * len(substantive_fires) / len(sessions), 1) if sessions else 0.0,
        "top_fire_tools": fire_tools.most_common(10),
        "median_calls_per_session": sorted(s["n_tool_calls"] for s in sessions)[len(sessions)//2] if sessions else 0,
        "max_calls_in_a_session": max((s["n_tool_calls"] for s in sessions), default=0),
    }

    if args.json:
        print(json.dumps({"summary": summary, "fired_sessions": fired if args.show_fires else None}, indent=2))
        return

    print("=== FRONTIER loop-rate on REAL Claude Code transcripts (real tool_stream verdict, 2026-06-06) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    if args.show_fires:
        print("\n=== fired sessions (peak REPEATING/STALLED) ===")
        for s in sorted(fired, key=lambda x: -x["peak_run"]):
            fr = s["fire"]
            kind = "POLL" if fr and fr["pollish"] else "SUBSTANTIVE"
            print(f"  {s['file'][:18]}  peak={s['peak_state']:9} run={s['peak_run']:>2}  "
                  f"calls={s['n_tool_calls']:>4}  first-fire={fr['state']}@{fr['tool']} [{kind}]")


if __name__ == "__main__":
    main()
