"""docs/314 P3 (issue #99) — the Mem0 occupant of the memory-store seam.

Pins the DRIVER's mapping of Mem0's record shapes into the seam — with a fake
client (the `client=` test seam), so the mapping is tested without the
`[memory-mem0]` extra — plus the lazy-import install hint and the entry-point
registration (`--store-kind mem0` resolves by name; the kernel imports no
provider). The real-SDK smoke (a live Mem0 store in a scratch venv) is the
docs/305 discipline and stays OUTSIDE the kernel suite: it needs a provider
account, which a hermetic suite must not.
"""

from __future__ import annotations

import sys

import pytest

from dos.drivers.memory_mem0 import Mem0Store, _parse_arg


# ---------------------------------------------------------------------------
# The arg grammar — PURE.
# ---------------------------------------------------------------------------


def test_parse_arg_bare_token_is_a_user_id():
    assert _parse_arg("alice") == {"user_id": "alice"}


def test_parse_arg_key_value_pairs():
    assert _parse_arg("user_id=alice,agent_id=bot") == {
        "user_id": "alice", "agent_id": "bot"}


def test_parse_arg_empty_is_no_filters():
    assert _parse_arg("") == {}
    assert _parse_arg("  ,  ") == {}


def test_oss_flag_is_driver_config_not_a_filter():
    st = Mem0Store("oss=1,user_id=alice")
    assert st._use_oss is True
    assert st._filters == {"user_id": "alice"}


# ---------------------------------------------------------------------------
# Record-shape mapping — both wire shapes, via the fake-client seam.
# ---------------------------------------------------------------------------


class _FakeClient:
    """Quacks like MemoryClient: get_all(**filters) + get(id)."""

    def __init__(self, payload, single=None):
        self.payload = payload
        self.single = single or {}
        self.calls: list = []

    def get_all(self, **filters):
        self.calls.append(filters)
        return self.payload

    def get(self, memory_id):
        return self.single.get(memory_id)


_REC = {"id": "m-1", "memory": "the agent prefers short words",
        "user_id": "alice", "created_at": "2026-06-12T00:00:00Z",
        "metadata": {"k": "v"}}


def test_list_maps_the_hosted_bare_list_shape():
    st = Mem0Store("user_id=alice", client=_FakeClient([_REC, {"id": 7}]))
    assert st.list() == ("m-1", "7")
    assert st._client.calls == [{"user_id": "alice"}]


def test_list_maps_the_oss_results_wrapper_shape():
    st = Mem0Store(client=_FakeClient({"results": [_REC]}))
    assert st.list() == ("m-1",)


def test_list_tolerates_garbage_payloads():
    assert Mem0Store(client=_FakeClient(None)).list() == ()
    assert Mem0Store(client=_FakeClient("nonsense")).list() == ()
    assert Mem0Store(client=_FakeClient([{"no_id": 1}, "junk"])).list() == ()


def test_read_returns_text_and_meta():
    st = Mem0Store(client=_FakeClient([], single={"m-1": _REC}))
    text, meta = st.read("m-1")
    assert text == "the agent prefers short words"
    assert meta["id"] == "m-1"
    assert meta["user_id"] == "alice"
    assert meta["metadata"] == {"k": "v"}


def test_read_unwraps_a_single_results_envelope():
    st = Mem0Store(client=_FakeClient([], single={"m-1": {"results": _REC}}))
    text, _ = st.read("m-1")
    assert text == "the agent prefers short words"


def test_read_missing_or_textless_record_raises():
    st = Mem0Store(client=_FakeClient([], single={"m-2": {"id": "m-2", "memory": ""}}))
    with pytest.raises(ValueError, match="no memory named 'm-1'"):
        st.read("m-1")
    with pytest.raises(ValueError, match="no memory named 'm-2'"):
        st.read("m-2")


# ---------------------------------------------------------------------------
# The vendor boundary — lazy import, install hint, no kernel involvement.
# ---------------------------------------------------------------------------


def test_missing_sdk_fails_with_the_install_hint(monkeypatch):
    """`sys.modules['mem0'] = None` makes `from mem0 import …` raise ImportError
    even when the extra IS installed — the absent-extra path, deterministically."""
    monkeypatch.setitem(sys.modules, "mem0", None)
    with pytest.raises(ValueError, match=r"dos-kernel\[memory-mem0\]"):
        Mem0Store("alice").list()


def test_mem0_resolves_by_name_through_the_entry_point():
    """`--store-kind mem0` discovers the driver; the seam names no vendor.

    Reads the installed dist metadata (like the gemini-dialect pin) — a stale
    editable install that predates the `dos.memory_stores` group needs a
    `pip install -e .` refresh.
    """
    from dos.memory_stores import resolve_store
    st = resolve_store("mem0", "user_id=alice")
    assert isinstance(st, Mem0Store)
    assert st._filters == {"user_id": "alice"}


def test_the_kernel_seam_imports_no_vendor():
    """The grep litmus, applied to the new seam module: the kernel seam may
    EXPLAIN the provider landscape in prose (notify.py names Slack the same
    way) but must never import or construct a provider as CODE — every
    `import mem0` lives in the driver."""
    import ast
    from pathlib import Path

    import dos.memory_stores as seam
    tree = ast.parse(Path(seam.__file__).read_text(encoding="utf-8"))
    vendors = {"mem0", "mem0ai", "zep", "letta", "langmem"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods = {(node.module or "").split(".")[0]}
        else:
            continue
        hit = mods & vendors
        assert not hit, f"kernel seam imports a vendor: {hit}"
