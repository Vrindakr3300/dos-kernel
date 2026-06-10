"""The weak-model Stage-1 gate (docs/153 §5): is a model's failure mix DOS-recoverable?

The honest unit of progress for "can DOS lift a weak model?". Given a recordings folder for ANY
model, it folds the three shipped byte-clean detectors over each FAILED run and reports the
**deduped per-task execution-substrate failure fraction** — the share of failures DOS could
advisory-flag (minted id / byte-identical loop / narrating premature stop) — against the
pre-registered threshold (docs/153 §3): >=15% => the failure mix is DOS-shaped, run the live A/B;
<15% => the detectors are blind to this model's dominant failure (silent-stop / planning), and "DOS
lifts this model" is FALSIFIED at ~$50, docs/149 repeating one rung down.

Pure replay (the `failure_distribution.py` / `replay_dangling.py` sibling): no model calls, no DB,
no Docker. Model-agnostic by construction — it reads only the recorded trajectory shape, so the SAME
gate runs on gemini (where it should report ~0, the known null — the instrument's self-test), on
DeepSeek, on Qwen. It NEVER assumes a magnitude; it MEASURES the recoverable fraction and checks the
threshold. This is the docs/145 discipline applied BEFORE the claim: measure the rate the whole
thesis rests on, do not simulate a guess.

Three detectors, deduped per task (so a task failing two ways counts once toward the fraction):
  * MINT       — `arg_provenance.classify_call` flags a mutating call whose id args never appeared
                 in prior env-authored results (the model invented an FK). Recoverable: nudge a read.
  * LOOP       — `tool_stream.classify_stream` flags a byte-identical (tool,args,result) run
                 (REPEATING/STALLED). Recoverable: re-surface the repeated value.
  * DANGLE     — `dangling_intent.classify_stop` flags a terminal turn that admits an open
                 obligation with no tool result after (the narrating premature stop). Recoverable:
                 re-surface the agent's own sentence.
The UNREACHABLE remainder (silent stop / planning) is reported too — it is the honest denominator
that docs/149 found dominates on gemini.
"""

from __future__ import annotations

import glob
import json
import sys

from dos.dangling_intent import StopEvidence, classify_stop
from dos.tool_stream import ToolStream, classify_stream

# Reuse the VALIDATED boundary readers + folds the other replay scripts already proved out — never
# re-roll them (the docs/153 "verify reuse before building" discipline). `evaluate_tool_call` +
# `is_mutating_tool` are the SAME write-verb-gated, task-text-corpus path `replay_recall.py` uses
# to get its measured 0-false-flag precision; a hand-rolled fold that gates reads or drops the task
# text over-fires (the bug the gemini self-test caught at 47% before this fix).
from benchmark.enterpriseops.replay_dangling import (
    _runs, _terminal_text, _results_after_terminal,
)
from benchmark.enterpriseops.replay_stall import stream_of
from benchmark.enterpriseops.dos_react import is_mutating_tool, evaluate_tool_call
from benchmark.enterpriseops.replay_recall import _is_blocked_result


# ---------------------------------------------------------------------------
# Per-run detector folds (each returns True iff that detector would fire).
# ---------------------------------------------------------------------------
def _fires_mint(run: dict, task_text: str) -> bool:
    """True iff arg_provenance would flag a minted id on a real MUTATING call. Uses the EXACT
    `replay_recall` path — `is_mutating_tool` (so reads are never gated) + `evaluate_tool_call`
    (which folds the task-text corpus, so a task-named id is not false-flagged) — the only fold
    with a measured 0-false-flag precision. A hand-rolled version over-fires; do not re-roll it."""
    prior = []
    for tr in run.get("tool_results", []) or []:
        if _is_blocked_result(tr):
            continue
        tn = tr.get("tool_name")
        args = tr.get("arguments", {}) or {}
        if is_mutating_tool(tn):
            v = evaluate_tool_call(tn, args, task_text, prior)
            if not v.believe:
                return True
        prior.append(tr)
    return False


def _fires_loop(run: dict) -> bool:
    """True iff tool_stream would fire REPEATING/STALLED at any prefix of the run's stream."""
    stream = stream_of(run)
    steps = stream.steps
    from dos.tool_stream import StreamState
    for i in range(1, len(steps) + 1):
        v = classify_stream(ToolStream(steps=steps[:i]))
        if v.state is not StreamState.ADVANCING:
            return True
    return False


def _fires_dangle(run: dict) -> bool:
    """True iff dangling_intent would fire on the terminal turn (narrating premature stop)."""
    ev = StopEvidence(
        final_turn_text=_terminal_text(run),
        results_after_turn=_results_after_terminal(run),
    )
    return classify_stop(ev).is_dangling


