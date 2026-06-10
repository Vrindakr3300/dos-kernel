"""GHF3 — the differential parity gate over the Go hook fast-path (docs/125).

This is the CI ratchet that keeps the native `dos-hook` decider byte-identical to
the Python `dos hook pretool` verb on the gated decision projection (the docs/124
contract). It is the Python side of the cross-engine differential:

  1. it regenerates the hermetic parity corpus from the LIVE Python decider
     (`go/internal/hook/parity/gen_corpus.py`), so the corpus can never drift from
     the Python behavior it claims to mirror; then
  2. it runs `go test` over the same corpus, which replays each case through the
     native decider and asserts byte-equality (`TestParityCorpus`).

If the Go toolchain is absent, the test SKIPS (the gate runs wherever Go is
available — CI installs it; a pure-Python dev box without Go still gets a green
suite, just without this cross-engine check). If `go test` reports a byte drift,
this FAILS loudly with the Go diff.

It also pins the corpus's own self-consistency on the Python side: every case's
`expected_stdout` must reproduce when re-run through the Python decider with the
SAME injected inputs — a tripwire on the Python decider regressing out from under
a stale corpus.

Run: `python -m pytest tests/test_go_hook_parity.py -q`
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GO_DIR = REPO / "go"
PARITY_DIR = GO_DIR / "internal" / "hook" / "parity"
GEN = PARITY_DIR / "gen_corpus.py"
CORPUS = PARITY_DIR / "corpus.jsonl"
GEN_POST = PARITY_DIR / "gen_corpus_posttool.py"
CORPUS_POST = PARITY_DIR / "corpus_posttool.jsonl"


def _have_go() -> bool:
    return shutil.which("go") is not None


def _regen(gen: Path) -> str:
    """Regenerate a corpus from the live Python decider; return its text."""
    out = subprocess.run(
        ["python", str(gen)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


def _regen_corpus() -> str:
    return _regen(GEN)


def test_corpus_regenerates_and_is_self_consistent():
    """The corpus must regenerate deterministically and reproduce the SAME bytes
    as the committed corpus.jsonl (a tripwire on either the Python decider OR the
    generator drifting). Regenerates and compares line-by-line."""
    fresh = _regen_corpus().strip().splitlines()
    committed = CORPUS.read_text(encoding="utf-8").strip().splitlines()
    assert fresh == committed, (
        "the parity corpus is stale — regenerate it with\n"
        f"  python {GEN.relative_to(REPO)} > {CORPUS.relative_to(REPO)}\n"
        "(the Python decider or the generator changed; the corpus must track it)."
    )


def test_posttool_corpus_regenerates_and_is_self_consistent():
    """The stream-stateful posttool corpus must likewise regenerate to the committed
    bytes (the tripwire on the posttool decider / tool_stream fold drifting)."""
    fresh = _regen(GEN_POST).strip().splitlines()
    committed = CORPUS_POST.read_text(encoding="utf-8").strip().splitlines()
    assert fresh == committed, (
        "the posttool parity corpus is stale — regenerate it with\n"
        f"  python {GEN_POST.relative_to(REPO)} > {CORPUS_POST.relative_to(REPO)}\n"
        "(the posttool decider or tool_stream fold changed; the corpus must track it)."
    )


def test_corpus_covers_every_decision_branch():
    """The gate is only as good as its coverage — assert the corpus exercises all
    four decision branches (deny / warn / passthrough) AND the two deny rungs
    (self-modify + disjointness-collision) + the WARN-and-pass branch, so a future
    edit that drops a branch from the corpus is caught."""
    cases = [json.loads(l) for l in CORPUS.read_text(encoding="utf-8").splitlines() if l.strip()]
    tags = {c["decision"] for c in cases}
    assert {"deny", "warn", "passthrough"} <= tags, f"missing decision tags: {tags}"
    names = {c["name"] for c in cases}
    # The load-bearing branches the gate must always cover.
    assert any("selfmodify" in n for n in names), "no self-modify deny case"
    assert any("collision" in n for n in names), "no disjointness-collision deny case"
    assert any("warn" in n for n in names), "no WARN-and-pass case"
    assert any("foreign" in n for n in names), "no foreign-repo (no runtime files) case"


@pytest.mark.skipif(not _have_go(), reason="Go toolchain not installed — cross-engine gate skipped")
def test_go_decider_byte_parity():
    """Run `go test` over the hook decider — this is the cross-engine assertion that
    the native Go decider emits bytes IDENTICAL to the Python decider on every
    corpus case (`TestParityCorpus`) plus the Go unit + pyjson tests."""
    # Ensure the corpora the Go tests will read are the freshly-regenerated ones
    # (both the pretool decision corpus and the stream-stateful posttool corpus).
    # newline="\n": the committed blobs are LF; without it, Windows' text-mode
    # translation rewrites them CRLF and a cold clone's tracked tree turns dirty
    # just from RUNNING the suite (caught by the 2026-06-10 agent-view A/B).
    CORPUS.write_text(_regen_corpus(), encoding="utf-8", newline="\n")
    CORPUS_POST.write_text(_regen(GEN_POST), encoding="utf-8", newline="\n")
    proc = subprocess.run(
        ["go", "test", "./internal/hook/"],
        cwd=str(GO_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "Go hook decider parity/unit tests FAILED — a decision drift between the "
        "native and Python deciders, or a unit regression:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
