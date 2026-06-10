"""Tests for the CI/Checks driver oracle (`dos.drivers.ci_status`).

This oracle is the docs/85 §2 *move-B* reference: a non-git artifact oracle that
answers "is the build green at this commit?" — the signal git is blind to
(docs/84 §3.3, ship≠correct). Two halves, tested independently the way the kernel
family is built:

  * `classify()` is PURE — a `classify(Evidence, Policy) -> Verdict` in the
    `dos.verdict` family. These tests pin its full four-state ladder
    (GREEN/RED/PENDING/NO_SIGNAL) and the two policy knobs on FROZEN evidence, no
    network — the whole point of caller-gathered evidence is replay-testability.
    The load-bearing property pinned here is the conservative one: a failure
    DOMINATES (RED over green/pending), an unfinished check is never a pass
    (PENDING over GREEN), and an unreachable/unwired provider NEVER fabricates a
    verdict (NO_SIGNAL, never GREEN) — the fail-safe-not-fail-open discipline.

  * `gather()`/`_run_gh()` is the boundary I/O. These tests poison `subprocess.run`
    so the suite never touches the network, and prove every failure mode (no `gh`,
    unauthenticated, unknown SHA, timeout, malformed JSON) degrades to an honest
    NO_SIGNAL evidence object rather than raising — the `git_delta` fail-safe stance.

Plus the structural pins: the verdict conforms to `dos.verdict.TypedVerdict`, and
the driver obeys the one-way import arrow (the kernel never imports it).
"""
from __future__ import annotations

import json
import subprocess

import pytest

from dos.drivers import ci_status as ci
from dos.drivers.ci_status import (
    Ci,
    CheckRun,
    CiEvidence,
    CiPolicy,
    classify,
)


def _ev(*checks: CheckRun, reachable: bool = True, detail: str = "", sha: str = "deadbeefcafe") -> CiEvidence:
    return CiEvidence(sha=sha, repo="o/r", checks=tuple(checks), reachable=reachable, detail=detail)


def _done(name: str, conclusion: str) -> CheckRun:
    return CheckRun(name=name, status="completed", conclusion=conclusion)


def _running(name: str) -> CheckRun:
    return CheckRun(name=name, status="in_progress", conclusion=None)


# ── the pure classifier: the four-state ladder ──────────────────────────────
class TestClassifyLadder:
    def test_all_success_is_green(self):
        v = classify(_ev(_done("test", "success"), _done("build", "success")))
        assert v.verdict is Ci.GREEN
        assert set(v.passing) == {"test", "build"}
        assert v.failing == () and v.pending == ()

    def test_any_failure_is_red(self):
        v = classify(_ev(_done("test", "success"), _done("build", "failure")))
        assert v.verdict is Ci.RED
        assert v.failing == ("build",)

    def test_failure_dominates_pending(self):
        # A red check and a still-running check at once → RED, never PENDING. The
        # conservative ordering: a believer must not be told "still cooking" while a
        # required check is already red.
        v = classify(_ev(_done("a", "failure"), _running("b")))
        assert v.verdict is Ci.RED
        assert v.failing == ("a",) and "b" in v.pending

    def test_running_check_is_pending_not_green(self):
        # No failure, but something hasn't finished → PENDING. An unfinished check is
        # not a pass.
        v = classify(_ev(_done("a", "success"), _running("b")))
        assert v.verdict is Ci.PENDING
        assert v.pending == ("b",) and v.passing == ("a",)

    def test_completed_without_conclusion_is_pending(self):
        # GitHub can report status=completed with a null conclusion briefly; treat the
        # missing conclusion as not-yet-conclusive, never as a pass.
        v = classify(_ev(CheckRun("a", "completed", None)))
        assert v.verdict is Ci.PENDING

    def test_neutral_and_skipped_do_not_redden(self):
        # A skipped optional job / a neutral conclusion is NOT a failure. An all-
        # neutral/skipped run (nothing required failed, nothing pending) is GREEN.
        v = classify(_ev(_done("a", "success"), _done("opt", "skipped"), _done("info", "neutral")))
        assert v.verdict is Ci.GREEN
        assert set(v.passing) == {"a", "opt", "info"}

    @pytest.mark.parametrize("bad", ["timed_out", "cancelled", "action_required", "stale"])
    def test_other_failing_conclusions_are_red(self, bad):
        assert classify(_ev(_done("x", bad))).verdict is Ci.RED


