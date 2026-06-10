"""Phase 6 (docs/207) — the generic dispatch-loop uses the new substrate end-to-end.

The `dos-dispatch-loop` skill now consults `dos pickable` + `dos cooldown` at
pick-selection and `dos reconcile` at the archive step. The loop_decide rungs that
back this (PICK_HELD_INVARIANT, PICK_COOLDOWN) shipped in Phase 3; these pin the
LOOP-LEVEL behavior the plan §6 names:

  * `test_dos_loop_skips_cooled_unit` — a loop handed a cooled next-unit STOPs
    (does not re-dispatch) — the re-pick storm broken at the loop level;
  * `test_dos_loop_reconciles_quiet_incomplete` — a claimed-done-but-NOT_SHIPPED
    pick reconciles to QUIET_INCOMPLETE, so it stays in the residual (the cross-run
    KEEP) for the next iteration instead of being silently dropped.

The skill text drives these via the verbs; here we exercise the kernel mechanism
the skill shells (the backtest-invariant shape).
"""
from __future__ import annotations

from dos import loop_decide as ld
from dos.cooldown import Cooldown, CooldownState
from dos.pickable import Pickability, HoldReason
from dos.reconcile import reconcile, Reconciliation


def _shipped() -> ld.IterationOutcome:
    return ld.IterationOutcome(kind=ld.OutcomeKind.SHIPPED)


def test_dos_loop_skips_cooled_unit():
    """A loop whose next unit is RECENTLY_ATTEMPTED (and nothing fresher is
    offerable) STOPs on PICK_COOLDOWN rather than re-dispatching — the storm broken
    at the loop level."""
    cool = Cooldown(state=CooldownState.RECENTLY_ATTEMPTED, unit_id="AUTH3",
                    until_ms=999, count=4, reason="drained 4× inside the window")
    state = ld.LoopState(iteration=2, max_iterations=10, cooldown=cool)
    d = ld.decide(state, _shipped())
    assert d.action == "stop"
    assert d.stop_reason == ld.StopReason.PICK_COOLDOWN
    assert d.surface is True


def test_dos_loop_clear_cooldown_continues():
    """A CLEAR cooldown does not stop — the loop dispatches the fresh unit."""
    state = ld.LoopState(iteration=2, max_iterations=10,
                         cooldown=Cooldown(state=CooldownState.CLEAR, unit_id="AUTH4"))
    d = ld.decide(state, _shipped())
    assert d.action == "continue"


def test_dos_loop_invariant_hold_stops():
    """A loop whose next unit is held by a re-dispatch-invariant reason honest-STOPs
    (the drain-trap the loop used to spin on)."""
    state = ld.LoopState(
        iteration=2, max_iterations=10,
        pickability=Pickability.HELD(HoldReason.DRAFT_CLASS, "plan is DRAFT"))
    d = ld.decide(state, _shipped())
    assert d.action == "stop"
    assert d.stop_reason == ld.StopReason.PICK_HELD_INVARIANT


def test_dos_loop_reconciles_quiet_incomplete():
    """A claimed-done-but-NOT_SHIPPED pick reconciles to QUIET_INCOMPLETE → it STAYS
    in the residual (the cross-run KEEP), re-entering the pickable set next
    iteration instead of being silently dropped on the agent's word."""
    v = reconcile("AUTH3", claimed_done=True, oracle_shipped=False)
    assert v.state is Reconciliation.QUIET_INCOMPLETE
    assert v.keeps_in_residual          # the KEEP — the claim never removes work
    assert v.flag == "QUIET_INCOMPLETE"  # the routing tag the next iteration reads


def test_dos_loop_verified_pick_leaves_residual():
    """A pick the oracle confirms shipped leaves the residual (not re-offered)."""
    v = reconcile("AUTH3", claimed_done=True, oracle_shipped=True)
    assert v.state is Reconciliation.VERIFIED
    assert not v.keeps_in_residual


def test_skill_names_the_new_verbs():
    """The dos-dispatch-loop screenplay actually shells the Phase-6 verbs (so the
    loop drives the kernel rungs, not prose). Grep the shipped skill."""
    from pathlib import Path
    import dos
    text = (Path(dos.__file__).parent / "skills" / "dos-dispatch-loop" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "dos pickable" in text
    assert "dos cooldown" in text
    assert "dos reconcile" in text
    assert "pick-cooldown" in text
    assert "QUIET_INCOMPLETE" in text
