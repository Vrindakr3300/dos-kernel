# Handoff — Toolathlon replay study (next agent)

> **GOAL (done, Phase 1):** test DOS on the Toolathlon benchmark (ICLR 2026,
> `hkust-nlp/Toolathlon`) the cheapest honest way — a **$0 replay** over the published
> `Toolathlon-Trajectories` dataset, scoring DOS's byte-clean detectors (`dangling_intent`,
> `tool_stream`) against the benchmark's **third-party** pass/fail oracle. Measure detector
> PURCHASE (fire-rate + oracle-confirmed precision), **not** task LIFT (frozen trajectory ⇒ no
> intervention ⇒ no lift number). The full design + the why-replay-not-live decision is **docs/157**.

## ⏩ LIFT-SIDE STATUS (2026-06-05 session — the DETECT→FIX push)

The DETECT-not-FIX boundary is being crossed. What is BUILT + $0-PROVEN this session:
- **`conversion_ceiling.py`** (`4622cb9`) — the $0 gate: corpus ceiling **+2.40pp MAX**, frontier
  models **0 recoverable** (the scissors confirmed), convertible mass = tool_stream loops on mid-tier.
- **`warn_patch.py`** (`974a799`) — the live **F0 tool_stream WARN** arm (re-surface the looping
  value), with **6 byte-parity tests** proving the live verdict == the offline replay (the silent-no-op
  risk closed). It is the 3rd member of the F0 family (`terminal_error_gate`/`DOS_DANGLING` are the
  others, docs/163).
- **The container A/B wiring** (`176cf23` + `_ab_wiring/`) — `sitecustomize.py` + a DOS_WARN-gated
  `run_single_containerized.sh` patch (saved as `toolathlon_runner_dos_warn.patch`). VERIFIED: the
  WARN patch installs `_dos_warn_wrapped=True` **inside the live task container** during a real
  gemini-2.5-pro run. The A/B is turnkey: `_ab_wiring/run_ab.sh <reps>`.
- **`src/dos/rewind.py`** (`fc64396`) — the **F1.5 rewind-conversation kernel verdict** (docs/164
  backjumping + no-good learning): the principled deeper FIX lever. Byte-clean BY CONSTRUCTION (the
  no-good note has no free-form str slot; an AGENT_AUTHORED excerpt is structurally filtered).
  Adversarially verified SHIP, 31 tests. The boundary reader + CLI + the FIX LOOP (P1) are unbuilt.

**RUNNING NOW:** the F0 A/B (`gemini-2.5-pro`, 6 loop-enriched pure-local tasks, OBSERVE vs WARN, 1
rep = 12 runs) in WSL2 — `_ab/batch.log`. Score when done:
`python -m benchmark.toolathlon.live_adapter _ab/observe_run* _ab/warn_run*`, then diff pass-rate +
the conversion rate (of WARN runs where tool_stream fired, fraction that flipped fail→pass).
**Honest boundary: N=6×1 is a DIRECTIONAL pilot** — report a wide CI; expand reps if the signal is
non-zero. The full recipe + every WSL/Docker trap (the `uv`/PATH silent-exit-0, no-concurrent-
containers, serper confound) is in **`AB_RUN_RECIPE.md`**. The FIX architecture is **docs/164** (the
F0–F3 ladder + the rewindable loop = the real answer to "weak model + DOS ≈ stronger model").

## YOUR FIRST TWO TASKS (operator-requested, do these before extending the study)

1. **VISUALIZE the data found.** The replay already wrote the explorable substrate — render it.
   Inputs (both gitignored, regenerate offline in seconds, see below):
   - `_results/replay_all_rows.jsonl` / `.csv` — **the durable flat dataset**: ONE ROW PER (model,
     run, task), every field a scalar. Columns: `model, model_run, task_name, passed,
     n_tool_steps, dangling_fired, dangling_cue, tool_stream_state, tool_stream_run,
     tool_stream_fired, final_text_len`. Loads straight into pandas/sqlite/a notebook — no
     reshaping.
   - `_results/replay_all.json` — the aggregate + per-model confusion grids.
   Suggested figures (the docs/157 §4 gaps): (a) per-model fire-rate vs base-fail-rate (the
   "fires-where-weakest" story); (b) precision/lift bar per detector per model family; (c)
   fire-rate vs model leaderboard rank (purchase vanishing on the frontier); (d) a confusion-grid
   heatmap. Keep it dependency-light (matplotlib/plotly) and write the figures to `_results/`
   (gitignored) + commit only a small static PNG/SVG if useful, or a `viz.py` that regenerates.
