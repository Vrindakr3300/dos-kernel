"""feasibility_split — the EnterpriseOps adapter + the TWO right-denominator scores (docs/198).

This is the operational successor to `feasibility_witness.py`: it reuses that module's $0 reads,
but routes them through the shared, benchmark-agnostic `_feasibility` primitive so the SAME split
runs on every DOS benchmark (Toolathlon, the academic sets) with only an adapter swap. The point
docs/198 makes — *split the population BEFORE scoring any cure* — is here made the default surface.

It produces, all $0 (recorded corpus, no Gemini / no gym):

  1. THE WITNESS — per tool, WALLED (0 successes anywhere = infeasible) vs CURABLE (a path exists).
     Env-authored, byte-clean (a non-error tool result is the gym's own reply).

  2. THE POPULATION SPLIT — every run routed to WALLED / CURABLE / NO_THRASH, so a conversion A/B
     scores the CURABLE slice only and a give-up-correctly arm scores the WALLED slice only. This
     is the cure for the category error (scoring conversion against infeasible tasks).

  3. THE WITNESS-GATED EARLY-HALT SCORE — the give-up-correctly value on WALLED runs, on the
     HONEST task-success denominator (false-abandon = halting a run that ACTUALLY succeeds). The
     docs/198 §2 sharpening: fire EARLIER and harder when the thrashing tool is WALLED. Compared
     head-to-head with the un-gated halt (fire on ANY Kth same-tool error) so the gate's value is
     legible: the witness-gated halt fires only where conversion is impossible, so its false-abandon
     is structurally 0 (you cannot kill a winner on a tool that never wins).

  4. THE CURABLE-SLICE CONVERSION READ — none vs each recorded cure arm, scored on the CURABLE
     slice ALONE (fired-flip net on the task-success denominator). This is "the experiment never
     run" — and on the current corpus it is UNDERPOWERED (n is tiny because natural thrash is rare
     and mostly on the one walled tool), so the read PRINTS the power and refuses to over-claim.

The EnterpriseOps struct-error grammar is imported BYTE-IDENTICALLY from `dos_react` (the
same-signal discipline, one-way arrow, never kernel). Run:

    python feasibility_split.py                          # all four reads over the natural A/B
    python feasibility_split.py --ks 2 3 4 --cure rewind_natural
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _BENCH)

# the shared agnostic primitive (CONSUMER side, never kernel)
from _feasibility import (  # noqa: E402
    ToolEvent, Verdict, Feasibility, feasibility_witness, fold_tool_stats,
    classify_run, split_corpus,
)
# the BYTE-IDENTICAL EnterpriseOps struct-error grammar (same signal as the live gate)
from dos_react import _is_struct_error, _result_text, _is_blocked_result  # noqa: E402


# --------------------------------------------------------------------------- adapter
def run_events(run: dict) -> List[ToolEvent]:
    """The EnterpriseOps adapter: a recorded run's `tool_results` -> agnostic ToolEvents.
    Excludes DOS-BLOCK synthetics (self-laundering guard) and empty tool names. is_error uses
    the live gate's own grammar so the witness sees the SAME bytes the live arm fires on."""
    out = []
    for tr in (run.get("tool_results") or []):
        if _is_blocked_result(tr):
            continue
        t = str(tr.get("tool_name", ""))
        if not t:
            continue
        out.append(ToolEvent(t, _is_struct_error(_result_text(tr))))
    return out


def _est_tokens(obj) -> int:
    """char/4 proxy for tool-result payload tokens (the restart_arm rule; relative ordering only)."""
    try:
        return len(json.dumps(obj, default=str)) // 4
    except (TypeError, ValueError):
        return len(str(obj)) // 4


def _sign_test_p(help_: int, discordant: int) -> Optional[float]:
    """Two-sided exact binomial (sign / McNemar) p-value for `help_` successes in `discordant`
    Bernoulli(0.5) trials. None if there are no discordant pairs (the cure changed nothing). Pure
    stdlib (math.comb), no scipy — the kernel-adjacent no-heavy-dep discipline."""
    import math
    n = discordant
    if n == 0:
        return None
    # P(X = k) under Binom(n, 0.5); two-sided = sum of probs <= P(observed)
    probs = [math.comb(n, k) * (0.5 ** n) for k in range(n + 1)]
    obs = probs[help_]
    return min(1.0, sum(p for p in probs if p <= obs + 1e-12))


