# 269 — Antigravity, the fifth host (full support, zero kernel change)

> **A vendor is a data row.** Adding Google Antigravity — the agentic IDE and its
> CLI — to DOS's cross-vendor binding is the clean confirmation that the seams built
> in docs/217 (the dialect renderer) and docs/221 (the installer) generalize the way
> they were designed to: a `drivers/hook_dialects.py` renderer + an install-spec +
> two `pyproject.toml` entry-point rows, and **nothing under `src/dos/*.py` changes.**

*Status: SHIPPED. As of 2026-06-09.*

## 0. What "full support for Antigravity" means here

DOS binds to an agent runtime on three surfaces (docs/217 §0, the
[[project-dos-cross-vendor-binding-audit]] finding):

1. **Kernel syscalls** (`verify`/`arbitrate`/`liveness`/…) — vendor-agnostic by
   construction (they adjudicate git + the lane journal, never the agent). Antigravity
   gets these for free, like every host.
2. **The MCP server** (`dos_mcp`) — the *advisory* path, the agent CALLS the referee.
   Antigravity is an MCP client (`mcpServers` in `~/.gemini/config/mcp_config.json`),
   so this is a zero-code win: a wiring snippet in `src/dos_mcp/README.md`, plus the
   generic `dos guard --mcp-config` injection.
