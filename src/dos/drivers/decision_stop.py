"""dos.drivers.decision_stop — a reference loop-STOP policy (a `dos.stop_policy` occupant).

The kernel scout's default is "an open operator decision is evidence-only, never a
STOP" (the 2026-06-03 directive). That is right for most decisions — a WEDGE or an
open soak gate blocks *future* work but wastes nothing while it waits, so halting
the whole loop on it is over-reach. But one decision class is different: a
`LIVENESS` row is an `OP_HALT` proposal — a run a watchdog judged SPINNING/hung
RIGHT NOW, actively burning budget. For a host that wants its loop to halt rather
than keep launching work alongside a doomed run, "stop on a LIVENESS decision" is a
legitimate policy.

This driver is the reference `dos.stop_policy.StopPolicy` occupant that encodes
exactly that, configurably:

  * `DecisionClassStopPolicy(stop_classes=("LIVENESS",))` — reads the live
    `dos.decisions` HUMAN queue and returns `StopVerdict.stop(...)` iff a pending
    decision's `kind` is in `stop_classes`; otherwise `StopVerdict.defer()` (fall
    through to the kernel's evidence-only default — WEDGE/soak/arbiter-refuse only
    surface). The default `stop_classes` is `("LIVENESS",)` — the one urgent class.

It lives in a **driver**, not the kernel, because it does I/O (reads the decision
queue) and encodes host policy (which classes are halt-worthy) — the same reason a
ruling judge or a model-backed overlap scorer lives here. The kernel seam
(`dos.stop_policy`) holds only the Protocol + the fail-to-DEFER wrapper + the
resource-floor AND; this is one concrete policy under it. Registered under the
`dos.stop_policies` entry-point group so `resolve_stop_policy("decision-class")`
returns it; a host opts in by naming it in `dos.toml [scout] stop_policy`.

Safety: the policy reads the queue inside `decide`, and any fault there is caught
by the kernel's `run_stop_policy` (fail-to-DEFER) — but we ALSO guard the read here
so a torn/missing queue degrades to "no halt-worthy decision" (DEFER) with a clear
reason, rather than relying solely on the wrapper. And whatever this returns, the
kernel ANDs it under the `resource_blocked` floor, so this policy can only ever
*add* a halt, never suppress the measured resource STOP.
"""

from __future__ import annotations

from dos.stop_policy import StopVerdict

# The decision classes this policy halts on, by default. LIVENESS = an OP_HALT
# proposal: a run hung/spinning NOW, burning budget — the one class where letting
# the loop keep launching work is worse than stopping. Everything else (WEDGE,
# ARBITER_REFUSE, PREFLIGHT_REFUSE, SOAK_GATE) blocks future work but wastes nothing
# waiting, so it stays evidence-only (DEFER → the kernel default surfaces it).
_DEFAULT_STOP_CLASSES = ("LIVENESS",)


class DecisionClassStopPolicy:
    """STOP the loop iff a pending operator decision is of a configured urgent class.

    The reference `dos.stop_policy.StopPolicy`. `stop_classes` is the set of
    `dos.decisions.DecisionKind` values that warrant a halt (default
    `("LIVENESS",)`). `decide` reads the live HUMAN decision queue for the active
    workspace and returns STOP on the first match, else DEFER.
    """

    name = "decision-class"

    def __init__(self, stop_classes: tuple[str, ...] = _DEFAULT_STOP_CLASSES) -> None:
        # Normalize to an upper-cased set for a case-insensitive `kind` match.
        self.stop_classes = frozenset(c.strip().upper() for c in stop_classes if c)

    def decide(self, state: object, config: object) -> StopVerdict:
        """Read the live HUMAN decision queue; STOP on an urgent-class row, else DEFER.

        Guarded: a missing/torn queue (or an absent kernel decisions module) →
        DEFER, never a spurious halt. The kernel's `run_stop_policy` would also
        catch a raise, but degrading here gives a clearer reason and keeps the
        policy honest on its own.
        """
        try:
            from dos import config as _config
            from dos import decisions as _decisions
            cfg = config if config is not None else _config.active()
            rows = _decisions.collect_decisions(cfg, resolver="HUMAN")
        except Exception as e:
            return StopVerdict.defer(
                f"decision-class policy could not read the queue ({e!r}) — "
                f"deferring (no halt)."
            )
        for d in rows:
            kind = getattr(getattr(d, "kind", None), "value", "")
            if str(kind).upper() in self.stop_classes:
                lane = getattr(d, "lane", "") or "-"
                text = getattr(d, "reason_text", "") or kind
                return StopVerdict.stop(
                    f"a {kind} decision is pending (lane {lane!r}): {text[:120]}. "
                    f"Host policy halts the loop on this class — resolve it "
                    f"(`dos decisions` / F9) before relaunching.",
                    cause_key=f"stop_on_{str(kind).lower()}",
                    evidence=(f"{kind} lane={lane}",
                              f"stop_classes={sorted(self.stop_classes)}"),
                )
        return StopVerdict.defer(
            f"no pending decision in the halt classes {sorted(self.stop_classes)} "
            f"({len(rows)} HUMAN decision(s) pending, all evidence-only)."
        )
