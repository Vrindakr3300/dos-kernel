# docs/285 — Operator help observability: the last rung, from the WAL out to the human

> **Status:** SHIPPED. `dos helped` + the in-flow hook nudge + the session-stop
> digest land together; pinned by `tests/test_help_summary.py` (47 tests). Built on
> the OP_ENFORCE stream the lane WAL already carries (docs/189 §C4) — no new store.
> **Phase 2 (2026-06-10):** clarity — recover the typed reason class so the phantom
> `admission`/`SELF_MODIFY` split collapses, gloss every class in plain English, and
> add `dos helped --explain` for concrete examples (which file, why).
> **Phase 3 (2026-06-13):** honesty — the headline now leads with what DOS *did*
> (the calls it actually REFUSED), not a total inflated by advisory warns; the rate
> denominator splits the same way; `dos helped --advisory` keeps the cautions one
> keystroke away. See "Phase 3" below.
> **Phase 4 (2026-06-13):** grounding + value — `dos helped --explain` now shows
> the adjudicated denominator (the number that grounds the count), a `value:` line
> per reason class (*why* the block mattered, not just what it means), and an honest
> footer tiering load-bearing refusals from low-signal advisory warns. See "Phase 4".

## The gap

DOS was already working. The installed Claude Code plugin fires on every
`PreToolUse` and, on a SELF_MODIFY edit or a lane collision, **refuses the call** —
and durably banks the refusal as an `OP_ENFORCE` record on the lane WAL
(`lane_journal`, docs/189 §C4). On this very repo the journal carried **604
behavior-changing blocks** before this doc — 604 times the substrate stopped a live
loop from rewriting the kernel adjudicating it, or from colliding on a held lane.

But **nobody ever told the operator.** The hook emitted a `deny` /
`additionalContext` to the *agent*; the record went to a JSONL file no human reads.
So the person running the fleet could be saved from a dozen self-overwrites a day
and never know. The observability "ran out" one rung short of the human — the
docs/204 §4 wall (the witness exists, but it never reaches the person who should
see it), applied to DOS's own value.

`dos observe` (docs/262) was the nearest existing surface, but it reads the
**verdict** journal, which is empty on this workspace (no syscall wires
`verdict_journal.record` here yet). The real, populated record of "DOS helped" is
the **enforcement** stream on the *lane* WAL. This doc reads *that*.

## The design — one pure fold, three surfaces

All three surfaces share a single pure fold (`src/dos/help_summary.py`); none mints
a new store or a new verdict. It is the `observe`/`decisions`/`trace`
read-only-projection posture: read the WAL, fold, render.

* **`summarize(records, *, holder, since) -> HelpSummary`** — folds OP_ENFORCE
  records into a "DOS caught N things" rollup, by intervention rung (BLOCK / WARN /
  DEFER), by typed reason class, by tool. Entries in, value out, no disk — the
  unit-test surface.
* **`should_nudge(help_index) -> bool`** — the cadence: fire on the **1st** help of
  a session (so the operator learns the substrate is alive) and **every 5th** after
  (1, 5, 10, 15…). The user's "maybe every 5th time it fires" made exact.

The three operator-facing surfaces:

1. **In-flow nudge** (`cmd_hook_pretool` step 5b). After the OP_ENFORCE write, fold
   this session's helps and, on the 1st + every 5th, append a one-line *"DOS has
   caught N things this session (X blocked, Y warned). Run `dos helped` for the
   breakdown."* to the hook's `additionalContext`. **Purely additive** — the
   `permissionDecision` is untouched (`_append_additional_context` returns a new
   dict; the deny still stands), and any fault fails silent (observability is never
   an enforcement input).
2. **`dos helped`** (pull command). The full operator rollup any time: headline
   count, by-reason-class and by-tool breakdowns, and an honest footer noting how
   many firings were observe-only. `--session SID` / `--since TS` / `--json`.
3. **Session-stop digest** (`cmd_hook_stop` → `_emit_help_digest`). When an agent is
   genuinely allowed to stop, print a once-per-session *"DOS has caught N things"*
   bookend — to **stderr** (the Stop stdout is the dialect CC parses; a digest there
   would be a malformed Stop output, the load-bearing no-op-avoidance discipline),
   guarded by a `.dos/help-digest/<sid>` stamp so the several Stop firings of one
   session don't repeat it. Skips entirely when the session caught nothing.

