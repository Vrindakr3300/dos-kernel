# 171 — DOS in skills, and the proof it solves the audited read-loop

> **Two halves of one claim.** (A) The shipped skill pack now teaches the
> syscalls by *worked example* — six `SKILL.md` screenplays plus a canonical
> [`EXAMPLES.md`](../src/dos/skills/EXAMPLES.md) cookbook, every transcript run
> against this repo's own generic workspace, naming no host. (B) Those same
> verbs *solve a real, audited pathology*: the `read_loop` the
> `/trajectory-audit` skill flagged in the `job` consumer repo on 2026-06-05 —
> 22 identical reads of one unchanged file, 177,866,472 cache-read tokens, no
> progress. `dos.tool_stream.classify_stream` catches that loop in flight and,
> at its default policy, would pre-empt up to ~17 of the 22 reads (the idealized
> back-to-back reading; the real interleaved stream is caught on each run that
> reaches the stall threshold — see B.3). This is a design/proof artifact, not
> strategy: it records what shipped and pins the verdict against the captured
> numbers.

---

## PART A — DOS in skills: the worked-example expansion

A skill is a **screenplay, not a program**: it shells `dos` verbs and reads the
verdict; the kernel decides ground truth, the skill narrates. The skill *is* the
judged agent; the kernel is the part that doesn't believe it. The SKP (docs/74)
already shipped the five domain-free screenplays as package-data. What landed now
is the **worked-example layer** on top of them.

### What was added

- A `## Worked example (live transcript)` section in each of the six shipped
  `SKILL.md` files under `src/dos/skills/`:
  `dos-next-up`, `dos-dispatch`, `dos-replan`, `dos-dispatch-loop`,
  `dos-replan-loop`, `dos-supervise-loop`. Each shows the screenplay's verbs run
  end-to-end against the generic workspace and the verdict the kernel returned.
- A new canonical cookbook, [`src/dos/skills/EXAMPLES.md`](../src/dos/skills/EXAMPLES.md)
  — *problem → the `dos` verbs → a real transcript → the rule it teaches*, one
  recipe per syscall. **Point readers here first**: it is the canonical entry to
  "how do I drive DOS from a skill?"

The recipes in `EXAMPLES.md`:

| # | Recipe | Verb(s) the rung lives on |
|---|---|---|
| 0 | Discover the workspace once, never re-read (the WCR on-ramp) | `dos doctor --workspace . --json` |
| 1 | Ask the truth syscall instead of grepping commit subjects | `dos verify … --json` |
| 2 | Take a lane before you write; honor the redirect | `dos arbitrate --lane L` |
| 3 | Gate the empty case by EXIT CODE, not prose | `dos gate <dispositions.json>` |
| 4 | Fold a run into ONE digest instead of re-reading state files | `dos status RUN_ID` (`dos trace` for the full walk) |
| 5 | Catch a doomed tool-loop in-flight | `dos.tool_stream.classify_stream` (Python API — no CLI verb) |
| 6 | Keep the WAL beat alive so a supervisor can see you | `dos lease-lane heartbeat` · `dos liveness` · `dos journal tail` |
| 7 | Do not trust a recalled memory; re-verify at read | `dos memory` / `dos_recall` |
| 8 | Wrap a headless agent so it CAN call the referee | `dos guard -- claude -p …` |

### The discipline (the litmus, restated for examples)

The shipped examples **name no host.** They drive `verify` / `arbitrate` /
`gate` / `status` / `liveness` / `lease-lane` / `tool_stream` against this repo's
*generic* dos workspace — the same lanes `dos doctor` reports
(`benchmark, docs, examples, scripts, spikes, src, tests` concurrent; `global`
exclusive), the generic plan `docs/82_liveness-oracle-plan`, the generic
`stamp.style == "grep"`. Every host-specific value a recipe needs is read once
from `dos doctor --workspace . --json` or from `dos.toml`, never hardcoded. A
`grep` of a shipped example for a host directory, lane, commit-prefix, or
filename returns nothing — the example analogue of "kernel imports no host," the
same rule SKP already enforces. The job-specific values in PART B
(`next_up_render.py`, the `replan` lane, session `8bd8c736`) live **only** in
this proof doc and the proof script, never inside `src/dos/skills/*`.

