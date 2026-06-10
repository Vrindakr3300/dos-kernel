# docs/173 — DOS for tool-related problems: the audit-grounded detector line

> The kernel is the part that doesn't believe the agents — and a **tool call** is
> exactly the moment an agent narrates an effect on shared state it did not author.
> This is the design surface where DOS's byte-author invariant (docs/138) earns its
> keep: every tool-failure verdict keys on bytes the **environment** wrote, never
> bytes the **agent** wrote.

**Status:** analysis + one shipped artifact (`benchmark/toolathlon/dos_solves_output_poll.py`,
commit `ed74d6e`). Grounded in the fresh trajectory audit
(`.dos/audits/trajectory-audit-20260605T224553Z.md`) + the two existing gyms
(Toolathlon, EnterpriseOps-Gym). Every load-bearing claim below was adversarially
verified (workflow `wf_78d6ccc0`, 7 agents) — corrections are folded in and marked.

---

## 1. The headline finding — two different "read-loop" signals, only one is sound

The 2026-06-05 trajectory audit (40 `dos` sessions) flagged `read_loop` as a
**HIGH systemic finding** [MEASURED]. The instinct is to read that as "9 read-loops the
in-flight detector would catch." **That instinct is wrong, and the distinction is the
whole point of this doc.** There are two signals, and they are not the same thing:

| Signal | Measures | Order? | Gates on env bytes? |
|---|---|---|---|
| **trajectory-audit histogram** | TOTAL reads per file (≥4 threshold; e.g. `test_toolathlon_replay.py` read 17×) | order-**blind** | no — pure count |
| **`tool_stream.classify_stream`** | the **consecutive trailing run** of identical `(tool, args, result_digest)` | order-**sensitive** (`_trailing_run` walks backward; any None/different step BREAKS the run) | **yes** — keys on env-authored `result_digest` |

Replaying the audit-named sessions through the shipped `dos.tool_stream` (keyed on the
real env-authored result bytes): **only `2cd77e93` FIRES** [MEASURED — reproduced
independently in the adversarial pass; 44/44 `test_tool_stream.py` green]. It is a
`.output` **poll-loop**: `Read bdbokqf2c.output` five times in a row (steps #55–#59), the
env returned an **identical 126-byte** payload (`sha256[:8]=deedb29c`) each time; the
verdict climbed ADVANCING → REPEATING(run 3,4) → **STALLED(run 5)**, then the trailing
run reset back to ADVANCING. The agent was burning Read calls polling an unchanged
background-task file — the `project-dos-poll-loop-antipattern` made concrete.

The other audit-flagged sessions **correctly do not fire**: their re-reads were either
*interleaved* (the trailing run resets) or returned *different bytes* (real progress —
e.g. `5c5d71f1` read `dos_react.py` at five different offsets, five different digests).
Result coverage was 97–100% and the max consecutive-identical run was 1 in all of them —
this is genuine non-firing, not a missing-tool-result artifact.

**Corrections from the adversarial pass (honored):**

1. **Recovery breaks at #60, not #61.** The verdict returns to ADVANCING at step #60 (an
   interleaved read of a *different* file), one step before the `.output` file's own new
   bytes at #61 — *any* non-matching step breaks the trailing run. A counterfactual
   stripping the interleaved read confirms the new `.output` bytes (`39dd5ac3 ≠ deedb29c`)
   are **independently sufficient** to break STALLED, because the repeat-identity key
   includes the env-authored `result_digest`. The mechanism holds either way.
2. **The session counts are window-dependent.** The exact tallies (40/9/6) wobble with the
   window-selection rule (first-prompt time vs file mtime, and the read-count threshold);
   an independent strict top-40-by-mtime histogram found 8 read_loop sessions, with
   `2cd77e93` at mtime-rank 40. State it as: **of the independently-detected read_loop
   population, exactly one (`2cd77e93`) fires the byte-clean detector.** The detector
   behavior is correct regardless of window; only the counts move at the edges.
3. **The relationship is a strict subset, not crossing sets.** On this corpus
   `tool_stream ⊂ audit` — tool_stream caught nothing the audit missed. That is exactly
   what you expect from a *coarse triage layer* (the histogram, over-counts) vs a *sound
   gate* (tool_stream). "Complementary, not redundant" is earned: the decisive
   demonstrator is `fcb319cf`, which a histogram flags as a read-loop (identical-byte
   `.output` reads) but tool_stream correctly **withholds** because the reads were
   interleaved. No case was found where tool_stream wrongly under-fires.

**Net:** the audit histogram is a broad **coarse-triage cost lens**; `tool_stream` is the
**strict, byte-clean, in-flight gate**. Do not conflate the audit's read-loop count with a
tool_stream catch rate.

