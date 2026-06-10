"""The PURE write-admission gate for Agent-Diff (docs/216→228) — $0, importable, no network.

THE SAME SHAPE AS tau2, A RICHER WITNESS
----------------------------------------
This is `benchmark/agentprocessbench/writeadmit/gate.py` re-aimed at Agent-Diff. The join is
identical; only the WITNESS is richer (a structured `{passed, failures, score}` instead of
tau2's single `db_match` bool):

  * the CLAIM side  = `benchmark.agentdiff.claim.confident_write_claim(answer_text)` — the
    Agent-Diff landed-phrase detector (the tau2 detector's lexicon misses every box/slack/
    linear/calendar write verb; see `claim.py`). The agent authored these bytes → FORGEABLE.
  * the WITNESS side = the env's `AssertionEngine.evaluate(diff)` result — `passed` (did the
    observed diff satisfy the GOLD assertion spec?), wrapped as an `EvidenceFacts` on the
    NON-FORGEABLE `OS_RECORDED` rung. The agent authors ZERO bytes of the observed diff (the
    differ computed it from DB snapshots), the gold spec (the task author wrote it), or the
    pass/fail verdict (the engine computed it).
  * the DECISION   = `dos.effect_witness.witness_effect(claim, [witness])`. BLOCK iff a
    confident write-claim is REFUTED by the accountable witness; ADMIT otherwise.

WHY `passed`, NOT THE STRUCTURED `failures`, DRIVES THE REFUTATION (the byte-clean choice)
------------------------------------------------------------------------------------------
The structured `failures`/`diff` are FORENSIC DETAIL carried alongside the verdict, never the
verdict itself. The refutation rides the single env-authored `passed` bit, because:
  (1) `passed` is the env's own all-assertions-hold verdict — the soundest available witness,
      and the one with the cleanest provenance (no parsing of failure strings the gate would
      then have to trust).
  (2) Refuting on a *partial* pass (some assertions failed) risks BLOCKing an honest agent
      that did the asserted write but tripped an unrelated strict-mode check — the docs/143
      −9 pp false-block lesson. So a confident write is REFUTED iff the env says the run did
      NOT pass; a partial/strict miss that still leaves `passed` True is never a block.
  (3) The structured detail is RECORDED in the decision (for the operator + the A/B handoff),
      but it never moves the refuted bit — keeping the witness a single accountable signal.

THE FLOOR THAT MAKES IT SAFE (the docs/216 invariant, kernel-enforced)
----------------------------------------------------------------------
`witness_effect` applies `believe_under_floor`: a read-back on the FORGEABLE `AGENT_AUTHORED`
rung yields UNWITNESSED (`refuted=False`), never REFUTED. A policy that pastes a fake
"assertions passed" receipt into its own answer can NEVER trip OR untrip the gate — only an
`OS_RECORDED` witness sets the refuted bit. The gate can only ever BLOCK-MORE under a sound
witness, never be talked into ADMIT by the agent's own bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from dos.effect_witness import (
    Accountability,
    EffectClaim,
    EvidenceFacts,
    witness_effect,
)

from .claim import confident_write_claim


@dataclass(frozen=True)
class AdmitDecision:
    """The gate's verdict on one trajectory's publish request."""
    admit: bool             # True -> publish to the handoff ledger; False -> BLOCK
    verdict: str            # the witness_effect verdict, or NO_CLAIM / UNWITNESSED_BUT_CLAIMED
    reason: str
    confident_write: bool   # did A make a confident write-claim at all?
    passed: Optional[bool]  # the env witness (True landed / False refuted / None no-witness)
    score: dict[str, Any] = field(default_factory=dict)
    failures: tuple[str, ...] = ()   # FORENSIC detail, NEVER drives the refutation


def parse_passed(resp: Any) -> Optional[bool]:
    """Defensively coerce a witness `passed` field to a genuine bool, else None (the must-fix).

    The live SDK returns `passed` on `TestResultResponse`/`EndRunResponse`; a transport error
    or a partial response can leave it absent or a truthy non-bool (an error-body dict). Only a
    GENUINE bool may move the refuted bit — `bool()` coercion of a truthy error body would
    spuriously refute. So: `isinstance(x, bool)` else None (no-witness -> admit). Accepts the
    raw value, an object with a `.passed` attr, or a dict with a `passed`/`'passed'` key.
    """
    x: Any = resp
    if not isinstance(resp, bool):
        if hasattr(resp, "passed"):
            x = getattr(resp, "passed")
        elif isinstance(resp, dict):
            x = resp.get("passed")
    return x if isinstance(x, bool) else None


def _has_presence(score: Optional[dict[str, Any]]) -> bool:
    """Did the env actually WITNESS anything? True iff score names a positive assertion total.

    The presence guard (the conservative-floor must-fix): the env can return `passed=False`
    for two very different reasons — a REAL all-fail (`total>0, failed==total`: the agent
    over-claimed) vs a RUNTIME error / un-evaluated run (`total==0, percent==0`: the ENV
    failed, not the agent). Refuting on the latter would FALSE-BLOCK an honest agent for the
    env's fault. So a refute requires `passed is False` AND a positive `total` — a genuine
    witness with assertions to fail. An empty-spec task (`passed=True, total=0`) never
    refutes anyway (passed is True), so this guard only ever SUPPRESSES a no-witness refute.
    """
    if not isinstance(score, dict):
        return False
    total = score.get("total")
    # `type(total) is int`, NOT `isinstance(total, int)`: bool is a subclass of int in
    # Python, so a malformed score `{"total": False}` would pass an isinstance check and
    # bypass the guard, false-ADMITting a refuted over-claim (the adversarial CRITICAL).
    # A genuine assertion total is a plain int; reject bool (and everything else).
    return type(total) is int and total > 0


def passed_witness(
    passed: Optional[bool], subject: str = "effect", *, score: Optional[dict[str, Any]] = None,
) -> list[EvidenceFacts]:
    """Wrap the env `AssertionEngine.passed` as a NON-FORGEABLE read-back.

    `passed is True`  -> the observed diff satisfied the gold assertion spec -> ATTEST.
    `passed is False` AND the witness has PRESENCE (score.total > 0) -> REFUTE.
    `passed is False` but NO presence (total==0 — a runtime/un-evaluated run) -> abstain ([]).
    `passed is None`  -> no witness available -> abstain ([]).

    Accountability is `OS_RECORDED`: the assertion engine computed `passed` over a diff the
    differ computed from DB snapshots the agent mutated only through the env's tool executor —
    the agent authors none of it. The Agent-Diff analogue of tau2's `db_match` witness, on the
    same non-forgeable rung, but backed by a structured multi-assertion verdict. When `score`
    is omitted (the frozen path always supplies it; a bare bool caller may not) presence is
    assumed for a False (the conservative caller-supplies-bool contract) — the live path ALWAYS
    passes `score` so the runtime-error guard is active where it matters.
    """
    if passed is True:
        return [EvidenceFacts.attest(
            "env_assertion_engine", Accountability.OS_RECORDED, subject,
            detail="observed diff satisfied the gold assertion spec (passed=True)")]
    if passed is False:
        if score is not None and not _has_presence(score):
            # A False with no asserted presence is a runtime/un-evaluated run, not an
            # over-claim — the env failed, not the agent. Abstain rather than false-block.
            return []
        return [EvidenceFacts.refute(
            "env_assertion_engine", Accountability.OS_RECORDED, subject,
            detail="observed diff did NOT satisfy the gold spec (passed=False)")]
    return []  # None -> no accountable witness -> UNWITNESSED -> admit (nothing to refute on)


def admit(
    answer_text: str,
    passed: Optional[bool],
    *,
    subject: str = "effect",
    failures: tuple[str, ...] = (),
    score: Optional[dict[str, Any]] = None,
) -> AdmitDecision:
    """Adjudicate A's publish request. BLOCK iff a confident write-claim is REFUTED.

    `answer_text` is A's final self-report (the forgeable claim). `passed` is the env witness
    (`AssertionEngine.evaluate(diff)['passed']`, live or frozen). `subject` is the correlation
    handle (default 'effect'; the batch path passes the task_id/runId so folding many tasks
    cannot collide in `witness_effect`). `failures`/`score` are forensic detail recorded in
    the decision but never used to refute. Pure: no I/O.
    """
    confident = confident_write_claim(answer_text or "")
    if not confident:
        # No write claimed -> nothing to gate. Publishing a non-write answer is harmless;
        # the gate only guards over-claimed WRITES inherited as state.
        return AdmitDecision(
            admit=True, verdict="NO_CLAIM",
            reason="no confident write claimed — nothing to gate",
            confident_write=False, passed=passed, score=score or {}, failures=failures)

    readbacks = passed_witness(passed, subject, score=score)
    if not readbacks:
        # A confident write-claim with NO accountable witness (passed None, or a runtime-error
        # False the presence guard suppressed). Surfaced as its OWN bucket — never pooled with
        # clean admits — so a confident over-claim that simply went un-witnessed stays visible.
        return AdmitDecision(
            admit=True, verdict="UNWITNESSED_BUT_CLAIMED",
            reason="confident write claimed but no accountable witness (un-evaluated / runtime error)",
            confident_write=True, passed=passed, score=score or {}, failures=failures)

    claim = EffectClaim(key="write_effect", subject=subject, narrated=(answer_text or "")[:160])
    v = witness_effect(claim, readbacks)
    # BLOCK iff an accountable witness REFUTED the confident write-claim. A forgeable
    # (AGENT_AUTHORED) read-back yields UNWITNESSED here, never REFUTED, so it cannot BLOCK.
    return AdmitDecision(
        admit=not v.refuted,
        verdict=v.verdict.value if hasattr(v.verdict, "value") else str(v.verdict),
        reason=v.reason,
        confident_write=True,
        passed=passed,
        score=score or {},
        failures=failures,
    )
