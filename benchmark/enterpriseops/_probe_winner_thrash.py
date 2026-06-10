"""_probe_winner_thrash — SAFETY check for the give-up-correctly K-gate (scratch, $0).

The load-bearing safety claim for early-halt is "it never halts a WINNING run". docs/198/194
scored false-abandon=0.000 on the NONE arm only. This probe asks the honest cross-arm question:
among SUCCESSFUL runs, does any reach K errors of a single tool (which a K-gate would halt)?

Result (2026-06-06, full 240/arm corpus):
  none           : 0/22 winners reach K=2 -> K=2 gate provably safe here.
  rewind_natural : 1/23 winners reach K=2 (recovers + succeeds) -> FA = 1/23 = 4.3% at K=2.
  BOTH arms      : 0 winners reach K=3 -> K=3 is the cross-arm provably-safe threshold.
The honest false-abandon is 0-4.3% at K=2 (arm-dependent), 0 at K>=3 -- not the flat 0.000 docs/198 stated.
"""
import glob, json, sys
from collections import defaultdict, Counter
sys.path.insert(0, ".")
from dos_react import _is_struct_error, _result_text, _is_blocked_result


def _is_err(tr):
    return _is_struct_error(_result_text(tr)) and not _is_blocked_result(tr)


def _runs(g):
    for f in sorted(glob.glob(g)):
        try:
            r = (json.load(open(f, encoding="utf-8")).get("runs") or [{}])[0]
        except Exception:
            continue
        yield f, r


def main():
    for arm in ["none", "rewind_natural"]:
        g = f"live_results_natural_ab/{arm}/results_*.json"
        succ_maxerr = []
        for _f, r in _runs(g):
            cnt = defaultdict(int)
            for tr in (r.get("tool_results") or []):
                if _is_err(tr):
                    cnt[str(tr.get("tool_name", ""))] += 1
            if r.get("overall_success"):
                succ_maxerr.append(max(cnt.values()) if cnt else 0)
        n = len(succ_maxerr)
        print(f"[{arm}] winners={n}  max-tool-err histogram: {dict(sorted(Counter(succ_maxerr).items()))}")
        for k in (2, 3, 4):
            fa = sum(1 for m in succ_maxerr if m >= k)
            print(f"   K={k}: winners reaching K errors (FALSE-ABANDON) = {fa}/{n} = {fa/n:.3f}" if n else "")


if __name__ == "__main__":
    main()