---

## 2. The four shipped detectors as a unified tool-trust surface

All four are **byte-clean** (the judged agent did not author the deciding bytes) and all
four are **advisory** (they REPORT; they never author a process cut).

| Detector | Failure class | The byte it keys on (env-authored) | Gym + headline number | Measured? |
|---|---|---|---|---|
| **tool_stream** (`tool_stream.py:285`) | Read/poll-loop — same `(tool,args,result)` recurs N× consecutively; REPEATING@3, STALLED@5 | `result_digest` of the result the gym MCP server / FS returned; None never matches → fail-safe break | **Toolathlon:** STALLED/repeat_run **22** on the real `8bd8c736` read-loop (177.9M cache-read tokens). **EnterpriseOps:** `p_stuck=0.0%` (n=757, the strong-model null). **Fresh audit:** fires on 1 of the read-loop population (`2cd77e93`) | **MEASURED both gyms** |
| **terminal_error** (`trajectory.py:494`; SSOT `additivity.py`) | Terminal env error narrated-past-as-success — hard error in the closing window no later same-tool success recovered | the env's **error-envelope bytes** (`is_struct_error`: MCP -3xxxx / isError / `Error:` / Traceback / nonzero exit) | **Toolathlon SSOT:** **76 catches, prec 95.0%, false-alarm 0.24%; 75/76 net-new vs the pair; union recall 4.74%→6.18% (+30% rel); 9 net-new on the frontier.** EnterpriseOps: **wired, NO number** | **MEASURED Toolathlon; UNMEASURED EnterpriseOps** |
| **dangling** (`dangling_intent.py`; `replay_dangling.py`) | Dangling intent / premature stop — agent's own terminal narration admits an unmet obligation; no later tool-result satisfies it | the env-authored **absence** of any `tool_result` after the terminal narration; the cue is agent-authored but read only on the **against-interest** axis | **EnterpriseOps:** recall **0.26** (paired, n=35) / 0.13 (full, n=280); false-fire **0.0** (n=8 passes). Live fix-conversion A/B: **wash-to-negative on a strong model, value=null** (n=4) | **MEASURED EnterpriseOps; pair-member Toolathlon** |
| **precursor** (`precursor_gate.py`; `precursor_grammar.toml`) | Acting before a mandated precursor fired — mutating call whose config-declared precursor produced no earlier result. **Firing-PRESENCE only** | whether a precursor-named tool produced **any** result before this call's index (a structural `tool_name` membership scan — never a relation/clause-satisfaction check) | **NEITHER gym — no number.** Grammar = **2 hand-authored rules**; the 13 real gym tasks yielded almost no clean Half-A sequencing obligations | **UNMEASURED on both — any figure would be ESTIMATED** |

**The unifying invariant (docs/138):** in every row, the bytes the verdict keys on were
authored by the environment, not the judged agent. The agent cannot forge "the env
returned the same bytes," "the env returned a hard error," "a prior tool produced a
result," or "no tool fired after I stopped." That is what makes all four sound and what
keeps all four from degenerating into satisfaction predicates (the §5a mirror-verifier
trap). Each detector's WARN re-surfaces an **env-authored** byte the agent already holds —
which is why re-presenting it is harmless if the agent was right and helpful if it was
stuck.

---

## 3. The pathology taxonomy with DOS status

### SHIPPED (a byte-clean catch exists and is built)

| Pathology | Deciding byte-author | Note |
|---|---|---|
| **Read/poll-loop** (byte-identical repeated result) | gym authored `result_digest` | `tool_stream`; §1 is the live nuance |
| **Eventual-consistency poll vs genuine stall** | same `result_digest`; sound by *refusing to author a satisfaction predicate* — WARN re-surfaces, never cuts | the honest hole made structural; `tool_stream_eval` scores recovered-rate vs false-resurface-rate |
| **Minted/hallucinated tool argument** | gym authored the prior read bytes; corpus has **no AGENT_AUTHORED member** | `arg_provenance` — 0.00% false-nudge on 249 real calls, ~83% recall on injected mints |
| **Acting before a mandated precursor** | gym authored the PRESENCE of the precursor's result | `precursor` — shipped but **empirically unquantified** |
| **Narrated past a hard terminal error** | MCP gateway authored the error envelope; soundness needs a TIGHT grammar (loose substring → 65% fire @ 69% false-alarm) | `terminal_error`, the Toolathlon SSOT |
| **Dangling intent / honest-but-premature stop** | agent cue read on the against-interest axis + env-authored absence of any later result | `dangling`; forgeable only by **suppression** → degrades to baseline (safe direction) |

### DESIGN (specified, not built / not owned offline)

