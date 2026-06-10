"""Run the writeadmit live A/B for ONE model over the wide natural sample (docs/231).

Usage: python _run_model.py <model> <out_dir> <budget_usd> [n_per_domain]

Drives `run_writeadmit(sample=N)` — the first N tasks/domain from the full tau2 sets
(default 30 → 60 tasks), resumable (cached rows skipped), budget-guarded. Loads the
GEMINI_API_KEY from .env. Emits a compact PROGRESS line per task so a Monitor can watch
it without the tau2 DEBUG firehose. This is the multi-model hardening docs/228 §5 asked
for ("More tasks + a second model would harden the base-rate").
"""
import os, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "src"))

for line in open(_REPO / ".env", encoding="utf-8"):
    line = line.strip()
    if line.startswith("GEMINI_API_KEY="):
        os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
assert os.environ.get("GEMINI_API_KEY"), "no GEMINI_API_KEY"

# silence the tau2 DEBUG firehose so the Monitor only sees our PROGRESS lines
try:
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
except Exception:
    pass

from benchmark.agentprocessbench.writeadmit.live_loop import run_writeadmit

model = sys.argv[1] if len(sys.argv) > 1 else "gemini/gemini-2.5-pro"
out_dir = sys.argv[2] if len(sys.argv) > 2 else "benchmark/agentprocessbench/writeadmit/live_results_m2_pro25"
budget = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
n_per = int(sys.argv[4]) if len(sys.argv) > 4 else 30

print(f"PROGRESS run-start model={model} sample={n_per}/domain budget=${budget} out={out_dir}", flush=True)
J = run_writeadmit(model=model, sample=n_per, out_dir=out_dir, budget_usd=budget,
                   max_steps=30, max_steps_retail=25)
print(f"PROGRESS run-done model={model} J={J}", flush=True)
