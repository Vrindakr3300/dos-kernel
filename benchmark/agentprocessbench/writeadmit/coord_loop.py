"""Item 4 — the multi-agent COORDINATION A/B: arbiter-vs-naive on a shared tau2 DB.

THE OTHER VALUE HALF-PLANE (docs/209 registry Item 4; the sibling of docs/228's
write-admission). docs/228 measured the referee-OVER-CLAIMS payoff (J=5 over-claims a
gate blocked before a peer inherited). THIS measures the referee-BETWEEN-AGENTS payoff:
two concurrent live agents mutate the SAME tau2 reservation; the naive flow lets the
second clobber the first; the dos.arbiter serializes them so BOTH land. docs/190 measured
this as a RATE (collisions/1k writes); this is the PAYOFF (clobbers structurally prevented),
with the gold DB-HASH as the witness — the agent authors zero bytes of it.

THE COMPOSITION PRIMITIVE (verified on the tau2-bench clone):
  an agent's "effect" = its tool-call sequence (in `run.messages`). The tau2 env applies
  a tool-call by running it against the env's in-memory DB (`environment.set_state` extracts
  (tool_call, tool_message) pairs and replays each). So to COMPOSE two agents' effects on
  ONE shared DB we build one env and replay A1's calls then A2's calls. The DB-hash of the
  composed env is ground truth.

  * NAIVE arm  — replay A1's mutating calls, then A2's, on one shared DB, in arrival order,
    NO coordination. A2's calls were computed against the ORIGINAL DB (it never saw A1's
    change), so a blind replay of both can DROP A1's edit (last-write-wins on the shared
    entity) → the composed hash ≠ the serialized-correct hash → a real clobber.
  * ARBITER arm — each agent leases the entity-region `reservations/<id>` via
    `dos.arbiter.arbitrate` before its mutation is applied. Two agents on the same
    reservation produce OVERLAPPING trees → the arbiter REFUSES the second until the first
    releases → they serialize → both mutations land coherently.

PAYOFF J = count of (entity contended by ≥2 agents) where the naive arm lost an edit
(composed hash ≠ serial hash) AND the arbiter arm did not (it serialized). A clobber
structurally prevented, read off the DB-hash — not a re-projected rate (docs/179).

KEY→REGION MAPPER (the registry's flagged hard part — it is trivial): a DB entity is a
path-like region string `reservations/<id>`, so two agents touching the same reservation
produce overlapping `requested_tree`s and `_tree.prefixes_collide` refuses the second. No
new arbiter machinery.

Gated behind GEMINI_API_KEY (the live arm spends tokens). The $0 deterministic smoke
(`smoke_synthetic`) proves the composition + arbiter mechanics with hand-built tool-calls,
no model — run it first.
"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Reuse the live key loader + the natural-sample plumbing from the write-admit driver.
from .live_loop import _load_gemini_key, _DEFAULT_MODEL


# --- the arbiter region mapper (the "hard part", which is one line) --------------------

def reservation_region(reservation_id: str) -> list[str]:
    """A DB entity as a path-like arbiter region. Two agents on the same reservation
    produce overlapping trees -> `dos.arbiter` refuses the second (serializes)."""
    return [f"reservations/{reservation_id}"]


def arbiter_admits(region: list[str], live_leases: list[dict]) -> bool:
    """Would dos.arbiter ADMIT a lease on `region` given the live leases? Pure, no I/O.

    Uses the real `arbitrate` with `force` off; ACQUIRE => admit, any refuse => deny. This
    is the same disjointness verdict the live `dos lease-lane` uses, exercised in-process.
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


# --- the tau2 shared-DB composition primitive -----------------------------------------

@dataclass
class AgentEffect:
    """One agent's mutation = the tool-calls it issued + the reservation it targeted."""
    owner: str
    reservation_id: str
    tool_calls: list  # the (ToolCall, ToolMessage) pairs, or raw messages to replay
    answer: str = ""


def _fresh_airline_env():
    """Build a fresh airline tau2 env (its own DB) we can replay tool-calls onto."""
    from tau2.domains.airline.environment import get_environment
    return get_environment()


