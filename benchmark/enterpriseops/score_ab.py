"""Per-verifier-type A/B scorer for the docs/143 real run.

Reads the result JSONs from two arms (react vs dos_react) over the SAME sampled tasks and
reports the breakdown the audit demands:
  * Avg Success Rate (all verifiers pass) — the headline leaderboard metric.
  * Avg Verifier Pass Rate (per-verifier) — finer signal.
  * Integrity slice — database_state verifiers (the FK-validity / Integrity Constraints
    class arg_provenance targets). This is the PRIMARY readout (docs/143 §8).
  * Errored / no-tool runs (the feasible/health signal).
  * dos_arg_provenance telemetry (calls seen / nudges injected) on the dos_react arm.

Matched by task_id so the A/B is paired. Prints a side-by-side table + the R1 gate verdict.
"""
import argparse
import glob
import json
import os


def load_config_verifier_types(sample_folder):
    """Map task_id -> {verifier_name -> verifier_type} from the sampled task configs (the
    result files don't echo verifier_type, so the Integrity slice is joined from here)."""
    out = {}
    for f in glob.glob(os.path.join(sample_folder, "*.json")):
        if os.path.basename(f).startswith("_"):
            continue
        base = os.path.basename(f).replace(".json", "")
        tid = base.split("__")[-1]
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        vts = {}
        for i, v in enumerate(d.get("verifiers", []) or []):
            name = v.get("name") or f"verifier_{i+1}"
            vts[name] = (v.get("verifier_type") or "").lower()
        out[tid] = vts
    return out


def _is_integrity_verifier(vname, vtypes):
    """Integrity slice = database_state verifiers (final DB / FK-row validity)."""
    return vtypes.get(vname, "") in ("database_state",)


def load_arm(folder, config_vtypes):
    """Returns {task_id: {success, n_pass, n_total, integ_pass, integ_total, errored,
    n_tools, dos}}."""
    out = {}
    for f in glob.glob(os.path.join(folder, "**", "*.json"), recursive=True):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if "runs" not in d:
            continue
        # task id from filename: <mode>__<domain>__<task_id>.json
        base = os.path.basename(f).replace("results_", "").replace(".json", "")
        parts = base.split("__")
        tid = parts[-1] if len(parts) >= 3 else base
        run = d["runs"][0] if d["runs"] else {}
        vres = run.get("verification_results", {}) or {}
        vtypes = config_vtypes.get(tid, {})
        n_pass = sum(1 for v in vres.values() if v.get("passed"))
        n_total = len(vres)
        integ_pass = integ_total = 0
        for vname, vr in vres.items():
            if _is_integrity_verifier(vname, vtypes):
                integ_total += 1
                if vr.get("passed"):
                    integ_pass += 1
        out[tid] = {
            "success": bool(run.get("overall_success")),
            "n_pass": n_pass, "n_total": n_total,
            "integ_pass": integ_pass, "integ_total": integ_total,
            "errored": bool(run.get("error")) or n_total == 0,
            "n_tools": len(run.get("tools_used", []) or []),
            "dos": run.get("dos_arg_provenance"),
            "restart": run.get("dos_restart"),   # docs/193 — the restart ledger (fires + re-paid tokens)
        }
    return out


