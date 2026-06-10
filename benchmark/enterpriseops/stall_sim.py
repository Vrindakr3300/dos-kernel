"""A faithful, NON-RIGGED stall-reader simulator (docs/145, the loop-economics axis).

╔══════════════════════════════════════════════════════════════════════════════════════════╗
║ ⚠ THE HEADLINE NUMBER IS SIMULATED — its MAGNITUDE is a GUESS, not a measurement.          ║
║                                                                                            ║
║ This sim's delta is governed by `p_stuck` (how often a real agent loops) × catch-rate ×    ║
║ `q_unstick` (how often a re-surface rescues it). The sim PROVES the mechanism plumbing      ║
║ (the verdict fires; the delta is EMERGENT — it → 0 when p_stuck→0 or q_unstick→0) but it    ║
║ does NOT prove the magnitude, because **p_stuck has no real-data anchor** — we have never   ║
║ measured how often gemini-3-flash loops on byte-identical reads. The precedent is exact:    ║
║ the arg_provenance sim said +11.3pp Integrity; the REAL gemini-3-flash run measured ~0      ║
║ (a strong model doesn't mint) and ~+1pp verifier-pass on a deliberately-weakened arm        ║
║ (RESULTS.md). Expect the same order-of-magnitude collapse here. The ONLY trustworthy        ║
║ number comes from `dos_react` on the real gym (the L4 run, docs/148). Use `--honest` to     ║
║ sweep p_stuck across a plausible→pessimistic range and SEE the magnitude is the one thing   ║
║ this sim cannot tell you.                                                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════════╝

The point: prove `dos.tool_stream.classify_stream` (the REPEATING/STALLED verdict) recovers
*stuck* episodes — a cheap agent looping on byte-identical reads until it times out — without
false-firing on *legitimate polling* (an eventual-consistency wait). The SAME `classify_stream`
the kernel ships runs unmodified here; the sim gives it the same inputs the real `dos_react`
wrapper would (an accumulated `(tool, args_digest, result_digest)` stream) and never shows it
the gold "is this actually stuck" label. It proves PLUMBING + EMERGENCE, never MAGNITUDE.

This is the loop-economics analogue of `simulator.py` (which proves the arg_provenance nudge).
Where that sim measures the Integrity slice, this one measures the **horizon / Task-Completion**
axis: a stuck episode that times out FAILS; a re-surface on REPEATING gives it a modeled second
chance to finish on the SAME budget. The delta EMERGES from a generative stuck/advance/poll
dynamic — never hardcoded — and is read against the honest downside (a false re-surface on a
legitimate poller, which is harmless-by-design but must be counted, the §3 hole made measurable).

THE GENERATIVE MODEL (the legitimacy line held)
===============================================
Each episode is a tool stream of K steps drawn from one of three regimes:
  * ADVANCING — every step returns NEW env bytes (distinct result_digest). The agent is making
    progress; the reader must NOT fire. The false-fire exposure on a healthy run.
  * STUCK     — at some depth the agent enters a loop: it re-issues the SAME (tool, args) and the
    env returns the SAME bytes, N times, until it would time out. The reader SHOULD fire; a
    re-surface gives a modeled second chance (q_unstick) to use the value and finish.
  * POLLING   — the agent legitimately re-reads the same status while an async write lands: the
    SAME bytes repeat for a while, THEN change (the write landed) and it finishes. The reader may
    fire (the bytes did repeat) — but it is a FALSE-resurface (the agent was right to wait). The
    honest downside. Modeled as harmless (re-presenting bytes it has) UNLESS the host has not put
    the poller on ignore_tools.

R0 (no reader) vs R1 (the stall reader)
=======================================
R0: the agent runs free; a STUCK episode loops to max_iterations and FAILS (it never used the
    value). A POLLING episode waits then finishes (PASS). An ADVANCING episode finishes (PASS).
R1: before it would loop again, the wrapper folds `classify_stream` over the REAL accumulated
    stream. On REPEATING/STALLED it re-surfaces the repeated env value; the agent gets a modeled
    second chance: with prob q_unstick it now uses the value and finishes (FAIL->PASS, the source
    of the bump); else it stays stuck (still FAILS). A fire on a POLLING episode is counted as a
    false-resurface but does NOT fail it (re-presenting bytes it already has is harmless).

The bump is then a function of the SIMULATED stuck-rate x catch-rate x q_unstick, not a constant;
it -> 0 as stuck-rate -> 0 (a model that doesn't loop) or q_unstick -> 0 (a re-surface it ignores)
— the same emergence discipline as the arg_provenance sim.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from dos.tool_stream import (
    StreamPolicy,
    StreamState,
    StreamStep,
    ToolStream,
    classify_stream,
)

_READ_TOOLS = ("get_incident", "get_user", "get_change", "list_tasks", "get_record")
_POLL_TOOLS = ("poll_status", "wait_for_write", "check_async")


@dataclass
class StallParams:
    """The two load-bearing knobs (`p_stuck`, `q_unstick`) are the sim's WHOLE magnitude — and
    only ONE of them has even a weak real-data anchor. Read the per-field honesty notes.

    `p_stuck` — **NO real anchor.** We have never measured how often gemini-3-flash loops on
      byte-identical reads. The default 0.30 is an optimistic GUESS; the strong-model lesson
      (a capable model that reads-first-and-doesn't-mint probably also doesn't thrash) says the
      real value is likely much lower. This single number dominates the headline → sweep it
      (`--honest`) rather than trust the default.
    `q_unstick` — **weak anchor.** The real gemini run measured a ~75% follow-up-after-nudge
      rate (48/64, RESULTS.md) — but for a MINT nudge, not a stall re-surface, so it is an
      UPPER BOUND on how often a re-surface rescues a stuck run, not a measurement of it.
      Defaulted to 0.75 (the measured anchor) so the sim is at least no rosier than the one
      real number we have; the true stall-recovery rate is unmeasured and plausibly lower."""

    k_min: int = 4
    k_max: int = 16            # horizon up to 16 (the paper's decay tail)
    p_stuck: float = 0.30      # GUESS — no real anchor; sweep it (--honest), do not trust it
    p_poll: float = 0.15       # fraction that legitimately poll (the false-fire exposure)
    stuck_run_len: int = 6     # how many identical steps a stuck loop emits (>= stall_n => caught)
    poll_run_len: int = 4      # identical polls before the async write lands (>= repeat_n => fires)
    q_unstick: float = 0.75    # the measured ~75% follow-up rate — an UPPER BOUND, not a stall measure
    max_iterations: int = 20
    ignore_pollers: bool = False  # does the host put the poll tools on ignore_tools?


@dataclass
class StallEpisode:
    regime: str                # "advancing" | "stuck" | "polling"
    stream: ToolStream         # the accumulated (tool, args, result) stream the reader sees


def _digest(rng: random.Random) -> str:
    """A fresh env-result digest (the gym authored these bytes — the agent did not)."""
    return f"r{rng.randint(0, 10**9):09d}"


def generate_episode(rng: random.Random, params: StallParams) -> StallEpisode:
    """Build one episode's tool stream — env-authored, never sees the reader."""
    k = rng.randint(params.k_min, params.k_max)
    roll = rng.random()
    steps: list[StreamStep] = []
    if roll < params.p_stuck:
        regime = "stuck"
        # some advancing prefix, then a byte-identical loop to (would-be) timeout
        prefix = max(1, k - params.stuck_run_len)
        for _ in range(prefix):
            tool = rng.choice(_READ_TOOLS)
            steps.append(StreamStep(tool, f"a{rng.randint(0,999)}", _digest(rng)))
        tool = rng.choice(_READ_TOOLS)
        args = f"a{rng.randint(0,999)}"
        frozen = _digest(rng)  # the value it keeps re-reading and failing to use
        for _ in range(params.stuck_run_len):
            steps.append(StreamStep(tool, args, frozen))
    elif roll < params.p_stuck + params.p_poll:
        regime = "polling"
        prefix = max(1, k - params.poll_run_len - 1)
        for _ in range(prefix):
            tool = rng.choice(_READ_TOOLS)
            steps.append(StreamStep(tool, f"a{rng.randint(0,999)}", _digest(rng)))
        tool = rng.choice(_POLL_TOOLS)
        args = f"a{rng.randint(0,999)}"
        waiting = _digest(rng)
        for _ in range(params.poll_run_len):
            steps.append(StreamStep(tool, args, waiting))  # waiting for the write
        steps.append(StreamStep(tool, args, _digest(rng)))  # the write landed (new bytes)
    else:
        regime = "advancing"
        for _ in range(k):
            tool = rng.choice(_READ_TOOLS)
            steps.append(StreamStep(tool, f"a{rng.randint(0,999)}", _digest(rng)))
    return StallEpisode(regime=regime, stream=ToolStream(steps=tuple(steps)))


