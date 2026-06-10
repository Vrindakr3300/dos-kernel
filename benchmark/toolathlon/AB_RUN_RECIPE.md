# The lift-side A/B — turnkey run recipe (gemini-2.5-pro, OBSERVE vs WARN)

> **Goal:** measure the FIX side of DOS on a third-party-scored benchmark — does a `tool_stream`
> WARN re-surface convert a doomed loop fail→pass? This is the number the $0 replay (docs/157) and
> the conversion-ceiling (docs/158) could only *bound*. Everything below the "RUN" line is BUILT and
> tested at $0; the run itself is the spend (~$10-25 of Gemini, local Docker / WSL2).

## What is already built + proven ($0, committed)

| piece | where | commit | proof |
|---|---|---|---|
| conversion-ceiling gate | `conversion_ceiling.py` | `4622cb9` | corpus ceiling +2.40pp; frontier 0 recoverable |
| live WARN arm | `warn_patch.py` | `974a799` | 6 byte-parity tests (live verdict == offline replay) |
| live scorer | `live_adapter.py` | (prior) | folds the SAME detectors over a live run dir |
| enriched tasklist | `_live/tasklists/pro_loop_enriched.txt` | this | 6 tasks where pro looped on tool_stream AND are pure-local |

**Target = `gemini-2.5-pro`** (12.1% base → lift is *measurable*; grok-4 was ideal but is xAI =
unreachable with our keys). **Subset = 6 loop-enriched pure-local tasks** (`academic-pdf-report`,
`arrange-workspace`, `dietary-health`, `logical-datasets-collection`, `sales-accounting`,
`shopping-helper`) — chosen because gemini-2.5-pro fired `tool_stream` REPEATING/STALLED on each in
the frozen replay, so a WARN has reach on *every* task (fire-rate ~100% by construction, the cure for
the docs/161 starved-subset). **Honest boundary: N=6 × 3 runs is a DIRECTIONAL pilot, not a powered
A/B** — report the conversion rate + a wide CI, never a tight lift claim. Scale to the 12-task
external set only if the pilot conversion is non-zero.

## The A/B design

| arm | harness | env | tasks | runs |
|---|---|---|---|---|
| OBSERVE (control) | stock | `DOS_WARN` unset | the 6 | 3 |
| WARN (treatment) | + warn_patch | `DOS_WARN=1` | the SAME 6, same seeds | 3 |

