"""Dogfood guard: this repo wires its OWN goal-gate (issue #18).

The substrate whose thesis is "don't believe the agent's self-report" must not
believe its own agents' self-reported goal completion. Issue #18's done-condition
has two checkable halves; this guard pins both against regression:

  A. The wiring is committed — this repo's tracked `.claude/settings.json` runs
     `dos hook stop` on the Stop event (the goal-gate, repo-intrinsic and
     independent of whether the dos-kernel plugin happens to be installed).
  B. The gate actually bites — a confident ship-claim for a phase git does NOT
     back is refused (the false-done the gate exists to catch), via the same
     claim-extract → oracle path the live Stop hook records to the observation
     log (the `dos-stats` fold's "stop blocks" row).

Neither half re-implements the kernel: half A asks the kernel's own
`hook_install.wired_events_json` detector (what `dos doctor --json`'s
`runtime_hooks` reports); half B drives `claim_extract` + `oracle` directly.
"""

from __future__ import annotations

import json
from pathlib import Path

from dos import claim_extract, hook_install, oracle
from dos import config as _config

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"


def test_repo_settings_wire_the_stop_goal_gate():
    """Half A: the tracked .claude/settings.json runs `dos hook stop` on Stop.

    Asked via the kernel's own detector — the same one `dos doctor --json`
    reports under runtime_hooks.claude-code — so this guard tracks the surface
    an operator reads, not a hand-rolled re-parse.
    """
    assert _SETTINGS.is_file(), f"{_SETTINGS} must exist (the committed wiring)"
    existing = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    spec = hook_install.host_spec("claude-code")
    wired = hook_install.wired_events_json(existing, spec)
    assert "Stop" in wired, (
        "this repo's .claude/settings.json must wire `dos hook stop` on the Stop "
        "event so its own sessions cannot self-certify a false 'done' (issue #18). "
        f"runtime_hooks/claude-code currently wires: {wired}"
    )


def test_goal_gate_refuses_an_unshipped_confident_claim():
    """Half B: a confident DOS-CLAIM for a phase git does not back is NOT shipped.

    This is the verdict the Stop hook turns into a {"decision":"block",…} — a
    false-done refusal. We assert the load-bearing rung (the claim is confident
    AND the oracle says source="none"), not the host envelope.
    """
    # A confident marker-rung claim, on its own line as the marker grammar requires.
    text = (
        "The dogfood goal-gate phase is complete.\n"
        "DOS-CLAIM: DOGFOOD-GOAL-GATE NONEXISTENT-PHASE-Z9\n"
        "Stopping now."
    )
    claims = claim_extract.extract_claims(text, allow_heuristic=False)
    assert claims, "the byte-exact DOS-CLAIM marker must extract as a confident claim"
    claim = claims[0]
    assert claim.confident, "a marker-rung claim is confident → actionable at Stop"

    cfg = _config.default_config(workspace=str(_REPO_ROOT))
    verdict = oracle.is_shipped(claim.plan, claim.phase, cfg=cfg)
    assert not verdict.shipped, "a fabricated phase must verify as NOT shipped"
    assert verdict.source == "none", (
        "git has no commit backing the claim → source='none' → the Stop hook "
        f"blocks the false done; got source={verdict.source!r}"
    )
