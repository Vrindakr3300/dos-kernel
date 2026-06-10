"""The pluggable loop-STOP policy seam — a host's "should a pending decision halt the loop?" call.

The dispatch scout (`dos.scout.choose`) has exactly ONE hardcoded STOP: rule 0,
`resource_blocked` — a measured can't-launch wall. Every other signal (an open
operator decision, a noisy scoreboard, a saturated `/unstick`) is **evidence
only, never a STOP** (the 2026-06-03 operator directive). That default is right
for the reference host, but it is a *policy*, and a different host may legitimately
want a different one: a `LIVENESS`/`OP_HALT` decision (a run hung RIGHT NOW,
burning budget) *should* stop its loop, while a `WEDGE`/soak decision should only
surface. Freezing that choice in the kernel is the wrong layer.

So the STOP-vs-surface call is a **pluggable seam**, exactly like `dos.judges`
(the adjudicator rung) and `dos.overlap_policies` (the disjointness scorer):

  * `StopPolicy` — the Protocol a host/driver implements (`name` + `decide`).
  * `StopVerdict` — a three-valued advisory ruling (STOP / DEFER / NEVER). DEFER
    = "no opinion, use the kernel default"; NEVER = "explicitly do not stop";
    STOP = "halt the loop." It mutates nothing — acting on it is the scout's job.
  * `NeverStopPolicy` — the built-in, unshadowable baseline: it DEFERs on
    everything, so with no policy wired the scout's behavior is byte-identical to
    today (evidence-only). The honest zero of the seam, like `AbstainJudge`.
  * `run_stop_policy` — the **fail-to-DEFER** wrapper: any raise / non-`StopVerdict`
    return becomes DEFER, never STOP. A buggy or hostile host policy can therefore
    never *manufacture* a halt by failing. The STOP analogue of `run_judge`'s
    fail-to-abstain (the safe direction for a halt-gate is "don't halt").
  * `stop_under_resource_floor` — the **AND-floor** guarantee: the kernel's
    `resource_blocked` STOP is the unforgeable floor. A policy is consulted ONLY
    when the floor does not already STOP, and a policy can only *add* a STOP on top
    of the floor — it can never suppress the `resource_blocked` halt. So a
    swappable STOP policy can only ever halt MORE than the kernel, never fewer
    (the dangerous direction — a hostile policy keeping a doomed loop alive past a
    measured resource wall — is structurally unreachable). Mirrors
    `overlap_policy.admissible_under_floor`.

Pure kernel seam (mechanism). The Protocol + verdict + wrappers + resolver live
here; every *ruling* policy with host/provider surface (one that reads the live
decision queue, calls a model, shells out) lives in a **driver**
(`dos.drivers.…`), discovered BY NAME at the call boundary — the kernel imports
no policy implementation (the `dos.drivers` litmus in CLAUDE.md). The scout takes
the resolved policy as an OPTIONAL input field and never resolves one itself, so
its pure default path is untouched.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# The three-valued ruling.
# ---------------------------------------------------------------------------


class StopStance(str, enum.Enum):
    """A STOP policy's three-valued ruling on whether the loop should halt.

    Three-valued by design (like `judges.Stance`): a binary stop/go would force a
    policy to take a side even when it has no opinion, and "no opinion" is exactly
    the common case (most iterations, the policy has nothing to say and the kernel
    default should apply). `DEFER` is that honest third answer.
    """

    STOP = "STOP"      # halt the loop now
    DEFER = "DEFER"    # no opinion — fall through to the kernel default (today: don't stop)
    NEVER = "NEVER"    # explicitly do NOT stop (a policy actively vetoing a halt-on-this)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class StopVerdict:
    """A STOP policy's frozen, advisory ruling. Three constructors, no other build path.

    Carries nothing that could mutate state (advisory-only by shape, like
    `JudgeVerdict`): the scout READS `should_stop` and decides; the policy never
    acts. `cause_key` is the closed token the scout stamps on a resulting STOP
    decision (so a test/operator sees which policy halted); `reason` is the
    one-line operator-facing prose.
    """

    _stance: StopStance
    reason: str = ""
    cause_key: str = "stop_policy"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    @property
    def stance(self) -> StopStance:
        return self._stance

    @property
    def should_stop(self) -> bool:
        """True iff this verdict halts the loop. DEFER and NEVER are both go."""
        return self._stance is StopStance.STOP

    @property
    def deferred(self) -> bool:
        """True iff the policy had no opinion (use the kernel default)."""
        return self._stance is StopStance.DEFER

    @classmethod
    def stop(cls, reason: str = "", *, cause_key: str = "stop_policy",
             evidence: tuple[str, ...] = ()) -> "StopVerdict":
        """Halt the loop. The one verdict a policy can NEVER reach by failing
        (see `run_stop_policy` — a failure degrades to DEFER, never STOP)."""
        return cls(_stance=StopStance.STOP, reason=reason, cause_key=cause_key,
                   evidence=tuple(evidence))

    @classmethod
    def defer(cls, reason: str = "", *, evidence: tuple[str, ...] = ()) -> "StopVerdict":
        """No opinion — use the kernel default. The conservative value every
        failure (raise / bad return) degrades to."""
        return cls(_stance=StopStance.DEFER, reason=reason, evidence=tuple(evidence))

    @classmethod
    def never(cls, reason: str = "", *, evidence: tuple[str, ...] = ()) -> "StopVerdict":
        """Explicitly do not stop on this (a policy vetoing a halt). Distinct from
        DEFER only in intent; both are 'go'. Cannot override the resource floor —
        the floor is checked BEFORE the policy is consulted."""
        return cls(_stance=StopStance.NEVER, reason=reason, evidence=tuple(evidence))


# ---------------------------------------------------------------------------
# The policy contract + the built-in baseline.
# ---------------------------------------------------------------------------


@runtime_checkable
class StopPolicy(Protocol):
    """The contract a host/driver implements to decide loop-STOP from scout state.

    ``name`` is the token `dos.toml`/`dos doctor` selects/lists. ``decide`` is
    handed the scout `state` (an opaque object — the policy reads the attributes it
    needs, e.g. `open_escalated_decisions`, off it; the type gives it nothing to
    mutate) and the active `config`, and returns a `StopVerdict`.

    A policy MAY do I/O *inside* ``decide`` (read the live `dos.decisions` queue,
    call a model, shell out) IFF it lives in a driver — the same allowance a ruling
    judge has, and the same reason it lives outside the kernel. The disciplines
    that keep it honest are NOT purity: they are fail-to-DEFER (`run_stop_policy`)
    and the resource floor (`stop_under_resource_floor`) — a failing policy can't
    halt, and no policy can suppress the measured `resource_blocked` STOP.
    """

    name: str

    def decide(self, state: object, config: object) -> StopVerdict:
        ...


class NeverStopPolicy:
    """The built-in, always-available policy: it DEFERs on everything.

    The STOP analogue of `AbstainJudge` / `PrefixOverlapPolicy` — a trusted
    baseline a plugin can never shadow (`resolve_stop_policy` resolves built-ins
    first). It is the honest zero of the seam: a workspace with NO policy wired
    still has a resolvable one, and it never halts the loop, so the scout's
    behavior is **byte-identical to before the seam** (the load-bearing default).
    """

    name = "never"

    def decide(self, state: object, config: object) -> StopVerdict:
        return StopVerdict.defer(
            "no STOP policy wired — the built-in policy defers, so an open "
            "decision is evidence-only (the kernel default)."
        )


# ---------------------------------------------------------------------------
# The fail-to-DEFER wrapper + the resource-floor AND.
# ---------------------------------------------------------------------------


def run_stop_policy(policy: StopPolicy, state: object, config: object) -> StopVerdict:
    """Run one STOP policy, enforcing **fail-to-DEFER**.

    The wrapper EVERY consumer calls instead of `policy.decide(...)` directly — it
    is what makes "a policy can never manufacture a halt by failing" structural:

      * a policy that **raises** (a bug, a model timeout, a torn queue read) →
        `DEFER`, naming the failure. Never propagates; never STOP.
      * a policy that returns **anything that is not a `StopVerdict`** (None, a
        dict, a duck-typed look-alike) → `DEFER`. We never read a foreign object's
        `should_stop`, so no halt sneaks through a wrong return type.

    The deliberate asymmetry with `admission.run_predicates` (which fails to
    *refuse*) and the symmetry with `judges.run_judge` (which fails to *abstain*):
    each role's safe failure is the one that takes NO consequential action. A
    STOP policy gates a halt, so its safe failure is "don't halt — defer."
    """
    name = getattr(policy, "name", type(policy).__name__)
    try:
        verdict = policy.decide(state, config)
    except Exception as e:  # fail-to-DEFER: a policy that raises cannot halt
        return StopVerdict.defer(
            f"stop policy {name!r} raised ({e!r}) — deferring (a halt-gate that "
            f"cannot answer never halts; it falls through to the kernel default)."
        )
    if not isinstance(verdict, StopVerdict):
        return StopVerdict.defer(
            f"stop policy {name!r} returned a {type(verdict).__name__}, not a "
            f"StopVerdict — deferring (a policy that does not return the verdict "
            f"type cannot be trusted to halt the loop)."
        )
    return verdict


def stop_under_resource_floor(
    policy: StopPolicy, state: object, config: object,
) -> StopVerdict:
    """Decide loop-STOP, AND-ed under the unforgeable `resource_blocked` floor.

    The structural soundness guarantee in one function (mirrors
    `overlap_policy.admissible_under_floor`). The kernel's `resource_blocked` STOP
    is the floor; a policy can only ever move toward MORE halting relative to it:

      * floor STOP (`state.resource_blocked` True) → the floor verdict is returned
        regardless of the policy. A hostile/buggy policy cannot even express a
        verdict that keeps a doomed loop alive past a measured resource wall — the
        dangerous cell is unreachable.
      * floor go, policy STOP → the policy's STOP (a host opted a decision class
        into halting — the safe, more-halting direction).
      * floor go, policy DEFER/NEVER → DEFER/NEVER (fall through to the scout's
        evidence-only default — today's behavior).
      * policy raises / wrong type → DEFER (via `run_stop_policy`; fail toward the
        default, never a spurious halt).

    `state` is read for `resource_blocked` / `resource_block_reason` by attribute
    (it is the scout `ScoutState`; we keep this module free of a scout import to
    avoid a cycle — scout imports stop_policy, not the reverse).
    """
    if getattr(state, "resource_blocked", False):
        why = getattr(state, "resource_block_reason", "") or "host cannot launch more work"
        return StopVerdict.stop(
            f"resource_blocked floor: {why}", cause_key="resource_blocked",
            evidence=(f"resource_blocked: {why}",),
        )
    return run_stop_policy(policy, state, config)


# ---------------------------------------------------------------------------
# Resolution — built-in first, then the `dos.stop_policies` entry-point group.
# ---------------------------------------------------------------------------

# The entry-point group a workspace/driver registers a STOP policy under.
STOP_POLICY_ENTRY_POINT_GROUP = "dos.stop_policies"

# The built-in policies, resolvable by name and UNSHADOWABLE by a plugin (a plugin
# registering `never` cannot displace this one — built-ins resolve first). Only the
# DEFER-everything baseline ships in the kernel; a queue-reading or model-backed
# policy lives in a driver/plugin.
_BUILT_IN_POLICIES: dict[str, type] = {
    NeverStopPolicy.name: NeverStopPolicy,
}


def _discover_entry_point_policies(*, _stderr=None) -> list[tuple[str, StopPolicy]]:
    """Find STOP policies registered under the `dos.stop_policies` group.

    A plugin registers ``name = "pkg.module:PolicyClass"`` in its
    ``[project.entry-points."dos.stop_policies"]``. We load each, instantiate it if
    it is a class, and return ``(name, policy)`` pairs sorted by name. A plugin
    that fails to load is skipped with a one-line stderr note rather than crashing
    a scout call — the same posture `_discover_entry_point_policies` (overlap) /
    judge discovery take."""
    stderr = _stderr if _stderr is not None else sys.stderr
    out: list[tuple[str, StopPolicy]] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=STOP_POLICY_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(STOP_POLICY_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash a call
        return out
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            obj = ep.load()
            policy = obj() if isinstance(obj, type) else obj
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: stop policy plugin {ep.name!r} failed to load ({e}); "
                f"skipping",
                file=stderr,
            )
            continue
        out.append((ep.name, policy))
    return out


def resolve_stop_policy(name: str, *, _stderr=None) -> StopPolicy:
    """Resolve a STOP policy by name: built-ins first, then `dos.stop_policies` plugins.

    Built-ins (`never`) resolve FIRST and cannot be shadowed by a plugin of the
    same name — the trusted-baseline guarantee, identical to `resolve_judge` /
    `resolve_overlap_policy`. An unknown name fails LOUD with the known list (it
    never silently degrades to `never`, which would hide a typo'd policy name): the
    caller asked for a specific policy and getting a different one silently is
    exactly the unannounced substitution the kernel refuses."""
    if name in _BUILT_IN_POLICIES:
        return _BUILT_IN_POLICIES[name]()
    discovered = dict(_discover_entry_point_policies(_stderr=_stderr))
    if name in discovered:
        return discovered[name]
    known = sorted(set(_BUILT_IN_POLICIES) | set(discovered))
    raise ValueError(
        f"unknown stop policy {name!r}; known: {', '.join(known)}"
    )


def active_stop_policy(*, config: object = None, _stderr=None) -> StopPolicy:
    """The STOP policy a CALLER threads into the scout (or None to use the default).

    Resolution: a workspace may name its policy in ``config.stop_policy_name`` (a
    `dos.toml [scout] stop_policy` data field); absent that, the built-in `never`
    baseline. Does ENTRY-POINT DISCOVERY (I/O) only when a non-`never` name is
    configured, so it is a CALL-BOUNDARY helper (the adapter that builds
    `ScoutState`), never called inside the pure `choose`. The pure default — no
    config, or `never` — returns the built-in with no discovery, so the hot path
    stays I/O-free, exactly as `active_overlap_policy` does.

    The pure `choose` never calls this; the adapter resolves the policy and passes
    it in as `ScoutState.stop_policy` (or leaves it None → the scout skips the rung
    entirely, byte-identical to before the seam)."""
    name = getattr(config, "stop_policy_name", None) if config is not None else None
    if not name or name == NeverStopPolicy.name:
        return NeverStopPolicy()
    return resolve_stop_policy(str(name), _stderr=_stderr)
