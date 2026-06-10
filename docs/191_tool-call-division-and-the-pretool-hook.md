# 191 — Tool-call division and the PRE hook DOS has not built

> The three MOMENTS of a single tool call — **PRE** (proposed, not executed),
> **BOUNDARY** (executed, returned), **POST/STOP** (turn ending) — are not one
> adjudication but three, and DOS must divide its distrust by the two asymmetries
> those moments expose, not by the wall-clock instant they occur. This plan
> theorizes the division and specifies `dos hook pretool` — the highest-leverage
> unbuilt member of DOS's hook family, the one moment a DOS verdict can *prevent*
> an effect.
>
> Provenance: a 4-phase agent workflow (`wf_390e50ba`, map → design → adversarial
> verify → synthesize), cross-checked against a mature production agent runtime
> (Claude Code) and `src/dos/`. Two load-bearing claims of the first draft were
> **refuted** by the verify phase and are corrected below (§5).

## 0. The thesis — two asymmetries that cross exactly once

A tool call is a *sequence* of runtime moments, and two properties vary monotonically
across them, in **opposite directions**:

1. **The evidence-locus asymmetry** (what bytes exist, and who authored them). As you
   move PRE → BOUNDARY → STOP, byte-authorship accrues *monotonically*:
   - **PRE** — only **agent-authored** bytes for *this* call exist: `tool_name`,
     `tool_input` (the agent chose the call and its arguments). The one env-authored
     thing available is the corpus of **prior** tool RESULTS from *earlier* calls (the
     `arg_provenance` corpus — `CorpusSource ∈ {TOOL_RESULT, TASK_TEXT}`, which has
     *no* `AGENT_AUTHORED` member by construction). **This call's `result_digest` does
     not exist yet.**
   - **BOUNDARY** — `+` this call's **env-authored** `result_digest`: the bytes the
     tool/MCP server returned, the load-bearing field the agent cannot forge.
   - **STOP** — `+` the turn's **git-minted** effects: commits/footprint whose
     *identity* the agent did not author.

2. **The actuation asymmetry** (what the host contract lets a verdict *do*). Set by the
   runtime, this runs the **opposite** way — enforcement power *falls* monotonically:
   - **PRE** can **DENY** (Claude Code's `PreToolUse` honors a `permissionDecision`
     return — a `deny` blocks a write that has not happened). This is the docs/126
     mediated-write "10×" moment, as an actual API.
   - **BOUNDARY** can only **ANNOTATE** (`PostToolUse` carries `additionalContext`
     only — no `permissionDecision`; the call already fired, so it is structurally
     advisory — docs/99).
   - **STOP** can only emit a host-honored `{ok:false}` the host *chooses* to act on.

These two curves cross **exactly once, at PRE** — the unique cell where a verdict that
needs no result (`SelfModifyPredicate`, `DisjointnessPredicate`, and the
HIGH-confidence whole-value mint from `arg_provenance` whose corpus is *prior* env
bytes) is **both sound AND backed by real deny-power.** That crossing is why
`dos hook pretool` is the highest-leverage unbuilt hook — and why it was correctly
built **last**: PRE is the one moment a DOS hook can *spurious-deny*, so it had to wait
for `dos.enforce`'s fail-to-OBSERVE + no-escalation brakes (docs/189 §A1) to exist
first.

**DOS stays a PDP, not a PEP.** The kernel only *computes* the deny (an
`EffectProposal{dispatch_call=False}`); the CC runtime is the PEP that consumes
`permissionDecision: deny` and withholds the call. The deny is a host-honored advisory
the operator opted into; the default `ObserveHandler` install emits **zero** deny.

## 1. The division table

