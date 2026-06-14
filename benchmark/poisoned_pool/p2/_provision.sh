#!/usr/bin/env bash
# _provision.sh — find a zone with capacity and create the P2 GPU VM. One-shot
# operator helper (not a rig module). Sweeps GPU types (T4 cheapest first, then
# the project's V100/P100 quota) across many zones until one accepts the create.
# Echoes "PROVISIONED <zone> <gpu>" on success.
set -uo pipefail

PROJ="${PROJ:?set PROJ to your GCP project id}"
NAME="${NAME:-pp-p2}"
IMG_FAMILY="${IMG_FAMILY:-pytorch-2-9-cu129-ubuntu-2204-nvidia-580}"
IMG_PROJ="deeplearning-platform-release"

# (gpu_type, machine_type) pairs — T4 first (cheapest, n1), then V100/P100.
PAIRS=(
  "nvidia-tesla-t4:n1-standard-8"
  "nvidia-tesla-v100:n1-standard-8"
  "nvidia-tesla-p100:n1-standard-8"
)
ZONES=(
  us-central1-a us-central1-b us-central1-c us-central1-f
  us-east1-c us-east1-d us-east4-a us-east4-b us-east4-c
  us-west1-a us-west1-b us-west4-a us-west2-b
  europe-west4-a europe-west4-b europe-west1-b
  asia-east1-a asia-southeast1-b
)

for pair in "${PAIRS[@]}"; do
  gpu="${pair%%:*}"; mt="${pair##*:}"
  for z in "${ZONES[@]}"; do
    echo "== try $gpu in $z ($mt) =="
    out=$(gcloud compute instances create "$NAME" \
      --project="$PROJ" --zone="$z" --machine-type="$mt" \
      --accelerator="type=$gpu,count=1" \
      --image-family="$IMG_FAMILY" --image-project="$IMG_PROJ" \
      --maintenance-policy=TERMINATE --boot-disk-size=100GB \
      --metadata=install-nvidia-driver=True 2>&1)
    if echo "$out" | grep -qE "\b$NAME\b.*RUNNING|status.*RUNNING"; then
      echo "PROVISIONED $z $gpu"
      echo "$out" | tail -2
      exit 0
    fi
    reason=$(echo "$out" | grep -oE "ZONE_RESOURCE_POOL_EXHAUSTED|QUOTA_EXCEEDED|does not have enough resources|already exists|Quota .* exceeded" | head -1)
    echo "   -> ${reason:-$(echo "$out" | tail -1)}"
    if echo "$out" | grep -q "already exists"; then
      echo "PROVISIONED $z $gpu (pre-existing)"; exit 0
    fi
  done
done
echo "PROVISION_FAILED — no zone/gpu had capacity"
exit 1
