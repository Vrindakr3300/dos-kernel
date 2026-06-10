"""The peer-B causal A/B driver (docs/229 §4) — frozen dry-run ($0) + live run (PAID).

WHAT THIS MEASURES
------------------
docs/228 produced J=5 as a COUNTED inheritance. This driver makes it CAUSAL: for each
A-run, it runs a downstream peer B on the SAME tau2 task A ran, under two arms, and reads
B's OWN env db_match. The only thing that differs between arms is the handoff B inherits
(peer_b.handoff): A's raw claim (believe) vs the gate's verdict (adjudicate).

  ΔB = success_rate(B | adjudicate) − success_rate(B | believe)

measured on the OVER-CLAIM slice (A's confident writes the witness refuted) and, as a
control, on the HONEST slice (A's confirmed writes — where the gate is a no-op, so ΔB must
be ≈0 by the control invariant).

WHY SAME-TASK REPLAY (a refinement of docs/229 §3 Design A)
-----------------------------------------------------------
B runs A's OWN task again, inheriting A's handoff as prior context. This needs no bespoke
follow-on task: the dependent work IS the same task. On an over-claim:
  * believe-B is told "X has been done" -> may report "already complete, nothing to do" ->
    inherits the phantom -> B's db_match stays False.
  * adjudicate-B is told "the prior action did NOT land, treat as unchanged" -> actually does
    the work -> B's db_match can become True.
ΔB is then literally: does telling B the truth (vs the phantom) make B complete the same
work correctly more often? That is the compounding-error-prevented quantity, ground-truthed
on both ends by the env DB-hash.

THE CONTROL (the honest slice)
------------------------------
On A's CONFIRMED writes the gate ADMITTED, so believe and adjudicate hand B byte-identical
context (peer_b control invariant). ΔB on that slice should be ≈0 — a built-in falsifier: if
ΔB is large on the control too, the effect is noise, not the handoff.

$0 UNTIL LIVE: `dry_run` folds whatever A-rows exist and asserts the control invariant on
each, with NO model. `run_causal` is gated on GEMINI_API_KEY and drives B live (~2×
per-task cost over the A-slice; resumable per (task, arm)).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .peer_b import AHandoff, BELIEVE, ADJUDICATE, ARMS, handoff, control_invariant_holds
from .live_loop import _load_gemini_key, _DEFAULT_MODEL, _last_assistant_text, _agent_llm_args


def _load_a_rows(a_dir: str) -> list[dict]:
    """Load every cached A-row JSON from a `run_writeadmit` out_dir (skips error rows)."""
    out = []
    p = Path(a_dir)
    if not p.exists():
        return out
    for f in sorted(p.glob("*.json")):
        try:
            row = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "error" in row and row.get("error"):
            continue
        out.append(row)
    return out


def dry_run(a_dir: str) -> int:
    """$0 fold over the A-rows: classify the slices + ASSERT the control invariant. No model.

    Prints how many over-claim vs honest-confirmed A-rows exist (the ΔB numerator/denominator
    targets) and verifies, for every row, that the believe/adjudicate handoff differs IFF the
    gate blocked (the structural guarantee that ΔB's control arm is ≈0). Returns the number of
    over-claim rows found (the live-run target size).
    """
    rows = _load_a_rows(a_dir)
    handoffs = [AHandoff.from_row(r) for r in rows]
    over = [a for a in handoffs if a.is_overclaim]
    honest = [a for a in handoffs if a.confident_write and a.db_match is True]
    noclaim = [a for a in handoffs if not a.confident_write]

    # the structural check: control invariant on EVERY row
    bad = [a for a in handoffs if not control_invariant_holds(a)]

    print(f"=== peer-B dry-run over {a_dir} ({len(rows)} clean A-rows) ===")
    print(f"  OVER-CLAIM A-rows (confident write & db_match==False): {len(over)}   <- ΔB slice")
    print(f"  HONEST   A-rows (confident write & db_match==True):    {len(honest)}   <- control slice")
    print(f"  NO-CLAIM A-rows (nothing to hand off as a write):      {len(noclaim)}")
    print(f"  control-invariant violations: {len(bad)}  (MUST be 0)")
    if bad:
        for a in bad[:5]:
            print(f"    ! {a.domain}/{a.task_id} admit={a.admit} db_match={a.db_match}")
    for a in over:
        print(f"    over-claim: {a.domain}/{a.task_id}  key={a.claim_key}  "
              f"claim={a.claim_text[:70]!r}")
    assert not bad, "control invariant violated — believe/adjudicate must differ IFF blocked"
    return len(over)


# ---------------------------------------------------------------------------------------
# The LIVE causal run. Gated on GEMINI_API_KEY. Drives B on A's own task under both arms.
# ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BRunRow:
    domain: str
    task_id: str
    arm: str
    db_match: object       # B's OWN env witness
    reward: float
    answer_excerpt: str
    a_was_overclaim: bool  # was the seeding A-row an over-claim? (selects the ΔB slice)


def _run_b_once(domain: str, task_id: str, init_state, *, model: str, max_steps: int, seed: int):
    """Drive peer B live on one task with an inherited `init_state` (the arm's handoff)."""
    import time
    from tau2.run import get_tasks, run_single_task
    from tau2.data_model.simulation import TextRunConfig

    tasks = get_tasks(domain)
    base = next((t for t in tasks if str(t.id) == str(task_id)), None)
    if base is None:
        return {"error": "task_id not found"}
    # clone the task with B's inherited initial_state (the handoff). model_copy keeps the
    # task's user_scenario/evaluation_criteria intact so B is graded on the SAME goal as A.
    task = base.model_copy(update={"initial_state": init_state})

    cfg = TextRunConfig(
        domain=domain, agent="llm_agent", llm_agent=model,
        llm_args_agent=_agent_llm_args(model),  # MODEL-AWARE: "disable" flash / "low" pro
        user="user_simulator", llm_user=model, llm_args_user={"temperature": 0.0},
        max_steps=max_steps,
    )
    last_exc = None
    run = None
    for _attempt in range(5):
        try:
            run = run_single_task(cfg, task, seed=seed)
            break
        except Exception as e:  # noqa: BLE001
            last_exc = e
            transient = ("InternalServerError" in type(e).__name__
                         or any(c in str(e) for c in ("503", "500", "502", "429", "overloaded")))
            if transient and _attempt < 4:
                time.sleep(1.5 * (2 ** _attempt))
                continue
            raise
    if run is None:
        raise last_exc
    ri = getattr(run, "reward_info", None)
    db_check = getattr(ri, "db_check", None) if ri is not None else None
    db_match = getattr(db_check, "db_match", None) if db_check is not None else None
    reward = float(getattr(ri, "reward", 0.0)) if ri is not None else 0.0
    answer = _last_assistant_text(run)
    cost = getattr(run, "agent_cost", None)
    return {"db_match": db_match, "reward": reward, "answer_excerpt": answer[:200],
            "agent_cost": cost}


def run_causal(a_dir: str, *, model: str = _DEFAULT_MODEL, max_steps: int = 30,
               seed: int = 0, include_honest: bool = True, limit: int | None = None,
               trust_handoff: bool = False,
               out_dir: str = "live_results_peerb", budget_usd: float = 15.0) -> dict:
    """PAID: drive B on each A-task under both arms, read B's db_match, fold ΔB.

    Runs the OVER-CLAIM A-rows (the ΔB slice) and, if `include_honest`, the CONFIRMED A-rows
    (the control slice). Resumable per `<out_dir>/<domain>__<id>__<arm>.json`. Returns a dict
    with the two success rates + ΔB on each slice. Gated on GEMINI_API_KEY ($0 without it).
    """
    if not _load_gemini_key():
        print("peer-B causal run is gated off — set GEMINI_API_KEY (or have it in .env).")
        return {}

    rows = _load_a_rows(a_dir)
    handoffs = [AHandoff.from_row(r) for r in rows]
    targets = [a for a in handoffs if a.is_overclaim]
    if include_honest:
        targets += [a for a in handoffs if a.confident_write and a.db_match is True]
    if limit is not None:
        targets = targets[:limit]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    posture = "TRUST-HANDOFF (non-re-verifying B)" if trust_handoff else "default (B free to re-verify)"
    print(f"peer-B CAUSAL run — {len(targets)} A-task(s) × {len(ARMS)} arms, model={model}, "
          f"posture={posture}, out={out_dir}")

    b_rows: list[dict] = []
    spent = 0.0
    for n, a in enumerate(targets, 1):
        for arm in ARMS:
            cache = out / f"{a.domain}__{a.task_id}__{arm}.json"
            if cache.exists():
                row = json.loads(cache.read_text(encoding="utf-8"))
                b_rows.append(row)
                print(f"  [{n}/{len(targets)}] {a.domain}/{a.task_id} {arm:>10} (cached) "
                      f"db_match={row.get('db_match')}")
                continue
            if spent >= budget_usd:
                print(f"  ! budget ${budget_usd:.0f} reached — stopping early.")
                return _fold_causal(b_rows, spent)
            init_state = handoff(a, arm, trust_handoff=trust_handoff)
            try:
                res = _run_b_once(a.domain, a.task_id, init_state, model=model,
                                  max_steps=max_steps, seed=seed)
            except Exception as e:  # one bad task must not waste the run
                res = {"error": f"{type(e).__name__}: {e}"}
            row = {
                "domain": a.domain, "task_id": a.task_id, "arm": arm,
                "a_was_overclaim": a.is_overclaim, **res,
            }
            cache.write_text(json.dumps(row, indent=2), encoding="utf-8")
            c = res.get("agent_cost")
            if isinstance(c, (int, float)):
                spent += float(c)
            b_rows.append(row)
            print(f"  [{n}/{len(targets)}] {a.domain}/{a.task_id} {arm:>10}  "
                  f"db_match={row.get('db_match')}  err={row.get('error','')}")

    return _fold_causal(b_rows, spent)


def _success(row: dict) -> bool:
    """B succeeded iff its OWN env witness says the end-state is correct (db_match True)."""
    return row.get("db_match") is True


def _fold_causal(b_rows: list[dict], spent: float) -> dict:
    """Fold B-rows into per-arm success rates + ΔB, on the over-claim and control slices."""
    ok = [r for r in b_rows if "error" not in r or not r.get("error")]

    def rate(slice_rows, arm):
        sub = [r for r in slice_rows if r.get("arm") == arm]
        if not sub:
            return None, 0, 0
        s = sum(1 for r in sub if _success(r))
        return s / len(sub), s, len(sub)

    over = [r for r in ok if r.get("a_was_overclaim")]
    ctrl = [r for r in ok if not r.get("a_was_overclaim")]

    rb_o, sb_o, nb_o = rate(over, BELIEVE)
    ra_o, sa_o, na_o = rate(over, ADJUDICATE)
    rb_c, sb_c, nb_c = rate(ctrl, BELIEVE)
    ra_c, sa_c, na_c = rate(ctrl, ADJUDICATE)

    def fmt(r, s, n):
        return f"{r:.1%} ({s}/{n})" if r is not None else "n/a"

    print("\n=== peer-B CAUSAL fold (docs/229) — ΔB = adjudicate − believe ===")
    print("  OVER-CLAIM slice (A confident-write, witness refuted):")
    print(f"    believe   B success: {fmt(rb_o, sb_o, nb_o)}")
    print(f"    adjudicate B success: {fmt(ra_o, sa_o, na_o)}")
    dB_over = (ra_o - rb_o) if (ra_o is not None and rb_o is not None) else None
    print(f"    ΔB (over-claim) = {dB_over:+.1%}" if dB_over is not None else "    ΔB (over-claim) = n/a")
    print("  CONTROL slice (A honest-confirmed write, gate no-op):")
    print(f"    believe   B success: {fmt(rb_c, sb_c, nb_c)}")
    print(f"    adjudicate B success: {fmt(ra_c, sa_c, na_c)}")
    dB_ctrl = (ra_c - rb_c) if (ra_c is not None and rb_c is not None) else None
    print(f"    ΔB (control)   = {dB_ctrl:+.1%}  (MUST be ≈0)" if dB_ctrl is not None else "    ΔB (control) = n/a")
    # believe-arm self-recovery: an over-claim B that succeeded DESPITE the phantom (kill-2)
    recov = sum(1 for r in over if r.get("arm") == BELIEVE and _success(r))
    print(f"  believe-arm self-recovery on over-claim slice: {recov}/{nb_o} "
          f"(B re-verified the phantom and fixed it on its own)")
    if spent:
        print(f"  approx spend: ${spent:.2f}")
    return {
        "dB_overclaim": dB_over, "dB_control": dB_ctrl,
        "believe_over": rb_o, "adjudicate_over": ra_o,
        "believe_ctrl": rb_c, "adjudicate_ctrl": ra_c,
        "believe_self_recovery": recov, "n_over": nb_o, "n_ctrl": nb_c, "spent": spent,
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="peer-B causal A/B (docs/229)")
    ap.add_argument("--a-dir", required=True, help="a run_writeadmit out_dir of cached A-rows")
    ap.add_argument("--dry-run", action="store_true", help="$0 fold + control-invariant check (no model)")
    ap.add_argument("--live", action="store_true", help="PAID: drive B live under both arms (gated)")
    ap.add_argument("--no-honest", action="store_true", help="skip the honest control slice")
    ap.add_argument("--trust-handoff", action="store_true",
                    help="dispose B to TRUST inherited state (docs/230 localization: the "
                         "non-re-verifying consumer the payoff is predicted to live at)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--budget", type=float, default=15.0)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--model", default=_DEFAULT_MODEL)
    ap.add_argument("--out", default="live_results_peerb")
    args = ap.parse_args(argv)
    if args.dry_run:
        dry_run(args.a_dir)
        return 0
    if args.live:
        run_causal(args.a_dir, model=args.model, max_steps=args.max_steps,
                   include_honest=not args.no_honest, limit=args.limit,
                   trust_handoff=args.trust_handoff,
                   out_dir=args.out, budget_usd=args.budget)
        return 0
    dry_run(args.a_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
