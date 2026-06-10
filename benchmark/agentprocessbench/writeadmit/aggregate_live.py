"""Fold EVERY writeadmit live-result dir into one cross-model / cross-window report.

docs/228 §5's first honest caveat — *"Small n, one model. J=5 over 43 clean tasks …
More tasks + a second model would harden the base-rate"* — is a standing invitation to
keep collecting. This is the tool that totals what has been collected: it reads every
`live_results_*/` directory (each a separate run: a model × a sample window), folds the
per-task rows the live loop cached, and reports J (the out-of-loop payoff) per run AND
in aggregate.

The numbers are a verbatim read-off of the same per-task JSON rows `live_loop.py:_report`
folds — this just unions them across runs the loop wrote one at a time. It adds NOTHING
the loop didn't already adjudicate; it only sums.

  J  = an over-claim caught and blocked = a row where the agent made a confident write
       CLAIM (`confident_write`, the forgeable self-report) AND the env DB-hash witness
       refuted it (`db_match is False`) AND the gate blocked it (`admit is False`).
       It is a count of phantom writes a peer B never inherits under *adjudicate* — a
       flip off ground truth, NOT a re-projected rate (docs/179).

The believe-vs-adjudicate arms (peer_b_run) write `__believe`/`__adjudicate` files; those
are a separate experiment (the causal A/B), so this aggregator reports the SINGLE-arm
natural/slice runs by default and lists the peer-B dirs separately without double-counting.

Read-only. Run from anywhere:  python -m benchmark.agentprocessbench.writeadmit.aggregate_live
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# When run as a script the package root is not on sys.path, so the re-fold's gate import
# (below) would fail and silently fall back to the stale cached bit — the exact docs/232 trap
# this aggregator now defends against. Add the repo root so `benchmark.agentprocessbench…`
# resolves either way (mirrors index_models.py).
_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# the four directional outcomes a single-arm row can land in (the gate's verdict, folded)
_OVERCLAIM = "overclaim"      # confident write & db_match False  -> blocked -> J
_CONFIRMED = "confirmed"      # confident write & db_match True   -> admitted (true positive)
_UNWITNESSED = "unwitnessed"  # confident write & db_match None   -> floor abstains -> admitted
_HONEST = "honest"            # no confident write                -> nothing to adjudicate


@dataclass
class RunFold:
    name: str
    n: int = 0
    errors: int = 0
    db_true: int = 0
    db_false: int = 0
    db_none: int = 0
    confident: int = 0
    overclaims: int = 0      # = J (blocked, by construction: gate blocks every refuted write)
    confirmed: int = 0
    unwitnessed: int = 0
    blocked_not_overclaim: int = 0  # a guard: blocked rows that aren't over-claims (should be 0)
    refold_flips: int = 0  # rows whose over-claim status changed vs the cached bit (docs/232)
    rows_not_refolded: int = 0  # rows the gate couldn't re-fold (fell back to the cached bit)
    cost: float = 0.0
    by_domain: dict = field(default_factory=lambda: defaultdict(int))
    overclaim_rows: list = field(default_factory=list)

    @property
    def clean(self) -> int:
        return self.n - self.errors

    @property
    def base_rate(self) -> float:
        return (self.overclaims / self.clean) if self.clean else 0.0


def _fresh_decision(row: dict):
    """Re-derive (confident_write, admit) from the row's answer text with the CURRENT gate,
    instead of trusting the row's cached bits.

    WHY (docs/232, the J=4-vs-5 reconciliation): a long resumable batch caches each row's
    `confident_write` AT THE TIME IT RAN. If the claim-extractor changes MID-RUN (the
    `_IDIOM_LANDED` "you're all set" idiom landed while the pro batch was in flight), the
    cache mixes pre-/post-fix bits and a sum over the cached bit is stale — on the pro run it
    misses airline 8, undercounting J by one. The LAW: trust a re-fold over a cached bit when
    the code changed under it. So this aggregator re-derives every row; the cached bit is only
    a fallback when the gate can't be imported (a stripped checkout), recorded in `refolded`.

    Returns (confident_write, admit_bit, refolded_ok).
    """
    answer = str(row.get("answer_excerpt", "") or "")
    dm = row.get("db_match")
    try:
        try:
            from .gate import admit  # package-module import
        except ImportError:
            from benchmark.agentprocessbench.writeadmit.gate import admit  # script import
        d = admit(answer, dm)
        return d.confident_write, d.admit, True
    except Exception:
        return bool(row.get("confident_write")), row.get("admit"), False


def _classify_cw(cw: bool, dm) -> str:
    """Classify a row from its (re-derived) confident-write bit + the env witness."""
    if not cw:
        return _HONEST
    if dm is False:
        return _OVERCLAIM
    if dm is True:
        return _CONFIRMED
    return _UNWITNESSED


def _classify(row: dict) -> str:
    """Classify a row, RE-DERIVING confident_write with the current extractor (docs/232)."""
    cw, _admit, _refolded = _fresh_decision(row)
    return _classify_cw(cw, row.get("db_match"))


def fold_dir(d: str) -> RunFold:
    """Fold one single-arm run dir into a RunFold (ignores __believe/__adjudicate files)."""
    fold = RunFold(name=os.path.basename(d.rstrip("/\\")))
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        base = os.path.basename(f)
        if "__believe" in base or "__adjudicate" in base:
            continue  # peer-B A/B arm, folded elsewhere — never double-count here
        try:
            row = json.loads(open(f, encoding="utf-8").read())
        except Exception as e:  # a half-written cache file must not crash the report
            print(f"  ! skip {f}: {e}", file=sys.stderr)
            continue
        fold.n += 1
        if "error" in row:
            fold.errors += 1
            continue
        fold.by_domain[row.get("domain", "?")] += 1
        c = row.get("agent_cost")
        if isinstance(c, (int, float)):
            fold.cost += float(c)
        dm = row.get("db_match")
        fold.db_true += dm is True
        fold.db_false += dm is False
        fold.db_none += dm is None
        # RE-DERIVE the decision with the current extractor (docs/232) — never trust the
        # cached bit, which a mid-run extractor change can have left stale. One call, used
        # for the count, the classification, and the integrity guard alike.
        cw, admit_bit, refolded = _fresh_decision(row)
        if not refolded:
            fold.rows_not_refolded += 1
        fold.confident += bool(cw)
        kind = _classify_cw(cw, dm)
        # docs/232 flip: did re-folding change this row's over-claim status vs the cached bit?
        cached_overclaim = bool(row.get("confident_write")) and dm is False
        if (kind == _OVERCLAIM) != cached_overclaim:
            fold.refold_flips += 1
        if kind == _OVERCLAIM:
            fold.overclaims += 1
            fold.overclaim_rows.append(row)
        elif kind == _CONFIRMED:
            fold.confirmed += 1
        elif kind == _UNWITNESSED:
            fold.unwitnessed += 1
        # integrity guard: a blocked row that is NOT an over-claim would break the J identity
        # (use the RE-DERIVED admit, consistent with the re-derived classification)
        if admit_bit is False and kind != _OVERCLAIM:
            fold.blocked_not_overclaim += 1
    return fold


def _is_peer_b_dir(d: str) -> bool:
    return any("__believe" in os.path.basename(f) or "__adjudicate" in os.path.basename(f)
               for f in glob.glob(os.path.join(d, "*.json")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Aggregate all writeadmit live results (docs/228 §5)")
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)),
                    help="dir holding the live_results_* run directories")
    ap.add_argument("--glob", default="live_results_*",
                    help="run-dir glob (default: live_results_*)")
    ap.add_argument("--json", action="store_true", help="emit the aggregate fold as JSON")
    args = ap.parse_args(argv)

    dirs = sorted(d for d in glob.glob(os.path.join(args.root, args.glob)) if os.path.isdir(d))
    single, peer_b = [], []
    for d in dirs:
        (peer_b if _is_peer_b_dir(d) else single).append(d)

    folds = [fold_dir(d) for d in single]
    folds = [f for f in folds if f.n]  # drop empty dirs

    grand = RunFold(name="GRAND TOTAL")
    for f in folds:
        grand.n += f.n; grand.errors += f.errors
        grand.db_true += f.db_true; grand.db_false += f.db_false; grand.db_none += f.db_none
        grand.confident += f.confident; grand.overclaims += f.overclaims
        grand.confirmed += f.confirmed; grand.unwitnessed += f.unwitnessed
        grand.blocked_not_overclaim += f.blocked_not_overclaim
        grand.refold_flips += f.refold_flips; grand.rows_not_refolded += f.rows_not_refolded
        grand.cost += f.cost
        grand.overclaim_rows.extend(f.overclaim_rows)
        for k, v in f.by_domain.items():
            grand.by_domain[k] += v

    if args.json:
        out = {
            "runs": [{"name": f.name, "n": f.n, "clean": f.clean, "errors": f.errors,
                      "confident": f.confident, "J": f.overclaims, "confirmed": f.confirmed,
                      "unwitnessed": f.unwitnessed, "base_rate": round(f.base_rate, 4),
                      "cost": round(f.cost, 4), "by_domain": dict(f.by_domain)}
                     for f in folds],
            "grand": {"n": grand.n, "clean": grand.clean, "errors": grand.errors,
                      "confident": grand.confident, "J": grand.overclaims,
                      "confirmed": grand.confirmed, "unwitnessed": grand.unwitnessed,
                      "base_rate": round(grand.base_rate, 4), "cost": round(grand.cost, 4),
                      "by_domain": dict(grand.by_domain),
                      "refold_flips": grand.refold_flips,
                      "rows_not_refolded": grand.rows_not_refolded},
            "peer_b_dirs": [os.path.basename(d) for d in peer_b],
        }
        print(json.dumps(out, indent=2))
        return 0

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # the over-claim excerpts may carry non-cp1252
    except Exception:
        pass

    print("=== writeadmit LIVE results — cross-model / cross-window fold (docs/228 §5) ===\n")
    hdr = f"{'run':<34} {'clean':>5} {'err':>4} {'cw':>4} {'J':>3} {'conf':>4} {'unw':>4} {'rate':>6} {'cost':>8}"
    print(hdr)
    print("-" * len(hdr))
    for f in folds:
        print(f"{f.name:<34} {f.clean:>5} {f.errors:>4} {f.confident:>4} {f.overclaims:>3} "
              f"{f.confirmed:>4} {f.unwitnessed:>4} {f.base_rate:>5.1%} ${f.cost:>7.3f}")
    print("-" * len(hdr))
    print(f"{grand.name:<34} {grand.clean:>5} {grand.errors:>4} {grand.confident:>4} {grand.overclaims:>3} "
          f"{grand.confirmed:>4} {grand.unwitnessed:>4} {grand.base_rate:>5.1%} ${grand.cost:>7.3f}")

    print(f"\ncw = confident write-claims · J = over-claims caught & BLOCKED (the payoff) · "
          f"conf = CONFIRMED writes admitted · unw = unwitnessed (floor abstains)")
    print(f"domains (all single-arm runs): {dict(grand.by_domain)}")
    print(f"  (decisions RE-DERIVED with the current extractor, docs/232 — not the cached bit; "
          f"{grand.refold_flips} row(s) flipped vs cache"
          + (f", {grand.rows_not_refolded} fell back to cache" if grand.rows_not_refolded else "")
          + ")")
    if grand.blocked_not_overclaim:
        print(f"  ⚠ INTEGRITY: {grand.blocked_not_overclaim} blocked rows are NOT over-claims "
              f"(the J identity expects 0 — investigate the gate)")
    else:
        print("  ✓ J identity holds: every blocked row is a witness-refuted over-claim.")

    if grand.overclaim_rows:
        print(f"\n=== the {len(grand.overclaim_rows)} live over-claims caught (J), verbatim ===")
        for r in grand.overclaim_rows:
            ex = (r.get("answer_excerpt") or "").replace("\n", " ")[:72]
            print(f"  {r.get('domain'):<8}/{str(r.get('task_id')):<4} db_match=False  \"{ex}\"")

    if peer_b:
        print(f"\npeer-B A/B run dirs (separate causal experiment, NOT in the J total above): "
              f"{[os.path.basename(d) for d in peer_b]}")

    print(f"\nHEADLINE: J = {grand.overclaims} live over-claims caught & blocked off the env "
          f"DB-hash, across {grand.clean} clean tasks "
          f"({grand.confident} confident writes; {grand.confirmed} honest writes correctly "
          f"admitted), total spend ${grand.cost:.2f}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
