"""The renderer seam — Axis 4 of hackability: pluggable output (RND, docs/72).

Output used to be hardcoded: `print` in `cli.py`, `render_text`/`render_json`
in `timeline.py`. A workspace that wanted a different shape (a one-line terse
status bar, a colorized TUI, an HTML fragment, a Slack block) had to fork. This
module is the seam that lets it *register* one instead.

The contract is a `Renderer`: a name plus a set of `render_*(decided_object)
-> str` methods. The kernel resolves a renderer **by name** at output time
(`resolve_renderer`), so `--output terse` finds a workspace's renderer without
the package ever importing it. Two renderers ship built-in and are always
available — `text` (the human form every command prints today) and `json` (the
machine form). A workspace *adds* renderers; it can never remove or shadow the
built-in two (they are the trusted fallback).

The one invariant that keeps an open renderer set safe (HACKING.md Axis-4 design
rule): **a renderer is pure presentation.** It is handed an already-decided
object (`ShipVerdict`, `LaneDecision`, `Timeline`, a man entry) and returns a
string. It receives no config, no leases, nothing it could decide *with* —
rendering is strictly downstream of the kernel, so presentation can never leak
policy back in. The worst a buggy renderer can do is produce ugly text; it can
never mis-verify a ship or mis-admit a lease.

Byte-faithfulness is the load-bearing property of Phase 1/3: the built-in `text`
and `json` renderers reproduce each command's *current* default output
character-for-character, so routing a command through the seam with the default
renderer changes nothing. The methods below are lifted verbatim from the
`cli.py` / `timeline.py` print sites they replace; the litmus tests in
`tests/test_render.py` pin the equality.
"""

from __future__ import annotations

import json
import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class Renderer(Protocol):
    """The presentation contract a workspace implements to add an output format.

    `name` is the token `--output <name>` selects. The `render_*` methods each
    take one already-decided kernel object and return a string. Only
    `render_decision` / `render_verdict` are required by the protocol (the
    Phase-1 surfaces); the later surfaces (`render_timeline` / `render_man` /
    `render_decisions`) are OPTIONAL — a renderer that only cares about verdicts
    inherits the text form for the rest by subclassing `BaseRenderer` (Phase 3).
    """

    name: str

    def render_decision(self, decision) -> str:  # arbiter LaneDecision
        ...

    def render_verdict(self, verdict) -> str:  # ship ShipVerdict
        ...


class BaseRenderer:
    """Shared base giving every renderer a total set of surfaces.

    A workspace renderer subclasses this and overrides only the surfaces it
    cares about; the optional surfaces (`render_timeline` / `render_man` /
    `render_decisions`) default to the **text** form, so a partial renderer is
    still total — `--output terse` on a `timeline` falls back to readable text
    rather than crashing (RND Phase 3a). The required surfaces
    (`render_decision` / `render_verdict`) are abstract here: a concrete
    renderer must define them (the built-ins below do, and the example
    `TerseRenderer` does).

    The fallbacks delegate to the module-level built-in `TEXT` renderer, NOT to
    `self`, so a renderer overriding `render_verdict` does not accidentally
    change how its un-overridden `render_timeline` looks — the fallback is
    always the canonical text form.
    """

    name: str = "base"

    def render_decision(self, decision) -> str:  # pragma: no cover - abstract
        raise NotImplementedError(
            f"{type(self).__name__} must implement render_decision"
        )

    def render_verdict(self, verdict) -> str:  # pragma: no cover - abstract
        raise NotImplementedError(
            f"{type(self).__name__} must implement render_verdict"
        )

    # --- optional surfaces (Phase 3): default to the canonical text form ----
    def render_timeline(self, timeline) -> str:
        return TEXT.render_timeline(timeline)

    def render_man(self, entry) -> str:
        return TEXT.render_man(entry)

    def render_decisions(self, rows) -> str:
        return TEXT.render_decisions(rows)


