"""The answer-corpus rot pin (docs/325 Phase A).

`docs/answers/` is the answer corpus: one self-contained, citation-dense page
per high-intent query, each written to be lifted verbatim by an answer engine.
The load-bearing honesty property is that *every number on a page links to the
in-repo file that proves it* — so this suite resolves every repo link each page
carries against the working tree (a renamed source would otherwise leave a dead
citation there forever), pins the answer-shaped skeleton an engine parses, and
checks the index links every page and back. The README-assembly discipline
(tests/test_readme_assembly.py) and the llms.txt rot pin
(tests/test_llms_txt.py), applied to the answer-facing corpus.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ANSWERS = REPO / "docs" / "answers"
INDEX = ANSWERS / "README.md"

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
# An absolute link that names a FILE in this repo, in either fetchable spelling.
REPO_FILE_RE = re.compile(
    r"https://(?:raw\.githubusercontent\.com/anthony-chaudhary/dos-kernel/master/"
    r"|github\.com/anthony-chaudhary/dos-kernel/blob/master/)(?P<path>[^)#?\s]+)"
)
# An absolute link that names a DIRECTORY in this repo.
REPO_TREE_RE = re.compile(
    r"https://github\.com/anthony-chaudhary/dos-kernel/tree/master/(?P<path>[^)#?\s]+)"
)


def _pages() -> list[Path]:
    return sorted(p for p in ANSWERS.glob("*.md") if p.name != "README.md")


def _links(text: str) -> list[tuple[str, str]]:
    return LINK_RE.findall(text)


def test_corpus_is_non_empty() -> None:
    pages = _pages()
    assert len(pages) >= 5, "the answer corpus seeds with at least the five core pages"
    assert INDEX.is_file(), "docs/answers/README.md indexes the corpus"


def test_every_page_is_answer_shaped() -> None:
    """H1 query, a liftable blockquote answer, names the package and a dos verb."""
    for page in _pages():
        text = page.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line.strip()]
        assert lines[0].startswith("# "), f"{page.name}: must open with the query as an H1"
        assert lines[1].startswith(">"), f"{page.name}: the H1 must be followed by the answer blockquote"
        assert "dos-kernel" in text, f"{page.name}: must name the dos-kernel package"
        assert re.search(r"\bdos [a-z-]+", text), f"{page.name}: must name at least one dos command"


def test_every_repo_link_resolves() -> None:
    """Every cited source must resolve — this is what makes 'every number is sourced' true."""
    dead: list[str] = []
    for page in [*_pages(), INDEX]:
        for _, url in _links(page.read_text(encoding="utf-8")):
            file_match = REPO_FILE_RE.match(url)
            if file_match and not (REPO / file_match.group("path")).is_file():
                dead.append(f"{page.name}: {url}")
            tree_match = REPO_TREE_RE.match(url)
            if tree_match and not (REPO / tree_match.group("path")).is_dir():
                dead.append(f"{page.name}: {url}")
    assert not dead, f"dead repo links in the answer corpus: {dead}"


def test_relative_sibling_links_resolve() -> None:
    """A relative link (to a sibling page, the FAQ, an incident) must resolve on disk.

    Fragment-only anchors and absolute URLs are out of scope here (the absolute
    repo links are covered above; section anchors aren't files).
    """
    dead: list[str] = []
    for page in [*_pages(), INDEX]:
        for _, url in _links(page.read_text(encoding="utf-8")):
            if url.startswith(("https://", "http://", "#", "mailto:")):
                continue
            target = url.split("#", 1)[0]
            if not target:
                continue  # pure anchor into the same page
            if not (page.parent / target).resolve().exists():
                dead.append(f"{page.name}: {url}")
    assert not dead, f"dead relative links in the answer corpus: {dead}"


def test_no_local_machine_paths() -> None:
    """The route-privacy-at-authoring-time rule, pinned for the public corpus."""
    for page in [*_pages(), INDEX]:
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:\\", text), f"{page.name}: must carry no local absolute path"


def test_index_links_every_page_and_back() -> None:
    """The index references every page; every page links back into the corpus."""
    index_text = INDEX.read_text(encoding="utf-8")
    index_targets = {
        url.split("#", 1)[0]
        for _, url in _links(index_text)
        if not url.startswith(("https://", "http://", "#", "mailto:"))
    }
    missing_from_index = [
        page.name for page in _pages() if page.name not in index_targets
    ]
    assert not missing_from_index, f"pages absent from docs/answers/README.md: {missing_from_index}"

    for page in _pages():
        text = page.read_text(encoding="utf-8")
        rels = [
            url.split("#", 1)[0]
            for _, url in _links(text)
            if not url.startswith(("https://", "http://", "#", "mailto:")) and url.split("#", 1)[0]
        ]
        # Every page reaches back into the repo's other surfaces (FAQ, incidents,
        # README, or a sibling answer page) — none is an orphan.
        assert rels, f"{page.name}: must cross-link back into the corpus / docs"
