"""Deterministic synthetic-trajectory generator — emits the gate's EXACT recorded-trajectory shape.

For a given `TierProfile`, generates `n_runs` run-dicts in the shape the weak-model gate folds
(`tool_results` / `conversation_flow` / `model_response` / `overall_success`), with each failed run
carrying ONE of the five declared failure shapes drawn from the tier's `fail_mix`, and passed runs
clean (a small declared share carrying an incidental cue so the enrichment filter has a pass-side
signal). The generator NEVER calls a detector — it only shapes bytes; the real shipped detectors
run later in the gate fold, exactly as they would on real recordings.

Byte-fidelity is verified against the gate's own readers:
  * mint           — a mutating tool (`is_mutating_tool` True) whose id-arg value never appears in
                     any prior tool-result bytes nor the task text => `evaluate_tool_call(...).believe`
                     is False (confirmed: the docs/153 §5 `replay_recall` path).
  * loop           — 4 byte-identical `(tool, args, result)` steps => `classify_stream(...).state`
                     is non-ADVANCING (REPEATING at 3, STALLED at 5; confirmed).
  * narrating_stop — terminal `model_response` carries a dangling cue ("I still need to …" /
                     "Next, I should …") with 0 results after => `classify_stop(...).is_dangling`.
  * silent_stop /  — a clean terminal, no cue, no loop, no mint: structurally invisible to all
    planning        three detectors (the unreachable remainder; the only difference between the two
                     is call-count narrative, irrelevant to the detectors — both are unreachable).

Determinism: a single seeded `random.Random` drives shape selection and id minting, so two runs at
the same seed produce byte-identical corpora (the docs/145 / fleet_horizon reproducibility rule).
"""

from __future__ import annotations

import random

from benchmark.iot_tier.tiers import TierProfile, FAILURE_SHAPES

# A confirmed-firing dangling cue (probed against dos.dangling_intent.classify_stop).
_DANGLE_CUE = "I still need to close the open incident before finishing."
# A confirmed clean terminal (does NOT fire the dangling detector).
_CLEAN_DONE = "Done. The incident is resolved and verified."

_TASK_TEXT = "Close the open incident for the affected user and confirm resolution."
_SEEN_ID = "INC0001"          # an id the env-authored read result exposes (mint-safe)
_LOOP_TOOL = "read_incident"  # a READ tool (loops are re-reads, not mutations)


def _seen_read(idx: int) -> dict:
    """An env-authored read result that exposes `_SEEN_ID` (so a later supported mutate is clean)."""
    return {
        "tool_name": "list_incidents",
        "arguments": {"query": f"open#{idx}"},
        "result": {"rows": [{"sys_id": _SEEN_ID, "state": "open"}]},
    }


def _mint_run(rng: random.Random) -> dict:
    """A FAILED run: a mutating call whose id-arg was never read (the minted FK)."""
    minted = f"INC{rng.randint(700000, 999999)}"  # never appears in a prior result or the task
    return {
        "overall_success": False,
        "tool_results": [
            {"tool_name": "update_incident", "arguments": {"sys_id": minted, "state": "closed"},
             "result": {"ok": False, "error": "not found"}},
        ],
        "conversation_flow": [{"type": "ai_message", "content": "Closing the incident now."}],
        "model_response": "I closed the incident.",
    }


def _loop_run(rng: random.Random) -> dict:
    """A FAILED run: 4 byte-identical re-reads (non-ADVANCING => REPEATING/STALLED)."""
    step = {"tool_name": _LOOP_TOOL, "arguments": {"sys_id": _SEEN_ID},
            "result": {"sys_id": _SEEN_ID, "state": "open"}}
    return {
        "overall_success": False,
        "tool_results": [dict(step) for _ in range(4)],
        "conversation_flow": [{"type": "ai_message", "content": "Checking the incident state."}],
        "model_response": "The incident is still open.",
    }


def _narrating_stop_run(rng: random.Random) -> dict:
    """A FAILED run: ends narrating an open obligation with nothing after (the dangle)."""
    return {
        "overall_success": False,
        "tool_results": [_seen_read(0)],
        "conversation_flow": [{"type": "ai_message", "content": "Looked up the incident."}],
        "model_response": _DANGLE_CUE,
    }


