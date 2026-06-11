"""The llms-full.txt assembly drift gate.

llms-full.txt is generated: the one-fetch expansion of llms.txt, assembled by
`scripts/build_llms_full.py` from the documents the index points at (its
non-Optional repo-file links, in index order). A generated artifact invites the
classic drift — someone edits llms-full.txt directly, or adds a doc to llms.txt
and forgets to rebuild — so this gate pins the one fact that prevents both:
llms-full.txt byte-equals the assembly. The sibling of
`tests/test_readme_assembly.py`, aimed at the agent-facing full-content file.

Source-tree-only: an installed wheel ships neither llms.txt nor the script,
so the whole module skips when they're absent.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BUILD_PY = _REPO / "scripts" / "build_llms_full.py"
_LLMS = _REPO / "llms.txt"
_LLMS_FULL = _REPO / "llms-full.txt"

pytestmark = pytest.mark.skipif(
    not (_BUILD_PY.exists() and _LLMS.exists()),
    reason="llms.txt / build script only exist in the source tree",
)


def _load_builder():
    spec = importlib.util.spec_from_file_location("_build_llms_full", _BUILD_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_llms_full_matches_assembly() -> None:
    """llms-full.txt is byte-identical to the assembly of llms.txt's roster."""
    mod = _load_builder()
    expected = mod.assemble(_REPO)
    actual = _LLMS_FULL.read_text(encoding="utf-8")
    assert actual == expected, (
        "llms-full.txt is out of sync with llms.txt's roster — run: "
        "python scripts/build_llms_full.py"
    )


def test_llms_full_is_spec_shaped() -> None:
    """Opens like llms.txt does: an H1, then the blockquote summary."""
    lines = [line for line in _LLMS_FULL.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[0].startswith("# "), "llms-full.txt must open with an H1"
    assert lines[1].startswith(">"), "the H1 must be followed by the blockquote summary"


def test_roster_covers_the_index() -> None:
    """Every non-Optional repo-file link in llms.txt is inlined exactly once.

    The roster is DERIVED from llms.txt (never a second hand-kept list), so the
    real assertion is that derivation and inlining agree: one source marker per
    rostered path, in index order.
    """
    mod = _load_builder()
    paths = mod.roster(_LLMS.read_text(encoding="utf-8"))
    text = _LLMS_FULL.read_text(encoding="utf-8")
    markers = re.findall(r"<!-- ====== source: (\S+) ====== -->", text)
    assert markers == paths, (
        f"llms-full.txt source markers {markers} do not match llms.txt's roster {paths}"
    )
    assert len(paths) >= 8, "the index roster collapsed — llms.txt should point at the core docs"


def test_no_local_machine_paths() -> None:
    """The route-privacy-at-authoring-time rule, pinned for the full-content file."""
    assert not re.search(r"[A-Za-z]:\\", _LLMS_FULL.read_text(encoding="utf-8")), (
        "llms-full.txt must carry no local absolute path"
    )