The **only** delta is the `DOS_WARN` flag. `warn_patch.apply_warn_patch()` is a no-op when the flag is
unset (so even a shared import can't confound OBSERVE). Lift = WARN pass-rate − OBSERVE pass-rate;
the real deliverable is the **conversion rate** = of WARN-arm runs where tool_stream fired, the
fraction that flipped fail→pass (the number the frozen replay structurally could not produce).

## RUN (WSL2 + Docker — the WARN arm cannot run on the public service)

**The architecture (verified):** the proven local path (docs/161 §3b) is
`scripts/run_single_containerized.sh <domain/task> ...`, which runs **`uv run main.py ...` INSIDE the
task container** (run_single_containerized.sh:466). `main.py:11` is exactly where the monkey-patches
load (`from utils.openai_agents_monkey_patch.custom_run_impl import *`). So the agent loop — and the
WARN patch — run **container-side**, not host-side. (`eval_client.py --mode public` is a *different*
path: it submits to a remote eval SERVER that runs a STOCK harness → cannot inject WARN. Use the
containerized runner, not eval_client, for the A/B.)

Run inside **WSL2 (Ubuntu 24.04)** (shares the Docker daemon; `lockon0927/toolathlon-task-image:1016beta`
already pulled). Traps from docs/161 §3b: **strip CRLF** from the tasklist (`sed -i 's/\r$//'`);
**never run two Toolathlon containers concurrently** (name/port collision — sequential only);
provision a real `serper_api_key` in `configs/token_key_session.py` (else web-search tasks infra-error
— not relevant to these 6 pure-local tasks, but check).

**⚠ THE `uv` PATH TRAP (cost a wasted smoke 2026-06-05):** `run_single_containerized.sh` calls
`uv run python ...` and runs as **root** in WSL with `uv` at `/root/.local/bin/uv`. A non-login
`wsl -e bash -c "..."` shell does NOT load `~/.profile`, so `uv` is not on PATH → the
`CONTAINER_RUNTIME=$(uv run python -c ...)` block fails, and with the script's `set -e` it **exits
SILENTLY right after the "Dump path:" echo with exit 0** (no container, no error printed, no
artifacts). The "exit 0 + empty output dir" is the signature. FIX: prepend
`export PATH="$HOME/.local/bin:$PATH"` to every WSL invocation (or use `bash -lc`). Always confirm an
artifact (`traj_log.json` / `eval_res.json`) was produced — exit 0 alone does NOT mean it ran.

The model key + endpoint reach the container via host env vars the runner propagates:
`export TOOLATHLON_OPENAI_BASE_URL='https://generativelanguage.googleapis.com/v1beta/openai/'` +
`export TOOLATHLON_OPENAI_API_KEY="$GEMINI_API_KEY"` (read the key from your environment).
Runner arg order: `run_single_containerized.sh <domain/task> <runmode> <dump_path> <modelname>
[provider=unified] [maxstep] ...` — all 6 A/B tasks live under the `finalpool` domain
(`finalpool/dietary-health` etc.).

### 0. the WARN wiring (CONTAINER-side — the key correction)

`main.py` runs inside the container via `uv run`. The DOS WARN patch must be importable THERE and
applied at interpreter start. Two clean options, neither edits Toolathlon's tracked source:
  * **(a) sitecustomize in the container's CWD.** The container runs `uv run main.py` from
    `/workspace` (the mounted Toolathlon root). Drop a `sitecustomize.py` at the Toolathlon root that,
    gated by `DOS_WARN`, adds the mounted dos repo to `sys.path` and calls `apply_warn_patch()`. It
    must reach the dos repo — mount it (`-v $DOS_REPO_HOST:/dos`) and `sys.path.insert(0,"/dos")`.
    Requires the runner to (i) pass `DOS_WARN` into the container env and (ii) add the `-v` mount —
    both are edits to a SCRIPT invocation, not to harness source.
  * **(b) bake a 2-line conditional import** into the container by appending to `main.py` ONLY in the
    WARN-arm image (a derived image `FROM lockon0927/...:1016beta` + a `COPY warn_patch.py` +
    sitecustomize). Cleaner reproducibility, more setup.

Pick (a) for the pilot. **PYTHONPATH (verified): `dos` is under `src/`, `benchmark.toolathlon` is at
the repo root — so the patch needs BOTH on the path:** `sys.path.insert(0,"/dos/src")` (for `dos`) +
`sys.path.insert(0,"/dos")` (for `benchmark.toolathlon`). Mount `-v $DOS_REPO_HOST:/dos`.

**Spend gate — VERIFIED PASS on the host WSL venv 2026-06-05** (must re-verify IN-CONTAINER before
the run): with `DOS_WARN=1` and both paths set,
```
python -c "from benchmark.toolathlon.warn_patch import apply_warn_patch; apply_warn_patch();
from agents._run_impl import RunImpl;
print(getattr(RunImpl.execute_tools_and_side_effects,'_dos_warn_wrapped',False))"
```
prints `True` (confirmed against the real `agents` SDK in `$TOOLATHLON_HOME/.venv`). If it
prints `False`, the patch did NOT install and the WARN arm would silently equal OBSERVE — **DO NOT
SPEND** until it prints True.

### 1. preflight ($0, in WSL)
```bash
# GEMINI_API_KEY must already be exported in your environment (do NOT grep a private .env)
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8           # cp1252 guard
sed -i 's/\r$//' "$DOS_REPO_HOST"/benchmark/toolathlon/_live/tasklists/pro_loop_enriched.txt
# probe gemini-2.5-pro reachability (one cheap chat/completions call) before spending
# confirm the container-side patch install verification above prints True
```

### 2. both arms (×3 each) — the only delta is DOS_WARN in the container env
```bash
cd $TOOLATHLON_HOME
# resolve each bare task name to its <domain>/<task> (eval_client/run_single both need the domain);
# domain = the finalpool subdir the task lives in.
TASKS="academic-pdf-report arrange-workspace dietary-health logical-datasets-collection sales-accounting shopping-helper"
for arm in observe warn; do
  [ "$arm" = warn ] && export DOS_WARN=1 || unset DOS_WARN
  for run in 1 2 3; do
    for t in $TASKS; do
      # one container at a time (sequential); pass DOS_WARN + the dos mount into the container
      bash scripts/run_single_containerized.sh "<domain>/$t" normal "./_ab/${arm}_run${run}" \
           gemini-2.5-pro unified 100
    done
  done
done
```
(Add `DOS_WARN` to the container `-e` env and `-v $DOS_REPO_HOST:/dos` to the `run_single_containerized.sh`
`CONTAINER_CMD` — the one script-invocation edit option (a) needs.)

### 3. score both arms (dos side, $0)
```bash
cd "$DOS_REPO_HOST"
python -m benchmark.toolathlon.live_adapter \
  $TOOLATHLON_HOME/_ab/observe_run1 ... $TOOLATHLON_HOME/_ab/warn_run3
# diff: paired pass-rate per task (McNemar / paired bootstrap CI) + the conversion rate
# (of WARN runs where tool_stream fired, fraction that flipped fail->pass — the real deliverable).
```

## Expected outcome (stated up front, per the EOG record)

A small lift on this looping subset, or ~null (a stuck model often loops on the exact step it cannot
form, even when reminded). **Either publishes:** lift>0 = "a measured DOS conversion on a benchmark we
don't score"; lift~0 = "DETECT not FIX, confirmed live — the ceiling is the ceiling." Report the
strong-model null and the wide N=6 CI as findings, never failures. The flag-gated, byte-parity-proven
mechanism is the durable contribution regardless of the number.
