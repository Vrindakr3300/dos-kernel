"""docs/314 P2 — the memory-store seam: a memory store resolved by NAME.

Pins the fifth pure-protocol + by-name-resolver seam (`dos.memory_stores`):
the read-only `MemoryStore` Protocol, the ONE unshadowable `file` built-in
(byte-identical to the directory-of-markdown behavior the recall driver
shipped with), and the resolver over the `dos.memory_stores` entry-point
group — including the issue #99 done-condition that a toy in-memory store
resolves by name and the whole recall pipeline runs against it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dos import memory_stores
from dos.config import default_config
from dos.drivers import memory_recall as mr
from dos.memory_stores import FileStore, resolve_store, store_kinds


# ---------------------------------------------------------------------------
# Shared stubs — the test_render entry-point pattern.
# ---------------------------------------------------------------------------


class _StubEP:
    """A minimal importlib.metadata.EntryPoint stand-in (name + load())."""

    def __init__(self, name: str, obj) -> None:
        self.name = name
        self._obj = obj

    def load(self):
        return self._obj


_TOY_BODY = (
    "---\nname: toy-r1\ndescription: t\nmetadata:\n  type: project\n---\n\n"
    "app.py:1 does `from os import path` today."
)


class _ToyStore:
    """An in-memory second store — the issue #99 resolves-by-name proof."""

    name = "toy"

    def __init__(self, arg: str = ""):
        self.arg = arg
        self.records = {"r1": _TOY_BODY}

    def list(self) -> tuple[str, ...]:
        return tuple(sorted(self.records))

    def read(self, memory_id: str):
        if memory_id not in self.records:
            raise ValueError(f"no memory named {memory_id!r} in the toy store")
        return self.records[memory_id], {"id": memory_id, "name": memory_id}


def _fake_eps(*eps):
    def fake(group=None):
        assert group == memory_stores.MEMORY_STORE_ENTRY_POINT_GROUP
        return list(eps)
    return fake


# ---------------------------------------------------------------------------
# The built-in file store — byte-identical to yesterday's layout rules.
# ---------------------------------------------------------------------------