## What counts as a "help" — and why it can't be gamed

A **help** is a BLOCK (a refused/withheld call), a WARN (a surfaced correction), or
a DEFER (escalated to a human) — the three rungs that *changed behavior*. A passive
OBSERVE is recorded (and counted in `enforced`) but is **not** a help: counting it
would inflate the number with silent logging that intervened in nothing.

**Byte-clean by construction (docs/138).** Every field the count reads —
`intervention`, `reason_class`, `tool`, `withheld`, `ts` — is **env-authored**: the
kernel wrote the OP_ENFORCE record downstream of an already-decided verdict. No
agent narration enters the count; a run cannot self-report its way to a bigger
"helped" number. The fold never parses the human-readable `reason` *text* — when a
record predates the `reason_class` lift (the 092ad29 fix, see
`[[project-dos-enforce-reason-class-drop-and-release-version-drift]]`), it falls back
to the env-authored `handler` name (`admission`/`provenance`), never to mining the
prose. On this repo's 604 real blocks that fallback turns 597 bare "UNCLASSIFIED"
into the meaningful "admission".

There is deliberately **no writer** in `help_summary` — it only reads what the
sensors already banked, so it can never journal a help the kernel did not enforce.

## Why the lane WAL and not a new counter

A separate counter file (incremented at each fire) could drift from the journal — a
crashed process, a lost increment, a double-count. Folding the WAL at read time
keeps a **single source of truth**: the same env-authored records `dos helped`, the
nudge, and the digest all read. The cost is a journal re-read per nudge fire (cheap;
torn-tail-tolerant via `lane_journal.read_all`), bought against never having two
numbers that disagree.

## Litmus

`help_summary.py` is a kernel-pure leaf (stdlib only; the boundary read happens in
the CLI verb / the hook handlers, never inside the fold). It names no host — the
session id, the reason classes, and the tools all come from the env-authored journal
records, not a hardcoded taxonomy. It adds no precondition and mints no belief: the
verdicts it counts were minted by the sensors. Delete it and you lose the reader, not
the data.

## Phase 2 — clarity: "what does `admission` mean, and WHICH ones?" (2026-06-10)

The first cut surfaced the number but not the meaning. On this repo it rendered
`admission 597 / SELF_MODIFY 13` — which is **misleading**: all 610 are the *same*
SELF_MODIFY block, but the 597 older records had their top-level `reason_class`
dropped (the 092ad29 gap), so they fell back to the bare handler name `admission`
and split into a phantom second bucket. The operator saw two opaque categories where
there was one, with no idea what either meant or what got blocked.

Three changes close that, all still **byte-clean** (every shown field is
env-authored; the human-readable `reason` prose is read but never trusted as a
*count* input — it is only echoed, the way `commit-audit` echoes a subject it does
not believe):

1. **Recover the typed class** (`_recover_reason_class`). Before falling back to the
   handler name, read the SAME `reason_class` token nested in the env-authored
   `proposal` body — present on the older records whose top-level token was never
   lifted. This collapses the phantom split: `admission 597 / SELF_MODIFY 13` becomes
   the honest `SELF_MODIFY 610`.
2. **Gloss every class** (`REASON_GLOSSARY` / `explain_reason`). A closed
   reference-data map from each reason class to a one-line plain-English meaning,
   rendered inline in the rollup. `SELF_MODIFY` now reads "an agent tried to edit the
   kernel's own running code while a loop was adjudicating it." An unknown class gets
   no gloss — we never invent one.
3. **Drill down to examples** (`dos helped --explain` / `render_explain_text`). Per
   reason class: the meaning, the count, and a few **concrete examples** — the file
   the refusal was about (extracted from the parenthesized path list in the kernel's
   own `reason`, e.g. `src/dos/arbiter.py`), the tool, and the kernel's one-line
   reason. So "blocked 610" becomes "blocked 610 edits to the kernel's own running
   code, e.g. src/dos/arbiter.py via Write." Examples are banked only when
   `with_examples=True` (the `--explain` / `--json` paths), so the cheap rollup and
   the hot hook-nudge path stay cheap. `--json` carries `examples` + `glossary`.