| MOMENT | EVIDENCE-LOCUS (whose bytes exist yet) | WHAT IT CAN DO (host actuation ceiling) | DOS VERDICTS SOUND HERE | CC HOOK EVENT | CC STDOUT DIALECT |
|---|---|---|---|---|---|
| **PRE** (proposed, not executed) | AGENT-AUTHORED ONLY: `tool_name`, `tool_input`. PLUS env bytes from **prior** calls (the `arg_provenance` corpus — no `AGENT_AUTHORED` member). This call's `result_digest` does **not** exist. | **PREVENT.** `PreToolUse` honors `permissionDecision: allow\|deny\|ask` — a `deny` blocks the write before it happens. (Verified: a `deny` decision sets the permission behavior to deny and raises a blocking error; the runtime skips the tool whenever the resolved behavior is not `allow`.) | `SelfModifyPredicate` (request-absolute: `request.tree` vs `_DISPATCH_RUNTIME_FILES`); `DisjointnessPredicate` (lane tree-overlap vs live leases); the HIGH-confidence whole-value mint (`arg_provenance.classify_call` over **prior** results → `intervention.choose_intervention` → BLOCK). | `PreToolUse` | `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny\|ask","permissionDecisionReason":"…","additionalContext":"…"}}`. Emit `permissionDecision` for deny; ONLY `additionalContext` (no `permissionDecision`) for WARN; empty for OBSERVE. **Never `updatedInput`** (that would mint corrective bytes — a byte-author violation, see §4). |
| **BOUNDARY** (executed, returned) | `+` ENV-AUTHORED `result_digest`. | **ANNOTATE only.** `PostToolUse` has no `permissionDecision` — only `additionalContext`. The call already fired. | `tool_stream.classify_stream` (ADVANCING/REPEATING/STALLED — **requires** the env `result_digest`); `terminal_error`. **SHIPPED** as `dos hook posttool`. | `PostToolUse` | `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"<re-surfaced env value>"}}` or empty. |
| **POST / STOP** (turn ending) | `+` GIT-MINTED effects. | **HOST-DECIDES.** `dos hook stop` emits `{ok:false,reason}`; exit code always 0 — the host interprets and decides. | `oracle.is_shipped` over `claim_extract` claims (registry-or-grep, ancestry-checked). **SHIPPED** as `dos hook stop`. | `Stop` / `SubagentStop` | `{"ok":false,"reason":"…"}` or `{"ok":true}`. |
| **fail-safe** (any moment, on hook fault) | N/A — could not read/parse/gather. | **NOTHING.** Every hook degrades to emit-nothing, exit 0 = passthrough. | — | (any) | empty stdout, exit 0. |

The rule the family enforces: **one moment, one verdict whose bytes exist there.**
Binding `tool_stream` at PRE (no `result_digest` yet) or `oracle` at PostToolUse would
be unsound. This is the litmus for every one of the 27 vacant hook cells (docs/189 §C5).

## 2. Why PRE is sound for exactly three verdicts

- **`SelfModifyPredicate`** reads `request.tree` against the frozen
  `_DISPATCH_RUNTIME_FILES` set (`src/dos/self_modify.py`). The tree is derived from the
  *proposed* path — it exists at PRE. Sound.
- **`DisjointnessPredicate`** reads `request.tree` against live leases
  (`lane_journal.replay`) — also proposed-path data. Sound.
- **`arg_provenance.classify_call`** asks "did the model MINT this id, or did it appear
  in **prior** env-authored results?" The corpus is *prior* RESULTS — env-authored, and
  available at PRE even though *this* call's result is not. This is the **cross-moment
  join**: PRE provenance reads the accumulating `posttool_sensor` stream. Sound — and
  byte-clean because `CorpusSource` has no `AGENT_AUTHORED` member (a minted id can never
  launder itself into the corpus).

`tool_stream` REPEATING and `terminal_error` are **unsound at PRE** — they need *this*
call's env `result_digest`, which does not exist until BOUNDARY. They bind at POST only.

## 3. The two rungs, two fail-directions (the centerpiece)

A PRE deny hook carries two *different* verdict seams with *different* safe-failure
directions, and the design's correctness rests on keeping them rigorously apart:

- **Rung A — structural admission** (auto-deny-safe). `admission.run_predicates` over
  `[SelfModifyPredicate, DisjointnessPredicate]` is **conjunctive-only** and
  **fail-CLOSED-to-REFUSE**: a buggy predicate can only *over*-refuse. An admission
  over-refusal is **operator-visible and `--force`-overridable** — it is an admission
  gate, not a mid-plan agent derail, so it carries **no −9 pp exposure** (the −9 pp
  wound was a DEFER/skip+reprompt on a thrashing agent, a *different* actuation). So a
  Rung-A refusal becomes a `permissionDecision: deny` directly.
- **Rung B — behavioral provenance** (confidence-gated, fail-to-OBSERVE). The
  provenance verdict is routed `classify_call → intervention.choose_intervention →
  enforce.run_handler`. `choose_intervention` clamps the rung into `[floor, ceiling]`
  with the **default `ceiling = BLOCK`**, making **DEFER structurally unreachable** (the
  turn-spending rung). `run_handler` is **fail-to-OBSERVE + no-escalation**: a handler
  that raises or returns a non-`EffectProposal` → OBSERVE (no deny), and a handler can
  never propose *harder* than the kernel's confidence-gated rung. So a handler bug
  **cannot manufacture a deny.**

