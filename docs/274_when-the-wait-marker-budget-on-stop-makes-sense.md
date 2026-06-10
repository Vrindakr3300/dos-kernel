# 274 — When the wait-marker budget on a Stop hook actually makes sense

> **Status:** FIXED (2026-06-09, commit `68c2499`). The wait-marker budget
> (`loop_decide.wait_marker_budget` + `marker_sensor` + `dos hook marker`, docs/259)
> was wired as an **unconditional second `Stop` hook** in
> `claude-plugin/hooks/hooks.json` (commit `bf17aaf`). On a bare `Stop` hook it
> **inverted its own purpose**: a cost-guard meant to *cap* keep-alive polling instead
> *manufactured* up to `max_markers` forced keep-alive turns on **every ordinary
> turn**. The fix: the budget now **arms only inside a loop** (a `--loop` flag, or the
> `DOS_LOOP`/`CID_RUN_ID` env a dispatch loop sets) and honors `stop_hook_active`; on
> any ordinary turn it allows the stop. The shipped plugin now wires only the
> evidence-gated `dos hook stop` — the budget is **opt-in**, a loop-local binding. This
> doc is the *why*, the when-it-is-right, and the use-case matrix (§The use-case
> matrix) — the mechanism must be opt-in and case-scoped, never a global default,
> because **not every setup wants the same thing**.

## The observed failure (what "coming up when it shouldn't" was)

A `/goal …` prompt was rejected with:

> UserPromptSubmit operation blocked by hook: **DOS wait-marker budget: wait-marker
> 2/4 — turn held open.** …

The block text is `cmd_hook_marker`'s budget-remains branch (`cli.py:4388`). The
prompt was rejected because the **previous** turn's `Stop` was being held open by
the marker hook, so the next `UserPromptSubmit` could not land.

The durable tally is unambiguous. In a **64-minute window** (12:52–13:56),
`.dos/markers/` held **44 distinct session files**, with this distribution of final
marker counts:

| markers reached | sessions |
|---|---|
| **4 / 4** (full wall) | **35** |
| 2 / 4 | 8 |
| 1 / 4 | 1 |
| any `RESET` record | **0** |

This is the tell. **A real poll-loop is ONE session with a burst.** What we have is
**44 separate, ordinary sessions each force-blocked up to the cap.** The mechanism
did not catch waste — it *generated* it: every session paid for up to 4 full
context-replay assistant turns producing nothing but "turn held open." That is
precisely the `4b4ff97c` pathology docs/259 set out to kill (252 markers / ~$7.80),
re-created by the guard itself, fanned across the whole fleet of sessions.

## Why it inverts — the load-bearing fact docs/259 never stated

