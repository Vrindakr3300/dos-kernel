"""Pins the MODEL-AWARE reasoning_effort selection (docs/231) — $0, no model, no network.

The regression this guards: gemini-2.5-pro REJECTS `reasoning_effort="disable"` with
`BadRequestError ... "Budget 0 is invalid. This model only works in thinking mode."`, so
the docs/228 second-model attempt (which sent "disable" to every model) errored on all 60
pro tasks and produced ZERO usable rows. `_agent_llm_args` must send "disable" only to
flash-tier models and a valid non-zero budget ("low") to -pro-tier (thinking-only) models.
A pure import-and-call test catches a reintroduction of the flat constant without any spend.
"""
from __future__ import annotations

import pytest

from .live_loop import _agent_llm_args


@pytest.mark.parametrize(
    "model,expected",
    [
        # flash-tier accepts "disable" (needed to stop the empty-thought crash)
        ("gemini/gemini-2.5-flash", "disable"),
        ("gemini/gemini-3-flash", "disable"),
        ("gemini-2.5-flash", "disable"),
        # -pro-tier is thinking-only: "disable" is fatal -> must be a non-zero budget
        ("gemini/gemini-2.5-pro", "low"),
        ("gemini/gemini-3-pro", "low"),
        ("gemini-2.5-pro", "low"),
        # a non-gemini id falls through to the flash default (no -pro tier marker)
        ("gpt-4o", "disable"),
    ],
)
def test_reasoning_effort_is_model_aware(model, expected):
    assert _agent_llm_args(model)["reasoning_effort"] == expected


def test_pro_never_gets_disable():
    """The exact fatal combination: a -pro model must NEVER be handed reasoning_effort=disable."""
    for model in ("gemini/gemini-2.5-pro", "gemini-2.5-pro", "gemini/gemini-3-pro"):
        assert _agent_llm_args(model)["reasoning_effort"] != "disable"


def test_temperature_is_always_zero():
    """Determinism knob is unchanged by the model branch."""
    for model in ("gemini/gemini-2.5-flash", "gemini/gemini-2.5-pro"):
        assert _agent_llm_args(model)["temperature"] == 0.0
