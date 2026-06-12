"""dos.drivers.nemo_action — the dos verdict as a NeMo Guardrails custom action (issue #51).

NeMo Guardrails (Apache-2.0) gives a rails config a custom-action shelf: a
function carrying ``action_meta`` is callable from a colang flow via
``execute``, and the flow branches on its return value. The existing actions
on that shelf adjudicate TEXT — toxicity, hallucination-likelihood,
prompt-injection. This one adjudicates whether a claimed EFFECT actually
happened: it re-reads git / the filesystem / the ship oracle (surfaces the
agent did not author) through the shared effect gate (docs/305) and returns
the typed verdict for the flow to act on.

    # config/actions.py  (auto-discovered by the rails config loader)
    from dos.drivers.nemo_action import make_dos_effect_check
    dos_effect_check = make_dos_effect_check(".", expect=[CommitClaim()])

    # rails/output.co
    define flow check effect claims
      $verdict = execute dos_effect_check(claim_text=$bot_message)
      if $verdict["tripped"]
        bot refuse to confirm unverified work

Or programmatically: ``rails.register_action(make_dos_effect_check("."),
name="dos_effect_check")``.

ADVISORY, twice over: the action only returns the verdict — the rail's own
policy decides what a refuted claim does to the flow (the docs/99 PDP-no-PEP
posture), and the gate's fail-to-abstain holds (a crash or unreachable
witness returns an ABSTAINED verdict with ``tripped=False``, never a
fabricated refusal, never a raise into the flow).

Import posture (the structural-twin rule, cf. ``agt_backend``)
==============================================================

NeMo's ``@action`` decorator does exactly one thing: set an ``action_meta``
dict attribute on the function. So this module imports NOTHING from
``nemoguardrails``: when the real decorator is importable it is used (a host
that introspects gets the genuine article); absent, a structurally identical
``action_meta`` is set by hand — byte-for-byte the same keys
(``tests/test_nemo_action.py`` pins the lockstep against the real package
when installed). Either way the factory works without the host package, and
the kernel dependency set is untouched.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from dos.drivers._effect_gate import Claim, EffectGate

__all__ = ["make_dos_effect_check"]


def _decorate(fn: Callable, name: str) -> Callable:
    """Attach NeMo's action metadata — the real decorator when available."""
    try:
        from nemoguardrails.actions import action

        return action(name=name)(fn)
    except ImportError:
        fn.action_meta = {  # type: ignore[attr-defined]
            "name": name,
            "is_system_action": False,
            "execute_async": False,
            "output_mapping": None,
        }
        return fn


def make_dos_effect_check(
    workspace: str | None = None,
    *,
    config: Any = None,
    expect: Sequence[Claim] = (),
    extract: Callable[[str], Sequence[Claim]] | None = None,
    name: str = "dos_effect_check",
) -> Callable:
    """Build the rails action over the shared effect gate.

    Parameters mirror `EffectGate` (workspace/config/expect/extract); ``name``
    is the action name a colang flow calls. A ``CommitClaim()`` in ``expect``
    pins its baseline to HEAD at THIS call — build the action when the rails
    app starts, before any agent runs.

    Returns an async function ``(claim_text=None, context=None) -> dict`` —
    the `GateVerdict` as a plain dict (``outcome`` / ``tripped`` / ``reason``
    / per-claim ``rows``), so a flow can branch on ``$verdict["tripped"]``
    and surface ``$verdict["reason"]``. When ``claim_text`` is omitted the
    action falls back to the context's ``bot_message`` (the conventional
    output-rail subject), then ``last_bot_message``.
    """
    gate = EffectGate(workspace, config=config, expect=expect, extract=extract)

    async def dos_effect_check(
        claim_text: str | None = None,
        context: dict | None = None,
    ) -> dict:
        text = claim_text
        if text is None and context:
            text = context.get("bot_message") or context.get("last_bot_message")
        return gate.adjudicate(text or "").to_dict()

    return _decorate(dos_effect_check, name)
