# 189 — Ideas from the Claude Code source extensible to DOS

> A deep design audit of a **mature production agent runtime** (Claude Code) for
> mechanisms liftable into the DOS kernel. Produced by a 10-reader fan-out (85 raw
> ideas) followed by **manual** adversarial verification of the load-bearing claims
> against both codebases — the workflow's automated verify pass was wiped twice
> by a transient server-side rate limit, so the survivor set below was
> adjudicated by hand (each high-value claim was re-opened in the runtime's
> behavior and cross-checked against `src/dos/`). Every claim was grounded in an
> observed runtime behavior; downgrades/refutations are called out, not hidden.

## 0. Executive summary

The single biggest finding: **Claude Code ships the PEP that DOS explicitly
lacks.** DOS's self-description is "a sound PDP with no PEP — it decides a
verdict, it does not enforce" (CLAUDE.md glossary; docs/125/126). The runtime's
permission system is a complete, working **Policy Enforcement Point** with the
exact shape DOS's advisory model has been circling: a closed decision vocabulary
(`allow`/`deny`/`ask`/`passthrough`), decision *provenance* (the source kind that
produced a verdict — rule / mode / classifier / hook / sandbox override / safety
check), **source precedence** (policy settings > project > local > user > CLI
arg), and — critically — a **`PreToolUse` hook that can return a
`permissionDecision` before the tool runs** (verified). That is the
mediated-write moment (docs/125 §"10x") made concrete. DOS does not need to
*become* a PEP, but it can lift the PEP's **shape** into a clean
enforcement-handler seam its drivers implement.

The five highest-leverage ideas, in order:

1. **PEP-as-handler-seam** — the multi-mode enforcement abstraction
   (coordinator/interactive/swarm behind one permission context) becomes
   DOS's missing `EnforcementHandler` protocol: one seam, pluggable
   observe/warn/block/delegate handlers, kernel stays advisory.
   *(✅ **SHIPPED this commit** as `dos.enforce` — see A1.)*
2. **`PreToolUse permissionDecision` = the real intervention-ladder BLOCK rung** —
   the runtime seam that turns DOS's OBSERVE‹WARN‹BLOCK ladder (docs/144) from a
   reported string into an *enforced* pre-tool verdict, bound where
   `dos hook posttool` already lives. *(new, high)*
3. **Config-linter / unreachable-reason detection** — the runtime statically
   finds dead/unreachable permission rules across precedence; DOS has
   **no** equivalent for its reason/lane registry (verified absent). A
   `dos doctor`-style integrity check that catches misconfigured
   reason cascades at config-write time. *(new, medium-high)*
4. **Structured intervention-result type + exit-code verb mapping** — the
   runtime's hook-result record (an `outcome` enum + a prevent-continuation flag +
   a stop reason + a blocking-error payload) and the `exit 2 = block` convention
   give DOS a closed, testable intervention-verdict record and a zero-friction
   script integration. *(new, high)*
5. **Hook-event taxonomy + hook-event journal records** — the runtime's closed
   27-event hook set (verified) maps every runtime moment DOS could bind a verdict
   to. DOS binds 2 of 27 today; `PostToolUseFailure`/`StopFailure`/
   `PermissionDenied`/`SubagentStop` are distrust-relevant seams sitting unused.
   Logging hook outcomes to the `lane_journal` makes "which hook blocked which
   phase" byte-clean, resumable evidence. *(new, high)*

Recurring theme beyond the PEP: the runtime has independently rediscovered DOS's
core disciplines — **closed-enum-as-data** (permission modes, memory types,
restore options, hook events), **byte-clean evidence** (a monotonic snapshot
counter as an agent-external liveness signal; the SSRF guard binding the
*validated* DNS result to the socket to close TOCTOU), and **fail-safe defaults**
(an invalid classifier response is treated as block-worthy). The convergence is
itself a validation of the DOS design laws.

---

## 1. Ranked ideas

### Theme A — Enforcement / the PEP DOS lacks  *(the headline)*

**A1. Enforcement-handler seam (PEP as a pluggable protocol).**  `value=HIGH · byte=clean · build=medium · new` — **✅ SHIPPED `dos.enforce`**
The runtime runs **three** enforcement policies behind **one** permission context:
a coordinator handler (await classifier, then dialog), an interactive handler
(race classifier vs user), and a swarm-worker handler (delegate to leader). The
handler is chosen by runtime context (whether automated checks block the dialog,
whether the actor is a swarm worker), not hardcoded.
→ **DOS**: lift the *seam*, not the policies. **Built as `src/dos/enforce.py`**
(this commit): the kernel holds the `EnforcementHandler` Protocol + the frozen
`EffectProposal` + the unshadowable built-in `ObserveHandler` (observe-only floor)
+ `run_handler` + a by-name resolver over the `dos.enforce_handlers` entry-point
group — byte-faithful to the `judges` / `overlap_policies` shape. A handler
**consumes an `intervention.InterventionDecision`** (the strength the kernel
already computes) and returns an `EffectProposal` (dispatch / withhold+synthetic /
note) a host PEP materializes. The kernel still only *decides*; the handler
proposes; the host acts. `run_handler` enforces **two** structural guarantees,
both fail-SAFE toward less disruption: (1) **fail-to-observe** — a raise or a
non-`EffectProposal` return degrades to the zero-disruption OBSERVE proposal, never
a spurious block (the docs/143 −9 pp lesson: disruption is the expensive mistake);
(2) **no-escalation** — a handler may de-escalate but a proposal more disruptive
than the kernel's rung is clamped back to OBSERVE. This generalizes the hand-coded
`if action is DEFER/BLOCK/OBSERVE` ladder currently inline in
`benchmark.enterpriseops.dos_react` into a swappable seam. 22 tests
(`tests/test_enforce.py`); listed in `dos doctor` ("enforce handlers").

