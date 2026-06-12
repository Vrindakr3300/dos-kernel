"""Contract tests for `dos.drivers.openai_agents_guardrail` (docs/305 Phase 2).

The verdict→``GuardrailFunctionOutput`` mapping via a structural stub (no SDK
anywhere), the loud-ImportError factory path, and an integration slice through
the REAL SDK's ``OutputGuardrail.run`` — skip-marked ``pip install
openai-agents`` so the core suite never depends on the optional host.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from dos.drivers._effect_gate import (
    CommitClaim,
    EffectGate,
    FileClaim,
    GateOutcome,
    GateVerdict,
)
from dos.drivers.openai_agents_guardrail import (
    _INSTALL_HINT,
    dos_output_guardrail,
    to_guardrail_output,
)


def _sdk_available() -> bool:
    # Probe the SYMBOLS, not the module name: an unrelated package named
    # `agents` on sys.path (seen in the wild) imports fine but is not the SDK.
    try:
        from agents import GuardrailFunctionOutput, OutputGuardrail  # noqa: F401
        return True
    except ImportError:
        return False


SDK_INSTALLED = _sdk_available()
needs_sdk = pytest.mark.skipif(
    not SDK_INSTALLED, reason="real host package required: pip install openai-agents",
)
needs_no_sdk = pytest.mark.skipif(
    SDK_INSTALLED, reason="exercises the missing-SDK loud path",
)


# ---------------------------------------------------------------------------
# The pure mapping, pinned with a structural stub (no SDK).
# ---------------------------------------------------------------------------


@dataclass
class _StubOutput:
    """Structural twin of the SDK's GuardrailFunctionOutput keyword surface."""

    output_info: Any
    tripwire_triggered: bool


def _verdict(outcome: GateOutcome, reason: str = "r") -> GateVerdict:
    return GateVerdict(outcome=outcome, reason=reason)


def test_tripped_maps_to_tripwire() -> None:
    out = to_guardrail_output(_verdict(GateOutcome.TRIPPED), _StubOutput)
    assert out.tripwire_triggered is True
    assert out.output_info["outcome"] == "TRIPPED"


@pytest.mark.parametrize(
    "outcome", [GateOutcome.CLEAR, GateOutcome.ABSTAINED, GateOutcome.NO_CLAIM]
)
def test_non_trip_outcomes_do_not_trip(outcome: GateOutcome) -> None:
    out = to_guardrail_output(_verdict(outcome), _StubOutput)
    assert out.tripwire_triggered is False
    # The abstain is RECORDED, never silent — the full verdict rides output_info.
    assert out.output_info["outcome"] == outcome.value
    assert out.output_info["reason"] == "r"


# ---------------------------------------------------------------------------
# The factory's loud missing-SDK path.
# ---------------------------------------------------------------------------


@needs_no_sdk
def test_factory_raises_loud_import_error_without_sdk() -> None:
    with pytest.raises(ImportError, match="pip install openai-agents"):
        dos_output_guardrail(".")
    assert "openai-agents" in _INSTALL_HINT


# ---------------------------------------------------------------------------
# The integration slice — through the REAL SDK machinery.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "ws"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-q", "-m", "seed")
    return r


@needs_sdk
def test_overclaim_trips_through_real_sdk(repo: Path) -> None:
    import asyncio

    from agents import Agent, RunContextWrapper

    guardrail = dos_output_guardrail(str(repo), expect=[CommitClaim()])
    worker = Agent(name="worker", instructions="land it",
                   output_guardrails=[guardrail])

    async def run() -> Any:
        ctx = RunContextWrapper(context=None)
        return await guardrail.run(
            agent=worker, agent_output="done! committed the fix.", context=ctx,
        )

    result = asyncio.run(run())
    assert result.output.tripwire_triggered is True
    assert result.output.output_info["outcome"] == "TRIPPED"


@needs_sdk
def test_backed_claim_passes_through_real_sdk(repo: Path) -> None:
    import asyncio

    from agents import Agent, RunContextWrapper

    (repo / "report.md").write_text("hi\n", encoding="utf-8")
    guardrail = dos_output_guardrail(str(repo), expect=[FileClaim("report.md")])
    worker = Agent(name="worker", instructions="write it",
                   output_guardrails=[guardrail])

    async def run() -> Any:
        ctx = RunContextWrapper(context=None)
        return await guardrail.run(
            agent=worker, agent_output="wrote report.md", context=ctx,
        )

    result = asyncio.run(run())
    assert result.output.tripwire_triggered is False
    assert result.output.output_info["outcome"] == "CLEAR"


# ---------------------------------------------------------------------------
# The factory wires the gate faithfully (no SDK needed — inspect the gate).
# ---------------------------------------------------------------------------


def test_gate_used_by_factory_matches_effect_gate_semantics(repo: Path) -> None:
    # The factory's behavior is EffectGate's: pin that the same construction
    # adjudicates the same way the no-SDK core does (the factory only maps).
    gate = EffectGate(str(repo), expect=[CommitClaim()])
    v = gate.adjudicate("done")
    assert v.outcome is GateOutcome.TRIPPED
    stub = to_guardrail_output(v, _StubOutput)
    assert stub.tripwire_triggered is True
