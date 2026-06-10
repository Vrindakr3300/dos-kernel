# 271 — The pure-Go frontier: what is left to port, and what must never be

> **Status:** plan (2026-06-09). The Go fast-path now has a *measured* speed claim
> ([270](270_go-hook-fastpath-benchmarks.md)) and a *byte-exact* correctness claim
> (the docs/124 parity corpus). With both nailed down, this doc answers the question
> the benchmark leaves open: **what should the Go binary do next, and where does the
> port stop?** It is grounded in the tree as it stands today, not in any earlier
> doc's "Status" line — including [268](268_gemini-integration-proof-and-the-go-dialect-gap.md),
> whose headline gap was already being closed in the working tree when this was
> written (see §1).

## Why this doc exists

DOS has exactly one piece of Go: `dos-hook`, the native hook decider (docs/100 named
the boundary, docs/124 fixed the parity contract, docs/125 broke ground, docs/270
proved the speed). It exists for one reason — the per-tool-call hook fires on *every*
tool call, and a Python interpreter cold-start per call is the dominant sensing
latency (~230–262 ms measured; the package import alone is ~153 ms). A static no-cgo
binary erases it (~6–15 ms). That is the whole charter.

So "pure Go" is **not** a goal in itself. The kernel is Python and stays Python. The
only question worth a plan is: *which decision-bearing work also sits on a felt-latency
hot path, such that moving it to the binary buys a fleet real time — and which work
would be moved only for the satisfaction of moving it?* This doc sorts the remaining
surface into those two piles and gives the first an honest phase order.

A note on where this work lives in the layering. The Go module is **dev-adjacent
native tooling that ships beside the package**, the same category as the release
scripts: nothing under `src/dos/*.py` imports it, and it consumes the Python kernel's
*behavior* (via the parity corpus) rather than its code. Editing the Go decider is
never editing the substrate — it is re-implementing a frozen projection of it in a
second language, gated by a differential test. Keep that framing: the binary is a
*faster mouth* for verdicts the Python kernel already defines, never a second source
of truth.

## 1. The dialect transcoder — the docs/268 gap, now closing

[268](268_gemini-integration-proof-and-the-go-dialect-gap.md) found a real hazard:
the Go binary computed a refusal correctly (e.g. SELF_MODIFY) but emitted the
**Claude-Code** envelope unconditionally, silently ignoring `--dialect`. For a host
whose deny grammar is not CC's nested `permissionDecision` (Gemini and Antigravity
honor a top-level `decision`; Cursor honors `permission`), that is a fail-**open**:
the host receives bytes it does not parse, finds no refusal, and proceeds. A
correctly-computed DENY would be dropped, and — in the worst case docs/268 names — an
agent wired Gemini→Go could rewrite the very kernel adjudicating it.

**This gap is being closed in the working tree as of 2026-06-09.** The fix mirrors
the Python kernel/driver split exactly (the docs/217 seam, on the output side):

