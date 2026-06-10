"""Driver for the Agent-Diff live ΔB run (docs/228→229). $-spending.

Usage: python benchmark/agentdiff/_run_delta_b.py [model] [sample] [out_dir]

Loads GEMINI_API_KEY from .env, puts the SDK + repo on path, drives run_delta_b, prints the
causal ΔB. Emits compact PROGRESS lines a Monitor can watch. The backend must be up on :8000.
"""
import os, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "benchmark"))
sys.path.insert(0, str(_REPO.parent / "agent-diff" / "sdk" / "agent-diff-python"))

for line in open(_REPO / ".env", encoding="utf-8"):
    line = line.strip()
    if line.startswith("GEMINI_API_KEY="):
        os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
assert os.environ.get("GEMINI_API_KEY"), "no GEMINI_API_KEY in .env"

from agentdiff.delta_b import run_delta_b

model = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash"
sample = int(sys.argv[2]) if len(sys.argv) > 2 else 24
out_dir = sys.argv[3] if len(sys.argv) > 3 else "benchmark/agentdiff/live_results"

print(f"PROGRESS run-start model={model} sample={sample} out={out_dir}", flush=True)
res = run_delta_b(model=model, split="test", sample=sample, out_dir=out_dir, max_iterations=25)
print(f"RESULT model={res.model} write_tasks={res.n_tasks} confident_write={res.n_confident_write} "
      f"overclaim={res.n_overclaim} blocked={res.n_blocked} "
      f"B_believe={res.b_success_believe} B_adjudicate={res.b_success_adjudicate} ΔB={res.delta_b}",
      flush=True)
if res.notes:
    print(f"NOTE {res.notes}", flush=True)
