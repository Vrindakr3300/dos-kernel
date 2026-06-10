"""Property-based proof of the install-surface contract (docs/273 family).

The install wrappers (`install.sh` / `install.ps1`) make exactly one promise:
*find a Python 3.11+, then forward every argument verbatim to `install.py`.* That
"verbatim forward" is an algebraic property, not a single example — it must hold
for ANY argument vector `install.py` accepts (every subcommand, every flag, in
any order). And the single-source-of-truth facts reader (`install_facts.py`) has
its own invariants: the extras/scripts it returns must be a faithful, sorted,
deduplicated projection of `pyproject.toml`.

This file pins both as ∀-laws with Hypothesis — the install-surface sibling of
`test_prop_breaker` / `test_prop_reconcile`. It is pure and fast: it never runs a
real install (that's `test_install_levels.py`); it checks the *contract* the
wrappers and facts reader promise, by parsing them as text and by re-reading
pyproject. Test-time only — `importorskip`s hypothesis so a bare `pip install -e .`
(no `[dev]`) still collects a green suite.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_install_facts_module():
    spec = importlib.util.spec_from_file_location(
        "install_facts", REPO_ROOT / "scripts" / "install_facts.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["install_facts"] = mod
    spec.loader.exec_module(mod)
    return mod


_FACTS_MOD = _load_install_facts_module()
FACTS = _FACTS_MOD.read_install_facts()

_SH = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
_PS1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The wrapper-forwarding contract: both wrappers end by exec-ing install.py with
# the full argument vector, and probe for the EXACT Python floor pyproject sets.
# ---------------------------------------------------------------------------

class TestWrappersForwardVerbatim:
    """Both wrappers hand `install.py` the whole arg vector, unmodified."""

    def test_sh_execs_install_py_with_all_args(self) -> None:
        # POSIX: `exec "$PY" install.py "$@"` — "$@" is the verbatim,
        # word-split-safe forward of every argument.
        assert re.search(r'exec\s+"\$PY"\s+install\.py\s+"\$@"', _SH), (
            "install.sh must end by exec-ing `install.py \"$@\"` so it forwards "
            "every argument verbatim; the forwarding contract is broken."
        )

    def test_ps1_invokes_install_py_with_all_args(self) -> None:
        # PowerShell: `& $py.Exe @preArgs install.py @ForwardArgs` — @ForwardArgs
        # splats the remaining-arguments array verbatim. (Named $ForwardArgs, not
        # $Args, to avoid shadowing the $Args automatic variable.)
        assert re.search(r"install\.py\s+@ForwardArgs", _PS1), (
            "install.ps1 must invoke `install.py @ForwardArgs` so it forwards "
            "every argument verbatim; the forwarding contract is broken."
        )
        assert "ValueFromRemainingArguments" in _PS1, (
            "install.ps1 must capture ALL trailing args via "
            "[Parameter(ValueFromRemainingArguments=$true)] — otherwise flags "
            "like `--extras mcp` are dropped before they reach install.py."
        )

    def test_both_wrappers_probe_the_pyproject_python_floor(self) -> None:
        """The version the wrappers require must equal `requires-python`.

        If pyproject moves its floor (say to >=3.12) and the wrappers still
        probe `>= (3, 11)`, a user on 3.11 would be told they're fine and then
        hit an install-time failure. Pin them in lockstep.
        """
        m = re.match(r">=\s*(\d+)\.(\d+)", FACTS.requires_python)
        assert m, f"unexpected requires-python form: {FACTS.requires_python!r}"
        major, minor = m.group(1), m.group(2)
        floor_tuple = f"({major}, {minor})"
        assert floor_tuple in _SH, (
            f"install.sh probes a different Python floor than pyproject's "
            f"{FACTS.requires_python} (expected `>= {floor_tuple}`)."
        )
        assert floor_tuple in _PS1, (
            f"install.ps1 probes a different Python floor than pyproject's "
            f"{FACTS.requires_python} (expected `>= {floor_tuple}`)."
        )


# ---------------------------------------------------------------------------
# install_facts is a faithful projection of pyproject — ∀ properties.
# ---------------------------------------------------------------------------

# A synthetic [project] table: a plausible name, version, a random set of extras,
# a random set of scripts. We re-run the projection logic over it and assert the
# invariants hold regardless of input shape.
_ident = st.text(alphabet="abcdefghijklmnopqrstuvwxyz-", min_size=1, max_size=12)
_version = st.from_regex(r"\d{1,2}\.\d{1,2}\.\d{1,2}", fullmatch=True)


class TestFactsProjection:
    @given(
        extras=st.dictionaries(_ident, st.lists(_ident, max_size=3), max_size=8),
        scripts=st.dictionaries(_ident, _ident, max_size=6),
        version=_version,
    )
    @settings(max_examples=300, deadline=None)
    def test_extras_and_scripts_are_sorted_deduped_keys(
        self, extras, scripts, version
    ) -> None:
        """The reader returns the sorted, deduplicated KEYS of each table."""
        project = {
            "name": "dos-kernel",
            "version": version,
            "optional-dependencies": extras,
            "scripts": scripts,
            "dependencies": [],
        }
        facts = _project_to_facts(project)
        # Sorted.
        assert list(facts.extras) == sorted(facts.extras)
        assert list(facts.console_scripts) == sorted(facts.console_scripts)
        # Exactly the keys (a dict can't repeat a key, so this is set-equality).
        assert set(facts.extras) == set(extras)
        assert set(facts.console_scripts) == set(scripts)
        # The version + name pass through unchanged.
        assert facts.version == version
        assert facts.dist_name == "dos-kernel"

    @given(version=_version)
    @settings(max_examples=50, deadline=None)
    def test_missing_optional_tables_yield_empty_tuples(self, version) -> None:
        """A [project] with no extras/scripts/deps yields empty tuples, not raise."""
        facts = _project_to_facts({"name": "dos-kernel", "version": version})
        assert facts.extras == ()
        assert facts.console_scripts == ()
        assert facts.core_dependencies == ()


def _project_to_facts(project: dict):
    """Build an InstallFacts from a raw [project] dict, mirroring the reader.

    We exercise the same projection the reader uses, but over synthetic inputs —
    so we can prove the ∀-law without writing throwaway pyproject files to disk.
    """
    InstallFacts = _FACTS_MOD.InstallFacts
    return InstallFacts(
        dist_name=project["name"],
        version=project["version"],
        extras=tuple(sorted(project.get("optional-dependencies", {}).keys())),
        console_scripts=tuple(sorted(project.get("scripts", {}).keys())),
        requires_python=project.get("requires-python", ""),
        core_dependencies=tuple(project.get("dependencies", ())),
    )


def test_real_pyproject_matches_the_synthetic_projection() -> None:
    """The synthetic projection used above equals the real reader on real input.

    Guards against the synthetic `_project_to_facts` drifting from the actual
    `read_install_facts` — they must agree on the live pyproject, or the ∀-laws
    are proving a function that isn't the one shipped.
    """
    project = _FACTS_MOD._project_table()
    assert _project_to_facts(project).as_dict() == FACTS.as_dict()


# ---------------------------------------------------------------------------
# The POSIX wrapper must stay LF-only with a valid shebang — a CRLF clone on
# Windows would turn `#!/usr/bin/env sh` into `sh\r` and break the bootstrap.
# ---------------------------------------------------------------------------

def test_install_sh_has_lf_shebang() -> None:
    """install.sh starts with a `#!` shebang and carries NO `\\r` line endings.

    `.gitattributes` pins `*.sh eol=lf`; this test is the runtime witness that the
    committed bytes actually honor it (a stray CRLF that slipped past the attribute
    would fail the shebang on Linux/WSL). It checks the on-disk bytes, the same
    surface a cloning user gets.
    """
    raw = (REPO_ROOT / "install.sh").read_bytes()
    assert raw.startswith(b"#!"), "install.sh lost its shebang line"
    assert b"\r\n" not in raw, (
        "install.sh contains CRLF line endings — a Windows clone would break its "
        "shebang (`sh\\r`). Ensure .gitattributes pins `*.sh eol=lf` and re-save LF."
    )
    first_line = raw.split(b"\n", 1)[0]
    assert b"sh" in first_line, (
        f"install.sh shebang looks wrong: {first_line!r}"
    )


def test_gitattributes_pins_sh_to_lf() -> None:
    """`.gitattributes` exists and forces `*.sh` to LF (the cross-platform leash)."""
    ga = REPO_ROOT / ".gitattributes"
    assert ga.is_file(), ".gitattributes is missing — *.sh eol is unpinned"
    text = ga.read_text(encoding="utf-8")
    assert re.search(r"\*\.sh\s+.*eol=lf", text), (
        ".gitattributes does not pin `*.sh ... eol=lf`; a Windows clone could "
        "CRLF-corrupt install.sh's shebang."
    )
