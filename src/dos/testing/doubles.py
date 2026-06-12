"""Hostile doubles + input batteries for the conformance suite (docs/306).

These are the *misbehaving occupants* the seam safety laws are stated against:
a judge that raises, a judge that returns a look-alike "agree" that is not a
`JudgeVerdict`, an overlap policy that lies "always disjoint", a transport
that raises mid-send. The suite (`dos.testing.suite`) runs each one through
the kernel's safety wrapper — `run_judge`, `admissible_under_floor`,
`send_safely` — inside a PLUGIN's own CI, proving the installed kernel still
converts every failure to its safe direction (ABSTAIN / the floor verdict /
a non-delivered result).

Two rules keep these doubles honest:

* **They are fixtures, never occupants.** Nothing here registers under any
  entry-point group, so no resolver walk (`active_judges`,
  `resolve_notifier`, …) can ever discover one. They exist only to be passed
  explicitly into a law check.
* **The junk-return doubles are traps on purpose.** `JunkReturnJudge` returns
  an object whose ``.agreed`` is ``True`` — if the kernel ever read a foreign
  object's attributes instead of type-checking the return, the trap would
  spring as a false-clear. `run_judge`'s law ("we never read a foreign
  object's `.agreed`") is what keeps it un-sprung.

Also here: the benign fixtures and hostile *input* batteries (claims,
notifications, tree pairs) every conformance class shares — one place, so the
suite and `JudgeTester` exercise identical inputs.

Pure stdlib + sibling kernel imports. No I/O, no host, no vendor.
"""

from __future__ import annotations

from dos.judges import Claim
from dos.lane_overlap import OverlapDecision, Verdict
from dos.notify import Notification, Severity


# ---------------------------------------------------------------------------
# Benign fixtures — the well-formed inputs a healthy occupant must handle.
# ---------------------------------------------------------------------------

# A claim shaped like the real thing: narration plus forgery-resistant evidence.
BENIGN_CLAIM = Claim(
    claim_text="phase P1 of plan X shipped",
    stated_reason="the suite is green and the work is committed",
    evidence=("commit abc1234 stamps plan X P1",),
)

# A notification shaped like the real thing: a digest row with one field.
BENIGN_NOTIFICATION = Notification(
    severity=Severity.INFO,
    title="conformance check",
    summary="a synthetic notification from dos.testing — never deliver this anywhere real",
    fields=(("lane", "docs"),),
    key="dos-testing-conformance",
    source="conformance",
)


# ---------------------------------------------------------------------------
# Hostile input batteries — adversarial INPUTS (the doubles below are
# adversarial OCCUPANTS). A conformant occupant routed through the kernel's
# wrapper must never let one of these escape as a raise or a foreign type.
# ---------------------------------------------------------------------------

HOSTILE_CLAIMS: tuple[Claim, ...] = (
    # nothing to weigh at all
    Claim(claim_text=""),
    # oversized narration (a runaway agent's wall of text)
    Claim(claim_text="x" * 50_000, stated_reason="y" * 50_000),
    # control characters, bidi override, NUL, replacement char (escaped so the
    # source file itself carries no raw bidi control — the Trojan-Source rule)
    Claim(claim_text="\u202edone\x00\ufffd \U0001f642", stated_reason="\r\n\t"),
    # evidence present but all blank
    Claim(claim_text="done", evidence=("",) * 100),
    # a long evidence haystack
    Claim(claim_text="done", evidence=tuple(f"evidence line {i}" for i in range(1_000))),
)

HOSTILE_NOTIFICATIONS: tuple[Notification, ...] = (
    # everything empty
    Notification(severity=Severity.URGENT, title="", summary=""),
    # oversized everything
    Notification(
        severity=Severity.WARN,
        title="t" * 10_000,
        summary="s" * 200_000,
        fields=tuple((f"k{i}", "v" * 1_000) for i in range(50)),
        key="k" * 5_000,
        source="src",
    ),
    # control characters and emoji where text is expected
    Notification(
        severity=Severity.INFO,
        title="\u202etitle\x00 \U0001f642",
        summary="\r\n\t",
        key="\x00",
        source="\U0001f642",
    ),
)

