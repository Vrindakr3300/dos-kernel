"""`dos.testing.suite` — the importable conformance suite (docs/306, issue #61).

What this is
============

The kernel's seam safety laws, packaged so a THIRD-PARTY plugin can prove them
in ITS OWN CI — this repo never sees the plugin's code. Subclass the class for
your seam kind with a ``Test*`` name, override one factory, and pytest runs
the laws against your occupant:

    # your_plugin/tests/test_conformance.py
    from dos.testing.suite import JudgeConformance
    from your_plugin import YourJudge

    class TestYourJudgeConformance(JudgeConformance):
        def make_judge(self):
            return YourJudge()

The base classes are deliberately NOT named ``Test*``, so importing this
module collects nothing; only your subclass runs. There is no pytest import
anywhere in `dos.testing` — the checks are plain methods + ``assert``, so any
runner that collects classes works and the kernel's dependency set stays
PyYAML-only. (The SQLAlchemy dialect-suite pattern: the host's invariants run
inside the plugin's checkout. ESLint's `RuleTester` half lives next door in
`dos.testing.tester`.)

Each class carries two kinds of law, deliberately:

* **Laws about YOUR occupant** — it names itself, satisfies the seam
  Protocol, returns the kernel's verdict type on benign input, and never
  escapes the kernel's safety wrapper on a hostile-input battery.
* **Laws about the INSTALLED kernel, proven in YOUR environment** — the
  ``test_kernel_*`` checks run the hostile doubles (`dos.testing.doubles`)
  through `run_judge` / `admissible_under_floor` / `arbitrate` /
  `send_safely`. If the `dos-kernel` version your CI pins ever broke a floor,
  your build goes red — version drift surfaces as a failing test, not a
  runtime surprise.

Layering: kernel-layer leaf — stdlib + sibling kernel imports only; no host,
no vendor, no I/O at law-check time (the one boundary touch is
`default_config(".")` inside the arbiter-level case, which is test-time, not
verdict-time). Nothing under `src/dos/` imports this package.
"""

from __future__ import annotations

import dataclasses

from dos import arbiter
from dos.admission import DisjointnessPredicate
from dos.config import LaneTaxonomy, default_config
from dos.judges import Judge, JudgeVerdict, run_judge
from dos.lane_overlap import OverlapDecision
from dos.notify import Notifier, NotifyResult, send_safely
from dos.overlap_policy import OverlapPolicy, admissible_under_floor
from dos.self_modify import SelfModifyPredicate
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

__all__ = [
    "JudgeConformance",
    "NotifierConformance",
    "OverlapPolicyConformance",
]


