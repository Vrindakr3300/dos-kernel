"""The live `dos plan` screen — a `rich.live` poll loop over `plan_board.snapshot`.

The rendering layer for `dos plan`'s interactive mode, the work-terrain sibling of
`dispatch_top_tui`. It re-`snapshot()`s the workspace on a cadence and redraws — a
read-only board an operator leaves open to watch the plan's claimed-vs-oracle terrain
move as a fleet ships phases. It mutates nothing: no lease, no launch, no write path;
the only effect is drawing.

**Graceful degradation (the floor that always works).** `rich` is an OPTIONAL dependency
(the `[tui]` extra) — the kernel core stays PyYAML-only. So this module is import-light
at module scope (no top-level `import rich`), and `run_plan` imports rich lazily; on
ImportError (rich not installed) or a non-interactive stdout (a pipe / CI) it falls
straight through to a single `plan_board.render_frame_text` frame and returns. `dos plan`
therefore ALWAYS works — `dos plan --once` and a piped `dos plan` print the plain frame
everywhere; the live redraw is the enhancement where rich is present and stdout is a tty.
Exactly the lazy-import + plain-floor split `dispatch_top_tui` uses.
"""

from __future__ import annotations

import sys
import time

from dos import config as _config
from dos import plan_board as _board


def _render_once(cfg, **kw) -> str:
    """One plain-text frame — the floor and the `--once` body."""
    return _board.render_frame_text(_board.snapshot(cfg, **kw))


def run_plan(
    config=None, *, once: bool = False, interval: float = 5.0,
    rows=None, source_name: str | None = None,
) -> int:
    """Run the live `dos plan` screen, or print one frame and return.

    Returns a process exit code (always 0 — a read-only viewer has nothing to fail).
    `once=True`, a non-interactive stdout, or a missing `rich` all collapse to a single
    plain-text frame. Otherwise a `rich.live` loop redraws every `interval` seconds until
    the operator interrupts (Ctrl-C), which exits cleanly — there is no state to unwind.

    ``rows`` / ``source_name`` thread the CLI's row-source choice through to each
    `snapshot()` so the live loop re-harvests the same source on every tick.
    """
    cfg = _config.ensure(config)
    snap_kw = {"rows": rows, "source_name": source_name}

    interactive = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if once or not interactive:
        print(_render_once(cfg, **snap_kw))
        return 0

    try:
        from rich.console import Console
        from rich.live import Live
    except ImportError:
        print(_render_once(cfg, **snap_kw))
        print("\n(install `dos-kernel[tui]` for the live auto-refreshing screen)")
        return 0

    console = Console()
    interval = max(0.5, float(interval))
    try:
        with Live(_renderable(cfg, **snap_kw), console=console, screen=True,
                  auto_refresh=False, transient=True) as live:
            while True:
                live.update(_renderable(cfg, **snap_kw), refresh=True)
                time.sleep(interval)
    except KeyboardInterrupt:
        print(_render_once(cfg, **snap_kw))
        return 0


def _renderable(cfg, **kw):
    """Build the rich renderable for one frame, or a plain string if rich is gone.

    Reuses the pure plain-text section renderers as the panel bodies — one source of
    truth for content; rich only adds the frame/colour. The phases panel border goes red
    when any divergence is present, so the operator's eye lands on the cell the screen
    exists to surface (the headline made visual)."""
    frame = _board.snapshot(cfg, **kw)
    try:
        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text
    except Exception:  # pragma: no cover - rich present in the live branch
        return _board.render_frame_text(frame)

    def _panel(title: str, body: str, style: str) -> Panel:
        return Panel(Text(body), title=f"[bold]{title}[/]", border_style=style,
                     title_align="left")

    def _body(text: str) -> str:
        lines = text.splitlines()
        return "\n".join(lines[1:]) if len(lines) > 1 else ""

    divergent = frame.summary()["divergent"]
    phases_style = "red" if divergent else "cyan"
    header = Text(
        f"dos plan · {frame.workspace} · {frame.now_iso}"
        + ("" if frame.initialized else "   (no dos.toml — generic main/global)")
        + (f"   ⚠ {divergent} divergent" if divergent else ""),
        style="bold red" if divergent else "bold cyan",
    )
    return Group(
        header,
        _panel("phases (claimed vs oracle)", _body(_board.render_phases_text(frame.phases)),
               phases_style),
        _panel("recent commits", _body(_board.render_activity_text(frame.activity)), "green"),
        Text("read-only · Ctrl-C to quit · this screen mutates nothing", style="dim"),
    )
