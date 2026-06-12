"""The dos NeMo-Guardrails action, invoked offline (issue #51).

No LLM, no API key, no nemoguardrails required: the action function IS the
seam (a rails flow only calls it via `execute` and branches on the dict it
returns), so the demo invokes it directly on the canonical caught-lie story —
an over-claimed commit refused, the landed commit accepted.

    python examples/nemo_guardrails/demo.py

With `nemoguardrails` installed, the same action wires into a rails app via
the sibling `config/` directory (see README.md).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from dos.drivers._effect_gate import CommitClaim
from dos.drivers.nemo_action import make_dos_effect_check


def main() -> int:
    repo = Path(tempfile.mkdtemp(prefix="dos_nemo_demo_"))

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "demo@example.invalid")
    git("config", "user.name", "demo")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git("add", "seed.txt")
    git("commit", "-q", "-m", "seed")

    # Built at "app start": the CommitClaim baseline pins to HEAD here.
    check = make_dos_effect_check(str(repo), expect=[CommitClaim()])

    forged = asyncio.run(check(claim_text="Done! Committed the fix."))
    print(f"forged claim   -> tripped={forged['tripped']}  ({forged['outcome']})")
    print(f"  flow would answer: {forged['reason']}")

    (repo / "fix.py").write_text("def fix(): ...\n", encoding="utf-8")
    git("add", "fix.py")
    git("commit", "-q", "-m", "land the fix")

    witnessed = asyncio.run(check(claim_text="Done! Committed the fix."))
    print(f"witnessed claim -> tripped={witnessed['tripped']}  ({witnessed['outcome']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
