# 148 — Running tests and sims concurrently here: the safe-parallelism levels

> **Status:** operational note + measured findings (2026-06-04). Not a kernel design plan — a
> map of *which* concurrent runs are safe on this repo, *why* (what shared mutable state each
> contends on), and the one-line invocation per level. Grounded in a live `pytest -n auto`
> run, the gym/sim source, and the WAL/config isolation knobs — not reasoned in the abstract.
>
> **The frame is the kernel's own.** "Can these run at once?" is exactly the question
> `dos arbitrate` answers for agents — *are their write-regions disjoint?* The same lens
> applies to our own test/sim processes: two runs are safe to parallelize iff they do not
> write the same region of shared mutable state. The levels below are sorted by how disjoint
> their regions are — safest first.

---

## 0. The shared mutable state (what any two concurrent runs could collide on)

Four contended regions exist on this repo. Every safety rule below is "keep concurrent runs in
*different* copies of these," and every level is rated by how easily that holds:

| Region | What writes it | Collision if shared |
|---|---|---|
| **Process-global active config** (`_config._ACTIVE`) | `set_active()` / `default_config()` in 8 test files | one run's `set_active` is seen by another *in the same process* → wrong workspace verdict |
| **The dogfood WAL + home** (`./.dos/lane-journal.jsonl`, `~/.dos`) | `ensure_project_home`, lease writes, `dos journal` | interleaved appends corrupt the journal; the [unbounded-growth audit] already saw test fixtures polluting the REAL dogfood WAL |
| **The live `dos.toml`** | nothing at test time (read-only) — but a run that *writes* one (`dos init`) in cwd would | a scaffolded config bleeds into a concurrent run's `active()` |
| **The gym DB + MCP ports + Gemini key** (heavy level) | `live_ab.py` (`os.chdir(_GYM)`, mutates `seed_database_file` DBs via MCP), the Docker MCP servers on a fixed host port, the rate-limited API key | **the worst** — irreversible DB mutation on a shared file, one Docker port, one key's rate limit |

The good news, **measured**: the unit tests already isolate the first two (every stateful test
takes `tmp_path` and redirects `DISPATCH_HOME` into it), so process-per-worker parallelism is
safe out of the box. The bad news: the heavy level shares all of region 4 and is **not** safe
to fan out naively.

---

## Level 1 — the pure simulator (`run_ab.py`): embarrassingly parallel, zero shared state

`benchmark/enterpriseops/simulator.py` + `run_ab.py` are **pure and deterministic per seed**:
`run_split(seed, …)` builds tasks and agent draws from a single `random.Random(seed)`, runs the
*real* `arg_provenance.classify_call` (no I/O, no DB, no model), and the R0/R1 arms are paired on
the same per-task seed. **No shared mutable state at all** — different seeds touch nothing in
common.

- **Safe to run:** any number at once, one process per seed-range. The headline already loops
  seeds internally; to fan out, shard the seed set across processes.
- **Invocation (background, harness-tracked):**
  ```bash
  # shard 3 seed-ranges across 3 background processes — they share nothing
  python -m benchmark.enterpriseops.run_ab --tasks 690 --seeds 3            # one process, 3 seeds
  # or for a real sweep, run disjoint seed sets as separate background tasks
  ```
- **Why it's safe:** the simulator never writes a file, never calls a clock (`Date.now` is not
  in the path), never touches `.dos/` or the gym. It is the `classify_*` purity discipline
  paying off — the same property that makes the kernel verdicts replay-testable makes the sim
  trivially parallel. **This is the level to fan out hard** when calibrating thresholds.

---

## Level 2 — the unit suite (`pytest`): safe under `-n auto` (MEASURED), process-per-worker

`pytest-xdist 3.8.0` is installed, and **the full suite passes under `-n auto`**:

```
python -m pytest -n auto -q     →  2129 passed in 26.15s   (vs ~140s serial — ~5× on this box)
```

- **Why it's safe even though 8 files mutate `_config._ACTIVE`:** xdist runs each worker in a
  **separate OS process**, so the `_ACTIVE` global is per-worker, never shared. And every
  stateful test already takes `tmp_path` + `monkeypatch.setenv("DISPATCH_HOME", tmp/…)`, so no
  two workers write the same `.dos/` or `~/.dos`. The isolation the tests were written with
  (for correctness) doubles as parallel-safety.
- **The one caveat:** this safety is a *property of the current tests*, not enforced by a
  `conftest.py` (there is none). A *new* test that calls `set_active()` without save/restore, or
  writes to the **real** `./.dos` or a fixed path instead of `tmp_path`, would be flaky under
  `-n` (and is a latent bug serially too — it pollutes the dogfood WAL, the [unbounded-growth
  audit] finding). **Rule for new tests:** `tmp_path` for any workspace; `monkeypatch.setenv`
  `DISPATCH_HOME`/`DISPATCH_WORKSPACE` for any home/active state; never touch `./.dos`.
