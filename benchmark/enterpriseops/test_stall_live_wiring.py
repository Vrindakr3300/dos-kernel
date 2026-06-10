"""test_stall_live_wiring.py — the STALLED trigger fires inside the REAL execute() loop (docs/176 §6.1).

The standalone + integration tests pin the gate and the enactment; this proves the LIVE WIRING:
that with DOS_STALL=1, the actual `DosReactOrchestrator.execute()` loop — the real control flow
plus the call-site block added to dos_react.py — detects a byte-identical tool stall mid-run and
SUBTRACTS to the pre-stall anchor. It drives the real orchestrator (the gym base class) with a
MOCK LLM that re-issues one stalling tool call and a MOCK tool executor returning byte-identical
results, so no live Gemini / no MCP container is needed.

THE IMPORT WRINKLE (why this runs in a subprocess). The gym ships a top-level package named
`benchmark`, which COLLIDES with this repo's own `benchmark/` package under pytest's rootdir
collection (pytest caches the repo's `benchmark` in sys.modules, shadowing the gym's
`benchmark.mcp_client` that `orchestrators.react` imports). Rather than fight pytest's import
machinery (and risk corrupting sibling tests' imports), the actual orchestrator run happens in a
clean SUBPROCESS with a gym-root-first sys.path — exactly how live_ab.py runs. The pytest test
shells that subprocess and asserts its verdict; `python test_stall_live_wiring.py` runs it
directly. Skipped (not failed) when the gym is absent — a kernel-only checkout stays green.

Run: PYTHONPATH=../../src python -m pytest test_stall_live_wiring.py -q
 or: python test_stall_live_wiring.py        # direct, prints the verdict
"""
from __future__ import annotations

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GYM = os.path.join(_HERE, "enterpriseops-gym")


# ---------------------------------------------------------------------------
# The actual orchestrator drive — run in a clean process (no pytest rootdir, so the gym's
# `benchmark` package resolves). Returns 0 + prints PASS on success, nonzero on failure.
# ---------------------------------------------------------------------------
_DRIVER = r'''
import sys, os, asyncio
_HERE = __HERE__
sys.path.insert(0, os.path.join(_HERE, "..", "..", "src"))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "enterpriseops-gym"))  # gym root FIRST
os.environ["DOS_STALL"] = "1"
for _k in ("DOS_CONSULT", "DOS_REWIND", "DOS_REWIND_NATURAL"):
    os.environ.pop(_k, None)

from langchain_core.messages import AIMessage
from dos_react import make_dos_react_orchestrator
Cls = make_dos_react_orchestrator()

class MockLLM:
    def __init__(self): self.calls = 0
    async def invoke_with_tools(self, messages, tools):
        self.calls += 1
        for m in messages:
            c = getattr(m, "content", "")
            if isinstance(c, str) and c.startswith("[DOS rewind]"):
                return AIMessage(content="done", tool_calls=[])   # recover after the rewind
        if self.calls == 1:  # a GOOD verified call first → the pre-stall anchor
            return AIMessage(content="lookup",
                             tool_calls=[{"name": "find_user", "args": {"name": "Ada"}, "id": "g1"}])
        return AIMessage(content="reading",   # then re-issue the SAME stalling call
                         tool_calls=[{"name": "read_row", "args": {"id": "ROW_X"}, "id": f"c{self.calls}"}])

class Cfg:
    system_prompt = "agent"; user_prompt = "read ROW_X"

class T(Cls):
    async def _execute_tool_call(self, tn, ta):
        if tn == "find_user":
            return {"result": {"success": True, "result": {"user_id": "u_1"}}, "gym_server": "mock"}
        return {"result": {"success": True, "result": {"rows": []}}, "gym_server": "mock"}  # the stall

orch = T(llm_client=MockLLM(), mcp_clients={},
         tool_to_server_mapping={"read_row": "mock", "find_user": "mock"},
         available_tools=[{"name": "read_row"}, {"name": "find_user"}],
         config=Cfg(), max_iterations=14)
res = asyncio.run(orch.execute())
flow = res["conversation_flow"]
rewinds = [e for e in flow if e.get("type") == "dos_rewind" and e.get("kind") == "stall"]

# --- assertions (the live-wiring contract) ---
assert len(rewinds) == 1, f"expected 1 stall rewind, got {len(rewinds)}"
rw = rewinds[0]
assert rw["tool_name"] == "read_row", rw
assert rw["repeat_run"] >= 5, rw                 # STALLED (>= stall_n default 5)
assert rw["rewind_to_turn"] == 0, rw             # rewound to the verified find_user anchor
assert rw["dropped_turns"], rw                   # the stalled turns WERE subtracted
note = " | ".join(rw["no_good_note"])
assert "NOT_SHIPPED" in note and "read_row" in note, note   # kernel token
assert "THIRD_PARTY" in note, note               # env bytes, floor-gated
# one-shot: it fired exactly once despite the long iteration budget (no cold-start livelock)
assert orch._dos_stats["rewinds"] == 1 and "read_row" in orch._stall_done
print("PASS stall_live_wiring: rewind_to_turn={} dropped={} repeat_run={}".format(
      rw["rewind_to_turn"], rw["dropped_turns"], rw["repeat_run"]))
'''


def _run_driver() -> subprocess.CompletedProcess:
    """Run the orchestrator drive in a clean subprocess (gym-root-first path)."""
    code = _DRIVER.replace("__HERE__", repr(_HERE))
    env = dict(os.environ)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)


import pytest  # noqa: E402


@pytest.mark.skipif(not os.path.isdir(_GYM),
                    reason="EnterpriseOps-Gym not cloned — live-wiring test skipped")
def test_stall_fires_inside_the_real_execute_loop():
    """DOS_STALL=1 + a byte-identical tool loop (after a verified prefix) → the real execute()
    loop SUBTRACTS to the pre-stall anchor with a byte-clean no-good note. Proven by driving the
    real orchestrator in a clean subprocess and asserting its conversation_flow."""
    cp = _run_driver()
    assert cp.returncode == 0, (
        f"live-wiring drive failed:\n--- stdout ---\n{cp.stdout}\n--- stderr ---\n{cp.stderr}"
    )
    assert "PASS stall_live_wiring" in cp.stdout, cp.stdout


if __name__ == "__main__":
    if not os.path.isdir(_GYM):
        print("SKIP: gym not cloned at", _GYM)
        sys.exit(0)
    cp = _run_driver()
    print(cp.stdout.strip())
    if cp.returncode != 0:
        print(cp.stderr.strip(), file=sys.stderr)
    sys.exit(cp.returncode)
