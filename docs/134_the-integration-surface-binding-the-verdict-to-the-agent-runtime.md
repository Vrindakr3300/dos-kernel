# The integration surface — binding the verdict to the agent runtime

> **DOS today is a verdict you must *remember to ask for*: a `dos verify PLAN PHASE`
> you run in a separate step, or an MCP tool the agent must *think* to call. The
> lowest-common-denominator dev wants the opposite — the verdict wired into the
> runtime so it fires *structurally*, at the moment the agent claims it is done,
> with no Python plumbing and ideally one declarative line. This note maps the
> *real* extension surfaces a modern agent host (Claude Code, the Agent SDK)
> exposes — `Stop`/`PostToolUse` hooks, SKILL.md frontmatter `hooks:`, the headless
> `claude -p --settings/--mcp-config` flags, the SDK `canUseTool` callback + the
> in-process MCP server — and specifies how DOS binds `verify`/`arbitrate` to each.
> The headline is the `Stop`-hook verifier: an agent says "shipped AUTH2," the
> hook runs the truth syscall, and on `NOT_SHIPPED` returns `{"ok": false,
> reason}` so the agent *cannot stop on a lie* and is fed the verdict to keep
> working. The one genuinely new component this requires — and the crux the naive
> "just run `dos verify` on stop" idea hides — is a CLAIM EXTRACTOR: the hook
> receives a *transcript*, not `(plan, phase)`, so something must read what the
> agent *claimed* before the oracle can check it. That extractor is the seam; the
> rest is wiring DOS already has.**

A consumer-integration plan in the family of [`80`](80_mcp-server-surface.md) (the
MCP server — the zero-Python-coupling adoption surface this builds *on top of*),
[`126`](126_the-mediated-write-and-the-apply-gate-pep.md) (the apply-gate PEP — the
*write-moment* enforcement point; this note is its *stop-moment* sibling), the
[`74`](74_skill-pack-plan.md) skill pack (the shipped generic `SKILL.md` screenplays
whose frontmatter this note newly exploits), and the DX argument in the sibling
strategy repo (`dos-private/dispatch-os-the-fastapi-of-fleets.md`, the
"hook-it-in-code-not-a-CLI-step" finding this note makes mechanical). It respects
the [`99`](99_runtime-validation-and-the-actuation-boundary.md) advisory-only
boundary with one deliberate, *user-owned* exception noted in §3.

**Status: the keystone + the launcher are SHIPPED; the emitters are the residual.**
`verify`/`arbitrate`/`--json`/the MCP server already existed; this note's build has
landed in three commits: (a) the **launcher verb** `dos guard` (§4) — the argv shim
that injects `--mcp-config`/`--settings` (`src/dos/guard.py` + `cmd_guard`); (b) the
**claim extractor** `dos.claim_extract` (§2.1) — the pure three-rung bridge with the
abstain-never-invent floor; and (c) `dos hook stop` (§2/§2.2) — the verify-on-stop
hook that reads the host event on stdin, extracts the claimed `(plan, phase)`,
verifies each against git, and emits `{"ok": false, reason}` on a NOT_SHIPPED
confident claim. All three are exercised on this repo against frozen transcripts (a transcript
claiming a shipped phase → `ok:true`; a made-up phase → `{"ok": false}` `via none`)
and pinned by 70 tests — which proves the transcript→claim→verify→verdict path, not
that a live host actually honors the `{"ok": false}` at a real `Stop` event (the
emitter/host-binding step is the residual below). **The residual is the emitters** (§6: `dos init --with-hooks` writing
the `.claude/settings.json` fragment) and the **SDK form** (§5: `dos.sdk` behind a
`[sdk]` extra) — neither built. The dogfood proof that the *pattern* works predates
all of it: `.claude/settings.json` here already ships a `Stop` hook that runs
`scripts/trajectory_audit.py` when the agent stops — §2 generalizes exactly that
shape to the verdict.

---

## 1. The facts on the ground (verified, not assumed)

Every integration claim below is grounded in the *actual* current extension surface
of the host, confirmed against the live tooling. The load-bearing facts, with the
real key names — and, as important, the **negatives** that kill the naive designs:

