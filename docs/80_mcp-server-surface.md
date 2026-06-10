# The MCP server — DOS as a tool any agent can call

> **The kernel is the part that doesn't believe the agents. This is the door
> through which the agents reach it.**

The genericization series (`docs/70`–`75`) made the syscalls *domain-free* — a
stranger can point DOS at their own repo and have `verify`/`refuse`/`arbitrate`
work without adopting any host convention. This note is the next question after
that one: **once the syscalls are domain-free, how does a neighboring system
actually adopt them?** The answer that lowers the integration cost the most is a
**Model Context Protocol server** — `verify` / `arbitrate` / the refusal
vocabulary / `doctor` exposed as MCP tools, so any MCP-speaking host (Claude
Desktop, Claude Code, Cursor, Cline, an Agent-SDK app) can call the referee with
**zero Python coupling**. It speaks JSON over stdio; it never asks the adopter to
`import dos`.

The thesis in one line: **the JSON tool surface, not the Python API, is the
product boundary for outsiders — so the highest-leverage adoption move is to make
that surface excellent and let the host's own agent drive it.**

This is a *surface* note (like RND `docs/72` / SKP `docs/74`), not a theory note —
it documents a shipped thing and the contract it must keep.

---

## 1. Where it lives, and the one-way arrow

`src/dos_mcp/` is a **consumer of `dos`**, exactly like `scripts/release_*.py`
and the `.claude/` skills. It `import dos` (and `mcp`); **nothing under
`src/dos/` imports `dos_mcp`.** That is the same dependency direction `CLAUDE.md`
draws for all tooling — the kernel is unaware its MCP wrapper exists, so the
wrapper can be rewritten or deleted without touching a single kernel module's
import graph. Pinned grep-checkably (`import dos_mcp` / `from dos_mcp` must not
appear under `src/dos/`) and by `tests/test_mcp_server.py`.

The one wrinkle versus `scripts/`/`​.claude/`: `dos_mcp` **is shipped**. It sits
under `src/`, so `find` packages it and `pip install dos-kernel[mcp]` installs
it, whereas the release scripts/skills ship with the repo but not in the wheel.
So it is a **separate shipped top-level package** — deliberately `dos_mcp`, not
`dos.mcp`. Folding it under `dos` would force a server framework into the
near-stdlib kernel and into every plain `pip install dos-kernel`. Instead the
`mcp` dependency lives only in the `[mcp]` extra; the kernel's own dependency set
stays PyYAML-only.

> **Litmus:** an edit to `src/dos_mcp/` is never an edit to the substrate. The
> MCP surface is its own workstream, the way release tooling is.

---

## 2. The tools — the syscall ABI, faithfully

Each tool is a thin wrapper that builds a `SubstrateConfig` from the caller's
`workspace` argument and hands it to the real kernel function via the
explicit-config rung (`oracle.is_shipped(cfg=…)`, `arbiter.arbitrate(config=…)`).
The tools return the kernel verdict's own `to_dict()` — no invented shape.

| Tool | Syscall | Answers |
|---|---|---|
| `dos_verify(plan, phase, workspace=".")` | `verify()` | Did (plan, phase) actually ship — from registry/git evidence, never self-report? Works on a bare repo with no plan. |
| `dos_arbitrate(lane, kind, tree, live_leases, force=False, workspace=".")` | `arbitrate()` | May this worker take this lane, or does its file-tree collide with a live lease? Pure — never persists. |
| `dos_refuse_reasons(workspace=".")` | `refuse()` | The closed refusal vocabulary (each reason simultaneously emittable / verifiable / refusable). |
| `dos_check_reason(reason_class, workspace=".")` | `refuse()` | Is THIS reason a member of that set? (an unknown one is `UNCLASSIFIED` drift). |
| `dos_doctor(workspace=".")` | — | The machine-readable workspace report (paths / lanes / stamp grammar) to discover the layout. |

Every tool honors the workspace's `dos.toml` — the same four-table readback
(`[lanes]`/`[paths]`/`[stamp]`/`[reasons]`) the CLI does — so pointing the server
at a foreign repo Just Works: its taxonomy drives `dos_arbitrate`, its ship
grammar drives `dos_verify`, its declared reasons appear in `dos_refuse_reasons`.

### The config-layering is shared, not copied

The CLI (`cli._apply_workspace`) and the server (`dos_mcp._load_workspace_config`)
both call ONE implementation — `config.load_workspace_config(workspace, *, job,
warn)`. They used to carry byte-identical readback loops, which is exactly the
drift the registry-as-data design exists to kill. The only divergence is what
each does with the result: the CLI `set_active`s it (a one-shot process);
the **server passes it explicitly into each syscall** and never mutates a
process-global, because a long-lived server fields concurrent calls against
different workspaces. `test_server_and_cli_resolve_identical_config` pins that the
two surfaces produce the same config from the same `dos.toml`.

