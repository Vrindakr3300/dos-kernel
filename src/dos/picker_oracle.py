"""Picker oracle — provable ground truth for /next-up picker quality.

Background
==========

`/next-up` and `/dispatch` emit `verdict=LIVE | WEDGE | DRAIN` per run.
That single token conflates several outcomes:

  * **LIVE**           — picker found work, child2 shipped it
  * **NO-PICK true**   — picker found no work AND none existed (correct DRAIN)
  * **NO-PICK fake**   — picker found no work BUT work existed (picker bug)
                          sub-causes: stale-claim ghost, regex false-pos,
                          misroute, renderer regression, unverified soak

The dangerous case is NO-PICK fake. Today it's invisible: every WEDGE looks
the same to the loop's stop signal, but the cost is real (~$2-5 per WEDGE
iter × 5-10 iters/day × ~$0 ships).

This module reconstructs ground truth for each historical dispatch:

  1. Read the picker's self-reported verdict envelope
     (`output/next-up/.verdict-<tag>.json`)
  2. Read the lane state at run time (`execution-state.yaml` snapshot via
     git, or current state for recent runs)
  3. Cross-check the picker's stated cause against on-disk facts:
       * STALE_CLAIM claimed → is the colliding claim actually stale?
       * OPERATOR_GATE claimed → is the soak deadline really open?
       * MISROUTE claimed → does the pick really belong elsewhere?
       * TRUE_DRAIN claimed → are all in-scope plans really `remaining:[]`?
  4. Emit a typed `PickerVerdict` with `oracle_disagrees: bool` flag.

The flag is what `/replan` consumes to route picker-bug findings.

Falsifiable metrics
-------------------

For any time window:

  precision = picks_shipped / picks_emitted
  recall    = (oracle_live_picks - missed_picks) / oracle_live_picks
  cost_per_ship = sum(dispatch_cost) / picks_shipped

`recall` is the hidden metric — today there's no number. Once the oracle
exists, it's a CI invariant.

CLI
===

    python scripts/picker_oracle.py classify <run_ts>
    python scripts/picker_oracle.py sweep --since 7d
    python scripts/picker_oracle.py report --window 24h
    python scripts/picker_oracle.py check --min-recall 0.7

`classify` is the per-run primitive; `sweep` is the idempotent bulk driver
(skips runs already classified); `report` emits the human-readable audit
markdown; `check` is the CI gate.

Repeatability
=============

Outputs live at `docs/_picker_audits/<window>/oracle.jsonl` (append-only,
keyed by `(run_ts, child_idx)` — re-run is a no-op). The audit report at
`docs/_picker_audits/<window>/picker_recall_audit.md`.

Wired callers (post-ship):
  * `/dispatch-loop` archive step — calls `classify` per iter
  * `/replan` sweep — calls `sweep --since 24h`; routes oracle_disagrees=true
    rows to `findings-followup-queue.md` as picker-bug findings
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import enum
import json
import re
import sys
from pathlib import Path

import os

# The closed `reason_class` vocabulary lives in `dos.wedge_reason` — the single
# source of truth the producer emits against. Importing it here keeps the
# oracle's recognition set in lockstep so a new WEDGE token is verifiable the
# moment it is emittable. (DOS makes this a clean package import; the origin
# repo needed a `sys.path.insert` because scripts ran as bare files.)
from dos import wedge_reason
from dos import config as _config

# Path coupling resolves against the ACTIVE WORKSPACE (separation refactor).
# The pure `classify(...)` takes `state` explicitly; only the I/O loaders +
# the sweep/report commands read these.


def _state_path() -> Path:
    env = os.environ.get("JOB_FANOUT_STATE_PATH") or os.environ.get("DISPATCH_STATE_PATH")
    return Path(env) if env else _config.active().paths.execution_state


def _chained_runs() -> Path:
    return _config.active().paths.chained_runs


def _next_up_dir() -> Path:
    return _config.active().paths.next_packets


def _audits_dir() -> Path:
    return _config.active().paths.picker_audits


SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Verdict taxonomy
# ---------------------------------------------------------------------------


class PickerOutcome(str, enum.Enum):
    LIVE = "LIVE"                # picker emitted >=1 pick AND >=1 shipped
    LIVE_DIRTY = "LIVE_DIRTY"    # picker emitted picks, none shipped (downstream issue)
    NO_PICK = "NO_PICK"          # picker emitted no usable packet
    UNKNOWN = "UNKNOWN"          # envelope missing/malformed


class NoPickCause(str, enum.Enum):
    TRUE_DRAIN = "TRUE_DRAIN"            # all in-scope plans `remaining:[]`, no findings
    OPERATOR_GATE = "OPERATOR_GATE"      # soak open / operator-attended / env-flag-gated
    STALE_CLAIM = "STALE_CLAIM"          # collision with claim > stale_threshold_h old
    MISROUTE = "MISROUTE"                # finding routed to wrong lane
    REGEX_FP = "REGEX_FP"                # scope-filter regex false-positive
    RENDERER_BUG = "RENDERER_BUG"        # packet rendered but soft-claim skipped
    UNCLASSIFIED = "UNCLASSIFIED"        # legacy envelope, no reason_class

    # convenience for "the LLM's claim is contradicted by on-disk state"
    @property
    def is_picker_bug(self) -> bool:
        return self in {
            NoPickCause.STALE_CLAIM,
            NoPickCause.MISROUTE,
            NoPickCause.REGEX_FP,
            NoPickCause.RENDERER_BUG,
        }


# Mapping from the picker's `reason_class` token to our canonical NoPickCause.
#
# The LANE_* tokens come from the CLOSED `wedge_reason.WedgeReason` set — the
# single source of truth the producer (`next_up_render`) now emits against. Before
# 2026-05-31 these were LLM-prose-only and NONE of them were in this map, so every
# WEDGE classified `UNCLASSIFIED` ("cannot verify") — the oracle's blind spot that
# made `recall_proxy=1.0`/`oracle_disagrees=0` meaningless (it could not classify
# the rows that mattered, [[feedback_wedge_verdict_is_llm_prose_not_code]]). We
# derive the LANE_* half of the map FROM `wedge_reason.REASON_TO_CATEGORY` so the
# two can never drift again — a new WedgeReason member is recognised here the moment
# it is added there. The legacy free-form aliases below stay for older envelopes.
# Unknown tokens still fall through to UNCLASSIFIED so the oracle is forward-compat.
_LEGACY_REASON_ALIASES: dict[str, NoPickCause] = {
    "MIS_ROUTED_FINDING": NoPickCause.MISROUTE,
    "MISROUTED": NoPickCause.MISROUTE,
    "STALE_CLAIM_COLLISION": NoPickCause.STALE_CLAIM,
    "FOREIGN_COLLISION": NoPickCause.STALE_CLAIM,
    "OPERATOR_GATED": NoPickCause.OPERATOR_GATE,
    "SOAK_OPEN": NoPickCause.OPERATOR_GATE,
    "DRAIN": NoPickCause.TRUE_DRAIN,
    "REGEX_FP": NoPickCause.REGEX_FP,
    "RENDERER_SKIP": NoPickCause.RENDERER_BUG,
}


def _build_reason_class_map() -> dict[str, NoPickCause]:
    """Merge the closed WedgeReason set (categorised) with the legacy aliases.

    Each `WedgeReason` carries a `NoPickCategory` whose value string equals a
    `NoPickCause` member name (pinned by `tests/test_wedge_reason.py`), so we
    resolve the cause via `NoPickCause[category.value]`. The legacy aliases are
    layered on top (they don't collide with the LANE_* tokens).
    """
    out: dict[str, NoPickCause] = {}
    for reason, category in wedge_reason.REASON_TO_CATEGORY.items():
        out[reason.value] = NoPickCause[category.value]
    out.update(_LEGACY_REASON_ALIASES)
    return out


REASON_CLASS_MAP: dict[str, NoPickCause] = _build_reason_class_map()


# The recognizer-ladder rungs `resolve_cause_with_source` reports — the
# reason-class analogue of `verify`'s `source` (registry/grep/none). A cause that
# came from a fuzzy MORPHOLOGICAL match must NOT masquerade as one from an EXACT
# declared token: the cross-check downstream is weaker evidence, and the decisions
# queue / `oracle_disagrees` routing must be able to see the rung (`docs/105` §3.1).
CAUSE_SOURCE_EXACT = "exact"               # frozen map or workspace ReasonRegistry
CAUSE_SOURCE_MORPHOLOGICAL = "morphological"  # rung-2 substring recognizer
CAUSE_SOURCE_NONE = "none"                  # UNCLASSIFIED floor — nothing recognized


def resolve_cause_with_source(
    reason_class: str | None,
) -> tuple[NoPickCause, str, str]:
    """Map a `reason_class` token onto `(cause, cause_source, matched)` — the
    full three-rung recognizer ladder (`docs/105`).

    Rungs, in descending authority (the first that answers wins, and NAMES itself):

      1. **exact** — the frozen `REASON_CLASS_MAP` (built-in `WedgeReason` set +
         legacy aliases), then the active workspace's `ReasonRegistry`
         (`dos.toml [reasons]`). A declared or built-in token resolves here;
         `cause_source="exact"`, `matched` is the token.
      2. **morphological** — the active workspace's `reason_morphology`
         (`MorphologyRuleset`, default `GENERIC_REASON_MORPHOLOGY`): an ordered
         `(substring → category)` recognizer that classifies the legible tail of
         LLM-authored compound tokens the exact rungs miss
         (`*FALSE_SHIP*`/`*OPERATOR*`/…). `cause_source="morphological"`, `matched`
         is the substring that fired (so the precedence is auditable).
      3. **none** — known to neither rung → `UNCLASSIFIED`, `cause_source="none"`,
         `matched=""`. The honest floor (`docs/76` §2's `source="none"` analogue):
         a genuinely-ambiguous token is abstained on, never guessed.

    Pure aside from reading the process-active config (the same dependency the
    other workspace-aware loaders here carry); every lookup is lazy and defensive
    so a missing/uninitialised config degrades to the frozen map + generic
    morphology alone, never raising.
    """
    if not reason_class:
        return NoPickCause.UNCLASSIFIED, CAUSE_SOURCE_NONE, ""
    key = reason_class.upper().strip()
    # Rung 1a — frozen map (built-ins + aliases).
    hit = REASON_CLASS_MAP.get(key)
    if hit is not None:
        return hit, CAUSE_SOURCE_EXACT, key
    # Rung 1b — workspace ReasonRegistry (a host-declared exact token).
    try:
        reg = _config.active().reasons
        cat = reg.category_for(key)  # 'UNCLASSIFIED' for an unknown token
        if cat != "UNCLASSIFIED":
            return NoPickCause(cat), CAUSE_SOURCE_EXACT, key
    except Exception:
        pass
    # Rung 2 — morphological recognizer (the legible-tail rung).
    try:
        ruleset = _config.active().reason_morphology
        morph = ruleset.classify(key)
        if morph is not None:
            cat, matched = morph
            return NoPickCause(cat), CAUSE_SOURCE_MORPHOLOGICAL, matched
    except Exception:
        pass
    # Rung 3 — the honest floor.
    return NoPickCause.UNCLASSIFIED, CAUSE_SOURCE_NONE, ""


def resolve_cause(reason_class: str | None) -> NoPickCause:
    """Map a `reason_class` token onto its `NoPickCause` (cause only).

    Thin back-compat wrapper over `resolve_cause_with_source` — returns just the
    cause, for callers that don't need the rung. The full three-rung ladder
    (exact → morphological → none) runs underneath; see
    `resolve_cause_with_source` for the rung semantics.
    """
    cause, _source, _matched = resolve_cause_with_source(reason_class)
    return cause


@dataclasses.dataclass(frozen=True)
class PickerVerdict:
    """One dispatch run's oracle outcome.

    `oracle_disagrees=True` means the picker's stated cause was contradicted
    by on-disk evidence — this is the picker-bug signal /replan routes.
    """

    run_ts: str                       # e.g. "20260526T182233Z"
    lane: str                         # e.g. "tailor" | "UP" | "apply"
    tag: str                          # e.g. "next-up-2026-05-26-3"
    outcome: PickerOutcome
    no_pick_cause: NoPickCause | None
    oracle_disagrees: bool
    picks_emitted: int
    picks_shipped: int
    cost_usd: float | None
    evidence: tuple[str, ...]         # human-readable rationale lines
    picker_reason: str                # picker's own free-text reason (truncated)
    # Which recognizer rung produced `no_pick_cause` — "exact" (a declared/built-in
    # token), "morphological" (the rung-2 substring recognizer matched a compound
    # token's shape), or "none" (UNCLASSIFIED floor / not a NO_PICK). The honesty
    # knob (`docs/105` §3.1): a morphologically-guessed cause is weaker evidence
    # than an exact one, and downstream routing must be able to tell them apart.
    # Defaulted so the LIVE / UNKNOWN construction sites (no cause) need no change.
    cause_source: str = CAUSE_SOURCE_NONE

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_ts": self.run_ts,
            "lane": self.lane,
            "tag": self.tag,
            "outcome": self.outcome.value,
            "no_pick_cause": self.no_pick_cause.value if self.no_pick_cause else None,
            "cause_source": self.cause_source,
            "oracle_disagrees": self.oracle_disagrees,
            "picks_emitted": self.picks_emitted,
            "picks_shipped": self.picks_shipped,
            "cost_usd": self.cost_usd,
            "evidence": list(self.evidence),
            "picker_reason": self.picker_reason,
        }


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """Best-effort YAML load — degrades to {} so the oracle never crashes."""
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _load_verdict_envelope(tag: str) -> dict | None:
    p = _next_up_dir() / f".verdict-{tag}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_dispatch_envelope(run_ts: str) -> dict | None:
    p = _chained_runs() / run_ts / "result_envelopes" / "next-up.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_dispatch_readme(run_ts: str) -> str:
    p = _chained_runs() / run_ts / "README.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


# Pull `--scope X` out of dispatch README args line. Falls back to lane lease
# stanza if `Args:` is bare.
_ARGS_SCOPE = re.compile(r"^- Args: --scope (\S+)", re.M)
_LANE_LEASE = re.compile(r"^- Lane lease: lane=(\S+)", re.M)
_CHILD1_COST = re.compile(r"\$(\d+(?:\.\d+)?)", re.M)


def _infer_lane(readme: str) -> str:
    m = _ARGS_SCOPE.search(readme)
    if m:
        return m.group(1)
    m = _LANE_LEASE.search(readme)
    if m:
        return m.group(1)
    return "unknown"


def _extract_cost(readme: str) -> float | None:
    """Sum the first two `$N.NN` figures (child1 + child2). Best-effort."""
    matches = _CHILD1_COST.findall(readme)
    if not matches:
        return None
    try:
        return sum(float(m) for m in matches[:2])
    except ValueError:
        return None


# The producer prints `verdict=WEDGE … reason_class=LANE_… route=/replan` into the
# headless session's free-text result (and the dispatch README echoes it), but the
# structured `.verdict-<tag>.json` envelope it writes alongside does NOT always carry
# `reason_class` as a field. Measured on job's corpus (2026-06-02): of 62 NO-PICKs the
# oracle could not classify, 29 (47%) had a recoverable token sitting in the dispatch
# `result` prose that the field-only read missed — recall was vacuous over them for a
# plumbing reason, not a real one. This recovers that emitted-but-unlifted token so the
# oracle can grade the decision. Uppercase-token shape mirrors the closed WedgeReason
# vocabulary; an unknown token still resolves to UNCLASSIFIED via `resolve_cause`.
_PROSE_REASON_CLASS = re.compile(r"reason_class=([A-Z][A-Z0-9_]*)")


def _recover_reason_class(*texts: str) -> str:
    """Best-effort extraction of an emitted `reason_class=` token from prose.

    Pure. Scans each text in order (caller passes the dispatch `result` first,
    then the README) and returns the FIRST match, or `""` if none. The fallback
    used only when the structured verdict envelope did not carry the field — so a
    real, emitted reason class is never silently dropped to UNCLASSIFIED.
    """
    for text in texts:
        if not text:
            continue
        m = _PROSE_REASON_CLASS.search(text)
        if m:
            return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# Cross-check rules — these are what make the oracle disagree
# ---------------------------------------------------------------------------


STALE_CLAIM_THRESHOLD_HOURS = 48  # claims older than this are presumed orphan


def _check_stale_claim_real(state: dict, evidence: list[str]) -> bool:
    """If the picker said STALE_CLAIM, does the claim actually look orphan?

    Returns True if the cause is BELIEVABLE (claim genuinely stale).
    Returns False if oracle DISAGREES (claim is fresh — picker bug).
    Best-effort: if we can't find the claim, abstain (return True).
    """
    # Picker bug shape: picker says blocked by a claim that's <24h old or
    # heart-beated recently. Without the specific claim ID in evidence, we
    # can only check the overall claim staleness shape — if all active claims
    # are <24h, the "stale claim" story doesn't hold.
    claims = state.get("active_claims") or state.get("hard_claims") or []
    if not claims:
        evidence.append("oracle: no active hard claims found in state — STALE_CLAIM claim is unverifiable, abstaining")
        return True
    now = dt.datetime.now(dt.timezone.utc)
    ages = []
    for c in claims if isinstance(claims, list) else []:
        ts = c.get("claimed_at") or c.get("heartbeat_at") or c.get("created_at")
        if not ts:
            continue
        try:
            t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            ages.append((now - t).total_seconds() / 3600)
        except Exception:
            continue
    if not ages:
        return True
    stale_count = sum(1 for a in ages if a >= STALE_CLAIM_THRESHOLD_HOURS)
    evidence.append(
        f"oracle: {stale_count}/{len(ages)} active claims older than {STALE_CLAIM_THRESHOLD_HOURS}h "
        f"(claims < threshold suggest STALE_CLAIM claim is suspect)"
    )
    return stale_count > 0


def _check_operator_gate_real(state: dict, picker_reason: str, evidence: list[str]) -> bool:
    """Verify any cited soak deadline is actually still open at run time."""
    # Look for soak-deadline-like dates in picker_reason
    deadline_match = re.search(r"(?:thru|until|through)\s+(\d{4}-\d{2}-\d{2})", picker_reason)
    if not deadline_match:
        return True  # nothing to verify; abstain in favor of picker
    deadline = deadline_match.group(1)
    today = dt.date.today().isoformat()
    if deadline >= today:
        evidence.append(f"oracle: soak deadline {deadline} >= today {today} — OPERATOR_GATE confirmed")
        return True
    evidence.append(f"oracle: soak deadline {deadline} < today {today} — gate has EXPIRED, picker should have re-picked")
    return False


def _check_true_drain_real(state: dict, scope_plan_ids: list[str], evidence: list[str]) -> bool:
    """If picker said TRUE_DRAIN, do any in-scope plans have non-empty `remaining`?"""
    if not scope_plan_ids:
        return True
    plans = state.get("plans") or []
    by_id = {p.get("id"): p for p in plans if isinstance(p, dict)}
    non_drained = []
    for pid in scope_plan_ids:
        plan = by_id.get(pid)
        if not plan:
            continue
        remaining = plan.get("remaining") or []
        if remaining:
            non_drained.append(f"{pid}({len(remaining)})")
    if non_drained:
        evidence.append(
            f"oracle: in-scope plans with non-empty remaining: {', '.join(non_drained)} — "
            f"TRUE_DRAIN is FALSE"
        )
        return False
    evidence.append(f"oracle: all in-scope plans ({', '.join(scope_plan_ids)}) have remaining:[] — TRUE_DRAIN confirmed")
    return True


def _check_misroute_real(envelope: dict, evidence: list[str]) -> bool:
    """A MISROUTE claim is self-explanatory; check the envelope at least names
    the misroute target. If the picker emits MIS_ROUTED_FINDING with no
    target lane, the claim is unfounded."""
    reason = envelope.get("reason", "")
    has_target = bool(re.search(r"belongs?\s+to\s+(\w+)|actually\s+(\w+)", reason, re.I))
    if has_target:
        evidence.append("oracle: MISROUTE claim names a target lane — believable")
        return True
    evidence.append("oracle: MISROUTE claim has no target lane named — unverifiable, picker may be hand-waving")
    return False


# ---------------------------------------------------------------------------
# Classification — pure function on assembled inputs
# ---------------------------------------------------------------------------


def classify(
    *,
    run_ts: str,
    verdict_env: dict | None,
    dispatch_env: dict | None,
    readme: str,
    state: dict,
) -> PickerVerdict:
    """Pure function — produces a PickerVerdict from assembled inputs."""
    lane = _infer_lane(readme)
    cost = _extract_cost(readme)

    # Tag — prefer verdict envelope's own tag; fall back to extracting from readme.
    tag = (verdict_env or {}).get("tag") or ""
    if not tag and readme:
        m = re.search(r"next-up-\d{4}-\d{2}-\d{2}-\d+", readme)
        if m:
            tag = m.group(0)

    picks_total = (verdict_env or {}).get("picks") or []
    picks_emitted = len(picks_total) if isinstance(picks_total, list) else 0
    picks_shipped = _extract_picks_shipped(readme)

    if not verdict_env:
        return PickerVerdict(
            run_ts=run_ts,
            lane=lane,
            tag=tag,
            outcome=PickerOutcome.UNKNOWN,
            no_pick_cause=None,
            oracle_disagrees=False,
            picks_emitted=0,
            picks_shipped=picks_shipped,
            cost_usd=cost,
            evidence=("oracle: no verdict envelope found",),
            picker_reason="",
        )

    picker_verdict = (verdict_env.get("verdict") or "").upper()
    picker_reason = (verdict_env.get("reason") or "")[:500]

    # LIVE shape: envelope has all_clear=true and picks emitted (round 0 is
    # the picker's "pre-veto-clean" round before refinement; both round 0
    # and final-round all_clear envelopes count as LIVE-shaped).
    if verdict_env.get("all_clear") and picks_emitted > 0:
        if picks_shipped > 0:
            outcome = PickerOutcome.LIVE
        else:
            outcome = PickerOutcome.LIVE_DIRTY
        return PickerVerdict(
            run_ts=run_ts,
            lane=lane,
            tag=tag,
            outcome=outcome,
            no_pick_cause=None,
            oracle_disagrees=False,
            picks_emitted=picks_emitted,
            picks_shipped=picks_shipped,
            cost_usd=cost,
            evidence=(f"oracle: picker emitted {picks_emitted} ACCEPT picks, {picks_shipped} shipped",),
            picker_reason=picker_reason,
        )

    # NO_PICK shape — verdict is WEDGE/DRAIN/(missing)/blocked. `resolve_cause`
    # is registry-aware: a workspace-declared reason class resolves to its
    # category here, so a custom reason is verifiable, not just emittable.
    evidence: list[str] = []
    reason_class = (verdict_env.get("reason_class") or "").upper().strip()
    # Prose fallback: the producer emits `reason_class=` into the dispatch result
    # (and README) even when the structured envelope drops the field. Recover it
    # so a genuinely-emitted token is graded, not lost to UNCLASSIFIED. Only fires
    # when the field is absent — the structured value always wins.
    if not reason_class:
        recovered = _recover_reason_class(
            str((dispatch_env or {}).get("result") or ""), readme
        )
        if recovered:
            reason_class = recovered.upper().strip()
            evidence.append(
                f"oracle: recovered reason_class={reason_class} from dispatch prose "
                f"(structured envelope dropped the field)"
            )
    cause, cause_source, matched = resolve_cause_with_source(reason_class)
    if cause == NoPickCause.UNCLASSIFIED and picker_verdict == "DRAIN":
        cause = NoPickCause.TRUE_DRAIN
        cause_source = CAUSE_SOURCE_EXACT  # the DRAIN verdict itself is the signal
    if cause_source == CAUSE_SOURCE_MORPHOLOGICAL:
        # The cause came from the rung-2 shape recognizer, not a declared token —
        # record which substring fired so the (weaker) basis is auditable.
        evidence.append(
            f"oracle: classified reason_class={reason_class} as {cause.value} via "
            f"morphological rung (matched {matched!r}; weaker than an exact token)"
        )

    # Cross-check: does on-disk state support the claim?
    disagrees = False
    # `scope` is the renderer's structured `{plan_ids: [...]}` block, but an
    # LLM-written no-pick envelope sometimes writes a free-text label string
    # (e.g. "tailor -> AR, IF, TS"). Only read plan_ids off a dict; a string
    # scope carries no machine-readable ids, so abstain (empty list -> the
    # TRUE_DRAIN cross-check abstains in favor of the picker).
    scope_raw = verdict_env.get("scope")
    scope_plan_ids = (
        (scope_raw.get("plan_ids") or []) if isinstance(scope_raw, dict) else []
    )

    if cause == NoPickCause.STALE_CLAIM:
        believable = _check_stale_claim_real(state, evidence)
        if not believable:
            disagrees = True
    elif cause == NoPickCause.OPERATOR_GATE:
        believable = _check_operator_gate_real(state, picker_reason, evidence)
        if not believable:
            disagrees = True
    elif cause == NoPickCause.TRUE_DRAIN:
        believable = _check_true_drain_real(state, scope_plan_ids, evidence)
        if not believable:
            disagrees = True
    elif cause == NoPickCause.MISROUTE:
        believable = _check_misroute_real(verdict_env, evidence)
        if not believable:
            disagrees = True
    elif cause == NoPickCause.UNCLASSIFIED:
        evidence.append("oracle: legacy envelope w/o reason_class; cannot verify — recommend backfill")

    return PickerVerdict(
        run_ts=run_ts,
        lane=lane,
        tag=tag,
        outcome=PickerOutcome.NO_PICK,
        no_pick_cause=cause,
        oracle_disagrees=disagrees,
        picks_emitted=picks_emitted,
        picks_shipped=picks_shipped,
        cost_usd=cost,
        evidence=tuple(evidence),
        picker_reason=picker_reason,
        cause_source=cause_source,
    )


# Order matters — `2/2 picks shipped` first, then bullet `Picks shipped: 2`, then last
# fallback `0 shipped`.
# Capture BOTH numerator and denominator so an inverted/oversized ratio
# (`315/82 shipped` — prose, not a per-run pick count) can be rejected: you
# cannot ship more picks than were dispatched. Seen 2026-05-28 inflating
# precision to 8.13 (data-trust-floor / DD axiom violation).
_RATIO_SHIPPED = re.compile(
    r"(\d+)\s*/\s*(\d+)\s+(?:chain phases?\s+)?(?:picks?\s+)?shipped", re.I
)
_BULLET_SHIPPED = re.compile(r"Picks shipped:\s+(\d+)", re.I)

# A single /next-up packet caps at 5 picks (next_up_render max_picks=5); a
# chained-depth slot can add a few hops. Anything beyond this from a README
# scrape is a cross-run / prose false-match, not a real per-run ship count.
_MAX_PER_RUN_SHIPPED = 12


def _extract_picks_shipped(readme: str) -> int:
    """Best-effort scan of dispatch README for ship count.

    Recognises (in order):
      * `2/2 picks shipped clean` (rejected when numerator > denominator)
      * `Picks shipped: 2`
      * `Picks shipped: none` / `0 shipped`
      * `Picks shipped: GH3 (...), FQ-348 (...)` — count parenthesised SHAs as a list

    Every recognised count is clamped to `_MAX_PER_RUN_SHIPPED`: a value past
    that is a cross-run or prose false-match, never a real per-run ship count.
    """
    m = _RATIO_SHIPPED.search(readme)
    if m:
        try:
            num, denom = int(m.group(1)), int(m.group(2))
            # Reject inverted/oversized ratios — `315/82 shipped` is prose,
            # not "315 of 82 picks". A real per-run ratio has num <= denom.
            if num <= denom and num <= _MAX_PER_RUN_SHIPPED:
                return num
        except ValueError:
            pass
    m = _BULLET_SHIPPED.search(readme)
    if m:
        try:
            return min(int(m.group(1)), _MAX_PER_RUN_SHIPPED)
        except ValueError:
            pass
    # `Picks shipped: <list>` shape — count entries with parenthesised commits
    list_match = re.search(r"Picks shipped:\s+([^\n]+)", readme, re.I)
    if list_match:
        candidates = list_match.group(1)
        # count parenthesised entries `(... <sha>)` — heuristic but precise enough
        n = len(re.findall(r"\([^)]+`?[0-9a-f]{6,}`?\)", candidates))
        if n > 0:
            return min(n, _MAX_PER_RUN_SHIPPED)
    lowered = readme.lower()
    if "picks shipped: none" in lowered or "0 shipped" in lowered or "none (lane drained)" in lowered:
        return 0
    return 0


# ---------------------------------------------------------------------------
# Sweep / report / check (the CLI surface)
# ---------------------------------------------------------------------------


def _list_recent_runs(since_iso: str | None) -> list[str]:
    _chained = _chained_runs()
    if not _chained.exists():
        return []
    out = []
    for child in sorted(_chained.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if not re.match(r"^\d{8}T\d{6}Z", name):
            continue
        if since_iso and name < since_iso:
            continue
        out.append(name)
    return out


def _parse_since(s: str | None) -> str | None:
    """Convert '7d' / '24h' / ISO -> 'YYYYMMDDTHHMMSSZ' string for comparison."""
    if not s:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    m = re.fullmatch(r"(\d+)([dh])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = dt.timedelta(days=n) if unit == "d" else dt.timedelta(hours=n)
        threshold = now - delta
        return threshold.strftime("%Y%m%dT%H%M%SZ")
    # assume ISO date
    try:
        d = dt.date.fromisoformat(s)
        return d.strftime("%Y%m%dT000000Z")
    except ValueError:
        return None


def _audit_dir(window: str) -> Path:
    return _audits_dir() / window


def _load_existing(window: str) -> dict[tuple[str, str], dict]:
    """Idempotency: load already-classified rows so re-runs are no-ops."""
    path = _audit_dir(window) / "oracle.jsonl"
    if not path.exists():
        return {}
    out: dict[tuple[str, str], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (row.get("run_ts", ""), row.get("tag", ""))
        out[key] = row
    return out


def _classify_one(run_ts: str, state: dict) -> PickerVerdict:
    readme = _load_dispatch_readme(run_ts)
    dispatch_env = _load_dispatch_envelope(run_ts)
    # Tag resolution — prefer dispatch envelope, else readme.
    tag = ""
    if dispatch_env and isinstance(dispatch_env.get("tag"), str):
        tag = dispatch_env["tag"]
    if not tag and readme:
        m = re.search(r"next-up-\d{4}-\d{2}-\d{2}-\d+", readme)
        if m:
            tag = m.group(0)
    verdict_env = _load_verdict_envelope(tag) if tag else None

    # Envelope-clobber guard. The dispatch's own `result` field is the
    # truth-bearer because it was written by the child's stdout at exit
    # time — the on-disk `.verdict-<tag>.json` can be overwritten by a
    # later same-tag dispatch (real bug seen in 20260526T155903Z's tag
    # `next-up-2026-05-26-2`). If dispatch `result` mentions verdict=WEDGE
    # but the verdict envelope claims all_clear, the envelope is stale —
    # synthesize a minimal verdict_env so classification doesn't misread.
    if dispatch_env and verdict_env:
        result_text = str(dispatch_env.get("result") or "")
        if "verdict=WEDGE" in result_text and verdict_env.get("all_clear"):
            # build a minimal synthetic envelope reflecting the true outcome
            verdict_env = {
                "tag": tag,
                "verdict": "WEDGE",
                "all_clear": False,
                "blocked": True,
                "picks": [],
                "reason": result_text[:500],
                "_synthesized": True,
                "_clobber_reason": "on-disk verdict envelope was overwritten by a later dispatch sharing the tag",
            }

    return classify(
        run_ts=run_ts,
        verdict_env=verdict_env,
        dispatch_env=dispatch_env,
        readme=readme,
        state=state,
    )


def cmd_classify(args: argparse.Namespace) -> int:
    state = _load_yaml(_state_path())
    v = _classify_one(args.run_ts, state)
    print(json.dumps(v.to_dict(), indent=2))
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    since_iso = _parse_since(args.since)
    runs = _list_recent_runs(since_iso)
    window = args.window or (args.since or "all")
    audit_dir = _audit_dir(window)
    audit_dir.mkdir(parents=True, exist_ok=True)
    out_path = audit_dir / "oracle.jsonl"
    existing = _load_existing(window)
    state = _load_yaml(_state_path())
    n_new = 0
    n_skip = 0
    rows: dict[tuple[str, str], dict] = dict(existing)
    for run_ts in runs:
        v = _classify_one(run_ts, state)
        key = (run_ts, v.tag)
        if key in existing and not args.force:
            n_skip += 1
            continue
        rows[key] = v.to_dict()
        n_new += 1
    rows_sorted = sorted(rows.values(), key=lambda r: (r.get("run_ts", ""), r.get("tag", "")))
    # Rewrite the file atomically (small enough, append-only-shape but idempotent)
    out_path.write_text(
        "\n".join(json.dumps(r) for r in rows_sorted) + "\n",
        encoding="utf-8",
    )
    print(f"sweep: {n_new} new, {n_skip} skipped, {len(rows_sorted)} total -> {out_path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    window = args.window
    audit_dir = _audit_dir(window)
    rows_path = audit_dir / "oracle.jsonl"
    if not rows_path.exists():
        print(f"no oracle.jsonl at {rows_path}; run `sweep --window {window}` first", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    md = _render_report(window, rows)
    out_path = audit_dir / "picker_recall_audit.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"report: {len(rows)} rows -> {out_path}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """CI gate. Exit 0 if recall floor met, 1 if not."""
    window = args.window
    rows_path = _audit_dir(window) / "oracle.jsonl"
    if not rows_path.exists():
        print(f"no oracle.jsonl at {rows_path}", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    metrics = _compute_metrics(rows)
    print(json.dumps(metrics, indent=2))
    if metrics["recall_proxy"] < args.min_recall:
        print(f"FAIL: recall_proxy {metrics['recall_proxy']:.2f} < floor {args.min_recall:.2f}", file=sys.stderr)
        return 1
    print(f"PASS: recall_proxy {metrics['recall_proxy']:.2f} >= floor {args.min_recall:.2f}")
    return 0


def _compute_metrics(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0, "precision": None, "recall_proxy": None, "cost_per_ship": None}
    picks_emitted = sum(r.get("picks_emitted", 0) for r in rows)
    total_cost = sum((r.get("cost_usd") or 0.0) for r in rows)
    # Precision counts ships ONLY from rows that actually emitted picks (LIVE /
    # LIVE_DIRTY). A README ship-count scraped off an UNKNOWN row (no verdict
    # envelope, picks_emitted=0) is a cross-run artefact — including it pushes
    # precision above 1.0 (the data-trust-floor violation seen 2026-05-28).
    emitted_rows = [r for r in rows if r.get("picks_emitted", 0) > 0]
    picks_shipped = sum(r.get("picks_shipped", 0) for r in emitted_rows)
    # recall_proxy: 1 - (oracle-disagrees fraction of no-pick runs).
    no_picks = [r for r in rows if r.get("outcome") == "NO_PICK"]
    picker_bugs = sum(1 for r in no_picks if r.get("oracle_disagrees"))
    # UNCLASSIFIED no-pick rows are NOT verified clean — they're unverifiable
    # (legacy envelope, no reason_class). Surface the count so a green
    # recall_proxy is honest about how much of the no-pick set it could not
    # check. The proxy itself stays conservative (unverifiable ≠ bug) so the CI
    # floor doesn't flap, but the operator sees the unverified denominator.
    unverifiable = sum(
        1 for r in no_picks if r.get("no_pick_cause") == "UNCLASSIFIED"
    )
    verified_no_pick = len(no_picks) - unverifiable
    recall_proxy = 1.0 - (picker_bugs / max(len(no_picks), 1)) if no_picks else 1.0
    precision = (picks_shipped / picks_emitted) if picks_emitted else None
    cost_per_ship = (total_cost / picks_shipped) if picks_shipped else None
    return {
        "n": n,
        "picks_emitted": picks_emitted,
        "picks_shipped": picks_shipped,
        "total_cost_usd": round(total_cost, 2),
        "precision": round(precision, 3) if precision is not None else None,
        "recall_proxy": round(recall_proxy, 3),
        "cost_per_ship": round(cost_per_ship, 2) if cost_per_ship is not None else None,
        "picker_bug_count": picker_bugs,
        "no_pick_count": len(no_picks),
        "unverifiable_no_pick_count": unverifiable,
        "verified_no_pick_count": verified_no_pick,
    }


def _render_report(window: str, rows: list[dict]) -> str:
    metrics = _compute_metrics(rows)
    # Cause histogram
    causes: dict[str, int] = {}
    for r in rows:
        c = r.get("no_pick_cause") or ""
        if c:
            causes[c] = causes.get(c, 0) + 1
    # Top oracle-disagreement rows
    bugs = [r for r in rows if r.get("oracle_disagrees")]
    bugs_sorted = sorted(bugs, key=lambda r: r.get("run_ts", ""), reverse=True)

    lines = [
        f"# Picker recall audit — window `{window}`",
        "",
        f"_Generated by `scripts/picker_oracle.py report --window {window}`._",
        "",
        "## Headline metrics",
        "",
        f"- **N dispatches:** {metrics['n']}",
        f"- **Picks emitted:** {metrics['picks_emitted']}",
        f"- **Picks shipped:** {metrics['picks_shipped']}",
        f"- **Precision** (shipped / emitted): `{metrics['precision']}`",
        f"- **Recall proxy** (1 − picker-bug / no-pick): `{metrics['recall_proxy']}`",
        f"- **No-pick verified / unverifiable:** "
        f"{metrics.get('verified_no_pick_count', 0)} / "
        f"{metrics.get('unverifiable_no_pick_count', 0)} "
        f"(recall_proxy is honest only over the verified set)",
        f"- **Total cost:** `${metrics['total_cost_usd']}`",
        f"- **Cost per ship:** `${metrics['cost_per_ship']}`",
        f"- **Picker-bug NO-PICKs:** {metrics['picker_bug_count']} / {metrics['no_pick_count']}",
        "",
        "## NO-PICK cause histogram",
        "",
        "| Cause | Count |",
        "|---|---|",
    ]
    for cause, count in sorted(causes.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{cause}` | {count} |")
    lines.append("")
    lines.append("## Oracle-disagrees rows (picker bugs)")
    lines.append("")
    if not bugs_sorted:
        lines.append("_None._")
    else:
        lines.append("| run_ts | lane | tag | cause | picker reason (truncated) |")
        lines.append("|---|---|---|---|---|")
        for r in bugs_sorted:
            reason = (r.get("picker_reason") or "").replace("|", "\\|").replace("\n", " ")[:120]
            lines.append(
                f"| `{r['run_ts']}` | {r.get('lane','')} | `{r.get('tag','')}` | "
                f"`{r.get('no_pick_cause','')}` | {reason} |"
            )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `recall_proxy` is a proxy because we can't enumerate the true set of pickable ")
    lines.append("  work without a parallel-universe picker run. Instead, we measure NO-PICK rows ")
    lines.append("  where on-disk state contradicts the picker's claim — those are *known* missed ")
    lines.append("  picks. A floor of 0.7 means at most 30% of NO-PICKs may be unverifiable; tune ")
    lines.append("  upward as cross-check coverage grows.")
    lines.append("- Backfill: legacy envelopes (`UNCLASSIFIED`) inflate the noise floor. As more ")
    lines.append("  envelopes carry `reason_class`, recall_proxy gets sharper.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_c = sub.add_parser("classify", help="classify a single dispatch run")
    p_c.add_argument("run_ts", help="e.g. 20260526T182233Z")
    p_c.set_defaults(func=cmd_classify)

    p_s = sub.add_parser("sweep", help="classify all dispatches in window; idempotent")
    p_s.add_argument("--since", default="7d", help="e.g. 7d, 24h, or ISO date")
    p_s.add_argument("--window", default=None, help="output dir name (default: --since value)")
    p_s.add_argument("--force", action="store_true", help="re-classify already-classified runs")
    p_s.set_defaults(func=cmd_sweep)

    p_r = sub.add_parser("report", help="render picker_recall_audit.md")
    p_r.add_argument("--window", required=True)
    p_r.set_defaults(func=cmd_report)

    p_k = sub.add_parser("check", help="CI gate: exit non-zero if recall floor not met")
    p_k.add_argument("--window", required=True)
    p_k.add_argument("--min-recall", type=float, default=0.7)
    p_k.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
