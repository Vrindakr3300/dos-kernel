"""The LIVE confirmation arm — headless `claude -p` agents on a shared tau2 DB.

The user asked to "also use headless claude sessions": this arm drives the two
contending agents as real `claude -p` invocations (the docs/272 forge pattern —
a Claude model named ONLY in the shelled command, never imported), then replays
the tool-calls THE MODEL CHOSE onto the real tau2 DB and measures J off the
DB-hash. This anchors the deterministic numbers (coord.py) to live model behavior:
the agents DECIDE which tool to call; the conflict is structural (both target the
same entity); the witness is non-forgeable (the env authors the hash).

Causal structure (identical to docs/233's live arm, Claude instead of Gemini):
  A1  — given the entity's PRE-state + a CANCEL goal, chooses a tool call.
  A2-naive  — given the SAME PRE-state (it never saw A1's change) + a MODIFY goal,
              chooses a tool call. Its call is STALE: computed before A1's cancel.
  A2-serial — given the POST-A1 state (the entity now cancelled) + the same MODIFY
              goal, chooses a tool call. Re-derived: it should see the cancel and
              decline / no-op. This is the SERIALIZED (arbiter) outcome.

  NAIVE composite  = replay A1's calls then A2-naive's calls on one DB.
  SERIAL composite = replay A1's calls then A2-serial's calls on one DB.
  J += 1 iff the naive composite clobbered (incoherent-merge OR dropped-write vs
         serial) AND the arbiter would refuse A2's concurrent lease.

GEMINI-free and network-free beyond the local `claude` CLI. Each agent decision is
cached per (entity, role) so the arm is resumable and cheap to re-confirm.
"""
from __future__ import annotations

import io
import os
import re
import json
import shutil
import subprocess
import contextlib
from pathlib import Path
from typing import Optional

from .coord import (
    DomainSpec, DOMAINS, entity_region, arbiter_admits, _fresh_env, _apply,
)

_CLAUDE = shutil.which("claude") or "claude"
_DEFAULT_MODEL = os.environ.get("TAU2COORD_CLAUDE_MODEL", "claude-haiku-4-5-20251001")


# --- the headless claude agent ---------------------------------------------------------

def _entity_snapshot(env, spec: DomainSpec, entity_id: str) -> dict:
    """A small, model-readable snapshot of the entity's CURRENT state (status + key fields)
    so the agent can decide whether its goal is still actionable (the TOCTOU read)."""
    coll = getattr(env.tools.db, spec.collection)
    obj = coll.get(entity_id) if hasattr(coll, "get") else coll[entity_id]
    snap = {"id": entity_id, "collection": spec.collection}
    for f in ("status", "user_id"):
        v = getattr(obj, f, None)
        if v is not None:
            snap[f] = v
    return snap


def _tool_catalog(spec: DomainSpec) -> str:
    """The mutating tools the agent may choose from, per domain (closed set)."""
    if spec.name == "airline":
        return ("cancel_reservation(reservation_id); "
                "update_reservation_baggages(reservation_id,total_baggages,nonfree_baggages,payment_id)")
    if spec.name == "retail":
        return ("cancel_pending_order(order_id,reason); "
                "modify_pending_order_address(order_id,address1,address2,city,state,country,zip)")
    return "(domain tools)"


def _ask_claude(prompt: str, *, model: str, timeout: int = 180) -> str:
    """One headless `claude -p` turn. Returns the raw stdout (the model's answer)."""
    proc = subprocess.run(
        [_CLAUDE, "-p", prompt, "--model", model],
        capture_output=True, text=True, timeout=timeout,
    )
    return (proc.stdout or "").strip()


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_tool_call(text: str) -> Optional[tuple[str, dict]]:
    """Extract the agent's chosen (tool, kwargs) from its reply. Returns None if the agent
    declined (no actionable tool) — the coherent re-derived outcome when the entity is gone.

    The agent AUTHORS this (forgeable); it never moves the J verdict, which is read off the
    env DB-hash. A malformed/declined reply -> no call -> no state change (fail-safe)."""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    tool = obj.get("tool")
    if not tool or str(tool).lower() in ("none", "decline", "no_action"):
        return None
    args = obj.get("args") or {}
    if not isinstance(args, dict):
        return None
    return (str(tool), args)


