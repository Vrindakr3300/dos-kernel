"""Mutex for the /fanout-true-headless-multi-agent Step 9.5 archive ceremony.

Two near-concurrent fanouts can both reach Step 9.5 inside a ~30s window. Both
write to `docs/_fanout_runs/INDEX.md` and stage `docs/_plans/execution-state.yaml`
through `git add`. Without serialization, the second orchestrator's edits are
absorbed into the first orchestrator's commit (queue finding #34, observed
20260508T0502Z vs 0458Z `f88a800`).

Lock semantics:
    Path: docs/_fanout_runs/.archive.lock (single shared mutex; gitignored)
    Owner: free-text tag, e.g. `fanout-<UTC-ts>`.
    TTL: 5 minutes — Step 9.5 archive should never run longer; older = orphan.

    Acquire is atomic O_CREAT|O_EXCL. On EEXIST, the helper reads the existing
    lock and decides:
        - same owner            → re-entrant; refresh acquired_at, exit 0.
        - other owner, age <TTL → poll up to --retries times at --retry-interval
                                  seconds; if still busy, exit 1.
        - other owner, age ≥TTL → steal via an atomic compare-and-swap on the
                                  lock inode (`_steal_stale_lock`): rename the
                                  stale lock to a per-stealer temp (atomic; only
                                  one stealer wins) then O_EXCL-recreate. Two
                                  concurrent stealers can never both end up
                                  holding the mutex (the old unlink+recreate was a
                                  TOCTOU that let them).

    Release unlinks the lock if owner matches; on owner mismatch (something
    stole it) prints a warning to stderr and still exits 0 — the archive
    ceremony shouldn't fail over a release race.

Subcommands:
    acquire <owner> [--retries 5] [--retry-interval 2] [--ttl-seconds 300]
        Exit 0 on success (printed: "acquired" | "re-entrant <prev-acquired-at>"
        | "stole-stale <prev-owner> age=<seconds>s").
        Exit 1 if the lock is owned by another live process and retries
        are exhausted (printed: "busy <prev-owner> age=<seconds>s").

    release <owner> [--force]
        Exit 0 if removed (or absent). With --force, removes regardless of
        owner (operator-orphaned cleanup).

    status
        Prints lock state: "free" | "held <owner> age=<seconds>s"
        | "stale <owner> age=<seconds>s".
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dos import _filelock
from dos import config as _config

DEFAULT_TTL_SECONDS = 300
DEFAULT_RETRIES = 5
DEFAULT_RETRY_INTERVAL = 2.0


def _lock_path() -> Path:
    """The cross-process archive lock path for the active workspace.

    Resolves against the injected config (separation refactor), with an env
    override for tests. Re-resolved each call so a test that re-points the
    workspace after import still redirects.
    """
    env = os.environ.get("DISPATCH_ARCHIVE_LOCK_PATH")
    if env:
        return Path(env)
    return _config.active().paths.archive_lock


# Module-level handle for back-compat with callers that read the attribute.
LOCK_PATH = _lock_path()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> dt.datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _read_lock_at(path: Path) -> dict | None:
    """Parse a lock file at an arbitrary path → its `{key: value}` info dict.

    Delegates to the shared `_filelock.read_lock` so this mutex and its siblings
    (lane_lease, home) parse a lock the one same way the shared steal CAS does."""
    return _filelock.read_lock(path)


def _read_lock() -> dict | None:
    return _read_lock_at(_lock_path())


def _write_lock(owner: str) -> None:
    """Atomic O_CREAT|O_EXCL create. Raises FileExistsError if lock present.

    Delegates to the shared `_filelock.write_lock` — the one O_EXCL create every
    mutex in the package uses."""
    _filelock.write_lock(_lock_path(), owner)


def _steal_stale_lock(owner: str, stale: dict) -> bool:
    """Atomically steal the SPECIFIC stale lock `stale` for `owner`. True iff WE won.

    Delegates to the shared `_filelock.steal_stale` — the ONE value-keyed
    compare-and-swap every mutex steals through (so the TOCTOU that let two stealers
    both hold the lock cannot be re-introduced by a per-site copy). `stale` is the
    lock-info dict the caller just `_read_lock`'d; the CAS only displaces the EXACT
    stale lock it names, restoring a racer's fresh lock on mismatch. See
    `_filelock.steal_stale` for the full three-step discipline."""
    return _filelock.steal_stale(_lock_path(), owner, stale)


def _refresh_lock(owner: str) -> None:
    """Re-write the lock with the current timestamp (re-entrant case)."""
    body = f"owner: {owner}\nacquired_at: {_now_iso()}\npid: {os.getpid()}\n"
    _lock_path().write_text(body, encoding="utf-8")


def _age_seconds(info: dict) -> float | None:
    ts = _parse_iso(info.get("acquired_at", ""))
    if ts is None:
        return None
    return (_now() - ts).total_seconds()


def cmd_acquire(args: argparse.Namespace) -> int:
    owner = args.owner
    ttl = args.ttl_seconds
    retries = args.retries
    interval = args.retry_interval

    for attempt in range(retries + 1):
        try:
            _write_lock(owner)
            print(f"acquired {owner}")
            return 0
        except FileExistsError:
            pass

        info = _read_lock()
        if info is None:
            # Lock was unlinked between EEXIST and read; retry the create.
            continue

        prev_owner = info.get("owner", "<unknown>")
        age = _age_seconds(info)

        if prev_owner == owner:
            _refresh_lock(owner)
            prev_at = info.get("acquired_at", "<unknown>")
            print(f"re-entrant {owner} prev-acquired-at={prev_at}")
            return 0

        if age is not None and age >= ttl:
            # Atomic compare-and-swap steal keyed on the stale lock's identity
            # (`info`): only the process that displaces the EXACT stale lock it
            # observed proceeds; a concurrent stealer that already won (and
            # re-created a fresh lock) is detected and conceded to, so two
            # processes can never both come away holding the mutex (the old
            # unlink-then-create TOCTOU). A lost steal falls through to retry.
            if not _steal_stale_lock(owner, info):
                continue
            print(f"stole-stale {prev_owner} age={age:.0f}s")
            return 0

        if attempt < retries:
            age_str = f"{age:.0f}s" if age is not None else "?s"
            print(f"  waiting on {prev_owner} (age={age_str}); retry {attempt + 1}/{retries}", file=sys.stderr)
            time.sleep(interval)
            continue

        age_str = f"{age:.0f}s" if age is not None else "?s"
        print(f"busy {prev_owner} age={age_str}", file=sys.stderr)
        return 1

    return 1


def cmd_release(args: argparse.Namespace) -> int:
    owner = args.owner
    info = _read_lock()
    if info is None:
        print("released (no-lock)")
        return 0

    if args.force:
        try:
            _lock_path().unlink()
        except FileNotFoundError:
            pass
        print(f"force-released (was: {info.get('owner', '<unknown>')})")
        return 0

    if info.get("owner") != owner:
        print(f"WARN: lock owner mismatch (have={info.get('owner', '<unknown>')}, expected={owner}); leaving alone", file=sys.stderr)
        return 0

    try:
        _lock_path().unlink()
    except FileNotFoundError:
        pass
    print(f"released {owner}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    info = _read_lock()
    if info is None:
        print("free")
        return 0
    owner = info.get("owner", "<unknown>")
    age = _age_seconds(info)
    age_str = f"{age:.0f}s" if age is not None else "?s"
    if age is not None and age >= args.ttl_seconds:
        print(f"stale {owner} age={age_str}")
    else:
        print(f"held {owner} age={age_str}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_acq = sub.add_parser("acquire", help="Acquire the archive lock (atomic + retry-with-backoff)")
    p_acq.add_argument("owner", help='Owner tag, e.g. "fanout-20260508T1900Z"')
    p_acq.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    p_acq.add_argument("--retry-interval", type=float, default=DEFAULT_RETRY_INTERVAL, help="Seconds between retries")
    p_acq.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS, help="Stale-threshold; older locks get stolen")

    p_rel = sub.add_parser("release", help="Release the archive lock")
    p_rel.add_argument("owner", help="Owner tag — must match holder unless --force")
    p_rel.add_argument("--force", action="store_true", help="Remove regardless of owner (operator orphan-cleanup)")

    p_st = sub.add_parser("status", help="Print current lock state")
    p_st.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)

    args = ap.parse_args()
    return {
        "acquire": cmd_acquire,
        "release": cmd_release,
        "status": cmd_status,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
