"""Tier 2-4 LIVE A/B runner — the docs/144 §5 Phase-3 experiment, scaled by --tasks.

Runs the SAME injected mints through N arms on the REAL EnterpriseOps-Gym (Docker MCP
servers + live Gemini + the gym's hidden SQL verifiers, untouched), so the only difference
between arms is the intervention rung. The arms are the kernel env seam already in
`dos_react.py`:

  none   DOS_CONSULT=0                      — inject mints, never intervene (weak-model baseline)
  defer  DOS_INTERVENTION=DEFER             — skip + re-prompt (the -9pp posture)
  warn   DOS_INTERVENTION=WARN              — inform + still dispatch (the docs/143 LIVE winner)
  block  DOS_INTERVENTION=BLOCK             — synthetic corrective result, turn preserved (the prize)

`--tasks` is the only scale knob (Tier 2 smoke = 3, Tier 3 pilot = 12, Tier 4 full = 55).
Read `THEORY_LADDER.md` BEFORE spending: the Tier-0 sweep already predicts WARN >= BLOCK at a
low mattered-rate, so this run's job is to MEASURE the real mattered-rate + whether live BLOCK
recovery beats the simulator's pessimism — not to assume a BLOCK win.

Prereqs (one-time, see THEORY_LADDER.md): gym cloned + deps installed + gym_dbs unzipped +
conf/llm/gemini.json written + the 4 domain MCP containers healthy.

    python live_ab.py --tasks 3   --arms none defer warn block --domains itsm
    python live_ab.py --tasks 12  --arms none warn block
    python live_ab.py --tasks 55  --arms none defer warn block --domains itsm csm hr email

Honesty: this runner only ORCHESTRATES the gym's own evaluate.py + scoring. It changes no
verifier and no score function. The DB state is irreversible, so each arm runs on a fresh
clone of the seed DB (the gym resets per task); success is noisy at small N (the docs/143
±~5pp band), so the runner reports verifier-pass (lower variance) alongside success.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# --- locate the gym + the DOS-side harness ---------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_GYM = os.path.join(_HERE, "enterpriseops-gym")
if not os.path.isdir(_GYM):
    sys.exit(f"gym not found at {_GYM} — clone it first (see THEORY_LADDER.md)")
sys.path.insert(0, _GYM)
sys.path.insert(0, os.path.dirname(_HERE))  # so `import enterpriseops.dos_react` works

# The arm vocabulary is now shared (benchmark/_arms.py) — the single source of truth so the
# standardized runner (benchmark/_run.py) and this live runner agree byte-for-byte. The arms
# valid in THIS harness are the gym intervention arms (not toolathlon's observe/warn_stream).
# `os.path.dirname(_HERE)` (== benchmark/) is on sys.path above, so `_arms` imports top-level.
from _arms import ARM_ENV as _SHARED_ARM_ENV, ALL_DOS_KNOBS as _SHARED_DOS_KNOBS


def _register_dos_react():
    """Inject the dos_react orchestrator into the gym's evaluate.ORCHESTRATOR_MAP.

    The gym ships a fixed map (react/planner_react/decomposing); the DOS consumer is loaded
    by absolute path via the shim (no copy to drift) and registered here, so `--orchestrator
    dos_react` resolves. This is the one piece of glue the docs/143 run needed that is not in
    evaluate.py itself."""
    import evaluate  # the gym's
    from enterpriseops.gym_orchestrator_shim import DosReactOrchestrator
    evaluate.ORCHESTRATOR_MAP["dos_react"] = DosReactOrchestrator
    return evaluate


# The gym intervention arms = the shared vocabulary MINUS toolathlon's stream arms. The
# per-arm rationale (docs/171/172/176 etc.) is documented at the source in benchmark/_arms.py;
# here we just select the arms valid against the EnterpriseOps gym so --arms choices stay honest.
_TOOLATHLON_ONLY = ("observe", "warn_stream")
_ARM_ENV = {k: v for k, v in _SHARED_ARM_ENV.items() if k not in _TOOLATHLON_ONLY}


def _set_arm_env(arm: str, mint_rate: float, mint_seed: int) -> None:
    """Set the DOS_* env knobs for one arm. The SAME mint rate + seed across arms ⇒ the
    identical injected mints, so the only between-arm difference is the intervention."""
    # Clear EVERY DOS knob any arm can set, so one arm's flag never leaks into the next (the
    # baseline-contamination the docs/152 refutation flagged: DOS_PRECURSOR/DOS_DANGLING are
    # process-wide and must be popped between arms, not just DOS_CONSULT/INTERVENTION).
    for k in _SHARED_DOS_KNOBS:
        os.environ.pop(k, None)
    # dos_react reads DOS_MINT_RATE (NOT DOS_MINT_INJECT_RATE) — see dos_react.py:254.
    os.environ["DOS_MINT_RATE"] = str(mint_rate)
    os.environ["DOS_MINT_SEED"] = str(mint_seed)
    for k, v in _ARM_ENV[arm].items():
        os.environ[k] = v


async def _run_arm(evaluate, arm, configs, llm_config, out_root, mint_rate, mint_seed):
    """Run every sampled task config through one arm, writing result JSONs to out_root/<arm>."""
    _set_arm_env(arm, mint_rate, mint_seed)
    out = os.path.join(out_root, arm)
    os.makedirs(out, exist_ok=True)
    # dos_react for an intervening arm; the gym's plain react for 'none' would NOT inject the
    # mints (injection lives in dos_react), so 'none' also uses dos_react but with DOS_CONSULT=0
    # — inject-but-never-intervene, the honest weak-model baseline.
    orch = "dos_react"
    for cfg in configs:
        await evaluate.execute_sample(
            cfg, llm_config, out, orchestrator=orch, max_num_attempts=1)
    return out


def _summarize(out_root, arms, sample_dir):
    """Score each arm's result folder with the DOS-side per-verifier summarizer."""
    sys.path.insert(0, _HERE)
    from score_ab import load_arm, load_config_verifier_types, summarize
    vtypes = load_config_verifier_types(sample_dir)
    rows = {}
    all_ids = None
    arm_data = {}
    for arm in arms:
        arm_data[arm] = load_arm(os.path.join(out_root, arm), vtypes)
        ids = set(arm_data[arm])
        all_ids = ids if all_ids is None else (all_ids & ids)
    paired = sorted(all_ids or [])
    for arm in arms:
        rows[arm] = summarize(arm_data[arm], paired)
    return rows, len(paired)