The captured transcripts in PART A's recipes are the live values from this
workspace (`dos_version 0.13.0`, the `grep-subject` SHIPPED on
`docs/82_liveness-oracle-plan liveness`, the `none` NOT_SHIPPED on
`docs/99…halt`, the `src`→`benchmark` arbiter redirect). Anything not captured
live is marked **ILLUSTRATIVE** (e.g. the `dos status` digest *shape*).

---

## PART B — Proof: DOS solves the audited `job`-repo `read_loop`

### B.1 The problem, from the audits

The `/trajectory-audit` skill swept the recent Claude Code session trajectories
and named the pathology twice over:

- **`job` trajectory audit, 2026-06-05 22:05** — `read_loop` flagged in **4
  sessions**. The headline session, `<session-id>`
  (`<project>`, 2.6 MB, **630 turns**, **177,866,472 cache-read tokens** — the
  single heaviest session by cache-read), read one unchanged file **22 times**:

  | reads | file |
  |---|---|
  | **22×** | `scripts/next_up_render.py` ← the headline read-loop |
  | 7× | `tests/test_next_up_render.py` |
  | 5× | `scripts/fanout_state.py` |
  | 3× | `tests/test_fanout_state.py` |

  **44 total Read calls across only 8 unique files.** 22 reads of one unchanged
  file is the loop-economics pathology (docs/145): the agent re-issues the same
  Read, the filesystem returns the *same bytes*, no new information enters the
  loop, and ~177M cache-read tokens burn while the task does not advance.

