# Durable rows schema — `replay_all_rows.{jsonl,csv}`

One flat row per `(model, run, task)`. Every field is a scalar — loads straight into
pandas / sqlite / a notebook with zero reshaping. Every number in `docs/157` §4 and
every figure in `viz.py` is recomputable from this file with **zero network** (the raw
trajectories under `_data/` are never needed once these rows exist).

Regenerate (offline, ~seconds once `_data/` is populated):

```bash
python -m benchmark.toolathlon.run_replay --all --no-download --by-model \
    --out  benchmark/toolathlon/_results/replay_all.json \
    --rows-out benchmark/toolathlon/_results/replay_all_rows
python -m benchmark.toolathlon.viz          # the 4 figures, from replay_all.json
```

The default run **normalizes** `tool_stream`'s `result_digest` (masks volatile env token
shapes — see `docs/157` §4). Pass `--raw-digest` to reproduce the raw lower-bound floor.

| Column | Type | Meaning |
|---|---|---|
| `model` | str | model family, run-suffix stripped (`gemini-2.5-flash_1` → `gemini-2.5-flash`) |
| `model_run` | str | the full `<model>_<run-index>` id (3 runs per model) |
| `task_name` | str | the Toolathlon task (e.g. `train-ticket-plan`) |
| `passed` | bool \| null | **the third-party oracle label** — `task_status.evaluation` from Toolathlon's own `evaluation/main.py`. `null` = the verifier produced no boolean (task errored / not run) → **excluded from precision**, never guessed. This is the un-forgeable rung DOS does not own. |
| `n_tool_steps` | int | length of the env-progress tool stream (local-noop tools like `claim_done` excluded) |
| `dangling_fired` | bool | `dos.dangling_intent` flagged this run (terminal narration admits open work, nothing env-authored acted after) |
| `dangling_cue` | str | the matched open-obligation marker text (`""` when quiet) |
| `tool_stream_state` | str | peak `dos.tool_stream` state: `ADVANCING` / `REPEATING` / `STALLED` |
| `tool_stream_run` | int | the peak consecutive-identical `(tool, args, result_digest)` run length |
| `tool_stream_fired` | bool | peak state reached the fire threshold (default `REPEATING`; `--ts-min-state STALLED` for the stricter bar) |
| `terminal_error_fired` | bool | the run STOPPED on an unresolved **structured env error** (`MCP error -3xxxx` / `isError:true` / `Traceback` / non-zero exit / permission-denied) in the closing window, never recovered (docs/158). The third byte-clean detector — the one that reaches the frontier. |
| `final_text_len` | int | length of the terminal narration (a quick completeness proxy) |

## Deriving the headline rates from the rows

```python
import pandas as pd
df = pd.read_csv("replay_all_rows.csv")
lab = df[df.passed.notna()]                      # drop the un-labeled rows
def grid(fired_col):
    f = lab[lab[fired_col]]
    return dict(
        fire_rate = len(f) / len(lab),
        precision = (~f.passed).mean(),           # of fires, fraction the oracle FAILED
        recall    = (~f.passed).sum() / (~lab.passed).sum(),
        base_fail = (~lab.passed).mean(),
    )
grid("dangling_fired"); grid("tool_stream_fired")
```

`precision − base_fail` is **lift** (the purchase signal: >0 ⇒ a fire is more likely a
real failure than a random run is).

## Companion aggregate + comparison artifacts (same dir)

- `replay_all.json` — the aggregate + per-model confusion grids (what `viz.py` reads).
- `replay_all_raw.json` / `replay_all_norm.json` — the **raw-vs-normalized** comparison
  (`--raw-digest` vs default). The normalizer's measured effect: `tool_stream` recall
  1.9%→2.9%, precision 84.9%→88.2%, lift +8.7→+12.0pp (recovers ~49 real repeats the raw
  floor under-counted); see `docs/157` §4.
