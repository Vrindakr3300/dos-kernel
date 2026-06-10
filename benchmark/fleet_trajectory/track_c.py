"""Track C — recovery-vs-collapse after a detected error (detect->fix, confound named).

Question: after a terminal error / failed tool call, did the session RECOVER, GIVE
UP CORRECTLY, THRASH, or GIVE UP WRONGLY?

The detect->fix wall (docs/204 §4) is unsolved, and docs/236 found self-recovery is
a CONFOUND: believe-B self-recovers 3/5, so ΔB≈0 at the easy hop. A real corpus
lets us MEASURE the base recovery rate instead of assuming it — and it does: of the
error events in this corpus, the overwhelming majority self-recover. That is the
docs/236 confound made visible off bytes we didn't author, and it is WHY in-loop
intervention payoff was ≈0.

GOLD (the session authors none of it): the subsequent tool-result stream + the
mutation deltas (the `liveness`/`productivity` evidence — was the run ADVANCING or
SPINNING?).

  RECOVERED          after the error, the SAME tool later SUCCEEDS, or a mutation
                     lands and the session keeps producing work (productivity not
                     STALLED). The error was a transient the agent worked through.
  THRASHED           the same failing call (same tool + same input signature)
                     repeats >= THRASH_MIN times — the read-loop / phantom-key
                     signature ([[project-dos-phantom-key-detector]]). Productivity
                     STALLS on a flat/zero delta sequence.
  GAVE_UP            the session ENDS at/near the error with no further mutation and
                     no recovery. Whether that was CORRECT (the task was genuinely
                     infeasible — the feasibility witness, docs/198) or WRONG (a
                     recoverable error abandoned) is a W3-goal judgment that bottoms
                     out at HUMAN on this repo, so we label GAVE_UP and ABSTAIN on
                     the correct/wrong split rather than fake a witness for it.

The benchmark instance: (session, error_event) -> {RECOVERED, THRASHED, GAVE_UP}.
Scoring DOS = does `productivity`/`breaker` call the shape (STALLED / OPEN) on the
same evidence, BEFORE a human would? This is the only track where positive-fix
value is real, so it is where DOS's honest ceiling shows: a high base recovery rate
means the *room* for a fix is small (the docs/236 lesson, measured here).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict

import dos.breaker as breaker
import dos.productivity as productivity
from benchmark.fleet_trajectory.corpus import Session, ToolEvent, load_corpus


RECOVERED = "RECOVERED"
THRASHED = "THRASHED"
GAVE_UP = "GAVE_UP"

THRASH_MIN = 2  # repeated identical failing calls to call it a thrash
AFTERMATH_WINDOW = 12  # events after the error we look at for the shape


@dataclass
class ErrorLabel:
    sid: str
    session_file: str
    error_tool: str
    error_sig: str  # redaction-safe input signature
    label: str  # RECOVERED | THRASHED | GAVE_UP
    n_repeats: int  # identical failing repeats after this error
    recovered_same_tool: bool  # the same tool later succeeded
    mutation_after: bool
    # the kernel's verdict on the post-error work trend
    productivity_verdict: str  # PRODUCTIVE | DIMINISHING | STALLED
    kernel_calls_stall: bool  # productivity == STALLED (the kernel's "spinning" call)
    # the kernel's COUNTER verdict — the right lens for a SHORT consecutive thrash
    # that a trend verdict won't catch
    breaker_opens: bool
    consecutive_fail_run: int  # consecutive failures from this error forward


def _post_error_deltas(after: list[ToolEvent]) -> list[float]:
    """Per-step 'work delta' proxy for the productivity verdict: a successful
    mutation is real work (delta 1.0); a successful non-mutation is partial work
    (0.4); a repeated error is zero work (0.0). This is the CALLER's measurement at
    the evidence boundary — the verdict itself stays magnitude-only."""
    deltas: list[float] = []
    for a in after[:AFTERMATH_WINDOW]:
        if a.is_error is True:
            deltas.append(0.0)
        elif a.name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
            deltas.append(1.0)
        else:
            deltas.append(0.4)
    return deltas


def _score_productivity(deltas: list[float]) -> tuple[str, bool]:
    if len(deltas) < 3:
        return ("UNKNOWN", False)
    # scale to the policy floor (default 500): map our 0..1 proxy to 0..1000
    scaled = [int(d * 1000) for d in deltas]
    hist = productivity.WorkHistory(deltas=tuple(scaled))
    verdict = productivity.classify(hist)
    name = verdict.productivity.name if hasattr(verdict, "productivity") else str(verdict)
    return (name, name == "STALLED")


def _consecutive_fail_run(events: list[ToolEvent], idx: int) -> int:
    """Count the run of consecutive error events starting at idx (inclusive)."""
    n = 0
    for a in events[idx:]:
        if a.is_error is True:
            n += 1
        else:
            break
    return n


def _breaker_opens(run_len: int) -> bool:
    """Would the circuit breaker OPEN given a consecutive-failure run of this
    length? Drive the pure kernel state machine, default policy (max_consecutive=3)."""
    counts = breaker.BreakerCounts()
    opened = False
    for _ in range(run_len):
        t = breaker.record_failure(counts)
        counts = t.counts if hasattr(t, "counts") else counts
        if breaker.classify(counts).is_open:
            opened = True
            break
    return opened


def label_error(session: Session, idx: int, events: list[ToolEvent]) -> ErrorLabel:
    e = events[idx]
    after = events[idx + 1:]
    same_repeats = sum(
        1 for a in after[:AFTERMATH_WINDOW]
        if a.name == e.name and a.input_repr == e.input_repr and a.is_error is True
    )
    recovered_same = any(
        a.name == e.name and a.is_error is False for a in after[:AFTERMATH_WINDOW]
    )
    mutation_after = any(a.name in ("Edit", "Write", "NotebookEdit", "MultiEdit") for a in after)
    prod_name, calls_stall = _score_productivity(_post_error_deltas(after))
    run_len = _consecutive_fail_run(events, idx)
    breaker_opens = _breaker_opens(run_len)

    if same_repeats >= THRASH_MIN:
        label = THRASHED
    elif not after:
        label = GAVE_UP
    elif recovered_same or mutation_after:
        label = RECOVERED
    else:
        # error followed only by non-recovering activity then stop
        label = GAVE_UP

    return ErrorLabel(
        sid=session.sid, session_file=session.path_file, error_tool=e.name,
        error_sig=e.input_repr[:60], label=label, n_repeats=same_repeats,
        recovered_same_tool=recovered_same, mutation_after=mutation_after,
        productivity_verdict=prod_name, kernel_calls_stall=calls_stall,
        breaker_opens=breaker_opens, consecutive_fail_run=run_len,
    )


def label_corpus(*, corpus_dir=None, exclude_sids=None, before=None) -> list[ErrorLabel]:
    kw = {} if corpus_dir is None else {"corpus_dir": corpus_dir}
    sessions = load_corpus(exclude_sids=exclude_sids, before=before, **kw)
    out: list[ErrorLabel] = []
    for s in sessions:
        ev = sorted(s.tool_events, key=lambda e: e.ts)
        for idx, e in enumerate(ev):
            if e.is_error is True:
                out.append(label_error(s, idx, ev))
    return out


def summarize(labels: list[ErrorLabel]) -> dict:
    from collections import Counter
    by = Counter(l.label for l in labels)
    n = len(labels)
    # the base recovery rate — MEASURED, the docs/236 confound made visible
    base_recovery = round(by[RECOVERED] / n, 4) if n else None
    # does the kernel's productivity verdict AGREE with the THRASH label? (scoring DOS)
    thrash = [l for l in labels if l.label == THRASHED]
    kernel_stall_on_thrash = sum(1 for l in thrash if l.kernel_calls_stall)
    recovered = [l for l in labels if l.label == RECOVERED]
    kernel_stall_on_recovered = sum(1 for l in recovered if l.kernel_calls_stall)  # false-alarm check
    # the BREAKER (a counter) is the right lens for a sustained consecutive run that
    # the trend verdict won't catch. Longest consecutive-fail runs = the genuine
    # stuck points; does the breaker open on them, and stay shut on the rest?
    breaker_opens_all = sum(1 for l in labels if l.breaker_opens)
    longest_run = max((l.consecutive_fail_run for l in labels), default=0)
    breaker_open_recovered = sum(1 for l in recovered if l.breaker_opens)
    return {
        "total_error_events": n,
        "label_distribution": dict(by),
        "base_recovery_rate": base_recovery,
        "thrash_events": len(thrash),
        "longest_consecutive_fail_run": longest_run,
        # productivity (trend) lens
        "productivity_stall_on_thrash": kernel_stall_on_thrash,
        "productivity_stall_on_recovered_false_alarm": kernel_stall_on_recovered,
        "productivity_false_alarm_rate": round(kernel_stall_on_recovered / len(recovered), 4) if recovered else None,
        # breaker (counter) lens — the right one for short sustained thrash
        "breaker_opens_total": breaker_opens_all,
        "breaker_opens_on_recovered_false_alarm": breaker_open_recovered,
        "breaker_false_alarm_rate": round(breaker_open_recovered / len(recovered), 4) if recovered else None,
        "note": "high base_recovery_rate => the ROOM for an in-loop fix is small "
                "(docs/236 confound, measured here off bytes we did not author). "
                "productivity is a TREND verdict (won't fire on a 2-repeat blip that "
                "recovers — correctly); breaker is a COUNTER (the right lens for a "
                "sustained consecutive run). Different shapes, different kernel verdicts.",
    }


if __name__ == "__main__":
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from benchmark.fleet_trajectory.corpus import detect_self_sid, parse_ts

    ap = argparse.ArgumentParser(description="Track C — recovery-vs-collapse labeler")
    ap.add_argument("--auto-exclude-self", action="store_true")
    ap.add_argument("--exclude-sid", action="append", default=[])
    ap.add_argument("--before")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--show-thrash", action="store_true")
    args = ap.parse_args()

    exclude = set(args.exclude_sid)
    if args.auto_exclude_self:
        sid = detect_self_sid()
        if sid:
            exclude.add(sid)
            print(f"[self-witness guard] excluding {sid}", flush=True)
    before = parse_ts(args.before) if args.before else None

    labels = label_corpus(exclude_sids=exclude, before=before)
    summ = summarize(labels)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for l in labels:
                fh.write(json.dumps(asdict(l)) + "\n")
    if args.json:
        print(json.dumps([asdict(l) for l in labels], indent=2))
    else:
        print(json.dumps(summ, indent=2))
        if args.show_thrash:
            print("\n--- THRASHED error events (the read-loop / phantom-key signature) ---")
            for l in labels:
                if l.label == THRASHED:
                    print(f"  [{l.error_tool}] x{l.n_repeats}  prod={l.productivity_verdict}  {l.error_sig!r}")