def _db_hash(env) -> Optional[str]:
    return env.get_db_hash()


def _replay_calls_on(env, tool_calls) -> int:
    """Apply a sequence of (tool_name, kwargs) mutations to `env`'s DB (the composition
    step). The replay method is `make_tool_call(name, **kwargs)` (verified on the clone).
    Returns the count of calls that applied without error. A call that errors makes no
    state change (the live-env semantics — e.g. a stale call onto an entity another agent
    already cancelled)."""
    applied = 0
    for name, kwargs in tool_calls:
        try:
            env.make_tool_call(name, requestor="assistant", **kwargs)
            applied += 1
        except Exception:
            continue  # stale/invalid call -> no state change (this IS the lost update)
    return applied


# --- the A/B fold ----------------------------------------------------------------------

@dataclass
class CoordResult:
    contended_entity: str
    n_agents: int
    naive_clobbered: bool      # composed-both hash != serialized-correct hash
    arbiter_serialized: bool   # the arbiter refused the 2nd concurrent lease
    j: int                     # 1 if naive lost an edit AND arbiter prevented it
    detail: str = ""


def coordinate(effects: list[AgentEffect], serial_effects: list[AgentEffect] | None = None) -> CoordResult:
    """Run both arms over effects that target the SAME reservation. Builds tau2 envs
    in-process (no model — the model ran upstream to PRODUCE the effects).

    NAIVE  = both agents' calls (each computed against the ORIGINAL DB) replayed blind on
             one shared DB. The 2nd agent's stale calls land on a DB the 1st already changed
             → a stale call can error (apply 0) = its update is LOST. -> naive_hash.
    SERIAL = the arbiter's outcome: the 2nd agent ran AFTER seeing the 1st's commit, so its
             calls are RE-DERIVED against the post-1st state. Caller supplies `serial_effects`
             (the re-run 2nd agent); if absent we fall back to the same calls (only honest
             when the effects don't actually conflict). -> serial_hash.

    A clobber = naive_hash != serial_hash (the blind compose lost/garbled an update the
    serialized compose kept). The arbiter PREVENTS it by refusing the 2nd concurrent lease.
    """
    assert effects, "need at least one effect"
    entity = effects[0].reservation_id

    # NAIVE: all effects' calls replayed onto one shared DB, back to back (stale 2nd).
    env_naive = _fresh_airline_env()
    naive_applied = [(_replay_calls_on(env_naive, e.tool_calls), len(e.tool_calls)) for e in effects]
    naive_hash = _db_hash(env_naive)

    # SERIAL: the serialized (arbiter) outcome — the 2nd agent re-derived post-1st.
    env_serial = _fresh_airline_env()
    serial = serial_effects if serial_effects is not None else effects
    serial_applied = [(_replay_calls_on(env_serial, e.tool_calls), len(e.tool_calls)) for e in serial]
    serial_hash = _db_hash(env_serial)

    # ARBITER: simulate two agents contending for the SAME region. The first acquires; the
    # second is REFUSED while the first holds (then would retry after release => serialize).
    region = reservation_region(entity)
    first_lease = [{"lane": region[0], "kind": "keyword", "tree": region, "owner": effects[0].owner}]
    arbiter_refused_second = (len(effects) >= 2) and (not arbiter_admits(region, first_lease))

    # A genuine clobber is DIRECTIONAL: the naive arm let the 2nd agent apply a STALE write
    # that the serialized 2nd agent (seeing the 1st's commit) correctly did NOT make. So the
    # 2nd agent's applied-mutation count must be STRICTLY GREATER under naive than serial AND
    # the resulting states must differ. (A symmetric `naive_hash != serial_hash` over-counts:
    # if the SERIAL arm happened to mutate more — pure run-to-run variance, not a lost update —
    # that is not a clobber the arbiter prevents. Caught live on pair 1OWO6T: serial added a
    # bag the naive run didn't → an artifact, correctly excluded here.)
    second_naive_applied = naive_applied[1][0] if len(naive_applied) >= 2 else 0
    second_serial_applied = serial_applied[1][0] if len(serial_applied) >= 2 else 0
    stale_write_let_through = second_naive_applied > second_serial_applied
    naive_clobbered = (naive_hash != serial_hash) and stale_write_let_through
    j = 1 if (naive_clobbered and arbiter_refused_second) else 0
    return CoordResult(
        contended_entity=entity, n_agents=len(effects),
        naive_clobbered=naive_clobbered, arbiter_serialized=arbiter_refused_second,
        j=j,
        detail=(f"naive={naive_hash[:12] if naive_hash else None} "
                f"serial={serial_hash[:12] if serial_hash else None} "
                f"naive_applied={[a for a, _ in naive_applied]} "
                f"serial_applied={[a for a, _ in serial_applied]} "
                f"stale_write_let_through={stale_write_let_through}"),
    )


