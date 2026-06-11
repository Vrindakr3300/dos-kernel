# 217 — The cross-vendor hook-dialect seam

> **The verdict is the kernel; the envelope is a driver.** DOS computes one
> dialect-neutral PRE/POST/STOP decision and renders it into the exact bytes the
> *host runtime* honors — Claude Code today, Gemini CLI / Codex CLI / Cursor next —
> the same kernel/driver split as `judges` (pure protocol + by-name resolver) and
> `overlap_policy` (pure scorer + by-name resolver).

*Status: the renderer + all four dialects + tests SHIPPED; the `--dialect` CLI wiring
is built-and-tested but UNCOMMITTED (held by `cli.py` tree contention — see note);
Phases 4–5 (config table + installer + eval) future. As of 2026-06-07.*

> **Shipped (2026-06-07).** `src/dos/hook_dialect.py` — the neutral `HookVerdict` +
> `HookDialect` protocol + four built-in renderers (`claude-code` default / `codex` /
> `gemini` / `cursor`) + a by-name `resolve_dialect` (fail-LOUD on unknown) over a
> `dos.hook_dialects` entry-point group. Pinned by `tests/test_hook_dialect.py` (27
> tests: round-trip floor, golden bytes per host, fail-loud, no-rewrite, end-to-end
> SELF_MODIFY across all four).
>
> **Built but not yet committed (2026-06-07).** The `--dialect` flag on `dos hook
> pretool` / `dos hook posttool` (the CLI transcodes the canonical Claude-Code dict
> from `decide()`/`warn_payload` through the selected renderer). It is implemented and
> manually verified end-to-end (all four hosts emit the right envelope for a real
> SELF_MODIFY deny; a bad name fails loud), and **the Phase-1 gate is met — the
> existing 67-test hook suite is byte-green, unchanged.** It is held back only because
> `src/dos/cli.py` currently carries several concurrent sessions' uncommitted work
> (incl. another session fixing `cmd_hook_stop`'s OWN dialect no-op — the exact bug §0
> cites), and staging it would sweep theirs (the shared-tree pathspec discipline).
> Land the CLI hunks once that file settles.
>
> **Phase 4 installer SHIPPED (2026-06-07, docs/221).** `dos init --hooks
> {claude-code,cursor,codex,gemini}` writes each host's OWN hook-config file
> (`.cursor/hooks.json` / `.codex/config.toml` / `.gemini/settings.json` /
> `.claude/settings.json`), wiring the shipped dialect renderers — merged +
> idempotent, the `--with-hooks` (= `--hooks claude-code`) command byte-identical to
> today. The pure machinery + the `claude-code` baseline live in
> `src/dos/hook_install.py`; the cursor/codex/gemini install-specs live in
> `drivers/hook_dialects.py` (the same kernel/driver split as the renderers),
> discovered via the `dos.hook_installs` entry-point group. Pinned by
> `tests/test_init_hooks_crossvendor.py` (12 tests) + the unchanged
> `test_init_hooks.py` parity floor. See docs/221.
>
> **Not yet built:** the `[hook_dialect]` config table (the OTHER Phase-4 half — pin/
> override an envelope so vendor drift is data, not code) and `dos hook-dialect-eval`
> (§4 Phase 5).

## 0. The finding that motivates this (audit, 2026-06-07)