2. **CONFIRM the data is durable to explore.** It is, by design — but verify and harden:
   - The **raw trajectories** (`_data/*.jsonl`, ~GBs) are gitignored CC-BY-4.0 data, re-fetched on
     demand (`dataset.ensure_file`). Do NOT commit them.
   - The **derived rows** (`_results/*_rows.{jsonl,csv}`) are the durable, self-contained,
     reproducible-from-frozen-data artifact — every number in docs/157 is recomputable from them
     with zero network. If you want them version-controlled, they are small enough; decide and
     un-gitignore `_results/*_rows.*` specifically if so (the raw `_data/` stays out).
   - Consider a tiny `schema.md` next to the rows documenting each column (half of it is in
     `replay.py:RunRow` docstring already).

## What is built + green (Phase 1, SHIPPED this session)

`benchmark/toolathlon/` — a CONSUMER of the kernel (`import dos`; nothing under `src/dos/` imports
it — the one-way arrow). Four modules, the `dos` pure-core-plus-boundary idiom:

- `trajectory.py` — boundary READER: raw record → frozen `StopEvidence` / `ToolStream`. Pure given
  the dict. Handles the dataset's JSON-string fields, OpenAI-chat message shape, local-noop-tool
  exclusion (`claim_done` is not "acting"), tool_call_id pairing.
- `replay.py` — the SCORER (pure over parsed trajectories): folds both detectors, joins to the
  third-party label, accumulates the `DetectorReport` confusion grid, AND emits the flat `RunRow`.
- `dataset.py` — the ONLY I/O: download + stream the JSONL from HF.
- `run_replay.py` — the CLI.
- `tests/test_toolathlon_replay.py` — **16 tests green**, all on FROZEN synthetic fixtures (zero
  network/LLM/MCP — the "testable with zero benchmark access" keystone).

**Verified results (docs/157 §4):** full corpus 7,116 records / 6,862 labeled, 22 models × 3 runs:
`dangling_intent` fire 1.5% / **precision 98.0%** / lift +21.9pp; `tool_stream` fire 1.7% /
precision 84.9% / lift +8.7pp. High precision, ~2% recall, purchase VANISHES on the strongest
model (claude-4.5-sonnet/opus, gemini-3-pro fire ~0). DETECT generalizes; the narrating/looping
recall ceiling holds — the EOG track record reproduced on a public, third-party-scored benchmark.

## How to run (all $0, no accounts, no containers, no API)

```bash
cd dos

# list the 66 dataset files
python -m benchmark.toolathlon.run_replay --list

# smoke: one file, first 10 records (downloads ~one file)
python -m benchmark.toolathlon.run_replay --files gemini-2.5-flash_1.jsonl --limit 10

# full corpus from cache (offline; ~seconds once _data/ is populated) + durable rows + JSON
python -m benchmark.toolathlon.run_replay --all --no-download --by-model \
    --out benchmark/toolathlon/_results/replay_all.json \
    --rows-out benchmark/toolathlon/_results/replay_all_rows

# the tests (zero network)
python -m pytest tests/test_toolathlon_replay.py -q
```

`--ts-min-state STALLED` counts only the harder stall as a tool_stream fire (stricter, fewer
fires). `--limit N` caps records/file for a cheap pass.

## The honest boundaries (do NOT overclaim — docs/157 §5)

