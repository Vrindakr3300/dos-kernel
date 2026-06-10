"""Single-task live smoke that the docs/231 pro fix works.

gemini-2.5-pro REJECTS reasoning_effort="disable" ("Budget 0 is invalid. This model
only works in thinking mode."), so the docs/228 second-model attempt errored on all 60
tasks. _agent_llm_args now sends "low" to -pro models. This drives ONE live pro airline
task through the SAME _run_one_live the batch uses and asserts it returns a db_match row
(not a BadRequestError). Cost ~$0.05-0.15. Gate before the full pro batch.
"""
import os, sys, time
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

from benchmark.agentprocessbench.writeadmit.live_loop import _run_one_live, _agent_llm_args

MODEL = "gemini/gemini-2.5-pro"
print(f"reasoning_effort for {MODEL}: {_agent_llm_args(MODEL)['reasoning_effort']}  (must be 'low')")
print(f"running ONE live {MODEL} airline task 0 ...")
t0 = time.time()
row, _ = _run_one_live("airline", "0", model=MODEL, max_steps=20, seed=0)
dt = time.time() - t0
print(f"\n=== done in {dt:.0f}s ===")
err = row.get("error")
if err:
    print("FAIL — task errored:", err[:200])
    raise SystemExit(1)
print("OK — pro task ran without crash.")
print("  db_match       =", row.get("db_match"))
print("  reward         =", row.get("reward"))
print("  confident_write=", row.get("confident_write"))
print("  verdict        =", row.get("verdict"))
print("  agent_cost     =", row.get("agent_cost"))
print("  answer excerpt :", str(row.get("answer_excerpt"))[:160])