- **dos-workspace audit, 2026-06-05 22:08** — `read_loop` in **8 sessions**,
  plus **`shell_poll`**: polling a `.output` file in a loop. The poll is
  *wasted* because the harness re-invokes the agent on background-task
  completion — there is nothing to poll for (the
  [don't-poll-background-tasks](../) working preference). The audit's **DOS
  cross-signal showed 0 confident joins**, because the *dispatch path* emits no
  `HEARTBEAT`/`SCAVENGE` journal ops — so the audit had no run-id-keyed beat to
  join the narration against.

That last point has a live exception that makes the join **reachable**: the `job`
lane journal *does* now carry the write-side ops. `dos journal --workspace .
tail` of `job/.dos/lane-journal.jsonl` shows real `HEARTBEAT` (lane `AB`,
`loop_ts 20260606T043137Z` — the beat that makes SPINNING reachable),
`ACQUIRE` (lane `replan`, kind `keyword`), `RELEASE` (lane `TF`), and a real
**`REFUSE` at seq 1736** on lane `replan`:

```text
REFUSE  lane=replan  seq=1736
        reason="lane replan is already held by a live loop — pick a different --scope or wait."
```

And the `REFUSE` row's `blocking_trees` for lane `AB` lists, among others,
`scripts/next_up_render.py` — i.e. **the very file the read-loop spun on sits in
the AB/orchestration blocking tree.** So the narration-vs-ground-truth join the
audit wants ("an agent burning 177M tokens re-reading a file while the kernel was
adjudicating that region") is not hypothetical: the lane journal already holds the
ground-truth side of it.

### B.2 The mechanism — `dos.tool_stream.classify_stream`

`tool_stream` is `liveness`'s lateral sibling (docs/145): the same
temporal-distrust verdict, re-aimed off the git/journal stream onto the
**in-process tool-result stream**. Where `liveness` asks "did GIT state
advance?", `tool_stream` asks "did the env's tool RESULTS advance, or did the
same `(tool, args, result_digest)` triple recur N times?"

`classify_stream(ToolStream, StreamPolicy) -> StreamVerdict` measures the
**trailing consecutive-identical run** and returns one of
`ADVANCING` / `REPEATING` / `STALLED`. `DEFAULT_POLICY` is **`repeat_n=3`**
(fire REPEATING at the 3rd identical call) and **`stall_n=5`** (fire STALLED at
the 5th).

The load-bearing **byte-clean argument** (docs/145 §5a — must stay accurate):
`StreamStep.result_digest` is **ENV-AUTHORED** — the filesystem / gym produced
those bytes, not the agent. The agent did *not* author the *identity* of its own
repeated results. So REPEATING is **provenance-of-repeated-output**, a pure byte
question about env-authored output, never an "is-the-agent-succeeding?"
satisfaction predicate (the mirror-verifier trap the
[consistency-is-not-grounding](../) law warns against). Because
eventual-consistency polling (re-GET until a value flips) is a *legitimate*
repeat, the consumer's action is a **turn-preserving WARN that re-surfaces the
value**, never a process cut (the docs/99 advisory line; the docs/144 −9pp
intervention-cost lesson). The verdict informs; it never kills the loop.

### B.3 The live proof

Replaying the captured 22× repeat through the Python API (no CLI verb exists —
see B.5) produced the **real captured output**:

```python
from dos.tool_stream import ToolStream, StreamStep, StreamPolicy, classify_stream
steps = tuple(StreamStep("Read", "digest(next_up_render.py)", "sha-of-file-bytes")
              for _ in range(22))
v = classify_stream(ToolStream(steps))
```

```text
state:      STALLED
repeat_run: 22
reason:     "the same (tool, args, result) triple repeated 22 consecutive times
             (>= stall 5) — the loop is near-certainly doomed; the env returned
             identical bytes each time (no new information)"
```

**The saving.** With `stall_n=5`, DOS fires REPEATING at the 3rd identical read
and STALLED at the **5th**. Re-surfacing the held file bytes at the stall point
pre-empts every read after it: on a tight uninterrupted 22-loop that is **~17 of
22 reads** saved — on the *same* budget, never a cut. (Honest reading: in the
real session the 22 reads are *interleaved* with reads of other files, so they
form several consecutive runs rather than one 22-run; `tool_stream` measures the
trailing run and catches the loop on *each* run that reaches `stall_n`,
re-surfacing every time the agent re-enters it. The single
`STALLED, repeat_run 22` above is the idealized back-to-back loop.) The full,
re-runnable proof — including the interleaved-stream sliding-window reading and a
byte-clean demonstration (flip one `result_digest` → the run breaks back to
ADVANCING) — is
[`benchmark/toolathlon/dos_solves_read_loop.py`](../benchmark/toolathlon/dos_solves_read_loop.py).

### B.4 The `shell_poll` half

`shell_poll` is the *same family*: a poll that re-reads a `.output` file and gets
back the same bytes is a `REPEATING` tool_stream over the poll tool — identical
`(tool, args, result_digest)` recurring, env-authored bytes, no new information.
Add the memory that **the harness re-invokes the agent on background-task
completion**, so the polling is wasted work even when the bytes *do* eventually
change.

Stated honestly: the **read-repetition** half is *mechanized* — `tool_stream`
classifies a poll-loop exactly as it classifies a read-loop. The
**poll-is-wasted** half is *advisory only* — "the harness will re-invoke you, so
don't poll" is a known anti-pattern (and a working-preference memory), **not yet
a kernel verb.** No syscall today reads the harness's re-invocation contract.

### B.5 The boundary (honest, per probe-then-build)

Per the [probe-target-and-verify-reuse](../) discipline, the exact proof
boundary:

- **No CLI verb.** There is no `dos tool-stream`. The stall verdict is consumed
  via the **Python API** (`dos.tool_stream.classify_stream`) or wired into a
  host's tool-result hook. The only CLI surface on this axis is
  `dos tool-stream-eval`, the per-axis *evaluation* harness — not a live
  classifier. The proof script and the EXAMPLES recipe both call the Python API.
- **Independent-Repository rule honored.** The proof *runs* against
  `job/` (reads its trajectory and lane journal) and *writes* its
  artifacts under `dos/` (this doc, the proof script). It does **not**
  edit `job/.claude/skills/*` or any job code.
- **The join is reachable but not yet wired in-flight.** The lane journal already
  carries the ground-truth side (B.1's seq-1736 REFUSE, the AB blocking tree),
  and `tool_stream` already classifies the agent-narration side. What is missing
  is the seam between them: the dispatch loop must **emit the per-read tool stream
  to a hook** for *in-flight* (rather than post-hoc) prevention.

**PROVEN vs FUTURE.** PROVEN: the verdict catches the real loop —
`classify_stream` returns `STALLED, repeat_run 22` on the captured stream, exact
and replay-testable offline with zero benchmark/LLM/MCP access, and would
pre-empt ~17 of 22 reads at the default policy. FUTURE: the in-flight hook wiring
— routing the live tool-result stream into `classify_stream` so the WARN
re-surfaces the held bytes *while the agent is still spinning*, instead of an
auditor finding the burn after the run is dead.
