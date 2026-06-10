"""The legalcite benchmark harness — replay the frozen corpus through the REAL
`citation_resolve.classify()` and measure DETECT recall + FALSE-FIRE rate (docs/279 §4).

$0, deterministic, no network: it reads `frozen_corpus.json` (clusters Free Law Project
authored, captured by `snapshot.py`) and runs each labeled cite through the actual
kernel-driver verdict — NOT a re-implementation. The numbers are therefore a property of
the shipped classifier, not of the harness.

Two headline metrics over a STATED denominator:

  DETECT recall  = fabricated cites flagged (UNRESOLVED or RESOLVED_MISMATCH)
                   ÷ fabricated cites total. The fraction of the Mata-class failures the
                   witness catches.
  FALSE-FIRE     = real, name-matching cites WRONGLY flagged ÷ real cites total. The
                   docs/277 falsifiable prediction is 0% by construction — a real cite
                   whose ground truth is "present + name-matches" must never be flagged.

It also reports the per-cite verdicts so a reader can audit every call, and the
collision sub-result (the `92 F.3d 1074` real-slot/fake-name catch).

    python -m benchmark.legalcite.harness            # human table
    python -m benchmark.legalcite.harness --json      # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "frozen_corpus.json"

# Import the REAL driver verdict — the whole point is to score the shipped classifier.
from dos.drivers.citation_resolve import (  # noqa: E402
    CitationEvidence,
    ResolvedCluster,
    Citation,
    classify,
)

# Verdicts that count as "flagged" (the witness refused to vouch for the cite).
_FLAGGED = {Citation.UNRESOLVED, Citation.RESOLVED_MISMATCH}


def _evidence_from_record(cite: str, rec: dict) -> CitationEvidence:
    """Build a (reachable) CitationEvidence from a frozen record — exactly the object
    `gather()` would have produced from the live read, minus the network."""
    cl = rec.get("cluster")
    clusters: tuple[ResolvedCluster, ...] = ()
    if cl:
        clusters = (ResolvedCluster(
            name=cl.get("name") or "",
            citations=tuple(cl.get("citations") or ()),
            opinion_text=cl.get("opinion_text") or "",
        ),)
    return CitationEvidence(
        cite=cite,
        claimed_name=rec.get("claimed_name") or "",
        quote=rec.get("quote") or "",
        clusters=clusters,
        reachable=True,
        detail="frozen corpus replay",
    )


def run() -> dict:
    snap = json.loads(FROZEN.read_text(encoding="utf-8"))
    real = snap.get("real", {})
    fab = snap.get("fabricated", {})

    real_rows = []
    false_fires = 0
    for cite, rec in sorted(real.items()):
        v = classify(_evidence_from_record(cite, rec))
        flagged = v.verdict in _FLAGGED
        if flagged:
            false_fires += 1
        real_rows.append({"cite": cite, "name": rec.get("claimed_name"),
                          "verdict": v.verdict.value, "flagged": flagged, "why": v.reason})

    fab_rows = []
    detected = 0
    collisions_caught = 0
    for cite, rec in sorted(fab.items()):
        v = classify(_evidence_from_record(cite, rec))
        flagged = v.verdict in _FLAGGED
        if flagged:
            detected += 1
        # A collision is a fabrication whose cite resolves to a real DIFFERENT cluster.
        is_collision = bool(rec.get("cluster"))
        if is_collision and flagged:
            collisions_caught += 1
        fab_rows.append({"cite": cite, "name": rec.get("claimed_name"),
                        "verdict": v.verdict.value, "flagged": flagged,
                        "collision": is_collision, "note": rec.get("note"), "why": v.reason})

    n_real = len(real_rows)
    n_fab = len(fab_rows)
    n_coll = sum(1 for r in fab_rows if r["collision"])
    return {
        "captured": snap.get("_meta", {}).get("captured"),
        "source": snap.get("_meta", {}).get("source"),
        "n_real": n_real,
        "n_fabricated": n_fab,
        "detected": detected,
        "false_fires": false_fires,
        "detect_recall": (detected / n_fab) if n_fab else 0.0,
        "false_fire_rate": (false_fires / n_real) if n_real else 0.0,
        "collisions_total": n_coll,
        "collisions_caught": collisions_caught,
        "real_rows": real_rows,
        "fabricated_rows": fab_rows,
    }


def _fmt(r: dict) -> str:
    out: list[str] = []
    out.append("=" * 78)
    out.append("legalcite — DOS catches fabricated/mis-quoted legal citations (docs/279)")
    out.append(f"  corpus: {r['source']} (captured {r['captured']}, FROZEN replay, $0)")
    out.append("=" * 78)
    out.append("")
    out.append(f"  REAL cites (must NOT flag):    {r['n_real']}")
    out.append(f"  FABRICATED cites (must flag):  {r['n_fabricated']}  "
               f"(of which {r['collisions_total']} are real-slot/fake-name collisions)")
    out.append("")
    out.append(f"  DETECT recall    = {r['detected']}/{r['n_fabricated']} = "
               f"{r['detect_recall']*100:.1f}%  (fabrications flagged)")
    out.append(f"  FALSE-FIRE rate  = {r['false_fires']}/{r['n_real']} = "
               f"{r['false_fire_rate']*100:.1f}%  (real cites wrongly flagged)")
    out.append(f"  collision catch  = {r['collisions_caught']}/{r['collisions_total']}  "
               f"(fabricated name on a real reporter slot)")
    out.append("")
    out.append("  --- real cites (the false-fire floor) ---")
    for row in r["real_rows"]:
        mark = "  FLAG!" if row["flagged"] else "  ok  "
        out.append(f"  {mark} {row['cite']:16s} {row['verdict']:18s} {row['name']}")
    out.append("")
    out.append("  --- fabricated cites (the detect set) ---")
    for row in r["fabricated_rows"]:
        mark = "caught" if row["flagged"] else " MISS!"
        tag = " [collision]" if row["collision"] else ""
        out.append(f"  {mark} {row['cite']:16s} {row['verdict']:18s} {row['name']}{tag}")
    out.append("")
    if r["false_fire_rate"] == 0.0:
        out.append("  ✓ FALSE-FIRE FLOOR HELD (0%) — the docs/277 §6 falsifiable prediction.")
    else:
        out.append("  ✗ FALSE-FIRE FLOOR BREACHED — a real cite was flagged; report honestly.")
    out.append("=" * 78)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark.legalcite.harness",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    args = ap.parse_args(argv)
    if not FROZEN.exists():
        print(f"frozen corpus missing: {FROZEN}\nrun: python benchmark/legalcite/snapshot.py",
              file=sys.stderr)
        return 2
    r = run()
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print(_fmt(r))
    # Exit non-zero if the false-fire floor is breached (a noisy resolver is worse than
    # none — the docs/277 cheap-kill, made the harness's own gate).
    return 0 if r["false_fire_rate"] == 0.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
