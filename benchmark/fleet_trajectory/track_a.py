"""Track A — concurrent over-write detection (the fleet-of-one wall, inverted).

Question: when two sessions held overlapping file regions in the same time
window, did one silently clobber the other's uncommitted work?

No public benchmark can pose this — they have no second writer. Here it is the
dominant condition (280/285 sessions overlap a sibling, docs/243 §1).

GOLD (unforgeable — the session authors none of it):
  - the per-path EDIT WINDOWS (timestamps the CC harness stamped, not the agent),
  - the interval overlap between two sessions,
  - the actual git commit time for that path (when a commit landed for it).

A pair sharing an in-tree path is classified per shared path:
  CLOBBER     two sessions both WROTE the path with INTERLEAVED windows and no
              commit landed between the first writer's last edit and the second
              writer's first edit — the literal last-writer-wins window where the
              first session's uncommitted bytes could be lost.
  SERIALIZED  they share the path but the windows are separated by a commit (or
              are strictly non-interleaved with a gap) — the second built ON the
              first; no loss hazard.
  DISJOINT    no shared in-tree path at all.

We then score the kernel: would `lane_overlap.overlap_verdict` have REFUSED the
colliding lease (treating each session's edited path-set as its requested tree)?
That is the docs/233 coordination metric — but on a REAL collision distribution
mined from this corpus, not a constructed one.

The payoff (not the rate): of the CLOBBER pairs, how many *actually* lost an edit
— i.e. the earlier writer's bytes never reached git because the later writer
overwrote the file and committed its own version. That is the
[[project-dos-intervention-bench-must-be-live-reactive]] discipline: rate != payoff.
"""
from __future__ import annotations

import datetime
import json
import subprocess
from dataclasses import dataclass, asdict

import dos.lane_overlap as lane_overlap
from benchmark.fleet_trajectory.corpus import DOS_TREE_ROOT, Session, load_corpus


# A commit landing for a path between two windows means the work was serialized
# through git. We also accept a plain temporal gap (no interleave) as serialized.
@dataclass
class PairLabel:
    session_i: str  # .jsonl basename
    session_j: str
    sid_i: str
    sid_j: str
    region: list[str]  # the shared in-tree paths
    label: str  # CLOBBER | SERIALIZED | DISJOINT
    n_shared: int
    # the kernel's verdict on the two path-sets
    kernel_verdict: str  # REFUSE_* | ADMIT_*
    kernel_would_refuse: bool
    # the consequential payoff signal (only meaningful for CLOBBER)
    interleaved_paths: list[str]  # shared paths whose windows actually interleaved
    window_detail: dict  # per-path window timing for audit


def _interleaved(
    w_i: tuple[datetime.datetime, datetime.datetime],
    w_j: tuple[datetime.datetime, datetime.datetime],
) -> bool:
    """Do two edit windows for the SAME path interleave (each writes while the
    other is also live)? Strict overlap of the two [first,last] intervals."""
    return w_i[0] < w_j[1] and w_j[0] < w_i[1]


def _repo_relative(path: str) -> str:
    """Recover a repo-relative path from a normalized absolute one by stripping
    everything up to and including the tree-root COMPONENT (`/<DOS_TREE_ROOT>/`).
    Sourced from the configurable basename (default "dos") rather than the author's
    `work/dos/` layout, so it is portable to any clone location. Falls back to the
    full path when the root component is absent."""
    needle = "/" + DOS_TREE_ROOT.replace("\\", "/").lower() + "/"
    idx = path.find(needle)
    return path[idx + len(needle):] if idx >= 0 else path


