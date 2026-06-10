# docs/191 — Proactive DOS: banking the verdict *before* the failure, on a non-agent denominator

> Dated synthesis — 2026-06-06. Produced from a 6-class adversarial workflow
> (`wf_59324748-561`: 14 candidates mined across the real problems we have
> actually hit → adversarial skeptic per candidate → ranked synthesis;
> 8 survived, 6 refuted). **Caveat of record:** 10 of the verify agents died to a
> transient server rate-limit (firing many concurrent verify agents trips the
> limiter — the same wipe that hit docs/189). So a handful of survivor/refute
> verdicts are *miner-claimed but not independently skeptic-verified*; the
> load-bearing facts below were **hand-verified against file:line / a live run**,
> not relayed. Companion to docs/188 (killed the rank-1 agent-side frontier bet),
> docs/189 (CC ships the PEP), and docs/190 (coordination measured). This doc is
> the **unifying lens** those three gesture at separately.

## 0. The question

*How can DOS be used **proactively** to solve real problems we have seen — and
what apparent **blocks** dissolve when re-framed through a kernel primitive?*

## 1. The organizing reframe (the one lens)

The conversion-gap finding (`wf_6647ad3c`) was: *detection is solved; value-capture
is the open problem; change the **consumer**, not the threshold.* This doc pushes
it one step earlier in **time**:

> **Change the consumer AND the moment.** Use the kernel's verdict *before the
> failure lands*, and bank it on a **denominator that is not an agent's
> pass-rate.**

Every refuted "lift" failed for one structural reason — it routed a sound verdict
**back to a frontier agent's next action**, where the conversion ceiling is
0.00pp (docs/170, docs/188). Three legitimate consumers remain, and **every
surviving play is one of them**:

- **(a) non-blocking re-surface on our OWN infra spend** — poll-loops, our tokens
  (PostToolUse `additionalContext`; structurally cannot withhold a turn).
- **(b) a non-agent FLEET denominator** — collisions averted / review-hours
  skipped; monotone in horizon×fanout, 0 at N=1 (the arbiter; the PreToolUse PEP).
- **(c) a write-GATE where the MODEL authors the fix and the kernel only ADMITS
  it** vs env-authored ground-truth bytes (PreToolUse `deny`; witness-gated
  `done`). Never author-and-believe a correction.

The detectors are solved. This is **entirely a routing problem**, and the routing
target is the **host's own enforcement and coordination surfaces** — not the
agent's correctness score.

## 2. Ranked proactive plays (survivors), best traction/$ first

### #1 — Wire PostToolUse so poll-loops are cut in-flight · SHIPPABLE NOW
- **Block:** Read/Bash poll-loops burn *our* session tokens; today the only catch
  is a post-mortem trajectory audit.
- **Shift:** Everything is already committed — `cmd_hook_posttool` (`cli.py:2346`)
  replays the session stream, classifies via `tool_stream.classify_stream`, emits
  the exact CC dialect (`warn_payload`, `posttool_sensor.py:255`). Tool-agnostic
  (keys on `(tool, args_digest, result_digest)`) → catches `Bash(tail x.output)`
  exactly like `Read`, zero extra code. **`.claude/settings.json` has only a Stop
  hook — one config block away** (verified).
- **Consumer/denominator:** (a). Re-surfaces to *our own* agent's next turn; banks
  our tokens/wall-clock; never routes to a pass-rate.
- **Honest magnitude — SMALL and already characterized:** the byte-clean verdict
  fired on **1 of 9** read_loop-flagged sessions (the histogram overstates ~9×;
  the self-supervision-as-token-savings pitch was **refuted** — see §4). Pitch as
  the cleanest **dogfood/adoption demo** + free Bash coverage, *never* a
  tokens-saved-per-month win.
- **Cheapest test:** add the `PostToolUse` block; one throwaway session, Read one
  unchanged file 3×; confirm `additionalContext` on turn 4 + `.dos/streams/<sid>
  .jsonl` has 3 STEP records, the 3rd stamped `verdict_state=REPEATING`.