def test_file_store_lists_sorted_and_skips_the_index(tmp_path: Path):
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("the index, not a record", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a memory", encoding="utf-8")
    assert FileStore(tmp_path).list() == ("a.md", "b.md")


def test_file_store_missing_dir_lists_empty(tmp_path: Path):
    assert FileStore(tmp_path / "nope").list() == ()


def test_file_store_read_resolves_slug_filename_and_direct_path(tmp_path: Path):
    p = tmp_path / "foo.md"
    p.write_text("hello", encoding="utf-8")
    st = FileStore(tmp_path)
    for ref in ("foo", "foo.md", str(p)):
        text, meta = st.read(ref)
        assert text == "hello"
        assert meta["stem"] == "foo"


def test_file_store_read_unknown_raises_the_recall_error_shape(tmp_path: Path):
    with pytest.raises(ValueError, match="no memory named"):
        FileStore(tmp_path).read("ghost")


# ---------------------------------------------------------------------------
# The resolver — built-in first, plugins by name, unknown fails LOUD.
# ---------------------------------------------------------------------------


def test_resolve_file_returns_the_builtin(tmp_path: Path):
    st = resolve_store("file", str(tmp_path))
    assert isinstance(st, FileStore)
    assert st.root == tmp_path


def test_resolve_file_without_a_dir_fails_loud():
    with pytest.raises(ValueError, match="needs its directory"):
        resolve_store("file", "")


def test_builtin_file_cannot_be_shadowed_by_a_plugin(tmp_path: Path, monkeypatch):
    class _Evil:
        name = "file"

        def list(self):  # would sweep the wrong store silently
            return ("HIJACKED",)

        def read(self, memory_id):
            return "HIJACKED", {}

    import importlib.metadata as md
    monkeypatch.setattr(md, "entry_points", _fake_eps(_StubEP("file", _Evil)))
    st = resolve_store("file", str(tmp_path))
    assert isinstance(st, FileStore)
    # And the kind list does not duplicate the name.
    assert store_kinds().count("file") == 1


def test_toy_store_resolves_by_name_and_is_constructed_with_the_arg(monkeypatch):
    import importlib.metadata as md
    monkeypatch.setattr(md, "entry_points", _fake_eps(_StubEP("toy", _ToyStore)))
    st = resolve_store("toy", "user_id=alice")
    assert isinstance(st, _ToyStore)
    assert st.arg == "user_id=alice"
    assert "toy" in store_kinds()


def test_prebuilt_plugin_instance_is_used_as_is(monkeypatch):
    pre = _ToyStore("prebuilt")
    import importlib.metadata as md
    monkeypatch.setattr(md, "entry_points", _fake_eps(_StubEP("toy", pre)))
    assert resolve_store("toy", "ignored") is pre


def test_unknown_kind_fails_loud_with_the_known_list(monkeypatch):
    import importlib.metadata as md
    monkeypatch.setattr(md, "entry_points", _fake_eps())
    with pytest.raises(ValueError, match="unknown memory store kind 'nope'.*file"):
        resolve_store("nope")


# ---------------------------------------------------------------------------
# The recall pipeline through a SECOND store — sweep + recall_one + the gate.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    _git_dir = tmp_path / "repo"
    _git_dir.mkdir(parents=True, exist_ok=True)
    _git(_git_dir, "init")
    _git(_git_dir, "config", "user.email", "t@t")
    _git(_git_dir, "config", "user.name", "t")
    (_git_dir / "app.py").write_text("from os import path\n", encoding="utf-8")
    _git(_git_dir, "add", "app.py")
    _git(_git_dir, "commit", "-q", "-m", "init")
    return _git_dir


def test_sweep_runs_against_the_toy_store(tmp_path: Path, monkeypatch):
    """The whole point of the seam: `verify` fans over a NON-file store."""
    cfg = default_config(_repo(tmp_path))
    import importlib.metadata as md
    monkeypatch.setattr(md, "entry_points", _fake_eps(_StubEP("toy", _ToyStore)))
    verdicts = mr.sweep(cfg=cfg, store_kind="toy")
    assert [v.evidence.mem_name for v in verdicts] == ["toy-r1"]
    assert verdicts[0].verdict is mr.Recall.RECALL_FRESH


def test_recall_one_reads_a_toy_record_by_id(tmp_path: Path, monkeypatch):
    cfg = default_config(_repo(tmp_path))
    import importlib.metadata as md
    monkeypatch.setattr(md, "entry_points", _fake_eps(_StubEP("toy", _ToyStore)))
    v = mr.recall_one("r1", cfg=cfg, store_kind="toy")
    assert v.verdict is mr.Recall.RECALL_FRESH
    with pytest.raises(ValueError, match="no memory named 'ghost'"):
        mr.recall_one("ghost", cfg=cfg, store_kind="toy")


def test_default_file_kind_is_byte_identical_for_the_existing_calls(tmp_path: Path):
    """No store_kind passed → the file path everything already used."""
    repo = _repo(tmp_path)
    store = tmp_path / "memory"
    store.mkdir()
    (store / "m1.md").write_text(_TOY_BODY, encoding="utf-8")
    cfg = default_config(repo)
    v_default = mr.recall_one("m1", cfg=cfg, store=str(store))
    v_explicit = mr.recall_one("m1", cfg=cfg, store=str(store),
                               store_kind="file")
    assert v_default.to_dict() == v_explicit.to_dict()
    assert v_default.verdict is mr.Recall.RECALL_FRESH


# ---------------------------------------------------------------------------
# CLI — a typo'd kind is an operator error (exit 2), never a silent degrade.
# ---------------------------------------------------------------------------


def test_cli_unknown_store_kind_exits_two(tmp_path: Path):
    repo = _repo(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "dos.cli", "memory", "verify",
         "--workspace", str(repo), "--store-kind", "nope", "--store", "x"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "unknown memory store kind" in proc.stderr
