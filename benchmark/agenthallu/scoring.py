"""SINGLE SOURCE OF TRUTH for the AgentHallu Tool-Use step-localization claims (docs/166 §4).

Every headline number the docs/166 note asserts about AgentHallu is computed HERE, from the cloned
CC-BY-4.0 corpus, with zero LLM / network calls. A test asserts `compute()`; `--emit` writes the
claims ledger; `--check` fails CI on drift. Because the prose, the test, and the ledger all consume
one function, the claim can NOT drift from the data.

    python -m benchmark.agenthallu.scoring            # print the claims
    python -m benchmark.agenthallu.scoring --check     # assert invariants (exit 1 on drift)
    python -m benchmark.agenthallu.scoring --emit      # write _results/agenthallu_claims.md

THE HEADLINE (verified on the 693-trajectory corpus, 103 Tool-Use):

  * `first_errored_response`, a $0 byte-clean step-localizer over ENV-authored tool responses,
    EXACT-hits the gold first-divergence step on 34.0% of Tool-Use trajectories -- ~2.9x the
    best frontier model's 11.6% on the same (hardest) category.
  * HONEST COST of the broad floor: it fires on 35.2% of CLEAN trajectories too (88/250 -- an
    errored response is a signal, not the hallucination). So its precision-when-fired is ~48.6%,
    and the false-alarm rate is reported as a FLOOR, not hidden.

THE FALSE-ALARM CUT (docs/166 §4b-ii, measured): two structural localizers ride the same env bytes
and cut that floor WITHOUT a satisfaction predicate:

  * `first_unrecovered_error` (RECOMMENDED) -- structural error-CHANNEL detection (a {"error": ...}
    key or a raised-error prose prefix, never an error WORD in legitimate data) + a byte-observable
    unrecovered-error gate (did a tool at the errored step return a clean env response later?). It
    cuts the false-alarm floor from 35.2% to 1.2% (3/250) and lifts precision to 83.8%, at the cost
    of 4 exact-hits (34.0% -> 30.1%, still ~2.6x the SOTA 11.6%). The recommended operating point for
    an advisory WARN surface (docs/144): a 35% false-resurface rate trains operators to ignore the
    signal; 1.2% stays credible.
  * `first_structural_error` (runner-up) -- the channel fix alone, keeping ~all recall (33.0%) at
    11.2% false-alarm (a ~3x cut for one exact-hit).

NOT shipped (measured non-additive on this BFCL slice -- the corpus-not-catch discipline): wiring
`arg_provenance` (0/36 on its Incorrect-Args target, +14 false-alarms if OR-merged) or `tool_stream`
(+1 hit at +12 false-alarms) as localizers. Their target failure modes (minted FK references;
consecutive looping) are essentially absent from these short, truncated, free-text trajectories;
their honest demo homes are EnterpriseOps-Gym and a long-horizon looping corpus. Corroboration is
also measured-false as a recall-preserving cut: the byte-clean detectors are complementary (only
6/35 baseline hits are double-witnessed), so requiring a second witness collapses recall to 6 hits.
The pitch stays "additive deterministic precision on the SOTA-hardest slice," NOT "beats overall."

The 11.6% comparison point is the paper's reported Tool-Use category average for the best model
(Gemini-2.5-Pro). We compare ONLY on Tool-Use because that is the byte-clean slice; the other four
categories are reasoning-faithfulness, outside the kernel mandate (we never distrust judgment).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .dataset import Trajectory, load
from .detector import LOCALIZERS

_HERE = Path(__file__).resolve().parent
_LEDGER = _HERE / "_results" / "agenthallu_claims.md"

# The paper's best-model accuracy on the Tool-Use category (Gemini-2.5-Pro), our comparison anchor.
SOTA_TOOLUSE = 0.116


@dataclass(frozen=True)
class LocalizerScore:
    name: str
    tool_use_total: int
    fired: int            # fired on a Tool-Use trajectory
    exact: int            # predicted step == gold step
    within1: int          # |predicted - gold| <= 1
    clean_total: int
    clean_fired: int      # FALSE ALARM: fired on a clean (non-hallucinated) trajectory

    @property
    def exact_rate(self) -> float:
        return self.exact / self.tool_use_total if self.tool_use_total else 0.0

    @property
    def within1_rate(self) -> float:
        return self.within1 / self.tool_use_total if self.tool_use_total else 0.0

    @property
    def precision(self) -> float:
        return self.exact / self.fired if self.fired else 0.0

    @property
    def false_alarm(self) -> float:
        return self.clean_fired / self.clean_total if self.clean_total else 0.0

    @property
    def lift_vs_sota(self) -> float:
        return self.exact_rate - SOTA_TOOLUSE


def _score_one(name: str, trajs: list[Trajectory]) -> LocalizerScore:
    fn = LOCALIZERS[name]
    tu = [t for t in trajs if t.is_hallucination and t.is_tool_use]
    clean = [t for t in trajs if not t.is_hallucination]
    fired = exact = within1 = 0
    for t in tu:
        pred = fn(t)
        if pred is None:
            continue
        fired += 1
        gold = t.gold
        if gold is None:
            continue
        if pred == gold:
            exact += 1
        if abs(pred - gold) <= 1:
            within1 += 1
    clean_fired = sum(1 for t in clean if fn(t) is not None)
    return LocalizerScore(
        name=name,
        tool_use_total=len(tu),
        fired=fired,
        exact=exact,
        within1=within1,
        clean_total=len(clean),
        clean_fired=clean_fired,
    )


def compute(trajs: Optional[list[Trajectory]] = None) -> dict[str, LocalizerScore]:
    """Score every registered localizer over the corpus. The SSOT entry point."""
    trajs = trajs if trajs is not None else list(load())
    return {name: _score_one(name, trajs) for name in LOCALIZERS}


def _format(scores: dict[str, LocalizerScore]) -> str:
    lines = [
        "# AgentHallu Tool-Use step-localization claims (docs/166 §4, SSOT)",
        "",
        f"Corpus: AgentHallu (arXiv 2601.06818, CC-BY-4.0), scored offline, $0.",
        f"Comparison anchor: best frontier model on Tool-Use = {SOTA_TOOLUSE:.1%} (Gemini-2.5-Pro).",
        "",
    ]
    for s in scores.values():
        lines += [
            f"## {s.name}",
            f"- Tool-Use trajectories: {s.tool_use_total}",
            f"- EXACT gold-step hit: {s.exact}/{s.tool_use_total} = {s.exact_rate:.1%} "
            f"(lift vs SOTA {SOTA_TOOLUSE:.1%}: {s.lift_vs_sota:+.1%}, ~{s.exact_rate / SOTA_TOOLUSE:.1f}x)",
            f"- within +/-1 step: {s.within1}/{s.tool_use_total} = {s.within1_rate:.1%}",
            f"- precision when fired: {s.exact}/{s.fired} = {s.precision:.1%}",
            f"- FALSE-ALARM floor (clean trajectories): {s.clean_fired}/{s.clean_total} "
            f"= {s.false_alarm:.1%}",
            "",
        ]
    return "\n".join(lines)


# Invariants the test + --check assert. Tolerances are loose enough to survive a corpus refresh
# (±~3pp around each measured value) but tight enough to catch a logic regression (e.g. the gold-step
# string/int coercion bug, or the recovery filter breaking and the false-alarm rebounding to baseline).
def _invariants(scores: dict[str, LocalizerScore]) -> list[str]:
    failures = []

    # Baseline: the broad-regex recall floor — UNCHANGED (still the honest high-false-alarm floor the
    # structural localizers improve on).
    s = scores["first_errored_response"]
    if s.tool_use_total != 103:
        failures.append(f"expected 103 Tool-Use trajectories, got {s.tool_use_total}")
    if not (0.28 <= s.exact_rate <= 0.40):
        failures.append(f"baseline exact_rate {s.exact_rate:.3f} outside [0.28, 0.40]")
    if s.exact_rate <= SOTA_TOOLUSE:
        failures.append(f"baseline exact_rate {s.exact_rate:.3f} did not beat SOTA {SOTA_TOOLUSE}")
    if not (0.25 <= s.false_alarm <= 0.40):
        failures.append(f"baseline false_alarm {s.false_alarm:.3f} outside [0.25, 0.40]")

    # Runner-up: the structural error-CHANNEL fix — ~all recall, ~3× lower false-alarm.
    a = scores["first_structural_error"]
    if not (0.30 <= a.exact_rate <= 0.37):
        failures.append(f"structural exact_rate {a.exact_rate:.3f} outside [0.30, 0.37]")
    if not (0.06 <= a.false_alarm <= 0.16):
        failures.append(f"structural false_alarm {a.false_alarm:.3f} outside [0.06, 0.16]")

    # RECOMMENDED: structural + unrecovered — the precision point, the headline false-alarm cut.
    b = scores["first_unrecovered_error"]
    if not (0.26 <= b.exact_rate <= 0.34):
        failures.append(f"unrecovered exact_rate {b.exact_rate:.3f} outside [0.26, 0.34]")
    if b.exact_rate <= SOTA_TOOLUSE:
        failures.append(f"unrecovered exact_rate {b.exact_rate:.3f} did not beat SOTA {SOTA_TOOLUSE}")
    if b.false_alarm > 0.04:
        failures.append(f"unrecovered false_alarm {b.false_alarm:.3f} exceeds 0.04 (precision claim)")
    if b.precision < 0.75:
        failures.append(f"unrecovered precision {b.precision:.3f} below 0.75 (precision claim)")

    return failures


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AgentHallu Tool-Use step-localization SSOT")
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
        print("OK: AgentHallu claims hold.")
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
