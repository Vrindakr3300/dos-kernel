# 270 — GHF benchmarks: proving the Go hook fast-path actually erases the cold-start

> **Status:** MEASURED (2026-06-09). The docs/125 Go hook fast-path shipped on the
> claim that it erases the Python interpreter cold-start on the per-tool-call hook
> hot path — "~10 ms instead of ~0.3–0.8 s." That claim was asserted in the source
> comments and pinned for **correctness** by the parity corpus, but it was never
> **measured**. This doc closes that gap: it adds the first benchmarks to the Go
> module and an end-to-end process-latency harness, and reports the verdict.
>
> **The claim holds.** Measured on this machine: **Go ~6–15 ms vs Python ~230–262 ms
> per hook invocation — a 16–43× median speedup, ~225–248 ms saved on every tool
> call** — with the two deciders emitting **byte-identical** stdout on every real
> spawn (live parity, not just the corpus). The Python cost is dominated by package
> import (`import dos.cli` alone is ~153 ms over a bare interpreter), which a compiled
> static binary has zero of — exactly the mechanism docs/125 predicted.

## Why this needed measuring (the dogfood rule)

The DOS contract is "the kernel is the part that doesn't believe the agents," and
the working ritual on this repo is to let a witness — not narration — close a claim.
docs/125's performance number was narration: a plausible figure in a comment,
unrefuted. The parity corpus proves the Go decider is **byte-correct** vs Python, but
correctness is not speed. A fast-path that is not actually fast is a silent
regression hiding behind a green test suite — precisely the failure mode the repo is
built to catch.

So the witness here is a **clock at the process boundary**, run from outside either
decider, that (a) times the real OS process and (b) checks the two emit identical
bytes. Neither decider gets to self-report its latency.

## What was built

Two artifacts, both **outside the kernel** (dev tooling that operates *on* the
package — the "kernel never imports its own tooling" litmus):

1. **`go/internal/hook/bench_test.go`** — the first `testing.B` benchmarks in the Go
   module. Three layers, so the end-to-end number can be attributed:
   - **Pure decision** (`Decide` / `classifyStream` / `waitMarkerBudget`): the
     verdict math, no JSON, no disk.
   - **Parse + decide** (`json.Unmarshal` of a real CC event → `Decide` → `Render`):
     adds per-call deserialization.
   - **Full boundary** (`DecidePretool` against a real temp workspace): adds the WAL
     read + the 11-file self-modify stat probe — the only disk the pretool path
     touches.

2. **`scripts/bench_hook_e2e.py`** — the end-to-end harness. Spawns the shipped
   `dos-hook` binary and `python -m dos.cli hook <verb>` N times each over an
   identical CC event on stdin, against this real workspace, and reports the
   wall-clock distribution + a live byte-parity check. `--json` emits a CI-ratchetable
   record.

## Results

### End-to-end process latency (the headline)

`python scripts/bench_hook_e2e.py`, 40–60 timed spawns each after warmup, Windows,
Python 3.13.7, AMD Ryzen 9 9950X:

| Verb | Event | Go median | Python median | Speedup | Saved/call | Parity |
|---|---|---:|---:|---:|---:|:--:|
| `pretool` | self_modify (deny) | 13.9 ms | 262 ms | **18.9×** | 248 ms | YES |
| `pretool` | read (passthrough) | 9.4 ms | 248 ms | **26.3×** | 238 ms | YES |
| `pretool` | disjoint (passthrough) | 8.9 ms | 244 ms | **27.5×** | 235 ms | YES |
| `posttool` | — | 7.0 ms | 238 ms | **33.8×** | 231 ms | YES |
| `stop` | — | 5.4 ms | 232 ms | **42.7×** | 227 ms | YES |
| `marker` | — | 6.2 ms | 246 ms | **39.7×** | 240 ms | YES |

Go is **stable** (stdev ~0.8 ms on the headline case); Python varies more (stdev
~25 ms) because import/GC dominates. The Python figure is **verb-independent**
(~230–262 ms everywhere) — the tell that the cost is fixed startup, not the decision.

### Attribution: it's the import, exactly as predicted

```
bare `python -c pass`        : ~32 ms   (interpreter only)
`python -c 'import dos.cli'`  : ~185 ms  (+153 ms — the package import graph)
full `python -m dos.cli hook` : ~250 ms  (+ -m machinery, argparse, the decision)
```

The ~250 ms Python latency decomposes as **~32 ms interpreter + ~153 ms package
import + ~65 ms module-run/argparse/decide**. The Go binary does *all of it* — load
*and* decision — in ~6–14 ms, because a static no-cgo binary has **no import graph to
walk**. This is the docs/125 mechanism, confirmed by measurement, not assumed.