**A2. `PreToolUse` permission-decision return = the enforced BLOCK rung.**  `value=HIGH · byte=clean · build=medium · new`
Verified: a `PreToolUse` hook may return a `permissionDecision` (plus a reason)
— the runtime consults it *before* executing the tool, so a hook can `deny` a
write that has not happened yet. This is the mediated-write moment (docs/125) as
an actual API.
→ **DOS**: `dos hook posttool` already exists (the docs/173 sensor, shipped). Its
sibling `dos hook pretool` is the natural BLOCK rung: emit a refuse verdict that
the agent runtime maps onto `permissionDecision: "deny"`. Pairs with A1 — the
handler decides whether the verdict becomes a deny or a warn. **First step**:
spec `dos hook pretool` to read tool+args from PreToolUse stdin, run the
relevant predicate (`SELF_MODIFY`, lane disjointness, dangerous-exec class from
B-tier), and emit the CC hook-JSON shape on the BLOCK decision only.

**A3. Two-stage enforcement (validate-then-sandbox fail-safe).**  `value=HIGH · byte=n/a · build=large · new`
The runtime's PEP is *layered*: tool-level command validation is the first gate,
an OS sandbox (bubblewrap/pledge) is the backstop — even a command that passes
validation is caught by the kernel sandbox.
→ **DOS**: `dos apply` (the opt-in host PEP, docs/126) should standardize a
*two-stage* contract: (1) query DOS oracles and refuse on verdicts; (2) hand the
admitted action to a host enforcement strategy (audit-only … OS sandbox). Define
the enforcement interface so host PEPs range from trivial to strong without the
kernel knowing which. This is the principled version of "DOS decides, host
enforces."

**A4. Dual-layer filesystem fences (deny-within-allow).**  `value=HIGH · build=small · strengthens*`
The runtime's path validator enforces an allow-only write region punched with
deny holes (e.g. `.claude/settings.json` stays blocked *inside* a writable temp
dir). Reject-if-any-deny precedes allow.
→ **DOS**: this is the *inverse* of the overlap-policy floor (docs/113). Today
the prefix floor is a permit-ceiling (a policy can only refuse-MORE). The
deny-within-allow pattern says some fences (`SELF_MODIFY`, sensitive-path
blocks) should be **deterministic deny-floors** a permissive policy cannot
override. **Caveat (my downgrade)**: DOS's `SELF_MODIFY` predicate already *is* a
deny-floor in spirit; the additive part is making the sensitive-path set
*declared data* (`dos.toml [deny_within]`) and AND-ing it under any admit. Real
but narrower than the agent's framing.

**A5. Permission-mode = risk-stratified verdict context.**  `value=MEDIUM · build=small · new`
Five permission modes (`default`/`acceptEdits`/`plan`/`bypassPermissions`/`dontAsk`)
gate checks *before* rule matching; in `acceptEdits`, writes inside CWD skip
safety checks (risk bounded to an operator-chosen dir).
→ **DOS**: `arbitrate(..., mode=strict|bounded|delegated)` — strict forces full
predicates, bounded fast-paths inside known-safe regions, delegated is today's
advisory floor. Expressiveness for fleet operators without rewriting policies.

---

### Theme B — Structural detectors / distrust-of-own-output

**B1. Dangerous-exec class as a *capability* detector (a SHAPE, not a word).**  `value=HIGH · byte=clean · build=small · new`
The runtime keeps a closed set of cross-platform code-execution patterns that
identify allow-rules granting **arbitrary code execution** (`python`, `node`,
`eval`, `exec`, `bash`, `ssh`, package runners…) — a structural capability
property, matched by exact rule-shape, not a substring scan for "dangerous".
→ **DOS**: this is the docs/158 lesson ("a SHAPE not a word") applied to
*permission-rule / lane auditing* rather than output classification. A
`code_exec_capability(claim) -> bool` predicate in the `SELF_MODIFY` family:
flag a lane/claim that hands an agent an arbitrary-exec interpreter. **First
step**: ship the cross-platform code-execution pattern set as a `dos.reasons`-style
data list + a predicate that fires `GRANTS_ARBITRARY_EXEC` on a matching claim.

**B2. Envelope-grammar tool-result detector (corroborates docs/158).**  `value=HIGH · byte=clean · build=medium · strengthens`
The runtime validates every tool/classifier response against a tight schema; a
malformed envelope is treated as block-worthy (verified pattern). This is the same
byte-clean envelope read DOS shipped as `terminal_error` (docs/158): read the
*env-authored* result bytes in a tight grammar, never agent narration.
→ **DOS**: mostly a corroboration of an existing detector, but the additive lift
is a **front-rung structural validator** in `tool_stream`: before the
`result_digest`, check JSON well-formedness / `{type,content}` shape and emit an
advisory WARN on garbage envelopes (byte-clean — reads MCP-authored bytes).

