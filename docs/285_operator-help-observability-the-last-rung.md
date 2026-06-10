# docs/285 — Operator help observability: the last rung, from the WAL out to the human

> **Status:** SHIPPED. `dos helped` + the in-flow hook nudge + the session-stop
> digest land together; pinned by `tests/test_help_summary.py` (29 tests). Built on
> the OP_ENFORCE stream the lane WAL already carries (docs/189 §C4) — no new store.
> **Phase 2 (2026-06-10):** clarity — recover the typed reason class so the phantom
> `admission`/`SELF_MODIFY` split collapses, gloss every class in plain English, and
> add `dos helped --explain` for concrete examples (which file, why). See below.

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
