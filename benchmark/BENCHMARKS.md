# Running the benchmarks — one command for all six

> **TL;DR.** `python -m benchmark._run list` shows every benchmark, its arms,
> cost ($0 vs paid), and prereqs. `python -m benchmark._run run <bench>` runs the
> cheapest free arm. `python -m benchmark._run preflight <bench> --arm <arm>`
> checks a paid arm's prereqs (and loads the Gemini key from `.env`) *before* you
> spend. `python -m benchmark._run status` tells you which committed numbers are
> stale vs the current kernel SHA.

This is the standardized runner over the six independent research programs
inventoried in [`_BENCH_MAP.md`](_BENCH_MAP.md). Before it, each benchmark had
its own run ritual, its own `DOS_*` env soup, and its own results convention
(`RESULTS.md` / `RESULTS.txt` / `_results/` / ten `live_results*/` dirs). The
runner unifies the *operation* without touching the *measurements*: it shells the
existing entrypoints — it never reimplements a benchmark or changes a scorer.

## The four verbs

```bash
python -m benchmark._run list                          # the inventory
python -m benchmark._run preflight <bench> [--arm A]   # check prereqs, load .env, fail loud+early
python -m benchmark._run run <bench> [--arm A] [--set k=v ...] [--dry-run]
python -m benchmark._run status                        # freshness vs HEAD
```

- **A named ARM, never raw env.** Each arm (`none`/`warn`/`block`/`rewind`/
  `restart`/… and toolathlon's `observe`/`warn_stream`) resolves to its `DOS_*`
  environment through the **single shared vocabulary** in [`_arms.py`](_arms.py).
  Every `DOS_*` knob is popped before an arm's env is applied (the docs/152
  no-leak rule). You never set `DOS_CONSULT`/`DOS_INTERVENTION`/`DOS_WARN` by hand.
  `live_ab.py` now *imports* that same vocabulary, so the live runner and this
  runner can never drift (pinned by `tests/test_bench_layering.py`).
- **`--set k=v`** overrides an entrypoint's `{token}` defaults (e.g.
  `--set tasks=12`, `--set "arms=none warn block"`, `--set efforts=6`).
- **`--dry-run`** resolves the argv + runs preflight but does not execute — use it
  to see exactly what a paid run will spend on.

## Free ($0) vs paid

Every $0 arm is runnable right now with no key:

```bash
python -m benchmark._run run toolathlon  --arm replay_smoke --set limit=20   # cached replay
python -m benchmark._run run fleet_horizon                                   # simulator (real kernel)
python -m benchmark._run run fleetforge                                      # simulator
python -m benchmark._run run agenthallu        --arm score                   # offline SSOT (dataset sibling-clone)
python -m benchmark._run run agentprocessbench --arm score                   # offline SSOT
python -m benchmark._run run enterpriseops     --arm theories                # Tier-0 $0 sweep
```

The paid arms call a real model and need Docker + a Gemini key + (for
enterpriseops) the cloned gym. The key lives in repo-root `.env`; **the runner's
preflight loads it** (nothing else does — see `_BENCH_MAP.md`). Always preflight first:

```bash
python -m benchmark._run preflight enterpriseops --arm live
#   [OK ] docker daemon
#   [OK ] GEMINI_API_KEY (set)        <- loaded from .env by the preflight
#   [OK ] benchmark/enterpriseops/enterpriseops-gym
#   READY
python -m benchmark._run run enterpriseops --arm live --set tasks=3 --set "arms=none warn block"
```

If a prereq is missing, preflight prints the exact fix command and the run
refuses (exit 2) — it never spends against a missing prereq.

## Freshness — which committed numbers are stale

Every `run` stamps `benchmark/<bench>/_runs/run_<sha>_<entry>.json` (gitignored)
recording the kernel version + git SHA the run was at. `status` reads them back:

```bash
python -m benchmark._run status
#   * fleet_horizon  — last cell @ 8148378 exit=0  [fresh]
#   * enterpriseops  — no local run  (committed summary exists)
```

`[STALE]` means your last local run was at an older SHA than HEAD — the kernel has
changed since, so re-run before trusting the number. This is the honest
fresh-vs-stale signal the scattered `RESULTS.*` files could not give.

## Where this lives (layering)

The runner (`_run.py`), the registry (`registry.py`), and the arm vocabulary
(`_arms.py`) live under `benchmark/` — the **consumer** side. They `import dos`
only to stamp the kernel version, and they launch every benchmark by subprocess;
nothing under `src/dos/*.py` imports the benchmark suite (the one-way arrow, same
as the MCP server and the release tooling). `tests/test_bench_layering.py` pins
it. Adding a benchmark or an arm = an edit here, never a kernel edit.