# --- the LIVE 2-agent causal arm (GEMINI-gated) ---------------------------------------

# Reservation-mutating tau2 airline tools (the write family that can clobber).
_RES_MUTATORS = {
    "cancel_reservation", "update_reservation_flights",
    "update_reservation_baggages", "update_reservation_passengers", "book_reservation",
}


def _extract_res_calls(run, reservation_id: str):
    """Pull the agent's mutating tool-calls that targeted `reservation_id`, as
    (tool_name, kwargs) pairs ready for `make_tool_call` replay. Reads the live run's
    messages (the agent authored the calls; the env authored the results — we replay the
    calls to recompose the effect)."""
    calls = []
    msgs = run.get_messages() if hasattr(run, "get_messages") else (getattr(run, "messages", []) or [])
    for m in msgs:
        for tc in (getattr(m, "tool_calls", None) or []):
            name = getattr(tc, "name", None)
            args = getattr(tc, "arguments", None) or {}
            if name in _RES_MUTATORS and args.get("reservation_id") == reservation_id:
                calls.append((name, dict(args)))
    return calls


def _run_agent_live(domain, task, *, model, max_steps, seed, inject_agent_data=None):
    """Run one agent live; optionally inject a starting DB state (the post-A1 state, so A2
    is RE-DERIVED against what A1 left — the faithful serialized outcome)."""
    from tau2.run import run_single_task
    from tau2.data_model.simulation import TextRunConfig
    from tau2.data_model.tasks import InitialState, InitializationData

    t = task
    if inject_agent_data is not None:
        t = task.model_copy(deep=True)
        t.initial_state = InitialState(
            initialization_data=InitializationData(agent_data=inject_agent_data))
    cfg = TextRunConfig(
        domain=domain, agent="llm_agent", llm_agent=model,
        llm_args_agent={"temperature": 0.0, "reasoning_effort": "disable"},
        user="user_simulator", llm_user=model, llm_args_user={"temperature": 0.0},
        max_steps=max_steps,
    )
    return run_single_task(cfg, t, seed=seed)