- **DETECT, not FIX.** Frozen trajectories → no intervention → **no lift number.** Whether a WARN
  re-surface would CONVERT a fired failure to a pass is the live-A/B question, and the EOG record
  predicts NULL on capable models (a capable model that stopped couldn't form the step). Lift has
  only ever appeared on a WEAK model — and the weak model where lift could appear is NOT the strong
  model where lift is leaderboard-citable (the scissors no single run closes).
- **`tool_stream` fire-rate is a LOWER BOUND.** `result_digest` digests RAW result bytes; volatile
  SaaS fields (timestamps, request-ids) make identical re-reads digest differently → under-counts
  repeats (and causes the handful of false alarms). **The #1 detector-quality lift** is a
  per-app-family `result_digest` NORMALIZER (strip volatile fields before hashing) — see
  `trajectory.to_tool_stream`'s caveat note.
- **`verify`/`arbitrate`/`liveness`/`resume` are NULL here:** single-agent isolated state ⇒ no
  admission; no git/WAL ⇒ shipped git-rung verify/liveness/resume inert. Toolathlon's own
  `evaluation/main.py` IS the verify rung and DOS does not own it. Only the two in-flight byte-clean
  detectors have a job.

## Traps already hit (don't re-learn)

- **Windows console is cp1252** → crashes printing the CJK task text / em-dash. `run_replay.py`
  forces stdout UTF-8; do the same in any new print script (`sys.stdout.reconfigure(encoding=
  "utf-8", errors="replace")`).
- Dataset fields `task_status` and `messages` arrive as **JSON STRINGS** (not objects) in the
  published files — `trajectory._coerce_json` handles both shapes; don't assume parsed.
- `task_status.evaluation` is the THIRD-PARTY label; **None (absent / task errored) is EXCLUDED**
  from precision, never guessed.
- A `tool` message usually lacks the tool NAME (only `tool_call_id`) — resolve it from the issuing
  assistant `tool_calls` (`_tool_msg_name`).
- The dataset is **66 files (22 models × 3 runs)**, not the README's "17×3". An interrupted
  download leaves a `.jsonl.part` — `ensure_file` writes `.part` then atomically replaces; clean
  stray `.part` files before an `--all --no-download` run (one bit me this session).
- **`_data/` and `_results/` are gitignored** (`benchmark/toolathlon/.gitignore`). The raw
  trajectories are large CC-BY data — keep them out of git. Commit code + docs only.
- **CONCURRENT AGENTS edit this repo.** Stage ONLY your lane (`git add benchmark/toolathlon
  docs/157 tests/test_toolathlon_replay.py`), never `git add -A`.

## The ladder beyond Phase 1 (cheapest-first, per docs/157)

- **Phase 2 (≈$0) — DONE this session.** The four figures (`viz.py` → `_results/fig{1-4}_*.png`,
  committed), the durable-rows confirmation (`schema.md` + un-gitignored CSV/JSON), and the
  `result_digest` normalizer (SHIPPED, `trajectory.normalize_result_bytes`, default-on, `--raw-digest`
  for the floor). **Surprise finding, recorded honestly:** the normalizer's effect was RECALL, not
  false-alarm-cleaning — `tool_stream` recall 1.9%→2.9%, precision 84.9%→88.2%, lift +8.7→+12.0pp
  (recovered ~49 real repeats the raw timestamp/UUID churn hid); **false alarms barely moved (18→20)**.
  So the grok-4/o4-mini/gemini-2.5-flash 8–10% false-alarm spikes are a DIFFERENT phenomenon (genuine
  identical-result polling on tasks that passed), NOT volatile-field noise — see docs/157 §4. Still
  open in Phase 2: the per-failure-mode breakdown (join fires to the paper §5 taxonomy).
- **Phase 3 (≈$1–3, optional):** a single-task LIVE seam smoke — confirm a DOS WARN round-trips
  through Toolathlon's agent loop. The seam (VERIFIED, docs/157 §1): the OpenAI path already
  monkey-patches dispatch at `utils/openai_agents_monkey_patch/custom_run_impl.py` (await a DOS
  verdict before `on_invoke_tool`, ~10–15 lines); the Claude path has a native `can_use_tool`
  pre-tool hook on `ClaudeAgentOptions` (but NOT wired in Toolathlon — a build). Use a local-only
  task (`needed_mcp_servers` ⊆ {filesystem, terminal, emails, canvas}) to avoid external accounts.
  This proves the seam; it is NOT a result (N=1 directional).
- **Phase 4 — the live none-vs-WARN A/B (the ONE move that makes this publishable).** The detailed
  ready-to-run prompt is below.

---

## PHASE 4 — the next model's prompt: the live A/B that produces a LIFT number

> **Why this is THE move.** Everything shipped so far measures **DETECT**, not **FIX**. A reviewer
> discounts a detection-only result: "you flag failures, but does flagging them FIX anything?" The
> replay cannot answer that — a frozen trajectory had no intervention. Only a live run where DOS's
> WARN actually re-surfaces the value mid-loop produces a **lift number** (Δ task-pass-rate,
> none-vs-WARN). That single number is the difference between "an interesting detector study" and "a
> substrate that moves a third-party benchmark." It is also the EXPENSIVE move, so it is gated and
> scoped tightly below.

**The honest prediction, up front (do not bury it).** The EOG track record predicts the FIX is
**null on capable models** and **directional-positive only on a weak model**: a capable model that
stopped could not form the next step, so re-surfacing its own value hands back the wall it hit; a
weak model that *looped* on an eventual-consistency re-read can be unstuck by re-presenting the value
it already holds. So the A/B's expected shape is: **~0 lift on the leaderboard models, a small
positive lift on the one weak model** — and the weak model where lift appears is NOT the strong model
where lift would be leaderboard-citable. That scissors is the result; the A/B *confirms* it on a
third-party-scored benchmark, which no DOS run has done. Report the null on strong models as a
finding, never as a failure.

**The target model.** `gemini-2.5-flash` — Toolathlon ran it at **3.7% Pass@1** (the weakest in the
paper table), and the replay shows it is the model where `tool_stream` ALREADY fires most (fire
3.8%, the loop-on-eventual-consistency signature). It is the single best shot at a positive lift and
the cheapest frontier model to run. (A second arm on a mid model like `gpt-5-mini` is optional, for
the "lift decays with capability" curve.)

**The seam to wire (VERIFIED, docs/157 §1 — this is a ~15-line build, not a rewrite).**
- OpenAI Agents SDK path (what gemini-2.5-flash runs through): Toolathlon already monkey-patches tool
  dispatch at `utils/openai_agents_monkey_patch/custom_run_impl.py`. Insert, immediately BEFORE
  `on_invoke_tool` dispatches the call: build the live `ToolStream` from the turn history so far
  (reuse `benchmark/toolathlon/trajectory.to_tool_stream`'s step-assembly — the SAME normalizer, so
  the live verdict matches the replay), call `dos.tool_stream.classify_stream`, and on `REPEATING`
  inject a **WARN** system/user message that re-surfaces `repeated_step.result_digest`'s value
  ("you already received this result N times: <value> — use it or do something different"). Do NOT
  block, skip, or substitute the call — WARN-only.
- Mirror `dangling_intent` at the STOP boundary: before the agent's final stop is accepted, run
  `classify_stop`; on a dangling verdict, inject the same kind of WARN ("you said you still need to
  X — continue") and let the loop take one more turn.

**The WARN-only discipline (NON-NEGOTIABLE — this is the −9pp lesson made structural).**
`[[project-dos-arg-provenance-shipped]]` and the docs/144 intervention A/B both showed a CORRECT
detector can be **net-harmful** if the intervention is too disruptive: a skip/block/synthetic-
substitution nudge derailed the model and cost MORE tasks than it saved (−9pp despite an 88% catch
rate; BLOCK was the worst arm in the gym A/B, WARN the best at +4.2pp). So:
- **OBSERVE arm** (control): detectors run, verdicts logged, NOTHING injected.
- **WARN arm** (treatment): on a fire, inject a turn-PRESERVING re-surface message only. Never cut a
  turn, never substitute a tool result, never force a skip. Re-surfacing a value the agent already
  holds is harmless if it was right to wait and helpful if it was stuck — the only safe actuation.
- Run the SAME tasks, SAME seeds, SAME max_iterations across both arms; the only delta is the WARN.

**The measurement.** Pass-rate per arm from Toolathlon's own `evaluation/main.py` (the third-party
oracle — DOS does not score the A/B, which is the whole point). Lift = WARN pass-rate − OBSERVE
pass-rate, with a per-task McNemar / paired-bootstrap CI (N≈108 tasks × runs; expect a wide CI at
this N — say so). Secondary: of the runs where a detector FIRED in the WARN arm, what fraction
flipped fail→pass vs the OBSERVE arm (the conversion rate the replay structurally could not measure).

**Cost & gating.** ≈$170–1.8K/full pass (≈32 app containers, Gmail/GitHub/Canvas/Notion accounts,
real API). **Gate before spending:** (1) a $0 Tier-0 prediction first — the gym A/B's $0 sweep
PREDICTED the live ranking, do the same here (replay the WARN logic offline over the existing
trajectories to bound the max possible conversions); (2) a Phase-3 single-task seam smoke (≈$1–3) to
prove the WARN round-trips before a full A/B; (3) restrict the first pass to **local-only tasks**
(`needed_mcp_servers` ⊆ {filesystem, terminal, emails, canvas}) to avoid external-account setup,
accepting the smaller N. Only escalate to the full external-account pass if the local-task lift is
non-zero.

**The deliverable.** A lift number with a CI and the conversion rate, written into docs/157 as a new
§ (DETECT→FIX), with the strong-model null reported as honestly as the weak-model lift. That turns
the replay's "PURCHASE, no lift" into "PURCHASE + a measured (likely small, weak-model-only) FIX on a
third-party-scored benchmark" — the publishable shape.

---

## Deliverable (Phase 2, DONE) / next (Phase 4)

Phase 2 shipped: the figures + durable-rows + normalizer, written up in docs/157 §4 with the RUNG,
the recall band, and the honest "normalizer lifted recall not false-alarms" finding. **Phase 4 (the
live A/B above) is the next agent's pickup — it is the one move that makes the study publishable.**
**Commit your lane only.**
