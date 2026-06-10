#!/usr/bin/env python3
"""probe_verify_rungs — EMPIRICAL SCOPING for native `stop` (docs/125 §8.2).

The handoff's paused step: before porting all 6 grep rungs into Go, COUNT which
rungs actually fire on THIS repo's real git history. A subtly-wrong verify blocks
a legitimate stop (a turn-killing regression), so we port the rungs that matter
first and corpus-gate the rest as ABSTAIN-to-Python.

Method:
  1. Harvest realistic (plan, phase) pairs from this repo's git log subjects:
       - `docs/<series>: <PHASE> ...` direct ships (the dominant shape here)
       - the `docs/NN_*.md` plan-doc basenames as plans
       - real recent commit subjects, tokenized for phase-shaped ids
  2. Run the LIVE `oracle.is_shipped(plan, phase, cfg=cfg)` over each, plus a
     batch of KNOWN-shipped phases from CLAUDE.md (docs/82 liveness, etc.).
  3. Tally the `source` (registry/grep/none) and the grep `via` rung
     (direct/release-prefix/hyg-slug/sub-phase-parent/body-mention/file-path).

Read-only. Prints a tally + a sample of each rung's hits.
"""
from __future__ import annotations

import collections
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # parity/->hook->internal->go->repo root
sys.path.insert(0, str(REPO / "src"))

from dos import config as _config  # noqa: E402
from dos import oracle, phase_shipped  # noqa: E402


def git(args: list[str]) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def harvest_pairs() -> list[tuple[str, str, str]]:
    """Return (plan, phase, note) candidates from real git history."""
    pairs: list[tuple[str, str, str]] = []
    # Curated KNOWN ships from CLAUDE.md + recent log, to exercise the grep rung.
    curated = [
        ("docs/82_liveness-oracle-plan", "liveness", "CLAUDE.md example: SHIPPED via grep"),
        ("docs/99_runtime-validation-and-the-actuation-boundary", "halt", "CLAUDE.md: NOT_SHIPPED via none"),
        ("docs/125_go-hook-fastpath-build-plan", "GHF1", "this plan, GHF1 shipped"),
        ("docs/125_go-hook-fastpath-build-plan", "GHF2", "this plan, GHF2 shipped"),
        ("docs/125_go-hook-fastpath-build-plan", "GHF3", "this plan, GHF3 shipped"),
        ("docs/125_go-hook-fastpath-build-plan", "GHF4", "groundwork only"),
        ("docs/125_go-hook-fastpath-build-plan", "GHF5", "not shipped"),
        ("docs/259_wait-marker-budget-runtime-lever", "marker_sensor", "recent commit"),
    ]
    pairs.extend(curated)

    # Harvest from log subjects of the form `docs/<series>: <PHASE> ...`.
    import re
    subj_re = re.compile(r"^[a-f0-9]+\s+(?:docs|go)/([A-Za-z0-9_\-]+):?\s+([A-Za-z0-9_.\-§]+)")
    for line in git(["log", "--oneline", "-n", "1500"]):
        m = subj_re.match(line)
        if not m:
            continue
        series, tok = m.group(1), m.group(2)
        tok = tok.strip("§").strip(".")
        # phase token must have a letter+digit, the shape this repo uses
        if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok):
            pairs.append((f"docs/{series}", tok, f"harvested: {line[:70]}"))
    # de-dup
    seen = set()
    uniq = []
    for p, ph, note in pairs:
        k = (p, ph)
        if k in seen:
            continue
        seen.add(k)
        uniq.append((p, ph, note))
    return uniq


def main() -> int:
    cfg = _config.load_workspace_config(str(REPO))
    _config.set_active(cfg)
    pairs = harvest_pairs()
    print(f"# probing {len(pairs)} (plan, phase) pairs against live oracle\n")

    src_tally = collections.Counter()
    via_tally = collections.Counter()
    shipped_count = 0
    samples: dict[str, list[str]] = collections.defaultdict(list)

    for plan, phase, note in pairs:
        verdict = oracle.is_shipped(plan, phase, cfg=cfg)
        src_tally[verdict.source] += 1
        rung = "-"
        if verdict.shipped:
            shipped_count += 1
            # Re-derive the grep `via` rung by calling the grep fallback directly.
            res = phase_shipped.check_phase_shipped(plan, phase)
            rung = res.get("via") or verdict.source
            via_tally[rung] += 1
            if len(samples[rung]) < 3:
                samples[rung].append(f"{plan} {phase} -> {verdict.sha[:9]} ({note[:50]})")
        else:
            if len(samples["NOT_SHIPPED"]) < 5:
                samples["NOT_SHIPPED"].append(f"{plan} {phase} [{verdict.source}] ({note[:40]})")

    print(f"## verdicts: {shipped_count} SHIPPED / {len(pairs) - shipped_count} not")
    print("\n## source tally (which gate answered):")
    for k, v in src_tally.most_common():
        print(f"  {k:12} {v}")
    print("\n## grep `via` rung tally (which grep rung fired on a SHIP):")
    for k, v in via_tally.most_common():
        print(f"  {k:18} {v}")
    print("\n## samples per rung:")
    for rung, ex in samples.items():
        print(f"  [{rung}]")
        for e in ex:
            print(f"     {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