- `go/internal/hook/dialect_transcode.go` — `transcodeCC(cc, dialect)` reads the
  canonical Claude-Code dict the decider already builds (the dialect-neutral lingua
  franca) and re-renders it into the host's grammar. `claude-code`/`codex`/`""` return
  the dict unchanged (codex copied CC's envelope verbatim); `gemini`/`antigravity`/
  `cursor` are small pure transforms. An unknown dialect degrades to CC (never
  crashes — the same fail-safe rule as `parseFlags` dropping unknown flags).
- `Decision.RenderAs(dialect)` in `decide.go` + the `--dialect` thread-through in
  `run.go`/`main.go` — so the verdict is computed vendor-blind (the CC dict, kept
  byte-for-byte for the durable journal), and `--dialect` selects an *output*
  transform strictly downstream of the decided verdict. That is exactly where the
  vendor-agnostic-kernel litmus says a vendor name belongs: the render step, never
  the adjudication.
- `parity_dialect_test.go` — extends the docs/124 parity contract from "the CC
  projection" to "every dialect projection": for each (verdict, dialect) the Go bytes
  must equal Python's `resolve_dialect(name).render(parse_cc(cc))`. This is the
  ratchet that keeps the two implementations from drifting.

The architectural note docs/268 already made holds: the Go side needs **no
entry-point plugin machinery**. The non-CC dialects are kernel-known closed data that
ship in the binary anyway, so a plain `switch` is the whole mechanism — there is no
third-party Go-driver-registration story, and none is wanted on the hot path.

**Forward item (small):** once the transcoder lands and its parity test is green,
docs/268's operator guidance ("wire non-CC hosts to the Python path") is obsolete and
should be retired in that doc, and the docs/125 status should note the Go binary now
speaks every shipped dialect. This doc is the place that reconciliation points to.

## 2. GHF5 — the native `verify`/oracle rung (the real frontier)

This is the one genuinely unbuilt pure-Go capability, and docs/124/125 already scoped
why it is hard. The `stop` verb's full power and a native `dos verify` both want the
**oracle cluster** (`oracle` + `phase_shipped` + `stamp` + the picker), and that
cluster is the single part of the kernel that is **not RE2-clean**.

### 2.1 The blocker, named exactly

Go's standard `regexp` is RE2: linear-time, but it forbids lookbehind, lookahead, and
backreferences. The oracle's ship-stamp grammar uses lookbehind in exactly three
places (audited in docs/124 §1.2, re-confirmed against the tree for this plan):

```
phase_shipped.py:201   _BOUNDARY_PRE_NEG = r"(?<![A-Za-z0-9.\-])"   # negative lookbehind
stamp.py:158           re.sub(r"(?<=\d)s$", "", tok)                # positive lookbehind (P0s -> P0)
stamp.py:465           r"(?<![\w./-])(?:\.\.?/)*(\w[\w\-]*/...)"     # negative lookbehind (path left-boundary)
```

Everything else the kernel matches — the arbiter, liveness, and loop clusters — uses
**zero** lookbehind/lookahead/backreference and is portable to RE2 as-is (docs/124
§1.2 measured this). So GHF5 is not "rewrite the kernel in Go"; it is "rewrite **three
boundary assertions** RE2-compatibly, then port the cluster that depends on them."

### 2.2 The two honest ways across, and the recommendation

1. **Rewrite the three boundaries as RE2 (capture-and-check).** Each lookbehind is
   expressible without the assertion by capturing the boundary character and checking
   it in code, or by anchoring differently. This is mechanical but exacting — the
   stamp grammar is the truth syscall's recognizer, so a byte for byte parity corpus
   over the *full* stamp vocabulary (every `[stamp]` convention, the host-strict and
   generic defaults) must gate it. The corpus is the deliverable, not the regex.
2. **Have the binary delegate `verify` to Python (the status quo for `stop`).** The
   `stop` verb already exits 3 = DELEGATE for the non-generic convention, and the
   `|| python` tail in `hooks.json` runs the Python verb with clean stdin. `verify` is
   **not on a per-tool-call hot path** — it is a truth query a human or supervisor
   runs out of band, not a hook that fires on every call. So the latency argument that
   justifies the native pretool path is *much weaker* for `verify`: a ~250 ms Python
   spawn for an occasional ground-truth check is a cost almost nobody feels.

**Recommendation: do not port `verify`/the oracle cluster to Go for latency.** The
felt-latency seam — the entire reason the Go module exists — is the *hook* hot path,
and `verify` is not on it. Porting the oracle would mean carrying the RE2-rewrite risk
(a subtle stamp-grammar divergence is a *correctness* bug in the truth syscall, the
worst place to have one) to buy time on a call that is not hot. The one case that
*does* justify it is docs/122's on-device kernel (§4 below), where there is no Python
to delegate to at all — and that is a different charter than "make the hook faster."

This reframes docs/125's "GHF5 is the only remaining phase": GHF5 is the only
remaining *capability*, but it is a capability the project may rationally choose never
to build for the hook, and to build only if and when the on-device runtime becomes a
funded goal. The honest plan is: **leave the oracle in Python; let the binary delegate
`verify`; revisit only under docs/122.**

## 3. Cross-compile and the build matrix (the cheap, owed piece)

The binary is built per-platform (`scripts/build_hook_binary.py`) and the plugin ships
launchers that pick the right one (`claude-plugin/bin/dos-hook{,.ps1}`). The Go module
is static no-cgo *by design* precisely so it cross-compiles trivially — the docs/122
on-device payoff is supposed to come "free later" from this property.

The owed work here is not code, it is **proof and coverage**:

- A CI job that cross-compiles the binary for the target matrix (at least
  `linux/amd64`, `linux/arm64`, `darwin/arm64`, `windows/amd64`) on every change to
  `go/`, so a platform-specific break is caught before a release rather than by a user
  whose plugin silently falls back to Python.
- The end-to-end harness (`scripts/bench_hook_e2e.py`, docs/270) gains a `--json`
  ratchet already; wiring it into CI as a *regression guard* (not a perf gate — the
  absolute number is machine-specific, but a 2× regression in the Go/Python *ratio*
  on the same runner is a real signal) would catch a fast-path that quietly stopped
  being fast.

Neither needs a new doc; both are CI plumbing on top of artifacts that already exist.

## 4. The on-device runtime (docs/122 — the only thing that flips §2)

[122](122_the-core-go-runtime-and-the-on-device-kernel.md) is the one context where
the §2 recommendation inverts. On a device with no Python interpreter — an edge agent,
a sealed appliance, a CI runner that ships only the binary — there is no `|| python`
tail to delegate to, so *every* verdict the device needs must be in the binary,
including `verify`. There, the RE2 rewrite of the stamp grammar stops being optional.

This is a deliberately *deferred* frontier, not a near-term one: it is gated on a
real on-device consumer existing, and DOS does not have one today. The point of naming
it here is to record that GHF5's cost (the stamp-grammar RE2 rewrite + its parity
corpus) is the *same* cost docs/122 will eventually pay — so if the on-device runtime
becomes real, GHF5 is its first phase, and this plan's §2.2 recommendation ("leave it
in Python") is explicitly scoped to "as long as Python is always present."

