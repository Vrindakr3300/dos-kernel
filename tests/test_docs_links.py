"""Every relative markdown link in a tracked doc resolves.

A 2026-06-12 corpus audit found 35 dead relative links across the design
docs — targets cited under pre-rename slugs (docs/115/116/117/132/144/89/99
all grew longer names after being cited), wrong ``../`` depth into the
private sibling checkout, glob-style pseudo-links (``138_*.md``), and links
to pre-seed docs that never existed in this repo's visible history. All of
it was honest rot: a file was renamed after being cited, and nothing failed.
This gate makes the next rename fail the suite instead of rotting silently —
the sibling of ``test_readme_assembly`` / ``test_llms_full``, aimed at the
corpus's own cross-references.

Two deliberate non-assertions:

- **Cross-repo links** (targets resolving OUTSIDE this repo, e.g. the
  ``../../dos-private`` sibling-checkout convention) are skipped: CI has no
  sibling checkout, and the private repo's filenames are not this suite's
  fact to pin.
- **Quoted spec syntax** that merely looks like a link (the llmstxt.org
  format line ``- [name](url): description`` in docs/299) is allowlisted by
  exact (file, target) pair, so a new false positive is a one-line,
  reviewable exemption.

Source-tree-only: an installed wheel ships no docs/ and no git index, so the
whole module skips outside a checkout.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

# Inline links and images: [text](target), ![alt](target). The target group
# stops at whitespace and ')'; an in-page anchor suffix (#...) is split off
# and never asserted (heading anchors are prose, not files).
_LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+?)(?:#[^)]*)?\)")

# (repo-relative file, link target) pairs that LOOK like relative links but
# are illustrative syntax quoted from a spec — not references to a file.
_ALLOWED_NON_LINKS = {
    # llmstxt.org's own format example: "- [name](url): one-line description"
    ("docs/299_agent-discoverability-aeo-plan.md", "url"),
}

pytestmark = pytest.mark.skipif(
    not (_REPO / ".git").exists(),
    reason="the docs link audit only applies to a source checkout",
)


def _tracked_markdown() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip("git unavailable — cannot enumerate tracked docs")
    return [line for line in proc.stdout.splitlines() if line]


def test_relative_doc_links_resolve() -> None:
    """No tracked .md carries a relative link to a file that does not exist."""
    dead: list[str] = []
    for rel in _tracked_markdown():
        path = _REPO / rel
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Tracked but deleted in the working tree (an in-flight move) —
            # the next commit's run sees the truth; nothing to assert now.
            continue
        for match in _LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "<")):
                continue
            if (rel, target) in _ALLOWED_NON_LINKS:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(_REPO):
                # The cross-repo sibling convention (../../dos-private/…):
                # valid only in the two-checkout layout, never on CI.
                continue
            if not resolved.exists():
                line = text[: match.start()].count("\n") + 1
                dead.append(f"{rel}:{line}: -> {target}")
    assert not dead, (
        "dead relative links in tracked docs (fix the target or, for quoted "
        "spec syntax, add an _ALLOWED_NON_LINKS pair):\n" + "\n".join(dead)
    )
