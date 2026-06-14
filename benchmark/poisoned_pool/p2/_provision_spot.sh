#!/usr/bin/env bash
# _provision_spot.sh — same as _provision.sh but SPOT provisioning model. SPOT
# draws from a different capacity pool than on-demand, so it often succeeds when
# on-demand is ZONE_RESOURCE_POOL_EXHAUSTED. A SPOT VM can be preempted; for the
# ~10-min LoRA SFT job that is an acceptable risk (re-run on preemption). Only
# the zones with per-region GPU quota are tried (GPUS_ALL_REGIONS is 0, so other
# regions can't attempt regardless of capacity).
set -uo pipefail

PROJ="${PROJ:?set PROJ to your GCP project id}"
NAME="${NAME:-pp-p2}"
IMG_FAMILY="${IMG_FAMILY:-pytorch-2-9-cu129-ubuntu-2204-nvidia-580}"
IMG_PROJ="deeplearning-platform-release"

PAIRS=(
  "nvidia-tesla-t4:n1-standard-8"
  "nvidia-tesla-v100:n1-standard-8"
  "nvidia-tesla-p100:n1-standard-8"
  "nvidia-tesla-p4:n1-standard-8"
)
# Only regions with seeded per-region GPU quota (us-central1, us-east1, ...).
ZONES=(
  us-central1-a us-central1-b us-central1-c us-central1-f
  us-east1-c us-east1-d us-east4-a us-east4-b us-east4-c
  us-west1-a us-west1-b us-west2-b
)

for pair in "${PAIRS[@]}"; do
  gpu="${pair%%:*}"; mt="${pair##*:}"
  for z in "${ZONES[@]}"; do
    echo "== try SPOT $gpu in $z ($mt) =="
    out=$(gcloud compute instances create "$NAME" \
      --project="$PROJ" --zone="$z" --machine-type="$mt" \
      --accelerator="type=$gpu,count=1" \
      --provisioning-model=SPOT --instance-termination-action=DELETE \
      --image-family="$IMG_FAMILY" --image-project="$IMG_PROJ" \
      --maintenance-policy=TERMINATE --boot-disk-size=100GB \
      --metadata=install-nvidia-driver=True 2>&1)
    if echo "$out" | grep -qE "\b$NAME\b.*RUNNING|status.*RUNNING" || echo "$out" | grep -q "already exists"; then
      echo "PROVISIONED $z $gpu SPOT"; exit 0
    fi
    echo "   -> $(echo "$out" | grep -oE "ZONE_RESOURCE_POOL_EXHAUSTED|QUOTA_EXCEEDED|GPUS_ALL_REGIONS|does not have enough resources" | head -1)"
  done
done
echo "PROVISION_FAILED — SPOT pool also empty"
exit 1
