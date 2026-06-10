# 275 — Making the MCP server fast: killing the per-call subprocess + the env probe

> **Status:** MEASURED + SHIPPED (2026-06-09). The `dos_mcp` server felt slow. It
> was — not in the FastMCP transport, but in two places the syscalls reached for on
> every tool call: (1) the truth syscall (`dos_verify`/`dos_commit_audit`) shelled
> out to a **whole second Python interpreter** (`python -m dos.phase_shipped
> --batch`) that re-ran `import dos` just to grep git; and (2) **every** tool call
> rebuilt the workspace `SubstrateConfig`, which probed the runtime `EnvPrint` — a
> `git rev-parse HEAD` subprocess + (first call) a Windows WMI platform query — for
> a field **no MCP tool reads**. A third, smaller leak: `import dos` itself forced
> the full config build (WMI + git) at import because `lane_journal` resolved its
> journal path eagerly.
>
> **Four surgical fixes, no behavior change, suite green.** Measured on this machine:
>
> | Operation | Before | After | Speedup |
> |---|---|---|---|
> | `import dos` (cold start) | ~125 ms | ~73 ms | **1.7×** |
> | config build (per tool call) | ~15.3 ms | ~3.1 ms | **4.9×** |
> | `dos_arbitrate` / `dos_refuse_reasons` / `dos_doctor` end-to-end | ~18 ms | ~3.1 ms | **~6×** |
> | `dos_verify` end-to-end | ~251 ms | ~71 ms | **3.5×** |
>
> The pure-verdict tools (no git) are now bound only by TOML parsing; the git-bound
> tools are bound only by the two irreducible `git log` reads the grep rung needs.
> The headline win is structural: a long-lived server no longer pays a Python
> interpreter cold-start **per `verify`**, and no longer re-probes a constant runtime
> fact on every call.

## The dogfood rule, applied to performance

This is the docs/270 lesson again from the other side. There, the claim "the Go hook
fast-path erases the cold-start" was narration until measured. Here, "the MCP server
seems slow" was a complaint until profiled. The fix in both cases is the same
discipline the repo runs on everything else: **let a witness, not a guess, say where
the time goes.** A profiler (`-X importtime`, `cProfile`) is the verify() of latency.

Every number below is from `cProfile` / `time.perf_counter` on this machine
(win32-AMD64, CPython 3.13), not from reading the code and estimating.

## The diagnosis

A `dos_verify` MCP tool call was ~251 ms. The profiler put the cost in three nested
places:

1. **`oracle.is_shipped` → `default_grep_fallback_batch` shelled out to a second
   interpreter (~233 ms).** The grep rung ran `[sys.executable, "-m",
   "dos.phase_shipped", "--batch"]` in a subprocess. That child has to *start a
   Python interpreter* and *`import dos`* (the docs/270 measurement: `import dos.cli`
   alone is ~153 ms; `import dos` here is ~73–125 ms) before it runs a single line of
   `git log`. So ~170 ms of the 233 ms was pure startup overhead the parent process —
   which **already has `dos.phase_shipped` imported** — paid for nothing. The actual
   git work is only ~60 ms.

2. **Every tool call rebuilt the config, probing an `EnvPrint` no tool reads
   (~13 ms/call).** `_load_workspace_config` → `default_config` → `gather_env_print()`
   ran a `git rev-parse HEAD` subprocess (~11 ms) plus, on the first call,
   `platform.machine()` (~28 ms, a WMI query on Windows; CPython caches it after). The
   `EnvPrint` (kernel version / SHA / OS / tool versions) is consumed only by the CLI
   `doctor` surface and the intent-ledger stamp — **never by any `dos_mcp` tool**. It
   was built and thrown away on every call.

