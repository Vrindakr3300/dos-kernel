"""Shared O_EXCL file-mutex primitives — the ONE home for "lock + value-keyed steal".

The package grew THREE independent hand-rolled `O_EXCL` mutexes — `archive_lock`
(the Step-9.5 archive ceremony), `lane_lease._Mutex` (the cross-process lane-grant
critical section), and `home._home_lock` (the machine-local index) — each with its
own copy of the same acquire/read/steal logic. When the steal was found to be a
non-value-keyed TOCTOU (two stealers of one stale lock could each displace the
other's fresh lock and both come away holding the mutex — a double-grant), the fix
landed in `archive_lock` ONLY, leaving the two siblings carrying the identical bug.
That is the "fix one site, the duplicate drifts" failure this module exists to end.

So the steal CAS and the O_EXCL write live HERE, parameterized on the lock path, and
every mutex routes through them — making the naive `unlink()` + `O_EXCL-create` steal
**unrepresentable** rather than a per-site choice. This is a Layer-1 leaf: pure
stdlib + a `Path`, no host names, no config, no policy. Each caller still owns its
own *path resolution* (env override + config seam) and its own retry/TTL policy; only
the three atomic FS ops — write, read, steal — are shared.

The discipline these encode:
  * `write_lock`  — atomic `O_CREAT|O_EXCL` create; raises `FileExistsError` if held.
    The ONLY way a lock is born, so "two writers both think they created it" cannot
    happen (the kernel serializes O_EXCL).
  * `read_lock`   — parse a lock file's `key: value` body to a dict (None if absent).
  * `steal_stale` — a **value-keyed compare-and-swap**: rename the lock to a unique
    temp, verify the grabbed content IS the stale lock the caller observed (else
    restore-on-mismatch and concede), then drop it and O_EXCL-create. Only the actor
    that displaces the EXACT stale lock it saw wins; a racer that already stole +
    recreated is detected and conceded to. Two concurrent stealers → exactly one owner.
"""
from __future__ import annotations

import datetime as dt
import os
import random
import sys
import time
from pathlib import Path


# ACCESS_DENIED / SHARING_VIOLATION / LOCK_VIOLATION — the three MoveFileEx
# replace-over-an-open-handle codes seen on win32 (the last from AV/indexer
# byte-range locks). Only these are retried by `atomic_replace`; any other
# OSError re-raises at once.
_REPLACE_RETRY_CODES = (5, 32, 33)


def atomic_replace(
    src: os.PathLike | str,
    dst: os.PathLike | str,
    *,
    budget_s: float = 3.0,
    base_s: float = 0.05,
    cap_s: float = 0.4,
    _stderr=None,
) -> None:
    """`os.replace(src, dst)` with bounded exp-backoff retry on win32 rename races.

    The ONE retry-hardened replace the package's atomic-write sites share
    (`home._atomic_write_jsonl`, `home._write_card`, `run_id.write_run_json`) —
    it belongs beside the O_EXCL write/read/steal primitives because it is the
    same class of atomic FS op, parameterized on a path and carrying no policy.

    On win32 `os.replace` -> `MoveFileEx` raises WinError 5 (ACCESS_DENIED) / 32
    (SHARING_VIOLATION) / 33 (LOCK_VIOLATION) whenever ANY other process holds an
    open handle to the DESTINATION during the rename — a lock-skipping reader, a
    `dos top` tail, `git add`, an AV/Search-indexer/OneDrive scan. A bare
    `os.replace` has NO retry, so the FIRST such collision kills the write
    mid-ceremony. This bounds-retries only on `_REPLACE_RETRY_CODES`, and only
    until `budget_s` elapses; any other OSError (or a non-Windows error, where
    `winerror is None`) re-raises immediately, so on POSIX it degrades to exactly
    one attempt (os.replace already overwrites atomically under open readers
    there). A one-line WARN is emitted before each backoff sleep so a foreign
    handle held LONGER than the budget is visible in the log rather than silently
    absorbed and then crashing opaquely. Pure stdlib (os/time/random) — the
    kernel "PyYAML-only" litmus holds.
    """
    stderr = _stderr if _stderr is not None else sys.stderr
    deadline = time.monotonic() + budget_s
    attempt = 0
    while True:
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            attempt += 1
            winerr = getattr(e, "winerror", None)
            if winerr not in _REPLACE_RETRY_CODES or time.monotonic() >= deadline:
                raise
            sleep_s = min(base_s * (2 ** (attempt - 1)), cap_s) + random.uniform(0, 0.02)
            print(
                f"dos: warning: atomic replace onto {os.fspath(dst)} hit WinError "
                f"{winerr} (attempt {attempt}); a reader/scan holds it open — "
                f"retrying in {sleep_s:.2f}s",
                file=stderr,
            )
            time.sleep(sleep_s)