class JudgeConformance:
    """The `dos.judges` safety laws (docs/86), runnable against YOUR judge.

    Subclass with a ``Test*`` name and override `make_judge`. The judge you
    return should work UNCONFIGURED — the conformance environment wires no
    provider, so a judge that needs one should degrade the way the shipped
    `llm` judge does: ABSTAIN with the gap named, never raise. Override
    `make_config` if your judge reads real config.
    """

    def make_judge(self) -> Judge:
        """Return YOUR judge instance. The one required override."""
        raise NotImplementedError(
            "subclass JudgeConformance with a Test*-named class and override "
            "make_judge() to return your judge instance"
        )

    def make_config(self) -> object:
        """The config handed to ``rule``. ``None`` by default — the built-ins
        ignore it; override when your judge reads a real `SubstrateConfig`."""
        return None

    # ── laws about YOUR occupant ─────────────────────────────────────────

    def test_names_itself(self):
        """A judge carries a non-empty string ``name`` — the token resolvers
        and `dos doctor` identify it by."""
        name = getattr(self.make_judge(), "name", None)
        assert isinstance(name, str) and name.strip(), (
            f"a judge must carry a non-empty str `name`; got {name!r}"
        )

    def test_satisfies_the_judge_protocol(self):
        """The occupant satisfies the `Judge` Protocol (``name`` + ``rule``)."""
        judge = self.make_judge()
        assert isinstance(judge, Judge), (
            f"{type(judge).__name__} does not satisfy dos.judges.Judge "
            f"(it needs a `name` attribute and a rule(claim, config) method)"
        )

    def test_rules_a_benign_claim_with_the_verdict_type(self):
        """``rule`` on a well-formed claim returns a `JudgeVerdict` — not a
        raise, not a look-alike. A judge that needs a provider must ABSTAIN
        when none is wired (the shipped `llm` judge's posture), never raise."""
        verdict = self.make_judge().rule(BENIGN_CLAIM, self.make_config())
        assert isinstance(verdict, JudgeVerdict), (
            f"rule() must return a JudgeVerdict; got {type(verdict).__name__} "
            f"(a judge that cannot rule should return JudgeVerdict.abstain(...))"
        )

    def test_hostile_claims_never_escape_run_judge(self):
        """Adversarial claims (empty, oversized, control characters) routed
        through `run_judge` — the supported call path — always come back as a
        `JudgeVerdict`. Nothing propagates to the caller."""
        judge = self.make_judge()
        config = self.make_config()
        for claim in HOSTILE_CLAIMS:
            verdict = run_judge(judge, claim, config)
            assert isinstance(verdict, JudgeVerdict), (
                f"run_judge let a non-verdict escape on claim "
                f"{claim.claim_text[:60]!r}: {type(verdict).__name__}"
            )

    # ── laws about the INSTALLED kernel, proven in your environment ─────

    def test_kernel_turns_a_raising_judge_into_abstain(self):
        """The fail-to-ABSTAIN floor: a judge that raises yields ABSTAIN,
        never AGREE — a failure can never auto-clear a claim."""
        verdict = run_judge(RaisingJudge(), BENIGN_CLAIM, self.make_config())
        assert isinstance(verdict, JudgeVerdict) and verdict.abstained, (
            f"a raising judge must degrade to ABSTAIN; got {verdict!r}"
        )
        assert not verdict.agreed, "a raising judge AGREED — the false-clear cell is open"

    def test_kernel_turns_a_junk_return_into_abstain(self):
        """The wrong-return-type trap: a judge returning an object whose
        ``.agreed`` is True (but which is not a `JudgeVerdict`) yields ABSTAIN
        — the kernel never reads a foreign object's attributes."""
        verdict = run_judge(JunkReturnJudge(), BENIGN_CLAIM, self.make_config())
        assert isinstance(verdict, JudgeVerdict) and verdict.abstained, (
            f"a junk-return judge must degrade to ABSTAIN; got {verdict!r}"
        )
        assert not verdict.agreed, "a junk return AGREED — a foreign .agreed was believed"