A "how well does DOS work right now with Gemini / Codex / Cursor" audit (web-grounded
on the three runtimes' current docs + run against this repo) found DOS has **three**
binding surfaces with very different cross-vendor reach:

| Surface | What it is | Cross-vendor reach today |
|---|---|---|
| Kernel syscalls (`verify`/`arbitrate`/`liveness`/`resume`) | adjudicate **git + the lane journal**, never the agent | **Vendor-irrelevant by construction** — ran clean on this repo; the worker's identity is invisible to them |
| MCP server (`src/dos_mcp/`) | DOS-as-a-tool the agent *calls*, JSON over stdio | **Works on all three today** — all three are MCP clients. Advisory only (a tool, not a gate). |
| Hooks (`dos hook pretool`/`posttool`/`stop`) | the **PEP** — deny/observe a call at the runtime seam | **Claude-Code-ONLY.** The renderers emit exclusively the CC `hookSpecificOutput` envelope. |

So **detection and adjudication are cross-vendor; enforcement is not.** The deny path —
the one place DOS actuates a verdict inside a live agent loop — speaks only Claude Code.

This was, until this audit, believed to be *fine*, because DOS's own notes held that
"the arbiter is being designed around / Cursor abandoned shared-write arbitration / CC
is the only runtime with a deny PEP." **That belief is now stale.** As of early–mid
2026 all three rivals ship a deny-capable pre-tool hook that runs an external command:

- **Gemini CLI** v0.26.0 (~Jan 2026): `BeforeTool` hook → `{"decision":"deny"}` (or
  exit 2); `AfterTool` → `hookSpecificOutput.additionalContext`. Registered under
  `hooks` in `~/.gemini/settings.json`. *(Gemini Code Assist, the IDE extension, has
  no hooks — CLI only.)*
- **Codex CLI** (~v0.117, 2026): `PreToolUse` → `permissionDecision:"deny"` (or exit
  2). **Deny-only** (allow/ask are parsed-but-rejected on `PreToolUse`) and fires only
  on the `Bash`/`apply_patch`/`unified_exec`/`mcp` handlers (a coverage gap, tracked
  upstream). Registered under `[[hooks.PreToolUse]]` in `~/.codex/config.toml`. Field
  names are copied from CC almost verbatim.
- **Cursor** 1.7 (2025-09-29): `beforeShellExecution` / `beforeMCPExecution` /
  `preToolUse` → `{"permission":"deny"}` (or exit 2), and it supports
  `"failClosed": true` — a *stronger* fail-direction than CC's fail-open. Registered in
  `.cursor/hooks.json`. *(Cursor 3.0, 2026-04-02, runs parallel agents in git
  worktrees by default → isolated, so the in-app collision the arbiter guards is moot
  there; the residual arbiter value is the merge-back join + non-worktree /
  cross-vendor fleets.)*

**The good news, and the reason this is a small build:** the three vendors copied CC's
hook design. The *stdin* payloads are near-identical (`tool_name` / `tool_input` /
`tool_response`); the *deltas* are (a) the **event-name strings** and (b) the **output
envelope**. DOS's verdict logic is already dialect-neutral — only the final render is
CC-bound. So this is a **renderer seam**, not a rewrite.

> **Caveat to pin (the [[feedback-date-observations-for-staleness]] discipline):** all
> three hook surfaces are < 12 months old and churn every minor release. This plan
> targets the dialects **as of 2026-06-07**; a `[hook_dialect]` config table (Phase 4)
> lets a host pin/override the exact envelope without a kernel edit, so dialect drift
> is a data change, not a code change.

## 1. Where the seam already is (the probe, not the contract)

Probed `src/dos/pretool_sensor.py` and `src/dos/posttool_sensor.py` directly (don't
trust the docstrings — read the call sites). The architecture is *already* split, it
just stops one inch short:

`pretool_sensor.decide(event, cfg, *, handler_name) -> (dialect_or_None, outcome_record)`

- `outcome_record` is **already dialect-neutral**: a dict with
  `decision ∈ {deny, warn, passthrough}`, plus `reason`, `reason_class`, `rung`,
  `intervention`, and (on a provenance BLOCK) the synthetic corrective `ctx`. This IS
  the pure verdict.
- `dialect_or_None` is the CC-specific rendering, built *inside* `decide()` by calling
  `pretool_sensor.deny_payload(reason, additional_context=...)` /
  `pretool_sensor.warn_payload(text)` — both hard-coded to
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": ...}}`.

`posttool_sensor.warn_payload(verdict) -> dict | None` is the same story for POST:
pure verdict in, CC `additionalContext` envelope out.

`cmd_hook_pretool` / `cmd_hook_posttool` / `cmd_hook_stop` in `cli.py` then
`print(json.dumps(payload))` that CC dict as the sole stdout contract.

**So the verdict is the kernel and the envelope is the last step.** The fix is to (1)
let `decide()` / the sensors return the *neutral* verdict, and (2) add a renderer
layer that turns the neutral verdict into the host's envelope, selected at the CLI
boundary. Nothing about the *decision* changes — this is byte-for-byte the existing CC
behavior when `dialect=claude-code` (the default).

## 2. The design — a `HookDialect` renderer, mirroring `judges` / `overlap_policy`

The kernel already has two precedents for "pure protocol in the kernel, ruling
implementation by-name": `dos.judges` (a `Judge` Protocol + `run_judge` +
entry-point resolver + the unshadowable `AbstainJudge` baseline) and
`dos.overlap_policy` (an `OverlapPolicy` Protocol + `admissible_under_floor` +
resolver + the unshadowable `PrefixOverlapPolicy` floor). The hook dialect is the
**third instance of that exact pattern**, on the *output* side.

