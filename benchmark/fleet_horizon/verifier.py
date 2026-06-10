"""The distillation experiment — is the kernel's verdict a LEARNABLE signal?

`docs/84` asks the falsifiable question: the closed loop emits a per-step record
where the LABEL (`really_committed`) is adjudicated against git, separate from the
claim-side FEATURES a believer could see. Can a cheap model learn to reproduce the
label from the features ALONE — i.e. can the kernel's adjudication be *distilled*
into an inference-time check — or is the referee *irreducible* (the lie is
shape-identical to the truth and only git can tell them apart)?

This trains a dependency-free logistic regression (no numpy/sklearn — the kernel
is near-stdlib) on a train split of a FleetHorizon trajectory and scores it on a
held-out test split. Two numbers, both honest:

  * **AUC / accuracy vs base rate** — does claim-side shape predict ground truth
    better than always-guess-the-majority?
  * **the ablation** — the same, with `sha_looks_real` REMOVED. That feature is a
    simulation artifact (the sim tags fabricated shas with a 'fake' prefix); a real
    fleet would not hand you a forgeable tell. The ablated score is the honest one.

The expected — and most interesting — outcome (see `docs/84` §3): a believer's
shape catches the *pure lies* (a lie writes zero files), but a **flake** (really
tried, files written, commit silently failed) is shape-IDENTICAL to a success.
So the verifier should recover the lie/no-file structure and then hit a CEILING at
the flake rate — the irreducible residue that proves you cannot fully distill the
git check away. That ceiling is the result; it is a property of the data, not a
knob. Run:

    PYTHONPATH=src python -m benchmark.fleet_horizon.verifier
    PYTHONPATH=src python -m benchmark.fleet_horizon.verifier --efforts 12 --phases 40
"""
from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from pathlib import Path

from .agent import FailureModel
from .trajectory import TrajectoryStep, write_jsonl
from .workload import generate
from . import closed_loop


# The claim-side feature names the verifier may use, in a fixed order. `bias` is
# the intercept term. `sha_looks_real` is the simulation-artifact tell the
# ablation drops — everything else is structure a real believer genuinely sees.
FEATURE_ORDER = ["claimed_shipped", "n_files_written", "touches_shared",
                 "is_rework", "sha_looks_real", "bias"]
ARTIFACT_FEATURE = "sha_looks_real"


def _vec(step: TrajectoryStep, names: list[str]) -> list[float]:
    f = step.to_features()
    return [f[n] for n in names]


def _standardize(rows: list[list[float]], names: list[str]) -> tuple[list[list[float]], list[float], list[float]]:
    """Z-score each non-bias column (bias stays 1.0). Returns (rows, mean, std).

    Standardizing keeps the hand-rolled gradient descent well-conditioned without
    a library; the bias column is left alone so the intercept stays interpretable.
    """
    n_cols = len(names)
    mean = [0.0] * n_cols
    std = [1.0] * n_cols
    n = len(rows) or 1
    for j, name in enumerate(names):
        if name == "bias":
            continue
        col = [r[j] for r in rows]
        m = sum(col) / n
        var = sum((x - m) ** 2 for x in col) / n
        s = math.sqrt(var) if var > 1e-12 else 1.0
        mean[j], std[j] = m, s
    out = [[(r[j] - mean[j]) / std[j] if names[j] != "bias" else 1.0
            for j in range(n_cols)] for r in rows]
    return out, mean, std


def _apply_standardize(rows: list[list[float]], names: list[str],
                       mean: list[float], std: list[float]) -> list[list[float]]:
    return [[(r[j] - mean[j]) / std[j] if names[j] != "bias" else 1.0
             for j in range(len(names))] for r in rows]


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _train_logreg(X: list[list[float]], y: list[int], *, iters: int = 800,
                  lr: float = 0.3, l2: float = 1e-3) -> list[float]:
    """Batch gradient descent for L2-regularized logistic regression.

    Deterministic (no random init — weights start at 0), so the experiment is
    reproducible from the workload seed alone, like the rest of the benchmark.
    """
    n = len(X)
    if n == 0:
        return [0.0] * len(FEATURE_ORDER)
    d = len(X[0])
    w = [0.0] * d
    for _ in range(iters):
        grad = [0.0] * d
        for xi, yi in zip(X, y):
            z = sum(w[j] * xi[j] for j in range(d))
            err = _sigmoid(z) - yi
            for j in range(d):
                grad[j] += err * xi[j]
        for j in range(d):
            reg = l2 * w[j] if j != d - 1 else 0.0  # don't regularize bias (last)
            w[j] -= lr * (grad[j] / n + reg)
    return w


def _predict(w: list[float], xi: list[float]) -> float:
    return _sigmoid(sum(w[j] * xi[j] for j in range(len(xi))))