**B3. Fail-safe-on-unparseable as a detector default.**  `value=MEDIUM · build=small · new`
The recurring rule across the runtime: *when the structural check cannot parse,
treat as block-worthy*, not pass-through (an invalid classifier response blocks;
a truncated-JSON fallback rather than silent acceptance). DOS's detectors abstain
on ambiguity (correct for an advisory PDP); but a documented "fail-toward-surface,
not fail-toward-silent" default for the WARN rung is worth pinning in the
detector-design guide (docs/159 lineage).

**B4. Two-stage classifier (cheap-allow / expensive-block asymmetry).**  `value=LOW · build=small · new`
The runtime's permission classifier is two-stage: a fast yes/no first pass (~64
tokens); only escalate to a chain-of-thought second pass (~4096 tokens) on a
*block* lean — cost-aware verdict asymmetry, shared cache prefix.
→ **DOS**: a `max_reasoning_tokens` hint on `run_judge` so hosts tune the
allow-cheap / block-expensive asymmetry as judges scale. Clean but not urgent.

**B5. Forgeability checklist as a meta-detector (a design gate).**  `value=MEDIUM · build=small · new`
CC's verification-agent prompt *names its own failure modes* ("reading is not
verification", "the implementer is an LLM too") so the agent trains against them.
→ **DOS**: formalize docs/158 §5's forgeability test as a **PR-time checklist /
pre-commit hook** on detector proposals: (1) does it read agent narration?
(2) can a model defeat it by changing narration? (3) is there a byte-clean
equivalent? If (1)/(2) → reject. A filter on *future* detector ideas — cheap,
catches the next generation of well-intentioned-but-forgeable proposals.

---

### Theme C — Intervention ladder / hook result types

**C1. Structured intervention-result record.**  `value=HIGH · ⚠ CORRECTED: DOS-ALREADY-HAS the decision type; the NEW part is the consumer seam (A1)`
The runtime's hook-result record carries an `outcome` enum
(success / blocking / non-blocking-error / cancelled) + a prevent-continuation
flag + a stop reason + a blocking-error payload. One record carries the whole
verb space; the stop-hook runner aggregates them across parallel hooks.
→ **DOS — corrected after a probe** (the "verify reuse before building" rule, my
memory note): this doc's first draft claimed the ladder is "string-reasoned in
practice" and that the structured *result type* was new. **Both wrong.**
`src/dos/intervention.py` ALREADY ships the closed `Intervention` vocabulary
(OBSERVE/WARN/BLOCK/DEFER), the `InterventionLadder` registry, the
`InterventionDecision` record (the structured result — `intervention` + `confidence`
+ `rung` + `disruption_cost` + `reason`), confidence-gating (`choose_intervention`),
the `synthetic_corrective_result` builder, AND the `dos.toml [intervention]`
on-ramp. So the *decision* type is **done**. The genuinely-missing piece the CC
audit points at is the **consumer** of that decision — *who takes an
`InterventionDecision` and proposes the effect* — which is exactly A1
(`dos.enforce`, now shipped). The `halt_clean` fourth verb (C2) remains a real
small addition to the existing ladder.

**C2. Prevent-continuation + stop-reason = a fourth verb (HALT-CLEAN).**  `value=MEDIUM · build=small · new`
The runtime distinguishes a *clean stop* (a `continue:false` plus a stop reason)
from a *blocking error*. Not every stop is a failure.
→ **DOS**: add `halt_clean` to the ladder distinct from `block` — signals a host
PEP to exit 0, not 1. Unblocks resume/checkpoint workflows (a SPINNING run can
ask for a graceful pause without being marked failed).

**C3. Exit-code → verb mapping (`exit 2 = block`).**  `value=MEDIUM · byte=clean · build=small · new`
In the runtime, a command hook exiting with code 2 maps to a blocking error;
0 = pass, other = non-blocking warn. Zero-friction for unsophisticated scripts —
no JSON parser needed.
→ **DOS**: a pure `hook_exit_classify(code, policy) -> intervention_verb` seam so
hosts declare which exit codes mean block/warn/observe. Pairs with `dos hook
pretool`/`posttool` for shell-script integrations.

**C4. Enforcement/hook outcomes as durable journal evidence.**  `value=HIGH · byte=clean · build=small · new` — **✅ SHIPPED `OP_ENFORCE`**
The runtime materializes each hook outcome as a typed attachment (a success /
blocking-error / stopped-continuation kind, carrying stdout/stderr/exit-code/
duration/command) — **runtime-authored**, flowing through the message stream
(verified).
→ **DOS — built this commit**: added a state-neutral `OP_ENFORCE` op +
`enforce_entry(proposal, …)` builder to the `lane_journal` WAL. A probe confirmed
the right home: `OP_REFUSE`/`OP_HALT` are the precedent for *recorded decisions
that grant/remove no lease* (forensic, not state-mutating), and an enforcement
outcome is exactly that kind of event — so it folds state-neutral in `replay`
(can never lose/invent a lease) and rides the existing journal readers
(`decisions`/`trace`/`journal_delta`) unchanged. The record lifts
`intervention`/`dispatch_call`/`withheld`/`handler` to the top level for cheap
forensic filtering and stores the full `EffectProposal.to_dict()` body +
correlation (run_id/lane/tool). So `resume()`/an auditor can now read *which call
was blocked at 14:03, by which handler, and what was substituted* — as ground
truth from the spine, closing the ARIES gap where a blocking handler left no
durable trace. 6 tests; the enforce + journal + all journal-reader suites stay
green. The named `OP_HOOK_RAN`/`OP_HOOK_BLOCKED` split is unnecessary — one
`OP_ENFORCE` carries the rung in its body, the closed-op-vocabulary discipline.

