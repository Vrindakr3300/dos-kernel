"""Recipe 0 — the universal pattern (framework-free), runnable.

The whole adapter is two functions (`_fixture.verified_done` / `_fixture.admit`):
`verify` at the "done" seam, `arbitrate` at the dispatch seam. Every framework
recipe in this directory is one of these, relocated to that framework's seam.

    python examples/fleet_frameworks/universal.py

Needs only `dos` (pip install -e . from the repo root).
"""

from __future__ import annotations

from dos import oracle

from _fixture import admit, make_demo_repo, verified_done


def run_demo(repo=None) -> dict:
    """Execute both seams against the throwaway repo; return the raw verdicts."""
    cfg = make_demo_repo(repo)
    held_lease = [{"lane": "api", "lane_kind": "cluster", "tree": ["src/api/**"]}]
    return {
        "auth1_done": verified_done("AUTH", "AUTH1", cfg),
        "auth2_done": verified_done("AUTH", "AUTH2", cfg),
        "detail": oracle.is_shipped("AUTH", "AUTH1", cfg=cfg),
        "admit_free": admit("api", ["src/api/**"], [], cfg),
        "admit_held": admit("api", ["src/api/**"], held_lease, cfg),
    }


def main() -> int:
    r = run_demo()
    d = r["detail"]
    print(f"verified_done('AUTH', 'AUTH1') = {r['auth1_done']}")
    print(f"verified_done('AUTH', 'AUTH2') = {r['auth2_done']}")
    print(f"verdict detail: shipped={d.shipped} source={d.source} sha={d.sha}")
    free, held = r["admit_free"], r["admit_held"]
    print(f"admit api (no leases): {free.outcome} -> {free.lane}")
    print(f"admit api (api held):  {held.outcome} - {held.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
