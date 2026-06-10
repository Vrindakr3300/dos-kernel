"""The PURE write-admission gate (docs/216 §6) — $0, importable, no model, no network.

THE CONSUMER, NOT THE PRODUCER
------------------------------
The gate sits between a producing agent A (which finished a tau2 task and emitted a
"resolved/done" claim + a proposed mutating write) and a downstream peer agent B (which
reads A's published result as its starting state). The gate is the out-of-loop consumer
the agent-side WARN ceiling could never reach (docs/188, docs/206): it adjudicates A's
CLAIM against an INDEPENDENT witness and changes what B inherits — it never injects a
turn into A's own loop (so the docs/188/199 turn-injection harm is structurally absent).

THE JOIN (reused verbatim from the over-claim probe)
----------------------------------------------------
  * the CLAIM side  = `_overclaim_probe_witness._confident_write_claim(answer_text)` — the
    converged confident-write detector (lexical ∩ write-verb ∩ witness agreed at 34/250,
    docs/216 §2). The agent authored these bytes → forgeable → never evidence.
  * the WITNESS side = the env DB-hash `db_match` (live: tau2 `EnvironmentEvaluator`
    `evaluator_env.py:124` `DBCheck.db_match`; frozen: a stand-in below), wrapped as an
    `EvidenceFacts` on the NON-FORGEABLE `OS_RECORDED` rung. The agent authors ZERO bytes
    of a DB hash.
  * the DECISION   = `dos.effect_witness.witness_effect(claim, [db_witness])`. BLOCK iff a
    confident write-claim is REFUTED by an accountable witness; ADMIT otherwise.

THE FLOOR THAT MAKES IT SAFE (verified, docs/216)
-------------------------------------------------
`witness_effect` applies `believe_under_floor`: a read-back on the FORGEABLE
`AGENT_AUTHORED` rung yields UNWITNESSED (`refuted=False`), never REFUTED — so a policy
that pastes a fake receipt into its own answer can NEVER trip the gate. Only an
`OS_RECORDED`/`THIRD_PARTY` witness can set the refuted bit. The gate can only ever
BLOCK-MORE under a sound witness, never be talked into ADMIT by the agent's own bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dos.effect_witness import (
    Accountability,
    EffectClaim,
    EvidenceFacts,
    witness_effect,
)

# The proven claim detector + the mutating-tool map — reused verbatim (docs/216 build
# step 1). Importing them here keeps ONE source of the confident-write rule.
from benchmark.agentprocessbench._overclaim_probe_witness import (
    _confident_write_claim,
    _MUTATING_TOOLS,
)


@dataclass(frozen=True)
class AdmitDecision:
    """The gate's verdict on one trajectory's publish request."""
    admit: bool          # True -> publish to the handoff ledger; False -> BLOCK
    verdict: str         # the underlying witness_effect verdict (CONFIRMED/REFUTED/UNWITNESSED/...)
    reason: str
    claim_key: str       # the mutating-tool key the claim was about ("" if no write claimed)
    confident_write: bool  # did A make a confident write-claim at all?


def db_witness(db_match: Optional[bool], subject: str = "effect") -> list[EvidenceFacts]:
    """Wrap the env DB-hash result as a NON-FORGEABLE read-back.

    `db_match is True`  -> the predicted post-run DB hash == the gold hash -> ATTEST.
    `db_match is False` -> the claimed write did not land as the correct state -> REFUTE.
    `db_match is None`  -> no witness available (the task has no DB check) -> abstain (UNWITNESSED).

    The accountability is `OS_RECORDED`: the hash is computed by the tau2 evaluator over an
    env the agent mutated only through the env's own tool executor — the agent authors none
    of it. This is the LIVE correctness witness that replaces the frozen human `final_label`
    and closes the docs/204 Wall-3 presence-vs-correctness gap.
    """
    if db_match is True:
        return [EvidenceFacts.attest(
            "env_db_hash", Accountability.OS_RECORDED, subject,
            detail="predicted DB hash == gold DB hash")]
    if db_match is False:
        return [EvidenceFacts.refute(
            "env_db_hash", Accountability.OS_RECORDED, subject,
            detail="predicted DB hash != gold (claimed write did not land correctly)")]
    return []  # None -> no accountable witness -> UNWITNESSED -> admit (nothing to refute on)


def admit(answer_text: str, db_match: Optional[bool]) -> AdmitDecision:
    """Adjudicate A's publish request. BLOCK iff a confident write-claim is REFUTED.

    `answer_text` is A's final self-report (the forgeable claim). `db_match` is the env
    DB-hash witness (live `DBCheck.db_match`, or a frozen stand-in). Pure: no I/O.
    """
    confident, tools = _confident_write_claim(answer_text or "")
    if not confident:
        # No write claimed -> nothing to gate. Publishing a non-write answer is harmless;
        # the gate only guards over-claimed WRITES inherited as state.
        return AdmitDecision(True, "NO_CLAIM", "no confident write claimed — nothing to gate",
                             "", False)

    claim_key = "|".join(tools) if tools else "generic-write"
    claim = EffectClaim(key=claim_key, subject="effect", narrated=(answer_text or "")[:160])
    v = witness_effect(claim, db_witness(db_match, "effect"))
    # BLOCK iff an accountable witness REFUTED the confident write-claim. A forgeable
    # (AGENT_AUTHORED) read-back yields UNWITNESSED here, never REFUTED, so it cannot BLOCK.
    return AdmitDecision(
        admit=not v.refuted,
        verdict=v.verdict.value if hasattr(v.verdict, "value") else str(v.verdict),
        reason=v.reason,
        claim_key=claim_key,
        confident_write=True,
    )


def is_mutating_tool(name: str) -> bool:
    """Whether a tool name is in the tau2 WRITE family (the claim_key vocabulary)."""
    return name in _MUTATING_TOOLS
