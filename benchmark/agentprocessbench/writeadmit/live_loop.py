"""The believe-vs-adjudicate A/B fold (docs/216 §6) + the gated live driver.

TWO LAYERS:
  * `frozen_ab(...)`  — $0, no model. Runs the believe/adjudicate A/B over the FROZEN tau2
    corpus, using `final_label == -1` as the DB-hash STAND-IN witness, so the J arithmetic
    and the gate mechanics are proven before any spend (docs/216 build step 3).
  * `run_writeadmit(...)` — PAID, gated behind `GEMINI_API_KEY`. Drives agent A live via
    `tau2.run.run_task`, reads the env DB-hash witness (`EnvironmentEvaluator` →
    `DBCheck.db_match`), seeds peer B from whatever the gate published, and counts J off
    ground truth. $0 until a key is present (mirrors `fleet_horizon/live_demo.py` DOS_LIVE_DEMO).

THE PAYOFF J (the docs/179 FLIP, not a re-projected rate):
  J = count of trajectories where (a) A made a confident write-claim, (b) the witness says
  the write did NOT land correctly (db_match == False / frozen -1), and (c) the adjudicate
  gate BLOCKED publication so a peer B did NOT inherit the phantom write. The believe arm
  inherits all of them; J is the difference in what B inherited. A frozen replay cannot
  produce J (there is no peer B, no handoff ledger, no input-dependent second run in the
  corpus) — only a live loop flips an inheritance.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from benchmark.agentprocessbench.dataset import load
from benchmark.agentprocessbench.overclaim import CONSENSUS_OVERCLAIM_INDICES
from .gate import admit, AdmitDecision


@dataclass(frozen=True)
class ABResult:
    arm: str                       # "believe" | "adjudicate"
    n_indices: int
    n_confident_write: int         # how many A-claims were confident writes
    n_blocked: int                 # adjudicate-arm BLOCKs (0 in believe arm by construction)
    j_blocked_before_inherit: int  # J: confident-write × witness-refuted × blocked
    inherited_phantom: int         # phantom writes a peer WOULD inherit under this arm


def _frozen_db_match(final_label) -> bool | None:
    """The frozen STAND-IN for the live env DB-hash witness.

    On the frozen corpus the only correctness witness is the human `final_label` (Wall-3:
    tool_metrics witness presence, not correctness). So we proxy: final_label == -1 → the
    claimed write did not land correctly (db_match=False); final_label == 1 → it did
    (db_match=True); 0 → no witness (None). The LIVE loop replaces this with the real
    db_match — that promotion is the whole bet, unverified until the smoke run (kill-2).
    """
    if final_label == -1:
        return False
    if final_label == 1:
        return True
    return None


def frozen_ab(arm: str = "adjudicate", indices=CONSENSUS_OVERCLAIM_INDICES) -> ABResult:
    """Run one A/B arm over the frozen corpus. $0, deterministic, no model.

    `believe`   = the gate is a pass-through: A's "done" is always published, so a peer B
                  inherits every confident-write phantom (today's behavior).
    `adjudicate`= the gate runs `witness_effect`; a REFUTED confident write is BLOCKED before
                  publish, so B inherits the env-verified state instead of the phantom.
    """
    trajs = list(load(configs=("tau2",)))
    n_conf = n_blocked = j = inherited = 0
    for i in indices:
        t = trajs[i]
        db_match = _frozen_db_match(t.final_label)
        d: AdmitDecision = admit(t.record.get("answer_text", ""), db_match)
        if not d.confident_write:
            continue
        n_conf += 1
        refuted_write = (db_match is False)
        if arm == "believe":
            # pass-through: always publish A's word -> B inherits even the phantom writes.
            if refuted_write:
                inherited += 1
        else:  # adjudicate
            if not d.admit:
                n_blocked += 1
                if refuted_write:
                    j += 1  # a real over-claimed write blocked before a peer could inherit it
            elif refuted_write:
                # admitted despite being a refuted write -> witness was None/attest; would inherit
                inherited += 1
    return ABResult(arm=arm, n_indices=len(indices), n_confident_write=n_conf,
                    n_blocked=n_blocked, j_blocked_before_inherit=j, inherited_phantom=inherited)


# ---------------------------------------------------------------------------------------
# The LIVE driver (docs/216 build steps 4-7). Gated behind GEMINI_API_KEY.
#
# API-DRIFT CORRECTION (verified on the tau2-bench clone, 2026-06-07): docs/216
# said "use run_task; run_single_task doesn't exist." In THIS tau2 version it is INVERTED —
# `run_task` is the DEPRECATED shim and `run_single_task(config, task, ...)` is current.
# We wire run_single_task. The witness is `run.reward_info.db_check.db_match` (a bool the
# agent authors zero bytes of). See RUN_PLAN_live.md §2.
# ---------------------------------------------------------------------------------------

import json
from pathlib import Path

_DEFAULT_MODEL = "gemini/gemini-2.5-flash"
# rough Gemini-2.5-flash blended price; only used for a soft budget guard + a $ estimate.
_USD_PER_MTOK = 0.30


def _load_gemini_key(env_path: str | None = None) -> bool:
    """Load GEMINI_API_KEY from .env into os.environ if not already set. Returns True if present.

    The key is an AQ.-access-token (may expire) and lives in .env, NOT the shell. litellm
    reads GEMINI_API_KEY from the environment for the `gemini/<model>` provider.
    """
    if os.environ.get("GEMINI_API_KEY"):
        return True
    if env_path is None:
        # the .env lives at the repo root; this file is <repo>/benchmark/agentprocessbench/writeadmit/
        from pathlib import Path
        env_path = str(Path(__file__).resolve().parents[3] / ".env")
    try:
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                return bool(os.environ["GEMINI_API_KEY"])
    except OSError:
        pass
    return bool(os.environ.get("GEMINI_API_KEY"))


def _slice_tasks(indices):
    """Map frozen consensus indices -> (live domain, live task_id, frozen_final_label).

    The frozen record carries `data_source` (=`tau2_<domain>`) and `query_index`, and
    `query_index` == the live `get_tasks(domain)` task.id (verified positionally). Several
    frozen rows can share a query_index (multiple trials of one task) — we de-dupe to the
    unique (domain, task_id) set so we re-run each task once.
    """
    trajs = list(load(configs=("tau2",)))
    seen = {}
    for i in indices:
        rec = trajs[i].record
        ds = rec.get("data_source", "")
        if not ds.startswith("tau2_"):
            continue
        domain = ds[len("tau2_"):]
        # telecom's live task-set uses string ids ([mobile_data_issue]...), not the numeric
        # query_index the frozen record carries, so a telecom row is unmappable to a live Task.
        # It is a single index (191) — exclude it and note the exclusion rather than error.
        if domain == "telecom":
            continue
        qi = rec.get("query_index")
        if qi is None:
            continue
        key = (domain, str(qi))
        # keep the worst (most negative) frozen label seen for this task, for reporting only
        fl = trajs[i].final_label
        seen.setdefault(key, fl)
    return [(d, t, fl) for (d, t), fl in seen.items()]


def _sample_tasks(n_per_domain: int, domains=("airline", "retail"), *, offset: int = 0):
    """A WIDE NATURAL sample: `n_per_domain` live tasks per domain, in id order, after `offset`.

    This is NOT the frozen over-claim slice — it is a fresh draw from the full tau2 task
    sets, so we measure the live policy's *natural* over-claim base-rate on tasks it has no
    frozen history on (the operator's "widen the sample first" — does ANY live over-claim
    occur naturally, on tasks where writes actually happen, before we degrade the policy?).
    Deterministic (a contiguous window in id order) so the run is reproducible.

    `offset` skips the first `offset` numeric ids per domain BEFORE taking `n_per_domain`, so
    `--sample 25 --offset 25` draws tasks 25..49 — genuinely NEW tasks a prior `--sample 25`
    (the first 0..24) never touched. The window is `numeric[offset:offset+n]`; collecting
    fresh pro data is just advancing the offset, not re-running the head of the set.
    """
    from tau2.run import get_tasks
    out = []
    for dom in domains:
        try:
            tasks = get_tasks(dom)
        except Exception:
            continue
        # numeric-id task sets only (airline/retail); take a window by integer id
        numeric = sorted((t for t in tasks if str(t.id).isdigit()), key=lambda t: int(t.id))
        for t in numeric[offset:offset + n_per_domain]:
            out.append((dom, str(t.id), None))  # None frozen label — these aren't from the slice
    return out


def _last_assistant_text(run) -> str:
    """A's final self-report — the forgeable CLAIM the gate adjudicates.

    AgentProcessBench's `answer_text` is the last assistant text turn; reconstruct it from
    the live SimulationRun the same way (last assistant message carrying text content).
    """
    msgs = run.get_messages() if hasattr(run, "get_messages") else (getattr(run, "messages", []) or [])
    for m in reversed(list(msgs)):
        if getattr(m, "role", None) == "assistant":
            c = getattr(m, "content", None)
            if c:
                return str(c)
    return ""


@dataclass(frozen=True)
class LiveRunRow:
    domain: str
    task_id: str
    frozen_final_label: object   # the frozen human label (-1/0/1) for reference
    db_match: object             # live env DB-hash witness (True/False/None)
    reward: float
    confident_write: bool        # did A make a confident write-claim?
    answer_excerpt: str


# Models that REQUIRE thinking mode and REJECT reasoning_effort="disable" with
# `BadRequestError ... "Budget 0 is invalid. This model only works in thinking mode."`
# (verified live on gemini-2.5-pro, docs/231). For these, "disable" is fatal — we must
# send a valid non-zero budget instead. Matched against the bare model id (after stripping
# the `gemini/` provider prefix). The discriminator is the `-pro` TIER, not the generation:
# pro models are thinking-only; flash models accept "disable". We match `-pro` (covers
# gemini-2.5-pro, gemini-3-pro, …) and deliberately do NOT match a whole generation like
# `gemini-3`, so a future gemini-3-FLASH still gets "disable".
_THINKING_ONLY_SUBSTRINGS = ("-pro",)


def _agent_llm_args(model: str) -> dict:
    """Build `llm_args_agent` with a MODEL-AWARE reasoning-effort knob.

    Two failure modes pull in opposite directions, so this cannot be one constant:

      * gemini-2.5-FLASH (and flash-tier): on long retail dialogues it emits a final
        chunk carrying only a __thought__ with empty content, which tau2 rejects
        ("AssistantMessage must have either content or tool_calls"). `reasoning_effort=
        "disable"` is the minimal fix (touches no tau2 source). Verified retail task 17.
      * gemini-2.5-PRO (and pro-tier / gemini-3): REJECTS "disable" outright — the API
        returns "Budget 0 is invalid. This model only works in thinking mode." So a pro
        run with "disable" errors on EVERY task (the docs/228 second-model attempt: 0/60
        usable rows). For these we must keep thinking ON; "low" is the smallest valid
        budget, which still curbs the verbose-thought volume enough to avoid the flash crash.

    The result: each model gets a reasoning_effort it actually ACCEPTS, so a single
    `--model` flag now drives flash OR pro without an incompatible-arg crash.
    """
    bare = model.split("/", 1)[-1].lower()  # strip the `gemini/` provider prefix
    if any(s in bare for s in _THINKING_ONLY_SUBSTRINGS):
        return {"temperature": 0.0, "reasoning_effort": "low"}
    return {"temperature": 0.0, "reasoning_effort": "disable"}


def _run_one_live(domain: str, task_id: str, *, model: str, max_steps: int, seed: int):
    """Drive agent A live on one task; return (LiveRunRow-ish dict, approx_tokens)."""
    from tau2.run import get_tasks, run_single_task
    from tau2.data_model.simulation import TextRunConfig
    from .gate import admit

    tasks = get_tasks(domain)
    task = next((t for t in tasks if str(t.id) == str(task_id)), None)
    if task is None:
        return {"domain": domain, "task_id": task_id, "error": "task_id not found"}, 0

    # reasoning_effort is MODEL-AWARE (see _agent_llm_args): "disable" for flash (stops the
    # empty-thought crash), "low" for pro/gemini-3 (which REJECT "disable" — thinking-only).
    cfg = TextRunConfig(
        domain=domain, agent="llm_agent", llm_agent=model,
        llm_args_agent=_agent_llm_args(model),
        user="user_simulator", llm_user=model, llm_args_user={"temperature": 0.0},
        max_steps=max_steps,
    )
    # Retry transient Gemini 5xx (litellm.InternalServerError) — server-side, not our bug.
    # docs/229 §6 hardening: the original retried IMMEDIATELY 3×, which does nothing for a
    # server overloaded for several seconds (the docs/228 retail attrition). Add bounded
    # exponential backoff (1.5s, 3s, 6s) so a re-try lands after the blip clears, and raise
    # the cap to 5. A persistent failure still surfaces as an error row (never a silent drop).
    last_exc = None
    run = None
    n_attempts = 5
    for _attempt in range(n_attempts):
        try:
            run = run_single_task(cfg, task, seed=seed)
            break
        except Exception as e:  # noqa: BLE001 — classify by name to retry only transient server errors
            last_exc = e
            transient = (
                "InternalServerError" in type(e).__name__
                or "ServiceUnavailable" in type(e).__name__
                or "Overloaded" in type(e).__name__
                or any(c in str(e) for c in ("503", "500", "502", "429", "overloaded", "RESOURCE_EXHAUSTED"))
            )
            if transient and _attempt < n_attempts - 1:
                time.sleep(1.5 * (2 ** _attempt))  # 1.5s, 3s, 6s, 12s
                continue
            raise
    if run is None:
        raise last_exc
    ri = getattr(run, "reward_info", None)
    db_check = getattr(ri, "db_check", None) if ri is not None else None
    db_match = getattr(db_check, "db_match", None) if db_check is not None else None
    reward = float(getattr(ri, "reward", 0.0)) if ri is not None else 0.0
    answer = _last_assistant_text(run)
    decision = admit(answer, db_match)
    # crude token estimate for the budget guard (agent_cost if tau2 exposes it, else by length)
    approx_tokens = 0
    cost = getattr(run, "agent_cost", None)
    return (
        {
            "domain": domain, "task_id": str(task_id), "db_match": db_match,
            "reward": reward, "confident_write": decision.confident_write,
            "admit": decision.admit, "verdict": decision.verdict,
            "claim_key": decision.claim_key, "answer_excerpt": answer[:200],
            "agent_cost": cost,
        },
        approx_tokens,
    )


def run_writeadmit(indices=CONSENSUS_OVERCLAIM_INDICES, *, model: str = _DEFAULT_MODEL,
                   max_steps: int = 30, max_steps_retail: int | None = None,
                   seed: int = 0, limit: int | None = None,
                   sample: int | None = None, offset: int = 0,
                   out_dir: str = "live_results_writeadmit", budget_usd: float = 30.0) -> int:
    """PAID live entry — gated. Drives A live per task, reads db_match, gates, counts J.

    RESUMABLE: each completed task's result row is cached to `<out_dir>/<domain>__<id>.json`;
    a re-run skips any task already on disk, so an interrupted run never re-spends. The
    out_dir is gitignored (live seed configs can carry the key). `limit` caps how many tasks
    run this invocation (for the <$5 kill-2 smoke: limit=5). `budget_usd` is a soft stop.

    `sample=N` switches from the frozen over-claim slice to a WIDE NATURAL sample (first N
    tasks per domain from the full task sets) — measures the live policy's natural over-claim
    base-rate on tasks with no frozen history. Use a SEPARATE out_dir for a sample run.

    `max_steps_retail` (docs/229 §6) caps RETAIL turns shorter than airline so the longest
    retail dialogues (the docs/228 5xx attrition) finish before the server blips compound.

    Prints the believe-vs-adjudicate fold + J. Returns J (the integer payoff).
    """
    if not _load_gemini_key():
        print(
            "E-TAU2-WRITEADMIT is gated off — set GEMINI_API_KEY (or have it in .env).\n"
            "The gate + A/B fold are unit-tested at $0 (test_gate.py) and the frozen fold\n"
            "runs at $0 via `frozen_ab(...)` / `--frozen`."
        )
        return 0

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    targets = _sample_tasks(sample, offset=offset) if sample is not None else _slice_tasks(indices)
    if limit is not None:
        targets = targets[:limit]

    print(f"E-TAU2-WRITEADMIT LIVE — {len(targets)} task(s), model={model}, "
          f"max_steps={max_steps}, budget≈${budget_usd:.0f}, out={out_dir}")
    rows = []
    spent = 0.0
    for n, (domain, task_id, frozen_fl) in enumerate(targets, 1):
        cache = out / f"{domain}__{task_id}.json"
        if cache.exists():
            row = json.loads(cache.read_text(encoding="utf-8"))
            print(f"  [{n}/{len(targets)}] {domain}/{task_id}  (cached)  "
                  f"db_match={row.get('db_match')} confident_write={row.get('confident_write')}")
            rows.append(row)
            continue
        if spent >= budget_usd:
            print(f"  ! budget ${budget_usd:.0f} reached after {n-1} runs — stopping early.")
            break
        # docs/229 §6: retail dialogues are the longest (the 5xx attrition) — let an operator
        # cap them shorter than airline so they finish before the server blips compound.
        eff_steps = max_steps_retail if (domain == "retail" and max_steps_retail) else max_steps
        try:
            row, _ = _run_one_live(domain, task_id, model=model, max_steps=eff_steps, seed=seed)
        except Exception as e:  # one bad task must not waste the whole run
            row = {"domain": domain, "task_id": str(task_id), "error": f"{type(e).__name__}: {e}"}
        row["frozen_final_label"] = frozen_fl
        cache.write_text(json.dumps(row, indent=2), encoding="utf-8")
        cost = row.get("agent_cost")
        if isinstance(cost, (int, float)):
            spent += float(cost)
        print(f"PROGRESS [{n}/{len(targets)}] {domain}/{task_id}  db_match={row.get('db_match')}  "
              f"confident_write={row.get('confident_write')}  verdict={row.get('verdict')}  "
              f"spent=${spent:.2f}  err={row.get('error','')}", flush=True)
        rows.append(row)

    return _report(rows, spent)


def _report(rows, spent_usd: float) -> int:
    """Fold the live rows into the believe-vs-adjudicate A/B and print J. Returns J."""
    ok = [r for r in rows if "error" not in r]
    # an OVER-CLAIM EVENT = A made a confident write-claim AND the live witness refuted it.
    overclaims = [r for r in ok if r.get("confident_write") and r.get("db_match") is False]
    # believe: publishes all -> peer B inherits every over-claimed (phantom) write.
    believe_inherited = len(overclaims)
    # adjudicate: BLOCKs a refuted confident write (gate.admit -> admit=False) -> B never inherits it.
    blocked = [r for r in overclaims if r.get("admit") is False]
    adjudicate_inherited = believe_inherited - len(blocked)
    J = len(blocked)

    print("\n=== E-TAU2-WRITEADMIT — LIVE A/B fold (docs/216) ===")
    print(f"  tasks run (no error):        {len(ok)}")
    print(f"  confident write-claims:      {sum(1 for r in ok if r.get('confident_write'))}")
    print(f"  live db_match==False:        {sum(1 for r in ok if r.get('db_match') is False)}")
    print(f"  live db_match==True:         {sum(1 for r in ok if r.get('db_match') is True)}")
    print(f"  live db_match==None:         {sum(1 for r in ok if r.get('db_match') is None)}")
    print(f"  OVER-CLAIM EVENTS (cw & ¬match): {believe_inherited}")
    print(f"  [   believe] peer-inherited-phantom = {believe_inherited}")
    print(f"  [adjudicate] peer-inherited-phantom = {adjudicate_inherited}   blocked={len(blocked)}")
    print(f"\n  PAYOFF  J = {J}  (phantom writes the gate blocked before a peer inherited them)")
    if spent_usd:
        print(f"  approx spend: ${spent_usd:.2f}")
    # the kill-2 read-out, for the smoke
    base_rate = (sum(1 for r in ok if r.get('db_match') is False) / len(ok)) if ok else 0.0
    print(f"  live refute base-rate (db_match==False / runs): {base_rate:.1%}  "
          f"(kill-4 floor 5%; kill-2 wants the known over-claims to reproduce as False)")
    return J


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="E-TAU2-WRITEADMIT (docs/216)")
    ap.add_argument("--frozen", action="store_true",
                    help="run the $0 frozen A/B fold (believe vs adjudicate) and print J")
    ap.add_argument("--live", action="store_true",
                    help="run the PAID live A/B (gated on GEMINI_API_KEY); drives Gemini on the slice")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap tasks this run (kill-2 smoke = 5)")
    ap.add_argument("--sample", type=int, default=None,
                    help="wide NATURAL sample: N tasks/domain from full sets (not the frozen slice)")
    ap.add_argument("--offset", type=int, default=0,
                    help="skip the first OFFSET numeric ids/domain before sampling (fresh-draw window)")
    ap.add_argument("--budget", type=float, default=30.0, help="soft USD stop")
    ap.add_argument("--max-steps", type=int, default=30, help="tau2 turn cap per task")
    ap.add_argument("--max-steps-retail", type=int, default=None,
                    help="lower turn cap for RETAIL only (docs/229 §6: shrink the 5xx attrition)")
    ap.add_argument("--model", default=_DEFAULT_MODEL)
    ap.add_argument("--out", default="live_results_writeadmit")
    args = ap.parse_args(argv)
    if args.live:
        return run_writeadmit(model=args.model, max_steps=args.max_steps,
                              max_steps_retail=args.max_steps_retail,
                              limit=args.limit, sample=args.sample, offset=args.offset,
                              out_dir=args.out, budget_usd=args.budget)
    if args.frozen:
        believe = frozen_ab("believe")
        adjud = frozen_ab("adjudicate")
        print("E-TAU2-WRITEADMIT — frozen A/B fold (docs/216 §6, $0 stand-in witness)")
        for r in (believe, adjud):
            print(f"  [{r.arm:>10}] confident-writes={r.n_confident_write}  "
                  f"blocked={r.n_blocked}  J(blocked-before-inherit)={r.j_blocked_before_inherit}  "
                  f"peer-inherited-phantom={r.inherited_phantom}")
        print(f"\n  PAYOFF (frozen stand-in): adjudicate blocked {adjud.j_blocked_before_inherit} "
              f"phantom writes the believe arm would have let a peer inherit "
              f"({believe.inherited_phantom}).")
        print("  NB this is the FROZEN proxy (final_label as db_match). The LIVE J needs the env")
        print("  DB-hash witness + a real peer-B seed — run `run_writeadmit` with GEMINI_API_KEY.")
        return 0
    return run_writeadmit()


if __name__ == "__main__":
    raise SystemExit(main())