Pinned by 11 added tests in `tests/test_help_summary.py` (29 total): the
proposal-body recovery, the handler fallback when no token exists anywhere, the
case-insensitive gloss + the never-invent rule, the env-authored path extraction,
the distinct-and-capped example banking, and the two renderer/CLI smokes.

## Phase 3 — honesty: headline what DOS DID, not what it merely warned about (2026-06-13)

Phase 2 made the count *legible*. Phase 3 makes it *honest*. On this repo the
rollup had grown to **"DOS has caught 802 things"** — and that number was wrong in
the way that matters. Folded by structure (no prose mined), the 802 split:

| Category | Count | `withheld` |
|---|---|---|
| BLOCK — a call DOS actually STOPPED (SELF_MODIFY edit / lane collision) | 176 | `true` |
| WARN — a contention caution; the call **ran anyway** | 629 | `false` |

So **DOS refused 176 calls** — but the headline credited it with 802, **~4.6×
inflated** by 629 advisory warns that changed no behavior. Nearly all 629 were the
single pattern `lane 'Read'/'Grep'/'PowerShell' has an EMPTY tree (unknown blast
radius) and cannot share live lane …` — read-only / unknown-footprint tools warned
but passed. This *directly violated the module's own rule* ("'Helped' is the rungs
that changed behavior … the number stays honest and is never inflated"): a
`withheld=false` advisory on a read-only tool changed nothing. And the rest of the
kernel already draws this line — `decisions.py` classes "unknown blast radius" as
*backpressure* (transient, not a decision), and `pretool_sensor.py` (issue #46) now
passes proven no-footprint reads CLEAN. The 629 are historical, pre-#46 warns;
`helped` was the one surface still counting them as headline "helps."

The fix keys off **one already-present, env-authored field — `withheld`** (no new
data, no text mining, byte-clean):

* **refused** = `withheld=true` — DOS actually stopped the call.
* **advisory** = a help that was not withheld — DOS surfaced a caution, the call
  proceeded.

Four changes, all structural:

1. **Refused-first headline** (`render_summary_text`). The count an operator reads
   first is the refused total: *"DOS has refused 176 calls for you."* The sub-line
   is **derived from `by_refused_reason`** (the withheld-only reason counts) — *"169
   SELF_MODIFY (kernel-self-edit), 8 admission (lane collision)"* — NOT a hardcoded
   two-category sentence, so it renders correctly for any of the 10+ reason classes
   the kernel emits (`UNKNOWN_LANE`, `provenance`, …), not just the two this journal
   happens to show. The 629 move to their own labeled line: *"+ 629 advisory cautions
   surfaced (the call was allowed to proceed)."* When nothing was withheld, the
   headline honestly leads with the advisory line instead.
2. **The rate denominator splits the same way** (`hook_observation.InterventionRate`).
   The old rate line — *"782 intervened (5.3%)"* — lumped refused with advised, the
   SAME conflation. From the already-recorded `outcome` field (`deny`/`block` vs
   `warn`), the rate now adds `refused`/`advised`: *"of those, 153 were refused (1.0%)
   and 629 were advised-but-allowed (4.2%)."* The headline and the rate finally tell
   one story. `intervened == refused + advised` on every outcome the kernel emits
   today; an unknown future token counts in `intervened` but neither sub-bucket (the
   safe direction).
3. **`dos helped --advisory`** keeps the 629 one keystroke away — broken down by
   tool (cautions cluster by tool) with a few concrete example reasons — so nothing
   is deleted or hidden, just off the default headline. `--json` carries `advisory`,
   `by_refused_reason`, `by_advisory_tool`, and the split rate.
4. **The nudge + stop digest** inherit the refused-first wording via `nudge_line`:
   *"DOS has refused N calls this session (+M advisory)."*

**Still byte-clean.** The refused/advisory split reads only the env-authored
`withheld` boolean and the env-authored `outcome` token; no `reason` prose is mined
for any count. `is_help` / `HELP_RUNGS` are unchanged — WARN/DEFER are still folded;
only the *presentation* separates withheld from advisory. No record is deleted or
rewritten; this is a read-time projection change.

**One gap surfaced, not papered over.** OP_ENFORCE and observation records carry
`holder`/`host_id`/`run_id`/`tool` but **no `model`** — DOS cannot say *which model*
made a caught call, so `helped` does not pretend to. The right home for that
dimension is the sensor (stamp the model from the PreToolUse event), tracked as a
separate `design` issue — not invented into this read-only projection.

Pinned by added tests in `tests/test_help_summary.py` (47 total) and
`tests/test_hook_observation.py`: the `advisory` property partition, the
withheld-only `by_refused_reason` / advisory-only `by_advisory_tool` folds, the
data-derived headline (incl. a multi-reason-class case that would catch a
hardcoded-two-category regression), the advisory-only headline, the `--advisory`
view + JSON split, the short-label never-invent rule, and the rate's
`refused`/`advised` split with its `intervened >= refused + advised` invariant.

## Phase 4 — grounding + value: "is this number real, and was the block worth it?" (2026-06-13)

Phase 3 made the count *honest* (refused vs advisory). Phase 4 answers the two
questions an operator asks of the deepest view, `dos helped --explain`: **is the
count grounded in a real denominator, and what did each block actually buy me?**
Audited on this repo, `--explain` had three gaps — every one a *missing* honest
fact, not a wrong one (the projection was already byte-clean):

1. **No grounding number on the deepest view.** The bare rollup shows the
   adjudicated denominator (*"of 14997 tool calls … 154 refused (1.0%)"*); the
   `--explain` drill-down — the one an operator opens to scrutinize — showed
   *none*. So the most-examined surface was the only one a reader could not
   ground. Fixed: `render_explain_text` now takes the same folded
   `hook_observation.InterventionRate` and renders the same self-contained block
   (reusing `_rate_lines`). Absent log ⇒ no block, byte-identical to before.
2. **What a class MEANS, never what the block BOUGHT.** `means:` glossed each
   class; nothing said *why stopping it mattered*. Added `REASON_VALUE` /
   `value_of` — a closed reference-data map (same keys, same never-invent rule as
   `REASON_GLOSSARY`) rendered as a `value:` line: `SELF_MODIFY` → *"prevented a
   kernel-corrupting self-edit — the agent would have rewritten the code that was
   adjudicating it"*; `admission` → *"prevented two workers colliding on the same
   files."* An unknown class gets no value line, exactly as it gets no gloss.
3. **No honest tiering of load-bearing vs noise.** On this repo 178 refusals
   withheld a real call; 629 advisory warns (mostly read-only Read/Grep against a
   busy lane) *ran anyway and changed nothing*. `--explain` listed them without
   saying which mattered. Added a closing footer derived from two env-authored
   counts — `withheld` (load-bearing refusals on write-capable tools) vs the
   advisory bucket (`by_advisory_tool`, named, flagged low-signal). This is the
   structural answer to *"is blocking a Read ever worth it?"*: the honest one on
   this repo is "those particular ones weren't," and the output now says so.

A fourth, smaller honesty fix is in the bare rollup: the headline counts every
withheld OP_ENFORCE on the lane journal (178) while the rate counts `deny`
outcomes in the observation log's shorter window (154) — two true numbers for the
same idea, four lines apart. The `_rate_lines` caveat now names *why* they differ
("two lenses on the same enforcement, not a disagreement") so the operator does
not read it as a bug.

**Still byte-clean, still no new store.** `REASON_VALUE` and `_WRITE_CAPABLE_TOOLS`
are closed reference data (the write-capable set is tool-NAME granularity — the
projection's altitude — deliberately NOT importing `pretool_sensor`'s bash-program
prefixes, which would be a category error and a sensor dependency). Every count
the footer renders is off the env-authored `withheld` / `tool` fields; no `reason`
prose feeds a value claim. `render_explain_text` gains a `rate=` param and three
lines; the fold is unchanged.

**Out of scope, surfaced not papered over.** A per-call *severity* score (beyond
the class-level value map) would need a new env-authored field at the sensor — not
invented into this projection. The model-dimension gap from Phase 3 (#143) is
unchanged. Pinned by 8 added tests in `tests/test_help_summary.py`: `value_of`
known/unknown/case-insensitive, the value line shown/omitted, the grounding rate
present/absent (byte-identical when absent), the load-bearing footer split + the
advisory-only case, and the reworded two-lenses caveat.
