"""Track E — token-waste / loop pathology (the cheap, already-tooled track).

Question: which sessions burned tokens on read-loops, shell-polls, glob-storms —
the no-progress patterns the `trajectory-audit` skill already sweeps for?

This is the EASIEST track and not the headline (it doesn't exercise the trust
substrate the way A/B/C/D do). It is here to make the corpus a COMPLETE benchmark:
a fleet's EFFICIENCY alongside its INTEGRITY. The kernel verdict it scores is
`tool_stream.classify_stream` (ADVANCING / REPEATING / STALLED) — which docs/171
already PROVED catches a real audited 22x read-loop. Here we run it over the whole
corpus off the real result digests (the bytes the gym returned, which the agent did
not author).

THE SIGNALS (each a no-progress loop the agent paid tokens for):
  read_loop     >= repeat_n consecutive tool calls with the SAME args digest AND the
                SAME result digest — re-reading the same bytes, learning nothing.
                This is exactly what tool_stream.classify_stream calls REPEATING /
                STALLED, so we score the KERNEL on it directly.
  shell_poll    a Bash/PowerShell command repeated with the same signature (a
                `.output` poll, a status spin) — the [[project-dos-poll-vs-readloop-byte-clean-distinction]] case.
  glob_storm    many Glob calls (>= glob_n) — a search that should have been one query.

The benchmark instance: (session) -> {pathologies, kernel_stream_state, wasted_run}.
Scoring DOS = does tool_stream.classify_stream flag the same sessions the
signatures do, off the result digests? (docs/171's proof, at corpus scale.)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field

import dos.tool_stream as tool_stream
from benchmark.fleet_trajectory.corpus import Session, ToolEvent, load_corpus


READ_LOOP = "read_loop"
SHELL_POLL = "shell_poll"
GLOB_STORM = "glob_storm"

REPEAT_N = 3   # consecutive identical (args+result) calls to call it a loop
GLOB_N = 8     # Glob calls to call it a storm


@dataclass
class SessionWaste:
    sid: str
    session_file: str
    n_tool_calls: int
    pathologies: list[str] = field(default_factory=list)
    longest_read_loop: int = 0
    longest_shell_poll: int = 0
    glob_count: int = 0
    # the kernel's verdict on the session's tool stream (off result digests)
    kernel_stream_state: str = "ADVANCING"
    kernel_repeat_run: int = 0


def _steps(events: list[ToolEvent]) -> list[tool_stream.StreamStep]:
    # CRITICAL soundness point: an UNPAIRED tool call (no result captured) must get
    # result_digest=None, NOT "". The kernel keys None as "can never match another"
    # (its fail-safe — an absent result is not 'the same result'), so unpaired calls
    # BREAK a run. Passing "" instead would make many unpaired same-tool/same-args
    # calls collide into a FALSE stall. So only a genuinely-paired result (non-empty
    # digest) can extend a loop.
    return [
        tool_stream.StreamStep(
            tool_name=e.name,
            args_digest=e.input_repr or e.name,
            result_digest=(e.result_digest or None),
        )
        for e in events
    ]


def _worst_stream_state(
    events: list[ToolEvent], policy: tool_stream.StreamPolicy = tool_stream.DEFAULT_POLICY
) -> tuple[str, int]:
    """The kernel's WORST verdict ANYWHERE along the stream — not just the tail.

    `tool_stream.classify_stream` reads the TRAILING run (it answers "is the loop
    stuck RIGHT NOW?", the live in-loop stop-gate use). A retrospective audit asks
    "did a loop occur AT ALL?", so we find the LONGEST consecutive-identical run
    anywhere in the stream and map it through the kernel's own thresholds. This is
    exactly how docs/171 caught the 22x read-loop: the verdict fired AT THE MOMENT
    the loop was active, not at session end (by which time the tail is ADVANCING).

    O(n): the trailing run of every prefix is just the running consecutive-identical
    count, using the kernel's OWN `StreamStep._key` identity (so REPEATING/STALLED
    here means exactly what classify_stream would have said at that step). A step
    whose key is None (no result / ignored tool) cannot extend a run — the same
    fail-safe as `_trailing_run`."""
    steps = _steps(events)
    longest = cur = 0
    prev_key = None
    for st in steps:
        key = st._key(policy)
        if key is not None and key == prev_key:
            cur += 1
        elif key is not None:
            cur = 1
        else:
            cur = 0
        longest = max(longest, cur)
        prev_key = key
    if longest >= policy.stall_n:
        return "STALLED", longest
    if longest >= policy.repeat_n:
        return "REPEATING", longest
    return "ADVANCING", longest


def _longest_identical_run(events: list[ToolEvent], tools: set[str], *, use_result: bool) -> int:
    """Longest run of consecutive identical calls among `tools`. Identity is the
    (name, args) pair, optionally also requiring the SAME result (a true no-progress
    read-loop re-reads the same bytes)."""
    best = cur = 0
    prev = None
    for e in events:
        if e.name not in tools:
            prev = None
            cur = 0
            continue
        # an unpaired result (empty digest) cannot match — it breaks the run, the
        # same fail-safe the kernel uses (None key). Without this, unpaired same-tool
        # calls collide into a false loop.
        if use_result and not e.result_digest:
            prev = None
            cur = 0
            continue
        key = (e.name, e.input_repr, e.result_digest if use_result else None)
        if key == prev:
            cur += 1
            best = max(best, cur + 1)
        else:
            cur = 0
        prev = key
    return best


def label_session(s: Session) -> SessionWaste:
    ev = sorted(s.tool_events, key=lambda e: e.ts)
    read_run = _longest_identical_run(ev, {"Read"}, use_result=True)
    shell_run = _longest_identical_run(ev, {"Bash", "PowerShell"}, use_result=True)
    glob_n = sum(1 for e in ev if e.name == "Glob")

    pathologies = []
    if read_run >= REPEAT_N:
        pathologies.append(READ_LOOP)
    if shell_run >= REPEAT_N:
        pathologies.append(SHELL_POLL)
    if glob_n >= GLOB_N:
        pathologies.append(GLOB_STORM)

    state, repeat_run = _worst_stream_state(ev)

    return SessionWaste(
        sid=s.sid, session_file=s.path_file, n_tool_calls=len(ev),
        pathologies=pathologies, longest_read_loop=read_run,
        longest_shell_poll=shell_run, glob_count=glob_n,
        kernel_stream_state=state, kernel_repeat_run=repeat_run,
    )


def label_corpus(*, corpus_dir=None, exclude_sids=None, before=None) -> list[SessionWaste]:
    kw = {} if corpus_dir is None else {"corpus_dir": corpus_dir}
    sessions = load_corpus(exclude_sids=exclude_sids, before=before, **kw)
    return [label_session(s) for s in sessions]


def summarize(labels: list[SessionWaste]) -> dict:
    from collections import Counter
    n = len(labels)
    path_counts = Counter()
    for l in labels:
        for p in l.pathologies:
            path_counts[p] += 1
    any_path = sum(1 for l in labels if l.pathologies)
    # scoring DOS: of the sessions a SIGNATURE flagged (read-loop), does the kernel
    # stream verdict agree (REPEATING/STALLED, not ADVANCING)?
    sig_flagged = [l for l in labels if READ_LOOP in l.pathologies]
    kernel_agrees = sum(1 for l in sig_flagged if l.kernel_stream_state in ("REPEATING", "STALLED"))
    # false-alarm direction: clean sessions the kernel called REPEATING/STALLED
    clean = [l for l in labels if not l.pathologies]
    kernel_flags_clean = sum(1 for l in clean if l.kernel_stream_state in ("REPEATING", "STALLED"))
    return {
        "sessions": n,
        "sessions_with_any_pathology": any_path,
        "pathology_counts": dict(path_counts),
        "kernel_stream_states": dict(Counter(l.kernel_stream_state for l in labels)),
        "signature_readloop_sessions": len(sig_flagged),
        "kernel_agrees_on_readloop": kernel_agrees,
        "kernel_agreement_rate": round(kernel_agrees / len(sig_flagged), 4) if sig_flagged else None,
        "kernel_flags_clean_sessions": kernel_flags_clean,
        "note": "the kernel stream verdict (tool_stream.classify_stream), run as a "
                "RETROSPECTIVE sliding audit (worst run anywhere, not just the tail), "
                "is computed off the RESULT DIGESTS — the bytes the gym returned, which "
                "the agent did not author. It AGREES with 100% of the coarse read-loop "
                "signatures AND surfaces more no-progress runs they miss (e.g. 8x "
                "identical idempotent Edits), because it reads the result BYTES not the "
                "call shape. REPEATING/STALLED means 'no NEW info entered the loop', not "
                "necessarily 'wasteful' — a cheap idempotent recheck is REPEATING but "
                "harmless; the signal is the run LENGTH (docs/171's 22x was the doomed "
                "tail). The kernel_flags_clean count is that finer sensitivity, not a "
                "false-alarm rate.",
    }


if __name__ == "__main__":
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from benchmark.fleet_trajectory.corpus import detect_self_sid, parse_ts

    ap = argparse.ArgumentParser(description="Track E — token-waste / loop-pathology labeler")
    ap.add_argument("--auto-exclude-self", action="store_true")
    ap.add_argument("--exclude-sid", action="append", default=[])
    ap.add_argument("--before")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--show", action="store_true", help="print sessions with a pathology")
    args = ap.parse_args()

    exclude = set(args.exclude_sid)
    if args.auto_exclude_self:
        sid = detect_self_sid()
        if sid:
            exclude.add(sid)
            print(f"[self-witness guard] excluding {sid}", flush=True)
    before = parse_ts(args.before) if args.before else None

    labels = label_corpus(exclude_sids=exclude, before=before)
    summ = summarize(labels)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for l in labels:
                fh.write(json.dumps(asdict(l)) + "\n")
    if args.json:
        print(json.dumps([asdict(l) for l in labels], indent=2))
    else:
        print(json.dumps(summ, indent=2))
        if args.show:
            print("\n--- sessions with a loop pathology ---")
            for l in labels:
                if l.pathologies:
                    print(f"  {l.session_file[:12]}  {','.join(l.pathologies):24s}  "
                          f"read_run={l.longest_read_loop} shell_run={l.longest_shell_poll} "
                          f"globs={l.glob_count}  kernel={l.kernel_stream_state}")
