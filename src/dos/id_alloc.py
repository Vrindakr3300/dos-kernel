"""Fleet-wide atomic id allocator — a never-reused, strictly-monotonic integer per scope.

docs/97 / the C6 cut of the git-issues→DOS audit.

The reference userland app keeps minting "the next free number" for a per-day series
(`next-up-<DATE>-N`) by GLOBBING the existing tags into a *used* set and running
`n = 1; while n in used: n += 1` — a textbook check-then-act with no fleet-wide atomic
claim. Two concurrent producers read the same `used` set, both pick the same `N`, and
one clobbers the other; the loser is refused (`TAG_COLLISION_CONCURRENT_SCOPES`) and its
lane bounces into replan for zero picks. The host tracks it as a recurring zero-pick
cause; the structural fix it names is *an atomic allocator*.

This is that allocator, as **domain-free kernel mechanism**. It mints a unique,
never-reused, strictly-monotonic integer per opaque ``scope_key`` — the kernel knows
nothing about "tags", "next-up", or dates; the host maps ``scope_key`` to whatever
series it is numbering and renders the int however it likes. The counter lives in a
tiny per-scope file mutated under the SAME ``_filelock`` O_EXCL mutex + value-keyed
steal the lane-lease and archive-lock critical sections use — so "two allocators hand
out the same int" is unrepresentable, the way O_EXCL makes "two writers both created
the lock" unrepresentable.

The contract, and how it differs from the host's glob-and-gap-fill:

  * **Never reused.** The counter only ever increases; a deleted/abandoned id is NOT
    handed out again. (The host's `while n in used` GAP-FILLS — it reuses the lowest
    free number, so deleting packet 3 makes the next mint reuse 3. A monotonic
    allocator does not: ids stay dense only as long as nothing is deleted. That is the
    deliberate trade — collision-safety over density. A host that needs the int purely
    as a collision-free key gains; a host that relies on dense numbering must accept
    gaps after a delete.)
  * **Strictly monotonic per scope.** Within one ``scope_key`` every ``allocate`` returns
    a value strictly greater than the previous one, across processes and across machines
    sharing the workspace.
  * **Atomic compare-and-increment.** The read→+1→write happens under the O_EXCL lock,
    and the write is ``_filelock.atomic_replace`` (the win32 rename-race-hardened
    replace) — so a concurrent reader/AV/indexer holding the counter file open cannot
    tear the increment.

Layer-1 leaf: pure stdlib + the shared ``_filelock`` primitives + the injected
``SubstrateConfig`` for path resolution. No host names, no plan schema, no policy — the
``scope_key`` is an opaque string the kernel never interprets.
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from pathlib import Path

from dos import _filelock
from dos.config import SubstrateConfig

# The counter files live beside the lane journal / archive lock — the per-project
# state home the seam already resolves (`leases_dir`, the reference layout's
# `docs/_plans`, the generic layout's `.dos/`). One file per scope, plus a sibling
# `.lock` per scope, both under a single `id-alloc/` subdir so the allocator's
# bookkeeping never collides with a lease/journal name.
_SUBDIR = "id-alloc"

# A scope_key is host data, so it may contain anything (slashes, spaces, unicode).
# We never interpret it, but it MUST map to a single safe filename. Keep a readable
# prefix of the original for debuggability, then disambiguate with a stable digest so
# two distinct keys that share a sanitized prefix never share a counter file.
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_READABLE = 48

# The default starting point: the FIRST id handed out for a fresh scope is 1 (so an
# int read as "how many have been minted" is also the last id). Injectable for hosts
# that number from 0 or from a legacy high-water mark.
DEFAULT_START = 1


def _digest(scope_key: str) -> str:
    """A short, stable, dependency-free digest of the scope key (collision-disambiguator).

    Not security-sensitive — it only has to make two distinct keys map to two distinct
    filenames with overwhelming probability. A 64-bit FNV-1a folded to 13 base-36 chars
    is plenty and needs no hashlib import policy call. Deterministic across processes and
    runs (no per-process seed), which is the property that matters: the same key always
    resolves to the same counter file.
    """
    h = 0xCBF29CE484222325
    for b in scope_key.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    out = []
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    n = h or 1
    while n:
        out.append(alphabet[n % 36])
        n //= 36
    return "".join(reversed(out)).rjust(13, "0")


def _scope_filename(scope_key: str) -> str:
    """Map an opaque scope key to a single safe filename stem (readable prefix + digest)."""
    readable = _SAFE.sub("-", scope_key).strip("-")[:_MAX_READABLE] or "scope"
    return f"{readable}.{_digest(scope_key)}"


def _alloc_dir(config: SubstrateConfig) -> Path:
    """The per-project directory the counter + lock files live under.

    Resolves from the injected config's `leases_dir` (the same per-project state home
    the lane journal uses), never `__file__`. An env override exists for tests, mirroring
    `lane_lease`/`archive_lock`."""
    env = os.environ.get("DISPATCH_ID_ALLOC_DIR")
    if env:
        return Path(env)
    base = config.paths.leases_dir or config.paths.dot_dos
    return Path(base) / _SUBDIR


def _counter_path(config: SubstrateConfig, scope_key: str) -> Path:
    return _alloc_dir(config) / f"{_scope_filename(scope_key)}.id"


def _lock_path(config: SubstrateConfig, scope_key: str) -> Path:
    return _alloc_dir(config) / f"{_scope_filename(scope_key)}.lock"


def _read_counter(path: Path) -> int | None:
    """Read the current high-water int (None if the scope has never allocated).

    A corrupt/empty file reads as None rather than raising — the caller seeds from
    `start` in that case, which can never hand out a value below an already-minted one
    because the file is only ever written a strictly-greater value under the lock."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _write_counter(path: Path, value: int) -> None:
    """Atomically replace the counter file with `value` (win32 rename-race hardened).

    Tmp-then-`atomic_replace` so a concurrent reader holding the counter open cannot see
    a torn write, and so a crash mid-write leaves the OLD value intact (never a partial
    int that would read as None and let `start` regress)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    tmp.write_text(str(value), encoding="utf-8")
    _filelock.atomic_replace(tmp, path)


# Retry budget for the O_EXCL hold. The critical section is a tiny read+write, so a
# busy lock clears fast — BUT on win32 a contended O_EXCL create + the
# atomic_replace it serializes can each cost tens of ms under a reader/scan holding
# the file open, so under heavy fan-out (N processes/threads hammering one scope)
# the budget must cover N serialized critical sections, not one. 200 × ~15ms mean
# (with jitter) ≈ a 3s worst-case wait — enough for a deep contended queue to drain
# without a spurious TimeoutError dropping a caller's allocation, while still
# bounding a genuinely-wedged lock. The interval carries ±50% jitter so concurrent
# retriers don't wake in lock-step and thrash the steal path.
DEFAULT_RETRIES = 200
DEFAULT_RETRY_INTERVAL = 0.01
DEFAULT_LOCK_TTL_SECONDS = 30


def _hold(config: SubstrateConfig, scope_key: str, owner: str, *,
          retries: int, retry_interval: float, ttl_seconds: int) -> Path:
    """Take the per-scope O_EXCL mutex (value-keyed steal on a stale hold). Returns lock path.

    The SAME acquire/steal discipline as `lane_lease._Mutex`: O_EXCL create, and if held
    past `ttl_seconds` displace ONLY the exact stale lock observed via
    `_filelock.steal_stale` (the value-keyed CAS — never the naive unlink+create that let
    two stealers both win). Raises TimeoutError if the lock cannot be taken in budget."""
    lock = _lock_path(config, scope_key)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries + 1):
        try:
            _filelock.write_lock(lock, owner)
            return lock
        except FileExistsError:
            pass  # lock is held — fall through to the read/steal/retry path
        except OSError as e:
            # On win32 the O_EXCL create can raise ACCESS_DENIED — NOT
            # FileExistsError — when a CONCURRENT stealer is mid-rename/unlink of
            # the same lock file (the steal CAS's transient window): the directory
            # entry exists but is briefly inaccessible. This surfaces two ways:
            # WinError 5/32/33 (with .winerror set), OR a bare PermissionError
            # (errno 13 / EACCES, .winerror None) when Python maps it to the errno
            # layer. BOTH are transient contention, not a real fault, so retry
            # exactly as for FileExists. Any other errno (a genuine
            # perms/ENOSPC/IO error) re-raises. Same transient-win32 discipline as
            # atomic_replace/unlink_retry, widened to the errno-13 manifestation.
            transient = (
                getattr(e, "winerror", None) in _filelock._REPLACE_RETRY_CODES
                or e.errno in (13,)  # EACCES — the bare-PermissionError manifestation
            )
            if not transient:
                raise
            if attempt < retries:
                time.sleep(retry_interval * (0.5 + random.random()))
            continue
        info = _filelock.read_lock(lock)
        if info is None:
            continue  # unlinked between EEXIST and read; retry the create
        if info.get("owner") == owner:
            return lock  # re-entrant — we already hold it
        age = _lock_age_seconds(info)
        if age is not None and age >= ttl_seconds:
            if _filelock.steal_stale(lock, owner, info):
                return lock  # won the value-keyed steal
            continue  # a racer won the steal — retry the normal path
        if attempt < retries:
            # ±50% jitter so N concurrent retriers don't wake in lock-step and
            # thrash the O_EXCL create / steal path (the lock-step thrash that
            # made a 16-way hammer occasionally exhaust the budget).
            time.sleep(retry_interval * (0.5 + random.random()))
    raise TimeoutError(
        f"id-alloc lock busy for scope {scope_key!r} "
        f"(owner={(_filelock.read_lock(lock) or {}).get('owner')})")


def _lock_age_seconds(info: dict) -> float | None:
    """Seconds since the lock's `acquired_at` stamp; None if unparseable (don't steal)."""
    import datetime as _dt
    raw = info.get("acquired_at", "")
    try:
        ts = _dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    except (ValueError, TypeError):
        return None
    return (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds()


def _release(lock: Path, owner: str) -> None:
    """Drop our O_EXCL hold (only if we still own it — never yank a racer's fresh lock).

    Uses `_filelock.unlink_retry` so a racing acquirer holding the lock file open on
    win32 (WinError 5/32/33) doesn't make our `finally`-time release raise — it retries
    briefly, then leaves a genuinely-stuck handle for the TTL steal to reap."""
    info = _filelock.read_lock(lock)
    if info is None:
        return
    if info.get("owner") not in (owner, None):
        return
    _filelock.unlink_retry(lock)


def allocate(
    config: SubstrateConfig,
    scope_key: str,
    *,
    start: int = DEFAULT_START,
    owner: str | None = None,
    retries: int = DEFAULT_RETRIES,
    retry_interval: float = DEFAULT_RETRY_INTERVAL,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> int:
    """Atomically allocate the next never-reused, strictly-monotonic id for ``scope_key``.

    The read→+1→write runs UNDER the per-scope O_EXCL mutex, so two cross-process
    callers serialize: the second reads the first's already-written high-water mark and
    returns a strictly-greater value. Returns the freshly-allocated int.

    * ``start`` — the first id handed out for a never-before-seen scope (default 1). A
      scope that already has a counter ignores ``start`` and continues from its
      high-water mark, so raising/lowering ``start`` later can never regress a live scope.
    * ``owner`` — the lock-body owner string (for debugging a stuck lock); defaults to a
      pid-stamped token. Never affects the value handed out.

    Raises ``TimeoutError`` only if the (tiny) critical section's lock cannot be taken
    within the retry budget — i.e. genuine sustained contention, not the normal race the
    lock exists to serialize.
    """
    if not scope_key:
        raise ValueError("scope_key is required (the opaque series the id belongs to)")
    # The owner string is the mutex's identity. It MUST be unique per concurrent
    # acquisition context — pid ALONE aliases sibling THREADS in one process, which the
    # re-entrancy check (`owner == ours → re-enter`) would then mistake for a recursive
    # hold and let two threads into the critical section together (the duplicate-id bug).
    # pid + thread-id makes every concurrent caller distinct while staying stable for a
    # genuine same-thread re-entry.
    own = owner or f"id-alloc:{os.getpid()}:{threading.get_ident()}"
    counter = _counter_path(config, scope_key)
    lock = _hold(config, scope_key, own,
                 retries=retries, retry_interval=retry_interval, ttl_seconds=ttl_seconds)
    try:
        current = _read_counter(counter)
        nxt = start if current is None else current + 1
        # A never-before-seen scope hands out `start`; an existing scope hands out
        # high-water + 1. Guard: if a caller passes a `start` BELOW an existing mark, the
        # existing mark wins (monotonic invariant — never regress).
        if current is not None and nxt <= current:
            nxt = current + 1
        _write_counter(counter, nxt)
        return nxt
    finally:
        _release(lock, own)


def peek(config: SubstrateConfig, scope_key: str) -> int | None:
    """The current high-water id for ``scope_key`` without allocating (None if never used).

    Lock-free read of an atomically-replaced file — a torn write is impossible (the
    replace is atomic), so this is always either the last fully-written value or None.
    Useful for a host that wants to render "next would be N+1" without claiming it."""
    return _read_counter(_counter_path(config, scope_key))
