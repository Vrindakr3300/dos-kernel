"""Shared, benchmark-agnostic FEASIBILITY SPLIT — the preprocessing step every
conversion A/B and every detector-precision score must run BEFORE scoring (docs/198).

WHY THIS EXISTS (the category error it prevents). The DOS livelock line spent three
workflows scoring cures ("can DOS make the agent SUCCEED on this loop?") against a
denominator polluted with INFEASIBLE tasks. The dominant "thrash" tool on
EnterpriseOps — `create_filter` — succeeds **0 times in 278+ calls across every arm**:
its schema demands ~9 `criteria` fields and the user task ("filter on sender only")
cannot be expressed under it. You cannot, even in principle, make an agent succeed at
an infeasible task, so every "refuted" verdict (rewind -3, block -6, abandon "refuted")
was measuring conversion where conversion is impossible.

The fix is a population split that comes FIRST and is byte-clean:

  * A tool is **WALLED** iff it has 0 successful (non-error) results ANYWHERE in the
    corpus; **CURABLE** iff the same tool succeeds on some run (a path provably exists).
  * The witness is **ENV-AUTHORED** — a non-error tool result is the environment's own
    reply, so an agent cannot forge that some OTHER run got a clean result. This is the
    `precursor_gate` / `arg_provenance` provenance shape (presence-of-evidence), the same
    discipline as `tool_stream`'s `result_digest`.

Then score on the RIGHT denominator per population:

  * On the CURABLE slice: score CONVERSION (did a cure flip fail->pass?). This is the
    only slice where conversion is even a coherent question.
  * On the WALLED slice: score GIVE-UP-CORRECTLY (tokens averted by an early halt, with
    false-abandon = halting a run that actually succeeds). On a wall there is nothing to
    convert, so the only honest value is to stop burning tokens.

This module is the BENCHMARK-AGNOSTIC core. A per-benchmark adapter supplies an iterable
of `ToolEvent(tool_name, is_error)` per run (EnterpriseOps reads `tool_results` +
`dos_react._is_struct_error`; Toolathlon reads `to_tool_stream` / `is_struct_error`),
and this module computes the witness + the split. It is pure stdlib data + folds; it
imports nothing from `dos` and nothing from a specific benchmark — a leaf the way
`_arms` is, on the CONSUMER side of the one-way arrow (the kernel never imports it).

    from _feasibility import feasibility_witness, ToolEvent, classify_run, Feasibility
    witness = feasibility_witness(all_runs_events)        # {tool: Verdict}
    cls = classify_run(this_run_events, witness)          # WALLED / CURABLE / NO_THRASH
"""
from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# The benchmark-agnostic event: one env-authored tool result.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolEvent:
    """One tool result, reduced to the two facts the witness needs.

      tool_name — the dispatched tool (env-authored identity).
      is_error  — True iff the ENV's reply was a structured error (the byte-clean signal;
                  each benchmark supplies its own struct-error grammar at the adapter edge).

    A `ToolEvent` is intentionally minimal: the witness does not read args, narration, or
    any agent-authored byte. A benchmark adapter is responsible for excluding synthetic
    DOS-BLOCK results (self-laundering guard) before yielding events here.
    """

    tool_name: str
    is_error: bool


class Verdict(str, enum.Enum):
    """The per-tool feasibility verdict (the witness output)."""

    WALLED = "WALLED"        # 0 successes anywhere in the corpus — INFEASIBLE
    CURABLE = "CURABLE"      # succeeds on some run — a path provably exists
    THIN = "THIN"           # too few observations to call (below min_obs); treated as CURABLE
                            # for splitting (conservative: do NOT declare a wall on thin data)

    def is_walled(self) -> bool:
        return self is Verdict.WALLED


class Feasibility(str, enum.Enum):
    """The per-RUN population class, derived from its thrash tools + the witness."""

    WALLED = "WALLED"        # the run thrashed on at least one WALLED tool (and none curable)
    CURABLE = "CURABLE"      # the run thrashed on a CURABLE tool (conversion is coherent here)
    NO_THRASH = "NO_THRASH"  # the run never thrashed (no same-tool >=K error loop)


# ---------------------------------------------------------------------------
# The witness: fold per-tool (ok, err) over the WHOLE corpus, then classify.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolStat:
    tool_name: str
    ok: int
    err: int

    @property
    def total(self) -> int:
        return self.ok + self.err

    def verdict(self, *, min_obs: int, curable_ratio: float) -> Verdict:
        """WALLED iff 0 successes (with enough error observations to be sure); CURABLE iff
        it clears `curable_ratio` of successes; THIN if too few observations to call.

        `curable_ratio` exists only to label the "mostly-walled but has 1-2 lucky successes"
        middle as CURABLE-leaning vs WALLED-leaning in REPORTS — for the SPLIT itself a single
        success is enough to make a tool CURABLE (a path provably exists), so the split uses
        `is_curable_for_split`. The ratio governs only the human-facing 3-way label."""
        if self.err < min_obs:
            return Verdict.THIN
        if self.ok == 0:
            return Verdict.WALLED
        return Verdict.CURABLE

    def is_curable_for_split(self) -> bool:
        """For population splitting, ONE env-authored success is proof a path exists. This is
        deliberately more permissive than `verdict()` — we never want to mis-route a run with a
        genuinely curable tool into the WALLED (no-conversion) bucket. A wall must be airtight."""
        return self.ok > 0


