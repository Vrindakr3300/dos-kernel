"""Typed gate verdict for a /next-up packet (QWB6).

Today the empty-packet gate in /dispatch-loop is a single binary fork — a
packet either has live picks or it does not, and "no live picks" is treated as
one thing: *drain*. But a 0-pick packet has at least three distinct root
causes, and each warrants a different response. Collapsing them is what lets
/dispatch-loop false-stop on stale stamps (queue #240, observed live in run
`20260517T1626Z` iter 3 — the loop "drained" while the backlog was full,
only the plan-doc SHIPPED stamps were stale).

`classify_packet()` is the keystone fix: a **pure** function that turns the
packet's picks + their dispositions into one typed verdict —

    LIVE         packet has >= 1 soft-claimable pick
    DRAIN        genuine empty backlog — nothing left to dispatch
    STALE-STAMP  phases shipped in git but plan-doc rows unstamped (false drain)
    BLOCKED      picks exist but soft-claimed by a sibling, or quota-blocked
                 (was WEDGE — renamed; WEDGE survives as a permanent alias)

QWB7 (the `--gate hard|soft|drive` policy) and QWB8 (`/dispatch` emits the
verdict token) are thin consumers of this function — they are NOT wired here.

⚓ Data-driven decisions (evidence-over-narrative): the verdict is derived from
already-loaded portfolio state — the packet's picks and their per-pick
dispositions (each carrying `check_phase_shipped`'s `via` field and the
plan-doc stamp boolean) — never from /dispatch's prose reply. Run
`20260517T1626Z` iter 3 *said* "stamp drift" in prose, but the loop could not
branch on prose, so it false-stopped. The verdict type is the fix.

⚓ Typed verdict over binary gate: a control-flow gate whose one signal
(drained backlog) has multiple root causes needs a typed verdict, not a binary
fork. `classify_packet` is pure (no subprocess, no file I/O — the caller passes
already-loaded state) precisely so it can be tested in isolation, away from
everything that makes a live /dispatch run expensive.

OC3 (2026-05-18): `classify_packet_file` is the validated I/O wrapper around
the pure `classify_packet`. Pre-OC3, /dispatch Step 5.6.1 *resolved* the
disposition list by hand-parsing the packet's `## Course corrections` prose —
the OC-P3 weakness: a well-formed-but-wrong dict produced a plausible-but-wrong
verdict (findings #240). OC3 moved disposition resolution into /next-up's
renderer, which emits the structured list to `.dispositions-<tag>.json`;
`classify_packet_file` reads that sidecar, rejects a stale/wrong-schema
contract (`StaleDispositionContract`), and delegates to `classify_packet`.
The classifier stays pure and is still the unit-test surface.
"""
from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The gate-side verdict enum is now defined centrally in scripts/dispatch_tokens.py
# (the single source of truth for every dispatch verdict/outcome/reason token).
# Re-export it here as `Verdict` so every existing `from gate_classify import
# Verdict` / `gate_classify.Verdict` reference keeps working unchanged (a
# byte-compatible re-export shim — the same pattern apply_core uses per CLAUDE.md).
# `Verdict.WEDGE` survives as a permanent Enum alias of `Verdict.BLOCKED` defined
# on GateVerdict, so any un-migrated `verdict is Verdict.WEDGE` keeps working.
# In DOS the verdict vocabulary lives in `dos.tokens` (the ported
# `dispatch_tokens`). One canonical package import — the dual-mode bare-sibling
# fallback the origin repo needed (scripts run as bare files) is gone now that
# everything is a proper package module.
from dos.tokens import GateVerdict as Verdict  # noqa: F401


# Drop-reason tokens a caller stamps on a dropped pick's disposition. These
# are the artefact the classifier keys on — not the packet's prose.
DROP_SHIPPED = "shipped"          # check_phase_shipped proved the phase shipped
DROP_SOFT_CLAIMED = "soft_claimed"  # a sibling fanout holds a live soft-claim
DROP_QUOTA_BLOCKED = "quota_blocked"  # quota / credential saturation

# `via` value from check_phase_shipped that counts as an unambiguous direct
# ship. STALE-STAMP is deliberately scoped to direct-ship evidence only — a
# weak verdict (release-prefix / body-mention / file-path) is exactly the
# #230 false-positive surface, and treating it as a confirmed ship would let
# the loop auto-clear drift that was never real.
SHIP_VIA_DIRECT = "direct"