### 2a. The neutral verdict (new pure type — `src/dos/hook_verdict.py`)

A closed, host-free description of *what the PEP decided*, with no envelope grammar:

```python
class HookMoment(enum.Enum):      # which lifecycle seam
    PRE = "pre"; POST = "post"; STOP = "stop"

class HookAction(enum.Enum):      # the dialect-neutral decision
    DENY = "deny"                 # withhold the call / refuse the stop
    WARN = "warn"                 # add context, do NOT block (turn-preserving)
    PASS = "pass"                 # emit nothing

@dataclass(frozen=True)
class HookVerdict:
    moment: HookMoment
    action: HookAction
    reason: str = ""              # operator-facing why (DENY/WARN)
    context: str = ""            # the corrective fact to re-surface (WARN, or DENY+ctx)
    reason_class: str = ""       # the typed refusal, when structural (SELF_MODIFY, …)
```

This is the same content `outcome_record` already carries — promoted from an ad-hoc
dict to a typed verdict so a renderer can switch on it exhaustively.

### 2b. The dialect Protocol + resolver (new kernel seam — `src/dos/hook_dialect.py`)

```python
class HookDialect(Protocol):
    name: str
    def render(self, v: HookVerdict) -> dict | None: ...   # host envelope, or None for PASS
    def parse_event(self, raw: dict) -> dict: ...           # normalize host event → the
                                                            # canonical {tool_name, tool_input,
                                                            # tool_response, session_id, cwd} shape
```

- Built-in **`ClaudeCodeDialect`** (`name="claude-code"`) — the **default**, and a
  byte-for-byte reproduction of today's `deny_payload`/`warn_payload`. The existing
  hook test-suite must stay green unchanged: that is the floor that proves this seam
  added zero behavior change.
- Built-in **`GeminiDialect`** (`name="gemini"`), **`CodexDialect`** (`name="codex"`),
  **`CursorDialect`** (`name="cursor"`) — the three new renderers (§3).