**C5. Hook-event taxonomy as a closed config enum.**  `value=MEDIUM→HIGH · build=small · strengthens`
Verified: the runtime's closed hook-event set has 27 entries (`PreToolUse`,
`PostToolUse`, **`PostToolUseFailure`**, `Stop`, **`StopFailure`**,
`SubagentStart`, `SubagentStop`, `PreCompact`, **`PermissionRequest`**,
**`PermissionDenied`**, `TaskCreated`, `TaskCompleted`, `WorktreeCreate`/`Remove`,
`FileChanged`, `CwdChanged`, …). DOS binds **2 of 27** (`Stop`, `PostToolUse`).
→ **DOS**: a `dos.hook_event` closed-data enum mapping each runtime moment to a
kernel verdict point. The unused distrust-relevant seams are the roadmap:
`PostToolUseFailure` (→ `terminal_error` live), `StopFailure` (→ verify-on-stop
negative path), `PermissionDenied` (→ refusal corroboration), `SubagentStop`
(→ per-worker verify-on-stop). This is the concrete version of docs/165's
"map every CC seam to a DOS verdict."

---

### Theme D — Coordination / fleet (orchestrator axis, docs/98/116)

**D1. Worker-result-as-structured-signal protocol.**  `value=HIGH · byte=clean · build=medium · new`
Worker outcomes arrive as **user-role messages** carrying a structured envelope
(task id / status / summary / result / usage, with tokens, tool-uses, duration)
— verified. The coordinator prompt is explicit: *"Worker results are internal
signals, not conversation partners — never thank or acknowledge them."* The
runtime authors the metadata, not the judged worker.
→ **DOS**: a durable `outcome_signal(run_id, status, {tokens, tool_uses,
duration})` record on the spine — byte-clean (runtime-authored) productivity
evidence feeding liveness/economics verdicts. This is the A2A-via-substrate move
(docs/116): a worker reports to the *substrate*, the coordinator reads the
*adjudicated signal*, never the worker's prose.

**D2. `reap_tree` — structured downward kill via abort cascade.**  `value=MEDIUM · byte=clean · build=medium · new`
In the runtime, each worker gets its own (or a child) abort controller;
parent-abort auto-aborts children, child-abort never touches siblings — an
asymmetric kill *tree*, not Unix signal-based process groups.
→ **DOS**: `reap_tree(run_id)` over the run lineage: journal a `REAP_TREE`
verdict *before* the kill fires (write-ahead), so termination is auditable
independent of process death. DOS's `halt` is advisory today; this is the
operative-kill design for the BLOCK rung.

**D3. Per-worker progress tracker (rate, not just liveness).**  `value=HIGH · byte=clean · build=medium · strengthens`
The runtime's per-worker task tracker holds cumulative tokens + a tool-use count
+ a capped sliding window of recent activities, updated per assistant message.
→ **DOS**: liveness is boolean (ADVANCING/SPINNING/STALLED); add a *rate* signal
(`progress_metrics`: tokens/turn, tool histogram) sampled per checkpoint and
journaled. Lets the intervention ladder WARN on *productive-but-slow* before it
BLOCKs on *stalled* — the docs/145 loop-economics axis with a continuous knob.

**D4. Per-worker tool-capability scoping (capability-lock ⟂ region-lock).**  `value=HIGH · byte=clean · build=medium · new`
In the runtime, each worker's tool pool is computed at spawn (the agent-type's
disallowed tools plus an explicit allowed-tools list), immutable for its
lifetime.
→ **DOS**: `arbitrate` admits **lanes** (spatial region-locks); CC adds an
orthogonal **capability-lock**. A `tool_admit(run_id, tool_set)` seam: declare
the capability set at spawn, gate invocations against it (WAL-durable). The
BLOCK rung can then *revoke a capability* (forbid Bash after a failed run), not
just deny a region. Fleet supervision needs both axes.

**D5. "Never hand off understanding" as a judge discipline.**  `value=MEDIUM · byte=n/a · build=large · new`
The coordinator prompt forbids `"based on your findings, fix X"` — the
coordinator must synthesize (file paths, line numbers) before delegating.
→ **DOS**: the kernel analogue is fail-to-abstain (docs/86) sharpened: a JUDGE
ruling that *defers* understanding (cites no evidence) should ABSTAIN, not
AGREE. Encodable as a `judge_eval` discipline: penalize a judge that claims a
verdict without grounding. Social discipline → kernel rule.

---

### Theme E — Memory commons (docs/103 "memory is an unverified agent", docs/116)

