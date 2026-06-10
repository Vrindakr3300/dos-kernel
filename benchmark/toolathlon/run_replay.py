"""CLI: replay the Toolathlon-Trajectories dataset through the DOS detectors and report PURCHASE.

    # list the dataset files (66 = 22 models x 3 runs, read live from the HF API)
    python -m benchmark.toolathlon.run_replay --list

    # smoke: one model, one run, first 10 records (downloads ~one file)
    python -m benchmark.toolathlon.run_replay --files gemini-2.5-flash_1.jsonl --limit 10

    # a few diverse models, all runs, full files -> JSON + table
    python -m benchmark.toolathlon.run_replay \
        --files claude-4.5-sonnet-0929_1.jsonl gpt-5_1.jsonl gemini-2.5-flash_1.jsonl \
        --out _results/replay.json

    # everything (all 66 files; large download, ~minutes; $0, no API)
    python -m benchmark.toolathlon.run_replay --all --out _results/replay_all.json

The headline is the per-detector confusion grid joined to the THIRD-PARTY `task_status.evaluation`
label: fire-rate, oracle-confirmed precision, recall-of-failures, and lift-over-base. This measures
DETECT, not FIX (frozen trajectory => no intervention => no lift number) — the docs/157 boundary.
"""

from __future__ import annotations

import argparse
import json
import sys

from dos.tool_stream import StreamState

from .dataset import DEFAULT_CACHE, list_files, load_corpus
from .replay import DetectorReport, replay


def _fmt_pct(x) -> str:
    return "  —  " if x is None else f"{x*100:5.1f}%"


def _print_detector(rep: DetectorReport, indent: str = "") -> None:
    print(
        f"{indent}{rep.name:<16} "
        f"fire={_fmt_pct(rep.fire_rate)}  "
        f"prec={_fmt_pct(rep.oracle_confirmed_precision)}  "
        f"(base={_fmt_pct(rep.base_fail_rate)})  "
        f"lift={_fmt_pct(rep.lift_over_base)}  "
        f"recall={_fmt_pct(rep.recall_of_failures)}  "
        f"falarm={_fmt_pct(rep.false_alarm_rate)}  "
        f"[fired={rep.fired} fail/pass={rep.fired_fail}/{rep.fired_pass} n={rep.labeled}]"
    )


def main(argv=None) -> int:
    # Windows console is cp1252 — force UTF-8 so the em-dash / CJK task text doesn't crash printing.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Replay Toolathlon trajectories through DOS detectors.")
    ap.add_argument("--list", action="store_true", help="list the dataset files and exit")
    ap.add_argument("--files", nargs="*", default=None, help="specific <model>_<run>.jsonl files")
    ap.add_argument("--all", action="store_true", help="use every file in the dataset")
    ap.add_argument("--limit", type=int, default=None, help="max records per file (smoke)")
    ap.add_argument("--no-download", action="store_true", help="use only cached files (offline)")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="cache dir for downloaded JSONL")
    ap.add_argument("--out", default=None, help="write the full report JSON here")
    ap.add_argument(
        "--rows-out",
        default=None,
        help="write the FLAT durable per-run rows here (.jsonl + a sibling .csv) — the explorable "
        "unit: one row per (model, run, task) with the detector verdicts + the third-party label",
    )
    ap.add_argument(
        "--ts-min-state",
        choices=["REPEATING", "STALLED"],
        default="REPEATING",
        help="the tool_stream peak state that counts as a fire (default REPEATING)",
    )
    ap.add_argument(
        "--raw-digest",
        action="store_true",
        help="digest RAW result bytes (the conservative LOWER-BOUND floor) instead of masking "
        "volatile env fields (timestamps/UUIDs/etc) — the docs/157 §4 normalizer is ON by default",
    )
    ap.add_argument(
        "--te-recovery",
        choices=["aware", "specific-only", "none"],
        default="aware",
        help="terminal_error recovery-check confidence knob (docs/162): 'aware' (default, "
        "conservative — any later same-tool success suppresses), 'specific-only' (surgical — a "
        "generic-executor recovery never suppresses; the same-tool-≠-same-operation finding), or "
        "'none' (aggressive — recovery ignored, the docs/159 §4b tight-no-recovery floor)",
    )
    ap.add_argument("--by-model", action="store_true", help="print the per-model breakdown table")
    args = ap.parse_args(argv)

    from pathlib import Path

    cache = Path(args.cache)

    if args.list:
        for fn in list_files():
            print(fn)
        return 0

    if args.all:
        files = list_files()
    elif args.files:
        files = args.files
    else:
        ap.error("pass --files <f...>, --all, or --list")
        return 2

    print(f"# replaying {len(files)} file(s) through dos.dangling_intent + dos.tool_stream", flush=True)
    corpus = load_corpus(
        files, cache_dir=cache, per_file_limit=args.limit, download=not args.no_download
    )
    result = replay(
        list(corpus), ts_min_state=StreamState[args.ts_min_state], normalize=not args.raw_digest,
        te_recovery=args.te_recovery,
    )

    print(f"\n## corpus: {result.n_records} records\n")
    print("# rates joined to the THIRD-PARTY task_status.evaluation label (None excluded):")
    print("#   prec = oracle-confirmed precision (of fires, fraction the verifier FAILED)")
    print("#   lift = prec - base_fail_rate  (>0 = real purchase; <=0 = no skill)\n")
    _print_detector(result.dangling)
    _print_detector(result.tool_stream)
    _print_detector(result.terminal_error)

    if args.by_model:
        print("\n## by model\n")
        for model, dmap in sorted(result.by_model.items()):
            print(f"  {model}")
            _print_detector(dmap["dangling_intent"], indent="    ")
            _print_detector(dmap["tool_stream"], indent="    ")
            _print_detector(dmap["terminal_error"], indent="    ")

    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"\n# wrote {outp}")

    if args.rows_out:
        import csv

        rp = Path(args.rows_out)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rows = [r.to_dict() for r in result.rows]
        # durable JSONL (one flat record per line — streams into pandas/sqlite/jq with no reshaping)
        with open(rp.with_suffix(".jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        # sibling CSV (loads straight into a spreadsheet / plotting notebook)
        if rows:
            with open(rp.with_suffix(".csv"), "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        print(f"# wrote {rp.with_suffix('.jsonl')} + {rp.with_suffix('.csv')} ({len(rows)} rows)")

    # Honest boundary, printed every run so it is never lost:
    if args.raw_digest:
        ts_note = (
            "tool_stream digested RAW result bytes (--raw-digest) — the conservative LOWER BOUND; "
            "volatile env fields (timestamps/UUIDs) make identical re-reads under-count (docs/157 §4)."
        )
    else:
        ts_note = (
            "tool_stream result_digest NORMALIZED (volatile timestamps/UUIDs/etc masked; docs/157 §4) "
            "— the calibrated estimate; pass --raw-digest for the raw lower-bound floor."
        )
    print(
        "\n# NOTE: this measures DETECT, not FIX — frozen trajectories, no intervention, no lift "
        f"number.\n#       {ts_note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