3. **Hooks** — the *enforcement* path, the runtime DENIES a call on a DOS verdict.
   This is the only surface that needs per-vendor code, and it is what this note is
   about: a **dialect renderer** (the bytes the verdict becomes) + an **install spec**
   (where/how those bytes wire into the host's own config file).

So "full support" = the enforcement surface joins the advisory + kernel surfaces
Antigravity already had. After this change `dos init --hooks antigravity` wires the
three DOS hooks, `dos doctor` reports the binding, and `dos hook pretool --dialect
antigravity` emits the bytes Antigravity honors.

## 1. The facts (web-grounded 2026-06-09)

Confirmed across the Antigravity hooks docs, the *Migrating to Antigravity CLI* guide,
and the feature deep-dive (event names corroborated across two independent sources).
Like every vendor's hook surface these churn per release — pin and re-verify.

| Facet | Antigravity |
|---|---|
| Hook config file | `.agents/hooks.json` (workspace-local; a workspace file wins over the global one) |
| Config format | JSON |
| Config *shape* | group-wrapped, **Claude-Code-style**: each event → a list of `{"matcher"?, "hooks":[{"type":"command","command":C}]}` groups (a matcher-less group matches every tool) |
| Tool/stop event names | `PreToolUse` / `PostToolUse` / `Stop` (also `BeforeModel` / `AfterModel` / `SessionStart` / `SubAgentStop`; DOS wires the tool + stop seams) |
| Hook *output* grammar | top-level **`{"decision":"deny"\|"allow", "reason"?:…}`** on stdout — **Gemini-style**, not CC's nested `permissionDecision` |
| MCP config | `~/.gemini/config/mcp_config.json` (`mcpServers`; `serverUrl` for HTTP) |

## 2. Why Antigravity is the *hybrid* host

The first four hosts kept two axes aligned: a host that used CC's *config shape* also
used CC's *output grammar* (Codex), and a host with its own output grammar also had
its own config shape (Gemini's flat list, Cursor's `permission`). Antigravity **mixes
them**:

- **Config shape = Claude Code** → the install spec is `json_group_wraps=True`,
  byte-shaped exactly like `claude_code_spec()`.
- **Output grammar = Gemini** → the renderer emits `{"decision":"deny","reason":…}`,
  so the wired command must carry `--dialect antigravity`.

This is the case the **`dialect_flag`-as-data** design (docs/221 §3a) was built for. A
`HostHookSpec` carries its renderer choice as a *data field*, so a host that wants CC's
config grammar with a non-CC output grammar is still a pure data row — `command_for`
appends the flag and never compares `self.host` against a literal. Had the installer
chosen a renderer by branching on the host name, Antigravity would have forced a new
branch; because it reads a data field, it forces only a new row.

## 3. The two design choices in the renderer

Antigravity's documented output vocabulary is just `decision` + `reason` — there is no
separate `additionalContext` channel (the one Gemini reuses for a re-surfaced fact).
So `AntigravityDialect`:

- **Folds the corrective FACT into `reason`.** A provenance DENY carries a `reason`
  (the operator-facing why) and may carry a `context` (a fact to re-surface). With no
  second field to put it in, the two are space-joined into `reason`. This is still the
  docs/191 §4 byte-author floor: the fact is *re-surfaced to read*, never minted as a
  rewritten tool argument (no `updated_input`/`updatedInput` key is ever emitted).
- **Renders a WARN as a bare `{"reason":…}` with no `decision` key.** A turn-preserving
  WARN must add context without withholding the call. Omitting `decision` leaves the
  allow/deny gate untouched (inert), so the note rides along without blocking — the
  same fail-to-passthrough direction every other dialect takes.

PASS renders `None` (emit nothing), like all hosts.

## 4. The change set

- `src/dos/drivers/hook_dialects.py` — `AntigravityDialect` (renderer) +
  `antigravity_install_spec()` (install facts). Both in the driver, because each names
  the vendor as code, which the vendor-blindness litmus forbids in a kernel module.
- `pyproject.toml` — two entry-point rows: `antigravity =
  dos.drivers.hook_dialects:AntigravityDialect` under `dos.hook_dialects`, and
  `antigravity = …:antigravity_install_spec` under `dos.hook_installs`.
- `src/dos/cli.py` — help-text only (the `--hooks` choices come from `host_names()`
  and the `--dialect` arg resolves by name, so both pick Antigravity up by discovery;
  only the prose enumerations were updated).
- Tests: `tests/test_hook_dialect.py` (Gemini-shaped output bytes, the
  context-folds-into-reason rule, the bare-reason WARN, PASS, no-rewrite-key) +
  `tests/test_init_hooks_crossvendor.py` (CC-shaped `.agents/hooks.json`, the
  `--dialect antigravity` flag, idempotency).
- **The Go fast-path** (see §4.5): `go/internal/hook/dialect_transcode.go` +
  `--dialect` threaded through `main.go`/`run.go`/`decide.go`, with
  `go/internal/hook/parity_dialect_test.go` pinning the Go bytes to Python's.
- Docs: docs/217 §7, docs/221 §3c, `src/dos_mcp/README.md`, and this note.

## 4.5. Closing the Go fast-path fail-OPEN (was docs/268's open gap)

The native Go `dos-hook` binary is the latency fast-path the Claude-Code plugin wires
(docs/124/125): it serves a hook decision in ~10 ms vs ~0.3–0.8 s for a Python spawn.
docs/268 found that it **silently ignored `--dialect`** and emitted the Claude-Code
envelope unconditionally — so pointing a non-CC host at the fast binary was a
**fail-OPEN**: the host receives `hookSpecificOutput` bytes, finds no top-level
`decision` key, and **proceeds**. A correctly computed SELF_MODIFY deny would be
dropped — the agent could rewrite the very kernel adjudicating it. For Antigravity
specifically, "full support" is hollow if the recommended fast path drops the deny, so
this is closed here, exactly per docs/268's design:

- **`dialect_transcode.go`** ports the Python `parse_cc` + per-host renderers into Go.
  The CC dict the decider already builds (`denyPayload`/`warnPayload`/`postWarnPayload`)
  stays the dialect-NEUTRAL lingua franca; `transcodeCC(cc, dialect)` re-renders it into
  the host envelope. So the verdict is still computed vendor-blind — only the OUTPUT
  branches on the by-name dialect, downstream of the decided verdict (exactly where the
  vendor-agnostic-kernel litmus says a vendor name belongs).
- **`Decision.Dialect` and the durable journal stay CC byte-for-byte**, so every
  existing parity test (which gates the CC projection) passes unchanged. Only the
  *stdout* render (`Decision.RenderAs(dialect)`) is new; `--dialect`/empty/`claude-code`
  is byte-identical to before (the parity floor).
- **No entry-point machinery** (unlike the Python side): the four non-CC dialects are
  kernel-known closed data that ship in the binary, so a plain `switch` is the whole
  mechanism. Go has no third-party driver-registration story here, and does not need
  one — the split that matters (verdict blind; output by data) survives the switch.
- **Fail-safe, not fail-loud:** an unknown dialect degrades to the CC bytes rather than
  crashing (the hot-path binary must never die on a host's argument; `parseFlags` drops
  unknown flags by the same rule). The honest typo-guard is still the Python resolver at
  `dos init --hooks` time, which only ever writes a KNOWN `--dialect`.

Verified end-to-end: a SELF_MODIFY event through the Go binary with `--dialect
antigravity` now emits `{"decision":"deny",…}` (byte-identical to `dos hook pretool
--dialect antigravity`), where before it emitted CC bytes Antigravity ignores. Pinned
by `parity_dialect_test.go` (golden bytes captured from the live Python renderers for
all five hosts) — the docs/124 parity contract extended from "the CC projection" to
"every dialect projection." The fast path and the Python fallback can no longer drift.

## 5. The litmus tests this keeps green

- **Kernel imports no host / names no vendor in code.** Every Antigravity token lives
  in `drivers/`; `tests/test_vendor_agnostic_kernel.py` stays green (8/8) — no new
  entry in `_VENDOR_CODE_EXCEPTIONS`, because the driver is allowed to name vendors.
- **A wrong host/dialect fails LOUD.** `resolve_dialect("antigravty")` /
  `host_spec("antigravty")` still raise; Antigravity adds a name, not a silent
  fallback.
- **The default is byte-for-byte today.** `--dialect claude-code` / `--with-hooks` are
  untouched; the existing `test_init_hooks.py` parity floor is unaffected.
- **No rewrite key, on the fifth host too.** The no-`updated_input` golden test is
  parametrized over every dialect, Antigravity included.

## 6. Scope fence (what this does NOT do)

- It does **not** make DOS a PEP by default — the wired `PreToolUse` hook runs `dos
  hook pretool`, whose default posture is observe/deny-only-on-structural-refusal
  (SELF_MODIFY et al.). This adds *which runtime can be wired*, not *whether DOS denies
  by default*.
- It does **not** wire Antigravity's `BeforeModel`/`AfterModel`/`SessionStart`/
  `SubAgentStop` events — DOS's three lifecycle moments map onto the tool + stop seams;
  the others are future surface if a verdict ever needs them.
- It does **not** chase per-vendor tool-coverage gaps — host limits; DOS renders
  correct bytes and documents the seam.

## 7. Provenance

Implements the docs/217 dialect seam + docs/221 installer for a new host, and closes
the docs/268 Go fast-path dialect gap (§4.5) for that host (and every non-CC host
along the way). Antigravity config/output facts web-grounded 2026-06-09 (Antigravity
hooks docs; the *Migrating to Antigravity CLI* guide; the feature deep-dive). The
DOS-side mechanics (the `dialect_flag`-as-data design, the group-wrap merge, the
entry-point discovery, the Go decider's CC-neutral-dict shape) were read from
`src/dos/hook_install.py` / `hook_dialect.py` / `drivers/hook_dialects.py` /
`go/internal/hook/decide.go`, not from the contract. See
[[project-dos-cross-vendor-binding-audit]] and
[[project-dos-vendor-seam-kernel-driver-split-rule]].