**E1. Memory provenance spine (birth-SHA + author + write-ts in frontmatter).**  `value=HIGH · byte=clean · build=small · new`
The runtime's memory records carry type + mtime but **no** provenance: no field
records *which agent wrote it* or *at what SHA*.
→ **DOS**: this is the *fix* for docs/103. A memory write stamps
`birth_sha + author_run_id + write_ts`. Recall then runs
`liveness.classify(write_sha)`: "were A's claims still on the live branch when B
recalled them?" Stale recalls become *detectable by an existing verdict*. DOS's
own memory store (this repo's `MEMORY.md` + topic files) is the first consumer.
**Cheapest high-value memory idea.**

**E2. Time-based staleness caveat → a refusal-scoped recall verdict.**  `value=MEDIUM · build=medium · strengthens`
In the runtime, memories more than a day old get a `<system-reminder>` "verify
against current code" caveat — heuristic, advisory, *not* re-verified against git.
→ **DOS**: replace the time heuristic with `recall_verify -> FRESH/STALE/
UNVERIFIABLE` grounded in SHA ancestry + `git_delta` since write-time, and make
STALE a *refusal* that can gate injection (not just a UI caveat). Builds directly
on E1.

**E3. Secret-scan pre-write as a refusal verdict.**  `value=HIGH · byte=clean · build=small · new`
The runtime's team-memory sync runs a gitleaks-pattern scan before upload; on a
hit the file is silently *skipped* + logged.
→ **DOS**: a `memdir_guard` driver: `scan_for_blocked_content(path, patterns)
-> BLOCKED_SECRET/ALLOWED/UNKNOWN`, patterns from `dos.toml [blocked_patterns]`,
fail-safe (BLOCKED_SECRET → **refuse** the write, surfaced to the `dos decisions`
operator queue — *adjudicated*, not silently skipped). Real security value;
small lift.

**E4. Team-memory sync = the blackboard disease, instrumented.**  `value=HIGH (as evidence) · byte=dirty · build=large · new`
The runtime's team-memory sync is a shared mutable commons (server-wins on pull,
push-local-wins on a stale-write conflict, **no content merge**). This is
*precisely* the fleet-scale blackboard docs/116 warns against — a commons that
believes its writers.
→ **DOS**: the design target is `dos.drivers.team_memory` that routes reads
through a `recall_verify` (E2) so agent B reads kernel-grounded verdicts about a
file's claims, never raw writer trust. Marked **dirty** because the *content* is
self-report; the *adjudication* (E1/E2 grounding) is what makes it clean. Large,
but it's the concrete A2A commons problem.

**E5. Closed memory-type taxonomy as a pluggable policy.**  `value=MEDIUM · build=small · strengthens`
The runtime's 4-type closed memory enum (user / feedback / project / reference)
with per-type scope guidance + graceful unknown-type degrade — *exactly* this
repo's `MEMORY.md` convention. → a `MemoryTypePolicy` seam (sibling of
`OverlapPolicy`): hosts add domain types, kernel keeps the type-check
deterministic; misclassification → `INVALID_MEMORY_TYPE` refuse. *(Note: DOS
already practices the convention informally; the lift is making it a seam.)*

**E6. MEMORY.md entrypoint truncation (line + byte cap with visible warning).**  `value=LOW · build=small · new`
The runtime caps the memory entrypoint at 200 lines / 25,000 bytes,
truncate-at-last-newline + a model-visible overflow warning. **Directly
relevant**: this repo's `MEMORY.md` *just tripped its own 24.4KB cap* (see the
session reminder). A `memdir_compact` housekeeping verb would propose
consolidation. Usability, not trust — low priority but immediately applicable.

---

### Theme F — Durability, lineage & resume (docs/107/137)

**F1. UUID lineage chain (parent-pointer) → a chained lane-journal.**  `value=HIGH · byte=clean · build=medium · new`
In the runtime, every transcript message carries its own id plus a parent id,
forming a linked-list; progress ticks are excluded from the chain and *bridged*
on load.
→ **DOS**: `lane_journal` is append-only but entries are **not explicitly
chained** — a crashed run leaves multiple possible re-entry points. Add a
`parent_event_id` (digest of the prior event) so the journal is a verifiable
linked-list with a single canonical recovery order. Strengthens `resume`'s
ancestry walk.

**F2. Ephemeral-vs-durable entry classification (resume-anchor safety).**  `value=MEDIUM · byte=clean · build=small · new`
The runtime marks a closed set of ephemeral progress types (bash/sleep progress)
that are *never* chain participants — resume never re-enters from an intermediate
tick.
→ **DOS**: tag `intent_ledger` entries DURABLE vs EPHEMERAL (heartbeats/
checkpoints are anchors; intermediate snapshots are not). A truncated journal
that lost ephemeral entries stays resumable — last DURABLE entry is the
re-entry point, never a best-guess.

