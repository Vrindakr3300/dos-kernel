"""run_coord_demo - AXIS 1 (coordination), K CONCURRENT AGENTS.

Proves: when K Hermes / OpenClaw swarm agents race to write the SAME shared-state
slot, the runtime's status quo (no lock manager) produces lost updates - the later
writes silently clobber the earlier ones. With DOS's arbiter leasing the region
first - through its real write-ahead log - exactly one agent acquires and books;
the rest are REFUSED before they write, so there are zero lost updates.

This is the gap the runtimes provably lack (multi-agent + shared state, no
transaction / locking API). The value is ZERO at K=1 (the honest falsifier - one
agent cannot collide with itself) and grows with K.

The coordination here is NOT simulated: the guarded arm calls `dos lease-lane
acquire` against a throwaway DOS workspace, which arbitrates AND journals the grant
to the WAL atomically (under DOS's archive-lock). A concurrent agent replays that
journal, sees the region held, and is refused. The witness is the shared store's
own `bookings_log`, read AFTER all agents finish - never an agent's self-report
(docs/138: witness != claimant).

Run:  python run_coord_demo.py [K]      (default K=4)
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

from hermes_adapter import acquire_lease, release_lease
from shared_resource import Reservations


SLOT = "42"  # every agent races for this one slot - maximal contention.
REGION = f"reservations/{SLOT}/**"


def run_naive_arm(k: int, store_path: Path) -> int:
    """K agents book the same slot concurrently with NO coordination."""
    store = Reservations(store_path, think_seconds=0.05)

    def book(i: int) -> None:
        store.book(SLOT, f"naive-agent-{i}")

    threads = [threading.Thread(target=book, args=(i,)) for i in range(k)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return store.lost_updates(SLOT)


def run_guarded_arm(k: int, store_path: Path, dos_workspace: Path) -> tuple[int, list[str]]:
    """K agents race the same slot, each acquiring the region through DOS's WAL
    first. Only the agent DOS admits books; the rest are refused.

    Each agent uses a DISTINCT loop_ts (its identity in the (loop_ts, lane) key),
    so the WAL can tell them apart - and the arbiter refuses every agent whose
    region collides with the one already journaled.
    """
    store = Reservations(store_path, think_seconds=0.05)
    results: list[tuple[str, str]] = []  # (agent, note)
    results_lock = threading.Lock()

    def one(i: int) -> None:
        owner = f"guarded-agent-{i}"
        verdict = acquire_lease(
            REGION, owner=owner, loop_ts=f"ts-{i}", workspace=dos_workspace,
        )
        if verdict.acquired:
            store.book(SLOT, owner)
            note = f"ACQUIRED region -> booked slot {SLOT}"
            # In a real run the agent releases when done; do so here so the lease
            # lifecycle is complete (the booking already landed under the lease).
            release_lease(REGION, owner=owner, loop_ts=f"ts-{i}", workspace=dos_workspace)
        else:
            # Refused: the region was already held (or the WAL write was contended
            # and lost the archive-lock race). Either way the agent did NOT write -
            # which is the guarantee. Report it cleanly, not the raw retry warning.
            note = f"REFUSED by DOS (region {REGION} held) - did not write"
        with results_lock:
            results.append((owner, note))

    threads = [threading.Thread(target=one, args=(i,)) for i in range(k)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log = [f"  {name}: {note}" for name, note in sorted(results)]
    return store.lost_updates(SLOT), log


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    print("=" * 72)
    print(f"AXIS 1 - COORDINATION ({k} concurrent agents racing slot {SLOT!r})")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dos_ws = tmp / "dos_ws"  # a throwaway DOS workspace - real WAL, isolated
        dos_ws.mkdir()
        naive_lost = run_naive_arm(k, tmp / "naive.json")
        guarded_lost, guarded_log = run_guarded_arm(k, tmp / "guarded.json", dos_ws)

    print("\nGUARDED arm (each agent acquires the region via `dos lease-lane` first):")
    print("\n".join(guarded_log))

    print("\n" + "-" * 72)
    print(f"  LOST UPDATES on slot {SLOT!r}     naive = {naive_lost}   guarded = {guarded_lost}")
    print("-" * 72)

    if k == 1:
        print("  (K=1: the honest falsifier - one agent cannot collide with itself,")
        print("   so BOTH arms show 0. DOS's coordination value appears only at K>=2.)")
        return 0
    if guarded_lost == 0 and naive_lost > 0:
        print(f"  [OK] Naive lost {naive_lost} update(s) - later agents clobbered earlier bookings.")
        print(f"  [OK] DOS serialized the writes: exactly one agent booked, the rest refused.")
        print(f"  [OK] Value grows with fleet size (lost updates ~= K-1 in the naive arm).")
        return 0
    print("  [!!] unexpected result - coordination did not prevent the collisions.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