**SKILL.md frontmatter** carries `name`, `description`, `when_to_use`,
`allowed-tools`, `disallowed-tools`, `paths` (a glob that auto-loads the skill on
matching files), `model`, `context: fork`, `agent`, and — the load-bearing one —
a **`hooks:`** object scoped to that skill's lifecycle. The negatives: frontmatter
**cannot run a command on its own** (no `on-invoke`; the only dynamic injection is
preprocessed `` !`cmd` `` substitution into the body), and it **cannot declare an
MCP server**. So a bare `@verify` *token* DOS magically parses is the wrong mental
model — the real, supported shape is a small declared `hooks:` block (which DOS can
emit), or a `!`dos …`` line in the body.

**Hooks** fire on a set of events; the three that matter here are `PreToolUse`
(before a tool runs — can `deny`/`allow`/`ask`), `PostToolUse` (after a tool
succeeds — can `block` + feed a `reason`), and **`Stop` / `SubagentStop`** (when the
agent/subagent finishes). A hook reads a JSON event on **stdin** (carrying
`session_id`, **`transcript_path`**, `cwd`, `hook_event_name`, and for tool events
`tool_name`/`tool_input`); it signals via **exit code** (`0` = no decision, `2` =
block with stderr fed back as feedback) or via a JSON object on stdout. Critically:
a **`Stop` hook can return `{"ok": false, "reason": "…"}` to make the agent keep
working** — the model receives the reason and does *not* stop. It cannot *force* a
stop, which is the correct asymmetry for a fail-closed verifier (it can refuse to
let a *false* "done" end the run; it never silences a real one).

**Headless** (`claude -p`) takes inline-JSON-capable flags: `--settings '<json>'`
(or a path), `--mcp-config '<json>'` (or a path), `--append-system-prompt`,
`--agents '<json>'`, `--allowedTools`, `--permission-mode`, `--output-format
json|stream-json`. There is **no `--hooks` flag** — hooks are passed *inside*
`--settings`. A `--bare` mode skips all auto-discovery (CI-honest: only explicit
flags apply). This is precisely enough to *wrap* a launch (§4).

**The Agent SDK** (`ClaudeAgentOptions`) takes a `hooks` dict of `HookMatcher`s
whose hooks can be **Python/TS callbacks** (not only shell commands), a
`can_use_tool` permission callback returning allow/deny (+ a rewritten input), and
`mcp_servers` — including an **in-process server** built with
`create_sdk_mcp_server` + the `@tool` helper. So an SDK app can mount DOS as an
in-process MCP server *and* as a `canUseTool` PEP with zero subprocess (§5).

**Settings merge**: `.claude/settings.json` (project, git-shareable) <
`.claude/settings.local.json` (local) < CLI flags, with managed/org on top.
Permission rules and hooks **merge** rather than overwrite, and project hooks
**auto-load when the repo is cloned** (after the trust dialog). So DOS can ship a
hook fragment a host repo simply *has* (§6).

**The DOS side**: `dos verify PLAN PHASE` requires the plan/phase as **positional
args** and emits clean machine output under `--json` (`{"shipped": true, "rung":
"…", "source": "…", "sha": "…", …}`); exit `0`/`1`/`2` *is* the verdict. The MCP
server (`dos-mcp`, [`80`](80_mcp-server-surface.md)) already exposes `dos_verify`
and friends over stdio and resolves its workspace via the same
`--workspace`/`$DISPATCH_WORKSPACE`/cwd seam.

The mismatch between the last two paragraphs and the hook facts is the whole design
problem: **a hook is handed a transcript; the oracle wants `(plan, phase)`.** §2.1
is that bridge.

---

## 2. The headline — the `Stop`-hook verifier

The single most useful binding, and the mechanical realization of the
"hook-it-in-code-not-a-CLI-step" finding: a `Stop` hook that refuses to let an agent
end the turn on an unverified "done."

The flow:

1. The agent finishes a turn, narrating something like *"Done — shipped the AUTH2
   endpoint."*
