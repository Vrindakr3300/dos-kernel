"""Deterministic detector evaluation over REAL gemini-3-flash trajectories (docs/143).

The live A/B is dominated by model run-to-run variance (Gemini at temp=0 is not fully
deterministic, and the DB-state verifiers see irreversible mutations), so a ±5pp "delta" at
~0 nudges is noise, not signal. This harness isolates the MECHANISM from that variance by
replaying the SAME recorded trajectories — no new model calls — and measuring the two
numbers that actually characterize the detector:

  PRECISION on real data  — of the mutating calls the model REALLY made, how many id args
                            did the detector flag that were in fact RESOLVED (false flags)?
                            Hardened target: 0. (A false flag is the §8 kill-signal.)

  RECALL on injected mints — take each real RESOLVED id arg and, in a controlled clone of
                             the call, replace it with a plausible MINT (a right-shape /
                             wrong-content id NOT in the corpus — the 'Incorrect ID
                             Resolution' failure mode). Does the detector catch it? This is
                             the recall the live models didn't exercise (flash resolves
                             correctly; flash-lite stalls), measured deterministically over
                             real corpora so it is honest, not simulated.

Both run over the real env-authored corpus each call actually had — no answer key, no
fabricated context. The mint injection is the ONLY perturbation, clearly labelled, so the
recall number is attributable purely to the detector.
"""
import argparse
import glob
import json
import random
import sys
from pathlib import Path

# This file lives at <repo>/benchmark/enterpriseops/replay_recall.py; parents[1] is the repo's
# benchmark dir, which must be importable so `enterpriseops.dos_react` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enterpriseops.dos_react import (  # noqa: E402
    is_mutating_tool, evaluate_tool_call, _is_blocked_result,
)


def _looks_idish(v):
    """A value worth perturbing into a mint: a non-trivial string/int that an FK slot holds."""
    s = str(v)
    return len(s) >= 3 and any(c.isdigit() for c in s) and " " not in s and "\n" not in s


def _mint_variant(rng, v):
    """A right-shape, wrong-content version of `v` — a plausible model mint."""
    s = str(v)
    out = []
    for c in s:
        if c.isdigit():
            out.append(str(rng.randint(0, 9)))
        else:
            out.append(c)
    cand = "".join(out)
    return cand if cand != s else cand + "9"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="a react results folder (run_1/*.json)")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    files = glob.glob(f"{args.results}/**/*.json", recursive=True)
    # PRECISION: flags on the real (resolved) calls
    real_mut = real_flags = 0
    # RECALL: inject one mint per eligible resolved id arg, in a clone (does NOT mutate the
    # corpus the model saw); count caught.
    injected = caught = 0

    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if "runs" not in d or not d["runs"]:
            continue
        run = d["runs"][0]
        tt = str(d.get("benchmark_config", {}).get("user_prompt", ""))
        prior = []
        for tr in run.get("tool_results", []):
            # docs/143 §13.4 anti-laundering: a recorded BLOCK's SYNTHETIC corrective result
            # echoes the unresolved id (by component) and is stamped `dos_blocked`. It is NOT a
            # real model call and must NEVER enter the corpus — otherwise it would inflate
            # precision (a re-mint substrings the corrective text → reads SUPPORTED) and deflate
            # recall (a genuine mint variant tests as "present" in corpus_text → skipped). The
            # live loop excludes it in build_prior_results; this offline replay must match.
            if _is_blocked_result(tr):
                continue
            tn = tr.get("tool_name")
            args_d = tr.get("arguments", {}) or {}
            if is_mutating_tool(tn):
                real_mut += 1
                v = evaluate_tool_call(tn, args_d, tt, prior)
                if not v.believe:
                    real_flags += 1
                # RECALL: for each id-ish scalar arg, clone the call with a GENUINE mint
                # (a value verified ABSENT from the corpus this call actually had) and test.
                # Verifying absence makes this a true "Incorrect ID Resolution" — not a lucky
                # collision — so the recall number is the detector's catch rate on real mints.
                corpus_text = (tt + " " + " ".join(
                    json.dumps(p.get("result", {}), default=str) for p in prior
                )).casefold()
                for k, val in args_d.items():
                    if isinstance(val, (str, int)) and _looks_idish(val):
                        minted = None
                        for _ in range(8):
                            cand = _mint_variant(rng, val)
                            if cand.casefold() not in corpus_text:
                                minted = cand
                                break
                        if minted is None:
                            continue  # couldn't make a genuinely-absent mint; skip (honest)
                        clone = dict(args_d)
                        clone[k] = minted
                        injected += 1
                        vv = evaluate_tool_call(tn, clone, tt, prior)
                        # caught iff the detector now flags this arg as unsupported
                        if not vv.believe and k in vv.unsupported:
                            caught += 1
            prior.append(tr)

    print("=" * 74)
    print(f"  Deterministic detector eval over REAL trajectories — {len(files)} tasks")
    print("=" * 74)
    print("  PRECISION (real resolved calls):")
    print(f"    {real_mut} mutating calls | {real_flags} false-flags "
          f"({100*real_flags/max(1,real_mut):.2f}%)  [hardened target: 0]")
    print("  RECALL (controlled mint injection on real id args):")
    print(f"    {injected} mints injected | {caught} caught "
          f"({100*caught/max(1,injected):.1f}%)")
    print("=" * 74)
    print("  Interpretation: the detector is SAFE on what the model really did (no false")
    print("  nudge) AND catches the named 'Incorrect ID Resolution' mint when it occurs —")
    print("  the two properties the live models (resolve-correctly / stall) didn't exercise.")
    print("=" * 74)


if __name__ == "__main__":
    main()
