"""Guard: each per-platform wheel carries EXACTLY ONE binary, of the RIGHT format (docs/286).

This pins the fix for the `build/` staging-dir leak — the bug where `python -m build`
re-used setuptools' `build/lib/dos/_bin/` across arches and swept a PRIOR arch's binary
into the NEXT wheel (a macOS Mach-O shipped inside the Windows wheel). The invariant:

  * a `py3-none-<platform>` wheel holds EXACTLY ONE `dos/_bin/dos-hook[.exe]`, and
  * that binary's magic bytes match the platform tag (PE for win, ELF for manylinux,
    Mach-O for macosx).

It actually RUNS `scripts/build_wheels.py` for two cross-compiled arches (one Windows,
one Linux — distinct binary formats AND distinct names, the exact pair that exposed the
leak) and inspects the produced bytes. The build-script "OK" message is not proof; the
bytes are. Skips cleanly when the Go toolchain is absent (CI legs without Go), the same
discipline as `test_go_hook_parity.py`.

Slow-ish (two `go build` + two `python -m build`), so it is a single combined test.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import dos

_REPO_ROOT = Path(dos.__file__).resolve().parents[2]
_BUILD_WHEELS = _REPO_ROOT / "scripts" / "build_wheels.py"

# One Windows arch + one Linux arch: distinct magic bytes (PE vs ELF) AND distinct
# in-package names (dos-hook.exe vs dos-hook) — the pair that surfaced the leak.
_ARCHES = ["windows/amd64", "linux/amd64"]

_MAGIC = {
    "PE": lambda h: h[:2] == b"MZ",
    "ELF": lambda h: h[:4] == b"\x7fELF",
    "MachO": lambda h: h[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"),
}


def _have_go() -> bool:
    return shutil.which("go") is not None


def _expected_format(platform_tag: str) -> str:
    if "win" in platform_tag:
        return "PE"
    if "manylinux" in platform_tag:
        return "ELF"
    if "macosx" in platform_tag:
        return "MachO"
    raise AssertionError(f"unmapped platform tag {platform_tag!r}")


@pytest.mark.skipif(not _have_go(), reason="Go toolchain not installed — wheel-build gate skipped")
@pytest.mark.skipif(
    os.environ.get("DOS_TEST_BUILD_WHEELS") != "1",
    reason="opt-in: runs `python -m build` in the shared repo root (set DOS_TEST_BUILD_WHEELS=1). "
           "Skipped by default — it shares dist/+build/ with any concurrent build, so it is "
           "flaky on a multi-session-hot tree / under xdist; CI's dedicated build job exercises "
           "build_wheels.py for real on a clean checkout.",
)
def test_each_wheel_has_exactly_one_correctly_formatted_binary():
    """Build two cross-arch wheels and assert each holds one binary of the right format.

    Opt-in (DOS_TEST_BUILD_WHEELS=1) because it runs `python -m build` against the shared
    repo dist/+build/, which a concurrent build (a peer session, or an xdist worker)
    clobbers mid-run. On a clean, single-builder checkout it is deterministic — which is
    exactly the CI build-job environment, where it is the regression guard for the
    build/ staging leak (a macOS binary that shipped inside the Windows wheel)."""
    bw = _load(_BUILD_WHEELS)
    version = subprocess.run(
        [sys.executable, "-c", "import dos; print(dos.__version__)"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, check=True,
    ).stdout.strip()
    dist = _REPO_ROOT / "dist"
    # The EXACT wheel each arch should produce (robust against leftover dist/ state — we
    # name the targets up front and assert on them, never on a set-diff that a crashed
    # prior run can poison).
    expected = {
        spec: dist / f"dos_kernel-{version}-py3-none-{bw._PLATFORM_TAGS[spec]}.whl"
        for spec in _ARCHES
    }

    def _unlink_resilient(p: Path) -> None:
        # A freshly-built .exe on Windows can be transiently locked (AV scan, lingering
        # handle); retry briefly so teardown is not flaky. A leftover is harmless (the
        # _bin binary is gitignored), so never fail the test on a cleanup lock.
        import time
        for _ in range(5):
            try:
                p.unlink(missing_ok=True)
                return
            except PermissionError:
                time.sleep(0.2)

    def _cleanup() -> None:
        for w in expected.values():
            _unlink_resilient(w)
        shutil.rmtree(_REPO_ROOT / "build", ignore_errors=True)
        for name in ("dos-hook", "dos-hook.exe"):
            _unlink_resilient(_REPO_ROOT / "src" / "dos" / "_bin" / name)

    _cleanup()  # start from a known-clean slate (drop any crashed-run leftovers)
    try:
        proc = subprocess.run(
            [sys.executable, str(_BUILD_WHEELS), "--no-sdist", "--arches", *_ARCHES],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"build_wheels.py failed:\n{proc.stdout}\n{proc.stderr}"
        for spec, wheel in expected.items():
            assert wheel.is_file(), f"{spec} did not produce {wheel.name}\n{proc.stdout}"
            tag = bw._PLATFORM_TAGS[spec]
            with zipfile.ZipFile(wheel) as z:  # close before unlink (Windows file lock)
                bins = [n for n in z.namelist() if "_bin/dos-hook" in n]
                head = z.read(bins[0])[:4] if bins else b""
            assert len(bins) == 1, (
                f"{wheel.name} must hold EXACTLY ONE binary, holds {bins} "
                f"(the build/ staging leak regressed — see docs/286)"
            )
            want = _expected_format(tag)
            assert _MAGIC[want](head), (
                f"{wheel.name} (tag {tag}) carries a {head.hex()} binary, expected {want} "
                f"magic — the wrong arch's binary leaked into this wheel"
            )
            # The Windows wheel's one binary must be the .exe; POSIX the bare name.
            want_name = "dos-hook.exe" if "win" in tag else "dos-hook"
            assert bins[0].endswith(want_name), f"{wheel.name}: binary is {bins[0]}, want …/{want_name}"
    finally:
        _cleanup()


def test_platform_tag_map_covers_the_build_matrix():
    """Every arch the plugin build matrix names has a PyPI platform tag in build_wheels."""
    bw = _load(_BUILD_WHEELS)
    hook = _load(_REPO_ROOT / "scripts" / "build_hook_binary.py")
    missing = [a for a in hook.DEFAULT_ARCHES if a not in bw._PLATFORM_TAGS]
    assert not missing, f"build_wheels has no platform tag for {missing}"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem + "_t", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