@dataclass(frozen=True)
class PickDisposition:
    """The per-pick evidence `classify_packet` consumes.

    A pick the packet *kept* (rendered as soft-claimable) has `live=True` and
    needs no other field. A pick the packet *dropped* (auto-dropped to Course
    corrections) has `live=False` and carries the evidence for *why* it
    dropped — the artefact the verdict stands on.
    """

    series: str
    phase: str
    live: bool
    # Evidence for a dropped pick (`live=False`). Ignored when `live=True`.
    drop_reason: str = ""        # one of DROP_* above
    ship_via: str = ""           # check_phase_shipped `via` field, when drop_reason==shipped
    ship_sha: str = ""           # the ship commit, for the reason string
    plan_doc_stamped: bool = True  # does the plan-doc heading carry a SHIPPED token?
    claim_tag: str = ""          # the fanout tag holding a live soft-claim, when soft_claimed

    def is_stale_stamp(self) -> bool:
        """True when this dropped pick is a shipped-but-unstamped phase.

        Direct-ship git evidence AND a plan-doc heading with no SHIPPED token
        — the exact false-drain shape behind queue #240. Weak ship verdicts
        do not qualify (see SHIP_VIA_DIRECT).
        """
        return (
            not self.live
            and self.drop_reason == DROP_SHIPPED
            and self.ship_via == SHIP_VIA_DIRECT
            and not self.plan_doc_stamped
        )

    def is_blocked(self) -> bool:
        """True when this dropped pick is blocked, not drained.

        A live soft-claim under a sibling tag, or a quota/credential block —
        work that exists but cannot be dispatched right now. (Was `is_wedge`;
        renamed alongside the WEDGE→BLOCKED verdict rename.)
        """
        return not self.live and self.drop_reason in (
            DROP_SOFT_CLAIMED,
            DROP_QUOTA_BLOCKED,
        )


@dataclass(frozen=True)
class ClassifyResult:
    """The typed verdict plus the evidence that produced it.

    `verdict` is the load-bearing field /dispatch-loop branches on. `reason`
    is a one-line operator-facing summary (drained-twice stop messages, the
    QWB8 archive-commit subject). `evidence` is the subset of dispositions
    that drove the verdict — kept so QWB7/QWB8 can surface *which* phases are
    stale/blocked without re-deriving them.
    """

    verdict: Verdict
    reason: str
    evidence: list[PickDisposition] = field(default_factory=list)

    @property
    def is_false_drain(self) -> bool:
        """True when this verdict is a non-`DRAIN` 0-live-pick gate.

        STALE-STAMP, BLOCKED, and RACE all render as "0 live picks" to the old
        binary gate, which is exactly why it false-stopped. QWB7's drained-twice
        rule counts `DRAIN` only — this property names the class it must
        exclude. NRT2 added RACE to this set: a lost candidates-cache lock
        race is also a "0 live picks" shape that must not arm drained-twice.
        """
        return self.verdict in (
            Verdict.STALE_STAMP,
            Verdict.BLOCKED,
            Verdict.RACE,
        )


class MalformedDisposition(ValueError):
    """A disposition dict the classifier cannot coerce.

    Raised instead of a bare ``KeyError`` so a caller (the /dispatch skill
    building dispositions from prose) gets a named, actionable error naming
    the missing field — not a stack trace that the loop swallows into a
    conservative DRAIN. See the dispatch SKILL Step 5.6.1 for the schema.
    """


def _coerce(obj: Any) -> PickDisposition:
    """Accept either a PickDisposition or a plain dict (fixture / JSON shape).

    The dict schema is tolerant by design — /dispatch builds these by hand
    from prose, so the easy-to-miss fields are aliased or derived:

    - ``phase`` accepts ``phase_id`` as an alias.
    - ``series`` is optional: when absent it is derived from ``phase`` by
      stripping the trailing phase number (``FB2`` -> ``FB``).
    - ``live`` defaults to ``False`` (the dropped-pick case — the only case
      that carries evidence; a live pick needs no disposition dict at all).

    A genuinely unusable dict (no ``phase``/``phase_id`` at all) raises
    ``MalformedDisposition``, never a bare ``KeyError``.
    """
    if isinstance(obj, PickDisposition):
        return obj
    if not isinstance(obj, dict):
        raise MalformedDisposition(
            f"disposition must be a PickDisposition or dict, got {type(obj).__name__}"
        )

    phase = obj.get("phase") or obj.get("phase_id")
    if not phase:
        raise MalformedDisposition(
            f"disposition is missing 'phase' (or 'phase_id'): {obj!r}"
        )

    series = obj.get("series")
    if not series:
        # Derive from the phase id: strip the trailing run of digits/dots.
        series = re.sub(r"[\d.]+$", "", str(phase)) or str(phase)

    return PickDisposition(
        series=str(series),
        phase=str(phase),
        live=bool(obj.get("live", False)),
        drop_reason=obj.get("drop_reason", ""),
        ship_via=obj.get("ship_via", ""),
        ship_sha=obj.get("ship_sha", ""),
        plan_doc_stamped=bool(obj.get("plan_doc_stamped", True)),
        claim_tag=obj.get("claim_tag", ""),
    )


