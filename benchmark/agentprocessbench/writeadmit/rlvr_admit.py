"""E-TAU2-RLVR-ADMIT — the lab-facing twin of the write-admission gate (docs/216 §5).

THE SAME WITNESS, A DIFFERENT CONSUMER
--------------------------------------
`gate.py` is the *commons / buyer* consumer: an out-of-loop write-admission gate that
decides what a downstream PEER inherits. This module is the *frontier-lab* consumer over
the IDENTICAL join — the only thing that changes is WHO reads the verdict and WHAT outcome
it flips:

    gate.admit(answer, db_match)            -> may peer B INHERIT A's write?   (commons)
    rlvr_admit.admit_to_reward_set(...)     -> may a fine-tune TRAIN on A's run? (lab)

The consumer here is a **reward-set admission filter** (an RL/SFT/DPO rejection sampler).
A self-judged sampler banks every "resolved/done" trajectory as a positive reward label —
which teaches the model to *over-claim more* (it is rewarded for confidently narrating
success it did not achieve: reward-hacking on its own narration). The witness-gated filter
accepts a "resolved" claim into the positive set ONLY if an independent witness CONFIRMS
the claimed write, and REJECTS a refuted "resolved" claim. The flipped outcome is the
**composition of the reward set a downstream fine-tune trains on** (docs/216 §5).

WHY THIS IS THE NON-DISTILLABLE LABEL (the prized RLVR property)
---------------------------------------------------------------
The accept/reject bit is a function of world-state the policy cannot reproduce from its
own weights or outputs. By the `believe_under_floor` floor (verified in `gate.py` + the
test below): a FORGEABLE `AGENT_AUTHORED` read-back can never flip CONFIRMED↔REFUTED —
only the env's own DB-hash can. A model cannot distill this reward from its own outputs,
which is exactly the hard, env-grounded signal RLVR wants. (Contrast a self-judge or an
LLM-judge reward: the policy CAN learn to satisfy those — `g3_forgeability.py`: a
deterministic floor false-accepts 0.000, an LLM-judge false-accepts 0.352.)

THE WITNESS IS THE NARROW WRITE-CORRECTNESS BIT, NOT THE COMPOSITE REWARD
------------------------------------------------------------------------
We label on `db_match` (the env DB-hash), NOT on tau2's full `reward`. The full reward
folds in the NL-COMMUNICATE checks too, so it can be 0 while the write landed correctly
(measured live: airline/7 has db_match=True but reward=0.0). Keying the reward LABEL on
the least-gameable sub-witness — the bit the agent authors zero of and that answers write
*correctness* — is the point: it is the cleanest non-distillable signal in the trajectory.

WHAT'S BUILT HERE ($0, runs on the REAL live rows from docs/228's J=5 run)
-------------------------------------------------------------------------
This is docs/216 §5 **Payoff 1** (acceptance-precision lift), promoted from the frozen
human-label proxy §5 specified to the LIVE `db_match` rows docs/228 produced — a strictly
stronger witness (correctness, not presence). It reuses the gate's verbatim join; the lab
fork is the final classifier `admit_to_reward_set` + the corpus fold `acceptance_ab`.
Payoff 2 (train two DPO/LoRA runs, measure the trained policy's over-claim-rate delta J2)
needs a GPU/SFT pipeline that does not exist on disk — it stays specified-but-deferred
(docs/230 §5).
"""

from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .gate import admit, AdmitDecision


# ---------------------------------------------------------------------------------------
# The lab fork: the LAST function only. Everything above (the claim detector, the witness
# wrap, the believe_under_floor join) is the gate's, reused byte-for-byte through `admit`.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RewardLabel:
    """The reward-labeler's verdict on one trajectory's bid for the positive set.

    `accept` — does this trajectory enter the SFT/DPO POSITIVE (preferred) set?
    `poison` — would a NAIVE (self-judged, witness-blind) sampler have accepted this as a
               positive WHILE the witness refutes it? (a confident "resolved" the env
               disconfirms). These are the labels the witness PURGES — the J of this arm.
    `dispreferred` — the DPO use: a refuted "resolved" claim is the *dispreferred* member
               of a (witnessed-resolved, over-claimed) preference pair.
    """
    accept: bool
    poison: bool
    dispreferred: bool
    verdict: str          # CONFIRMED / REFUTED / UNWITNESSED / NO_CLAIM (the gate's join)
    resolved_claim: bool  # did the trajectory make a confident "resolved/done" write-claim?
    reason: str


