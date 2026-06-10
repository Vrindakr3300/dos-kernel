"""Provider-limit category — the one canonical vocabulary the dispatch family
collapses every rate-limit / quota / overload signal into (the PI5 collapse
target promised in the job repo's ``agents/quota/base.py``).

Three independent taxonomies exist upstream, each correct for its own input:

  * ``rate_limit_classify.Kind`` (job) — string markers on a ``claude -p``
    terminal envelope ({RATE_LIMITED, OVERLOADED, CREDIT_LOW, NONE}).
  * ``agents.quota.QuotaErrorClass`` (job) — provider exceptions
    ({RPM_THROTTLED, DAILY_QUOTA_EXHAUSTED, SUBSCRIPTION_BLACKOUT, TRANSIENT_429}).
  * apply-next-loop outcome tokens (job) — exit-code + log regex
    ({LLM-QUOTA-EXHAUSTED, LLM-QUOTA-EXHAUSTED-DURABLE, CORRELATED-OUTAGE, …}).

They overlap but share no OUTPUT type, so every loop re-decided "transient vs
usage vs hard-quota" on its own and drifted. This module is **not** a fourth
classifier — it is the shared category + the canonical backoff policy that all
three map *into* via the thin pure ``from_*`` translators below.

⚓ Provider-invariance (job CLAUDE.md "Bulkhead"): provider distinctions stay
infrastructure inside the adapter. The mapper takes the upstream enum's VALUE
(a plain ``str``), never the upstream class — so ``dos`` imports nothing from
``agents.quota`` / ``rate_limit_classify``; the dependency arrow points the
right way (job → dos), never back.

The kernel decision logic that ACTS on a category already lives in
``dos.loop_decide.decide`` (``OutcomeKind.OVERLOADED`` → ``retry-same-iter``
with the same backoff ladder; ``RATE_LIMITED`` → stop). This module does not
change that — it standardizes the *word*, and ``policy_for`` makes the backoff
ladder a single source of truth both sides can read.

PURE — no I/O, no clock. py.typed.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class ProviderLimit(str, enum.Enum):
    """The canonical provider-limit category — what dispatch reasons about.

    ``str``-valued so it round-trips as a token (``ProviderLimit.USAGE_WINDOW
    == "usage_window"``), same convention as ``loop_decide.OutcomeKind`` and
    ``gate_classify.Verdict``.

      TRANSIENT_OVERLOAD — server-side 529 / ``overloaded_error`` / the harness
                           "Server is temporarily limiting requests (not your
                           usage limit)" surface. Clears in seconds-to-minutes.
                           Policy: retry the SAME unit of work with backoff;
                           escalate to stop only after K consecutive hits (an
                           outage, not a blip).
      USAGE_WINDOW       — a 429 / quota / 5-hour / 7-day / weekly cap. Every
                           retry fails identically until the window resets on a
                           TIMER. Policy: stop (or durable-defer past a measured
                           ``window_end``); re-invoke after reset.
      HARD_QUOTA         — a billing block ("credit balance too low") or an
                           opaque subscription blackout. No timer fixes it — an
                           OPERATOR must act. Policy: stop + surface.
      NONE               — no provider-limit signal.

    The load-bearing split is TRANSIENT_OVERLOAD (retry) vs everything else
    (stop/defer). A real overload and a real quota window can BOTH arrive as a
    ``rejected`` rate-limit event — the disambiguator is the error TYPE
    (529/overloaded vs 429/quota) and the "(not your usage limit)" prose, NOT
    the ``rejected`` status alone.
    """

    TRANSIENT_OVERLOAD = "transient_overload"
    USAGE_WINDOW = "usage_window"
    HARD_QUOTA = "hard_quota"
    NONE = "none"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Canonical backoff ladder for a transient overload retry. Mirrors
# ``loop_decide._OVERLOADED_BACKOFF`` deliberately — this module is the shared
# source of truth, ``loop_decide`` keeps its own copy for the hot decide() path
# but the two MUST stay equal (asserted by a cross-module test in both repos).
_OVERLOAD_BACKOFF: tuple[int, ...] = (60, 270, 1200)
_OVERLOAD_ESCALATE_AFTER = 3  # consecutive TRANSIENT_OVERLOAD hits → stop


@dataclass(frozen=True)
class LimitPolicy:
    """The canonical handling policy for one :class:`ProviderLimit` category.

    A pure lookup (see :func:`policy_for`) — the single place the dispatch
    family reads "is this retryable, with what backoff, when do I escalate,
    does an operator have to act, will it clear on its own". Consumers must not
    re-derive these per-loop (that is the drift this module exists to kill).
    """

    category: ProviderLimit
    retryable_same_iter: bool
    """True only for TRANSIENT_OVERLOAD — retry the same unit of work."""

    backoff_seconds: tuple[int, ...]
    """Backoff ladder for the retry; ``()`` for non-retryable categories."""

    escalate_after: int
    """Consecutive hits of this category before escalating to a hard stop.

    ``_OVERLOAD_ESCALATE_AFTER`` (3) for TRANSIENT_OVERLOAD; ``1`` for the
    stop-now categories (the first hit already stops).
    """

    operator_action_required: bool
    """True for HARD_QUOTA — no backoff/wait resolves it; a human must act."""

    resets_on_timer: bool
    """True when the limit clears on its own (TRANSIENT_OVERLOAD, USAGE_WINDOW);
    False for HARD_QUOTA (operator-gated) and NONE."""


_POLICIES: dict[ProviderLimit, LimitPolicy] = {
    ProviderLimit.TRANSIENT_OVERLOAD: LimitPolicy(
        category=ProviderLimit.TRANSIENT_OVERLOAD,
        retryable_same_iter=True,
        backoff_seconds=_OVERLOAD_BACKOFF,
        escalate_after=_OVERLOAD_ESCALATE_AFTER,
        operator_action_required=False,
        resets_on_timer=True,
    ),
    ProviderLimit.USAGE_WINDOW: LimitPolicy(
        category=ProviderLimit.USAGE_WINDOW,
        retryable_same_iter=False,
        backoff_seconds=(),
        escalate_after=1,
        operator_action_required=False,
        resets_on_timer=True,
    ),
    ProviderLimit.HARD_QUOTA: LimitPolicy(
        category=ProviderLimit.HARD_QUOTA,
        retryable_same_iter=False,
        backoff_seconds=(),
        escalate_after=1,
        operator_action_required=True,
        resets_on_timer=False,
    ),
    ProviderLimit.NONE: LimitPolicy(
        category=ProviderLimit.NONE,
        retryable_same_iter=False,
        backoff_seconds=(),
        escalate_after=1,
        operator_action_required=False,
        resets_on_timer=False,
    ),
}


def policy_for(category: ProviderLimit) -> LimitPolicy:
    """Return the canonical :class:`LimitPolicy` for ``category``.

    Total over the enum — every :class:`ProviderLimit` member has a policy (a
    test asserts exhaustiveness, so a new category cannot ship without one).
    """
    return _POLICIES[category]


# ---------------------------------------------------------------------------
# Mappers — pure translators FROM each upstream taxonomy INTO the canonical
# category. They do NOT classify (the upstream classifier already did); they
# translate. Each takes the upstream token's str VALUE, so this module never
# imports the upstream class (keeps the job→dos dependency arrow one-way).
# ---------------------------------------------------------------------------

# rate_limit_classify.Kind values (job/scripts/rate_limit_classify.py).
_RATE_LIMIT_KIND_TO_CATEGORY: dict[str, ProviderLimit] = {
    "OVERLOADED": ProviderLimit.TRANSIENT_OVERLOAD,
    "RATE_LIMITED": ProviderLimit.USAGE_WINDOW,
    "CREDIT_LOW": ProviderLimit.HARD_QUOTA,
    "NONE": ProviderLimit.NONE,
}


def from_rate_limit_kind(kind: str) -> ProviderLimit:
    """Map a ``rate_limit_classify.Kind`` value → canonical category.

    Accepts the enum member or its ``str`` value (the enum is ``str``-valued,
    so ``str(Kind.OVERLOADED) == "OVERLOADED"``). Unknown → NONE (defensive:
    an unrecognized token must not masquerade as a real limit).
    """
    return _RATE_LIMIT_KIND_TO_CATEGORY.get(str(kind), ProviderLimit.NONE)


# agents.quota.QuotaErrorClass values (job/agents/quota/base.py).
_QUOTA_ERROR_CLASS_TO_CATEGORY: dict[str, ProviderLimit] = {
    "rpm_throttled": ProviderLimit.TRANSIENT_OVERLOAD,
    "transient_429": ProviderLimit.TRANSIENT_OVERLOAD,
    "daily_quota_exhausted": ProviderLimit.USAGE_WINDOW,
    "subscription_blackout": ProviderLimit.USAGE_WINDOW,
}


def from_quota_error_class(qec: str) -> ProviderLimit:
    """Map an ``agents.quota.QuotaErrorClass`` value → canonical category.

    This is the Bulkhead seam: the apply adapter keeps ``QuotaErrorClass``
    internally for its own backoff; at the dispatch boundary it maps UP into
    the canonical category. ``rpm_throttled``/``transient_429`` are short-timer
    server-side throttles → TRANSIENT_OVERLOAD; the daily/subscription caps are
    timer-reset windows → USAGE_WINDOW. (A genuine billing block surfaces as a
    HARD_QUOTA via the rate_limit_classify CREDIT_LOW path, not here.) Unknown →
    NONE.
    """
    return _QUOTA_ERROR_CLASS_TO_CATEGORY.get(str(qec), ProviderLimit.NONE)


# apply-next-loop Step-3 outcome tokens (job/.claude/skills/apply-next-loop).
_APPLY_OUTCOME_TOKEN_TO_CATEGORY: dict[str, ProviderLimit] = {
    "LLM-QUOTA-EXHAUSTED": ProviderLimit.USAGE_WINDOW,
    "LLM-QUOTA-EXHAUSTED-DURABLE": ProviderLimit.USAGE_WINDOW,
    # CORRELATED-OUTAGE / BROWSER-SERVICE-UNAVAILABLE are NOT provider limits —
    # they are infra outages with their own stop policy; they map to NONE so a
    # caller asking "is this a provider limit?" gets a truthful no.
    "CORRELATED-OUTAGE": ProviderLimit.NONE,
    "BROWSER-SERVICE-UNAVAILABLE": ProviderLimit.NONE,
}


def from_apply_outcome_token(token: str) -> ProviderLimit:
    """Map an apply-next-loop Step-3 outcome token → canonical category.

    Both the transient (``LLM-QUOTA-EXHAUSTED``, Q==3 stop) and the durable
    (``LLM-QUOTA-EXHAUSTED-DURABLE``, measured-window stop-on-first) quota
    tokens are USAGE_WINDOW — the durability difference is a policy nuance
    (``resets_on_timer`` + a measured ``window_end``), not a different category.
    Unknown / non-limit tokens → NONE.
    """
    return _APPLY_OUTCOME_TOKEN_TO_CATEGORY.get(str(token), ProviderLimit.NONE)


__all__ = [
    "ProviderLimit",
    "LimitPolicy",
    "policy_for",
    "from_rate_limit_kind",
    "from_quota_error_class",
    "from_apply_outcome_token",
]
