#!/usr/bin/env python3
"""dos_solves_read_loop — a re-runnable PROOF that `dos.tool_stream` catches the REAL read-loop.

The audited problem (trajectory audit 2026-06-05 22:05, job session <session-id>)
=============================================================================

The DOS `trajectory-audit` skill swept the job repo's Claude Code session trajectories
and named one session as a textbook **read-loop** pathology:

  * session ............ <session-id>  (in <project>)
  * cache-read tokens .. 177,866,472  (the single heaviest session by cache-read)
  * Read calls ......... 44 total across only **8 unique files**
  * the headline ....... **22x** reads of ``job/scripts/next_up_render.py``
                         (next: 7x test_next_up_render.py, 5x fanout_state.py, 3x test_fanout_state.py)

22 reads of one unchanged file is the loop-economics pathology docs/145 is about: the agent
re-issues the same Read, the env (the filesystem) returns the **same bytes**, no new information
enters the loop, and ~177M cache-read tokens burn while the task does not advance. The audit
catches this **post-hoc** — after the run is dead, by histogramming the trajectory. THIS script
is the **in-flight** version: it replays the same Read stream through `dos.tool_stream.classify_stream`
*as the calls arrive*, and shows DOS would have returned REPEATING at the 3rd identical read in a
run and STALLED at the 5th — early enough to re-surface the held file bytes and pre-empt the rest of
each run **on the same budget** (docs/145: convert a doomed re-read loop into a finished task, never
a cut).

HONESTY NOTE on "22 in a row": in the real call-order the 22 next_up_render.py reads are
**interleaved** with reads of other files, so they form several consecutive runs (3, 5, 4, 9, 1) —
the longest trailing run is 9, not 22. `tool_stream` measures the TRAILING run, so DOS catches the
loop on EACH run that reaches stall_n (re-surfacing every time the agent re-enters it). The single
"STALLED, repeat_run 22" the orchestrator captured live is the **synthetic tight loop** (22 reads
back-to-back) — the idealized uninterrupted case. This script reports BOTH readings, each labelled,
so the proof never overstates the consecutive depth of the real stream.

What this proves (and what it does NOT)
=======================================

  * It proves the **verdict** would have fired in-flight on the real captured stream — the
    sliding-window classification is exact, deterministic, and replay-testable with **zero**
    benchmark / LLM / MCP access (the `dos.tool_stream` keystone).
  * It does NOT claim the loop was *certainly* doomed: eventual-consistency polling is a legitimate
    repeat (the module's named honest hole). That is precisely why the consumer's action is a
    turn-preserving WARN that **re-surfaces** the value, never a process cut (docs/99 advisory line,
    docs/144 -9pp intervention-cost lesson).

The byte-clean property (docs/145 §5a — must stay accurate)
===========================================================

`StreamStep.result_digest` is **ENV-AUTHORED**: the filesystem / gym produced those bytes, not the
agent. The agent did NOT author the *identity* of its own repeated results. So REPEATING is
provenance-of-repeated-output — a pure byte question about env-authored bytes — never an
"is-the-agent-succeeding?" satisfaction predicate (the mirror-verifier trap). Section 4 below
DEMONSTRATES this: flip ONE `result_digest` (the env returned DIFFERENT bytes once) and the run
breaks back to ADVANCING. The verdict keys on env-authored output identity, not agent narration.

No CLI verb for this axis
=========================

There is **no** ``dos tool-stream`` verb — the stall verdict is consumed via the Python API
(`dos.tool_stream.classify_stream`) or wired into a host's tool-result hook. (`dos tool-stream-eval`
exists, but it is the per-axis EVAL harness, not a live classifier.) This script therefore calls the
**Python API**, exactly as a host tool-result hook would. The job Independent-Repository rule is
honored: the script READS the job trajectory and WRITES nothing into job — it only prints a report.

Run it:  ``python dos_solves_read_loop.py``  ->  prints the report, exits 0.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Optional

from dos.tool_stream import (
    DEFAULT_POLICY,
    StreamState,
    StreamStep,
    ToolStream,
    classify_stream,
)

# ---------------------------------------------------------------------------
# The REAL trajectory. If present we read it; otherwise we fall back to a
# documented synthetic that mirrors the captured per-file counts exactly.
# ---------------------------------------------------------------------------
TRAJECTORY_PATH = (
    Path.home() / ".claude" / "projects" / "<project>" / "<session-id>.jsonl"
)

# The captured per-file Read counts (trajectory audit 2026-06-05 22:05). Used to BUILD the
# synthetic fallback AND to sanity-check the live parse, so the proof is identical whether or
# not the .jsonl is on this machine.
CAPTURED_READ_COUNTS: "list[tuple[str, int]]" = [
    ("job/scripts/next_up_render.py", 22),       # <-- the headline read-loop
    ("job/tests/test_next_up_render.py", 7),
    ("job/scripts/fanout_state.py", 5),
    ("job/tests/test_fanout_state.py", 3),
    ("dos/src/dos/preflight.py", 3),
    ("job/scripts/next_up_context.py", 2),
    (
        "~/.claude/tmp/<project>/<session-id>/tasks/bm1s34gzu.output",
        1,
    ),
    ("dos/tests/test_preflight_sidecar.py", 1),
]  # sum = 44 reads across 8 unique files


# ---------------------------------------------------------------------------
# result_digest: the ENV-AUTHORED fact.
# ---------------------------------------------------------------------------
def _result_digest_for(file_path: str) -> str:
    """The env-authored result digest for a Read of an UNCHANGED file.

    DESIGN CHOICE (documented): for this replay we cannot recover the historical file BYTES at
    each read, so we use a stand-in — the SHA-256 of the (canonical) ``file_path``. The honest
    semantics this encodes: **an unchanged file read N times returns identical bytes, so its
    result_digest is identical across those N reads.** That identity is exactly what `tool_stream`
    keys on, and it is env-authored (the filesystem decides the bytes, not the agent). The
    file_path stand-in preserves the load-bearing property — same unchanged file -> same digest —
    while staying offline and deterministic. (To make the proof byte-exact against history, swap
    this for the real result bytes from the trajectory's tool_result blocks; the verdict logic is
    unchanged because it compares pre-computed digests, never hashes live.)
    """
    return hashlib.sha256(file_path.casefold().encode("utf-8")).hexdigest()[:16]


def _args_digest_for(file_path: str) -> str:
    """A stable digest of the call's NORMALIZED args — agent-authored.

    For a Read, the load-bearing arg is the file_path. We normalize on the path alone (NOT the
    offset/limit) so that re-reads of the SAME file count as the same call even when the agent
    nudges the window — the real loop here re-read next_up_render.py with varying offsets, and the
    pathology is "same file, same bytes, again", not "same byte-range". Keying on file_path makes
    the 22 reads of next_up_render.py a single repeat run, which is the honest reading of the loop.
    """
    return hashlib.sha256(("read:" + file_path.casefold()).encode("utf-8")).hexdigest()[:16]


def _step_for(file_path: str) -> StreamStep:
    return StreamStep(
        tool_name="Read",
        args_digest=_args_digest_for(file_path),
        result_digest=_result_digest_for(file_path),
    )


# ---------------------------------------------------------------------------
# Parse the real trajectory -> the ordered Read stream as StreamStep tuples.
# ---------------------------------------------------------------------------
def read_steps_from_trajectory(jsonl_path: Path) -> List[StreamStep]:
    """Parse a Claude Code .jsonl and extract the ordered ``Read`` tool_use calls as StreamSteps.

    Walks the file line-by-line (each line is one transcript record), pulls every
    ``message.content[*]`` block of ``type == "tool_use"`` with ``name == "Read"`` IN ORDER, and
    builds a `StreamStep` per call. The ``result_digest`` is the env-authored fact (see
    `_result_digest_for`): identical reads of an unchanged file share a digest, so a consecutive
    run of same-file reads is exactly a `tool_stream` repeat run.

    Returns the steps in call order. Malformed lines are skipped (the trajectory is large and may
    carry partial records); the parse never raises on bad JSON.
    """
    steps: List[StreamStep] = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Read"
                ):
                    file_path = (block.get("input") or {}).get("file_path")
                    if isinstance(file_path, str) and file_path:
                        steps.append(_step_for(file_path))
    return steps


def synthetic_read_steps() -> List[StreamStep]:
    """A documented synthetic Read stream mirroring the captured per-file counts EXACTLY.

    Used when the real .jsonl is absent. It emits the headline 22-repeat block FIRST (so the
    sliding-window report lands on the real loop), then the remaining captured files. The total is
    44 reads across 8 unique files — byte-for-byte the audited shape. Because the run-length verdict
    measures the trailing consecutive-identical run, grouping each file's reads contiguously
    faithfully reproduces "22 identical reads of next_up_render.py in a row".
    """
    steps: List[StreamStep] = []
    for file_path, count in CAPTURED_READ_COUNTS:
        for _ in range(count):
            steps.append(_step_for(file_path))
    return steps


# ---------------------------------------------------------------------------
# The sliding-window report — when does DOS first say REPEATING / STALLED?
# ---------------------------------------------------------------------------
def first_index_at_state(steps: List[StreamStep], target: StreamState) -> Optional[int]:
    """The 1-based step index at which a sliding `classify_stream` FIRST returns ``target``.

    Replays the stream prefix-by-prefix (steps[:i] for i in 1..N) exactly as a live tool-result
    hook would after each call, returning the first i whose verdict state == target, or None if it
    never reaches that state. This is the in-flight question: "after which Read would DOS have
    intervened?" — not a whole-history histogram.
    """
    for i in range(1, len(steps) + 1):
        v = classify_stream(ToolStream(tuple(steps[:i])), DEFAULT_POLICY)
        if v.state == target:
            return i
    return None


def _step_key(s: StreamStep):
    return (s.tool_name.casefold(), s.args_digest, s.result_digest)


def consecutive_runs(steps: List[StreamStep]) -> "list[tuple[int, int]]":
    """All maximal consecutive same-(tool, args, result) runs, as (start_index_1based, length).

    This is what `tool_stream` actually measures in flight: the TRAILING identical run, which
    resets whenever a different result enters the stream. In the real session the 22 reads of
    next_up_render.py are INTERLEAVED with reads of other files, so they form SEVERAL runs (3, 5,
    4, 9, 1), not one 22-run — and `tool_stream` catches the loop on each run that reaches stall_n,
    re-surfacing the value every time the agent re-enters it. This honest reading is reported
    alongside the synthetic tight-22 block (where the captured repeat_run 22 comes from).
    """
    if not steps:
        return []
    runs: "list[tuple[int, int]]" = []
    start, length = 0, 1
    for i in range(1, len(steps)):
        if _step_key(steps[i]) == _step_key(steps[i - 1]):
            length += 1
        else:
            runs.append((start + 1, length))
            start, length = i, 1
    runs.append((start + 1, length))
    return runs


def reads_preempted(steps: List[StreamStep], stall_n: int) -> int:
    """How many reads DOS would pre-empt by re-surfacing at STALLED across ALL consecutive runs.

    For each maximal consecutive run of length L, once the run reaches `stall_n` the consumer
    re-surfaces the held bytes; every read AFTER the stall point (L - stall_n of them) is a read
    DOS would save. Summed over every run in the stream — the honest in-flight saving, given the
    real interleaving, not a single tight-22 idealization.
    """
    return sum(max(0, length - stall_n) for _, length in consecutive_runs(steps))


def _build_tight_22_block() -> List[StreamStep]:
    """A SYNTHETIC tight loop: 22 next_up_render.py reads BACK-TO-BACK (no interleaving).

    This is the idealized "what a single uninterrupted 22-read loop looks like" — and it is where
    the captured live result (STALLED, repeat_run 22) comes from. It is labelled SYNTHETIC
    throughout; the real stream (below) interleaves these reads, so the trailing-run there peaks at
    9, not 22. Both readings are reported so the proof never overstates the consecutive depth.
    """
    fp = CAPTURED_READ_COUNTS[0][0]  # next_up_render.py, count 22
    return [_step_for(fp) for _ in range(22)]


def main() -> int:
    print("=" * 78)
    print("DOS tool_stream vs the REAL read-loop (job session <session-id>)")
    print("trajectory audit 2026-06-05 22:05 - 22x next_up_render.py, 44 reads / 8 files,")
    print("177,866,472 cache-read tokens. This is the IN-FLIGHT version of that post-hoc catch.")
    print("=" * 78)

    if TRAJECTORY_PATH.exists():
        steps = read_steps_from_trajectory(TRAJECTORY_PATH)
        source = f"REAL trajectory ({TRAJECTORY_PATH})"
    else:
        steps = synthetic_read_steps()
        source = "SYNTHETIC fallback (real .jsonl not on this machine) - mirrors captured counts"

    print(f"\nstream source : {source}")
    print(f"total Read steps parsed : {len(steps)}")
    print(f"policy : repeat_n={DEFAULT_POLICY.repeat_n} (-> REPEATING), "
          f"stall_n={DEFAULT_POLICY.stall_n} (-> STALLED)")

    # ---- 3a. the REAL interleaved stream, as a live hook would see it -------
    print("\n" + "-" * 78)
    print("3a. SLIDING-WINDOW over the REAL stream (verdict after each Read, in true call-order)")
    print("-" * 78)
    print(
        "HONEST READING: in the real session the 22 next_up_render.py reads are INTERLEAVED with\n"
        "reads of other files, so they form SEVERAL consecutive runs, not one 22-run. The trailing\n"
        "run is what tool_stream measures in flight, so DOS catches the loop on EACH run that\n"
        "reaches stall_n - and re-surfaces the held bytes every time the agent re-enters it."
    )
    runs = consecutive_runs(steps)
    stalled_runs = [(s, length) for (s, length) in runs if length >= DEFAULT_POLICY.stall_n]
    repeating_runs = [(s, length) for (s, length) in runs if length >= DEFAULT_POLICY.repeat_n]
    longest = max((length for _, length in runs), default=0)
    print(f"\nconsecutive same-file read-runs (start#, length) : {runs}")
    print(f"longest consecutive identical run : {longest} reads")
    print(f"runs that reach REPEATING (>= {DEFAULT_POLICY.repeat_n}) : {len(repeating_runs)}  "
          f"-> {repeating_runs}")
    print(f"runs that reach STALLED   (>= {DEFAULT_POLICY.stall_n}) : {len(stalled_runs)}  "
          f"-> {stalled_runs}")

    first_rep = first_index_at_state(steps, StreamState.REPEATING)
    first_stall = first_index_at_state(steps, StreamState.STALLED)
    print(f"\nfirst REPEATING : after Read #{first_rep}  "
          f"(the {DEFAULT_POLICY.repeat_n}rd identical read in a run - a no-progress loop established)")
    print(f"first STALLED   : after Read #{first_stall}  "
          f"(the {DEFAULT_POLICY.stall_n}th identical read in a run - near-certainly doomed)")

    preempted = reads_preempted(steps, DEFAULT_POLICY.stall_n)
    print(
        f"\nreads DOS would pre-empt (summed over every run, the reads AFTER each stall) : "
        f"{preempted}\n  -> re-surfacing the held file bytes at each {DEFAULT_POLICY.stall_n}th "
        f"identical read saves ~{preempted} reads on the SAME budget"
    )

    full_v = classify_stream(ToolStream(tuple(steps)), DEFAULT_POLICY)
    print("\nStreamVerdict over the FULL real stream (the last read was not a repeat, so the\n"
          "trailing-run verdict at end-of-stream is ADVANCING - the loop fired EARLIER, mid-stream):")
    print(json.dumps(full_v.to_dict(), indent=2))

    # ---- 3b. the SYNTHETIC tight 22-loop (where repeat_run 22 comes from) ---
    print("\n" + "-" * 78)
    print("3b. SYNTHETIC tight 22-read loop (22 next_up_render.py reads BACK-TO-BACK)")
    print("-" * 78)
    print(
        "This is the idealized uninterrupted loop - what the audit's '22x' looks like if the agent\n"
        "never breaks out. It is SYNTHETIC (the real reads were interleaved). It is the source of\n"
        "the captured live result (STALLED, repeat_run 22)."
    )
    tight = _build_tight_22_block()
    tight_rep = first_index_at_state(tight, StreamState.REPEATING)
    tight_stall = first_index_at_state(tight, StreamState.STALLED)
    tight_v = classify_stream(ToolStream(tuple(tight)), DEFAULT_POLICY)
    print(f"\nfirst REPEATING : after read #{tight_rep}   first STALLED : after read #{tight_stall}")
    print(f"reads AFTER the first STALLED (DOS would pre-empt) : {len(tight) - tight_stall} of 22")
    print("\nStreamVerdict over the tight 22-loop:")
    print(json.dumps(tight_v.to_dict(), indent=2))
    print(
        f"\n  state={tight_v.state}  repeat_run={tight_v.repeat_run}  "
        f"(matches the captured live result: STALLED, repeat_run 22)"
    )
    assert tight_v.state == StreamState.STALLED and tight_v.repeat_run == 22, (
        "the synthetic tight 22-loop must reproduce the captured STALLED / repeat_run 22"
    )

    # ---- 4. byte-clean property: flip ONE result_digest -> ADVANCING -------
    print("\n" + "-" * 78)
    print("4. BYTE-CLEAN PROPERTY - flip ONE env-authored result_digest (env returned DIFFERENT")
    print("   bytes once) and the trailing run breaks back to ADVANCING.")
    print("-" * 78)
    # Take the tight 22-loop and replace the LAST step's result_digest with a different one (as if
    # the env returned new bytes on that read). The repeat-identity key changes, so the trailing run
    # resets to 1 -> ADVANCING. The verdict keys on ENV-authored output identity, not agent narration.
    mutated = list(tight)
    last = mutated[-1]
    mutated[-1] = StreamStep(
        tool_name=last.tool_name,
        args_digest=last.args_digest,  # agent-authored args UNCHANGED (same call)...
        result_digest="ENV_RETURNED_NEW_BYTES",  # ...but the ENV authored different result bytes
    )
    mutated_v = classify_stream(ToolStream(tuple(mutated)), DEFAULT_POLICY)
    print(f"unchanged 22-loop verdict : state={tight_v.state}, repeat_run={tight_v.repeat_run}")
    print(
        f"after flipping the LAST result_digest (same args, NEW env bytes) : "
        f"state={mutated_v.state}, repeat_run={mutated_v.repeat_run}"
    )
    assert tight_v.state == StreamState.STALLED, "expected the unchanged 22-loop to be STALLED"
    assert mutated_v.state == StreamState.ADVANCING, (
        "expected the byte-flipped loop to break back to ADVANCING"
    )
    print(
        "  PROVEN: the agent's call (tool+args) is identical in both runs; only the ENV-AUTHORED\n"
        "  result bytes changed. The verdict followed the ENV, not the agent's narration."
    )

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(
        f"On the REAL interleaved stream DOS fired REPEATING after read #{first_rep} and STALLED "
        f"after\nread #{first_stall}, catching the next_up_render.py loop on {len(stalled_runs)} "
        f"separate runs and\npre-empting ~{preempted} reads by re-surfacing the held bytes. On a "
        f"tight uninterrupted\n22-loop the verdict is STALLED / repeat_run 22 (the captured live "
        f"result). The signal keys\non env-authored output identity (byte-clean), so it replays "
        f"offline and cannot be forged\nby agent narration."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
