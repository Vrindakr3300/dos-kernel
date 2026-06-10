"""Closed `reason_class` vocabulary for `/next-up` no-pick (WEDGE / DRAIN) verdicts.

⚓ One surface per metric / mechanical-contract-over-prose. Before this module the
WEDGE refusal — the single most common dispatch-loop outcome (110/128 runs shipped
0 picks in the 7d window of 2026-05-31, yet the scoreboard read `live_ship_rate=1.0`
because it only measures *launched* picks) — was authored entirely in `/next-up`
SKILL Step 2.5/Step 3 LLM prose. Each WEDGE envelope invented its own `reason_class`
token and its own ad-hoc JSON shape. The three consumers could not agree on the set:

  * the PRODUCER (`scripts/next_up_render.py`) only emitted typed verdicts for
    `LANE_DRAINED` / `ALREADY_SHIPPED` / `IN_FLIGHT` / `FILE_COLLISION` / `RACE`;
    every LANE_* WEDGE was hand-written;
  * the VERIFIER (`scripts/picker_oracle.py`) recognised ~8 tokens, NONE of the
    LANE_* WEDGE tokens the LLM actually wrote — so every WEDGE classified as
    `UNCLASSIFIED` ("cannot verify — recommend backfill"). The oracle reported
    itself healthy (`oracle_disagrees=0`) precisely because it could not classify
    the rows that mattered;
  * the CONSUMER (`scripts/fanout_preflight_context.py`) never opened the verdict
    envelope at all (FQ-410).

This module is the one place the token set is declared. All three consumers import
it, so a new reason class is added once, here, and is simultaneously:
emittable by the producer, verifiable by the oracle, and refusable by the preflight.

Pure stdlib (no third-party imports) so `next_up_render` / `fanout_state` /
`picker_oracle` / `fanout_preflight_context` can all import it without dragging in
their own heavy deps. The companion category vocabulary lives in
`picker_oracle.NoPickCause`; we mirror the category *strings* here (not the enum) to
avoid a circular import, and `tests/test_dispatch_pick_observability.py` pins the two in lockstep.
"""

from __future__ import annotations

import enum


class NoPickCategory(str, enum.Enum):
    """Coarse category each `reason_class` rolls up to.

    Mirrors the string values of `picker_oracle.NoPickCause` so the oracle can map
    a `WedgeReason` straight onto its verification branch. Kept as an independent
    enum (not an import of `NoPickCause`) so this low-level module has zero
    `scripts/`-internal deps; `tests/test_dispatch_pick_observability.py` asserts every value here
    is a member of `NoPickCause`.
    """

    TRUE_DRAIN = "TRUE_DRAIN"        # all in-scope plans remaining:[]; no findings
    OPERATOR_GATE = "OPERATOR_GATE"  # soak open / operator-attended / env-flag-gated
    STALE_CLAIM = "STALE_CLAIM"      # collision with an in-flight/foreign soft|hard claim
    LEASE_HELD = "OPERATOR_GATE"     # foreign live /dispatch-loop owns the lane lease
    INFLIGHT = "STALE_CLAIM"         # remaining phases all soft-claimed by a sibling packet
    MISROUTE = "MISROUTE"            # finding routed to the wrong lane
    RENDERER_BUG = "RENDERER_BUG"    # packet rendered picks but the renderer dropped an artifact
    UNCLASSIFIED = "UNCLASSIFIED"    # legacy / hand-authored envelope, no known token


