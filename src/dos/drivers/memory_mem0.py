"""dos.drivers.memory_mem0 — the Mem0 occupant of the memory-store seam (docs/314 P3).

The first provider driver behind `dos.memory_stores` (issue #99). Mem0's
headline feature is AUTO-EXTRACTING memories from conversation — the writer
believes the agent's narration by design — which is exactly the poison the
recall gate (docs/103) and the write gate (docs/314 P1, `dos memory admit`)
adjudicate. This driver maps Mem0's record shape into the seam so both gates
run against a hosted store:

    dos memory verify --store-kind mem0 --store user_id=alice   # sweep for stale claims
    dos memory recall <record-id> --store-kind mem0             # one record's verdict

and the admit gate needs no store at all — a Mem0 writer pipes the candidate
bytes through `dos memory admit` BEFORE calling the provider's add-memory API.

Kernel/driver split (the `notify_slack` precedent): this module names its
vendor as code — `from mem0 import …` — which the vendor-blindness litmus
forbids in a kernel module, so it lives HERE and registers through the
`dos.memory_stores` entry-point group in pyproject. The SDK import is LAZY
(inside the client builder, never at module load), so entry-point discovery of
this driver never fails when the `[memory-mem0]` extra is absent — it
resolves, and reports the install hint only when a read is attempted.

The store ARG grammar
=====================

`--store` carries one comma-separated selector string:

    user_id=alice                  # the common case (also the bare-token default)
    user_id=alice,agent_id=bot     # any provider filter keys, passed to get_all
    oss=1,user_id=alice            # use the local OSS `Memory` instead of the
                                   # hosted `MemoryClient` (which reads MEM0_API_KEY)

Read-only, like every seam occupant: this driver lists and reads records; it
never writes, edits, or deletes a memory (the kernel adjudicates — what to do
with a STALE/POISON verdict stays the host's call).
"""

from __future__ import annotations

from typing import Mapping

_INSTALL_HINT = (
    "the Mem0 memory-store driver needs the `mem0ai` package — "
    "pip install 'dos-kernel[memory-mem0]' (or: pip install mem0ai)"
)

# Arg keys that configure the DRIVER rather than filter the provider query.
_DRIVER_KEYS = frozenset({"oss"})


def _parse_arg(arg: str) -> dict[str, str]:
    """`user_id=alice,agent_id=bot` → {…}; a bare token → {'user_id': token}. PURE."""
    out: dict[str, str] = {}
    for part in (arg or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, _, v = part.partition("=")
            k, v = k.strip(), v.strip()
            if k:
                out[k] = v
        else:
            out.setdefault("user_id", part)
    return out


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


class Mem0Store:
    """A read-only `dos.memory_stores.MemoryStore` over a Mem0 memory store.

    `client` is the test seam: a pre-built client (anything with `get_all` /
    `get`) skips the SDK import entirely, so the mapping is testable without
    the extra installed — and a custom-configured OSS `Memory` can be injected
    by a host that builds its own.
    """

    name = "mem0"

    def __init__(self, arg: str = "", client=None):
        parsed = _parse_arg(arg)
        self._use_oss = _truthy(parsed.get("oss", ""))
        self._filters = {k: v for k, v in parsed.items() if k not in _DRIVER_KEYS}
        self._client = client

    # -- the vendor boundary: lazy, fail-with-hint --------------------------
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if self._use_oss:
            try:
                from mem0 import Memory  # type: ignore[import-not-found]
            except ImportError as e:
                raise ValueError(_INSTALL_HINT) from e
            try:
                self._client = Memory()
            except Exception as e:
                raise ValueError(f"mem0 OSS client failed to initialize: {e}") from e
            return self._client
        try:
            from mem0 import MemoryClient  # type: ignore[import-not-found]
        except ImportError as e:
            raise ValueError(_INSTALL_HINT) from e
        try:
            # Reads MEM0_API_KEY from the environment — the SDK's own contract;
            # this driver never handles a credential itself.
            self._client = MemoryClient()
        except Exception as e:
            raise ValueError(
                f"mem0 hosted client failed to initialize (is MEM0_API_KEY set?): {e}"
            ) from e
        return self._client

    # -- record-shape tolerance ----------------------------------------------
    @staticmethod
    def _records(payload) -> list[Mapping]:
        """Both wire shapes: a bare list (hosted v1) and {'results': […]} (OSS v1.1+)."""
        if isinstance(payload, Mapping):
            payload = payload.get("results") or []
        if not isinstance(payload, (list, tuple)):
            return []
        return [r for r in payload if isinstance(r, Mapping)]

    @staticmethod
    def _text_of(rec: Mapping) -> str:
        return str(rec.get("memory") or rec.get("text") or "")

    # -- the seam ------------------------------------------------------------
    def list(self) -> tuple[str, ...]:
        recs = self._records(self._ensure_client().get_all(**self._filters))
        return tuple(str(r["id"]) for r in recs if r.get("id") is not None)

    def read(self, memory_id: str) -> tuple[str, Mapping[str, object]]:
        try:
            rec = self._ensure_client().get(memory_id)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(
                f"no memory named {memory_id!r} in the mem0 store ({e})") from e
        if isinstance(rec, Mapping) and isinstance(rec.get("results"), Mapping):
            rec = rec["results"]  # some OSS versions wrap a single get too
        if not isinstance(rec, Mapping) or not self._text_of(rec):
            raise ValueError(f"no memory named {memory_id!r} in the mem0 store")
        meta: dict[str, object] = {
            "id": str(rec.get("id") or memory_id),
            "name": str(rec.get("id") or memory_id),
        }
        for k in ("user_id", "agent_id", "run_id", "created_at", "updated_at"):
            if rec.get(k) is not None:
                meta[k] = rec[k]
        if isinstance(rec.get("metadata"), Mapping):
            meta["metadata"] = dict(rec["metadata"])
        return self._text_of(rec), meta
