"""The $0 offline REWIND-CEILING estimator — an UPPER BOUND on the pass-rate lift a DOS
REWIND/BACKJUMP (docs/164 F1.5) could buy on the frozen Toolathlon corpus, with ZERO API spend,
AND its disjointness from the WARN re-surface ceiling (`conversion_ceiling.py`).

WHY THIS EXISTS — the mechanism `conversion_ceiling` could not measure
=====================================================================
`conversion_ceiling.py` sizes the WARN RE-SURFACE ceiling: of FAILED runs, how many fire a detector
AND are "recoverable" because the value the agent needed was ALREADY in its trajectory and a WARN
re-presenting it could unblock. A WARN *appends* a message; it authors no step (the docs/143 −9pp
lesson, made structural). That ceiling is small (165 of 5,228 failed = +2.40pp corpus) and on the
frozen corpus it is concentrated in `dangling_intent` on weak models; on strong models it is ~0.

REWIND is a DIFFERENT mechanism (docs/164 F1.5, `dos/rewind.py`). It *subtracts* the polluted
context: roll the transcript back to a kernel-minted checkpoint BEFORE a dead-end branch, EXCISE the
dead-end turns, and re-enter with a byte-clean no-good note (the kernel's typed verdict + the env's
own error excerpt — NEVER a generated critique). It is the SUBTRACT sibling of WARN's RE-SURFACE.

The thesis this estimator tests on real data:

  > A WARN cannot fix a failure caused by the agent COMMITTING TO A WRONG APPROACH early, because
  > re-surfacing a value does not un-commit the path — the accreted dead-end turns keep pulling the
  > agent back into the same hole (the chronological-backtracking trap docs/164 names). When the env
  > keeps REJECTING the agent's repeated mutation (a wall of error results), there is no usable value
  > to re-surface; the only thing that helps is SUBTRACTING the wrong branch. That failure class is
  > DISJOINT from the WARN-recoverable class by construction — WARN needs a *usable* looped value,
  > rewind needs an *error-dominated* looped value — so the two ceilings cannot double-count.

WHAT MAKES A RUN "REWIND-FIXABLE" (the load-bearing, byte-clean definition)
===========================================================================
A FAILED run is REWIND-FIXABLE iff it exhibits a DEAD-END MUTATION BRANCH — the agent committed to a
mutation (a write/patch/post/update/create/upload/edit/scale/delete tool) and THRASHED on it while
the ENVIRONMENT kept rejecting it:

  (1) MUTATION TOOL. The looping tool is a state-mutating tool (a fixed name-shape grammar). A
      read/list/query loop is NOT a dead-end branch — re-reading is the docs/145 WARN class, and an
      eventual-consistency poll (`status: converting`) is a legitimate repeat. Only a MUTATION the
      env rejects is a committed-to-a-wrong-write dead end.

  (2) THRASH, NOT A SINGLE STUCK CALL. The tool is issued >= MIN_CALLS times with >= MIN_DISTINCT_ARGS
      distinct arg-shapes. The distinct-args requirement is what separates a DEAD-END BRANCH (the
      agent keeps *trying variations* of a wrong approach) from a "can't-tell-it-succeeded" identical
      re-issue (the docs/145 tool_stream class, which a WARN re-surface — "you already did this" —
      addresses). A rewind targets the *branch*, so it needs evidence the agent explored a branch.

  (3) THE ENV REJECTED IT (the byte-clean, load-bearing gate). >= ERR_FRACTION of that mutation
      tool's ENV-AUTHORED results are errors / unusable (`is_struct_error` OR the broad
      `conversion_ceiling.is_usable_result` no-output/poll/tool-not-found grammar). This is the wall:
      the env kept saying "no". It is what makes the branch a DEAD END (vs a legitimate sequence of
      varied successful writes — writing 50 different cells to a sheet VARIES its args by design and
      is NOT a dead end, so SUCCESS-dominated thrash is excluded). It is also the DISJOINTNESS from
      WARN: a usable looped value (WARN's requirement) and an error-dominated looped value (rewind's
      requirement) are mutually exclusive — the two ceilings cannot overlap.

THE CHECKPOINT (where the offline backjump would land)
======================================================
The rewind target is the turn index of the FIRST call to the looping mutation tool: the backjump
excises the entire dead-end branch (every turn from the first thrash-call onward) and re-enters with
the env's own rejection bytes as the no-good note. This is the offline placement the live
`rewind.rewind_plan` would compute; the estimator reports HOW MANY turns would be subtracted (the
"forged context removed" magnitude, the same quantity `rewind_counterfactual.py` reports for the
EnterpriseOps gym), never that the agent then succeeds (conversion is a live question).

WHAT THIS IS AND IS NOT (the ceiling discipline, carried from conversion_ceiling)
=================================================================================
This is an UPPER BOUND, never a prediction. It assumes every rewind-fixable run would convert
fail->pass, which a real rewind will NEVER achieve (docs/144's live A/B converted a *fraction* of
even the winning arm; docs/172 pre-registers a modest live band). Read `max_lift_pp` as "you cannot
possibly beat this." The safe error is to UNDER-count (over-reject), which only LOWERS the ceiling —
so a run we are unsure about is NOT rewind-fixable. The estimator's headline is NOT its own ceiling
but the DISJOINTNESS: |rewind-fixable AND NOT warn-fixable| — the population a WARN structurally
cannot touch, which is the whole reason rewind is a distinct mechanism worth having.

BYTE-CLEANLINESS / PROVENANCE (the §5a line, same as tool_stream / conversion_ceiling)
======================================================================================
The load-bearing gate (3) reads ENV-AUTHORED result bytes only (the gym MCP server produced them;
the judged agent did not author the IDENTITY of its repeated results). The tool NAME and arg-shapes
in (1)/(2) are agent-authored, but classifying them can only EXCLUDE a run (a mutation-thrash filter
removes leverage; it can never be a satisfaction predicate — the established safe-direction rule).
The agent cannot forge its way into "rewind-fixable": it cannot make the env return errors it did not
return. So the verdict is provenance-of-an-env-rejection, never a forgeable "I'm stuck" self-report.

  python -m benchmark.toolathlon.rewind_ceiling            # the per-model + corpus ceiling + disjointness
  python -m benchmark.toolathlon.rewind_ceiling --json     # the full result as JSON
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .conversion_ceiling import classify_recoverability, is_usable_result, load_cached_corpus
from .dataset import DEFAULT_CACHE
from .replay import run_row, traj_tool_steps
from .trajectory import Trajectory, _tool_msg_name, is_struct_error

# ---------------------------------------------------------------------------
# The dead-end-mutation grammar + the thrash thresholds (generic, documented).
# ---------------------------------------------------------------------------
# A mutation tool's name contains one of these stems. Deliberately a NAME-shape rule (not a fixed
# allow-list): a host's mutation tools are not enumerable in the kernel, and a stem match can only
# EXCLUDE a run from the ceiling (the safe direction), never admit a satisfaction predicate. Reads
# the agent-chosen tool NAME, which is agent-authored — but per the §5a safe-direction rule, using it
# only to FILTER (mutation vs read) removes leverage; the load-bearing gate is the env-authored (3).
_MUTATION_STEMS = (
    "patch", "post", "write", "update", "create", "upload", "put",
    "edit", "scale", "delete", "append", "insert", "send", "add",
)

# Thrash thresholds. MIN_CALLS=5 = the agent issued the mutation at least 5 times (a loop, not a
# single stuck call). ERR_FRACTION=0.6 = a majority of that tool's env results were rejections (the
# dead-end wall). All tuned for the SAFE direction (raising any only lowers the ceiling).
#
# THE BRANCH DISCRIMINATOR — env-authored, NOT agent-authored (the byte-clean fix, 2026-06-05).
# An adversarial pass caught that keying "branch vs re-issue" on distinct *args_digest* is a
# forgeable agent-byte read: `_normalize_args` collapses only key-ORDER, so cosmetic arg perturbation
# (trailing whitespace, int-vs-string, a benign extra field) mints a distinct args_digest while the
# env returns byte-identical bytes — an agent could promote itself from WARN-shape to rewind-only with
# zero new env-authored evidence. The MEASURED leak: 14 of 64 args-keyed runs had distinct_result=1
# (the env returned the IDENTICAL byte every call — the single-repeated-value WARN shape), e.g.
# gemini-2.5-pro/task-tracker posted 29 DIFFERENT args but got ONE identical error envelope back.
#
# So the PRIMARY discriminator is MIN_DISTINCT_RESULTS — distinct *result_digest* among the loop-tool
# calls (env-authored: the gym MCP server wrote those bytes). A genuine dead-end BRANCH gets >= 2
# DISTINCT env responses (different errors, or some success + some error — the agent explored a region
# and the env answered variously); a WARN-shaped wall gets ONE identical byte hammered N times. The
# agent cannot forge a second distinct env result it did not receive. MIN_DISTINCT_ARGS is RETAINED
# only as a labelled UPPER-VARIANT knob (the args-variety count is reported beside the byte-clean
# count + their gap, never AS the disjoint-from-WARN headline).
MIN_CALLS = 5
MIN_DISTINCT_RESULTS = 2   # PRIMARY, env-authored: distinct result_digest among loop-tool calls
MIN_DISTINCT_ARGS = 2      # upper-variant only (agent-authored; reported beside, never headlined)
ERR_FRACTION = 0.6

# THE EVENTUAL-CONSISTENCY / TRANSIENT-RETRY GUARD (an adversarial pass caught this, 2026-06-05).
# A 409 conflict "Please try again", a 429/rate-limit, a 503/timeout, or a "still converting" poll is a
# LEGITIMATE repeat — the env is telling the agent to RETRY THE SAME action, not that the action is a
# dead-end branch. Re-issuing IS the correct behavior; there is no wrong branch to subtract. A run
# whose rejection wall is dominated by these transient codes is EXCLUDED (it is the docs/145 honest
# hole, not a rewind target). MEASURED: this removed 5 of the 50 byte-clean runs — e.g.
# gemini-2.5-pro/task-tracker hammered notion-API-post-page 29× into a 409 conflict_error/"try again".
_RETRY_WALL = re.compile(
    r"\b409\b|\b429\b|\b503\b|conflict|please try again|\btry again\b|rate.?limit"
    r"|too many requests|temporarily unavailable|\btimeout\b|timed out"
    r"|\bstatus\b.{0,12}\bconverting\b",
    re.IGNORECASE,
)

# THE PERMISSION / ACCESS-WALL GUARD (the synthesis FIX 3, 2026-06-05). A mutation walled by a
# permission/access error (object_not_found, "shared with your integration", 403/forbidden, "not
# authorized") is NOT a committed-wrong-approach branch — the resource is unreachable to this agent
# regardless of how it phrases the write, so a backjump to a clean checkpoint buys nothing (the agent
# re-hits the same wall). Excluded (the honest direction). MEASURED: removed 2 of the 20.
_PERMISSION_WALL = re.compile(
    r"object_not_found|shared with your integration|permission denied|not authorized"
    r"|\bforbidden\b|access denied|unauthorized|insufficient permission|not shared"
    r"|\b403\b|\b401\b",
    re.IGNORECASE,
)


def _is_mutation_tool(name: str) -> bool:
    """True iff the tool name looks like a state MUTATION (a write), by the fixed stem grammar.

    A read/list/query/get loop is NOT a dead-end mutation branch — re-reading is the WARN/tool_stream
    class, and an eventual-consistency poll is a legitimate repeat. The stem match is content-blind
    over the agent-chosen NAME; per the safe-direction rule it only ever EXCLUDES (a non-mutation loop
    is dropped), so it adds no forgeable leverage. PURE."""
    n = (name or "").strip().lower()
    # Split on common tool-name separators so a stem matches a *segment*, not a coincidental substring
    # ("update" in "update_incident" yes; not "creategory"-style false hits — segment match is tighter).
    segments = re.split(r"[-_./:]", n)
    return any(any(seg == stem or seg.startswith(stem) for stem in _MUTATION_STEMS) for seg in segments)


# ---------------------------------------------------------------------------
# The rewind-fixable verdict over one trajectory.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RewindFix:
    """Whether a FAILED run exhibits a dead-end MUTATION branch a backjump could excise, plus the
    offline checkpoint placement + subtraction magnitude (never a conversion claim).

    `fixable` is the BYTE-CLEAN primary verdict (env-authored result-diversity). `args_variant` is the
    looser upper variant that also admits agent-authored args-only diversity — TRUE for every
    byte-clean run PLUS the forgeable-promotion runs; reported beside the primary, never as it. A run
    with `args_variant and not fixable` is a WARN-shaped wall promoted only by agent-chosen call
    shapes (the env returned one identical byte every call)."""

    fixable: bool                   # PRIMARY, byte-clean: >= MIN_DISTINCT_RESULTS env results
    args_variant: bool = False      # upper variant: also admits args-only diversity (agent-authored)
    loop_tool: str = ""             # the mutation tool that thrashed
    n_calls: int = 0                # how many times it was issued
    n_distinct_args: int = 0        # distinct arg-shapes (agent-authored — upper-variant signal only)
    n_distinct_results: int = 0     # distinct ENV result bytes (the byte-clean branch signal)
    n_results: int = 0              # env-authored results observed for it
    n_err_results: int = 0          # of those, errors/unusable (the rejection wall)
    checkpoint_turn: int = -1       # message index of the FIRST thrash call (the backjump target)
    dropped_turns: int = 0          # turns from the checkpoint onward that a rewind would excise

    @property
    def err_fraction(self) -> float:
        return self.n_err_results / self.n_results if self.n_results else 0.0


def classify_rewind_fix(traj: Trajectory) -> RewindFix:
    """Classify whether `traj` is REWIND-FIXABLE (a dead-end mutation branch the env kept rejecting).

    PURE given the trajectory (the caller did the JSONL I/O). Reuses `traj_tool_steps` (the SSOT step
    extractor) and `is_struct_error`/`is_usable_result` (the SSOT result grammar) so it can never
    drift from the detectors.

    The BRANCH discriminator is ENV-AUTHORED (the byte-clean fix): a genuine dead-end branch gets
    >= MIN_DISTINCT_RESULTS DISTINCT env responses among the loop-tool calls (the env answered the
    agent's exploration variously — different errors, or some success + some error), which the agent
    cannot forge. The agent-authored args-diversity is computed too but only powers the labelled
    `args_variant` upper bound, never the primary `fixable`. The mutation/err gates read agent tool
    name + env result bytes respectively; the former is exclusion-only (safe direction)."""
    steps = traj_tool_steps(traj)
    if not steps:
        return RewindFix(fixable=False)

    # Per-tool: call count, distinct ENV result-digests (byte-clean branch signal), distinct agent
    # arg-shapes (upper-variant signal only).
    counts: Counter = Counter()
    resultsets: dict[str, set] = defaultdict(set)
    argsets: dict[str, set] = defaultdict(set)
    for s in steps:
        counts[s.tool_name] += 1
        resultsets[s.tool_name].add(s.result_digest)
        argsets[s.tool_name].add(s.args_digest)

    # The candidate looping mutation tool: a mutation issued >= MIN_CALLS whose ENV results show
    # >= MIN_DISTINCT_RESULTS distinct bytes (the byte-clean branch gate). If several qualify, take
    # the one with the most calls (the dominant dead-end branch).
    candidates = [
        tool for tool, n in counts.items()
        if _is_mutation_tool(tool) and n >= MIN_CALLS and len(resultsets[tool]) >= MIN_DISTINCT_RESULTS
    ]
    # The args-variety UPPER variant also admits a mutation loop whose ENV results are identical but
    # whose AGENT args varied (the forgeable promotion — measured, reported, never headlined).
    args_candidates = [
        tool for tool, n in counts.items()
        if _is_mutation_tool(tool) and n >= MIN_CALLS and len(argsets[tool]) >= MIN_DISTINCT_ARGS
    ]
    if not args_candidates:
        return RewindFix(fixable=False)
    # Pick the dominant loop tool from the (wider) args-candidate pool so the upper-variant path also
    # has a loop_tool to report; `fixable` is decided by whether it clears the ENV-authored gate.
    loop_tool = max(args_candidates, key=lambda t: counts[t])

    # Gate (3): the ENV-AUTHORED rejection wall. Read the result content of every `tool` message that
    # answered a call to loop_tool, and count how many are errors/unusable. This is the load-bearing,
    # non-forgeable evidence — the agent cannot make the env return errors it did not return.
    results = [
        str(m.get("content", ""))
        for m in traj.messages
        if m.get("role") == "tool" and _tool_msg_name(m, traj.messages) == loop_tool
    ]
    if not results:
        return RewindFix(fixable=False)
    err_results = [c for c in results if is_struct_error(c) or not is_usable_result(c)]
    n_err = len(err_results)
    if n_err / len(results) < ERR_FRACTION:
        # SUCCESS-dominated: a legitimate sequence of varied successful writes (e.g. many cells to a
        # sheet), NOT a dead end. Excluded — the env did NOT reject it. (The honest direction: this
        # exclusion is the whole reason the ceiling is small and not the inflated naive thrash count.)
        return RewindFix(fixable=False)

    # EXCLUSION (a): the EVENTUAL-CONSISTENCY / transient-retry wall. If a majority of the rejections
    # are transient-retry codes (409/429/503/conflict/"try again"/rate-limit/converting), the env is
    # asking the agent to RETRY THE SAME action, not signalling a dead-end branch — re-issuing is
    # correct, there is nothing to subtract. Excluded (the honest direction; the err-grammar's broad
    # 'error/failed' match would otherwise count these as a wall and inflate the ceiling — the UNSAFE
    # direction here, opposite to conversion_ceiling where broad rejection lowers its ceiling).
    if n_err and sum(1 for c in err_results if _RETRY_WALL.search(c)) / n_err >= 0.5:
        return RewindFix(fixable=False)

    # EXCLUSION (a2): the PERMISSION / ACCESS wall. If a majority of the rejections are permission/
    # access errors (object_not_found / "shared with your integration" / 403 / "not authorized"), the
    # resource is unreachable to this agent regardless of how it phrases the write — a backjump buys
    # nothing (the agent re-hits the same wall). Excluded (the honest direction). MEASURED: removed 2.
    if n_err and sum(1 for c in err_results if _PERMISSION_WALL.search(c)) / n_err >= 0.5:
        return RewindFix(fixable=False)

    # EXCLUSION (b): an EARLY SUCCESS. If the FIRST call to the loop tool returned a usable (non-error)
    # result, a real write LANDED before the wall — there is no pure dead-end branch, and rewinding to
    # before it would DELETE real progress (the "the wrong commit is the envelope, not the branch"
    # residual). Conservative over-rejection (the honest upper-bound direction). MEASURED: this removed
    # 13 of the 50 — e.g. arrange-workspace's first create_directory succeeded, then the agent committed
    # to a wrong nested path. (A subtler design could rewind to AFTER the early success; that is a live
    # question this offline upper bound does not adjudicate — it excludes, the safe direction.)
    if is_usable_result(results[0]) and not is_struct_error(results[0]):
        return RewindFix(fixable=False)

    # The checkpoint: the message index of the FIRST call to loop_tool (the backjump target — excise
    # the dead-end branch from here onward). Find it by walking assistant tool_calls in order.
    checkpoint_turn = -1
    for i, m in enumerate(traj.messages):
        if m.get("role") != "assistant":
            continue
        for tc in (m.get("tool_calls") or []):
            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
            if str(fn.get("name", "")) == loop_tool:
                checkpoint_turn = i
                break
        if checkpoint_turn >= 0:
            break
    dropped = max(0, len(traj.messages) - checkpoint_turn) if checkpoint_turn >= 0 else 0

    # PRIMARY (byte-clean) `fixable`: the dominant loop tool's ENV results show >= MIN_DISTINCT_RESULTS
    # distinct bytes (a genuine branch the env answered variously — non-forgeable). The args-variety
    # path always reached here (loop_tool came from args_candidates), so `args_variant` is True for
    # every run that clears the err gate; `fixable` adds the env-result-diversity requirement on top.
    n_distinct_results = len(resultsets[loop_tool])
    byte_clean = n_distinct_results >= MIN_DISTINCT_RESULTS

    return RewindFix(
        fixable=byte_clean,
        args_variant=True,
        loop_tool=loop_tool,
        n_calls=counts[loop_tool],
        n_distinct_args=len(argsets[loop_tool]),
        n_distinct_results=n_distinct_results,
        n_results=len(results),
        n_err_results=n_err,
        checkpoint_turn=checkpoint_turn,
        dropped_turns=dropped,
    )


# ---------------------------------------------------------------------------
# Per-model + corpus ceiling + the DISJOINTNESS-from-WARN report.
# ---------------------------------------------------------------------------
@dataclass
class ModelRewindCeiling:
    """One model's rewind-ceiling row + its disjointness from the WARN-recoverable set.

      rewind_fixable    — FAILED runs with a BYTE-CLEAN dead-end mutation branch (env-rejected thrash
                          with >= MIN_DISTINCT_RESULTS distinct env responses). The PRIMARY count.
      args_variant      — the looser UPPER variant (also admits agent-authored args-only diversity).
                          rewind_fixable <= args_variant; the gap = forgeable agent-byte promotions.
      warn_fixable      — FAILED runs the WARN re-surface ceiling marks recoverable (conversion_ceiling).
      only_rewind       — rewind_fixable AND NOT warn_fixable: the population a WARN cannot touch.
      both              — in BOTH sets (expected ~0 by construction: usable vs error-dominated loop).
      max_lift_pp       — rewind_fixable / n_tasks * 100 (the UPPER BOUND if every one converted).
      only_rewind_pp    — only_rewind / n_tasks * 100 (the NON-OVERLAPPING headroom — the headline).
    """

    model: str
    n_tasks: int = 0
    passes: int = 0
    rewind_fixable: int = 0          # SOUND-GATES primary: byte-clean + retry/perm/early + never-solved
    args_variant: int = 0            # looser upper variant (agent-byte inflated; reported beside)
    fire_gated: int = 0              # the most-conservative variant: ALSO requires a tool_stream fire
    warn_fixable: int = 0
    only_rewind: int = 0
    both: int = 0
    turns_subtracted: int = 0   # total dead-end turns a rewind would excise across fixable runs

    @property
    def pass_rate(self) -> float:
        return self.passes / self.n_tasks if self.n_tasks else 0.0

    @property
    def max_lift_pp(self) -> float:
        return 100.0 * self.rewind_fixable / self.n_tasks if self.n_tasks else 0.0

    @property
    def only_rewind_pp(self) -> float:
        return 100.0 * self.only_rewind / self.n_tasks if self.n_tasks else 0.0

    @property
    def args_promotions(self) -> int:
        """The forgeable agent-byte promotions: args-variant minus byte-clean (the leak the fix closes)."""
        return self.args_variant - self.rewind_fixable

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "n_tasks": self.n_tasks,
            "pass_rate_pct": round(100.0 * self.pass_rate, 2),
            "rewind_fixable": self.rewind_fixable,
            "fire_gated": self.fire_gated,
            "args_variant_upper": self.args_variant,
            "args_promotions": self.args_promotions,
            "warn_fixable": self.warn_fixable,
            "only_rewind": self.only_rewind,
            "both_rewind_and_warn": self.both,
            "turns_subtracted": self.turns_subtracted,
            "max_lift_pp": round(self.max_lift_pp, 2),
            "only_rewind_pp": round(self.only_rewind_pp, 2),
        }


@dataclass
class RewindCeilingResult:
    """The whole rewind-ceiling result — per-model rows + the corpus ceiling + disjointness."""

    models: list = field(default_factory=list)  # list[ModelRewindCeiling], capability-ascending
    n_records: int = 0
    n_labeled: int = 0

    @property
    def corpus_n_tasks(self) -> int:
        return sum(m.n_tasks for m in self.models)

    @property
    def corpus_rewind_fixable(self) -> int:
        return sum(m.rewind_fixable for m in self.models)

    @property
    def corpus_args_variant(self) -> int:
        return sum(m.args_variant for m in self.models)

    @property
    def corpus_fire_gated(self) -> int:
        return sum(m.fire_gated for m in self.models)

    @property
    def corpus_args_promotions(self) -> int:
        """Forgeable agent-byte promotions corpus-wide = args-variant − byte-clean (the leak closed)."""
        return self.corpus_args_variant - self.corpus_rewind_fixable

    @property
    def corpus_warn_fixable(self) -> int:
        return sum(m.warn_fixable for m in self.models)

    @property
    def corpus_only_rewind(self) -> int:
        return sum(m.only_rewind for m in self.models)

    @property
    def corpus_both(self) -> int:
        return sum(m.both for m in self.models)

    @property
    def corpus_turns_subtracted(self) -> int:
        return sum(m.turns_subtracted for m in self.models)

    @property
    def corpus_ceiling_pp(self) -> float:
        n = self.corpus_n_tasks
        return 100.0 * self.corpus_rewind_fixable / n if n else 0.0

    @property
    def corpus_only_rewind_pp(self) -> float:
        n = self.corpus_n_tasks
        return 100.0 * self.corpus_only_rewind / n if n else 0.0

    def best_regime(self) -> Optional["ModelRewindCeiling"]:
        """The model with the most rewind headroom (highest only_rewind, ties by rewind_fixable)."""
        pool = [m for m in self.models if m.rewind_fixable > 0]
        if not pool:
            return None
        return max(pool, key=lambda m: (m.only_rewind, m.rewind_fixable))

    def to_dict(self) -> dict:
        best = self.best_regime()
        return {
            "n_records": self.n_records,
            "n_labeled": self.n_labeled,
            "corpus": {
                "n_tasks": self.corpus_n_tasks,
                "rewind_fixable_sound_gates": self.corpus_rewind_fixable,
                "fire_gated_conservative": self.corpus_fire_gated,
                "args_variant_upper": self.corpus_args_variant,
                "args_promotions": self.corpus_args_promotions,
                "warn_fixable": self.corpus_warn_fixable,
                "only_rewind": self.corpus_only_rewind,
                "both_rewind_and_warn": self.corpus_both,
                "turns_subtracted": self.corpus_turns_subtracted,
                "ceiling_pp": round(self.corpus_ceiling_pp, 2),
                "only_rewind_pp": round(self.corpus_only_rewind_pp, 2),
            },
            "best_regime": best.model if best else None,
            "models": [m.to_dict() for m in self.models],
        }


def compute_rewind_ceiling(trajectories: Iterable[Trajectory]) -> RewindCeilingResult:
    """Fold the rewind-fixable + WARN-recoverable classifiers over every trajectory into the per-model
    + corpus rewind ceiling AND its disjointness from the WARN ceiling.

    Pure over the (already-parsed) trajectories (materialized once — two passes). A run is LABELED iff
    its oracle label is True/False; unlabeled (passed None) is excluded, never guessed. A fix counts
    only on a FAILED run. The disjointness is computed per run (rewind vs WARN-recoverable on the SAME
    run) so `only_rewind`/`both` are exact.

    THE GATE LADDER (the synthesis's sound fixes + the one contested choice, reported transparently):
      * `rewind_fixable` (the PRIMARY, "sound gates") = the byte-clean `classify_rewind_fix` (mutation +
        env-result-diversity + ≥60% err + retry-guard + permission-guard + early-success-guard) AND the
        NEVER-SOLVED gate (the task was solved by at least one run somewhere in the corpus — a task no
        model EVER solved is plausibly impossible, the "wrong commit is the envelope, not the branch"
        residual; crediting it would not be an upper bound on the NAMED mechanism). MEASURED: 20.
      * `fire_gated` (the MOST-CONSERVATIVE variant) = the above AND `run_row(traj).tool_stream_fired`
        (a consecutive identical-triple repeat). The synthesis sided with restoring this; this estimator
        REPORTS it as a variant rather than adopting it as the headline, because a varying-branch thrash
        (distinct env rejections, no consecutive identical run) IS a dead-end branch the rewind mechanism
        targets — gating it away conflates "no consecutive repeat" with "no branch" (§4 of docs/175).
        MEASURED: 8. The 20-vs-8 gap is the sensitivity to that one contested choice, shown not hidden.
      * `args_variant` = the looser agent-args-keyed upper bound (the forgeable-promotion audit)."""
    trajectories = list(trajectories)
    # Pre-pass: per-task pass count across the WHOLE corpus (for the never-solved gate). A task with
    # zero passes anywhere is plausibly impossible/mis-specified — not a rewind target.
    task_solved: dict[str, bool] = {}
    for traj in trajectories:
        if traj.passed is True:
            task_solved[traj.task_name] = True
        else:
            task_solved.setdefault(traj.task_name, False)

    by_model: dict[str, ModelRewindCeiling] = {}
    n_records = 0
    n_labeled = 0
    for traj in trajectories:
        n_records += 1
        if traj.passed is None:
            continue
        n_labeled += 1
        mc = by_model.setdefault(traj.model, ModelRewindCeiling(model=traj.model))
        mc.n_tasks += 1
        if traj.passed:
            mc.passes += 1
            continue  # a fix on a passed run cannot lift the pass-rate (skip the classify)
        # FAILED run: classify both mechanisms on the SAME run for an exact disjointness.
        rf = classify_rewind_fix(traj)
        warn = classify_recoverability(traj).any_recoverable
        if rf.args_variant:
            mc.args_variant += 1   # the looser upper count (agent-byte inflated)
        # The never-solved gate gates the SOUND-GATES primary (and everything below it).
        sound = rf.fixable and task_solved.get(traj.task_name, False)
        if sound:
            mc.rewind_fixable += 1
            mc.turns_subtracted += rf.dropped_turns
            # the most-conservative variant ALSO requires a consecutive-repeat tool_stream fire
            if run_row(traj).tool_stream_fired:
                mc.fire_gated += 1
        if warn:
            mc.warn_fixable += 1
        if sound and warn:
            mc.both += 1
        elif sound and not warn:
            mc.only_rewind += 1
    models = sorted(by_model.values(), key=lambda m: (m.pass_rate, m.model))
    return RewindCeilingResult(models=models, n_records=n_records, n_labeled=n_labeled)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def _print_summary(s: RewindCeilingResult) -> None:
    print(f"# {s.n_records:,} records · {s.n_labeled:,} labeled · {len(s.models)} models")
    print(
        "# REWIND CEILING = an UPPER BOUND. Assumes EVERY rewind-fixable dead-end branch converts "
        "fail->pass — a real rewind achieves only a FRACTION (docs/172 pre-registers a modest band)."
    )
    print(
        "# rewfix (PRIMARY, sound gates) = a FAILED, EVER-SOLVED-task run where a MUTATION thrashed "
        "(>= {c} calls) drawing >= {r} DISTINCT env responses (non-forgeable branch), >= {e:.0%} "
        "rejections, NOT a retry/permission wall, NO early success.".format(
            c=MIN_CALLS, r=MIN_DISTINCT_RESULTS, e=ERR_FRACTION)
    )
    print(
        "# firegate = the MOST-CONSERVATIVE variant (rewfix AND a consecutive tool_stream fire). "
        "Reported, NOT headlined — a varying-branch thrash with no consecutive repeat is still a branch."
    )
    print(
        "# argsvar = the LOOSER upper bound (agent-args-keyed). gap (argsvar - rewfix) = forgeable "
        "agent-byte promotions, NEVER headlined. only_rw = rewfix AND NOT warn-fixable (WARN cannot touch)."
    )
    print()
    hdr = (
        f"{'model':<26} {'pass%':>6} {'tasks':>6} {'rewfix':>7} {'firegt':>7} {'argsvar':>8} "
        f"{'warnfix':>8} {'only_rw':>8} {'both':>5} {'max_pp':>7} {'only_pp':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for m in s.models:
        print(
            f"{m.model:<26} {100*m.pass_rate:6.1f} {m.n_tasks:6d} {m.rewind_fixable:7d} "
            f"{m.fire_gated:7d} {m.args_variant:8d} {m.warn_fixable:8d} {m.only_rewind:8d} {m.both:5d} "
            f"{m.max_lift_pp:7.2f} {m.only_rewind_pp:8.2f}"
        )
    print("-" * len(hdr))
    print(
        f"{'CORPUS':<26} {'':>6} {s.corpus_n_tasks:6d} {s.corpus_rewind_fixable:7d} "
        f"{s.corpus_fire_gated:7d} {s.corpus_args_variant:8d} {s.corpus_warn_fixable:8d} "
        f"{s.corpus_only_rewind:8d} {s.corpus_both:5d} {s.corpus_ceiling_pp:7.2f} {s.corpus_only_rewind_pp:8.2f}"
    )
    best = s.best_regime()
    print()
    print(
        f"DISJOINTNESS — the headline: rewind-fixable={s.corpus_rewind_fixable} (sound gates), "
        f"warn-fixable={s.corpus_warn_fixable}, "
        f"BOTH={s.corpus_both} (MEASURED, not asserted — usable-loop vs error-dominated-loop are exclusive), "
        f"ONLY-rewind={s.corpus_only_rewind} (+{s.corpus_only_rewind_pp:.2f}pp a WARN structurally CANNOT touch)."
    )
    print(
        f"GATE-SENSITIVITY LEDGER (the honest range): sound-gates={s.corpus_rewind_fixable} "
        f"(+{s.corpus_ceiling_pp:.2f}pp) is the PRIMARY; the most-conservative fire-gated variant="
        f"{s.corpus_fire_gated} — the {s.corpus_rewind_fixable - s.corpus_fire_gated}-run gap is the "
        f"varying-branch thrash that a (contested) tool_stream-fire precondition would discard. "
        f"args-variant upper={s.corpus_args_variant} (gap {s.corpus_args_promotions} = forgeable agent-byte "
        f"promotions, removed from the headline)."
    )
    print(
        f"SUBTRACTION MAGNITUDE: across the {s.corpus_rewind_fixable} sound-gates rewind-fixable runs a "
        f"backjump would excise {s.corpus_turns_subtracted:,} dead-end turns of accreted context."
    )
    if best is not None:
        print(
            f"BEST A/B TARGET: {best.model} — {best.only_rewind} only-rewind runs "
            f"(ceiling +{best.only_rewind_pp:.2f}pp). Where a paid rewind A/B has the most non-WARN headroom."
        )
    print(
        f"CORPUS REWIND CEILING: at most +{s.corpus_ceiling_pp:.2f}pp pass-rate lift if EVERY dead-end "
        f"branch converted (+{s.corpus_only_rewind_pp:.2f}pp of it WARN cannot reach). The real lift is a "
        f"FRACTION — do not overclaim (docs/172)."
    )


def main(argv: Optional[list] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 trap (Windows console)
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--cache", type=Path, default=DEFAULT_CACHE,
        help="directory of cached _data/*.jsonl trajectories (offline; no download)",
    )
    ap.add_argument("--json", action="store_true", help="print the full RewindCeilingResult as JSON")
    args = ap.parse_args(argv)

    if not args.cache.exists() or not any(args.cache.glob("*.jsonl")):
        ap.error(f"no cached trajectories under {args.cache} — run run_replay.py --all to populate _data/")

    s = compute_rewind_ceiling(load_cached_corpus(args.cache))

    if args.json:
        print(json.dumps(s.to_dict(), indent=2))
        return 0

    _print_summary(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
