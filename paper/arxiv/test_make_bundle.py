"""Self-contained checks for make_bundle.py — the arXiv bundle builder.

This lives NEXT TO the script it tests, deliberately OUTSIDE tests/ (which the
kernel suite owns via `testpaths = ["tests"]`). The paper tooling is outside the
four kernel layers — the same reason scripts/ and the MCP server have no kernel
test — so its check ships here and runs on demand:

    python -m pytest paper/arxiv/test_make_bundle.py -q
    # or, with no pytest:  python paper/arxiv/test_make_bundle.py

The load-bearing case is the regression I fixed: arxiv-latex-cleaner PRUNES
refs.bib (it keeps a compiled .bbl but drops the .bib SOURCE), and since main.tex
does \\bibliography{refs}, a bundle without refs.bib (and without a .bbl) makes
arXiv's BibTeX run fail so every \\cite renders [?]. The fix restores the
bibliography files into the cleaned tree; these checks pin that it (a) actually
produces a tarball, (b) keeps refs.bib in it, and (c) keeps main.tex + the
sections + the referenced figures, so the bundle stays compilable.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tarfile
from pathlib import Path

ARXIV_DIR = Path(__file__).resolve().parent
PAPER_DIR = ARXIV_DIR.parent
REPO_ROOT = PAPER_DIR.parent


def _build_bundle(tmp_out: Path) -> Path:
    """Run make_bundle.py end-to-end into a throwaway tarball and return its path.

    Uses whatever arxiv-latex-cleaner state the environment has — the fix must
    hold BOTH with the cleaner (it prunes refs.bib, restoration kicks in) and
    without it (refs.bib was never pruned). Either way the assertions below hold,
    which is the point: the bundle is correct regardless of the cleaner.
    """
    cp = subprocess.run(
        [sys.executable, str(ARXIV_DIR / "make_bundle.py"),
         "--date", "test", "--out", str(tmp_out)],
        capture_output=True, text=True,
    )
    assert cp.returncode == 0, f"make_bundle.py failed:\n{cp.stdout}\n{cp.stderr}"
    assert tmp_out.exists(), f"no tarball produced at {tmp_out}"
    return tmp_out


def test_bundle_keeps_refs_bib(tmp_path):
    """The regression: refs.bib MUST be in the tarball (cleaner prunes it)."""
    out = _build_bundle(tmp_path / "arxiv-test.tar.gz")
    with tarfile.open(out) as t:
        top = {n for n in t.getnames() if "/" not in n}
    assert "refs.bib" in top, (
        "refs.bib is missing from the bundle — \\cite keys will render [?]. "
        "The arxiv-latex-cleaner restoration in make_bundle.py regressed."
    )


def test_bundle_is_compilable_shape(tmp_path):
    """main.tex at root, the section .tex present, and every \\includegraphics
    target resolves to a bundled figure — the structural shape that compiles."""
    out = _build_bundle(tmp_path / "arxiv-test.tar.gz")
    with tarfile.open(out) as t:
        names = set(t.getnames())
        top = {n for n in names if "/" not in n}
        assert "main.tex" in top, "main.tex must be at the tarball root"
        sections = [n for n in names if n.startswith("sections/") and n.endswith(".tex")]
        assert sections, "no sections/*.tex in the bundle"

        figs = {n.split("/", 1)[1] for n in names if n.startswith("figs/")}
        stems = {f.rsplit(".", 1)[0] for f in figs}
        pat = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
        unresolved = []
        for sec in sections:
            body = t.extractfile(sec).read().decode("utf-8")
            for m in pat.finditer(body):
                target = m.group(1).strip().split("/")[-1]
                if target not in figs and target.rsplit(".", 1)[0] not in stems:
                    unresolved.append(target)
        assert not unresolved, f"figures referenced but not bundled: {unresolved}"


def test_graphicspath_covers_flat_layout():
    """main.tex's \\graphicspath must list {figs/} (the flat bundle layout), not
    only {../figs/} (the repo layout) — else figures don't resolve on arXiv."""
    main_tex = (ARXIV_DIR / "main.tex").read_text(encoding="utf-8")
    gp = re.search(r"\\graphicspath\{([^\n]+)\}", main_tex)
    assert gp, "no \\graphicspath in main.tex"
    assert "{figs/}" in gp.group(0), (
        f"\\graphicspath must include {{figs/}} for the flat bundle layout; got {gp.group(0)}"
    )


if __name__ == "__main__":
    # Allow running without pytest: drive each test with a temp dir.
    import tempfile

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                if "tmp_path" in fn.__code__.co_varnames:
                    with tempfile.TemporaryDirectory() as d:
                        fn(Path(d))
                else:
                    fn()
                print(f"[PASS] {name}")
            except AssertionError as e:
                failures += 1
                print(f"[FAIL] {name}: {e}")
    print(f"\n{'all passed' if not failures else f'{failures} FAILED'}")
    raise SystemExit(1 if failures else 0)
