"""The trio-additivity claims, reproducible from the durable rows alone (docs/158).

This module is the SINGLE SOURCE OF TRUTH for the `terminal_error` additivity story. Every
headline number a figure draws or a sentence asserts is computed HERE, from
`_results/replay_all_rows.csv` (the durable, frozen per-run join), with zero network / LLM / MCP.
`viz.py` reads `compute()`; the test suite asserts `compute()`; the `--emit` claims ledger prints
`compute()`. Because all three consume one function, a figure can NOT drift from the prose, and any
agent or person can reproduce the claims with one command:

    python -m benchmark.toolathlon.additivity            # print the claims to stdout
    python -m benchmark.toolathlon.additivity --check     # assert the invariants (exit 1 on drift)
    python -m benchmark.toolathlon.additivity --emit      # write _results/additivity_claims.md

The headline (verified against the corpus this docstring was written for, 7,116 records / 6,862
labeled, 22 models x 3 runs):

  * `terminal_error` standalone: 76 catches, precision 95.0%, false-alarm 0.24%.
  * ADDITIVE: 75 of those 76 are NET NEW (missed by BOTH shipped detectors) -> a distinct slice,
    not a re-catch.
  * Union recall rises 4.74% -> 6.18% (pair -> trio), a +30% relative gain, at union precision
    92.6% / false-alarm 1.59%.
  * It reaches the FRONTIER: on the strongest models (Toolathlon pass-rate >= the frontier cut),
    where dangling+tool_stream catch almost nothing, terminal_error still catches net-new failures
    (9 net-new vs the pair's 6). HONEST FRAMING: tool_stream already catches a FEW frontier
    failures, so the claim is "first signal for the strong-model failures the pair MISSES," NOT
    "first to reach the frontier at all" (the over-claim a stale draft of docs/158 made).

The word "frontier" here is a DATA-DERIVED capability threshold (default: pass-rate >= 0.30, the
same capability axis viz.py's other figures use), NOT a hand-picked model list. That keeps the
"reaches the frontier" claim honest: it is whatever the strongest N models in THIS corpus are.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

_HERE = Path(__file__).resolve().parent
_DEFAULT_ROWS = _HERE / "_results" / "replay_all_rows.csv"
_DEFAULT_LEDGER = _HERE / "_results" / "additivity_claims.md"

# The three byte-clean in-flight detectors, in ship order. The first two are the SHIPPED pair
# (docs/157); terminal_error is the addition under test (docs/158).
PAIR = ("dangling", "tool_stream")
TRIO = ("dangling", "tool_stream", "terminal_error")

# Capability cut that defines "frontier": a model whose Toolathlon pass-rate is at least this is
# counted as frontier. This is the SAME capability proxy (1 - base_fail_rate per model) the rest of
# the study uses; 0.30 isolates the strongest ~8 models, where the pair goes nearly silent.
FRONTIER_PASS_RATE = 0.30


def _truthy(v: object) -> bool:
    return str(v).strip().lower() in {"true", "1"}


def _fired(row: dict, det: str) -> bool:
    return _truthy(row[f"{det}_fired"])


@dataclass
class DetectorSlice:
    """One detector's confusion counts over a set of labeled runs (the replay.DetectorReport cells,
    recomputed from the durable rows so this module needs only the CSV)."""

    name: str
    fired_fail: int = 0  # TP — fired on an oracle-FAILED run
    fired_pass: int = 0  # FP — fired on an oracle-PASSED run (false alarm)
    oracle_failed: int = 0
    oracle_passed: int = 0

    @property
    def fired(self) -> int:
        return self.fired_fail + self.fired_pass

    @property
    def precision(self) -> Optional[float]:
        return self.fired_fail / self.fired if self.fired else None

    @property
    def recall(self) -> Optional[float]:
        return self.fired_fail / self.oracle_failed if self.oracle_failed else None

    @property
    def false_alarm(self) -> Optional[float]:
        return self.fired_pass / self.oracle_passed if self.oracle_passed else None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "fired": self.fired,
            "fired_fail": self.fired_fail,
            "fired_pass": self.fired_pass,
            "precision": _r(self.precision),
            "recall": _r(self.recall),
            "false_alarm": _r(self.false_alarm),
        }


@dataclass
class UnionSlice:
    """A SET of detectors treated as one OR-combined detector (a run fires if ANY member fires).

    Union TP/FP are de-duplicated by run: a failure caught by two members counts once. This is the
    honest way to pool — it is why the trio's recall is not the sum of the parts."""

    members: tuple
    tp: int = 0  # distinct FAILED runs caught by at least one member
    fp: int = 0  # distinct PASSED runs flagged by at least one member
    oracle_failed: int = 0
    oracle_passed: int = 0

    @property
    def fired(self) -> int:
        return self.tp + self.fp

    @property
    def precision(self) -> Optional[float]:
        return self.tp / self.fired if self.fired else None

    @property
    def recall(self) -> Optional[float]:
        return self.tp / self.oracle_failed if self.oracle_failed else None

    @property
    def false_alarm(self) -> Optional[float]:
        return self.fp / self.oracle_passed if self.oracle_passed else None

    def to_dict(self) -> dict:
        return {
            "members": list(self.members),
            "fired": self.fired,
            "tp": self.tp,
            "fp": self.fp,
            "precision": _r(self.precision),
            "recall": _r(self.recall),
            "false_alarm": _r(self.false_alarm),
        }


