"""A LIVE end-to-end run of the self-improving loop ENGINE on this repo (docs/280).

NOT a unit test (those are tests/test_drivers_self_improve.py, on fakes). This
drives the real `dos.drivers.self_improve.run_cycle` with REAL I/O: a real git
worktree, a real candidate commit, the real pytest suite run on the worktree, and
a real env-measured metric (the count of passing improve-module tests). The point
is to prove the loop's keep-gate fires correctly on LIVE evidence the agent did not
author — the metric is counted by pytest, not claimed.

Run from the repo root with the worktree already created:
    git worktree add ../_si-demo HEAD
    python benchmark/si_live_demo.py ../_si-demo
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Import the real engine + kernel from the LIVE tree (this repo), not the worktree.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dos import improve  # noqa: E402
from dos.drivers import self_improve as si  # noqa: E402


# The metric measures EVERY improve-related test by glob — so a NEW test file the
# candidate adds is counted too (the loop must see the candidate's real effect, or
# it will honestly revert it as a no-op, which is exactly what a too-narrow metric
# produced on the first run of this demo).
def _improve_test_args(tree: Path) -> list[str]:
    return [str(p.relative_to(tree)) for p in sorted((tree / "tests").glob("test_improve*.py"))] + [
        "tests/test_drivers_self_improve.py"
    ]


def _run_suite(tree: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *_improve_test_args(tree)],
        cwd=tree, capture_output=True, text=True,
    )


def _passing_count(tree: Path) -> int:
    """The REAL metric: how many improve-related tests pass on this tree. Env-measured."""
    proc = _run_suite(tree)
    for line in proc.stdout.splitlines():
        if "passed" in line:
            # e.g. "30 passed in 0.40s"
            for tok in line.split():
                if tok.isdigit():
                    return int(tok)
    return 0


def _suite_green(tree: Path) -> bool:
    """The REAL suite witness: did the improve suite exit 0 on this tree?"""
    return _run_suite(tree).returncode == 0


def main(worktree: str) -> int:
    tree = Path(worktree).resolve()

    # --- baseline: the real metric on the green worktree, BEFORE any candidate ---
    baseline = _passing_count(tree)
    print(f"baseline metric (passing improve tests): {baseline}")

    # --- the injected PROPOSER: add one real passing test + commit it (real I/O) ---
    new_test = tree / "tests" / "test_improve_live_addon.py"

    def propose() -> si.Candidate:
        new_test.write_text(
            "def test_live_addon_keep_is_zero_exit():\n"
            "    from dos import improve\n"
            "    ev = improve.CandidateEvidence(suite_passed=True, truth_clean=True,\n"
            "                                   work=2, baseline_work=1)\n"
            "    assert improve.classify(ev).verdict is improve.Candidate.KEEP\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", str(new_test)], cwd=tree, check=True,
                       capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m",
             "test(280): a live-demo addon test", "--", str(new_test)],
            cwd=tree, check=True, capture_output=True,
        )
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tree, text=True,
                             capture_output=True).stdout.strip()
        return si.Candidate(present=True, commit=sha,
                            narrated="added one real passing test", tokens=1500)

    # --- the injected GATHER: real suite + real metric on the worktree ---
    def gather(c: si.Candidate) -> si.WitnessReadback:
        return si.WitnessReadback(
            suite_passed=_suite_green(tree),
            truth_clean=True,  # the candidate claims no plan phase; commit is a real ancestor
            work=_passing_count(tree),
        )

    merged: list[str] = []
    discarded: list[str] = []

    def merge(c: si.Candidate) -> None:
        merged.append(c.commit)

    def discard(c: si.Candidate) -> None:
        # Real revert: drop the candidate commit + the file from the worktree.
        subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=tree,
                       capture_output=True)
        discarded.append(c.commit)

    def escalate(v: improve.CandidateVerdict) -> None:  # pragma: no cover - not hit here
        print(f"ESCALATE: {v.reason}")

    ctx = si.CycleContext(
        propose=propose, gather=gather, merge=merge, discard=discard,
        escalate=escalate, baseline_work=baseline,
    )

    # --- run ONE real cycle; the KERNEL decides off the real numbers ---
    result = si.run_cycle(ctx, consecutive_reverts=0)

    print(f"candidate metric (after): {result.candidate.commit[:8] if result.candidate else '-'}")
    print(f"verdict : {result.verdict.verdict if result.verdict else 'SKIP'}")
    print(f"action  : {result.action}")
    print(f"reason  : {result.reason}")
    print(f"next baseline (ratchet): {result.next_baseline}")
    print(f"merged={len(merged)} discarded={len(discarded)}")

    # The honest expectation: adding a real passing test RAISES the metric, the
    # suite stays green, so the KERNEL says KEEP — witnessed by pytest's count, not
    # by the proposer's word.
    assert result.verdict is not None
    assert result.verdict.verdict is improve.Candidate.KEEP, "a real passing-test gain must KEEP"
    assert result.next_baseline > baseline, "the ratchet must raise the baseline"
    print("\nLIVE RESULT: the kernel KEPT a witnessed improvement (real pytest count). ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "../_si-demo"))
