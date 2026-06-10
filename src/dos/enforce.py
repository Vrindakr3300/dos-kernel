"""The enforcement-handler seam — *who consumes an intervention decision, and how.*

docs/189 §A1 (the Claude Code source audit). DOS is "a sound PDP with no PEP": the
kernel *decides* a verdict, it does not *enforce*. Two modules already split the
**decision** side of an in-flight catch:

  * `dos.arg_provenance` / the detectors mint the VERDICT (was this id minted?).
  * `dos.intervention` maps a verdict → an `InterventionDecision`: *at what strength*
    should a consumer act (OBSERVE ‹ WARN ‹ BLOCK ‹ DEFER), confidence-gated, with a
    synthetic-corrective payload builder for the turn-preserving BLOCK.

What was missing is the **consumer** side: the thing that TAKES an
`InterventionDecision` and *proposes the effect* — append a note, withhold the call
and substitute a synthetic result, re-prompt, or delegate the decision to a leader
agent. Today that dispatch is **hand-coded inline** in one consumer
(`benchmark.enterpriseops.dos_react`: an `if action is DEFER / BLOCK / OBSERVE`
ladder). The Claude Code permission system showed the clean shape — three policies
(`coordinatorHandler` / `interactiveHandler` / `swarmWorkerHandler`) behind **one**
seam, chosen by runtime context, not hardcoded. This module lifts that *shape*.

The seam, not the policies
==========================

`EnforcementHandler` is the bring-your-own-PEP surface, the exact sibling of
`dos.judges` (the JUDGE rung) and `dos.overlap_policies` (the disjointness scorer):

  * The KERNEL holds only the pure protocol + two frozen value types + a built-in
    `ObserveHandler` (the unshadowable observe-only baseline) + `run_handler` (the
    fail-safe wrapper) + a by-name resolver over the `dos.enforce_handlers`
    entry-point group.
  * Every *ruling* handler with real PEP surface — an interactive dialog, a swarm
    delegate, an actual call-blocker, a sandbox wrapper — lives in a **driver** or a
    plugin, discovered by name at the call boundary, never imported by the kernel
    (the `drivers/__init__` one-way arrow). The handler returns a *proposal*; a host
    PEP (`dos apply`, docs/126) is what finally acts. So DOS stays a PDP even with
    this seam: the kernel proposes, the host enforces.

Fail-to-OBSERVE — the safe-failure direction for this role
==========================================================

Each rung of the trust ladder has its own *safe* failure, and they point in
different directions on purpose:

  * a safety **predicate** that cannot answer fails CLOSED → REFUSE
    (`admission.run_predicates`): the safe direction for *admission* is "deny".
  * an advisory **judge** that cannot answer fails to ABSTAIN (`judges.run_judge`):
    the safe direction for *adjudication* is "ask a human".
  * an enforcement **handler** that cannot answer fails to **OBSERVE**
    (`run_handler`, here): the safe direction for *actuation* is "do nothing — let
    the call through with a recorded note". A handler that RAISES, or returns a
    non-`EffectProposal`, must NOT become a spurious BLOCK/DEFER — withholding a
    legitimate call on a handler bug is how an advisory kernel turns into a
    self-inflicted DoS (the docs/143 −9 pp lesson: disruption is the expensive
    mistake). So a broken handler degrades to the zero-disruption proposal, never an
    enforcement it never intended. `run_handler` makes that structural, exactly as
    `run_judge` makes fail-to-abstain structural.

Note the asymmetry with `run_judge`: a judge's failure must never AGREE (auto-clear
a claim); a handler's failure must never *escalate* (auto-disrupt a call). Both
refuse to let a failure become the dangerous outcome for their role; they differ
only in which outcome is dangerous.

⚓ Pure kernel, no I/O inside a proposal, advisory only — the dos idiom (mirrors
`dos.judges`, `dos.overlap_policies`). A handler MAY do I/O *inside* `handle` (an
interactive dialog reads a TTY, a delegate sends a message) — that is exactly why a
ruling handler lives outside the kernel boundary. The seam itself is pure: a
Protocol, two frozen value types, an observe-only built-in, and resolver/runner
helpers. Entry-point discovery (the one bit of I/O) happens at the call boundary in
`active_handlers`, never inside a proposal.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from dos.intervention import Intervention, InterventionDecision


# ---------------------------------------------------------------------------
# The proposal a handler returns — frozen, advisory (the kernel proposes, the
# host PEP acts). The actuation dual of `JudgeVerdict`.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EffectProposal:
    """What a handler RECOMMENDS a host PEP do with an intervention — advisory, frozen.

    A handler reads an `InterventionDecision` (the *strength*) and proposes the
    concrete effect a host should materialize. It carries NOTHING it could mutate:
    it is read by `dos apply` / a consumer loop / an operator, and acting on it is
    always a separate, explicit step. This keeps the seam PDP-only — a handler can
    no more "enforce itself into" a state change than a judge can believe itself
    into one.

    Fields:
      intervention      — the rung this proposal actuates (echoed from the decision,
                          possibly DE-escalated by a fail-safe; never escalated past
                          it — see `run_handler`). The closed `Intervention` ABI.
      dispatch_call     — should the host let the REAL tool call fire? True for
                          OBSERVE/WARN; False for BLOCK/DEFER. Read this, never infer
                          from the rung name (the `InterventionLadder.dispatches`
                          contract, carried onto the proposal).
      synthetic_result  — the corrective payload a host substitutes for a withheld
                          call (only set on a BLOCK; `dispatch_call` is then False).
                          Built by `intervention.synthetic_corrective_result`. None
                          when the call dispatches or the rung does not substitute.
      note              — advisory text a host may attach to the result / surface to
                          the agent (the WARN annotation, the OBSERVE ledger line).
      handler           — the name of the handler that produced this proposal (for
                          the audit ledger / `dos doctor`). Set by `run_handler`.
      reason            — one line: why this proposal, for the operator log.
    """

    intervention: Intervention
    dispatch_call: bool
    synthetic_result: dict | None = None
    note: str = ""
    handler: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        # The one structural invariant: a synthetic result is only meaningful when
        # the real call is withheld. A proposal that both dispatches the call AND
        # substitutes a synthetic result is incoherent (the agent would see both the
        # real effect and a "we blocked it" note) — reject it loudly, the
        # `InterventionSpec.returns_synthetic implies not dispatches` discipline.
        if self.synthetic_result is not None and self.dispatch_call:
            raise ValueError(
                "EffectProposal: a synthetic_result is substituted for a WITHHELD "
                "call — dispatch_call must be False when synthetic_result is set"
            )

    @property
    def withholds_call(self) -> bool:
        """True iff the host should NOT fire the real call (`not dispatch_call`) —
        the data-driven test a consumer reads, never a hardcoded `{BLOCK, DEFER}`."""
        return not self.dispatch_call

    def to_dict(self) -> dict:
        return {
            "intervention": self.intervention.value,
            "dispatch_call": self.dispatch_call,
            "synthetic_result": self.synthetic_result,
            "note": self.note,
            "handler": self.handler,
            "reason": self.reason,
        }


@runtime_checkable
class EnforcementHandler(Protocol):
    """The contract a host implements to consume an intervention decision.

    ``name`` is the token a consumer selects and `dos doctor` lists. ``handle`` is
    handed the frozen `InterventionDecision` (the strength the kernel recommends) and
    the active `config` (read-only) and returns an `EffectProposal` (the effect the
    handler recommends a host PEP materialize).

    A handler MAY do I/O *inside* ``handle`` (prompt a TTY, send a delegate message,
    consult a sandbox) — unlike a predicate or renderer, which are pure. That is the
    whole reason a real handler lives in a driver, outside the kernel boundary: this
    is the PEP-adjacent rung where actuation surface is allowed. The disciplines that
    keep it honest are advisory-only (it returns a proposal, mutates nothing) and
    fail-to-observe (enforced by `run_handler`, not by trusting the handler), NOT
    purity.
    """

    name: str

    def handle(self, decision: InterventionDecision, config: object) -> EffectProposal:
        ...


def _observe_proposal(decision: InterventionDecision, *, handler: str, reason: str) -> EffectProposal:
    """The zero-disruption proposal: dispatch the real call, attach a recorded note.

    The actuation floor — what every fail-safe and the built-in degrade to. Always
    OBSERVE: the call fires unchanged, the verdict is recorded but the agent is not
    interrupted. It can never withhold a call, so it is the one proposal a broken or
    untrusted handler is allowed to fall back to.
    """
    return EffectProposal(
        intervention=Intervention.OBSERVE,
        dispatch_call=True,
        synthetic_result=None,
        note=decision.reason,
        handler=handler,
        reason=reason,
    )


class ObserveHandler:
    """The built-in, always-available handler: it proposes OBSERVE on everything.

    The enforcement analogue of `judges.AbstainJudge` and the `text` renderer — a
    trusted floor a plugin can never shadow (`resolve_handler` resolves built-ins
    first). It is the honest zero of the seam: a workspace with NO PEP wired still
    has a resolvable handler, and it records every verdict while letting every call
    through (the safe, advisory, zero-disruption behavior — DOS's PDP-only default).
    It is also the baseline a real handler is measured against: a handler that does
    no better than OBSERVE has added enforcement nobody asked for.

    Deliberately ignores the decision's *strength*: even a BLOCK/DEFER decision is
    actuated as OBSERVE here. Escalating past OBSERVE is opt-in — it requires wiring
    a ruling handler in a driver. The built-in never disrupts.
    """

    name = "observe"

    def handle(self, decision: InterventionDecision, config: object) -> EffectProposal:
        return _observe_proposal(
            decision,
            handler=self.name,
            reason=(
                "no enforcement handler wired — the built-in observes only: the call "
                "dispatches unchanged and the verdict is recorded (configure a "
                "dos.enforce_handlers driver to actuate BLOCK/DEFER)."
            ),
        )


def run_handler(
    handler: EnforcementHandler, decision: InterventionDecision, config: object
) -> EffectProposal:
    """Run one handler against one decision, enforcing **fail-to-observe** AND the
    **no-escalation** invariant. The wrapper EVERY consumer should call instead of
    `handler.handle(...)` directly.

    Two structural guarantees, both fail-SAFE toward less disruption:

      1. fail-to-observe — a handler that **raises** (a dialog times out, a delegate
         is unreachable, a bug) → the zero-disruption OBSERVE proposal, naming the
         failure. A handler that returns **anything that is not an `EffectProposal`**
         (None, a dict, a duck-typed look-alike) → OBSERVE. We never read a foreign
         object's `.withholds_call`, so no spurious block sneaks through a wrong
         return type.
      2. no-escalation — a handler may DE-escalate (propose a rung no more disruptive
         than the kernel recommended) but never ESCALATE past it. A handler that
         returns a proposal MORE disruptive than the decision's rung is clamped back
         down to the decision's rung as an OBSERVE-safe note. This makes "a handler
         can never act harder than the kernel's confidence-gated recommendation" a
         property of the wrapper, not a hope — the actuation analogue of judges'
         "a failure can never auto-clear".

    Both guarantees point the same way: a handler's failure or overreach degrades
    toward LESS disruption, never more. Withholding a legitimate call on a handler
    fault is the expensive mistake (the docs/143 −9 pp posture); this wrapper makes
    it structurally unreachable by accident.
    """
    name = getattr(handler, "name", type(handler).__name__)
    try:
        proposal = handler.handle(decision, config)
    except Exception as e:  # fail-to-observe: a handler that raises cannot enforce
        return _observe_proposal(
            decision,
            handler=name,
            reason=(
                f"handler {name!r} raised ({e!r}) — observing only (an actuation "
                f"handler that faults must not withhold the call; it degrades to the "
                f"zero-disruption proposal, never a spurious block)."
            ),
        )
    if not isinstance(proposal, EffectProposal):
        return _observe_proposal(
            decision,
            handler=name,
            reason=(
                f"handler {name!r} returned a {type(proposal).__name__}, not an "
                f"EffectProposal — observing only (a handler that does not return the "
                f"proposal type cannot be trusted to withhold a call)."
            ),
        )
    # no-escalation: a handler may propose a LESS-or-equally disruptive rung, never a
    # MORE disruptive one than the kernel's confidence-gated recommendation. Compare
    # on the closed Intervention rank order (OBSERVE < WARN < BLOCK < DEFER). On
    # overreach, degrade to the zero-disruption proposal rather than honor the
    # escalation — the fail-safe direction.
    if _rank(proposal.intervention) > _rank(decision.intervention):
        return _observe_proposal(
            decision,
            handler=name,
            reason=(
                f"handler {name!r} proposed {proposal.intervention.value}, more "
                f"disruptive than the kernel's {decision.intervention.value} "
                f"recommendation — clamped to OBSERVE (a handler may de-escalate, "
                f"never escalate past the confidence-gated rung)."
            ),
        )
    # Stamp the handler name if the handler left it blank (so the audit ledger always
    # records who produced the proposal) without mutating a frozen instance.
    if not proposal.handler:
        return EffectProposal(
            intervention=proposal.intervention,
            dispatch_call=proposal.dispatch_call,
            synthetic_result=proposal.synthetic_result,
            note=proposal.note,
            handler=name,
            reason=proposal.reason,
        )
    return proposal


# The fixed disruption order of the closed `Intervention` ABI — used only to enforce
# the no-escalation invariant in `run_handler`. This mirrors the canonical rank order
# in `BASE_INTERVENTIONS` (OBSERVE 0 < WARN 10 < BLOCK 20 < DEFER 30) but is kept as a
# tiny local total order on the ENUM so `run_handler` never needs a ladder instance to
# compare two rungs (a handler is selected per-decision; threading a ladder through
# would couple the seam to a ladder value it does not otherwise need). A host that adds
# a custom rung via `InterventionLadder.extend` still actuates through the closed enum,
# so this stays total over everything a handler can propose.
_INTERVENTION_RANK: dict[Intervention, int] = {
    Intervention.OBSERVE: 0,
    Intervention.WARN: 1,
    Intervention.BLOCK: 2,
    Intervention.DEFER: 3,
}


def _rank(intervention: Intervention) -> int:
    """The disruption rank of an `Intervention` for the no-escalation check.

    An unknown member (impossible for the closed enum, but defensive) ranks at the
    TOP (max + 1) so it is treated as maximally disruptive — a value `run_handler`
    cannot tell is safe is clamped, never let through. The conservative direction."""
    return _INTERVENTION_RANK.get(intervention, max(_INTERVENTION_RANK.values()) + 1)


# ---------------------------------------------------------------------------
# Resolution — built-in first, then the `dos.enforce_handlers` entry-point group.
# ---------------------------------------------------------------------------

# The entry-point group a workspace/researcher registers a handler under.
HANDLER_ENTRY_POINT_GROUP = "dos.enforce_handlers"

# The built-in handlers, resolvable by name and UNSHADOWABLE by a plugin (a plugin
# registering `observe` cannot displace this one — built-ins resolve first). Only the
# zero-disruption `observe` floor ships in the kernel; every ruling handler with PEP
# surface lives in a driver/plugin (the kernel has no actuation surface).
_BUILT_IN_HANDLERS: dict[str, type] = {
    ObserveHandler.name: ObserveHandler,
}


def _discover_entry_point_handlers(*, _stderr=None) -> list[tuple[str, EnforcementHandler]]:
    """Find handlers registered under the `dos.enforce_handlers` entry-point group.

    A handler plugin registers ``name = "pkg.module:HandlerClass"`` in its
    ``[project.entry-points."dos.enforce_handlers"]``. We load each, instantiate it if
    it is a class, and return ``(entry_point_name, handler)`` pairs sorted by name
    (stable, so `dos doctor` order is deterministic). A plugin that fails to load is
    skipped with a one-line stderr note rather than crashing — the same posture
    `judges._discover_entry_point_judges` / predicate / renderer discovery take (a
    broken third-party plugin is the operator's to fix, not a kernel fault).
    """
    stderr = _stderr if _stderr is not None else sys.stderr
    out: list[tuple[str, EnforcementHandler]] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=HANDLER_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(HANDLER_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash a call
        return out
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            obj = ep.load()
            handler = obj() if isinstance(obj, type) else obj
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: enforce handler plugin {ep.name!r} failed to load ({e}); skipping",
                file=stderr,
            )
            continue
        out.append((ep.name, handler))
    return out


def resolve_handler(name: str, *, _stderr=None) -> EnforcementHandler:
    """Resolve a handler by name: built-ins first, then `dos.enforce_handlers` plugins.

    Built-ins (`observe`) resolve FIRST and cannot be shadowed by a plugin of the same
    name — the trusted-floor guarantee, identical to `resolve_judge` / `resolve_renderer`.
    An unknown name fails LOUD with the known list (it never silently degrades to
    `observe`, which would hide a typo'd handler selection): the caller asked for a
    specific actuator and getting a different one silently is exactly the kind of
    unannounced substitution the kernel refuses.
    """
    if name in _BUILT_IN_HANDLERS:
        return _BUILT_IN_HANDLERS[name]()
    discovered = dict(_discover_entry_point_handlers(_stderr=_stderr))
    if name in discovered:
        return discovered[name]
    known = sorted(set(_BUILT_IN_HANDLERS) | set(discovered))
    raise ValueError(f"unknown enforce handler {name!r}; known: {', '.join(known)}")


def active_handlers(*, _stderr=None) -> list[tuple[str, EnforcementHandler]]:
    """Every resolvable handler as ``(name, handler)`` — built-ins THEN discovered
    plugins, the order `dos doctor` lists. Does ENTRY-POINT DISCOVERY (I/O), so it is a
    call-boundary helper, never called inside a proposal."""
    built = [(n, cls()) for n, cls in _BUILT_IN_HANDLERS.items()]
    discovered = _discover_entry_point_handlers(_stderr=_stderr)
    return built + discovered


def active_handler_names(*, _stderr=None) -> list[str]:
    """The names of every active handler (built-in + discovered) — what `dos doctor`
    lists so an operator can see which actuators the enforcement seam can call (the
    handler analogue of "see the active judges / predicates / reason set")."""
    return [name for name, _handler in active_handlers(_stderr=_stderr)]
