#!/usr/bin/env bash
# _remote_run.sh — bootstrap + run the docs/322 P2 real-weights run on a fresh
# GPU VM (the PyTorch DLVM image: torch + CUDA already present). Not tracked as
# a rig module — a one-shot operator helper scp'd to the box. It installs the
# dos kernel from the payload, the GPU training deps, then runs both arms and
# prints the held-out metrics. Idempotent enough to re-run after a transient.
set -euo pipefail

WORK="${WORK:-$HOME/pp_p2}"
PAYLOAD="${PAYLOAD:-$HOME/payload.tar}"
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-Coder-1.5B-Instruct}"
EPOCHS="${EPOCHS:-3}"
KEVAL="${KEVAL:-3}"

echo "== unpack payload =="
rm -rf "$WORK/src" && mkdir -p "$WORK/src"
tar -xf "$PAYLOAD" -C "$WORK/src"

echo "== python + cuda check =="
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"

echo "== install dos kernel (from payload) + GPU deps =="
pip install -q -e "$WORK/src"
pip install -q "transformers>=4.44" "peft>=0.12" "trl>=0.10" "datasets>=2.20" "accelerate>=0.33"

echo "== run both arms (weights actually move) =="
cd "$WORK/src"
python -m benchmark.poisoned_pool.p2.run_p2 \
    --run-dir "$WORK/run" \
    --base-model "$BASE_MODEL" \
    --epochs "$EPOCHS" --k-eval "$KEVAL"

echo "== evidence written =="
ls -la "$WORK/run/RESULTS_run3.md" "$WORK/run/results_run3.json"
echo "== held-out metrics =="
python - "$WORK/run/results_run3.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for arm in ("S", "W"):
    a = d["arms"][arm]
    h = a["heldout"]
    print(f"Arm {arm}: overclaim={h['overclaim_rate']:.3f} "
          f"true_success={h['true_success_rate']:.3f} "
          f"train_poison={a['manifest_audit']['poison_frac']:.3f} "
          f"loss={a['train_summary'].get('train_loss')}")
PY
