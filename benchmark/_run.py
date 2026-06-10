"""The standardized benchmark runner — one entrypoint for all 6 DOS benchmarks.

    python -m benchmark._run list                       # the inventory + cost + prereqs
    python -m benchmark._run preflight <bench> [--arm A] # check prereqs, load .env, fail loud
    python -m benchmark._run run <bench> [--arm A] [--set k=v ...] [--dry-run]
    python -m benchmark._run status                      # which committed numbers are stale vs HEAD

WHY THIS IS LAYERING-SAFE. This file lives under `benchmark/` (the CONSUMER side,
same as the MCP server / release scripts relative to the kernel). It `import dos`
ONLY to stamp the kernel version into a run record, and it imports the benchmark
`registry` (also consumer-side). It launches every benchmark by SUBPROCESS
(`python -m benchmark.<x>`), never folding a benchmark's logic into the kernel's
import graph. Nothing under `src/dos/*.py` imports this — the one-way arrow,
pinned by tests/test_bench_layering.py.

A named ARM resolves to DOS_* env via the shared `_arms` vocabulary, so the
operator never sets a DOS_* variable by hand (the cure for env-knob soup). Every
DOS_* knob is popped before an arm's env is applied (the docs/152 no-leak rule).
Every run writes a stamped record under benchmark/<bench>/_runs/ (gitignored)
recording the kernel version, date, arm, and prereq state — so a later `status`
can tell a fresh run from a stale committed summary.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent              # benchmark/
_REPO = _HERE.parent                                  # repo root
sys.path.insert(0, str(_HERE))                        # so `import registry`, `import _arms` resolve

import _arms                                           # noqa: E402
import registry                                        # noqa: E402


# --------------------------------------------------------------------------- .env
def load_dotenv(path: Path = None) -> list:
    """Load KEY=VALUE lines from repo-root .env into os.environ (without clobbering
    a value already set in the real environment). Returns the names loaded. This is
    the fix for "the Gemini key sits in .env but nothing loads it" — paid arms need it."""
    path = path or (_REPO / ".env")
    loaded = []
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            loaded.append(k)
    return loaded


# --------------------------------------------------------------- prereq checking
def _docker_up() -> bool:
    exe = shutil.which("docker")
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _dataset_present(root_env: str) -> bool:
    """A *_ROOT dataset is present if the env points at a dir, OR a sibling clone exists.
    Mirrors the 3-way fallback in the benchmarks' own corpus_root()."""
    p = os.environ.get(root_env)
    if p and Path(p).is_dir():
        return True
    name = "AgentHallu/AgentHallu" if root_env == "AGENTHALLU_ROOT" else "AgentProcessBench"
    for base in (_REPO.parent,):
        if (base / name).is_dir():
            return True
    return False


def check_prereq(pr: "registry.Prereq") -> tuple:
    """Return (ok: bool, detail: str). Loads .env first for API_KEY checks."""
    if pr.kind == registry.NONE:
        return True, "no prereq"
    if pr.kind == registry.DOCKER:
        return (_docker_up(), "docker daemon")
    if pr.kind == registry.API_KEY:
        load_dotenv()
        ok = bool(os.environ.get(pr.detail))
        return ok, f"{pr.detail} ({'set' if ok else 'UNSET'})"
    if pr.kind == registry.DATASET:
        return _dataset_present(pr.detail), f"{pr.detail} corpus"
    if pr.kind == registry.GYM:
        return (_REPO / pr.detail).is_dir(), pr.detail
    return False, f"unknown prereq kind {pr.kind!r}"


def prereq_state(entry: "registry.Entrypoint") -> list:
    """Gather the structured prereq state for one entrypoint WITHOUT printing.

    Returns a list of {kind, detail, ok} dicts — the data the run-stamp records so a
    later reader knows exactly what was (or was not) satisfied when the run executed
    (the cure-2 `prereq_state` field). Empty list ⇒ no external prereqs ($0). This is
    the "I/O at the boundary, data to the record" split: the checks run here, the
    pure data lands in the stamp."""
    state = []
    for pr in entry.prereqs:
        ok, detail = check_prereq(pr)
        state.append({"kind": pr.kind, "detail": detail, "ok": ok})
    return state


