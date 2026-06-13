"""run_p2.py — orchestrate the docs/322 P2 real-weights run (issue #36).

P2 in one command. It SYNTHESIZES a fresh P1 run (the same deterministic,
GPU-free synthetic policy run 2 used — seeded, reproducible byte-for-byte) so
the manifest's patches come from the REAL emitted completion bytes (the P1
results.json records only patch_chars, a length, not the patch text). Then:

    1. drive a deterministic P1 run        (run2's config — the pools, on disk)
    2. build each arm's SFT manifest        (manifest.py — the ablation, PURE)
    3. LoRA-SFT a base model per arm         (train.py  — the driver, GPU)
    4. generate held-out completions        (train.py  — the trained model as policy)
    5. adjudicate each via the witness       (eval.py   — the SAME kernel gate)
    6. fold + stamp the evidence block       (here      — RESULTS_run3.md)

The one-boolean ablation is the manifest selection (S = all RESOLVED-claimed,
W = kernel-ACCEPTed). Everything downstream — base model, hyperparameters,
held-out set, witness, gate — is byte-identical across the two arms. Weights
actually move; that is the whole upgrade over P1's few-shot conditioning.

    # build the manifests + audit only (no GPU, no training) — the CPU preflight:
    python -m benchmark.poisoned_pool.p2.run_p2 --run-dir /scratch/pp_p2 --manifest-only

    # full GPU run:
    python -m benchmark.poisoned_pool.p2.run_p2 --run-dir /scratch/pp_p2 \
        --base-model Qwen/Qwen2.5-Coder-1.5B-Instruct --write-beside

The `--manifest-only` path runs anywhere and is what the suite pins; the full
path needs the `[gpu]` extra and a GPU. Determinism, scale, and the no-execution
rule are the threats named in train.py and docs/322 §3.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import eval as p2_eval
from . import manifest as p2_manifest

BESIDE = Path(__file__).resolve().parent.parent  # benchmark/poisoned_pool/


# ---------------------------------------------------------------------------
# Synthesize a fresh, deterministic P1 run so the completion bytes (the
# patches the manifest needs) exist on disk. Reuses run2's exact config.
# ---------------------------------------------------------------------------

def synthesize_p1_run(run_dir: Path) -> List[Dict]:
    """Drive the GPU-free synthetic-policy P1 run (run2's config) to completion
    in `run_dir`, returning the adjudicated rows. Idempotent-ish: refuses to
    clobber an existing run (run.py's guard), so callers pass a fresh dir."""
    from .. import run as pp_run
    from ..run2 import RUN2, POLICY
    src = run_dir / "p1"
    pp_run.init_run(src, policy=POLICY, **RUN2)
    for _ in range(RUN2["gens"]):
        pp_run.drive_run(src, policy_name=POLICY["name"])
        pp_run.ingest_run(src)
    rows: List[Dict] = []
    traj = src / "trajectories.jsonl"
    for line in traj.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Build both arms' manifests + the manifest-poison audit (the CPU preflight).
# ---------------------------------------------------------------------------

def build_manifests(rows: List[Dict],
                    loader: p2_manifest.CompletionLoader) -> Dict:
    sft = {arm: p2_manifest.build_sft_manifest(rows, arm, loader)
           for arm in ("S", "W")}
    dpo_W = p2_manifest.build_dpo_manifest(rows, loader)
    audit = {arm: p2_manifest.manifest_poison(recs) for arm, recs in sft.items()}
    return {"sft": sft, "dpo_W": dpo_W, "audit": audit}


def write_manifests(run_dir: Path, built: Dict) -> None:
    md = run_dir / "manifests"
    md.mkdir(parents=True, exist_ok=True)
    for arm, recs in built["sft"].items():
        (md / f"sft_{arm}.jsonl").write_text(
            "\n".join(json.dumps(r.to_json()) for r in recs) + "\n",
            encoding="utf-8")
    (md / "dpo_W.jsonl").write_text(
        "\n".join(json.dumps(r.to_json()) for r in built["dpo_W"]) + "\n",
        encoding="utf-8")
    (md / "audit.json").write_text(
        json.dumps(built["audit"], indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# The full GPU path — train both arms, eval both on the held-out set.
# ---------------------------------------------------------------------------

def train_and_eval(run_dir: Path, built: Dict, *, base_model: str,
                   k_eval: int = 3, seed: int = 7, epochs: float = 3.0) -> Dict:
    from . import train as p2_train  # lazy — needs the [gpu] extra
    prompts = p2_manifest.heldout_eval_prompts(k_eval=k_eval)
    arms: Dict[str, Dict] = {}
    for arm in ("S", "W"):
        cfg = p2_train.TrainConfig(
            base_model=base_model, seed=seed, epochs=epochs,
            output_dir=str(run_dir / f"adapter_{arm}"))
        summary = p2_train.train_sft(built["sft"][arm], cfg)
        completions = p2_train.generate(cfg.output_dir, prompts, cfg)
        result = p2_eval.eval_arm(prompts, completions)
        (run_dir / f"completions_{arm}.json").write_text(
            json.dumps(completions, indent=2), encoding="utf-8")
        arms[arm] = {
            "train_summary": summary,
            "manifest_audit": built["audit"][arm],
            "heldout": result["metrics"],
            "rows": result["rows"],
        }
    return {"base_model": base_model, "k_eval": k_eval, "seed": seed,
            "epochs": epochs, "n_heldout_prompts": len(prompts), "arms": arms}


# ---------------------------------------------------------------------------
# Evidence — the stamped RESULTS_run3.md beside the bench.
# ---------------------------------------------------------------------------

def _stamp_line() -> str:
    import dos
    sha = ""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            sha = out.stdout.strip()
    except OSError:
        pass
    date = datetime.date.today().isoformat()
    mid = f" sha={sha}" if sha else ""
    return f"<!-- dos-bench-stamp: kernel={dos.__version__}{mid} date={date} -->"


def render_results_md(results: Dict, *, manifest_only: bool) -> str:
    a = results.get("arms", {})
    lines = [
        "# poisoned_pool — run 3: real weights (docs/322 P2, issue #36)",
        "",
        _stamp_line(),
        "",
        "> Does training a policy's WEIGHTS on a self-judged admitted pool "
        "(Arm S) carry poison the witness-gated kernel pool (Arm W, "
        "dos.reward.admit) keeps out by construction — measured on a held-out "
        "set the pools never trained on?",
        "",
    ]
    if manifest_only:
        lines += [
            "## Manifest preflight (CPU — no weights moved yet)",
            "",
            "This block is the GPU-free preflight: it builds each arm's SFT "
            "training manifest from a finished P1 run and audits the poison "
            "fraction of the TRAINING set. The full run (below, once a GPU is "
            "available) LoRA-SFTs both arms and measures the trained model on "
            "the held-out set.",
            "",
            "| arm | manifest size | poison_n | poison_frac |",
            "|---|---|---|---|",
        ]
        for arm in ("S", "W"):
            au = results["audit"][arm]
            lines.append(f"| {arm} | {au['size']} | {au['poison_n']} | "
                         f"{au['poison_frac']:.3f} |")
        lines += [
            "",
            f"Arm W DPO preference pairs available: {results['dpo_W_pairs']} "
            "(chosen = witness-confirmed, rejected = REJECT_POISON).",
            "",
            "**The structural floor (docs/234), visible already in the "
            "manifest:** Arm S's training set carries the over-claim poison "
            "(poison_frac > 0); Arm W's is exactly 0 — the kernel cannot admit "
            "a refuted claim, so it cannot enter the manifest. Weights have not "
            "moved yet; what moves them is the manifest, and the manifests "
            "already differ in exactly the predicted way.",
        ]
        return "\n".join(lines) + "\n"

    lines += [
        f"Base model: `{results['base_model']}` · LoRA SFT · "
        f"{results['epochs']} epochs · seed {results['seed']} · "
        f"held-out prompts: {results['n_heldout_prompts']}.",
        "",
        "## The held-out metrics (weights actually moved)",
        "",
        "| metric | Arm S (self-judged pool) | Arm W (dos.reward.admit pool) |",
        "|---|---|---|",
    ]
    def cell(arm, key):
        v = a[arm]["heldout"].get(key)
        return f"{v:.3f}" if isinstance(v, float) else str(v)
    for key, label in (
        ("overclaim_rate", "held-out over-claim rate"),
        ("true_success_rate", "held-out true success rate"),
        ("claim_rate", "held-out claim rate"),
    ):
        lines.append(f"| {label} | {cell('S', key)} | {cell('W', key)} |")
    lines += [
        f"| training-set poison fraction | "
        f"{a['S']['manifest_audit']['poison_frac']:.3f} | "
        f"{a['W']['manifest_audit']['poison_frac']:.3f} |",
        f"| training-set size | {a['S']['manifest_audit']['size']} | "
        f"{a['W']['manifest_audit']['size']} |",
        "",
        "## Per-arm detail",
        "",
        "```json",
        json.dumps({arm: {"train_summary": a[arm]["train_summary"],
                          "manifest_audit": a[arm]["manifest_audit"],
                          "heldout": a[arm]["heldout"]}
                    for arm in ("S", "W")}, indent=2),
        "```",
        "",
        "Threats to validity: small N (counts ship beside rates); GPU "
        "training/sampling is not bit-reproducible across hardware (base model "
        "+ library versions + seed recorded above); the no-execution rule is "
        "instruction-enforced and can only DEFLATE over-claims symmetrically. "
        "See docs/322 §3.",
    ]
    return "\n".join(lines) + "\n"


def report(run_dir: Path, results: Dict, *, manifest_only: bool,
           write_beside: bool = False) -> None:
    out_json = run_dir / "results_run3.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md = render_results_md(results, manifest_only=manifest_only)
    (run_dir / "RESULTS_run3.md").write_text(md, encoding="utf-8")
    if write_beside:
        (BESIDE / "results_run3.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8")
        (BESIDE / "RESULTS_run3.md").write_text(md, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m benchmark.poisoned_pool.p2.run_p2")
    p.add_argument("--run-dir", required=True, type=Path,
                   help="where to synthesize the P1 run + write manifests, "
                        "adapters, and evidence")
    p.add_argument("--base-model", default=None,
                   help="HF base model id (default: the small coder in train.py)")
    p.add_argument("--k-eval", type=int, default=3)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--manifest-only", action="store_true",
                   help="CPU preflight: build + audit manifests, no training")
    p.add_argument("--write-beside", action="store_true",
                   help="also write the evidence beside the bench package")
    a = p.parse_args(argv)

    run_dir = a.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = synthesize_p1_run(run_dir)
    loader = p2_manifest.run_dir_loader(run_dir / "p1")
    built = build_manifests(rows, loader)
    write_manifests(run_dir, built)

    if a.manifest_only:
        results = {
            "plan": "docs/322", "issue": 36, "mode": "manifest-only",
            "rows_source": "synthesized P1 run (run2 config)",
            "audit": built["audit"],
            "dpo_W_pairs": len(built["dpo_W"]),
        }
        report(run_dir, results, manifest_only=True, write_beside=a.write_beside)
        print(json.dumps({"mode": "manifest-only", "audit": built["audit"],
                          "dpo_W_pairs": len(built["dpo_W"])}, indent=2))
        return 0

    from . import train as p2_train  # noqa: F401 — fail fast if the extra is absent
    base_model = a.base_model or p2_train.DEFAULT_BASE_MODEL
    results = train_and_eval(
        run_dir, built, base_model=base_model, k_eval=a.k_eval,
        seed=a.seed, epochs=a.epochs)
    results.update({"plan": "docs/322", "issue": 36, "mode": "real-weights",
                    "rows_source": "synthesized P1 run (run2 config)",
                    "dpo_W_pairs": len(built["dpo_W"])})
    report(run_dir, results, manifest_only=False, write_beside=a.write_beside)
    print(json.dumps({arm: results["arms"][arm]["heldout"]
                      for arm in ("S", "W")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
