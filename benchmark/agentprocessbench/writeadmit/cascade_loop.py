"""F1 (docs/245) — the cascade-depth experiment: does corruption COMPOUND down a chain?

THE QUESTION. docs/228/233 measured one event blocked (J). docs/245 O4 says the number
that *scales* with a fleet is not events-prevented but COMPOUNDING corruption averted: a
poisoned write is not one lost event — it is a poisoned INPUT every downstream agent then
builds on, so under "believe" corruption should grow with chain depth, while under
"adjudicate" the gate blocks it once at the root and the whole chain stays clean.

WHY A STATE CASCADE, NOT A NARRATED ONE. docs/229/236 found that a NARRATED handoff
(`peer_b.py`, B inherits A's claim TEXT) lets each capable LLM hop SELF-RECOVER — it
re-reads and heals the phantom, so ΔB≈0 (docs/236 proved the ≈0 was recovery LAUNDERING;
a non-LLM endpoint showed ΔB=+1.0). Compounding is a property of STATE, not prose: if the
corruption lives in the DB each node INHERITS AS ITS STARTING WORLD (not as a sentence it
can second-guess), a node cannot "re-check away" a wrong reservation it was handed as fact.
So this cascade hands forward the DB STATE (via tau2's `initialization_data.agent_data`),
the structural form the self-healing endpoint cannot launder.

THE CHAIN (depth D, on one shared reservation R):
  node 0 (root)  — A acts on R. If A OVER-CLAIMS (confident write, db_match=False), the root
                   DB is CORRUPT. (Natural root: a live A on a write-heavy task; synthetic
                   root for the $0 mechanism check: a hand-built corrupt write.)
  believe chain  — node k+1 inherits node k's RAW resulting DB (the forgeable outcome). The
                   poison propagates: each node builds on a wrong world.
  adjudicate     — the gate checks the root claim vs the root DB-hash; on REFUTED it blocks,
                   so node 1 inherits the GOLD (env-verified) DB instead — the chain is clean
                   from node 1 on. (On ADMITTED the gate is a no-op = the control invariant.)

THE WITNESS at every node = the DB-hash vs gold (the agent authors zero bytes). The measured
curve: corrupted-nodes vs depth, believe vs adjudicate. PAYOFF(D) = believe_corrupted(D) −
adjudicate_corrupted(D), which should GROW with D under believe and be ~0 under adjudicate.

Gated behind GEMINI_API_KEY for the live arm; `--smoke` runs the $0 STATE-cascade mechanism
with a synthetic corrupt root (no model), proving the propagation + gate-stops-it logic.
"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .live_loop import _load_gemini_key, _DEFAULT_MODEL
from .coord_loop import (
    _fresh_airline_env, _db_hash, _replay_calls_on, _run_agent_live,
    _extract_res_calls, reservation_region,
)


@dataclass
class CascadeResult:
    depth: int
    arm: str                       # "believe" | "adjudicate"
    corrupted_nodes: int           # nodes whose DB != gold (poison reached them)
    node_hashes: list              # the DB-hash at each node (forensic)
    detail: str = ""


def _gold_hash_for(reservation_id: str) -> str:
    """The correct DB-hash: a fresh env (no corruption). Gold = the task designer's snapshot."""
    return _db_hash(_fresh_airline_env())


