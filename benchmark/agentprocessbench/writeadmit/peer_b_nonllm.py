"""The NON-LLM peer-B arm (docs/236 §5 H3, the keystone) — PURE, $0, no model, no network.

WHAT THIS MEASURES, AND WHY IT IS DECISIVE
------------------------------------------
docs/235 ran the peer-B handoff against a capable LLM B and measured ΔB≈0 — and docs/236
explains why: an LLM B *re-verifies* the inherited phantom and self-recovers (3/5), so the
measurement was the LLM's own recovery rate, not the handoff. Recovery was a CONFOUND.

This probe removes the confound by removing the recovery channel. The non-LLM B
(`peer_b.decide_nonllm`) is a fixed downstream pipeline that acts on its input VERBATIM:
told "done", it proceeds; told "not done / re-verify", it redoes. It is arm-blind (a
function of the handoff TEXT, never of which arm produced it), so a believe→proceed /
adjudicate→redo split is caused by the gate's correction, not assigned here.

    ΔB(non-LLM) = success(B | adjudicate) − success(B | believe)   on the over-claim slice

On an over-claim the gold state requires the write to land (it did not, under A): a proceeding
B inherits the phantom (FAIL), a redoing B reaches gold (SUCCESS). So ΔB(non-LLM) equals the
DEFLECTION RATE — the fraction of over-claims where believe sends a non-re-verifying consumer
down the wrong path and adjudicate prevents it.

THE KEYSTONE READ (docs/236)
----------------------------
    laundering gap = ΔB(non-LLM) − ΔB(LLM, docs/235)

If ΔB(non-LLM) is materially > 0 while ΔB(LLM)≈0, the gap IS the recovery-laundering
coefficient: the LLM B's self-recovery was hiding a real out-of-loop payoff that lands intact
at a consumer that cannot self-heal. That is the §6 cheapest decisive experiment, and it runs
at $0 over the already-cached A-rows (no GEMINI_API_KEY needed).

USAGE
-----
    python -m benchmark.agentprocessbench.writeadmit.peer_b_nonllm \
        live_results_m1_flash25 live_results_m2_pro25 [--json]

Each positional is a `run_writeadmit` out_dir of cached A-row JSON (the same rows
`AHandoff.from_row` consumes). Read-only; prints a table (or JSON) and exits.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from peer_b import (  # noqa: E402  (path-injected sibling; the module is pure/$0)
    AHandoff, BELIEVE, ADJUDICATE,
    nonllm_outcome, nonllm_deflected, blast_radius_curve,
)


def _load_rows(a_dir: str) -> list[dict]:
    """Load every cached A-row JSON from one out_dir (skips unreadable / error rows)."""
    out: list[dict] = []
    for f in sorted(glob.glob(os.path.join(a_dir, "*.json"))):
        try:
            row = json.loads(open(f, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict) and not row.get("error"):
            out.append(row)
    return out


@dataclass
class NonLlmResult:
    a_dirs: list[str]
    n_rows: int
    n_overclaim: int
    n_blocked_overclaim: int       # over-claims the gate actually BLOCKED (adjudicate differs)
    believe_fail: int              # over-claims where believe-B proceeds on the phantom (fails)
    adjudicate_success: int        # over-claims where adjudicate-B is told to redo (succeeds)
    deflected: int                 # believe FAIL and adjudicate SUCCESS — the directional flip
    delta_b_nonllm: float          # deflected / n_overclaim  (= adj_success_rate − bel_success_rate)
    blast_curve: list[float]

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def measure(a_dirs: list[str]) -> NonLlmResult:
    rows: list[dict] = []
    for d in a_dirs:
        rows.extend(_load_rows(d))
    handoffs = [AHandoff.from_row(r) for r in rows]
    overclaims = [a for a in handoffs if a.is_overclaim]

    bel_fail = sum(1 for a in overclaims if nonllm_outcome(a, BELIEVE) is False)
    adj_ok = sum(1 for a in overclaims if nonllm_outcome(a, ADJUDICATE) is True)
    blocked = sum(1 for a in overclaims if not a.admit)
    deflected = sum(1 for a in overclaims if nonllm_deflected(a))
    n_oc = len(overclaims)
    delta = (deflected / n_oc) if n_oc else 0.0
    return NonLlmResult(
        a_dirs=a_dirs,
        n_rows=len(handoffs),
        n_overclaim=n_oc,
        n_blocked_overclaim=blocked,
        believe_fail=bel_fail,
        adjudicate_success=adj_ok,
        deflected=deflected,
        delta_b_nonllm=round(delta, 4),
        blast_curve=blast_radius_curve(delta),
    )


def _render(res: NonLlmResult, llm_delta_b: Optional[float]) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("NON-LLM peer-B (docs/236 sec.5 H3) -- recovery removed, $0")
    lines.append("=" * 72)
    lines.append(f"  A-dirs                 {', '.join(os.path.basename(d) for d in res.a_dirs)}")
    lines.append(f"  rows folded            {res.n_rows}")
    lines.append(f"  over-claim slice       {res.n_overclaim}   (confident write x witness-refuted)")
    lines.append(f"    gate BLOCKED         {res.n_blocked_overclaim}   (adjudicate carries the correction)")
    lines.append(f"  believe-B FAIL         {res.believe_fail}   (proceeds on the phantom)")
    lines.append(f"  adjudicate-B SUCCESS   {res.adjudicate_success}   (told to redo -> reaches gold)")
    lines.append(f"  DEFLECTED (flip)       {res.deflected}   (believe fail -> adjudicate success)")
    lines.append("-" * 72)
    lines.append(f"  dB (non-LLM)           {res.delta_b_nonllm:+.4f}   ({res.deflected}/{res.n_overclaim})")
    if llm_delta_b is not None:
        gap = res.delta_b_nonllm - llm_delta_b
        lines.append(f"  dB (LLM, docs/235)     {llm_delta_b:+.4f}")
        lines.append(f"  LAUNDERING GAP         {gap:+.4f}   (non-LLM - LLM = recovery-laundering coefficient)")
    lines.append("-" * 72)
    hops = " ".join(f"h{i+1}={v}" for i, v in enumerate(res.blast_curve))
    lines.append(f"  blast radius (chain)   {hops}")
    lines.append("    expected deflected-hops if N non-re-verifying consumers chain (docs/236 sec.7)")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Non-LLM peer-B arm (docs/236 §5 H3) — $0.")
    ap.add_argument("a_dirs", nargs="+", help="run_writeadmit out_dir(s) of cached A-row JSON")
    ap.add_argument("--llm-delta-b", type=float, default=None,
                    help="the measured LLM ΔB (docs/235) to compute the laundering gap")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the table")
    args = ap.parse_args(argv)

    res = measure(args.a_dirs)
    if args.json:
        out = res.as_dict()
        out["llm_delta_b"] = args.llm_delta_b
        if args.llm_delta_b is not None:
            out["laundering_gap"] = round(res.delta_b_nonllm - args.llm_delta_b, 4)
        print(json.dumps(out, indent=2))
    else:
        print(_render(res, args.llm_delta_b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
