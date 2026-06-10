"""run_demo — the combined Hermes / OpenClaw × DOS integration demo.

Runs both prongs and prints one scoreboard:

  * AXIS 2 (safety, single agent) — DOS refuses arbitrary-exec tool commands
    before they run. The value that holds even for ONE agent.
  * AXIS 1 (coordination, K agents) — DOS's arbiter serializes concurrent writes
    to shared state, eliminating lost updates. The value that GROWS with the fleet.

Both numbers are measured off ground truth (a sentinel file the unsafe commands
write; the shared store's own booking log), never an agent's self-report.

Run:  python run_demo.py [K]      (default K=4 for the coordination arm)
"""

from __future__ import annotations

import sys

import run_coord_demo
import run_safety_demo


def main() -> int:
    print("\n" + "#" * 72)
    print("#  DOS x Hermes / OpenClaw - the missing safety gate + lock manager")
    print("#" * 72 + "\n")

    safety_rc = run_safety_demo.main()
    print()
    coord_rc = run_coord_demo.main()

    print("\n" + "#" * 72)
    print("#  SCOREBOARD")
    print("#" * 72)
    print(f"  axis 2 (safety, 1 agent)      {'PASS' if safety_rc == 0 else 'FAIL'}"
          "   - unsafe commands blocked before they run")
    print(f"  axis 1 (coordination, fleet)  {'PASS' if coord_rc == 0 else 'FAIL'}"
          "   - lost updates eliminated under contention")
    print("#" * 72)
    print("\n  The wire-in is `hermes_adapter.py` - two functions, no `import dos`.")
    print("  Copy it into your runtime's tool-execution loop. See README.md.\n")

    return 0 if (safety_rc == 0 and coord_rc == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
