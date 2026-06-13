"""memory_stores — the memory-store seam: a memory store resolved by NAME (docs/314 P2).

> **The verdict is the kernel's; *where the memories live* is a driver.** The
> recall gate (docs/103) and the write gate (docs/314 P1) adjudicate memory
> BYTES against ground truth. Until this seam they could only read one layout —
> a directory of markdown files. But the memories of real fleets increasingly
> live behind provider APIs (Mem0, Zep, Letta, LangMem), whose headline feature
> is auto-extracting memories from conversation — believing the agent's
> narration by design. This seam lets the same two gates run against ANY store,
> resolved by name at the call boundary. **No provider name appears in this
> module.**

This is the kernel's pure-protocol + by-name-resolver pattern, for the FIFTH
time — after `dos.judges` (the JUDGE rung), `dos.overlap_policy` (the
disjointness scorer), `dos.hook_dialect` (the host-hook renderer), and
`dos.notify` (the delivery side). The shape is identical: a small Protocol +
ONE unshadowable built-in + a by-name resolver; every provider store (which
names a vendor as code — a Mem0 store is inherently Mem0-specific) lives in a
DRIVER and registers through the `dos.memory_stores` entry-point group.

The protocol is deliberately a READ surface
===========================================

A `MemoryStore` answers two questions: *what memories are there* (`list`) and
*what are this one's bytes* (`read`). It cannot write, edit, or delete — the
recall sweep is read-only (docs/103 §6: STALE routes a *proposal*, never an
`rm`), and the write gate adjudicates a candidate BEFORE it enters any store,
so the gate needs no store handle at all. A store that wants to surface a
verdict back into its records (an `annotate` banner) does so in its own
driver, on its own authority — the kernel never mutates a memory store.

Failure direction
=================

A *resolve* of an unknown kind fails LOUD with the known list (a typo'd
`--store-kind` is an operator error, the `resolve_judge` posture — never a
silent degrade that would quietly sweep the wrong store). A *read* that cannot
bind an id raises `ValueError` with the store's own message; the caller maps
it to its usage-error surface. A plugin that fails to LOAD is skipped with a
stderr note (a broken third-party plugin is the operator's to fix, not a
kernel fault — the `_discover_entry_point_judges` posture).

Pure-stdlib. The built-in `file` store reproduces the directory-of-markdown
behavior the recall driver shipped with, byte-identical, so resolving
`("file", <dir>)` is exactly yesterday's sweep.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

# The entry-point group a provider store registers under (the
# `dos.judges`/`dos.notifiers` convention). The kernel imports no occupant.
MEMORY_STORE_ENTRY_POINT_GROUP = "dos.memory_stores"


@runtime_checkable
class MemoryStore(Protocol):
    """What the recall/admit boundary needs from a memory store. READ-ONLY.

    `list()` returns the store's memory ids (a filename, a provider record id —
    opaque to the kernel). `read(id)` returns the memory's BYTES plus a small
    free-form meta mapping (display name, timestamps — advisory; the verdict is
    computed from the bytes, never the meta). A store raises `ValueError` for
    an id it cannot bind ("no memory named …").
    """

    name: str

    def list(self) -> tuple[str, ...]:  # pragma: no cover - protocol signature
        ...

    def read(self, memory_id: str) -> tuple[str, Mapping[str, object]]:  # pragma: no cover
        ...


class FileStore:
    """The ONE unshadowable built-in — a directory of markdown files.

    Byte-identical to the layout the recall driver shipped with (docs/103):
    every `*.md` under the root is a memory, except `MEMORY.md` (the index,
    not a record). `read` accepts a direct file path, an exact filename, or a
    bare slug (`foo` → `foo.md`) — the same resolution `dos memory recall`
    has always done.
    """

    name = "file"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def list(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(sorted(
            p.name for p in self.root.glob("*.md") if p.name != "MEMORY.md"
        ))

    def _resolve(self, memory_id: str) -> Path:
        p = Path(memory_id)
        if p.is_file():
            return p
        cand = self.root / (memory_id if memory_id.endswith(".md") else f"{memory_id}.md")
        if cand.is_file():
            return cand
        raise ValueError(f"no memory named {memory_id!r} under {self.root}")

    def read(self, memory_id: str) -> tuple[str, Mapping[str, object]]:
        p = self._resolve(memory_id)
        # An unreadable file propagates OSError — the caller (the recall
        # boundary) already degrades that to an empty-evidence verdict, the
        # same tolerance `gather()` shipped with.
        text = p.read_text(encoding="utf-8", errors="replace")
        return text, {"id": p.name, "stem": p.stem, "path": str(p)}


# The built-ins, resolved FIRST and unshadowable (the trusted-fallback
# guarantee `resolve_judge`/`resolve_dialect`/`resolve_notifier` give).
_BUILT_IN_KINDS = (FileStore.name,)


def _entry_points(*, _stderr=None):
    """The `dos.memory_stores` entry points, defensively. Discovery I/O."""
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.9+
        return []
    try:
        return list(entry_points(group=MEMORY_STORE_ENTRY_POINT_GROUP))
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        return list(entry_points().get(MEMORY_STORE_ENTRY_POINT_GROUP, []))  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: discovery never crashes a call
        return []


def store_kinds(*, _stderr=None) -> tuple[str, ...]:
    """Every resolvable store kind — built-ins first, then discovered, sorted.

    The list a `--store-kind` error message names. Does entry-point discovery
    (I/O), so it is a call-boundary helper.
    """
    discovered = sorted(
        ep.name for ep in _entry_points(_stderr=_stderr)
        if ep.name not in _BUILT_IN_KINDS
    )
    return _BUILT_IN_KINDS + tuple(discovered)


def resolve_store(kind: str, arg: str = "", *, _stderr=None) -> "MemoryStore":
    """Resolve a memory store by kind: built-ins first, then plugins. Fail LOUD.

    `arg` is the store's one configuration string — the directory for `file`,
    a provider-specific selector (e.g. a user/collection id) for a driver. A
    plugin entry point may expose a class or factory (called with `arg`) or a
    pre-built instance (used as-is; `arg` ignored). The built-in `file` kind
    cannot be shadowed by a plugin claiming the same name.
    """
    if kind == FileStore.name:
        if not arg:
            raise ValueError(
                "the `file` memory store needs its directory as the store arg "
                "(--store <dir>)")
        return FileStore(arg)
    stderr = _stderr if _stderr is not None else sys.stderr
    for ep in _entry_points(_stderr=stderr):
        if ep.name != kind or ep.name in _BUILT_IN_KINDS:
            continue
        try:
            obj = ep.load()
        except Exception as e:
            raise ValueError(f"memory store {kind!r} failed to load: {e}") from e
        # A class/factory is constructed with the arg; an already-built store
        # (it quacks: has list+read and is not a type) is used as-is.
        if not isinstance(obj, type) and hasattr(obj, "list") and hasattr(obj, "read"):
            return obj  # type: ignore[return-value]
        try:
            return obj(arg)  # type: ignore[misc,return-value]
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"memory store {kind!r} failed to construct: {e}") from e
    known = ", ".join(store_kinds(_stderr=stderr))
    raise ValueError(f"unknown memory store kind {kind!r}; known: {known}")