2. The `Stop` hook fires, receiving `{transcript_path, cwd, …}` on stdin.
3. The hook runs a **claim extractor** (§2.1) over the transcript tail → a set of
   `(plan, phase)` claims the agent just asserted (possibly empty).
4. For each claim, the hook runs `dos verify --workspace <cwd> --json PLAN PHASE`.
5. If every claim is `shipped: true` → exit `0` (let the agent stop — honest done).
6. If any claim is `NOT_SHIPPED` → emit `{"ok": false, "reason": "DOS: you claimed
   AUTH2 shipped, but `verify` finds no commit backing it (via none). Land the
   commit or correct the claim."}` → the agent keeps working, fed the verdict.

This is the `@verify` the operator asked for, but realized where it belongs: not as
a token in a file, but as a **structural property of the runtime** — the agent
*cannot* close a turn on a lie, the same move `verify` makes against a worker,
applied to the worker's own stop event. It is fail-closed in the safe direction
(refuses a false done; never suppresses a true one), and it is **zero Python for the
dev** — it ships as a `.claude/settings.json` block (§6) or a `dos`-emitted fragment.

### 2.1 The crux: the claim extractor (the one new component)

The naive "run `dos verify` on stop" hides the hard part: *verify what?* The hook
has a transcript, not arguments. So DOS needs a small new leaf — `dos.claim_extract`
— that reads the last assistant turn(s) of a transcript and returns the
**verifiable claims** an agent made. Three rungs, strongest-first, mirroring the
oracle's own evidence-ladder discipline:

- **Explicit marker (strongest, opt-in).** The agent (or its skill) is instructed
  to end a completed unit with a machine line: `DOS-CLAIM: AUTH AUTH2`. The
  extractor greps it out byte-exactly. This is the place the operator's literal
  `@verify`-style marker lives — but it is the agent *declaring what to check*, not
  a directive DOS executes. Cheapest and most precise.
- **Frontmatter-bound (structural).** When the stop is a `SubagentStop` for a skill
  whose frontmatter declares `dos.plan`/`dos.phase` (a DOS-specific frontmatter
  convention §3 adds), the claim is *known from the skill*, no transcript parsing
  needed — the most reliable rung.
- **Heuristic (weakest, fail-to-skip).** Absent a marker, scan for "shipped/landed
  /done X" patterns. This rung is deliberately *advisory and abstaining*: if it
  cannot confidently extract a `(plan, phase)`, it returns **no claim** and the hook
  exits `0` (let the agent stop). It must never *fabricate* a claim — a false claim
  would make the verifier itself the unreliable narrator it exists to catch
  ([`103`](103_memory-is-an-unverified-agent.md)'s disease, inward).

The extractor is **pure** (`extract_claims(transcript_text, policy) ->
list[Claim]`), the `liveness.classify` posture: the transcript read happens at the
hook boundary, the extraction logic is a testable pure function over frozen text.
Its honesty rule is the load-bearing one: **abstain, never invent** — a `verify`
that runs against a hallucinated `(plan, phase)` is worse than no verifier, so the
weak rung's only failure mode is a *missed* check, never a *false* one.

> **Why this is the crux, stated plainly.** Every "wire DOS into the agent loop"
> idea founders on the same rock: the loop speaks *transcript*, the oracle speaks
> *(plan, phase)*. You either (a) make the agent *declare* the claim in a form the
> extractor can lift byte-exactly (the marker / frontmatter rungs — reliable,
> requires one convention), or (b) *infer* it from prose (the heuristic rung —
> zero-convention, necessarily abstaining). There is no third option that is both
> zero-convention and reliable, and a design that pretends otherwise is hand-waving.
> DOS's answer is to ship all three rungs and let the floor be "abstain."

---

## 3. SKILL.md frontmatter — the dev-types-one-block version

Because `SKILL.md` frontmatter carries a real **`hooks:`** field, a skill author can
bind the verifier to *that skill's* `SubagentStop` declaratively — the closest thing
to the operator's "put `@verify` in the skill.md" that the host actually supports:

```yaml
---
name: ship-the-auth-endpoint
description: Implement and ship AUTH2.
dos.plan: AUTH            # DOS-specific frontmatter convention (this note adds it)
dos.phase: AUTH2          # → the frontmatter-bound claim rung (§2.1), no parsing
hooks:
  SubagentStop:
    - hooks:
        - type: command
          command: "dos hook stop --workspace ."   # the §2.2 hook entrypoint
---
```

Two things make this real rather than aspirational:

1. **`dos hook stop` is a new thin verb** (§2.2) that does the stdin-read →
   extract → verify → `{"ok": false}` dance, so the skill author writes *one line*,
   not a script. It reads `dos.plan`/`dos.phase` from the firing skill's frontmatter
   (passed through the hook context) when present — the reliable rung — and falls
   back to the transcript extractor otherwise.
2. The `dos.plan`/`dos.phase` keys are **DOS's convention layered on top of the
   host's open frontmatter**, not a host feature. They are read by `dos hook stop`,
   ignored by the host. This keeps the contract clean: the host parses its keys, DOS
   parses its keys, and the only coupling is the one `command:` line.

The negative to state honestly: this is **skill-scoped** — the frontmatter `hooks:`
only fires for *that* skill's lifecycle. A repo-wide verifier (every agent, every
turn) is the `.claude/settings.json` form (§6), not the frontmatter form. Frontmatter
is the right surface for "this *particular* unit of work must be verified before the
subagent reports done"; settings is the right surface for "this *repo* never trusts
a bare done."