@enum.unique
class WedgeReason(str, enum.Enum):
    """The closed set of `reason_class` tokens a no-pick verdict may carry.

    Membership here is the contract: the producer validates against it before
    writing an envelope, the oracle maps each member onto a `NoPickCause`, and the
    preflight refuses a packet whose envelope carries any of them. A token observed
    in the wild that is NOT here is exactly the prose-drift this module exists to
    end — it surfaces as `UNCLASSIFIED` and is a bug to add, not to tolerate.

    The tokens below are the union of (a) the deterministic verdicts the renderer
    already wrote and (b) every distinct LANE_* token observed in real
    `output/next-up/.verdict-*.json` envelopes through 2026-05-31.
    """

    # --- deterministic, already code-emitted -------------------------------
    LANE_DRAINED = "LANE_DRAINED"                      # 0 plans + 0 findings (true drain)

    # --- the LANE_* family, formerly LLM-prose-only ------------------------
    # Every remaining phase is soak-observation-gated with no dispatchable code
    # follow-up (TM5 7d soak; AR7 blocked on AR5 soak denominator).
    LANE_BLOCKED_ON_SOAK_GATED_PHASES = "LANE_BLOCKED_ON_SOAK_GATED_PHASES"
    # A foreign, live /dispatch-loop holds this cluster's lane lease (racing it is
    # the collision the lane arbiter exists to prevent). Carry the holder in `reason`.
    LANE_LEASE_HELD_BY_LIVE_DISPATCH_LOOP = "LANE_LEASE_HELD_BY_LIVE_DISPATCH_LOOP"
    # Remaining phases are all soft-claimed in-flight by a sibling packet, and/or
    # deferred by the plan body's own gate.
    LANE_ALL_INFLIGHT_OR_DEFERRED = "LANE_ALL_INFLIGHT_OR_DEFERRED"
    # The lane's remaining phases are a mix of shipped-but-unstamped + in-flight +
    # stale-stamped — the apply/tailor "everything's already done or drifting" shape.
    LANE_ALL_SHIPPED_INFLIGHT_OR_STALE_STAMP = "LANE_ALL_SHIPPED_INFLIGHT_OR_STALE_STAMP"
    # Generic "every remaining phase is blocked, or its stamp is drifted" — the
    # catch-all the tailor lane wrote when soak + stamp-drift co-occur.
    LANE_ALL_BLOCKED_OR_STALE_STAMP = "LANE_ALL_BLOCKED_OR_STALE_STAMP"
    # The lane is blocked on an unanswered operator decision (e.g. CD #357), and the
    # routing finding is already soft-claimed by a sibling. No automation clears it.
    LANE_BLOCKED_ON_OPERATOR_DECISION = "LANE_BLOCKED_ON_OPERATOR_DECISION"

    # --- producer-failure class (NOT a no-pick — picks EXIST) --------------
    # The renderer rendered >= 1 pick but DROPPED the `.prompts.json` prompt
    # sidecar (absent / corrupt / empty bodies), so the orchestrator has no
    # worker prompt to launch. Unlike every LANE_* reason above (the picker
    # decided not to pick), this is a *producer* defect: the picker picked, the
    # renderer failed to serialize the bodies. FQ-419/FQ-420 — the root cause
    # behind the recurring downstream `body_empty_picks` refuse (6+ consecutive
    # dispatch runs wedged across apply/tailor/CD lanes, 2026-06-01). The
    # producer-side verify (`dos.packet_sidecar.assert_packet_shippable`) emits
    # this so the refusal points at the renderer, one rung above /fanout. Routes
    # to /unstick (a structural renderer fix), not /replan (the backlog is fine).
    RENDERER_SIDECAR_DROPPED = "RENDERER_SIDECAR_DROPPED"


# Each WedgeReason → its NoPickCategory. Exhaustive over the enum (a test asserts
# completeness), so adding a member without categorising it fails CI rather than
# silently degrading to UNCLASSIFIED at runtime.
REASON_TO_CATEGORY: dict[WedgeReason, NoPickCategory] = {
    WedgeReason.LANE_DRAINED: NoPickCategory.TRUE_DRAIN,
    WedgeReason.LANE_BLOCKED_ON_SOAK_GATED_PHASES: NoPickCategory.OPERATOR_GATE,
    WedgeReason.LANE_LEASE_HELD_BY_LIVE_DISPATCH_LOOP: NoPickCategory.LEASE_HELD,
    WedgeReason.LANE_ALL_INFLIGHT_OR_DEFERRED: NoPickCategory.INFLIGHT,
    WedgeReason.LANE_ALL_SHIPPED_INFLIGHT_OR_STALE_STAMP: NoPickCategory.INFLIGHT,
    WedgeReason.LANE_ALL_BLOCKED_OR_STALE_STAMP: NoPickCategory.OPERATOR_GATE,
    WedgeReason.LANE_BLOCKED_ON_OPERATOR_DECISION: NoPickCategory.OPERATOR_GATE,
    WedgeReason.RENDERER_SIDECAR_DROPPED: NoPickCategory.RENDERER_BUG,
}