# ── the pure classifier: the no-signal floor (fail-safe) ────────────────────
class TestClassifyNoSignal:
    def test_unreachable_is_no_signal_never_green(self):
        # The provider call failed. We observed nothing → NO_SIGNAL, with the gather's
        # error class surfaced. This is the rung that must NEVER be a fabricated GREEN.
        v = classify(_ev(reachable=False, detail="gh not authenticated (run `gh auth login`)"))
        assert v.verdict is Ci.NO_SIGNAL
        assert "not authenticated" in v.reason

    def test_unreachable_ignores_any_stale_checks(self):
        # Even if a checks tuple is somehow present, reachable=False means we did not
        # trust the read → NO_SIGNAL regardless (fail-safe, never fail-open).
        v = classify(_ev(_done("test", "success"), reachable=False, detail="network"))
        assert v.verdict is Ci.NO_SIGNAL

    def test_no_checks_but_reachable_is_no_signal_with_honest_reason(self):
        # gh worked; the commit just has no CI. NO_SIGNAL, but the reason says "no CI
        # here", distinct from the unreachable case.
        v = classify(_ev())  # reachable=True, checks=()
        assert v.verdict is Ci.NO_SIGNAL
        assert "no CI checks found" in v.reason

    def test_empty_sha_unreachable_does_not_crash(self):
        v = classify(CiEvidence(sha="", reachable=False, detail="no commit SHA given"))
        assert v.verdict is Ci.NO_SIGNAL


# ── the pure classifier: the policy knobs ───────────────────────────────────
class TestClassifyPolicy:
    def test_required_checks_filters_gating_set(self):
        # Only `test` is required; a failing non-required `lint` must NOT redden.
        pol = CiPolicy(required_checks=frozenset({"test"}))
        v = classify(_ev(_done("test", "success"), _done("lint", "failure")), pol)
        assert v.verdict is Ci.GREEN
        assert v.passing == ("test",)

    def test_required_failing_still_reddens(self):
        pol = CiPolicy(required_checks=frozenset({"test"}))
        v = classify(_ev(_done("test", "failure"), _done("lint", "success")), pol)
        assert v.verdict is Ci.RED

    def test_no_required_check_matches_is_no_signal(self):
        # There are checks, but none match the required set → no gating signal.
        pol = CiPolicy(required_checks=frozenset({"nonexistent"}))
        v = classify(_ev(_done("test", "success")), pol)
        assert v.verdict is Ci.NO_SIGNAL
        assert "match the required set" in v.reason

    def test_policy_rejects_bad_treat_pending_as(self):
        with pytest.raises(ValueError):
            CiPolicy(treat_pending_as=Ci.GREEN)


