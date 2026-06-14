#!/usr/bin/env bash
# _drive_remote.sh — push the payload to a provisioned GPU VM, run the P2
# real-weights run, and pull the evidence back. One-shot operator helper.
#   ZONE=us-central1-c PROJ=<id> bash _drive_remote.sh
# Expects: the VM `pp-p2` RUNNING in $ZONE, /tmp/pp_payload/payload.tar local,
# and benchmark/poisoned_pool/p2/_remote_run.sh in the cwd repo.
set -uo pipefail

PROJ="${PROJ:?set PROJ}"
ZONE="${ZONE:?set ZONE}"
NAME="${NAME:-pp-p2}"
PAYLOAD_LOCAL="${PAYLOAD_LOCAL:-/tmp/pp_payload/payload.tar}"
OUT_LOCAL="${OUT_LOCAL:-/tmp/pp_payload}"
SSH="gcloud compute ssh $NAME --project=$PROJ --zone=$ZONE --tunnel-through-iap"
SCP="gcloud compute scp --project=$PROJ --zone=$ZONE --tunnel-through-iap"

echo "== wait for SSH (DLVM boot + CUDA setup can take 1-3 min) =="
for i in $(seq 1 30); do
  if $SSH --command="echo ready" 2>/dev/null | grep -q ready; then echo "ssh ok (try $i)"; break; fi
  sleep 10
done

echo "== push payload + remote runner =="
$SCP "$PAYLOAD_LOCAL" "$NAME:~/payload.tar"
$SCP benchmark/poisoned_pool/p2/_remote_run.sh "$NAME:~/_remote_run.sh"

echo "== run (LoRA SFT both arms + eval) — streams remote stdout =="
$SSH --command="BASE_MODEL='${BASE_MODEL:-Qwen/Qwen2.5-Coder-1.5B-Instruct}' EPOCHS='${EPOCHS:-3}' KEVAL='${KEVAL:-3}' bash ~/_remote_run.sh"

echo "== pull evidence back =="
mkdir -p "$OUT_LOCAL"
$SCP "$NAME:~/pp_p2/run/results_run3.json" "$OUT_LOCAL/results_run3.json"
$SCP "$NAME:~/pp_p2/run/RESULTS_run3.md" "$OUT_LOCAL/RESULTS_run3.md"
echo "PULLED $OUT_LOCAL/results_run3.json"
