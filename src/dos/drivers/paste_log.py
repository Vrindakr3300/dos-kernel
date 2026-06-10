"""dos.drivers.paste_log — the floor log source: operator-pasted text. A JUDGE hint.

docs/117 §7 — the worked move-B example for the `log_source` seam, and **deliberately
the floor of the accountability spectrum**. It exists to demonstrate the fence the
seam puts around the easy-to-ingest sources, not to be trusted as a verdict source.

What it is
==========

A `log_source.LogSource` that wraps text the operator hands in — a pasted terminal
buffer, a copied stack trace, a `screen`/`tmux` scrollback dumped into the prompt. It
is the single easiest log source to ingest (~zero integration: the text is already in
hand) and, by the docs/117 §2 **inversion law**, the *least* trustworthy for exactly
that reason: the agent (or the operator relaying the agent) chose every byte that
reached here, so the bytes are a self-report wearing evidence's clothes — the docs/84
§3.1 forgeable floor, `INFO: tests passed` in a logger rendered as a paste.

Why it is hard-tagged `AGENT_AUTHORED`
======================================

Its `accountability` is `AGENT_AUTHORED` and there is no way to construct it at any
higher rung. That is the load-bearing point of this driver as an *example*: a consumer
routes off the tag (`if ev.accountability.is_agent_authored: feed_a_judge(ev)`), so
this source has no path to an oracle verdict by construction. It answers the docs/117
§1 objection ("an LLM already reads logs") concretely — pasted text IS that loop, and
the kernel's contribution is to give it the correct, lower rung (a JUDGE *hint*,
advisory and fail-to-abstain — `judges` / `drivers/llm_judge`), never a deterministic
verdict. The slop move is to ship a paste adapter as a "verification source"; the
honest move is to ship it tagged as the floor with the fence visible.

How a consumer uses it (the right way)
======================================

    from dos import log_source as _ls
    from dos.drivers.paste_log import PasteLogSource

    src = PasteLogSource(text=pasted_buffer)        # or .from_stdin()
    ev = _ls.gather_log(src, subject=run_id, config=cfg)
    # ev.accountability.is_agent_authored is True →
    #   hand ev.lines to a JUDGE as a hint (advisory), NEVER classify as an oracle.

This driver imports the kernel (`dos.log_source`); the kernel never imports it (the
`drivers/__init__` one-way rule, pinned by `tests/test_log_source.py`). It is NOT in
`dos.drivers.__init__`'s eager imports — like `ci_status`, it is loaded on demand by a
consumer, so it stays off the kernel's import surface.

Pure-stdlib; the only "I/O" is reading the text it was handed (or stdin in the
classmethod), and even a read failure degrades through `gather_log` to NO_SIGNAL.
"""

from __future__ import annotations

import sys

from dos.log_source import Accountability, LogEvidence

# Imported only for type clarity / the entry-point contract; a real plugin would
# register this class under `[project.entry-points."dos.log_sources"]`.

# Cap how much pasted text we retain, so a multi-megabyte paste can't bloat the
# evidence object a judge is handed. A floor source's value is a *hint*; the first N
# lines are plenty, and an unbounded buffer is a footgun, not a feature.
_MAX_LINES = 2000


class PasteLogSource:
    """A `LogSource` over operator-supplied text. Hard-tagged `AGENT_AUTHORED`.

    `name` is `"paste"` (the token a resolver/`dos doctor` would show).
    `accountability` is `AGENT_AUTHORED`, fixed — a class-level constant, not a
    per-call choice, so this source can never claim a higher rung (the docs/117 §2
    inversion law made structural). `gather` ignores `subject`/`config` for routing
    purposes (the text is whatever was handed in; there is nothing to look up) and
    returns the retained lines as `reachable` evidence — "reachable" here means only
    "we have the text," NOT "the text is trustworthy"; the `AGENT_AUTHORED` tag carries
    the trust ceiling, and `reachable=True` on a floor source still routes to a judge.
    """

    name = "paste"
    accountability = Accountability.AGENT_AUTHORED

    def __init__(self, text: str = "") -> None:
        """Wrap a block of pasted text (a terminal buffer, a stack trace).

        Splitlines now (at construction, the boundary), capped at `_MAX_LINES`, so
        `gather` does no work that could raise. Empty text is fine — it yields a
        `no_signal` evidence (nothing was pasted), the honest floor.
        """
        lines = (text or "").splitlines()
        # Keep the LAST _MAX_LINES — a terminal buffer's tail (the recent output, the
        # error, the exit summary) is the part a judge wants, not the scrolled-off head.
        self._lines: tuple[str, ...] = tuple(lines[-_MAX_LINES:])

    @classmethod
    def from_stdin(cls) -> "PasteLogSource":
        """Build a source from whatever is on stdin (the `dos … < buffer.txt` ergonomic).

        The read happens HERE, at the construction boundary, fail-safe: any read error
        degrades to empty text (→ a `no_signal` gather), never a raise — the
        `git_delta`/`ci_status` "every failure → safe empty" posture.
        """
        try:
            text = sys.stdin.read()
        except Exception:
            text = ""
        return cls(text=text)

    def gather(self, subject: str, config: object) -> LogEvidence:
        """Return the pasted lines as evidence — or `no_signal` if nothing was pasted.

        Never raises (the lines were split at construction). Empty paste → `no_signal`
        (the honest floor: there is genuinely no log here). Non-empty → `reached` with
        the lines, tagged `AGENT_AUTHORED` so the consumer routes it to a judge. The
        `detail` says in plain words that this is a floor source, so an operator reading
        `dos doctor` / a `--json` dump is reminded *why* it can't ground a verdict.
        """
        if not self._lines:
            return LogEvidence.no_signal(
                self.name,
                self.accountability,
                detail="no text pasted — the floor source has no log signal.",
            )
        return LogEvidence.reached(
            self.name,
            self.accountability,
            self._lines,
            detail=(
                f"{len(self._lines)} line(s) of operator-pasted text — "
                f"AGENT_AUTHORED (the forgeable floor): a JUDGE hint only, never a "
                f"deterministic verdict source (docs/117 §1)."
            ),
        )