def admit_to_reward_set(answer_text: str, db_match: Optional[bool]) -> RewardLabel:
    """Decide whether one trajectory's "resolved" claim enters the positive reward set.

    The fork of `gate.admit`: same claim-extractor, same witness, same floor — a DIFFERENT
    consumer. Pure: no I/O. (`answer_text` is A's forgeable self-report; `db_match` is the
    env DB-hash witness — the same two independently-authored fields the gate adjudicates.)

    Policy (witness-gated rejection sampling):
      * NO confident write-claim                      -> not a "resolved" bid -> not accepted
        into the WRITE-positive set (nothing to verify), not poison (it claimed nothing).
      * confident write-claim AND witness CONFIRMS    -> ACCEPT (a witnessed-resolved positive).
      * confident write-claim AND witness REFUTES      -> REJECT + flag POISON + DISPREFERRED
        (a naive sampler would have banked this as a positive; the witness purges it).
      * confident write-claim AND no witness (None)    -> abstain: not accepted as a witnessed
        positive (we never mint a positive on the unforgeable rung without a witness), not
        poison (the witness did not refute it — `believe_under_floor`, never invent a verdict).
    """
    d: AdmitDecision = admit(answer_text, db_match)
    if not d.confident_write:
        return RewardLabel(
            accept=False, poison=False, dispreferred=False,
            verdict=d.verdict, resolved_claim=False,
            reason="no confident write-claim — not a resolved bid for the write-positive set",
        )
    # A confident "resolved" write-claim. The gate's `admit` is True iff NOT refuted.
    if d.verdict == "CONFIRMED":
        return RewardLabel(
            accept=True, poison=False, dispreferred=False,
            verdict=d.verdict, resolved_claim=True,
            reason="witnessed-resolved write — accepted into the positive set",
        )
    if d.verdict == "REFUTED":
        return RewardLabel(
            accept=False, poison=True, dispreferred=True,
            verdict=d.verdict, resolved_claim=True,
            reason="confident 'resolved' the env DB-hash refutes — POISON positive purged",
        )
    # UNWITNESSED (db_match is None): a confident claim with no accountable witness. We do
    # not accept it as a witnessed positive (no CONFIRM), and it is not poison (no REFUTE).
    return RewardLabel(
        accept=False, poison=False, dispreferred=False,
        verdict=d.verdict, resolved_claim=True,
        reason="confident write but no env witness — abstain (never mint a positive unverified)",
    )


# ---------------------------------------------------------------------------------------
# The $0 acceptance-precision A/B over the REAL live rows (docs/228's J=5 run).
#
# believe-select  = the naive self-judged sampler: accept every confident "resolved" claim
#                   as a positive (witness-blind). This is today's default RLVR/RFT loop.
# adjudicate-select = the witness-gated filter: accept iff db_match CONFIRMS.
#
# The two Payoff-1 numbers (docs/216 §5): acceptance PRECISION of each arm (fraction of the
# accepted positives that are genuinely witnessed-resolved), and J = the poison positives
# the witness PURGED (the believe arm banks them; the adjudicate arm does not).
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptanceABResult:
    n_rows: int                  # clean live rows folded
    n_resolved_bids: int         # confident "resolved" write-claims (the positive candidates)
    believe_accepted: int        # naive arm: every resolved bid (witness-blind)
    believe_poison: int          # of those, how many the witness refutes (poison banked)
    believe_precision: float     # witnessed-resolved / accepted, naive arm
    adjudicate_accepted: int     # witness-gated arm: only db_match==True bids
    adjudicate_poison: int       # poison the gated arm banks (0 by construction)
    adjudicate_precision: float  # witnessed-resolved / accepted, gated arm (1.0 by construction)
    j_poison_purged: int         # J: poison positives the witness removed (= believe_poison)
    delta_precision: float       # adjudicate_precision - believe_precision (the ΔP lift)


def _row_label(row: dict) -> RewardLabel:
    """Label one cached live row. The row carries the agent's answer + the env db_match."""
    answer = row.get("answer_excerpt") or row.get("answer_text") or ""
    return admit_to_reward_set(answer, row.get("db_match"))