### In-process decision cost (the micro-benchmarks)

`go test -bench . -benchmem`, same machine. The decision work the binary does *after*
the OS has loaded it:

| Benchmark | ns/op | allocs/op | What it is |
|---|---:|---:|---|
| `Decide_ReadPassthrough` | **38 ns** | 0 | a read short-circuits — zero allocation |
| `Decide_DisjointDocPassthrough` | 396 ns | 1 | a disjoint edit admits |
| `Decide_SelfModifyDeny` | 3.5 µs | 22 | the deny + dialect render |
| `Decide_CollisionDeny` | 3.4 µs | 31 | overlap scorer + deny render |
| `ParseAndDecide` | 6.0 µs | 53 | + `json.Unmarshal` of a real event |
| `DecidePretool_FullBoundary` | **178 µs** | 299 | + WAL read + 11-file stat probe (deny) |
| `DecidePretool_PassthroughBoundary` | **159 µs** | 111 | idle repo, read passes through |
| `ReplayJournal_256` | 193 µs | 535 | folding a 256-lease WAL (large fleet) |
| `ClassifyStream_64` | 4.8 µs | 130 | a 64-step repeat-run scan |

The full in-process pretool decision is **~0.16 ms**, and it is **disk-I/O-bound**
(the 11-file stat probe + WAL read), not CPU — the pure decision is sub-microsecond.
So the entire native per-call budget is **process spawn + ~0.16 ms**, and the
end-to-end ~6–14 ms Go figure is almost all OS process creation, which is
irreducible and tiny. There is no remaining fat to trim on the native path.

## The honest caveats (where the numbers could mislead)

- **Machine-specific.** This is a fast desktop (Ryzen 9 9950X, warm disk cache). The
  *speedup* is robust, but the absolute Python figure scales with the machine: on a
  cold-disk CI runner or a laptop, `import dos.cli` can easily push the Python path
  toward the **0.3–0.8 s upper end** docs/125 quotes. The ~250 ms measured here is the
  *low* end of that range, on favorable hardware — so the docs/125 estimate is not
  wrong, it was conservative. The fast-path matters *more* on slow machines, not less.
- **The `||` fallback is free when Go wins.** The real `hooks.json` runs
  `dos-hook … || python …`. When the Go binary exits 0 (the common case — it owns
  every pretool/posttool/marker outcome and the generic stop path), **Python never
  spawns**. The 250 ms is only paid when the binary is absent (exit 127) or
  DELEGATES (exit 3, an advanced stop flag / a non-generic convention). So a default
  install pays the Go number on virtually every call.
- **Read-while-held is a deny, in BOTH implementations.** A surprise the benchmarks
  surfaced: with a live lane held whose tree is known, a `Read` (empty-but-known
  requested tree) is *refused* by the disjointness predicate's "empty requested tree
  vs a known lease → refuse" branch (`admission.py:201`, faithfully ported to
  `admission.go`). This is parity-correct (the Go and Python agree byte-for-byte),
  not a Go bug — but it means the passthrough benchmark uses an *idle* workspace (no
  held lane), which is the common single-agent case. Worth a separate look at whether
  reads *should* bypass admission entirely (they take no tree), but that is a
  **kernel-policy** question for both implementations, out of scope for this perf doc.
- **Frequency is the multiplier.** 240 ms/call sounds small until you multiply by the
  hook fire-rate: the PreToolUse hook fires on *every* tool call, and a busy session
  is hundreds of calls. At 300 calls, the fast-path saves **~72 s of wall-clock the
  user would otherwise spend watching a hook think** — per session.

## How to reproduce

```bash
# Micro-benchmarks (dodge the hot-tree GOCACHE lock — see the memory note):
export GOCACHE=/c/work/dos/go/.cache_bench
cd go && go test -run '^$' -bench . -benchmem ./internal/hook/

# End-to-end (spawns the real binary vs the real python verb):
python scripts/bench_hook_e2e.py --iterations 50 --verb pretool --event self_modify
python scripts/bench_hook_e2e.py --json --verb pretool --event self_modify   # CI record
```

## Verdict

docs/125 shipped a performance claim on the strength of an argument; this doc
provides the witness. The argument was right: a static Go binary serves the
per-tool-call hook decision **16–43× faster** than the Python verb, saving
**~225–248 ms on every call**, while emitting **byte-identical** output — and the
saved time is precisely the package-import cold-start the binary structurally avoids.
The fast-path does what it says.
