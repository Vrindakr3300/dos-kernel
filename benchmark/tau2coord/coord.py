"""The ported coordination A/B — domain-parametric, deterministic ($0) core.

PORT of writeadmit/coord_loop.py (docs/233) from airline-only to a domain spec.
Same composition primitive, same arbiter region mapper, a UNIFIED clobber metric
that covers both tau2 lost-update signatures discovered while porting:

  (1) INCOHERENT-MERGE clobber (airline): A2's stale write LANDS on the entity A1
      already changed -> the naive composite hash != the correct serial hash. The
      stale baggage update sticks to a cancelled reservation = a corrupted state.
  (2) DROPPED-WRITE clobber (retail): A2's stale write ERRORS on the entity A1
      already cancelled -> A2 applied 0 in the composite though it applied 1 alone
      -> its work silently VANISHES (the classic lost update). The hashes can be
      EQUAL here (naive == A1-only == serial) yet a write was still lost, so the
      hash metric alone misses it; the solo>naive applied-count catches it.

A clobber = signature (1) OR (2). In BOTH the arbiter PREVENTS it identically:
it refuses A2's concurrent lease on the shared region `<entity>/<id>`, forcing
serialization, under which A2 re-derives against post-A1 state and either no-ops
or adjusts coherently. The witness is the tau2 env's `get_db_hash()` — the agent
authors zero bytes of it (the docs/138 non-forgeability invariant).

This is the deterministic ($0) core: the conflict pairs are hand-built tool-call
sequences (the model is NOT in the loop here — it ran upstream to PRODUCE the
effects in the live arm). It proves the COORDINATION MECHANISM and counts J off
the real tau2 DB. Run `python -m benchmark.tau2coord.coord --deterministic`.
"""
from __future__ import annotations

import io
import json
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# --- the arbiter region mapper (the docs/233 "hard part", which is one line) -----------

def entity_region(collection: str, entity_id: str) -> list[str]:
    """A DB entity as a path-like arbiter region. Two agents on the same entity produce
    OVERLAPPING trees -> `dos.arbiter` refuses the second (serializes). One line, no new
    machinery — `reservations/4WQ150`, `orders/#W5918442`, etc."""
    return [f"{collection}/{entity_id}"]


def arbiter_admits(region: list[str], live_leases: list[dict]) -> bool:
    """Would dos.arbiter ADMIT a lease on `region` given the live leases? Pure, no I/O.

    The same disjointness verdict `dos lease-lane` uses, exercised in-process: ACQUIRE =>
    admit, any refuse => deny. A buggy/hostile policy can only refuse-MORE, never admit a
    collision (the overlap-floor guarantee), so this is a sound lower bound on serialization.
    """
    from dos import arbiter
    dec = arbiter.arbitrate(
        requested_lane=region[0],
        requested_kind="keyword",
        requested_tree=region,
        live_leases=live_leases,
    )
    outcome = getattr(dec, "outcome", None)
    outcome = outcome.value if hasattr(outcome, "value") else str(outcome)
    return outcome in ("acquire", "ACQUIRE")


# --- the domain spec: what makes each tau2 domain a contention site --------------------

@dataclass
class DomainSpec:
    """How to build a conflict pair on one tau2 domain. A pair = two agents on ONE entity:
      A1 = the CANCEL-shaped mutation (cancel the entity).
      A2 = a STALE mutation computed against the entity's PRE-cancel state.
    `pick_entities` enumerates contendable entity ids; `a1`/`a2` build the (tool, kwargs)
    calls for a chosen entity. Adding a domain = one DomainSpec, never an arbiter edit."""
    name: str
    collection: str                                   # the DB collection (e.g. "reservations")
    pick_entities: Callable[[object], list[str]]      # env -> contendable entity ids
    a1: Callable[[object, str], tuple[str, dict]]     # (env, id) -> A1 (cancel) call
    a2: Callable[[object, str], tuple[str, dict]]     # (env, id) -> A2 (stale) call


