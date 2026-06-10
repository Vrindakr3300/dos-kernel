"""The replay scorer: fold the DOS detectors over frozen trajectories, join to the third-party label.

The deliverable (docs/157): per detector, the **fire-rate** and the **oracle-confirmed precision** —
of the runs the detector flagged, the fraction the INDEPENDENT verifier (`task_status.evaluation`)
scored as failed. A detector that fires mostly on runs the third party also failed has real
purchase; one that fires on passed runs is a false alarm. This measures DETECT (not FIX): the
trajectory is frozen, no intervention happened, so there is no lift number — and that is the honest
boundary, stated up front.

Pure over the parsed trajectories (the I/O is in `dataset.py`); every number here is reproducible
from the frozen JSONL with zero benchmark/MCP/LLM access — the keystone the audit calls "testable
with zero benchmark access".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from dos.dangling_intent import DEFAULT_POLICY as DI_POLICY, DanglingPolicy, classify_stop
from dos.tool_stream import (
    DEFAULT_POLICY as TS_POLICY,
    StreamPolicy,
    StreamState,
    ToolStream,
    classify_stream,
)

from .trajectory import (
    Trajectory,
    terminal_error_fired,
    to_stop_evidence,
    to_tool_stream,
)


# ---------------------------------------------------------------------------
# Per-run detector firings (pure, replay-only).
# ---------------------------------------------------------------------------
def dangling_fired(traj: Trajectory, policy: DanglingPolicy = DI_POLICY) -> bool:
    """True iff `dangling_intent` flags this run (terminal narration admits open work, nothing
    env-authored acted after). Pure fold of `classify_stop` over the boundary evidence."""
    return classify_stop(to_stop_evidence(traj), policy).is_dangling


def tool_stream_peak(
    traj: Trajectory, policy: StreamPolicy = TS_POLICY, *, normalize: bool = True
) -> StreamState:
    """The PEAK stall state reached anywhere in the run.

    `classify_stream` is a LIVE verdict over the run ENDING at the latest step (the "stuck right
    now?" question). For a replay over a COMPLETED trajectory we want "did the loop EVER stall?",
    so we fold the verdict over every growing prefix and keep the strongest state seen (STALLED >
    REPEATING > ADVANCING). This is the streaming semantics the detector was built for, evaluated
    offline — exactly what a live consumer would have observed turn-by-turn.

    `normalize` (default True) masks volatile env token shapes before digesting (the docs/157 §4
    lift); pass False for the RAW conservative lower-bound floor.
    """
    order = {StreamState.ADVANCING: 0, StreamState.REPEATING: 1, StreamState.STALLED: 2}
    peak = StreamState.ADVANCING
    steps = traj_tool_steps(traj, normalize=normalize)
    for i in range(1, len(steps) + 1):
        st = classify_stream(ToolStream(steps=tuple(steps[:i])), policy).state
        if order[st] > order[peak]:
            peak = st
            if peak is StreamState.STALLED:
                break  # nothing stronger; stop early
    return peak


def traj_tool_steps(traj: Trajectory, *, normalize: bool = True):
    """The frozen `StreamStep` tuple for a trajectory (cached-free; cheap).

    `normalize` (default True) applies the volatile-field masker before hashing results."""
    return to_tool_stream(traj, normalize=normalize).steps


def tool_stream_fired(
    traj: Trajectory, policy: StreamPolicy = TS_POLICY, *, min_state: StreamState = StreamState.REPEATING,
    normalize: bool = True,
) -> bool:
    """True iff the run's peak stall state reached `min_state` (default REPEATING) or stronger."""
    order = {StreamState.ADVANCING: 0, StreamState.REPEATING: 1, StreamState.STALLED: 2}
    return order[tool_stream_peak(traj, policy, normalize=normalize)] >= order[min_state]


# ---------------------------------------------------------------------------
# The confusion grid for ONE detector against the third-party label.
# ---------------------------------------------------------------------------
@dataclass
class DetectorReport:
    """The replay confusion grid + headline rates for one detector across a set of runs.

    Cells join the detector's FIRE/quiet against the oracle's FAIL/pass (label None excluded):

                          oracle FAILED   oracle PASSED
        detector FIRED      fired_fail      fired_pass     <- a fire on a PASSED run is a false alarm
        detector quiet      quiet_fail      quiet_pass

    Rates:
      fire_rate                 = fired / labeled                  (how often it speaks)
      oracle_confirmed_precision= fired_fail / fired               (of fires, fraction the 3rd party failed)
      recall_of_failures        = fired_fail / oracle_failed       (of failures, fraction it caught)
      false_alarm_rate          = fired_pass / oracle_passed       (of passes, fraction it wrongly flagged)
    `base_fail_rate` is the corpus's own failure rate — the precision floor a no-skill detector that
    fired on everything would hit. Precision MUST beat base_fail_rate to show purchase.
    """

    name: str
    labeled: int = 0          # runs with a boolean evaluation label
    unlabeled: int = 0        # runs excluded (evaluation None)
    oracle_failed: int = 0
    oracle_passed: int = 0
    fired_fail: int = 0
    fired_pass: int = 0
    quiet_fail: int = 0
    quiet_pass: int = 0

    @property
    def fired(self) -> int:
        return self.fired_fail + self.fired_pass

    @property
    def fire_rate(self) -> float:
        return self.fired / self.labeled if self.labeled else 0.0

    @property
    def base_fail_rate(self) -> float:
        return self.oracle_failed / self.labeled if self.labeled else 0.0

    @property
    def oracle_confirmed_precision(self) -> Optional[float]:
        return self.fired_fail / self.fired if self.fired else None

    @property
    def recall_of_failures(self) -> Optional[float]:
        return self.fired_fail / self.oracle_failed if self.oracle_failed else None

    @property
    def false_alarm_rate(self) -> Optional[float]:
        return self.fired_pass / self.oracle_passed if self.oracle_passed else None

    @property
    def lift_over_base(self) -> Optional[float]:
        """Precision minus the base failure rate — the purchase signal. >0 means a fire is MORE
        likely to be a real failure than a random run is. <=0 means no skill (it fires
        indiscriminately)."""
        p = self.oracle_confirmed_precision
        return None if p is None else p - self.base_fail_rate

    def observe(self, fired: bool, passed: Optional[bool]) -> None:
        if passed is None:
            self.unlabeled += 1
            return
        self.labeled += 1
        if passed:
            self.oracle_passed += 1
            if fired:
                self.fired_pass += 1
            else:
                self.quiet_pass += 1
        else:
            self.oracle_failed += 1
            if fired:
                self.fired_fail += 1
            else:
                self.quiet_fail += 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "labeled": self.labeled,
            "unlabeled": self.unlabeled,
            "oracle_failed": self.oracle_failed,
            "oracle_passed": self.oracle_passed,
            "fired": self.fired,
            "fired_fail": self.fired_fail,
            "fired_pass": self.fired_pass,
            "quiet_fail": self.quiet_fail,
            "quiet_pass": self.quiet_pass,
            "fire_rate": round(self.fire_rate, 4),
            "base_fail_rate": round(self.base_fail_rate, 4),
            "oracle_confirmed_precision": (
                None if self.oracle_confirmed_precision is None
                else round(self.oracle_confirmed_precision, 4)
            ),
            "recall_of_failures": (
                None if self.recall_of_failures is None else round(self.recall_of_failures, 4)
            ),
            "false_alarm_rate": (
                None if self.false_alarm_rate is None else round(self.false_alarm_rate, 4)
            ),
            "lift_over_base": (
                None if self.lift_over_base is None else round(self.lift_over_base, 4)
            ),
        }


