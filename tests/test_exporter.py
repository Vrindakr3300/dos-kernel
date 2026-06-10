"""The verdict-exporter seam (`dos.exporter`) + the `file` driver — pure, no network (docs/266).

Covers Phase 1:

* the kernel seam — the `null` built-in (unshadowable, resolves first), the by-name
  resolver (unknown fails LOUD), `export_safely`'s fail-soft contract (any raise → a
  non-exported result, never propagated), the `_max_seq_cursor` helper, and the
  `_accepted_kwargs` superset-filter;
* the `file` DRIVER — a fake-path round-trip ships N events as N JSONL lines (the
  journal's own line shape), `--dry-run` + no-path ship nothing, a non-serializable
  field degrades cleanly, a relative path resolves against `root`;
* the structural litmus — `exporter.py` names no transport in code.

The seam mirrors `notify.py` byte-for-byte; these tests mirror `test_notify.py` +
`test_notify_webhook.py`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from dos import exporter
from dos.exporter import (
    EXPORTER_ENTRY_POINT_GROUP,
    ExportResult,
    Exporter,
    NullExporter,
    _accepted_kwargs,
    _max_seq_cursor,
    active_exporter_names,
    export_safely,
    resolve_exporter,
)
from dos.drivers.export_file import FileExporter, resolve_path
from dos.verdict_journal import VerdictEvent


# ---------------------------------------------------------------------------
# A few real VerdictEvents — the exporter's payload is the journal's own type.
# ---------------------------------------------------------------------------


def _ev(syscall: str, verdict: str, *, seq: int = 0, run_id: str = "", detail=None) -> VerdictEvent:
    return VerdictEvent(
        syscall=syscall, verdict=verdict, run_id=run_id, seq=seq,
        detail=detail or {}, ts="2026-06-09T00:00:00Z",
    )


_BATCH = [
    _ev("liveness", "STALLED", seq=1, run_id="RID-a", detail={"idle_s": 600}),
    _ev("efficiency", "WASTEFUL", seq=2, run_id="RID-a", detail={"work": 0, "tokens": 5000}),
    _ev("verify", "SHIPPED", seq=3, run_id="RID-b"),
]


# =====================================================================================
# 1. the seam — null built-in, resolver, fail-soft, cursor, kwarg filter
# =====================================================================================


def test_null_is_the_unshadowable_built_in():
    """`null` resolves with no plugins, ships nothing, and is the default baseline."""
    ex = resolve_exporter("null")
    assert isinstance(ex, NullExporter)
    assert ex.name == "null"
    res = ex.export(_BATCH)
    assert isinstance(res, ExportResult)
    assert res.exported == 0
    assert "null sink" in res.detail
    # null still reports the cursor (the highest seq) so a --since drain can advance.
    assert res.cursor == "3"


def test_null_in_active_names_first():
    names = active_exporter_names()
    assert names and names[0] == "null"


def test_resolve_unknown_fails_loud():
    """A typo'd transport is an operator error — raises with the known list, never a
    silent degrade to null (which would drop every event quietly)."""
    with pytest.raises(ValueError) as ei:
        resolve_exporter("nope")
    msg = str(ei.value)
    assert "unknown exporter 'nope'" in msg
    assert "null" in msg  # the known list is surfaced


def test_export_safely_converts_a_raise_to_a_non_exported_result():
    """The fail-soft floor: observability must not crash the observed. A transport that
    raises becomes ExportResult(exported=0, detail='error: …'), never an exception."""

    class _Boom:
        name = "boom"

        def export(self, events):
            raise RuntimeError("collector down")

    res = export_safely(_Boom(), _BATCH)
    assert res.exported == 0
    assert "error:" in res.detail
    assert "collector down" in res.detail


def test_export_safely_rejects_a_non_result_shape():
    """A misbehaving occupant that returns a non-ExportResult is treated as a soft
    failure rather than trusting an unknown shape downstream."""

    class _Liar:
        name = "liar"

        def export(self, events):
            return {"exported": 999}  # not an ExportResult

    res = export_safely(_Liar(), _BATCH)
    assert res.exported == 0
    assert "non-ExportResult" in res.detail


def test_export_safely_passes_a_clean_result_through():
    class _Good:
        name = "good"

        def export(self, events):
            return ExportResult(exported=len(events), detail="ok", cursor="3")

    res = export_safely(_Good(), _BATCH)
    assert res.exported == 3 and res.detail == "ok" and res.cursor == "3"


def test_max_seq_cursor():
    assert _max_seq_cursor(_BATCH) == "3"
    assert _max_seq_cursor([]) == ""           # empty batch → "" (no advance)
    assert _max_seq_cursor([_ev("x", "Y", seq=0)]) == "0"
    # robust to a non-int seq (degrades to 0, never raises)
    bad = VerdictEvent(syscall="x", verdict="Y")
    object.__setattr__(bad, "seq", "not-an-int")
    assert _max_seq_cursor([bad]) == "0"


def test_accepted_kwargs_filters_to_constructor_params():
    """The CLI hands one superset bag; resolve filters it to each constructor's params
    so `file` is never handed a `host`/`port` it doesn't declare."""
    bag = {"path": "/p", "host": "h", "port": 8125, "endpoint": "e",
           "dry_run": True, "root": "/r", "bogus": 1}
    accepted = _accepted_kwargs(FileExporter, bag)
    assert set(accepted) == {"path", "dry_run", "root"}


