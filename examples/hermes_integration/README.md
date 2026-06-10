# `hermes_integration` — DOS as the safety gate + lock manager for a Hermes / OpenClaw swarm

This is a self-contained, **offline** worked example of wiring DOS into an
autonomous agent runtime in the Hermes / OpenClaw / SwarmClaw family. It proves
two independent kinds of value, and the second matters **even for a single agent**:

| Axis | Demo | What DOS adds | Fleet needed? |
|---|---|---|---|
| **2 — Safety** | `run_safety_demo.py` | Refuses an arbitrary-code-execution tool command (a prompt-injected `bash -c 'rm -rf …'`, an `npx <fetched-pkg>`, `sudo …`) **before it runs**. SHAPE-not-word, so `cat python.txt` is fine. | **No** — one agent. |
| **1 — Coordination** | `run_coord_demo.py` | When K agents race to write the same shared-state slot, DOS's arbiter (through its real write-ahead log) admits exactly one and refuses the rest, so the **lost updates the runtime would silently incur drop to zero**. | Yes — value grows with K. |

```bash
# from this directory, with `dos-kernel` installed (pip install -e ../.. for dev):
python run_demo.py          # both axes, one scoreboard
python run_safety_demo.py   # just the safety gate (single agent)
python run_coord_demo.py 8  # just the coordination, 8 concurrent agents
python run_coord_demo.py 1  # the honest falsifier — at K=1 DOS adds nothing
```

## Why this is the right integration for these runtimes

Hermes and OpenClaw are persistent, general-purpose autonomous runtimes: they run
on your machine, reach you over messaging, and execute recurring workflows with
**privileged tools** (shell, code-exec, file-ops, browser) under **weak default
security**. The 2026 record on them is two recurring problems — and DOS answers
both with primitives it already ships:

