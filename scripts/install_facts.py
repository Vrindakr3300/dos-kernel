#!/usr/bin/env python3
"""Single source of truth for the install surface — derived from `pyproject.toml`.

DOS now offers many install paths (uv tool / uvx, pip, pip -e, the repo-local
`install.sh`/`install.ps1` wrappers, the Claude Code plugin, and the planned
Homebrew/WinGet/Scoop channels). Those paths are *documented* in the README and
`docs/INSTALL.md` and *scripted* in the wrappers — and every one of them repeats
facts that actually live in `pyproject.toml`: the distribution name, the version,
the set of extras (`mcp`, `dev`, `tui`, …), and the console-script names
(`dos`, `dos-mcp`). Hand-copied, those repetitions ROT: an extra gets renamed, a
script is dropped, and the install docs keep promising the old name.

This module is the leash. It reads `pyproject.toml` ONCE and exposes the install
facts as plain data, so:

  * `tests/test_install_drift.py` can assert no install doc/script names an extra
    or console script that `pyproject.toml` does not declare (the drift gate —
    the install-surface sibling of `tests/test_docs_version_drift.py`'s
    version leash);
  * any future doc/manifest generator (a Homebrew formula, a WinGet manifest)
    can be templated from one authoritative place instead of a second hand-copy.

It is **dev tooling that operates ON the package** (like the release scripts),
NOT part of the kernel: it `tomllib`-reads the repo's own `pyproject.toml` and
imports nothing from `dos`. Pure stdlib (`tomllib` ships in 3.11+, which the
kernel already requires), so it adds no dependency and runs in the bare `[dev]`
test environment.

CLI (handy for eyeballing what the gate sees, and for templating):

    python scripts/install_facts.py            # human-readable summary
    python scripts/install_facts.py --json      # the facts as JSON
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The repo root is one level up from scripts/. We anchor on this file, NOT cwd,
# so the facts reader works from anywhere (the same `__file__`-vs-cwd care the
# rest of the tooling takes — note this is *tooling*, which legitimately ships
# with the repo it serves, unlike the kernel which must never assume its tree).
REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


@dataclass(frozen=True)
class InstallFacts:
    """The authoritative install surface, read from `pyproject.toml`.

    Every field is a fact a human-written install doc or script repeats; the
    drift gate compares what the docs/scripts SAY against these.
    """

    # The pip-install / dependency-pin name. `dos-kernel`, NOT `dos` (the bare
    # `dos` on PyPI is an unrelated squatter — see SECURITY.md "Supply chain").
    dist_name: str
    # The version the package reports (the same literal the version-drift gate
    # leashes the doc banners to).
    version: str
    # The extras a user may request as `pip install dos-kernel[<extra>]` /
    # `--extras <extra>` / `uv tool install ".[<extra>]"`. Sorted for stable
    # comparison + display.
    extras: tuple[str, ...]
    # The console scripts the install puts on PATH (`dos`, `dos-mcp`). A doc that
    # promises a `dos-<x>` command that isn't here is lying to the reader.
    console_scripts: tuple[str, ...]
    # The minimum Python the install requires (`requires-python`), e.g. ">=3.11".
    # The wrappers probe for exactly this floor; a doc that says "3.9+" would drift.
    requires_python: str
    # The core (non-extra) runtime dependencies — what a bare `pip install
    # dos-kernel` pulls. The "near-stdlib: only PyYAML" claim is checkable here.
    core_dependencies: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "dist_name": self.dist_name,
            "version": self.version,
            "extras": list(self.extras),
            "console_scripts": list(self.console_scripts),
            "requires_python": self.requires_python,
            "core_dependencies": list(self.core_dependencies),
        }


def _project_table(pyproject_path: Path = PYPROJECT) -> dict:
    """Parse `pyproject.toml` and return its `[project]` table."""
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)
    try:
        return data["project"]
    except KeyError as exc:  # pragma: no cover — a malformed pyproject is a bug
        raise RuntimeError(
            f"{pyproject_path} has no [project] table — cannot read install facts."
        ) from exc


def read_install_facts(pyproject_path: Path = PYPROJECT) -> InstallFacts:
    """Read the canonical install facts from `pyproject.toml`.

    The ONE place that knows where each fact lives in the TOML; everything else
    (the drift gate, any future generator) consumes the returned dataclass.
    """
    project = _project_table(pyproject_path)
    extras = tuple(sorted(project.get("optional-dependencies", {}).keys()))
    console_scripts = tuple(sorted(project.get("scripts", {}).keys()))
    core_deps = tuple(project.get("dependencies", ()))
    return InstallFacts(
        dist_name=project["name"],
        version=project["version"],
        extras=extras,
        console_scripts=console_scripts,
        requires_python=project.get("requires-python", ""),
        core_dependencies=core_deps,
    )


def _main(argv: list[str]) -> int:
    facts = read_install_facts()
    if "--json" in argv:
        print(json.dumps(facts.as_dict(), indent=2))
        return 0
    print(f"distribution     {facts.dist_name}")
    print(f"version          {facts.version}")
    print(f"requires-python  {facts.requires_python}")
    print(f"console scripts  {', '.join(facts.console_scripts)}")
    print(f"extras           {', '.join(facts.extras)}")
    print(f"core deps        {', '.join(facts.core_dependencies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
