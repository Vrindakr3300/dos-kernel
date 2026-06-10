"""Claim TTL / kind / status math — pure branch logic over scalars.

Lifted from the job userland's ``scripts/fanout_state.py`` (MQ3X P1, docs/62).
The kernel half of the OS7 per-status TTL model: given a claim's
``(status, kind, expected_wallclock)`` scalars (and a frozen ``TtlPolicy`` of the
host's tuning), compute how long the claim lives. Plus the legacy-row inference
(``infer_kind`` / ``infer_status``) the ``stats`` / ``disambiguate`` verbs use to
label un-migrated rows consistently.

``dos`` carries **mechanism, not policy** (the package-wide invariant): the OS7
minute constants are job *tuning*, so they live on a ``TtlPolicy`` dataclass the
CALLER supplies — exactly the ``LivenessPolicy`` / ``loop_decide`` thresholds
split. The defaults below match the job's historical values so a caller that
passes ``DEFAULT_POLICY`` (or nothing) is byte-identical to the pre-lift code.

Purity boundary (docs/62 §0): every function here takes scalars and returns
scalars — zero ``datetime.now`` / ``os`` / ``Path`` / ``open`` / ``yaml`` /
``importlib``. The three job-side functions that read the CLOCK
(``_compute_expires_at`` / ``_claim_heartbeat_expired`` / ``_is_working_claim_fresh``)
keep their clock-reading WRAPPER in ``agents/leases/`` and delegate their decision
to the ``now``-injected pure cores here (``expires_at_from`` is the first; the
others land with the P3 io-layer move).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

# Claim taxonomy — the closed value sets. Carried with the inference functions
# because they decide which inferred label is "valid" (explicit field wins).
VALID_CLAIM_KINDS = ("soft", "hard", "agent_in_session")
VALID_CLAIM_STATUSES = ("working", "awaiting_decision", "awaiting_commit", "stale", "done")


@dataclass(frozen=True)
class TtlPolicy:
    """OS7 per-status TTL tuning — policy, not mechanism (job-side data).

    The single 90-min TTL was wrong for all three claim kinds; TTL now matches the
    kind's lifecycle. ``None`` resolved minutes = infinity (no ``claim_expires_at``
    written). The defaults reproduce the job's historical constants exactly:

      awaiting_commit_minutes  — 24h, drives the OS2 auto-archive cadence.
      agent_in_session_minutes — 6h, one operator session (overrides status).
      default_working_wallclock_minutes — used when ``expected_wallclock`` is absent
                                 (matches pre-OS7 ``--ttl-minutes 90`` callsites).
      working_ttl_multiplier   — working TTL = ``expected_wallclock × multiplier``.
    """

    awaiting_commit_minutes: int = 24 * 60
    agent_in_session_minutes: int = 6 * 60
    default_working_wallclock_minutes: int = 30
    working_ttl_multiplier: int = 3

    def __post_init__(self) -> None:
        for name in (
            "awaiting_commit_minutes", "agent_in_session_minutes",
            "default_working_wallclock_minutes", "working_ttl_multiplier",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"TtlPolicy.{name} must be non-negative")


DEFAULT_POLICY = TtlPolicy()


def infer_kind(
    entry: dict,
    dispatcher_kinds: tuple[tuple[str, str], ...] = (),
) -> str:
    """Infer claim_kind for legacy rows that pre-date the 2026-05-13 schema
    addition. Used by ``disambiguate`` and ``stats`` so the operator sees a
    consistent kind label even on un-migrated rows. Never written back to disk;
    the explicit field on new rows takes precedence.

    ``dispatcher_kinds`` is the host's ``(dispatched_by-prefix, claim_kind)`` map for
    the legacy fallback — the prefixes name a host's dispatcher SKILLS (e.g. the
    reference app's ``fanout-`` → ``hard`` / ``next-up-`` → ``soft``), so the kernel
    hardcodes NONE of them (userland-coupling audit 2026-06-08): the host passes its
    own. Pairs are tried in order; the first matching prefix wins. Empty (the kernel
    default) means a row with no explicit kind / TTL is simply ``unknown``."""
    if entry.get("claim_kind") in VALID_CLAIM_KINDS:
        return entry["claim_kind"]
    if entry.get("claim_expires_at"):
        return "soft"
    by = (entry.get("dispatched_by") or "").lower()
    for prefix, kind in dispatcher_kinds:
        if by.startswith(prefix.lower()):
            return kind
    return "unknown"


def infer_status(entry: dict) -> str:
    """Infer claim_status. Returns 'working' for in_progress rows lacking explicit
    claim_status; the precise working/stale split needs heartbeat substrate."""
    if entry.get("claim_status") in VALID_CLAIM_STATUSES:
        return entry["claim_status"]
    if entry.get("status") == "in_progress":
        return "working"
    return entry.get("status", "unknown")


def expected_wallclock(claim_kind: str, ttl_minutes: int | None) -> int:
    """Default expected wallclock per claim_kind. Used by the stale detector when
    an explicit ``expected_wallclock_minutes`` isn't set on the row."""
    if ttl_minutes:
        return ttl_minutes
    if claim_kind == "soft":
        return 90
    if claim_kind == "agent_in_session":
        return 60  # in-conversation agents tend to be quicker
    return 360  # hard fanout default — agents can take up to a few hours


def resolve_ttl_minutes(
    claim_status: str, claim_kind: str,
    expected_wallclock_minutes: int | None,
    policy: TtlPolicy = DEFAULT_POLICY,
) -> int | None:
    """OS7 — per-status TTL formula. Returns minutes until claim expiry, or
    ``None`` for infinity (no TTL field written).

    Resolution order:
      1. claim_kind=agent_in_session → 6h (in-conversation agents shouldn't linger
         past one operator session; overrides status formula).
      2. claim_status=working → expected_wallclock × multiplier (defaults to
         ``policy.default_working_wallclock_minutes`` when expected_wallclock is
         absent — matches pre-OS7 behaviour for legacy ``--ttl-minutes 90``).
      3. claim_status=awaiting_commit → 24h (drives OS2 auto-archive).
      4. claim_status=awaiting_decision / stale → None (operator drives resolution).
    """
    if claim_kind == "agent_in_session":
        return policy.agent_in_session_minutes
    if claim_status == "working":
        ew = expected_wallclock_minutes or policy.default_working_wallclock_minutes
        return ew * policy.working_ttl_multiplier
    if claim_status == "awaiting_commit":
        return policy.awaiting_commit_minutes
    return None


def expires_at_from(now: _dt.datetime, ttl_minutes: int | None) -> str | None:
    """Pure core of ``_compute_expires_at``: convert a TTL in minutes (or
    None=infinity) to an ISO ``%Y-%m-%dT%H:%MZ`` timestamp, given an injected
    ``now``. The clock-reading wrapper (``agents/leases/ttl.py``) supplies
    ``dt.datetime.now(dt.timezone.utc)``; this stays pure + replay-testable."""
    if ttl_minutes is None:
        return None
    expiry = now + _dt.timedelta(minutes=ttl_minutes)
    return expiry.strftime("%Y-%m-%dT%H:%MZ")