THRESHOLD = 0.15  # docs/153 §3 pre-registered: >= => DOS-shaped, run the A/B; < => falsified.


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "benchmark/enterpriseops/live_results"
    files = glob.glob(f"{folder}/**/*.json", recursive=True)

    n_fail = n_pass = 0
    # per-detector fire counts on failed vs passed runs — the enrichment test that separates
    # SIGNAL (fires more on failures) from NOISE (fires equally/more on passes = false positives).
    ff = {"mint": 0, "loop": 0, "dangle": 0}   # fires on FAILED
    pf = {"mint": 0, "loop": 0, "dangle": 0}   # fires on PASSED
    fire_any_enriched = 0  # deduped per failed run, counting ONLY detectors enriched on failures
    model = "?"
    rows = []  # (failed?, {detector: fired})

    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        top = d if isinstance(d, dict) else {}
        bc = top.get("benchmark_config", {}) or {}
        m = bc.get("model") or bc.get("llm") or bc.get("model_name")
        if m:
            model = str(m)
        task_text = str(bc.get("user_prompt", "") or "")
        for r in _runs(d):
            s = r.get("overall_success")
            if s is None:
                continue
            fired = {
                "mint": _fires_mint(r, task_text),
                "loop": _fires_loop(r),
                "dangle": _fires_dangle(r),
            }
            if s is False:
                n_fail += 1
                for k, v in fired.items():
                    ff[k] += 1 if v else 0
            else:
                n_pass += 1
                for k, v in fired.items():
                    pf[k] += 1 if v else 0
            rows.append((s is False, fired))

    def rate(c, n):
        return (c / n) if n else 0.0

    # A detector is SIGNAL iff its failed-run fire-rate exceeds its passed-run fire-rate (it is
    # enriched on the failures it claims to recover). A detector that fires equally on passes is
    # NOISE (false positives) and must NOT count toward the recoverable fraction — the honesty
    # fix the gemini self-test forced (MINT fired 24% on passes vs 17% on failures = pure noise).
    enriched = {k: rate(ff[k], n_fail) > rate(pf[k], n_pass) for k in ff}

    # deduped recoverable = failed runs fired on by AT LEAST ONE enriched detector
    fire_any_enriched = sum(
        1 for is_fail, fired in rows
        if is_fail and any(fired[k] and enriched[k] for k in fired)
    )
    frac = rate(fire_any_enriched, n_fail)
    unreachable = n_fail - fire_any_enriched

    print("=" * 80)
    print(f"  WEAK-MODEL GATE (docs/153 §5) — model: {model}")
    print("  the deduped execution-substrate failure fraction DOS could advisory-flag")
    print("  (pure replay of the three shipped detectors; no model calls / DB / Docker)")
    print("=" * 80)
    print(f"  FAILED runs: {n_fail}   PASSED runs: {n_pass}")
    print("  detector       fail-rate  pass-rate  enriched? (signal vs noise)")
    for k, name in (("mint", "MINT  "), ("loop", "LOOP  "), ("dangle", "DANGLE")):
        fr, pr = 100 * rate(ff[k], n_fail), 100 * rate(pf[k], n_pass)
        tag = "SIGNAL" if enriched[k] else "NOISE (excluded)"
        print(f"  {name}         {fr:5.0f}%     {pr:5.0f}%     {tag}")
    print("-" * 80)
    print(f"  deduped DOS-recoverable (enriched detectors only): {fire_any_enriched}  "
          f"({100*frac:.0f}% of failures)")
    print(f"  UNREACHABLE (silent-stop / planning / noise-only):  {unreachable}  ({100*(1-frac):.0f}%)")
    print("-" * 80)
    print(f"  pre-registered threshold: {100*THRESHOLD:.0f}%")
    if n_fail == 0:
        print("  NO failed runs in this corpus — nothing to gate.")
    elif frac >= THRESHOLD:
        print(f"  VERDICT: {100*frac:.0f}% >= {100*THRESHOLD:.0f}% -> DOS-SHAPED failure mix. Run the live")
        print("  WARN-only A/B (Stage 2) -- the execution-substrate fraction is non-trivial.")
    else:
        print(f"  VERDICT: {100*frac:.0f}% < {100*THRESHOLD:.0f}% -> FALSIFIED for this model. The enriched")
        print("  detectors are blind to its dominant failure (silent-stop / planning). 'DOS lifts")
        print("  this model' dies here -- docs/149 one rung down. The honest cheap kill.")
    print("=" * 80)


if __name__ == "__main__":
    main()