| Pathology | Why design-only |
|---|---|
| **Confidently-wrong final content** (right object, wrong content, no in-trace cue) | The **DOMINANT** frontier failure (~59% of top-4 models confidently claim completion while failing). NO in-trace byte betrays it — the agent never re-read the state. The only byte-clean catch is a **fresh THIRD_PARTY world-read AFTER the run** (`derived_witness`/`believe_under_floor`), which DOS does not own offline (a recorded trace can't supply a fresh world-read). Cost tier = the live re-read = the benchmark's own oracle rung. DOS-specific value here is **attribution** (which claim was false), not new ground truth. |
| **Required-arg underfill on a write** | Cleanest residual extension (reads ZERO prose; checks an empty env-schema-required arg against env-authored schema bytes). Honest cap (docs/150 §6): structurally blind to the never-called-tool shape → low-single-digit insurance, correctly noted-not-built. |
| **Error-streak walk-past** (N consecutive env errors) | Same provenance as terminal_error; a run-length over env error envelopes. Largely **subsumed by terminal_error** (which already requires "no later recovery"). |
| **Cross-tool set-coverage shortfall** (claimed-N vs env-enumerated-N) | Split provenance: the cardinality is env-authored, but the JOIN ("is this the required set?") is an agent-authored relation = the mirror-verifier trap. Sound only for the narrow subclass where one env tool both enumerates and is the operate target. Prototype-only. |

### OUT OF SCOPE (no env-authored byte can decide it — DOS structurally refuses)

| Pathology | Why DOS forfeits it |
|---|---|
| **Forbidden-action / wrong-resource policy violation** (NL prohibition) | "Does the policy forbid THIS action?" is NL-prohibition inference — the predicate is agent/wrapper-authored from agent-visible prose, forgeable-in-favor, with a brutal 660:30 false-block downside. DOS owns only **Half-A** (env-authored precursor PRESENCE); **Half-B** (the prohibition relation) is correctly DROPPED. |
| **Premature-completion via silent planning gap** (no narration) | The **majority** of premature completions (the measured ~92% head). NO byte betrays it: the env records what an agent DID, never what it was REQUIRED to do; no narration on either axis, no failed tool result (the tool was never called). Catching it needs a planner/oracle-plan — the +14–35pp lever DOS forfeits **by doctrine** (building it makes DOS a second unverified reasoner). The picker-side reconcile (docs/168) can detect-and-KEEP an incomplete unit across runs *once an oracle confirms* non-completion — but that is not a per-trajectory catch. |

---

## 4. Where it binds in the agent runtime — and the honest no-ops

### The `.output`-poll seam (the one that matters for the fresh audit)

The `2cd77e93` poll-loop binds to **exactly one** Claude Code extension point: the
**PostToolUse hook**. It is the only CC seam handed *both* `tool_input` (the `.output` path
the agent authored) *and* `tool_output` (the env-authored result bytes the verdict keys
on). The design binding:

1. A PostTool sensor digests each call as
   `(tool_name.casefold(), args_digest=hash(sorted tool_input), result_digest=hash(tool_output))`.
2. Appends it to a `session_id`-scoped `.dos/streams/<id>.jsonl` accumulator.
3. Runs `tool_stream.classify_stream` over the accumulated `ToolStream`.
4. On REPEATING/STALLED, re-surfaces the held value as a **non-blocking** WARN —
   `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"<the repeated env value + 'this .output returned the same N bytes M times; the background task has not progressed'>"}}`
   — **never** `decision:block`.

This *preserves the legit poll*: when the env returns different bytes, the trailing run
resets and `classify_stream` breaks back to ADVANCING on its own. A real
eventual-consistency poll is never cut; only a truly-stuck identical-byte loop is surfaced.

### Honest warnings (they downgrade the status of every binding above)

- **The four tool-failure detectors are bound to ZERO live CC/MCP seams today.**
  `tool_stream` reaches CC by *no live seam* — only offline `dos tool-stream-eval` over
  replayed `StreamCases`; the others run only inside the gym harnesses. There is **no
  `dos hook pretool`, no `dos hook posttool`, no PostToolUse sensor** — the `hook`
  subparser exposes only `stop` (`cli.py:5036`). The PostTool sensor that would catch the
  `.output` poll-loop is **design-only** (docs/165 Tier 1).
- **The flagship `dos hook stop` is a SILENT NO-OP against real Claude Code** (verified by
  hand-read): `cli.py:2333` emits `{"ok": false, "reason": …}` then returns 0. Real CC Stop
  hooks honor only `{"decision":"block"}`, `{"hookSpecificOutput":{"additionalContext":…}}`,
  exit 2, or `{"continue":false}` — **none** of `{"ok":false}`. The agent stops anyway. The
  repo's `test_hook_stop` is a **mirror-test** (asserts the bytes match the shape DOS chose,
  never against a CC instance honoring them), which is why the no-op went green. docs/165 §2
  names the ~5-line fix. Until it lands, the whole Stop family inherits the dead byte.
