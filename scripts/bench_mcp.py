#!/usr/bin/env python3
"""bench_mcp.py — the per-tool-call latency harness for the dos-mcp server (docs/275).

Dev tooling that operates ON the package (it builds the real FastMCP server and
times its tool dispatch) — NOT part of the kernel. Lives in scripts/ like the other
benchmark harnesses (the "kernel never imports its own tooling" litmus).

WHAT IT PROVES
--------------
docs/275 made the MCP server fast by (1) running the truth syscall's git-log grep
rung IN-PROCESS instead of spawning a `python -m dos.phase_shipped` child that
re-ran `import dos`, and (2) skipping the per-call `EnvPrint` probe (a `git
rev-parse` subprocess + a platform query) no tool reads. This harness measures the
real per-tool-call wall-clock through the actual server, so the speedup is a
measured fact, not a comment — the dogfood rule (let a witness, not narration,
close a claim) applied to latency.

It reports two things:
  * LATENCY — `time.perf_counter()` around `server.call_tool(...)` for the
    representative tools (verify = git-bound; arbitrate / refuse_reasons =
    pure-verdict), after warmup, distribution over N calls.
  * EQUIVALENCE — the grep rung run in-process vs forced-subprocess
    (DOS_ORACLE_GREP_SUBPROCESS=1) must return BYTE-IDENTICAL verdicts; the
    speedup is only sound because the process boundary was never part of the
    answer. A mismatch is a hard failure (exit 1).

USAGE
-----
    python scripts/bench_mcp.py [--iterations N] [--warmup W] [--workspace PATH] [--json]

`--json` emits a machine-readable record for a docs writeup / a CI ratchet. The
default workspace is this repo (it has real ship-commits for `dos_verify` to find).
Exit code is 0 on success, 1 if the in-process/subprocess equivalence check fails
(the one result that would mean the optimization changed an answer).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _summarize(samples_ms: list[float]) -> dict:
    s = sorted(samples_ms)
    n = len(s)
    return {
        "n": n,
        "min_ms": round(s[0], 2),
        "median_ms": round(statistics.median(s), 2),
        "p90_ms": round(s[min(n - 1, int(n * 0.9))], 2),
        "max_ms": round(s[-1], 2),
        "mean_ms": round(statistics.mean(s), 2),
    }


def _extract(result) -> dict:
    """Pull the tool's returned dict out of a FastMCP call_tool result.

    FastMCP returns a (content, structured) tuple or a CallToolResult depending on
    version; the structured payload is the tool's dict. Fall back to parsing the
    first text content as JSON.
    """
    # (content_blocks, structured_dict) tuple shape
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or (result[0] if isinstance(result, tuple) else None)
    if content:
        text = getattr(content[0], "text", None)
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                pass
    return {}


async def _bench(server, tool: str, args: dict, *, iterations: int, warmup: int) -> dict:
    for _ in range(warmup):
        await server.call_tool(tool, args)
    samples: list[float] = []
    for _ in range(iterations):
        t = time.perf_counter()
        await server.call_tool(tool, args)
        samples.append((time.perf_counter() - t) * 1000.0)
    return _summarize(samples)


def _prove_equivalence(workspace: str) -> tuple[bool, dict]:
    """In-process grep vs forced-subprocess grep must agree — the soundness gate."""
    from dos import config as _config
    from dos import oracle

    cfg = _config.load_workspace_config(workspace, gather_env=False)
    _config.set_active(cfg)
    # Pairs that actually resolve on THIS repo (a real ship + honest negatives).
    pairs = [("docs/82_liveness-oracle-plan", "liveness"),
             ("docs/99_runtime-validation-and-the-actuation-boundary", "halt"),
             ("docs/265_x", "nope-phase")]

    def _run() -> dict:
        out = oracle.default_grep_fallback_batch(list(pairs))
        return {f"{p[0]}|{p[1]}": (v.shipped, v.source, v.sha, v.rung)
                for p, v in ((p, out[p]) for p in pairs if p in out)}

    os.environ.pop("DOS_ORACLE_GREP_SUBPROCESS", None)
    in_proc = _run()
    os.environ["DOS_ORACLE_GREP_SUBPROCESS"] = "1"
    sub_proc = _run()
    os.environ.pop("DOS_ORACLE_GREP_SUBPROCESS", None)
    return in_proc == sub_proc, {"in_process": in_proc, "subprocess": sub_proc}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--workspace", default=str(REPO))
    ap.add_argument("--json", action="store_true", help="emit a machine-readable record")
    args = ap.parse_args(argv)

    try:
        from dos_mcp.server import build_server
    except SystemExit as e:  # the [mcp] extra missing
        print(f"bench_mcp: {e}", file=sys.stderr)
        return 2

    ws = args.workspace

    # 1) Soundness gate FIRST — a speedup that changed an answer is worthless.
    equal, detail = _prove_equivalence(ws)

    # 2) Latency through the REAL server dispatch.
    server = build_server()

    async def _all() -> dict:
        return {
            "dos_verify": await _bench(
                server, "dos_verify",
                {"plan": "docs/82_liveness-oracle-plan", "phase": "liveness",
                 "workspace": ws},
                iterations=args.iterations, warmup=args.warmup),
            "dos_arbitrate": await _bench(
                server, "dos_arbitrate", {"lane": "src", "workspace": ws},
                iterations=args.iterations, warmup=args.warmup),
            "dos_refuse_reasons": await _bench(
                server, "dos_refuse_reasons", {"workspace": ws},
                iterations=args.iterations, warmup=args.warmup),
        }

    latency = asyncio.run(_all())

    record = {
        "workspace": ws,
        "iterations": args.iterations,
        "in_process_equals_subprocess": equal,
        "latency": latency,
    }

    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"dos-mcp per-tool-call latency  (workspace={ws}, N={args.iterations})")
        print(f"  in-process == subprocess verdicts: {'YES' if equal else 'NO — MISMATCH!'}")
        for tool, s in latency.items():
            print(f"  {tool:20s} median {s['median_ms']:7.2f}ms   "
                  f"min {s['min_ms']:7.2f}ms   p90 {s['p90_ms']:7.2f}ms")

    if not equal:
        print("\nFAIL: the in-process grep rung disagreed with the subprocess rung — "
              "the optimization changed a verdict.", file=sys.stderr)
        print(json.dumps(detail, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
