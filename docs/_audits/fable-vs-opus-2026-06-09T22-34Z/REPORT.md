# Claude Fable 5 vs Opus 4.8 — head-to-head, head­less CLI path

**Run UTC:** 2026-06-09T22:34Z · **Harness:** `claude -p --model {fable,opus}` (the
exact headless path this repo's loops use) · **Budget:** $20 ceiling, **spent
$8.63** · **Runs:** 40/40 completed (no truncation).

---

## TL;DR

On a **20-task agentic-coding suite run live through the headless CLI** (12
SWE-bench-Verified-shaped bug-fixes + 8 Terminal-Bench-shaped tool tasks, each
graded by a **hidden OS-recorded oracle** the model never saw):

- **Fable 5 solved 20/20 (100%). Opus 4.8 solved 19/20 (95%).** The single
  difference is `swe11_duration`, where Opus made a correct *partial* fix but
  missed a spec requirement stated in the docstring; Fable handled the full spec.
- **Fable costs ≈2× Opus for the same work** — measured: **$5.83 vs $2.79 total
  (2.09×)**, **$0.292 vs $0.147 per solved task (1.98×)**, per-task median
  **2.02×** (range 1.34×–4.60×). This matches the published 2× list price
  ($10/$50 vs $5/$25 per Mtok) plus Fable's heavier per-call cache-write.
- **At this task difficulty both models nearly saturate**, so this suite cannot
  separate them on raw frontier capability — and it is not meant to. The wide
  published gaps live on *harder* suites (SWE-bench **Pro** 80% vs 69%;
  **FrontierCode** 29.3% vs 13.4%) that need per-instance Docker we can't stand up
  here. **Read this audit as a cost-and-reliability measurement on real
  every-loop-shaped work, not as a frontier-capability ranking.**

**Recommendation on the loops' Fable default:** see [§4](#4-recommendation). Short
version: **the 2× is not earned on routine loop work** (bug-fixes, file edits,
scaffolding, shell tasks), where Opus matched Fable 19/20 at half the price and
1.5× faster wall-clock. Keep Fable as the default **only** for the work that
actually lands in Fable's published lead — frontier-difficulty / long-horizon
tasks — and route routine loop steps to Opus.

---

## 0. Method & honesty caveats (read first)

### What was measured
Both models were driven through the **identical** invocation, only `--model`
differing — the method the goal pinned and that this repo's loops use:

```
claude -p "<task>" --model {fable|opus} --permission-mode bypassPermissions \
        --max-turns 30 --output-format stream-json --include-partial-messages \
        --verbose > run.log 2> run.err
```

Per run we captured the `result` envelope (`total_cost_usd`, `modelUsage`,
`num_turns`, `duration_ms`, `stop_reason`, `terminal_reason`) and the benchmark's
own pass/fail. Files: `run_bench.py` (runner), `suite.py` (tasks + oracles),
`analyze.py` (tables), `runs/*.json` (one record per run), `results.json`
(roll-up).

### The grading is non-forgeable (the DOS philosophy, applied to itself)
The agent is shown a buggy/empty git repo and a task; **it never sees the grading
test.** After it commits, the oracle materializes a **clean checkout of the
agent's `HEAD`** (`git archive HEAD | tar -x`, so a dirtied working tree cannot
fake a pass), drops in the hidden test, and runs it. **The oracle's OS exit code
is the witness** — the agent authored zero bytes of it. This is the same
non-forgeable-witness design as this repo's `benchmark/fleet_horizon/forge.py`
and `dos.oracle` (docs/121 acceptance verb): pass/fail is a property of the world,
not of the model's "I'm done" narration. A negative control (grade an unfixed
repo) confirmed the oracle *fails* unsolved work rather than rubber-stamping it.