def run_coord_live(*, model: str = _DEFAULT_MODEL, max_steps: int = 30, seed: int = 0,
                   pairs: int = 3, out_dir: str = "live_results_coord", budget_usd: float = 30.0) -> int:
    """The live causal coordination A/B. For each conflict pair on a shared reservation R:
      A1 runs (cancels/changes R) -> capture A1's effect, get post-A1 DB.
      A2-naive runs on ORIGINAL state -> its calls are STALE (computed before A1).
      A2-serial runs on POST-A1 state (injected) -> coherent (the arbiter's outcome).
      NAIVE  hash = replay A1's + A2-naive's calls on one DB.
      SERIAL hash = replay A1's + A2-serial's calls on one DB.
      J += 1 if naive != serial (a clobber) — the arbiter, refusing the 2nd concurrent
      lease, would have produced the SERIAL state.

    Resumable per-pair JSON cache; out_dir gitignored. Returns total live J.
    """
    if not _load_gemini_key():
        print("coord live arm is GEMINI_API_KEY-gated. Use --smoke for the $0 mechanism.")
        return 0
    from tau2.run import get_tasks

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    tasks = get_tasks("airline")
    # Conflict tasks: A1 = a CANCEL-shaped task, A2 = a CHANGE-shaped task, both on one R.
    # We pick reservations and synthesize the two agents' GOALS via the task user-prompt by
    # reusing real airline tasks but pinning both agents to the same reservation id.
    # (Simplest faithful conflict: A1 cancels R; A2 adds a bag to R.)
    env0 = _fresh_airline_env()
    res_ids = [r for r in env0.tools.db.reservations.keys()]
    # F2 STEP 1 (docs/245): prefer the NATURAL contention sites — reservations that
    # ≥2 independent tau2 tasks target in their gold actions — over the first-N PIN.
    # This is what kills objection O2 ("your collisions are constructed"): the
    # conflict pairs now fall OUT of the real task distribution (measured 2.35%
    # natural pairwise rate, 18 sites), they are not hand-picked. Falls back to the
    # pin only if the predictor finds no natural contention (it would also have told
    # us to KILL the live build).
    try:
        from .natural_collisions import contended_reservation_ids
        natural = [r for r in contended_reservation_ids("airline") if r in env0.tools.db.reservations]
    except Exception:
        natural = []
    chosen = (natural or res_ids)[:pairs]
    if natural:
        print(f"[F2] drawing {min(pairs, len(natural))} conflict pair(s) from "
              f"{len(natural)} NATURAL contention sites (not pinned) — kills O2.")

    total_j = 0
    rows = []
    for n, R in enumerate(chosen, 1):
        cache = out / f"pair_{R}.json"
        if cache.exists():
            row = json.loads(cache.read_text(encoding="utf-8"))
            print(f"  [{n}/{len(chosen)}] R={R} (cached) J={row.get('j')}")
            rows.append(row); total_j += row.get("j", 0); continue
        try:
            row = _run_one_pair(tasks, R, model=model, max_steps=max_steps, seed=seed)
        except Exception as e:
            row = {"reservation": R, "error": f"{type(e).__name__}: {e}"}
        cache.write_text(json.dumps(row, indent=2), encoding="utf-8")
        print(f"  [{n}/{len(chosen)}] R={R}  J={row.get('j')}  "
              f"naive_clobbered={row.get('naive_clobbered')}  err={row.get('error','')[:40]}")
        rows.append(row); total_j += row.get("j", 0)

    ok = [r for r in rows if "error" not in r]
    clob = [r for r in ok if r.get("naive_clobbered")]
    print(f"\n=== COORDINATION LIVE A/B (airline, shared reservation) ===")
    print(f"  conflict pairs run: {len(ok)}   (errors {len(rows)-len(ok)})")
    print(f"  naive clobbered:    {len(clob)}")
    print(f"  arbiter-prevented (J): {total_j}   <<< coordination PAYOFF off the DB-hash")
    return total_j


def _run_one_pair(tasks, R, *, model, max_steps, seed):
    """One conflict pair on reservation R. A1 cancels R; A2 adds a bag to R."""
    # We pin both agents to R by using a task whose user wants exactly this on R. The
    # simplest faithful realization runs the agents on a task and replays only the calls
    # that hit R; but to GUARANTEE both touch R we drive the mutations directly as the
    # agents' GOAL via a thin task prompt. Here we use the deterministic effect the agent
    # WOULD produce (cancel / add-bag) — the live agent decides HOW (which tool args), the
    # conflict is structural. (A1 and A2 are independent live runs.)
    a1_task = _pin_task(tasks, R, goal="cancel")
    a2_task = _pin_task(tasks, R, goal="addbag")

    a1_run = _run_agent_live("airline", a1_task, model=model, max_steps=max_steps, seed=seed)
    a1_calls = _extract_res_calls(a1_run, R)

    # post-A1 DB (apply A1's calls to a fresh env, dump it for injection into A2-serial)
    env_a1 = _fresh_airline_env(); _replay_calls_on(env_a1, a1_calls)
    post_a1 = env_a1.tools.db.model_dump()

    a2_naive_run = _run_agent_live("airline", a2_task, model=model, max_steps=max_steps, seed=seed)
    a2_naive_calls = _extract_res_calls(a2_naive_run, R)
    a2_serial_run = _run_agent_live("airline", a2_task, model=model, max_steps=max_steps,
                                    seed=seed, inject_agent_data=post_a1)
    a2_serial_calls = _extract_res_calls(a2_serial_run, R)

    a1_eff = AgentEffect("agent-1", R, a1_calls)
    res = coordinate([a1_eff, AgentEffect("agent-2", R, a2_naive_calls)],
                     serial_effects=[a1_eff, AgentEffect("agent-2", R, a2_serial_calls)])
    return {
        "reservation": R, "j": res.j, "naive_clobbered": res.naive_clobbered,
        "arbiter_serialized": res.arbiter_serialized, "detail": res.detail,
        "a1_calls": [n for n, _ in a1_calls],
        "a2_naive_calls": [n for n, _ in a2_naive_calls],
        "a2_serial_calls": [n for n, _ in a2_serial_calls],
    }


