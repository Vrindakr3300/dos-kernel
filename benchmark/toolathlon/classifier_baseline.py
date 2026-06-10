"""The trained-classifier baseline — the fair, runnable head-to-head for docs/160.

The most direct SOTA neighbor to DOS's `terminal_error` is a TRAINED failure classifier over
trajectory features (the method of arXiv 2511.04032, "Detecting Silent Failures in Multi-Agentic AI
Trajectories", which reports ~98% accuracy / 99.8% precision with XGBoost on its own datasets). The
question this module answers honestly: *run that method on OUR corpus, on the SAME scoreboard, and
see how it compares to the near-free DOS detector.*

The two are not the same KIND of thing, and the comparison must make that visible — which is the
whole point (docs/160 §1):

  * DOS detector  — ZERO training, ZERO labels, one deterministic pass over a single frozen trace.
                    No train/test split exists because there is no `fit`. Runs on a brand-new task
                    with no prior data. Reads only env-authored bytes (byte-clean).
  * classifier    — REQUIRES a labeled training corpus, MUST be scored held-out (a classifier scored
                    on its own training data is meaningless), and its features include trajectory
                    STRUCTURE the agent partly authors (step counts, narration length) — so it is a
                    mirror-verifier risk (docs/143 §5a): great offline, degrades when the model trains
                    against it. On a NEW domain with no labels it cannot run at all.

So this module reports the classifier UNDER A TRAIN/TEST SPLIT (k-fold), and prints the
labels-required + held-out caveat next to every number. The honest read is not "X beats Y" — it is
"these occupy different deployment regimes; the classifier's bigger number is bought with a labeled
training set DOS does not need." The classifier is best understood as a JUDGE-rung driver (a model
verifying a model) that would sit UNDER DOS's deterministic floor, not as a replacement for it.

Pure-Python (no sklearn/xgboost — the kernel side stays near-stdlib): a logistic-regression model
trained by gradient descent over standardized features, plus a decision-stump majority baseline. The
point is the REGIME contrast, not squeezing the last F1 point; a heavier model would only widen the
"needs more labels / more tuning" gap the comparison is drawing.

    python -m benchmark.toolathlon.classifier_baseline            # the head-to-head table
    python -m benchmark.toolathlon.classifier_baseline --folds 10 # more folds
    python -m benchmark.toolathlon.classifier_baseline --emit     # write the comparison ledger
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_ROWS = Path(__file__).resolve().parent / "_results" / "replay_all_rows.csv"


# --------------------------------------------------------------------------- data
def _truthy(v) -> bool:
    return str(v).strip().lower() in {"true", "1"}


def _label(row) -> "bool | None":
    p = str(row.get("passed", "")).strip().lower()
    if p == "true":
        return False   # passed -> NOT a failure (label 0)
    if p == "false":
        return True    # failed -> a failure (label 1)
    return None        # unlabeled -> excluded


# The classifier feature vector — trajectory STRUCTURE, the same family 2511.04032 uses (path
# length, call counts, output sizes). Deliberately INCLUDES features the agent partly authors
# (final_text_len, the detector flags) so the comparison shows what a structure classifier can
# squeeze out of the same trace DOS reads — and so the mirror-verifier caveat is concrete.
_FEATURES = (
    "n_tool_steps",
    "tool_stream_run",
    "final_text_len",
    "dangling_fired",
    "tool_stream_fired",
    "terminal_error_fired",
)


def _vec(row) -> list:
    out = []
    for f in _FEATURES:
        v = row.get(f, "")
        if f in ("dangling_fired", "tool_stream_fired", "terminal_error_fired"):
            out.append(1.0 if _truthy(v) else 0.0)
        else:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                out.append(0.0)
    return out


def load_labeled(rows_csv: Path = _DEFAULT_ROWS) -> tuple:
    """Return (X, y, raw_rows) for the labeled rows only."""
    X, y, raw = [], [], []
    with rows_csv.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            lab = _label(r)
            if lab is None:
                continue
            X.append(_vec(r))
            y.append(1 if lab else 0)
            raw.append(r)
    return X, y, raw


# --------------------------------------------------------------------------- pure logistic regression
def _standardize(X, mean, std):
    return [[(x - m) / s if s else 0.0 for x, m, s in zip(row, mean, std)] for row in X]


def _fit_logreg(X, y, *, epochs=300, lr=0.5, l2=1e-3):
    n = len(X)
    d = len(X[0]) if X else 0
    # standardize on the TRAIN split only (no test leakage)
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    var = [sum((row[j] - mean[j]) ** 2 for row in X) / n for j in range(d)]
    std = [math.sqrt(v) if v > 0 else 1.0 for v in var]
    Xs = _standardize(X, mean, std)
    w = [0.0] * d
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for xi, yi in zip(Xs, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = p - yi
            for j in range(d):
                gw[j] += err * xi[j]
            gb += err
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * (gb / n)
    return {"w": w, "b": b, "mean": mean, "std": std}


def _predict_proba(model, X):
    Xs = _standardize(X, model["mean"], model["std"])
    out = []
    for xi in Xs:
        z = model["b"] + sum(wj * xj for wj, xj in zip(model["w"], xi))
        out.append(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))))
    return out


# --------------------------------------------------------------------------- scoring
@dataclass
class Score:
    name: str
    fired: int
    tp: int          # fired & truly failed
    fp: int          # fired & truly passed
    n_fail: int
    n_pass: int

    @property
    def precision(self):
        return self.tp / self.fired if self.fired else float("nan")

    @property
    def recall(self):
        return self.tp / self.n_fail if self.n_fail else float("nan")

    @property
    def false_alarm(self):
        return self.fp / self.n_pass if self.n_pass else float("nan")

    def lift(self, base):
        return self.precision - base if self.fired else float("nan")


def _score(name, preds, y) -> Score:
    n_fail = sum(y)
    n_pass = len(y) - n_fail
    fired = sum(1 for p in preds if p)
    tp = sum(1 for p, yi in zip(preds, y) if p and yi == 1)
    fp = fired - tp
    return Score(name, fired, tp, fp, n_fail, n_pass)


def _kfold_indices(n, folds, seed_perm):
    # deterministic fold assignment (no Math.random — stable across runs)
    return [seed_perm[i] % folds for i in range(n)]


def _held_out_proba(X, y, folds):
    """k-fold held-out probabilities for every row (the only fair way to score a trained model)."""
    n = len(y)
    fold_of = [i % folds for i in range(n)]  # deterministic interleave, no RNG (stable on resume)
    held = [0.0] * n
    for f in range(folds):
        tr_X = [X[i] for i in range(n) if fold_of[i] != f]
        tr_y = [y[i] for i in range(n) if fold_of[i] != f]
        model = _fit_logreg(tr_X, tr_y)
        te_idx = [i for i in range(n) if fold_of[i] == f]
        for i, p in zip(te_idx, _predict_proba(model, [X[i] for i in te_idx])):
            held[i] = p
    return held


def _pick_threshold(held_proba, y, *, objective, target_recall=None):
    """Choose a decision threshold over held-out probabilities under a stated objective. Reporting
    MULTIPLE operating points (deployable / F1 / recall-matched) is what keeps the comparison fair
    to the classifier — a single threshold can flatter or strawman it."""
    base = sum(y) / len(y)
    best = None
    for t in [i / 100 for i in range(1, 100)]:
        preds = [1 if p >= t else 0 for p in held_proba]
        s = _score(f"@{t:.2f}", preds, y)
        if s.fired == 0:
            continue
        prec, rec, fa = s.precision, s.recall, s.false_alarm
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        if objective == "deployable":
            key = (fa <= 0.02, s.lift(base), -fa)         # max lift under a 2% false-alarm ceiling
        elif objective == "f1":
            key = (f1,)                                    # best balanced operating point
        elif objective == "recall_match":
            key = (-abs(rec - target_recall), prec)        # match a target recall, best precision there
        else:
            key = (s.lift(base),)
        if best is None or key > best[0]:
            best = (key, t, preds)
    if best is None:
        preds = [1 if p >= 0.5 else 0 for p in held_proba]
        return 0.5, preds
    return best[1], best[2]


# --------------------------------------------------------------------------- the head-to-head
def compare(rows_csv: Path = _DEFAULT_ROWS, *, folds=5, structure_only=False) -> dict:
    """If structure_only, drop the DOS detector flags from the feature set — the FAITHFUL
    2511.04032 setup (trajectory structure alone). Without it the classifier leans on the very DOS
    flags it is being compared against (its top weights ARE dangling_fired/terminal_error_fired),
    so structure_only is the honest version of the head-to-head."""
    global _FEATURES
    saved_features = _FEATURES
    if structure_only:
        _FEATURES = ("n_tool_steps", "tool_stream_run", "final_text_len")
    try:
        X, y, raw = load_labeled(rows_csv)
        return _compare_inner(X, y, raw, folds)
    finally:
        _FEATURES = saved_features  # never leak the mutated feature set (test isolation)


def _compare_inner(X, y, raw, folds) -> dict:
    n = len(y)
    base = sum(y) / n
    n_fail = sum(y)

    # DOS zero-training detectors (no fit, no split — one pass over each trace)
    def det(name, col):
        preds = [1 if _truthy(r[col]) else 0 for r in raw]
        return _score(name, preds, y)

    dos_terminal = det("terminal_error", "terminal_error_fired")
    dos_dangling = det("dangling_intent", "dangling_fired")
    dos_tstream = det("tool_stream", "tool_stream_fired")
    trio_preds = [
        1 if (_truthy(r["terminal_error_fired"]) or _truthy(r["dangling_fired"]) or _truthy(r["tool_stream_fired"])) else 0
        for r in raw
    ]
    dos_trio = _score("DOS trio (union)", trio_preds, y)

    # trained classifier, held-out k-fold — reported at THREE operating points so neither side is
    # strawmanned: a deployable point (max lift under 2% false-alarm), the F1-optimal point, and a
    # point recall-matched to terminal_error (apples-to-apples on "how often it speaks").
    held = _held_out_proba(X, y, folds)
    t_dep, p_dep = _pick_threshold(held, y, objective="deployable")
    t_f1, p_f1 = _pick_threshold(held, y, objective="f1")
    t_rm, p_rm = _pick_threshold(held, y, objective="recall_match", target_recall=dos_terminal.recall)
    clf_dep = _score(f"trained clf — DEPLOYABLE pt ({folds}-fold held-out)", p_dep, y)
    clf_f1 = _score(f"trained clf — F1-OPTIMAL pt ({folds}-fold held-out)", p_f1, y)
    clf_rm = _score(f"trained clf — recall-MATCHED to terminal_error", p_rm, y)
    # in-sample (no split) at the F1 threshold — to show the train/test optimism gap honestly
    full = _fit_logreg(X, y)
    insample = [1 if p >= t_f1 else 0 for p in _predict_proba(full, X)]
    clf_insample = _score("trained clf — IN-SAMPLE @F1 (no split, OPTIMISTIC)", insample, y)

    return {
        "n_labeled": n,
        "base_fail_rate": base,
        "n_fail": n_fail,
        "folds": folds,
        "thresholds": {"deployable": t_dep, "f1": t_f1, "recall_match": t_rm},
        "scores": [
            dos_terminal, dos_dangling, dos_tstream, dos_trio,
            clf_dep, clf_f1, clf_rm, clf_insample,
        ],
        "base": base,
    }


def _fmt(s: Score, base: float) -> str:
    def pct(x):
        return "  —  " if (x is None or (isinstance(x, float) and math.isnan(x))) else f"{x*100:5.1f}%"
    return (
        f"{s.name:<46} fire={pct(s.fired / (s.n_fail + s.n_pass))}  "
        f"prec={pct(s.precision)}  lift={pct(s.lift(base))}  "
        f"recall={pct(s.recall)}  falarm={pct(s.false_alarm)}  "
        f"[tp/fp={s.tp}/{s.fp}]"
    )


def render(result: dict) -> str:
    base = result["base"]
    lines = []
    th = result["thresholds"]
    lines.append(f"# DOS detector vs trained-classifier baseline (docs/160)")
    lines.append(
        f"# corpus: {result['n_labeled']} labeled rows · base fail rate {base*100:.1f}% · "
        f"{result['folds']}-fold CV · thresholds dep={th['deployable']:.2f}/f1={th['f1']:.2f}/"
        f"rm={th['recall_match']:.2f}"
    )
    lines.append("# lift = precision - base (skill above guessing); falarm = fires on a PASS")
    lines.append("")
    for s in result["scores"]:
        lines.append(_fmt(s, base))
    lines.append("")
    lines.append("# REGIME CAVEAT (the load-bearing point — docs/160 §1):")
    lines.append("#   DOS detectors      : ZERO training, ZERO labels, one pass per trace, byte-clean,")
    lines.append("#                        runs on a brand-new task with no prior data.")
    lines.append("#   trained classifier : REQUIRES a labeled training corpus + a held-out split to be")
    lines.append("#                        meaningful; the in-sample row shows how optimistic it looks")
    lines.append("#                        WITHOUT the split. On a new domain with no labels it cannot")
    lines.append("#                        run at all. Reads agent-authored structure -> mirror-verifier")
    lines.append("#                        risk (degrades when the model trains against it).")
    lines.append("#   => Not a replacement for the detector — a JUDGE-rung driver that would sit UNDER")
    lines.append("#      the deterministic floor (ORACLE -> JUDGE -> HUMAN).")
    return "\n".join(lines)


def main(argv=None) -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="DOS detector vs trained-classifier baseline.")
    ap.add_argument("--rows", default=str(_DEFAULT_ROWS))
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--structure-only", action="store_true",
                    help="drop DOS detector flags from features (the faithful 2511.04032 setup)")
    ap.add_argument("--emit", action="store_true", help="write _results/classifier_comparison.md")
    args = ap.parse_args(argv)
    result = compare(Path(args.rows), folds=args.folds, structure_only=args.structure_only)
    text = render(result)
    print(text)
    if args.emit:
        out = Path(args.rows).resolve().parent / "classifier_comparison.md"
        out.write_text("```\n" + text + "\n```\n", encoding="utf-8")
        print(f"\n# wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