3. **`import dos` forced the full config build at import (~40 ms once).**
   `lane_journal.py` resolved a module-level `JOURNAL_PATH = Path(... or
   _default_journal_path())`, and `_default_journal_path()` calls `config.active()` →
   `default_config()` → the same WMI + git probe — firing it the instant anything
   imported `dos`, for a path almost nothing reads as a value (the live functions all
   re-resolve via `_journal_path()` per call).

The unifying observation: **the runtime `EnvPrint` and a commit's touched-file set
are constants for a process's lifetime** (the kernel SHA can't move under a running
server; a git commit is immutable by construction), yet both were recomputed
per-call; and **the grep rung's subprocess re-imported the very package that called
it.**

## The four fixes

All four preserve behavior exactly — the verdicts are byte-identical, the only change
is *when* and *how often* the work runs.

### 1. Run the grep rung IN-PROCESS (`oracle.py`)

`default_grep_fallback_batch` now calls `dos.phase_shipped`'s internals directly —
`_build_log_cache()` once, then per pair `_check_phase_with_cache` → `_consult_plan_body`
→ `_apply_filepath_backstop`, the **same functions in the same order** the child's
`main()` `--batch` branch runs. The package is already imported in this interpreter,
so there is nothing to gain from a subprocess and ~170 ms to lose. The stamp
convention the subprocess needed an `ENV_STAMP_CONVENTION` env hand-off for is simply
**already active** in-process (the `is_shipped(cfg=…)` branch `set_active`s it before
calling). The out-of-process path is kept as a fallback (forced by
`DOS_ORACLE_GREP_SUBPROCESS=1`) so a hypothetical rung-import failure degrades to the
previously-shipped behavior rather than a wrong answer. Verified byte-identical:
in-process and subprocess produce the same `shipped`/`source`/`sha`/`rung` on every
pair tried. **~233 ms → ~62 ms.**

### 2. Memoize `gather_env_print()` per process (`env_print.py`)

The print describes the running kernel and is constant for the process; the module
docstring already said "gathered ONCE at the build boundary." Now that is literally
true: a per-process memo keyed on `(tools, kernel_root)` means the `git rev-parse`
subprocess + platform probe run once, every later gather is free. Helps **every**
caller, the CLI included. **~13 ms → ~0 ms after the first call.**

### 3. Let a caller skip the `EnvPrint` entirely (`config.py` + `server.py`)

`default_config` / `job_config` / `load_workspace_config` take a new `gather_env: bool
= True` (default unchanged, so the CLI/doctor/intent-ledger are byte-identical). The
MCP server's `_load_workspace_config` passes `gather_env=False` — it reads no
`cfg.env`, so `env` stays `None` (the documented "not recorded" state every consumer
already handles). Belt-and-suspenders with fix 2: the memo makes the cost ~0 after the
first call, and `gather_env=False` removes even the first call from the path.

### 4. Resolve `lane_journal.JOURNAL_PATH` lazily (`lane_journal.py`)

The eager module-level `JOURNAL_PATH` is now a PEP 562 module `__getattr__` that
resolves on first *access* (via the same `_journal_path()` the live functions use),
not at import. `import dos` no longer fires the WMI + git probe. The name stays
exported for back-compat (`from dos.lane_journal import *`, the host re-export shims).
**~125 ms → ~73 ms cold start.**

### Bonus — memoize a commit's touched-file set (`oracle.py`)

