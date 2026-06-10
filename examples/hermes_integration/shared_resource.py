"""shared_resource — a tiny stand-in for the shared state a Hermes / OpenClaw swarm
fights over (a shared memory document, a task board, an external resource).

It is a JSON "reservations" store with a deliberately RACY read-modify-write: an
agent reads a slot, "thinks" (a short sleep — the window where another agent can
interleave), then writes its booking back. With no coordination, two agents that
both read the slot as free will both write — and the second silently clobbers the
first. That lost update is the bug DOS's arbiter prevents (and the bug the runtimes
punt to the user, having no lock manager).

The store also records a tamper-proof witness: `bookings_log` is an append-only
list of every write that actually landed on disk. The demo counts collisions by
reading THIS (the resource's own state), never an agent's self-report — the
docs/138 invariant (witness != claimant).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path


class Reservations:
    """A racy shared store. One JSON file; read-modify-write with a think-window."""

    def __init__(self, path: str | Path, *, think_seconds: float = 0.05):
        self.path = Path(path)
        self.think_seconds = think_seconds
        # A process-local lock guards only the FILE bytes (so a concurrent write
        # never tears the JSON and crashes the reader). It deliberately does NOT
        # guard the logical read-modify-write — that race (the lost update) is the
        # whole point, and it is exactly what an unsynchronized shared store (a
        # memory doc, a DB row touched without a transaction) exhibits.
        self._io_lock = threading.Lock()
        if not self.path.exists():
            self._write({"slots": {}, "bookings_log": []})

    # -- raw IO (byte-atomic, so no torn reads) --------------------------------
    def _read(self) -> dict:
        with self._io_lock:
            return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, state: dict) -> None:
        # Atomic replace: write a temp file then os.replace it in. The reader sees
        # either the old or the new whole file, never a half-written one.
        with self._io_lock:
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(state, fh, indent=2)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    def _append_booking(self, slot: str, holder: str, observed_free: bool) -> None:
        """Append a booking to the log AND set the slot holder, byte-atomically.

        The log-append is serialized (so no booking record is lost to a torn
        write), but the SLOT value is overwritten by whoever appends last — so two
        agents that both `book` the same slot leave two log entries and the second's
        holder wins, the first's booking lost. That asymmetry is the lost update.
        """
        with self._io_lock:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            state["slots"][slot] = holder
            state["bookings_log"].append(
                {"slot": slot, "holder": holder, "observed_free": observed_free, "ts": _now()}
            )
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(state, fh, indent=2)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    # -- the racy booking operation -------------------------------------------
    def book(self, slot: str, holder: str) -> bool:
        """Book `slot` for `holder` via a read-modify-write with a think-window.

        Returns True if this call OBSERVED the slot as free. WITHOUT external
        coordination this is unsafe: two agents can both read the slot free during
        their think-windows and both write, the second overwriting the first. Every
        write is appended to `bookings_log`, so the log reveals how many writes raced
        onto the same slot — and `lost_updates` counts the overwrites.
        """
        # 1. READ the slot (the stale snapshot the decision is based on).
        current = self._read()["slots"].get(slot)
        observed_free = current is None
        # 2. THINK — the window where a concurrent agent reads the same free slot.
        time.sleep(self.think_seconds)
        # 3. WRITE the booking back, based on the (now possibly stale) read.
        self._append_booking(slot, holder, observed_free)
        return observed_free

    # -- witness ---------------------------------------------------------------
    def lost_updates(self, slot: str) -> int:
        """Count lost updates on `slot`, off `bookings_log` (the resource's own
        state — never an agent's self-report; docs/138 witness != claimant).

        A lost update is a booking whose writer OBSERVED the slot free (so it
        believed it had won the slot) but whose holder is NOT the final holder — its
        write was silently overwritten by a later racer. With N agents racing one
        slot and no coordination, N-1 such bookings are lost. With the arbiter
        serializing, exactly one agent is admitted and books; the rest are refused
        BEFORE they write, so there is one booking and zero lost updates.
        """
        state = self._read()
        final = state["slots"].get(slot)
        writes = [b for b in state["bookings_log"] if b["slot"] == slot]
        # Bookings that thought they won the free slot but aren't the final holder.
        lost = [b for b in writes if b["observed_free"] and b["holder"] != final]
        return len(lost)

    def final_holder(self, slot: str) -> str | None:
        return self._read()["slots"].get(slot)

    def write_count(self, slot: str) -> int:
        return sum(1 for b in self._read()["bookings_log"] if b["slot"] == slot)


def _now() -> float:
    return time.time()


__all__ = ["Reservations"]