class TextRenderer(BaseRenderer):
    """The human form — byte-identical to what each command prints today.

    Each method reproduces the exact print site it replaces:
      * `render_verdict`  ← `cli.cmd_verify`'s non-`--json` branch.
      * `render_decision` ← `cli.cmd_arbitrate`'s `json.dumps(..., sort_keys=True)`
        line. Arbitrate has NO human form today (it always prints compact JSON),
        so its "text" form IS that JSON — this keeps `dos arbitrate` (default
        renderer) byte-identical, exactly the Phase-1/2 contract.
      * `render_timeline` ← `timeline.render_text`.
      * `render_man`      ← the line block `cli.cmd_man` prints for one entry.
      * `render_decisions`← `decisions.render_list_plain`.
    """

    name = "text"

    def render_verdict(self, verdict) -> str:
        mark = "SHIPPED" if verdict.shipped else "NOT_SHIPPED"
        sha = f" {verdict.sha}" if verdict.sha else ""
        src = f" (via {verdict.source})" if verdict.source else ""
        return f"{mark} {verdict.plan} {verdict.phase}{sha}{src}"

    def render_decision(self, decision) -> str:
        # Arbitrate's current default is compact sorted JSON. The `--pretty`
        # flag (indent=2) is handled at the call site, not here, because the
        # renderer contract is `(object) -> str` with no formatting args; the
        # CLI passes a pre-pretty-printed string straight through when --pretty
        # is set and --output is the default (see cli.cmd_arbitrate).
        return json.dumps(decision.to_dict(), sort_keys=True)

    def render_timeline(self, timeline) -> str:
        from dos import timeline as _timeline
        return _timeline.render_text(timeline)

    def render_man(self, entry) -> str:
        # `entry` is a ManEntry (below) — the already-assembled lines a man page
        # prints. Joining is the whole render: the kernel decided the content,
        # the renderer only lays it out.
        return "\n".join(entry.lines)

    def render_decisions(self, rows) -> str:
        from dos import decisions as _decisions
        return _decisions.render_list_plain(rows)


class JsonRenderer(BaseRenderer):
    """The machine form — byte-identical to each command's `--json` branch.

    `render_verdict` ← `cli.cmd_verify`'s `--json` branch
    (`json.dumps(to_dict(), sort_keys=True)`); `render_decision` ← arbitrate's
    compact JSON; `render_timeline` ← `timeline.render_json`. For surfaces with
    no native JSON form today (`man`), it emits a structured object so `--output
    json` is always meaningful.
    """

    name = "json"

    def render_verdict(self, verdict) -> str:
        return json.dumps(verdict.to_dict(), sort_keys=True)

    def render_decision(self, decision) -> str:
        return json.dumps(decision.to_dict(), sort_keys=True)

    def render_timeline(self, timeline) -> str:
        from dos import timeline as _timeline
        return _timeline.render_json(timeline)

    def render_man(self, entry) -> str:
        return json.dumps(entry.to_dict(), sort_keys=True, default=str)

    def render_decisions(self, rows) -> str:
        # indent=2 to match `cli.cmd_decisions`'s legacy `--json` branch
        # byte-for-byte, so `--output json` and `--json` coincide for decisions.
        return json.dumps([d.to_dict() for d in rows], indent=2, default=str)