def cascade_state(root_corrupt_calls, *, depth: int, arm: str,
                  downstream_calls=None) -> CascadeResult:
    """Run a STATE cascade of `depth` nodes on one reservation. PURE-ish (in-process envs,
    no model — the model ran upstream to produce the calls).

    root_corrupt_calls : the root node's mutating calls (the poison). [(name, kwargs), ...]
    downstream_calls   : per-node calls for nodes 1..depth-1 (each a [(name,kwargs)] list).
                         If None, downstream nodes make NO new mutation — so the only thing
                         that can make node k corrupt is INHERITING a corrupt DB (the cleanest
                         compounding probe: corruption spreads purely by inheritance).

    believe    : node k+1 starts from node k's RAW resulting DB (inherit the outcome).
    adjudicate : node 1 starts from GOLD (the gate blocked the refuted root); the rest inherit
                 normally — so the chain is clean from node 1 on.
    """
    gold = _gold_hash_for("_")  # gold = a fresh env's hash (no node has corrupted it)
    downstream_calls = downstream_calls or [[] for _ in range(max(0, depth - 1))]

    node_hashes = []
    corrupted = 0

    # --- node 0 (root): apply the root calls to a fresh env -> the (possibly corrupt) root DB
    env = _fresh_airline_env()
    _replay_calls_on(env, root_corrupt_calls)
    root_hash = _db_hash(env)
    root_corrupt = (root_hash != gold)

    if arm == "adjudicate" and root_corrupt:
        # the gate BLOCKED the refuted root write -> node 1 onward inherits GOLD, not the poison.
        # node 0 itself is the producer's own state; the FLEET (nodes 1..) never sees the poison.
        env = _fresh_airline_env()  # reset to gold for the downstream chain
        node0_hash = root_hash      # the root's own state (the producer); recorded but not propagated
        node_hashes.append(node0_hash)
        # nodes 1..depth-1 run on gold (clean)
        for k in range(depth - 1):
            _replay_calls_on(env, downstream_calls[k] if k < len(downstream_calls) else [])
            h = _db_hash(env)
            node_hashes.append(h)
            if h != gold:
                corrupted += 1
        return CascadeResult(depth=depth, arm=arm, corrupted_nodes=corrupted,
                             node_hashes=node_hashes,
                             detail=f"root corrupt={root_corrupt} GATED -> chain inherits gold")

    # believe (or adjudicate with a clean root): node k+1 inherits node k's RAW DB.
    node_hashes.append(root_hash)
    if root_corrupt:
        corrupted += 1
    for k in range(depth - 1):
        # env already carries node k's state -> node k+1 builds ON it (inherit the outcome)
        _replay_calls_on(env, downstream_calls[k] if k < len(downstream_calls) else [])
        h = _db_hash(env)
        node_hashes.append(h)
        if h != gold:
            corrupted += 1
    return CascadeResult(depth=depth, arm=arm, corrupted_nodes=corrupted,
                         node_hashes=node_hashes,
                         detail=f"root corrupt={root_corrupt} PROPAGATED down the chain")


# --- the $0 mechanism smoke (synthetic corrupt root, no model) -------------------------

def smoke_synthetic(depth: int = 4) -> int:
    """Prove the compounding mechanism at $0: a corrupt root DB propagates down a believe
    chain (every node inherits the poison -> corrupted grows with depth) but is gated to a
    clean chain under adjudicate (node 1+ inherit gold). No model."""
    print(f"cascade smoke (synthetic corrupt root, $0) — depth {depth}")
    env0 = _fresh_airline_env()
    R = list(env0.tools.db.reservations.keys())[0]
    # a synthetic POISON at the root: cancel R (a real state change) while the "task" required
    # R to stay active -> the root DB diverges from gold. Downstream nodes make no new write,
    # so any corruption at node k is PURELY inherited (the cleanest compounding probe).
    root = [("cancel_reservation", {"reservation_id": R})]

    believe = cascade_state(root, depth=depth, arm="believe")
    adjud = cascade_state(root, depth=depth, arm="adjudicate")

    print(f"  reservation R={R}  (root poison: cancel R; downstream nodes make no new write)")
    print(f"  [   believe] corrupted nodes = {believe.corrupted_nodes}/{depth}  "
          f"({believe.detail})")
    print(f"  [adjudicate] corrupted nodes = {adjud.corrupted_nodes}/{depth}  "
          f"({adjud.detail})")
    payoff = believe.corrupted_nodes - adjud.corrupted_nodes
    print(f"\n  COMPOUNDING PAYOFF(D={depth}) = {payoff}  "
          f"(believe poison reaches all {depth} nodes; the gate keeps the fleet clean)")
    # the mechanism holds iff believe corrupts the whole chain and adjudicate gates it to ~0
    ok = (believe.corrupted_nodes == depth) and (adjud.corrupted_nodes == 0)
    print(f"  => compounding mechanism {'DEMONSTRATED' if ok else 'CHECK'}: under believe "
          f"corruption grows to the full depth; under adjudicate the gate stops it at the root.")
    return 0 if ok else 1


# --- the LIVE cascade (GEMINI-gated): live downstream agents, do they compound or heal? ---