`docs/259` assumed, implicitly, that **a `Stop` hook fires only when the loop is
choosing not to stop** — i.e. on a deliberate keep-alive *poll* turn
(`marker_sensor.py:44-58`: *"A keep-alive wait-marker is the loop CHOOSING NOT TO
STOP"*). The polarity is built on that premise:

- budget **remains** → `{"decision":"block"}` → hold the turn open one more marker;
- budget **spent** → emit nothing → allow the stop.

The premise is **false**. Per the Claude Code hooks reference (confirmed
2026-06-09):

> **Stop** | When Claude finishes responding

and

> `Stop` | `"decision": "block"` | **Prevents Claude from stopping, continues the
> conversation**

So the `Stop` hook fires when Claude finishes **any** turn — a normal interactive
answer, a headless response, *everything* — and a `block` **forces the agent to keep
working**. The marker hook has **no signal at the bare `Stop` event** that
distinguishes:

- *a deliberate keep-alive poll turn* (the loop re-invoked itself only to wait on a
  background task it cannot observe) — **the case the budget is for**, from
- *a finished turn that did real work and is legitimately done* — **every other
  turn**.

Lacking that signal, it treats **every** finished turn as a poll-wait and blocks it
up to `max_markers`. The cost guard becomes a cost *generator*. It also ignores the
`stop_hook_active` field the Stop event actually carries (Claude Code's own
infinite-loop guard, true when the turn is *already* continuing because of a prior
Stop-hook block) — the one in-band hint that "this stop is hook-induced, not
loop-induced."

### Why the uncommitted `--reset` patch can't fix it

The working tree adds `UserPromptSubmit` + `SessionStart` hooks that call
`dos hook marker --reset` (docs/259 §Follow-up 2). That zeroes the tally at
**turn-start**. But the 4 forced blocks happen at **turn-end** (the `Stop` events),
*after* the reset. Reset-at-start → work → 4× block-at-stop → next turn → reset → …
The tally shows it: **zero RESET records were ever written**, and every session
still walked `1/4 → 4/4`. Resetting the counter does not change *that the Stop hook
fires on every turn and blocks it*. The defect is the **trigger**, not the count.

## The mechanism is sound; the binding is wrong

Nothing above impugns `loop_decide.wait_marker_budget` (pure, correct, well-tested)
or `marker_sensor` (a faithful `posttool_sensor`/`intent_ledger` accumulator). The
budget *arithmetic* is right. The error is entirely in **where it is wired**: a bare
`Stop` hook is the wrong actuation point because `Stop` ≠ "the loop is polling."

This is the docs/99 PDP/PEP line, sharpened: the kernel computed a correct verdict,
but the **enforcement point** (the host's hook binding) consulted it on the wrong
event. A correct verdict at the wrong seam is a wrong action.

## When does a wait-marker budget on Stop actually make sense?

The budget makes sense **exactly when a `Stop` reliably means "the loop is about to
poll again."** That is true in a narrow, identifiable set of cases — and false in
the default interactive case. The discriminator is always: **is there an
independent, ground-truth signal that this stop is a keep-alive poll, not a finished
turn?**

### ✅ Case A — a headless `/loop` (or cron) dispatch loop, scoped by env

The original target. A `claude -p`-driven loop re-invokes itself to wait on a
background child. Here a `Stop` genuinely does precede another poll. **But it must be
scoped so it only arms inside that loop**, e.g.:

- the loop exports a sentinel env var (`DOS_LOOP=1`, or the existing `CID_RUN_ID`
  the marker record already reads), and the marker hook **no-ops unless it is set**;
- or the binding lives in the loop's **own** `settings.json` / skill, not the global
  plugin everyone installs.

The budget then caps *that loop's* polling and is invisible to every interactive
session. This is the "specific case" — opt-in, env-gated, loop-local.

### ✅ Case B — Stop gated on a real "still waiting" signal

Arm the block **only when a background task is actually in flight** — i.e. join the
verdict to evidence the agent didn't author:

- a live `TaskList`/orphan-sweep showing an unreaped child (OC1), or
- a forward-delta read at `Stop` (`git_delta`/`journal_delta`, the docs/259
  §Follow-up "auto-derive RESET from a live delta" step): **no delta since
  turn-start AND a known-pending wait → it's a poll; block. A delta → real work →
  allow stop.**

This is **Option 2** from the live triage ("make marker self-disarm on a real
turn"). It is the *correct* general form, but it is a larger change: the marker hook
must read a forward-delta signal at `Stop`, which `liveness` already knows how to do
but the marker boundary does not yet pull in. It generalizes cleanly onto
`noop_streak` (the count is already "no-op turns since the last forward delta") —
the missing half is wiring the *reset trigger* to a live delta instead of an
explicit `--reset` hook.

### ✅ Case C — respect `stop_hook_active`

Whatever the gate, the hook should read `stop_hook_active` and **never escalate a
stop that is already hook-continued**. That is Claude Code's own infinite-loop
backstop; ignoring it is how a budget turns into a forced march. Even Case A/B
should honor it.

### ❌ Case D — the bare global `Stop` hook (what shipped)

Wiring it for **every** session with **no** poll-signal is the inverting case. On an
interactive turn there is no background poll to cap, so every block is pure waste.
This is the binding that was disabled, and it should stay disabled as a default.

## The design conclusion — opt-in and case-scoped, never a global default

**Not every setup wants the same thing** (the user's framing, and the right one):

- An **interactive developer** wants the agent to **stop when it's done**. A
  wait-marker budget here is all cost, no benefit — it forces ≥1 wasted turn on
  *every* exchange. For them the right default is **off**.
- A **headless `/loop` / fleet operator** wants polling **capped**. For them the
  budget is valuable — *but only armed inside the loop*, via env-gating (Case A) or a
  loop-local binding, ideally also delta-gated (Case B).
- A **cost-sensitive CI / batch** run might want it always-on *because* it is always
  a loop — and there a bare `Stop` binding is fine, because in that environment a
  `Stop` really does mean "poll again."

So the budget should be:

1. **Off by default** in the shipped plugin (remove `marker` from the unconditional
   `Stop` array — keep `dos hook stop`, the verify-on-stop hook, which is correctly
   conditional: it blocks only a *false done*, evidence-gated, so it does not fire on
   an honest finished turn).
2. **Opt-in** for the cases that want it, documented as such — env-gated (Case A),
   delta-gated (Case B), and `stop_hook_active`-aware (Case C). The hook stays
   shipped and available; only the *global default binding* is withdrawn.

The deeper lesson, in the kernel's own terms: a `Stop`-hook block is a **PEP that
forces work**, so it is only safe where the *trigger* is itself evidence-gated. `dos
hook stop` earns its place on the bare `Stop` array because its block is gated on a
ground-truth contradiction (claimed-ship vs git). `dos hook marker` does **not** —
its block is gated only on a count that says nothing about whether *this* stop is a
poll. The fix is not to delete the budget; it is to give its trigger the same
evidence discipline every other DOS verdict has, or to scope it to the one
environment where `Stop` already carries that meaning.

## What to change (when we act — this doc is analysis only)

- **Now:** keep the plugin `marker` `Stop` binding disabled (done by the operator).
  Drop the unmerged `marker --reset` `UserPromptSubmit`/`SessionStart` hooks too —
  they reset a counter whose firing was never the problem.
- **Case A (cheap, narrow):** add an env-gate to `cmd_hook_marker` (no-op unless
  `DOS_LOOP`/`CID_RUN_ID` is set) and document the loop-local opt-in binding. This is
  the "specific cases for now" path.
- **Case B (correct, larger):** teach the marker boundary to read a forward-delta at
  `Stop` (`git_delta`/`journal_delta`) and allow-stop on any real delta — the
  docs/259 §Follow-up auto-RESET, folded onto `noop_streak`.
- **Case C (always):** read `stop_hook_active` and never re-block an already-continued
  stop.
- **Docs:** fold the "when it fires / when to wire" reality into docs/259 (which
  currently never states that `Stop` fires on every turn).

## The use-case matrix — who the defaults serve, and what each setup needs

The load-bearing design principle: **the default must serve the most common
installer, and every other setup is an opt-in away.** For the DOS Claude Code plugin,
the most common installer is an **interactive developer**, so the default ships the
hooks that help *that* person and nothing that taxes them. The wait-marker budget is
not in that set — it is a loop operator's tool. Walking the matrix:

| Use case | What a `Stop` means here | Wait-marker budget | Why |
|---|---|---|---|
| **Interactive dev** (the DEFAULT) | "I finished answering; the human will type next." | **OFF** | A `Stop` is never a poll. An armed budget would force ≥1 wasted keep-alive turn on *every* exchange — pure cost, the inversion this doc is about. Default plugin ships only `dos hook stop` (verify-on-stop), which is silent unless a *false ship-claim* is detected. |
| **Headless `/loop` / fleet dispatch** | "This tick is done; I'm about to poll the background child again." | **ON, armed inside the loop** | Here a `Stop` *does* precede a poll, so capping it saves real cache-replay (the 252-marker / $7.80 case). Armed by `CID_RUN_ID` (the loop already sets it) or `--loop` on a loop-local `settings.json` Stop binding — invisible to interactive sessions. |
| **Cost-sensitive CI / batch** | "This non-interactive run finished a step." | **ON** (env or `--loop`) | Always a loop, never a human; a bare-ish armed binding is fine *because* in this environment a `Stop` reliably means "continue the batch." `DOS_LOOP=1` in the CI env arms it globally for that runner only. |
| **A loop that legitimately re-enters a wait** (long-lived session, multiple wait phases) | "I made real progress, now I wait again." | **ON + RESET on progress** | The budget must not punish a loop that *advanced* between waits. The `--reset` form (or, future, an auto-RESET off a live `git_delta`) zeroes the tally on a forward delta so each wait phase gets a fresh budget (docs/259 §Follow-up 2, folds onto `noop_streak`). |
| **A non-Claude-Code host** (Gemini / Cursor / Codex) | host-specific stop event | **ON if it polls**, via the host dialect | The verdict is host-neutral; `--dialect` renders the same block into the host's stop envelope (docs/217). The arming question is identical: only where that host's stop-event means "poll again." |

Three reusable rules fall out, and they generalize past this one hook:

1. **Default to the median installer, not the power user.** The interactive dev is the
   majority; the loop operator is the minority who can afford one line of opt-in
   config. A guard that taxes the majority to serve the minority is mis-defaulted —
   even when (as here, post-fix) the tax is harmless, it is still noise.
2. **An intervention is only a safe default if its trigger is evidence, not an
   assumption about the moment.** `dos hook stop` ships on by default because its block
   is gated on a *ground-truth contradiction* (claim vs git) — it is silent on every
   honest turn. `dos hook marker` cannot, because its trigger ("this `Stop` is a
   poll") is an assumption the bare event does not justify. **The arming signal IS the
   missing evidence** — `--loop`/`DOS_LOOP`/`CID_RUN_ID` is exactly the proof that the
   assumption holds, supplied from outside the event.
3. **Ship the mechanism, gate the binding.** The budget stays in the kernel and the
   binary; only the *default wiring* is withdrawn. A setup that wants it adds one Stop
   hook with `--loop`. This is the same split as every other DOS policy: mechanism is
   always present, policy is declared per-workspace.

## Audit — does any other DOS hook share this bug class? (2026-06-09)

After the fix, the other shipped hooks were audited for the same defect — *a hook
bound to an event that fires more broadly than its decision logic assumes, so it
intervenes on a false structural assumption.* **None do.** Each intervenes only on
positive evidence, and every default fails toward passthrough/allow:

- **`PreToolUse`** (`cmd_hook_pretool` → `pretool_sensor.decide`) — can DENY a tool
  call, so it is the highest-stakes one. It does **not** share the class. A read-only
  tool (Read/Grep/Glob/LS/WebFetch/…) takes an **empty-known tree**
  (`pretool_sensor.py:156`) and is structurally admitted by the disjointness predicate
  and short-circuited out of the behavioral rung (`pretool_sensor.py:351`) — **a
  benign Read/search is never denied.** Rung A denies only on a *real* lease-region
  collision or a *real* self-modify path-prefix hit (request-absolute, evidence-based,
  not a substring guess). Rung B's default handler is `observe` → **zero behavioral
  deny** on a default install; a deny requires an operator-wired ruling handler.
- **`Stop`** (`cmd_hook_stop`) — blocks only on an **actionable contradiction**: the
  agent *claimed* `(plan, phase)` shipped AND `oracle.is_shipped` says it did not
  (`cli.py:4217`). An ordinary turn with **no claim** returns early and allows the stop
  (`cli.py:4200`). It already honors `stop_hook_active` (`cli.py:4178`) — which is why
  bringing `marker` up to that same standard was the right, consistent fix.
- **`PostToolUse`** (`cmd_hook_posttool`) — *cannot block* (fires after the tool ran);
  its worst case is an advisory re-surfaced value, not a withheld call or a held-open
  turn. Out of the bug class by construction.

So the marker hook was the **only** hook whose trigger was an *assumption about the
moment* rather than *evidence read from it* — which is exactly why it was the only one
that inverted. The fix realigns it with the others: intervene only when the evidence
(here, the loop-arming signal) is present.

## Modularization + user config (2026-06-09, follow-up to the fix)

The fix above left `cli.cmd_hook_marker` carrying the arming logic as two inline `if`
blocks, with the cap and the arming signals hardcoded. A follow-up pass made the
subsystem modular and user-configurable without changing the shipped default
behavior:

- **`src/dos/marker_gate.py` (NEW)** — the pure ARMING decision, extracted out of the
  CLI. `decide(*, stop_hook_active, loop_flag, env, policy) -> ArmDecision` encodes the
  two guards as one unit-tested function (the env is injected, so the arming truth
  table is replay-tested away from `os.environ`). Carries `MarkerPolicy` (the
  `noop_streak.NoOpStreakPolicy` posture) + the declarative `policy_from_table` /
  `load_from_toml` loaders. Kernel-clean: stdlib only, names no host/vendor.
- **The budget verdict folds onto `noop_streak.classify`** (docs/259 §Follow-up 1) —
  the generalization of `wait_marker_budget`. Byte-equal on the allow bit + carried
  count (pinned by `test_noop_streak::test_equivalent_to_wait_marker_budget`); the
  emitted block reason keeps the `wait-marker N/M — turn held open` wording verbatim
  (the equivalence pin does *not* cover the reason string, and those bytes are pinned
  by the Go parity corpus).
- **`dos.toml [marker]`** — three declared knobs, layered through `SubstrateConfig.marker`
  the same way `[tool_stream]`/`[overlap]` are:

  | key | default | what it tunes |
  |---|---|---|
  | `max_streak` | `4` | the no-op-turn budget (handed to `noop_streak`). |
  | `arm_on_env` | `["DOS_LOOP", "CID_RUN_ID"]` | the env-var names whose presence arms the budget — **a host names its own loop sentinel here** (REPLACES the built-ins; `[]` = only `--loop` arms). |
  | `respect_stop_hook_active` | `true` | honor Claude Code's infinite-loop backstop (never re-block an already-continued stop). |

  Precedence for the cap: `--max-markers` flag › `[marker] max_streak` › the generic 4.

- **`cli.cmd_hook_marker`** shrinks to thin glue: parse → resolve → `marker_gate.decide`
  → `noop_streak.classify` → emit. The ~100 lines of inline policy become two calls.
- **The Go fast-path** (`go/internal/hook/marker.go`) keeps the two built-in arming
  signals and the default cap/backstop; it does **not** read `dos.toml` (config is a
  Python-boundary concern, and the plugin's `dos-hook || python` fallback applies the
  full `[marker]` policy). The pure arithmetic + emitted block bytes stay byte-identical
  — only the arming-*config* surface differs by language. A comment in `marker.go`
  records this split.

This is the same kernel pattern every other DOS policy follows: **mechanism is always
present (the arming decision + the budget), policy is declared per-workspace** (the
cap, which signals arm it, whether the backstop is honored). The default install is
unchanged — interactive turn → not armed → allow stop — and a loop operator now tunes
the behavior in `dos.toml` instead of editing code.

## Provenance

Diagnosis from the live `.dos/markers/` tally (44 sessions, 35 at the 4/4 wall, 0
RESETs), the `bf17aaf` binding commit, and the Claude Code hooks reference (Stop =
"when Claude finishes responding"; `block` = "prevents Claude from stopping,
continues the conversation"), confirmed 2026-06-09. The fix shipped in `68c2499`
(`cli.cmd_hook_marker` + the native Go `DecideMarker`, byte-parallel; the plugin
`hooks.json` reduced to `dos hook stop`; guard tests in `test_marker_sensor.py` +
`marker_test.go`; Go↔Python parity corpus unchanged). The cross-hook audit
(§Audit) covered `PreToolUse`/`Stop`/`PostToolUse`. Sibling reading:
[[project-dos-poll-loop-antipattern]] (the waste this targets), docs/259 (the
mechanism), docs/191 (the PreToolUse actuation×evidence cell), docs/270 (the
"read-while-lane-held is a parity-correct DENY" note the audit checked). Triage
options offered live were: (1) unwire, (2) self-disarm on a real turn, (3)
investigate — the user chose investigate, then scoped the ask to "when does this
make sense / specific cases / different use cases / not everyone wants the same
setup," which §The use-case matrix answers. The implemented fix is option (2)'s
loop-scoped form (arm-on-evidence) plus the plugin default reduced to the
evidence-gated hooks only.