**F3. Run-metadata sidecar (`meta.json` partner to the journal).**  `value=MEDIUM · byte=clean · build=medium · new`
The runtime writes a small per-agent metadata sidecar (agent type, worktree path,
description) beside the (huge) transcript so resume routing reads metadata without
parsing the JSONL; never compacted.
→ **DOS**: `run-<id>.meta.json` per run-dir carrying RUN_ID, lane, ledger schema
version, entry-point verb. Pre-flight validation ("does this run belong to THIS
kernel version?", the docs/117 `durable_schema` refuse-don't-guess) *before*
expensive ledger parsing.

**F4. Atomic context-path binding (the wrong-workspace bug).**  `value=MEDIUM · byte=clean · build=small · strengthens`
The runtime's session switch updates the session id **and** the project dir
atomically; a documented bug had resume loading the *wrong* session because the
path was derived from `cwd` while the recorded session project dir differed.
→ **DOS**: `resume_evidence` must read from the dir the run was **spawned** in
(recorded in F3's sidecar), never guessed from cwd. Closes a
resume-from-wrong-workspace hazard. Small, defensive.

**F5. A monotonic snapshot counter = an agent-external liveness counter.**  `value=HIGH · byte=clean · build=medium · new`
The runtime keeps a monotonic counter incremented by the *session loop* on every
snapshot (even post-eviction), consumed by its git-diff-stats view as an
activity/plateau signal.
→ **DOS**: the **conversation-axis analogue** of `liveness` — instead of "did
git advance?", "did transcript+file state advance?", from a counter the *runtime*
authors (un-forgeable by the agent). Binds REPL/conversation progress to the
liveness verdict, separating "model emitted a turn" (forgeable) from "state
changed measurably" (auditable). Strong fit for the docs/154 latency axis.

**F6. Prompt-id correlation spine (OTel-style live trace).**  `value=HIGH · byte=clean · build=medium · new`
In the runtime, each prompt gets a prompt id; every event during that prompt
(tool calls, API responses, hook outputs) references it.
→ **DOS**: `dos trace` (docs/137) today joins git+journal *post-hoc*. Add a live
`DECISION_SPAN` record keyed on `run_id` + step + parent-trace-id drawn from the
**kernel's own** event log (not agent-reported UUIDs) — a forward-moving
correlation spine, not just a lie-detector.

---

### Theme G — Config seam / hackability (docs/HACKING.md, SubstrateConfig)

**G1. Config-linter: unreachable-rule / shadowed-reason detection.**  `value=MEDIUM-HIGH · byte=clean · build=small · new`
Verified: the runtime's unreachable-rule detector finds an allow rule made
unreachable by a tool-wide deny/ask, **categorized** (deny vs ask shadow), **with
a fix suggestion**, and **context-aware** (the sandbox exception). Verified absent
in DOS — no `shadow`/`unreachable` linting of the reason/lane registry exists.
→ **DOS**: a `dos doctor`-class integrity service (driver, not kernel):
`detect_unreachable_reasons(registry)` flags a reason/lane shadowed by a more
general one *before* it, at config-write time. As the reason vocabulary and the
`judges`/`overlap_policies`/`predicates` plugin seams grow (docs/113/135), the
chance of a dead-code refusal grows; this catches it. Evidence is config-authored
(byte-clean). **Genuinely new, small, and squarely in DOS's self-describing-
registry ethos.**

**G2. Remote-managed policy authority (precedence + ETag + fail-open).**  `value=HIGH · build=large · new`
The runtime layers a policy authority (remote > MDM/HKLM > managed file > HKCU),
an ETag/checksum cache, hourly background refresh, **fail-open** on network error,
a security-check before apply, and **first-source-wins** (not deep-merge) for the
managed policy settings.
→ **DOS**: DOS has no remote-policy override; config is local. A
`policy-refresh` driver modeling this (ETag cache + background poll + fail-open +
"first source wins" to avoid ambiguity) is the enterprise-governance seam
(docs/120 big-tech adoption). Large but high-value for fleet operators.

**G3. Plugin-only customization lockdown (closed surface enum).**  `value=HIGH · build=medium · strengthens`
The runtime keeps a closed set of customization surfaces (skills, agents, hooks,
MCP); when a strict plugin-only mode is set, user/project/local sources are
blocked **at discovery time**, and only managed + plugin sources survive.
→ **DOS**: mint `PLUGIN_ONLY_<SURFACE>` refuse classes applied when an untrusted
source tries to register a hook/judge/overlap-policy. The "approved surface vs
untrusted surface" split is the governance complement to the `dos.judges`/
`dos.overlap_policies` entry-point seams.

**G4. Drop-in policy fragments (`dos.toml.d/` alphabetic merge).**  `value=MEDIUM · build=medium · new`
The runtime supports a managed-settings base file plus a drop-in directory of
fragments sorted alphabetically (systemd/sudoers style) so independent teams ship
policy without editing one file.
→ **DOS**: a `dos.toml.d/` directory (alphabetically merged into the reason/lane/
stamp registries) lets teams contribute policy fragments modularly. Pairs with
G2's authority layering.

**G5. Frozen config snapshot at the boundary.**  `value=HIGH but DOS-ALREADY-HAS · drop`
The runtime snapshots its hook config once at startup, gated by a managed-policy
authority. This is *exactly* DOS's `SubstrateConfig` "I/O at the boundary, data to
the pure core" rule (CLAUDE.md 2a). **The reader agent correctly self-flagged this
`dos-already-has`** — included only as confirmation that the runtime independently
arrived at DOS's seam discipline. No lift.

**G6. Realpath dedup + first-wins merge.**  `value=MEDIUM · build=small · strengthens`
When loading its skills directories, the runtime dedups config sources by
`realpath` to catch the same file reached via symlink/overlapping-parent. → DOS
could adopt realpath-dedup in its own file-tree overlap checks (`lane_overlap`) to
catch symlink collisions a glob compare would miss.

---

### Theme H — Loop economics (docs/145/154; `loop_decide`/`tokens`)

**H1. Diminishing-returns multi-signal continuation gate.**  `value=HIGH · byte=clean · build=small · new`
Verified: the runtime's token-budget check is a pure state-in/decision-out
function whose STOP requires **three** ANDed signals — continuation-count ≥ 3
**and** last-delta < 500 tokens **and** prior-delta < 500. A
*productivity-velocity* gate, not a hard count cap; the AND prevents false-stops
on a single slow turn.
→ **DOS**: `loop_decide` today stops on a hard `max_iterations=10` and hand-coded
consecutive-unclear breakers. Add a `diminishing_returns` rung: stop when the
*token-delta velocity* drops below a threshold regardless of count —
distinguishing "2M tokens → 1 ship" (productive-slow) from "1M tokens → 0 ships"
(unproductive). Converts the iteration cap from stop-after-N to
stop-when-unproductive. Pure, small, byte-clean (token counts are runtime-
authored). **Cleanest loop-economics lift.**

**H2. Generic circuit-breaker abstraction.**  `value=MEDIUM · build=small · strengthens`
Across the runtime (auto-compaction; permission-denial tracking with a denial
limit and a fall-back-to-prompting trigger), the same "increment on failure, reset
on success, give up after N" pattern recurs. DOS hand-codes each breaker
(`CONSECUTIVE_UNCLEAR`, `CONSECUTIVE_DIRTY_ZERO`) as ~10-15 near-identical lines.
→ **DOS**: a `circuit_breaker(outcome_kind, max_failures) -> BreakerTriggered`
facility in `loop_decide` so hosts add breakers (RATE_LIMITED, etc.) without
duplicating counter logic. *(Ironically: the rate-limit that killed this
workflow's verify pass is exactly the failure class such a breaker would
handle.)*

**H3. Verdict-repeat → escalate-the-mechanism circuit breaker.**  `value=MEDIUM · byte=clean · build=medium · new`
The runtime's denial tracking falls back from classifier to human after N
consecutive auto-denies (assume the classifier is stuck).
→ **DOS**: the verdict-based analogue — if `liveness → STALLED` (or the same
`refuse` reason) recurs N times for a lane, **change the mechanism**: escalate to
a JUDGE (Axis-6) or to HUMAN, rather than re-emitting the same verdict. "Don't
keep refusing identically; escalate the rung." Keeps the kernel pure; escalation
lives in a driver.

**H4. Continuation *nudge* (in-flight soft signal before a hard stop).**  `value=MEDIUM · build=small · new`
The runtime's token-budget check carries a nudge message — an *ephemeral* "keep
working, you're at 45% of budget, do not summarize" injected on `continue` (never
durable, never replayed).
→ **DOS**: every DOS reason is durable today; there's no *ephemeral* in-flight
nudge surface. A WARN-before-STOP nudge (wired through `dos hook posttool` →
`hookSpecificOutput`) is the soft-advisory precursor to the hard loop stop — the
intervention ladder's missing pre-BLOCK rung in the loop-economics axis.

---

### Theme I — Rewind / checkpoint (docs/164/172)

**I1. Closed restore-option vocabulary.**  `value=MEDIUM · build=small · new`
Verified: the runtime's rewind UI offers a closed restore-option enum (both /
conversation / code / summarize / summarize-up-to / never-mind) over the
(conversation × code) restore matrix.
→ **DOS**: the docs/172 rewind axis livelocked partly because subtract-vs-append
was an *implicit binary*. A `checkpoint_restore_policy` enum
(`FULL`/`STATE_ONLY`/`TRANSCRIPT_ONLY`/`SURVEY`) in `dos.toml [checkpoint]` makes
rewind strategy *pluggable per-workspace* (a Workflow forbids transcript edits;
a dev-tool allows both). Names the axis that was muddled.

