"""Tests for `dos.reconcile` — the quiet-completion gate (docs/168 §3, docs/207 Phase 4).

Groups:
  * the pure join — VERIFIED / QUIET_INCOMPLETE / HONEST_OPEN, the fail-closed-on-
    the-claim floor (a claim NEVER removes work; only the oracle does);
  * `TestToolathlonCorpus` — THE scoring gate docs/207 §Phase 4 names, extended
    from the quiet-failure DETECT-in-trajectory study to KEEP-in-residual: over the
    toolathlon corpus, a claim-done + oracle-`passed=False` row → QUIET_INCOMPLETE,
    scored against the held-out independent-verifier label. Skips when absent.

NOTE (docs/207-seam-ledger §4.4): the corpus is ~7,116 trajectories across 66 JSONL
files, NOT the "751" the plan cites (a stale figure). This gate reads the available
`_data/*.jsonl` with the ground-truth `task_status.evaluation` field; no held-out
751 subset is required.
"""
from __future__ import annotations

import glob
import os

import pytest

from dos import reconcile as _reconcile
from dos.reconcile import Reconciliation, reconcile


# ---------------------------------------------------------------------------
# The pure join.
# ---------------------------------------------------------------------------


class TestReconcileJoin:
    def test_oracle_shipped_is_verified(self):
        v = reconcile("U1", claimed_done=True, oracle_shipped=True)
        assert v.state is Reconciliation.VERIFIED
        assert not v.keeps_in_residual

    def test_oracle_shipped_verified_even_without_claim(self):
        # Ground truth confirms it whether or not the agent claimed it.
        v = reconcile("U1", claimed_done=False, oracle_shipped=True)
        assert v.state is Reconciliation.VERIFIED

    def test_claimed_but_not_shipped_is_quiet_incomplete(self):
        v = reconcile("U1", claimed_done=True, oracle_shipped=False)
        assert v.state is Reconciliation.QUIET_INCOMPLETE
        assert v.keeps_in_residual          # KEPT — the claim never removes work
        assert v.is_quiet_failure
        assert v.flag == "QUIET_INCOMPLETE"

    def test_not_claimed_not_shipped_is_honest_open(self):
        v = reconcile("U1", claimed_done=False, oracle_shipped=False)
        assert v.state is Reconciliation.HONEST_OPEN
        assert v.keeps_in_residual
        assert not v.is_quiet_failure
        assert v.flag == ""

    def test_fail_closed_on_the_claim(self):
        # The whole point: a claim-done that the oracle refutes must NOT leave the
        # residual. If this ever returns VERIFIED on a refuted claim, the gate is wrong.
        v = reconcile("U1", claimed_done=True, oracle_shipped=False)
        assert v.keeps_in_residual, "a refuted claim must stay in the residual"

    def test_to_dict_round_trips(self):
        v = reconcile("U1", claimed_done=True, oracle_shipped=False)
        d = v.to_dict()
        assert d["state"] == "QUIET_INCOMPLETE"
        assert d["keeps_in_residual"] is True
        assert d["flag"] == "QUIET_INCOMPLETE"


# ---------------------------------------------------------------------------
# The toolathlon scoring gate (docs/207 Phase 4).
# ---------------------------------------------------------------------------

_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "benchmark", "toolathlon", "_data")


def _claimed_done(traj) -> bool:
    """Did the agent call the `claim_done` local tool (its self-report)?"""
    for m in traj.messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or ():
            name = str((tc.get("function") or {}).get("name", "")).lower()
            if "claim_done" in name or "claimdone" in name:
                return True
    return False


@pytest.mark.skipif(
    not (os.path.isdir(_DATA) and glob.glob(os.path.join(_DATA, "*.jsonl"))),
    reason="the toolathlon corpus is not present on this machine (offline gate)",
)
class TestToolathlonCorpus:
    """Score `reconcile` over the toolathlon corpus: a claim-done + oracle-`passed=
    False` row must classify QUIET_INCOMPLETE — the natural extension of the
    quiet-failure study from DETECT-in-trajectory to KEEP-in-residual, scored by an
    independent verifier (`task_status.evaluation`) DOS did not author (docs/157's
    bar)."""

    def _corpus(self):
        import sys
        bench = os.path.join(os.path.dirname(_DATA), "..")
        if bench not in sys.path:
            sys.path.insert(0, os.path.dirname(os.path.dirname(_DATA)))
        from toolathlon import dataset  # type: ignore
        rows = []
        # Cap per-file so the gate stays fast (a few thousand trajectories total).
        for p in sorted(glob.glob(os.path.join(_DATA, "*.jsonl"))):
            for traj in dataset.iter_trajectories(p, limit=40):
                if traj.passed is None:
                    continue  # the verifier produced no boolean — excluded from scoring
                rows.append((_claimed_done(traj), bool(traj.passed)))
        return rows

    def test_corpus_present(self):
        rows = self._corpus()
        assert len(rows) >= 100, f"expected ≥100 scorable trajectories, got {len(rows)}"

    def test_claim_done_plus_eval_false_is_quiet_incomplete(self):
        """Every claim-done + oracle-`passed=False` row classifies QUIET_INCOMPLETE,
        and every oracle-`passed=True` row classifies VERIFIED — the exact mapping."""
        rows = self._corpus()
        for claimed, passed in rows:
            v = reconcile("u", claimed_done=claimed, oracle_shipped=passed)
            if passed:
                assert v.state is Reconciliation.VERIFIED
            elif claimed:
                assert v.state is Reconciliation.QUIET_INCOMPLETE
            else:
                assert v.state is Reconciliation.HONEST_OPEN

    def test_quiet_incomplete_precision_recall(self):
        """QUIET_INCOMPLETE, scored against the held-out fail label. PRECISION must
        be 1.0 BY CONSTRUCTION (a QUIET_INCOMPLETE only fires on oracle-not-shipped,
        which IS a fail), and it must RECALL every claimed-fail — the quiet failures
        the picker would otherwise silently drop."""
        rows = self._corpus()
        tp = fp = claimed_fails = 0
        for claimed, passed in rows:
            v = reconcile("u", claimed_done=claimed, oracle_shipped=passed)
            quiet = v.state is Reconciliation.QUIET_INCOMPLETE
            actual_fail = not passed
            if not passed and claimed:
                claimed_fails += 1
            if quiet and actual_fail:
                tp += 1
            elif quiet and not actual_fail:
                fp += 1
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        assert fp == 0, "a QUIET_INCOMPLETE must never fire on a passing run (precision 1.0)"
        assert precision == 1.0
        # Every claimed-fail is recalled (the keep that prevents the silent drop).
        assert tp == claimed_fails
        assert tp > 0, "the corpus should contain real claim-done-but-failed quiet failures"