def classify_packet(dispositions: list[Any]) -> ClassifyResult:
    """Classify a /next-up packet's picks into one typed gate verdict.

    PURE — no subprocess, no file or git I/O. The caller resolves every pick's
    disposition first (run `check_phase_shipped` for the `via` field, read the
    plan-doc heading for the stamp boolean, check the registry for sibling
    soft-claims) and passes the already-decided evidence in.

    `dispositions` — a list of `PickDisposition` (or dict equivalents, the
    fixture/JSON shape). One per pick the packet rendered, kept or dropped.

    Decision order is most-specific-first so a mixed packet resolves
    deterministically:

      1. LIVE        — any pick is `live` (soft-claimable). A packet with even
                       one live pick is not drained, whatever the others are.
      2. STALE-STAMP — no live picks, and >= 1 dropped pick is a direct-ship
                       phase whose plan-doc heading lacks a SHIPPED token. This
                       is the #240 false-drain: work shipped, the doc lagged.
      3. BLOCKED     — no live picks, no stale stamps, and >= 1 dropped pick is
                       soft-claimed by a sibling tag or quota-blocked.
      4. DRAIN       — no live picks and no recoverable signal: a genuine
                       empty backlog. The only verdict QWB7's drained-twice
                       rule may count toward an early stop.

    An empty packet (`dispositions == []`) is `DRAIN` — /next-up rendered no
    picks at all, so there is nothing left to dispatch.
    """
    dets = [_coerce(d) for d in dispositions]

    live = [d for d in dets if d.live]
    if live:
        return ClassifyResult(
            verdict=Verdict.LIVE,
            reason=f"{len(live)} live pick(s) — packet has dispatchable work",
            evidence=live,
        )

    stale = [d for d in dets if d.is_stale_stamp()]
    if stale:
        ids = ", ".join(f"{d.series} {d.phase}" for d in stale)
        return ClassifyResult(
            verdict=Verdict.STALE_STAMP,
            reason=(
                f"{len(stale)} pick(s) shipped in git but plan-doc unstamped "
                f"({ids}) — false drain, not an empty backlog"
            ),
            evidence=stale,
        )

    blocked = [d for d in dets if d.is_blocked()]
    if blocked:
        ids = ", ".join(f"{d.series} {d.phase}" for d in blocked)
        return ClassifyResult(
            verdict=Verdict.BLOCKED,
            reason=(
                f"{len(blocked)} pick(s) blocked by a sibling soft-claim or "
                f"quota ({ids}) — work exists but is not dispatchable now"
            ),
            evidence=blocked,
        )

    return ClassifyResult(
        verdict=Verdict.DRAIN,
        reason="no live picks and no recoverable signal — backlog genuinely drained",
        evidence=[],
    )


# ---------------------------------------------------------------------------
# OC3 — classify directly from the renderer's disposition sidecar.
#
# `classify_packet` is pure: the caller resolves every pick's disposition and
# passes the list in. Pre-OC3, /dispatch Step 5.6.1 *resolved* that list by
# hand-parsing the packet's `## Course corrections` prose — the OC-P3 weakness
# (a well-formed-but-wrong dict → a plausible-but-wrong verdict, findings
# #240). OC3 moved the resolution to the renderer, which emits the structured
# list to `.dispositions-<tag>.json`. `classify_packet_file` reads that file,
# validates the envelope, and delegates to `classify_packet`. /dispatch now
# makes one call against a derived artefact — there is no hand-assembly step.
#
# `classify_packet` stays pure and is still the unit-test surface; this
# function is the thin, validated I/O wrapper around it.
# ---------------------------------------------------------------------------

# The schema tag the renderer (`next_up_render._build_dispositions` →
# `cmd_render`) stamps on the sidecar. A mismatch fails loudly: a /dispatch
# reading a contract its /next-up did not write is exactly the OC-P4 silent
# drift this guard refuses to let through.
DISPOSITIONS_SCHEMA = "oc3-dispositions-v1"

# NRT2 (docs/53): the schema tag the renderer's `_emit_race_envelope` stamps
# on the per-tag race sidecar (`output/next-up/.race-<tag>.json`). A wrong
# `schema` value silently degrades to the existing classification (DRAIN /
# STALE-STAMP / BLOCKED) — a malformed race envelope must NOT promote an
# otherwise-LIVE packet to RACE.
RACE_SCHEMA = "next-up-race-v1"


