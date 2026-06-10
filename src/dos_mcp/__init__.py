"""dos-mcp — the DOS syscalls as an MCP server.

This package is the **Model Context Protocol surface** for the DOS kernel: it
exposes `verify` / `arbitrate` / the structured-refusal vocabulary / `doctor` as
MCP tools, so any MCP-speaking agent host (Claude Desktop, Cursor, Cline,
Continue, an Agent-SDK app) can call the DOS referee with **zero Python coupling**
— it speaks JSON over stdio, not `import dos`.

Why it lives OUTSIDE the kernel (the one-way arrow)
===================================================

`dos_mcp` is a **consumer of `dos`**, exactly like `scripts/release_*.py` and the
`.claude/` skills are. It `import dos` (and `mcp`); **nothing under `src/dos/`
imports `dos_mcp`.** That is the same dependency direction the CLAUDE.md layering
contract draws for all dev/integration tooling — the kernel is unaware its MCP
wrapper exists, so the wrapper can be rewritten or deleted without touching a
single kernel module's import graph. It is a *separate top-level package*
(`dos_mcp`, not `dos.mcp`) for that reason: folding it under `dos` would put a
server framework dependency inside the deliberately near-stdlib kernel.

What it exposes (the syscall ABI, faithfully)
==============================================

Each tool is a thin wrapper that builds a `SubstrateConfig` from the caller's
`workspace` argument (honoring that workspace's `dos.toml`, the same four-table
readback the `dos` CLI does) and hands it to the real kernel function via the
explicit-config rung (`oracle.is_shipped(cfg=...)`, `arbiter.arbitrate(config=...)`).
The tools return the kernel verdict's own `to_dict()` — no invented shape:

  * ``dos_verify``         — the truth syscall: did (plan, phase) actually ship,
                             from git/registry evidence rather than self-report?
                             Works against a bare git repo with no plan.
  * ``dos_arbitrate``      — the pure admission kernel: may a worker take this lane
                             given the live leases, or does its file-tree collide?
  * ``dos_refuse_reasons`` — the closed structured-refusal vocabulary (every reason
                             is simultaneously emittable / verifiable / refusable).
  * ``dos_check_reason``   — is THIS reason_class a member of that closed set? (so a
                             producer can only emit a reason the oracle can verify.)
  * ``dos_doctor``         — the machine-readable workspace report (paths / lanes /
                             stamp grammar) an agent reads to discover the layout.

Read-only discipline is preserved: `verify`, the reason tools, and `doctor` write
nothing (the no-`.dos/` contract). `arbitrate` is exposed as a PURE adjudication —
it never captures the `--force` decision side-effect the CLI does, because an MCP
tool should decide, not persist.
"""

from __future__ import annotations

from dos_mcp.server import build_server, main

__all__ = ["build_server", "main"]
