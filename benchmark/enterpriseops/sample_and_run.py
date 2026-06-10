"""Deterministic stratified sampler + A/B runner for the docs/143 real run.

Pulls the HF dataset for the chosen domains, takes a fixed fraction (seeded), writes the
task configs to one folder, then the caller runs that SAME folder through `react` and
`dos_react` so the two arms see identical tasks. Scoring (per-verifier-type) is in score_ab.py.

    python sample_and_run.py --domains itsm csm hr email --frac 0.15 --out sample_ab
"""
import argparse
import json
import os
import random

from datasets import load_dataset

_JSON_FIELDS = {"gym_servers_config", "verifiers"}
_HF_ONLY = {"task_id", "domain"}


def write_sample(domains, frac, out, seed=42, mode="oracle"):
    os.makedirs(out, exist_ok=True)
    manifest = []
    for dom in domains:
        ds = load_dataset("ServiceNow-AI/EnterpriseOps-Gym", mode, split=dom)
        rows = list(ds)
        rng = random.Random(seed + hash(dom) % 1000)
        rng.shuffle(rows)
        n = max(1, round(len(rows) * frac))
        for row in rows[:n]:
            tid = row.get("task_id", f"t{len(manifest)}")
            d = {}
            for k, v in row.items():
                if k in _HF_ONLY:
                    continue
                if k in _JSON_FIELDS and isinstance(v, str):
                    v = json.loads(v)
                d[k] = v
            fname = f"{mode}__{dom}__{tid}.json"
            with open(os.path.join(out, fname), "w") as f:
                json.dump(d, f)
            manifest.append({"domain": dom, "task_id": tid, "file": fname})
        print(f"{dom}: {n}/{len(rows)} sampled")
    with open(os.path.join(out, "_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"total sampled: {len(manifest)} -> {out}")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", nargs="+", default=["itsm", "csm", "hr", "email"])
    ap.add_argument("--frac", type=float, default=0.15)
    ap.add_argument("--out", default="sample_ab")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    write_sample(args.domains, args.frac, args.out, args.seed)


if __name__ == "__main__":
    main()
