"""docs/TROUBLESHOOTING.md + the doctor squatter guard — the first-run safety net.

The doc is the "is this normal?" page for the day-1 stumbles; the guard is the
machine-readable distribution-name fact in `dos doctor`. The pins keep the doc
from silently losing one of the four stumbles and keep the guard's wording stable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import dos

_ROOT = Path(dos.__file__).resolve().parents[2]
_DOC = _ROOT / "docs" / "TROUBLESHOOTING.md"


def _cli(*argv: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(Path(dos.__file__).parents[1])}
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv],
        capture_output=True, text=True, env=env,
    )


def test_troubleshooting_doc_exists():
    assert _DOC.is_file(), "docs/TROUBLESHOOTING.md is missing"


def test_doc_names_the_squatter_and_real_distribution():
    text = _DOC.read_text(encoding="utf-8")
    assert "dos-kernel" in text
    assert "squat" in text.lower()
    assert "pip install dos-kernel" in text


def test_doc_covers_the_four_day1_stumbles():
    text = _DOC.read_text(encoding="utf-8").lower()
    # (1) squatter, (2) hooks auto-detection, (3) via none, (4) phantom lease.
    assert "pip install dos" in text
    assert "--hooks auto" in text
    assert "via none" in text
    assert "phantom lease" in text


def test_doctor_text_carries_the_distribution_guard(tmp_path: Path):
    proc = _cli("doctor", "--workspace", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    # The informational distribution line names the real distribution + the squatter.
    assert "dos-kernel" in proc.stdout
    assert "squatter" in proc.stdout


def test_doctor_json_carries_the_distribution_name(tmp_path: Path):
    proc = _cli("doctor", "--json", "--workspace", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["distribution"] == "dos-kernel"
