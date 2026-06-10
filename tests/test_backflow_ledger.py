"""Tests for the job→DOS back-flow ledger (`scripts/backflow_ledger.py`).

This is DOS dev/audit tooling, not a kernel module — it operates *on* the package
(greps `src/dos/` for fix-id citations), the same one-way arrow as
`claims_lint.py` / `trajectory_audit.py`. The suite pins the properties that make
the ledger trustworthy rather than decorative:

  * the LANDED half is DERIVED from the code (a fix-id is "landed" iff a kernel
    module cites it) — so it cannot drift from reality;
  * the OWED detector filters out everything LANDED, curated-STRANDED, out-of-lane,
    or resolved-by-commit — so a stale OWED row is a real regression a CI gate
    catches, not noise;
  * the known-landed picker/integrity cohort is actually present (a guard against
    someone deleting a provenance citation during a refactor).

It is advisory by construction (exits 0 on render; 1 only under `--check` with a
genuine OWED) — a PDP, not a PEP, the same posture as the kernel.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

# Import the script-under-test by path (it is not an installed package).
_HELPER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "backflow_ledger.py"
_spec = importlib.util.spec_from_file_location("backflow_ledger", _HELPER_PATH)
bl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bl)

_REPO = Path(__file__).resolve().parent.parent


# ── the LANDED half is derived from the code, and the known cohort is present ──
class TestLandedDerivation:
    def test_landed_is_grep_derived(self):
        landed = bl.derive_landed(_REPO)
        # a dict of fix_id -> [modules]; every value is a non-empty module list
        assert isinstance(landed, dict)
        assert landed, "no fix-id citations found in src/dos — provenance lost?"
        for fid, mods in landed.items():
            assert mods and all(m.endswith(".py") for m in mods)

    def test_known_picker_cohort_landed(self):
        """The picker/integrity cohort that demonstrably crossed must stay cited.

        A regression here means a refactor dropped a provenance comment — the
        thing the §8d review rule exists to prevent.
        """
        landed = bl.derive_landed(_REPO)
        for fid in ("FQ-420", "FQ-449", "FQ-452", "FQ-493", "MQ3X"):
            assert fid in landed, f"{fid} provenance citation missing from src/dos"

    def test_pickable_drain_trap_cite(self):
        # FQ-493 (the HoldReason drain-trap gate) lands in pickable.py specifically.
        landed = bl.derive_landed(_REPO)
        assert "pickable.py" in landed.get("FQ-493", [])


# ── the OWED detector is correct (the load-bearing one) ────────────────────────
class TestOwedDetector:
    def test_resolved_commit_not_owed(self):
        """A commit whose disposition is recorded must NOT surface OWED."""
        landed = bl.derive_landed(_REPO)
        for sha in bl._RESOLVED_BY_COMMIT:
            fixes = [(sha, "fix(dispatch): some unmatchable subject 529")]
            owed = bl.detect_owed(fixes, landed, bl.STRANDED)
            assert owed == [], f"{sha} is resolved but flagged OWED"

    def test_stranded_fix_id_not_owed(self):
        """A job commit whose FQ-id is in the curated STRANDED list is tracked."""
        landed = bl.derive_landed(_REPO)
        fixes = [("deadbeef", "fix(replan): FQ-494 cooldown reset")]
        assert bl.detect_owed(fixes, landed, bl.STRANDED) == []

    def test_landed_fix_id_not_owed(self):
        landed = bl.derive_landed(_REPO)
        fixes = [("deadbeef", "fix(arbiter): FQ-449 sibling-disjoint auto-pick")]
        assert bl.detect_owed(fixes, landed, bl.STRANDED) == []

    def test_out_of_lane_not_owed(self):
        landed = bl.derive_landed(_REPO)
        fixes = [("deadbeef", "fix(apply/gemini): FQ-472 terminal JSON")]
        assert bl.detect_owed(fixes, landed, bl.STRANDED) == []

    def test_genuinely_untracked_IS_owed(self):
        """The detector must still fire on a real untracked fix (no false-negative)."""
        landed = bl.derive_landed(_REPO)
        fixes = [("cafe1234", "fix(dispatch): FQ-9999 a brand-new wedge nobody tracked")]
        owed = bl.detect_owed(fixes, landed, bl.STRANDED)
        assert owed == [("cafe1234", "fix(dispatch): FQ-9999 a brand-new wedge nobody tracked")]

    def test_keyword_match_stranded_not_owed(self):
        """An id-less commit matched by a STRANDED match_text keyword is tracked."""
        landed = bl.derive_landed(_REPO)
        fixes = [("deadbeef", "fix(dispatch): launch child2 /fanout DETACHED")]
        assert bl.detect_owed(fixes, landed, bl.STRANDED) == []


# ── the STRANDED work-list shape is well-formed (it drives the plan) ───────────
class TestStrandedShape:
    def test_two_high_value_lifts_owed(self):
        """Exactly the two HIGH items carry a LIFT disposition with a target phase."""
        lifts = [r for r in bl.STRANDED if r["disposition"] == "LIFT"]
        assert {r["id"] for r in lifts} == {"S1", "S2"}
        for r in lifts:
            assert r["value"] == "HIGH"
            assert "Phase" in r["target"]

    def test_scope_outs_have_reason(self):
        for r in bl.STRANDED:
            if r["disposition"] == "SCOPE-OUT":
                assert r["target"], f"{r['id']} scope-out has no recorded reason"
