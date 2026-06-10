"""E1 runner — the distillation falsifier on REAL policy behavior (docs/206 §5).

`verifier.py` runs the `docs/84` distillation on a *simulated* trajectory. This
runs the EXACT same scorer (`verifier.score_feature_set`, unchanged) on the
**real-policy** trajectory mined from session transcripts by `real_trajectory.py`
and adjudicated against real git ancestry. The simulator is gone; the question is
the same:

    Can a cheap claim-side model distil the git verdict, or is it irreducible?

The honest number is the ABLATED one (drops `sha_looks_real`, here meaning "the
result printed a `[ref sha]` commit line"). The strong result is: claim-side shape
recovers the pure-lie/no-op structure and then hits a CEILING at the natural flake
rate — a flake (printed a commit line + files, but the sha is not reachable from
HEAD) is shape-identical to a real landing, so only the git ancestry check
separates them. That ceiling is the proof the referee is non-distillable on real
behavior, not just in simulation.

Run:
    PYTHONPATH=src python -m benchmark.fleet_horizon.verify_real \
        --transcripts ~/.claude/projects/<project>/ --repo .
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import verifier
from .real_trajectory import build_corpus, corpus_summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Distil the kernel's verdict from REAL policy trajectories (docs/206 E1)")
    ap.add_argument("--transcripts", required=True,
                    help="dir of Claude Code session .jsonl transcripts")
    ap.add_argument("--repo", default=".",
                    help="git repo to adjudicate claimed shas against")
    ap.add_argument("--min-bytes", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--strict-head", action="store_true",
                    help="label landings by HEAD ancestry only (default: any ref, "
                         "the conservative rung that cannot inflate the flake count)")
    args = ap.parse_args(argv)

    print(f"mining {args.transcripts} (adjudicating against {args.repo}, "
          f"{'HEAD-ancestry' if args.strict_head else 'any-ref'})...", flush=True)
    steps = build_corpus(Path(args.transcripts), Path(args.repo),
                         min_bytes=args.min_bytes, any_ref=not args.strict_head)
    s = corpus_summary(steps)
    if s["steps"] < 20:
        print(f"too few commit-claims ({s['steps']}) to score; need >=20.")
        return 1

    full = verifier.score_feature_set(steps, seed=args.seed)
    ablated_names = [n for n in verifier.FEATURE_ORDER
                     if n != verifier.ARTIFACT_FEATURE]
    ablated = verifier.score_feature_set(steps, seed=args.seed,
                                         feature_names=ablated_names)

    print("=" * 78)
    print("E1 — can a claim-side verifier DISTIL the kernel's verdict on REAL behavior?")
    print("=" * 78)
    print(f"\nCorpus: {s['steps']} real git-commit claims across {s['sessions']} "
          f"sessions")
    print(f"  landed (in ancestry) {s['landed']} / not-landed {s['not_landed']} "
          f"(base rate {s['base_rate']})")
    print(f"  not-landed split: {s['pure_lie_or_noop']} pure-lie/no-op + "
          f"{s['flakes_shape_identical']} FLAKE (shape-identical to a success)")
    print(f"  train/test: {full.n_train}/{full.n_test} "
          f"(label = sha reachable from HEAD, adjudicated by git)\n")

    print("Can claim-side shape predict ground truth better than guessing?")
    print(f"  {full.headline()}")
    print(f"  {ablated.headline()}")
    print(f"  weights (ablated): {ablated.weights}")

    print("\nThe irreducible residue (the part git CANNOT be distilled out of):")
    a = ablated
    pure_den = a.lies_total - a.flakes_total
    print(f"  claimed-shipped-but-not-in-ancestry in test set : {a.lies_total}")
    print(f"    +- PURE LIES (no commit line) the model flags  : "
          f"{a.pure_lies_caught}/{pure_den}  <- learnable from shape")
    print(f"    +- FLAKES (commit line + files, unreachable)   : "
          f"caught {a.flakes_caught}/{a.flakes_total}  "
          f"<- shape-IDENTICAL to a landing; only git separates them")

    print("\nReading (docs/206 §5 / docs/84 §3), ON REAL POLICY BEHAVIOR:")
    if a.flakes_total > 0 and a.flakes_caught < a.flakes_total:
        print("  -> CONFIRMED: partial distillation with a HARD floor, on real")
        print("     trajectories with the simulator removed. A cheap verifier recovers")
        print("     the pure-lie structure but CANNOT tell a flake from a real landing")
        print("     -- they print the same commit line and the same files. The git")
        print("     ancestry check is IRREDUCIBLE for that residue. E1 confirms the")
        print("     non-distillability floor is a property of real behavior, not the sim.")
    elif a.accuracy <= a.base_rate + 1e-6:
        print("  -> NO distillation: claim-side shape carries no signal beyond base")
        print("     rate. The referee is fully irreducible on this corpus.")
    else:
        print("  -> NULL RESULT: the verifier beats base rate AND clears the flake")
        print("     residue on real behavior -- distillation looks viable here, which")
        print("     would WEAKEN the irreducibility claim (docs/206 §5 E1 null). Report")
        print("     it honestly; the floor was cheapness, not irreplaceability.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