---

## 3. Built for agents (the Claude-friendly surface)

A faithful wrapper is necessary but not sufficient: the surface is shaped so an
agent reaches for the right tool at the right moment, and so a *user* can drive it
directly from the host UI.

- **"USE THIS WHEN…" triggers.** Every tool description leads with the situation
  that should make the agent call it ("another agent *claims* a task is done…",
  "you are about to touch files other agents may be editing…"). Agents select
  tools from descriptions; the trigger is what makes the selection happen.

- **Actionable `interpretation` fields.** Each decision tool returns an
  `interpretation` string ALONGSIDE the kernel's verbatim verdict — a one-line
  "what this means for your next action" (`dos_verify` on no evidence: *"Treat it
  as not done. Do NOT accept a worker's claim that it shipped without
  evidence."*). The kernel fields are never rewritten; the hint is strictly
  downstream of the decided verdict, so it obeys the renderer invariant
  (`docs/76` / HACKING Axis 4) — it can never leak policy back into the
  adjudication. The worst a wrong hint can do is read awkwardly.

- **Prompts — user-invokable entry points.** `verify_a_claim`,
  `can_i_take_this_lane`, `refuse_with_a_reason` surface in the host (e.g. as
  `/`-commands in Claude Desktop) so a user drives DOS without knowing tool names;
  each returns a short instruction that teaches the agent the right tool +
  sequence.

- **Resources — browsable context.** `dos://reasons` and `dos://lanes` (plus
  `…/{workspace}` templated variants) render the refusal vocabulary and lane
  taxonomy as markdown a host can *read* as context, not only call.

> **Design rule (same as a renderer):** the `interpretation`/prompt/resource text
> is presentation. It is handed an already-decided verdict (or reads already-
> declared config) and returns prose. It decides nothing. This is why adding it
> is safe — it sits on the same side of the line as `dos.render`.

---

## 4. Read-only discipline carries through

The no-`.dos/` contract (`docs/75` §6.5) holds across the MCP layer: `dos_verify`,
the reason tools, and `dos_doctor` write nothing — run them against a stranger's
repo and no `.dos/` appears (pinned by `test_{verify,doctor}_tool_writes_no_dos_dir`).
`dos_arbitrate` is a **pure adjudication**: unlike `dos arbitrate --force` on the
CLI, the tool never captures the force-override decision — an MCP tool decides, it
does not persist. (If a future version wants the decision-capture side effect, it
should be an explicit, separately-named tool, not a silent write on `force=True`.)

---

## 5. Install & wire

```bash
pip install 'dos-kernel[mcp]'   # dist name is dos-kernel; the server is an optional extra
dos-mcp                         # serve over stdio (what an MCP host launches)
```

Host config (Claude Desktop / Claude Code):

```json
{ "mcpServers": { "dos": {
    "command": "dos-mcp",
    "env": { "DISPATCH_WORKSPACE": "/path/to/the/repo/it/should/serve" } } } }
```

`DISPATCH_WORKSPACE` sets the default `workspace` for every tool (overridable
per-call). See `src/dos_mcp/README.md` for the full snippet + the module-form
fallback.

---

## 6. The open seams (named honestly)

- **`spawn`/`reap` are not exposed.** The correlation spine (run-ids, the lane
  journal) is a writing surface; the MCP tools today are the read-only/pure
  syscalls plus `arbitrate`. A `dos_lease` tool that actually persists a lease
  (and therefore creates `.dos/`) is a deliberate next step, not an oversight —
  it crosses from "pure adjudication" into "stateful effect," which wants its own
  design pass (idempotency, the host's lease lifecycle).
- **No streaming / progress.** A long `verify` over a large history is a single
  blocking call. Fine today; if a host wants incremental output it maps onto MCP
  progress tokens later.
- **Overlap with TOA (`docs/78`).** The `refuse` tools are the MCP expression of
  the same structured-refusal on-ramp the typed-outcome-adoption note pitches as
  "DOS's `tsconfig.json`." They should stay aligned: if TOA adds a reason
  `--check` rail, `dos_check_reason` is its natural agent-facing surface.

---

## See also

- `src/dos_mcp/README.md` — the host config snippet + the tool/prompt/resource
  catalog.
- [`CLAUDE.md`](../CLAUDE.md) — the layering contract; the MCP server is fenced
  off as a consumer with its own litmus.
- [`HACKING.md`](HACKING.md) — calling-vs-extending: the MCP server is the
  agent-facing way to *call* DOS, distinct from the four ways to *extend* it.
- `docs/78_typed-outcome-adoption-plan.md` — the structured-refusal on-ramp the
  `refuse` tools express.