### #2 — The $0 real-collision footprint as the honest coordination headline · SHIPPABLE NOW (measured)
- **Block:** coordination value was asserted from a *simulated* `lie_rate=0.12`.
- **Shift:** `benchmark/fleet_horizon/measure_real_collisions.py` replays the
  operator's own ~2764 real CC transcripts through the **byte-identical kernel
  rule** (`_tree.prefixes_collide`). **Hand-verified live run today:**
  **21 concurrent cross-session same-path collisions** / 179 writing sessions /
  4210 writes (**4.99 / 1k**); **238 of 1044 paths written by >1 session** — incl.
  `MEMORY.md` (two sessions 14.8 s apart), `cli.py` (113 s), `__init__.py`,
  `stamp.py` + its test. Zero injection, zero fake rate, zero model calls. (This
  is the docs/190 measurement; one workflow skeptic wrongly called "21"
  unsubstantiated — that skeptic never ran the script; I did.)
- **Consumer/denominator:** (b). Contended-path surface on git-write events; 0 at
  N=1, grows with concurrent fanout — the monotone equation **observed, not
  assumed.**
- **Honest bound:** an *upper bound* (proxies concurrency by write-timestamp
  proximity, counts same-absolute-path equality, not full glob algebra). The
  `kernel_prefixes_collide_agrees` flag is a tautology — drop/fix it.
- **Cheapest test:** already runnable (`--json`). One extension: `--by-session-
  count` bucketing to **draw** the 0@N=1→rising curve from real data.

### #3 — `dos hook pretool`: occupy CC's PreToolUse `permissionDecision` · NEEDS A BUILD (~40 lines)
- **Block:** DOS is a sound PDP with **no PEP** — it detects, cannot prevent.
- **Shift:** the PEP already exists *in the host.* CC's PreToolUse returns
  `{permissionDecision:"deny", ...}` **before** execution (docs/189; verified-real,
  unlike the `dos hook stop` no-op). The arbiter is already pure + pre-effect:
  `arbitrate` (`arbiter.py:146`) takes `requested_tree + live_leases` → typed
  `SELF_MODIFY` / collision / `CLASS_BUDGET_EXHAUSTED` refuse, no I/O. Missing:
  a ~40-line `cmd_hook_pretool` (sibling of `cmd_hook_posttool`; **confirmed
  absent**) lifting `tool_input.file_path` → single-element `requested_tree`,
  calling `arbitrate` **directly** (not `enforce.run_handler` — wrong seam), `deny`
  only on a structural refuse.
- **Consumer/denominator:** (b). Writes-PREVENTED. Out-of-box value is **only** the
  narrow `SELF_MODIFY` case; the fleet-collision headline is conditional on lease
  discipline vanilla CC fleets lack (0 at N=1, 0 with no leases).
- **Cheapest test:** build the stub; wire one `Write|Edit`-scoped `PreToolUse`
  block; second concurrent agent attempts an Edit in the live `src` lane. Decisive:
  does CC actually withhold it + surface the reason? (Probe the seam before
  believing it — the `dos hook stop` no-op precedent.)

### #4 — PreToolUse contract-gate: converge the schema-blindness underfill loop · NEEDS A BUILD
- **Block:** schema-blindness thrash (`create_filter` emits `from1` for `from`) —
  up to 48 consecutive malformed re-issues; WARN re-surface is **refuted** on it
  (the env already re-prints `criteria.from: is required` every turn, ignored).
