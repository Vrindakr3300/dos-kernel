#!/usr/bin/env python
"""Make paper.html fully self-contained: inline the CSS and every figure as data URIs.

Why this exists: the assembled paper.html references its stylesheet and figures by
*relative* path (`href="style.css"`, `src="figs/NAME.png"`). That only renders when the
file is opened from the paper/ directory in a browser that resolves relative assets.
Open it anywhere else — a Markdown/HTML previewer, a moved copy, an inline viewer, an
email attachment — and the images silently break (the path no longer resolves).

This step rewrites paper.html in place so it carries its own bytes:
  * <link rel="stylesheet" href="style.css">  ->  an inline <style>…</style>
  * <img src="figs/NAME.png">                 ->  <img src="data:image/png;base64,…">

After this, the single paper.html renders identically no matter how it is opened — the
"self-contained" property the README already promises, made literally true for the HTML
(the PDF was always self-contained because Chrome embeds the images at render time).

    python paper/embed.py            # rewrite paper/paper.html in place
    python paper/embed.py in.html    # rewrite a specific file in place

Run by build.py as the final step. Idempotent: an already-inlined file has no relative
asset references left to replace, so re-running is a no-op.
"""
from __future__ import annotations

import base64
import mimetypes
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _data_uri(path: Path) -> str | None:
    """base64 data: URI for an asset file, or None if it does not exist."""
    if not path.exists():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def inline(html_path: Path) -> None:
    base = html_path.parent
    html = html_path.read_text(encoding="utf-8")
    inlined_imgs = missing_imgs = 0

    # 1) inline the stylesheet(s): <link rel="stylesheet" href="X"> -> <style>…</style>
    def repl_css(m: re.Match) -> str:
        href = m.group("href")
        css = base / href
        if css.exists():
            return f"<style>\n{css.read_text(encoding='utf-8')}\n</style>"
        return m.group(0)  # leave a non-local href (e.g. a CDN) untouched

    html = re.sub(
        r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*\bhref=["\'](?P<href>[^"\']+)["\'][^>]*/?>',
        repl_css, html, flags=re.IGNORECASE,
    )

    # 2) inline <img src="…"> for every LOCAL (non data:, non http) asset
    def repl_img(m: re.Match) -> str:
        nonlocal inlined_imgs, missing_imgs
        src = m.group("src")
        if src.startswith(("data:", "http://", "https://")):
            return m.group(0)
        uri = _data_uri(base / src)
        if uri is None:
            missing_imgs += 1
            print(f"  ! img source not found, left as-is: {src}", file=sys.stderr)
            return m.group(0)
        inlined_imgs += 1
        return m.group(0).replace(m.group("q") + src + m.group("q"),
                                  m.group("q") + uri + m.group("q"), 1)

    html = re.sub(
        r'<img\b[^>]*\bsrc=(?P<q>["\'])(?P<src>[^"\']+)(?P=q)[^>]*>',
        repl_img, html, flags=re.IGNORECASE,
    )

    html_path.write_text(html, encoding="utf-8")
    print(f"embedded {html_path.name}: {inlined_imgs} images inlined"
          + (f", {missing_imgs} MISSING" if missing_imgs else "")
          + f"  ({len(html):,} bytes self-contained)")


def main(argv: list[str]) -> int:
    target = Path(argv[0]) if argv else HERE / "paper.html"
    target = target.resolve()
    if not target.exists():
        raise SystemExit(f"HTML not found: {target}")
    inline(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