def acceptance_ab(rows: Iterable[dict]) -> AcceptanceABResult:
    """Fold the live rows into the believe-select vs adjudicate-select acceptance A/B.

    Pure over already-loaded rows (the file read happens in `load_live_rows`). Counts the
    two Payoff-1 numbers. A "resolved bid" is a confident write-claim; an accepted positive
    is witnessed-resolved (db_match True) for the gated arm, every bid for the naive arm.
    """
    rows = [r for r in rows if "error" not in r]
    bids = [r for r in rows if _row_label(r).resolved_claim]
    # The naive (believe-select) sampler accepts every resolved bid. Its accepted set is the
    # bids; the witnessed-resolved subset is the ones the witness CONFIRMS.
    witnessed_resolved = sum(1 for r in bids if r.get("db_match") is True)
    believe_poison = sum(1 for r in bids if _row_label(r).poison)
    believe_accepted = len(bids)
    believe_precision = (witnessed_resolved / believe_accepted) if believe_accepted else 0.0
    # The witness-gated (adjudicate-select) sampler accepts only the CONFIRMED bids.
    adjudicate_accepted = sum(1 for r in bids if _row_label(r).accept)
    adjudicate_poison = 0  # by construction — a refuted bid is never accepted
    adjudicate_precision = 1.0 if adjudicate_accepted else 0.0  # every accepted is witnessed
    return AcceptanceABResult(
        n_rows=len(rows),
        n_resolved_bids=len(bids),
        believe_accepted=believe_accepted,
        believe_poison=believe_poison,
        believe_precision=believe_precision,
        adjudicate_accepted=adjudicate_accepted,
        adjudicate_poison=adjudicate_poison,
        adjudicate_precision=adjudicate_precision,
        j_poison_purged=believe_poison,
        delta_precision=adjudicate_precision - believe_precision,
    )


# Both run dirs from docs/228 (gitignored — they sit at the repo root, written by the live
# driver's default out_dir). The slice run (Run A) + the natural sample (Run B), de-duped by
# (domain, task_id) with the sample winning ties (it is the fresh natural draw).
_LIVE_RUN_DIRS = ("live_results_writeadmit_sample", "live_results_writeadmit")


def load_live_rows(run_dirs: Iterable[str] = _LIVE_RUN_DIRS, *, root: str = ".") -> list[dict]:
    """Load + de-dupe the cached live rows from docs/228's run. Returns [] if absent.

    The dirs are gitignored (seed configs can carry the API key), so this is a best-effort
    read: a fresh checkout that never ran the paid loop gets [] and the CLI says so. Later
    dirs in `run_dirs` are loaded FIRST so an earlier dir (the natural sample) overrides on
    a (domain, task_id) collision.
    """
    bykey: dict[tuple[str, str], dict] = {}
    for d in reversed(list(run_dirs)):  # earlier dir wins -> load it last
        for f in sorted(glob.glob(str(Path(root) / d / "*.json"))):
            try:
                r = json.loads(Path(f).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if "domain" in r and "task_id" in r:
                bykey[(r["domain"], str(r["task_id"]))] = r
    return list(bykey.values())


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="E-TAU2-RLVR-ADMIT (docs/216 §5 / docs/230) — the lab-facing reward-labeler arm")
    ap.add_argument("--root", default=".", help="repo root holding the live_results_* dirs")
    ap.add_argument("--json", action="store_true", help="emit the A/B result as JSON")
    args = ap.parse_args(argv)

    rows = load_live_rows(root=args.root)
    if not rows:
        print(
            "E-TAU2-RLVR-ADMIT: no live rows found (looked for "
            f"{', '.join(_LIVE_RUN_DIRS)} under {args.root!r}).\n"
            "Run the paid loop first (docs/228): `python -m benchmark.agentprocessbench."
            "writeadmit.live_loop --live --sample 25` with GEMINI_API_KEY set.\n"
            "The labeler arithmetic + the non-distillability floor are unit-tested at $0 "
            "(test_rlvr_admit.py)."
        )
        return 0

    r = acceptance_ab(rows)
    if args.json:
        import dataclasses
        print(json.dumps(dataclasses.asdict(r), indent=2))
        return 0

    print("=== E-TAU2-RLVR-ADMIT — acceptance-precision A/B on the LIVE rows (docs/230) ===")
    print(f"  clean live rows folded:               {r.n_rows}")
    print(f"  confident 'resolved' write-bids:      {r.n_resolved_bids}  (the positive candidates)")
    print(f"  ── believe-select (naive self-judged sampler — witness-blind) ──")
    print(f"     accepted positives:                {r.believe_accepted}")
    print(f"     POISON banked (witness refutes):   {r.believe_poison}")
    print(f"     acceptance precision:              {r.believe_precision:.1%}")
    print(f"  ── adjudicate-select (witness-gated by db_match) ──")
    print(f"     accepted positives:                {r.adjudicate_accepted}")
    print(f"     poison banked:                     {r.adjudicate_poison}  (0 by construction)")
    print(f"     acceptance precision:              {r.adjudicate_precision:.1%}")
    print(f"\n  PAYOFF 1a  J = {r.j_poison_purged}  (poison positives the witness PURGED from the reward set)")
    print(f"  PAYOFF 1b  ΔP = +{r.delta_precision:.1%}  (acceptance-precision lift, witness-gated vs naive)")
    print("\n  Non-distillable: only the env DB-hash flips accept/reject; a forgeable")
    print("  AGENT_AUTHORED read-back can never (the believe_under_floor floor, test_rlvr_admit.py).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