class PlainRenderer(BaseRenderer):
    """A plain-language verdict for a *non-coder* end-user (RND, the adoption floor).

    The built-in `text` renderer answers a developer ("NOT_SHIPPED P 1 (via none)");
    this answers the person who asked an agent to build something and needs one
    sentence: *did I actually get it?* It is the always-available default behind the
    non-coder authoring story — a dev team shipping a product to non-coders gets a
    legible verdict with `--output plain` and **zero plugin**, then overrides it with
    their own `dos.renderers` renderer when they want their product's exact wording
    (the `examples/dos_ext` `friendly` renderer is that copy-me override).

    It encodes the three disciplines that separate a trustworthy non-coder surface
    from a confident-lie machine — and, like every renderer, it is pure presentation
    over an already-decided verdict, so it can only phrase the kernel's verdict, never
    change it:

      1. **Contrast, never the bare accusation.** A bare `NOT_SHIPPED (via none)`
         reads as an accusation or a broken tool; this states the result and attaches
         a *way forward*, so "no" is a next step.
      2. **Presence, never correctness.** `verify` answers "is the thing you asked for
         actually IN what was built?" — a presence fact from git, NOT "is it correct /
         safe" (the file-path rung is presence, not goal). So a "yes" here says *it's
         in there* and pointedly does NOT say *it works*. Over-claiming correctness is
         exactly the failure a non-coder surface exists to prevent.
      3. **Hedge the weak rung.** When the verdict was reached only because a commit
         *subject* mentioned the phase (`source == "grep-subject"`), the deliverable
         may not really be built — a known sharp edge of the grep floor. This lowers
         its confidence and says so rather than passing a soft yes off as a hard one.

    Decisions (the `arbitrate` surface) render as a plain "started / waiting /
    started-elsewhere, nothing overwritten" so a non-coder reads a collision as a safe
    wait, not an error.
    """

    name = "plain"

    def render_verdict(self, verdict) -> str:
        thing = self._thing(verdict)
        if verdict.shipped:
            if verdict.source == "grep-subject":
                return (
                    f"Probably yes: {thing} looks like it was added, but the only "
                    f"sign is a note in the project history, not the built result "
                    f"itself. Worth opening it to confirm it's really there. "
                    f"(This checks that it's present, not that it works.)"
                )
            return (
                f"Yes: {thing} is in what was built. (This checks that it's present "
                f"— not that it's correct or safe; that still needs a review.)"
            )
        return (
            f"Not yet: {thing} isn't in what was built. The agent may have said it "
            f"was done, but it isn't in the project yet. Ask it to actually add "
            f"{thing}, then check again."
        )

    def render_decision(self, decision) -> str:
        if decision.outcome == "acquire":
            if decision.auto_picked:
                return (
                    f"Started — working on a free area ('{decision.lane}'), since "
                    f"the one first requested was busy. Nothing was overwritten."
                )
            return f"Started — working on '{decision.lane}'."
        first_line = decision.reason.splitlines()[0] if decision.reason else ""
        tail = f" ({first_line})" if first_line else ""
        return (
            f"Waiting — another helper is already changing this part, so this one "
            f"is holding off to avoid clobbering it.{tail}"
        )

    @staticmethod
    def _thing(verdict) -> str:
        """The user-facing name of the thing checked. A host product passes a human
        title via its own renderer; the built-in uses the phase name (then plan),
        quoted so it reads as a referent, not jargon."""
        name = verdict.phase or verdict.plan or "the change"
        return f"'{name}'"


class ManEntry:
    """A rendered-content envelope for `dos man` (RND Phase 3b).

    `cmd_man` used to `print(...)` its lines inline. To bring it under the
    renderer seam without changing a byte of default output, the command now
    assembles its lines into a `ManEntry` (the *decided* content) and hands it
    to a renderer. `text` joins the lines (the old output verbatim); `json`
    emits the structured `fields`. This is the same content/presentation split
    the verdict/decision surfaces already have — the kernel decides what a man
    page says, the renderer decides how it looks.
    """

    __slots__ = ("lines", "fields")

    def __init__(self, lines: list[str], fields: dict | None = None) -> None:
        self.lines = list(lines)
        self.fields = dict(fields or {})

    def to_dict(self) -> dict:
        return dict(self.fields)


# The always-available built-ins. A workspace cannot remove or shadow these
# (resolve_renderer resolves built-in names FIRST), so they are the trusted
# fallback every command can always reach. `text`/`json` are the developer/machine
# forms; `plain` is the non-coder end-user form (the adoption floor — a legible
# verdict with zero plugin, overridable by a workspace `dos.renderers` renderer).
TEXT = TextRenderer()
JSON = JsonRenderer()
PLAIN = PlainRenderer()
BUILTIN_RENDERERS: dict[str, Renderer] = {"text": TEXT, "json": JSON, "plain": PLAIN}

