"""`dos.testing` — prove the seam safety laws in YOUR plugin's CI (docs/306).

The kernel's plugin seams each carry a safety law: a judge that fails can
only ABSTAIN (never AGREE), an overlap scorer can only refuse-MORE (never
admit a collision past the prefix floor), a notifier that fails is a
non-delivered result (never a crashed producer). This package turns each law
into a test a third-party plugin runs in its own checkout, against its own
occupant and its own installed `dos-kernel` — this repo never sees the
plugin's code.

Two surfaces:

* **The conformance suite** (`dos.testing.suite`) — subclass
  `JudgeConformance` / `OverlapPolicyConformance` / `NotifierConformance`
  with a ``Test*`` name, override one factory, and pytest runs the laws.
* **`JudgeTester`** (`dos.testing.tester`) — write (claim, expected-stance)
  tables, get the hostile cases auto-run for free.

The hostile doubles (`dos.testing.doubles`) are importable fixtures for your
own tests; they are never registered under any entry-point group.

No pytest import anywhere — plain classes + ``assert`` — so the kernel's
dependency set stays PyYAML-only and any test runner works. Worked examples:
`examples/conformance_plugins/` in the kernel repo (one minimal plugin per
seam kind, each with its conformance tests wired).
"""

from dos.testing.doubles import (
    BENIGN_CLAIM,
    BENIGN_NOTIFICATION,
    COLLIDING_PAIRS,
    DISJOINT_PAIRS,
    HOSTILE_CLAIMS,
    HOSTILE_NOTIFICATIONS,
    JunkReturnJudge,
    JunkReturnNotifier,
    JunkReturnOverlapPolicy,
    LyingAdmitPolicy,
    RaisingJudge,
    RaisingNotifier,
    RaisingOverlapPolicy,
)
from dos.testing.suite import (
    JudgeConformance,
    NotifierConformance,
    OverlapPolicyConformance,
)
from dos.testing.tester import JudgeTester

__all__ = [
    # the suite
    "JudgeConformance",
    "NotifierConformance",
    "OverlapPolicyConformance",
    # the table harness
    "JudgeTester",
    # the doubles + batteries
    "BENIGN_CLAIM",
    "BENIGN_NOTIFICATION",
    "COLLIDING_PAIRS",
    "DISJOINT_PAIRS",
    "HOSTILE_CLAIMS",
    "HOSTILE_NOTIFICATIONS",
    "JunkReturnJudge",
    "JunkReturnNotifier",
    "JunkReturnOverlapPolicy",
    "LyingAdmitPolicy",
    "RaisingJudge",
    "RaisingNotifier",
    "RaisingOverlapPolicy",
]
