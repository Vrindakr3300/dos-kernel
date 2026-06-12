"""The plugin's own CI: conformance + the safe-direction pins + discovery."""

from dos.overlap_policy import admissible_under_floor
from dos.testing.suite import OverlapPolicyConformance

from example_overlap_policy import BasenameOverlapPolicy


class TestBasenamePolicyConformance(OverlapPolicyConformance):
    """One factory override — pytest runs every seam law, including the
    arbiter-level proof that a lying-admit cannot double-book a held lane."""

    def make_policy(self):
        return BasenameOverlapPolicy()


def test_stricter_than_the_floor_is_allowed():
    """The policy refuses a pair the prefix floor would admit (both globs end
    in `**`) — refuse-MORE is the safe, permitted direction."""
    decision = admissible_under_floor(
        BasenameOverlapPolicy(), ["src/web/**"], ["src/worker/**"], None
    )
    assert not decision.admissible


def test_genuinely_distinct_basenames_still_admit():
    """The policy must not refuse everything — distinct files admit."""
    decision = admissible_under_floor(
        BasenameOverlapPolicy(), ["docs/a.md"], ["tests/b.py"], None
    )
    assert decision.admissible


def test_registered_under_the_entry_point_group():
    """The pyproject entry point took: the kernel resolves this policy by name.
    (Needs the `pip install -e .` — discovery reads installed metadata.)"""
    from dos.overlap_policy import resolve_overlap_policy

    assert resolve_overlap_policy("basename").name == "basename"
