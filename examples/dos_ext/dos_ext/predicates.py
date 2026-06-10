"""A custom DOS admission predicate — the safety axis of hackability (ADM, Axis 3).

DOS's built-in admission predicates are the tree-disjointness check (two lanes
may run concurrently only if their file trees barely intersect) and the
SELF_MODIFY guard (no lease may edit the orchestrator's own running code). A
workspace that wants ITS OWN admission rule — "refuse a new lease when we're over
the monthly token budget," "refuse a lease outside business hours" — ships an
`AdmissionPredicate` and registers it via a `dos.predicates` entry_point (see this
package's `pyproject.toml`). The arbiter runs the built-ins PLUS every discovered
predicate, conjunctively.

The one invariant that keeps an OPEN predicate set safe (HACKING.md Axis 3): a
predicate may only **REFUSE**, never force-admit. `AdmissionVerdict` has only
`.admit()` / `.refuse(reason)` — there is no "admit harder" return value — so a
buggy or hostile workspace predicate is *structurally* incapable of loosening
admission (the worst it can do is refuse too much, a visible, safe-direction
failure). `--force` (the operator) remains the sole override of any refusal.

A predicate is PURE: it does NO I/O during arbitration. Any live data it needs
(the current token spend) is pre-computed and read off `config` — exactly how
`pick_oracle` does its I/O outside the arbiter. This example reads a budget cap
and a current-spend value the host stashed on `config` before the `arbitrate()`
call; if they are absent it admits (a guard that can't tell admits — but note a
guard that RAISES is fail-closed-refused by the runner, the safe direction).
"""

from __future__ import annotations

from dos.admission import AdmissionRequest, AdmissionVerdict


class BudgetGuard:
    """Refuse a new lease when the workspace is over its monthly token budget.

    The copy-me skeleton from HACKING.md §3, as a real registered predicate. The
    budget cap and current spend are read off `config` (pre-computed by the host
    before `arbitrate()` — the arbiter and its predicates stay pure). Reads two
    optional attributes the host attaches to its `SubstrateConfig`:
      * ``token_budget`` — the monthly cap (None / absent ⇒ no budget enforced).
      * ``tokens_spent`` — the current spend (absent ⇒ treated as 0).

    Ignores ``live_lease`` — a budget overrun is a property of the WORKSPACE, not
    of any particular live lease (like SELF_MODIFY). It still implements the
    per-lease signature so it composes in the same conjunction; it returns the
    same verdict for every live lease, which is harmless (the runner
    short-circuits on the first refusal).
    """

    name = "budget-guard"

    def __call__(self, request: AdmissionRequest, live_lease: dict,
                 config: object) -> AdmissionVerdict:
        cap = getattr(config, "token_budget", None)
        if cap is None:
            return AdmissionVerdict.admit()
        spent = getattr(config, "tokens_spent", 0) or 0
        if spent >= cap:
            return AdmissionVerdict.refuse(
                f"monthly token budget exhausted ({spent}/{cap}) — refusing "
                f"lane {request.lane!r}. Raise the cap or wait for the window "
                f"to reset (pass --force to override)."
            )
        return AdmissionVerdict.admit()


# A module-level instance, so the entry_point can point at either the class
# (`...:BudgetGuard`, which `dos` instantiates) or this ready-made object
# (`...:budget_guard`, used as-is). The pyproject registers the class form; this
# alias documents that a bare callable/instance works too.
budget_guard = BudgetGuard()
