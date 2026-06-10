"""The atomic id allocator (`dos.id_alloc`) — C6 of the git-issues→DOS audit.

The load-bearing property is the one the host's glob-and-gap-fill `_next_tag` lacks:
two concurrent allocators of one scope must NEVER hand out the same int (the
`TAG_COLLISION_CONCURRENT_SCOPES` zero-pick race). These pin that, plus the
never-reused / strictly-monotonic / per-scope-isolated contract, and the win32
rename-race hardening inherited from `_filelock.atomic_replace`.
"""
from __future__ import annotations

import threading

import pytest

from dos import _filelock, id_alloc
from dos import config as _config


@pytest.fixture
def config(tmp_path, monkeypatch):
    """A config rooted at a throwaway dir; the allocator writes under the pinned
    `id-alloc` dir. The env override makes the counter dir unambiguously inside
    tmp_path (the SubstrateConfig boundary litmus — nothing under the package tree),
    mirroring the `test_lane_lease` cfg fixture."""
    monkeypatch.setenv("DISPATCH_ID_ALLOC_DIR", str(tmp_path / "_idalloc"))
    return _config.default_config(str(tmp_path))


# ── the basic contract ──────────────────────────────────────────────────────


def test_first_allocation_is_start(config):
    assert id_alloc.allocate(config, "next-up-2026-06-03") == 1


def test_custom_start(config):
    assert id_alloc.allocate(config, "series", start=10) == 10
    assert id_alloc.allocate(config, "series", start=10) == 11  # start ignored once seeded


def test_strictly_monotonic(config):
    got = [id_alloc.allocate(config, "s") for _ in range(5)]
    assert got == [1, 2, 3, 4, 5]


def test_scopes_are_isolated(config):
    assert id_alloc.allocate(config, "alpha") == 1
    assert id_alloc.allocate(config, "beta") == 1
    assert id_alloc.allocate(config, "alpha") == 2
    assert id_alloc.allocate(config, "beta") == 2


def test_peek_does_not_allocate(config):
    assert id_alloc.peek(config, "s") is None
    assert id_alloc.allocate(config, "s") == 1
    assert id_alloc.peek(config, "s") == 1
    assert id_alloc.peek(config, "s") == 1  # idempotent — no claim taken
    assert id_alloc.allocate(config, "s") == 2


def test_never_reused_after_simulated_delete(config):
    # The whole point vs glob-and-gap-fill: the counter only ever increases. Even if a
    # host deletes the artifact for id 2, the next allocate is 4, never a reused 2.
    assert [id_alloc.allocate(config, "s") for _ in range(3)] == [1, 2, 3]
    assert id_alloc.allocate(config, "s") == 4  # gap-fill would have returned 2


def test_empty_scope_key_rejected(config):
    with pytest.raises(ValueError):
        id_alloc.allocate(config, "")


def test_distinct_keys_sharing_sanitized_prefix_do_not_collide(config):
    # Two keys that sanitize to the same readable stem must still get distinct counters
    # (the digest disambiguates), or they'd share a high-water mark and collide.
    a = "next up / 2026"          # sanitizes to next-up-2026
    b = "next:up:2026"            # also sanitizes toward next-up-2026
    assert id_alloc.allocate(config, a) == 1
    assert id_alloc.allocate(config, b) == 1  # independent counter, not 2


# ── corruption tolerance ────────────────────────────────────────────────────


def test_corrupt_counter_reads_as_unseeded(config):
    id_alloc.allocate(config, "s")  # seeds the file at 1
    path = id_alloc._counter_path(config, "s")
    path.write_text("not-an-int", encoding="utf-8")
    # A corrupt file reads as None → reseeds from start. The replace-on-write keeps this
    # from ever being a partial int, so this only fires on external tampering.
    assert id_alloc.allocate(config, "s", start=5) == 5


# ── the concurrency regression: two stealers, then the real serialization ───


def test_two_threads_one_scope_no_duplicates(config):
    """Many threads allocating one scope concurrently must yield a contiguous,
    duplicate-free set — the property the host's read-max-then-glob TOCTOU violated."""
    n_threads = 16
    per_thread = 8
    got: list[int] = []
    lock = threading.Lock()

    def worker():
        local = [id_alloc.allocate(config, "hot") for _ in range(per_thread)]
        with lock:
            got.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = n_threads * per_thread
    assert len(got) == total
    assert len(set(got)) == total, "duplicate id handed out — the collision race is back"
    assert sorted(got) == list(range(1, total + 1)), "ids must be a contiguous 1..N run"


def test_stale_lock_is_stolen_not_deadlocked(config):
    """A crashed allocator that left its lock behind must not wedge the scope forever:
    once the lock ages past TTL, the next allocator value-keyed-steals it and proceeds."""
    # Hand-plant a stale lock (old acquired_at) for the scope.
    lock_path = id_alloc._lock_path(config, "s")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        "owner: dead\nacquired_at: 2020-01-01T00:00:00Z\npid: 9\n", encoding="utf-8")
    # With a 0s TTL the stale lock is immediately stealable; allocate must succeed.
    assert id_alloc.allocate(config, "s", ttl_seconds=0) == 1
    # And the stolen lock was released, so a second allocate also proceeds cleanly.
    assert id_alloc.allocate(config, "s", ttl_seconds=0) == 2


def test_timeout_when_lock_held_fresh(config, monkeypatch):
    """If the lock is held by a LIVE owner (fresh stamp) and never releases, allocate
    raises TimeoutError rather than stealing a live lock or hanging."""
    lock_path = id_alloc._lock_path(config, "s")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _filelock.write_lock(lock_path, "live-holder")  # fresh acquired_at == now
    with pytest.raises(TimeoutError):
        id_alloc.allocate(config, "s", retries=2, retry_interval=0.001, ttl_seconds=10_000)


# ── the operator surface (dos id-alloc) ─────────────────────────────────────


def test_cli_allocate_and_peek(tmp_path, monkeypatch, capsys):
    """`dos id-alloc allocate/peek` drives the same allocator end-to-end through the
    workspace seam — peek before any claim is null, allocate increments, peek follows."""
    import json

    from dos import cli

    monkeypatch.setenv("DISPATCH_ID_ALLOC_DIR", str(tmp_path / "_idalloc"))
    # `--workspace` is registered at the `id-alloc` parser level (after the verb name,
    # before the allocate/peek sub-subcommand) — the same placement liveness/gate use.
    ws = ["id-alloc", "--workspace", str(tmp_path)]

    assert cli.main([*ws, "peek", "series"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scope": "series", "id": None}

    assert cli.main([*ws, "allocate", "series"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scope": "series", "id": 1}

    assert cli.main([*ws, "allocate", "series"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scope": "series", "id": 2}

    assert cli.main([*ws, "peek", "series"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scope": "series", "id": 2}