### 3.1 `dos hook stop` and the actuation boundary

`dos hook stop` is the one place DOS code emits a `{"ok": false}` that *changes
control flow* — which looks, at first glance, like a violation of the
[`99`](99_runtime-validation-and-the-actuation-boundary.md) advisory-only law (the
kernel computes verdicts; it never spawns/kills/forces). It is not, for the same
reason the [`126`](126_the-mediated-write-and-the-apply-gate-pep.md) apply-gate is
not: **the enforcement happens in the *host's* process, at a seam the *user opted
into* by installing the hook.** DOS still only *computes* (`is_shipped` →
`{"ok": false}` is a pure transform of the verdict); the *host* is what declines to
stop. The kernel never reaches out and halts a process — it answers a question the
host asked it at a boundary the user wired. The advisory floor holds: remove the
hook and DOS goes back to pure verdicts. (This is exactly the PDP-with-a-user-owned-
PEP shape the security spine argues for — `dos-private/dispatch-os-security-10x-100x.md`
§10× — wearing an ergonomic hat instead of a security one.)

---

## 4. The headless wrapper — `dos guard -- claude -p …`

For the dev launching agents non-interactively (CI, a batch fleet, a cron), the
integration is a **launcher that injects the wiring and execs the real binary**:

```bash
dos guard --workspace . -- claude -p "implement AUTH2" --output-format json
```

`dos guard` (a new verb) builds the host-flag JSON and `exec`s the underlying
command with it appended:

- **`--mcp-config '<json>'`** — injects the DOS MCP server (`{"dos": {"command":
  "dos-mcp"}}`) so the agent *can* call `dos_verify` mid-run.
- **`--settings '<json>'`** — injects the `Stop`-hook block from §2 (this is the
  *only* way to add a hook to a headless run — there is no `--hooks` flag), so the
  agent *cannot end* on an unverified claim.
- **`--append-system-prompt`** — optionally appends the one instruction that makes
  the marker rung reliable: *"When you complete a unit of work, end with a line
  `DOS-CLAIM: <plan> <phase>`."*

The design points:

1. `dos guard` **does not reimplement the host** — it is a `~30-line` argv shim that
   computes JSON and `exec`s `claude` (or any host that takes the same flags). It is
   a *helper* (layer 3), names no host internals, and degrades to a plain passthrough
   if the host doesn't recognize a flag.
2. It is **opt-in and visible** — the dev typed `dos guard`, so the wrapping is not
   hidden magic; `dos guard --print-config` dumps the exact JSON it would inject for
   inspection.