# ---------------------------------------------------------------------------
# The whole-corpus replay.
# ---------------------------------------------------------------------------
@dataclass
class RunRow:
    """One durable, flat per-run record — the explorable unit the next agent visualizes.

    Deliberately FLAT (no nesting) so it loads straight into a dataframe / sqlite / a plotting
    notebook with zero reshaping. One row per (model, run, task); every field is a scalar. This is
    the 'data found in a durable format to explore' deliverable: the replay's raw join, frozen, so
    a viz never re-folds the trajectories and the numbers are reproducible from the row file alone.
    """

    model: str
    model_run: str
    task_name: str
    passed: object              # True / False / None (the third-party oracle label)
    n_tool_steps: int           # length of the env-progress tool stream
    dangling_fired: bool
    dangling_cue: str           # the matched marker text (or "")
    tool_stream_state: str      # peak StreamState: ADVANCING / REPEATING / STALLED
    tool_stream_run: int        # the peak consecutive-identical run length
    tool_stream_fired: bool
    terminal_error_fired: bool  # stopped on an unresolved structured env error, recovery="aware" (docs/158)
    final_text_len: int         # length of the terminal narration (a quick completeness proxy)
    # The docs/162 recovery-knob's surgical mode, carried ALONGSIDE the conservative column so the
    # higher-recall trio is a first-class SSOT claim (additivity.py folds either column). Always the
    # specific-only verdict regardless of the row's te_recovery (which controls only the conservative
    # `terminal_error_fired` confusion-grid column); both modes are present in every durable row.
    terminal_error_specific_fired: bool = False

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "model_run": self.model_run,
            "task_name": self.task_name,
            "passed": self.passed,
            "n_tool_steps": self.n_tool_steps,
            "dangling_fired": self.dangling_fired,
            "dangling_cue": self.dangling_cue,
            "tool_stream_state": self.tool_stream_state,
            "tool_stream_run": self.tool_stream_run,
            "tool_stream_fired": self.tool_stream_fired,
            "terminal_error_fired": self.terminal_error_fired,
            "final_text_len": self.final_text_len,
            "terminal_error_specific_fired": self.terminal_error_specific_fired,
        }