A single `is_shipped` on a `shipped=True` grep verdict fetched the same SHA's
footprint twice (the #399 release-bump post-filter, then `_demote_if_false_positive`),
each a `git show` subprocess; a fan-out re-hit the same release-bump SHAs repeatedly.
`_git_touched_files` now memoizes per `(workspace-root, sha)`. A git SHA is
content-addressed — immutable — so this is the safest possible cache (no staleness
concern); `None` (transient git failure) is never cached. **is_shipped ~92 ms → ~64 ms.**

## Why this is safe (the soundness argument)

The repo's whole thesis is that a referee must not believe a forgeable self-report.
None of these caches touch a verdict's *trust* properties:

- The `EnvPrint` and the touched-file set are **environment-authored facts** (git, the
  platform), not agent claims. Caching a fact the agent cannot forge changes latency,
  not trust.
- The in-process grep rung runs the **identical adjudication code** as the subprocess
  — same git history, same matchers, same backstops, same forgeability `source`
  grading (`grep-subject` vs `grep-artifact`). The process boundary was never part of
  the verdict; it was an implementation detail with a 170 ms tax.
- A git SHA's footprint is immutable by the content-addressing guarantee, so the SHA
  memo can never serve stale content (a rewritten history yields *new* SHAs).
- Every cache is per-process and (where a workspace is involved) keyed on the
  workspace root, so a long-lived server fielding multiple workspaces never crosses
  their histories.

## Self-testing — how a regression is caught

A performance fix that isn't pinned rots: someone reverts to the subprocess "to be
safe," or breaks the env memo, and the suite stays green because nothing checked. So
the change ships with tests that fail if the fast path regresses — and each was
**mutation-verified** (the regression injected, the test confirmed to fail, the code
restored) so the guard is real, not vacuous coverage:

- **`tests/test_oracle_grep_in_process.py`** (new) — pins the load-bearing claim:
  the in-process rung and the (kept-as-fallback) subprocess rung return
  **byte-identical** `shipped`/`source`/`sha`/`rung` on a real repo, driven through
  `oracle.is_shipped(cfg=…)`. The structural guard `test_default_grep_spawns_no_subprocess`
  spies on `oracle.subprocess.run` and asserts a default grep makes **zero**
  `python -m dos.phase_shipped` spawns — a deterministic check, no flaky millisecond
  budget. Its complement pins that `DOS_ORACLE_GREP_SUBPROCESS=1` *does* spawn the
  child (the fallback stays reachable, not dead code). Two more pin the touched-file
  memo (consistent + caller-isolated; an unresolvable SHA is uncached).
- **`tests/test_env_print.py`** (extended) — `TestEnvPrintMemoizedPerProcess` pins
  the memo returns the same object and a cache hit never re-runs `_kernel_sha`
  (instrument it to explode, prove a hit doesn't reach it). `TestGatherEnvFlagSkipsTheProbe`
  pins `gather_env=False → env=None` for all three builders and that the builder
  makes **no** `gather_env_print` call at all (make the gatherer explode, prove the
  build still succeeds).
- **`tests/test_lane_journal.py`** (extended) — pins `JOURNAL_PATH` is **not**
  materialized in the module dict at import (PEP 562 lazy), still resolves to
  `_journal_path()` on access, and — in a subprocess — that a fresh `import dos`
  leaves the EnvPrint memo **empty** (the cross-process proof the eager-build is
  gone).
- **`tests/test_mcp_server.py`** (extended) — the end-to-end contract: the server's
  config build skips the env probe (`cfg.env is None`), and a real `dos_verify` tool
  call spawns no python child for the grep rung.
- **`scripts/bench_mcp.py`** (new) — the repeatable on-demand proof (the docs/270
  `bench_hook_e2e.py` pattern): times the real server's per-tool-call latency and
  **gates on the in-process==subprocess equivalence** (exit 1 if a verdict ever
  diverges). Run `python scripts/bench_mcp.py` (add `--json` for a CI ratchet).

## What was NOT changed

The ~60 ms floor on `dos_verify` is the two `git log` reads the grep rung needs
(`--oneline -4000` + `-50 --format=…`). That is genuine work against the target
repo's history; it is the irreducible cost of answering "did this ship?" from git
rather than from narration. Lowering it further would mean a durable ship index (the
docs/82 `_consult_plan_body` direction), which is a different lever than "stop doing
redundant work," and out of scope here. The ~3 ms floor on the pure-verdict tools is
`tomllib` re-parsing `dos.toml` ~14× per config build (once per `load_from_toml`
loader); collapsing that to a single parse is a clean follow-up but already well under
the perception threshold.