**I2. Message-keyed file snapshots (the rewind-coordination DOS livelocked on).**  `value=HIGH · byte=clean · build=medium · new`
In the runtime, each file-history snapshot carries a message id;
content-addressed backups (keyed on a path-hash + version), only changed files
copied, unchanged inherit the prior reference. Rewind = lookup-by-message-id +
atomic multi-file restore.
→ **DOS**: docs/172 found a *rewind livelock* (subtract removes a symptom, the
file state and transcript drift apart). CC's model — **file checkpoints keyed to
the same message boundary as the conversation** — is the missing coordination: a
`status(run_id, message_id) -> FileSnapshot` per-turn artifact-state oracle,
deterministic over message history. This is the cross-agent accountability
surface docs/116 is blocked on: "what file state did agent X leave when it said
'done'?" **The most directly relevant rewind idea.**

**I3. Diff-preview oracle (fast has-changes vs full diff-stats).**  `value=HIGH · byte=clean · build=small · new`
The runtime splits a cheap boolean has-any-changes probe (early-exit on mtime)
from a full line-level diff-stats call. Cheap yes/no without reading backups.
→ **DOS**: `verify()` never previews verdict *magnitude*. A
`checkpoint_preview(turn_id) -> (changed_file_count, est: Option<DiffStats>)`
fast path is the load-bearing surface for the docs/126 apply-gate: *show the
human the diff before asking "commit this rewind?"* Small, high-value for the PEP.

**I4. Partial-restore as a structured verdict.**  `value=MEDIUM · build=medium · strengthens`
The runtime's restore probes the backup, creates missing dirs, retries, falls
back copy←link — restoration is often *partial* (file X backup missing, Y
restored).
→ **DOS**: `resume_plan` is binary (RESUMABLE/DIVERGED/UNRESUMABLE); add a
`PARTIAL_RESTORE(missing=[...], recovered=[...])` verdict + `repair_actions` so
the host decides "halt+alert vs continue with partial state" — the PEP needs that
granularity.

---

## 2. Cross-cutting themes

