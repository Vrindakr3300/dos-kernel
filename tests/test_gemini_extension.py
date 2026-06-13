"""The Gemini CLI extension manifest — the auto-indexed-gallery adoption surface.

`gemini-extension.json` at the repo ROOT is what `gemini extensions install
<github-url>` reads to install DOS as a Gemini CLI extension, and what Google's
auto-indexed extensions gallery (geminicli.com/extensions) crawls public repos
for and ranks by stars. One in-tree file buys a standing listing on the official
surface — so the file must stay valid and in lockstep with the package it fronts.
This pins the contract (issue #101):

  * **JSON validity + required fields** — the manifest parses and carries the
    fields the Gemini extension schema REQUIRES: `name` (lowercase-dashes,
    matching the repo), `version`, `description`.
  * **Version lockstep** — the manifest `version` tracks the package version
    (`dos.__version__`), the same single-source rule the release skill enforces
    for `pyproject.toml` ↔ `__init__.py` ↔ the Claude plugin manifest. A stale
    literal here is the drift this catches; `scripts/release_bump.py` bumps it.
  * **The MCP server is the shipped one** — the `mcpServers.dos` entry launches
    `python -m dos_mcp.server` (the same server `claude-plugin/.mcp.json` names),
    so the gallery isn't fronting a broken command.
  * **The context file exists** — `contextFileName` points at a real file in the
    repo (Gemini loads it as the extension's instructions to the model).

The manifest lives OUTSIDE the kernel (it is packaging — nothing under
`src/dos/` imports it), the same one-way arrow as the Claude plugin bundle and
the release scripts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import dos

_REPO_ROOT = Path(dos.__file__).resolve().parents[2]
MANIFEST = _REPO_ROOT / "gemini-extension.json"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Existence + JSON validity + the required fields
# ---------------------------------------------------------------------------
def test_manifest_exists_and_parses():
    assert MANIFEST.is_file(), f"missing manifest: {MANIFEST}"
    obj = _load()  # raises on invalid JSON
    assert isinstance(obj, dict), f"{MANIFEST} is not a JSON object"


def test_required_fields_present():
    """name / version / description are the Gemini-extension-schema required keys."""
    m = _load()
    for field in ("name", "version", "description"):
        assert m.get(field), f"gemini-extension.json must declare a non-empty `{field}`"


def test_name_is_lowercase_dashes_and_matches_repo():
    """The schema requires a lowercase-dashes name matching the repo/dir.

    The repo is `dos-kernel`; the gallery key and the install target derive from
    it, so a mismatch (or an uppercase/underscore name) breaks the listing.
    """
    m = _load()
    name = m["name"]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), \
        f"extension name must be lowercase-dashes: {name!r}"
    assert name == "dos-kernel", \
        f"extension name should match the repo `dos-kernel`, got {name!r}"


# ---------------------------------------------------------------------------
# version lockstep with the package (the recurring drift class)
# ---------------------------------------------------------------------------
def test_gemini_extension_version_tracks_package():
    """The manifest version is single-sourced from the package, like the plugin.

    A manifest fronting `dos-kernel X.Y.Z` on the gallery should advertise that
    version; a drifted literal here is the staleness this pins. The bump is part
    of `/release` (scripts/release_bump.py::bump_gemini_extension) — this only
    asserts they match, it doesn't choose the value.
    """
    m = _load()
    assert m.get("version") == dos.__version__, (
        f"gemini-extension.json version {m.get('version')!r} != package "
        f"{dos.__version__!r} — bump gemini-extension.json in lockstep with the "
        f"release (scripts/release_bump.py handles it under the `gemini` target)")


# ---------------------------------------------------------------------------
# mcpServers — the same shipped server the Claude bundle names
# ---------------------------------------------------------------------------
def test_mcp_server_entry_launches_dos_mcp():
    m = _load()
    servers = m.get("mcpServers")
    assert isinstance(servers, dict) and servers, \
        "the manifest must register an MCP server under `mcpServers`"
    assert "dos" in servers, "the DOS server must be registered under `dos`"
    entry = servers["dos"]
    assert entry.get("command"), "the server entry needs a `command`"
    args = entry.get("args", [])
    # Launched as `python -m dos_mcp.server`, the same shape as the Claude bundle's
    # .mcp.json — robust against the `dos-mcp` console script not being on PATH.
    assert "dos_mcp.server" in args or "dos_mcp.server" in str(entry.get("command")), \
        f"server should launch dos_mcp.server: {entry}"


def test_mcp_server_actually_builds():
    """The prerequisite the manifest assumes: the MCP server imports + constructs.

    Skips when the optional `[mcp]` extra is absent (the kernel's own deps are
    PyYAML-only), matching tests/test_mcp_server.py and the plugin-manifest test.
    """
    import pytest
    pytest.importorskip("mcp", reason="dos-mcp needs the optional `mcp` extra")
    from dos_mcp.server import build_server
    assert build_server() is not None


# ---------------------------------------------------------------------------
# contextFileName — points at a real instructions file
# ---------------------------------------------------------------------------
def test_context_file_exists():
    """`contextFileName` is the file Gemini loads as the extension's instructions.

    If declared, it must resolve to a real file in the repo (else the install
    silently ships no context). If omitted, Gemini falls back to GEMINI.md — so
    require whichever is in force to exist.
    """
    m = _load()
    ctx_name = m.get("contextFileName", "GEMINI.md")
    ctx_path = _REPO_ROOT / ctx_name
    assert ctx_path.is_file(), (
        f"contextFileName {ctx_name!r} does not resolve to a file at {ctx_path} — "
        f"the extension would install with no model context")