def _agent_decision(spec: DomainSpec, entity_id: str, *, goal: str, state_env,
                    model: str) -> Optional[tuple[str, dict]]:
    """Drive ONE headless claude agent: show it the entity's CURRENT state + a goal, let it
    choose a tau2 tool call (or decline if the goal is no longer actionable). `state_env`
    fixes WHICH state the agent reads (pre- or post-A1) — that read is the TOCTOU point."""
    snap = _entity_snapshot(state_env, spec, entity_id)
    goal_text = {
        "cancel": f"The customer wants to CANCEL {spec.collection[:-1]} {entity_id}.",
        "modify": (f"The customer wants to MODIFY {spec.collection[:-1]} {entity_id} "
                   f"({'add one extra checked bag' if spec.name=='airline' else 'change the shipping address'})."),
    }[goal]
    prompt = (
        f"You are a customer-service agent for a {spec.name} system. Current state of the "
        f"entity you must act on:\n{json.dumps(snap)}\n\n{goal_text}\n\n"
        f"Available tools: {_tool_catalog(spec)}\n\n"
        f"RULES: Only act if the goal is still possible given the current state. If the "
        f"entity is already cancelled/closed, the goal is NOT possible — DECLINE.\n\n"
        f"Reply with ONLY a JSON object, no prose, no code fence:\n"
        f'  to act:    {{\"tool\": \"<tool_name>\", \"args\": {{...}}}}\n'
        f'  to decline: {{\"tool\": null, \"reason\": \"<why>\"}}'
    )
    reply = _ask_claude(prompt, model=model)
    call = _parse_tool_call(reply)
    # Backfill required args the model commonly omits (payment_id, address fields), so a
    # well-intentioned ACT is not scored as a decline due to a missing-arg error. The model
    # still authors the DECISION to act; we only complete the boilerplate args.
    if call is not None:
        call = _backfill_args(spec, entity_id, call)
    return call


def _backfill_args(spec: DomainSpec, entity_id: str, call: tuple[str, dict]) -> tuple[str, dict]:
    """Complete the BOILERPLATE args the model should not be inventing (payment_id, address
    fields, the entity id itself), with KNOWN-VALID values, so a genuine DECISION-to-act is
    not scored as a decline merely because the model hallucinated a payment id. We FORCE the
    plumbing (override, not setdefault) but never touch the model's TOOL CHOICE or its
    decision to act vs decline — that is the TOCTOU signal we measure. The arbiter verdict
    and the DB-hash are untouched by this normalization."""
    name, args = call
    args = dict(args)
    if spec.name == "airline" and name == "update_reservation_baggages":
        ref = spec.a2(_fresh_env(spec.name), entity_id)[1]
        # FORCE the structural args to a valid combo (the model only decided to add a bag).
        for k in ("total_baggages", "nonfree_baggages", "payment_id", "reservation_id"):
            args[k] = ref[k]
    if spec.name == "retail" and name == "modify_pending_order_address":
        ref = spec.a2(_fresh_env(spec.name), entity_id)[1]
        for k, v in ref.items():
            args[k] = v  # FORCE a valid address payload (the model only decided to modify).
    args.setdefault("reservation_id" if spec.name == "airline" else "order_id", entity_id)
    if spec.name == "retail" and name == "cancel_pending_order":
        # `reason` is a CLOSED enum ({"no longer needed","ordered by mistake"}); the model's
        # free-text reason ("customer requested...") is rejected. FORCE a valid enum value —
        # the agent decided to CANCEL; the exact reason string is boilerplate, not a decision.
        args["reason"] = "no longer needed"
    return (name, args)


# --- the live A/B over one entity ------------------------------------------------------

def _hash_after(spec: DomainSpec, calls: list[tuple[str, dict]]) -> tuple[str, list[int]]:
    """Replay a list of calls onto a fresh DB; return (db_hash, applied-flags)."""
    env = _fresh_env(spec.name)
    applied = [_apply(env, c) for c in calls if c is not None]
    return env.get_db_hash(), applied


