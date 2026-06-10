# docs/282 — The MCP tool call has no deadline; a stalled call should return a typed `STALLED`, not hang

> **Status:** PLAN (design + root-cause; no code shipped yet).
> Observed 2026-06-09 while dogfooding the latest DOS (v0.18.0) against this repo.

## The observation (live, on this repo)

While running the DOS-on-DOS validation ritual, an MCP tool call —
`mcp__plugin_dos-kernel_dos__dos_commit_audit` against `HEAD` on this repo — **spun
without returning** and had to be killed by the operator. The same verdict computed
two other ways finished instantly:

| Surface | Call | Wall time |
|---|---|---|
| **CLI** | `dos commit-audit --workspace . b2923f1` | **305 ms** |
| **In-process** | `commit_audit.audit_commit('HEAD', root=…)` | **~40 ms** |
| **MCP tool** | `dos_commit_audit(ref="HEAD")` via the plugin server | **spun (killed)** |

The divergence is the whole point: the **kernel logic is healthy** (CLI + in-process
both fast), so the fault is **not the syscall** — it is the **MCP transport/server
layer**, which today has **no deadline on a tool call**. `grep -n "timeout\|deadline\|
asyncio.wait_for" src/dos_mcp/server.py` returns nothing: every tool body runs
unbounded, so a server that is busy / mid-restart / blocked on a held OS resource
hangs the call forever instead of failing in a structured way.

## Why this repo is the worst case for it

This is a **multi-session-hot tree** (see the memory note
`project-dos-multi-session-hot-tree`). During the spin, several concurrent Claude
sessions were landing commits — HEAD moved 5+ commits in minutes, and the working
tree carried other sessions' unstaged edits. In that window a peer's `git commit`
transiently holds `.git/index.lock`, and **any `git show HEAD` / `git diff` blocks
on that lock**. `audit_commit` on the *moving* `HEAD` ref is therefore the most
contention-prone call in the server — whereas the CLI run I timed used an explicit
immutable SHA (`b2923f1`), which never contends. (`HEAD` vs SHA is the same
moving-target hazard `liveness` already reasons about.)

So the trigger is real and reproducible-in-spirit: **an unbounded syscall over a
shared OS resource (the git index) on a hot tree.** The fix must not assume the
syscall is fast — it must assume any syscall *can* stall and bound it.

## The DOS way to flag this (the design)

A hung tool call is **an agent — here, the server — narrating nothing while making
no forward progress.** The kernel already has the exact verdict for that condition,
and already names it: `liveness.Verdict.STALLED` — *"no fresh heartbeat, no commits
— dead/hung, not spinning"* (`src/dos/liveness.py:84`). The discipline the kernel
preaches for *worker* runs should apply to **its own MCP surface**:

> **A tool call is a mini-run. Bound it with a deadline. On expiry, return a typed
> `STALLED` refusal from the closed vocabulary — never hang.**

Three properties, each matching an existing kernel rule:

1. **Deadline → typed refusal, fail-safe.** Wrap each tool body in a wall-clock
   budget (default e.g. 5 s, configurable). On expiry, return a structured
   `{"verdict": "STALLED", "reason": "tool 'dos_commit_audit' exceeded its 5000 ms
   deadline — the server or a shared OS resource (git index) is blocked", …}`
   instead of letting the await hang. This is the **fail-safe** rule the kernel
   already uses in `hook_exit` (unknown non-zero → WARN) and `run_judge` (any
   raise → ABSTAIN): *unknown completion → intervene/surface, never silently
   proceed and never silently spin.* The deadline value is **policy** (a config
   field), the deadline *mechanism* is the server's.

2. **The CLI is the ground-truth fallback witness.** When the MCP surface stalls,
   the CLI computing the identical verdict in 305 ms is the **non-forgeable
   witness** that the syscall itself is healthy — it localizes the fault to the
   *transport*, not the *kernel*. This is the audit's own
   narration-vs-ground-truth lesson (the `trajectory-audit` headline) turned on the
   tooling: the STALLED envelope should *say so* — "the kernel verdict is reachable
   via `dos <verb>` on the CLI; this is a transport stall."

3. **Surface it, do not retry.** A STALLED verdict is **advisory** (docs/99): the
   server reports the stall; it does not auto-retry (a retry on a held index lock
   just stalls again — the `project-dos-poll-loop-antipattern` failure mode). The
   operator/agent decides: fall back to the CLI, or wait for the lock holder to
   finish. The verdict routes to the `decisions` queue like any other refusal.

## Where the mechanism lives (layering)

This is a **server (dos_mcp) concern, not a kernel-module change.** The kernel
already owns the `STALLED` *vocabulary* (`liveness`); the **deadline wrapper** is
transport mechanism that belongs in `src/dos_mcp/server.py` — a small decorator
applied at `@mcp.tool()` registration that races the tool body against a timer and,
on timeout, returns the typed envelope. No `src/dos/` leaf is edited; the one-way
arrow (`dos_mcp` imports `dos`, never the reverse) is preserved. The reason string
may reuse a closed-vocabulary class; if a dedicated `TOOL_STALLED` reason is wanted
in `BASE_REASONS`, that is a seam-data edit (`dos.reasons`), declarable per
workspace — but the minimal first cut needs only the server-side wrapper + the
`STALLED` verdict literal.

## Implementation sketch (next step, not yet shipped)

```python
# src/dos_mcp/server.py — a deadline wrapper raced against each tool body.
# FastMCP tools are sync here; run the body in a worker thread and join with a
# timeout so a blocked git/OS call cannot hang the event loop forever.
def _with_deadline(fn, budget_ms: int = 5000):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        box: dict[str, Any] = {}
        t = threading.Thread(target=lambda: box.update(r=fn(*a, **k)), daemon=True)
        t.start(); t.join(budget_ms / 1000)
        if t.is_alive():               # STALLED — the body never returned in time
            return {
                "verdict": "STALLED",
                "reason": (f"tool {fn.__name__!r} exceeded its {budget_ms} ms "
                           "deadline — the server or a shared OS resource is blocked"),
                "fallback": f"compute this verdict on the CLI: dos {_cli_verb(fn)} …",
            }
        return box["r"]
    return wrapper
```

(A daemon thread can't be force-killed in CPython, so the blocked thread leaks until
the OS resource frees — acceptable for a stall escape hatch; the point is the *call*
returns a typed verdict promptly, not that the zombie work is reaped. A
process-pool variant that *can* be killed is a heavier follow-up.)

## Test (the discipline applied to itself)

Pin it the way the kernel pins every verdict — a fixture-driven, injected-clock test
under `tests/test_mcp_server.py`: register a tool whose body blocks on an
`threading.Event` that is never set, call it through the wrapper with a tiny budget
(e.g. 50 ms), and assert it returns `{"verdict": "STALLED", …}` within the budget +
slack — **never** hangs the test. The fast path (body returns before the deadline)
must pass through byte-identically, so the existing `dos_verify` / `dos_commit_audit`
return shapes are unchanged when nothing stalls.

## One-line takeaway

The kernel's thesis is *don't believe a self-narrating worker.* A tool call that
spins is the server narrating "I'm working" with no forward progress — so the DOS
way to flag it is the kernel's own `STALLED` verdict, bounded by a deadline, with the
CLI as the ground-truth fallback witness. **Bound the call; type the stall; surface,
don't retry.**
