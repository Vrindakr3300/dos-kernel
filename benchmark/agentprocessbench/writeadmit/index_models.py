"""Cross-model index for the E-TAU2-WRITEADMIT live runs (docs/232).

docs/228 measured the out-of-loop write-admission payoff (J=5) on ONE model
(gemini-2.5-flash) and explicitly flagged "Small n, one model. More tasks + a second
model would harden the base-rate." This folds EVERY per-model result dir into one
indexed summary: per model J (over-claims the gate blocked), the live over-claim
base-rate, confirmed-honest-writes admitted, and the per-domain split — plus a combined
roll-up. The gate's two soundness directions (admit CONFIRMED, block REFUTED) are
reported separately so a regression in either is visible.

It reads the gitignored `live_results_*/` dirs (which carry the Gemini key in seed
configs) but EMITS only a folded summary — counts + claim excerpts, never the key, never
a raw transcript — so the summary JSON is safe to COMMIT as the durable index.

Usage:
  python index_models.py                 # human table over all configured models
  python index_models.py --json out.json # also write the committable summary JSON
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

try:  # the Windows console is cp1252 by default; the table uses no non-ASCII now, but be safe
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# When run as a script (`python index_models.py`) the package root is not on sys.path, so
# the absolute fallback import in _fresh_decision (and the re-fold it enables) would fail.
# Add the repo root so `benchmark.agentprocessbench…` resolves either way.
_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The models indexed, in report order. (label, result-dir). Add a row to index a new model.
HERE = Path(__file__).resolve().parent
MODELS = [
    ("gemini-2.5-flash", HERE / "live_results_m1_flash25"),
    ("gemini-2.5-pro", HERE / "live_results_m2_pro25"),
]


def _fresh_decision(row: dict):
    """Re-derive (confident_write, admit, verdict) from the row's answer text with the
    CURRENT gate, instead of trusting the row's cached bits.

    WHY (docs/235, the J=4-vs-5 reconciliation): a long resumable batch caches each row's
    `confident_write` at the time it ran. If the claim-extractor changes MID-RUN (here the
    `_IDIOM_LANDED` "you're all set" idiom landed while the pro batch was in flight), the
    cache mixes pre- and post-fix bits and the inline count is stale. Re-folding through the
    current extractor is the trustworthy number — and on the pro run it flips airline 8 from
    a missed over-claim to a counted one, lifting pro from J=4 to J=5 (identical to flash).
    The lesson generalized: trust a re-fold over a cached bit when the code changed under it.

    Falls back to the cached fields if the extractor/gate can't be imported (so the index
    still runs in a stripped checkout), recording which path was used.
    """
    answer = str(row.get("answer_excerpt", "") or "")
    dm = row.get("db_match")
    try:
        try:
            from .gate import admit  # when imported as a package module
        except ImportError:
            from benchmark.agentprocessbench.writeadmit.gate import admit  # when run as a script
        d = admit(answer, dm)
        return d.confident_write, d.admit, d.verdict, True
    except Exception:
        return row.get("confident_write"), row.get("admit"), row.get("verdict"), False


def _fold_dir(d: Path) -> dict:
    """Fold one model's result dir into the writeadmit statistics.

    OVER-CLAIM EVENT = the agent made a confident write-claim AND the env DB-hash refuted
    it (db_match is False). J = over-claims the adjudicate gate BLOCKED (admit is False) —
    phantom writes a peer B never inherits. CONFIRMED = confident write the witness backs
    (db_match True); we check the gate ADMITTED it (does not block correct work).

    The (confident_write, admit, verdict) triple is RE-DERIVED with the current extractor
    (see `_fresh_decision`), not read from the cached row — robust to a mid-run extractor
    change (docs/235).
    """
    rows = [json.loads(Path(f).read_text(encoding="utf-8")) for f in glob.glob(str(d / "*.json"))]
    ok = [r for r in rows if "error" not in r]
    errs = [r for r in rows if "error" in r]
    by_dom: dict[str, dict] = {}
    overclaims = []
    confirmed_admitted = confirmed_total = 0
    cw = 0
    spend = 0.0
    refolded = True
    for r in ok:
        dom = r.get("domain", "?")
        dd = by_dom.setdefault(dom, {"clean": 0, "cw": 0, "overclaim": 0, "blocked": 0})
        dd["clean"] += 1
        dm = r.get("db_match")
        c = r.get("agent_cost")
        if isinstance(c, (int, float)):
            spend += float(c)
        confident_write, admit_bit, verdict, was_refold = _fresh_decision(r)
        refolded = refolded and was_refold
        if confident_write:
            cw += 1
            dd["cw"] += 1
            if dm is False:
                dd["overclaim"] += 1
                blocked = admit_bit is False
                if blocked:
                    dd["blocked"] += 1
                overclaims.append({
                    "domain": dom, "task_id": r.get("task_id"),
                    "verdict": verdict, "admit": admit_bit,
                    "blocked": blocked, "claim": str(r.get("answer_excerpt", ""))[:140],
                })
            elif dm is True:
                confirmed_total += 1
                if admit_bit:
                    confirmed_admitted += 1
    blocked_total = sum(1 for o in overclaims if o["blocked"])
    n_false = sum(1 for r in ok if r.get("db_match") is False)
    return {
        "n_clean": len(ok),
        "n_error": len(errs),
        "n_confident_write": cw,
        "n_overclaim_events": len(overclaims),
        "J_blocked": blocked_total,
        "n_confirmed_writes": confirmed_total,
        "n_confirmed_admitted": confirmed_admitted,
        "live_refute_base_rate": (n_false / len(ok)) if ok else 0.0,
        "overclaim_base_rate": (len(overclaims) / len(ok)) if ok else 0.0,
        "approx_spend_usd": round(spend, 4),
        "refolded_with_current_extractor": refolded,
        "by_domain": by_dom,
        "overclaims": overclaims,
    }


def build_index(models=MODELS) -> dict:
    per_model = {}
    for label, d in models:
        if not Path(d).exists():
            per_model[label] = {"missing": True, "dir": str(d)}
            continue
        per_model[label] = _fold_dir(Path(d))
    # combined roll-up over models that ran
    ran = [m for m in per_model.values() if not m.get("missing")]
    combined = {
        "n_clean": sum(m["n_clean"] for m in ran),
        "n_error": sum(m["n_error"] for m in ran),
        "n_confident_write": sum(m["n_confident_write"] for m in ran),
        "n_overclaim_events": sum(m["n_overclaim_events"] for m in ran),
        "J_blocked": sum(m["J_blocked"] for m in ran),
        "n_confirmed_writes": sum(m["n_confirmed_writes"] for m in ran),
        "n_confirmed_admitted": sum(m["n_confirmed_admitted"] for m in ran),
        "approx_spend_usd": round(sum(m["approx_spend_usd"] for m in ran), 4),
    }
    combined["overclaim_base_rate"] = (
        combined["n_overclaim_events"] / combined["n_clean"] if combined["n_clean"] else 0.0
    )
    return {"experiment": "E-TAU2-WRITEADMIT", "doc": "docs/232",
            "per_model": per_model, "combined": combined}


def _print_table(idx: dict) -> None:
    print("\n=== E-TAU2-WRITEADMIT — cross-model index (docs/232) ===\n")
    hdr = f"{'model':<20} {'clean':>5} {'err':>4} {'cw':>4} {'over':>5} {'J':>3} {'conf-ok/n':>9} {'oc-rate':>8} {'$':>7}"
    print(hdr); print("-" * len(hdr))
    for label, m in idx["per_model"].items():
        if m.get("missing"):
            print(f"{label:<20}  (no results dir yet: {m['dir']})")
            continue
        conf = f"{m['n_confirmed_admitted']}/{m['n_confirmed_writes']}"
        print(f"{label:<20} {m['n_clean']:>5} {m['n_error']:>4} {m['n_confident_write']:>4} "
              f"{m['n_overclaim_events']:>5} {m['J_blocked']:>3} {conf:>8} "
              f"{m['overclaim_base_rate']:>7.1%} {m['approx_spend_usd']:>7.2f}")
    c = idx["combined"]
    print("-" * len(hdr))
    conf = f"{c['n_confirmed_admitted']}/{c['n_confirmed_writes']}"
    print(f"{'COMBINED':<20} {c['n_clean']:>5} {c['n_error']:>4} {c['n_confident_write']:>4} "
          f"{c['n_overclaim_events']:>5} {c['J_blocked']:>3} {conf:>8} "
          f"{c['overclaim_base_rate']:>7.1%} {c['approx_spend_usd']:>7.2f}")
    # per-model over-claim detail (the J ledger)
    for label, m in idx["per_model"].items():
        if m.get("missing") or not m.get("overclaims"):
            continue
        print(f"\n  {label} — the {m['J_blocked']} blocked over-claim(s) (J ledger):")
        for o in m["overclaims"]:
            mark = "BLOCKED" if o["blocked"] else "ADMITTED(!)"
            print(f"    {o['domain']}/{o['task_id']:<3} {o['verdict']:<9} {mark:<11} | {o['claim']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="cross-model writeadmit index (docs/232)")
    ap.add_argument("--json", default=None, help="write the committable summary JSON here")
    args = ap.parse_args(argv)
    idx = build_index()
    _print_table(idx)
    if args.json:
        Path(args.json).write_text(json.dumps(idx, indent=2), encoding="utf-8")
        print(f"\nwrote summary index -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
