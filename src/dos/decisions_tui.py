"""The interactive operator-decision TUI — list + drill-in, over `dos.decisions`.

The curses rendering layer for `dos decisions`. It is a thin, **read-only
router** over `decisions.collect_decisions` (the projection) and
`decisions.next_steps` (the action bar): it shows the pending decisions, lets the
operator move through them and read each one's meaning/evidence/fix (projected
from the `ReasonRegistry`), and — when an action key is pressed — **emits the
exact shell command to stdout and exits**. The TUI never mutates substrate state
itself; the operator runs the emitted command in their own shell. That keeps it
inside the kernel's observe-first / "the manual never blocks a dispatch run"
discipline (no redraw can fire a dispatch; there is no code path here that
acquires a lease or launches an agent).

**Graceful degradation.** `curses` is absent on stock Windows Python (it needs
`windows-curses`), and the package is otherwise zero-hard-dependency. So
`run_tui` imports curses lazily and, on ImportError (or a non-interactive
stdout), falls straight through to `decisions.render_list_plain` — the plain
list is the floor, the TUI is the enhancement. `dos decisions` therefore always
works; it is merely interactive where the terminal supports it.

This module is deliberately import-light at module scope (no top-level `import
curses`) so that importing `dos.decisions_tui` never fails on a curses-less box —
only *calling* `run_tui` reaches for curses, and that call is guarded.
"""

from __future__ import annotations

import subprocess
import sys

from dos import config as _config
from dos import decisions as _decisions


def _copy_to_clipboard(text: str) -> bool:
    """Best-effort copy `text` to the OS clipboard. Returns True on success.

    Tries the platform's native clipboard tool; never raises, never adds a hard
    dependency. A False return just means the operator copies by hand.
    """
    candidates: list[list[str]] = []
    if sys.platform == "win32":
        candidates.append(["clip"])
    elif sys.platform == "darwin":
        candidates.append(["pbcopy"])
    else:
        candidates.append(["xclip", "-selection", "clipboard"])
        candidates.append(["xsel", "--clipboard", "--input"])
    for cmd in candidates:
        try:
            p = subprocess.run(cmd, input=text.encode("utf-8"), timeout=5)
            if p.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def run_tui(config: _config.SubstrateConfig | None = None, *, resolver: str | None = "HUMAN") -> int:
    """Run the interactive decisions TUI, or fall back to the plain list.

    Returns a process exit code. On an action-key press the TUI exits and the
    chosen shell command is printed to stdout (so the operator can run it); `q`
    / Esc exits with no output. When curses is unavailable or stdout is not a
    tty, prints the plain list and returns 0 — the floor that always works.
    """
    cfg = _config.ensure(config)

    try:
        import curses
    except ImportError:
        # The floor: no curses on this box (e.g. Windows without windows-curses).
        print(_decisions.render_list_plain(
            _decisions.collect_decisions(cfg, resolver=resolver)))
        return 0

    # `curses.wrapper` restores the terminal on exit/exception. The inner loop
    # returns either None (quit, no action) or a (key, command) tuple for an
    # emitted action — we print the command AFTER wrapper returns so it lands on
    # the restored terminal, not inside the alternate screen.
    result: dict = {}

    def _inner(stdscr):
        result["value"] = _main_loop(stdscr, curses, cfg, resolver)

    try:
        curses.wrapper(_inner)
    except curses.error:
        # A terminal too small / not curses-capable mid-run — degrade, don't crash.
        print(_decisions.render_list_plain(
            _decisions.collect_decisions(cfg, resolver=resolver)))
        return 0

    emitted = result.get("value")
    if not emitted:
        return 0
    key, command = emitted
    if key == "c":
        ok = _copy_to_clipboard(command)
        # On copy, still echo the command so a no-clipboard box isn't left empty.
        suffix = "  (copied to clipboard)" if ok else "  (copy unavailable — shown above)"
        print(command + suffix)
        return 0
    # Emit-and-exit: the operator runs this in their shell.
    print(command)
    return 0


# Action keys that, when pressed, emit a command and exit. The `m`/`r`/`f`/`j`/`c`
# set is whatever `next_steps` produced for the selected decision; we look the key
# up in that list so the TUI and the plain detail stay in lockstep (one source).
_QUIT_KEYS = frozenset({ord("q"), 27})  # q, Esc


def _init_colors(curses) -> dict:
    """Set up the urgency colour pairs once; return a tier→attr map.

    Best-effort: a terminal with no colour (or `start_color` failing) yields an
    empty map and `_draw` falls back to bold/normal — the floor never depends on
    colour. Pair indices 1–3 are NOW(red)/SOON(yellow)/LATER(dim).
    """
    attrs: dict = {}
    # Defensive against a stripped/limited curses (or a test double): any missing
    # colour method just means no colour, never a crash. The list still renders
    # via the leading glyph + the selected-row reverse-video, so colour is pure
    # enhancement (the same observe-first floor discipline as the plain list).
    try:
        if not curses.has_colors():
            return attrs
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_RED, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_WHITE, -1)
        attrs[_decisions.Urgency.NOW] = curses.color_pair(1) | curses.A_BOLD
        attrs[_decisions.Urgency.SOON] = curses.color_pair(2)
        attrs[_decisions.Urgency.LATER] = curses.color_pair(3) | getattr(curses, "A_DIM", 0)
    except Exception:  # pragma: no cover - terminal/double-dependent
        return {}
    return attrs


