"""An example `dos.notifiers` plugin occupant — deliberately tiny.

A real transport posts to Slack / a webhook / a pager; this one appends to an
in-memory list (the classic test-double transport, also genuinely useful in a
host's own tests). It is here to show the SHAPE — the `name` token, the
`send(note)` method, the `NotifyResult` return — and the posture the
conformance suite expects: constructible unconfigured, delivering nowhere
real.
"""

from __future__ import annotations

from dos.notify import Notification, NotifyResult


class CollectingNotifier:
    """Deliver into ``self.sent`` and report success — nothing leaves the
    process."""

    name = "collecting"

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, note: Notification) -> NotifyResult:
        self.sent.append(note)
        return NotifyResult(
            delivered=True,
            detail=f"collected #{len(self.sent)}",
            ref=str(len(self.sent)),
        )
