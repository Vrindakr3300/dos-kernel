"""dos.drivers.plan_scope — a reference `ScopeSource` (outside the kernel line).

The kernel ships the scope-source SEAM (`dos.scope_source`: the `ScopeSource`
Protocol, the `ScopeVerdict`, the `honest_under_floor` conjunction, the null
`AllDeclaredScope` baseline, the resolver) but NO *ruling* source — exactly as it
ships the judge seam but no ruling judge, and the overlap seam but no model-backed
scorer. A source that consults an EXTERNAL account of scope is a JUDGE-rung
adjudicator (it reads the world, it is not pure), so it lives **here, in a
driver** — outside the kernel boundary, where I/O is allowed
(`drivers/__init__.py`: "they import the kernel; the kernel never imports them").

What this source does
=====================

`PlanScopeSource` cross-checks a run's **declared** extent (`state.declared_steps`,
the self-reported denominator of the residual) against an **expected** set of
units — the *real* scope, supplied from outside the run. The expected set is the
external account the kernel must not trust the agent to report honestly:

  * **Where it comes from.** `config.expected_scope_steps` — a workspace declares
    its real phase list in `dos.toml` (`[completion] expected_scope`), or a host
    driver injects it from its plan registry (the phase list of the plan the run is
    executing). This driver is agnostic about the source; it reads the iterable off
    the config it is handed.
  * **The ruling.** If every expected unit appears in `declared_steps`, the extent
    is honest → `extent_honest=True` (the run put the whole job on the books). If
    any expected unit is MISSING from the declared steps, the run under-declared →
    `extent_honest=False`, carrying the missing units. Fed into
    `completion.classify`, that flips an otherwise-`COMPLETE` run to
    `UNDERDECLARED`: the residual is empty, but it was measured against too small a
    denominator.

This is the canonical Gap-B example from docs/117 §5.3 ("diff the declared steps
against the plan registry's phase list"), made concrete and deterministic.

Why it is a driver, not the kernel
==================================

It reads `config` to LOCATE the external scope and (in the host-injected case) the
plan registry is itself read from disk — that is the I/O a kernel verdict may not
do. The discipline that keeps it safe is the seam's, not purity: a `ScopeSource`
can only ever WITHHOLD `COMPLETE` (the conjunction + `run_scope` fail-to-strict
guarantee it), so even a buggy or lying scope source surfaces an `UNDERDECLARED`
decision rather than silently certifying done. The kernel imports nothing from
here; `completion.classify` takes the `ScopeVerdict` this produces as data.

Wiring it
=========

Register it under the `dos.scope_sources` entry-point group, then a workspace names
it in `dos.toml [completion] scope_sources = ["plan"]`; the CLI boundary resolves
it via `scope_source.active_scope_sources` and threads the verdict into
`completion.classify`. Or construct it directly and pass its verdict in (what the
tests do). The entry-point name is conventionally ``plan``.
"""

from __future__ import annotations

from typing import Iterable, Optional

# Imports the kernel — never the other way round (the driver rule).
from dos.intent_ledger import LedgerState
from dos.scope_source import ScopeVerdict


def _expected_from_config(config: object) -> Optional[tuple[str, ...]]:
    """The expected (real) scope unit ids, read off the config (the data seam).

    Reads ``config.expected_scope_steps`` when present and iterable; returns it as a
    tuple of str. Returns ``None`` when the config carries no expected scope at all —
    the "I have no external account to check against" case, which the source treats
    as *honest* (it cannot claim under-declaration it has no evidence for; that would
    refuse completion for every run on a workspace that simply did not declare an
    expected set). Defensive on purpose — a malformed value yields ``None`` rather
    than crashing the completion path, the warn-and-fall-back posture every config
    axis takes."""
    raw = getattr(config, "expected_scope_steps", None)
    if raw is None:
        return None
    try:
        return tuple(str(x) for x in raw)
    except TypeError:
        return None


class PlanScopeSource:
    """A reference `ScopeSource`: declared steps vs an expected phase list.

    `name` is ``plan`` — the token a workspace names in `dos.toml [completion]
    scope_sources` and `dos doctor` lists. `scope_verdict` reads the expected scope
    off the config and diffs it against `state.declared_steps`.
    """

    name = "plan"

    def __init__(self, expected: Optional[Iterable[str]] = None) -> None:
        """`expected` lets a host inject the real scope directly (e.g. from its plan
        registry) instead of via config — the tuple takes precedence over
        ``config.expected_scope_steps`` when both are present. With neither, the
        source has no external account and votes honest (see `_expected_from_config`).
        """
        self._expected: Optional[tuple[str, ...]] = (
            tuple(str(x) for x in expected) if expected is not None else None
        )

    def scope_verdict(self, state: LedgerState, config: object) -> ScopeVerdict:
        expected = self._expected
        if expected is None:
            expected = _expected_from_config(config)
        if expected is None:
            # No external account of scope → nothing to contradict the declaration.
            # Vote honest (the source has no evidence of under-declaration).
            return ScopeVerdict(
                extent_honest=True,
                reason="no expected scope configured — declared extent not contested",
                source=self.name,
            )
        declared = set(state.declared_steps)
        missing = tuple(u for u in expected if u not in declared)
        if not missing:
            return ScopeVerdict(
                extent_honest=True,
                reason=(f"all {len(expected)} expected unit(s) are in the declared "
                        f"extent — the whole job was put on the books"),
                source=self.name,
            )
        return ScopeVerdict(
            extent_honest=False,
            reason=(f"{len(missing)} expected unit(s) absent from the declared extent "
                    f"— the run under-declared its scope"),
            source=self.name,
            missing=missing,
        )