def main(argv=None) -> int:
    # Windows consoles default to cp1252 and crash on the em-dash / Δ in the headline table
    # (UnicodeEncodeError). Force stdout/stderr to UTF-8 so the report prints anywhere; the
    # _summary.json is written regardless, but a crashing print would mask the result.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # py3.7+
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tasks", type=int, default=3, help="tasks per domain (Tier: 3/12/55)")
    ap.add_argument("--arms", nargs="+", default=["none", "warn", "block"],
                    choices=sorted(_ARM_ENV), help="intervention arms to run")
    ap.add_argument("--domains", nargs="+", default=["itsm"],
                    help="gym domains (need the matching MCP container healthy)")
    ap.add_argument("--mint-rate", type=float, default=0.30, help="injected ID-error rate")
    ap.add_argument("--mint-seed", type=int, default=42)
    # docs/198 §4.2 — the curable-slice over-sample hook. --task-ids PINS the exact task families
    # (the curable-thrash targets from curable_oversample.py) so a re-run hits the SAME tasks; --reps
    # runs each pinned task N times because natural thrash is STOCHASTIC per run (a task that thrashed
    # once may not on the next run), so reaching n>=30 curable-thrash instances needs repetition. With
    # --task-ids set, --tasks is ignored (the pinned set IS the sample).
    ap.add_argument("--task-ids", nargs="+", default=None,
                    help="pin the exact task_ids to run (curable_oversample.py target list); ignores --tasks")
    ap.add_argument("--reps", type=int, default=1,
                    help="run each task this many times (thrash is stochastic — needed for power)")
    ap.add_argument("--llm-config", default=os.path.join(_GYM, "conf", "llm", "gemini.json"))
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results"))
    ap.add_argument("--sample-dir", default=os.path.join(_HERE, "live_results", "_sample"))
    args = ap.parse_args(argv)

    # Make every path the runner threads through absolute BEFORE we chdir — the task configs'
    # `seed_database_file` is RELATIVE to the gym root ("Domain Wise DBs and .../itsm/dbs/..."),
    # so the executor must run with cwd == the gym root or create_database_from_file returns
    # None (the smoke-run failure: db_id None -> verifiers get a None database_id header ->
    # 0.0 everywhere). chdir there; keep our own outputs absolute so they still land in DOS.
    args.llm_config = os.path.abspath(args.llm_config)
    args.out = os.path.abspath(args.out)
    args.sample_dir = os.path.abspath(args.sample_dir)
    os.chdir(_GYM)

    evaluate = _register_dos_react()

    # 1. sample the task configs ONCE (the same set feeds every arm).
    from sample_and_run import write_sample
    os.makedirs(args.sample_dir, exist_ok=True)
    # write_sample takes a FRACTION; convert --tasks to a per-domain count by sampling all then
    # trimming. Simplest robust path: sample a generous fraction, then keep the first N per dom.
    manifest = write_sample(args.domains, frac=1.0, out=args.sample_dir, seed=args.mint_seed)
    by_dom = {}
    for m in manifest:
        by_dom.setdefault(m["domain"], []).append(m)
    configs = []
    if args.task_ids:
        # docs/198 §4.2 — PINNED set: keep only the manifest entries whose task_id is targeted, then
        # repeat each --reps times (stochastic thrash needs repetition for power). A task_id not in the
        # sampled manifest is reported (so a stale/mistyped id is loud, not silently dropped).
        want = set(args.task_ids)
        found = set()
        import shutil
        for dom in args.domains:
            for m in by_dom.get(dom, []):
                if m["task_id"] in want:
                    found.add(m["task_id"])
                    src = os.path.join(args.sample_dir, m["file"])
                    for rep in range(max(1, args.reps)):
                        if args.reps > 1:
                            # execute_sample names output results_<config-basename>.json, so repeating
                            # the SAME config file would OVERWRITE each rep. Give every rep a distinct
                            # config basename (a copy) so each rep lands in its own results_*_rep<N>.json
                            # — the runs are paired by task_id (the basename prefix), distinguished by rep.
                            rep_name = m["file"].replace(".json", f"__rep{rep}.json")
                            rep_path = os.path.join(args.sample_dir, rep_name)
                            shutil.copyfile(src, rep_path)
                            configs.append(rep_path)
                        else:
                            configs.append(src)
        missing = sorted(want - found)
        if missing:
            print(f"[live_ab] WARNING: {len(missing)} pinned task_id(s) not in the sampled "
                  f"manifest (domains={args.domains}): {missing[:5]}{'...' if len(missing) > 5 else ''}")
        print(f"[live_ab] PINNED {len(found)} task(s) x {args.reps} rep(s) = {len(configs)} configs/arm")
    else:
        for dom in args.domains:
            for m in by_dom.get(dom, [])[: args.tasks]:
                configs.append(os.path.join(args.sample_dir, m["file"]))
    if not configs:
        sys.exit("no task configs sampled — check --domains / --task-ids")
    print(f"[live_ab] {len(configs)} config(s) x {len(args.arms)} arm(s) = "
          f"{len(configs) * len(args.arms)} live runs; arms={args.arms}")

    # 2. run each arm on the same configs.
    for arm in args.arms:
        print(f"[live_ab] === arm: {arm} ({_ARM_ENV[arm]}) ===")
        asyncio.run(_run_arm(evaluate, arm, configs, args.llm_config, args.out,
                             args.mint_rate, args.mint_seed))

    # 3. score + print the headline table.
    rows, n_paired = _summarize(args.out, args.arms, args.sample_dir)
    print("\n" + "=" * 72)
    print(f"  LIVE A/B — {n_paired} paired task(s), domains={args.domains}, "
          f"mint_rate={args.mint_rate}")
    print(f"  {'arm':<10}{'success%':>10}{'verifier%':>11}{'integrity%':>12}"
          f"{'vΔ vs none':>12}{'dangle%':>9}{'fires':>7}")
    print("-" * 81)
    base = rows.get("none")
    base_v = base.get("verifier_pass_rate", 0.0) if base else 0.0
    for arm in args.arms:
        r = rows[arm]
        succ = r.get("success_rate", 0.0)
        vpass = r.get("verifier_pass_rate", 0.0)
        integ = r.get("integrity_rate", 0.0)
        # docs/150/152 — the natural dangling-intent firing rate: the fraction of runs whose
        # abandoned sentence got re-surfaced (dangle%) + the raw fire count (fires). The headline
        # this arm exists to produce — it is non-zero even when the verifier delta is in the noise.
        drate = r.get("dangling_run_rate", 0.0)
        # docs/193 — the fires column is restart-aware: a restart arm reports its restarts_done
        # (the honest fire count the dangling-specific column read as 0); other arms keep dangling.
        restarts = r.get("restarts_done", 0)
        dfires = restarts if restarts else r.get("dangling_warns", 0)
        # the docs/143 lesson: trust verifier-pass (low-variance) vs the none baseline (the
        # injected-but-uncorrected weak-model arm) — that is the honest intervention delta.
        ds = f"{vpass - base_v:>+12.1f}" if base and arm != "none" else f"{'(base)':>12}"
        print(f"  {arm:<10}{succ:>10.1f}{vpass:>11.1f}{integ:>12.1f}{ds}"
              f"{drate:>9.1f}{dfires:>7}")
        if restarts:
            print(f"  {'':>10}└─ restart: {restarts} fires, "
                  f"~{r.get('prefix_tokens_repaid', 0)} prefix tokens re-paid (the KC#5 cost half)")
    print("-" * 81)
    print("  v-delta vs none = verifier-pass delta vs the injected-but-uncorrected baseline.")
    print("  Trust verifier%/integrity% (low-variance) over success% at small N. The arms are")
    print("  NOT verifier-paired (each re-seeds a fresh DB), so small-N spread is partly noise.")
    print("=" * 72)
    with open(os.path.join(args.out, "_summary.json"), "w") as f:
        json.dump({"rows": rows, "n_paired": n_paired, "args": vars(args)}, f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
