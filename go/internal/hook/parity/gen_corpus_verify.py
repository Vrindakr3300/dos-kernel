#!/usr/bin/env python3
"""Generate the native-VERIFY differential parity corpus (docs/125 native stop).

Each line is a self-contained, HERMETIC verify case:

    {
      "name": "...",                  # human label
      "plan": "...", "phase": "...",  # the (plan, phase) queried
      "oneline": ["<sha> <subject>", ...],  # the EXACT git-log window the rung scans
      "py_shipped": bool,             # Python oracle's verdict on this evidence
      "py_sha": "...",                # the resolved short-sha (or "")
      "py_via": "...",                # the grep rung that fired (direct/.../"" )
      "py_source": "grep-subject|grep-artifact|grep|none"  # the graded source
    }

The oracle side is the PURE `phase_shipped._check_phase_with_cache` over the captured
oneline window (NOT a live git read), so the Go `verifyDirect` replay sees byte-
identical evidence — the same discipline as the pretool corpus's injected leases.

`py_source` is graded the way `oracle._grade_grep_source(via)` does, so the Go test
can assert the full (shipped, sha, via, source) projection, not just shipped.

The corpus mixes:
  * REAL ships from this repo's history (direct rung → grep-subject)
  * REAL not-shipped pairs (fabricated phases → none)
  * BOOKKEEPING subjects (snapshot / archive <run-id>) that NAME a phase but must
    not ship it (the universal-guard exclusion)
  * RELEASE-prefix subjects (vX.Y.Z: … <PHASE>) — the rung the native port ABSTAINS
    on; the Go side must return supported=false here (and the gate asserts it)
  * BOUNDARY cases (SF1.2 vs SF1.2-port) that exercise _BOUNDARY_NEG

Run: python gen_corpus_verify.py > corpus_verify.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # parity/->hook->internal->go->repo root
sys.path.insert(0, str(REPO / "src"))

from dos import config as _config  # noqa: E402
from dos import oracle, phase_shipped  # noqa: E402


def _oneline_window(cfg) -> list[str]:
    """The real git-log oneline window this repo's rung would scan, captured ONCE."""
    _config.set_active(cfg)
    return phase_shipped._git_log(["--oneline", f"-{phase_shipped._ONELINE_WINDOW}"])


def verdict_over(plan: str, phase: str, oneline: list[str], cfg) -> dict:
    """Python's PURE grep verdict over the captured oneline window.

    Uses `_check_phase_with_cache` (the exact pure core check_phase_shipped calls,
    minus the live git read + plan-body/file-path backstops which are inert on the
    no-plan stop path). Then grades the source the way oracle.is_shipped does, so the
    corpus carries the same (shipped, sha, via, source) the live syscall reports.
    """
    matchers = phase_shipped._subject_matchers(cfg)
    res = phase_shipped._check_phase_with_cache(plan, phase, oneline, [], matchers)
    via = res.get("via", "") or ""
    shipped = bool(res.get("shipped"))
    source = oracle._grade_grep_source(via) if shipped else "none"
    return {
        "py_shipped": shipped,
        "py_sha": (res.get("sha") or ""),
        "py_via": via,
        "py_source": source,
    }


def case(name: str, plan: str, phase: str, oneline: list[str], cfg) -> dict:
    v = verdict_over(plan, phase, oneline, cfg)
    return {"name": name, "plan": plan, "phase": phase, "oneline": oneline, **v}


def build_cases(cfg) -> list[dict]:
    full = _oneline_window(cfg)
    cases: list[dict] = []

    # --- REAL ships from this repo (direct rung). These are the cases that prove the
    #     native direct rung resolves a real ship byte-identically. Use the FULL window
    #     so the ship is actually present.
    real_ships = [
        ("real-liveness", "docs/82_liveness-oracle-plan", "liveness"),
        ("real-ghf2", "docs/125_go-hook-fastpath-build-plan", "GHF2"),
        ("real-f4", "docs/256", "F4"),
        ("real-marker-sensor", "docs/259", "marker_sensor"),
    ]
    for nm, p, ph in real_ships:
        cases.append(case(nm, p, ph, full, cfg))

    # --- REAL not-shipped (fabricated phase that no commit names) → none.
    cases.append(case("unshipped-fabricated", "docs/99_x", "halt", full, cfg))
    cases.append(case("unshipped-ghf5", "docs/125_go-hook-fastpath-build-plan", "GHF5", full, cfg))

    # --- Hermetic SYNTHETIC windows: a tiny injected log isolates ONE rung so the gate
    #     pins the decision shape independent of whatever real history happens to hold.
    # Direct ship, glued generic form `<SERIES><PHASE>:`.
    cases.append(case("synth-glued-direct", "AUTH", "AUTH2",
                      ["abc1234 AUTH2: ship token refresh", "def5678 chore: tidy"], cfg))
    # Direct ship, spaced `<SERIES>:?\s+<PHASE>` form with an optional dir prefix.
    cases.append(case("synth-spaced-direct", "docs/77", "P3",
                      ["aaa1111 docs/77: P3 wire the gate", "bbb2222 misc"], cfg))
    # Boundary: query `SF1.2` must NOT match `SF1.2-port`.
    cases.append(case("synth-boundary-nomatch", "docs/x", "SF1.2",
                      ["ccc3333 docs/x: SF1.2-port follow-up work"], cfg))
    # Boundary: query `SF1.2` DOES match the exact `SF1.2`.
    cases.append(case("synth-boundary-match", "docs/x", "SF1.2",
                      ["ddd4444 docs/x: SF1.2 the real ship"], cfg))
    # Bookkeeping: a snapshot subject NAMES the phase but must not ship it.
    cases.append(case("synth-bookkeeping-snapshot", "AUTH", "AUTH2",
                      ["eee5555 working-dir snapshot: AUTH2 in flight"], cfg))
    # Bookkeeping: an archive <run-id> rollup quotes the phase, must not ship.
    cases.append(case("synth-bookkeeping-archive", "FB", "FB2",
                      ["fff6666 docs/fanout: archive 20260530T093407Z chain (FB2 halted)"], cfg))
    # Release-prefix ONLY (no direct ship): the rung the native port ABSTAINS on.
    cases.append(case("synth-release-prefix-only", "EC", "EC17",
                      ["1112223 v0.268.0: EC17 escalation + RS4 archetype"], cfg))
    # A clean miss in a tiny window → none.
    cases.append(case("synth-clean-miss", "ZZ", "ZZ9",
                      ["7778889 docs/aa: BB3 unrelated", "0001112 chore: nothing"], cfg))

    return cases


def main() -> int:
    cfg = _config.load_workspace_config(str(REPO))
    lines = [json.dumps(c, sort_keys=True) for c in build_cases(cfg)]
    payload = "\n".join(lines) + "\n"
    # Write UTF-8 WITHOUT a BOM. A `python … > file.jsonl` redirect under PowerShell
    # writes UTF-16-with-BOM, which the Go JSON parser chokes on (the bytes 0xFF 0xFE
    # lead). Writing the file directly with an explicit utf-8 encoding (newline="" so
    # we control the line terminator) is encoding-robust regardless of the shell. An
    # explicit `--out` arg (or the default sibling path) is the target.
    out = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).resolve().parent / "corpus_verify.jsonl")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    sys.stderr.write(f"wrote {len(lines)} cases -> {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
