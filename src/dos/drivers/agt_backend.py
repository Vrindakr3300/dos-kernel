"""dos.drivers.agt_backend — dos verdicts in AGT's ExternalPolicyBackend seat (docs/302).

Microsoft's Agent Governance Toolkit (AGT, `microsoft/agent-governance-toolkit`,
MIT; PyPI distribution `agent-governance-toolkit`) gives its policy evaluator a
pluggable backend seat: any object with a `name` property and an
`evaluate(context) -> BackendDecision` method sits beside its native YAML rules,
exactly where its own OPA and Cedar backends sit (their ADR-0015). This driver
puts a dos verdict in that seat:

    from agent_os.policies import PolicyEvaluator
    from dos.drivers.agt_backend import DosBackend

    evaluator = PolicyEvaluator()
    evaluator.load_policies("policies/")
    evaluator.add_backend(DosBackend(workspace=".", seat="verify"))
    decision = evaluator.evaluate(context)

The dependency arrow points at us: this module speaks AGT's contract; nothing
in AGT imports dos-kernel. That is why the adapter is a layer-4 driver — the
same rule that lets `notify_slack.py` name Slack and `llm_judge.py` name a
model vendor lets THIS module name AGT.

The verdict mapping (docs/302 §1)
=================================

  * dos REFUSE / refuted claim  → ``allowed=False, action="deny"``,
    ``reason="dos:<reason>"``, ``error=None``           — binds in AGT.
  * dos affirmative             → ``allowed=True, action="allow"``,
    ``error=None``                                       — binds in AGT.
  * dos ABSTAIN / under-specified context / a FAILED dos evaluation
                                → ``error="abstain: <why>"``  — AGT SKIPS the
    decision and evaluation falls through to the next backend / the default.

The third row is deliberate, twice over. AGT's evaluator skips any decision
whose ``error`` is set (`agent_os/policies/evaluator.py`, the
``if result.error is None`` guard) — that skip channel is the only honest place
for fail-to-abstain: an advisor that says nothing false rather than guessing.
And a dos evaluation that *crashes* also abstains rather than fabricating a
deny — the kernel's fail-to-abstain discipline (`judges.py`, docs/86), not
AGT's fail-closed-deny (theirs is right for a gate IN the path; dos sits
beside it). Anything dos wants to BIND must return ``error=None``. The
upstream asymmetry (failure and abstention share one channel; there is no
"failed AND bind deny") is AGT's documented-contract gap, tracked on their
tracker — this adapter works within current semantics.

Evidence rides the audit fields: a shipped verdict's commit digest goes in
``proof_artefact`` (``git:<sha>``) and ``verification_pointers`` carries the
graded evidence source/rung, which AGT's evaluator copies verbatim into the
winning ``PolicyDecision.audit_entry`` — their high-assurance channel, built
for exactly this kind of backend.

The two seats (docs/302 §2)
===========================

  * ``seat="verify"`` (default): the context names an effect claim via
    ``dos_plan`` + ``dos_phase``. Shipped → allow (+ evidence); not shipped →
    deny (``dos:unverified-claim`` — the oracle looked at git and found
    nothing; a definite negative, not an abstain); keys absent → abstain.
  * ``seat="arbitrate"``: the context names a footprint via ``dos_tree`` (a
    list of repo-relative path prefixes; falls back to a single ``path`` key).
    ``acquire`` → allow; ``refuse`` → deny with the arbiter's reason; no
    footprint → abstain.

Import posture (the `notify_slack` rule)
========================================

Nothing from ``agent_os`` is imported at module load. The decision object is
duck-typed: the real ``agent_os.policies.backends.BackendDecision`` is tried
lazily inside ``evaluate``; absent → a local structurally-equal dataclass (the
evaluator only reads fields, it never isinstance-checks). So importing this
driver never fails for lack of the host's package, and the kernel dependency
set is untouched. The one loud path (the silent-cliff rule): construct with
``require_agt=True`` to make a missing ``agent_os`` an immediate ``ImportError``
with the install hint, for hosts that want the missing-dep case to be an
error rather than a permanently-skipped seat.

Host-version drift: the published ``agent_os_kernel`` 3.7.0 ``BackendDecision``
predates the evidence pair (``proof_artefact`` / ``verification_pointers``).
Decisions are therefore constructed with only the fields the installed class
actually declares (`_construct` filters by dataclass fields) — on an older
host the verdict still BINDS and the full dos verdict stays readable in
``raw_result``; only the audit-entry evidence propagation (a newer-evaluator
feature anyway) is absent. A field-filter miss must never silently demote a
bind to an abstain.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable

_INSTALL_HINT = (
    "the AGT host package is not installed — "
    "`pip install agent-governance-toolkit` (imports as `agent_os`)"
)

_SEATS = ("verify", "arbitrate")


@dataclasses.dataclass
class _LocalBackendDecision:
    """Structural twin of `agent_os.policies.backends.BackendDecision`.

    Field names and defaults mirror AGT's dataclass exactly — their evaluator
    reads attributes (`result.error`, `result.allowed`, …), it never
    isinstance-checks, so this twin is indistinguishable in the seat. Used only
    when `agent_os` is not importable; when it is, the real class is used so a
    host that DOES isinstance-check gets the genuine article.
    """

    allowed: bool
    action: str = "allow"
    reason: str = ""
    backend: str = ""
    raw_result: Any = None
    evaluation_ms: float = 0.0
    error: str | None = None
    proof_artefact: str | None = None
    verification_pointers: dict[str, str] = dataclasses.field(default_factory=dict)


def _decision_cls() -> type:
    """The real AGT decision class when installed, else the local twin."""
    try:
        from agent_os.policies.backends import BackendDecision
        return BackendDecision
    except Exception:  # noqa: BLE001 — absence of the optional host package
        return _LocalBackendDecision


def _construct(cls: type, **kwargs: Any) -> Any:
    """Build a decision, keeping only the fields ``cls`` actually declares.

    The published host package versions drift (3.7.0 lacks the evidence pair);
    passing an unknown kwarg would raise inside ``evaluate`` and turn a BIND
    into an abstain — the silent-degrade this filter exists to prevent.
    """
    try:
        names = {f.name for f in dataclasses.fields(cls)}
    except TypeError:  # not a dataclass — pass everything through, let it speak
        return cls(**kwargs)
    return cls(**{k: v for k, v in kwargs.items() if k in names})


def _agt_available() -> bool:
    try:
        import agent_os.policies.backends  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class DosBackend:
    """A dos verdict in AGT's external-policy-backend seat.

    Parameters
    ----------
    workspace:
        Workspace root to adjudicate against (the repo the dos verdicts read).
        ``None`` → the process-active dos config.
    seat:
        ``"verify"`` (effect-claim oracle, default) or ``"arbitrate"``
        (footprint admission). One seat per instance, chosen at construction —
        a host wanting both registers two backends.
    config:
        An explicit ``SubstrateConfig`` (wins over ``workspace``).
    require_agt:
        ``True`` → raise ``ImportError`` at construction when ``agent_os`` is
        not importable (the loud path). Default ``False`` — the duck-typed
        decision twin keeps the seat working without the package.
    verifier:
        Test seam: ``(plan, phase) -> ShipVerdict``-shaped object. ``None`` →
        the real ship oracle (`dos.oracle.is_shipped` against the workspace).
    arbitrate_fn:
        Test seam: ``(lane, kind, tree) -> LaneDecision``-shaped object.
        ``None`` → the real arbiter over the workspace's live leases.
    """

    def __init__(
        self,
        workspace: str | None = None,
        *,
        seat: str = "verify",
        config: Any = None,
        require_agt: bool = False,
        verifier: Callable[[str, str], Any] | None = None,
        arbitrate_fn: Callable[[str, str, list[str]], Any] | None = None,
    ) -> None:
        if seat not in _SEATS:
            raise ValueError(f"unknown seat {seat!r}; expected one of {_SEATS}")
        if require_agt and not _agt_available():
            raise ImportError(_INSTALL_HINT)
        self._workspace = workspace
        self._seat = seat
        self._config = config
        self._verifier = verifier
        self._arbitrate_fn = arbitrate_fn

    # -- protocol surface -----------------------------------------------------

    @property
    def name(self) -> str:
        return "dos"

    def evaluate(self, context: dict[str, Any]) -> Any:
        """Adjudicate ``context`` → a ``BackendDecision``-shaped object.

        Never raises: a failed dos evaluation ABSTAINS (``error`` set, which
        AGT skips) rather than fabricating a verdict — fail-to-abstain, the
        advisor's floor, distinct from a *definite* dos negative (an
        unverified claim or an admission refusal), which binds a deny.
        """
        start = time.perf_counter()
        try:
            if self._seat == "verify":
                decision = self._evaluate_verify(context)
            else:
                decision = self._evaluate_arbitrate(context)
        except Exception as e:  # noqa: BLE001 — fail-to-abstain, never fabricate
            decision = self._abstain(f"dos evaluation failed: {e}")
        decision.evaluation_ms = (time.perf_counter() - start) * 1000
        return decision

    # -- the two seats ----------------------------------------------------------

    def _evaluate_verify(self, context: dict[str, Any]) -> Any:
        plan = str(context.get("dos_plan") or "").strip()
        phase = str(context.get("dos_phase") or "").strip()
        if not plan or not phase:
            return self._abstain(
                "context names no effect claim (expected dos_plan + dos_phase)")
        verdict = self._verify(plan, phase)
        pointers = {
            "plan": plan,
            "phase": phase,
            "source": str(getattr(verdict, "source", "") or ""),
        }
        rung = str(getattr(verdict, "rung", "") or "")
        if rung:
            pointers["rung"] = rung
        raw = verdict.to_dict() if hasattr(verdict, "to_dict") else None
        if getattr(verdict, "shipped", False):
            sha = getattr(verdict, "sha", None)
            return self._make(
                allowed=True,
                action="allow",
                reason=f"dos:verified-shipped ({pointers['source'] or 'git'})",
                raw_result=raw,
                proof_artefact=f"git:{sha}" if sha else None,
                verification_pointers=pointers,
            )
        return self._make(
            allowed=False,
            action="deny",
            reason=(f"dos:unverified-claim — no git evidence that "
                    f"{plan} {phase} shipped"),
            raw_result=raw,
            verification_pointers=pointers,
        )

    def _evaluate_arbitrate(self, context: dict[str, Any]) -> Any:
        tree = context.get("dos_tree")
        if not tree and context.get("path"):
            tree = [context["path"]]
        if not tree:
            return self._abstain(
                "context names no footprint (expected dos_tree or path)")
        tree = [str(t) for t in tree]
        lane = str(context.get("dos_lane") or "agt")
        kind = str(context.get("dos_lane_kind") or "keyword")
        decision = self._arbitrate(lane, kind, tree)
        raw = decision.to_dict() if hasattr(decision, "to_dict") else None
        if getattr(decision, "outcome", "") == "acquire":
            return self._make(
                allowed=True,
                action="allow",
                reason=f"dos:admitted (lane {getattr(decision, 'lane', lane)!r})",
                raw_result=raw,
            )
        why = str(getattr(decision, "reason", "") or "admission refused")
        return self._make(
            allowed=False,
            action="deny",
            reason=f"dos:{why}",
            raw_result=raw,
        )

    # -- default adjudicators (the boundary I/O, behind the test seams) ---------

    def _cfg(self) -> Any:
        from dos import config as _config

        if self._config is not None:
            return self._config
        if self._workspace is not None:
            return _config.load_workspace_config(workspace=self._workspace)
        return _config.ensure(None)

    def _verify(self, plan: str, phase: str) -> Any:
        if self._verifier is not None:
            return self._verifier(plan, phase)
        from dos import oracle

        return oracle.is_shipped(plan, phase, cfg=self._cfg())

    def _arbitrate(self, lane: str, kind: str, tree: list[str]) -> Any:
        if self._arbitrate_fn is not None:
            return self._arbitrate_fn(lane, kind, tree)
        from dos import admission as _admission
        from dos import arbiter, lane_lease

        cfg = self._cfg()
        try:
            live = lane_lease.live_leases(cfg)
        except Exception:  # noqa: BLE001 — a WAL read is best-effort (the CLI rule)
            live = []
        budgets = dict(cfg.class_budgets.as_arbiter_budgets())
        return arbiter.arbitrate(
            requested_lane=lane,
            requested_kind=kind,
            requested_tree=tree,
            live_leases=live,
            config=cfg,
            predicates=_admission.active_predicates(config=cfg),
            class_budgets=budgets or None,
        )

    # -- decision construction ---------------------------------------------------

    def _make(self, *, allowed: bool, action: str, reason: str,
              raw_result: Any = None, proof_artefact: str | None = None,
              verification_pointers: dict[str, str] | None = None) -> Any:
        return _construct(
            _decision_cls(),
            allowed=allowed,
            action=action,
            reason=reason,
            backend=self.name,
            raw_result=raw_result,
            error=None,
            proof_artefact=proof_artefact,
            verification_pointers=dict(verification_pointers or {}),
        )

    def _abstain(self, why: str) -> Any:
        # `allowed=False` is belt-and-braces: AGT's evaluator never reads it on
        # an error row (the row is skipped), but a consumer that forgets the
        # error check must not see a phantom allow.
        return _construct(
            _decision_cls(),
            allowed=False,
            action="deny",
            reason=f"dos abstained: {why}",
            backend=self.name,
            error=f"abstain: {why}",
        )
