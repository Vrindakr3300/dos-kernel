"""A *custom* non-coder verdict surface — how a dev team OVERRIDES the built-in
`plain` renderer with their own product's wording.

DOS now ships a built-in `plain` renderer (`dos verify --output plain`) — the
zero-plugin, legible non-coder floor. This example is the next step: it shows a dev
team writing their OWN renderer (`--output friendly`) when they want their product's
exact tone and their own feature titles, not the generic built-in phrasing. It is
the worked example behind the strategy claim that "the non-coder verdict surface IS
a `dos.renderers` plugin a dev team writes" (see the dos-private docs
`dispatch-os-the-non-coder-authoring-floor.md` §5,
`dispatch-os-the-framework-a-dev-team-bundles.md` §3, and the adopter cookbook). The
kernel computes a *correct* verdict from ground truth; the host turns it into a
sentence *their* users act on — without forking the package. The kernel guarantees
the verdict's HONESTY; the host owns the phrasing's FIT.

The relationship: `text`/`json`/`plain` are the always-available built-ins
(developer / machine / non-coder); `friendly` here is the *customized* non-coder
variant a product ships — same audience as `plain`, the team's own words. (And
`renderer.py`'s `terse` is the coder's status-bar form.) All render the SAME
`ShipVerdict`; only the words differ.

Three disciplines this example encodes — they are the difference between a verdict
surface a non-coder can trust and a confident-lie machine:

1. **Contrast, never the bare accusation.** A bare `NOT_SHIPPED (via none)` reads to
   a non-coder as either an accusation or a broken tool. We always state the
   YES shape and the NO shape in the same vocabulary, and attach a *way forward* to
   the NO — so "no" is a next step, not a dead end. (Iconicity rule:
   `dispatch-os-iconicity.md`, `dispatch-os-launch-posts-hn-linkedin.md`.)

2. **Presence, never correctness.** `dos verify` answers "is the thing you asked
   for actually IN what was built?" — a PRESENCE fact from git. It does NOT answer
   "is it CORRECT / safe / well-built" (that is Wall §3 — the file-path rung is
   presence, not goal). So a truthful non-coder "yes" says *"it's in there"* and
   pointedly does NOT say *"it works."* Over-claiming correctness here is exactly
   the failure this whole surface exists to prevent.

3. **Hedge the weak rung.** When the verdict was reached only because a commit
   *subject* mentioned the phase (`source == "grep-subject"`), the deliverable may
   not actually be built — a known sharp edge of the grep floor. A responsible
   host surface lowers its confidence and says so, rather than passing a soft
   "yes" off as a hard one.

It imports nothing from `dos`: a renderer is pure presentation, handed
already-decided objects.
"""

from __future__ import annotations


class FriendlyRenderer:
    """A product's own non-coder verdict output. Register as a `dos.renderers`
    entry_point (see this package's `pyproject.toml`): `--output friendly`.

    Same role as the built-in `plain`, but this is the copy-me template for a team
    that wants its own wording. Pure presentation. It reads the verdict/decision
    fields and returns a human sentence; it never decides anything. The "thing you
    asked for" is referred to by the phase name the verdict carries — a real product
    substitutes a feature title the non-coder typed; here we use what the
    kernel knows.
    """

    name = "friendly"

    # -- the truth surface: "did I actually get what I asked for?" --------------
    def render_verdict(self, verdict) -> str:
        # verdict is a dos.oracle.ShipVerdict: .shipped (bool), .plan, .phase,
        # .sha, .source ("registry" | "grep" | "grep-artifact" | "grep-subject"
        # | "none").
        thing = self._thing(verdict)

        if verdict.shipped:
            # PRESENCE, not correctness. Note the deliberate "it's in there" /
            # NOT "it works" wording, and the weak-rung hedge.
            if verdict.source == "grep-subject":
                # Reached only via a commit message mentioning it — weak evidence
                # the deliverable is really built. Say so.
                return (
                    f"Probably yes: {thing} looks like it was added, but the only "
                    f"sign is a note in the project history, not the built result "
                    f"itself. Worth opening it to confirm it's really there. "
                    f"(This checks that it's present, not that it works.)"
                )
            return (
                f"Yes: {thing} is in what was built. "
                f"(This checks that it's present — not that it's correct or safe; "
                f"that still needs a review.)"
            )

        # NOT shipped — the contrast case. Plain, non-accusatory, with a next step.
        return (
            f"Not yet: {thing} isn't in what was built. The agent may have said it "
            f"was done, but it isn't in the project yet. Ask it to actually add "
            f"{thing}, then check again."
        )

    # -- the coordination surface: "are two helpers fighting over the same thing?"
    def render_decision(self, decision) -> str:
        # decision is a dos.arbiter.LaneDecision.
        if decision.outcome == "acquire":
            if decision.auto_picked:
                return (
                    f"Started — working on a free area ('{decision.lane}'), since "
                    f"the one first requested was busy. Nothing was overwritten."
                )
            return f"Started — working on '{decision.lane}'."
        # Refused: another worker holds the region. Not an error — a safe wait.
        first_line = decision.reason.splitlines()[0] if decision.reason else ""
        tail = f" ({first_line})" if first_line else ""
        return (
            f"Waiting — another helper is already changing this part, so this one "
            f"is holding off to avoid clobbering it.{tail}"
        )

    @staticmethod
    def _thing(verdict) -> str:
        """The user-facing name of the thing checked. A host product would pass a
        human title here; absent that, the phase name is the best the kernel has,
        and we quote it so it reads as a referent, not jargon."""
        name = verdict.phase or verdict.plan or "the change"
        return f"'{name}'"