def test_exporter_protocol_runtime_checkable():
    assert isinstance(NullExporter(), Exporter)
    assert isinstance(FileExporter(), Exporter)


def test_entry_point_group_name():
    assert EXPORTER_ENTRY_POINT_GROUP == "dos.exporters"


# =====================================================================================
# 2. the file driver — round-trip, dry-run, no-path, non-serializable, relative path
# =====================================================================================


def test_file_round_trip_ships_n_events_as_n_jsonl_lines(tmp_path):
    """The keystone: N events → N JSONL lines at the path, each the event's own
    to_record() (the journal's line shape, so a downstream parser needs no new schema)."""
    out = tmp_path / "verdicts.jsonl"
    ex = FileExporter(path=str(out))
    res = ex.export(_BATCH)
    assert res.exported == 3
    assert str(out) in res.detail
    assert res.cursor == "3"

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    recs = [json.loads(l) for l in lines]
    # each line is the verdict-journal record shape (schema-tagged, byte-clean detail)
    assert recs[0]["syscall"] == "liveness" and recs[0]["verdict"] == "STALLED"
    assert recs[0]["detail"] == {"idle_s": 600}
    assert recs[0]["schema_family"] == "verdict-journal"
    assert recs[2]["run_id"] == "RID-b"


def test_file_appends_across_two_drains(tmp_path):
    """Two drains append (don't truncate) — a follow loop accretes lines."""
    out = tmp_path / "v.jsonl"
    FileExporter(path=str(out)).export(_BATCH[:1])
    FileExporter(path=str(out)).export(_BATCH[1:])
    assert len(out.read_text(encoding="utf-8").splitlines()) == 3


def test_file_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "v.jsonl"
    res = FileExporter(path=str(out), dry_run=True).export(_BATCH)
    assert res.exported == 0
    assert "[dry-run]" in res.detail
    assert "would append 3" in res.detail
    assert not out.exists()
    assert res.cursor == "3"  # cursor still advances under dry-run


def test_file_no_path_is_a_non_exported_result(tmp_path, monkeypatch):
    """No --path, no $DOS_EXPORT_FILE, no .env key → fail-soft non-exported result."""
    monkeypatch.delenv("DOS_EXPORT_FILE", raising=False)
    res = FileExporter(path="", root=tmp_path).export(_BATCH)
    assert res.exported == 0
    assert "no export path" in res.detail


