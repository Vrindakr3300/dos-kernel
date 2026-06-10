#!/bin/bash
# The lift-side A/B batch runner (docs/164 F0 tool_stream WARN). Runs OBSERVE then WARN arms over the
# loop-enriched pure-local subset, sequentially (the no-concurrent-Toolathlon-containers rule), with
# the container-side WARN wiring gated by DOS_WARN. Resumable: skips a task whose eval_res.json exists.
#
# Usage:  bash run_ab.sh <reps>   (default 2 — a directional pilot; bump to 3 for a CI)
# Run from your Toolathlon checkout inside WSL2.  Records every run; idempotent on re-invoke.
# Set these env vars first (no hardcoded machine paths):
#   GEMINI_API_KEY   — your Gemini key (read from the environment; never grep a .env)
#   DOS_REPO_HOST    — absolute path to your dos checkout (mounted into the container as /dos)
#   AB_ROOT (arg 3)  — output root
set -u  # NOT -e: one task failing must not abort the batch (log + continue)

export PATH="$HOME/.local/bin:$PATH"                       # the uv trap (see AB_RUN_RECIPE.md)
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8                 # cp1252 guard
export TOOLATHLON_OPENAI_BASE_URL='https://generativelanguage.googleapis.com/v1beta/openai/'
export TOOLATHLON_OPENAI_API_KEY="${GEMINI_API_KEY:-}"     # from the environment
export DOS_REPO_MOUNT=/dos                                 # the sitecustomize reads this

REPS="${1:-2}"
MODEL="${2:-gemini-2.5-pro}"                               # arg 2: target model (pro default; flash is more loop-prone)
AB_ROOT="${3:-./_ab}"                                      # arg 3: output root (per-model dir to avoid collision)
TASKS="academic-pdf-report arrange-workspace dietary-health logical-datasets-collection sales-accounting shopping-helper"
MAXSTEP=100                                                # match the replay (loops appeared at full horizon)
DOS="${DOS_REPO_HOST:?set DOS_REPO_HOST to your dos checkout path}"
RUNNER=scripts/run_single_containerized.sh

echo "=== lift-side A/B: $MODEL, $REPS reps x 2 arms x 6 tasks = $((REPS*2*6)) runs, out=$AB_ROOT ==="
[ -z "$TOOLATHLON_OPENAI_API_KEY" ] && { echo "FATAL: no GEMINI key"; exit 1; }

run_one() {  # arm run task
  local arm="$1" run="$2" task="$3"
  local out="$AB_ROOT/${arm}_run${run}"
  local done_marker="$out/finalpool/$task/eval_res.json"
  if [ -f "$done_marker" ]; then echo "  skip (done): $arm/$run/$task"; return; fi
  echo "  RUN: $arm run$run $task"
  bash "$RUNNER" "finalpool/$task" normal "$out" "$MODEL" unified "$MAXSTEP" >/dev/null 2>&1
  if [ -f "$done_marker" ]; then
    local p; p="$(python3 -c "import json;print(json.load(open('$done_marker')).get('pass'))" 2>/dev/null)"
    echo "    -> pass=$p"
  else
    echo "    -> NO RESULT (run failed; logged, continuing)"
  fi
}

for arm in observe warn; do
  if [ "$arm" = warn ]; then
    export DOS_WARN=1 DOS_REPO_HOST="$DOS"
    # the patched runner mounts $DOS->/dos + the sitecustomize + sets DOS_WARN in-container (no cp needed)
    echo "WARN arm: DOS_WARN=1 (runner injects the dos mount + sitecustomize)"
  else
    unset DOS_WARN
    echo "OBSERVE arm: stock harness"
  fi
  for run in $(seq 1 "$REPS"); do
    for t in $TASKS; do run_one "$arm" "$run" "$t"; done
  done
done

echo "=== batch done. score with: python -m benchmark.toolathlon.live_adapter $AB_ROOT/observe_run* $AB_ROOT/warn_run* ==="
