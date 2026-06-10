"""test_schema_refresh_live_wiring.py — the curable-CONVERSION re-surface fires inside the REAL
execute() loop (docs/200/205, rank 1).

The pure tests (test_schema_refresh.py) pin the extractor + the kind-dispatched directive; this
proves the LIVE WIRING: with DOS_SCHEMA_REFRESH=1, the actual `DosReactOrchestrator.execute()`
loop — the real control flow plus the call-site block added to dos_react.py — detects a NATURAL
same-tool thrash on a CURABLE tool and APPENDS the env's own schema corrective as a forcing
function, WITHOUT subtracting any turns (the additive WARN-rung, not the rewind subtract).

It drives the real orchestrator (the gym base class) with a MOCK LLM that re-issues one curable
tool call whose MOCK result is a structured "is required" error, so no live Gemini / no MCP
container is needed. Same subprocess + gym-root-first path discipline as test_stall_live_wiring.py
(the gym ships a top-level `benchmark` package that collides with this repo's under pytest).

Run: PYTHONPATH=../../src python -m pytest test_schema_refresh_live_wiring.py -q
 or: python test_schema_refresh_live_wiring.py        # direct, prints the verdict
"""
from __future__ import annotations

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GYM = os.path.join(_HERE, "enterpriseops-gym")


# ---------------------------------------------------------------------------
# The actual orchestrator drive — run in a clean process (no pytest rootdir, so the gym's
# `benchmark` package resolves). Prints PASS on success, nonzero on failure.
# ---------------------------------------------------------------------------
_DRIVER = r'''
import sys, os, asyncio
_HERE = __HERE__
sys.path.insert(0, os.path.join(_HERE, "..", "..", "src"))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "enterpriseops-gym"))  # gym root FIRST
os.environ["DOS_SCHEMA_REFRESH"] = "1"
# CONSULT=0 (the natural regime) + clear every sibling arm so only the re-surface is active.
for _k in ("DOS_CONSULT", "DOS_REWIND", "DOS_REWIND_NATURAL", "DOS_STALL", "DOS_RESTART"):
    os.environ.pop(_k, None)
os.environ["DOS_CONSULT"] = "0"

from langchain_core.messages import AIMessage
from dos_react import make_dos_react_orchestrator
Cls = make_dos_react_orchestrator()

# the env's OWN curable corrective (a missing-required list) — exactly the EnterpriseOps grammar.
ENV_ERR = ("❌ Invalid Tool Arguments: ['responseBodyHtml: is required', "
           "'restrictToContacts: is required', 'restrictToDomain: is required']")

class MockLLM:
    """Thrashes the SAME curable tool twice (a natural same-tool fail-thrash), then stops. After the
    DOS directive arrives it stops (we only assert the directive was injected, not that it recovers —
    recovery is the LIVE A/B's question, not the wiring's)."""
    def __init__(self): self.calls = 0
    async def invoke_with_tools(self, messages, tools):
        self.calls += 1
        for m in messages:
            c = getattr(m, "content", "")
            if isinstance(c, str) and c.startswith("[DOS]"):
                return AIMessage(content="ok, will fix", tool_calls=[])  # stop once nudged
        if self.calls <= 2:   # two failing calls to the same curable tool = the natural thrash
            return AIMessage(content="setting vacation",
                             tool_calls=[{"name": "update_vacation_settings",
                                          "args": {"enabled": True}, "id": f"c{self.calls}"}])
        return AIMessage(content="done", tool_calls=[])

class Cfg:
    system_prompt = "agent"; user_prompt = "set a vacation responder"

class T(Cls):
    async def _execute_tool_call(self, tn, ta):
        # the gym's structured-error envelope shape (isError=true, content[].text)
        return {"result": {"success": True,
                           "result": {"content": [{"type": "text", "text": ENV_ERR}],
                                      "isError": True}},
                "gym_server": "mock"}

orch = T(llm_client=MockLLM(), mcp_clients={},
         tool_to_server_mapping={"update_vacation_settings": "mock"},
         available_tools=[{"name": "update_vacation_settings"}],
         config=Cfg(), max_iterations=14)
res = asyncio.run(orch.execute())
flow = res["conversation_flow"]
refreshes = [e for e in flow if e.get("type") == "dos_schema_refresh"]

# --- assertions (the live-wiring contract) ---
assert len(refreshes) == 1, f"expected 1 schema-refresh, got {len(refreshes)}: {refreshes}"
r = refreshes[0]
assert r["tool_name"] == "update_vacation_settings", r
assert r["kind"] == "SCHEMA", r                      # the curable kind that converts
assert r["n_fail"] >= 2, r                           # the natural thrash threshold
assert orch._dos_stats["schema_refresh_warns"] == 1, orch._dos_stats
assert "update_vacation_settings" in orch._schema_refresh_done   # one-shot/tool

# ADDITIVE, not a subtract: no rewind/restart event in the flow, and rewinds stat untouched.
assert orch._dos_stats["rewinds"] == 0, orch._dos_stats
assert not [e for e in flow if e.get("type") in ("dos_rewind", "dos_restart")], flow

# (the re-surface is appended to `messages` as a [DOS] HumanMessage carrying the env's field name;
#  its byte-cleanliness is pinned by the pure test. Here we assert the wiring + additivity.)
print("PASS schema_refresh_live_wiring: kind={} n_fail={} warns={} rewinds={}".format(
      r["kind"], r["n_fail"], orch._dos_stats["schema_refresh_warns"], orch._dos_stats["rewinds"]))
'''


def _run_driver() -> subprocess.CompletedProcess:
    code = _DRIVER.replace("__HERE__", repr(_HERE))
    env = dict(os.environ)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)


import pytest  # noqa: E402


@pytest.mark.skipif(not os.path.isdir(_GYM),
                    reason="EnterpriseOps-Gym not cloned — live-wiring test skipped")
def test_schema_refresh_fires_inside_the_real_execute_loop():
    """DOS_SCHEMA_REFRESH=1 + a natural same-tool curable thrash → the real execute() loop APPENDS
    the env's own schema corrective (additive, no subtract). Proven by driving the real orchestrator
    in a clean subprocess and asserting its conversation_flow + stats."""
    cp = _run_driver()
    assert cp.returncode == 0, (
        f"live-wiring drive failed:\n--- stdout ---\n{cp.stdout}\n--- stderr ---\n{cp.stderr}"
    )
    assert "PASS schema_refresh_live_wiring" in cp.stdout, cp.stdout


if __name__ == "__main__":
    if not os.path.isdir(_GYM):
        print("SKIP: gym not cloned at", _GYM)
        sys.exit(0)
    cp = _run_driver()
    print(cp.stdout.strip())
    if cp.returncode != 0:
        print(cp.stderr.strip(), file=sys.stderr)
    sys.exit(cp.returncode)