# ── the boundary reader: every failure degrades, never raises ───────────────
class TestGatherFailSafe:
    def test_missing_gh_is_unreachable(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("gh")
        monkeypatch.setattr(subprocess, "run", boom)
        ev = ci.gather("abc123", repo="o/r")
        assert ev.reachable is False and "not installed" in ev.detail

    def test_timeout_is_unreachable(self, monkeypatch):
        def slow(*a, **k):
            raise subprocess.TimeoutExpired(cmd="gh", timeout=20)
        monkeypatch.setattr(subprocess, "run", slow)
        ev = ci.gather("abc123")
        assert ev.reachable is False and "timed out" in ev.detail

    def test_nonzero_unauth_is_labelled(self, monkeypatch):
        class P:
            returncode = 1
            stdout = ""
            stderr = "error: not logged into any GitHub hosts. Run gh auth login"
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
        ev = ci.gather("abc123")
        assert ev.reachable is False and "not authenticated" in ev.detail

    def test_nonzero_404_is_labelled(self, monkeypatch):
        class P:
            returncode = 1
            stdout = ""
            stderr = "gh: Not Found (HTTP 404)"
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
        ev = ci.gather("abc123")
        assert ev.reachable is False and "not found" in ev.detail

    def test_empty_sha_short_circuits_without_calling_gh(self, monkeypatch):
        def tripwire(*a, **k):  # pragma: no cover - must not be called
            raise AssertionError("gh should not be called for an empty SHA")
        monkeypatch.setattr(subprocess, "run", tripwire)
        ev = ci.gather("")
        assert ev.reachable is False and "no commit SHA" in ev.detail

    def test_good_read_parses_checks(self, monkeypatch):
        payload = json.dumps({"check_runs": [
            {"name": "test", "status": "completed", "conclusion": "success"},
            {"name": "build", "status": "in_progress", "conclusion": None},
            {"name": "", "status": "completed", "conclusion": "success"},  # dropped: no name
        ]})

        class P:
            returncode = 0
            stdout = payload
            stderr = ""
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
        ev = ci.gather("abc123", repo="o/r")
        assert ev.reachable is True
        assert {c.name for c in ev.checks} == {"test", "build"}  # the nameless one dropped
        # And the whole gather → classify round-trips to the honest PENDING.
        assert classify(ev).verdict is Ci.PENDING

    def test_malformed_json_is_empty_not_crash(self, monkeypatch):
        class P:
            returncode = 0
            stdout = "{not json"
            stderr = ""
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
        ev = ci.gather("abc123")
        assert ev.reachable is True and ev.checks == ()
        assert classify(ev).verdict is Ci.NO_SIGNAL  # reachable, but nothing to read


# ── structural pins ─────────────────────────────────────────────────────────
class TestContractConformance:
    def test_verdict_conforms_to_typed_verdict(self):
        # The CI verdict satisfies the dos.verdict.TypedVerdict contract, so a future
        # dos.verdicts.register could expose it uniformly (it stays a driver oracle,
        # not a kernel verb, because it fails gate 3 — domain-free — speaking GitHub).
        from dos.verdict import conforms
        v = classify(_ev(_done("test", "success")))
        assert conforms(v) is True

    def test_to_dict_is_json_shaped(self):
        v = classify(_ev(_done("test", "success"), _done("build", "failure")))
        d = v.to_dict()
        assert d["verdict"] == "RED"
        assert d["failing"] == ["build"]
        assert d["evidence"]["repo"] == "o/r"
        # Round-trips through json without a custom encoder.
        assert json.loads(json.dumps(d))["verdict"] == "RED"

    def test_kernel_does_not_import_this_driver(self):
        # The one-way arrow: a driver imports the kernel, never the reverse. Walk the
        # IMPORT STATEMENTS (AST) of the kernel source (everything under src/dos except
        # drivers/) for an import of this module — there must be none.
        #
        # AST, not a substring grep: the kernel legitimately NAMES `ci_status` in PROSE
        # now — `config.py`'s `[verify] non_git_oracle = "ci_status"` example, the
        # docs/265 seam docstrings in `oracle.py`/`cli.py` — and a docstring mention is
        # not a coupling (the kernel resolves the driver BY NAME at the boundary via
        # `_load_witness_driver`, never `import`s it). This mirrors the canonical
        # `test_vendor_agnostic_kernel.py::test_no_kernel_module_imports_a_driver`,
        # which is explicit that it walks imports "not docstrings, so a comment
        # mentioning `drivers/__init__` does not trip it". The real guarantee — no
        # kernel module imports this driver — is unchanged and still enforced; only the
        # blunt substring check (which a prose mention false-trips) is corrected.
        import ast
        import pathlib

        import dos
        root = pathlib.Path(dos.__file__).parent
        offenders = []
        for p in root.rglob("*.py"):
            if "drivers" in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.endswith("ci_status") or "ci_status" in alias.name.split("."):
                            offenders.append(f"{p.name}:{node.lineno}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod.endswith("ci_status") or "ci_status" in mod.split("."):
                        offenders.append(f"{p.name}:{node.lineno}: from {mod} import …")
                    # also `from dos.drivers import ci_status`
                    elif mod.endswith("drivers") or mod == "dos.drivers":
                        for alias in node.names:
                            if alias.name == "ci_status":
                                offenders.append(f"{p.name}:{node.lineno}: from {mod} import ci_status")
        assert offenders == [], f"kernel modules import the ci_status driver: {offenders}"