### These are PROXIES, named so — not the official leaderboard numbers
The published Fable 5 card reports **SWE-bench Verified 95.0%** and
**Terminal-Bench 2.1 84.3%**. Those come from the **official harnesses**
(SWE-bench Verified runs a Docker image per real GitHub issue; Terminal-Bench runs
its own task containers) — too heavy to stand up reliably in this environment.
So this suite is an **honest hand-built proxy** with the same *shape* (resolve a
real defect / complete a real CLI task; a hidden test must pass), labeled
`swe_proxy` / `term_proxy` throughout. **Do not read 20/20 here as "Fable scores
100% on SWE-bench Verified."** It means: *on 12 representative bug-fixes and 8
representative shell tasks, run live, Fable passed all of them.* The point of the
audit is the **cost and reliability comparison under an identical harness**, which
is measured exactly, not the absolute capability score.

### Subset honesty
The suite is **20 tasks (12 + 8)**, above the goal's ≥10-per-bench floor for the
two families. It is a representative subset of the *kind* of work the loops do,
not a sample of the official benchmark instance sets. Stated, not hidden.

### Integrity checks that passed
- **No silent Fable→Opus fallback.** The card warns Fable falls back to Opus on
  cybersecurity/bio/chem/distillation safety refusals. Every Fable run's
  `modelUsage` shows **only `claude-fable-5`** (ex the harness's own haiku
  sub-agent); every Opus run shows only `claude-opus-4-8`. Clean A/B — no
  coding task tripped a safety classifier.
- **Cost figures reconcile.** `total_cost_usd` equals the sum of per-model
  `costUSD` in `modelUsage` on every spot-check (e.g. `swe9_csv` fable
  $0.6129 = $0.6123 fable + $0.0006 haiku).

### Budget (stated up front, honored)
Hard **$20** ceiling, checked after every run, stop-and-write on breach.
**Spent $8.63**, all 40 runs completed, no early stop. Per-run cap `--max-turns
30`.

---

<!-- TABLES BELOW ARE GENERATED BY analyze.py FROM results.json — NOT HAND-ENTERED -->

## 1. Per-benchmark results — Fable 5 vs Opus 4.8

### SWE-bench-Verified-shaped (hidden pytest oracle)

| Model | Solved | Pass-rate | Total $ | $/solved | Avg turns | Avg wall (s) |
|---|---|---|---|---|---|---|
| fable | 12/12 | 100% | $3.99 | $0.333 | 6.0 | 41 |
| opus  | 11/12 | 92%  | $1.86 | $0.169 | 6.1 | 26 |

### Terminal-Bench-shaped (hidden command oracle)

| Model | Solved | Pass-rate | Total $ | $/solved | Avg turns | Avg wall (s) |
|---|---|---|---|---|---|---|
| fable | 8/8 | 100% | $1.84 | $0.230 | 4.5 | 25 |
| opus  | 8/8 | 100% | $0.94 | $0.117 | 4.9 | 20 |

### Overall (both families)

| Model | Solved | Pass-rate | Total $ | $/solved | Avg turns | Avg wall (s) |
|---|---|---|---|---|---|---|
| fable | 20/20 | 100% | $5.83 | $0.292 | 5.4 | 34 |
| opus  | 19/20 | 95%  | $2.79 | $0.147 | 5.6 | 23 |

## 2. $/solved-task and the quality-per-dollar verdict

