# dos-mcp — the DOS syscalls as an MCP server

> The kernel is the part that doesn't believe the agents. This is how any
> MCP-speaking agent reaches it.

`dos-mcp` exposes the DOS trust substrate over the **Model Context Protocol**, so
a host like Claude Desktop, Cursor, Cline, Continue, or an Agent-SDK app can call
the referee with **zero Python coupling** — it speaks JSON over stdio, never
`import dos`. It is the lowest-friction way to adopt DOS: install, point your host
at it, and your agents can verify claims, arbitrate leases, and refuse with a
structured reason.

## The tools

| Tool | Syscall | What it answers |
|---|---|---|
| `dos_verify(plan, phase, workspace=".")` | `verify()` | *Did (plan, phase) actually ship?* — from git/registry evidence, never a worker's self-report. Works against a bare git repo with no plan. Returns `{shipped, source, sha?, …}`; `source` ∈ `registry`/`grep`/`none` names how thin the evidence was. |
| `dos_commit_audit(ref="HEAD", workspace=".")` | `verify()` (plan-free) | *Does a commit's CLAIM match its DIFF?* — author-neutral (human or agent), no plan needed. Catches a `fix:` that touched only a README, an `--allow-empty "shipped"`, a "tests pass" that deleted assertions. Returns `{verdict, witness, reason, source_files, …}`; `witness` ∈ `diff-witnessed` (non-forgeable) / `subject-only` (forgeable). Grades the KIND of change, never correctness. |
| `dos_arbitrate(lane, kind, tree, live_leases, force=False, workspace=".")` | `arbitrate()` | *May this worker take this lane right now?* — pure, state-in/decision-out. Refuses when a worker's file-tree collides with a live lease. Returns `{outcome, lane, reason, free_clusters, …}`. |
| `dos_refuse_reasons(workspace=".")` | `refuse()` | *What may I refuse with?* — the closed refusal vocabulary. Every reason is simultaneously emittable, verifiable, and refusable. |
| `dos_check_reason(reason_class, workspace=".")` | `refuse()` | *Is this reason real?* — membership check, so a producer can only emit a reason the oracle can verify (an unknown one is `UNCLASSIFIED` drift). |
| `dos_status(run_id, …, workspace=".")` | `liveness()` + `resume()` | *What is the state of run X right now?* — one folded, peer-readable fact: liveness (is it moving?), ledger-VERIFIED progress (never the agent's claim), the held-lease region, and the resume plan once it stopped. Fail-closed; the digest has **no `claimed` field** by construction. |
| `dos_recall(name, …, workspace=".")` | — | *Is this recalled memory still TRUE?* — re-verify a memory against git + the working tree at read time, instead of trusting a frozen self-report. Returns `RECALL_FRESH`/`RECALL_STALE`/`RECALL_UNVERIFIABLE`. |
| `dos_doctor(workspace=".")` | — | The machine-readable workspace report (paths / lanes / stamp grammar) an agent reads once to discover the layout. |

Every tool takes an optional `workspace` (a repo path, default the server's cwd)
and honors that workspace's `dos.toml` — the same four-table readback
(`[lanes]`/`[paths]`/`[stamp]`/`[reasons]`) the `dos` CLI does. So pointing the
server at a foreign repo Just Works: its lane taxonomy drives `dos_arbitrate`, its
ship-stamp grammar drives `dos_verify`, its declared reasons appear in
`dos_refuse_reasons`.

`verify`, the reason tools, and `doctor` are **read-only** — they never create a
`.dos/` directory in the served repo (pinned by the smoke test). `dos_arbitrate`
is a **pure adjudication**: unlike `dos arbitrate --force` on the CLI, it never
persists a decision.

## Built for agents (and for you, directly)

The server is shaped so Claude (and any agent) reaches for the right tool at the
right moment, and so you can drive it from the host UI without knowing tool names.

**Actionable verdicts.** Every decision tool returns an `interpretation` field
alongside the kernel's verbatim verdict — a one-line "what this means for your
next action," so a model acts on guidance instead of a bare dict:

```jsonc
// dos_verify on an unproven claim:
{ "shipped": false, "source": "none",
  "interpretation": "NOT shipped — and there is NO positive evidence either way.
                     Treat it as not done. Do NOT accept a worker's claim that it
                     shipped without evidence." }
```

The kernel fields are never rewritten; the hint is strictly downstream of the
decided verdict (the renderer invariant — it can't leak policy back into the
adjudication). Tool descriptions also lead with an explicit *"USE THIS WHEN…"* so
the agent knows the trigger, not just the mechanics.

**Prompts — slash-commands a user invokes directly.** These surface in the host
(e.g. as `/`-commands in Claude Desktop) and teach the agent the right tool + the
right sequence:

| Prompt | What it does |
|---|---|
| `verify_a_claim(plan, phase)` | Confirm a claim shipped from evidence, not anyone's word. |
| `can_i_take_this_lane(lane, tree?)` | Get a clear GO / STOP before starting work that touches files. |
| `refuse_with_a_reason(situation)` | Pick a verifiable refusal reason instead of free-text prose. |

**Resources — browsable context.** A host can *read* the workspace's vocabulary
and taxonomy as context, not just call tools:

| Resource | Contents |
|---|---|
| `dos://reasons` (+ `dos://reasons/{workspace}`) | The refusal vocabulary, as markdown. |
| `dos://lanes` (+ `dos://lanes/{workspace}`) | The lane taxonomy + each lane's file tree. |

## Install & run

```bash
# Dist name is `dos-kernel` (the bare `dos` on PyPI is an unrelated package). The
# [mcp] extra pulls the server framework; the core kernel stays near-stdlib:
pip install 'dos-kernel[mcp]'
dos-mcp                       # serve over stdio (what an MCP host launches)
```

The kernel itself stays near-stdlib — a core install (no `[mcp]`) does **not**
pull the MCP framework; the `[mcp]` extra adds it only when you want the server.

## Wire it into a host

### Claude Desktop / Claude Code (`claude_desktop_config.json` / `.mcp.json`)

```json
{
  "mcpServers": {
    "dos": {
      "command": "dos-mcp",
      "env": { "DISPATCH_WORKSPACE": "/path/to/the/repo/it/should/serve" }
    }
  }
}
```

`DISPATCH_WORKSPACE` sets the default `workspace` for every tool (a tool call can
still override it per-call with the `workspace` argument). Omit it to default to
the server's working directory.

If `dos-mcp` isn't on `PATH`, use the module form:

```json
{ "command": "python", "args": ["-m", "dos_mcp.server"] }
```

### Gemini CLI (`~/.gemini/settings.json` or project `.gemini/settings.json`)

Gemini CLI registers MCP servers under the same `mcpServers` key, with `env` for
the served workspace:

```json
{
  "mcpServers": {
    "dos": {
      "command": "dos-mcp",
      "env": { "DISPATCH_WORKSPACE": "/path/to/the/repo/it/should/serve" }
    }
  }
}
```

The agent then calls `dos_verify` / `dos_arbitrate` / … like any other tool. (This
is the *advisory* surface — the agent can call the referee. To make Gemini CLI
*deny* a tool call on a DOS verdict you want a `BeforeTool` hook, which is the
cross-vendor hook-dialect work in `docs/217`, not MCP.)

### Codex CLI (`~/.codex/config.toml` or project `.codex/config.toml`)

Codex uses TOML `[mcp_servers.<name>]` tables (note the underscore):

```toml
[mcp_servers.dos]
command = "dos-mcp"

[mcp_servers.dos.env]
DISPATCH_WORKSPACE = "/path/to/the/repo/it/should/serve"
```

Or register it without editing the file: `codex mcp add dos --env
DISPATCH_WORKSPACE=/path/to/repo -- dos-mcp`. List active servers with `/mcp` in
the Codex TUI.

### Cursor (`.cursor/mcp.json` project, or `~/.cursor/mcp.json` global)

```json
{
  "mcpServers": {
    "dos": {
      "command": "dos-mcp",
      "env": { "DISPATCH_WORKSPACE": "/path/to/the/repo/it/should/serve" }
    }
  }
}
```

Note Cursor caps the number of *active MCP tools across all servers combined*
(~40 as of early 2026). `dos-mcp` exposes a small handful of syscall tools, so it
fits comfortably — but if you load many MCP servers, keep the total under the cap
or Cursor will silently drop the overflow.

### Google Antigravity (`~/.gemini/config/mcp_config.json`, or via the MCP store UI)

Antigravity registers MCP servers under the same `mcpServers` key. You can edit the
config file directly, or use the IDE: open **Manage MCP Servers** → **View raw config**
and add:

```json
{
  "mcpServers": {
    "dos": {
      "command": "dos-mcp",
      "env": { "DISPATCH_WORKSPACE": "/path/to/the/repo/it/should/serve" }
    }
  }
}
```

For an HTTP server Antigravity uses `serverUrl` (not `url`); `dos-mcp` runs over stdio,
so the `command`/`args`/`env` form above is the one to use. As with Gemini CLI, this is
the *advisory* surface (the agent CALLS `dos_verify` / …). To make Antigravity *deny* a
tool call on a DOS verdict, wire its `PreToolUse` hook with `dos init --hooks antigravity`
(the enforcement half — docs/217 §7 / docs/221 §3c).

> **Two surfaces, both cross-vendor (as of 2026-06-07).** MCP makes DOS a tool the
> agent can *call* on every one of these hosts with zero code change — the
> **advisory** path (the agent asks). Making a host *deny* a call on a DOS verdict is
> the **enforcement** path, which rides each host's own hook seam (Claude Code
> `PreToolUse`, Gemini `BeforeTool`, Codex `PreToolUse`, Cursor
> `beforeShellExecution`, Antigravity `PreToolUse`). That path is **now cross-vendor too** ([docs/217](../../docs/217_the-cross-vendor-hook-dialect-seam.md)
> renderers + [docs/221](../../docs/221_the-cross-vendor-hook-installer.md) installer):
> one command wires the right config file for whichever host you run —
>
> ```bash
> dos init --hooks claude-code .   # .claude/settings.json
> dos init --hooks cursor .        # .cursor/hooks.json
> dos init --hooks codex .         # .codex/config.toml
> dos init --hooks gemini .        # .gemini/settings.json
> dos init --hooks antigravity .   # .agents/hooks.json
> ```
>
> Wire **both**: MCP lets the agent check its own work; the hooks stop a bad action
> before it lands. The MCP snippets above are the advisory half; the `--hooks`
> command is the enforcement half.

## Where this sits in the package

`dos_mcp` is a **consumer of `dos`**, exactly like `scripts/release_*.py` and the
`.claude/` skills. It imports `dos`; **nothing under `src/dos/` imports
`dos_mcp`** — the one-way dependency arrow the layering contract (`CLAUDE.md`)
draws for all tooling. That's why it's a separate top-level package (`dos_mcp`,
not `dos.mcp`): the kernel is deliberately near-stdlib, and folding a server
framework inside it would break that. You can rewrite or delete the whole MCP
surface without touching a single kernel module.
