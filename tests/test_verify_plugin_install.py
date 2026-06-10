"""The plugin install-integrity verifier — 'is what I installed what git shipped?'

`scripts/verify_plugin_install.py` compares an installed plugin bundle against
`HEAD:claude-plugin`, using git's own blob SHA as the reference (the bytes git
committed, which the installer did not author — the docs/138 forge-resistant
witness, turned on the plugin's own files). This pins its four verdicts:

  * the repo's OWN claude-plugin/ tree verifies clean against HEAD (--self),
  * a STRAY file (installed, not in HEAD) fails,
  * a MODIFIED file (bytes differ from the committed blob) fails,
  * a MISSING file (in HEAD, absent from the install) fails,
  * the gitignored bin/.dos/ runtime debris down-grades to a benign note, not a fail.

Like the script, this lives OUTSIDE the kernel (it checks a distribution surface;
nothing under src/dos/ imports it) — the same one-way arrow as build_plugin.py.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import dos

_REPO_ROOT = Path(dos.__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "verify_plugin_install.py"

_spec = importlib.util.spec_from_file_location("_verify_plugin_install", _SCRIPT)
assert _spec and _spec.loader, f"cannot load {_SCRIPT}"
vpi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vpi)


def _materialize_committed_bundle(dest: Path) -> None:
    """Write HEAD:claude-plugin into dest/ — a clean, byte-faithful 'install'.

    Uses `git archive` so the files are exactly the committed blobs (the thing a
    marketplace CLONE actually ships), giving us a known-good baseline to perturb.
    """
    dest.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", "HEAD", vpi.PLUGIN_PREFIX],
        cwd=str(_REPO_ROOT), capture_output=True, check=True,
    ).stdout
    # git archive prefixes paths with claude-plugin/; strip that one level so dest/
    # is the bundle root (mirrors how the install dir holds bin/, skills/, ... directly).
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = member.name
            prefix = vpi.PLUGIN_PREFIX + "/"
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            assert src is not None
            target.write_bytes(src.read())


def test_self_tree_verifies_clean_against_head():
    """The repo's own claude-plugin/ working tree matches HEAD (modulo benign debris)."""
    report = vpi.verify(_REPO_ROOT / vpi.PLUGIN_PREFIX, _REPO_ROOT)
    assert report["ok"], (
        f"claude-plugin/ diverges from HEAD: missing={report['missing']} "
        f"modified={report['modified']} stray={report['stray']}")
    assert report["matched"] == report["total_committed"] > 0


def test_clean_materialized_bundle_is_ok(tmp_path):
    """A bundle materialized straight from `git archive HEAD` verifies clean."""
    bundle = tmp_path / "install"
    _materialize_committed_bundle(bundle)
    report = vpi.verify(bundle, _REPO_ROOT)
    assert report["ok"], f"a git-archive bundle should be clean: {report}"
    assert not report["stray"] and not report["modified"] and not report["missing"]


def test_stray_file_fails(tmp_path):
    bundle = tmp_path / "install"
    _materialize_committed_bundle(bundle)
    (bundle / "skills" / "INJECTED.md").write_text("not in HEAD", encoding="utf-8")
    report = vpi.verify(bundle, _REPO_ROOT)
    assert not report["ok"]
    assert "skills/INJECTED.md" in report["stray"]


def test_modified_file_fails(tmp_path):
    bundle = tmp_path / "install"
    _materialize_committed_bundle(bundle)
    # Perturb a committed file's bytes — its blob SHA no longer matches HEAD.
    target = bundle / ".mcp.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    report = vpi.verify(bundle, _REPO_ROOT)
    assert not report["ok"]
    assert ".mcp.json" in report["modified"]


def test_missing_file_fails(tmp_path):
    bundle = tmp_path / "install"
    _materialize_committed_bundle(bundle)
    (bundle / ".mcp.json").unlink()
    report = vpi.verify(bundle, _REPO_ROOT)
    assert not report["ok"]
    assert ".mcp.json" in report["missing"]


def test_benign_bin_dos_debris_does_not_fail(tmp_path):
    """The gitignored bin/.dos/ runtime stream debris is a NOTE, not a STRAY fail.

    This is the exact debris a directory-source install carries (the plugin's own
    hook writes it). It won't ship via a marketplace clone, so it must not redden
    an otherwise-faithful install."""
    bundle = tmp_path / "install"
    _materialize_committed_bundle(bundle)
    debris = bundle / "bin" / ".dos" / "streams" / "deadbeef.jsonl"
    debris.parent.mkdir(parents=True, exist_ok=True)
    debris.write_text('{"op":"STEP"}\n', encoding="utf-8")
    report = vpi.verify(bundle, _REPO_ROOT)
    assert report["ok"], f"benign bin/.dos/ debris must not fail: {report}"
    assert "bin/.dos/streams/deadbeef.jsonl" in report["benign_stray"]
    assert not report["stray"]


def test_cli_exit_code_is_the_verdict(tmp_path):
    """Exit 0 on a clean bundle, exit 1 on a divergence — the verdict IS the code."""
    bundle = tmp_path / "install"
    _materialize_committed_bundle(bundle)
    assert vpi.main([str(bundle)]) == 0
    (bundle / "skills" / "INJECTED.md").write_text("stray", encoding="utf-8")
    assert vpi.main([str(bundle)]) == 1
