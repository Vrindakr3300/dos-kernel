"""Tests for the custom non-coder verdict surface (`FriendlyRenderer`).

`FriendlyRenderer` is the example OVERRIDE of the built-in `plain` renderer (the
built-in's own tests live in `tests/test_render.py`). These pin the same three
disciplines that make the surface trustworthy to someone who cannot read the code:
presence-not-correctness, contrast-with-a-way-forward, and the grep-subject hedge.

Run from the repo root with the example package importable:

    pip install -e examples/dos_ext
    python -m pytest examples/dos_ext/test_friendly_renderer.py -q

They mirror `tests/test_render.py`'s frozen-`ShipVerdict` style. The example package
depends on `dos-kernel`, so `ShipVerdict`/`LaneDecision` import cleanly.
"""

from __future__ import annotations

from dos.oracle import ShipVerdict
from dos.arbiter import LaneDecision

from dos_ext.friendly_renderer import FriendlyRenderer

R = FriendlyRenderer()


# -- presence, never correctness -------------------------------------------------
def test_shipped_says_present_not_correct():
    v = ShipVerdict(plan="AUTH", phase="login-page", shipped=True, sha="abc123",
                    source="registry")
    out = R.render_verdict(v)
    assert "login-page" in out
    # affirms presence...
    assert "in what was built" in out
    # ...and explicitly refuses to claim correctness (the Wall §3 line)
    assert "not that it's correct" in out
    # never the bare jargon a non-coder can't read
    assert "SHIPPED" not in out and "via" not in out


# -- contrast + a way forward, never a bare accusation ---------------------------
def test_not_shipped_is_non_accusatory_with_next_step():
    v = ShipVerdict(plan="AUTH", phase="login-page", shipped=False, source="none")
    out = R.render_verdict(v)
    assert "Not yet" in out
    assert "isn't in what was built" in out
    # the way forward — "no" is a next step, not a dead end
    assert "Ask it to actually add" in out
    # not the bare accusatory / system-error-looking string
    assert "NOT_SHIPPED" not in out and "none" not in out


# -- hedge the weak rung (grep-subject) -----------------------------------------
def test_grep_subject_is_hedged_not_a_hard_yes():
    v = ShipVerdict(plan="AUTH", phase="login-page", shipped=True, sha="abc123",
                    source="grep-subject")
    out = R.render_verdict(v)
    # a soft yes, explicitly weaker than the registry/grep-artifact "yes"
    assert "Probably yes" in out
    assert "project history" in out  # names WHY it's weak
    # and still carries the presence-not-correctness caveat
    assert "present, not that it works" in out


def test_strong_yes_is_unhedged():
    """A registry/grep-artifact verdict gives the confident form, distinct from the
    grep-subject hedge — so the two rungs read differently to the user."""
    strong = R.render_verdict(
        ShipVerdict(plan="P", phase="x", shipped=True, source="grep-artifact"))
    weak = R.render_verdict(
        ShipVerdict(plan="P", phase="x", shipped=True, source="grep-subject"))
    assert strong.startswith("Yes:")
    assert weak.startswith("Probably yes")
    assert strong != weak


# -- coordination surface: collisions in plain language --------------------------
def test_decision_refuse_is_a_safe_wait_not_an_error():
    d = LaneDecision(outcome="refuse", lane="src", auto_picked=False,
                     reason="src is held by run abc")
    out = R.render_decision(d)
    assert "Waiting" in out
    assert "clobber" in out  # explains it's protective, not broken


def test_decision_autopick_reassures_nothing_overwritten():
    d = LaneDecision(outcome="acquire", lane="docs", auto_picked=True, reason="")
    out = R.render_decision(d)
    assert "Started" in out
    assert "Nothing was overwritten" in out