# A WEDGE carrying any of these reason classes means "do not render, route to
# /replan" — it is a refusal, not a deferred-but-valid packet. (All of them, today;
# the set is named explicitly so a future advisory-only reason class can be added
# without auto-refusing.)
REFUSE_REASONS: frozenset[WedgeReason] = frozenset(REASON_TO_CATEGORY)

_ALL_TOKENS: frozenset[str] = frozenset(r.value for r in WedgeReason)


# ---------------------------------------------------------------------------
# Registry-aware helpers.
#
# The `WedgeReason` enum above is the BUILT-IN reason set, kept verbatim so this
# module stays byte-compatible (every `WedgeReason.X` reference, the lockstep
# test, the `REASON_TO_CATEGORY`/`REFUSE_REASONS` maps all unchanged). The four
# helpers below are the hackability seam: they answer for the built-in set first
# (fast, no I/O), then fall through to the ACTIVE WORKSPACE's `ReasonRegistry`
# (`dos.config.active().reasons`) so a workspace-DECLARED reason — one that is not
# a `WedgeReason` enum member — is still known / categorised / refusable through
# the exact same call. `coerce` still returns an enum member for a built-in token
# (callers that switch on `WedgeReason.X` are unaffected) and `None` for a
# registry-only token (use `category_for` / `is_refusal`, which understand both).
#
# `dos.config` is imported LAZILY inside each helper so this module keeps its
# leaf-import character (it does not pull `config` at import time — `picker_oracle`
# imports `wedge_reason` precisely because it is cheap), and so a process that
# never installs a custom registry pays nothing.
# ---------------------------------------------------------------------------


def _active_reasons():
    """The active workspace's ReasonRegistry, or None if config is unavailable.

    Lazy + defensive: if `dos.config` cannot be imported or no config is active,
    return None and the caller falls back to the built-in enum alone — the
    helpers must never crash a consumer just because no workspace was installed.
    """
    try:
        from dos import config as _config
        return _config.active().reasons
    except Exception:
        return None


def is_known_reason(token: str | None) -> bool:
    """True iff `token` is a known reason — a built-in `WedgeReason` member OR a
    reason declared on the active workspace's `ReasonRegistry` (case-insensitive)."""
    if not token:
        return False
    if token.strip().upper() in _ALL_TOKENS:
        return True
    reg = _active_reasons()
    return bool(reg and reg.is_known(token))


def coerce(token: str | None) -> WedgeReason | None:
    """Return the built-in `WedgeReason` for `token`, or None.

    Case-insensitive and whitespace-tolerant so a hand-authored envelope (during the
    prose→code transition) still classifies. Returns None for a token that is not a
    BUILT-IN member — including a workspace-declared registry-only reason; such a
    token is real and known (`is_known_reason` is True, `category_for`/`is_refusal`
    answer for it) but has no enum member, so callers that need the typed enum use
    the built-in set while callers that need the verdict use the registry-aware
    helpers below.
    """
    if not token:
        return None
    try:
        return WedgeReason(token.strip().upper())
    except ValueError:
        return None


