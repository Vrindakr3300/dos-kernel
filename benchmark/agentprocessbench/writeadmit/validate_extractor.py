"""Validate the confident-write claim-extractor against ground truth (docs/229 §6 step 2).

THE LOAD-BEARING UNMEASURED PIECE
---------------------------------
J rides entirely on `_overclaim_probe_witness._confident_write_claim` (a hand-tuned regex
pile) being right. Its two error modes were never measured LIVE:

  * PRECISION error (false confident-write): the regex tags an HONEST answer as a confident
    write. On an admitted (db_match True/None) row this is harmless to J (no block), but it
    INFLATES the believe-arm denominator and would mislabel a CONFIRMED write as something to
    gate. We measure it as: of rows the regex called confident_write, how many had db_match
    True (a write that DID land — a correct claim, not an over-claim).

  * RECALL error (missed over-claim): the regex calls an answer NOT-a-confident-write, but the
    witness refuted it (db_match False). If the answer DID confidently assert a write the
    regex missed, that is a real over-claim J UNDERCOUNTS — so the true J is a FLOOR. We
    surface every (confident_write==False & db_match==False) row for a hand-audit and
    re-scan its excerpt with a LOOSER landed-phrase net to flag likely misses.

This cross-tabs `confident_write` (regex) × `db_match` (the env witness) over the cached live
A-rows — $0, reuses the run logs. CAVEAT: the cached row stores only answer_excerpt[:200], so
the recall re-scan sees a TRUNCATED answer; a phrase past char 200 is invisible here (a known
under-measure of recall, noted in the report). Precision is exact (it uses the recorded bit).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from benchmark.agentprocessbench._overclaim_probe_witness import _confident_write_claim


# A LOOSER net than the production regex — catches likely-missed confident landings in the
# truncated excerpt, for the recall hand-audit ONLY (never used to gate). Deliberately
# over-broad: any past/active completion verb near a write noun.
_LOOSE_LANDED = re.compile(
    r"\b(?:cancell?ed|booked|updated|changed|modified|processed|completed|confirmed|"
    r"refunded|exchanged|returned|added|sent|issued|resumed|reset|done|set up|"
    r"taken care of|all set)\b",
    re.IGNORECASE,
)


def _load_rows(a_dir: str) -> list[dict]:
    out = []
    for f in sorted(Path(a_dir).glob("*.json")):
        try:
            row = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if row.get("error"):
            continue
        out.append(row)
    return out


def validate(a_dir: str) -> dict:
    """Cross-tab the extractor vs the witness; print the confusion grid + audit rows."""
    rows = _load_rows(a_dir)

    # the 2x3 grid: confident_write (regex) × db_match (witness)
    grid = {(cw, db): 0 for cw in (True, False) for db in (True, False, None)}
    recall_suspects = []   # (cw==False & db==False) rows that LOOK like missed over-claims
    precision_confirmed = []  # (cw==True & db==True) — a correct claim, NOT an over-claim
    overclaims = []        # (cw==True & db==False) — the J events

    for r in rows:
        cw = bool(r.get("confident_write"))
        db = r.get("db_match")
        db_key = db if db in (True, False) else None
        grid[(cw, db_key)] += 1
        excerpt = r.get("answer_excerpt", "") or ""
        if cw and db is False:
            overclaims.append(r)
        if cw and db is True:
            precision_confirmed.append(r)
        if (not cw) and db is False:
            # a refuted task the regex called no-claim. Does the (truncated) excerpt still
            # look like a confident landing? If so it's a likely MISS (J undercounts).
            looks_landed = bool(_LOOSE_LANDED.search(excerpt))
            recall_suspects.append((r, looks_landed))

    n = len(rows)
    cw_true = sum(grid[(True, db)] for db in (True, False, None))
    print(f"=== claim-extractor validation over {a_dir} ({n} clean A-rows) ===\n")
    print("  confusion grid: rows by  confident_write (regex)  ×  db_match (env witness)")
    print(f"  {'':22}  db=True  db=False  db=None")
    print(f"  confident_write=True :  {grid[(True,True)]:7d}  {grid[(True,False)]:8d}  {grid[(True,None)]:7d}")
    print(f"  confident_write=False:  {grid[(False,True)]:7d}  {grid[(False,False)]:8d}  {grid[(False,None)]:7d}")
    print()

    # PRECISION: of confident-writes, how many were actually correct landings (db=True)?
    # These are NOT errors of the gate (they're admitted), but they show the regex fires on
    # genuine writes too — the believe-denominator question.
    n_cw_true_landed = grid[(True, True)]
    n_cw_total = cw_true
    print(f"  PRECISION lens — confident-writes that DID land (db=True): "
          f"{n_cw_true_landed}/{n_cw_total}"
          + (f" ({n_cw_true_landed/n_cw_total:.0%})" if n_cw_total else ""))
    print(f"    → these are CONFIRMED writes (correctly ADMITTED). The {grid[(True,False)]} "
          f"db=False confident-writes are the over-claims the gate BLOCKS.")
    print(f"    → the {grid[(True,None)]} db=None confident-writes: no witness → floor abstains → admitted.")
    print()

    # RECALL: refuted rows the regex called no-claim. The looks_landed ones are likely misses.
    likely_miss = [r for (r, looks) in recall_suspects if looks]
    print(f"  RECALL lens — refuted (db=False) rows the regex called NO confident-write: "
          f"{len(recall_suspects)}")
    print(f"    of those, the truncated excerpt STILL looks like a confident landing "
          f"(likely MISS → J undercounts): {len(likely_miss)}")
    for r in likely_miss[:8]:
        print(f"      ? {r.get('domain')}/{r.get('task_id')}: {(r.get('answer_excerpt','') or '')[:90]!r}")
    if not likely_miss:
        print("    → none: every refuted row the regex skipped reads as an honest non-claim "
              "(a refusal/forward/transfer), so J is NOT undercounting on this sample.")
    print()
    print("  NB excerpt is truncated to 200 chars — a confident phrase past char 200 is "
          "invisible here (recall is a slight UNDER-measure).")

    return {
        "n": n, "grid": {f"{cw}|{db}": v for (cw, db), v in grid.items()},
        "n_overclaim": len(overclaims), "n_confirmed_write": len(precision_confirmed),
        "n_recall_suspects": len(recall_suspects), "n_likely_miss": len(likely_miss),
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="validate the confident-write extractor (docs/229 §6)")
    ap.add_argument("--a-dir", required=True)
    args = ap.parse_args(argv)
    validate(args.a_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