def test_file_empty_batch_is_a_clean_noop(tmp_path):
    out = tmp_path / "v.jsonl"
    res = FileExporter(path=str(out)).export([])
    assert res.exported == 0
    assert "no new events" in res.detail
    assert not out.exists()  # nothing written for an empty batch


def test_file_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "deep" / "v.jsonl"
    res = FileExporter(path=str(out)).export(_BATCH)
    assert res.exported == 3
    assert out.exists()


def test_file_non_serializable_field_degrades_cleanly(tmp_path):
    """A detail value json can't encode fails the whole batch fail-soft (no partial
    write + raise) — the to_record() builds the dict but json.dumps on a set raises."""
    out = tmp_path / "v.jsonl"
    bad = VerdictEvent(syscall="x", verdict="Y", seq=1, detail={"bad": {1, 2, 3}})
    res = FileExporter(path=str(out)).export([bad])
    assert res.exported == 0
    assert "not serializable" in res.detail
    assert not out.exists()


def test_file_relative_path_resolves_against_root(tmp_path, monkeypatch):
    """A relative --path lands under the workspace root, not the drain's cwd."""
    monkeypatch.delenv("DOS_EXPORT_FILE", raising=False)
    resolved = resolve_path("verdicts.jsonl", root=tmp_path)
    assert Path(resolved) == tmp_path / "verdicts.jsonl"
    # and an absolute path is left alone
    abs_p = tmp_path / "abs.jsonl"
    assert resolve_path(str(abs_p), root=tmp_path) == str(abs_p)


def test_file_path_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DOS_EXPORT_FILE", str(tmp_path / "fromenv.jsonl"))
    assert resolve_path("", root=tmp_path) == str(tmp_path / "fromenv.jsonl")
    # explicit arg wins over env
    monkeypatch.setenv("DOS_EXPORT_FILE", str(tmp_path / "fromenv.jsonl"))
    assert resolve_path(str(tmp_path / "explicit.jsonl"), root=tmp_path) == str(
        tmp_path / "explicit.jsonl")


def test_file_dotenv_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("DOS_EXPORT_FILE", raising=False)
    (tmp_path / ".env").write_text('DOS_EXPORT_FILE="env-file.jsonl"\n', encoding="utf-8")
    assert resolve_path("", root=tmp_path) == str(tmp_path / "env-file.jsonl")


def test_file_resolvable_by_name_via_entry_point():
    """`resolve_exporter("file")` finds the driver by name through the dos.exporters
    entry-point group (proves the pyproject registration + editable install)."""
    ex = resolve_exporter("file", path="/tmp/x.jsonl", host="ignored", port=9999)
    assert isinstance(ex, FileExporter)
    assert ex.name == "file"


def test_file_in_active_names():
    assert "file" in active_exporter_names()


# =====================================================================================
# 3. structural litmus — the kernel seam names no transport in code
# =====================================================================================


def test_exporter_module_names_no_transport_in_code():
    """`exporter.py` is the kernel seam — it must name no transport (file/statsd/otlp/
    datadog/…) as a code identifier or string compare; those live only in drivers +
    pyproject. (The vendor-agnostic litmus, applied to the transport axis.)"""
    src = Path(exporter.__file__)
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    transports = {"statsd", "otlp", "datadog", "grafana", "loki", "honeycomb",
                  "opentelemetry", "fluent", "vector", "promtail", "splunk"}
    # identifiers used as code (Names + Attributes) — NOT docstrings/comments, where
    # these names legitimately appear as illustrative prose.
    code_ids: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            code_ids.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            code_ids.add(node.attr.lower())
    leaked = {t for t in transports if t in code_ids}
    assert not leaked, f"exporter.py names a transport in code: {leaked}"
    # and no string-literal compare against a transport name (a future `if to=='otlp'`)
    bad_compares: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op in [node.left, *node.comparators]:
                if isinstance(op, ast.Constant) and isinstance(op.value, str):
                    if op.value.lower() in transports:
                        bad_compares.append(op.value)
    assert not bad_compares, f"exporter.py compares to a transport literal: {bad_compares}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