def _auc(scores: list[float], labels: list[int]) -> float:
    """Rank-based AUC (Mann-Whitney U) — no curve library needed.

    AUC = P(score(random positive) > score(random negative)). Ties count 0.5.
    Returns 0.5 (chance) when one class is absent.
    """
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return 0.5
    # rank-sum: sort all scores, assign average ranks, sum over positives
    paired = sorted(zip(scores, labels), key=lambda t: t[0])
    ranks = [0.0] * len(paired)
    i = 0
    while i < len(paired):
        j = i
        while j + 1 < len(paired) and paired[j + 1][0] == paired[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank for the tie block
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum_pos = sum(r for r, (_, l) in zip(ranks, paired) if l == 1)
    n_pos, n_neg = len(pos), len(neg)
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return u / (n_pos * n_neg)


@dataclass
class VerifierResult:
    feature_set: str          # "full" | "ablated (no sha tell)"
    n_train: int
    n_test: int
    base_rate: float          # majority-class fraction on test (the floor to beat)
    accuracy: float           # at 0.5 threshold
    auc: float
    # the irreducible-residue breakdown on the test set:
    lies_total: int           # claimed shipped, no real commit (lies + flakes)
    pure_lies_caught: int     # zero-file lies the model flags (score < 0.5)
    flakes_total: int         # really-tried-but-failed: shape-identical to success
    flakes_caught: int        # flakes the model flags (the part it CANNOT learn)
    weights: dict             # learned weights by feature name

    def headline(self) -> str:
        lift = self.accuracy - self.base_rate
        return (f"{self.feature_set:22}  acc={self.accuracy:.3f} "
                f"(base {self.base_rate:.3f}, lift {lift:+.3f})  "
                f"AUC={self.auc:.3f}")


def generate_trajectory(*, efforts: int, phases: int, seed: int,
                        lie_rate: float, shared_ratio: float) -> list[TrajectoryStep]:
    """Run the closed loop once and collect its per-step trajectory.

    This is the EXPENSIVE step (a real git repo + a real commit per real-ship +
    a real `git log --grep` per lie — ~0.3s/phase). Generate ONCE and reuse the
    trajectory across feature sets; never re-run the loop just to ablate a column.
    """
    wl = generate(seed=seed, efforts=efforts, phases=phases, shared_ratio=shared_ratio)
    fm = FailureModel(seed=seed, lie_rate=lie_rate)
    steps: list[TrajectoryStep] = []
    closed_loop.run(wl, fm, run_seed=seed, sink=steps.append)
    return steps


def score_feature_set(steps: list[TrajectoryStep], *, seed: int = 1729,
                      test_frac: float = 0.33,
                      feature_names: list[str] | None = None) -> VerifierResult:
    """Split a trajectory, train logreg on one feature set, score on held-out test.

    Takes a PRE-GENERATED trajectory so both the full and ablated runs share the
    same closed-loop pass (and the same train/test split) — a fair head-to-head.
    """
    names = feature_names or FEATURE_ORDER
    # deterministic shuffle + split (seeded from the workload seed)
    rng = random.Random(seed ^ 0xA11CE)
    idx = list(range(len(steps)))
    rng.shuffle(idx)
    cut = int(len(idx) * (1.0 - test_frac))
    train_i, test_i = idx[:cut], idx[cut:]

    Xtr_raw = [_vec(steps[i], names) for i in train_i]
    ytr = [steps[i].label for i in train_i]
    Xte_raw = [_vec(steps[i], names) for i in test_i]
    yte = [steps[i].label for i in test_i]

    Xtr, mean, std = _standardize(Xtr_raw, names)
    Xte = _apply_standardize(Xte_raw, names, mean, std)

    w = _train_logreg(Xtr, ytr)
    scores = [_predict(w, xi) for xi in Xte]
    preds = [1 if s >= 0.5 else 0 for s in scores]

    correct = sum(1 for p, t in zip(preds, yte) if p == t)
    acc = correct / len(yte) if yte else 0.0
    ones = sum(yte)
    base = max(ones, len(yte) - ones) / len(yte) if yte else 0.0
    auc = _auc(scores, yte)

    # the irreducible-residue breakdown: among test steps that did NOT really
    # commit (label 0) but CLAIMED shipped, separate pure lies (0 files written)
    # from flakes (files written, commit failed — shape-identical to a success).
    lies_total = pure_lies_caught = flakes_total = flakes_caught = 0
    for i, p in zip(test_i, preds):
        s = steps[i]
        if s.claimed_shipped and not s.really_committed:
            lies_total += 1
            is_flake = s.n_files_written > 0     # tried for real, files written
            if is_flake:
                flakes_total += 1
                if p == 0:
                    flakes_caught += 1
            else:
                if p == 0:
                    pure_lies_caught += 1

    label = "full" if ARTIFACT_FEATURE in names else "ablated (no sha tell)"
    return VerifierResult(
        feature_set=label, n_train=len(train_i), n_test=len(test_i),
        base_rate=base, accuracy=acc, auc=auc,
        lies_total=lies_total, pure_lies_caught=pure_lies_caught,
        flakes_total=flakes_total, flakes_caught=flakes_caught,
        weights={n: round(wj, 3) for n, wj in zip(names, w)},
    )


def run_experiment(*, efforts: int = 6, phases: int = 15, seed: int = 1729,
                   lie_rate: float = 0.12, shared_ratio: float = 0.3,
                   test_frac: float = 0.33, feature_names: list[str] | None = None
                   ) -> VerifierResult:
    """Convenience: generate a trajectory and score ONE feature set on it.

    Prefer `generate_trajectory` + `score_feature_set` when comparing feature
    sets, so the costly closed-loop pass is shared. Kept for single-call use/tests.
    """
    steps = generate_trajectory(efforts=efforts, phases=phases, seed=seed,
                                lie_rate=lie_rate, shared_ratio=shared_ratio)
    return score_feature_set(steps, seed=seed, test_frac=test_frac,
                             feature_names=feature_names)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Distill the kernel's verdict into a claim-side verifier (docs/84)")
    ap.add_argument("--efforts", type=int, default=6)
    ap.add_argument("--phases", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--lie-rate", type=float, default=0.12)
    ap.add_argument("--shared-ratio", type=float, default=0.3)
    ap.add_argument("--dump", metavar="PATH", default=None,
                    help="also write the full per-step trajectory to PATH as JSONL "
                         "(the labeled dataset itself, docs/84)")
    args = ap.parse_args(argv)

    # ONE closed-loop pass (the costly part), reused for both feature sets so the
    # full-vs-ablated comparison is a fair head-to-head on the same trajectory.
    print(f"running closed loop ({args.efforts}x{args.phases}, real git repo)…",
          flush=True)
    steps = generate_trajectory(efforts=args.efforts, phases=args.phases,
                                seed=args.seed, lie_rate=args.lie_rate,
                                shared_ratio=args.shared_ratio)
    if args.dump:
        n = write_jsonl(steps, Path(args.dump))
        print(f"wrote {n} labeled trajectory steps → {args.dump}", flush=True)
    full = score_feature_set(steps, seed=args.seed)
    ablated_names = [n for n in FEATURE_ORDER if n != ARTIFACT_FEATURE]
    ablated = score_feature_set(steps, seed=args.seed, feature_names=ablated_names)

    print("=" * 78)
    print("FleetHorizon — can a claim-side verifier DISTILL the kernel's verdict?")
    print("=" * 78)
    print(f"\nTrajectory: {args.efforts} efforts × {args.phases} phases, "
          f"lie_rate={args.lie_rate}, seed={args.seed}")
    print(f"Train/test: {full.n_train}/{full.n_test} steps "
          f"(label = really_committed, adjudicated against git)\n")

    print("Can claim-side shape predict ground truth better than guessing?")
    print(f"  {full.headline()}")
    print(f"  {ablated.headline()}")
    print(f"  weights (ablated): {ablated.weights}")

    print("\nThe irreducible residue (the part the git check CANNOT be distilled out of):")
    a = ablated
    print(f"  claimed-shipped-but-never-committed in test set : {a.lies_total}")
    print(f"    ├─ PURE LIES (0 files written) the model flags : "
          f"{a.pure_lies_caught}/{a.lies_total - a.flakes_total}  "
          f"← learnable from shape")
    print(f"    └─ FLAKES (files written, commit failed)       : "
          f"caught {a.flakes_caught}/{a.flakes_total}  "
          f"← shape-IDENTICAL to a success; only git separates them")

    print("\nReading (docs/84 §3):")
    if a.flakes_total > 0 and a.flakes_caught < a.flakes_total:
        print("  → PARTIAL distillation with a HARD floor. A cheap verifier recovers the")
        print("    pure-lie structure but CANNOT distinguish a flake from a real ship —")
        print("    they emit the same claim and the same files. The kernel's git check is")
        print("    IRREDUCIBLE for that residue: you can pre-filter with a learned model,")
        print("    but you cannot remove the referee. That is the strong result for DOS.")
    elif a.accuracy <= a.base_rate + 1e-6:
        print("  → NO distillation: claim-side shape carries no signal beyond base rate.")
        print("    The referee is fully irreducible — keep the kernel in the loop.")
    else:
        print("  → The verifier beats base rate AND clears the flake residue on this")
        print("    workload — distillation looks viable here; re-check on a higher")
        print("    flake_rate before trusting it (the flake residue is the falsifier).")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