# The entry-point group a workspace registers a renderer under (Phase 2).
RENDERER_ENTRY_POINT_GROUP = "dos.renderers"


class UnknownRenderer(Exception):
    """`--output <name>` named a renderer that resolves to nothing.

    Carries the known-renderer list so the CLI can fail loud with an actionable
    message (the completeness posture: an unknown name never silently falls back
    to text — that would hide a typo'd `--output`). Subclasses `Exception` (not
    `KeyError`) so `str(e)` is the clean message, not the `KeyError`-repr'd form
    with surrounding quotes.
    """

    def __init__(self, name: str, known: list[str]) -> None:
        self.name = name
        self.known = list(known)
        super().__init__(
            f"unknown renderer {name!r}; known: {', '.join(self.known)}"
        )


def _discover_entry_point_renderers(*, _stderr=None) -> dict[str, Renderer]:
    """Find workspace renderers registered under the `dos.renderers` group.

    A renderer plugin registers `name = "pkg.module:RendererClass"` in its
    `[project.entry-points."dos.renderers"]`. We load each, instantiate it, and
    key it by its declared entry-point name. A plugin whose name collides with a
    built-in (`text`/`json`) is IGNORED with a one-line stderr note — a plugin
    must not be able to silently capture `json` and change what every machine
    consumer parses. A plugin that fails to load (bad import, constructor
    raises) is skipped with a note rather than crashing every `dos` command
    (a broken third-party plugin is the operator's to fix, not a kernel fault).
    """
    stderr = _stderr if _stderr is not None else sys.stderr
    out: dict[str, Renderer] = {}
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=RENDERER_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(RENDERER_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash output
        return out
    for ep in eps:
        if ep.name in BUILTIN_RENDERERS:
            print(
                f"warning: renderer plugin {ep.name!r} collides with a built-in "
                f"renderer and is ignored (built-ins cannot be shadowed)",
                file=stderr,
            )
            continue
        try:
            cls = ep.load()
            renderer = cls() if isinstance(cls, type) else cls
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: renderer plugin {ep.name!r} failed to load ({e}); "
                f"skipping",
                file=stderr,
            )
            continue
        out[ep.name] = renderer
    return out


def _names_from(discovered: dict[str, Renderer]) -> list[str]:
    """Built-ins first, then discovered plugin names (built-in collisions already
    filtered out by discovery) — the stable order the `--output bogus` error and
    `dos doctor` both want."""
    return list(BUILTIN_RENDERERS) + [n for n in sorted(discovered)
                                      if n not in BUILTIN_RENDERERS]


def known_renderers(*, _stderr=None) -> list[str]:
    """Every renderer name resolvable right now (built-ins + discovered), sorted
    with the built-ins first so the `--output bogus` error lists `text, json`
    ahead of any plugin."""
    return _names_from(_discover_entry_point_renderers(_stderr=_stderr))


def resolve_renderer(name: str, *, _stderr=None) -> Renderer:
    """Return the renderer registered as ``name`` — built-ins first, then plugins.

    Resolution order (Phase 2): the built-in `text`/`json` map is consulted
    FIRST, so a workspace can never shadow the trusted fallback; only on a
    built-in miss do we consult the `dos.renderers` entry points. An unresolved
    name raises `UnknownRenderer` with the known list — it never silently falls
    back to text (a typo'd `--output` must be loud, the completeness posture).

    Discovery runs at most ONCE per call: a built-in miss discovers the plugins,
    and the same `discovered` dict feeds the `UnknownRenderer` known-list — so a
    colliding plugin's stderr note is emitted once, never duplicated by a second
    discovery pass for the error message.
    """
    builtin = BUILTIN_RENDERERS.get(name)
    if builtin is not None:
        return builtin
    discovered = _discover_entry_point_renderers(_stderr=_stderr)
    plugin = discovered.get(name)
    if plugin is not None:
        return plugin
    raise UnknownRenderer(name, _names_from(discovered))
