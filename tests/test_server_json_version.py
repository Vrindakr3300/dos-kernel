"""server.json — the MCP Registry manifest's version tracks the package.

`server.json` (repo root) is the manifest `mcp-registry-publish.yml` publishes to
the official MCP Registry. The registry validates the PyPI package named in it by
fetching the EXACT pinned version's README and looking for the ownership marker,
and the workflow's own preflight refuses on any skew between server.json and
pyproject. So every version reference in server.json must track the package
version — the same single-source lockstep the plugin manifest is held to
(`tests/test_plugin_manifest.py::test_plugin_version_tracks_package_version`).

A stale server.json is the drift this pins; `scripts/release_bump.py`'s `server`
target keeps it in step (issue #30). This file lives OUTSIDE the kernel — the
same one-way arrow as the release scripts and the plugin manifest test.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import dos

_REPO_ROOT = Path(dos.__file__).resolve().parents[2]
SERVER_JSON = _REPO_ROOT / "server.json"

_FROM_PIN_RE = re.compile(r"dos-kernel\[mcp\]==(\d+\.\d+\.\d+)")


def _load() -> dict:
    return json.loads(SERVER_JSON.read_text(encoding="utf-8"))


def test_server_json_exists_and_parses():
    assert SERVER_JSON.is_file(), "server.json (the MCP Registry manifest) is missing"
    obj = _load()  # raises on invalid JSON
    assert isinstance(obj, dict), "server.json is not a JSON object"


def test_top_level_version_tracks_package():
    """The server release version single-sources from the package, like the plugin.

    A manifest publishing `dos-kernel X.Y.Z` to the registry must name that version;
    a drifted literal here is what strands `mcp-registry-publish.yml`'s preflight.
    (The bump is part of `/release` — this only asserts they match.)
    """
    obj = _load()
    assert obj.get("version") == dos.__version__, (
        f"server.json .version {obj.get('version')!r} != package {dos.__version__!r} "
        "— bump server.json in lockstep (scripts/release_bump.py's `server` target does this)")


def test_package_version_tracks_package():
    obj = _load()
    packages = obj.get("packages") or []
    assert packages, "server.json must declare at least one package"
    for i, pkg in enumerate(packages):
        assert pkg.get("version") == dos.__version__, (
            f"server.json packages[{i}].version {pkg.get('version')!r} != package "
            f"{dos.__version__!r} — the PyPI pin drifted from the release")


def test_from_pin_tracks_package():
    """The `--from dos-kernel[mcp]==X.Y.Z` runtimeArgument pins the version too.

    This is the THIRD version reference issue #30's fix has to keep in step (the issue
    body said "two", but the runtime arg pins it as well) — a stale pin would have
    `uvx` install the wrong version even if the two `"version"` keys were correct.
    """
    obj = _load()
    pins: list[str] = []
    for pkg in obj.get("packages") or []:
        for arg in pkg.get("runtimeArguments") or []:
            val = arg.get("value", "")
            m = _FROM_PIN_RE.search(val if isinstance(val, str) else "")
            if m:
                pins.append(m.group(1))
    assert pins, "expected a `dos-kernel[mcp]==X.Y.Z` pin in a runtimeArgument value"
    for pin in pins:
        assert pin == dos.__version__, (
            f"server.json `--from` pin {pin!r} != package {dos.__version__!r}")