@dataclass
class ArmStats:
    n: int = 0
    completed: int = 0          # episodes that finished (the Task-Completion slice)
    timeouts: int = 0
    fired: int = 0              # episodes the reader fired REPEATING/STALLED on
    fired_stuck: int = 0
    fired_polling: int = 0      # the false-resurface cell
    recovered: int = 0          # stuck episodes a re-surface unstuck

    @property
    def completion_rate(self) -> float:
        return 100.0 * self.completed / self.n if self.n else 0.0


def run_episode_r0(ep: StallEpisode, params: StallParams) -> bool:
    """Baseline: a STUCK episode loops to timeout and FAILS; advancing/polling finish."""
    return ep.regime != "stuck"


def _fires_incrementally(stream: ToolStream, policy: StreamPolicy) -> bool:
    """True iff the reader fires on ANY prefix of the stream — the honest model of how the real
    `dos_react` consumer calls `classify_stream` (per step, as the stream grows), not just once
    at the end. This is what catches a POLLING episode MID-WAIT (before the async write lands and
    breaks the run): folding only the final stream would miss it (the trailing run is length 1
    once the write lands), understating the false-resurface exposure — the §3 honest hole."""
    steps = stream.steps
    for i in range(1, len(steps) + 1):
        v = classify_stream(ToolStream(steps=steps[:i]), policy)
        if v.state is not StreamState.ADVANCING:
            return True
    return False