def _main_loop(stdscr, curses, cfg, resolver):
    """The curses event loop. Returns None (quit) or (key, command) (emit).

    Pure-ish: it re-reads `collect_decisions` on each full redraw so ages update
    and a resolved decision drops off the list, but it performs no writes.
    """
    curses.curs_set(0)
    stdscr.keypad(True)
    urgency_attrs = _init_colors(curses)

    selected = 0
    rows = _decisions.collect_decisions(cfg, resolver=resolver)

    while True:
        if rows:
            selected = max(0, min(selected, len(rows) - 1))
        _draw(stdscr, curses, rows, selected, resolver, cfg, urgency_attrs)

        ch = stdscr.getch()
        if ch in _QUIT_KEYS:
            return None
        if ch in (curses.KEY_DOWN, ord("j")):
            selected += 1
            continue
        if ch in (curses.KEY_UP, ord("k")):
            selected -= 1
            continue
        if ch in (curses.KEY_RESIZE,):
            continue
        if ch in (ord("R"),):  # refresh the queue (re-read sources)
            rows = _decisions.collect_decisions(cfg, resolver=resolver)
            continue
        # An action key — look it up in the selected decision's next_steps.
        if rows:
            try:
                key_char = chr(ch).lower()
            except ValueError:
                continue
            steps = _decisions.next_steps(rows[selected], cfg)
            for k, command in steps:
                if k == key_char:
                    return (k, command)
        # Unrecognised key — ignore and redraw.


def _draw(stdscr, curses, rows, selected, resolver, cfg=None, urgency_attrs=None):
    """Render one frame: list pane (top) + detail pane (bottom).

    The list is the triage surface: each row leads with a severity glyph +
    colour (red NOW / yellow SOON / dim LATER, anchored on the same rank the
    queue sorts by), shows the human-readable reason (not the raw enum), and
    ends with the 1–2 live action keys for that row — so the operator sees what
    is on fire and what they can do about it without entering the detail pane.
    """
    cfg = _config.ensure(cfg)
    urgency_attrs = urgency_attrs or {}
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    def _put(y, x, text, attr=0):
        if 0 <= y < height and x < width:
            stdscr.addnstr(y, x, text, max(0, width - x - 1), attr)

    scope_label = (resolver or "ALL")
    tally = _decisions.urgency_tally(rows)
    tally_s = f" ({tally})" if tally else ""
    title = f" operator decisions · {scope_label} · {len(rows)} pending{tally_s} "
    _put(0, 0, title.ljust(width - 1), curses.A_REVERSE)

    # ---- list pane ----
    list_top = 2
    list_h = max(3, (height - 2) // 2)
    if not rows:
        _put(list_top, 2, "(none pending — nothing is waiting on you)")
    for i, d in enumerate(rows[:list_h]):
        cursor = ">" if i == selected else " "
        glyph = _decisions.urgency_glyph(d)
        dup = f" ×{d.dup_count}" if d.dup_count > 1 else ""
        hint = _decisions.fmt_action_hints(d, cfg)
        hint_s = f"   {hint}" if hint else ""
        reason = (d.reason_text or d.reason_token)
        line = (f"{cursor}{glyph} {i + 1:>2}  {_decisions._fmt_age(d.age_seconds):>4}  "
                f"{d.kind.value:<16}  {(d.lane or '-'):<10}  {reason[:36]}{dup}{hint_s}")
        if i == selected:
            attr = curses.A_BOLD | curses.A_REVERSE
        else:
            attr = urgency_attrs.get(_decisions.urgency_of(d), 0)
        _put(list_top + i, 0, line, attr)

    # ---- detail pane ----
    detail_top = list_top + list_h + 1
    _put(detail_top - 1, 0, "─" * (width - 1))
    if rows:
        detail = _decisions.render_detail_plain(rows[selected], cfg)
        for j, dl in enumerate(detail.splitlines()):
            _put(detail_top + j, 0, dl)

    # ---- footer ----
    # Name the live action keys for the SELECTED row in full (incl. copy /
    # let-it-ride), so the operator never has to read the detail pane to learn
    # what they can press. Falls back to the generic hint when nothing is
    # selected. `R refresh · q quit` are always-on and listed once at the end.
    if rows:
        keys = _decisions.footer_keys(rows[selected], cfg) or "(no action)"
        foot = f" ↑/↓ move · {keys} · R refresh · q quit "
    else:
        foot = " ↑/↓ move · R refresh · q quit "
    _put(height - 1, 0, foot.ljust(width - 1), curses.A_REVERSE)
    stdscr.refresh()
