"""Heterogeneous, multi-vendor fleets — proving the A/B is vendor-blind.

FleetHorizon's headline (`README.md` §honesty) is a property of the *kernel*, not
of any one agent: GIVEN a fleet that lies at rate L and collides at rate C, what
does the open loop bank that the closed loop catches? The base benchmark runs one
`FailureModel` across the whole fleet — every effort lies at the same rate. That
is the right default for the swept headline, but it leaves an obvious question
unanswered: *does any of this depend on the agent being Claude?*

It does not, and this module is how we PROVE it. A real fleet is heterogeneous —
some efforts are a high-recall/low-precision model that over-claims (lies more),
some are a careful model whose commits occasionally don't land (flakes more), some
are a steady baseline. We model that as **per-effort failure profiles** carrying a
`vendor` label, and we run the SAME profile map through BOTH arms. The honesty
invariant is preserved verbatim: the open and closed loops still attempt the same
lies, in the same order, from the same seeds — the arms differ only in whether the
kernel BELIEVES the claim. The kernel never reads the `vendor` label (it cannot —
`oracle.is_shipped`/`arbiter.arbitrate` take a claim and a footprint, not an
identity); the label exists only so the *scorer* can attribute caught lies back to
the vendor that emitted them.

Why this is still simulated (not a live `gemini -p`): the same three reasons as
`agent.py` — determinism, hand-checkable lies, and "we are not measuring how often
Gemini lies." The profile *rates* are illustrative archetypes, not vendor
benchmarks; the claim we prove is the conditional one — *given* a mixed fleet at
these rates, DOS catches every banked falsehood and attributes it correctly,
regardless of which vendor label rides along. A live multi-CLI demo (the
unfalsifiable kind) lives separately in `live_demo.py`, fenced off from the
falsifiable A/B on purpose.
"""
from __future__ import annotations

import dataclasses

from .agent import FailureModel, Worker


# Illustrative vendor archetypes. These are NOT measured vendor lie-rates — they
# are three DISTINCT failure shapes (over-claimer / flaky / steady) wearing vendor
# labels, so the heterogeneous fleet exercises the kernel against efforts that fail
# in different ways at once. The names make the test legible ("the Gemini-flavored
# effort lied; DOS caught it"); the kernel is blind to the name. Rates sit in the
# same conservative band as agent.py's defaults (lie≈0.12) so the demo does not
# inflate DOS's value — a higher lie-rate would only make the closed loop look
# better.
VENDOR_ARCHETYPES: dict[str, dict[str, float]] = {
    # over-claimer: reports shipped more readily than it commits (high lie rate).
    "gemini":  {"lie_rate": 0.18, "flake_rate": 0.06, "thrash_rate": 0.05},
    # flaky executor: genuinely tries, but its commits silently fail more often
    # (high flake rate — an *honest* falsehood the oracle still catches by git).
    "codex":   {"lie_rate": 0.08, "flake_rate": 0.16, "thrash_rate": 0.05},
    # steady baseline: the conservative agent.py defaults.
    "claude":  {"lie_rate": 0.12, "flake_rate": 0.08, "thrash_rate": 0.05},
}


@dataclasses.dataclass(frozen=True)
class FleetProfile:
    """A per-effort failure-model map that is drop-in for a single `FailureModel`.

    Both arms bind workers with ``{e.name: model.worker(e.name) ...}``. A
    `FleetProfile` exposes the SAME ``worker(effort)`` method, so it substitutes
    for a `FailureModel` at that seam with ZERO change to either arm — that is the
    point: heterogeneity is injected entirely at the worker factory, the arms and
    the kernel are untouched.

    ``models``  — effort name → its own seeded `FailureModel`.
    ``vendors`` — effort name → its vendor label (for per-vendor attribution by the
                  scorer; the kernel never sees this).
    """

    models: dict[str, FailureModel]
    vendors: dict[str, str]

    def worker(self, effort: str) -> Worker:
        """Return the worker for ``effort`` from its OWN model — same interface as
        ``FailureModel.worker`` so the arms call it identically."""
        return self.models[effort].worker(effort)

    def vendor_of(self, effort: str) -> str:
        return self.vendors[effort]


def round_robin_fleet(
    effort_names: list[str], *, seed: int,
    vendors: tuple[str, ...] = ("claude", "gemini", "codex"),
) -> FleetProfile:
    """Assign vendor archetypes round-robin across the efforts.

    Each effort gets its own `FailureModel` seeded from the run seed XOR the
    effort's position, so efforts are independent yet the whole fleet is
    reproducible from one seed (the honesty invariant: same seed → same lies). The
    vendor archetype sets that effort's lie/flake/thrash rates.
    """
    models: dict[str, FailureModel] = {}
    assigned: dict[str, str] = {}
    for i, name in enumerate(effort_names):
        vendor = vendors[i % len(vendors)]
        rates = VENDOR_ARCHETYPES[vendor]
        # a per-effort seed so distinct efforts roll independently, but a pure
        # function of (seed, position) so the fleet is reproducible.
        models[name] = FailureModel(seed=seed ^ (i * 0x9E3779B1 & 0xFFFFFFFF), **rates)
        assigned[name] = vendor
    return FleetProfile(models=models, vendors=assigned)


def single_vendor_fleet(
    effort_names: list[str], vendor: str, *, seed: int,
) -> FleetProfile:
    """A homogeneous fleet where every effort wears the SAME vendor archetype.

    Used to prove the A/B's qualitative outcome (closed loop banks no lies; catches
    exactly what the open loop banked) is INVARIANT to which vendor the whole fleet
    is — i.e. swapping every Claude effort for a Gemini effort changes the numbers
    but not the verdict.
    """
    rates = VENDOR_ARCHETYPES[vendor]
    models = {
        name: FailureModel(seed=seed ^ (i * 0x9E3779B1 & 0xFFFFFFFF), **rates)
        for i, name in enumerate(effort_names)
    }
    return FleetProfile(models=models, vendors={n: vendor for n in effort_names})