def run_row(
    traj: Trajectory,
    *,
    di_policy: DanglingPolicy = DI_POLICY,
    ts_policy: StreamPolicy = TS_POLICY,
    ts_min_state: StreamState = StreamState.REPEATING,
    normalize: bool = True,
    te_recovery: str = "aware",
) -> RunRow:
    """Compute the flat durable row for one trajectory — the per-run join, frozen for exploration.

    The durable row ALWAYS carries BOTH terminal_error modes (the docs/162 SSOT contract):
    `terminal_error_fired` is the conservative recovery="aware" verdict (the shipped default,
    byte-identical across runs), and `terminal_error_specific_fired` is the surgical
    recovery="specific-only" verdict. `te_recovery` does NOT change the durable columns — it only
    selects which mode the CLI confusion grid scores (see `replay`); the rows stay stable so
    additivity.py can fold either trio reproducibly."""
    from .trajectory import to_stop_evidence
    from dos.dangling_intent import classify_stop
    from dos.tool_stream import ToolStream, classify_stream

    ev = to_stop_evidence(traj)
    di = classify_stop(ev, di_policy)
    steps = traj_tool_steps(traj, normalize=normalize)
    peak = tool_stream_peak(traj, ts_policy, normalize=normalize)
    # the run-length at the peak (re-derive cheaply: fold to the peak prefix is overkill; the
    # whole-stream verdict's repeat_run is the trailing run — good enough for the durable row,
    # and the peak STATE is already the strongest seen)
    whole = classify_stream(ToolStream(steps=tuple(steps)), ts_policy)
    order = {StreamState.ADVANCING: 0, StreamState.REPEATING: 1, StreamState.STALLED: 2}
    ts_fired = order[peak] >= order[ts_min_state]
    return RunRow(
        model=traj.model,
        model_run=traj.model_run,
        task_name=traj.task_name,
        passed=traj.passed,
        n_tool_steps=len(steps),
        dangling_fired=di.is_dangling,
        dangling_cue=di.matched_cue,
        tool_stream_state=peak.value,
        tool_stream_run=whole.repeat_run,
        tool_stream_fired=ts_fired,
        terminal_error_fired=terminal_error_fired(traj, recovery="aware"),
        final_text_len=len(ev.final_turn_text or ""),
        terminal_error_specific_fired=terminal_error_fired(traj, recovery="specific-only"),
    )


