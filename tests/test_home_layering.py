"""Layering litmus for `dos.home` (docs/75_state-home-plan.md, Law 3).

`home.py` is layer-1 kernel: it may import only `dos.config` (the seam it reads)
and `dos.archive_lock` (a downward edge for the cross-process lock primitive),
plus stdlib. And NO kernel module may import `dos.home` — only the CLI (layer 3)
wires it in. Together these keep the dependency graph an acyclic DAG
(`config ← home ← cli`, `config ← {archive_lock ← home}`) and prove the feared
`home → … → home` import cycle cannot form. Same AST-walk idiom as
`test_judge.py::TestBulkhead`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import dos


_ALLOWED_DOS_IMPORTS = {"dos.config", "dos.archive_lock", "dos"}


def _imported_dos_modules(py: Path) -> list[str]:
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.append(node.module)
    return [m for m in mods if m == "dos" or m.startswith("dos.")]


def test_home_imports_only_config_and_archive_lock():
    """home.py imports only the allowed `dos.*` modules (+ stdlib)."""
    home_py = Path(dos.__file__).parent / "home.py"
    offenders = [m for m in _imported_dos_modules(home_py)
                 if m not in _ALLOWED_DOS_IMPORTS]
    assert offenders == [], f"home.py imports disallowed dos modules: {offenders}"


def test_no_kernel_module_imports_home():
    """No `src/dos/*.py` except cli.py imports dos.home (only the CLI wires it).

    A kernel persist module importing `home` would create a cycle risk and break
    the read-only-writes-nothing layering; the hook fires from the CLI instead.
    """
    core_dir = Path(dos.__file__).parent
    offenders = []
    for py in core_dir.glob("*.py"):
        if py.name in ("home.py", "cli.py"):
            continue  # home is the module under test; cli is the allowed importer
        if "dos.home" in _imported_dos_modules(py):
            offenders.append(py.name)
    assert offenders == [], f"kernel modules import dos.home: {offenders}"


def test_home_names_no_host():
    """home.py names no host (Law 2) — generic `.dos`/main/global vocabulary only."""
    home_py = (Path(dos.__file__).parent / "home.py").read_text(encoding="utf-8")
    # Word-boundary-ish check: the host tokens must not appear as identifiers.
    for host_token in ("import job", "drivers.job", "apply_", "tailor_"):
        assert host_token not in home_py, f"home.py names a host: {host_token!r}"