def run_episode_r1(rng: random.Random, ep: StallEpisode, params: StallParams,
                   policy: StreamPolicy, arm: ArmStats) -> bool:
    """The stall reader: fold `classify_stream` over the real stream INCREMENTALLY (as the
    consumer would, per step); on a fire, model the second chance. Returns whether finished."""
    fired = _fires_incrementally(ep.stream, policy)
    if fired:
        arm.fired += 1
        if ep.regime == "stuck":
            arm.fired_stuck += 1
            # the re-surface gives a modeled second chance to use the value and finish
            if rng.random() < params.q_unstick:
                arm.recovered += 1
                return True
            return False  # ignored the re-surface, stays stuck
        if ep.regime == "polling":
            arm.fired_polling += 1   # a FALSE-resurface — harmless (it has the bytes), finishes
            return True
        # advancing fired? (shouldn't, but if it did it's harmless) -> finishes
        return True
    # did not fire: stuck stays stuck (FAIL), advancing/polling finish
    return ep.regime != "stuck"


def run_split(seed: int, n: int, params: StallParams) -> tuple[ArmStats, ArmStats]:
    """Run the SAME n episodes (same per-episode seed) through R0 and R1 — a paired A/B."""
    policy = StreamPolicy(
        repeat_n=3, stall_n=5,
        ignore_tools=frozenset(_POLL_TOOLS) if params.ignore_pollers else frozenset(),
    )
    gen = random.Random(seed)
    r0, r1 = ArmStats(), ArmStats()
    for _ in range(n):
        ep = generate_episode(gen, params)
        ag_seed = gen.randint(0, 2**31)
        r0.n += 1
        if run_episode_r0(ep, params):
            r0.completed += 1
        else:
            r0.timeouts += 1
        r1.n += 1
        if run_episode_r1(random.Random(ag_seed), ep, params, policy, r1):
            r1.completed += 1
        else:
            r1.timeouts += 1
    return r0, r1