def _silent_or_planning_run(rng: random.Random, shape: str) -> dict:
    """A FAILED run invisible to all three detectors: a clean stop, no cue/loop/mint.

    `silent_stop` stops early after a couple of reads; `planning` narrates a clean (non-cue)
    plan and stops. Neither fires a detector — both are the unreachable remainder (docs/153 §4).
    """
    n_reads = 1 if shape == "silent_stop" else 2
    flow = [{"type": "ai_message", "content": "Reviewing the situation."}]
    if shape == "planning":
        flow.append({"type": "ai_message", "content": "The plan is to review, then act."})
    return {
        "overall_success": False,
        "tool_results": [_seen_read(i) for i in range(n_reads)],
        "conversation_flow": flow,
        "model_response": _CLEAN_DONE,  # a clean terminal — no dangling cue
    }


def _pass_run(rng: random.Random, incidental: dict) -> dict:
    """A PASSED run. Clean by default; a declared share carries an incidental mint / dangling cue
    so the enrichment filter has a pass-side signal (this is what reproduces MINT-as-noise)."""
    # supported mutate: the id WAS read first, so it is not a mint.
    trs = [_seen_read(0),
           {"tool_name": "update_incident", "arguments": {"sys_id": _SEEN_ID, "state": "closed"},
            "result": {"ok": True}}]
    model_response = _CLEAN_DONE
    if rng.random() < incidental.get("mint", 0.0):
        # an incidental UNSUPPORTED-looking mutate on a passed run (the residual false-flag MINT)
        trs.append({"tool_name": "set_priority",
                    "arguments": {"ref_id": f"REQ{rng.randint(700000, 999999)}", "priority": "2"},
                    "result": {"ok": True}})
    if rng.random() < incidental.get("narrating_stop", 0.0):
        model_response = _DANGLE_CUE  # an incidental dangling cue on a passed run
    return {
        "overall_success": True,
        "tool_results": trs,
        "conversation_flow": [{"type": "ai_message", "content": "Resolving the incident."}],
        "model_response": model_response,
    }


_FAIL_BUILDERS = {
    "mint": _mint_run,
    "loop": _loop_run,
    "narrating_stop": _narrating_stop_run,
}


def _draw_shape(rng: random.Random, fail_mix: dict) -> str:
    """Draw one failure shape from the conditional distribution (sums to 1.0)."""
    r = rng.random()
    cum = 0.0
    for shape in FAILURE_SHAPES:
        cum += fail_mix.get(shape, 0.0)
        if r < cum:
            return shape
    return FAILURE_SHAPES[-1]  # float-rounding guard


def generate_corpus(tier: TierProfile, n_runs: int = 400, seed: int = 1729) -> dict:
    """Generate one tier's synthetic corpus in the gate's exact JSON shape.

    Deterministic given (`tier`, `n_runs`, `seed`). Returns
    `{benchmark_config: {model, user_prompt}, runs: [...]}` — the same top-level shape the gate
    reads from a recordings file, so `gate_fraction(corpus['runs'], corpus task_text)` folds it.
    """
    rng = random.Random(seed)
    runs = []
    for _ in range(n_runs):
        if rng.random() < tier.per_task_fail_rate:
            shape = _draw_shape(rng, tier.fail_mix)
            if shape in _FAIL_BUILDERS:
                runs.append(_FAIL_BUILDERS[shape](rng))
            else:  # silent_stop | planning — the unreachable remainder
                runs.append(_silent_or_planning_run(rng, shape))
        else:
            runs.append(_pass_run(rng, tier.pass_incidental))
    return {
        "benchmark_config": {
            "model": f"iot_tier::{tier.name}::{tier.model_class}",
            "user_prompt": _TASK_TEXT,
        },
        "runs": runs,
    }


# The task text the mint fold uses (exposed so the harness folds with the identical corpus text).
TASK_TEXT = _TASK_TEXT