- **Fable 5**: solved 20/20 at **$0.292/solved-task** (total $5.83).
- **Opus 4.8**: solved 19/20 at **$0.147/solved-task** (total $2.79).
- **Cost ratio (Fable $/solved ÷ Opus $/solved): 1.98×.** Total-spend ratio
  **2.09×**; per-task median **2.02×** (min 1.34×, max 4.60× on `swe9_csv`,
  where Fable's cache-write ballooned).
- **Quality delta (Fable − Opus solved): +1 task** out of 20 each (+5pp).
- **Wall-clock:** Fable 687s vs Opus 468s total — **Opus is 1.47× faster**.

**Quality-per-dollar:** On this routine-work suite, **Opus is the better
quality-per-dollar buy by a wide margin** — it bought 95% of Fable's solved tasks
at ~50% of the cost and ~68% of the wall-clock. Fable's extra +1 solve cost an
incremental **$3.04** of total spend (the whole 2× premium across 20 tasks) to buy
one additional correct task on a suite this easy. That is a poor marginal rate
*here*; it would invert on a suite where Fable's published capability lead is
large (see §3 and §4).

## 3. Per-task outcomes — the one disagreement is the whole story

| Task | Family | Fable | Opus | Fable $ | Opus $ | Fable t | Opus t |
|---|---|---|---|---|---|---|---|
| swe1_daterange | swe | ✅ | ✅ | $0.346 | $0.245 | 7 | 11 |
| swe2_lru | swe | ✅ | ✅ | $0.315 | $0.146 | 5 | 5 |
| swe3_split | swe | ✅ | ✅ | $0.277 | $0.139 | 5 | 5 |
| swe4_email | swe | ✅ | ✅ | $0.270 | $0.156 | 5 | 6 |
| swe5_counter | swe | ✅ | ✅ | $0.266 | $0.134 | 5 | 5 |
| swe6_roman | swe | ✅ | ✅ | $0.288 | $0.138 | 5 | 5 |
| swe7_median | swe | ✅ | ✅ | $0.277 | $0.150 | 5 | 6 |
| swe8_geom | swe | ✅ | ✅ | $0.273 | $0.133 | 6 | 6 |
| swe9_csv | swe | ✅ | ✅ | $0.613 | $0.133 | 11 | 5 |
| swe10_flatten | swe | ✅ | ✅ | $0.264 | $0.128 | 5 | 5 |
| **swe11_duration** | swe | ✅ | ❌ | $0.528 | $0.147 | 8 | 6 |
| swe12_brackets | swe | ✅ | ✅ | $0.274 | $0.204 | 5 | 8 |
| term1_fizzbuzz | term | ✅ | ✅ | $0.191 | $0.086 | 3 | 3 |
| term2_sum | term | ✅ | ✅ | $0.259 | $0.146 | 5 | 6 |
| term3_config | term | ✅ | ✅ | $0.223 | $0.107 | 4 | 4 |
| term4_logcount | term | ✅ | ✅ | $0.228 | $0.107 | 4 | 4 |
| term5_greet | term | ✅ | ✅ | $0.219 | $0.124 | 4 | 5 |
| term6_wordcount | term | ✅ | ✅ | $0.267 | $0.123 | 6 | 5 |
| term7_scaffold | term | ✅ | ✅ | $0.226 | $0.121 | 6 | 7 |
| term8_pipeline | term | ✅ | ✅ | $0.227 | $0.124 | 4 | 5 |

- **Both solved:** 19 · **Fable only:** 1 (`swe11_duration`) · **Opus only:** 0 ·
  **Neither:** 0

### Why Opus missed `swe11_duration` (and why it's a real signal, not noise)
The task: `humanize(seconds)` → `'Hh Mm Ss'` **dropping leading zero units**
(`61 → '1m 1s'`, `5 → '5s'`), and there *was* a minutes-math bug to fix.

- **Opus** committed *"Fix minutes calculation in humanize()"* — it correctly
  fixed the minutes math, but returned **`'0h 1m 1s'`** for 61: it did the
  explicit bug but **did not implement the "drop leading zero units" requirement**
  stated in the docstring. The hidden oracle caught it.
- **Fable** committed *"Fix humanize() minutes math **and drop leading zero
  units**"* — it read and satisfied the *full* spec, including the in-docstring
  requirement, in one pass (at +$0.38 and +2 turns).

Both models **committed honestly** — Opus's subject accurately describes what it
did; neither over-claimed. The difference is **spec coverage**: Fable picked up a
requirement buried in the docstring that Opus, optimizing for the headline ask,
left on the floor. That is exactly the kind of edge — completeness on
under-specified / multi-part tasks — where a frontier model earns its keep, and it
shows up here as the single 5pp gap.

## 4. Recommendation — does the loops' Fable default earn its 2× cost?

**Not on routine loop work. Yes on frontier/long-horizon work.** The answer is
per-section, because the cost-justification genuinely differs:

| Work type (per the loops' actual usage) | Verdict | Why |
|---|---|---|
| **Routine code edits, bug-fixes, refactors, file/shell ops, scaffolding** (the bulk of every-loop steps) | **Route to Opus** | This suite *is* that work. Opus matched Fable on 19/20, at **half the $** and **1.5× faster**. The 2× premium bought a single extra solve on an easy task — a bad marginal rate. Halving the per-step cost of the high-volume work is the single biggest lever. |
| **Spec-heavy / multi-requirement tasks where completeness matters** | **Lean Fable** | `swe11_duration` is the in-miniature case: Fable caught a buried docstring requirement Opus dropped. On tasks where missing one sub-requirement fails the whole thing, Fable's completeness edge is worth more than 2×. |
| **Frontier-difficulty / long-horizon agentic work** | **Keep Fable** | This is where the *published* gap is large and this proxy says nothing: SWE-bench **Pro** 80% vs 69%, **FrontierCode** 29.3% vs 13.4%, AutomationBench 17.4% vs 12.9%. When Opus's pass-rate falls off a cliff and Fable's holds, "2× the cost of a *solved* task" beats "1× the cost of a *failed* one." |
| **Cybersecurity / bio / chem / model-distillation** | **Use Opus directly** | Fable's published path *falls back to Opus* on these via safety classifiers (20.9% of Terminal-Bench trials), so you pay Fable's 2× rate for Opus-class output. Skip the middleman. |

**Bottom line for the default.** A blanket Fable default **overpays** on the
high-frequency, low-difficulty steps that dominate loop volume — exactly the work
this audit measured, where Opus is the clear quality-per-dollar winner (19/20 @
0.5×). The defensible policy is a **difficulty-routed default**: Opus for routine
steps, Fable reserved for the frontier/long-horizon/spec-dense tasks where its
published lead is real and a failed cheap run costs more than a solved expensive
one. If a single static default must be chosen for cost reasons, **Opus is the
better value for typical loop work**; Fable's 2× is justified by *capability
headroom you only cash in on hard tasks*, which this suite is too easy to exhibit.

---

## 5. Reproduce

```bash
cd docs/_audits/fable-vs-opus-2026-06-09T22-34Z
PYTHONIOENCODING=utf-8 python run_bench.py \
    --models fable,opus --families swe,term --budget 20 --max-turns 30
PYTHONIOENCODING=utf-8 python analyze.py        # regenerates §1–§3 tables
```

Each run is independent (fresh throwaway git repo, fresh `claude -p`), so results
will vary run-to-run at the margin (model nondeterminism); the **2× cost ratio**
and the **near-saturation on this difficulty** are the stable findings, not the
exact identity of which one easy task (if any) a model misses.

## 6. Sources (published numbers used for context, not for the live scores)

- [Claude Fable 5: Review, Benchmarks and Pricing — llm-stats.com](https://llm-stats.com/blog/research/claude-fable-5-review)
- [Claude Fable 5 & Mythos 5: The Frontier, Split in Two — digitalapplied.com](https://www.digitalapplied.com/blog/claude-fable-5-mythos-5-release-benchmarks-2026)
- [Claude Fable 5 Benchmarks and Prompting Guide — agentpedia.codes](https://agentpedia.codes/blog/claude-fable-5-benchmark-prompting-guide)
- [SWE-bench Verified — vals.ai](https://www.vals.ai/benchmarks/swebench)

Published context (Fable 5 / Opus 4.8): SWE-bench Verified **95.0% / 88.6%**;
SWE-bench Pro **80.0% / 69.2%**; FrontierCode (Diamond) **29.3% / 13.4%**;
OSWorld-Verified **85.0% / 83.4%**; Terminal-Bench 2.1 **84.3%** (20.9% safety
fallback to Opus); pricing **$10/$50** vs **$5/$25** per Mtok.