def _mean_std(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, var ** 0.5


def headline(n: int, seeds: list[int], params: StallParams) -> None:
    r0c, r1c = [], []
    agg = ArmStats()
    for s in seeds:
        r0, r1 = run_split(s, n, params)
        r0c.append(r0.completion_rate)
        r1c.append(r1.completion_rate)
        agg.fired += r1.fired
        agg.fired_stuck += r1.fired_stuck
        agg.fired_polling += r1.fired_polling
        agg.recovered += r1.recovered
        agg.n += r1.n
    m0, s0 = _mean_std(r0c)
    m1, s1 = _mean_std(r1c)
    pollers = "ON ignore_tools" if params.ignore_pollers else "NOT exempted"
    print("=" * 78)
    print(f"  EnterpriseOps-Gym STALL-READER simulated A/B — {n} episodes x {len(seeds)} seeds")
    print(f"  (the SAME dos.tool_stream.classify_stream the kernel ships runs in R1)")
    print(f"  pollers: {pollers}")
    print("=" * 78)
    print(f"{'Metric':<40}{'R0 (react)':>14}{'R1 (stall rdr)':>16}{'delta':>8}")
    print("-" * 78)
    print(f"{'Task-Completion %':<40}{m0:>10.2f}±{s0:<3.1f}{m1:>11.2f}±{s1:<3.1f}{m1-m0:>+8.2f}")
    print("-" * 78)
    print(f"  episodes the reader fired on:   {agg.fired}")
    print(f"  fired on STUCK (a useful fire): {agg.fired_stuck}")
    print(f"  fired on POLLING (false-resurface, harmless): {agg.fired_polling}")
    print(f"  stuck episodes RECOVERED:       {agg.recovered}")
    print("=" * 78)
    delta = m1 - m0
    gate = delta >= 2.0
    print(f"  R1 GATE (Task-Completion +>=2pp from unsticking loops): "
          f"{'PASS' if gate else 'n/a'}")
    print(f"    completion delta = {delta:+.2f}pp  |  false-resurfaces = {agg.fired_polling} "
          f"(harmless; exempt via ignore_tools)")
    print("=" * 78)


def honest_sweep(n: int, seeds: list[int]) -> None:
    """The honesty instrument: sweep `p_stuck` (the ONE unmeasured number that governs the
    magnitude) across a plausible→pessimistic range at the MEASURED q_unstick=0.75 anchor, and
    show that the headline is whatever p_stuck you assume. The whole point: the sim cannot tell
    you the magnitude — only the real gym run can. The strong-model row (p_stuck=0.05) is the
    honest default expectation (a capable model that doesn't mint probably doesn't thrash)."""
    print("=" * 78)
    print(f"  STALL-READER honesty sweep — {n} episodes x {len(seeds)} seeds, q_unstick=0.75 (measured anchor)")
    print(f"  The magnitude is WHATEVER p_stuck is — and p_stuck is UNMEASURED. Read this as a")
    print(f"  range of GUESSES, not a result. Only the real gym run settles it (docs/148 L4).")
    print("=" * 78)
    print(f"{'p_stuck (assumed loop-rate)':<34}{'completion delta':>20}{'  reading'}")
    print("-" * 78)
    readings = {
        0.05: "strong model (likely real) — the honest default expectation",
        0.10: "mildly looping cheap model",
        0.20: "moderately looping cheap model",
        0.30: "the optimistic guess the headline used",
    }
    for ps in (0.05, 0.10, 0.20, 0.30):
        r0c = r1c = r0n = r1n = 0
        for s in seeds:
            r0, r1 = run_split(s, n, StallParams(p_stuck=ps))
            r0c += r0.completed; r0n += r0.n; r1c += r1.completed; r1n += r1.n
        d = 100.0 * r1c / r1n - 100.0 * r0c / r0n
        print(f"  p_stuck={ps:<4.2f}{'':<22}{d:>+8.2f}pp        {readings[ps]}")
    print("-" * 78)
    print("  [!] The arg_provenance precedent: sim said +11.3pp, real gemini run measured ~0 /")
    print("      ~+1pp verifier-pass. Expect the same collapse here -- the real number is the run.")
    print("=" * 78)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="the stall-reader simulated A/B (docs/145)")
    ap.add_argument("--episodes", type=int, default=500, help="episodes per seed")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--ignore-pollers", action="store_true",
                    help="put the poll tools on ignore_tools (drops false-resurfaces to 0)")
    ap.add_argument("--honest", action="store_true",
                    help="sweep the UNMEASURED p_stuck — show the magnitude is a guess, not a result")
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    if args.honest:
        honest_sweep(args.episodes, seeds)
    else:
        params = StallParams(ignore_pollers=args.ignore_pollers)
        headline(args.episodes, seeds, params)
