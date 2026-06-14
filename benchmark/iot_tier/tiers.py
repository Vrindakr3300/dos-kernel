"""The declared model-tier ladder — the calibration, made auditable.

Each `TierProfile` is the DECLARED INPUT to the sweep, not a result: a per-task failure rate and
the split of those failures across the five shapes the three shipped detectors do / do not see.
Two of the five shapes are DOS-recoverable (mint, loop) plus the narrating premature stop
(dangle); the other two (silent_stop, planning) are the unreachable remainder DOS owns 0% of
(docs/153 §4). As a model weakens, the unreachable remainder GROWS — and at the IoT tier the
`can-do-step-when-nudged` decay (docs/153 §1) migrates the narrating-stop share INTO silent-stop
(the model stops narrating "I need X" because it can no longer form even the narration). That
migration is the mechanism behind the predicted collapse.

EVERY number here is cited to docs/153 §1–§2 and is the *assumption a reader gets to audit*, never
a measured magnitude. The frontier row is pinned to reproduce the gate's published gemini self-test
(docs/153 §5: ~13% recoverable, MINT excluded as noise, DANGLE+LOOP signal, < 15% threshold). The
real measurement that would replace these assumptions is the docs/153 Stage-0 ~$50 corpus run at
the IoT tier — named in README.md as the falsifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The five failure shapes. The first three are what the shipped detectors can flag (the
# DOS-recoverable execution substrate); the last two are the unreachable remainder.
FAILURE_SHAPES = ("mint", "loop", "narrating_stop", "silent_stop", "planning")
RECOVERABLE_SHAPES = ("mint", "loop", "narrating_stop")


@dataclass(frozen=True)
class TierProfile:
    """One model-size tier's DECLARED failure calibration (an input, not a result).

    `fail_mix` is the conditional distribution over FAILURE_SHAPES GIVEN a run failed; it sums
    to 1.0. `pass_incidental` is the small share of PASSED runs that carry an incidental mint /
    dangling cue (real strong models do this — it is what makes the enrichment filter have a
    pass-side signal to subtract, and what reproduces MINT-as-noise on the frontier tier).
    """
    name: str
    model_class: str           # the real model class this tier is calibrated to (for the print)
    per_task_fail_rate: float  # share of tasks that fail at all
    fail_mix: dict             # conditional dist over FAILURE_SHAPES | fail, sums to 1.0
    pass_incidental: dict = field(default_factory=dict)  # {mint|narrating_stop: share of PASSES}
    note: str = ""             # the one-line modeling note (cited)

    def __post_init__(self):
        s = sum(self.fail_mix.get(k, 0.0) for k in FAILURE_SHAPES)
        if abs(s - 1.0) > 1e-6:
            raise ValueError(f"{self.name}: fail_mix must sum to 1.0, got {s:.4f}")
        for k in self.fail_mix:
            if k not in FAILURE_SHAPES:
                raise ValueError(f"{self.name}: unknown failure shape {k!r}")


# ---------------------------------------------------------------------------------------------
# The ladder. Numbers interpolate the docs/153 §1–§2 ladder; the extrapolation rule to IoT is
# stated in the `note` and in README.md. These are ASSUMPTIONS, presented for audit.
# ---------------------------------------------------------------------------------------------
LADDER: tuple[TierProfile, ...] = (
    # FRONTIER — pinned to the gemini-2.5-flash self-test (docs/153 §5). ~87% unreachable
    # (silent-stop + planning); DANGLE ~11% of failures (the docs/150 13% recall); LOOP ~2%;
    # mint ~0 real (it reads its FKs first). pass_incidental.mint reproduces MINT-as-noise:
    # the gate must EXCLUDE mint here (fires >= on passes), leaving DANGLE+LOOP < 15% => null.
    TierProfile(
        name="frontier",
        model_class="gemini-2.5-flash class",
        per_task_fail_rate=0.45,
        fail_mix={"mint": 0.01, "loop": 0.02, "narrating_stop": 0.11,
                  "silent_stop": 0.49, "planning": 0.37},
        pass_incidental={"mint": 0.06},  # the residual false-flag MINT rate (docs/153 §5)
        note="Pinned to the docs/153 §5 gemini null: ~13% recoverable < 15% => DOS-shape FALSE.",
    ),
    # MID — DeepSeek-V3.2 class (docs/153 §2, the principled middle). Good enough to plan a
    # quarter of tasks, so execution fumbles are a BIGGER share of its gap: mint+loop rise off
    # the floor, narrating-stop rises, the unreachable remainder shrinks vs frontier. This is
    # where docs/153 predicts the recoverable fraction PEAKS.
    TierProfile(
        name="mid",
        model_class="DeepSeek-V3.2 class",
        per_task_fail_rate=0.75,
        fail_mix={"mint": 0.08, "loop": 0.07, "narrating_stop": 0.22,
                  "silent_stop": 0.34, "planning": 0.29},
        pass_incidental={"mint": 0.04},
        note="docs/153 §2 principled middle: execution fumbles a larger share => predicted PEAK.",
    ),
    # SMALL — Qwen3-class (docs/153 §2 'the floor, not the proof'). Failing strategy on most
    # tasks: planning share grows back, can-do-when-nudged starts to decay so narrating-stop is
    # past its peak, silent-stop rises. Recoverable fraction is OFF peak, descending.
    TierProfile(
        name="small",
        model_class="Qwen3-class",
        per_task_fail_rate=0.84,
        fail_mix={"mint": 0.06, "loop": 0.06, "narrating_stop": 0.18,
                  "silent_stop": 0.40, "planning": 0.30},
        pass_incidental={"mint": 0.04},
        note="docs/153 §2 floor: strategy fails more; narrating-stop past peak, descending.",
    ),
    # IOT — sub-3B edge class. The can-do-step-when-nudged decay reaches its end (docs/153 §1):
    # the model can no longer form even the narration, so the narrating-stop share COLLAPSES and
    # migrates into silent-stop, which (with planning) dominates. The recoverable fraction
    # COLLAPSES back below — possibly below — the frontier null. This is the predicted COLLAPSE.
    TierProfile(
        name="iot",
        model_class="sub-3B edge class",
        per_task_fail_rate=0.92,
        fail_mix={"mint": 0.04, "loop": 0.04, "narrating_stop": 0.07,
                  "silent_stop": 0.52, "planning": 0.33},
        pass_incidental={"mint": 0.03},
        note="docs/153 §1 can-do-when-nudged decay: narration collapses into silent-stop => COLLAPSE.",
    ),
)


def by_name(name: str) -> TierProfile:
    for t in LADDER:
        if t.name == name:
            return t
    raise KeyError(name)