def _pin_task(tasks, reservation_id, *, goal):
    """Build a task whose user-goal targets `reservation_id` with `goal` (cancel|addbag).

    The user-simulator reads `task.user_scenario.instructions` (a UserInstructions object,
    rendered via str()). We mutate its `reason_for_call` + `task_instructions` IN PLACE so
    the type is preserved (structured vs plain), pinning both the reservation and the action
    so the two agents provably contend on the same entity.
    """
    base = tasks[0].model_copy(deep=True)
    # Pin the user IDENTITY to R's real owner — else the agent rightly refuses to mutate
    # someone else's reservation and the conflict never fires (a silent J=0 trap).
    owner = _owner_identity(reservation_id)
    who = f"You are {owner['name']} (user id {owner['user_id']})."
    if goal == "cancel":
        reason = f"You want to cancel your reservation {reservation_id}."
        steps = (f"{who} Ask the agent to cancel reservation {reservation_id}. Provide your "
                 f"user id if asked. If the agent asks for confirmation, confirm. Request nothing else.")
    else:
        reason = f"You want to add one extra checked bag to reservation {reservation_id}."
        steps = (f"{who} Ask the agent to add exactly one extra checked bag to reservation "
                 f"{reservation_id}, paying with a payment method on file. Provide your user id "
                 f"if asked. Request nothing else.")
    instr = getattr(getattr(base, "user_scenario", None), "instructions", None)
    if instr is not None:
        for f, v in (("reason_for_call", reason), ("task_instructions", steps),
                     ("known_info", who), ("unknown_info", None)):
            if hasattr(instr, f):
                try:
                    setattr(instr, f, v)
                except Exception:
                    pass
    return base


def _owner_identity(reservation_id: str) -> dict:
    """The real (name, user_id) that owns a reservation — so the pinned user is authorized."""
    env = _fresh_airline_env()
    r = env.tools.db.reservations[reservation_id]
    uid = r.user_id
    u = env.tools.db.users[uid]
    nm = getattr(u, "name", None)
    name = f"{getattr(nm,'first_name','')} {getattr(nm,'last_name','')}".strip() if nm else uid
    return {"user_id": uid, "name": name or uid}


# --- the $0 deterministic smoke (no model) --------------------------------------------

