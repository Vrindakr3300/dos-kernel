"""A custom DOS output renderer — the code axis of hackability.

DOS's built-in renderers turn a decision/verdict into `text` or `json`. A
workspace that wants a different shape (a one-line terse form for a status bar, a
colorized TUI, an HTML fragment, a Slack block) ships a `Renderer` and registers
it via a `dos.renderers` entry_point (see this package's `pyproject.toml`). The
kernel resolves renderers by name at output time, so `--output terse` finds this
class without the `dos` package knowing it exists.

The contract a renderer implements (see `docs/HACKING.md` §4):

    class Renderer(Protocol):
        name: str
        def render_decision(self, decision) -> str: ...   # arbiter LaneDecision
        def render_verdict(self, verdict) -> str: ...      # ship ShipVerdict
        # optional, as the surfaces grow:
        def render_timeline(self, timeline) -> str: ...
        def render_man(self, entry) -> str: ...
        def render_decisions(self, rows) -> str: ...

This example renders the two required surfaces as a single terse line, and
implements ONE optional surface (`render_timeline`) to demonstrate the
partial-implementation pattern: a renderer overrides only the surfaces it cares
about, and `dos` falls back to the built-in `text` form for the rest. It is
deliberately tiny — the point is the SHAPE of the seam, not the styling. It
imports nothing from `dos` (a renderer is pure presentation, handed
already-decided objects — it needs none of the kernel).
"""

from __future__ import annotations


class TerseRenderer:
    """One-line output for a status bar. Register as a `dos.renderers` entry_point.

    Pure presentation: it reads the decision/verdict fields and returns a string.
    It never decides anything — rendering is downstream of the kernel, never a
    place policy leaks back in.
    """

    name = "terse"

    def render_decision(self, decision) -> str:
        # decision is a dos.arbiter.LaneDecision. ASCII-only so a copy-me example
        # renders on a cp1252 Windows console without UTF-8 reconfiguration.
        if decision.outcome == "acquire":
            pick = " (auto)" if decision.auto_picked else ""
            return f"OK {decision.lane}{pick}"
        return f"REFUSED: {decision.reason.splitlines()[0] if decision.reason else 'no reason'}"

    def render_verdict(self, verdict) -> str:
        # verdict is a dos.oracle.ShipVerdict
        mark = "SHIPPED" if verdict.shipped else "not-shipped"
        sha = f" {verdict.sha}" if verdict.sha else ""
        return f"{mark} {verdict.plan} {verdict.phase}{sha} [{verdict.source}]"

    def render_timeline(self, timeline) -> str:
        # One optional surface, to show the partial-implementation pattern. A
        # renderer that omits this (and render_man / render_decisions) still
        # works — `dos` falls back to the built-in `text` form for the surfaces
        # a renderer doesn't implement. `timeline` is a dos.timeline.Timeline.
        gaps = sum(1 for c in timeline.checks if c.verdict == "GAP")
        return (f"{timeline.run_ts}: {len(timeline.stages)} stages, "
                f"{gaps} gap(s)")
