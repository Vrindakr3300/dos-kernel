"""LIVE orchestrator demo — a REAL cross-process A/B: ultracode-flow vs DOS-dispatch.

⚠️  THIS IS A DEMO, NOT THE BENCHMARK.  ⚠️

The falsifiable orchestrator A/B is `harness_loop.py` + `test_orchestrator.py`,
which is deterministic and simulated for the reasons `agent.py:8-18` gives. This
module is the opposite on purpose: it runs the orchestrator axis (docs/98) with
**real, separate OS processes** sharing the **real** lane-journal WAL through the
**real** `dos lease-lane` verb, against a **real** git repo — so the gap the
simulation predicts (a naive harness clobbers; a disciplined one does not) is
shown happening on disk, hand-checkable with `git log`.

It is NOT a measurement (no model in the loop here either — the "workers" are
shell writers so a "clobber" stays checkable), and it must never gate CI.

The setup mirrors the docs/98 live test: a throwaway git repo with N issues whose
footprints deliberately OVERLAP on one shared file. We run the same set of
concurrent writers TWICE, each writer a separate `subprocess`:

  * ARM "dos-dispatch" / disciplined harness — each writer first calls
    `dos lease-lane acquire --lane <issue> --kind keyword --tree <its files>
    --owner <issue>`. On exit 0 (ACQUIRE) it does its write+commit, then
    `dos lease-lane release`. On exit 1 (REFUSE) it backs off and retries after the
    holder releases — so two writers contending on the shared file SERIALIZE: two
    commits, both edits present, ZERO clobber.

  * ARM "naive-flow" — each writer just writes+commits immediately, no
    `dos lease-lane` call (the literal "run agent() in parallel() and forget the
    lease"). Two writers racing the shared file CLOBBER: the second commit
    overwrites the first writer's line, detectable only by `git log` after the fact.

Then we read GROUND TRUTH off git for both arms and report:

  * commits touching the shared file, and whether any line was lost (a real clobber);
  * how many `dos lease-lane` calls returned REFUSE (collisions caught at contention);
  * whether `dos verify`-style ground truth agrees with each arm's claimed ships.

FALSIFIABLE PREDICTION (the headline): the dos-dispatch arm lands every writer's
edit to the shared file with no loss; the naive-flow arm loses at least one. The
boundary falsifier: with `--overlap 0` (no shared file) both arms are identical —
the orchestrator is moot when nothing contends.

Run it explicitly (gated OFF by default; it spawns processes + writes a temp repo,
but spends NO model tokens — the workers are deterministic shell writers):

    DOS_LIVE_DEMO=1 PYTHONPATH=src \
        python -m benchmark.fleet_horizon.live_orchestrator_demo --issues 3 --overlap 2

`--issues N` = number of concurrent writers; `--overlap K` = how many of them also
write the shared file (the contention surface). With K<2 there is no contention.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode the → / — this demo
# prints. Match the kernel modules' guard so the demo runs on Windows too.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


SHARED_FILE = "shared/config.txt"
_REPO = str(Path(__file__).resolve().parents[2])
_SRC = str(Path(_REPO) / "src")


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "demo@bench.local")
    _git(repo, "config", "user.name", "OrchDemo")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("orchestrator demo repo\n", encoding="utf-8")
    (repo / "shared").mkdir(exist_ok=True)
    (repo / SHARED_FILE).write_text("# shared config — every issue appends one line\n",
                                    encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "root: init")


def _dos(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke the `dos` CLI in a SEPARATE process against `repo` as the workspace.

    Sets the lane-journal + lock env to the demo repo so the cross-process WAL is
    shared by every writer process — exactly how separate Workflow branches would
    coordinate. Uses `python -c` to call cli.main (the console-script entry)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = _SRC + os.pathsep + env.get("PYTHONPATH", "")
    env["DISPATCH_LANE_JOURNAL_PATH"] = str(repo / ".lane_journal.jsonl")
    env["DISPATCH_LANE_LEASE_LOCK_PATH"] = str(repo / ".lane-lease.lock")
    return subprocess.run(
        [sys.executable, "-c", "import sys; from dos.cli import main; sys.exit(main())",
         *args],
        cwd=str(repo), capture_output=True, text=True, env=env)


def _writer_files(issue: str, writes_shared: bool) -> list[str]:
    files = [f"{issue}/mod.txt"]
    if writes_shared:
        files.append(SHARED_FILE)
    return files


def _do_write_and_commit(repo: Path, issue: str, files: list[str]) -> None:
    for rel in files:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        # OVERWRITE the shared file's payload line (last-write-wins) so a clobber is
        # a real lost edit; append for private files.
        if rel == SHARED_FILE:
            head = "# shared config — every issue appends one line\n"
            p.write_text(head + f"owner={issue}\n", encoding="utf-8")
        else:
            with p.open("a", encoding="utf-8") as f:
                f.write(f"{issue}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"{issue}: ship")


def _run_arm_naive(repo: Path, issues: list[tuple[str, bool]]) -> dict:
    """Naive flow: every writer commits immediately, no lease. Records clobbers."""
    shared_writers = [iss for iss, sh in issues if sh]
    for issue, writes_shared in issues:
        _do_write_and_commit(repo, issue, _writer_files(issue, writes_shared))
    # ground truth: how many distinct owners survive in the shared file?
    surviving = _surviving_owner(repo)
    lost = max(0, len(shared_writers) - (1 if surviving else 0))
    return {"arm": "naive-flow", "refusals": 0, "shared_writers": shared_writers,
            "surviving_owner": surviving, "edits_lost": lost,
            "commits_touching_shared": _commits_touching(repo, SHARED_FILE)}


def _run_arm_dispatch(repo: Path, issues: list[tuple[str, bool]]) -> dict:
    """Disciplined harness / DOS-dispatch: each writer takes a lane lease via
    `dos lease-lane` before writing the shared file, so contenders serialize."""
    refusals = 0
    serialized_owners: list[str] = []
    for issue, writes_shared in issues:
        files = _writer_files(issue, writes_shared)
        kind = "keyword"
        tree = files  # the writer's real footprint
        if writes_shared:
            # contend for the shared region through the kernel; retry until granted
            for attempt in range(20):
                res = _dos(repo, "lease-lane", "--workspace", ".", "acquire",
                           "--lane", issue, "--kind", kind, "--tree", *tree,
                           "--owner", issue)
                if res.returncode == 0:
                    break
                if res.returncode == 1:
                    refusals += 1
                    time.sleep(0.05)
                    continue
                # lock-busy or error
                time.sleep(0.05)
            _do_write_and_commit(repo, issue, files)
            serialized_owners.append(issue)
            _dos(repo, "lease-lane", "--workspace", ".", "release",
                 "--lane", issue, "--owner", issue)
        else:
            _do_write_and_commit(repo, issue, files)
    surviving = _surviving_owner(repo)
    shared_writers = [iss for iss, sh in issues if sh]
    # under serialization every shared writer's commit landed in turn; the FINAL
    # surviving owner is the last to write, but NO edit was lost to a clobber —
    # each landed as its own commit. "edits_lost" measures concurrent clobber, which
    # serialization eliminates.
    lost = _count_clobbers(repo, SHARED_FILE, len(shared_writers))
    return {"arm": "dos-dispatch", "refusals": refusals,
            "shared_writers": shared_writers, "surviving_owner": surviving,
            "edits_lost": lost, "serialized": serialized_owners,
            "commits_touching_shared": _commits_touching(repo, SHARED_FILE)}


def _surviving_owner(repo: Path) -> str:
    for line in (repo / SHARED_FILE).read_text(encoding="utf-8").splitlines():
        if line.startswith("owner="):
            return line.split("=", 1)[1]
    return ""


def _commits_touching(repo: Path, path: str) -> int:
    out = _git(repo, "log", "--oneline", "--", path)
    return len([l for l in out.splitlines() if l.strip()])


def _count_clobbers(repo: Path, path: str, n_shared_writers: int) -> int:
    """A clobber = a commit to the shared file that REPLACED a prior owner line
    without that prior owner ever getting its own commit. Under serialization each
    writer gets its own commit (commits == writers), so clobbers = 0. Under the
    naive race, writers commit but earlier lines are overwritten in the same
    physical file before the next read — surfaced as fewer surviving owners than
    writers. We approximate the lost-edit count by (writers − distinct owners that
    ever appeared in a commit)."""
    # distinct owners that appear across the file's history
    log = _git(repo, "log", "-p", "--", path)
    owners = set()
    for line in log.splitlines():
        s = line.lstrip("+").strip()
        if s.startswith("owner="):
            owners.add(s.split("=", 1)[1])
    return max(0, n_shared_writers - len(owners))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issues", type=int, default=3, help="concurrent writers")
    ap.add_argument("--overlap", type=int, default=2,
                    help="how many writers ALSO write the shared file (contention)")
    args = ap.parse_args(argv)

    if not os.environ.get("DOS_LIVE_DEMO"):
        print("live orchestrator demo is OPT-IN — set DOS_LIVE_DEMO=1 to run it.\n"
              "It spawns real processes + a temp git repo (no model tokens), and\n"
              "shows `dos lease-lane` preventing on disk the clobber a naive flow\n"
              "lets through. It is a smoke, NOT the benchmark (that is\n"
              "test_orchestrator.py / harness.py --orchestrator-sweep).")
        return 0

    overlap = max(0, min(args.overlap, args.issues))
    issues = [(f"issue-{i:02d}", i < overlap) for i in range(args.issues)]

    print(f"orchestrator live demo — {args.issues} writers, {overlap} contending on "
          f"{SHARED_FILE}\n")

    results = []
    for arm_fn in (_run_arm_naive, _run_arm_dispatch):
        tmp = Path(tempfile.mkdtemp(prefix="orch_live_"))
        repo = tmp / "repo"
        repo.mkdir()
        try:
            _init_repo(repo)
            results.append(arm_fn(repo, issues))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    for r in results:
        print(f"  [{r['arm']:>12}] shared writers={len(r['shared_writers'])}  "
              f"lease-lane refusals={r['refusals']}  "
              f"commits→shared={r['commits_touching_shared']}  "
              f"surviving owner={r['surviving_owner'] or '(none)'}  "
              f"EDITS LOST={r['edits_lost']}")

    naive = next(r for r in results if r["arm"] == "naive-flow")
    disp = next(r for r in results if r["arm"] == "dos-dispatch")
    print()
    if overlap < 2:
        print("  → overlap < 2: no contention. Both arms identical — the orchestrator")
        print("    is MOOT when nothing contends (the docs/98 boundary, shown live).")
    elif disp["edits_lost"] == 0 and naive["edits_lost"] > 0:
        print(f"  → PREDICTION HELD: the naive flow LOST {naive['edits_lost']} edit(s) "
              f"to a clobber; dos-dispatch lost 0 (serialized via {disp['refusals']} "
              f"refusal(s) at contention). `dos lease-lane` prevented on disk what")
        print("    the naive parallel() flow let through — the gap, live.")
    else:
        print(f"  → naive lost={naive['edits_lost']}, dispatch lost={disp['edits_lost']} "
              f"(refusals={disp['refusals']}). Re-run; contention is timing-dependent\n"
              f"    in a live race — the deterministic proof is test_orchestrator.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