def _pin_dependent_task(tasks, reservation_id, owner):
    """A downstream node's task: act on R (add a bag), pinned to R's owner. Whether the node
    SUCCEEDS depends on the DB state it inherited — gold (R active) lets it succeed; a
    believe-inherited corrupt state (R wrongly cancelled) is where it must either heal or
    compound. Reuses coord_loop's pinning shape."""
    from .coord_loop import _pin_task
    return _pin_task(tasks, reservation_id, goal="addbag")


def run_fanout_live(*, model: str = _DEFAULT_MODEL, max_steps: int = 22, seed: int = 0,
                    depth: int = 3, fanout: int = 2, out_dir: str = "live_results_fanout",
                    budget_usd: float = 30.0) -> int:
    """F1-SUPER-LINEAR (docs/251 NEXT-A): the fan-out tree, not a single chain.

    F1 measured a single chain (linear D−1). The fleet thesis claims a depth-D, fan-out-F
    *tree* of agents touching the poisoned entity has F^D leaves, so one root over-claim caught
    poisons F^D downstream nodes — a SUPER-LINEAR payoff. Here every node spawns `fanout`
    children, all reading/acting on the same poisoned reservation R; we run a LIVE agent at
    each tree node and count corrupted leaves.

    HONEST SCOPE: this measures the BREADTH fanout — the *count of agents blocked by the shared
    poison* grows F^D with the tree (every agent that depends on R fails or stalls and leaves R
    corrupt). It is NOT field-amplification (one corrupt value mutating into many); tau2 airline
    has no clean derived-entity vector for that (see docs/251). The breadth form IS the correct
    fleet model: a poisoned shared resource blocks every agent that touches it, and that set
    grows with the fleet's branching. believe → F^D corrupt; adjudicate (gate gives gold) → 0.

    Cost ≈ Σ_{d=1..depth} fanout^d live runs PER ARM (depth=3,fanout=2 → 2+4+8=14/arm).
    """
    if not _load_gemini_key():
        print("fanout live arm is GEMINI_API_KEY-gated. Use --smoke for the $0 mechanism.")
        return 0
    from tau2.run import get_tasks

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    cache = out / f"fanout_d{depth}_f{fanout}.json"
    if cache.exists():
        row = json.loads(cache.read_text(encoding="utf-8"))
        print(f"(cached) payoff={row.get('payoff')}  believe={row.get('believe_corrupt_leaves')} "
              f"adjudicate={row.get('adjudicate_corrupt_leaves')}")
        return row.get("payoff", 0)

    tasks = get_tasks("airline")
    env0 = _fresh_airline_env()
    R = list(env0.tools.db.reservations.keys())[0]
    owner_uid = env0.tools.db.reservations[R].user_id
    corrupt_db = (lambda e: (_replay_calls_on(e, [("cancel_reservation", {"reservation_id": R})]),
                             e.tools.db.model_dump())[1])(_fresh_airline_env())
    gold_db = _fresh_airline_env().tools.db.model_dump()
    gold_status = None  # active reservation has status=None

    def _r_status(db_dict):
        try:
            return db_dict["reservations"][R].get("status", "?")
        except Exception:
            return "?"

    dep_task = _pin_dependent_task(tasks, R, owner_uid)

    def _run_tree(arm, inherit_db):
        """Run the fan-out tree level by level. Each node is a live agent on `inherit_db`
        acting on R; a LEAF is corrupt iff R is still poisoned at its end. Counts corrupt
        leaves (= the agents the poison blocked). Total nodes run = Σ fanout^d."""
        corrupt_leaves = 0
        total_leaves = fanout ** depth
        nodes_run = 0
        per_level = []
        node_seed = 0
        for d in range(1, depth + 1):
            level_nodes = fanout ** d
            level_corrupt = 0
            for _ in range(level_nodes):
                run = _run_agent_live("airline", dep_task, model=model, max_steps=max_steps,
                                      seed=seed + node_seed, inject_agent_data=inherit_db)
                node_seed += 1
                nodes_run += 1
                calls = _extract_res_calls(run, R)
                env_node = _fresh_airline_env()
                env_node.tools.update_db(inherit_db)
                _replay_calls_on(env_node, calls)
                if _r_status(env_node.tools.db.model_dump()) != gold_status:
                    level_corrupt += 1
            per_level.append({"depth": d, "nodes": level_nodes, "corrupt": level_corrupt})
            if d == depth:
                corrupt_leaves = level_corrupt
        return corrupt_leaves, total_leaves, nodes_run, per_level

    print(f"LIVE fan-out tree: depth={depth} fanout={fanout} -> {fanout**depth} leaves/arm, "
          f"R={R} (root poison: R cancelled)")
    bel_corrupt, leaves, bel_nodes, bel_levels = _run_tree("believe", corrupt_db)
    adj_corrupt, _, adj_nodes, adj_levels = _run_tree("adjudicate", gold_db)
    payoff = bel_corrupt - adj_corrupt
    row = {
        "depth": depth, "fanout": fanout, "leaves": leaves, "reservation": R,
        "believe_corrupt_leaves": bel_corrupt, "adjudicate_corrupt_leaves": adj_corrupt,
        "payoff": payoff, "believe_nodes_run": bel_nodes, "adjudicate_nodes_run": adj_nodes,
        "believe_levels": bel_levels, "adjudicate_levels": adj_levels,
    }
    cache.write_text(json.dumps(row, indent=2), encoding="utf-8")
    bel_summary = [(l["depth"], "%d/%d" % (l["corrupt"], l["nodes"])) for l in bel_levels]
    print(f"  [   believe] corrupt leaves = {bel_corrupt}/{leaves}  (per level: {bel_summary})")
    print(f"  [adjudicate] corrupt leaves = {adj_corrupt}/{leaves}  (inherited gold)")
    print(f"\n  SUPER-LINEAR PAYOFF(D={depth},F={fanout}) = {payoff}  "
          f"(= F^D = {fanout}^{depth} corrupt leaves the gate prevents, if believe poisons all)")
    return payoff