- **Invocation:**
  ```bash
  python -m pytest -n auto -q                    # the whole suite, parallel
  python -m pytest -n auto tests/test_tool_stream*.py -q   # one module's tests, parallel
  python -m pytest -p no:randomly -q             # (no randomly plugin here, but pin order if added)
  ```
  Use `-n auto` for the gate; use serial (`-q` alone) when you need deterministic ordering to
  debug a single failure, since xdist's distribution order is nondeterministic.

---

## Level 3 — concurrent `dos` CLI verbs against THIS repo: the arbiter is the safety mechanism

Running several `dos` verbs at once against the live repo (e.g. a `dos arbitrate` loop in one
shell, a `dos top` in another) is **the kernel's own use case** — and the kernel is built to make
it safe *by adjudicating it*, not by luck:

- **Read-only verbs** (`verify`, `doctor`, `decisions`, `plan --once`, `tool-stream-eval`,
  `intervention-eval`, `top` snapshot) take **no lease, write nothing** — any number run
  concurrently, always safe. Most of what you'd run in parallel is here.
- **Lease-taking verbs** (`arbitrate`, `lease-lane acquire`) **serialize through the WAL by
  design** — that *is* `dos`'s job. Two `arbitrate` calls for overlapping regions: the second is
  refused/redirected (the dogfood example in CLAUDE.md — you ask for `src`, get auto-picked
  `benchmark` because `src` was busy). So concurrent lease verbs are safe *because the arbiter
  refuses the collision*, not because you avoided it.
- **The one footgun:** a verb that **writes the WAL** (a real lease, `dos journal compact`) run
  concurrently with the **test suite** (if a test ever wrote the real `./.dos` — it shouldn't,
  per Level 2) would interleave. Keep the suite in `tmp_path` and this can't happen.
- **Invocation:** just run them; the arbiter is the concurrency control. The `DISPATCH_HOME`
  mutex (`home.py:128`, "hold the DOS_HOME write mutex for the duration of the block") serializes
  the central-index append, so even concurrent first-writes don't corrupt `~/.dos`.

---

## Level 4 — the LIVE gym A/B (`live_ab.py`): NOT safe to fan out naively (the heavy level)

This is where naive parallelism corrupts results. `live_ab.py`:

- **`os.chdir(_GYM)`** — changes the *process* working directory. Two live runs in one process is
  impossible; even in separate processes they fight over the gym tree.
- **Mutates `seed_database_file` DBs through the MCP servers** — "every action is permanent and
  irreversible" (the benchmark's whole premise). Two runs against the **same** gym DB file
  interleave irreversible writes → both results are garbage, and the hidden SQL verifier sees a
  mixed final state.
- **One Docker MCP host port** (8005-family) and **one rate-limited Gemini key** — fanning out N
  runs either port-collides or burns the shared rate limit, and the paper's pairing discipline
  (R0/R1 on the **same** injected seed) breaks if arms race.

**The safe way to run more than one live arm:**

1. **Serialize arms by default** — run R0, then R1, then the BLOCK arm, one after another against
   one gym clone. This is what the existing harness assumes; the paired-seed discipline *requires*
   the same injected mints across arms, which a serial run guarantees.
2. **If you must parallelize, give each run a fully disjoint copy of region 4:** its own **gym
   clone** (a separate `seed_database_file` tree — copy `gym_dbs` per run), its own **Docker MCP
   stack on a distinct host port**, and either a **separate API key** or a shared **rate-limiter**
   in front of the key. Without all three, the runs are not disjoint and the arbiter analogy
   says: refuse, don't race.
3. **The honest cheaper path:** parallelize at **Level 1** (the pure sim) for threshold
   calibration, and keep the live run **serial** — the live run's value is the *magnitude on real
   DB state*, which a corrupted concurrent run destroys. Spend the parallelism budget where it's
   free (the sim), pay the serial cost where it buys correctness (the gym).

---

## The one-paragraph rule

**Parallelism is safe exactly where the write-regions are disjoint — the same test `dos arbitrate`
applies to agents.** The pure simulator (Level 1) shares nothing → fan out freely. The unit suite
(Level 2) is isolated by `tmp_path` + process-per-worker → `pytest -n auto`, measured green in 26s.
Concurrent `dos` verbs (Level 3) are made safe *by the arbiter itself* (read-only verbs share
nothing; lease verbs serialize through the WAL). The live gym A/B (Level 4) shares an irreversible
DB, one Docker port, and one rate-limited key → **serialize by default**, and only parallelize with
a fully cloned gym + distinct port + separate/limited key. When unsure which level you're at, ask
the kernel's question: *what mutable region does this write, and is another run writing the same
one?*

**Cross-refs:** the arbiter / disjoint-region discipline this borrows = `dos arbitrate` + docs/89;
the WAL-pollution hazard at Level 2 = the unbounded-growth audit (test fixtures in the real
dogfood WAL); the pure-`classify` purity that makes Level 1 free = `arg_provenance` / `tool_stream`
/ `liveness` module docstrings; the live harness = `benchmark/enterpriseops/live_ab.py` +
`RESULTS.md`; the sim = `benchmark/enterpriseops/{simulator,run_ab}.py`.