def _runs(arm_glob):
    for f in sorted(glob.glob(arm_glob)):
        try:
            r = (json.load(open(f, encoding="utf-8")).get("runs") or [{}])[0]
        except Exception:
            continue
        yield f, r


def _tid(f):
    b = os.path.basename(f).replace("results_", "").replace(".json", "")
    return b


# --------------------------------------------------------------------------- early-halt
def _incremental_fire(run: dict, tool_name: str, k: int) -> Optional[int]:
    """The tool_results index where `tool_name` first reaches its Kth struct error with the Kth
    still erroring (the live `natural_thrash_gate` site, replayed over the growing prefix)."""
    err = 0
    for i, tr in enumerate(run.get("tool_results") or []):
        if str(tr.get("tool_name", "")) != tool_name or _is_blocked_result(tr):
            continue
        if _is_struct_error(_result_text(tr)):
            err += 1
            if err >= k:
                return i
    return None


def _tail_tokens(run: dict, fire_idx: int) -> int:
    """Tokens averted by halting at fire_idx (the whole tail after the fire)."""
    saved = 0
    for j, tr in enumerate(run.get("tool_results") or []):
        if j > fire_idx:
            saved += _est_tokens(tr.get("result"))
    return saved


def early_halt_score(none_runs: Dict[str, dict], witness: Dict[str, Verdict],
                     ks: Sequence[int], *, gated: bool) -> Dict[int, dict]:
    """Score early-halt on the TASK-SUCCESS denominator. `gated=True` is the docs/198 §2 sharpening:
    only fire on a WALLED thrash tool (fire harder where conversion is impossible). `gated=False` is
    the un-gated halt (fire on the first Kth same-tool error, any tool). false_abandon = we'd halt a
    run whose overall_success is True (kill a winner). On a WALLED population that is structurally 0."""
    out = {}
    for k in ks:
        fired = false_abandon = tok_saved = 0
        for r in none_runs.values():
            # which tools can fire? gated => walled thrash tools only; ungated => any tool
            tools = {str(tr.get("tool_name", "")) for tr in (r.get("tool_results") or [])
                     if tr.get("tool_name")}
            if gated:
                tools = {t for t in tools if witness.get(t) is Verdict.WALLED}
            fires = {}
            for t in tools:
                idx = _incremental_fire(r, t, k)
                if idx is not None:
                    fires[t] = idx
            if not fires:
                continue
            # the live arm halts the FIRST fire
            _t, fire_idx = min(fires.items(), key=lambda kv: kv[1])
            fired += 1
            if r.get("overall_success"):
                false_abandon += 1
            tok_saved += _tail_tokens(r, fire_idx)
        out[k] = {"fired": fired, "false_abandon": false_abandon,
                  "fa_rate": (false_abandon / fired) if fired else 0.0,
                  "tokens_saved": tok_saved}
    return out


# --------------------------------------------------------------------------- conversion
def conversion_on_curable(none_runs: Dict[str, dict], cure_runs: Dict[str, dict],
                          witness: Dict[str, Verdict]) -> dict:
    """The curable-slice conversion read: paired none-vs-cure, scored on the CURABLE slice ALONE.
    fired-flip net = (help - hurt) on runs where the none arm thrashed on a CURABLE tool. Returns
    the net AND the n, so the caller can refuse to over-claim when underpowered."""
    paired = sorted(set(none_runs) & set(cure_runs))
    slices = {Feasibility.WALLED: [], Feasibility.CURABLE: [], Feasibility.NO_THRASH: []}
    for tid in paired:
        cls = classify_run(run_events(none_runs[tid]), witness)
        slices[cls].append(tid)

    def net(ids):
        help_ = hurt = same = 0
        for tid in ids:
            a = bool(none_runs[tid].get("overall_success"))
            b = bool(cure_runs[tid].get("overall_success"))
            if b and not a:
                help_ += 1
            elif a and not b:
                hurt += 1
            else:
                same += 1
        # The paired fail<->pass flips are a SIGN TEST (McNemar's, exact binomial on the
        # discordant pairs): under H0 "the cure does nothing", help and hurt are each Binom(d, 0.5)
        # where d = help + hurt. A bare net>0 is NOT a result — with d=2 (the live n=6 slice) even
        # net=+2 is p=0.25, not significant. Reporting p forces the honesty docs/198 §3 demands.
        d = help_ + hurt
        p = _sign_test_p(help_, d)
        return {"n": len(ids), "help": help_, "hurt": hurt, "same": same,
                "net": help_ - hurt, "discordant": d, "sign_p": p,
                "significant": (p is not None and p < 0.05 and help_ > hurt)}

    return {
        "paired": len(paired),
        "all": net(paired),
        "no_thrash": net(slices[Feasibility.NO_THRASH]),
        "walled": net(slices[Feasibility.WALLED]),
        "curable": net(slices[Feasibility.CURABLE]),
        "curable_ids": slices[Feasibility.CURABLE],
    }


