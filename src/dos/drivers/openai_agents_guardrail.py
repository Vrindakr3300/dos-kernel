"""dos.drivers.openai_agents_guardrail — the dos verdict at the SDK's tripwire seam (docs/305).

The OpenAI Agents SDK (PyPI ``openai-agents``, imports as ``agents``) runs
``output_guardrails`` over an agent's final output and HALTS the run when one
trips — ``Runner.run(...)`` raises ``OutputGuardrailTripwireTriggered``; the
caller catches it and re-dispatches instead of consuming the claim. That
checkpoint is the seat for an env-evidence verdict: when a finished run's
declared deliverable (a commit, a file, a shipped phase) is ABSENT from a
read-back the agent did not author, the tripwire fires.

    from agents import Agent, Runner
    from dos.drivers.openai_agents_guardrail import dos_output_guardrail
    from dos.drivers._effect_gate import CommitClaim

    agent = Agent(
        name="worker",
        instructions="Land the fix, then report.",
        # Build the guardrail BEFORE the run: a CommitClaim() pins its
        # baseline to HEAD here, so anything the run lands is visible.
        output_guardrails=[dos_output_guardrail(".", expect=[CommitClaim()])],
    )
    try:
        result = await Runner.run(agent, "fix the bug in parser.py")
    except OutputGuardrailTripwireTriggered as e:
        ...  # the over-claim was caught: re-dispatch; the verdict (what was
        # claimed, what the witness saw, what would make it pass) rides
        # e.guardrail_result.output.output_info.

The dependency arrow points at us: this module speaks THEIR contract; nothing
in the SDK imports dos-kernel. Layer-4 driver — the same rule that lets
``agt_backend.py`` name AGT lets this module name the OpenAI Agents SDK.

The verdict mapping (docs/305 §1)
=================================

  * gate ``TRIPPED``   → ``tripwire_triggered=True``  — an accountable
    read-back REFUTED a claimed effect; the run halts instead of the claim
    landing.
  * gate ``CLEAR`` / ``ABSTAINED`` / ``NO_CLAIM`` → ``tripwire_triggered=False``
    — fail-to-abstain (docs/86): only a refutation blocks; "could not tell"
    never manufactures a trip.
  * EVERY verdict, the abstain included, rides ``output_info`` (the gate's
    ``to_dict()``), so an abstain is recorded, never silent.

Import posture
==============

Unlike the AGT seat (duck-typeable), you cannot ATTACH an Agents-SDK guardrail
without the SDK installed — so the factory imports ``agents`` lazily and a
missing SDK is a LOUD ``ImportError`` with the install hint, not an abstain
(the silent-cliff rule). The verdict→``GuardrailFunctionOutput`` mapping is a
module-level pure function so the no-SDK tests pin it with a structural stub.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from dos.drivers._effect_gate import Claim, EffectGate, GateVerdict

__all__ = ["dos_output_guardrail", "to_guardrail_output"]

_INSTALL_HINT = (
    "the OpenAI Agents SDK is not installed — `pip install openai-agents` "
    "(imports as `agents`)"
)


def to_guardrail_output(verdict: GateVerdict, output_cls: type) -> Any:
    """The pure verdict→``GuardrailFunctionOutput`` mapping (docs/305 §1).

    ``output_cls`` is the SDK's class (or a structural stub in tests): it must
    accept ``output_info`` and ``tripwire_triggered`` keywords. Only a TRIPPED
    gate trips the wire; everything else — the abstain included — passes with
    the full verdict recorded in ``output_info``.
    """
    return output_cls(
        output_info=verdict.to_dict(),
        tripwire_triggered=verdict.tripped,
    )


def dos_output_guardrail(
    workspace: str | None = None,
    *,
    config: Any = None,
    expect: Sequence[Claim] = (),
    extract: Callable[[str], Sequence[Claim]] | None = None,
    name: str = "dos-effect-gate",
) -> Any:
    """Build the SDK ``OutputGuardrail`` that adjudicates a run's final output.

    Parameters mirror `EffectGate` (workspace/config/expect/extract); ``name``
    is the guardrail's display name in the SDK's run result. Returns the SDK's
    ``OutputGuardrail`` — attach via ``Agent(output_guardrails=[...])``.

    Raises ``ImportError`` with the install hint when the SDK is absent: a
    guardrail that cannot be attached must fail loudly at build time, not
    silently never-run.
    """
    try:
        from agents import GuardrailFunctionOutput, OutputGuardrail
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e

    gate = EffectGate(workspace, config=config, expect=expect, extract=extract)

    async def _adjudicate(ctx: Any, agent: Any, output: Any) -> Any:
        text = "" if output is None else str(output)
        return to_guardrail_output(gate.adjudicate(text), GuardrailFunctionOutput)

    return OutputGuardrail(guardrail_function=_adjudicate, name=name)
