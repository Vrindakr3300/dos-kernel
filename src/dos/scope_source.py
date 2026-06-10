"""The scope-source seam — docs/117 Phase 4: distrust the declared EXTENT.

Why this exists
===============

`completion.classify` answers "is the WHOLE declared job verifiably done?" by
asking `resume` whether the residual (`declared − verified`) is empty. But that
question trusts ONE thing it should not: the **denominator**. `declared_steps`
comes from the run's own `INTENT` record — a self-report of *how big the job is*.
An agent that declares three steps, ships three, and stops has an empty residual
and looks `COMPLETE` — even if the real job had five. This is the completion
analogue of the disease the whole kernel is built against (`docs/103`): a verdict
computed from the judged agent's own narration of its scope.

A `ScopeSource` is the rung that distrusts the extent. It cross-checks the
declared steps against an **external** account of scope — the plan registry's
phase list, a PR's changed-files, an issue's acceptance criteria — and rules:
did the run declare the *whole* job, or under-declare it? Its verdict can only
make completion HARDER (withhold `COMPLETE`, surface `UNDERDECLARED`); it can
never grant completion. So "done means done against the *real* scope, not the
scope the agent chose to admit" becomes a kernel-checkable property — without
baking any host's notion of scope into the kernel.

The same seam shape, re-aimed at extent
=======================================

This module is the `overlap_policy` / `judges` apparatus pointed at scope:

  * a `ScopeSource` **Protocol** (the contract a driver implements),
  * a built-in **null** source `AllDeclaredScope` (always `extent_honest=True` —
    "trust the declared extent," i.e. *today's* behavior; the unshadowable
    baseline, the `PrefixOverlapPolicy` / `AbstainJudge` analogue),
  * `run_scope` (one source, fail-to-strict) and `honest_under_floor` (the
    conjunction over many — `extent_honest ⟺ every source agrees`),
  * a by-name **resolver** (built-ins first, unshadowable, fail-loud on unknown),
  * call-boundary entry-point **discovery** over the `dos.scope_sources` group.

The safe direction, by construction
====================================

The structural guarantee is the inverse of `overlap_policy`'s and *simpler* for
it. There the plugin returns a verdict that includes ADMIT (the dangerous,
false-*admit* direction), so a deterministic floor must be ANDed in to stop a
lying plugin from admitting a collision. Here the dangerous direction is a
false-*COMPLETE*, and a `ScopeSource` can only ever push toward the SAFE side —
it withholds completion. So no competing deterministic floor is needed: the
conjunction alone is the guarantee.

  > A wired `ScopeSource` may turn a `COMPLETE` into `UNDERDECLARED`. It can
  > never turn an `UNDERDECLARED` (or an `INCOMPLETE`) into `COMPLETE`.

`completion.classify` grants `COMPLETE` only as
``residual_empty AND honest_under_floor(scope_verdicts).extent_honest``. With no
source wired, `honest_under_floor(())` is honest, so completion is **byte-for-byte
today's "all declared verified" floor**. Each wired source can only flip an
`extent_honest` from True to False — strictly stricter. And `run_scope` converts
any raise / malformed return to `extent_honest = False` (the judge fail-to-ABSTAIN
analogue, biased toward *refusing completion*): a buggy or hostile source surfaces
a decision rather than silently certifying done. The `AllDeclaredScope` baseline is
the one source a plugin can never displace (the resolver returns built-ins first),
so the floor — "trust the declared extent" — is always reachable and never forgeable
away.

Purity & layering
=================

Pure stdlib — a Protocol, a built-in null source, the conjunction helpers, a
resolver. No host names, no I/O inside a verdict. It sits in the kernel beside
`overlap_policy` / `judges` (which likewise hold a pure protocol + resolver while
real *implementations* live outside). A source MAY do I/O *inside* `scope_verdict`
(read the plan registry, shell `git`, call an API) IFF it lives in a **driver** —
the JUDGE-rung allowance — but the kernel's own `AllDeclaredScope` does not.
Entry-point discovery (the one bit of I/O) happens at the call boundary in
`active_scope_sources`, exactly as `active_overlap_policy` / `active_judges` /
`active_predicates` do. The `dos.drivers` litmus (no `src/dos/*` except `drivers/`
imports `dos.drivers`) covers the real sources.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from dos.intent_ledger import LedgerState


# ───────────────────────────── the scope verdict ──────────────────────────────
@dataclass(frozen=True)
class ScopeVerdict:
    """One `ScopeSource`'s ruling on a run's DECLARED extent.

    ``extent_honest`` is the load-bearing boolean: True iff the source believes the
    run declared the *whole* job (the residual's denominator was not understated).
    False means the run under-declared — there is real scope it never put on the
    books, so an empty residual does NOT mean done. ``reason`` is the operator-facing
    one-liner. ``missing`` is the optional, legibility-only list of scope the source
    found beyond the declared steps (e.g. plan phases not in `declared_steps`) — it
    is carried into the `UNDERDECLARED` reason so a human sees *what* was omitted,
    but the verdict turns on ``extent_honest`` alone. ``source`` names the ruling
    source (for the surfaced reason / the decisions queue).

    The asymmetry is the point and mirrors the seam: an honest verdict permits
    `COMPLETE` (subject to every other source also agreeing); a dishonest one
    withholds it. A source can move the verdict only toward `UNDERDECLARED`.
    """

    extent_honest: bool
    reason: str
    source: str = ""
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "extent_honest": self.extent_honest,
            "reason": self.reason,
            "source": self.source,
            "missing": list(self.missing),
        }


@runtime_checkable
class ScopeSource(Protocol):
    """The contract a driver implements to distrust a run's declared extent.

    ``name`` is the token `dos doctor` lists and a `--scope-source <name>` selects.
    ``scope_verdict`` is handed the run's `LedgerState` (it reads `declared_steps`
    and `goal`/`plan`/`phase` — the *declared* extent) + the active ``config``
    (read-only — it reads policy / locates the external account of scope, but the
    type gives it nothing to mutate) and returns a `ScopeVerdict`.

    A source MAY do I/O *inside* ``scope_verdict`` (read the plan registry, shell
    out to `git`, call an issue tracker) — unlike a predicate or a renderer, which
    are pure — IFF it lives in a driver, the same reason a ruling judge does. The
    discipline that keeps it honest is NOT purity; it is the conjunction
    (`honest_under_floor`) + fail-to-strict (`run_scope`): whatever a source
    returns, `COMPLETE` requires EVERY source to vote honest, and a raise / bad
    return is read as *dishonest*, so a source is structurally unable to grant
    completion — only to withhold it.
    """

    name: str

    def scope_verdict(self, state: LedgerState, config: object) -> ScopeVerdict:
        ...


class AllDeclaredScope:
    """The built-in null source: trust the declared extent (today's behavior).

    Always returns ``extent_honest=True`` — it asserts that whatever the run
    declared IS the whole job. With only this source (or none) wired, completion is
    **byte-for-byte identical to before the seam**: `honest_under_floor` is honest,
    so `classify` grants `COMPLETE` purely on the empty residual, exactly as it did
    in Phase 1. It is the unshadowable baseline a plugin can never displace
    (`resolve_scope_source` resolves built-ins first) — the scope analogue of the
    unshadowable `prefix` policy / `abstain` judge / `text` renderer.

    It does no I/O and reads nothing external — it is the *absence* of a scope
    check, made explicit as an object so "no source wired" and "the null source"
    are the same code path.
    """

    name = "all-declared"

    def scope_verdict(self, state: LedgerState, config: object) -> ScopeVerdict:
        return ScopeVerdict(
            extent_honest=True,
            reason="declared extent trusted (no external scope check wired)",
            source=self.name,
        )


# The unshadowable baseline instance — pure, stateless, reused.
_NULL_SOURCE = AllDeclaredScope()


def run_scope(source: ScopeSource, state: LedgerState, config: object) -> ScopeVerdict:
    """Run ONE `ScopeSource`, converting any misbehavior to a DISHONEST verdict.

    The fail-to-strict boundary (the judge `run_judge` analogue, biased toward
    *refusing completion*). A source that raises, or returns something that is not a
    `ScopeVerdict`, is mapped to ``extent_honest=False`` — we withhold `COMPLETE`
    and surface `UNDERDECLARED` rather than risk certifying done on a broken scope
    check. This is the conservative direction for "are we done": a source failing
    open (→ honest → COMPLETE) would let a crashing scope check silently grant
    completion, exactly the unannounced trust the kernel refuses.

    A source that returns a well-formed honest/dishonest verdict is passed through
    verbatim (its ``reason``/``missing`` carried for the operator).
    """
    name = getattr(source, "name", type(source).__name__)
    try:
        verdict = source.scope_verdict(state, config)
    except Exception as e:  # fail-to-strict: a raising source withholds COMPLETE
        return ScopeVerdict(
            extent_honest=False,
            reason=(f"scope source {name!r} raised ({e!r}) — withholding COMPLETE "
                    f"(failing to UNDERDECLARED, the conservative direction)"),
            source=name,
        )
    if not isinstance(verdict, ScopeVerdict):
        # Never read a foreign object's `.extent_honest` — a wrong return type cannot
        # be trusted to grant completion. Treat as dishonest (withhold COMPLETE).
        return ScopeVerdict(
            extent_honest=False,
            reason=(f"scope source {name!r} returned a {type(verdict).__name__}, not "
                    f"a ScopeVerdict — withholding COMPLETE (conservative)"),
            source=name,
        )
    return verdict


@dataclass(frozen=True)
class ScopeConjunction:
    """The combined extent ruling over many sources — `extent_honest` + the why.

    ``extent_honest`` is the AND over every source's vote. ``verdicts`` are the
    individual rulings (so a reader sees who voted what); ``dishonest`` is the
    subset that withheld completion (empty iff honest). ``missing`` is the union of
    all flagged-missing scope (deduped, order-preserving) — what `classify` folds
    into the `UNDERDECLARED` reason."""

    extent_honest: bool
    verdicts: tuple[ScopeVerdict, ...] = ()
    dishonest: tuple[ScopeVerdict, ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        if self.extent_honest:
            n = len(self.verdicts)
            return (f"declared extent confirmed honest by {n} scope source(s)"
                    if n else "declared extent trusted (no scope source wired)")
        names = ", ".join(sorted({v.source for v in self.dishonest if v.source}))
        miss = f" (missing: {', '.join(self.missing)})" if self.missing else ""
        return (f"declared extent under-declared per scope source(s) "
                f"[{names or 'unnamed'}]{miss}")


def honest_under_floor(verdicts: tuple[ScopeVerdict, ...]) -> ScopeConjunction:
    """Combine scope verdicts: ``extent_honest`` iff EVERY source votes honest.

    The structural soundness guarantee in one function — the inverse of
    `overlap_policy.admissible_under_floor` and simpler, because here the dangerous
    direction (false-COMPLETE) is the one a source *cannot reach*:

      * no verdicts → honest (the floor: with nothing wired, the declared extent is
        trusted — today's behavior, the `AllDeclaredScope` baseline).
      * all honest → honest (every source agrees the extent was the whole job).
      * ANY dishonest → DISHONEST (one source flagging under-declaration withholds
        `COMPLETE`; the others cannot out-vote it — a source can only push toward
        `UNDERDECLARED`, never away from it).

    So a wired source can only ever move completion toward `UNDERDECLARED`. There is
    no AND-with-a-floor as in `overlap_policy` because withholding is already the
    safe side: the conjunction itself IS the guarantee. (`run_scope` should be
    applied to each source BEFORE this, so a raising source is already a dishonest
    verdict here — fail-to-strict composes with the conjunction.)"""
    vs = tuple(verdicts)
    dishonest = tuple(v for v in vs if not v.extent_honest)
    # Union of flagged-missing scope across dishonest sources, order-preserving + deduped.
    seen: set[str] = set()
    missing: list[str] = []
    for v in dishonest:
        for m in v.missing:
            if m not in seen:
                seen.add(m)
                missing.append(m)
    return ScopeConjunction(
        extent_honest=not dishonest,
        verdicts=vs,
        dishonest=dishonest,
        missing=tuple(missing),
    )


# ---------------------------------------------------------------------------
# Resolution — built-in first, then the `dos.scope_sources` entry-point group.
# ---------------------------------------------------------------------------

# The entry-point group a workspace/researcher registers a scope source under.
SCOPE_SOURCE_ENTRY_POINT_GROUP = "dos.scope_sources"

# The built-in sources, resolvable by name and UNSHADOWABLE by a plugin (a plugin
# registering `all-declared` cannot displace this one — built-ins resolve first).
# Only the null baseline ships in the kernel; every real source (plan-registry,
# changed-files, acceptance-criteria) lives in a driver/plugin.
_BUILT_IN_SOURCES: dict[str, type] = {
    AllDeclaredScope.name: AllDeclaredScope,
}


def _discover_entry_point_sources(*, _stderr=None) -> list[tuple[str, ScopeSource]]:
    """Find scope sources registered under the `dos.scope_sources` group.

    A source plugin registers ``name = "pkg.module:SourceClass"`` in its
    ``[project.entry-points."dos.scope_sources"]``. We load each, instantiate it if
    it is a class, and return ``(entry_point_name, source)`` pairs sorted by name
    (stable, so `dos doctor` order is deterministic). A plugin that fails to load is
    skipped with a one-line stderr note rather than crashing completion — the same
    posture overlap-policy / judge / predicate discovery take."""
    stderr = _stderr if _stderr is not None else sys.stderr
    out: list[tuple[str, ScopeSource]] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=SCOPE_SOURCE_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(SCOPE_SOURCE_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash a call
        return out
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            obj = ep.load()
            source = obj() if isinstance(obj, type) else obj
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: scope source plugin {ep.name!r} failed to load ({e}); "
                f"skipping",
                file=stderr,
            )
            continue
        out.append((ep.name, source))
    return out


def resolve_scope_source(name: str, *, _stderr=None) -> ScopeSource:
    """Resolve a scope source by name: built-ins first, then plugins.

    Built-ins (`all-declared`) resolve FIRST and cannot be shadowed by a plugin of
    the same name — the trusted-baseline guarantee, identical to
    `resolve_overlap_policy` / `resolve_judge`. An unknown name fails LOUD with the
    known list (it never silently degrades to `all-declared`, which would hide a
    typo'd source name): the caller asked for a specific scope check and getting a
    different one silently is the unannounced substitution the kernel refuses."""
    if name in _BUILT_IN_SOURCES:
        return _BUILT_IN_SOURCES[name]()
    discovered = dict(_discover_entry_point_sources(_stderr=_stderr))
    if name in discovered:
        return discovered[name]
    known = sorted(set(_BUILT_IN_SOURCES) | set(discovered))
    raise ValueError(
        f"unknown scope source {name!r}; known: {', '.join(known)}"
    )


def active_scope_sources(*, config: object = None, _stderr=None) -> list[ScopeSource]:
    """The scope sources a CALLER threads into `completion.classify`.

    Resolution: a workspace may name its sources in ``config.scope_source_names``
    (a list — the `dos.toml [completion] scope_sources` data field); absent that, an
    EMPTY list (NOT the null source) so the default path runs no source and is
    byte-identical to today (`honest_under_floor(())` is honest). Does ENTRY-POINT
    DISCOVERY (I/O) when names are configured, so it is a CALL-BOUNDARY helper (the
    CLI's `cmd_complete`, `dos doctor`), never called inside the pure `classify`. The
    pure default — no config — returns `[]` with no discovery, so completion's hot
    path stays I/O-free, exactly as `built_in_predicates` / `active_overlap_policy`.

    Returning `[]` (not `[AllDeclaredScope()]`) by default is deliberate: an empty
    list and the null source produce the SAME verdict (honest), and `[]` keeps the
    default truly side-effect-free (no discovery, no per-source call). The null
    source exists for an operator who wants to name it explicitly / for the resolver
    floor, not as the implicit default population."""
    names = getattr(config, "scope_source_names", None) if config is not None else None
    if not names:
        return []
    out: list[ScopeSource] = []
    for nm in names:
        out.append(resolve_scope_source(str(nm), _stderr=_stderr))
    return out


def active_scope_source_names(*, _stderr=None) -> list[str]:
    """The names of every resolvable scope source (built-in + discovered) — what
    `dos doctor` lists so an operator can see which extent checks completion could
    use (the scope analogue of "see the active predicates / judges / policies")."""
    built = list(_BUILT_IN_SOURCES)
    discovered = [n for n, _s in _discover_entry_point_sources(_stderr=_stderr)]
    return built + discovered