def preflight(spec: "registry.BenchSpec", entry: "registry.Entrypoint", verbose=True) -> bool:
    """Check every prereq for one entrypoint. Returns True iff all pass; prints the
    fix command for each failure (loud + early — never spend on a missing prereq)."""
    all_ok = True
    if not entry.prereqs:
        if verbose:
            print(f"  [{spec.name}/{entry.name}] no prereqs — $0/{entry.cost}")
        return True
    for pr in entry.prereqs:
        ok, detail = check_prereq(pr)
        mark = "OK " if ok else "MISSING"
        if verbose:
            print(f"  [{mark}] {detail}")
            if not ok and pr.fix:
                print(f"          fix: {pr.fix}")
        all_ok = all_ok and ok
    return all_ok


# ------------------------------------------------------------------ run + stamp
def _kernel_version() -> str:
    try:
        import dos  # CONSUMER import — for the stamp only; the kernel never imports us
        return getattr(dos, "__version__", "?")
    except Exception:
        return "?"


def _git_head() -> str:
    try:
        r = subprocess.run(["git", "-C", str(_REPO), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else "?"
    except Exception:
        return "?"


# --------------------------------------------------------- the RESULTS-stamp grammar
# A scored summary (RESULTS.md / RESULTS.txt) is the TRACKED artifact whose numbers go
# stale as the kernel moves under them (cure 5). For `status` to flag that, the summary
# must carry a machine-parseable provenance stamp. The canonical grammar is one comment
# line, identical in .md and .txt (both tolerate a bare `#`/`<!-- -->` line):
#
#     <!-- dos-bench-stamp: kernel=0.13.0 sha=8148378 date=2026-06-06 -->
#
# The parser is TOLERANT: it reads the canonical `kernel=` field if present, else falls
# back to the legacy `# dos kernel X.Y.Z` line some summaries already carry, else reports
# "unstamped". It diffs the parsed kernel VERSION against the current `_kernel_version()`
# — version is what both the summaries and `dos.__version__` honestly carry (the kernel
# SHA is not recorded inside the committed files, so version is the available comparand).
_STAMP_CANON_RE = re.compile(
    r"dos-bench-stamp:\s*kernel=(?P<kernel>[0-9][0-9A-Za-z.\-]*)"
    r"(?:\s+sha=(?P<sha>[0-9a-f]{4,40}))?"
    r"(?:\s+date=(?P<date>[0-9T:\-]+))?",
    re.IGNORECASE,
)
# the legacy stamp already in fleet_horizon/RESULTS.txt: `# dos kernel 0.6.0`
_STAMP_LEGACY_RE = re.compile(r"#\s*dos kernel\s+(?P<kernel>[0-9][0-9A-Za-z.\-]*)", re.IGNORECASE)


def results_stamp_line(kernel: str = None, sha: str = None, date: str = None) -> str:
    """The canonical RESULTS provenance stamp line for the current (or given) state.

    A summary's author drops this near the top so `status` can later judge freshness.
    Defaults to the live kernel version / git head / today (UTC date)."""
    kernel = kernel or _kernel_version()
    sha = sha or _git_head()
    date = date or _now_iso()[:10]
    return f"<!-- dos-bench-stamp: kernel={kernel} sha={sha} date={date} -->"


def read_results_stamp(path: Path) -> dict:
    """Parse a committed RESULTS file's provenance stamp.

    Returns {found, kernel, sha, date, source} — `source` is 'canon' | 'legacy' | 'none'.
    Scans only the file head (stamps live near the top); tolerant of either grammar and
    of a missing file. PURE-ish: one bounded read, no mutation."""
    out = {"found": False, "kernel": None, "sha": None, "date": None, "source": "none"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    head = "\n".join(text.splitlines()[:40])  # the stamp lives near the top
    m = _STAMP_CANON_RE.search(head)
    if m:
        out.update(found=True, source="canon", kernel=m.group("kernel"),
                   sha=m.group("sha"), date=m.group("date"))
        return out
    m = _STAMP_LEGACY_RE.search(head)
    if m:
        out.update(found=True, source="legacy", kernel=m.group("kernel"))
    return out


def _resolve_argv(entry: "registry.Entrypoint", overrides: dict) -> list:
    """Fill {token} placeholders in the entrypoint argv from defaults + --set overrides.
    A multi-word value (e.g. arms='none warn block') expands to multiple argv items."""
    subs = dict(entry.defaults)
    subs.update(overrides)
    out = []
    for tok in entry.argv:
        if tok.startswith("{") and tok.endswith("}"):
            key = tok[1:-1]
            if key not in subs:
                raise SystemExit(f"entrypoint {entry.name} needs --set {key}=... (no default)")
            out.extend(str(subs[key]).split())
        else:
            out.append(tok)
    return out


def _launch_argv(entry: "registry.Entrypoint", overrides: dict) -> tuple:
    """Build (argv, cwd) for the subprocess. Module form by default
    (`python -m <mod> <args>` from the repo root); script form when the entrypoint
    sets `script` (`python <abs script> <args>` from `cwd`) — the gym-collision
    escape hatch. Returns (argv, cwd_path)."""
    resolved = _resolve_argv(entry, overrides)
    if entry.script:
        script = _REPO / entry.script
        cwd = _REPO / entry.cwd if entry.cwd else _REPO
        # resolved[0] is the module name (display only); the rest are the args.
        return [sys.executable, str(script)] + resolved[1:], cwd
    return [sys.executable, "-m"] + resolved, _REPO


def _now_iso() -> str:
    """The run timestamp (UTC, second precision). A run-record DATE so a later reader
    can order runs and tell a fresh stamp from an old one — the cure-2 `date` field."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _stamp_slug(entry: "registry.Entrypoint") -> str:
    """A filesystem-safe slug distinguishing runs of the SAME entry at the SAME SHA
    that differ by ARM — so two paid arms of one `live` entry don't collide to one
    stamp file (the per-arm-record requirement of cure 2). The arm is the load-bearing
    discriminant; without one the entry name alone is unambiguous."""
    slug = f"{entry.name}_{entry.arm}" if entry.arm else entry.name
    return re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-")


def run(spec, entry, overrides, dry_run=False, model=None) -> int:
    # 1) preflight (loud, early)
    if not preflight(spec, entry, verbose=True):
        print(f"\nPREREQS NOT MET for {spec.name}/{entry.name} — refusing to run "
              f"(fix the MISSING items above).")
        return 2
    # 2) resolve the arm's DOS_* env (pop all knobs first — the no-leak rule)
    env = dict(os.environ)
    _arms.clear_dos_knobs(env)
    if entry.arm:
        env.update(_arms.arm_env(entry.arm))
    # 3) build the subprocess argv (module form, or script form for the gym arm)
    argv, cwd = _launch_argv(entry, overrides)
    print(f"\n$ {' '.join(argv)}")
    print(f"  cwd={cwd}  arm={entry.arm or '(none)'} dos_env="
          f"{ {k: env[k] for k in _arms.ALL_DOS_KNOBS if k in env} }")
    if dry_run:
        print("  --dry-run: not executing")
        return 0
    # 4) run from the resolved cwd (repo root for -m; the entry's cwd for script form)
    proc = subprocess.run(argv, cwd=str(cwd), env=env)
    # 5) stamp a run record (gitignored). The cure-2 convention: every run records
    # {kernel_sha, date, arm, model, prereq_state} — so `status` can tell a fresh run
    # from a stale committed summary and an operator can audit WHAT ran UNDER WHAT.
    runs_dir = _HERE / spec.name / "_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    head = _git_head()
    stamp = {
        "bench": spec.name, "entry": entry.name, "arm": entry.arm or None,
        "cost": entry.cost, "kernel_version": _kernel_version(), "git_head": head,
        "date": _now_iso(), "model": model,
        "argv": argv[1:], "launch": "script" if entry.script else "module",
        "exit_code": proc.returncode, "overrides": overrides,
        "prereq_state": prereq_state(entry),
    }
    # filename keyed by git head + entry + arm so a re-run at the same SHA is
    # idempotently named PER (entry, arm) — two arms of one entry no longer collide.
    rec = runs_dir / f"run_{head}_{_stamp_slug(entry)}.json"
    rec.write_text(json.dumps(stamp, indent=2), encoding="utf-8")
    print(f"\n  exit={proc.returncode}  stamped {rec.relative_to(_REPO)}")
    return proc.returncode


# ------------------------------------------------------------------------ verbs
def cmd_list(args) -> int:
    head = _git_head()
    print(f"DOS benchmarks (kernel {_kernel_version()} @ {head})\n")
    for spec in registry.BENCHMARKS.values():
        print(f"* {spec.name}")
        print(f"    Q: {spec.question}")
        for e in spec.entrypoints:
            pr = ",".join(sorted({p.kind for p in e.prereqs})) or "none"
            armtxt = f" arm={e.arm}" if e.arm else ""
            print(f"      - {e.name:14s} [{e.cost:4s}] prereqs={pr}{armtxt}  — {e.does}")
        if spec.results_summary:
            print(f"    summary: {spec.results_summary}")
        print()
    return 0


def cmd_preflight(args) -> int:
    spec = registry.BENCHMARKS[args.bench]
    entry = spec.entry(args.arm) if args.arm else spec.free_default()
    print(f"Preflight {spec.name}/{entry.name} (cost={entry.cost}):")
    ok = preflight(spec, entry, verbose=True)
    print("\nREADY" if ok else "\nNOT READY — fix the MISSING items above.")
    return 0 if ok else 2


def cmd_run(args) -> int:
    spec = registry.BENCHMARKS[args.bench]
    entry = spec.entry(args.arm) if args.arm else spec.free_default()
    overrides = {}
    for kv in (args.set or []):
        k, _, v = kv.partition("=")
        overrides[k.strip()] = v.strip()
    return run(spec, entry, overrides, dry_run=args.dry_run, model=args.model)


def _summary_freshness(spec) -> str:
    """The cure-5 headline: is this benchmark's COMMITTED scored summary stale?

    Reads spec.results_summary's provenance stamp and diffs its kernel version against
    the live kernel. This answers 'are the PUBLISHED numbers stale?' — independent of
    whether a local re-run exists (the previous status conflated the two and reported a
    7-version-stale summary as `fresh` just because a local run was written at HEAD)."""
    if not spec.results_summary:
        return "no committed summary"
    path = _REPO / spec.results_summary
    if not path.is_file():
        return f"summary missing ({spec.results_summary})"
    stamp = read_results_stamp(path)
    if not stamp["found"]:
        return "summary UNSTAMPED (add a dos-bench-stamp line — cannot judge freshness)"
    cur = _kernel_version()
    k = stamp["kernel"]
    if k == cur:
        return f"summary fresh (kernel {k})"
    return f"summary STALE (numbers at kernel {k}, now {cur})"


def cmd_status(args) -> int:
    """Two independent freshness signals per benchmark:

      1. the COMMITTED summary's stamped kernel vs the live kernel — 'are the published
         numbers stale?' (the cure-5 headline); and
      2. the latest LOCAL run record's git head vs HEAD — 'did I re-run here at HEAD?'.

    The two were previously conflated (a local run at HEAD masked a stale committed
    summary). They are reported on separate lines now."""
    head = _git_head()
    cur = _kernel_version()
    print(f"Freshness vs HEAD ({head}, kernel {cur}):\n")
    for spec in registry.BENCHMARKS.values():
        print(f"* {spec.name:18s} — {_summary_freshness(spec)}")
        runs_dir = _HERE / spec.name / "_runs"
        recs = sorted(runs_dir.glob("run_*.json")) if runs_dir.is_dir() else []
        if not recs:
            print(f"  {'':18s}   local: no local run")
            continue
        latest = json.loads(recs[-1].read_text(encoding="utf-8"))
        stale = latest.get("git_head") != head
        flag = "STALE (run was at " + latest.get("git_head", "?") + ")" if stale else "at HEAD"
        print(f"  {'':18s}   local: last {latest.get('entry')} @ {latest.get('git_head')} "
              f"exit={latest.get('exit_code')}  [{flag}]")
    return 0


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="benchmark._run", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the benchmark inventory")
    benches = sorted(registry.BENCHMARKS)
    p_pre = sub.add_parser("preflight", help="check a benchmark's prereqs")
    p_pre.add_argument("bench", choices=benches)
    p_pre.add_argument("--arm", help="entrypoint/arm name (default: cheapest free)")
    p_run = sub.add_parser("run", help="run a benchmark entrypoint")
    p_run.add_argument("bench", choices=benches)
    p_run.add_argument("--arm", help="entrypoint/arm name (default: cheapest free)")
    p_run.add_argument("--set", action="append", metavar="k=v", help="override a {token} default")
    p_run.add_argument("--model", help="the model this run uses (recorded in the stamp; "
                                       "the runner does not enforce it — paid entrypoints "
                                       "select their own model via --set/config)")
    p_run.add_argument("--dry-run", action="store_true", help="resolve + preflight but do not execute")
    sub.add_parser("status", help="which committed numbers are stale vs HEAD")
    args = ap.parse_args(argv)
    return {"list": cmd_list, "preflight": cmd_preflight, "run": cmd_run, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