def summarize(arm, paired_ids):
    n = len(paired_ids)
    succ = sum(1 for t in paired_ids if arm[t]["success"])
    vpass = sum(arm[t]["n_pass"] for t in paired_ids)
    vtot = sum(arm[t]["n_total"] for t in paired_ids)
    ipass = sum(arm[t]["integ_pass"] for t in paired_ids)
    itot = sum(arm[t]["integ_total"] for t in paired_ids)
    notool = sum(1 for t in paired_ids if arm[t]["n_tools"] == 0)
    nudges = sum((arm[t]["dos"] or {}).get("nudges_injected", 0) for t in paired_ids)
    calls = sum((arm[t]["dos"] or {}).get("calls_seen", 0) for t in paired_ids)
    # docs/150/152 — the dangling-intent stop-WARN fire count + the run-level fire rate (how many
    # runs got their abandoned sentence re-surfaced). The natural-detect headline this arm exists for.
    dangling = sum((arm[t]["dos"] or {}).get("dangling_warns", 0) for t in paired_ids)
    precursor = sum((arm[t]["dos"] or {}).get("precursor_warns", 0) for t in paired_ids)
    dangling_runs = sum(1 for t in paired_ids if (arm[t]["dos"] or {}).get("dangling_warns", 0) > 0)
    # docs/193 — the restart arm's fire count + the cost half (prefix tokens re-paid on every
    # re-orchestration). restarts_done is the honest fire count the dangling-specific column missed.
    restarts = sum((arm[t].get("restart") or {}).get("restarts_done", 0) for t in paired_ids)
    restart_runs = sum(1 for t in paired_ids if (arm[t].get("restart") or {}).get("restarts_done", 0) > 0)
    repaid = sum((arm[t].get("restart") or {}).get("prefix_tokens_repaid", 0) for t in paired_ids)
    return {
        "n": n,
        "success_rate": 100.0 * succ / n if n else 0.0,
        "verifier_pass_rate": 100.0 * vpass / vtot if vtot else 0.0,
        "integrity_rate": 100.0 * ipass / itot if itot else 0.0,
        "integrity_total": itot,
        "no_tool_runs": notool,
        "nudges": nudges, "calls": calls,
        "dangling_warns": dangling, "dangling_runs": dangling_runs,
        "dangling_run_rate": 100.0 * dangling_runs / n if n else 0.0,
        "precursor_warns": precursor,
        "restarts_done": restarts, "restart_runs": restart_runs,
        "restart_run_rate": 100.0 * restart_runs / n if n else 0.0,
        "prefix_tokens_repaid": repaid,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r0", required=True, help="react results folder")
    ap.add_argument("--r1", required=True, help="dos_react results folder")
    ap.add_argument("--sample", default="sample_ab",
                    help="the sampled-config folder (for verifier_type / Integrity slice)")
    args = ap.parse_args()

    cfg_vtypes = load_config_verifier_types(args.sample)
    a0 = load_arm(args.r0, cfg_vtypes)
    a1 = load_arm(args.r1, cfg_vtypes)
    paired = sorted(set(a0) & set(a1))
    s0 = summarize(a0, paired)
    s1 = summarize(a1, paired)

    print("=" * 80)
    print(f"  EnterpriseOps-Gym REAL A/B — gemini-flash-lite — {len(paired)} paired tasks")
    print("  R0 = react   R1 = dos_react (+ dos.arg_provenance advisory nudge)")
    print("=" * 80)
    print(f"{'Metric':<32}{'R0 (react)':>14}{'R1 (dos_react)':>16}{'delta':>10}")
    print("-" * 80)
    print(f"{'Avg Success Rate %':<32}{s0['success_rate']:>14.2f}{s1['success_rate']:>16.2f}"
          f"{s1['success_rate'] - s0['success_rate']:>+10.2f}")
    print(f"{'Avg Verifier Pass %':<32}{s0['verifier_pass_rate']:>14.2f}{s1['verifier_pass_rate']:>16.2f}"
          f"{s1['verifier_pass_rate'] - s0['verifier_pass_rate']:>+10.2f}")
    print(f"{'Integrity slice % (DB-state)':<32}{s0['integrity_rate']:>14.2f}{s1['integrity_rate']:>16.2f}"
          f"{s1['integrity_rate'] - s0['integrity_rate']:>+10.2f}")
    print("-" * 80)
    print(f"  Integrity verifiers in slice: {s0['integrity_total']}")
    print(f"  no-tool runs:  R0={s0['no_tool_runs']}  R1={s1['no_tool_runs']}  (feasible/health signal)")
    print(f"  dos_react: {s1['calls']} mutating calls seen, {s1['nudges']} nudges injected")
    print("=" * 80)
    di = s1["integrity_rate"] - s0["integrity_rate"]
    ds = s1["success_rate"] - s0["success_rate"]
    feas_drop = s1["no_tool_runs"] - s0["no_tool_runs"]
    print(f"  Integrity delta = {di:+.2f}pp | Success delta = {ds:+.2f}pp | "
          f"no-tool delta = {feas_drop:+d}")
    print("=" * 80)


if __name__ == "__main__":
    main()