1. **Unsafe actions (single agent).** Prompt injection in a fetched page or a buggy
   community skill steers the agent into a destructive or exfiltrating command, and
   the runtime's sandbox can be disabled by config. DOS's `exec_capability`
   classifier (lifted from Claude Code's `dangerousPatterns.ts`) asks *"does this
   command invoke an arbitrary-code-execution entry point?"* by the **shape of the
   program**, not a forgeable keyword — and the runtime refuses it before it runs.

2. **Uncoordinated shared state (fleet).** Both runtimes run swarms (delegation,
   sub-agents, parallel joins) over **shared memory documents / a task board**, and
   **neither ships a transaction or locking API** for that state. Two agents that
   each individually "succeed" still clobber each other — the lost-update bug. DOS's
   lane arbiter is exactly the missing lock manager: a region lease, durable in a
   write-ahead log, that refuses the second taker.

DOS does not replace these runtimes and does not solve prompt injection. It is the
**trust substrate underneath** them — "the part that doesn't believe the agents" —
adjudicating each act against ground truth instead of the agent's narration of it.

## The wire-in — `hermes_adapter.py` (copy this)

The entire integration is **two functions an integrator drops into their runtime's
tool-execution loop**. There is no `import dos`; the adapter shells the `dos` CLI,
exactly as any foreign runtime must (the zero-coupling adoption surface).

```python
from hermes_adapter import guard_action, acquire_lease

# AXIS 2 — before your agent runs a tool command:
verdict = guard_action(proposed_command, deny_on_arbitrary_exec=True)
if not verdict.allowed:
    return verdict.message       # DOS refused an arbitrary-exec command; tell the agent
run_the_command(proposed_command)

# AXIS 1 — before your agent writes a shared resource:
lease = acquire_lease(f"reservations/{slot}/**", owner=agent_id,
                      loop_ts=unique_ts, workspace=shared_dos_workspace)
if not lease.acquired:
    back_off()                   # another agent holds the region; do other work
    return
write_the_shared_resource(slot)
release_lease(f"reservations/{slot}/**", owner=agent_id, loop_ts=unique_ts,
              workspace=shared_dos_workspace)
```

`deny_on_arbitrary_exec` is **your** policy knob, not DOS's: DOS only *reports* the
capability (advisory by default — spurious disruption is the expensive mistake). An
*unattended* agent reaching the public internet should hard-block (`True`); a
supervised interactive one might merely warn (`False`).

### What each call shells

| Adapter function | DOS verb | Verdict |
|---|---|---|
| `guard_action(cmd)` | `dos exec-capability --command "<cmd>"` | exit 0 = BOUNDED/EMPTY (allow), exit 3 = GRANTS_ARBITRARY_EXEC (deny) |
| `claim_region(region, leases)` | `dos arbitrate --lane <region> --tree <region> --leases <json>` | a **pure** acquire/refuse decision (no disk write) — for when you hold the live-lease set yourself |
| `acquire_lease(region, …)` | `dos lease-lane acquire …` | the **durable** path — arbitrates AND journals the grant to the WAL atomically; the next agent replays it |
| `release_lease(region, …)` | `dos lease-lane release …` | frees the region (RELEASE to the WAL) |

## The files

- **`hermes_adapter.py`** — the integration boundary. The functions above. **The
  one file you copy.**
- **`shared_resource.py`** — a tiny racy "reservations" store standing in for a
  shared memory document / DB row / task record. Byte-atomic writes (so the file
  never tears), but a deliberate read-modify-write *logical* race (the lost update).
- **`swarm_agent.py`** — a mock Hermes / OpenClaw worker that runs a tool command
  and/or books a slot, in `naive` (no gate) or `guarded` (DOS in the loop) mode.
- **`run_safety_demo.py`** / **`run_coord_demo.py`** / **`run_demo.py`** — the A/B
  harnesses and the combined scoreboard.

## The witnesses are non-forgeable (the repo's own discipline)

Neither headline number trusts an agent's self-report (DOS's docs/138 invariant —
*the only witness worth trusting is one the claimant can't author*):

- **Safety:** counts the unsafe commands that **actually executed**, by reading a
  sentinel file the stand-in hazard commands append to — not what the agent claims
  it did.
- **Coordination:** counts lost updates by **re-reading the shared store's own
  booking log** after all agents finish — a booking that believed it won the free
  slot but is not the final holder is a lost update.

## The honest falsifier

At **K=1** the coordination demo shows `naive = 0, guarded = 0`: a single agent
cannot collide with itself, so DOS's lock manager adds nothing. The value is
strictly a **fleet** property and grows with K (lost updates ≈ K−1 in the naive
arm). The safety axis, by contrast, is real at K=1 — which is the whole point of
splitting them. See `docs/278` for the full design and the benchmark precedent
(docs/233/245: coordination payoff measured live, `payoff = C(K,2)·shared·clobber·F^D`).

## How to point it at a *real* Hermes / OpenClaw runtime

1. `pip install dos-kernel` so the `dos` CLI is on PATH (the adapter falls back to
   `python -m dos.cli` for a dev checkout).
2. Copy `hermes_adapter.py` into your runtime.
3. In your tool-execution path, call `guard_action(cmd)` before running a shell /
   code-exec tool, and honor a deny.
4. For shared state, pick a **region naming convention** (here `reservations/<id>/**`)
   and a **single shared DOS workspace** all your agents point at (so they share one
   WAL), then bracket each shared-state write with `acquire_lease` / `release_lease`.
5. Optionally go further, two ways:
   - **Hook dialect (Hermes).** Hermes' `pre_tool_call` shell hook reads a
     `{"decision":"block","reason":…}` deny on stdout — exactly what
     `dos hook pretool --dialect hermes` emits. Wire it in `cli-config.yaml`
     (`hooks: pre_tool_call: [{command: "dos hook pretool --workspace . --dialect hermes"}]`)
     to get DOS's structural admission (SELF_MODIFY / lane collision) as a native
     pre-tool gate, no adapter code. (OpenClaw's hook is an in-process TS return, not
     stdout — so it has no dialect; see `docs/278` Surface 3.)
   - **MCP server.** Expose DOS as `dos-mcp` (the runtimes' documented #1 extension
     path) so `dos_arbitrate` / `dos_verify` become native agent tools — see
     `docs/278` Phase 3.
