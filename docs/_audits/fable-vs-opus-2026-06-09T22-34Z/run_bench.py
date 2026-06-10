"""Fable 5 vs Opus 4.8 head-to-head runner.

For each (task, model) pair: seed a throwaway git repo, drive the agent with the
EXACT same `claude -p` invocation (only --model differs), capture the result
envelope, then grade against a CLEAN checkout of the agent's HEAD using a hidden
OS-recorded oracle the agent never saw. Writes one JSON per run + a roll-up.

The grading is the non-forgeable witness (the same design as
`benchmark/fleet_horizon/forge.py`): pass/fail is the OS exit code of a test the
agent did not author, run against `git archive HEAD` (so a dirtied working tree
cannot fake a pass). The agent's "I'm done" narration is never trusted.

Budget: a hard USD ceiling (default $20). Cumulative cost is checked AFTER every
run; once the ceiling is reached the runner stops and writes what it has. No
silent truncation — the roll-up records how many of the planned runs completed.

Usage:
    python run_bench.py --models fable,opus --budget 20 [--families swe,term]
                        [--max-turns 30] [--only swe1_daterange,term2_sum]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from suite import SUITE, Task, setup_repo  # noqa: E402

RUNS_DIR = HERE / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Map the short --model token to the canonical model id for the report.
MODEL_ID = {"fable": "claude-fable-5", "opus": "claude-opus-4-8"}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    return r.stdout.strip()


def parse_envelope(log_path: Path) -> dict:
    """Pull the final `result` envelope out of the stream-json log."""
    env = {}
    try:
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "result":
                env = o
    except FileNotFoundError:
        pass
    return env


def grade(task: Task, repo: Path) -> tuple[bool, str]:
    """Run the hidden oracle against a CLEAN checkout of the agent's HEAD.

    Returns (passed, detail). passed ⟺ the oracle command exits 0 against the
    materialized HEAD tree with the hidden test dropped in. The agent never saw
    the oracle and cannot dirty the exported tree, so this is a world fact.
    """
    head = _git(repo, "rev-parse", "HEAD")
    if not head:
        return (False, "no commit on HEAD (agent committed nothing)")
    export = Path(tempfile.mkdtemp(prefix=f"grade_{task.key}_"))
    try:
        arch = subprocess.run(["git", "-C", str(repo), "archive", "HEAD"],
                              capture_output=True)
        if arch.returncode != 0:
            return (False, "git archive HEAD failed")
        untar = subprocess.run(["tar", "-x", "-C", str(export)],
                               input=arch.stdout, capture_output=True)
        if untar.returncode != 0:
            return (False, "tar extract failed")
        # Drop the hidden oracle files into the clean checkout.
        for rel, content in task.oracle_files.items():
            p = export / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        # ensure tests/ is importable as needed; pytest rootdir = export
        r = subprocess.run(task.oracle_cmd, shell=True, cwd=str(export),
                           capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0
        tail = (r.stdout or "")[-600:] + (r.stderr or "")[-300:]
        return (ok, tail.strip())
    except subprocess.TimeoutExpired:
        return (False, "oracle timed out")
    finally:
        shutil.rmtree(export, ignore_errors=True)


def run_one(task: Task, model: str, max_turns: int) -> dict:
    """Drive one (task, model) pair end to end; return the per-run record."""
    workdir = Path(tempfile.mkdtemp(prefix=f"bench_{task.key}_{model}_"))
    repo = workdir / "repo"
    repo.mkdir()
    setup_repo(task, repo)

    log = RUNS_DIR / f"{task.key}__{model}.log"
    err = RUNS_DIR / f"{task.key}__{model}.err"

    cmd = [
        "claude", "-p", task.prompt,
        "--model", model,
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(max_turns),
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as lf, open(err, "w", encoding="utf-8") as ef:
        proc = subprocess.run(cmd, cwd=str(repo), stdout=lf, stderr=ef,
                              timeout=900)
    wall_s = time.time() - t0

    env = parse_envelope(log)
    passed, detail = grade(task, repo)

    head = _git(repo, "rev-parse", "--short", "HEAD")
    head_subject = _git(repo, "log", "-1", "--format=%s")
    n_commits = _git(repo, "rev-list", "--count", "HEAD")

    rec = {
        "task": task.key,
        "family": task.family,
        "note": task.note,
        "model": model,
        "model_id": MODEL_ID.get(model, model),
        "passed": passed,
        "oracle_detail": detail[:500],
        "cli_returncode": proc.returncode,
        "wall_s": round(wall_s, 1),
        # result envelope fields
        "total_cost_usd": env.get("total_cost_usd"),
        "num_turns": env.get("num_turns"),
        "duration_ms": env.get("duration_ms"),
        "stop_reason": env.get("stop_reason"),
        "is_error": env.get("is_error"),
        "subtype": env.get("subtype"),
        "terminal_reason": env.get("terminal_reason"),
        "modelUsage": env.get("modelUsage"),
        # git fossils — proof the agent actually committed something
        "head": head,
        "head_subject": head_subject[:120],
        "n_commits_total": n_commits,
    }
    (RUNS_DIR / f"{task.key}__{model}.json").write_text(
        json.dumps(rec, indent=2), encoding="utf-8")
    shutil.rmtree(workdir, ignore_errors=True)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="fable,opus")
    ap.add_argument("--budget", type=float, default=20.0, help="hard USD ceiling")
    ap.add_argument("--families", default="swe,term")
    ap.add_argument("--max-turns", type=int, default=30)
    ap.add_argument("--only", default="", help="comma-list of task keys to run")
    ap.add_argument("--out", default=str(HERE / "results.json"))
    args = ap.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    families = {f.strip() for f in args.families.split(",") if f.strip()}
    only = {t.strip() for t in args.only.split(",") if t.strip()}
    tasks = [t for t in SUITE if t.family in families and (not only or t.key in only)]

    planned = len(tasks) * len(models)
    print(f"planned runs: {planned} ({len(tasks)} tasks x {len(models)} models); "
          f"budget ${args.budget:.2f}; max-turns {args.max_turns}")

    records: list[dict] = []
    spent = 0.0
    stopped_early = False
    # Order: task-major so fable and opus run back-to-back on the same task
    # (same harness state, fairest A/B), and a budget stop leaves whole tasks done.
    for task in tasks:
        for model in models:
            if spent >= args.budget:
                stopped_early = True
                print(f"  BUDGET REACHED (${spent:.2f} >= ${args.budget:.2f}) — stopping")
                break
            print(f"  -> {task.key:18} {model:6} ...", end="", flush=True)
            try:
                rec = run_one(task, model, args.max_turns)
            except subprocess.TimeoutExpired:
                rec = {"task": task.key, "family": task.family, "model": model,
                       "passed": False, "oracle_detail": "RUN TIMED OUT (900s)",
                       "total_cost_usd": None, "num_turns": None, "wall_s": 900.0,
                       "stop_reason": "timeout"}
                (RUNS_DIR / f"{task.key}__{model}.json").write_text(
                    json.dumps(rec, indent=2), encoding="utf-8")
            records.append(rec)
            c = rec.get("total_cost_usd") or 0.0
            spent += c
            verdict = "PASS" if rec.get("passed") else "fail"
            print(f" {verdict}  ${c:.3f}  {rec.get('num_turns')}t  "
                  f"{rec.get('wall_s')}s  (cum ${spent:.2f})")
        if stopped_early:
            break

    roll = {
        "planned_runs": planned,
        "completed_runs": len(records),
        "stopped_early_on_budget": stopped_early,
        "budget_usd": args.budget,
        "total_spent_usd": round(spent, 4),
        "models": models,
        "families": sorted(families),
        "max_turns": args.max_turns,
        "records": records,
    }
    Path(args.out).write_text(json.dumps(roll, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}  (completed {len(records)}/{planned}, "
          f"spent ${spent:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