def _fresh_env(domain: str):
    """A fresh tau2 env (its own DB) we can replay tool-calls onto, with stderr muffled
    (tau2 emits noisy loguru lines on import/build)."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        mod = __import__(f"tau2.domains.{domain}.environment", fromlist=["get_environment"])
        return mod.get_environment()


def _apply(env, call: tuple[str, dict]) -> int:
    """Apply one (tool_name, kwargs) mutation to env's DB. Returns 1 if it applied without
    error, 0 if it errored (a stale/invalid call makes NO state change — this IS the lost
    update). The replay verb is `make_tool_call` (verified on the tau2 clone)."""
    name, kwargs = call
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            env.make_tool_call(name, requestor="assistant", **kwargs)
        return 1
    except Exception:
        return 0


# --- domain specs for the deterministic-DB tau2 domains --------------------------------

def _airline_payment_id(env, R: str) -> str:
    r = env.tools.db.reservations[R]
    ph = getattr(r, "payment_history", None) or []
    if ph:
        pid = getattr(ph[0], "payment_id", None) or getattr(ph[0], "id", None)
        if pid:
            return pid
    u = env.tools.db.users[r.user_id]
    pm = getattr(u, "payment_methods", {}) or {}
    return list(pm.keys())[0] if pm else "credit_card_1"


AIRLINE = DomainSpec(
    name="airline",
    collection="reservations",
    pick_entities=lambda env: list(env.tools.db.reservations.keys()),
    a1=lambda env, R: ("cancel_reservation", {"reservation_id": R}),
    # A2 (stale): add a checked bag to R — valid against pre-cancel R, stale after A1.
    a2=lambda env, R: ("update_reservation_baggages",
                       {"reservation_id": R, "total_baggages": 3, "nonfree_baggages": 1,
                        "payment_id": _airline_payment_id(env, R)}),
)

RETAIL = DomainSpec(
    name="retail",
    collection="orders",
    pick_entities=lambda env: [k for k, v in env.tools.db.orders.items()
                               if getattr(v, "status", None) == "pending"],
    a1=lambda env, R: ("cancel_pending_order", {"order_id": R, "reason": "no longer needed"}),
    # A2 (stale): change R's shipping address — valid against a pending R, stale after cancel.
    a2=lambda env, R: ("modify_pending_order_address",
                       {"order_id": R, "address1": "742 Evergreen Terrace", "address2": "",
                        "city": "Springfield", "state": "OR", "country": "USA", "zip": "97403"}),
)

DOMAINS: dict[str, DomainSpec] = {d.name: d for d in (AIRLINE, RETAIL)}


# --- the unified clobber metric (both signatures) + the arbiter verdict ----------------

@dataclass
class PairResult:
    domain: str
    entity: str
    a2_solo_applied: int       # A2 alone on the original DB (its own check passed)
    a2_naive_applied: int      # A2 in the naive A1->A2 composite (stale)
    naive_hash: Optional[str]
    serial_hash: Optional[str]
    incoherent_merge: bool     # signature 1: naive_hash != serial_hash
    dropped_write: bool        # signature 2: a2_solo_applied > a2_naive_applied
    naive_clobbered: bool      # (1) OR (2)
    arbiter_serialized: bool   # the arbiter refused A2's concurrent lease
    j: int                     # 1 iff a clobber occurred AND the arbiter prevented it

    def to_row(self) -> dict:
        return {
            "domain": self.domain, "entity": self.entity, "j": self.j,
            "naive_clobbered": self.naive_clobbered,
            "incoherent_merge": self.incoherent_merge, "dropped_write": self.dropped_write,
            "arbiter_serialized": self.arbiter_serialized,
            "a2_solo_applied": self.a2_solo_applied, "a2_naive_applied": self.a2_naive_applied,
            "naive_hash": self.naive_hash, "serial_hash": self.serial_hash,
        }


def coordinate_pair(spec: DomainSpec, entity: str) -> PairResult:
    """Run both arms for ONE conflict pair on `entity`, deterministically (no model).

      SOLO   = A2 alone on a fresh DB (proves A2's own check passed -> it would commit).
      NAIVE  = A1 then A2 on ONE shared DB, arrival order, NO coordination. A2's calls were
               computed against the pre-A1 entity, so the blind replay either corrupts the
               state (signature 1) or drops A2's write (signature 2).
      SERIAL = the arbiter's outcome: A1 lands, then A2 RE-DERIVED against post-A1 state.
               Seeing the entity already cancelled, A2 correctly no-ops -> == the A1-only
               state. (This is the state the referee produces; the witness is its hash.)
      ARBITER= would dos.arbiter refuse A2's concurrent lease while A1 holds the region?

    J = 1 iff a clobber occurred (signature 1 OR 2) AND the arbiter would have prevented it
    (refused A2's concurrent lease, forcing the SERIAL outcome). Off the DB-hash.
    """
    a1 = spec.a1(_fresh_env(spec.name), entity)  # build against a throwaway env for lookups
    a2 = spec.a2(_fresh_env(spec.name), entity)

    # SOLO: A2 alone on the original DB.
    env_solo = _fresh_env(spec.name)
    a2_solo = _apply(env_solo, a2)

    # NAIVE: A1 then A2-stale on one shared DB.
    env_naive = _fresh_env(spec.name)
    _apply(env_naive, a1)
    a2_naive = _apply(env_naive, a2)
    naive_hash = env_naive.get_db_hash()

    # SERIAL: A1 lands; A2 re-derived sees the cancel and no-ops -> == A1-only.
    env_serial = _fresh_env(spec.name)
    _apply(env_serial, a1)
    serial_hash = env_serial.get_db_hash()

    # ARBITER: A1 holds the region; would A2's concurrent lease be refused?
    region = entity_region(spec.collection, entity)
    held = [{"lane": region[0], "kind": "keyword", "tree": region, "owner": "agent-1"}]
    arbiter_serialized = not arbiter_admits(region, held)

    incoherent_merge = (naive_hash != serial_hash)
    dropped_write = (a2_solo > a2_naive)
    naive_clobbered = incoherent_merge or dropped_write
    j = 1 if (naive_clobbered and arbiter_serialized) else 0

    return PairResult(
        domain=spec.name, entity=entity,
        a2_solo_applied=a2_solo, a2_naive_applied=a2_naive,
        naive_hash=naive_hash, serial_hash=serial_hash,
        incoherent_merge=incoherent_merge, dropped_write=dropped_write,
        naive_clobbered=naive_clobbered, arbiter_serialized=arbiter_serialized, j=j,
    )


def disjoint_control(spec: DomainSpec) -> dict:
    """The FALSIFIER: two agents on DIFFERENT entities must NOT be serialized (the arbiter
    admits a disjoint lease) and must NOT score a clobber. Proves the metric is not rigged
    to always report 'prevented' — the docs/233 'J=0 = the falsifier working' discipline,
    made structural. Returns {admit_disjoint, admit_same, ok}."""
    env = _fresh_env(spec.name)
    ids = spec.pick_entities(env)
    if len(ids) < 2:
        return {"admit_disjoint": None, "admit_same": None, "ok": None,
                "note": "fewer than 2 entities; control skipped"}
    r1, r2 = entity_region(spec.collection, ids[0]), entity_region(spec.collection, ids[1])
    held = [{"lane": r1[0], "kind": "keyword", "tree": r1, "owner": "agent-1"}]
    admit_disjoint = arbiter_admits(r2, held)   # A2 on a DIFFERENT entity -> expect True
    admit_same = arbiter_admits(r1, held)       # A2 on the SAME entity   -> expect False
    return {"admit_disjoint": admit_disjoint, "admit_same": admit_same,
            "ok": (admit_disjoint is True and admit_same is False),
            "entities": [ids[0], ids[1]]}


def run_deterministic(domains: list[str], pairs_per_domain: int) -> dict:
    """The $0 deterministic A/B over `pairs_per_domain` conflict pairs per domain. Returns
    a result dict: per-domain rows + the headline J (clobbers prevented), the naive baseline
    (clobbers committed by the naive arm), and the disjoint-entity FALSIFIER control."""
    out: dict = {"domains": {}, "total_pairs": 0, "total_naive_clobbers": 0, "total_j": 0,
                 "controls": {}}
    for dom in domains:
        spec = DOMAINS[dom]
        env0 = _fresh_env(dom)
        entities = spec.pick_entities(env0)[:pairs_per_domain]
        rows = [coordinate_pair(spec, e).to_row() for e in entities]
        naive_clobbers = sum(1 for r in rows if r["naive_clobbered"])
        j = sum(r["j"] for r in rows)
        out["domains"][dom] = {
            "pairs": len(rows), "naive_clobbers": naive_clobbers, "j": j, "rows": rows,
        }
        out["controls"][dom] = disjoint_control(spec)
        out["total_pairs"] += len(rows)
        out["total_naive_clobbers"] += naive_clobbers
        out["total_j"] += j
    out["controls_ok"] = all(c.get("ok") is not False for c in out["controls"].values())
    return out


def _print_deterministic(res: dict) -> None:
    print("=== tau2coord DETERMINISTIC A/B (docs/233 port, off the tau2 DB-hash) ===\n")
    for dom, d in res["domains"].items():
        print(f"  [{dom}]  pairs={d['pairs']}  naive_clobbers={d['naive_clobbers']}  "
              f"arbiter-prevented J={d['j']}")
        for r in d["rows"]:
            sig = ("incoherent-merge" if r["incoherent_merge"]
                   else "dropped-write" if r["dropped_write"] else "no-clobber")
            print(f"      {r['entity']:14} clobber={str(r['naive_clobbered']):5} ({sig:16}) "
                  f"arbiter_serialized={r['arbiter_serialized']}  J={r['j']}  "
                  f"naive={str(r['naive_hash'])[:10]} serial={str(r['serial_hash'])[:10]}")
    print(f"\n  TOTAL pairs:            {res['total_pairs']}")
    print(f"  NAIVE arm clobbers:     {res['total_naive_clobbers']}   "
          f"<<< baseline: lost updates a re-run wrapper does NOT prevent (each check passed)")
    print(f"  ARBITER-prevented (J):  {res['total_j']}   "
          f"<<< coordination PAYOFF off the DB-hash")
    print(f"\n  FALSIFIER control (disjoint entities -> NOT serialized):")
    for dom, c in res["controls"].items():
        print(f"    [{dom}] admit_disjoint={c.get('admit_disjoint')} "
              f"admit_same={c.get('admit_same')} -> ok={c.get('ok')}")
    print(f"  controls_ok = {res['controls_ok']}   "
          f"(arbiter admits disjoint, refuses same -> the metric CAN report J=0)")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="tau2coord — docs/233 coordination port")
    ap.add_argument("--deterministic", action="store_true",
                    help="$0 deterministic multi-domain A/B (no model)")
    ap.add_argument("--domains", default="airline,retail",
                    help="comma-separated tau2 domains (default airline,retail)")
    ap.add_argument("--pairs", type=int, default=4, help="conflict pairs PER domain")
    ap.add_argument("--json", action="store_true", help="emit the result dict as JSON")
    args = ap.parse_args(argv)

    if args.deterministic or not (args.json):
        domains = [d.strip() for d in args.domains.split(",") if d.strip()]
        res = run_deterministic(domains, args.pairs)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            _print_deterministic(res)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
