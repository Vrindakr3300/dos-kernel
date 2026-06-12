"""The plugin's own CI: conformance + behavior pins + discovery."""

from dos.notify import send_safely
from dos.testing.doubles import BENIGN_NOTIFICATION
from dos.testing.suite import NotifierConformance

from example_notifier import CollectingNotifier


class TestCollectingNotifierConformance(NotifierConformance):
    """One factory override — pytest runs every seam law."""

    def make_notifier(self):
        return CollectingNotifier()


def test_collects_what_it_delivers():
    notifier = CollectingNotifier()
    result = send_safely(notifier, BENIGN_NOTIFICATION)
    assert result.delivered
    assert notifier.sent == [BENIGN_NOTIFICATION]


def test_registered_under_the_entry_point_group():
    """The pyproject entry point took: the kernel resolves this notifier by
    name. (Needs the `pip install -e .` — discovery reads installed metadata.)"""
    from dos.notify import resolve_notifier

    assert resolve_notifier("collecting").name == "collecting"