- **MCP is structurally weaker than a hook for this.** The 7 `mcp__dos__*` tools make
  verify/arbitrate/recall *callable* but never *automatic* — the agent must choose to call
  them, and **none of the four tool-failure detectors is an MCP tool at all.** The
  waste-catching path is the hook surface (the runtime insists), not MCP (the agent can
  decline). "MCP-server-as-hook is not a thing" (docs/134 §9).
- **The DOS lane-journal join is benchmark-only / sparse:** 40 trajectory-only sessions vs
  3 journal-only leases, **0 refusals → no contention-vs-waste hit.** Ordinary CC work in
  this repo does not populate the WAL, so any binding keying on `run_id`/lease has no live
  identity. The prerequisite that does NOT exist (docs/165 Tier 3): a CC
  `session_id ↔ DOS run_id/start-SHA/lease` seam (`run_id` is minted from
  epoch/pid/monotonic, no `session_id` link).

---

## 5. The single highest-value next build

**Build the `dos hook posttool` tool_stream sensor (the PostToolUse binding in §4).**

Justification from the audit's *real* waste, not theory:

1. **It catches the one thing the fresh audit actually proved is real and current.**
   `2cd77e93` is a ground-truth-verified poll-loop on *this* repo, *this* week, reproduced
   independently and confirmed by the adversarial pass. Every other shipped number is an
   old job loop (`8bd8c736`), a strong-model null (`p_stuck=0.0%`), or a gym replay. The
   PostTool sensor turns the *only live positive catch* from a post-hoc audit finding into
   an in-flight WARN.
2. **It is the cheapest build with the cleanest soundness story.** The verdict
   (`classify_stream`) is already shipped and green; the eval harness (`tool_stream_eval`)
   is shipped; the byte-clean property is proven. What's missing is a **boundary-coordinate
   adapter**, not a kernel change — and it does **not** require the absent `session_id ↔
   run_id` seam, because tool_stream keys on the in-process stream, not the WAL.
3. **It is the only shipped detector whose value can move success UP, not just prevent a
   wrong write.** Re-surfacing the env-authored value the agent already holds converts a
   doomed re-read loop into a finished task on the **same budget** — and its value is
   independent of minting, so unlike `arg_provenance`/the intervention ladder it does
   **not** vanish on a strong model (it fires on *any* looping model).
4. **The WARN is safe in both branches.** A legit poll that returns different bytes resets
   the trailing run and is never cut; re-presenting the env's own prior bytes is harmless
   if the agent was right to wait and helpful if it was stuck.

Explicitly *not* the top pick: fixing `dos hook stop`'s dead byte is higher-profile (the
docs/134 keystone) but it catches premature-completion, whose dominant head is the **silent
stopper DOS structurally cannot own** (§3 out-of-scope) — so its ceiling is the narrating
subset. The PostTool tool_stream sensor catches the waste the audit *measured this week*,
on the cleanest footing, for the least code. Do that first; the Stop fix is the natural
second.

---

## Operator summary

1. **The audit histogram (order-blind total reads) and `tool_stream` (consecutive run
   gated on env-byte identity) are DIFFERENT signals** — only `2cd77e93` (a `.output`
   poll-loop, 5× identical 126B `deedb29c`) fires the byte-clean detector [MEASURED]; the
   histogram is coarse triage, tool_stream is the sound in-flight gate.
2. **Four detectors form the tool-trust surface** — tool_stream/terminal_error are MEASURED
   (Toolathlon SSOT: 76 catches @95%/0.24%; STALLED repeat_run 22), dangling is MEASURED on
   EnterpriseOps (recall 0.26 paired), **precursor is UNMEASURED on both** — all byte-clean,
   all advisory.
3. **Today they bind to ZERO live CC seams** (`dos hook stop` is a silent no-op vs real CC;
   only offline eval + gym harnesses exist) — **the single highest-value build is the
   `dos hook posttool` tool_stream sensor**, the smallest change that catches the one real
   waste this week's audit found in-flight.

---

**Artifacts:** `benchmark/toolathlon/dos_solves_output_poll.py` (the firing case, byte-exact
against the real transcript — commit `ed74d6e`) · `benchmark/toolathlon/dos_solves_read_loop.py`
(the old job `8bd8c736` case) · `.dos/audits/trajectory-audit-20260605T224553Z.md` (the audit).
