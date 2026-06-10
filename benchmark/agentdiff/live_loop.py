"""The believe-vs-adjudicate A/B fold + the gated live driver, for Agent-Diff (docs/216→228).

TWO LAYERS:
  * `frozen_ab(...)`  — $0, no model. Runs the believe/adjudicate A/B over the bench tasks,
    using a SYNTHETIC over-claim run (an empty observed diff) judged by the REAL Agent-Diff
    assertion engine as the witness. This proves the J arithmetic and the gate mechanics
    before any spend — and unlike the tau2 stand-in, the witness here is the PRODUCTION
    engine, only the diff is synthesized.
  * `run_writeadmit(...)` — PAID, gated behind `GEMINI_API_KEY` (and the Agent-Diff backend on
    `localhost:8000`). Drives agent A live via the SDK (init_env → start_run → agent acts →
    evaluate_run), reads the env witness (`evaluate_run().passed` + the structured diff),
    seeds peer B from whatever the gate published, and counts J off ground truth. $0 until a
    key is present (mirrors the tau2 writeadmit DOS_LIVE gating).

THE PAYOFF J (the docs/179 FLIP, not a re-projected rate):
  J = count of trajectories where (a) A made a confident write-claim, (b) the env witness
  says the asserted change did NOT hold (passed == False), and (c) the adjudicate gate
  BLOCKED publication so a peer B did NOT inherit the phantom write. The believe arm inherits
  all of them; J is the difference in what B inherited. A frozen replay cannot produce a
  CAUSAL ΔB (there is no second run); it proves the gate BLOCKS the right rows. The live loop
  (peer B actually re-running) is what flips an inheritance — that is `run_writeadmit`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .dataset import load_tasks
from .gate import admit, AdmitDecision
from .peer_b import AHandoff, handoff_text, BELIEVE, ADJUDICATE, ARMS


@dataclass(frozen=True)
class ABResult:
    arm: str                  # "believe" | "adjudicate"
    n_tasks: int
    n_confident_write: int    # how many A-claims were confident writes
    n_overclaim: int          # confident-write × env-refuted (passed==False)
    n_blocked: int            # adjudicate-arm BLOCKs (0 in believe arm by construction)
    inherited_phantom: int    # phantom writes a peer WOULD inherit under this arm


# A confident-write self-report A emits on a write task. Deterministic (no model): the frozen
# layer's A *always* claims success — that is the over-claim being modeled. The witness (the
# real assertion engine over an empty diff) is what refutes it. Domain-generic so it fires the
# Agent-Diff claim detector for any service.
_SYNTHETIC_DONE_CLAIM = (
    "Done. I have completed the requested changes and updated the records as asked; "
    "the task has been successfully finished."
)


def frozen_ab(arm: str = "adjudicate", split: str = "test") -> ABResult:
    """Run one A/B arm over the bench tasks. $0, deterministic, REAL assertion engine.

    Models the canonical over-claim: agent A claims "done" (a confident write) on every write
    task, but the observed diff is EMPTY (nothing landed). The witness is the production
    `AssertionEngine.evaluate(empty_diff)['passed']` — False for every write task — so:

    `believe`   = the gate is a pass-through: A's "done" is always published, so a peer B
                  inherits every confident-write phantom (today's fleet behavior).
    `adjudicate`= the gate runs `witness_effect`; a REFUTED confident write is BLOCKED before
                  publish, so B inherits the env-verified correction instead of the phantom.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {ARMS}")
    from .frozen_witness import simulate_overclaim  # lazy: needs the clone

    tasks = [t for t in load_tasks(split) if t.is_write_task]
    n_conf = n_over = n_blocked = inherited = 0
    for t in tasks:
        witness = simulate_overclaim(t)  # the real env verdict on the empty over-claim diff
        d: AdmitDecision = admit(_SYNTHETIC_DONE_CLAIM, passed=witness.passed,
                                 failures=witness.failures, score=witness.score)
        if d.confident_write:
            n_conf += 1
        is_overclaim = d.confident_write and (witness.passed is False)
        if is_overclaim:
            n_over += 1

        a = AHandoff(service=t.service, test_id=t.test_id, claim_text=_SYNTHETIC_DONE_CLAIM,
                     confident_write=d.confident_write, admit=d.admit, passed=witness.passed)
        if arm == ADJUDICATE:
            if not d.admit:
                n_blocked += 1
            # under adjudicate, a blocked row is corrected -> B does NOT inherit the phantom.
            if is_overclaim and d.admit:
                inherited += 1  # an over-claim the gate FAILED to block (should be 0)
        else:  # believe: every confident "done" is published -> B inherits every phantom.
            if is_overclaim:
                inherited += 1

    return ABResult(arm=arm, n_tasks=len(tasks), n_confident_write=n_conf,
                    n_overclaim=n_over, n_blocked=n_blocked, inherited_phantom=inherited)


def print_frozen_summary(split: str = "test") -> None:
    """Print the J arithmetic for both arms — the $0 proof the gate blocks the right rows."""
    believe = frozen_ab(BELIEVE, split)
    adjud = frozen_ab(ADJUDICATE, split)
    print(f"[agentdiff writeadmit — frozen A/B over split={split!r}]")
    print(f"  write tasks               : {adjud.n_tasks}")
    print(f"  confident-write over-claims: {adjud.n_overclaim}")
    print(f"  believe   — inherited phantom: {believe.inherited_phantom}  (B starts from a false belief)")
    print(f"  adjudicate — blocked         : {adjud.n_blocked}  inherited phantom: {adjud.inherited_phantom}")
    print(f"  J (over-claims the gate blocked before a peer inherited them): {adjud.n_blocked}")
    print("  NB: a CAUSAL ΔB needs the live loop (peer B re-running) — run_writeadmit with a key.")


def run_writeadmit(
    *,
    model: str = "gemini-2.5-flash",
    split: str = "test",
    sample: Optional[int] = 20,
    services: Optional[tuple[str, ...]] = None,
    out_dir: str = "benchmark/agentdiff/live_results",
    budget_tokens: Optional[int] = None,
    max_iterations: int = 30,
) -> int:
    """The PAID live driver entry point — runs the causal ΔB measurement.

    Drives agent A live via the SDK over the selected write tasks, gates each on the env
    `AssertionEngine` witness, then on the over-claim slice re-runs a downstream peer B under
    both arms and reports ΔB (the docs/229 causal payoff). $0 + opt-in message when
    GEMINI_API_KEY is absent (so the test suite stays free). Returns ΔB (in tasks).
    """
    if not os.environ.get("GEMINI_API_KEY"):
        print("run_writeadmit: set GEMINI_API_KEY (+ Agent-Diff backend on :8000) to run the "
              "live believe-vs-adjudicate ΔB. Frozen $0 proof: print_frozen_summary().")
        return 0
    from .delta_b import run_delta_b  # lazy: needs the SDK + backend

    result = run_delta_b(model=model, split=split, sample=sample, services=services,
                         out_dir=out_dir, budget_tokens=budget_tokens, max_iterations=max_iterations)
    print(f"[agentdiff writeadmit — live ΔB] model={result.model} "
          f"write_tasks={result.n_tasks} overclaim_slice={result.n_overclaim} "
          f"B_believe={result.b_success_believe} B_adjudicate={result.b_success_adjudicate} "
          f"ΔB={result.delta_b}")
    if result.notes:
        print(f"  note: {result.notes}")
    return result.delta_b


if __name__ == "__main__":
    import sys
    raise SystemExit(run_writeadmit() if "--live" in sys.argv else (print_frozen_summary() or 0))