# Tree pairs the prefix floor REFUSES (a collision at any tolerance) — the
# pairs no policy may admit through `admissible_under_floor`. Mirrors the
# in-tree soundness-floor suite (tests/test_overlap_policy.py).
COLLIDING_PAIRS: tuple[tuple[list[str], list[str]], ...] = (
    (["src/api/x.py"], ["src/api/x.py"]),                 # exact glob
    (["src/api/a.py", "src/api/b.py"], ["src/api/**"]),   # over the 1/3 ratio
    (["**/*"], ["**/*"]),                                 # whole-repo
)

# Tree pairs the prefix floor ADMITS (genuinely disjoint regions) — what a
# policy must still be ABLE to admit (the suite must not demand over-refusal).
DISJOINT_PAIRS: tuple[tuple[list[str], list[str]], ...] = (
    (["src/web/**"], ["src/worker/**"]),
    (["docs/a.md"], ["tests/b.py"]),
)


# ---------------------------------------------------------------------------
# Judge doubles — the fail-to-ABSTAIN law's adversaries (docs/86).
# ---------------------------------------------------------------------------


class RaisingJudge:
    """A judge whose ``rule`` always raises — the model-timeout / buggy-plugin
    shape. The law: `run_judge` converts the raise to ABSTAIN, never AGREE,
    and never propagates."""

    name = "raising-judge"

    def rule(self, claim: Claim, config: object):
        raise RuntimeError("this judge always raises (a dos.testing conformance double)")


class _AgreeLookAlike:
    """NOT a `JudgeVerdict`, but duck-typed to read as a cleared claim. If any
    consumer read these attributes off a foreign return type, this would be a
    false-clear — the exact cell the seam is built to make unreachable."""

    agreed = True
    abstained = False
    disagreed = False
    stance = "AGREE"
    why = "trust me"


class JunkReturnJudge:
    """A judge that returns the look-alike above instead of a `JudgeVerdict`.
    The law: `run_judge` type-checks the return and converts it to ABSTAIN —
    it never reads a foreign object's ``.agreed``."""

    name = "junk-return-judge"

    def rule(self, claim: Claim, config: object):
        return _AgreeLookAlike()


# ---------------------------------------------------------------------------
# Overlap-policy doubles — the soundness floor's adversaries (docs/113).
# ---------------------------------------------------------------------------


class LyingAdmitPolicy:
    """A hostile scorer: claims every pair is disjoint, even identical globs.
    The law: `admissible_under_floor` ANDs it under the prefix floor, so it is
    structurally unable to admit a floor-refused pair — including through the
    real `arbiter.arbitrate`."""

    name = "lying-admit"

    def overlaps(self, requested_tree, lease_tree, config) -> OverlapDecision:
        return OverlapDecision(
            Verdict.ADMIT_DISJOINT, 0, len(requested_tree), "I lie: always safe"
        )


class RaisingOverlapPolicy:
    """A scorer that raises on every pair. The law: the floor verdict is used
    alone — fail-closed to today's prefix behavior, never looser."""

    name = "raising-policy"

    def overlaps(self, requested_tree, lease_tree, config) -> OverlapDecision:
        raise RuntimeError("this policy always raises (a dos.testing conformance double)")


class JunkReturnOverlapPolicy:
    """A scorer that returns a string instead of an `OverlapDecision`. The
    law: the kernel never reads a foreign object's ``.admissible`` — the floor
    verdict is used alone."""

    name = "junk-return-policy"

    def overlaps(self, requested_tree, lease_tree, config):
        return "definitely disjoint, trust me"


# ---------------------------------------------------------------------------
# Notifier doubles — the fail-SOFT law's adversaries (docs/225).
# ---------------------------------------------------------------------------


class RaisingNotifier:
    """A transport that raises mid-send — the network-down / bad-token shape.
    The law: `send_safely` converts the raise to a non-delivered
    `NotifyResult`; advisory telemetry never crashes the producer."""

    name = "raising-notifier"

    def send(self, note: Notification):
        raise RuntimeError("this transport always raises (a dos.testing conformance double)")


class JunkReturnNotifier:
    """A transport that returns truthy junk instead of a `NotifyResult`. The
    law: `send_safely` type-checks the return and reports a soft failure — a
    foreign shape is never trusted downstream."""

    name = "junk-return-notifier"

    def send(self, note: Notification):
        return "delivered!"