class OverlapPolicyConformance:
    """The `dos.overlap_policies` soundness floor (docs/113), runnable against
    YOUR scorer.

    Subclass with a ``Test*`` name and override `make_policy`. The law these
    checks pin: a policy may refuse pairs the prefix floor admits (stricter is
    safe), but can NEVER admit a pair the floor refuses — not through
    `admissible_under_floor`, and not through the real `arbiter.arbitrate`.
    """

    def make_policy(self) -> OverlapPolicy:
        """Return YOUR overlap policy instance. The one required override."""
        raise NotImplementedError(
            "subclass OverlapPolicyConformance with a Test*-named class and "
            "override make_policy() to return your overlap policy instance"
        )

    def make_config(self) -> object:
        """The config handed to ``overlaps``. ``None`` by default (the kernel
        falls back to its own 1/3 ratio); override to hand yours real config."""
        return None

    # ── laws about YOUR occupant ─────────────────────────────────────────

    def test_names_itself(self):
        """A policy carries a non-empty string ``name``."""
        name = getattr(self.make_policy(), "name", None)
        assert isinstance(name, str) and name.strip(), (
            f"an overlap policy must carry a non-empty str `name`; got {name!r}"
        )

    def test_satisfies_the_overlap_policy_protocol(self):
        """The occupant satisfies the `OverlapPolicy` Protocol."""
        policy = self.make_policy()
        assert isinstance(policy, OverlapPolicy), (
            f"{type(policy).__name__} does not satisfy dos.overlap_policy."
            f"OverlapPolicy (it needs `name` and overlaps(req, lease, config))"
        )

    def test_scores_known_trees_with_the_decision_type(self):
        """``overlaps`` on known tree pairs returns an `OverlapDecision` —
        the kernel's typed verdict, never a bare bool or a foreign shape."""
        policy = self.make_policy()
        config = self.make_config()
        for req, lease in DISJOINT_PAIRS + COLLIDING_PAIRS:
            decision = policy.overlaps(list(req), list(lease), config)
            assert isinstance(decision, OverlapDecision), (
                f"overlaps({req}, {lease}) must return an OverlapDecision; "
                f"got {type(decision).__name__}"
            )

    def test_cannot_admit_a_floor_refused_pair(self):
        """YOUR policy, ANDed under the floor, cannot admit a colliding pair.
        Whatever ``overlaps`` returns, `admissible_under_floor` refuses every
        pair the unforgeable prefix floor refuses — the refuse-MORE-only law,
        proven with your occupant in the loop."""
        policy = self.make_policy()
        config = self.make_config()
        for req, lease in COLLIDING_PAIRS:
            decision = admissible_under_floor(policy, list(req), list(lease), config)
            assert not decision.admissible, (
                f"a floor-refused pair was admitted with {policy.name!r} in the "
                f"loop: ({req}, {lease}) — the soundness floor did not hold"
            )

    # ── laws about the INSTALLED kernel, proven in your environment ─────

    def test_kernel_floor_blocks_a_lying_admit(self):
        """A hostile policy that claims everything is disjoint still cannot
        admit a floor-refused pair — the AND is not the plugin's to skip."""
        config = self.make_config()
        for req, lease in COLLIDING_PAIRS:
            decision = admissible_under_floor(LyingAdmitPolicy(), list(req), list(lease), config)
            assert not decision.admissible, (
                f"the lying-admit double admitted a floor-refused pair: ({req}, {lease})"
            )

    def test_kernel_degrades_a_raising_policy_to_the_floor(self):
        """A policy that raises falls back to the floor verdict alone — colliding
        pairs stay refused, and a genuinely disjoint pair is still admitted
        (fail-closed to today's prefix behavior, never looser, never deadlocked)."""
        config = self.make_config()
        for req, lease in COLLIDING_PAIRS:
            decision = admissible_under_floor(RaisingOverlapPolicy(), list(req), list(lease), config)
            assert not decision.admissible, (
                f"a raising policy admitted a floor-refused pair: ({req}, {lease})"
            )
        req, lease = DISJOINT_PAIRS[0]
        decision = admissible_under_floor(RaisingOverlapPolicy(), list(req), list(lease), config)
        assert decision.admissible, (
            "a raising policy must degrade to the FLOOR verdict on a disjoint "
            "pair (today's behavior), not to a blanket refusal"
        )

    def test_kernel_degrades_a_junk_return_to_the_floor(self):
        """A policy returning a foreign type falls back to the floor verdict —
        the kernel never reads a foreign object's ``.admissible``."""
        config = self.make_config()
        for req, lease in COLLIDING_PAIRS:
            decision = admissible_under_floor(
                JunkReturnOverlapPolicy(), list(req), list(lease), config
            )
            assert not decision.admissible, (
                f"a junk-return policy admitted a floor-refused pair: ({req}, {lease})"
            )

    # ── the arbiter-level case (the issue #61 done-condition bullet) ─────

    def _arbiter_config(self):
        """A deterministic two-lane taxonomy whose lanes share one region —
        built on the kernel's generic default, so it behaves identically in
        this repo, a plugin checkout, or an empty directory."""
        return dataclasses.replace(
            default_config("."),
            lanes=LaneTaxonomy(
                concurrent=("held", "contender"),
                autopick=(),
                exclusive=(),
                trees={"held": ("src/api/",), "contender": ("src/api/",)},
            ),
        )

    def _arbitrate_with(self, policy: OverlapPolicy):
        """Route ``policy`` through the REAL `arbiter.arbitrate` against a live
        lease holding the identical region the request wants."""
        live = [{"lane": "held", "lane_kind": "cluster", "tree": ["src/api/**"]}]
        return arbiter.arbitrate(
            requested_lane="contender",
            requested_kind="cluster",
            requested_tree=["src/api/**"],
            live_leases=live,
            config=self._arbiter_config(),
            predicates=[DisjointnessPredicate(policy=policy), SelfModifyPredicate()],
        )

    def test_kernel_lying_admit_cannot_double_book_through_arbitrate(self):
        """The end-to-end proof: the lying-admit double routed through the real
        arbiter cannot double-book a held lane — the floor sits under the
        predicate the arbiter runs, not beside it."""
        decision = self._arbitrate_with(LyingAdmitPolicy())
        assert decision.outcome == "refuse", (
            "a lying-admit policy double-booked a held lane through arbitrate — "
            "the soundness floor is not structural at the arbiter level"
        )

    def test_plugin_policy_cannot_double_book_through_arbitrate(self):
        """The same end-to-end case with YOUR policy in the loop: an identical
        region held by a live lease is refused no matter what your scorer says."""
        decision = self._arbitrate_with(self.make_policy())
        assert decision.outcome == "refuse", (
            f"{self.make_policy().name!r} double-booked a held lane through "
            f"arbitrate — the floor must refuse an identical-region pair"
        )