## 5. What must NEVER be ported to Go (the boundary)

A plan for "pure Go" is incomplete without the stop line. Three things stay Python by
construction, and moving them to Go would violate the architecture, not advance it:

- **The MCP server (`dos_mcp/`).** MCP is a server framework (`FastMCP`); folding it
  into the binary would drag a dependency tree onto a hot path that is static-stdlib by
  charter, and CLAUDE.md already forbids even folding the *Python* MCP server under
  `dos`. There is no Go MCP server and there should not be one — MCP is the
  vendor-neutral adoption surface precisely because it is JSON-over-stdio with no
  language coupling; a second implementation buys nothing and doubles the maintenance.
- **The heavy-I/O kernel modules.** The supervisor loop, the durable-schema/intent
  ledger recovery family, the timeline assembler, the decision/`top` TUIs — these are
  not on a per-call hot path, they do substantial I/O, and several carry rich prose
  the docs/124 contract explicitly declines to freeze byte-for-byte. The binary's
  parity contract is "byte-exact on the *decision-bearing fields*, prose stays
  matchable-or-Python"; modules whose *value* is the prose or the I/O orchestration
  have nothing to gain from a native port and everything to lose in parity drift.
- **Anything whose verdict is the *only* copy.** The binary is a faster renderer of
  verdicts the Python kernel defines. The moment Go computed a verdict the Python
  kernel could not reproduce, the parity corpus would have nothing to pin it against,
  and the "one source of truth, two mouths" discipline would break. Every Go decider
  must remain a projection of a Python one, gated by a differential test. That is the
  invariant that keeps the second language safe.

## 6. The phase order (honest, dependency-aware)

| Phase | Work | Hot path? | Risk | Recommendation |
|---|---|---|---|---|
| **P1** | Dialect transcoder (§1) | yes (hook) | low (small pure transforms; parity-pinned) | **land it** — it closes a fail-open hazard; in flight already |
| **P2** | Cross-compile CI + ratio-regression guard (§3) | n/a (build) | low (plumbing on existing artifacts) | **do next** — cheap, prevents silent fallback-to-Python |
| **P3** | GHF5 native `verify`/oracle (§2) | **no** (`verify` is out-of-band) | high (RE2 rewrite of the truth-syscall recognizer) | **defer** — leave in Python; binary delegates; revisit only under P4 |
| **P4** | On-device runtime (§4, docs/122) | n/a (no Python present) | high (carries P3's cost) | **deferred frontier** — gated on a real on-device consumer; P3 becomes its phase 1 |

The through-line: **P1 and P2 are real, cheap, and on (or supporting) the hot path
that justifies the binary's existence. P3 and P4 are a capability the project may
rationally never build for the hook, and should build only when an on-device consumer
makes the RE2 cost unavoidable.** "Pure Go" as a finish line is a non-goal; a *faster
hook that speaks every host's dialect* is the goal, and P1+P2 reach it.

## Provenance

Grounded in the tree at 2026-06-09: the dialect transcoder (`dialect_transcode.go` +
`parity_dialect_test.go` + the `RenderAs`/`--dialect` thread-through) read live from
the working tree; the three lookbehinds re-confirmed at `phase_shipped.py:201`,
`stamp.py:158`, `stamp.py:465`; the Go tree swept for dead artifacts (none —
`tree.go`'s `laneTreesDisjoint` is deliberately ported-ahead, "Kept for GHF5
convergence", not dead code). Builds on docs/100/122/124/125 (the Go-core lineage),
docs/217/221/268/269 (the cross-vendor seam), and docs/270 (the benchmark this plan
follows).