@dataclass
class ReplayResult:
    """Reports for every detector over a corpus, plus per-model breakdowns and the durable rows."""

    dangling: DetectorReport = field(default_factory=lambda: DetectorReport("dangling_intent"))
    tool_stream: DetectorReport = field(default_factory=lambda: DetectorReport("tool_stream"))
    terminal_error: DetectorReport = field(default_factory=lambda: DetectorReport("terminal_error"))
    # detector x model -> report (the generality slice: does it fire cleanly across model families?)
    by_model: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)  # the flat durable RunRow per trajectory
    n_records: int = 0

    def to_dict(self) -> dict:
        return {
            "n_records": self.n_records,
            "detectors": {
                "dangling_intent": self.dangling.to_dict(),
                "tool_stream": self.tool_stream.to_dict(),
                "terminal_error": self.terminal_error.to_dict(),
            },
            "by_model": {
                model: {d: rep.to_dict() for d, rep in dmap.items()}
                for model, dmap in sorted(self.by_model.items())
            },
        }


def replay(
    trajectories: Iterable[Trajectory],
    *,
    di_policy: DanglingPolicy = DI_POLICY,
    ts_policy: StreamPolicy = TS_POLICY,
    ts_min_state: StreamState = StreamState.REPEATING,
    normalize: bool = True,
    te_recovery: str = "aware",
) -> ReplayResult:
    """Fold both detectors over every trajectory, join to the third-party label, accumulate grids.

    Pure over the (already-parsed) trajectories. Produces the whole-corpus reports AND a per-model
    breakdown (the docs/157 'generality' question: do the detectors fire cleanly across Claude AND
    GPT-5 AND Gemini AND DeepSeek, or are they overfit to one family?).

    `normalize` (default True) applies the `tool_stream` volatile-field masker (docs/157 §4); pass
    False to reproduce the RAW conservative lower-bound numbers. `te_recovery` is the docs/162
    terminal_error recovery knob ("aware" default / "specific-only" / "none"); it selects which mode
    the terminal_error CONFUSION GRID scores. The durable rows always carry BOTH the aware and the
    specific-only columns regardless (the SSOT contract — see `run_row`).
    """
    out = ReplayResult()
    for traj in trajectories:
        out.n_records += 1
        row = run_row(
            traj, di_policy=di_policy, ts_policy=ts_policy, ts_min_state=ts_min_state,
            normalize=normalize, te_recovery=te_recovery,
        )
        out.rows.append(row)
        di = row.dangling_fired
        ts = row.tool_stream_fired
        # the grid scores the requested recovery mode: aware/specific-only are the two durable row
        # columns; "none" is recomputed (it is not a durable column — the rows carry only the two
        # defensible operating points).
        if te_recovery == "specific-only":
            te = row.terminal_error_specific_fired
        elif te_recovery == "none":
            te = terminal_error_fired(traj, recovery="none")
        else:
            te = row.terminal_error_fired
        out.dangling.observe(di, traj.passed)
        out.tool_stream.observe(ts, traj.passed)
        out.terminal_error.observe(te, traj.passed)
        m = traj.model
        dmap = out.by_model.setdefault(
            m,
            {
                "dangling_intent": DetectorReport("dangling_intent"),
                "tool_stream": DetectorReport("tool_stream"),
                "terminal_error": DetectorReport("terminal_error"),
            },
        )
        dmap["dangling_intent"].observe(di, traj.passed)
        dmap["tool_stream"].observe(ts, traj.passed)
        dmap["terminal_error"].observe(te, traj.passed)
    return out
