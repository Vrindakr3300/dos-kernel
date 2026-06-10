#!/usr/bin/env python3
"""bench_hook_e2e.py — the END-TO-END hook-latency harness (docs/265).

This is dev tooling that operates ON the package (it spawns the shipped `dos-hook`
binary and the `python -m dos.cli hook` verb and times them) — NOT part of the
kernel. It lives in scripts/ for the same reason the release scripts do (the
"kernel never imports its own tooling" litmus).

WHAT IT PROVES
--------------
docs/125's whole reason-for-being is a performance claim: the per-tool-call hook
hot path pays ~0.3-0.8 s of Python interpreter cold-start on EVERY call, and the
static Go binary erases it (claimed ~10 ms). That claim was asserted in comments and
pinned for CORRECTNESS by the parity corpus, but never MEASURED. The Go micro-
benchmarks (internal/hook/bench_test.go) show the in-PROCESS decision is ~0.16 ms
(disk-I/O-bound, not CPU). So the entire per-call budget is process spawn + ~0.16 ms
— and the headline figure is therefore dominated by INTERPRETER COLD-START, which a
process-boundary measurement is the only honest way to capture.

This harness spawns each decider N times over an IDENTICAL CC PreToolUse event on
stdin, against this real workspace, and reports the wall-clock distribution. It does
NOT trust either decider's self-report; it measures `time.perf_counter()` around the
OS process and checks the two emit BYTE-IDENTICAL stdout (the live parity check at
the boundary).

USAGE
-----
    python scripts/bench_hook_e2e.py [--iterations N] [--warmup W] [--verb pretool]
                                     [--event self_modify|read|disjoint] [--json]

The default (`pretool`, self_modify event, N=50) is the headline number: the cost of
the deny path most users feel the kernel on. `--json` emits a machine-readable record
for the docs writeup / a CI ratchet.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


# The event spectrum — one representative CC PreToolUse event per decision the PRE
# path can reach, so the harness can measure the deny path (the heaviest, with a
# render) and the passthrough path (the common case) at the process boundary.
def _event(kind: str) -> dict:
    cwd = str(REPO).replace("\\", "/")
    base = {"hook_event_name": "PreToolUse", "session_id": "e2e-bench", "cwd": cwd}
    if kind == "self_modify":
        return {**base, "tool_name": "Edit",
                "tool_input": {"file_path": "src/dos/arbiter.py"}}
    if kind == "read":
        return {**base, "tool_name": "Read",
                "tool_input": {"file_path": "src/dos/arbiter.py"}}
    if kind == "disjoint":
        return {**base, "tool_name": "Edit",
                "tool_input": {"file_path": "docs/notes.md"}}
    raise SystemExit(f"unknown event kind {kind!r}")


def _go_binary() -> Path | None:
    """The built native binary for THIS machine. Prefer the repo-root dev build
    (go/dos-hook.exe), then the bundled per-arch plugin binaries."""
    cands = [
        REPO / "go" / ("dos-hook.exe" if sys.platform == "win32" else "dos-hook"),
        REPO / "claude-plugin" / "bin" / (
            "dos-hook-windows-amd64.exe" if sys.platform == "win32"
            else "dos-hook-linux-amd64" if sys.platform.startswith("linux")
            else "dos-hook-darwin-arm64"),
    ]
    for c in cands:
        if c.exists():
            return c
    return None


def _time_spawn(argv: list[str], stdin_bytes: bytes) -> tuple[float, bytes, int]:
    """Spawn one process, feeding stdin_bytes, return (elapsed_seconds, stdout, rc).

    Times the FULL process lifecycle (fork/exec + run + exit) with perf_counter —
    the honest wall-clock a hook costs the turn, INCLUDING interpreter cold-start for
    the Python path. cwd is the repo so `python -m dos.cli` resolves the package."""
    t0 = time.perf_counter()
    proc = subprocess.run(argv, input=stdin_bytes, capture_output=True, cwd=str(REPO))
    elapsed = time.perf_counter() - t0
    return elapsed, proc.stdout, proc.returncode


def _summary(samples: list[float]) -> dict:
    """Distribution summary in milliseconds. Median is the honest 'typical' felt
    latency; min is the warm-cache floor; p90 captures the tail a session feels."""
    ms = sorted(s * 1000.0 for s in samples)
    n = len(ms)
    return {
        "n": n,
        "min_ms": round(ms[0], 2),
        "median_ms": round(statistics.median(ms), 2),
        "mean_ms": round(statistics.fmean(ms), 2),
        "p90_ms": round(ms[min(n - 1, int(n * 0.90))], 2),
        "max_ms": round(ms[-1], 2),
        "stdev_ms": round(statistics.pstdev(ms), 2) if n > 1 else 0.0,
    }


def _run_one(name: str, argv: list[str], stdin_bytes: bytes,
             iterations: int, warmup: int) -> tuple[dict, bytes]:
    """Warm up `warmup` times (page-in / OS file cache), then time `iterations`
    spawns. Returns (summary, last_stdout) — the stdout is kept for the parity
    cross-check."""
    for _ in range(warmup):
        _time_spawn(argv, stdin_bytes)
    samples: list[float] = []
    last_out = b""
    for _ in range(iterations):
        elapsed, out, rc = _time_spawn(argv, stdin_bytes)
        samples.append(elapsed)
        last_out = out
    return _summary(samples), last_out


def main() -> int:
    ap = argparse.ArgumentParser(description="End-to-end DOS hook latency: Go vs Python")
    ap.add_argument("--iterations", type=int, default=50,
                    help="timed spawns per decider (default 50)")
    ap.add_argument("--warmup", type=int, default=5,
                    help="untimed warmup spawns per decider (default 5)")
    ap.add_argument("--verb", default="pretool",
                    choices=["pretool", "posttool", "stop", "marker"])
    ap.add_argument("--event", default="self_modify",
                    choices=["self_modify", "read", "disjoint"])
    ap.add_argument("--json", action="store_true", help="emit a machine-readable record")
    args = ap.parse_args()

    stdin_bytes = (json.dumps(_event(args.event)) + "\n").encode("utf-8")

    go_bin = _go_binary()
    if go_bin is None:
        print("[bench] no native dos-hook binary found — build it with "
              "`cd go && go build -o dos-hook.exe ./cmd/dos-hook` first", file=sys.stderr)
        return 2

    go_argv = [str(go_bin), args.verb, "--workspace", "."]
    py_argv = [sys.executable, "-m", "dos.cli", "hook", args.verb, "--workspace", "."]

    if not args.json:
        print(f"# DOS hook end-to-end latency — verb={args.verb} event={args.event}")
        print(f"# iterations={args.iterations} warmup={args.warmup}  "
              f"python={sys.version.split()[0]}  platform={sys.platform}")
        print(f"# go binary: {go_bin}")
        print()

    go_sum, go_out = _run_one("go", go_argv, stdin_bytes, args.iterations, args.warmup)
    py_sum, py_out = _run_one("python", py_argv, stdin_bytes, args.iterations, args.warmup)

    # The LIVE parity check at the process boundary: both deciders must emit
    # byte-identical stdout (the GHF contract, verified on real spawns, not a corpus).
    parity = go_out.strip() == py_out.strip()
    speedup_median = (py_sum["median_ms"] / go_sum["median_ms"]
                      if go_sum["median_ms"] > 0 else float("inf"))

    record = {
        "verb": args.verb, "event": args.event,
        "iterations": args.iterations, "warmup": args.warmup,
        "python_version": sys.version.split()[0], "platform": sys.platform,
        "go_binary": str(go_bin),
        "go": go_sum, "python": py_sum,
        "speedup_median": round(speedup_median, 1),
        "saved_ms_median": round(py_sum["median_ms"] - go_sum["median_ms"], 2),
        "parity_byte_identical": parity,
        "go_stdout_len": len(go_out.strip()),
        "python_stdout_len": len(py_out.strip()),
    }

    if args.json:
        print(json.dumps(record, indent=2))
        return 0 if parity else 1

    def row(label: str, s: dict) -> str:
        return (f"  {label:<8} n={s['n']:<4} "
                f"min={s['min_ms']:>7.2f}  median={s['median_ms']:>7.2f}  "
                f"mean={s['mean_ms']:>7.2f}  p90={s['p90_ms']:>7.2f}  "
                f"max={s['max_ms']:>7.2f}  (ms)")

    print("Latency per hook invocation (lower is better):")
    print(row("Go", go_sum))
    print(row("Python", py_sum))
    print()
    print(f"  -> median speedup:  {speedup_median:6.1f}x   "
          f"({py_sum['median_ms']:.2f} ms -> {go_sum['median_ms']:.2f} ms, "
          f"saves {py_sum['median_ms'] - go_sum['median_ms']:.2f} ms/call)")
    print(f"  -> parity (byte-identical stdout on real spawns): "
          f"{'YES' if parity else 'NO -- DRIFT'}")
    if not parity:
        print(f"\n  go stdout:     {go_out.strip()!r}")
        print(f"  python stdout: {py_out.strip()!r}")
    return 0 if parity else 1


if __name__ == "__main__":
    raise SystemExit(main())