@dataclass
class ModelRow:
    """Per-model capability + each detector's TP and the trio/pair union TP — the per-model table the
    corpus headline averages over, and the basis of the frontier split."""

    model: str
    labeled: int
    oracle_failed: int
    pass_rate: float          # capability proxy = passes / labeled
    det_tp: dict              # detector -> TP on this model
    pair_tp: int             # |D ∪ T| failures caught
    trio_tp: int             # |D ∪ T ∪ E| failures caught
    te_netnew: int           # terminal_error catches the pair MISSED, on this model

    @property
    def is_frontier(self) -> bool:
        return self.pass_rate >= FRONTIER_PASS_RATE

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "labeled": self.labeled,
            "oracle_failed": self.oracle_failed,
            "pass_rate": _r(self.pass_rate),
            "is_frontier": self.is_frontier,
            "det_tp": dict(self.det_tp),
            "pair_tp": self.pair_tp,
            "trio_tp": self.trio_tp,
            "te_netnew": self.te_netnew,
        }


@dataclass
class TrioStats:
    """The whole additivity result — corpus slices, the per-model table, and the derived claims.

    Everything a figure or a sentence needs is a field here; nothing recomputes trajectories."""

    n_records: int
    n_labeled: int
    n_failed: int
    n_passed: int
    frontier_pass_rate: float
    detectors: dict            # name -> DetectorSlice (standalone)
    pair: UnionSlice
    trio: UnionSlice
    te_netnew_total: int       # terminal_error TP missed by the pair, corpus-wide
    te_overlap_with_pair: int  # terminal_error TP the pair ALSO caught (the non-additive remainder)
    te_netnew_frontier: int    # of te_netnew_total, how many land on frontier models
    frontier_models: list      # model names with pass_rate >= cut, capability-sorted
    frontier_pair_tp: int      # failures the pair catches across all frontier models
    frontier_te_tp: int        # failures terminal_error catches across all frontier models
    frontier_te_netnew: int    # frontier failures terminal_error catches that the pair MISSED
    models: list               # list[ModelRow], capability-ascending

    # -- derived headline numbers (so the ledger/figures read them, never re-derive) -----------
    @property
    def union_recall_gain_pp(self) -> float:
        return 100.0 * (self.trio.recall - self.pair.recall)

    @property
    def union_recall_gain_relative(self) -> float:
        return (self.trio.recall - self.pair.recall) / self.pair.recall if self.pair.recall else float("nan")

    def to_dict(self) -> dict:
        return {
            "n_records": self.n_records,
            "n_labeled": self.n_labeled,
            "n_failed": self.n_failed,
            "n_passed": self.n_passed,
            "frontier_pass_rate": self.frontier_pass_rate,
            "detectors": {k: v.to_dict() for k, v in self.detectors.items()},
            "pair": self.pair.to_dict(),
            "trio": self.trio.to_dict(),
            "terminal_error_netnew_total": self.te_netnew_total,
            "terminal_error_overlap_with_pair": self.te_overlap_with_pair,
            "terminal_error_netnew_on_frontier": self.te_netnew_frontier,
            "union_recall_gain_pp": _r(self.union_recall_gain_pp / 100.0),  # store as fraction
            "union_recall_gain_relative": _r(self.union_recall_gain_relative),
            "frontier": {
                "pass_rate_cut": self.frontier_pass_rate,
                "models": self.frontier_models,
                "pair_tp": self.frontier_pair_tp,
                "terminal_error_tp": self.frontier_te_tp,
                "terminal_error_netnew": self.frontier_te_netnew,
            },
            "models": [m.to_dict() for m in self.models],
        }