# --------------------------------------------------------------------------- main
def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"))
    ap.add_argument("--ks", type=int, nargs="+", default=[2, 3, 4])
    ap.add_argument("--cure", default="rewind_natural", help="the cure arm to read conversion for")
    ap.add_argument("--min-obs", type=int, default=3, help="min errors before a tool can be WALLED")
    ap.add_argument("--min-curable-n", type=int, default=30,
                    help="the powered threshold for a curable-slice conversion claim (docs/198 §4.2)")
    ap.add_argument("--emit-walled", metavar="PATH", default=None,
                    help="write the WALLED tool set to a JSON file (DATA, not source) for the live "
                         "DOS_ABANDON arm to read — keeps corpus-specific identity out of code")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    # load the corpus (all arms for the witness; none + cure for the splits)
    all_corpus = [run_events(r) for _f, r in _runs(os.path.join(args.out, "*", "results_*.json"))]
    none_runs = {_tid(f): r for f, r in _runs(os.path.join(args.out, "none", "results_*.json"))}
    cure_runs = {_tid(f): r for f, r in _runs(os.path.join(args.out, args.cure, "results_*.json"))}

    witness = feasibility_witness(all_corpus, min_obs=args.min_obs)
    stats = fold_tool_stats(all_corpus)

    # 1) the witness
    walled = sorted(t for t, v in witness.items() if v is Verdict.WALLED)
    # the WALLED-set-as-DATA emit: the live DOS_ABANDON arm reads this JSON so the corpus-specific
    # tool identity is never hardcoded in source (the judge-panel's cleanest-layering point).
    if args.emit_walled:
        with open(args.emit_walled, "w", encoding="utf-8") as f:
            json.dump({"walled_tools": walled, "min_obs": args.min_obs,
                       "corpus": os.path.basename(args.out.rstrip("/\\")),
                       "schema": "dos.feasibility.walled.v1"}, f, indent=2)
        print(f"[feasibility_split] wrote WALLED set ({len(walled)} tools) -> {args.emit_walled}")
    # 2) the split (over the none arm — the baseline trajectory determines feasibility class)
    split = split_corpus({t: run_events(r) for t, r in none_runs.items()}, witness)
    # 3) early-halt, gated vs ungated
    gated = early_halt_score(none_runs, witness, args.ks, gated=True)
    ungated = early_halt_score(none_runs, witness, args.ks, gated=False)
    # 4) curable-slice conversion
    conv = conversion_on_curable(none_runs, cure_runs, witness) if cure_runs else None

    if args.json:
        print(json.dumps({
            "walled_tools": walled,
            "split_counts": split.counts(),
            "early_halt_gated": gated,
            "early_halt_ungated": ungated,
            "conversion": conv,
        }, indent=2, default=str))
        return 0

    print("=" * 80)
    print("  FEASIBILITY SPLIT — split the population BEFORE scoring any cure (docs/198)")
    print(f"  corpus: {args.out}   runs(none)={len(none_runs)}  cure={args.cure} ({len(cure_runs)})")
    print("=" * 80)
    print(f"  {'tool':<30}{'ok':>6}{'err':>6}   verdict")
    print("-" * 80)
    for t in sorted(stats, key=lambda x: -stats[x].err):
        s = stats[t]
        if s.err < args.min_obs:
            continue
        print(f"  {t:<30}{s.ok:>6}{s.err:>6}   {witness[t].value}")
    print("-" * 80)
    print(f"  WALLED tools (conversion is a category error here): {walled or '(none)'}")
    print()
    print("  POPULATION SPLIT (none arm) — score conversion on CURABLE, give-up on WALLED:")
    for k, v in split.counts().items():
        print(f"    {k:<12} {v}")
    print()

    # 3) early-halt
    print("=" * 80)
    print("  GIVE-UP-CORRECTLY (early-halt) on the TASK-SUCCESS denominator")
    print("  GATED = fire only on a WALLED thrash (docs/198 §2: fire harder where infeasible)")
    print("=" * 80)
    print(f"  {'K':>3}  {'--- WITNESS-GATED ---':^34}   {'--- UN-GATED (any tool) ---':^34}")
    print(f"  {'':>3}  {'fired':>7}{'FA':>5}{'FA-rate':>9}{'tok-saved':>12}   "
          f"{'fired':>7}{'FA':>5}{'FA-rate':>9}{'tok-saved':>12}")
    print("-" * 80)
    halt_passes = []
    for k in args.ks:
        g, u = gated[k], ungated[k]
        if g["fa_rate"] < 0.10 and g["tokens_saved"] > 0:
            halt_passes.append(k)
        print(f"  {k:>3}  {g['fired']:>7}{g['false_abandon']:>5}{g['fa_rate']:>9.3f}{g['tokens_saved']:>12}   "
              f"{u['fired']:>7}{u['false_abandon']:>5}{u['fa_rate']:>9.3f}{u['tokens_saved']:>12}")
    print("-" * 80)
    print("  PRE-REGISTERED KILL (docs/194 §5): ship iff EXISTS K: gated FA-rate<0.10 AND saved>0")
    if halt_passes:
        best = min(halt_passes)
        print(f"  -> PASSES at K={halt_passes}. Witness-gated early-halt SHIPS (cheap-model tier).")
        print(f"     cheapest K={best}: FA {gated[best]['fa_rate']:.3f}, {gated[best]['tokens_saved']} "
              f"tokens saved, {gated[best]['fired']} runs halted (all on a WALLED wall).")
    else:
        print("  -> no K clears it on this corpus (no walled thrash to halt) — detection-only.")

    # 4) conversion
    if conv is not None:
        print()
        print("=" * 80)
        print(f"  CURABLE-SLICE CONVERSION — none vs {args.cure}, the experiment docs/198 §3 frames")
        print("  fired-flip NET (help - hurt) on the task-success denominator, per population")
        print("=" * 80)
        print(f"  {'slice':<22}{'n':>5}{'help':>6}{'hurt':>6}{'same':>6}{'NET':>6}{'sign-p':>9}")
        print("-" * 80)
        for name, key in (("all paired", "all"), ("no-thrash", "no_thrash"),
                          ("WALLED-only", "walled"), ("has CURABLE thrash", "curable")):
            c = conv[key]
            pp = f"{c['sign_p']:.3f}" if c["sign_p"] is not None else "  n/a"
            print(f"  {name:<22}{c['n']:>5}{c['help']:>6}{c['hurt']:>6}{c['same']:>6}{c['net']:>+6}{pp:>9}")
        print("-" * 80)
        cn = conv["curable"]["n"]
        cc = conv["curable"]
        print(f"  CURABLE slice n={cn}, discordant pairs d={cc['discordant']}; "
              f"powered threshold (docs/198 §4.2) = {args.min_curable_n}.")
        # the kill is BOTH: powered (n>=threshold) AND significant (sign-test p<0.05, help>hurt).
        if cn < args.min_curable_n or cc["discordant"] < 6:
            print(f"  -> UNDERPOWERED. The curable-slice conversion A/B is GENUINELY UNTESTED — the")
            print(f"     natural thrash rate is too low to settle it on the recorded corpus (d="
                  f"{cc['discordant']} flips; a sign test needs d>=6 to even reach p<0.05). It needs")
            print(f"     TARGETED re-runs that over-sample the curable-thrash tasks (see")
            print(f"     curable_oversample.py for the recipe). DO NOT read the curable NET as a")
            print(f"     result — with d={cc['discordant']}, sign-p={cc['sign_p']}. (docs/198 §3 discipline.)")
        elif cc["significant"]:
            print(f"  -> POWERED + SIGNIFICANT (n={cn}, NET={cc['net']:+d}, sign-p={cc['sign_p']:.3f}<0.05).")
            print(f"     The cure CONVERTS on the slice where conversion is coherent.")
        else:
            print(f"  -> POWERED but NOT significant (n={cn}, NET={cc['net']:+d}, "
                  f"sign-p={cc['sign_p']:.3f}). Conversion is null/weak even where feasible.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