- `resolve_dialect(name) -> HookDialect` — by-name over a `dos.hook_dialects`
  entry-point group + the four built-ins, fail-to-**`claude-code`** is **wrong** here
  (a host that asked for `cursor` and silently got CC emits a no-op against Cursor) —
  so the resolver **raises** on an unknown name (the operator picked the wrong host;
  surface it, the [[feedback-probe-target-and-verify-reuse-before-building]] honesty).
  *(Contrast `judges`/`overlap_policy`, which fail-SAFE because their fallback is the
  safe direction; a dialect's fallback is not safe, so it fails LOUD.)*

> **Why this does not break the litmus tests.** The renderers are PURE
> (verdict in, dict out, no I/O) and host-free at the *kernel* seam (the Protocol +
> the four built-in dialects name only their own envelope grammar, which is host-ABI,
> not host-*policy* — the same way `stamp.JOB_STAMP_CONVENTION` names a grammar
> without importing a host). A host-specific *ruling* dialect (e.g. a proprietary
> runtime's envelope) would be a `dos.hook_dialects` **plugin** or a `drivers/` module,
> never a kernel edit — identical to `dos.judges` / `dos.overlap_policies`. The
> "kernel imports no host" litmus stays true: a built-in dialect imports no host
> *module*; it emits a host *wire-format*, which is data.

### 2c. The wiring (edit `pretool_sensor` / `posttool_sensor` / `cli.py`)

- `pretool_sensor.decide(...)` returns `(HookVerdict, outcome_record)` instead of
  `(cc_dict, outcome_record)`. The CC dict is no longer built here.
  `deny_payload`/`warn_payload` **stay** (now thin wrappers the `ClaudeCodeDialect`
  calls — so any existing importer of `pretool_sensor.deny_payload` is unbroken).
- `posttool_sensor` grows a `verdict_from_stream(...) -> HookVerdict | None`; its
  `warn_payload` stays as the CC renderer the default dialect uses.
- `cli.py` `cmd_hook_*` gain `--dialect {claude-code,gemini,codex,cursor}` (default
  `claude-code`). The boundary becomes: read event → `dialect.parse_event` → run the
  pure verdict → `dialect.render(verdict)` → `print` (or nothing). `--dialect` is the
  **only** new operator surface; everything else is unchanged.
- `dos init --hooks <host>` (Phase 4) writes the right config block for the chosen
  host (the `settings.json` / `config.toml` / `hooks.json` snippet), closing the
  install-friction gap the same way `dos init --skills` did for SKP.

### 2d. As-built (2026-06-07) — the transcoder, not a `decide()` rewrite

The build took the **cheaper, zero-risk** path the §2 sketch hinted at and §"the
neutral form is the CC dict" in `hook_dialect.py` settles: rather than re-plumb
`decide()`'s four return sites to emit `HookVerdict` (which would have churned the 67
green hook tests that assert `decide()`'s CC shape), `decide()` / `warn_payload` are
**unchanged** and keep returning the canonical Claude-Code dict. The seam **transcodes**
that dict: `hook_dialect.parse_cc(cc_dict, *, moment) -> HookVerdict`, then
`dialect.render(verdict) -> host_dict`. The CC dict is *lossless* for every target
(deny carries reason + optional context, warn carries context, pass is None), so this
loses nothing — and the `ClaudeCodeDialect` round-trips to the same bytes (the Phase-1
gate). `parse_event` (normalizing a *foreign host's* inbound event) was **not** needed
for Phases 1–3: DOS reads a Claude-Code-shaped event on stdin today, and the three
rivals' inbound payloads (`tool_name`/`tool_input`/`tool_response`) are near-identical,
so the existing readers suffice; a host whose *inbound* shape diverges enough to need
normalization is a Phase-3.5 follow-up, not a blocker for *emitting* the right envelope.
`deny_payload`/`warn_payload` stayed as-is (the `ClaudeCodeDialect`/`CodexDialect`
produce the same bytes independently rather than wrapping them — simpler, and it keeps
the renderer pure-of-the-sensor).

## 3. The three new dialects (exact envelopes, as of 2026-06-07)

The verdict→envelope table. `PASS` always renders `None` (emit nothing) for all four.

| `HookAction` | Claude Code (default) | Gemini CLI | Codex CLI | Cursor |
|---|---|---|---|---|
| **DENY** (PRE) | `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":R}}` | `{"decision":"deny","reason":R}` | `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":R}}` | `{"permission":"deny","agent_message":R}` |
| **WARN** (PRE) | `{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":C}}` | `{"hookSpecificOutput":{"additionalContext":C}}` | `{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":C}}` | `{"permission":"allow","agent_message":C}` *(allow + message = pass-with-context)* |
| **DENY** (POST/STOP) | n/a at POST (cannot block); STOP emits the CC stop envelope | `AfterTool`/`AfterAgent` deny shape | `PostToolUse` `block` shape | `stop` is post-hoc (notification) |
| **WARN** (POST) | `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":C}}` | `{"hookSpecificOutput":{"additionalContext":C}}` (`AfterTool`) | `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":C}}` | `afterFileEdit`/`stop` notification context |

Notes that shape the renderers (each is a real per-vendor constraint, not a guess):

- **Codex is nearly CC-identical** — the cheapest dialect; mostly a pass-through of
  the CC envelope. Its one real divergence is **coverage** (only Bash/`apply_patch`/
  `unified_exec`/`mcp` handlers fire `PreToolUse`), which is a *host* limit, not a
  render difference — DOS renders the same bytes; Codex just won't call the hook on
  every tool. Document it; don't try to fix it in DOS.
- **Gemini uses `{"decision":"deny"}`** (not `permissionDecision`) and event names
  `BeforeTool`/`AfterTool` (not `PreToolUse`/`PostToolUse`). `parse_event` must map
  Gemini's `hook_event_name` and (snake_case) payload onto the canonical shape.
- **Cursor uses `{"permission":"deny"|"allow"}`** and a different event taxonomy
  (`beforeShellExecution`/`beforeMCPExecution`/`preToolUse`). A WARN maps to
  `{"permission":"allow", ...message}` (Cursor has no "pass-but-add-context" that
  isn't an allow). Cursor also honors **exit code 2 = deny** and `failClosed` — so the
  Cursor binding doc should recommend `"failClosed": true` (DOS's fail-direction is
  fail-to-PASS internally, but a *host* fail-closed on DOS *crashing* is the operator's
  call — surface the trade-off).
- **The anti-laundering rule survives unchanged.** No dialect ever emits
  `updatedInput` / `updated_input` (Cursor's `preToolUse` *can* rewrite tool input —
  DOS must NOT use it; minting corrective bytes for the agent is the docs/191 §4
  byte-author violation). The renderer for every host carries only `reason` + `context`
  (a fact to re-surface), never a rewritten argument.

## 4. Build order (each rung independently shippable + testable)

1. **Phase 1 — neutral verdict + CC dialect parity (the floor).** Add
   `hook_verdict.py` + `hook_dialect.py` with ONLY `ClaudeCodeDialect`. Rewire
   `decide`/sensors/`cli` to route through it. **Gate: the entire existing hook
   test-suite passes byte-unchanged.** This rung adds zero behavior; it only moves the
   envelope render behind the seam. (Ship it alone — it's the refactor that makes the
   rest a data add.)
2. **Phase 2 — Codex dialect** (cheapest; near-CC). Add `CodexDialect` + `--dialect
   codex` + a golden-bytes test (a fixed `HookVerdict` → the exact Codex JSON). Document
   the handler-coverage limit.
3. **Phase 3 — Gemini + Cursor dialects.** Add `GeminiDialect` / `CursorDialect` +
   their `parse_event` normalizers + golden-bytes tests + a `parse_event` round-trip
   test (a real captured Gemini/Cursor event → the canonical shape → the right
   verdict). This is where the event-name remap lives.
4. **Phase 4 — `[hook_dialect]` config + `dos init --hooks <host>`.** A `dos.toml`
   table to pin/override an envelope (dialect drift = data, not code) and an installer
   that writes the host's config block. Closes install friction (the SKP `--skills`
   analogue).
5. **Phase 5 (eval) — `dos hook-dialect-eval`.** The friendliness instrument (the
   `tool-stream-eval` / `overlap-eval` sibling): replay a corpus of captured host
   events through each dialect and confirm (a) DENY round-trips to the host's
   block-bytes, (b) PASS emits nothing, (c) no dialect ever emits a rewrite key. The
   honesty gate that a dialect is not a silent no-op (the original `dos hook stop`-vs-CC
   bug, generalized to four hosts).

## 5. The litmus tests this plan must keep green

- **Kernel imports no host.** No new module under `src/dos/` (except `drivers/`) names
  a host *module*. The dialects name host *wire-formats* (data), exactly as
  `stamp`/`reasons` name grammars. Grep-checkable.
- **The default is byte-for-byte today.** `--dialect claude-code` (the default) must
  reproduce the current `deny_payload`/`warn_payload` output exactly — the existing
  hook suite is the proof, run unchanged (Phase 1 gate).
- **A wrong dialect fails LOUD, not silent.** `resolve_dialect("typo")` raises; it
  must NOT fall back to CC (a silent CC fallback against a Cursor host is the no-op bug
  this whole plan exists to prevent). New test.
- **No dialect mints corrective bytes.** A golden test per dialect asserts the rendered
  envelope contains no `updatedInput`/`updated_input`/input-rewrite key — the docs/191
  §4 byte-author floor, enforced across all four hosts.
- **PASS emits nothing, everywhere.** `dialect.render(HookVerdict(action=PASS))` is
  `None` for all four; the CLI prints nothing. (The fail-to-passthrough direction is
  preserved per-host.)

## 6. What this does NOT do (scope fence)

- It does **not** make DOS a PEP by default. The default Rung-B handler stays
  `observe` (PDP-only); a behavioral deny still requires a wired ruling handler. This
  plan changes *which runtimes can receive a deny DOS computes*, not *whether DOS denies
  by default*.
- It does **not** chase per-vendor tool-coverage gaps (Codex's partial `PreToolUse`
  handler set; Cursor's incomplete headless-mode hook firing). Those are host limits;
  DOS renders correct bytes and documents the limit.
- It does **not** touch the MCP surface — that is already cross-vendor (a separate,
  zero-code win: ship the per-host wiring snippets in `src/dos_mcp/README.md`, done
  alongside this plan).

## 7. As-built addendum (2026-06-09) — Antigravity, the *hybrid* host

Google **Antigravity** (the agentic IDE + its CLI) is the fifth host, added as a
`dos.hook_dialects` + `dos.hook_installs` plugin pair with **zero kernel change** —
the proof that the seam this doc built generalizes to a new vendor the way it was
designed to (a `drivers/hook_dialects.py` renderer + an install-spec + two
entry-point rows, nothing under `src/dos/*.py`).

Antigravity is interesting because it is a **hybrid of the two grammars DOS already
spoke**, so it exercises a config/output combination none of the first four hosts
did:

| Facet | Antigravity | Looks like |
|---|---|---|
| Config file | `.agents/hooks.json` (workspace-local; a workspace file wins over the global one) | (its own path) |
| Config *shape* | group-wrapped: each event → a list of `{"matcher"?, "hooks":[{"type":"command","command":C}]}` groups (a matcher-less group matches every tool) | **Claude Code** (`json_group_wraps=True`) |
| Event names | `PreToolUse` / `PostToolUse` / `Stop` (also fires `BeforeModel`/`AfterModel`/`SessionStart`/`SubAgentStop`; DOS wires the tool + stop seams) | **Claude Code** |
| Hook *output* | top-level `{"decision":"deny"\|"allow", "reason"?:…}` on stdout | **Gemini** |

So the **install spec is CC-shaped** (`antigravity_install_spec`,
`json_group_wraps=True`) but the **renderer is Gemini-shaped**
(`AntigravityDialect` → `{"decision":"deny","reason":…}`). The wired command carries
`--dialect antigravity` (data on the `HostHookSpec`) so the group-wrapped config
points at the `decision`-grammar renderer — the `dialect_flag`-as-data design (§3a /
docs/221 §3a) is exactly what makes a host that mixes-and-matches the two axes a pure
data row, no `if host == …` branch. The two divergences from CC:

- **Output, not config.** Antigravity reads `decision`/`allow|deny`, not CC's nested
  `permissionDecision`. The renderer emits the Gemini envelope.
- **One operator-facing field.** Antigravity documents only `decision` + `reason` (no
  separate `additionalContext` channel), so a provenance DENY's corrective FACT is
  folded into `reason` (space-joined), and a turn-preserving WARN emits a bare
  `{"reason":…}` with **no** `decision` key (inert to the allow/deny gate). No
  tool-input rewrite key is ever emitted — the docs/191 §4 byte-author floor holds on
  the fifth host exactly as on the first four.

MCP needs nothing host-specific (Antigravity is an MCP client: `mcpServers` in
`~/.gemini/config/mcp_config.json`); the `src/dos_mcp/README.md` wiring snippet
covers it, and `dos guard --mcp-config` injects the server generically. Facts
web-grounded 2026-06-09 (Antigravity hooks docs + the `Migrating to Antigravity CLI`
guide). Pinned by the `antigravity` cases in `tests/test_hook_dialect.py` +
`tests/test_init_hooks_crossvendor.py`; the vendor-blindness litmus
(`tests/test_vendor_agnostic_kernel.py`) stays green because every Antigravity token
lives in the driver.

## 7b. As-built addendum (2026-06-10) — Claude Cowork, the *shared-surface* host

Anthropic's **Claude Cowork** (the agentic desktop app) is the sixth host — and the
degenerate row that proves the seam's other end: it runs the **same Claude Code
agent harness** (in a Linux VM), so its envelope is not "like" CC's, it IS CC's.
`ClaudeCoworkDialect` delegates to the CC renderer (the Codex precedent: an
explicit by-name entry + a home for future divergence), and its install spec wires
the **same `.claude/settings.json`** Claude Code reads, with NO `--dialect` flag —
a shared file must serve both runtimes, and the default IS the envelope. The one
Cowork-specific fact rides the spec's `note` as data: the Cowork app does not
*fire* hooks yet (anthropics/claude-code#63360, as of 2026-06-10) — a host
coverage limit (the Codex kind), not a missing seam (the Trae kind, docs/294).
Full reasoning + facts: [docs/298](298_claude-cowork-the-sixth-host-shared-surface.md).

## 8. Provenance

Audit + probe done 2026-06-07. Vendor facts web-grounded on the three runtimes' then-current
docs (Gemini CLI v0.26.0 hooks; Codex CLI `PreToolUse`; Cursor 1.7/3.0 hooks); Antigravity
added 2026-06-09 (§7). The DOS-side seam (`decide` returns `(dialect, outcome)`;
`outcome_record` already neutral) was read directly from `src/dos/pretool_sensor.py` /
`posttool_sensor.py`, not from the contract. See the [[project-dos-cross-vendor-binding-audit]]
memory and docs/191 (the PRE-division / byte-author floor this dialect seam preserves) +
docs/165 (the CC runtime-binding roadmap this generalizes off Claude Code onto more hosts).