class StaleDispositionContract(ValueError):
    """The disposition sidecar is missing, malformed, or a schema mismatch.

    Raised — rather than silently falling back to a conservative ``DRAIN`` —
    so a /dispatch reading a stale or wrong-shaped contract fails specifically
    and visibly. The caller decides the fallback (Step 5.6.1's documented
    ``DRAIN`` default), but it does so *knowing* the sidecar was unusable, not
    by accident.
    """


def _race_envelope_for(dispositions_path: Path) -> ClassifyResult | None:
    """If a sibling `.race-<tag>.json` envelope exists alongside the OC3
    sidecar AND carries `schema == RACE_SCHEMA`, return a typed RACE
    `ClassifyResult` that names the foreign holder. Otherwise return None.

    NRT2 (docs/53): the race envelope is the artefact `next_up_render` writes
    when `_acquire_candidates_lock_or_race` times out. Its presence next to
    the packet's tag means this /next-up shell lost a lock race against a
    sibling — the packet on disk (if any) is wrong-scope and the loop must
    not classify it as DRAIN / STALE-STAMP / BLOCKED.

    A malformed envelope (bad JSON, wrong schema, missing fields) returns
    None — RACE classification is *precedence-only*; an unusable race file
    falls through to the existing verdicts so a corrupt sidecar cannot
    silently promote a real LIVE/DRAIN/BLOCKED packet to a spurious RACE.
    """
    name = dispositions_path.name
    if name.startswith(".dispositions-") and name.endswith(".json"):
        tag = name[len(".dispositions-"):-len(".json")]
    else:
        return None
    race_path = dispositions_path.parent / f".race-{tag}.json"
    if not race_path.exists():
        return None
    try:
        env = json.loads(race_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(env, dict) or env.get("schema") != RACE_SCHEMA:
        return None
    blocked_by = env.get("blocked_by_pid")
    attempted_at = env.get("attempted_at") or "(unknown)"
    lock_path = env.get("lock_path") or "(unknown)"
    reason = env.get("reason") or (
        f"/next-up shell lost the candidates-cache lock race for tag={tag!r} "
        f"(blocked_by_pid={blocked_by}, attempted_at={attempted_at}, "
        f"lock_path={lock_path})"
    )
    return ClassifyResult(verdict=Verdict.RACE, reason=reason, evidence=[])


def classify_packet_file(path: str | Path) -> ClassifyResult:
    """Classify a /next-up packet from its OC3 disposition sidecar file.

    `path` — the `.dispositions-<tag>.json` the renderer wrote next to the
    packet. The file's envelope is `{"tag", "schema", "dispositions": [...]}`.

    NRT2 (docs/53): if a sibling `.race-<tag>.json` envelope (schema
    `next-up-race-v1`) exists in the same directory, that wins — the packet
    came from a /next-up shell that lost a candidates-cache lock race, and the
    on-disk packet is wrong-scope. RACE takes precedence over DRAIN /
    STALE-STAMP / WEDGE because those classifications would be derived from
    the wrong-scope packet. A malformed race envelope (bad JSON, wrong schema)
    falls through to the existing classification so a corrupt sidecar cannot
    silently promote a real verdict to a spurious RACE.

    Raises `StaleDispositionContract` when the file is absent, is not valid
    JSON, lacks the `dispositions` array, or carries a `schema` value other
    than `DISPOSITIONS_SCHEMA` — a wrong-shaped contract fails loudly here
    instead of producing a plausible-but-wrong verdict downstream.

    A well-formed file delegates straight to the pure `classify_packet`.
    """
    p = Path(path)
    race = _race_envelope_for(p)
    if race is not None:
        return race
    if not p.exists():
        raise StaleDispositionContract(
            f"disposition sidecar not found: {p} — "
            f"run `next_up_render.py render` to emit it"
        )
    try:
        envelope = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise StaleDispositionContract(
            f"disposition sidecar {p} is not readable JSON: {e}"
        ) from e
    if not isinstance(envelope, dict):
        raise StaleDispositionContract(
            f"disposition sidecar {p} is not a JSON object: {type(envelope).__name__}"
        )
    schema = envelope.get("schema")
    if schema != DISPOSITIONS_SCHEMA:
        raise StaleDispositionContract(
            f"disposition sidecar {p} has schema {schema!r}, "
            f"expected {DISPOSITIONS_SCHEMA!r} — the /next-up that wrote it is "
            f"out of contract with this /dispatch"
        )
    dispositions = envelope.get("dispositions")
    if not isinstance(dispositions, list):
        raise StaleDispositionContract(
            f"disposition sidecar {p} has no `dispositions` list "
            f"(got {type(dispositions).__name__})"
        )
    # `_coerce` inside `classify_packet` raises `MalformedDisposition` on a
    # genuinely unusable entry — that surfaces as-is; it is the per-field
    # loud failure the schema guard's sibling.
    return classify_packet(dispositions)


# ---------------------------------------------------------------------------
# QWB7 — gate policy modes for /dispatch-loop.
#
# classify_packet() above turns a packet into one typed Verdict. QWB7 adds the
# *policy* layer: given that verdict and a `--gate hard|soft|drive` mode chosen
# at /dispatch-loop invocation, what should the loop actually DO with this
# iteration? One classifier, three callers, an explicit policy — exactly the
# rebalance the ⚓ typed-verdict-over-binary-gate anchor names ("give the loop a
# policy when one gate must serve different intents").
#
# `gate_policy()` is pure for the same reason `classify_packet()` is: the
# Tier-3 replay harness must exercise the hard-vs-drive divergence without a
# live /dispatch run.
# ---------------------------------------------------------------------------

# The three gate policy modes. `hard` is the default — bare /dispatch-loop is
# byte-unchanged.
GATE_HARD = "hard"
GATE_SOFT = "soft"
GATE_DRIVE = "drive"
GATE_MODES = (GATE_HARD, GATE_SOFT, GATE_DRIVE)


@dataclass(frozen=True)
class GateAction:
    """What /dispatch-loop's Step 3 does with one iteration's verdict.

    A pure value the loop branches on — the policy decision extracted out of
    SKILL.md prose so the Tier-3 replay can assert it without a live run.

    Fields:
      next_mode             — `dispatch` | `replan` | `stop`. `stop` ends the
                              loop; `dispatch`/`replan` is the next iteration's
                              mode.
      counts_toward_drain   — True iff this iteration increments the
                              drained-twice counter. QWB7's load-bearing rule:
                              **only a true DRAIN counts.** STALE-STAMP and
                              BLOCKED never do — that kills the #240 false-stop
                              class structurally.
      reconcile             — True iff the loop must run an inline stamp-
                              reconcile pass (QWB2's reconcile_plan_doc_stamps)
                              before the next iteration. Set for `drive`/`soft`
                              on STALE-STAMP — the loop self-heals stamp drift
                              instead of stopping on it.
      surface               — True iff the loop must surface this verdict to
                              the operator (a stop that needs a human, or a
                              BLOCKED the loop will not sit waiting on).
      reason                — one-line operator-facing summary.
    """

    next_mode: str
    counts_toward_drain: bool
    reconcile: bool
    surface: bool
    reason: str


def gate_policy(verdict: Verdict, mode: str = GATE_HARD) -> GateAction:
    """Map a typed gate verdict + a `--gate` mode to a loop action.

    PURE — no I/O. The caller (/dispatch-loop Step 3) has already run
    `classify_packet()` for the verdict and parsed `--gate` once at Step 0.

    The policy matrix (QWB7 plan, docs/44):

      | --gate | STALE-STAMP            | BLOCKED        | DRAIN              | RACE                |
      |--------|-----------------------|----------------|--------------------|--------------------|
      | hard   | /replan, counts*      | /replan, counts*| /replan, stop on 2nd| continue, retry-once|
      | soft   | auto-clear, re-dispatch| stop + surface | stop + surface     | continue, retry-once|
      | drive  | auto-clear, re-dispatch| stop + surface | stop on true DRAIN | continue, retry-once|

    NRT2 (docs/53): RACE behaves the same in all three modes — sleep + retry-
    once, never count toward drained-twice / SHIPPED-DIRTY-0. The packet on
    disk is wrong-scope; the foreign holder will produce the intended packet.

      * `hard` keeps today's behavior: a non-LIVE verdict routes to /replan and
        the iteration counts toward drained-twice. (Pre-QWB7 the loop counted
        *every* gate; QWB7's precise rule is DRAIN-only — but under `hard` a
        STALE-STAMP/BLOCKED still routes to /replan, so the operator who wants
        the old conservative behavior gets it. The difference: even under
        `hard`, STALE-STAMP/BLOCKED no longer *increment the counter*, so a
        single stale-stamp gate can no longer arm a false drained-twice stop —
        it just spends a /replan iteration. This is the structural #240 fix;
        `drive` then goes further and self-heals inline.)

    LIVE is never a gate verdict the loop branches on here — a LIVE packet
    means /fanout ran and shipped; the loop simply continues `dispatch`. It is
    accepted for completeness so a caller can route any verdict through one
    function.

    `mode` defaults to `hard`; an unknown mode raises `ValueError` (the Step 0
    parser must reject a bad `--gate` value before threading it).
    """
    if mode not in GATE_MODES:
        raise ValueError(
            f"unknown --gate mode {mode!r} — expected one of {GATE_MODES}"
        )

    if verdict is Verdict.LIVE:
        return GateAction(
            next_mode="dispatch",
            counts_toward_drain=False,
            reconcile=False,
            surface=False,
            reason="LIVE — picks shipped, continue dispatch",
        )

    if verdict is Verdict.DRAIN:
        # A true DRAIN is the only verdict that may count toward an early stop,
        # in every mode. Under hard it routes through /replan first (drained-
        # twice = the *second* DRAIN around a /replan); under soft/drive a true
        # DRAIN stops directly — the backlog is genuinely empty.
        if mode == GATE_HARD:
            return GateAction(
                next_mode="replan",
                counts_toward_drain=True,
                reconcile=False,
                surface=False,
                reason="DRAIN — backlog drained, /replan to refill (drained-twice on 2nd)",
            )
        return GateAction(
            next_mode="stop",
            counts_toward_drain=True,
            reconcile=False,
            surface=True,
            reason="DRAIN — backlog genuinely drained, stopping",
        )

    if verdict is Verdict.RACE:
        # NRT2 (docs/53): a candidates-cache lock race. The packet on disk is
        # wrong-scope; the foreign holder will (or already has) emitted the
        # intended packet. Retry semantics: sleep briefly + retry once
        # (/dispatch-loop SKILL.md policy line) rather than route to /replan or
        # stop — the lock will clear when the sibling /next-up finishes. RACE
        # never counts toward drained-twice and never counts toward the
        # SHIPPED-DIRTY-0 / back-to-back ceilings (the back-to-back streak
        # counts ONLY SHIPPED-DIRTY iterations; a GATE verdict=RACE never
        # increments it structurally — this branch keeps that contract loud).
        return GateAction(
            next_mode="dispatch",
            counts_toward_drain=False,
            reconcile=False,
            surface=True,
            reason="RACE — candidates cache race; rerun on lock-clear (sleep + retry once, no drain count)",
        )

    if verdict is Verdict.STALE_STAMP:
        # The #240 false-drain. Never counts toward drained-twice in any mode.
        if mode == GATE_HARD:
            return GateAction(
                next_mode="replan",
                counts_toward_drain=False,
                reconcile=False,
                surface=False,
                reason="STALE-STAMP — /replan to stamp the drift (does NOT count toward drained-twice)",
            )
        # soft / drive — self-heal: reconcile the stamps inline and re-dispatch
        # WITHOUT counting the iteration. The loop heals stamp drift instead of
        # false-stopping on it.
        return GateAction(
            next_mode="dispatch",
            counts_toward_drain=False,
            reconcile=True,
            surface=False,
            reason="STALE-STAMP — auto-clear via inline stamp-reconcile, re-dispatch (no drain count)",
        )

    # Verdict.BLOCKED — picks exist but a sibling soft-claim / quota blocks them.
    # Never counts toward drained-twice. Under hard it spends a /replan
    # iteration; under soft/drive it stops and surfaces — the loop must not sit
    # unattended waiting on a quota window or block a sibling batch. drive
    # self-heals only the *deterministic* cause (STALE-STAMP), never a BLOCKED.
    if mode == GATE_HARD:
        return GateAction(
            next_mode="replan",
            counts_toward_drain=False,
            reconcile=False,
            surface=False,
            reason="BLOCKED — /replan (does NOT count toward drained-twice)",
        )
    return GateAction(
        next_mode="stop",
        counts_toward_drain=False,
        reconcile=False,
        surface=True,
        reason="BLOCKED — picks blocked by sibling-claim/quota, stopping + surfacing",
    )


# ---------------------------------------------------------------------------
# FQ-240 — /replan productivity verdict (the second half of the drained-twice fix).
#
# QWB6/QWB7 fixed the *input-gate* half of finding #240: a 0-pick /dispatch now
# carries a typed verdict, and the drained-twice counter increments on DRAIN
# only — so a STALE-STAMP gate can no longer arm a false stop. But finding #240
# named a SECOND, distinct shape that QWB7 did not close: the drained-twice rule
# treats *any* completed /replan as a valid refill attempt. A /replan can
# complete having done **0 gardening and 0 refill** — most cleanly via /replan's
# §1.5 no-op skip gate ("no new evidence since <ts>"), which prints one line and
# writes nothing. When the next /dispatch DRAINs, the loop calls it
# DRAINED_TWICE and stops — declaring the portfolio drained even though /replan
# never actually *tried* to refill. The honest stop is: drained-twice fires only
# when a **productive** /replan (one that refilled / gardened) was still followed
# by a DRAIN.
#
# `classify_replan_productivity()` is the typed verdict that distinguishes the
# two. It is PURE (no I/O) for the same reason `classify_packet` / `gate_policy`
# are: the loop's stop condition can be replay-tested without a live /replan run.
#
# ⚓ Typed verdict over binary gate ([[feedback_typed_verdict_over_binary_gate]]):
# the drained-twice trigger must read a typed /replan-productivity verdict, not
# "a /replan ran". A /replan that ran-but-did-nothing is not a refill attempt.
#
# ⚓ Data-driven decisions (evidence-over-narrative): the verdict is derived from
# the /replan iteration's own terminal `result` text — the structural no-op skip
# marker /replan emits, and its gardening-count summary — never from a prose
# guess about whether the sweep "felt productive".
# ---------------------------------------------------------------------------


class ReplanProductivity(str, enum.Enum):
    """Whether a completed /replan iteration actually refilled / gardened.

    `str`-valued so it round-trips through Step 3's grep stdout token without a
    lookup table (mirrors `Verdict` / `OutcomeKind`).

      PRODUCTIVE    /replan ran its full sweep and did real work — promoted a
                    candidate, reconciled an anchor, swept a stale claim,
                    backfilled a SHIPPED stamp, reranked the queue, etc. This is
                    a genuine refill attempt: a DRAIN that *still* follows it is
                    an honest drained-twice signal.
      UNPRODUCTIVE  /replan completed without refilling the backlog: it hit the
                    §1.5 no-op skip gate ("no new evidence"), or it ran the sweep
                    but every gardening counter came back 0 (0 promoted, 0
                    reconciled, 0 swept, 0 backfilled, …). A DRAIN after such a
                    /replan is NOT drained-twice — /replan never actually tried.
    """

    PRODUCTIVE = "PRODUCTIVE"
    UNPRODUCTIVE = "UNPRODUCTIVE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# The structural marker /replan's §1.5 no-op skip gate prints (replan/SKILL.md
# §1.5). When this appears in the iteration's terminal result text, the sweep
# did not run at all — 0 gardening, 0 refill, no replan-state.yaml write, no
# archive commit. The single most-decisive unproductive signal.
REPLAN_NOOP_SKIP_MARKER = "/replan skipped: no new evidence"

# The gardening-count tokens /replan's §7 summary emits ("**Gardening:** <M>
# anchors reconciled · <P> percent-refreshes · …") plus the §7 header's
# "<N>/<X> promoted to inbox · <C> auto-closed · <A> added". When EVERY count a
# /replan reports is 0, the sweep ran but did no work — the second unproductive
# shape (sweep-ran-found-nothing, distinct from the no-op skip). Each entry is
# (regex, "this many were acted on" group): a non-zero in ANY one of them is
# enough to call the sweep productive.
_REPLAN_WORK_PATTERNS = (
    # §7 header — candidates promoted to inbox. The header form is "<N>/<X>
    # promoted" (N acted-on of X candidates); capture the NUMERATOR (the count
    # actually promoted), not the denominator, so "0/4 promoted" reads as 0.
    r"(\d+)\s*(?:/\s*\d+)?\s+promoted",
    r"(\d+)\s+auto-closed",         # §7 header — queue rows auto-closed
    r"(\d+)\s+added",               # §7 header — new queue rows added
    r"(\d+)\s+anchors?\s+reconciled",
    r"(\d+)\s+percent-refreshes",
    r"(\d+)\s+stale\s+claims?\s+swept",
    r"(\d+)\s+gitignore\s+patterns?\s+added",
    r"(\d+)\s+tomb-stamps?\s+applied",
    r"(\d+)\s+stale\s+fanouts?\s+flagged",
    r"(\d+)\s+queue\s+rows?\s+reranked",
    r"(\d+)\s+next-hits\s+reranked",
    r"(\d+)\s+escalated",
)


def classify_replan_productivity(replan_result_text: str) -> ReplanProductivity:
    """Classify one completed /replan iteration's productivity. PURE — no I/O.

    `replan_result_text` is the /replan iteration's terminal `result` text — the
    same envelope text Step 3 already extracted into `result.json`. The caller
    passes the already-loaded text; this function does no file or git I/O so it
    is replay-testable away from a live $2-4 /replan run.

    Decision order (most-decisive first):

      1. The §1.5 no-op skip marker present → UNPRODUCTIVE. The sweep never ran;
         it found no new evidence and exited cheap without writing state.
      2. The sweep ran — read its gardening counts. If ANY work counter is
         non-zero → PRODUCTIVE (a genuine refill attempt). If EVERY recognised
         counter is 0 (a 0/0/0 ceremony sweep) → UNPRODUCTIVE.
      3. No recognised counts at all (a pre-FQ-240 /replan build, a truncated
         envelope, an unexpected format) → PRODUCTIVE — the conservative
         default. Treating an unparseable /replan as productive preserves
         today's behavior (the drained-twice rule still fires on the next
         DRAIN), so this change can NEVER make the loop run *longer* than it does
         today on a /replan it cannot read; it only spares the false-stop on a
         /replan it can positively confirm did nothing.
    """
    text = replan_result_text or ""

    # 1. The no-op skip gate — the cleanest unproductive signal.
    if REPLAN_NOOP_SKIP_MARKER in text:
        return ReplanProductivity.UNPRODUCTIVE

    # 2. The sweep ran — did any gardening counter report work?
    saw_a_count = False
    for pattern in _REPLAN_WORK_PATTERNS:
        m = re.search(pattern, text)
        if m:
            saw_a_count = True
            if int(m.group(1)) > 0:
                return ReplanProductivity.PRODUCTIVE

    if saw_a_count:
        # Every recognised counter was 0 — a 0/0/0 sweep that ran but did
        # nothing. /replan completed without refilling the backlog.
        return ReplanProductivity.UNPRODUCTIVE

    # 3. No recognised summary at all — conservative PRODUCTIVE (preserves the
    #    pre-FQ-240 drained-twice behavior; never extends the loop).
    return ReplanProductivity.PRODUCTIVE


# ---------------------------------------------------------------------------
# /replan §1.5 no-op-skip decision — the PRODUCER-side twin of the consumer-side
# `classify_replan_productivity` above.
#
# `classify_replan_productivity` reads a *completed* /replan's terminal text
# (the consumer: the dispatch-loop driver deciding drained-twice). This function
# is the *producer* decision /replan's own §1.5 gate makes BEFORE it sweeps:
# given the two evidence counters its context bundler computes, should the sweep
# run at all, or skip cheap?
#
#   replan_skip_decision(new_findings, substantive_ships) -> SKIP | PROCEED
#
# Before this lift the same boolean lived in THREE hand-synced copies that only
# agreed by accident: (a) the LLM following /replan SKILL.md §1.5 prose, (b) the
# kernel re-deriving "the sweep did nothing" downstream by string-matching
# REPLAN_NOOP_SKIP_MARKER, (c) `replan_context.py`'s BOOKKEEPING_PREFIXES list
# (comment: "keep in sync if /replan SKILL.md adds new classes"). Lifting the
# predicate here lets the producer print the SKIP marker FROM the kernel-owned
# constant and the consumer key on that SAME constant — they agree by
# construction, not by coincidence.
#
# ⚓ Typed verdict over binary gate ([[feedback_typed_verdict_over_binary_gate]]):
# the §1.5 gate is a fork on "is there new evidence"; emit a typed SKIP/PROCEED,
# not a bare bool, so the marker the producer prints and the verdict the consumer
# reads are the one shared vocabulary.
#
# PURE — no I/O. The two counters are reduced at /replan's I/O edge
# (`replan_context.py`, which already greps git + the findings window); this
# decision is replay-testable on frozen (new_findings, substantive_ships) inputs,
# exactly like `classify_replan_productivity` / `classify_packet`.
# ---------------------------------------------------------------------------


class ReplanSkip(str, enum.Enum):
    """Whether /replan's §1.5 gate should run the sweep or skip it cheap.

    `str`-valued so it round-trips through the context bundler's JSON without a
    lookup table (mirrors `ReplanProductivity` / `Verdict`).

      SKIP     No new evidence since the last run (0 new findings AND 0
               substantive ships) — the sweep cannot produce a non-trivial
               result, so /replan prints REPLAN_NOOP_SKIP_MARKER and exits
               without running steps 2-7, writing replan-state.yaml, or making
               an archive commit. The consumer-side `classify_replan_productivity`
               reads that marker and calls the iteration UNPRODUCTIVE.
      PROCEED  At least one new finding OR one substantive ship since the last
               run — there is real evidence to garden; run the full sweep.
    """

    SKIP = "SKIP"
    PROCEED = "PROCEED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def replan_skip_decision(new_findings: int, substantive_ships: int) -> ReplanSkip:
    """Classify /replan's §1.5 no-op-skip gate. PURE — no I/O.

    `new_findings` is the count of findings entries that post-date the last
    /replan run; `substantive_ships` is the count of non-bookkeeping commits in
    `<last_run_commit>..HEAD`. Both are computed by `replan_context.py` at the
    I/O edge and passed in here — this function makes no file, git, or clock
    call, so the §1.5 decision is replay-testable away from a live $2-4 sweep.

    The rule is the §1.5 gate verbatim: a sweep with no new evidence cannot
    produce a non-trivial result. Skip iff BOTH counters are zero; any positive
    signal in either → PROCEED (run the full sweep). Negative inputs are treated
    as zero (defensive — a malformed count must never *suppress* a real sweep).
    """
    nf = max(0, int(new_findings))
    ss = max(0, int(substantive_ships))
    if nf == 0 and ss == 0:
        return ReplanSkip.SKIP
    return ReplanSkip.PROCEED