def unlink_retry(
    path: os.PathLike | str,
    *,
    budget_s: float = 1.0,
    base_s: float = 0.02,
    cap_s: float = 0.2,
    _stderr=None,
) -> bool:
    """`os.unlink(path)` with bounded exp-backoff retry on the win32 open-handle races.

    The release-side sibling of `atomic_replace`. On win32, deleting a file ANY other
    process holds open raises WinError 5/32/33 (ACCESS_DENIED / SHARING_VIOLATION /
    LOCK_VIOLATION) — the same MoveFileEx-family codes — so a bare `lock.unlink()` to
    DROP a mutex can spuriously raise the instant a racing acquirer has the lock file
    open mid-read/mid-steal. A dropped release then leaks the lock until its TTL, and a
    raised release crashes the caller's `finally`. This retries only those codes within
    `budget_s`; a missing file is success (the lock is already gone — the goal). Any
    other OSError, or a POSIX error where `winerror is None`, re-raises at once (POSIX
    unlink under an open handle succeeds anyway, so it degrades to one attempt there).
    Returns True if the file is gone (unlinked or already absent), False only if the
    budget elapsed with the handle still held — the caller treats that as "left for the
    TTL to reap", never a crash. Pure stdlib — the kernel "PyYAML-only" litmus holds.
    """
    stderr = _stderr if _stderr is not None else sys.stderr
    deadline = time.monotonic() + budget_s
    attempt = 0
    while True:
        try:
            os.unlink(os.fspath(path))
            return True
        except FileNotFoundError:
            return True  # already gone — the release goal is met
        except OSError as e:
            attempt += 1
            winerr = getattr(e, "winerror", None)
            if winerr not in _REPLACE_RETRY_CODES:
                raise
            if time.monotonic() >= deadline:
                print(
                    f"dos: warning: could not unlink {os.fspath(path)} (WinError "
                    f"{winerr} — a reader/scan holds it open); leaving it for TTL reap",
                    file=stderr,
                )
                return False
            sleep_s = min(base_s * (2 ** (attempt - 1)), cap_s) + random.uniform(0, 0.01)
            time.sleep(sleep_s)


def now_iso() -> str:
    """The lock-body timestamp format every mutex stamps (`acquired_at`)."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_body(owner: str) -> str:
    """The canonical lock-file body: owner + acquired_at + pid, one `key: value` per line.

    Centralized so the steal CAS's value-comparison (owner + acquired_at) reads the
    same fields every writer stamps. A caller that needs extra fields may append, but
    these three are the contract `steal_stale` keys on."""
    return f"owner: {owner}\nacquired_at: {now_iso()}\npid: {os.getpid()}\n"


def read_lock(path: Path) -> dict | None:
    """Parse a lock file's `key: value` body into a dict; None if absent/unreadable.

    The single parser the canonical read AND the steal CAS share (so the value the
    CAS compares is read the same way the holder wrote it). Never raises."""
    if not path.exists():
        return None
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return None
    info: dict = {}
    for line in contents.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            info[k.strip()] = v.strip()
    return info


def write_lock(path: Path, owner: str) -> None:
    """Atomic `O_CREAT|O_EXCL` create. Raises `FileExistsError` if the lock is held.

    The ONLY way a lock comes into existence — O_EXCL is the kernel-serialized
    primitive that guarantees exactly one creator. `mkdir(parents=True)` first so a
    fresh `.dos/` tree doesn't fail the create."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        os.write(fd, lock_body(owner).encode("utf-8"))
    finally:
        os.close(fd)


def steal_stale(path: Path, owner: str, stale: dict) -> bool:
    """Atomically steal the SPECIFIC stale lock `stale` at `path` for `owner`. True iff WON.

    `stale` is the lock-info dict the caller just `read_lock`'d — the exact stale lock
    it decided to steal. Stealing is a **compare-and-swap keyed on that identity**
    (owner + acquired_at), not on the path alone — which is what closes the TOCTOU the
    naive `unlink()` + `write_lock()` had: there, the unlink took no owner and re-read
    nothing, so two stealers of one stale lock could each unlink the other's fresh lock
    and O_EXCL-create onto the emptied path — both believed they held the mutex.

    The CAS, three steps, each an atomic FS op:
      1. `os.rename` the lock to a per-stealer UNIQUE temp (atomic; a stealer that
         already moved the inode makes ours raise → we lost → return False/retry).
      2. **Verify the temp's content IS the stale lock we observed.** A path-only
         rename is insufficient: a racing stealer that already stole + RE-CREATED a
         fresh lock would have ours move *their* fresh lock — so on a mismatch we
         atomically PUT IT BACK (rename temp→path) and concede. This value check is
         what makes it a true CAS: we only ever displace the stale lock, never a
         winner's live one.
      3. Drop the verified-stale temp and O_EXCL-create our own. A racer that
         re-created the lock in the residual window makes the O_EXCL raise
         FileExistsError → we lost → return False without clobbering theirs.

    Every failure path returns False and leaves the FS consistent (displaced lock
    restored, or our temp cleaned up); only a clean win returns True. A unique temp
    name (pid + monotonic_ns) keeps concurrent stealers from colliding on the temp.
    """
    tmp = path.parent / f".{path.name}.steal.{os.getpid()}.{time.monotonic_ns()}"
    stale_owner = str((stale or {}).get("owner", ""))
    stale_at = str((stale or {}).get("acquired_at", ""))
    try:
        os.rename(str(path), str(tmp))  # step 1: claim whatever is at the path, atomically
    except (FileNotFoundError, OSError):
        return False  # already moved/removed by another stealer — we did not win
    # Step 2: CAS check — is what we grabbed the stale lock we MEANT to steal?
    grabbed = read_lock(tmp)
    grabbed_owner = str((grabbed or {}).get("owner", ""))
    grabbed_at = str((grabbed or {}).get("acquired_at", ""))
    if grabbed_owner != stale_owner or grabbed_at != stale_at:
        # Grabbed a DIFFERENT lock than observed — a racer already won + recreated.
        # Put it back atomically and concede; if the restore loses to yet another
        # racer, drop our temp. Never co-own.
        try:
            os.rename(str(tmp), str(path))
        except OSError:
            try:
                os.unlink(str(tmp))
            except OSError:
                pass
        return False
    # Step 3: it WAS the stale lock — drop it and O_EXCL-create our own.
    try:
        os.unlink(str(tmp))
    except OSError:
        pass
    try:
        write_lock(path, owner)
    except FileExistsError:
        # A racer re-created the lock between our verified rename and our create.
        # We lost — do NOT clobber theirs.
        return False
    return True