def _r(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), n)


# --------------------------------------------------------------------------- load + compute
def load_rows(rows_csv: Path = _DEFAULT_ROWS) -> list:
    with rows_csv.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def rows_fingerprint(rows_csv: Path = _DEFAULT_ROWS) -> str:
    """A short content hash of the durable rows file — the provenance stamp the ledger records so a
    reader can tell if the committed ledger is STALE relative to the committed CSV (the detector
    grammar was retuned once, moving the numbers; this catches that drift). Line-ending-insensitive
    so CRLF/LF normalization doesn't change the digest."""
    import hashlib

    h = hashlib.sha256()
    with rows_csv.open("rb") as fh:
        for line in fh:
            h.update(line.replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def compute(
    rows: Iterable[dict],
    *,
    frontier_pass_rate: float = FRONTIER_PASS_RATE,
    pair: tuple = PAIR,
    trio: tuple = TRIO,
    te_specific: bool = False,
) -> TrioStats:
    """Fold the durable rows into the full additivity result. Pure over the row dicts.

    A row is LABELED iff `passed` parses to True/False; rows with an absent oracle label (passed
    "" / None) are excluded from every count, never guessed — the same rule replay.py uses.

    `te_specific` (docs/162): fold the SURGICAL terminal_error column (`terminal_error_specific_fired`,
    recovery="specific-only") instead of the conservative default (`terminal_error_fired`,
    recovery="aware"). Implemented as a pure pre-fold rewrite — every downstream `_fired(row,
    "terminal_error")` then transparently reads the surgical verdict — so the surgical trio is a
    first-class, `--check`-reproducible claim with zero call-site changes. Default False = the
    conservative SSOT numbers, unchanged. A rows file written before docs/162 (no specific column) is
    handled gracefully: a missing column reads as not-fired (refuse-to-guess), so `te_specific=True`
    on an old file degrades to the aware trio rather than raising.
    """
    rows = list(rows)
    if te_specific:
        # pure rewrite: alias the surgical column onto the name the fold reads. Refuse-to-guess on an
        # old rows file: absent specific column -> treat as not-fired (never the aware value).
        rows = [
            {**r, "terminal_error_fired": r.get("terminal_error_specific_fired", "False")}
            for r in rows
        ]
    n_records = len(rows)
    labeled = [r for r in rows if str(r["passed"]) in ("True", "False")]
    n_labeled = len(labeled)
    failed = [r for r in labeled if str(r["passed"]) == "False"]
    passed = [r for r in labeled if str(r["passed"]) == "True"]
    n_failed, n_passed = len(failed), len(passed)

    all_dets = tuple(dict.fromkeys((*pair, *trio)))  # ordered unique

    # standalone per-detector slices
    det_slices = {d: DetectorSlice(d, oracle_failed=n_failed, oracle_passed=n_passed) for d in all_dets}
    for r in labeled:
        is_fail = str(r["passed"]) == "False"
        for d in all_dets:
            if _fired(r, d):
                if is_fail:
                    det_slices[d].fired_fail += 1
                else:
                    det_slices[d].fired_pass += 1

    pair_u = _union_slice(labeled, pair, n_failed, n_passed)
    trio_u = _union_slice(labeled, trio, n_failed, n_passed)

    # terminal_error additivity vs the pair (run-keyed sets so a double-catch counts once)
    def key(r):
        return (r["model_run"], r["task_name"])

    pair_fail_keys = {key(r) for r in failed if any(_fired(r, d) for d in pair)}
    te_fail_keys = {key(r) for r in failed if _fired(r, "terminal_error")}
    te_netnew_keys = te_fail_keys - pair_fail_keys
    te_overlap = len(te_fail_keys & pair_fail_keys)

    # per-model table + frontier split
    models = _per_model(labeled, pair, trio)
    frontier = [m for m in models if m.pass_rate >= frontier_pass_rate]
    frontier_set = {m.model for m in frontier}
    te_netnew_frontier = sum(1 for r in failed if key(r) in te_netnew_keys and r["model"] in frontier_set)

    fr_fail = [r for r in failed if r["model"] in frontier_set]
    fr_pair_keys = {key(r) for r in fr_fail if any(_fired(r, d) for d in pair)}
    fr_te_keys = {key(r) for r in fr_fail if _fired(r, "terminal_error")}

    return TrioStats(
        n_records=n_records,
        n_labeled=n_labeled,
        n_failed=n_failed,
        n_passed=n_passed,
        frontier_pass_rate=frontier_pass_rate,
        detectors=det_slices,
        pair=pair_u,
        trio=trio_u,
        te_netnew_total=len(te_netnew_keys),
        te_overlap_with_pair=te_overlap,
        te_netnew_frontier=te_netnew_frontier,
        frontier_models=[m.model for m in frontier],
        frontier_pair_tp=len(fr_pair_keys),
        frontier_te_tp=len(fr_te_keys),
        frontier_te_netnew=len(fr_te_keys - fr_pair_keys),
        models=models,
    )


def _union_slice(labeled: list, members: tuple, n_failed: int, n_passed: int) -> UnionSlice:
    u = UnionSlice(members=tuple(members), oracle_failed=n_failed, oracle_passed=n_passed)
    for r in labeled:
        if any(_fired(r, d) for d in members):
            if str(r["passed"]) == "False":
                u.tp += 1
            else:
                u.fp += 1
    return u


def _per_model(labeled: list, pair: tuple, trio: tuple) -> list:
    by_model: dict = {}
    for r in labeled:
        by_model.setdefault(r["model"], []).append(r)

    out = []
    for model, rs in by_model.items():
        n = len(rs)
        passes = sum(1 for r in rs if str(r["passed"]) == "True")
        fails = [r for r in rs if str(r["passed"]) == "False"]

        def keyset(dets):
            return {(r["model_run"], r["task_name"]) for r in fails if any(_fired(r, d) for d in dets)}

        det_tp = {d: len(keyset((d,))) for d in trio}
        pair_keys = keyset(pair)
        trio_keys = keyset(trio)
        te_keys = keyset(("terminal_error",))
        out.append(
            ModelRow(
                model=model,
                labeled=n,
                oracle_failed=len(fails),
                pass_rate=passes / n if n else 0.0,
                det_tp=det_tp,
                pair_tp=len(pair_keys),
                trio_tp=len(trio_keys),
                te_netnew=len(te_keys - pair_keys),
            )
        )
    out.sort(key=lambda m: (m.pass_rate, m.model))
    return out


# --------------------------------------------------------------------------- invariants (the proof)
def check_invariants(s: TrioStats) -> list:
    """Return a list of FAILED invariant messages (empty == all hold). These are the structural
    claims that must be true of ANY corpus, so they catch silent data drift, not just this corpus's
    specific numbers."""
    fails = []

    def want(cond: bool, msg: str):
        if not cond:
            fails.append(msg)

    # 1. additivity decomposition: trio recall = pair recall + net-new (run-keyed, deduped).
    want(
        s.trio.tp == s.pair.tp + s.te_netnew_total,
        f"trio TP ({s.trio.tp}) != pair TP ({s.pair.tp}) + terminal_error net-new ({s.te_netnew_total})",
    )
    # 2. terminal_error standalone TP splits exactly into net-new + overlap-with-pair.
    te = s.detectors["terminal_error"]
    want(
        te.fired_fail == s.te_netnew_total + s.te_overlap_with_pair,
        f"terminal_error TP ({te.fired_fail}) != net-new ({s.te_netnew_total}) + overlap ({s.te_overlap_with_pair})",
    )
    # 3. adding a detector to a union can only RAISE recall (monotone).
    want(s.trio.recall >= s.pair.recall, "trio recall < pair recall (union not monotone!)")
    # 4. frontier net-new is a subset of total net-new.
    want(
        0 <= s.te_netnew_frontier <= s.te_netnew_total,
        f"frontier net-new ({s.te_netnew_frontier}) out of [0, {s.te_netnew_total}]",
    )
    # 5. frontier set is exactly the models at/above the cut, and they are the strongest.
    want(
        all(m.pass_rate >= s.frontier_pass_rate for m in s.models if m.model in set(s.frontier_models)),
        "a frontier model has pass_rate below the cut",
    )
    # 6. per-model net-new sums to the corpus net-new (no double counting across models).
    per_model_netnew = sum(m.te_netnew for m in s.models)
    want(
        per_model_netnew == s.te_netnew_total,
        f"sum of per-model net-new ({per_model_netnew}) != corpus net-new ({s.te_netnew_total})",
    )
    return fails


# --------------------------------------------------------------------------- the claims ledger
def render_ledger(s: TrioStats, rows_csv: Path) -> str:
    """A human-readable + machine-checkable markdown ledger: every headline number, its formula, and
    the exact command to regenerate it. This file is the durable artifact a reviewer reads."""
    te = s.detectors["terminal_error"]
    d = s.detectors["dangling"]
    t = s.detectors["tool_stream"]
    rel = s.union_recall_gain_relative

    def pct(x):
        return "n/a" if x is None else f"{100 * x:.2f}%"

    lines = []
    A = lines.append
    A("# terminal_error additivity — the durable claims (docs/158)")
    A("")
    A("> Generated by `python -m benchmark.toolathlon.additivity --emit`. Every number below is")
    A(f"> recomputed from `{rows_csv.name}` (the frozen per-run join) with zero network/LLM. Re-run")
    A("> the command to reproduce; `--check` asserts the structural invariants and exits non-zero on")
    A("> drift. Do NOT hand-edit — edit the data or the module and regenerate.")
    A(">")
    A(f"> **Provenance:** generated from `{rows_csv.name}` with content fingerprint "
      f"`sha256:{rows_fingerprint(rows_csv)}`. If a regenerated CSV has a different fingerprint, this")
    A("> ledger is STALE — re-run `--emit` (the detector grammar was retuned once, which moved the counts).")
    A("")
    A(f"**Corpus:** {s.n_records:,} records · {s.n_labeled:,} labeled "
      f"({s.n_failed:,} oracle-FAIL, {s.n_passed:,} oracle-PASS) · {len(s.models)} models × 3 runs.")
    A("")
    A("## 1. terminal_error standalone — high precision, tiny recall")
    A("")
    A("| metric | value | formula |")
    A("|---|---|---|")
    A(f"| catches (TP) | **{te.fired_fail}** | fired on an oracle-FAILED run |")
    A(f"| false alarms (FP) | {te.fired_pass} | fired on an oracle-PASSED run |")
    A(f"| precision | **{pct(te.precision)}** | TP / (TP+FP) |")
    A(f"| recall | {pct(te.recall)} | TP / all {s.n_failed:,} failures |")
    A(f"| false-alarm rate | **{pct(te.false_alarm)}** | FP / all {s.n_passed:,} passes |")
    A("")
    A("## 2. ADDITIVITY — the catches are a distinct slice, not a re-catch")
    A("")
    A(f"- terminal_error catches **{te.fired_fail}** failures; **{s.te_netnew_total} are NET NEW** "
      f"(missed by BOTH dangling and tool_stream).")
    A(f"- Only **{s.te_overlap_with_pair}** overlap with the pair — so it is {100*s.te_netnew_total/te.fired_fail:.0f}% additive, "
      f"a different failure mode, not redundancy.")
    A("")
    A("## 3. UNION RECALL — pair → trio")
    A("")
    A("| detector set | members | union recall | union precision | union false-alarm |")
    A("|---|---|---|---|---|")
    A(f"| pair | dangling + tool_stream | **{pct(s.pair.recall)}** | {pct(s.pair.precision)} | {pct(s.pair.false_alarm)} |")
    A(f"| trio | + terminal_error | **{pct(s.trio.recall)}** | {pct(s.trio.precision)} | {pct(s.trio.false_alarm)} |")
    A("")
    A(f"- Union recall rises **{pct(s.pair.recall)} → {pct(s.trio.recall)}** "
      f"(+{s.union_recall_gain_pp:.2f} pp, **+{100*rel:.0f}% relative**).")
    A(f"- The cost is small: union precision {pct(s.pair.precision)} → {pct(s.trio.precision)}, "
      f"false-alarm {pct(s.pair.false_alarm)} → {pct(s.trio.false_alarm)}.")
    A("")
    A(f"## 4. FRONTIER reach (capability cut: Toolathlon pass-rate ≥ {s.frontier_pass_rate:.2f})")
    A("")
    A(f"The {len(s.frontier_models)} strongest models — {', '.join(s.frontier_models)} — are where the")
    A("pair goes nearly silent (a strong model fails *quietly*: no dangling cue, no visible loop).")
    A("")
    A("| on frontier models | failures caught |")
    A("|---|---|")
    A(f"| dangling + tool_stream (pair) | {s.frontier_pair_tp} |")
    A(f"| terminal_error | {s.frontier_te_tp} |")
    A(f"| terminal_error **net-new** (pair missed) | **{s.frontier_te_netnew}** |")
    A("")
    A(f"So on the frontier, where the pair catches {s.frontier_pair_tp}, terminal_error adds "
      f"{s.frontier_te_netnew} catches the pair could not see. (Honest framing: tool_stream DOES "
      f"catch some frontier failures, so this is the first signal for the strong-model failures the "
      f"pair MISSES, not the first to reach the frontier *at all*.)")
    A("")
    A("## 5. Per-model contribution (capability-ascending)")
    A("")
    A("| model | pass-rate | failures | dangling | tool_stream | terminal_error | te net-new | frontier |")
    A("|---|---:|---:|---:|---:|---:|---:|:--:|")
    for m in s.models:
        A(f"| {m.model} | {100*m.pass_rate:.1f}% | {m.oracle_failed} | "
          f"{m.det_tp['dangling']} | {m.det_tp['tool_stream']} | {m.det_tp['terminal_error']} | "
          f"{m.te_netnew} | {'✓' if m.is_frontier else ''} |")
    A("")
    A("## Reproduce")
    A("")
    A("```bash")
    A("# regenerate the durable rows from the frozen trajectories (offline once _data/ is cached):")
    A("python -m benchmark.toolathlon.run_replay --all --no-download --by-model \\")
    A("    --out benchmark/toolathlon/_results/replay_all.json \\")
    A("    --rows-out benchmark/toolathlon/_results/replay_all_rows")
    A("# recompute + re-assert these claims:")
    A("python -m benchmark.toolathlon.additivity --check")
    A("# redraw the figures from the same numbers:")
    A("python -m benchmark.toolathlon.viz")
    A("```")
    A("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- main
def _print_summary(s: TrioStats) -> None:
    te = s.detectors["terminal_error"]
    print(f"# {s.n_records:,} records · {s.n_labeled:,} labeled · {len(s.models)} models")
    print(f"terminal_error standalone : {te.fired_fail} TP / {te.fired_pass} FP · "
          f"prec {100*te.precision:.1f}% · recall {100*te.recall:.2f}% · false-alarm {100*te.false_alarm:.2f}%")
    print(f"additivity               : {s.te_netnew_total} of {te.fired_fail} net-new "
          f"({s.te_overlap_with_pair} overlap with pair)")
    print(f"union recall pair→trio   : {100*s.pair.recall:.2f}% → {100*s.trio.recall:.2f}% "
          f"(+{s.union_recall_gain_pp:.2f}pp, +{100*s.union_recall_gain_relative:.0f}% rel)")
    print(f"frontier (pass≥{s.frontier_pass_rate:.2f})       : pair {s.frontier_pair_tp} caught, "
          f"terminal_error {s.frontier_te_tp} caught, {s.frontier_te_netnew} net-new · "
          f"models={len(s.frontier_models)}")


def main(argv: Optional[list] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 trap (Windows console)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=Path, default=_DEFAULT_ROWS, help="durable per-run rows CSV")
    ap.add_argument("--frontier-pass-rate", type=float, default=FRONTIER_PASS_RATE,
                    help="capability cut: model counted as frontier iff pass-rate >= this")
    ap.add_argument("--check", action="store_true", help="assert the structural invariants; exit 1 on any failure")
    ap.add_argument("--emit", nargs="?", const=str(_DEFAULT_LEDGER), default=None,
                    help="write the markdown claims ledger (default: _results/additivity_claims.md)")
    ap.add_argument("--json", action="store_true", help="print the full TrioStats as JSON")
    args = ap.parse_args(argv)

    if not args.rows.exists():
        ap.error(f"no rows CSV at {args.rows} — run run_replay.py --all ... --rows-out first")

    s = compute(load_rows(args.rows), frontier_pass_rate=args.frontier_pass_rate)

    if args.json:
        import json
        print(json.dumps(s.to_dict(), indent=2))
        return 0

    _print_summary(s)

    if args.emit is not None:
        ledger = render_ledger(s, args.rows)
        out = Path(args.emit)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(ledger, encoding="utf-8")
        print(f"\nwrote {out}")

    if args.check:
        problems = check_invariants(s)
        if problems:
            print("\nINVARIANT FAILURES:", file=sys.stderr)
            for p in problems:
                print(f"  ✗ {p}", file=sys.stderr)
            return 1
        print(f"\nall {6} structural invariants hold ✓")
        # staleness guard: warn (don't fail) if a committed ledger no longer matches the current CSV
        ledger_path = Path(args.emit) if args.emit is not None else _DEFAULT_LEDGER
        if ledger_path.exists():
            fresh = render_ledger(s, args.rows)
            if ledger_path.read_text(encoding="utf-8") != fresh:
                print(f"  ⚠ {ledger_path.name} is STALE vs the current rows — re-run with --emit",
                      file=sys.stderr)
            else:
                print(f"  {ledger_path.name} is up to date with the rows ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
