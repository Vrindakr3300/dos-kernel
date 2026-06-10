# 176 — Live trajectory verification: walk, re-walk, and prune the known-bad path

> *Dated framing — written 2026-06-06. A snapshot of the concept space for "DOS
> for tool verification + walking/re-walking agent trajectories live + pruning a
> known-bad path instead of re-orchestrating a fresh context window." Every
> status label (PROVEN / BUILT / DESIGNED / UNBUILT) and every number is a dated
> observation against the working tree on that day, not an eternal truth. Doc
> numbers 173–175 were taken by concurrent work; this lands at 176. Produced from
> a grounded multi-lens exploration (10 agents) cross-checked against the live
> modules, then hardened by two adversarial skeptics — §4 folds their findings in
> rather than papering over them.*

## 0. What changed under the framing while it was being written (read first)

The exploration that produced this doc was commissioned to map a concept. Three
things in the working tree moved the ground truth *after* the map was drawn, and
the doc reflects the moved ground, not the brief:

| Surface | Brief assumed | Working tree on 2026-06-06 | Verified by |
|---|---|---|---|
| `tool_stream.classify_stream` (detect) | shipped, replay-proven | unchanged — PROVEN (caught real read-loop `8bd8c736`, repeat_run 22) | `benchmark/toolathlon/dos_solves_read_loop.py` |
| The in-flight PostToolUse seam | UNBUILT (the keystone gap) | **BUILT** (untracked) — `src/dos/posttool_sensor.py` + `dos hook posttool` | `src/dos/posttool_sensor.py`, `cli.py:2346` |
| The rewind/prune conversion thesis | DESIGNED, pre-registered, unrun | **SETTLED — REFUTED on the live EnterpriseOps regime** | docs/172 §8, docs/175 §8 (`3225fc8`) |
| A restart (re-orchestrate-fresh) arm | the missing comparand | still UNBUILT — added by this work as a standalone arm | `benchmark/enterpriseops/restart_arm.py` |

The single biggest correction: **the obvious "prune beats re-orchestrate" win is
not what the data shows.** The powered live A/B (n=48, docs/172 §8 / docs/175 §8)
**refutes** the conversion thesis on the weak-model + injected-mint regime —
rewind landed −3.4pp *below* block, with a *negative* fired-run flip net. The
mechanism of the refutation is the very boundary this framing must respect, so it
is §4's spine, not a footnote.

## 1. The one-paragraph thesis

In DOS terms this concept is **the distrust kernel re-aimed from the durable
git/journal axis onto the in-process tool-result stream, with a SUBTRACT
actuation instead of an APPEND one.** "Tool verification" is not "is the result
correct" (the mirror-verifier trap the kernel structurally refuses) — it is a
*family of byte-author distrust questions* about a tool call and its result, each
decided from bytes the judged agent did not author. "Walking a trajectory live"
is consulting one pure verdict — `tool_stream.classify_stream` — over the
*trailing window* of those env-authored result digests as they arrive;
"re-walking" is the byte-identical computation run later over a recorded `.jsonl`.
The two are the same function on two clocks (purity + I/O-at-the-boundary is the
keystone), differing only in *when the digests arrive* and *who consumes the
verdict*. "Pruning" is the doctrinally-clean SUBTRACT sibling of the
measured-losing APPEND move: once the trailing window says the path's answer is
known, the kernel can propose `rewind.rewind_plan` (truncate the dead tail to the
last kernel-verified anchor, re-enter with an un-forgeable no-good note) rather
than author-and-believe a correction. **Detect, prune, and re-enter are each
shipped, pure, and tested; the frontier is the live edges between them — and
whether subtraction actually converts, which the data says depends on whether the
dead path's *cause* lives after the anchor.**

## 2. Tool verification = a family of byte-clean distrust questions

The sharpest definition: **the family of advisory verdicts that distrust a tool
CALL or its RESULT by asking *who authored the deciding bytes* — never *is the
result correct* — admissible only when the deciding field is authored by the env,
the OS, or a third party, not the judged agent.** The axis that matters is *does
it survive a strong model?* — a check that vanishes when the model
reads-before-it-writes is a weak-model crutch, not a kernel primitive.