**The fail-CLOSED-vs-(−9 pp) "conflict" is not a conflict — it is a coexistence**
(corrected in §5). Admission fails CLOSED (cheap, operator-visible over-refusal); the
behavioral path fails toward WARN/OBSERVE (`on_low_confidence` defaults to WARN, which
still dispatches — the expensive −9 pp direction is avoided). The two coexist in one
hook, selected by which seam produced the verdict.

**Deny vs WARN resolution.** Emit `permissionDecision: deny` **only** when (a) a Rung-A
predicate refuses with a structural `reason_class` (SELF_MODIFY / collision), **or**
(b) Rung B yields `Confidence.HIGH → BLOCK` **and** the resolved handler proposes
`withholds_call` with a `synthetic_result`. **WARN-and-pass** (`additionalContext`, no
`permissionDecision`) on `Confidence.LOW`, on any composite/partial mint, and whenever
no synthetic corrective exists. DEFER unreachable.

## 4. The PEP-not-PEP discipline and the `updatedInput` refusal

CC's `PreToolUse` schema *also* offers `updatedInput` (rewrite the agent's args). The
family **deliberately excludes it**: emitting `updatedInput` would make DOS author
corrective bytes *for* the agent — the kernel minting the fix, violating the byte-author
invariant (docs/138). `pretool` stays **deny / passthrough / additionalContext only**.
The temptation to "just fix the arg" will recur and must be refused.

A turn-preserving BLOCK surfaces the corrective via
`intervention.synthetic_corrective_result` *inside* `permissionDecisionReason` (+
`additionalContext`) — naming the unresolved arg by NAME + component TOKENS only, never
echoing the minted id value (the anti-laundering shape, docs/143 §5a).

## 5. Corrections the adversarial verify phase forced

1. **REFUTED: there is no "dangerous-exec capability class."** The first draft (echoing
   docs/189 §B1, a *proposal*) listed a third PRE-sound verdict. Verification found no
   such typed class in `admission.py` / `lane_overlap.py` / `self_modify.py`. The
   built-in admission conjunction is **exactly two** predicates: `SelfModifyPredicate`
   and `DisjointnessPredicate`. (`code_exec_capability` remains an *unbuilt* docs/189
   §B1 idea, out of scope here.)
2. **CORRECTED: fail-CLOSED-vs-(−9 pp) is a coexistence, not a conflict.** Verification
   showed `intervention.py` already fails toward PASS (`on_low_confidence` defaults to
   WARN, which dispatches), *not* toward deny. §3 states the resolved coexistence.
3. **CONFIRMED + cited:** PRE evidence is agent-authored-only; `tool_stream`/
   `terminal_error` are unsound at PRE. The table binds them strictly at BOUNDARY.
4. **CONFIRMED + cited:** the PDP-not-PEP claim rests on verified `enforce.py`
   semantics — a PRE deny is an `EffectProposal{dispatch_call=False}` (the frozen
   `__post_init__` guards `synthetic_result ⟹ not dispatch_call`); the CC runtime is the
   PEP; the default `ObserveHandler` install emits zero deny.

## 6. The build — `dos hook pretool`

A layer-3 CLI verb `cmd_hook_pretool` in `src/dos/cli.py` (sibling of
`cmd_hook_posttool`) + a kernel-boundary adapter `src/dos/pretool_sensor.py` (sibling of
`posttool_sensor.py`). The adapter READS the host event, runs already-shipped PURE
kernel verdicts, and emits the host dialect. It names no host beyond the `PreToolUse`
JSON shape, takes no lease, resolves paths via `SubstrateConfig`; ruling handlers stay
in `drivers/`.

**STDIN.** CC `PreToolUse` event: `{hook_event_name:"PreToolUse", session_id,
transcript_path, cwd, tool_name, tool_input, tool_use_id, permission_mode?}`. The
**structural PRE marker** is the *absence* of a `tool_response`/`tool_output` key (that
is what distinguishes PRE from BOUNDARY). Defensive parse identical to
`cmd_hook_posttool`: any failure → emit nothing, exit 0 (passthrough). Resolve workspace
`--workspace › event.cwd › cwd`.

**STDOUT.** Exclusively the CC `PreToolUse` dialect or empty. `--debug` to STDERR only
(the no-pollution discipline — the dialect must be byte-exact or the hook is a silent
no-op, the old `dos hook stop` lesson).

**Tree extraction is conservative** (open tension): parsing a Bash command or an Edit
path into `AdmissionRequest.tree` is lossy. An un-parseable *mutating*-call tree is
treated as **unknown blast radius → refuse at the SELF_MODIFY rung**, never silently
emptied to admit (a missed self-modify is the dangerous direction).

