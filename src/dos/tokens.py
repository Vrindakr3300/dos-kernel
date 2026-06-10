"""Central vocabulary for every dispatch verdict / outcome / blocked-reason token.

THE GLOSSARY (this docstring IS the central index the operator asked for).
========================================================================

The dispatch family classifies each `/dispatch` iteration into a typed token.
Those tokens are written verbatim into git commit subjects
(`docs/dispatch: archive … verdict=BLOCKED`) and grepped back out by the loop to
decide continue / replan / stop. Before this module they were string literals
copy-pasted across ~290 sites in two unrelated enums with no shared home. This
module is the one place they are defined.

Gate-side verdicts (`GateVerdict`) — the INPUT gate: *did the picker produce
live, dispatchable picks?* Emitted by `/next-up` / `/dispatch` Step 9.

    LIVE         the packet has ≥1 dispatchable pick — /fanout ran (or will).
    DRAIN        a genuine empty backlog — there is nothing left to dispatch.
    STALE-STAMP  work shipped in git but the plan-doc rows are unstamped, so the
                 picker SEES a drain that is not real (a false drain).
    BLOCKED      picks exist but something is blocking them — a sibling claim, a
                 quota wall, a ship-oracle false-positive, an open operator
                 decision. There IS work; the loop cannot unblock it on its own.
                 (Renamed from the old, confusing "WEDGE" — see legacy aliases.)
    RACE         this render lost a candidates-cache lock race to a sibling
                 /next-up shell; sleep briefly + retry once (the lock will clear).

Outcome-side verdicts (`OutcomeVerdict`) — the MEASURED outcome: *after /fanout
ran, what actually landed?* Emitted by `scripts/packet_verdict.py classify`,
which measures the post-fanout commit set against the start-SHA (it does NOT
trust the input token).

    SHIPPED-CLEAN    every live pick produced its expected commit set. Healthy.
    SHIPPED-DIRTY    partial — some picks shipped, some did not (retry-able).
    STALLED          picks neither shipped nor cleanly failed (killed / no
                     result envelope) — needs operator triage.
    BLOCKED-OUTCOME  /fanout RAN but shipped nothing for a structural reason
                     (correlated outage / self-collision / decision-needed) — a
                     retry would re-block the same lane. (Renamed from the old
                     "WEDGED"; distinct name from the input-side BLOCKED so the
                     input-gate-vs-measured-outcome distinction stays legible.)

Why two enums, not one: the input gate ("could the picker find work?") and the
measured outcome ("did the work that ran actually land?") answer different
questions about different moments. Collapsing them lost information; they stay
distinct. Only the confusing *word* "wedge" is gone from both.

Blocked reasons (`BlockedReason` + `BLOCKED_REASONS`) — WHY a BLOCKED /
BLOCKED-OUTCOME happened. The operator-facing catalog; each reason carries a
plain-English label, whether it needs an operator decision (vs. a structural
defect the automation could fix), and a one-line fix sketch. The reason KEYS are
the same canonical keys `scripts/unstick_audit.py:CAUSES` clusters on — this
module owns the catalog, `unstick_audit` owns the cue-matching that maps an
Outcome-cell string to one of these keys. A test asserts the two stay in sync.

Legacy aliases (PERMANENT)
==========================
Historical commits already on disk say `verdict=WEDGE` / `verdict=WEDGED`, and a
peer machine's un-pulled code (or an in-flight headless child) may still
reference `Verdict.WEDGE`. So:

  * `GateVerdict.WEDGE` is a permanent Enum ALIAS of `GateVerdict.BLOCKED` (same
    object — `is` works), and `OutcomeVerdict.WEDGED` aliases `BLOCKED_OUTCOME`.
  * `LEGACY_TOKEN_ALIASES` maps the raw strings `"WEDGE" → "BLOCKED"` and
    `"WEDGED" → "BLOCKED-OUTCOME"`. `normalize_token()` applies it, so any
    consumer reading an old `verdict=WEDGE` commit transparently gets `BLOCKED`.
  * `KNOWN_VERDICT_TOKENS` accepts BOTH spellings of each, so the archive-token
    validator never raises on a legacy or a new token.

These aliases are never removed (no deprecation window) — the tiny permanent
cost is that the word "wedge" survives in exactly these alias lines + the
`LEGACY_TOKEN_ALIASES` map, and nowhere else in live code.

Note on `normalize_token` vs the Enum: once `WEDGE` is an alias, `WEDGE`'s
*value* is `"BLOCKED"`, so `GateVerdict("WEDGE")` RAISES (no member has value
`"WEDGE"`). That is intentional — legacy-string parsing happens at the STRING
layer via `normalize_token` BEFORE enum construction, never by feeding a legacy
string to the Enum constructor.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Gate-side verdicts (input gate — did the picker produce live picks?)
# ---------------------------------------------------------------------------
class GateVerdict(str, enum.Enum):
    """One typed gate verdict. `str`-valued so it round-trips as a bare token.

    A `str`-Enum compares equal to its bare string, so
    `GateVerdict.STALE_STAMP == "STALE-STAMP"` holds and the token survives a
    plain-text round-trip through a commit subject without a lookup table.
    """

    LIVE = "LIVE"
    DRAIN = "DRAIN"
    STALE_STAMP = "STALE-STAMP"
    BLOCKED = "BLOCKED"
    # NRT2 (docs/53): the candidates-cache lock timed out — another /next-up
    # shell held the plan→render window for this tag. RACE is its own typed
    # verdict (not BLOCKED) because the retry semantics differ: BLOCKED is "work
    # exists but blocked" (sleep doesn't help — quota window or sibling claim),
    # RACE is "this exact render lost a lock race" (one short sleep + retry-once
    # is the right response, and the iteration must NOT count toward the
    # SHIPPED-DIRTY-0 / back-to-back ceilings — /dispatch-loop policy).
    RACE = "RACE"

    # --- PERMANENT legacy alias (see module docstring) -----------------------
    # The old, confusing spelling. Same value object as BLOCKED, so
    # `GateVerdict.WEDGE is GateVerdict.BLOCKED` and any un-migrated
    # `verdict is Verdict.WEDGE` comparison keeps working forever.
    WEDGE = "BLOCKED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# Outcome-side verdicts (measured outcome — did the work that ran land?)
# ---------------------------------------------------------------------------
class OutcomeVerdict(str, enum.Enum):
    """One typed stage-3 outcome verdict. `str`-valued so it round-trips as a
    token (the same pattern `GateVerdict` uses for the archive-subject token)."""

    SHIPPED_CLEAN = "SHIPPED-CLEAN"
    SHIPPED_DIRTY = "SHIPPED-DIRTY"
    STALLED = "STALLED"
    BLOCKED_OUTCOME = "BLOCKED-OUTCOME"

    # --- PERMANENT legacy alias (see module docstring) -----------------------
    # The old spelling. Same value object as BLOCKED_OUTCOME.
    WEDGED = "BLOCKED-OUTCOME"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# Legacy-token string aliases (the raw-string layer normalize_token applies).
# PERMANENT — never removed. The two places (plus the Enum alias members above)
# the word "wedge" survives in live code.
# ---------------------------------------------------------------------------
LEGACY_TOKEN_ALIASES: dict[str, str] = {
    "WEDGE": "BLOCKED",
    "WEDGED": "BLOCKED-OUTCOME",
}


def normalize_token(raw: str | None) -> str | None:
    """Upper-case a raw verdict/outcome token and apply the legacy aliases.

    The single chokepoint every consumer routes a grepped/parsed token through,
    so a historical `verdict=WEDGE` commit transparently aggregates under
    `BLOCKED` (and `WEDGED` under `BLOCKED-OUTCOME`). Returns ``None`` for a
    falsy input (a README usually carries no token — that is fine). Does NOT
    validate against the known set — that is `normalize_verdict_token`'s job
    (which calls this first, then checks membership).

    This is the layer that handles legacy strings; do NOT feed a legacy string
    to `GateVerdict(...)`/`OutcomeVerdict(...)` directly — once `WEDGE` is an
    alias its value is `"BLOCKED"`, so `GateVerdict("WEDGE")` raises.
    """
    if not raw:
        return None
    t = raw.strip().upper()
    if not t:  # whitespace-only — treat as no token
        return None
    return LEGACY_TOKEN_ALIASES.get(t, t)


# ---------------------------------------------------------------------------
# Known upstream archive verdict-tokens -> a coarse hint about what the token
# CLAIMED (docs/49 Open concern #3). The classifier never trusts this as the
# final word; it only uses it to detect the lie (token says LIVE, commit set is
# empty). Both legacy AND new spellings of the blocked tokens are present so the
# validator never raises on either.
# ---------------------------------------------------------------------------
KNOWN_VERDICT_TOKENS: dict[str, str] = {
    "LIVE": "claims-picks-shipped",
    "DRAIN": "claims-empty-backlog",
    "STALE-STAMP": "claims-false-drain",
    "BLOCKED": "claims-blocked",
    "WEDGE": "claims-blocked",            # legacy spelling of BLOCKED
    "BLOCKED-OUTCOME": "claims-blocked-outcome",
    "WEDGED": "claims-blocked-outcome",   # legacy spelling of BLOCKED-OUTCOME
    "COLLISION": "claims-sibling-or-hard-claim-collision",
    "ERROR": "claims-crash",
    # RATE_LIMITED — /dispatch archives this when child1/child2 envelopes carry
    # a usage/quota/credit signal (scripts/rate_limit_classify). /dispatch-loop
    # OutcomeKind.RATE_LIMITED stops on it and writes .resume.json so the same
    # packet can be resumed without re-/next-up-ing.
    "RATE_LIMITED": "claims-quota-wall",
}


# ---------------------------------------------------------------------------
# The blocked-reason catalog — WHY a BLOCKED / BLOCKED-OUTCOME happened.
#
# The reason KEYS are the canonical cause keys `scripts/unstick_audit.py:CAUSES`
# clusters on (plus the `uncategorized_nonship` fall-through `UNCATEGORIZED`).
# This module owns the OPERATOR-FACING catalog (plain-English label, whether it
# needs an operator decision, a one-line fix sketch); `unstick_audit` owns the
# rich cue-matching that maps an Outcome-cell string to one of these keys. A
# test (`tests/test_dispatch_tokens.py`) asserts the key sets stay in sync, so
# adding a cause in one place without the other fails CI.
# ---------------------------------------------------------------------------
class BlockedReason(str, enum.Enum):
    """A named, stable reason a dispatch iteration was BLOCKED.

    `str`-valued and equal to the canonical `unstick_audit.Cause.key` string, so
    a `cause_key` mined by `/unstick` maps to a `BlockedReason` by value.
    """

    STALE_CLAIM_FALSE_BLOCK = "stale_claim_false_block"
    SHIP_ORACLE_FALSE_POSITIVE = "ship_oracle_false_positive"
    LYING_VERDICT_TOKEN = "lying_verdict_token"
    PREFLIGHT_SCRATCH_RACE = "preflight_scratch_race"
    WAIT_MARKER_RUNAWAY = "wait_marker_runaway"
    CHILD2_FANOUT_DIED_PRE_SHIP = "child2_fanout_died_pre_ship"
    PACKET_INCOHERENCE = "packet_incoherence"
    ENCODING_MOJIBAKE = "encoding_mojibake"
    LANE_SOAK_GATED = "lane_soak_gated"
    LANE_ALL_INFLIGHT_OR_DEFERRED = "lane_all_inflight_or_deferred"
    CHILD_PARKED_PRE_STEP9_NO_ENVELOPE = "child_parked_pre_step9_no_envelope"
    DATA_GATED_CLOSEOUT = "data_gated_closeout"
    OPERATOR_DECISION = "operator_decision"
    GATE_WEDGE_UNSPECIFIED = "gate_wedge_unspecified"
    BODY_EMPTY_PICKS = "body_empty_picks"
    UNCATEGORIZED_NONSHIP = "uncategorized_nonship"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class BlockedReasonInfo:
    """The operator-facing facts about one blocked reason.

    `label` is plain English (the word a confused operator reads).
    `operator_action_required` distinguishes a human-gated halt (the operator
    must answer something) from a structural defect the automation could fix.
    `fix_sketch` is a one-line pointer to the structural fix; the full,
    memory-linked fix prose lives on the matching `unstick_audit.Cause.fix`.
    `self_heals_via` names the loop's own remedy when one exists
    (`/replan` for a stamp/refill drift, `/unstick` for a recurring structural
    defect, or "" for a human-gated reason).
    """

    key: str
    label: str
    operator_action_required: bool
    fix_sketch: str
    self_heals_via: str


# Keyed by BlockedReason value. The label + fix_sketch are deliberately TERSE
# (operator-report grade) — the exhaustive structural fix prose stays on the
# matching unstick_audit.Cause to avoid two copies drifting.
BLOCKED_REASONS: dict[str, BlockedReasonInfo] = {
    BlockedReason.STALE_CLAIM_FALSE_BLOCK.value: BlockedReasonInfo(
        key="stale_claim_false_block",
        label="A stale or sibling claim is false-blocking a live pick",
        operator_action_required=False,
        fix_sketch="Auto-expire a working/hard claim whose deliverables are durable "
        "at HEAD (or whose heartbeat exceeds TTL) inside /fanout register-prescreen.",
        self_heals_via="/unstick",
    ),
    BlockedReason.SHIP_ORACLE_FALSE_POSITIVE.value: BlockedReasonInfo(
        key="ship_oracle_false_positive",
        label="The ship-oracle wrongly thinks the work already shipped",
        operator_action_required=False,
        fix_sketch="Add an on-disk deliverable-existence check so a (plan,phase) is "
        "'shipped' only when its named artefact exists — not on a touch-count heuristic.",
        self_heals_via="/unstick",
    ),
    BlockedReason.LYING_VERDICT_TOKEN.value: BlockedReasonInfo(
        key="lying_verdict_token",
        label="The archive verdict token disagrees with the actual commit set",
        operator_action_required=False,
        fix_sketch="Branch the loop on packet_verdict.py classify (commit-set vs "
        "start-SHA) instead of trusting the prose verdict= token.",
        self_heals_via="/unstick",
    ),
    BlockedReason.PREFLIGHT_SCRATCH_RACE.value: BlockedReasonInfo(
        key="preflight_scratch_race",
        label="A shared preflight scratch race resolved the wrong packet",
        operator_action_required=False,
        fix_sketch="Give each fanout run a per-run preflight scratch path (or assert "
        "the resolved packet basename matches the fed path).",
        self_heals_via="/unstick",
    ),
    BlockedReason.WAIT_MARKER_RUNAWAY.value: BlockedReasonInfo(
        key="wait_marker_runaway",
        label="A child burned its turn budget deliberating a no-pick / gated lane",
        operator_action_required=False,
        fix_sketch="Tighten the Scout/early-exit guard so a no-pick gated lane "
        "returns a typed DRAIN/BLOCKED in <N turns instead of deliberating.",
        self_heals_via="/unstick",
    ),
    BlockedReason.CHILD2_FANOUT_DIED_PRE_SHIP.value: BlockedReasonInfo(
        key="child2_fanout_died_pre_ship",
        label="A long background child (e.g. /fanout) was reaped when its parent exited pre-ship",
        operator_action_required=False,
        fix_sketch="Launch the long background child DETACHED (own process group / "
        "new session) so a parent turn-budget exit cannot reap it; the parent then "
        "adopts the survivor via its orphan-sweep. The foreground-hold fix only "
        "works for a child shorter than the foreground wait ceiling.",
        self_heals_via="/unstick",
    ),
    BlockedReason.PACKET_INCOHERENCE.value: BlockedReasonInfo(
        key="packet_incoherence",
        label="The dispatch packet was internally incoherent / corrupted under concurrency",
        operator_action_required=False,
        fix_sketch="Snapshot the scope's plan-ids immediately before render and "
        "re-render under a fresh tag; HALT + log packet-corruption rather than launch.",
        self_heals_via="/unstick",
    ),
    BlockedReason.ENCODING_MOJIBAKE.value: BlockedReasonInfo(
        key="encoding_mojibake",
        label="UTF-16 / encoding mangled a headless log so the verdict was unparseable",
        operator_action_required=False,
        fix_sketch="Decode headless stream-json logs as utf-16 (or transcode to a "
        ".utf8.log sibling) before envelope-extract / verdict-grep.",
        self_heals_via="/unstick",
    ),
    BlockedReason.LANE_SOAK_GATED.value: BlockedReasonInfo(
        key="lane_soak_gated",
        label="The lane's only work is soak-gated, so it has nothing dispatchable yet",
        operator_action_required=False,
        fix_sketch="Register the soak follow-up as soak_window_dispatchable with its "
        "unblock date so /next-up picks it DURING the window instead of BLOCK-storming.",
        self_heals_via="/replan",
    ),
    BlockedReason.LANE_ALL_INFLIGHT_OR_DEFERRED.value: BlockedReasonInfo(
        key="lane_all_inflight_or_deferred",
        label="The lane is DRAINED — every pick is already in-flight or deferred, "
        "nothing dispatchable right now (a refill condition, not a wedge)",
        operator_action_required=False,
        fix_sketch="This is a drained lane, not a break — /replan refills it. The only "
        "defect is when the drain reason_class (LANE_ALL_INFLIGHT_OR_DEFERRED) is "
        "flattened to bare 'child2 skipped' prose with no structured cause, so /unstick "
        "mis-clusters it as a generic wedge; carry the reason_class into the archive "
        "Outcome cell so the next sweep routes /replan, never /unstick.",
        self_heals_via="/replan",
    ),
    BlockedReason.CHILD_PARKED_PRE_STEP9_NO_ENVELOPE.value: BlockedReasonInfo(
        key="child_parked_pre_step9_no_envelope",
        label="Parked-child DRAIN — child2 skipped pre-Step-9, parent recommended "
        "/replan (refill, not a wedge)",
        operator_action_required=False,
        # Sibling of LANE_ALL_INFLIGHT_OR_DEFERRED (same whole-lane-drain family,
        # /replan route). Distinct only in HOW the drain token is recovered: the
        # child2 /fanout was skipped before writing its Step-9 Outcome because the
        # parent /dispatch -p exited at its wait-budget, so the structured cause is
        # reconstructed from the parent's archive subject (driver Step 3.2.7) rather
        # than carried from the child README. It is a MEASUREMENT ARTIFACT (the
        # parent stopped waiting), NOT a break — /replan refills, /unstick is wrong.
        fix_sketch="Parked-child DRAIN, not a wedge — /replan refills; never /unstick. "
        "Deeper lever if it recurs at volume: child2 detachment / a longer parent "
        "wait-budget so the child reaches Step 9. The routing itself is already correct.",
        self_heals_via="/replan",
    ),
    BlockedReason.DATA_GATED_CLOSEOUT.value: BlockedReasonInfo(
        key="data_gated_closeout",
        label="A phase close-out is data-gated on a live run that isn't dispatchable",
        operator_action_required=False,
        fix_sketch="Register the close-out as a soak follow-up with a dated unblock "
        "condition so the loop skips it cleanly instead of BLOCK-storming.",
        self_heals_via="/replan",
    ),
    BlockedReason.OPERATOR_DECISION.value: BlockedReasonInfo(
        key="operator_decision",
        label="The lane is blocked on an open operator decision (no mechanism resolves it)",
        operator_action_required=True,
        fix_sketch="Type the decision into a decision-needed findings row with an "
        "explicit option set so /replan promotes it to a pick the operator answers ONCE.",
        self_heals_via="",  # human-gated — JO escalator (Step 3.45) surfaces it once
    ),
    BlockedReason.GATE_WEDGE_UNSPECIFIED.value: BlockedReasonInfo(
        key="gate_wedge_unspecified",
        label="Blocked, but the Outcome cell named no structural cause (unroutable)",
        operator_action_required=False,
        fix_sketch="Tighten the /dispatch-loop Step-3 archive prose to always name "
        "the blocked cause (which gate fired, which claim/oracle/decision blocked).",
        self_heals_via="/unstick",
    ),
    BlockedReason.BODY_EMPTY_PICKS.value: BlockedReasonInfo(
        key="body_empty_picks",
        label="The packet rendered LIVE but its picks are body-empty "
        "(dropped .prompts.json sidecar) so every /fanout refuses",
        operator_action_required=False,
        # FQ-420: /next-up dropped the `.prompts.json` prompt sidecar before
        # returning LIVE, so preflight saw `prompt_text_len==0 AND files==[]`
        # for every go-pick (`preflight._body_empty_picks`) and /fanout refused
        # — a renderer defect that BLOCKS the whole dispatch path until fixed,
        # not a one-off the loop can /replan around. This is the typed cause the
        # `/unstick` cue for the body-empty / sidecar-drop shape maps to (the
        # cue lives in unstick_audit.py:CAUSES; this is its catalog home), so a
        # recurring sidecar-drop clusters under a real structural cause instead
        # of vanishing into `uncategorized_nonship`. Self-heals via `/unstick`
        # (the recurring-structural-defect channel), never `/replan` — a refill
        # sweep cannot restore a sidecar the renderer never wrote.
        fix_sketch="Make /next-up emit the `.prompts.json` sidecar (or its "
        "in-packet prompt bodies) BEFORE it returns LIVE, and have the renderer "
        "refuse to stamp LIVE on a packet whose picks have empty bodies.",
        self_heals_via="/unstick",
    ),
    BlockedReason.UNCATEGORIZED_NONSHIP.value: BlockedReasonInfo(
        key="uncategorized_nonship",
        label="A novel blocker shape the cue table does not recognise yet",
        operator_action_required=False,
        fix_sketch="Read the example Outcome cell; if recurring, add a cue to "
        "unstick_audit.py:CAUSES so future sweeps cluster it. A one-off routes "
        "to /replan; a RECURRING uncategorized nonship escalates to /unstick "
        "(see recurring_self_heal_for) — a refill sweep cannot fix a defect that "
        "keeps recurring.",
        self_heals_via="/replan",
    ),
}


def blocked_reason_for_key(cause_key: str | None) -> BlockedReasonInfo | None:
    """Map a canonical `unstick_audit` cause-key to its operator-facing catalog
    entry, or ``None`` for an unknown / empty key. The lookup the dispatch-loop
    report uses to name a BLOCKED reason from the recurring-wedge `cause_key`.
    """
    if not cause_key:
        return None
    return BLOCKED_REASONS.get(cause_key.strip())


# The recurrence threshold at which a generic, otherwise-/replan-routed cause is
# no longer treated as a one-off and escalates to /unstick. Mirrors
# `unstick_audit.py`'s `--min-recurrence` default (a cluster is "recurring" at
# this many affected runs). Kept here so the *routing* rule lives with the
# catalog it routes over — the job audit calls `recurring_self_heal_for` rather
# than re-encoding the threshold beside its clusterer.
RECURRENCE_ESCALATION_RUNS = 2

# The generic, prose-defect causes whose remedy DEPENDS on recurrence: a single
# occurrence is plausibly transient (route to /replan for a human read / refill),
# but a cause that keeps recurring is a structural defect /replan cannot fix —
# it must escalate to /unstick. A specific cause (a stale-claim false-block, a
# ship-oracle false-positive, a body-empty sidecar drop) already names its own
# channel and is NOT recurrence-dependent; only the catch-alls are.
_RECURRENCE_ESCALATING_KEYS = frozenset({
    BlockedReason.UNCATEGORIZED_NONSHIP.value,
    BlockedReason.GATE_WEDGE_UNSPECIFIED.value,
})


def recurring_self_heal_for(cause_key: str | None, runs_affected: int) -> str:
    """The self-heal channel for a cause, given how many runs it has affected.

    The catalog's static `self_heals_via` is the *one-off* remedy. This is the
    recurrence-aware resolver the `/unstick` sweep consults: a generic
    catch-all cause (`uncategorized_nonship`, `gate_wedge_unspecified`) that has
    recurred across `>= RECURRENCE_ESCALATION_RUNS` runs escalates from its
    default `/replan` to `/unstick` — a refill sweep cannot fix a defect that
    keeps recurring, so the recurring case routes to the structural-defect
    channel. This closes the FQ-420 recurring-wedge cue gap: a 5th-consecutive
    `uncategorized_nonship` no longer self-heals via `/replan` forever; once it
    crosses the recurrence floor it routes to `/unstick`.

    A cause that names a specific structural channel (not a catch-all) returns
    its catalog `self_heals_via` unchanged — recurrence does not override an
    already-specific routing (a `body_empty_picks` is `/unstick` at one run, a
    `lane_soak_gated` is `/replan` however often it recurs). An unknown key
    returns `""` (no known remedy), matching `blocked_reason_for_key` returning
    None.

    PURE — the caller supplies `runs_affected` from its own cluster count
    (`unstick_audit.BlockerCluster.runs_affected`); this function holds only the
    routing rule, never the clustering.
    """
    info = blocked_reason_for_key(cause_key)
    if info is None:
        return ""
    if (
        info.key in _RECURRENCE_ESCALATING_KEYS
        and runs_affected >= RECURRENCE_ESCALATION_RUNS
    ):
        return "/unstick"
    return info.self_heals_via
