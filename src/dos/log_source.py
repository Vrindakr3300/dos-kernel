"""The log-source seam — pluggable log adapters, sorted by who authored the byte.

docs/117 — the log-specific sequel to docs/93 (the accountability spectrum for
non-git sources) and docs/95 (OS-level evidence). It answers the objection that
sinks a naive "native log adapters" feature: *an LLM already runs a program and
reads its log — what does routing logs through DOS add?* The answer is the whole
kernel thesis restated for one input — **a log is only evidence when the party that
authored the bytes is not the party being judged.** When an agent runs a program and
reads its own log, the agent is simultaneously the actor and the witness; the log it
surfaces is a self-report wearing evidence's clothes (the docs/103 distrust-the-
self-report law, the docs/84 §3.1 forgeable floor). A log climbs to *evidence* only
when the bytes are authored elsewhere: the kernel (not the agent) launched the
process and read the OS exit code, or the bytes are an infrastructure fossil the
agent cannot author (a cloud audit trail, a CI record, a privileged journald tree).

This module is the **pure seam** the log backends plug into — field-for-field the
shape `judges` (the JUDGE rung) and `overlap_policy` (the disjointness scorer)
already proved: a Protocol, frozen value types, an unshadowable built-in baseline, a
by-name resolver over an entry-point group, and a fail-safe runner. Every *backend*
with real I/O surface (read a file, shell `journalctl`, call the CloudWatch API)
lives in a `drivers/*` module — it imports the kernel; the kernel never imports it
(the `drivers/__init__` rule, pinned by `tests/test_log_source.py`). The kernel ships
only the abstraction + the honest zero, exactly as it ships the `Judge` protocol +
`AbstainJudge` while every ruling judge lives in a driver.

The one idea that makes this a *verification* seam and not a log-aggregation library
=================================================================================

Every `LogSource` declares its **`accountability`** — where it sits on the docs/93
spectrum — as DATA on the source, never inferred from content. That tag is what makes
the docs/117 §2 *inversion law* structural rather than a convention a host must
remember:

  * `AGENT_AUTHORED` — the floor. The agent (or a process it controls) wrote these
    bytes: a pasted terminal buffer, the agent's own stdout, a `screen`/`tmux`
    scrollback, a local app log. Convenient to ingest (~zero effort) and worthless as
    ground truth for exactly that reason — the agent chose every byte that reached
    here. A consumer routes this to a **JUDGE** (advisory, fail-to-abstain — `judges`),
    a *hint*, never a deterministic verdict.
  * `OS_RECORDED` — the OS authored it: a kernel-launched process's exit code +
    captured stream (the docs/117 §5 acceptance prize), a privileged journald/Event-Log
    tree the agent can't write. The agent cannot forge an OS exit status or backdate a
    root-gated log entry. A consumer may ground an **oracle** verdict on it.
  * `THIRD_PARTY` — infrastructure the agent does not control authored it: a cloud
    audit trail, a load-balancer access log, a CI build record. Hard to ingest (API +
    auth + parse) and the highest-value source for exactly that reason — a deploy or a
    served request leaves *only* this fossil. An **oracle** verdict.

The *flexibility* lives in which source you wire (the provenance / which-signal); the
*adjudication* — JUDGE-vs-oracle — is a fixed function of the declared tag. That is the
docs/76 line held exactly, and it means a buggy or over-eager host cannot accidentally
promote a pasted log into a verdict: an `AGENT_AUTHORED` source has no path to the
oracle classifier by construction.

The inversion law, in one sentence (docs/117 §2)
================================================

A log's ingestion-ease is *inversely* proportional to its evidentiary value, because
both are governed by the same variable: proximity to the agent. The sources easiest
to ingest (paste, own stdout) are the floor; the sources hardest to ingest (cloud
trails) are the strongest. So this seam is organized by `accountability`, never by
convenience — the convenient sources still get backends, but they self-declare the
floor rung and route to a judge.

Purity & layering
=================

Pure stdlib — an enum, two frozen value types, a built-in source that is always
unreachable, and resolver/runner helpers. NO provider surface, no I/O inside a
verdict, names no host. It sits in the kernel layer beside `judges`/`overlap_policy`/
`render` (which likewise hold a pure protocol + resolver while the implementations
live outside). Entry-point discovery (the one bit of I/O) happens at the call boundary
in `active_log_sources`, exactly as `active_judges` / `active_predicates` do.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class Accountability(str, enum.Enum):
    """Where a log source sits on the docs/93 accountability spectrum.

    Carried as DATA on each `LogSource` (a declared property, never inferred from the
    bytes), so a consumer routes by the tag and the docs/117 §2 inversion law is
    structural: an `AGENT_AUTHORED` source physically cannot reach an oracle verdict
    path. `str`-valued so it round-trips through a CLI token / JSON without a lookup
    table (the `Liveness` / `Stance` idiom).

    Ordered floor → strongest. The dangerous direction is "treat an agent-authored log
    as if the OS or a third party wrote it" — so the tag a source declares is the
    *ceiling* on how much a consumer may trust it, never a floor a consumer may raise.
    """

    AGENT_AUTHORED = "AGENT_AUTHORED"  # the agent/its process wrote it — JUDGE hint only
    OS_RECORDED = "OS_RECORDED"        # the OS authored it (exit code, privileged journald)
    THIRD_PARTY = "THIRD_PARTY"        # infra the agent can't write (cloud trail, CI, LB log)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_agent_authored(self) -> bool:
        """True iff this is the forgeable floor — a JUDGE hint, never a verdict source.

        The one predicate a consumer needs to honor the inversion law: route
        `is_agent_authored` evidence to a judge (advisory), everything else may ground
        an oracle. Named so the routing reads in plain words at the call site
        (`if ev.accountability.is_agent_authored: feed_a_judge(...)`).
        """
        return self is Accountability.AGENT_AUTHORED


@dataclass(frozen=True)
class LogEvidence:
    """Frozen, caller-gathered log facts — the `verdict.py` Evidence half, for logs.

    The `CiEvidence` / `ProgressEvidence` analogue: facts gathered at the boundary
    (inside a backend's `gather`) and handed to a consuming verdict, which is pure.

      source_name    — the backend that produced this (`"paste"`, `"cloudwatch"`),
                       for the operator-facing reason + the JSON consumer.
      accountability — the source's spectrum rung (above). The load-bearing field:
                       a consumer routes JUDGE-vs-oracle off this, never off content.
      lines          — the pulled log lines, in source order. Empty on a degrade.
      reachable      — was the source actually reached and read? **Defaults to
                       False** — the fail-safe zero: an evidence object that nobody
                       successfully populated reads as "no signal," never as an empty-
                       but-trusted log. A consumer treats `reachable=False` as
                       NO_SIGNAL/abstain, the honest floor a non-git artifact oracle
                       (the move-B driver template) degrades to.
      detail         — a one-line human note (why unreachable, or what was read), for
                       the reason string / `dos doctor` — legible distrust.

    Two constructors make the two outcomes unmistakable and keep the fail-safe default
    from being fat-fingered: `reached(...)` for a successful read, `no_signal(...)` for
    every degrade. There is deliberately no third way to set `reachable=True`.
    """

    source_name: str
    accountability: Accountability
    lines: tuple[str, ...] = field(default_factory=tuple)
    reachable: bool = False
    detail: str = ""

    @classmethod
    def reached(
        cls,
        source_name: str,
        accountability: Accountability,
        lines: tuple[str, ...],
        *,
        detail: str = "",
    ) -> "LogEvidence":
        """The source was reached and read. The ONLY constructor that sets
        `reachable=True` — so a reachable log is always a deliberate, populated read,
        never an accident of the default."""
        return cls(
            source_name=source_name,
            accountability=accountability,
            lines=tuple(lines),
            reachable=True,
            detail=detail,
        )

    @classmethod
    def no_signal(
        cls,
        source_name: str,
        accountability: Accountability,
        *,
        detail: str = "",
    ) -> "LogEvidence":
        """The source could not be reached/read — the honest floor (no source wired,
        auth failed, timeout, empty). `reachable=False`, no lines. What every failure
        in `gather_log` degrades to, and what a consuming verdict reads as
        NO_SIGNAL/abstain — never a fabricated pass (the `run_judge`
        fail-safe-never-fail-open discipline)."""
        return cls(
            source_name=source_name,
            accountability=accountability,
            lines=(),
            reachable=False,
            detail=detail,
        )

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "accountability": self.accountability.value,
            "lines": list(self.lines),
            "reachable": self.reachable,
            "detail": self.detail,
        }


@runtime_checkable
class LogSource(Protocol):
    """The contract a backend implements to add a log adapter.

    `name` is the token a resolver selects and `dos doctor` would list.
    `accountability` is the source's declared spectrum rung — a CLASS-LEVEL property,
    fixed by the backend, not chosen per call (a `paste` source is `AGENT_AUTHORED`
    always; it has no honest path to a higher rung). `gather` is handed a `subject`
    (an opaque correlation handle — a run-id, a commit SHA, a unit name; the backend
    decides what it means) and the active `config` (read-only), and returns a
    `LogEvidence`.

    A backend MAY do I/O *inside* `gather` (read a file, shell `journalctl`, call an
    API) — unlike a predicate or renderer, which are pure. That is exactly why a real
    backend lives in a driver, outside the kernel boundary: this seam is where I/O
    surface is allowed, the same latitude the `Judge` protocol gives a ruling judge.
    The discipline that keeps it honest is not purity but **fail-safe** (enforced by
    `gather_log`, below, not by trusting the backend) plus the **fixed accountability
    tag** (a backend cannot lie its way up the spectrum at call time).
    """

    name: str
    accountability: Accountability

    def gather(self, subject: str, config: object) -> LogEvidence:
        ...


class NullLogSource:
    """The built-in, always-available source: it reaches nothing.

    The log analogue of the `text` renderer / `AbstainJudge` — a trusted, unshadowable
    fallback (`resolve_log_source` resolves built-ins first). It is the honest zero of
    the seam: a workspace with NO log adapter wired still has a resolvable source, and
    it returns `no_signal` for every subject (the safe, conservative behavior — a
    consumer sees "no log signal," never a fabricated read).

    Tagged `AGENT_AUTHORED` — the floor — so that even the *absence* of a real source
    can never be mistaken for a trustworthy rung: the most a missing adapter can claim
    is the least-trusted tag, and it is unreachable on top of that.
    """

    name = "null"
    accountability = Accountability.AGENT_AUTHORED

    def gather(self, subject: str, config: object) -> LogEvidence:
        return LogEvidence.no_signal(
            self.name,
            self.accountability,
            detail=(
                "no log adapter wired — the built-in null source reaches nothing, so "
                "this subject has no log signal (configure a dos.log_sources backend)."
            ),
        )


def gather_log(source: LogSource, subject: str, config: object) -> LogEvidence:
    """Run one source against one subject, enforcing **fail-safe, never fail-open**.

    The wrapper EVERY consumer should call instead of `source.gather(...)` directly —
    it is what makes "a backend can never manufacture a trusted log by failing" a
    structural guarantee rather than a hope (the `run_judge` discipline, restated for
    logs):

      * a source that **raises** (file missing, API timeout, a bug) → an unreachable
        `no_signal` naming the failure. Never propagates; never a reachable read.
      * a source that returns **anything that is not a `LogEvidence`** (None, a dict, a
        list of lines, a duck-typed look-alike) → `no_signal`. We never read a foreign
        object's `.reachable`/`.lines`, so no fabricated read can sneak through a wrong
        return type.

    The degrade preserves the source's declared `accountability` so a consumer still
    routes correctly even on failure (an unreachable `THIRD_PARTY` source is still not
    a judge hint — it is an oracle source that had no signal this time). The tag is
    read defensively (`getattr`, defaulting to the floor) so even a malformed source
    object cannot escape to a higher rung via the failure path.

    Note the direction matches `run_judge` (an evidence/adjudication gatherer), not
    `admission.run_predicates` (a safety gate):
    a log source is *evidence-gathering*, so its safe failure is "no signal" (let the
    consuming verdict abstain / report NO_SIGNAL), never "deny" and never "pass."
    """
    name = getattr(source, "name", type(source).__name__)
    acct = getattr(source, "accountability", Accountability.AGENT_AUTHORED)
    if not isinstance(acct, Accountability):
        acct = Accountability.AGENT_AUTHORED
    try:
        ev = source.gather(subject, config)
    except Exception as e:  # fail-safe: a source that raises produces no signal
        return LogEvidence.no_signal(
            str(name),
            acct,
            detail=(
                f"log source {name!r} raised ({e!r}) — no signal (an evidence "
                f"gatherer that cannot read produces NO_SIGNAL, never a fabricated log)."
            ),
        )
    if not isinstance(ev, LogEvidence):
        return LogEvidence.no_signal(
            str(name),
            acct,
            detail=(
                f"log source {name!r} returned a {type(ev).__name__}, not a "
                f"LogEvidence — no signal (a source that does not return the evidence "
                f"type cannot be trusted to have read anything)."
            ),
        )
    return ev


# ---------------------------------------------------------------------------
# Resolution — built-in first, then the `dos.log_sources` entry-point group.
# ---------------------------------------------------------------------------

# The entry-point group a workspace/researcher registers a log backend under.
LOG_SOURCE_ENTRY_POINT_GROUP = "dos.log_sources"

# The built-in sources, resolvable by name and UNSHADOWABLE by a plugin (a plugin
# registering `null` cannot displace this one — built-ins resolve first). Only the
# conservative `null` baseline ships in the kernel; every reading backend lives in a
# driver/plugin (the kernel has no I/O/provider surface).
_BUILT_IN_SOURCES: dict[str, type] = {
    NullLogSource.name: NullLogSource,
}


def _discover_entry_point_sources(*, _stderr=None) -> list[tuple[str, LogSource]]:
    """Find log backends registered under the `dos.log_sources` entry-point group.

    A backend plugin registers ``name = "pkg.module:SourceClass"`` in its
    ``[project.entry-points."dos.log_sources"]``. We load each, instantiate it if it
    is a class, and return ``(entry_point_name, source)`` pairs sorted by name (stable,
    so listing order is deterministic). A plugin that fails to load is skipped with a
    one-line stderr note rather than crashing — the same posture
    `judges._discover_entry_point_judges` / predicate / renderer discovery take (a
    broken third-party plugin is the operator's to fix, not a kernel fault).
    """
    stderr = _stderr if _stderr is not None else sys.stderr
    out: list[tuple[str, LogSource]] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=LOG_SOURCE_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(LOG_SOURCE_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash a call
        return out
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            obj = ep.load()
            source = obj() if isinstance(obj, type) else obj
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: log source plugin {ep.name!r} failed to load ({e}); skipping",
                file=stderr,
            )
            continue
        out.append((ep.name, source))
    return out


def resolve_log_source(name: str, *, _stderr=None) -> LogSource:
    """Resolve a log source by name: built-ins first, then `dos.log_sources` plugins.

    Built-ins (`null`) resolve FIRST and cannot be shadowed by a plugin of the same
    name — the trusted-fallback guarantee, identical to `resolve_judge` /
    `resolve_renderer`. An unknown name fails LOUD with the known list (it never
    silently degrades to `null`, which would hide a typo'd source name): the caller
    asked for a specific adapter and getting a different one silently is exactly the
    unannounced substitution the kernel refuses.
    """
    if name in _BUILT_IN_SOURCES:
        return _BUILT_IN_SOURCES[name]()
    discovered = dict(_discover_entry_point_sources(_stderr=_stderr))
    if name in discovered:
        return discovered[name]
    known = sorted(set(_BUILT_IN_SOURCES) | set(discovered))
    raise ValueError(f"unknown log source {name!r}; known: {', '.join(known)}")


def active_log_sources(*, _stderr=None) -> list[tuple[str, LogSource]]:
    """Every resolvable source as ``(name, source)`` — built-ins THEN discovered
    plugins. Does ENTRY-POINT DISCOVERY (I/O), so it is a call-boundary helper, never
    called inside a verdict (the `active_judges` discipline)."""
    built = [(n, cls()) for n, cls in _BUILT_IN_SOURCES.items()]
    discovered = _discover_entry_point_sources(_stderr=_stderr)
    return built + discovered


def active_log_source_names(*, _stderr=None) -> list[str]:
    """The names of every active source (built-in + discovered) — what `dos doctor`
    would list so an operator can see which log adapters are wired (the log analogue
    of "see the active judges / predicates")."""
    return [name for name, _src in active_log_sources(_stderr=_stderr)]
