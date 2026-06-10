"""_precision_ground — the GROUND-TRUTH the curable-conversion precision-gate analysis rests on.

docs/205 §7 (the FIRING-PRECISION lever). The measured verdict on the schema_refresh cure is:
it CONVERTS where aimed (+2 on the curable slice) but is NET-NEGATIVE (-5 overall, -7 on
baseline-passing runs) because injecting the directive turn perturbs runs that were ALREADY ON
TRACK. The named next lever is FIRING PRECISION: gate on "would-fail", not merely "thrashed".

This module establishes the ground truth that lever needs:
  * which none-arm runs the K=2 curable thrash gate WOULD fire on (the cure's target set),
  * the fire-TIME env bytes (only what was seen UP TO AND INCLUDING the Kth error — never the
    run's final outcome, which is the LABEL, not a predictor),
  * the ground-truth "would-fail" label = the PAIRED none-arm overall_success, and
  * whether the cure ACTUALLY fired in the refresh arm (the dos_schema_refresh event).

It REUSES the byte-clean grammar from the benchmark modules (never reinvents _is_struct_error):
  - dos_react.natural_thrash_gate / _is_struct_error / _result_text / _is_blocked_result
  - feasibility_witness.feasibility_witness  (CURABLE = ok>=1, WALLED = ok==0)
  - schema_refresh.extract_corrective / refresh_directive  (the SCHEMA-kind classifier + framing)

CORPUS SHAPE (measured, honest caveats):
  * 88 files per arm, ONE run per file. The pairing key benchmark_config.user_prompt has only
    11 DISTINCT values, each replicated 8 times (88 = 11 reps-of-8). A dict keyed by user_prompt
    would silently drop 7 of every 8 runs — so load_fire_set() keys by user_prompt but keeps ALL
    8 reps under each, and the rep-level flips (the well-defined per-run help/hurt) are computed
    by FILENAME, which is byte-identical across arms (results_<task-id>__repN.json).
  * The DBs are RE-SEEDED fresh per run (NOT verifier-paired): filename pairing is NOMINAL
    (same task seed + rep index), not a guarantee the two arms saw the identical hidden state.
  * The cure only fires on a natural_thrash_gate hit whose env corrective renders a NON-EMPTY
    refresh_directive (OPAQUE -> "" -> no fire). The live cure does NOT re-check the feasibility
    witness, so it can fire on a WALLED tool too; this module's fire_set_none honors the task
    definition exactly: gate fires on a CURABLE-kind tool (witness ok>=1).

Run as __main__ to print the headline counts. Downstream probes IMPORT load_fire_set().
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# REUSE the byte-clean grammar — never reinvent _is_struct_error / the gate.
from dos_react import (  # noqa: E402
    natural_thrash_gate,
    _is_struct_error,
    _result_text,
    _is_blocked_result,
)
from feasibility_witness import feasibility_witness  # noqa: E402
from schema_refresh import extract_corrective, refresh_directive, KIND_SCHEMA  # noqa: E402

# ---------------------------------------------------------------------------
# Corpus locations (Windows-native paths — the bench runs under win32 python).
# ---------------------------------------------------------------------------
_AB_ROOT = os.path.join(_HERE, "live_results_curable_schema_ab")
NONE_GLOB = os.path.join(_AB_ROOT, "none", "results_*.json")
REFRESH_GLOB = os.path.join(_AB_ROOT, "schema_refresh", "results_*.json")
ALL_GLOB = os.path.join(_AB_ROOT, "*", "results_*.json")

# K for the natural thrash gate (the documented K=2 "natural_thrash_gate").
THRASH_K = 2


# ---------------------------------------------------------------------------
# Per-arm, per-file reader. One run per file; the pairing key + outcome live at
# the FILE top level (benchmark_config.user_prompt), NOT inside the run dict.
# ---------------------------------------------------------------------------
def _iter_arm(arm_glob: str):
    """Yield (basename, user_prompt, run_dict) for every results_*.json in an arm."""
    for f in sorted(glob.glob(arm_glob)):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        bc = d.get("benchmark_config") or {}
        up = bc.get("user_prompt")
        runs = d.get("runs") or []
        if not runs:
            continue
        yield os.path.basename(f), up, runs[0]


def _cure_event_present(run: dict) -> bool:
    """True iff the cure's dos_schema_refresh event appears in conversation_flow (it ACTUALLY
    fired in this refresh-arm run)."""
    for e in run.get("conversation_flow") or []:
        if isinstance(e, dict) and e.get("type") == "dos_schema_refresh":
            return True
    return False


def curable_tool_set(corpus_glob: str = ALL_GLOB) -> set:
    """CURABLE tools = feasibility_witness ok>=1 (a successful path exists somewhere in the
    corpus). Computed over BOTH arms (the witness is env-authored, cross-run). Byte-clean."""
    return {t for t, ok, _er in feasibility_witness(corpus_glob) if ok >= 1}


# ---------------------------------------------------------------------------
# Fire-time evidence. The K=2 gate trips at the Kth structured error of a tool.
# A would-fail predicate may use ONLY bytes seen up to and including that Kth
# error — never the run's final outcome (that is the label).
# ---------------------------------------------------------------------------
def _fire_time_prefix(tool_results: list, tool_name: str, k: int = THRASH_K) -> Optional[int]:
    """Index (into tool_results) of the Kth structured error of `tool_name`, or None if the
    tool never reaches K errors. This is the FIRE-TIME boundary: bytes at indices [0..return]
    are admissible to a would-fail predictor; bytes after it are NOT (the future)."""
    seen = 0
    for i, tr in enumerate(tool_results):
        if str(tr.get("tool_name", "")) != tool_name:
            continue
        if _is_blocked_result(tr):
            continue
        if _is_struct_error(_result_text(tr)):
            seen += 1
            if seen >= k:
                return i
    return None


def _curable_gate_hits(tool_results: list, curable: set, k: int = THRASH_K
                       ) -> List[Tuple[str, int, str, str]]:
    """Every CURABLE-tool natural_thrash_gate hit in a run. Returns a list of
    (tool_name, n_failures, fire_time_excerpt, corrective_kind):
      * fire_time_excerpt = the Kth-error env bytes (redacted, <=200 chars) — the gate's own
        latest-error excerpt is the latest error; for an HONEST fire-time read we re-derive the
        excerpt from the Kth error itself (bytes seen UP TO the gate trip), not a later one.
      * corrective_kind = extract_corrective(...).kind over those fire-time bytes (SCHEMA tells
        us the cure would emit a non-empty directive).
    natural_thrash_gate is what the live cure keys on (same-tool >=K structured errors, latest
    still erroring); we additionally require the tool to be CURABLE (the task's fire_set defn)."""
    names = sorted({str(tr.get("tool_name", "")) for tr in tool_results})
    hits: List[Tuple[str, int, str, str]] = []
    for nm in names:
        if not nm or nm not in curable:
            continue
        gate = natural_thrash_gate(tool_results, nm, min_failures=k)
        if gate is None:
            continue
        n_fail, _gate_excerpt = gate
        # FIRE-TIME excerpt: the Kth error itself (not the run's latest), so the bytes honor the
        # "up to and including the Kth error" rule rather than peeking at later results.
        kth = _fire_time_prefix(tool_results, nm, k)
        if kth is None:
            # gate fired but K-prefix not found (shouldn't happen) — fall back to gate excerpt.
            excerpt = _gate_excerpt
            kind = extract_corrective(_gate_excerpt).kind
        else:
            kth_text = _result_text(tool_results[kth])
            corr = extract_corrective(kth_text)
            excerpt = (corr.raw or kth_text)[:200]
            kind = corr.kind
        hits.append((nm, n_fail, excerpt, kind))
    return hits


# ---------------------------------------------------------------------------
# The per-prompt record. Keyed by user_prompt (the task's pairing key) but it
# carries ALL reps (8 each) so nothing is silently dropped, plus rep-level flips
# by filename (the well-defined per-run help/hurt that yields the net -5).
# ---------------------------------------------------------------------------
@dataclass
class RepRecord:
    basename: str
    none_success: Optional[bool] = None
    refresh_success: Optional[bool] = None
    none_fires: bool = False          # K=2 gate fires on a CURABLE tool in the none arm
    refresh_fired: bool = False       # dos_schema_refresh event present in the refresh arm
    thrash_tools: tuple = ()          # CURABLE tool name(s) the gate fired on (none arm)
    fire_excerpts: tuple = ()         # fire-TIME env error excerpt(s) (bytes up to Kth error)
    fire_kinds: tuple = ()            # extract_corrective kind(s) over the fire-time bytes


@dataclass
class PromptRecord:
    prompt: str
    reps: List[RepRecord] = field(default_factory=list)

    # ---- prompt-level rollups (the duplicate-aware aggregates) ----
    @property
    def n_reps(self) -> int:
        return len(self.reps)

    @property
    def none_success(self) -> Optional[bool]:
        """Prompt-level 'would-pass' label: ANY none-arm rep passed. (8 reps; majority/any both
        reported in __main__. 'any pass' is the most generous would-pass — conservative for a
        would-FAIL gate, i.e. it under-counts would-fail.)"""
        vals = [r.none_success for r in self.reps if r.none_success is not None]
        if not vals:
            return None
        return any(vals)

    @property
    def none_pass_rate(self) -> float:
        vals = [r.none_success for r in self.reps if r.none_success is not None]
        return (sum(1 for v in vals if v) / len(vals)) if vals else 0.0

    @property
    def refresh_success(self) -> Optional[bool]:
        vals = [r.refresh_success for r in self.reps if r.refresh_success is not None]
        if not vals:
            return None
        return any(vals)

    @property
    def refresh_pass_rate(self) -> float:
        vals = [r.refresh_success for r in self.reps if r.refresh_success is not None]
        return (sum(1 for v in vals if v) / len(vals)) if vals else 0.0

    @property
    def none_fires(self) -> bool:
        """Would the gate fire in the none arm for this prompt (on ANY rep)?"""
        return any(r.none_fires for r in self.reps)

    @property
    def refresh_fired(self) -> bool:
        return any(r.refresh_fired for r in self.reps)

    @property
    def thrash_tools(self) -> tuple:
        s = set()
        for r in self.reps:
            s.update(r.thrash_tools)
        return tuple(sorted(s))

    @property
    def fire_excerpts(self) -> tuple:
        out: List[str] = []
        for r in self.reps:
            out.extend(r.fire_excerpts)
        return tuple(out)


def load_fire_set(none_glob: str = NONE_GLOB,
                  refresh_glob: str = REFRESH_GLOB,
                  all_glob: str = ALL_GLOB,
                  k: int = THRASH_K) -> List[PromptRecord]:
    """The reusable entry point. Returns a list of per-prompt PromptRecords, each carrying all
    reps with: none_success, refresh_success (None if no rep-paired file), none_fires (would the
    K=2 curable thrash gate fire in the none arm), refresh_fired (did the cure event appear),
    the thrashing CURABLE tool name(s), and the fire-TIME error excerpt(s) (env bytes up to the
    Kth error). Rep pairing is by FILENAME (byte-identical across arms); prompt pairing is by
    benchmark_config.user_prompt (8 reps per prompt — none are dropped)."""
    curable = curable_tool_set(all_glob)

    # rep-level reads, keyed by basename (the cross-arm filename pairing).
    none_by_base: Dict[str, dict] = {}
    refresh_by_base: Dict[str, dict] = {}
    none_prompt: Dict[str, str] = {}
    refresh_prompt: Dict[str, str] = {}

    for base, up, run in _iter_arm(none_glob):
        none_by_base[base] = run
        none_prompt[base] = up
    for base, up, run in _iter_arm(refresh_glob):
        refresh_by_base[base] = run
        refresh_prompt[base] = up

    all_bases = sorted(set(none_by_base) | set(refresh_by_base))

    # group reps by prompt. Prefer the none-arm prompt; fall back to the refresh-arm prompt.
    by_prompt: Dict[str, PromptRecord] = {}
    for base in all_bases:
        up = none_prompt.get(base, refresh_prompt.get(base))
        nrun = none_by_base.get(base)
        rrun = refresh_by_base.get(base)

        none_fires = False
        thrash_tools: tuple = ()
        fire_excerpts: tuple = ()
        fire_kinds: tuple = ()
        if nrun is not None:
            tr = nrun.get("tool_results") or []
            hits = _curable_gate_hits(tr, curable, k)
            if hits:
                none_fires = True
                thrash_tools = tuple(h[0] for h in hits)
                fire_excerpts = tuple(h[2] for h in hits)
                fire_kinds = tuple(h[3] for h in hits)

        rec = RepRecord(
            basename=base,
            none_success=(nrun.get("overall_success") if nrun is not None else None),
            refresh_success=(rrun.get("overall_success") if rrun is not None else None),
            none_fires=none_fires,
            refresh_fired=(_cure_event_present(rrun) if rrun is not None else False),
            thrash_tools=thrash_tools,
            fire_excerpts=fire_excerpts,
            fire_kinds=fire_kinds,
        )
        pr = by_prompt.setdefault(up, PromptRecord(prompt=up))
        pr.reps.append(rec)

    return [by_prompt[p] for p in sorted(by_prompt, key=lambda x: (x is None, x))]


# ---------------------------------------------------------------------------
# Headline counts (the schema fields the downstream probe needs).
# ---------------------------------------------------------------------------
def headline(records: Optional[List[PromptRecord]] = None) -> dict:
    if records is None:
        records = load_fire_set()
    all_reps = [r for pr in records for r in pr.reps]

    # rep-level flips by filename (the well-defined per-run help/hurt -> documented net -5).
    paired = [r for r in all_reps
              if r.none_success is not None and r.refresh_success is not None]
    rep_help = sum(1 for r in paired if r.none_success is False and r.refresh_success is True)
    rep_hurt = sum(1 for r in paired if r.none_success is True and r.refresh_success is False)

    # fire set (none arm): gate fires on a CURABLE tool.
    fire_reps = [r for r in all_reps if r.none_fires]
    fire_none = len(fire_reps)
    would_fail = sum(1 for r in fire_reps if r.none_success is False)
    would_pass = sum(1 for r in fire_reps if r.none_success is True)

    # cure actually fired in the refresh arm.
    fire_refresh = sum(1 for r in all_reps if r.refresh_fired)

    # prompt-level pairing (the schema's n_pairs / paired_help / paired_hurt by user_prompt).
    prompt_paired = [pr for pr in records
                     if pr.none_success is not None and pr.refresh_success is not None]
    n_pairs_prompt = len(prompt_paired)
    prompt_help = sum(1 for pr in prompt_paired
                      if pr.none_success is False and pr.refresh_success is True)
    prompt_hurt = sum(1 for pr in prompt_paired
                      if pr.none_success is True and pr.refresh_success is False)

    return {
        "n_prompts": len(records),
        "n_reps_total": len(all_reps),
        "n_rep_pairs": len(paired),
        "rep_help_none_fail_refresh_pass": rep_help,
        "rep_hurt_none_pass_refresh_fail": rep_hurt,
        "fire_set_none": fire_none,
        "fire_set_refresh_cure_fired": fire_refresh,
        "would_fail_in_fire_set": would_fail,
        "would_pass_in_fire_set": would_pass,
        "n_pairs_prompt": n_pairs_prompt,
        "prompt_help": prompt_help,
        "prompt_hurt": prompt_hurt,
        "none_success_total": sum(1 for r in all_reps if r.none_success is True),
        "refresh_success_total": sum(1 for r in all_reps if r.refresh_success is True),
    }


def main() -> int:
    recs = load_fire_set()
    h = headline(recs)
    print("=" * 78)
    print("  PRECISION-GROUND — curable-conversion (schema_refresh) ground truth (docs/205 §7)")
    print(f"  none:    {NONE_GLOB}")
    print(f"  refresh: {REFRESH_GLOB}")
    print("=" * 78)
    print(f"  distinct prompts (user_prompt pairing key) : {h['n_prompts']}")
    print(f"  total reps (files) per arm                 : {h['n_reps_total']}")
    print(f"  rep-pairs (by filename, both arms present)  : {h['n_rep_pairs']}")
    print("-" * 78)
    print("  REP-LEVEL FLIPS (by filename — the documented net effect):")
    print(f"    help (none FAIL & refresh PASS)           : {h['rep_help_none_fail_refresh_pass']}")
    print(f"    hurt (none PASS & refresh FAIL)           : {h['rep_hurt_none_pass_refresh_fail']}")
    print(f"    net success (help - hurt)                 : "
          f"{h['rep_help_none_fail_refresh_pass'] - h['rep_hurt_none_pass_refresh_fail']}")
    print("-" * 78)
    print("  FIRE SET (none arm: K=2 gate fires on a CURABLE tool):")
    print(f"    fire_set_none                             : {h['fire_set_none']}")
    print(f"    would_fail in fire set (none success=F)   : {h['would_fail_in_fire_set']}")
    print(f"    would_pass in fire set (none success=T)   : {h['would_pass_in_fire_set']}  <- harm risk")
    print(f"  CURE ACTUALLY FIRED (refresh dos_schema_refresh event): {h['fire_set_refresh_cure_fired']}")
    print("-" * 78)
    print("  PROMPT-LEVEL (user_prompt key; 8 reps each, ANY-pass rollup):")
    print(f"    n_pairs (prompts in BOTH arms)            : {h['n_pairs_prompt']}")
    print(f"    paired_help (none fail & refresh pass)    : {h['prompt_help']}")
    print(f"    paired_hurt (none pass & refresh fail)    : {h['prompt_hurt']}")
    print("-" * 78)
    print(f"  none success total  : {h['none_success_total']} / {h['n_reps_total']}")
    print(f"  refresh success total: {h['refresh_success_total']} / {h['n_reps_total']}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