3. It composes with `--bare`: `dos guard --bare -- claude -p …` produces a fully
   explicit, auto-discovery-free launch — the CI-honest form where *only* the DOS
   wiring and the dev's flags apply.

This is the "wrap a Claude Code headless launch" the operator asked for, made
concrete: DOS doesn't get *inside* the host, it *frames* the launch with the two
flags (`--mcp-config`, `--settings`) that the host already honors.

---

## 5. The SDK form — `canUseTool` + an in-process MCP server

For an app built on the Agent SDK (TS/Python), the integration is **two callbacks,
zero subprocess**:

- **In-process MCP server.** `create_sdk_mcp_server(name="dos", tools=[verify_tool,
  arbitrate_tool])` where each `@tool` calls straight into `dos.oracle.is_shipped` /
  `dos.arbiter.arbitrate` — no `dos-mcp` process, no stdio. Mount it in
  `ClaudeAgentOptions(mcp_servers={"dos": server})`. The agent calls
  `mcp__dos__verify` in-process.
- **`canUseTool` as a write-moment PEP.** A permission callback that, before a
  `Bash(git commit …)` or an `Edit`, consults `dos.arbiter.arbitrate` for the lane
  and returns `deny` on a collision — the [`126`](126_the-mediated-write-and-the-apply-gate-pep.md)
  apply-gate, realized as an SDK callback instead of a CLI gate. And a `Stop` hook
  *as a Python callback* (the SDK allows callbacks, not only shell commands) that
  runs the §2 verify-on-stop logic in-process.

DOS should ship these as a tiny importable helper — `dos.sdk` (a new layer-3
module): `dos.sdk.mcp_server()` returns the configured in-process server, and
`dos.sdk.verify_on_stop(plan, phase)` returns a ready `HookCallback`. The SDK app
writes:

```python
from dos import sdk
options = ClaudeAgentOptions(
    mcp_servers={"dos": sdk.mcp_server(workspace=".")},
    hooks={"Stop": [HookMatcher(hooks=[sdk.verify_on_stop_from_transcript(workspace=".")])]},
    can_use_tool=sdk.arbitrate_writes(workspace="."),
)
```

This is the FastAPI-grade Python ergonomic from the strategy sibling, made literal:
the dev mounts DOS in three lines of *options*, and the verdict is now structural in
their SDK loop. `dos.sdk` imports the host SDK lazily (it's an optional `[sdk]`
extra, the `[mcp]` precedent), so the core kernel's PyYAML-only dependency floor is
untouched.

---

## 6. The clone-and-it-works form — a shipped `.claude/settings.json` fragment

The lowest-buy-in form of all: a host repo that simply *contains* the hook, so any
agent run in that repo is verified with no per-launch action. DOS ships an emittable
fragment (and `dos init --with-hooks` writes it):

```jsonc
// .claude/settings.json  (project-level, git-shareable, auto-loads on clone)
{
  "hooks": {
    "Stop": [
      { "hooks": [{ "type": "command", "command": "dos hook stop --workspace ." }] }
    ]
  }
}
```

This is byte-for-byte the shape this very repo *already* uses to run its trajectory
audit on `Stop` (`.claude/settings.json` here) — so the pattern is dogfood-proven;
§6 only swaps the audit command for the verify hook. Because project hooks merge and
auto-load on clone (after the trust dialog), a team adopting DOS gets the verifier by
*cloning*, not by configuring. The honest caveats: it requires the user to accept the
workspace-trust dialog (correct — an auto-running hook *should* require consent), and
it is `cwd`-scoped to the repo (the workspace seam handles that).

---

## 7. The five points, ranked by buy-in (the adoption ladder)

The same continuum the [`fastapi-of-fleets`](../../dos-private/dispatch-os-the-fastapi-of-fleets.md)
strategy doc argues for, made mechanical — pick the shallowest that fits:

| # | Surface | Dev action | Buy-in | Enforcement point |
|---|---|---|---|---|
| 6 | `.claude/settings.json` fragment | clone the repo (or `dos init --with-hooks`) | **lowest** | `Stop` hook, repo-wide |
| 2 | The `Stop`-hook verifier | accept the trust dialog | low | `Stop` hook |
| 3 | SKILL.md `hooks:` + `dos.plan/phase` | one frontmatter block | low | `SubagentStop`, per-skill |
| 4 | `dos guard -- claude -p …` | prefix the launch | medium | injected `--settings`/`--mcp-config` |
| 5 | SDK `sdk.mcp_server()` + `canUseTool` | three lines of options | medium (writing an SDK app) | in-process callbacks |

Note the property the table makes visible: **enforcement moves from "the dev runs a
command" (today) to "the runtime fires it structurally" (all five rows).** That is
the entire point — the verdict stops being a thing you remember and becomes a thing
the loop *does*.

---

## 8. Build order

1. **`dos.claim_extract`** (§2.1) — the pure extractor + its three rungs +
   abstain-never-invent floor. Pinned by frozen-transcript tests (the
   `liveness.classify` posture). *This is the keystone; everything else assumes it.*
2. **`dos hook stop`** (§2.2/§3.1) — the thin CLI verb: read stdin event → extract →
   `verify --json` → emit `{"ok": false, reason}` or exit `0`. The `{"ok": false}`
   transform is pure over the verdict.
3. **The emitted fragments** (§6) — `dos init --with-hooks` writes the
   `.claude/settings.json` block; `dos hook stop --print-config` dumps it.
4. **`dos guard`** (§4) — the argv shim + `--print-config`.
5. **`dos.sdk`** (§5) — the in-process MCP server + the `canUseTool`/`Stop`
   callbacks, behind a `[sdk]` extra.

Phases 1–3 are the minimum viable binding (the `Stop`-hook verifier, the headline).
4–5 broaden the surface. None touches a kernel verdict module — `claim_extract` is a
new pure leaf, the rest are helpers/drivers and emitted data, so the litmus tests
(kernel imports no host; advisory-only holds via the user-owned PEP) stay green by
construction.

---

## 9. The honest negatives (what this is *not*, and what could go wrong)

Stated up front, the same discipline the kernel applies to agents:

- **There is no magic `@verify` token DOS parses out of a SKILL.md and auto-runs.**
  The host's frontmatter cannot run a command. The real shape is a declared `hooks:`
  block (which DOS emits) plus an optional `DOS-CLAIM:` marker the *agent* writes.
  "Simpler is better" lands as *one emitted block + one optional marker line*, not a
  bare decorator the way `@app.get` works in Python. Calling it `@verify` is a
  helpful *metaphor* for the marker rung; it is not a literal host feature.
- **The claim extractor is the soft spot.** Its weak (heuristic) rung can *miss* a
  claim (then the agent stops unverified — a false negative, the safe direction) but
  must never *fabricate* one (a false positive would make the verifier lie). The
  whole component's correctness reduces to "abstain when unsure," and that must be
  adversarially tested.
- **A `Stop` hook cannot *force* a stop.** It can only refuse to let a *false* done
  end the run. That is the correct asymmetry, but it means DOS-via-hook cannot kill a
  runaway — that remains [`99`](99_runtime-validation-and-the-actuation-boundary.md)/
  `dos watch`'s advisory job (record + propose), not this note's.
- **Hook/SDK surfaces are host-version-coupled.** Unlike `verify` (pure git), these
  bindings depend on the host's current hook schema and flag set (§1). They belong in
  **drivers/helpers**, never the kernel — and `dos guard` must degrade to a
  passthrough when a flag is unrecognized, so a host upgrade can't wedge a launch.
- **MCP-server-as-hook is not a thing.** The MCP server makes `dos_verify`
  *callable*; it does not make verification *automatic*. Automation requires a hook
  (§2) or a wrapper (§4). The two compose — MCP for "the agent can ask," hook for
  "the runtime insists" — but neither substitutes for the other.

The bet, like every adoption argument: the distance between *"I felt the pain"* and
*"the runtime catches it for me"* is currently a `dos verify` you have to remember.
This note closes that distance to a single emitted hook block — and names, rather
than hides, the one new thing (claim extraction) that closing it actually costs.
