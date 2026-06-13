"""The Smithery manifest — the MCP-registry listing surface (smithery.ai).

`smithery.yaml` at the repo ROOT is what Smithery reads to list/launch the DOS
MCP server. Smithery is the de-facto registry of MCP servers and the on-ramp to
the awesome-mcp-servers crawl, so the file must stay valid and front the SAME
shipped server every other distribution manifest names. This pins the contract:

  * **YAML validity + the stdio shape** — the manifest parses and declares a
    `startCommand` of `type: stdio` (DOS adjudicates the caller's LOCAL git repo,
    so it must run locally, not in a network-sandboxed hosted runtime).
  * **The launch command is the shipped server** — `commandFunction` invokes the
    `dos-kernel[mcp]` distribution's `dos-mcp` entry (the console script
    `pyproject.toml` declares), so the listing isn't fronting a broken command.
  * **No secret in the schema** — DOS is deterministic and needs no API key; the
    only config property is the optional `workspace`, mapped to the
    `DISPATCH_WORKSPACE` env the server reads (same knob as server.json).

The manifest lives OUTSIDE the kernel (it is packaging — nothing under
`src/dos/` imports it), the same one-way arrow as the Claude plugin bundle, the
Gemini extension manifest, and the release scripts. Unlike those manifests it
carries NO version literal — the `commandFunction` resolves `dos-kernel[mcp]`
from PyPI at launch, so there is no version to keep in lockstep (hence no
`release_bump.py` target and no version-drift test here).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # PyYAML is the kernel's one runtime dep

import dos

_REPO_ROOT = Path(dos.__file__).resolve().parents[2]
MANIFEST = _REPO_ROOT / "smithery.yaml"


def _load() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Existence + YAML validity
# ---------------------------------------------------------------------------
def test_manifest_exists_and_parses():
    assert MANIFEST.is_file(), f"missing manifest: {MANIFEST}"
    obj = _load()  # raises on invalid YAML
    assert isinstance(obj, dict), f"{MANIFEST} is not a YAML mapping"


# ---------------------------------------------------------------------------
# The startCommand is a LOCAL stdio server (not a hosted container)
# ---------------------------------------------------------------------------
def test_start_command_is_stdio():
    """DOS reads the caller's local git repo, so it must run as a local stdio
    server — a network-sandboxed hosted runtime can't see the user's repo, and
    the verdict would be hollow. The header explains the choice; this pins it."""
    m = _load()
    start = m.get("startCommand")
    assert isinstance(start, dict), "smithery.yaml must declare a `startCommand` mapping"
    assert start.get("type") == "stdio", (
        f"DOS must list as a local stdio server (it reads the caller's git repo); "
        f"got type={start.get('type')!r}")


# ---------------------------------------------------------------------------
# The launch command fronts the shipped server, via the dos-kernel distribution
# ---------------------------------------------------------------------------
def test_command_function_launches_shipped_server():
    """The commandFunction must invoke the real, pip-installable server.

    It is a JS string (Smithery evaluates it), so we assert on its text: it
    resolves the `dos-kernel[mcp]` distribution and runs the `dos-mcp` entry —
    the same server `claude-plugin/.mcp.json`, `gemini-extension.json`, and
    `server.json` all name. A typo here is a listing that 404s on launch."""
    m = _load()
    fn = m["startCommand"].get("commandFunction", "")
    assert isinstance(fn, str) and fn.strip(), "commandFunction must be a non-empty string"
    assert "dos-kernel[mcp]" in fn, (
        "commandFunction must resolve the `dos-kernel[mcp]` distribution (the "
        "[mcp] extra carries the server framework), like server.json's --from pin")
    assert "dos-mcp" in fn or "dos_mcp.server" in fn, (
        "commandFunction must launch the shipped server (`dos-mcp` console script "
        "or `dos_mcp.server` module)")


# ---------------------------------------------------------------------------
# No secret in the schema — DOS is deterministic; the only knob is `workspace`
# ---------------------------------------------------------------------------
def test_config_schema_has_no_secret_and_carries_workspace():
    """DOS needs no API key (it's deterministic, no LLM). The config schema's
    only property is the optional `workspace`, the git repo to adjudicate —
    mapped to DISPATCH_WORKSPACE, the same env server.json documents."""
    m = _load()
    schema = m["startCommand"].get("configSchema", {})
    assert isinstance(schema, dict), "configSchema must be a JSON-Schema mapping"
    # Nothing required: a deterministic server takes no mandatory credential.
    assert not schema.get("required"), (
        f"DOS needs no required config (no API key); got required={schema.get('required')!r}")
    props = schema.get("properties", {})
    assert "workspace" in props, "the optional `workspace` knob must be declared"
    # The command must wire the workspace knob to the env the server actually reads.
    fn = m["startCommand"]["commandFunction"]
    assert "DISPATCH_WORKSPACE" in fn, (
        "the `workspace` config must map to the DISPATCH_WORKSPACE env the server reads")


# ---------------------------------------------------------------------------
# The prerequisite the manifest assumes: the MCP server actually builds
# ---------------------------------------------------------------------------
def test_mcp_server_actually_builds():
    """The listing assumes a launchable server. Skips when the optional `[mcp]`
    extra is absent (the kernel's own deps are PyYAML-only), matching
    tests/test_gemini_extension.py and the plugin-manifest test."""
    pytest.importorskip("mcp", reason="dos-mcp needs the optional `mcp` extra")
    from dos_mcp.server import build_server
    assert build_server() is not None