class NotifierConformance:
    """The `dos.notifiers` fail-SOFT law (docs/225), runnable against YOUR
    transport.

    Subclass with a ``Test*`` name and override `make_notifier`. Return the
    occupant in its UNCONFIGURED or dry-run form — these checks send synthetic
    notifications, and a conformance run must never deliver anywhere real (the
    shipped `slack` driver's unconfigured posture: a "no token — skipped"
    result, not a post).
    """

    def make_notifier(self) -> Notifier:
        """Return YOUR notifier instance (unconfigured / dry-run form). The
        one required override."""
        raise NotImplementedError(
            "subclass NotifierConformance with a Test*-named class and override "
            "make_notifier() to return your notifier in its dry-run form"
        )

    # ── laws about YOUR occupant ─────────────────────────────────────────

    def test_names_itself(self):
        """A notifier carries a non-empty string ``name``."""
        name = getattr(self.make_notifier(), "name", None)
        assert isinstance(name, str) and name.strip(), (
            f"a notifier must carry a non-empty str `name`; got {name!r}"
        )

    def test_satisfies_the_notifier_protocol(self):
        """The occupant satisfies the `Notifier` Protocol (``name`` + ``send``)."""
        notifier = self.make_notifier()
        assert isinstance(notifier, Notifier), (
            f"{type(notifier).__name__} does not satisfy dos.notify.Notifier "
            f"(it needs a `name` attribute and a send(note) method)"
        )

    def test_sends_safely_with_the_result_type(self):
        """`send_safely` over a well-formed notification returns a
        `NotifyResult` — delivered or not, never a raise."""
        result = send_safely(self.make_notifier(), BENIGN_NOTIFICATION)
        assert isinstance(result, NotifyResult), (
            f"send_safely must return a NotifyResult; got {type(result).__name__}"
        )

    def test_hostile_payloads_never_crash_the_producer(self):
        """Adversarial notifications (empty, oversized, control characters)
        through `send_safely` always come back as a `NotifyResult` — advisory
        telemetry never crashes the fleet loop that emitted it."""
        notifier = self.make_notifier()
        for note in HOSTILE_NOTIFICATIONS:
            result = send_safely(notifier, note)
            assert isinstance(result, NotifyResult), (
                f"send_safely let a non-result escape on note "
                f"{note.title[:60]!r}: {type(result).__name__}"
            )

    # ── laws about the INSTALLED kernel, proven in your environment ─────

    def test_kernel_turns_a_raising_transport_into_undelivered(self):
        """The fail-SOFT floor: a transport that raises yields a non-delivered
        `NotifyResult` with the error named — never a crashed producer."""
        result = send_safely(RaisingNotifier(), BENIGN_NOTIFICATION)
        assert isinstance(result, NotifyResult) and not result.delivered, (
            f"a raising transport must yield a non-delivered result; got {result!r}"
        )

    def test_kernel_turns_a_junk_return_into_undelivered(self):
        """The wrong-return-type trap: a transport returning truthy junk is
        reported as a soft failure — a foreign shape is never trusted."""
        result = send_safely(JunkReturnNotifier(), BENIGN_NOTIFICATION)
        assert isinstance(result, NotifyResult) and not result.delivered, (
            f"a junk-return transport must yield a non-delivered result; got {result!r}"
        )