| Member | Deciding field (env-authored) | Verdict | Status | Survives strong model? |
|---|---|---|---|---|
| (a) **Result-identity** — did `(tool, args, result_digest)` recur N× consec? | `result_digest` (the env hashed its own reply) | ADVANCING/REPEATING/STALLED | **PROVEN** (`tool_stream`, real read-loop) | **YES (partial)** — loop-economics, FP surface = legit polling → WARN-not-cut |
| (b) **Arg-provenance** — id minted, never read? | arg vs `{TOOL_RESULT, TASK_TEXT}` corpus | SUPPORTED/UNSUPPORTED/ABSTAIN | **PROVEN** (`arg_provenance`) | **NO** — vanishes on a careful model; weak-model lift |
| (c) **Result-content** — error wrapped as success? | terminal error envelope | nudge → WARN | **BUILT** (`terminal_error_gate`, benchmark-side, un-lifted) | **PARTIAL** — HTTP-200-with-error-body defeats a careful reader |
| (d) **Precursor-presence** — mandated precursor fired? | tool_name membership scan | ATTESTED/REFUTED/NO_SIGNAL → WARN | **SHIPPED** (`precursor_gate`) | **PARTIAL** — catches a real skip; cannot bind precursor→action (forgeable) |
| (e) **Effect-vs-claim** — agent says "row X written"; did a witness see it? | `evidence.believe_under_floor` | belief only on `OS_RECORDED`/`THIRD_PARTY` | primitive **SHIPPED**; live-stream binding **UNBUILT** | **YES — keystone**; distrusts the *world*, not the prose |

**The correction the adversarial pass surfaced:** `completion`/`resume` key off
the **plan-step intent ledger + git ancestry**, *not* "tool call N claimed effect
E." So on a *live tool stream*, member (e) is **forgeable today**, because the
only witness wired in is the env's reply to the *same* write call (the
`log_source` actor-witness collapse: the agent is simultaneously actor and
witness). Byte-cleanness requires a **read-back from a different surface**
(`evidence.derived_witness`).

