#!/bin/bash
# Run all pure-local Toolathlon tasks SEQUENTIALLY on local WSL containers (gemini-2.5-flash).
# CRLF-safe (strips \r), cleans stale containers between tasks, resilient to single-task failure.
# Run from your Toolathlon checkout; set DOS_REPO_HOST to your dos checkout path.
cd "${TOOLATHLON_HOME:?set TOOLATHLON_HOME to your Toolathlon checkout path}"
export PATH=$HOME/.local/bin:$PATH
export TOOLATHLON_OPENAI_BASE_URL='https://generativelanguage.googleapis.com/v1beta/openai/'
export TOOLATHLON_OPENAI_API_KEY="$1"
DOS="${DOS_REPO_HOST:?set DOS_REPO_HOST to your dos checkout path}"
OUT=$DOS/benchmark/toolathlon/_live/results/local_pure_batch
LIST=$DOS/benchmark/toolathlon/_live/tasklists/pure_local.txt
n=0; total=$(grep -c . "$LIST")
while IFS= read -r task; do
  task="${task%$'\r'}"            # strip trailing CR (Windows CRLF)
  task="$(echo -n "$task" | tr -d '[:space:]')"
  [ -z "$task" ] && continue
  n=$((n+1))
  echo "===== [$n/$total] $task ====="
  docker ps -aq --filter "name=alpha-toolathlon-finalpool-$task" | xargs -r docker rm -f 2>/dev/null
  rm -rf "$OUT/finalpool/$task" 2>/dev/null
  timeout 900 bash scripts/run_single_containerized.sh "finalpool/$task" testrun "$OUT" gemini-2.5-flash unified 100 >/tmp/tl_$task.log 2>&1
  rc=$?
  ev="$OUT/finalpool/$task/eval_res.json"
  if [ -f "$ev" ]; then
    pass=$(grep -o '"pass": *\(true\|false\)' "$ev" | head -1)
    echo "  [$task] DONE rc=$rc $pass"
  else
    echo "  [$task] NO_EVAL rc=$rc -- tail:"; tail -3 /tmp/tl_$task.log | sed "s/^/    /"
  fi
done < "$LIST"
echo "===== BATCH COMPLETE: $n tasks ====="