def smoke_synthetic() -> int:
    """Prove the ARBITER mechanic at $0: two agents contending for the same reservation
    region are serialized (the 2nd lease refused while the 1st holds); two on DIFFERENT
    reservations are both admitted. This is the coordination INVARIANT, no model needed."""
    print("coordination smoke (synthetic, $0) — arbiter region serialization")
    # same entity -> 2nd refused
    region = reservation_region("4WQ150")
    held = [{"lane": region[0], "kind": "keyword", "tree": region, "owner": "agent-1"}]
    same = arbiter_admits(region, held)
    # different entity -> admitted
    other = reservation_region("VAAOXJ")
    diff = arbiter_admits(other, held)
    print(f"  agent-2 on SAME reservation 4WQ150 (agent-1 holds): admit={same}  (expect False = serialized)")
    print(f"  agent-2 on OTHER reservation VAAOXJ:                admit={diff}  (expect True  = disjoint, concurrent)")
    ok = (same is False) and (diff is True)
    print(f"  => arbiter region invariant {'HOLDS' if ok else 'FAILED'}: refuses a")
    print(f"     same-entity concurrent write, admits a disjoint one.")

    # --- the LOST-UPDATE mechanism, on the real airline DB ($0) ------------------------
    # Two agents both target reservation R. A1 cancels R. A2 (computed against the ORIGINAL
    # R, before A1) tries to update R's baggages. NAIVE: A1 cancels, then A2's update lands
    # on a cancelled R -> errors -> A2's work LOST, AND A1's cancel is the only effect.
    # SERIAL (A2 re-derived post-A1): A2 sees R already cancelled and does nothing coherent
    # (e.g. informs the user) -> the states DIFFER. The arbiter forces serial.
    print("\n  lost-update on the real airline DB (A1 cancels R; A2's stale update on R):")
    from tau2.domains.airline.environment import get_environment
    env0 = get_environment()
    R = list(env0.tools.db.reservations.keys())[0]
    a1 = AgentEffect(owner="agent-1", reservation_id=R,
                     tool_calls=[("cancel_reservation", {"reservation_id": R})])
    # A2 (stale): add a bag to R — valid against the ORIGINAL R, stale after A1's cancel.
    a2_stale = AgentEffect(owner="agent-2", reservation_id=R,
                           tool_calls=[("update_reservation_baggages",
                                        {"reservation_id": R, "total_baggages": 3,
                                         "nonfree_baggages": 1, "payment_id": _first_payment(env0, R)})])
    # A2 (re-derived serial): seeing R already cancelled, it makes NO mutation (coherent).
    a2_serial = AgentEffect(owner="agent-2", reservation_id=R, tool_calls=[])
    res = coordinate([a1, a2_stale], serial_effects=[a1, a2_serial])
    print(f"    {res.detail}")
    print(f"    naive_clobbered={res.naive_clobbered}  arbiter_serialized={res.arbiter_serialized}  J={res.j}")
    mech_ok = res.arbiter_serialized  # the arbiter must refuse the 2nd concurrent lease
    print(f"  => coordination MECHANISM {'demonstrated' if mech_ok else 'FAILED'}: the arbiter")
    print(f"     serializes the conflicting pair; J counts a clobber it prevents.")
    return 0 if (ok and mech_ok) else 1


def _first_payment(env, reservation_id: str) -> str:
    """A valid payment_id for a reservation (update tools require one). Best-effort."""
    try:
        r = env.tools.db.reservations[reservation_id]
        ph = getattr(r, "payment_history", None) or []
        if ph:
            pid = getattr(ph[0], "payment_id", None) or getattr(ph[0], "id", None)
            if pid:
                return pid
        # fall back to the user's first payment method
        u = env.tools.db.users[r.user_id]
        pm = getattr(u, "payment_methods", {}) or {}
        if pm:
            return list(pm.keys())[0]
    except Exception:
        pass
    return "credit_card_1"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Item 4 — coordination A/B (docs/209 registry)")
    ap.add_argument("--smoke", action="store_true", help="$0 synthetic arbiter-serialization smoke")
    ap.add_argument("--live", action="store_true", help="PAID live 2-agent causal arm (GEMINI-gated)")
    ap.add_argument("--pairs", type=int, default=3, help="conflict pairs (reservations) to run")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--model", default=_DEFAULT_MODEL)
    ap.add_argument("--out", default="live_results_coord")
    ap.add_argument("--budget", type=float, default=30.0)
    args = ap.parse_args(argv)
    if args.smoke:
        return smoke_synthetic()
    if args.live:
        j = run_coord_live(model=args.model, max_steps=args.max_steps, pairs=args.pairs,
                           out_dir=args.out, budget_usd=args.budget)
        return 0
    print("Use --smoke for the $0 mechanic, or --live --pairs N for the paid causal arm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