**Durability.** On any non-passthrough outcome, append an `OP_ENFORCE` `lane_journal`
entry (the `enforce_entry` builder already ships, `lane_journal.py:676`; `OP_ENFORCE`
is *not* in `_STATE_MUTATING_OPS`, so `replay` ignores it for lease state — it only adds
forensic history). Stamp `run_id`/`step` as `posttool` does for the `firing_label` join.

**Opt-in only.** `DEFAULT_PRETOOL_HOOK_COMMAND` wires into `guard.py` behind a
`--block-on-pretool` flag (like `--verify-on-stop`), default OFF. A hook that can deny
is a deliberate operator choice, never injected by default — this is what keeps the
default install PDP-only.

### Tests (`tests/test_hook_pretool.py`)

1. Fail-to-passthrough: empty/bad/no-`tool_name` stdin → empty stdout, exit 0.
2. SELF_MODIFY deny: a Write to a kernel runtime path → `permissionDecision:"deny"`.
3. Disjointness deny: a tree colliding a live lease → deny; disjoint tree → passthrough.
4. Behavioral HIGH-mint → deny *with* `synthetic_result`; LOW-mint → `additionalContext`
   only, no `permissionDecision`.
5. **Handler-fault structural proof**: a handler that raises / returns non-`EffectProposal`
   → NO deny emitted (fail-to-observe through `run_handler`).
6. **No-escalation**: a handler proposing DEFER on a BLOCK decision → clamped, never
   reaches stdout as deny.
7. **Default-install PDP proof**: with only `ObserveHandler` wired, a HIGH-mint emits
   passthrough (zero deny).
8. Dialect-exactness: stdout is byte-exact CC `PreToolUse` JSON; `--debug` only on stderr.
9. Ceiling clamp: even a `dos.toml` ladder raising ceiling to DEFER cannot make the PRE
   hook emit a turn-spending rung.

## 7. Build sequence

0. **DONE (verified).** `dos.enforce` (`EffectProposal` + `EnforcementHandler` +
   `ObserveHandler` + `run_handler` with fail-to-OBSERVE + no-escalation) and
   `dos.intervention` (`choose_intervention` with `ceiling=BLOCK` clamp +
   `synthetic_corrective_result`) exist. `lane_journal.OP_ENFORCE` + `enforce_entry`
   also already ship.
1. **`pretool_sensor.py`** — the boundary adapter, mirroring `posttool_sensor.py`.
2. **`cmd_hook_pretool`** in `cli.py` + the `pretool` subparser.
3. **`tests/test_hook_pretool.py`** — the nine tests, with the handler-fault and
   default-install-PDP proofs as the load-bearing structural pins.
4. **guard wiring** (opt-in): `--block-on-pretool`, default OFF, pinned by a test that
   the default guard injects no pretool hook.
5. **`OP_ENFORCE` journal write** on every non-passthrough outcome (docs/189 §C4).
6. *(future)* a live A/B of BLOCK-as-deny on EnterpriseOps-Gym — the −9 pp was measured
   on a *different* (skip+reprompt) actuation, so the turn-preserving deny conversion is
   **unproven live** and must earn default-on with its own measurement (the docs/170
   velocity thesis counts a per-call latency tax against DOS).

## 8. Open tensions (carried forward)

- **BLOCK-as-deny is unproven live.** The −9 pp was a DEFER-shaped actuation; the
  turn-preserving deny at PRE is different and untested. It must earn default-on.
- **PDP-not-PEP erosion risk.** `permissionDecision: deny` is the closest DOS has come to
  enforcing. The discipline holds only because (a) CC is the actual enforcer, (b) the
  deny is operator-opted-in via guard, and (c) the default `ObserveHandler` emits zero
  deny. If a future host auto-trusts the deny without operator wiring, DOS has silently
  become a PEP — the host-owns-the-deny line must stay documented.
- **Tree extraction is lossy + host-specific.** A mis-parse → false collision deny
  (over-refuse, survivable) or a missed self-modify (under-refuse, dangerous). The
  conservative default (unknown tree → SELF_MODIFY refuse) biases to the safe side.
- **Latency.** `PreToolUse` runs synchronously *before every tool call* and BLOCKS
  execution (unlike PostToolUse). The prior-results gather (the `posttool` stream) +
  `classify_call` per call is a hot-loop tax the docs/170 thesis counts against DOS; the
  gather must be bounded/cached.
- **Cross-moment coupling.** Rung B depends on the `posttool_sensor` stream's freshness.
  A missing/stale stream degrades provenance to empty-corpus `believe=True` (the safe
  direction) — but PRE coverage is then only as good as the POST stream that feeds it.
- **27 vacant hook cells invite over-binding.** Each future member must have a
  moment-appropriate sound verdict whose bytes exist at that moment.