**Most valuable unbuilt member: (e) effect-witness on the live tool stream** —
read-back-after-write adjudicated by `believe_under_floor`. It is the *only*
member whose value **grows** with model strength (it catches the
confident-but-wrong strong model that (b) and (d) cannot), it is genuinely
byte-clean (the read-back is issued to a *different* tool than the write), and its
kernel primitive already ships. The missing piece is a consumer loop step that
issues the independent read-back plus a thin new `effect_witness.py` leaf (a
per-tool-call verdict, distinct from `completion`'s per-declared-plan-step).

## 3. Live-walk vs re-walk: one pure verdict, two clocks

`classify_stream(ToolStream, StreamPolicy) -> StreamVerdict` is "a frozen tuple of
digests in, a frozen verdict out" — the caller computes the digests at the
boundary; the kernel hashes nothing live, reads no clock, no disk (the
`liveness.classify` / `git_delta` shape). Three consequences make this the
keystone:

- **Source-indifference** — the verdict cannot tell a live digest from one
  recorded a week ago, so **re-walk *is* live-walk run later**, not an
  approximation of it.
- **Zero-access testability** — the whole detector runs on frozen fixtures, no
  model / MCP / DB.
- **Doctrinal cleanliness for free** — the digests are env-authored, so REPEATING
  is provenance-of-repeated-output, never a forgeable satisfaction predicate.

**The unifying abstraction: `live-walk = re-walk(trailing window) consulted
in-flight`.** `classify_stream` judges only the *tail* run-length, not the whole
history; the replay harness makes this literal (it folds prefixes `steps[:i]` to
find the first index where the trailing run crosses threshold). The only
differences between modes are *when the digests arrive* and *who consumes the
verdict*. This reframes the pruning intuition precisely: **once the trailing-window
verdict is STALLED, the path's answer is known** — the env is returning identical
bytes, no new information is entering — which is the moment SUBTRACT is *cheapest*
relative to re-orchestration (it is a separate question, §4, whether it
*converts*).

| Mode | Whose trajectory | When | Built? |
|---|---|---|---|
| **Walk** (live, self) | mine, mid-run | before next tool call | per-iteration consult BUILT in the harness; the **PostToolUse hook now BUILT** (`posttool_sensor`) |
| **Re-walk** (replay) | recorded `.jsonl` | offline, $0 | **PROVEN** |
| **Re-walk-other** (supervisor) | a peer's / fleet's | on a timer, out-of-process | BUILT — **git/journal axis only** (`drivers/watchdog`, `dispatch_top`) |

The **third mode is real and distinct**: `drivers/watchdog` polls
`liveness.classify` from *outside* a watched run's process on an independent clock.
But it re-walks peers on the **git/journal** axis ("did GIT advance?"), never the
tool-stream axis, because a peer's live tool stream is in *its* process memory,
not on disk. To re-walk a peer's tool stream, the peer must emit its triples to a
durable surface — which is exactly what `posttool_sensor`'s session-scoped
`.dos/streams/<sid>.jsonl` accumulator now does (same emitter, the sink is just
durable rather than in-process).

**The in-flight hook — now BUILT, with the one load-bearing correctness fact
honored.** `src/dos/posttool_sensor.py` + `dos hook posttool` turn a live
PostToolUse event into a `StreamStep`, persist the accumulating stream across the
many short-lived hook processes of one session, classify the trailing run, and on
REPEATING/STALLED emit the **exact Claude-Code dialect** CC honors
(`{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
…}}`). This is the fix for the sibling `dos hook stop`'s known no-op: that hook
emits `{"ok": false}`, a dialect real CC *ignores*; the posttool sensor emits the
honored shape and only that. Two structural facts make it correct by
construction: PostToolUse fires *after* the tool ran, so it **cannot block** — it
can only ADD context — which makes the docs/99 advisory-only doctrine unavoidable;
and it re-surfaces the env-authored value even on STALLED, never a cut, because a
poll of a not-yet-complete background task is a legitimate repeat.

## 4. The prune-vs-reorchestrate law — and where the data says it flips

When a path P is known-dead, recovery cost decomposes into two terms: *tokens /
latency to return to a good state* and *retained knowledge that P is dead*. Three
moves:

| Move | Corruption | Lesson "P is dead" | Status |
|---|---|---|---|
| **Restart** (fresh window) | subtracted (gone) | **LOST** (naive) — fresh window can re-walk P; **KEPT** if seeded with the no-good note | naive default; **arm added by this work** |
| **Append** (BLOCK) | **KEPT** — forged synthetic result poisons next steps | kept but smothered | **MEASURED net-harmful** (−6 flips, +0.0pp vs none, n=78) |
| **Subtract + no-good** (rewind) | dead tail excised | **KEPT** — note re-enters carrying "this id never appeared" | placement PROVEN; **conversion REFUTED on this regime** |

This is **backjumping with no-good learning** (docs/164 F1.5) — CSP/SAT no-good
learning applied to a conversation. The note is doctrinally clean for the same
reason BLOCK's append is *not*: `rewind.build_no_good_note` has **no
`critique`/`advice`/`message` parameter** (the absence is the lock); every token
is a registry-known `VerdictToken`; the env excerpt attaches only if
`accountability != AGENT_AUTHORED`. It tells the agent *the env said this id never
appeared* (third-party fact), never *here is the right answer* (forged belief).
That satisfies the ONE FIX rule (docs/164) by construction, and it **held live**:
18/18 live rewinds emitted only kernel tokens + env bytes, zero generated prose.

**The arithmetic (measured placement, derived cost).** The $0 replay measured
exactly: 6/78 block runs thrashed, 6/6 fired REWIND with a found anchor, **46
turns subtracted, 18 appends eliminated** (`rewind.py`'s subtraction is pure —
`t.index > checkpoint.turn_index`). That is the *magnitude* of forged context a
subtract removes. The *cost saving* (tokens / cache / latency) is a separate
pricing model multiplied onto that magnitude — and it is **not instrumented**: the
replay records turns, never tokens or cache state. At horizon × fanout (docs/170),
the delta grows with fanout and prefix length, but the ~8% fire rate is a
weak-agent number (on a strong model the natural mint rate is ~0/406, so the
saving lives in the weak-execution slice).

**Now the refutations, folded in — this is where the headline frays:**

1. **The conversion is not just unmeasured — the powered run REFUTES it.** Live
   A/B run A (n=48, 4 domains, mint 0.40): rewind 44.9% verifier vs block 48.3%
   (**−3.4pp**), fired-run flip net **−3** (4 help / 7 hurt), tripping two
   pre-registered kill conditions (docs/172 §8). A small ITSM-only n=20 landed
   favorably (+6.2pp) but two opposite-sign results on a sub-5pp effect is the
   textbook signature of a noise-dominated measurement; the larger sample governs.

2. **The mechanism of the refutation IS the boundary this framing flagged.** The
   failure is a **rewind livelock**: when the dead end's cause is an *upstream
   omission* (the agent never looked up the id, and that missing read lives
   *before* the rewind anchor), backjumping to a clean prefix hands back the same
   prefix that caused the invention, so the agent **re-emits the same invented id
   and re-thrashes**. Subtraction removed a *symptom*, not the *cause*. This is
   exactly the synthesis's predicted flip-point: *prune flips to worse-than-restart
   when the root cause sits upstream of the anchor.*

3. **The named rival was never built — until now.** The whole experiment compared
   rewind / none / block; **restart (kill + fresh window) was not an arm.** So
   "pruning ≻ orchestrating fresh context windows" had **zero measured comparand
   on the restart side.** This work adds it (§6), precisely because the refutation
   motivates it: if rewind livelocks on an *upstream* cause by handing back the
   poisoned prefix, a restart that *re-reasons the prefix from scratch* may escape
   where rewind cannot — and a restart *seeded* with the byte-clean no-good note
   keeps the lesson too, collapsing prune's "keeps the lesson" advantage to just
   "keeps the warm prefix (when warm)."

4. **An unguarded transcript-corruption path can make prune worse than both.**
   The live truncation keeps ToolMessages `[0..anchor]` and drops the rest; if the
   anchor was the first of a *multi-tool-call* turn, the kept tail can end with
   sibling `tool_calls` unanswered — a hard API 400 on the next invoke. The
   current consumer guards the inverse hazard (a ToolMessage with no preceding
   AIMessage) but not this one; whether it bites depends on whether the agent
   emits parallel tool_calls — unmeasured.

**Where prune flips to worse-than-restart, stated plainly:** (a) the root cause
sits *upstream* of the anchor (the measured livelock); (b) a multi-tool-call cut
strands sibling tool_calls → API 400; (c) the agent re-derives the dead id from
the surviving prefix and re-thrashes (the note is advisory — PDP not PEP — so it
informs, never binds). **The law holds only while the corruption lives strictly
after the last kernel-verified turn and the prefix doesn't re-spawn it.**

**EVIDENCED vs PLAUSIBLE.** *Evidenced:* the subtraction is pure (code); the
no-good note is byte-clean (code + 18/18 live); the replay placement counts
(46/18/6-of-6) are real and dated; **APPEND is measured net-harmful**; and
**SUBTRACT does not convert when the cause is upstream** (the powered live
refutation). *Plausible-only / unmeasured:* the token/cache/latency cost (a
TTL-conditional pricing model, never instrumented); **prune ≻ RESTART** (the rival
the §6 arm exists to finally measure); whether a *restart* escapes the upstream
livelock rewind fell into. Do not paper over this: the placement-and-cleanliness
half is proven, the conversion half is refuted on this regime, and the vs-restart
half is the open question this work sets up to answer.

## 5. The closed FIX loop without generating a correction

The pieces are real and compose, on paper, into the full FIX loop the kernel can
offer *without authoring a correction*:

- **detect** — `tool_stream.classify_stream` → STALLED (env-authored, §3), now
  consultable live via `posttool_sensor`.
- **prune** — `rewind.rewind_plan` → REWIND to a `SuspendCheckpoint`, dropping
  dead-end turns, re-entering with a `NoGoodNote` structurally incapable of
  carrying generated prose. ONE-FIX rule satisfied by construction.
- **re-enter** — `resume.resume_plan` over the `run_id`-keyed intent ledger gives
  the residual to re-dispatch.
- **cap** — `completion.convergence` → THRASHING/STARVED so the rewind loop can't
  itself spin forever.

**It is BUILT-as-verdicts / PARTIALLY-WIRED-as-a-loop.** The concrete gaps the
data exposes:

1. **The live rewind trigger was hardcoded to the mint regime** (`block_counts >=
   2`) / the gym error grammar (`natural_thrash_gate`'s `_is_struct_error`), with
   the `Convergence.THRASHING` handed to `rewind_plan` a literal constant. **NOW
   BUILT (§6.1): the domain-free `classify_stream → STALLED` trigger**
   (`stall_trigger.py`) — env-authored byte-identity, no failure taxonomy, proven
   cross-domain. It maps STALLED→THRASHING at the boundary (kernel untouched).
   **Turn-preserving guard honored:** STALLED is the safe prune signal; bare
   REPEATING stays WARN (a legitimate eventual-consistency poll must not be pruned).
2. **The anchor is ad-hoc, not a shared fossil.** The consumer mints a
   `SuspendCheckpoint` on the fly; it never writes an `OP_SUSPEND`. So the "two
   rewind axes, one anchor" design (git-`resume` + transcript-`rewind`) is *not
   realized in-flight*. Wiring, not a new module: call `intent_ledger.suspend_entry`
   at the rewind point.
3. **The cause-vs-symptom gap is the real one.** The refutation says the
   content-free subtract cannot supply a missing *cause*. The only rung that
   addresses an *omission* cause is F3 — supply the verified missing fact at the
   write, **gated** (docs/126 PEP). The closed loop above recovers from a *symptom*
   dead end; an *upstream-cause* dead end needs either a restart that re-reasons
   the prefix (§6) or F3.

## 6. The restart arm — the missing comparand (built by this work)

`benchmark/enterpriseops/restart_arm.py` adds the rival the experiment never had,
as a **standalone module** (zero edits to the concurrently-held `dos_react.py` /
`live_ab.py` — the disjoint-lane discipline). It is a thin subclass of the
dos_react orchestrator that, on the same THRASH trigger the rewind arm uses,
**discards the in-flight window and re-orchestrates from a fresh context** — the
naive "kill it and start over" recovery — with one knob: `--seed-no-good`, which
prepends the *same byte-clean no-good note* the rewind arm re-enters with, so the
experiment can separate prune's two claimed advantages:

- **restart (unseeded)** — keeps the warm prefix? NO. Keeps the lesson? NO. The
  pure "re-orchestrate a fresh context window" baseline the user's framing names.
- **restart (seeded with the no-good note)** — keeps the warm prefix? NO. Keeps
  the lesson? YES. Isolates "the lesson is what mattered, not the warm prefix."
- **rewind** — keeps the warm prefix? YES (when cache-warm). Keeps the lesson? YES.

Holding the detector identical across {none, block, rewind, restart,
restart_seeded}, the four-way isolates exactly: append-vs-subtract-vs-restart, and
warm-prefix-vs-lesson. **The token ledger** (a per-arm count of prefix tokens
re-paid, turns carried, and re-orchestration events) is recorded alongside, so the
cost half of §4 — asserted there, never instrumented — finally has numbers. The
arm ships with a no-gym AST-extraction unit test (the `test_rewind_arm.py`
pattern) proving the restart mechanism (window discard + optional seed) before any
Gemini spend; the live conversion run is future work, gated on the concurrent
benchmark edits committing.

**The pre-registered prediction (stated before any scored restart run):** if the
refutation's mechanism is right (rewind livelocks because the cause is *upstream*
of the anchor), then **restart should beat rewind on the upstream-cause slice** —
re-reasoning the whole prefix is the only move in this set that can escape an
upstream omission — while **rewind should beat restart on token cost** (it keeps
the warm prefix). And **restart_seeded ≈ restart_unseeded** would mean the lesson
re-entry buys little once the prefix is re-reasoned, whereas **restart_seeded >
restart_unseeded** would mean the no-good note is load-bearing independent of the
prefix. The kill condition for "restart is the answer": restart ≤ none on verifier
pass (re-orchestration is net-harmful — cold-start + lost good work outweighs
escaping the dead path).

## 6.1 The domain-free STALLED prune trigger (built by this work)

`benchmark/enterpriseops/stall_trigger.py` closes frontier item #1: it wires the
kernel's `tool_stream.classify_stream → STALLED` as the prune trigger, replacing
the domain-coupled `block_counts >= 2` (mint-specific) and `natural_thrash_gate`
(gym-error-grammar-specific) with the env-authored, model-durable signal. A
**standalone module** (zero edits to the concurrently-held `dos_react.py`), it is
the one-line wiring swap at the natural-thrash call site:

```python
gate = stall_thrash_gate(tool_results, tool_name, self._stream_policy)
# (tool_results → ToolStream via the SAME posttool_sensor.step_from_event the live
#  hook uses, so the in-flight loop signal is BYTE-IDENTICAL to the PostToolUse hook)
```

**The safe-signal discipline, enforced:** the gate fires ONLY on `StreamState.STALLED`
(the trailing run of byte-identical `(tool, args, result)` triples reached
`stall_n`, default 5), never on REPEATING (3–4 identical = WARN-only: a legitimate
eventual-consistency poll must not be pruned). Proven by `test_stall_trigger.py`
(12 tests: STALLED fires, REPEATING/ADVANCING/too-short do not, the in-the-hole-now
tool guard, a custom `stall_n`, and the same-signal-as-the-hook equivalence).

**THE INTEGRATION FINDING (surfaced by `test_stall_to_rewind_integration.py`, 8
tests).** Wiring STALLED to the *existing* `_maybe_rewind_natural` exposed a real
gap: that method's anchor-finder (`_is_verified`) rejects a turn only if it is a
**structured error** — correct for the error-dominated stall (the stalled turns ARE
errors), but **wrong for a byte-identical *success-looking* stall** (re-reading a
row that returns `{"rows": []}` with outer `success: True` N times). Those stalled
turns pass `_is_verified`, so the error-path anchor walks *backward into the stall*
and anchors inside it → subtracts nothing. So the STALLED path computes its OWN
pre-stall anchor (`stall_anchor_index = len − repeat_run − 1`, the turn before the
consecutive stall) and enacts via a self-contained `enact_stall_rewind` that drives
the REAL kernel `rewind_plan` with the correct anchor + a byte-clean no-good note
(a `VERIFY_NOT_SHIPPED` token over the stalled tool + the env's own repeated bytes,
THIRD_PARTY). The fail-safe holds: a stall from turn 0 (no verified prefix) yields
an absent checkpoint → kernel UNANCHORED → the enactment refuses to truncate
(never rewind to a turn the kernel did not stamp). **The byte-identical-loop class
(STALLED) and the error-dominated-branch class (natural_thrash) are different
failure shapes with different correct anchors** — docs/175 §4's loop-vs-branch
distinction, now reproduced at the anchor level. The STALLED trigger ADDS the
domain-free loop class; it does not supersede the branch gate.

**LIVE WIRING — now BUILT (not just designed).** The trigger is wired into the real
`dos_react.py` `execute()` loop behind a `DOS_STALL` env knob (additive — it runs
*alongside* `natural_thrash_gate`, not replacing it, so the loop class and the
branch class are both caught), plus a `stall` arm in `live_ab.py`. Proven by
`test_stall_live_wiring.py`: it drives the **real** `DosReactOrchestrator.execute()`
loop (the gym base class) with a mock LLM that re-issues one stalling call after a
verified prefix, and asserts the loop SUBTRACTS to the pre-stall anchor mid-run —
`rewind_to_turn=0`, `dropped=[1..5]`, `repeat_run=5`, the no-good note carrying only
the `NOT_SHIPPED` kernel token + the env's `THIRD_PARTY` bytes. (It runs the drive
in a clean subprocess because the gym ships a top-level `benchmark` package that
collides with this repo's under pytest's rootdir — the honest way to exercise the
real loop without corrupting sibling-test imports.) So detect→prune now fires
inside a real agent loop on the domain-free env-authored signal; the only thing
still pending is a **paid live A/B run** (`live_ab.py --arms none stall
--mint-rate 0`), and its expected result is honest: on a strong model that rarely
byte-loops the fire rate is ~0 (docs/145's measured `p_stuck≈0`), so this earns its
keep as the durable loop-hygiene primitive on a cheap/looping agent (docs/170),
not as a strong-model lift.

## 6.2 The STALLED slice exists but does NOT clear the actuation bar ($0, measured)

docs/191 measured the WHOLE natural-thrash population (gemini-2.5-flash,
`live_results_natural_ab/none`) and found it **uncurable in-loop** — the dominant
class is varying-arg *schema-blindness* (`create_filter` sending `from1`/`from1_`,
`update_vacation_settings` wrong-value-encoding), and even cost-aversion abandon
fails its kill at false-abandon ≈ 0.33. But docs/191's gate keyed on "K consecutive
same-tool **errors**" — the error-shaped trigger — which conflates the
varying-branch majority with the byte-identical-**loop** minority the STALLED
trigger actually targets. So the decision-relevant question for §6.1 is narrower:
*on this corpus, does the byte-identical STALLED slice exist, and does pruning it
convert?* Two $0 replays answer it (`replay_stall.py` + the new
`stall_recovery_probe.py`, pinned by `test_stall_recovery_probe.py`):

| measurement | value |
|---|---|
| runs scanned / with tool calls | 130 / 118 |
| STALLED fires (byte-identical loop) | **3 (2.5%)** — small but NON-zero, a *distinct* slice |
| of those, true dead-ends | **2** (`create_filter`, never recovers, fail) — correct prune targets |
| of those, **self-recovered (false prune)** | **1** (`update_vacation_settings` succeeds later) |
| **false-prune rate** | **0.33** — the SAME floor docs/191 found for the broader abandon gate |

**The honest verdict (the conversion side of §6.1):** the STALLED slice is real and
*not* the uncurable schema-blindness branch (validating the trigger is not vacuous),
but its false-prune rate (1/3) **does not clear a <10% bar** — a third of fired runs
escape the byte-loop on their own. So an in-loop STALLED→prune is **not** a safe
*default*; it must stay **WARN-first / opt-in**, exactly the posture §6.1 already
ships (the `DOS_STALL` opt-in flag + the safe-signal rule REPEATING→WARN). The probe
*confirms* that conservative default was right rather than over-claiming a
conversion win. One nuance keeps the prune defensible where abandon was not: a prune
**truncates+retries** (turn-preserving), it does not **kill** the run — so a wrong
prune costs a re-tried prefix, not destroyed work, a strictly lower false-fire cost
than docs/191's abandon. But 1/3 is still too high to default-cut. **Detection of
the slice: sound and measured. Default actuation: refused; opt-in only.** This is
the docs/191 discipline (detection-soundness ≠ conversion) applied to the exact
byte-identical slice §6.1 serves.

## 6.3 The paid live A/B was NOT spent — it is gated-null by Tier-1 ($0, 2026-06-06)

§6.1/§6.2 left exactly one item open: the *paid* `live_ab.py --arms none stall
--mint-rate 0` run. **It was deliberately not run, and that is the doctrine-correct
call.** The `THEORY_LADDER.md` rule is explicit — *read Tier 0/1 before spending on
Tier 2+, so a live run confirms a prediction instead of being a blind first data
point.* Tier 1 here is `replay_stall.py` (the variance-free `classify_stream` fold
over recorded trajectories) + `stall_recovery_probe.py` + `trigger_population_xtab.py`,
all $0. Re-run on the **full available corpus** (4 recorded dirs, far larger than
§6.2's single 130-run slice), they settle the paid run before a cent:

| corpus dir | runs w/ calls | STALLED fires | REPEATING | p_stuck |
|---|---|---|---|---|
| `live_results` (4-arm mint A/B) | 325 | 1 | 6 | 2.2% |
| `live_results_natural` | 116 | 0 | 1 | 0.9% |
| `live_results_natural_ab` | 443 | 3 | 7 | 2.3% |
| `live_results_natural_run` | 191 | 1 | 5 | 3.1% |
| **pooled** | **1,075** | **5** | **19** | **~2.2%** |

Three facts converge, and every one points the same way:

1. **The STALLED prune fires on ~0.5% of runs** (5 STALLED / 1,075 with-calls). The
   *longest byte-identical run seen anywhere is 5* — the exact `stall_n` threshold —
   so the population sits right at the floor; almost every fire is REPEATING (the
   WARN class), not STALLED (the prune class). This is the real base rate, not the
   guessed `p_stuck≈0` of the §6.1 prediction — and it confirms it.
2. **The rewind-addressable population among the fires is 0** (`trigger_population_xtab.py`,
   160 natural runs: LOOP/STALLED fires 2×, both non-addressable — 1 success-spin →
   WARN, 1 error-loop → class-C schema injection). This is the docs/172 §9.3 result
   (0 conversions / 0 flips on the SUBTRACT) reproduced on the *loop* trigger
   specifically: the SUBTRACT is the wrong verb for what STALLED detects.
3. **The prune actuation fails its own safety bar** (`stall_recovery_probe.py`:
   false-prune rate 0.33, kill-bar 0.10) — so even where it fires, pruning is
   WARN-first/opt-in, never a default cut, exactly as §6.1 ships it.

So a paid `none`-vs-`stall` A/B over ~100+ tasks would, by the measured base rate,
observe ~0–1 STALLED fire that the cause-ablation already shows converts nothing,
while the actuation already fails the safety bar to be a default. **It is a run
pre-registered null by the very evidence that is supposed to gate it.** The honest
landing is identical to the rewind arm's (docs/172 §9.3): the **DETECT is complete,
sound, byte-clean, model-durable, and proven firing mid-loop** (`test_stall_live_wiring.py`,
19 stall tests green); the **conversion is null on this regime** because the
addressable population is empty. We do not spend to re-confirm a null the gating
tier already measured. The live wiring (`test_stall_live_wiring.py`) proves the arm
fires correctly — so the null is *empty-population*, not *broken-pipeline*. **DETECT
complete; conversion gated-null; paid A/B closed unspent.**

## 7. Ranked unbuilt frontier

Governed by docs/170: **defensive lift decays to ~0 on a strong model; what
survives a model upgrade is loop-hygiene under fanout.** A smarter model still
polls eventual-consistency, still re-reads the same file on a long horizon, still
burns a window on a dead path — and does it N× in parallel. The prize is the
token/latency-hygiene framing.

1. **~~Generalize the live prune trigger to `classify_stream → STALLED` + wire it
   into the loop + run the paid A/B~~ — BUILT (§6.1) + CLOSED (§6.3).**
   `stall_trigger.py` (the gate + correct-anchor `enact_stall_rewind`), wired into
   `dos_react.py`'s real `execute()` behind `DOS_STALL` + a `live_ab.py` `stall`
   arm, proven firing mid-loop by `test_stall_live_wiring.py` (the real
   orchestrator, no spend). **The paid live A/B is now resolved: closed UNSPENT,
   gated-null by Tier-1 (§6.3).** The $0 replay over the full 1,075-run corpus
   measured the real STALLED base rate at ~0.5% (confirming the docs/145 `p_stuck≈0`
   prediction), the rewind-addressable population among fires at 0 (the docs/172
   §9.3 null on the loop trigger), and the prune false-prune rate at 0.33 (below its
   own safety bar) — so a paid run is pre-registered null and the ladder rule says
   not to spend. **DETECT complete + proven; conversion gated-null; no remaining
   cost. Durability: HIGH** — env-authored, model-orthogonal.
2. **The live SUSPEND-anchor write** — one `intent_ledger.suspend_entry` at the
   rewind point so git-`resume` and transcript-`rewind` re-enter from the same
   fossil. **Cost: LOW**, **durability: HIGH**.
3. **The restart arm's live conversion run + token ledger** (§6) — settle
   prune-vs-restart with real numbers, on the upstream-cause slice the refutation
   identified. **Cost: MEDIUM** (a paid run, gated on prereqs). **Durability:
   MEDIUM** — answers a question; the answer may be regime-specific.
4. **`effect_witness.py` + read-back loop step** (§2 member (e)) — the only
   tool-verification check whose value *grows* with model strength. **Cost:
   MEDIUM** (primitive shipped; needs the consumer read-back + thin leaf).
   **Durability: HIGHEST on the correctness axis** — but a correctness play, so it
   ranks below #1 for *frontier* leverage while being the most durable check.
5. **The F3 gated-supply rung** (docs/126 PEP) — the only rung that addresses an
   *upstream-cause* dead end, which the refutation says subtraction cannot. **Cost:
   HIGH** (a write-time PEP). **Durability: HIGH** — it is the 10× move.

**#1 is now built AND closed (§6.3); #2 (the SUSPEND-anchor write) is the next
concrete step.** Item #1 is docs/170-durable (loop-hygiene under fanout, not
defensive lift), its verdict is proven against a real cross-domain loop, and it is
the one edge that turns "re-walk live → prune" from a benchmark demo into a
domain-free production loop. The detect (posttool), the prune (rewind), the
domain-free trigger (`stall_trigger`), AND the live wiring into the real `execute()`
loop (`DOS_STALL` + the `stall` arm, proven firing mid-loop) all exist — and the
paid A/B that would have scored it is now resolved as gated-null (§6.3): the $0
Tier-1 corpus settles the conversion at 0 on the empty addressable population, so no
spend is warranted. With #1 closed, **#2 (the SUSPEND-anchor write) makes the anchor
a shared fossil** and is the next move; #4 (`effect_witness`) is the durable
correctness play.

## 8. The honest scoreboard

- **PROVEN** (real data, real verdict, dated): `tool_stream.classify_stream`
  catches the actual audited read-loop (`8bd8c736`, STALLED repeat_run 22),
  cross-domain, offline, $0. The rewind subtraction is pure and the no-good note
  is byte-clean (code-verified + 18/18 live). Replay placement: 6/78 thrashed, 6/6
  fired with an anchor, 46 turns / 18 appends subtracted. **APPEND (BLOCK) is
  measured net-harmful** (−6, +0.0pp, n=78). **SUBTRACT (rewind) does not convert**
  on the powered live regime (−3.4pp vs block, flip net −3, n=48) — the
  upstream-cause livelock.
- **BUILT-NOT-RUN-LIVE**: the in-flight PostToolUse seam (`posttool_sensor` +
  `dos hook posttool` — emits the real CC dialect, unlike the `dos hook stop`
  no-op); the per-iteration distrust consult (harness); `terminal_error_gate`
  (benchmark-side, un-lifted); the third-mode watchdog re-walk (git/journal axis
  only); the restart arm + token ledger (§6, this work — unit-tested, live run
  pending); **the domain-free STALLED prune trigger (§6.1, `stall_trigger.py` —
  21 tests incl. the STALLED→SUBTRACT integration, the success-looking-stall anchor
  finding, AND `test_stall_live_wiring.py` driving the REAL execute() loop;
  WIRED into `dos_react.py` behind `DOS_STALL` + a `live_ab.py` `stall` arm; only
  the paid A/B run is left)**.
- **DESIGNED**: the live SUSPEND-anchor write (two-axes-one-anchor); the
  conversation token/cache-cost model.
- **UNBUILT (named)**: `effect_witness.py` + read-back loop step (the most durable
  distrust check); the F3 gated-supply rung (the only cause-fix, docs/126); the
  `convergence` live loop-cap consumer.

**The frontier in one line:** the *detect* half is shipped and proven, the *prune*
half is shipped and proven, the *live in-flight detect hook* is built, AND
detect→prune is now WIRED on the domain-free STALLED signal and proven firing
inside the real loop — so the open frontier narrows to (a) the paid live A/B runs
(the `stall` arm and the `restart` arm), and (b) the conversion question, where the
data already says subtraction alone does not convert an *upstream-cause* dead end,
which is exactly why the restart arm (§6) was built: to measure whether
re-orchestration escapes where subtraction livelocked.

## 9. Provenance

- Concept map + taxonomy + the live-walk/re-walk abstraction + the
  prune-vs-reorchestrate economics: a grounded 10-agent exploration workflow
  (`wf_551c8b36`), each lens cross-checked against the live modules, hardened by
  two adversarial skeptics whose findings are §4.
- `tool_stream` PROVEN catch: `benchmark/toolathlon/dos_solves_read_loop.py`
  (`8bd8c736`, STALLED repeat_run 22), docs/171.
- The PostToolUse seam: `src/dos/posttool_sensor.py` + `cli.py:cmd_hook_posttool`
  (concurrent work, untracked on 2026-06-06), docs/173 §4–§5.
- The rewind kernel surface + byte-clean note: `src/dos/rewind.py`,
  `src/dos/rewind_tokens.py`, `src/dos/rewind_evidence.py`, `tests/test_rewind.py`
  (31 tests).
- The live rewind refutation: docs/172 §8 + docs/175 §8 (`3225fc8`), powered A/B
  n=48 (−3.4pp vs block, flip net −3); the placement replay
  `benchmark/enterpriseops/rewind_counterfactual.py` (6/6 fired, 46/18).
- The restart arm + token ledger: `benchmark/enterpriseops/restart_arm.py` +
  `benchmark/enterpriseops/test_restart_arm.py` (this work).
- The docs/170 scissors (defensive lift decays, loop-hygiene survives) and the
  0.00pp strong-model conversion ceiling: docs/170, the weak-plus-substrate
  significance ruling.
