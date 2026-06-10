#!/usr/bin/env python
"""Render the assembled paper HTML to PDF via headless Chrome.

No LaTeX / pandoc / weasyprint on this machine — Chrome headless is the reliable
path that embeds the PNG figures cleanly. Usage:

    python paper/render.py            # paper/paper.html -> paper/paper.pdf
    python paper/render.py in.html out.pdf
"""
import subprocess
import sys
from pathlib import Path

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit("Chrome not found in the known install locations.")


def main() -> None:
    here = Path(__file__).resolve().parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "paper.html"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "paper.pdf"
    src = src.resolve()
    out = out.resolve()
    if not src.exists():
        raise SystemExit(f"source HTML not found: {src}")

    chrome = find_chrome()
    url = src.as_uri()
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--no-sandbox",
        f"--print-to-pdf={out}",
        "--virtual-time-budget=8000",
        url,
    ]
    print("rendering:", src.name, "->", out.name)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if not out.exists():
        sys.stderr.write(proc.stdout + "\n" + proc.stderr + "\n")
        raise SystemExit(f"Chrome did not produce {out}")
    size = out.stat().st_size
    print(f"OK: {out}  ({size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