- **The runtime is the PEP, DOS is the PDP — and they compose.** Almost every
  Theme-A/C/I idea is a place where the runtime *enforces* what DOS *decides*. The
  single most valuable structural move is the `EnforcementHandler` seam (A1): it
  gives every refuse verdict a configurable consumer without making the kernel
  enforce — resolving the "detection is solved, value-capture is the open problem"
  tension (conversion-gap memory) by *changing the consumer*, exactly as that
  memory prescribes.
- **Closed-enum-as-data, everywhere.** Permission modes, memory types, restore
  options, hook events, dangerous-exec patterns, customization surfaces — the
  runtime independently reached DOS's HACKING.md "closed enum → declared data"
  pattern. Each is a near-drop-in `dos.toml` registry (G3/G4/E5/C5/I1).
- **Byte-clean by construction recurs as a discovered discipline.** The monotonic
  snapshot counter (F5), the SSRF DNS-result→socket binding (closing TOCTOU), the
  runtime-authored worker-result envelope (D1), and `tool_stream`'s own
  env-authored `result_digest` all share one rule: *let the runtime/env author the
  evidence, never the judged agent*. The runtime arriving here independently is
  strong external validation of the docs/138 invariant.
- **Structural detectors beat keyword detectors.** B1 (capability, not the word
  "dangerous") and B2 (envelope grammar) re-prove docs/158's "a SHAPE not a word"
  from a second codebase.

## 3. Refuted / downgraded / out of scope

- **Tool-stream provenance-by-resolver-kind** (permissions-pep) — *premise
  partly refuted by direct check.* The idea claimed `tool_stream` is "agnostic to
  tool kind / doesn't separate env- from agent-authored." Verified false:
  `tool_stream.py:39-44` already builds REPEATING **only** on the env-authored
  `result_digest`, with `tool_name`/`args_digest` explicitly marked agent-authored.
  The genuinely-additive residue (a per-tool-class MCP-vs-Bash provenance *kind*)
  is real but **low** value, not the medium claimed.
- **Frozen config snapshot** (G5) — `dos-already-has` (SubstrateConfig). Kept as
  convergence evidence only.
- **Forked-agent prompt-cache sharing** (tokenbudget) — provider/runtime-layer
  optimization, not a kernel abstraction; correctly self-flagged `dos-already-has`
  re: resume.
- **Closure-scoped init / stale-cache-discard ceremony / nudge-cache-clear**
  (tokenbudget) — host-layer (agent runtime) cache hygiene, `byte=n/a`, no kernel
  surface. Documented as host-integration templates only.
- **Parallel-hook executor** (stop-hooks) — a thin orchestrator, not a novel
  signal; `value=low`. Reference pattern for host hook-runners, not a kernel
  change.
- **Conditional path-pattern skills, lite-log lazy load, session-active pub/sub,
  context-delta telemetry** — niche/telemetry-only, `value=low`; parked.

## 4. Recommended next build

**Steps 1 (A1) and 2 (C4) are DONE** — `dos.enforce` + the `OP_ENFORCE` journal
record shipped. The remaining step: `dos hook pretool` (A2), then E1.

Rationale — it is the cheapest path to *proving value-capture*, which the
conversion-gap memory names as DOS's one open problem:
1. ~~**A1 + C1** give the intervention ladder a real type and a real seam~~ —
   **DONE.** The seam is `src/dos/enforce.py` (`EnforcementHandler` Protocol +
   `EffectProposal` + unshadowable `ObserveHandler` + fail-to-observe / no-escalation
   `run_handler` + `dos.enforce_handlers` resolver), 22 tests, on `dos doctor`. C1's
   *decision type* was already shipped in `dos.intervention` (the doc's
   first-draft claim that it was new is corrected above). So the structural home
   for the whole intervention ladder now exists; a ruling handler (interactive /
   block / delegate) is a driver away.
2. ~~**C4** makes every intervention *durable, auditable, resumable* by journaling
   enforcement outcomes~~ — **DONE.** `OP_ENFORCE` + `enforce_entry` in the
   `lane_journal` WAL, folded state-neutral (the `OP_REFUSE`/`OP_HALT` precedent),
   carrying `EffectProposal.to_dict()` + correlation. 6 tests; journal-reader suites
   green. "Which call was blocked, by which handler, what was substituted?" is now
   answerable from the spine — the ARIES gap closed.
3. **A2** (`dos hook pretool`) then turns the ladder's BLOCK rung from a reported
   string into an *enforced* pre-tool deny via the verified
   `PreToolUse permissionDecision` seam — the mediated-write moment, bound exactly
   where `dos hook posttool` already lives. The handler from step 1 is what decides
   whether the verdict becomes a deny.

Together these convert DOS's "we detected it" into "we did something about it,
and there's a byte-clean record proving what" — without the kernel ever leaving
PDP territory (the handler, not the kernel, enforces). The seam (step 1) is the
foundation everything in Theme A/C reaches from; it is now in place.

A fast follow with outsized leverage: **E1 (memory provenance spine)** — it fixes
docs/103 for *this very repo's* memory store, is small, and is byte-clean.

---

*Provenance: reader fan-out `wf_516412fb` (10 subsystems, 85 ideas, cached in the
run journal after the verify/synthesis phases were rate-limited); survivors
hand-verified against the production agent runtime's behavior and `src/dos/` on
2026-06-06.*