def fold_tool_stats(corpus: Iterable[Iterable[ToolEvent]]) -> Dict[str, ToolStat]:
    """Per tool, count (ok, err) over EVERY run in the corpus. `corpus` is an iterable of
    per-run event iterables. The witness must see the WHOLE corpus (all arms, all runs) so a
    success in ANY run lifts a tool out of WALLED — that cross-run join is the whole point
    (a fold mints the WALLED/CURABLE fact only by joining many independently-authored runs)."""
    ok: Dict[str, int] = defaultdict(int)
    err: Dict[str, int] = defaultdict(int)
    for run in corpus:
        for ev in run:
            if not ev.tool_name:
                continue
            if ev.is_error:
                err[ev.tool_name] += 1
            else:
                ok[ev.tool_name] += 1
    tools = set(ok) | set(err)
    return {t: ToolStat(t, ok.get(t, 0), err.get(t, 0)) for t in tools}


def feasibility_witness(
    corpus: Iterable[Iterable[ToolEvent]], *, min_obs: int = 3, curable_ratio: float = 0.2
) -> Dict[str, Verdict]:
    """The witness: {tool_name -> Verdict} over the whole corpus. A tool is WALLED only if it
    has >= `min_obs` errors and 0 successes anywhere (an airtight, env-authored wall)."""
    stats = fold_tool_stats(corpus)
    return {t: s.verdict(min_obs=min_obs, curable_ratio=curable_ratio) for t, s in stats.items()}


def walled_tools(
    corpus: Iterable[Iterable[ToolEvent]], *, min_obs: int = 3
) -> set:
    """Convenience: just the set of WALLED tool names (for split routing / gating)."""
    stats = fold_tool_stats(corpus)
    return {t for t, s in stats.items()
            if s.err >= min_obs and not s.is_curable_for_split()}


# ---------------------------------------------------------------------------
# Per-run thrash detection (which tools the agent dead-ended on) + the split.
# ---------------------------------------------------------------------------
def thrash_tools(run: Sequence[ToolEvent], *, min_failures: int = 2) -> List[str]:
    """The tools this run THRASHED on: a tool with >= `min_failures` structured errors whose
    LATEST own result is still an error (the agent is in the hole right now, not recovered).
    This is `dos_react.natural_thrash_gate`'s rule, lifted to the agnostic event stream — the
    same byte-clean signal, never a parallel look-alike (the events carry the env's verdict)."""
    by_tool: Dict[str, List[bool]] = defaultdict(list)
    for ev in run:
        if ev.tool_name:
            by_tool[ev.tool_name].append(ev.is_error)
    out = []
    for tn, flags in by_tool.items():
        if sum(flags) >= min_failures and flags and flags[-1]:
            out.append(tn)
    return out


def classify_run(
    run: Sequence[ToolEvent],
    witness: Mapping[str, Verdict],
    *,
    min_failures: int = 2,
) -> Feasibility:
    """Route a run into its population class. A run is CURABLE if it thrashed on ANY tool that is
    not WALLED (conversion is coherent there); WALLED if it thrashed ONLY on walled tools; else
    NO_THRASH. The asymmetry is deliberate: a single curable thrash makes the run CURABLE, so a
    cure is never scored against a run it could in principle help, and a wall is only declared
    when EVERY thrash in the run is on an infeasible tool."""
    tt = thrash_tools(run, min_failures=min_failures)
    if not tt:
        return Feasibility.NO_THRASH
    walled = {t for t in tt if witness.get(t) is Verdict.WALLED}
    curable = [t for t in tt if witness.get(t) is not Verdict.WALLED]
    if curable:
        return Feasibility.CURABLE
    if walled:
        return Feasibility.WALLED
    return Feasibility.NO_THRASH


# ---------------------------------------------------------------------------
# Reporting helper — the human-facing 3-way breakdown a benchmark prints.
# ---------------------------------------------------------------------------
@dataclass
class SplitReport:
    """The split of a paired-run corpus into the three populations, with each run's id."""

    walled: List[str] = field(default_factory=list)
    curable: List[str] = field(default_factory=list)
    no_thrash: List[str] = field(default_factory=list)

    def add(self, run_id: str, cls: Feasibility) -> None:
        {Feasibility.WALLED: self.walled,
         Feasibility.CURABLE: self.curable,
         Feasibility.NO_THRASH: self.no_thrash}[cls].append(run_id)

    def counts(self) -> Dict[str, int]:
        return {"WALLED": len(self.walled), "CURABLE": len(self.curable),
                "NO_THRASH": len(self.no_thrash)}


def split_corpus(
    runs: Mapping[str, Sequence[ToolEvent]],
    witness: Mapping[str, Verdict],
    *,
    min_failures: int = 2,
) -> SplitReport:
    """Split a {run_id -> events} mapping into the three populations against the witness."""
    rep = SplitReport()
    for run_id, events in runs.items():
        rep.add(run_id, classify_run(events, witness, min_failures=min_failures))
    return rep


__all__ = [
    "ToolEvent", "Verdict", "Feasibility", "ToolStat",
    "fold_tool_stats", "feasibility_witness", "walled_tools",
    "thrash_tools", "classify_run", "SplitReport", "split_corpus",
]