def run_one_live(spec: DomainSpec, entity_id: str, *, model: str) -> dict:
    """One live conflict pair, three headless-claude decisions (A1, A2-naive, A2-serial),
    J read off the DB-hash."""
    pre_env = _fresh_env(spec.name)  # the PRE-state both A1 and A2-naive read.

    a1 = _agent_decision(spec, entity_id, goal="cancel", state_env=pre_env, model=model)
    a2_naive = _agent_decision(spec, entity_id, goal="modify", state_env=pre_env, model=model)

    # Build the POST-A1 state for A2-serial to read (A1's call applied to a fresh env).
    post_env = _fresh_env(spec.name)
    if a1 is not None:
        _apply(post_env, a1)
    a2_serial = _agent_decision(spec, entity_id, goal="modify", state_env=post_env, model=model)

    # SOLO: A2-naive's chosen call alone on the ORIGINAL DB (did its own check pass -> would
    # it commit?). This is A2's TOCTOU read: it passed, so A2 believes it will succeed.
    _, solo_applied = _hash_after(spec, [a2_naive]) if a2_naive else ("", [])
    a2_solo = sum(solo_applied)

    # A1 alone, to confirm A1's cancel actually landed (else there is no contention).
    _, a1_only = _hash_after(spec, [a1]) if a1 else ("", [])
    a1_applied = sum(a1_only)

    # NAIVE composite: A1 then A2-naive on one DB. Track A2's applied flag positionally.
    naive_hash, naive_applied = _hash_after(spec, [a1, a2_naive])
    serial_hash, _ = _hash_after(spec, [a1, a2_serial])
    # A2's applied flag is the LAST entry (A1 may be None and get filtered out).
    a2_naive_applied = naive_applied[-1] if (a2_naive is not None and naive_applied) else 0

    region = entity_region(spec.collection, entity_id)
    held = [{"lane": region[0], "kind": "keyword", "tree": region, "owner": "agent-1"}]
    arbiter_serialized = not arbiter_admits(region, held)

    incoherent_merge = (naive_hash != serial_hash)
    dropped_write = (a2_solo > a2_naive_applied)
    naive_clobbered = incoherent_merge or dropped_write
    j = 1 if (naive_clobbered and arbiter_serialized) else 0
    return {
        "domain": spec.name, "entity": entity_id, "j": j,
        "naive_clobbered": naive_clobbered, "incoherent_merge": incoherent_merge,
        "dropped_write": dropped_write, "arbiter_serialized": arbiter_serialized,
        "a1_call": a1[0] if a1 else None, "a1_applied": a1_applied,
        "a2_naive_call": a2_naive[0] if a2_naive else None,
        "a2_serial_call": a2_serial[0] if a2_serial else None,
        "a2_solo_applied": a2_solo, "a2_naive_applied": a2_naive_applied,
        "naive_hash": naive_hash, "serial_hash": serial_hash,
    }


def run_live(domains: list[str], pairs_per_domain: int, *, model: str = _DEFAULT_MODEL,
             out_dir: str = "live_results_tau2coord") -> dict:
    """The live headless-claude A/B. Resumable per-(domain,entity) JSON cache; out_dir
    gitignored. Returns the result dict (same shape as the deterministic arm)."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    res: dict = {"domains": {}, "total_pairs": 0, "total_naive_clobbers": 0, "total_j": 0,
                 "model": model}
    for dom in domains:
        spec = DOMAINS[dom]
        env0 = _fresh_env(dom)
        entities = spec.pick_entities(env0)[:pairs_per_domain]
        rows = []
        for e in entities:
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{dom}_{e}")
            cache = out / f"pair_{safe}.json"
            if cache.exists():
                row = json.loads(cache.read_text(encoding="utf-8"))
            else:
                try:
                    row = run_one_live(spec, e, model=model)
                except Exception as ex:
                    row = {"domain": dom, "entity": e, "error": f"{type(ex).__name__}: {ex}"}
                cache.write_text(json.dumps(row, indent=2), encoding="utf-8")
            rows.append(row)
            print(f"  [{dom}] {e:14} J={row.get('j')} clobber={row.get('naive_clobbered')} "
                  f"a1={row.get('a1_call')} a2_naive={row.get('a2_naive_call')} "
                  f"a2_serial={row.get('a2_serial_call')} err={row.get('error','')[:30]}")
        ok = [r for r in rows if "error" not in r]
        naive_clobbers = sum(1 for r in ok if r.get("naive_clobbered"))
        j = sum(r.get("j", 0) for r in ok)
        res["domains"][dom] = {"pairs": len(ok), "naive_clobbers": naive_clobbers,
                               "j": j, "errors": len(rows) - len(ok), "rows": rows}
        res["total_pairs"] += len(ok)
        res["total_naive_clobbers"] += naive_clobbers
        res["total_j"] += j
    return res


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="tau2coord LIVE arm — headless claude agents")
    ap.add_argument("--domains", default="airline,retail")
    ap.add_argument("--pairs", type=int, default=2, help="conflict pairs PER domain")
    ap.add_argument("--model", default=_DEFAULT_MODEL)
    ap.add_argument("--out", default="live_results_tau2coord")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    res = run_live(domains, args.pairs, model=args.model, out_dir=args.out)
    print(f"\n=== tau2coord LIVE A/B (headless claude={args.model}, off the DB-hash) ===")
    print(f"  pairs run:           {res['total_pairs']}")
    print(f"  NAIVE arm clobbers:  {res['total_naive_clobbers']}")
    print(f"  ARBITER-prevented J: {res['total_j']}   <<< live coordination payoff")
    if args.json:
        print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