def _git_commit_times_for_path(path: str, repo: str) -> list[datetime.datetime]:
    """All commit author-times that touched `path` (the unforgeable serialization
    boundary). `path` is normalized (forward-slash, lowercased); we recover a
    repo-relative path via the tree-root component."""
    rel = _repo_relative(path)
    try:
        out = subprocess.run(
            ["git", "-C", repo, "log", "--all", "--format=%aI", "--", rel],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return []
    times = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            times.append(datetime.datetime.fromisoformat(line))
        except Exception:
            pass
    return times


def _commit_between(
    times: list[datetime.datetime], lo: datetime.datetime, hi: datetime.datetime
) -> bool:
    return any(lo < t < hi for t in times)


def classify_pair(
    s_i: Session, s_j: Session, repo: str, *, use_git: bool = True
) -> PairLabel | None:
    """Label one overlapping session pair. Returns None if the sessions don't
    temporally overlap (not a candidate)."""
    if not s_i.overlaps(s_j):
        return None
    shared = sorted(s_i.edited_paths & s_j.edited_paths)
    # the kernel verdict is always computable from the two requested path-sets
    tree_i = sorted(s_i.edited_paths)
    tree_j = sorted(s_j.edited_paths)
    if tree_i and tree_j:
        dec = lane_overlap.overlap_verdict(tree_i, tree_j)
        kv = dec.verdict.name
        kwr = not dec.admissible
    else:
        kv, kwr = "ADMIT_DISJOINT", False

    if not shared:
        return PairLabel(
            session_i=s_i.path_file, session_j=s_j.path_file,
            sid_i=s_i.sid, sid_j=s_j.sid, region=[], label="DISJOINT",
            n_shared=0, kernel_verdict=kv, kernel_would_refuse=kwr,
            interleaved_paths=[], window_detail={},
        )

    interleaved: list[str] = []
    detail: dict = {}
    for p in shared:
        w_i = s_i.edit_window(p)
        w_j = s_j.edit_window(p)
        if not (w_i and w_j):
            continue
        il = _interleaved(w_i, w_j)
        # a commit landing between the earlier window's end and the later
        # window's start serializes the two — no clobber.
        first, second = (w_i, w_j) if w_i[0] <= w_j[0] else (w_j, w_i)
        serialized_by_commit = False
        if use_git:
            ctimes = _git_commit_times_for_path(p, repo)
            serialized_by_commit = _commit_between(ctimes, first[1], second[0])
        detail[p] = {
            "win_i": [w_i[0].isoformat(), w_i[1].isoformat()],
            "win_j": [w_j[0].isoformat(), w_j[1].isoformat()],
            "interleaved": il,
            "serialized_by_commit": serialized_by_commit,
        }
        if il and not serialized_by_commit:
            interleaved.append(p)

    label = "CLOBBER" if interleaved else "SERIALIZED"
    return PairLabel(
        session_i=s_i.path_file, session_j=s_j.path_file,
        sid_i=s_i.sid, sid_j=s_j.sid, region=shared, label=label,
        n_shared=len(shared), kernel_verdict=kv, kernel_would_refuse=kwr,
        interleaved_paths=interleaved, window_detail=detail,
    )


def label_corpus(
    repo: str, *, corpus_dir: str | None = None, use_git: bool = True,
    exclude_sids: set[str] | None = None, before: "datetime.datetime | None" = None,
) -> list[PairLabel]:
    """Label every overlapping session pair that shares ≥1 in-tree path.

    To keep it O(useful) we only emit a PairLabel for pairs that either (a) share
    a path, or (b) overlap and we want the DISJOINT negative — we emit the shared
    ones (the interesting cells) and a count of pure-disjoint overlaps separately
    via summarize().
    """
    kw = {} if corpus_dir is None else {"corpus_dir": corpus_dir}
    sessions = load_corpus(exclude_sids=exclude_sids, before=before, **kw)
    labels: list[PairLabel] = []
    for i in range(len(sessions)):
        si = sessions[i]
        if not si.edited_paths:
            continue
        for j in range(i + 1, len(sessions)):
            sj = sessions[j]
            # sessions are sorted by start; once sj starts after si ends, no
            # later sj can overlap si either.
            if sj.start and si.end and sj.start >= si.end:
                break
            if not (si.edited_paths & sj.edited_paths):
                continue  # we only materialize shared-path pairs
            pl = classify_pair(si, sj, repo, use_git=use_git)
            if pl is not None:
                labels.append(pl)
    return labels


def concurrency_census(
    *, corpus_dir: str | None = None, exclude_sids: set[str] | None = None,
    before: "datetime.datetime | None" = None,
) -> dict:
    """The DENOMINATOR + the SPECIFICITY check — the honest framing that keeps
    Track A from reading as "the kernel refuses everything."

    Over ALL temporally-overlapping editing pairs, split by share-a-path vs
    disjoint-paths, and ask the kernel its verdict on each. The load-bearing number
    is SPECIFICITY: of the disjoint-path concurrent pairs (safe parallelism), what
    fraction does the kernel correctly ADMIT? A referee that refuses safe
    concurrency is useless; this proves it doesn't."""
    kw = {} if corpus_dir is None else {"corpus_dir": corpus_dir}
    sessions = [s for s in load_corpus(exclude_sids=exclude_sids, before=before, **kw) if s.edited_paths]
    n_temporal = n_shared = n_disjoint = 0
    admit_disjoint = refuse_disjoint = 0
    refuse_shared = admit_shared = 0
    for i in range(len(sessions)):
        si = sessions[i]
        for j in range(i + 1, len(sessions)):
            sj = sessions[j]
            if sj.start and si.end and sj.start >= si.end:
                break
            if not si.overlaps(sj):
                continue
            n_temporal += 1
            dec = lane_overlap.overlap_verdict(sorted(si.edited_paths), sorted(sj.edited_paths))
            if si.edited_paths & sj.edited_paths:
                n_shared += 1
                if dec.admissible:
                    admit_shared += 1
                else:
                    refuse_shared += 1
            else:
                n_disjoint += 1
                if dec.admissible:
                    admit_disjoint += 1
                else:
                    refuse_disjoint += 1
    return {
        "concurrent_editing_pairs": n_temporal,
        "share_a_path": n_shared,
        "disjoint_paths": n_disjoint,
        "kernel_refuses_of_shared": refuse_shared,
        "kernel_admits_of_shared": admit_shared,
        "sensitivity_refuse_shared": round(refuse_shared / n_shared, 4) if n_shared else None,
        "kernel_admits_of_disjoint": admit_disjoint,
        "kernel_false_refuses_of_disjoint": refuse_disjoint,
        "specificity_admit_disjoint": round(admit_disjoint / n_disjoint, 4) if n_disjoint else None,
        "n_sessions": len(sessions),
    }


def summarize(labels: list[PairLabel]) -> dict:
    """The headline numbers: collisions found, fraction the kernel would prevent,
    fraction that interleaved (the consequential-clobber payoff)."""
    by_label = {"CLOBBER": 0, "SERIALIZED": 0, "DISJOINT": 0}
    for l in labels:
        by_label[l.label] = by_label.get(l.label, 0) + 1
    shared_pairs = [l for l in labels if l.n_shared > 0]
    clobbers = [l for l in labels if l.label == "CLOBBER"]
    # of the real collisions (shared-path pairs), how many would the kernel refuse?
    kernel_refused = sum(1 for l in shared_pairs if l.kernel_would_refuse)
    # of the CLOBBER pairs (the consequential ones), how many would it refuse?
    clobber_refused = sum(1 for l in clobbers if l.kernel_would_refuse)
    return {
        "pairs_with_shared_region": len(shared_pairs),
        "label_distribution": by_label,
        "kernel_would_refuse_of_shared": kernel_refused,
        "kernel_refuse_frac_of_shared": round(kernel_refused / len(shared_pairs), 4) if shared_pairs else None,
        "clobber_pairs": len(clobbers),
        "kernel_would_refuse_of_clobbers": clobber_refused,
        "kernel_refuse_frac_of_clobbers": round(clobber_refused / len(clobbers), 4) if clobbers else None,
        "distinct_clobbered_paths": sorted({p for l in clobbers for p in l.interleaved_paths}),
    }


if __name__ == "__main__":
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Track A — concurrent over-write labeler")
    ap.add_argument("--repo", default=os.getcwd(), help="git repo root (gold)")
    ap.add_argument("--no-git", action="store_true", help="skip git commit-boundary check (faster, looser)")
    ap.add_argument("--exclude-sid", action="append", default=[], help="self-witness guard: exclude these session ids")
    ap.add_argument("--auto-exclude-self", action="store_true",
                    help="auto-detect + exclude the currently-running session (docs/243 caveat #1)")
    ap.add_argument("--before", help="FREEZE: drop sessions starting at/after this ISO instant (reproducible snapshot)")
    ap.add_argument("--json", action="store_true", help="emit full per-pair labels as JSON")
    ap.add_argument("--out", help="write labels JSONL to this path")
    args = ap.parse_args()

    from benchmark.fleet_trajectory.corpus import detect_self_sid, parse_ts

    exclude = set(args.exclude_sid)
    if args.auto_exclude_self:
        self_sid = detect_self_sid()
        if self_sid:
            exclude.add(self_sid)
            print(f"[self-witness guard] excluding running session {self_sid}", flush=True)
    before = parse_ts(args.before) if args.before else None

    census = concurrency_census(exclude_sids=exclude, before=before)
    labels = label_corpus(
        args.repo, use_git=not args.no_git, exclude_sids=exclude, before=before
    )
    summ = summarize(labels)
    report = {"census": census, "labels": summ}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for l in labels:
                fh.write(json.dumps(asdict(l)) + "\n")
    if args.json:
        print(json.dumps([asdict(l) for l in labels], indent=2))
    else:
        print(json.dumps(report, indent=2))
        print("\n--- the honest framing ---")
        print(f"  {census['concurrent_editing_pairs']} concurrent editing pairs; "
              f"{census['disjoint_paths']} are region-disjoint and the kernel ADMITS "
              f"{census['specificity_admit_disjoint']:.0%} of them (specificity — it does NOT refuse safe parallelism).")
        print(f"  {census['share_a_path']} share a write region; the kernel refuses "
              f"{census['sensitivity_refuse_shared']:.0%} (sensitivity).")
        print(f"  of those, {summ['clobber_pairs']} actually INTERLEAVED with no commit between "
              f"(the consequential last-writer-wins clobbers); kernel would refuse "
              f"{summ['kernel_refuse_frac_of_clobbers']:.0%}.")
        print("\n--- CLOBBER pairs (the consequential cells) ---")
        for l in labels:
            if l.label == "CLOBBER":
                print(f"  {l.session_i[:12]} x {l.session_j[:12]}  "
                      f"kernel={'REFUSE' if l.kernel_would_refuse else 'admit '}  "
                      f"paths={l.interleaved_paths}")
