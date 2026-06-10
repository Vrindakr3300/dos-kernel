"""SKP Phase 3 — the lease-aware skills (`dos-dispatch`, `dos-dispatch-loop`).

`dos-dispatch` adds concurrency: a lane lease via `dos arbitrate` so parallel
dispatches on disjoint lanes don't collide, and `dos gate` driving the empty
case. `dos-dispatch-loop` adds the typed loop decision (`loop_decide.decide`)
driving continue/replan/stop. This test drives the kernel surfaces those
screenplays call:

  1. **`test_dos_dispatch_takes_lane`** — two dispatch runs on disjoint
     WCR-declared lanes both ADMIT; overlapping trees COLLIDE — through
     `dos arbitrate`, proving the admission decision is the kernel's.
  2. **`test_dos_loop_stops_on_drain_twice`** — the loop's scripted decision
     calls `loop_decide.decide` and halts with DRAINED_TWICE after a DRAIN
     following a productive `/replan` that followed a DRAIN.

Plus the design-law grep guard: the shipped skills name no host literal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import dos


SKILL_DIR = Path(dos.__file__).parent / "skills"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _write_toml(repo: Path, body: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "dos.toml").write_text(body, encoding="utf-8")


def _cli(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    # Pin the subprocess to the imported `dos` source tree (see
    # test_skill_pack_generic._cli) so a sibling editable install can't shadow it.
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(dos.__file__).parents[1])}
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


_FOREIGN_LANES = """\
[lanes]
concurrent = ["api", "worker", "web"]
exclusive  = ["infra"]
autopick   = ["api", "worker"]
[lanes.trees]
api    = ["src/api/**"]
worker = ["src/worker/**"]
web    = ["web/**"]
infra  = ["deploy/**"]
"""


# ===========================================================================
# (1) dos-dispatch takes a lane through dos arbitrate
# ===========================================================================


def test_dos_dispatch_takes_lane(tmp_path: Path):
    """Two dispatches on disjoint lanes both ADMIT; overlapping trees COLLIDE —
    the lease decision a `dos-dispatch` Step 1 reads from `dos arbitrate`."""
    _write_toml(tmp_path, _FOREIGN_LANES)

    # api dispatch admits while worker holds a disjoint lease (Step 1 acquire).
    admit = _cli(
        tmp_path, "arbitrate", "--lane", "api", "--kind", "cluster",
        "--leases", json.dumps([{"lane": "worker", "tree": ["src/worker/**"]}]),
    )
    assert admit.returncode == 0, admit.stderr
    d = json.loads(admit.stdout)
    assert d["outcome"] == "acquire"
    assert d["tree"] == ["src/api/**"]  # the declared lane tree, read back (WCR)

    # a second dispatch whose tree OVERLAPS a live lease is REFUSED (collision) —
    # the keyword path exercises the tree-disjointness algebra.
    collide = _cli(
        tmp_path, "arbitrate", "--lane", "api", "--kind", "keyword",
        "--tree", "src/api/**",
        "--leases", json.dumps([{"lane": "web", "tree": ["src/api/handlers.py"]}]),
    )
    assert collide.returncode == 1, collide.stdout
    assert json.loads(collide.stdout)["outcome"] == "refuse"


# ===========================================================================
# (2) dos-dispatch-loop stops on drained-twice via loop_decide.decide
# ===========================================================================


def test_dos_loop_stops_on_drain_twice(tmp_path: Path):
    """The loop's scripted decision composes `loop_decide.decide`: a DRAIN, then a
    productive /replan, then a DRAIN halts with DRAINED_TWICE — the kernel
    decides, not the screenplay (Phase 3 litmus)."""
    from dos.loop_decide import (
        LoopState, IterationOutcome, OutcomeKind, StopReason, decide,
    )
    from dos.gate_classify import Verdict
    from dos.tokens import GateVerdict

    state = LoopState(iteration=1, gate_mode="hard")

    # iter 1 — a GATE DRAIN: under hard this routes to /replan, arms nothing yet.
    d1 = decide(state, IterationOutcome(kind=OutcomeKind.GATE,
                                        verdict=GateVerdict.DRAIN))
    assert d1.action == "continue" and d1.next_mode == "replan"

    # iter 2 — a PRODUCTIVE /replan: arms the drained-twice trigger.
    from dos.gate_classify import ReplanProductivity
    d2 = decide(d1.next_state,
                IterationOutcome(kind=OutcomeKind.REPLAN_DONE,
                                 replan_productivity=ReplanProductivity.PRODUCTIVE))
    assert d2.action == "continue" and d2.next_mode == "dispatch"

    # iter 3 — a GATE DRAIN again: /replan tried and could not refill → STOP.
    d3 = decide(d2.next_state, IterationOutcome(kind=OutcomeKind.GATE,
                                                verdict=GateVerdict.DRAIN))
    assert d3.action == "stop"
    assert d3.stop_reason is StopReason.DRAINED_TWICE


def test_dos_loop_stale_stamp_never_drained_twice(tmp_path: Path):
    """A STALE-STAMP gate routes to /replan but NEVER arms a false drained-twice
    stop — the structural #240 fix the loop skill must preserve."""
    from dos.loop_decide import LoopState, IterationOutcome, OutcomeKind, decide
    from dos.tokens import GateVerdict

    state = LoopState(iteration=2, last_replan_drained=True, gate_mode="hard")
    # Even with last_replan_drained armed, a STALE-STAMP must not stop.
    d = decide(state, IterationOutcome(kind=OutcomeKind.GATE,
                                       verdict=GateVerdict.STALE_STAMP))
    assert d.action == "continue", d
    assert d.next_mode == "replan"


# ===========================================================================
# (3) the shipped dispatch skills name no host literal
# ===========================================================================


def test_dispatch_skills_ship_and_name_no_host_literal():
    for name in ("dos-dispatch", "dos-dispatch-loop"):
        skill = SKILL_DIR / name / "SKILL.md"
        assert skill.exists(), f"missing {skill}"
        text = skill.read_text(encoding="utf-8")
        for token in ("docs/_plans", "output/next-up", "docs/dispatch:",
                      "docs/_dispatch_loops", "docs/_chained_runs"):
            assert token not in text, f"{name} must not name {token!r}"
        for lane in ("apply", "tailor", "discovery"):
            assert lane not in text, f"{name} must not name job lane {lane!r}"
