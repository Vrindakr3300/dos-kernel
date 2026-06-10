"""The canonical caught-lie example — declared once, copies pinned by lockstep.

Every first-touch surface tells the same tiny story: an agent claims it shipped
two things — "the login endpoint (AUTH1)" and "the password reset (AUTH2)" —
one claim is backed by a real commit, the other never landed. The tokens, the
feature names, and the one real commit subject ARE the canonical example, and
this module is their single source of truth.

Two kinds of consumer:

* the EXECUTABLE demo (`dos quickstart`, `cli.cmd_quickstart`) builds its
  transcript from these constants, so the running demo cannot drift from the
  declared story;
* every PROSE / SCRIPT / FIGURE surface that quotes the example (the README
  parts under `docs/readme/`, `docs/QUICKSTART.md`, `examples/demo/`,
  `examples/plans/example-plan.md`, `examples/fleet_frameworks/`, the CI smoke
  step) carries a hand-written COPY in its own genre — a story, a walkthrough,
  an SVG — and `tests/test_canonical_example_lockstep.py` scans the tracked
  tree and pins the two facts that must agree across genres:

    1. any concrete ship-stamp spelling of the shipped phase is exactly
       ``COMMIT_SUBJECT`` (no "AUTH1: implement login" dialects), and
    2. a feature name is never paired with the wrong phase token.

  A NEW file that quotes the example automatically falls under the same scan:
  propagation is "copy the canonical strings", and the lockstep test catches a
  miscopy. Genre-local prose (how the story is told) stays free.

This is demo DATA — pure stdlib, no I/O, no host names — not a syscall and not
policy. The lockstep test re-pins these literals independently (the same
two-witness discipline as the Go parity corpus), so editing this module is a
deliberate two-place change, never a silent one.
"""

from __future__ import annotations

# The plan groups the two phases; a phase id is any letters+digit token.
PLAN = "AUTH"
SHIPPED_PHASE = "AUTH1"
UNSHIPPED_PHASE = "AUTH2"

# The named claims — what the agent SAYS it shipped. Naming both features is
# what makes the catch legible to someone who has never heard of a "phase".
SHIPPED_FEATURE = "the login endpoint"
UNSHIPPED_FEATURE = "the password reset"

# The one real commit (the ship-stamp the oracle reads) and the work it lands.
COMMIT_SUBJECT = f"{SHIPPED_PHASE}: ship {SHIPPED_FEATURE}"
WORK_FILE = "login.py"
WORK_CONTENT = "def login(): ...\n"

# The agent's cheerful over-claim — the line the demo opens with.
AGENT_CLAIM = (
    f'"Done! Shipped {SHIPPED_FEATURE} ({SHIPPED_PHASE}) '
    f'and {UNSHIPPED_FEATURE} ({UNSHIPPED_PHASE})."'
)