- **Shift:** the *one* underfill sub-case that converts — gate the
  **env-named-required-field-absence** sub-case at the real PEP: on a PreToolUse
  for a tool that already failed schema-validation this session (read the fossil
  stream), check proposed args vs the env-named required SET; `deny` (with the
  env's required-field list as reason) when a required field is still absent;
  **abstain=allow** when the env did not name the gap (route true-omission to
  HUMAN). The model AUTHORS the fix; the kernel only ADMITS it vs the known
  contract. NB: the model **already receives** `inputSchema.required[]` up front
  (`llm_client.py:188-200`) and ignores it — so the gate must fire on the **env's
  post-failure required bytes** (reactive, byte-clean), never the pre-call schema
  (a no-op: schema-blindness ≠ schema-absence).
- **Consumer/denominator:** (c). Malformed writes refused pre-execution.

### #5 — Witness-gated `done`: an MCP `dos_attest` tool · NEEDS A BUILD
- **Block:** 83.3% of frontier failures are **silent** (well-formed, narrated
  success, stopped) — a `verify()` problem (out-of-trace world-read), not
  tool_stream/liveness.
- **Shift:** move the oracle off the transcript onto the artifact, and route the
  agent's claim-of-done **through** it. The seam is green: `evidence.EvidenceSource`
  + `gather_evidence` + `believe_under_floor` (`evidence.py:412`) + the
  `os_acceptance` exit-code witness (`os_acceptance.py:76`). The gap is one tool
  wide: `dos_mcp/server.py` exposes **only `dos_verify`** (git rung) — no
  attest/believe tool (verified: 7 tools, none witness-gated). Add
  `dos_attest(subject=acceptance_command)` → `gather_evidence(OsAcceptance…)` →
  `believe_under_floor`. The witness bytes are the env-authored OS exit code;
  `believe_under_floor` **structurally refuses** an `AGENT_AUTHORED` "it passed"
  (pinned: `test_agent_authored_attestation_NEVER_grants_belief`).
- **Consumer/denominator:** (c). Withholds the terminating success-belief *before*
  the false DONE lands; targets the `CLAIM_SUCCESS×WROTE=95` cell.
- **Hard caveat:** the **$0 offline replay is NOT decisive** — the cached corpus
  has no run-start snapshot / world end-state to witness. Build it cheaply over
  green primitives, but the decisive evidence costs a **live env stand-up**. Treat
  `NO_SIGNAL`-on-abstain as a **non-go** (an absent witness must never read "done").

### Companion to #5 — `dos.toml [evidence]` per-task acceptance-command map
Pre-declare, per lane/task, the cheap byte-unforgeable world-read that decides done
(the closed-config-as-data pattern, mirroring `[reasons]`/`[stamp]`). Fold it
through `believe_under_floor` as a rung **above** git-grep in `cmd_hook_stop`: a
stop is admitted only if `(git-ancestry OK) AND (declared world-witness ATTESTS)`;
degrades to today's git-only gate when no entry exists. **Cheapest test runnable
HERE, offline:** `[evidence] command="python -m pytest -q"` for the `src` lane;
make a deliberately-broken commit whose *subject* carries the ship-stamp (git-grep
→ SHIPPED); confirm `dos hook stop` now returns `ok:false` because pytest REFUTES.

## 3. Apparent blocks that dissolve (reframes that survived)

- **"0.00pp frontier defensive lift = DOS doesn't help."** → the kernel being
  **correctly silent.** A model that fails less AND mints less *should* trip an
  advisory distrust kernel ~0 times — harmlessness is the proof of **no
  false-alarm tax on competent agents.** That frees the value onto the orthogonal
  **coordination** axis, backed by §2's real measurement. REAL: the silence is a
  *measured* property of a sound detector.
- **"DOS detects but can't prevent (no PEP)."** → it doesn't need to *become* a
  PEP; it **occupies the host's.** CC ships a verified pre-effect `deny`; the
  arbiter is already a pure pre-effect PDP. Only a ~40-line dialect adapter is
  missing.
- **"Schema-blindness is unfixable in-context."** → true for any *re-surface*,
  false for a *gate.* The cure isn't telling the model again; it's **refusing the
  malformed write** until the model's own re-issue satisfies the env-named set.
  Byte-clean, convergent by construction.
- **"Frontier-silent failures are invisible."** → invisible *in-trace*; visible to
  a **world-read.** A result-state witness bound to the done-decision, abstaining
  on the semantic residue. REAL as mechanism (green, pinned) — with the honest
  asterisk that proving it needs the live env.

## 4. Honest cuts (refuted — do not re-propose)

- **Poll-loop catch as a tokens-saved magnitude win.** The audit `read_loop` flag
  is an order-blind histogram; `classify_stream` needs a *consecutive* same-triple
  run on env bytes. Fired on **1 of 9** → ~2 saved reads, dwarfed by cache-read
  tokens it doesn't touch. Keep #1 as DEMO/adoption only; score by byte-clean
  firings.
- **"Inject-contract via `additionalContext`" as a third cure class.** Re-surfaces
  the env's `is required` bytes the model already receives and ignores 2–48× —
  collapses into the refuted WARN. Build the **gate (#4)**, not the renderer.
- **"Complete-contract pre-gate" (schema source-2).** `inputSchema.required[]`
  reaches the model up front and is ignored → no-op (schema-blindness ≠
  schema-absence). Only source-1 (env post-failure bytes) fires — the already-named
  reactive F2.
- **"NO_MUTATION trip-wire as a ready-to-ship 100%-sound rung."** Not computable
  offline (no world snapshot in the corpus); the only offline proxy reads the
  agent-authored *tool name* — the §5a-forbidden in-trace stretch. The 33 cells are
  `_frontier_contingency.txt` ESTIMATES, not an FP=0 detector. The sound version is
  UNBUILT (= F3/PEP status).
- **"Anti-self-readback guard" as a standalone win.** Already shipped + pinned
  (`believe_under_floor` filters `AGENT_AUTHORED`). It's the **named soundness
  constraint ON** #3–#5, never a standalone deliverable.
- **"Message-keyed file checkpoints (rewind isn't dead)."** Mis-sold as a
  `rewind.py` extension — rewind operates only on transcript turns (opaque bytes);
  zero file-state surface. It's a net-new content-addressed store, **dominated** by
  the already-shipped lease arbiter (prospective region-lock) for the collision job,
  and the A2A surface it claims to unblock (`dos status`) already ships and
  deliberately shares the *adjudicated residue*, not working-tree bytes (the
  blackboard docs/116 warns against).

## 5. The one cheapest next move

**Add a `PostToolUse` block to `.claude/settings.json` running
`dos hook posttool`, then run one throwaway session that Reads the same unchanged
file 3×.**

Highest traction/$: the sensor is fully committed (`cmd_hook_posttool`,
`cli.py:2346`; 28 green tests; correct CC dialect), settings.json today has **only**
a Stop hook, and the bank is on our own non-agent denominator via a structurally
non-blocking re-surface. **Decision in one session:** does `additionalContext`
appear on turn 4, and did `.dos/streams/<sid>.jsonl` accumulate 3 STEP records, the
3rd stamped `verdict_state=REPEATING`? That single observation settles whether the
in-flight path works against the real CC harness — and it is the **identical config
mechanism** that unblocks #3 and #4, so it de-risks the whole PreToolUse/PEP line
for the cost of one settings entry.

## 5a. UPDATE (2026-06-06, same day) — play #1 SHIPPED + verified live

The cheapest move was executed. `.claude/settings.json` now wires the
`PostToolUse` seam (`e2d5aa9`): matcher `Read|Bash|Grep|Glob`, **synchronous**
(`additionalContext` must land before the next turn — the Stop audit is async
because it's fire-and-forget; this is not), direct `python -m dos.cli hook
posttool` exec so CC passes the event on stdin.

**A real bug was caught by verifying against the CC SOURCE, not the docs prose**
(the docs/189 lesson, re-earned): a claude-code-guide consult said the PostToolUse
result key is `tool_response` for #3 but **`tool_result`** for the input field.
The sensor reads only `tool_response`/`tool_output` (`posttool_sensor.py:142`) — if
`tool_result` were right, the sensor would find no result → `result_digest=None` →
**never fire on a live session** (the silent-no-op class that bit `dos hook stop`).
**Ground truth settles it:** CC v2.1.88's own Zod contract
`PostToolUseHookInputSchema` (`coreSchemas.ts:442`) declares **`tool_response`** —
the sensor's primary key is correct, no bug. `additionalContext` IS consumed for
PostToolUse (`toolHooks.ts:133-140`). The bundled config-skill corroborates
(`updateConfig.ts:177`: `"tool_response": {...}  // PostToolUse only`).

**Verified live:** 3 byte-identical events (one `session_id`) → events 1-2 emit
nothing (ADVANCING), event 3 emits the exact dialect with the env digest
`923813462f5d1a1c`; the `.dos/streams/<sid>.jsonl` fossil accumulated 3 STEP
records, the 3rd stamped `verdict_state=REPEATING`. **Known cost:** ~0.35 s/tool
call (Python interpreter cold-start), added synchronously to every matched call —
the honest price of the in-flight catch. 65 posttool+tool_stream tests green.

What remains for play #1 is the *field* observation the offline test cannot give:
run real sessions and count how many get a re-surface and whether the model then
breaks the loop (the docs/188 kill-criterion, now on the live seam).

## 6. Provenance / cross-refs

- Workflow: `wf_59324748-561` (31 agents, 2.18M tokens; 10 verify agents lost to a
  transient rate-limit — verdicts on those candidates are miner-claimed).
- Hand-verified: `measure_real_collisions.py --json` (21 collisions, live);
  `cli.py:2247/2346` (`cmd_hook_stop`/`posttool` present, `pretool` absent);
  `dos_mcp/server.py:108-369` (7 tools, no attest); `.claude/settings.json`
  (Stop-only); `posttool_sensor.py:255-298` (correct CC dialect vs the `dos hook
  stop` no-op it documents).
- Builds on: docs/170 (frontier lift = coordination), docs/177 (frontier-silent),
  docs/188 (rank-1 agent-side bet killed), docs/189 (CC ships the PEP), docs/190
  (coordination measured + F3 gateability), the conversion-gap synthesis
  (`wf_6647ad3c`).
