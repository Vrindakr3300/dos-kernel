"""Pin the pre-publish leak scanner (`scripts/leak_scan.py`) so the gate cannot
silently fail open.

The scanner is the deterministic floor under the whole fresh-seed publishing
model: CI runs it on every push, and `seed_public_repo.ps1` refuses to cut a
seed while it fails. Twice (the v0.4.0 launch list, then the 2026-06-10 audit)
the gate went stale and leaks re-accumulated unnoticed — a regression in
`scan()` itself would be the same failure one level down, so its load-bearing
behaviors get a test: every vocabulary class fires, the name-regex catches the
case/suffix forms the old literals missed, base64 payload runs do NOT
false-positive it, the EXCLUDE list is honored, and an unreviewed
`docs/reports/` file is flagged.

Two deliberate constructions:
- The scanner is private-side tooling, excluded from the public seed — in the
  seeded tree this whole module self-skips.
- Every forbidden string below is ASSEMBLED at runtime (concatenation), never
  written literally, so this test file — which ships in the public tree — can
  never itself trip the scanner.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCANNER = Path(__file__).resolve().parents[1] / "scripts" / "leak_scan.py"

pytestmark = pytest.mark.skipif(
    not _SCANNER.is_file(),
    reason="leak scanner is private-side tooling, absent from the public seed",
)


def _load_scanner():
    spec = importlib.util.spec_from_file_location("leak_scan", _SCANNER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    return tmp_path


# Forbidden strings, assembled so they never appear literally in this file.
_BS = chr(92)
_DEV_PATH = "C:" + _BS + "work"
_HOME_PATH = "C:/" + "Users"
_NAME_TITLE = "Ca" + "MA"  # the prose form the old literal only knew with "-style"
_NAME_UPPER = "CA" + "MA"  # the script-comment form no literal ever covered
_NAME_SUFFIX = "ca" + "ma" + "-complete"


def _hit_patterns(mod, root: Path, rel: str) -> set[str]:
    return {pat for (r, pat, _why) in mod.scan(root) if r == rel}


def _hit_whys(mod, root: Path, rel: str) -> set[str]:
    return {why for (r, _pat, why) in mod.scan(root) if r == rel}


def test_every_vocabulary_class_fires(tmp_path):
    mod = _load_scanner()
    root = _git_repo(tmp_path)
    planted = "\n".join(
        [
            f"path one {_DEV_PATH}{_BS}sibling",
            f"path two {_HOME_PATH}/someone",
            # The JSON-escaped-inside-JSON depth (4 backslashes) that shipped in
            # agent-run sample logs while the literals only knew depths 1 and 2.
            "path three C:" + _BS * 4 + "Users" + _BS * 4 + "someone",
            f"name a {_NAME_TITLE}-style serving",
            f"name b plain {_NAME_UPPER} mention",
            f"name c {_NAME_SUFFIX}",
        ]
    )
    (root / "notes.md").write_text(planted, encoding="utf-8")

    whys = _hit_whys(mod, root, "notes.md")
    assert any("dev-machine path" in w for w in whys), "dev-path class must fire"
    assert any("home-directory path" in w for w in whys), "home-dir class must fire"
    assert any("serving system" in w for w in whys), "the name regex must fire on standalone forms"


def test_escaping_depth_alone_fires_the_path_classes(tmp_path):
    """Each deeper escaping form was invisible to the literal one level above it
    (the four-backslash form does not contain the two-backslash form as a
    substring) — pin that the regex catches depth 4 on its own."""
    mod = _load_scanner()
    root = _git_repo(tmp_path)
    deep = "C:" + _BS * 4 + "Users" + _BS * 4 + "name"
    (root / "log.jsonl").write_text('{"partial": "' + deep + '"}', encoding="utf-8")
    whys = _hit_whys(mod, root, "log.jsonl")
    assert any("home-directory path" in w for w in whys)


def test_base64_payload_runs_do_not_false_positive_the_name_regex(tmp_path):
    """The four letters inside a longer alphanumeric run (a base64 image payload,
    the paper.html shape) have no word boundary — the regex must stay silent."""
    mod = _load_scanner()
    root = _git_repo(tmp_path)
    payload = "MMfSueqcA" + "MAAAAAAAAAal9JHRyTBiBCLn"  # boundary-free run
    (root / "rendered.txt").write_text(f"data:image;base64,{payload}", encoding="utf-8")
    assert _hit_patterns(mod, root, "rendered.txt") == set()


def test_excluded_files_are_not_scanned(tmp_path):
    mod = _load_scanner()
    root = _git_repo(tmp_path)
    target = root / "scripts" / "leak_scan.py"
    target.parent.mkdir()
    target.write_text(f"forbidden {_DEV_PATH} example", encoding="utf-8")
    assert _hit_patterns(mod, root, "scripts/leak_scan.py") == set()


def test_unreviewed_report_is_flagged_fail_closed(tmp_path):
    mod = _load_scanner()
    root = _git_repo(tmp_path)
    rel = "docs/reports/2099-01-01_some-new-report.md"
    target = root / rel
    target.parent.mkdir(parents=True)
    target.write_text("content with no forbidden string at all", encoding="utf-8")
    pats = _hit_patterns(mod, root, rel)
    assert "<unreviewed report>" in pats


def test_main_exit_codes_are_the_verdict(tmp_path, capsys):
    mod = _load_scanner()
    root = _git_repo(tmp_path)
    (root / "clean.md").write_text("nothing to see", encoding="utf-8")
    assert mod.main([sys.argv[0], str(root)]) == 0
    (root / "dirty.md").write_text(f"oops {_DEV_PATH}", encoding="utf-8")
    assert mod.main([sys.argv[0], str(root)]) == 1