def category_for(token: str | None) -> NoPickCategory:
    """Map a `reason_class` token onto its NoPickCategory.

    Built-in members resolve through `REASON_TO_CATEGORY`. A workspace-declared
    reason resolves through the active `ReasonRegistry` (its category string is a
    `NoPickCategory` value by construction). A token known to neither →
    `UNCLASSIFIED` (forward-compatible: a brand-new label does not crash a
    consumer, it classifies as drift until declared — and `--check` turns that
    drift into a CI failure).
    """
    reason = coerce(token)
    if reason is not None:
        return REASON_TO_CATEGORY[reason]
    reg = _active_reasons()
    if reg is not None:
        cat = reg.category_for(token)  # 'UNCLASSIFIED' for an unknown token
        try:
            return NoPickCategory(cat)
        except ValueError:
            return NoPickCategory.UNCLASSIFIED
    return NoPickCategory.UNCLASSIFIED


def is_refusal(token: str | None) -> bool:
    """True iff a verdict carrying `token` must NOT be rendered (route to /replan).

    Used by `fanout_preflight_context` to refuse a packet whose `.verdict` envelope
    was pre-routed WEDGE, independent of how many picks look live (FQ-410). A
    built-in member honors `REFUSE_REASONS`; a workspace-declared reason honors its
    own `refusal` flag (so a workspace CAN declare an advisory-only reason). Unknown
    tokens are treated as refusals — a no-pick envelope with an unrecognised
    reason_class is still a no-pick, and launching against it is the exact hazard.
    """
    reason = coerce(token)
    if reason is not None:
        return reason in REFUSE_REASONS
    reg = _active_reasons()
    if reg is not None:
        # The registry returns True for both a declared-refusal reason AND an
        # unknown token (its own conservative default) — exactly the policy here.
        return reg.is_refusal(token)
    # No registry available — an unrecognised token is drift; refuse conservatively.
    return True


# A verdict carrying one of these (or no verdict at all) is launchable; anything
# else (WEDGE / DRAIN / RACE / …) is a refusal shape. The single source of truth
# for the launchable set — `preflight` and `decisions` previously each kept their
# own identical copy of this frozenset (one edit from drift).
LAUNCHABLE_VERDICTS: frozenset[str] = frozenset({"", "LIVE", "ACCEPT"})


def envelope_is_refusal(envelope: dict | None) -> tuple[bool, str | None]:
    """Decide whether a `.verdict-<tag>.json` ENVELOPE means REFUSE (do not launch).

    The one canonical reader of an envelope's refusal shape — `preflight` (which
    gates a packet launch) and `decisions` (which surfaces a no-pick as an operator
    decision) both need exactly this judgement, and previously each carried its own
    byte-identical copy flagged "kept in lockstep" (the drift hazard this collapses).
    It belongs here beside `is_refusal(token)`: that answers for a bare reason
    *token*, this answers for the whole *envelope* — the token check is one of the
    four rungs below.

    Refuses when the envelope is a no-pick / blocked shape, most-specific first:
      * `do_not_render` truthy, or `blocked` truthy without `all_clear`;
      * `verdict` is anything other than a launchable token (LIVE / ACCEPT / absent)
        — i.e. WEDGE / DRAIN / RACE;
      * `reason_class` is a known refusal token (`is_refusal`).
    A LIVE-shaped envelope (`all_clear=true` and a launchable verdict) does NOT
    refuse. Returns `(refuse, reason)` where reason is a short machine-readable tag
    (or None when not a refusal), prefixed `verdict_envelope:` for log greppability.
    """
    if not envelope:
        return (False, None)
    verdict = str(envelope.get("verdict") or "").strip().upper()
    reason_class = envelope.get("reason_class")
    all_clear = bool(envelope.get("all_clear"))
    if envelope.get("do_not_render"):
        return (True, f"verdict_envelope:do_not_render verdict={verdict or '?'}")
    if envelope.get("blocked") and not all_clear:
        return (True, f"verdict_envelope:blocked verdict={verdict or '?'}")
    if verdict and verdict not in LAUNCHABLE_VERDICTS:
        return (True, f"verdict_envelope:verdict={verdict}")
    if reason_class is not None and is_refusal(str(reason_class)):
        return (True, f"verdict_envelope:reason_class={reason_class}")
    return (False, None)
