#!/usr/bin/env python3
"""claims_lint — an advisory calibration check for DOS prose.

DOS's thesis applied to its own documentation: the kernel distrusts an agent's
*narration* about code and checks the artifact; this lint distrusts the docs'
*narration* about results and flags the spans most likely to overclaim.

It is **advisory**, not a gate — a PDP, not a PEP, the same posture as the kernel
itself. It reports candidate spans for a human to weigh; it does not fail CI and it
does not edit anything. Most hits are judgement calls, and some are legitimate
(a real correctness invariant honestly says a kernel "never double-books").

It flags two narrow, high-signal classes that are *almost never* load-bearing:

  1. MARKETING superlatives — "revolutionary", "game-changing", "paradigm shift",
     "crushes", "dominates", "nobody else", "the only X that" — heat, not signal.
  2. UNHEDGED proof words on EMPIRICAL claims — "proven", "definitively",
     "conclusively", "a smoking gun" — when a single corpus / one run / a simulated
     denominator is the evidence. (We flag the word; a human checks the evidence.)

It deliberately does NOT flag the kernel's protected vocabulary — the typed
verdicts (SHIPPED/SPINNING/REFUSE/ABSTAIN…), honest self-critical verdicts about
DOS's own bets (KILLED/REFUTED/"net loss"), or mechanism invariants stated as
such. Softening those would make the docs less honest, which is the wrong
direction. See CONTRIBUTING.md "Claims discipline" for the rubric this encodes.

Usage:
    python scripts/claims_lint.py [PATH ...]      # default: docs/ + the root *.md
    python scripts/claims_lint.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --- the three flagged classes ----------------------------------------------
# The patterns are deliberately NARROW: only spans that are almost never
# load-bearing in this corpus. Polysemous technical words ("dominates" as in
# "cold-start dominates CI", "disruption-cost ordering") are intentionally NOT
# matched — a noisy lint gets ignored, which is worse than a quiet one.

# Marketing superlatives: hype that adds heat, not signal.
MARKETING = re.compile(
    r"\b(revolutionary|game[- ]chang\w*|paradigm[- ]shift\w*|"
    r"blow\w*\s+(?:the\s+\w+\s+)?away|nobody\s+else\s+(?:can|does|has|is)|"
    r"snake[- ]oil|silver[- ]bullet|world[- ]class|best[- ]in[- ]class|"
    r"unbeatable|unstoppable|magic(?:al)?\s+(?:bullet|sauce))\b",
    re.IGNORECASE,
)

# Unhedged proof words — flag for a human to check the evidence behind them.
# (The word is the flag; whether it overclaims depends on the evidence, which a
# human weighs. "Measured / observed / on this corpus" is the calibrated form.)
PROOF = re.compile(
    r"\b(definitively|conclusively|categorically|beyond\s+(?:any\s+)?doubt|"
    r"irrefutabl\w*|incontrovertibl\w*|smoking\s+gun|"
    r"the\s+strongest\s+(?:measured\s+)?signal\s+in\s+the\s+field)\b",
    re.IGNORECASE,
)

# Contemptuous framing of other work / the field — keep the critique, drop the
# sneer. ("the disease" is a recurring metaphor for the blackboard/A2A failure
# mode — borderline; flagged so a human decides whether it reads as contempt.)
CONTEMPT = re.compile(
    r"\b(?:cargo[- ]cult\w*|just\s+slop|is\s+(?:just\s+)?slop\b|pure\s+slop|"
    r"mere\s+theater|security\s+theater|hand[- ]wav(?:e|es|ing|y))\b",
    re.IGNORECASE,
)

CLASSES = [("marketing", MARKETING), ("proof", PROOF), ("contempt", CONTEMPT)]

# Lines we never flag: fenced code, and the lint's own pattern definitions.
FENCE = re.compile(r"^\s*```")


def scan_file(path: Path) -> list[dict]:
    hits: list[dict] = []
    in_fence = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hits
    for n, line in enumerate(lines, 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for cls, pat in CLASSES:
            for m in pat.finditer(line):
                hits.append(
                    {
                        "file": str(path),
                        "line": n,
                        "class": cls,
                        "match": m.group(0),
                        "context": line.strip()[:160],
                    }
                )
    return hits


def gather(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            out.extend(sorted(pp.rglob("*.md")))
        elif pp.suffix == ".md":
            out.append(pp)
    return out


def main(argv: list[str] | None = None) -> int:
    # Be robust on a legacy-codepage console (Windows cp1252) — never crash on a
    # stray non-ASCII char in a doc line we're quoting back.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Advisory calibration check for DOS prose.")
    ap.add_argument("paths", nargs="*", help="files or dirs (default: docs/ + root *.md)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    if args.paths:
        targets = args.paths
    else:
        targets = ["docs"] + [str(p) for p in Path(".").glob("*.md")]

    files = gather(targets)
    hits: list[dict] = []
    for f in files:
        # Don't lint our own pattern source.
        if f.name == "claims_lint.py":
            continue
        hits.extend(scan_file(f))

    if args.json:
        print(json.dumps({"scanned": len(files), "hits": hits}, indent=2))
        return 0

    if not hits:
        print(f"claims_lint: {len(files)} files scanned, no candidate overclaims flagged.")
        return 0

    by_class: dict[str, int] = {}
    for h in hits:
        by_class[h["class"]] = by_class.get(h["class"], 0) + 1
    print(f"claims_lint: {len(files)} files scanned, {len(hits)} candidate span(s) for review")
    print("  (advisory -- each is a judgement call; see CONTRIBUTING.md 'Claims discipline')")
    print("  by class: " + ", ".join(f"{k}={v}" for k, v in sorted(by_class.items())))
    print()
    for h in hits:
        print(f"  {h['file']}:{h['line']}  [{h['class']}]  >> {h['match']} <<")
        print(f"      {h['context']}")
    # Advisory: exit 0 always. This is a PDP, not a PEP.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
