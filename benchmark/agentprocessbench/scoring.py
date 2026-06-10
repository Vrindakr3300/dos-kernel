"""SINGLE SOURCE OF TRUTH for the AgentProcessBench boundary + error-slice-floor claims (docs/174).

The docs/174 reframe (the K2 probe FIRED — byte-clean parity with the LLM judge is impossible
because the gold rates EFFECTIVENESS not errors): this corpus is a BOUNDARY instrument + a
deterministic FLOOR, NOT a judge rival. So the SSOT computes, per config:

  1. THE BOUNDARY (the headline): what fraction of gold FIRST-divergences are ERROR-CAUSED (the env
     authored a non-success status at/near the gold step) vs SILENT (a `status:success` step the
     agent got wrong by logic). The silent majority is exactly where the deterministic ORACLE rung
     ends and the JUDGE/provenance rung must take over. This is the paper-worthy number.
  2. THE ERROR-SLICE FLOOR: restricted to the error-caused trajectories, how well does the $0
     byte-clean `first_env_error` localizer hit the gold first-divergence step (FirstErrAcc-on-slice)?
     This is the deterministic floor a forgeable LLM judge must beat, WITH attribution the pass/fail
     gold does not give.
  3. THE FALSE-ALARM analogue: on trajectories the gold marks fully clean (final_label != -1, no -1
     step), how often does the detector fire anyway?

    python -m benchmark.agentprocessbench.scoring            # print the claims
    python -m benchmark.agentprocessbench.scoring --check     # assert invariants (exit 1 on drift)
    python -m benchmark.agentprocessbench.scoring --emit      # write _results/agentprocessbench_claims.md

THE HEADLINE (verified on the 1,000-trajectory corpus):
  * Only ~11% (bfcl) / ~27% (tau2) of gold first-divergences are error-caused — so ~73-89% of agent
    divergences leave NO error byte. The byte-clean FirstErrAcc ceiling is that error-caused fraction,
    far below the LLM-judge's published 65.8%. The boundary IS the result.
  * On the error-caused slice, the $0 `first_env_error` localizer hits the gold first-divergence step
    deterministically at near-zero false-alarm — a floor, with attribution, at zero model cost.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .dataset import Trajectory, load, CONFIGS, STRUCTURED_CONFIGS
from .detector import LOCALIZERS

_HERE = Path(__file__).resolve().parent
_LEDGER = _HERE / "_results" / "agentprocessbench_claims.md"

# The LLM-judge FirstErrAcc the paper reports for its best model (Gemini-3-Flash-Thinking) — our
# contrast anchor. The byte-clean detector is a deterministic FLOOR under this, not a rival to it.
JUDGE_FIRSTERRACC = 0.658

# A gold -1 step is "error-caused" iff the env authored a non-success status within this many message
# indices of the gold first-divergence step (the labeled assistant step, or its immediate neighbor —
# the result lands one message later, and the human may label the assistant turn or the turn it
# reacts to). Window of 1 = {gold-1, gold, gold+1}.
_ERROR_WINDOW = 1


def _error_caused(traj: Trajectory) -> bool:
    """True iff the gold FIRST-divergence step coincides (within _ERROR_WINDOW) with an env error —
    i.e. the divergence is one a byte-clean detector could even in principle catch. PURE."""
    gold = traj.first_negative_step
    if gold is None:
        return False
    status = traj.step_tool_status()
    return any(
        status.get(j) == "error"
        for j in range(gold - _ERROR_WINDOW, gold + _ERROR_WINDOW + 1)
    )


def _hit(pred: Optional[int], gold: Optional[int], window: int = _ERROR_WINDOW) -> bool:
    """A localizer prediction hits the gold first-divergence step within `window` message indices."""
    return pred is not None and gold is not None and abs(pred - gold) <= window


@dataclass(frozen=True)
class ConfigScore:
    config: str
    total: int
    localizable: int          # trajectories with a gold first-divergence (a -1 step)
    error_caused: int         # of localizable, how many are error-caused (the BOUNDARY numerator)
    # The error-slice floor for `first_env_error` (the plain status-channel detector):
    slice_fired: int          # of error-caused, how many the detector fired on
    slice_hit: int            # of error-caused, how many the detector localized within window
    # False-alarm: on fully-clean trajectories (no -1 step), how often each detector fires.
    clean_total: int
    clean_fired: int          # first_env_error
    # The recovery-gated variant — corpus-dependent: it cuts false-alarm but on bfcl over-suppresses
    # the (errored-then-nominally-recovered-yet-still-wrong) divergences (the docs/159 false-
    # reassurance phenomenon). Reported so the trade-off is visible, never hidden.
    gated_slice_hit: int
    gated_clean_fired: int

    @property
    def error_caused_rate(self) -> float:
        return self.error_caused / self.localizable if self.localizable else 0.0

    @property
    def slice_firsterracc(self) -> float:
        """FirstErrAcc restricted to the error-caused slice (the deterministic floor)."""
        return self.slice_hit / self.error_caused if self.error_caused else 0.0

    @property
    def false_alarm(self) -> float:
        return self.clean_fired / self.clean_total if self.clean_total else 0.0

    @property
    def gated_slice_firsterracc(self) -> float:
        return self.gated_slice_hit / self.error_caused if self.error_caused else 0.0

    @property
    def gated_false_alarm(self) -> float:
        return self.gated_clean_fired / self.clean_total if self.clean_total else 0.0

    @property
    def corpus_firsterracc(self) -> float:
        """FirstErrAcc over ALL localizable trajectories — the byte-clean CEILING (bounded above by
        error_caused_rate, since a silent divergence can never be localized from env bytes)."""
        return self.slice_hit / self.localizable if self.localizable else 0.0


def _score_config(cfg: str, trajs: list[Trajectory]) -> ConfigScore:
    sub = [t for t in trajs if t.config == cfg]
    localizable = [t for t in sub if t.first_negative_step is not None]
    error_caused = [t for t in localizable if _error_caused(t)]
    fired = hit = gated_hit = 0
    fn = LOCALIZERS["first_env_error"]
    gated = LOCALIZERS["first_unrecovered_env_error"]
    for t in error_caused:
        gold = t.first_negative_step
        pred = fn(t)
        if pred is not None:
            fired += 1
            if _hit(pred, gold):
                hit += 1
        if _hit(gated(t), gold):
            gated_hit += 1
    clean = [t for t in sub if not t.negative_steps and t.final_label != -1]
    clean_fired = sum(1 for t in clean if fn(t) is not None)
    gated_clean_fired = sum(1 for t in clean if gated(t) is not None)
    return ConfigScore(
        config=cfg,
        total=len(sub),
        localizable=len(localizable),
        error_caused=len(error_caused),
        slice_fired=fired,
        slice_hit=hit,
        clean_total=len(clean),
        clean_fired=clean_fired,
        gated_slice_hit=gated_hit,
        gated_clean_fired=gated_clean_fired,
    )


def compute(trajs: Optional[list[Trajectory]] = None) -> dict[str, ConfigScore]:
    """Score every config. The SSOT entry point."""
    trajs = trajs if trajs is not None else list(load())
    return {cfg: _score_config(cfg, trajs) for cfg in CONFIGS}


def _format(scores: dict[str, ConfigScore]) -> str:
    lines = [
        "# AgentProcessBench boundary + error-slice-floor claims (docs/174, SSOT)",
        "",
        "Corpus: AgentProcessBench (RUCBM, arXiv 2603.14465, MIT), scored offline, $0.",
        f"Contrast anchor: LLM-judge best FirstErrAcc = {JUDGE_FIRSTERRACC:.1%} (Gemini-3-Flash-Thinking).",
        "",
        "The gold rates task EFFECTIVENESS, not tool errors. The byte-clean detector reads only the",
        "env-authored tool-status channel, so its FirstErrAcc ceiling is the ERROR-CAUSED fraction.",
        "This is a BOUNDARY + a deterministic FLOOR, NOT a judge rival.",
        "",
    ]
    for cfg in CONFIGS:
        s = scores[cfg]
        tag = " (structured — the method's home)" if cfg in STRUCTURED_CONFIGS else " (free-text — degrades)"
        lines += [
            f"## {cfg}{tag}",
            f"- trajectories: {s.total} ({s.localizable} with a gold first-divergence)",
            f"- BOUNDARY — error-caused first-divergences: {s.error_caused}/{s.localizable} "
            f"= {s.error_caused_rate:.1%} (so {1 - s.error_caused_rate:.1%} are SILENT — no error byte, "
            f"out of byte-clean reach)",
            f"- ERROR-SLICE FLOOR — first_env_error FirstErrAcc on the error-caused slice: "
            f"{s.slice_hit}/{s.error_caused} = {s.slice_firsterracc:.1%} "
            f"(false-alarm {s.clean_fired}/{s.clean_total} = {s.false_alarm:.1%})",
            f"- recovery-gated variant (first_unrecovered_env_error): slice FirstErrAcc "
            f"{s.gated_slice_hit}/{s.error_caused} = {s.gated_slice_firsterracc:.1%}, "
            f"false-alarm {s.gated_clean_fired}/{s.clean_total} = {s.gated_false_alarm:.1%} "
            f"— cuts false-alarm but on bfcl over-suppresses errored-then-still-wrong divergences",
            f"- byte-clean CEILING (FirstErrAcc over ALL localizable): "
            f"{s.slice_hit}/{s.localizable} = {s.corpus_firsterracc:.1%} (vs judge {JUDGE_FIRSTERRACC:.1%})",
            "",
        ]
    # The cross-config headline.
    struct = [scores[c] for c in STRUCTURED_CONFIGS]
    tot_loc = sum(s.localizable for s in struct)
    tot_err = sum(s.error_caused for s in struct)
    lines += [
        "## Headline (structured subsets bfcl+tau2)",
        f"- {tot_err}/{tot_loc} = {tot_err / tot_loc:.1%} of gold first-divergences are error-caused; "
        f"the rest are SILENT semantic failures.",
        f"- That silent majority is the measured BOUNDARY where the deterministic ORACLE rung ends and "
        f"the JUDGE/provenance rung must take over (docs/162 'errored != wrong', generalized).",
        "",
    ]
    return "\n".join(lines)


# Invariants the test + --check assert. Loose enough to survive a corpus refresh, tight enough to
# catch a logic regression (e.g. the step_labels str/int coercion, or the status-channel alignment).
def _invariants(scores: dict[str, ConfigScore]) -> list[str]:
    failures = []
    for cfg in CONFIGS:
        if scores[cfg].total != 250:
            failures.append(f"{cfg}: expected 250 trajectories, got {scores[cfg].total}")

    # The BOUNDARY headline — the load-bearing measured finding (docs/174 K2). bfcl ~11%, tau2 ~27%.
    bfcl = scores["bfcl"]
    tau2 = scores["tau2"]
    if not (0.05 <= bfcl.error_caused_rate <= 0.20):
        failures.append(f"bfcl error_caused_rate {bfcl.error_caused_rate:.3f} outside [0.05, 0.20]")
    if not (0.18 <= tau2.error_caused_rate <= 0.38):
        failures.append(f"tau2 error_caused_rate {tau2.error_caused_rate:.3f} outside [0.18, 0.38]")

    # The boundary claim: the byte-clean CEILING must sit BELOW the judge (the whole point — it is a
    # floor, not a rival). If the ceiling ever exceeds the judge, the boundary framing is wrong.
    for cfg in STRUCTURED_CONFIGS:
        if scores[cfg].corpus_firsterracc >= JUDGE_FIRSTERRACC:
            failures.append(
                f"{cfg}: byte-clean ceiling {scores[cfg].corpus_firsterracc:.3f} >= judge "
                f"{JUDGE_FIRSTERRACC} — the boundary framing (floor not rival) would be violated"
            )

    # The FLOOR must be real: on the error-caused slice the detector should localize a meaningful
    # fraction (else it is not even a floor). Loose lower bound.
    if bfcl.slice_firsterracc < 0.30:
        failures.append(f"bfcl slice FirstErrAcc {bfcl.slice_firsterracc:.3f} below 0.30 (floor too weak)")
    return failures


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AgentProcessBench boundary/floor SSOT")
    ap.add_argument("--check", action="store_true", help="assert invariants; exit 1 on drift")
    ap.add_argument("--emit", action="store_true", help="write the claims ledger")
    args = ap.parse_args(argv)

    scores = compute()
    text = _format(scores)

    if args.check:
        fails = _invariants(scores)
        if fails:
            print("DRIFT:", *fails, sep="\n  ", file=sys.stderr)
            return 1
        print("OK: AgentProcessBench claims hold.")
        return 0

    if args.emit:
        _LEDGER.parent.mkdir(parents=True, exist_ok=True)
        _LEDGER.write_text(text, encoding="utf-8")
        print(f"wrote {_LEDGER}")
        return 0

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
