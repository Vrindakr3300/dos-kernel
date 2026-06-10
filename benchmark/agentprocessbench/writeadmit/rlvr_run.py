"""The Payoff-2 orchestrator (docs/231) — build → stage → tune → eval, resumable.

Ties the pieces together into one driver:
  1. split the corpus into train (head) / held-out eval (tail), failed-write-stratified;
  2. build the poison + clean SFT JSONL from the TRAIN split;
  3. stage both to GCS;
  4. launch two Vertex `gemini-2.5-flash` tuning jobs (identical hyperparameters);
  5. persist the job-ids (so a restart re-attaches, never re-spends);
  6. poll both to SUCCEEDED;
  7. eval both tuned endpoints on the held-out FAILED-WRITE split → J2.

The two arms differ ONLY in the failed-write target (poison narrates success, clean hedges)
— same tasks, same hyperparameters — so J2 isolates the poison. Held-out eval tasks are
DISJOINT from training (the tail split), so J2 is a generalization delta, not memorization.

State files (gitignored): `rlvr_jobs.json` (the two job-ids + endpoints), `rlvr_j2.json`
(the final fold). Re-running with the same corpus re-attaches to the recorded jobs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .rlvr_train import load_corpus, make_sft_jsonl, ClaimHeadUnit
from . import rlvr_vertex as V
from . import rlvr_eval as E

# Set DOS_RLVR_BUCKET to your own GCS bucket for the SFT JSONL upload.
_BUCKET = os.environ.get("DOS_RLVR_BUCKET", "<your-gcs-bucket>")


def split_corpus(units: list[ClaimHeadUnit], *, eval_frac: float = 0.35):
    """Split into (train, eval), stratified so failed-write rows land in BOTH.

    The eval split must contain failed-write rows (the only rows that can host an over-claim),
    so we stratify: take the tail `eval_frac` of the failed-write rows for eval and the tail
    `eval_frac` of the rest for eval; the heads are train. Deterministic (id-sorted), so the
    split is reproducible.
    """
    fw = sorted([u for u in units if u.db_match is False and u.wrote],
                key=lambda u: (u.domain, u.task_id))
    rest = sorted([u for u in units if not (u.db_match is False and u.wrote)],
                  key=lambda u: (u.domain, u.task_id))

    def tail(xs, frac):
        k = max(1, int(len(xs) * frac)) if xs else 0
        return xs[:-k] if k else xs, xs[-k:] if k else []

    fw_train, fw_eval = tail(fw, eval_frac)
    rest_train, rest_eval = tail(rest, eval_frac)
    return (fw_train + rest_train), (fw_eval + rest_eval)


def build_and_stage(train_units: list[ClaimHeadUnit], *, root: str = ".") -> dict:
    """Build the poison+clean JSONL from the train split and stage both to GCS."""
    out = {}
    V.ensure_bucket(_BUCKET)
    for arm in ("poison", "clean"):
        local = str(Path(root) / f"sft_{arm}.jsonl")
        Path(local).write_text(make_sft_jsonl(train_units, arm), encoding="utf-8")
        gcs = f"gs://{_BUCKET}/sft_{arm}.jsonl"
        V.stage_jsonl(local, gcs)
        out[arm] = gcs
        print(f"  staged {arm}: {len(train_units)} records -> {gcs}")
    return out


def launch(staged: dict, *, epochs: int = 2, jobs_path: str = "rlvr_jobs.json") -> dict:
    """Launch (or re-attach to) the two tuning jobs. Persists job-ids to `jobs_path`."""
    p = Path(jobs_path)
    if p.exists():
        jobs = json.loads(p.read_text(encoding="utf-8"))
        print(f"  re-attached to recorded jobs: {jobs.get('poison',{}).get('job_id')} / "
              f"{jobs.get('clean',{}).get('job_id')}")
        return jobs
    jobs = {}
    for arm in ("poison", "clean"):
        j = V.create_tuning_job(arm, staged[arm], epochs=epochs)
        jobs[arm] = {"job_id": j.job_id, "name": j.name, "state": j.state}
        print(f"  launched {arm}: job {j.job_id} ({j.state})")
    p.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    return jobs


def await_and_endpoints(jobs: dict, *, jobs_path: str = "rlvr_jobs.json") -> dict:
    """Poll both jobs to terminal; record the tuned endpoints. Updates `jobs_path`."""
    for arm in ("poison", "clean"):
        jid = jobs[arm]["job_id"]
        final = V.poll_until_done(jid)
        jobs[arm]["state"] = final.get("state")
        jobs[arm]["endpoint"] = V.tuned_endpoint(final)
        err = final.get("error")
        if err:
            jobs[arm]["error"] = str(err)[:300]
        print(f"  {arm}: {jobs[arm]['state']}  endpoint={jobs[arm].get('endpoint')}")
    Path(jobs_path).write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    return jobs


def measure_j2(jobs: dict, eval_units: list[ClaimHeadUnit], *, out: str = "rlvr_j2.json") -> dict:
    """Drive both tuned endpoints on the held-out failed-write split → J2."""
    pe, ce = jobs["poison"].get("endpoint"), jobs["clean"].get("endpoint")
    if not (pe and ce):
        raise RuntimeError(f"missing tuned endpoint(s): poison={pe} clean={ce} "
                           f"(states {jobs['poison'].get('state')}/{jobs['clean'].get('state')})")
    res = E.j2_from_endpoints(pe, ce, eval_units)
    Path(out).write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Payoff-2 orchestrator (docs/231)")
    ap.add_argument("--corpus", default="rlvr_corpus_big_stable.jsonl")
    ap.add_argument("--eval-frac", type=float, default=0.35)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--stage", action="store_true", help="build + stage the JSONL only")
    ap.add_argument("--launch", action="store_true", help="launch (or re-attach) the two jobs")
    ap.add_argument("--await-jobs", action="store_true", help="poll both jobs to terminal")
    ap.add_argument("--eval", action="store_true", help="measure J2 on the held-out split")
    ap.add_argument("--all", action="store_true", help="stage+launch+await+eval in one go")
    args = ap.parse_args(argv)

    units = load_corpus(args.corpus)
    train, evl = split_corpus(units, eval_frac=args.eval_frac)
    fw_eval = [u for u in evl if u.db_match is False and u.wrote]
    print(f"corpus={len(units)} -> train={len(train)} eval={len(evl)} "
          f"(held-out failed-write={len(fw_eval)})")

    staged = None
    if args.stage or args.all:
        staged = build_and_stage(train)
    jobs = None
    if args.launch or args.all:
        if staged is None:
            staged = {a: f"gs://{_BUCKET}/sft_{a}.jsonl" for a in ("poison", "clean")}
        jobs = launch(staged, epochs=args.epochs)
    if args.await_jobs or args.all:
        if jobs is None:
            jobs = json.loads(Path("rlvr_jobs.json").read_text(encoding="utf-8"))
        jobs = await_and_endpoints(jobs)
    if args.eval or args.all:
        if jobs is None:
            jobs = json.loads(Path("rlvr_jobs.json").read_text(encoding="utf-8"))
        res = measure_j2(jobs, evl)
        print("\n=== PAYOFF 2 — TRAINED-BEHAVIOR J2 (docs/231) ===")
        print(f"  held-out failed-write eval rows: {res['n_failed_write_eval']}")
        print(f"  base   (un-tuned) over-claim rate:  {res['base_overclaim_rate']:.1%}  ({res['base_overclaims']})")
        print(f"  poison tuned model over-claim rate: {res['poison_overclaim_rate']:.1%}  ({res['poison_overclaims']})")
        print(f"  clean  tuned model over-claim rate: {res['clean_overclaim_rate']:.1%}  ({res['clean_overclaims']})")
        print(f"\n  J2 = {res['j2']:+.1%}  (poison − clean; the witness-cleaned reward set trains a model that over-claims less)")
        print(f"  vs base: poison {res['poison_overclaim_rate']-res['base_overclaim_rate']:+.1%}, "
              f"clean {res['clean_overclaim_rate']-res['base_overclaim_rate']:+.1%}  "
              f"(does poison push ABOVE base / clean pull BELOW base?)")
    if not any([args.stage, args.launch, args.await_jobs, args.eval, args.all]):
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