def run_cascade_live(*, model: str = _DEFAULT_MODEL, max_steps: int = 25, seed: int = 0,
                     depth: int = 3, out_dir: str = "live_results_cascade",
                     budget_usd: float = 30.0) -> int:
    """Live F1: a corrupt root, then `depth-1` LIVE downstream agents that inherit either the
    raw (believe) or gold (adjudicate) DB and ACT on it. Measures, per arm, how many live
    nodes end corrupt (db != gold) — the live test of compound-vs-self-heal (docs/236 crux).

    Each downstream node runs ONCE PER ARM (believe-inherit vs gold-inherit), so cost ≈
    2×(depth-1) live runs + 1 root run per chain.
    """
    if not _load_gemini_key():
        print("cascade live arm is GEMINI_API_KEY-gated. Use --smoke for the $0 mechanism.")
        return 0
    from tau2.run import get_tasks

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    cache = out / f"cascade_d{depth}.json"
    if cache.exists():
        row = json.loads(cache.read_text(encoding="utf-8"))
        print(f"(cached) {json.dumps(row, indent=2)[:600]}")
        return row.get("payoff", 0)

    tasks = get_tasks("airline")
    env0 = _fresh_airline_env()
    R = list(env0.tools.db.reservations.keys())[0]
    owner_uid = env0.tools.db.reservations[R].user_id
    gold = _db_hash(_fresh_airline_env())

    # ROOT: corrupt R (cancel it) — the poison. (Synthetic root keeps the experiment cheap +
    # deterministic; the natural-over-claim root is the docs/233 result, already measured.)
    root_calls = [("cancel_reservation", {"reservation_id": R})]
    env_root = _fresh_airline_env(); _replay_calls_on(env_root, root_calls)
    corrupt_db = env_root.tools.db.model_dump()   # believe nodes inherit THIS
    gold_db = _fresh_airline_env().tools.db.model_dump()  # adjudicate nodes inherit THIS

    dep_task = _pin_dependent_task(tasks, R, owner_uid)

    def _r_status(db_dict) -> str:
        """R's status in a DB dump — the ENTITY-LEVEL corruption witness. The poison is
        'R is wrongly cancelled'; a node is CORRUPTED iff R is still cancelled at its end,
        HEALED iff R is active again. This is precise (it measures the specific corruption),
        unlike a whole-DB hash (which conflates legitimate task progress with the poison) and
        unlike db_match (which compares to a gold built on the SAME injected corruption, so it
        can't see that the start itself was wrong — evaluator_env.py:92-101)."""
        try:
            return db_dict["reservations"][R].get("status", "?")
        except Exception:
            return "?"

    gold_status = _r_status(gold_db)  # R's correct status (active)

    def _run_chain(arm: str, inherit_db):
        """Run depth-1 live nodes, each inheriting `inherit_db`, acting on R. A node is corrupt
        iff R is STILL in the poisoned (cancelled) state at the node's end — i.e. the node
        inherited the corruption and did not heal it. (Each node runs fresh on the inherited DB
        to isolate the inheritance effect per hop.)"""
        corrupted = 0
        per_node = []
        for k in range(depth - 1):
            run = _run_agent_live("airline", dep_task, model=model, max_steps=max_steps,
                                  seed=seed + k, inject_agent_data=inherit_db)
            ri = getattr(run, "reward_info", None)
            dbm = getattr(getattr(ri, "db_check", None), "db_match", None) if ri else None
            calls = _extract_res_calls(run, R)
            # the node's end world = inherited DB + its own calls
            env_node = _fresh_airline_env()
            env_node.tools.update_db(inherit_db)
            _replay_calls_on(env_node, calls)
            end_status = _r_status(env_node.tools.db.model_dump())
            corrupt = (end_status != gold_status)   # R still in the poisoned state -> corrupt
            if corrupt:
                corrupted += 1
            per_node.append({"node": k + 1, "db_match_vs_taskgold": dbm,
                             "R_end_status": end_status, "R_gold_status": gold_status,
                             "corrupted": corrupt, "calls": [n for n, _ in calls]})
        return corrupted, per_node

    print(f"LIVE cascade depth={depth}, R={R} (root: cancel R = poison)")
    bel_corrupt, bel_nodes = _run_chain("believe", corrupt_db)
    adj_corrupt, adj_nodes = _run_chain("adjudicate", gold_db)
    payoff = bel_corrupt - adj_corrupt
    row = {
        "depth": depth, "reservation": R, "gold_hash": gold[:12],
        "believe_corrupted_nodes": bel_corrupt, "adjudicate_corrupted_nodes": adj_corrupt,
        "payoff": payoff, "believe_nodes": bel_nodes, "adjudicate_nodes": adj_nodes,
    }
    cache.write_text(json.dumps(row, indent=2), encoding="utf-8")
    print(f"  [   believe] live nodes that stayed CORRUPT (did not heal) = {bel_corrupt}/{depth-1}")
    print(f"  [adjudicate] live nodes that stayed CORRUPT = {adj_corrupt}/{depth-1}  (inherited gold)")
    print(f"\n  LIVE COMPOUNDING PAYOFF(D={depth}) = {payoff}")
    print("  believe nodes (node, R_end_status, corrupted):",
          [(n['node'], n['R_end_status'], n['corrupted']) for n in bel_nodes])
    print("  adjudicate nodes:",
          [(n['node'], n['R_end_status'], n['corrupted']) for n in adj_nodes])
    print("  > if believe nodes stay CORRUPT (R cancelled) and adjudicate stay CLEAN (R active),")
    print("    the fleet thesis holds LIVE: corruption a self-healing-LLM cannot launder out of STATE.")
    return payoff


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="F1 cascade-depth (docs/245)")
    ap.add_argument("--smoke", action="store_true", help="$0 synthetic state-cascade mechanism")
    ap.add_argument("--live", action="store_true", help="PAID live cascade chain (GEMINI-gated)")
    ap.add_argument("--fanout-live", action="store_true",
                    help="PAID live FAN-OUT tree — the F^D super-linear payoff (docs/251 NEXT-A)")
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--fanout", type=int, default=2, help="children per node (the F in F^D)")
    ap.add_argument("--max-steps", type=int, default=22)
    ap.add_argument("--model", default=_DEFAULT_MODEL)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.smoke:
        return smoke_synthetic(depth=args.depth)
    if args.fanout_live:
        run_fanout_live(model=args.model, max_steps=args.max_steps, depth=args.depth,
                        fanout=args.fanout, out_dir=args.out or "live_results_fanout")
        return 0
    if args.live:
        run_cascade_live(model=args.model, max_steps=args.max_steps, depth=args.depth,
                         out_dir=args.out or "live_results_cascade")
        return 0
    print("Use --smoke for the $0 mechanism, or --live --depth D for the paid live cascade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
