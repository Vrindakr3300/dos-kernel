"""The intent ledger — a third durable surface for *declared intent + adjudicated progress* (docs/107 §3).

> **The WAL answers "what was decided about leases." The intent ledger answers
> "what was the run trying to accomplish, and how far did the *evidence* say it
> got." The first is the kernel believing only effects; the second is the kernel
> storing a self-report so it can later distrust it against the fossils.**

DOS already records what a run **decided** (`lane_journal`: leases taken, dropped,
evicted) and what it **committed** (git ancestry). It records nothing about what a
run was **trying to do** and **how far it got** on the part that isn't a commit
yet — so when a run crashes mid-flight, a successor cannot *continue* it (only
`SCAVENGE` its lane). This module is the missing log: an append-only, `fsync`'d,
replay-foldable record of **declared intent** and **progress beats against it**,
one per run, keyed by `run_id` from birth.

It is `lane_journal`'s sibling, deliberately byte-mirroring its ARIES discipline
(`docs/107 §3`):

  * **Same shape, different subject.** `append`/`read_all`/`replay`/`compact`,
    `fsync` on write, torn-tail tolerant (`read_all` skips ONLY the torn final
    line, keeps a mid-file `_CORRUPT` sentinel). Where `lane_journal` folds to a
    *live-lease set*, this folds to a *declared-intent + verified-step set* (the
    `LedgerState`) the pure `resume.resume_plan` consumes.
  * **Different key, which closes a gap as a side effect.** Keyed by `run_id`
    (the ledger lives at ``.dos/runs/<run_id>/intent.jsonl``, next to `run.json`),
    NOT by `(loop_ts, lane)`. So the `(loop_ts,lane)→run_id` join `94 §7` /
    `journal_delta`'s "HARD PROBLEM" flagged is *sidestepped* — the resumption
    data is in a log keyed by `run_id` from the start. The WAL stays exactly what
    it is (lease correctness); this carries the run-scoped progress it was never
    meant to hold.

**The epistemic spine** (`docs/107 §3.2`, the `103`/`102` move): the asymmetry
between `STEP_CLAIMED` (the agent's say-so — *content*, distrusted) and
`STEP_VERIFIED` (a minted belief over git ancestry — *structure*, trusted). Replay
reads `STEP_VERIFIED`s as done and treats every `STEP_CLAIMED` without a matching
`STEP_VERIFIED` as **not done** — fail-closed. This module holds the *vocabulary,
the writers, and the pure replay fold*; the `STEP_VERIFIED` MINT (re-verifying a
claimed SHA against ancestry on the non-forgeable rung) is a CLI-boundary helper
(it does git I/O), exactly as `liveness`'s evidence-gather is a boundary, not the
pure verdict. The pure verdict over a `LedgerState` lives in `dos.resume`.

Write is library-only and happens UNDER the run's own writer (the dispatch loop /
a driver), each run owning its own file — there is no cross-run contention, so
unlike the WAL there is no shared mutex to hold (one writer per `run_id`). `O_APPEND`
+ `fsync` is the durability floor.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

from dos import config as _config
from dos import durable_schema as _schema

# The durable-schema family + version every intent-ledger record carries (§6).
# Bumped ONLY on a NON-additive shape change; a new op or a new optional field is
# additive and does NOT bump it (the `durable_schema` contract). This kernel
# UNDERSTANDS up to `INTENT_LEDGER_SCHEMA` — a record tagged higher is REFUSED at
# read time (`read_all`'s schema gate), never guessed.
SCHEMA_FAMILY = "intent-ledger"
INTENT_LEDGER_SCHEMA = 1

INTENT_JSONL_NAME = "intent.jsonl"

# The closed op vocabulary (§3.2). Additive: a future op a newer writer emits is
# SKIPPED by an older `replay` (it acts only on the ops it knows), the same
# forward-compat the lane-journal `_STATE_MUTATING_OPS` gate gives — so adding an
# op never bumps the schema version.
OP_INTENT = "INTENT"                    # a run declares its goal (at spawn / first dispatch)
OP_STEP_CLAIMED = "STEP_CLAIMED"        # the agent SAYS it finished a unit of work (forgeable)
OP_STEP_VERIFIED = "STEP_VERIFIED"      # the kernel CONFIRMED a claimed step against ancestry
OP_SUSPEND = "SUSPEND"                  # a run voluntarily yields (pause; §4)
OP_RESUME_PROPOSED = "RESUME_PROPOSED"  # a successor minted a resume point + proposed continuation
OP_CORRUPT = "_CORRUPT"                 # replay hit an unparseable non-trailing line (sentinel)

# The ops `replay` folds into the LedgerState. `_CORRUPT` and any unknown op are
# recorded-but-not-folded (the lane-journal `_STATE_MUTATING_OPS` posture): a
# torn/foreign line must never silently mutate the reconstructed intent.
_FOLDED_OPS = frozenset(
    {OP_INTENT, OP_STEP_CLAIMED, OP_STEP_VERIFIED, OP_SUSPEND, OP_RESUME_PROPOSED}
)


def ledger_now_iso() -> str:
    """Second-resolution UTC stamp for ledger entries (the `lane_journal` idiom)."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Where it lives — the run-dir the spine already creates, keyed by run_id.
# --------------------------------------------------------------------------


def run_dir_for(run_id: str, *, cfg: "_config.SubstrateConfig | None" = None) -> Path:
    """The run-dir ``<runs>/<run_id>/`` for ``run_id`` under the active workspace.

    Rides the layout's run-dir tree (`paths.fanout_runs`, which is `.dos/runs`
    under the generic layout — the same tree the spine stamps `run.json` into).
    Keyed by the run-id token itself, NOT a UTC-timestamp dir name: the ledger is
    correlated-by-construction with the spine (`docs/107 §3.1`). Pure path
    arithmetic — never creates the dir (a read-only caller must be able to ASK for
    the path without a write; `append` is the only creator).
    """
    cfg = _config.ensure(cfg)
    return cfg.paths.fanout_runs / run_id


def ledger_path_for(run_id: str, *, cfg: "_config.SubstrateConfig | None" = None) -> Path:
    """The ``intent.jsonl`` path for ``run_id`` (next to its ``run.json``)."""
    return run_dir_for(run_id, cfg=cfg) / INTENT_JSONL_NAME


# --------------------------------------------------------------------------
# I/O — append (fsync, library-only) + read_all (torn-tail + schema gate).
# --------------------------------------------------------------------------


def append(run_id: str, entry: dict, *, path: Path | None = None,
           cfg: "_config.SubstrateConfig | None" = None) -> dict:
    """Append one entry to ``run_id``'s intent ledger and `fsync` it. Returns the stamped entry.

    Stamps `run_id` (the key — always THIS run's), `ts` (if absent), and the §6
    `schema` tag (if the builder didn't already), then writes one canonical-JSON
    line + newline, `flush` + `os.fsync` so the record is durable before the
    function returns (log-before-act, the WAL invariant). `O_APPEND` makes the
    write atomic w.r.t. any other appender at the OS level; one writer per `run_id`
    means there is no cross-run mutex to hold (unlike the shared WAL).

    The entry shape is the caller's decision payload (use the `*_entry` builders);
    this only fills the universal fields. `path` overrides the resolved run-dir
    location (tests / a driver writing elsewhere).
    """
    p = path or ledger_path_for(run_id, cfg=cfg)
    e = dict(entry)
    e["run_id"] = run_id  # the key is authoritative — always this run's
    e.setdefault("ts", ledger_now_iso())
    if _schema.SCHEMA_KEY not in e:
        e.update(_schema.tag(SCHEMA_FAMILY, INTENT_LEDGER_SCHEMA))
    line = json.dumps(e, sort_keys=True, default=str, ensure_ascii=False) + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return e


def read_all(run_id: str | None = None, *, path: Path | None = None,
             cfg: "_config.SubstrateConfig | None" = None,
             understands: int = INTENT_LEDGER_SCHEMA) -> list[dict]:
    """Return every ledger entry for ``run_id`` in append order, schema-gated.

    Two distrust postures layered (the §6 floor on top of the ARIES floor):

      * **Torn-tail tolerance** (the `lane_journal.read_all` contract): an
        unparseable TRAILING line (a crash mid-`append`) is skipped — a
        half-written record is "didn't happen", the safe WAL read. A non-trailing
        unparseable line is a real integrity breach, kept as an `_CORRUPT`
        sentinel so an audit/replay still flags it.
      * **Schema gate** (§6, the refuse-don't-guess floor): a parseable record
        whose `schema` tag is a NON-additively-newer version than `understands` is
        NOT returned as data — it is replaced by an `_CORRUPT`-style
        `_UNREADABLE` sentinel carrying the readability verdict, so `replay`/the
        fold treat it as un-foldable rather than best-effort-parsing a shape this
        kernel does not know. An UNTAGGED (legacy/pre-tag) record is treated
        permissively as readable (the family's implicit v1) — the tolerant-fold
        side of the `durable_schema.UNTAGGED` contract. A WRONG_FAMILY record (a
        foreign line in the file) is likewise kept as an `_UNREADABLE` sentinel.

    Pass `run_id` to resolve the run-dir path, or `path` to read a specific file
    (tests). `understands` is the reader's schema ceiling (defaults to this
    kernel's) — injectable so a test can simulate an OLD reader meeting a NEW
    record.
    """
    p = path or (ledger_path_for(run_id, cfg=cfg) if run_id else None)
    if p is None:
        raise ValueError("read_all needs a run_id or an explicit path")
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    out: list[dict] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            # Torn final line → "didn't happen"; a mid-file corrupt line → sentinel.
            if i == len(lines) - 1:
                break
            out.append({"op": OP_CORRUPT, "_raw": s, "_line": i})
            continue
        if not isinstance(obj, dict):
            continue
        # The §6 schema gate. UNTAGGED/READABLE proceed; UNREADABLE_NEWER and
        # WRONG_FAMILY become an un-foldable sentinel that records WHY (so a
        # surfaced resume verdict can say "v3 record, kernel reads ≤ v1 — migrate").
        v = _schema.classify(obj, family=SCHEMA_FAMILY, understands=understands)
        if v.readability in (_schema.Readability.READABLE, _schema.Readability.UNTAGGED):
            out.append(obj)
        else:
            out.append({
                "op": OP_CORRUPT,
                "_unreadable": v.to_dict(),
                "_raw": s,
                "_line": i,
            })
    return out


# --------------------------------------------------------------------------
# The replay fold → LedgerState (pure; the resume verdict's evidence shape).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SuspendCheckpoint:
    """The CONVERSATION rewind anchor a SUSPEND record may carry (docs/164 F1.5).

    Defined HERE — beside the SUSPEND record it serializes onto — because it is a
    durable-record shape, the sibling of the git-axis `suspend_resume_sha`. The SAME
    SUSPEND record carries both: `resume_sha` (the git re-entry point, read by
    `resume.resume_plan`) and this `(turn_index, transcript_digest)` (the
    conversation re-entry checkpoint, read by `rewind.rewind_plan`). `rewind` imports
    this type from here — the one-way layering arrow (`rewind` → `intent_ledger`),
    never the reverse.

    `transcript_digest` is the kernel's hash of the transcript-up-to-`turn_index` at
    suspend time — the NON-FORGEABLE anchor (its byte-author is the kernel's hash, not
    the judged agent). The conversation rewind is valid ONLY if the live turn at
    `turn_index` still digests to it (`rewind` enforces this — else UNANCHORED).

    `present=False` is the honest zero: a SUSPEND from a kernel too old to stamp a
    checkpoint (the additive-evolution case) folds back to an absent checkpoint, never
    a guessed one. `from_record` builds it from a folded SUSPEND dict, tolerating the
    missing fields.
    """

    turn_index: int = -1
    transcript_digest: str = ""
    present: bool = False

    @classmethod
    def absent(cls) -> "SuspendCheckpoint":
        """The honest zero — no minted checkpoint (an older kernel's SUSPEND)."""
        return cls(turn_index=-1, transcript_digest="", present=False)

    @classmethod
    def from_record(cls, entry: "Mapping | dict") -> "SuspendCheckpoint":
        """Build from a SUSPEND record's additive fields, tolerating their absence.

        A SUSPEND with no `transcript_digest` (an older kernel, or a git-only suspend)
        folds to `absent()` — the skip-unknown tolerant-read rule. Present iff a
        non-empty `transcript_digest` was recorded (the digest is the load-bearing
        field; a `checkpoint_turn` with no digest is not a usable anchor).
        """
        digest = str(entry.get("transcript_digest") or "")
        if not digest:
            return cls.absent()
        turn_raw = entry.get("checkpoint_turn")
        try:
            turn = int(turn_raw)
        except (TypeError, ValueError):
            turn = -1
        return cls(turn_index=turn, transcript_digest=digest, present=True)


@dataclass(frozen=True)
class LedgerState:
    """The reconstructed intent of one run — `replay`'s output, `resume_plan`'s input.

    The intent-ledger analogue of `lane_journal.replay`'s live-lease list: a pure
    fold of the entry sequence into "what did this run DECLARE, and which steps did
    the kernel VERIFY." Deliberately carries CLAIMED and VERIFIED separately — the
    whole epistemic point (§3.2) is that they are not the same, and the resume fold
    treats only VERIFIED as done.

      run_id            — the run this state describes (the ledger's key).
      goal              — the declared free-form goal string (the latest INTENT's).
      plan / phase      — the declared (plan, phase) if the run named one (else "").
      start_sha         — the run's declared start commit (the resume floor anchor).
      declared_steps    — the ordered step ids the INTENT declared (may be empty: a
                          run with a free-form goal and no enumerated steps).
      step_regions      — {step_id: (glob, …)} — each step's declared FILE REGION
                          (repo-relative globs). OPTIONAL: a step with no region falls
                          back to the non-empty-footprint check. When present, the
                          resume re-adjudication (`resume_evidence`) requires the
                          step's commit footprint to INTERSECT this region, closing the
                          §5 hole where a forged record points at a real-but-unrelated
                          commit (a commit outside the step's region isn't its work).
      claimed           — {step_id: claimed_sha} — the agent's self-reports
                          (DISTRUSTED; a pointer to a commit to check, not proof).
      verified          — {step_id: VerifiedStep} — steps the kernel CONFIRMED
                          against ancestry on the non-forgeable rung (TRUSTED).
      suspended         — True iff the run's last lifecycle record is a SUSPEND
                          (it parked voluntarily; §4) and no later INTENT re-opened it.
      suspend_resume_sha— the resume-point SHA the SUSPEND recorded (a cheaper,
                          still-re-verified hint; "" if not suspended / not given).
      suspend_checkpoint— the CONVERSATION rewind anchor the SUSPEND recorded (docs/164
                          F1.5): a `(turn_index, transcript_digest)` the kernel stamped,
                          read by `rewind.rewind_plan`. The sibling of `suspend_resume_sha`
                          on the SAME SUSPEND record (git axis reads the SHA, conversation
                          axis reads this). `absent()` if not suspended / an older kernel's
                          SUSPEND that stamped no checkpoint (the additive-evolution zero).
      resume_proposed   — predecessor run_ids a RESUME_PROPOSED was already minted
                          for (idempotence; §5 req 4): a second resume sees these and
                          does not double-propose.
      corrupt_lines     — count of `_CORRUPT`/`_UNREADABLE` sentinels seen (a
                          non-zero count is an integrity signal the resume verdict
                          degrades on — UNRESUMABLE when the fold isn't sound).
      unreadable_newer  — True iff ≥1 sentinel was an UNREADABLE_NEWER schema (a
                          record this kernel is too OLD to read): the §6 floor —
                          resume must refuse, not guess.
    """

    run_id: str
    goal: str = ""
    plan: str = ""
    phase: str = ""
    start_sha: str = ""
    declared_steps: tuple[str, ...] = ()
    step_regions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    claimed: dict[str, str] = field(default_factory=dict)
    verified: dict[str, "VerifiedStep"] = field(default_factory=dict)
    suspended: bool = False
    suspend_resume_sha: str = ""
    suspend_checkpoint: SuspendCheckpoint = field(default_factory=SuspendCheckpoint.absent)
    resume_proposed: tuple[str, ...] = ()
    corrupt_lines: int = 0
    unreadable_newer: bool = False

    @property
    def has_intent(self) -> bool:
        """True iff at least one INTENT record was folded (a goal/plan/steps exist).

        UNRESUMABLE's floor: with no INTENT there is no declared work to compute a
        residual from — `resume_plan` returns UNRESUMABLE rather than guessing one.
        """
        return bool(self.goal or self.plan or self.declared_steps)


@dataclass(frozen=True)
class VerifiedStep:
    """A step the kernel confirmed against ancestry (`STEP_VERIFIED`'s payload).

    `sha` is the ancestry-backed commit; `via` names the verify RUNG that backed it
    (`file-path`/`registry`/… — NEVER the forgeable subject-grep, §5 req 2);
    `rungs`/`verdicts` echo the backing detail for forensics. This is the minted
    belief — the only thing resume reads as "done."
    """

    step_id: str
    sha: str
    via: str = ""
    verdicts: tuple[str, ...] = ()


def replay(entries: Iterable[dict]) -> LedgerState:
    """Fold the ledger sequence into a `LedgerState`. PURE — entries in, state out.

    The intent-ledger redo fold (the third ARIES phase's input). Folding rules
    (later records win for scalar fields; sets accumulate):

      * INTENT          → set goal/plan/phase/start_sha/declared_steps; a later
                          INTENT (a re-declared/re-opened run) overrides and clears
                          `suspended` (the run is live again).
      * STEP_CLAIMED    → record claimed[step_id] = claimed_sha (the distrusted
                          self-report — a pointer to a commit to check).
      * STEP_VERIFIED   → record verified[step_id] = VerifiedStep (the minted
                          belief; the ONLY "done" signal).
      * SUSPEND         → mark suspended + carry its recorded resume-point SHA.
      * RESUME_PROPOSED → record the predecessor run_id (idempotence).
      * _CORRUPT / _UNREADABLE / unknown → counted, never folded into intent (a
                          torn/foreign/too-new line must not mutate the
                          reconstructed goal — the lane-journal skip-unknown rule).

    Returns a frozen `LedgerState`; `replay([])` is an empty state with
    `has_intent == False` (the UNRESUMABLE floor for a run that declared nothing).
    """
    run_id = ""
    goal = ""
    plan = ""
    phase = ""
    start_sha = ""
    declared_steps: tuple[str, ...] = ()
    step_regions: dict[str, tuple[str, ...]] = {}
    claimed: dict[str, str] = {}
    verified: dict[str, VerifiedStep] = {}
    suspended = False
    suspend_resume_sha = ""
    suspend_checkpoint = SuspendCheckpoint.absent()
    resume_proposed: list[str] = []
    corrupt = 0
    unreadable_newer = False

    for e in entries:
        op = str(e.get("op") or "")
        rid = str(e.get("run_id") or "")
        if rid:
            run_id = rid
        if op not in _FOLDED_OPS:
            # _CORRUPT / _UNREADABLE / unknown — recorded, not folded.
            if op == OP_CORRUPT:
                corrupt += 1
                un = e.get("_unreadable")
                if isinstance(un, dict) and un.get("readability") == "UNREADABLE_NEWER":
                    unreadable_newer = True
            continue
        if op == OP_INTENT:
            goal = str(e.get("goal") or goal)
            plan = str(e.get("plan") or plan)
            phase = str(e.get("phase") or phase)
            start_sha = str(e.get("start_sha") or start_sha)
            steps = e.get("declared_steps")
            if isinstance(steps, (list, tuple)):
                declared_steps = tuple(str(s) for s in steps)
            regions = e.get("step_regions")
            if isinstance(regions, dict):
                step_regions = {
                    str(k): tuple(str(g) for g in v)
                    for k, v in regions.items()
                    if isinstance(v, (list, tuple))
                }
            # A fresh INTENT re-opens a parked run (it is live again).
            suspended = False
            suspend_resume_sha = ""
            suspend_checkpoint = SuspendCheckpoint.absent()
        elif op == OP_STEP_CLAIMED:
            sid = str(e.get("step_id") or "")
            if sid:
                claimed[sid] = str(e.get("sha") or "")
        elif op == OP_STEP_VERIFIED:
            sid = str(e.get("step_id") or "")
            if sid:
                vds = e.get("verdicts")
                verified[sid] = VerifiedStep(
                    step_id=sid,
                    sha=str(e.get("sha") or ""),
                    via=str(e.get("via") or ""),
                    verdicts=tuple(str(v) for v in vds) if isinstance(vds, (list, tuple)) else (),
                )
        elif op == OP_SUSPEND:
            suspended = True
            suspend_resume_sha = str(e.get("resume_sha") or e.get("sha") or "")
            # The conversation-rewind anchor (docs/164 F1.5) — additive, tolerant of
            # absence (an older kernel's SUSPEND folds to an absent checkpoint).
            suspend_checkpoint = SuspendCheckpoint.from_record(e)
        elif op == OP_RESUME_PROPOSED:
            pred = str(e.get("predecessor_run_id") or e.get("predecessor") or "")
            if pred and pred not in resume_proposed:
                resume_proposed.append(pred)

    return LedgerState(
        run_id=run_id,
        goal=goal,
        plan=plan,
        phase=phase,
        start_sha=start_sha,
        declared_steps=declared_steps,
        step_regions=dict(step_regions),
        claimed=dict(claimed),
        verified=dict(verified),
        suspended=suspended,
        suspend_resume_sha=suspend_resume_sha,
        suspend_checkpoint=suspend_checkpoint,
        resume_proposed=tuple(resume_proposed),
        corrupt_lines=corrupt,
        unreadable_newer=unreadable_newer,
    )


# --------------------------------------------------------------------------
# Entry builders — the writer's vocabulary, defined HERE (one home), pure.
# Each carries the §6 schema tag so even a record written directly (not via
# `append`) is self-declaring.
# --------------------------------------------------------------------------


def intent_entry(
    *,
    goal: str = "",
    plan: str = "",
    phase: str = "",
    start_sha: str = "",
    declared_steps: Iterable[str] | None = None,
    step_regions: "dict[str, Iterable[str]] | None" = None,
    env: "Mapping | None" = None,
) -> dict:
    """Build an INTENT entry — a run declaring its goal (at spawn / first dispatch).

    `goal` is a free-form intent string; `plan`/`phase` the structured target if one
    exists; `start_sha` the run's start commit (the resume floor anchor); `declared_steps`
    the ordered step ids the run means to complete (may be omitted — a free-form goal).
    `step_regions` (OPTIONAL) maps a step id → its file region (repo-relative globs): at
    resume, a step's verifying commit footprint must INTERSECT this region (§5, the
    real-but-unrelated-commit defense). A step with no region falls back to the
    non-empty-footprint check. Believed AS A CLAIM at resume (§3.2): the residual is
    computed from it, but every "done" is re-verified.

    `env` (OPTIONAL) is the run's environment print — ``cfg.env.to_dict()`` (an
    `env_print.EnvPrint`), recorded at birth so the fossil says *under what* the run
    declared its intent (``docs/115`` primitive 1: kernel version + SHA + Python +
    OS + declared tools). Purely ADDITIVE — an INTENT with no `env` is a run from a
    kernel that did not stamp prints, read back unchanged (the additive-evolution
    contract: a new optional field never bumps `INTENT_LEDGER_SCHEMA`). The kernel
    RECORDS it; it does not yet adjudicate on it (a later phase reads env-divergence
    as a resume signal). The print is data, not a decision input — the docs/76 line.
    """
    e = {
        **_schema.tag(SCHEMA_FAMILY, INTENT_LEDGER_SCHEMA),
        "op": OP_INTENT,
        "goal": goal,
        "plan": plan,
        "phase": phase,
        "start_sha": start_sha,
    }
    if declared_steps is not None:
        e["declared_steps"] = [str(s) for s in declared_steps]
    if step_regions is not None:
        e["step_regions"] = {str(k): [str(g) for g in v] for k, v in step_regions.items()}
    if env is not None:
        e["env"] = dict(env)
    return e


def step_claimed_entry(step_id: str, sha: str) -> dict:
    """Build a STEP_CLAIMED entry — the agent SAYS it finished a step (forgeable).

    `sha` is the commit the agent CLAIMS landed the step. Never believed on its own
    (§3.2): a pointer to a commit to check, not proof. The `STEP_VERIFIED` mint is
    what turns a claim into a belief.
    """
    return {
        **_schema.tag(SCHEMA_FAMILY, INTENT_LEDGER_SCHEMA),
        "op": OP_STEP_CLAIMED,
        "step_id": str(step_id),
        "sha": str(sha or ""),
    }


def step_verified_entry(step_id: str, sha: str, *, via: str = "",
                        verdicts: Iterable[str] | None = None) -> dict:
    """Build a STEP_VERIFIED entry — the kernel CONFIRMED a claimed step (§5).

    Written ONLY by the CLI-boundary mint (`dos.resume.verify_step` / the dispatch
    loop) after re-checking the claimed SHA against ancestry on the NON-FORGEABLE
    rung (§5 req 2: `via` is `file-path`/`registry`, never the forgeable
    subject-grep). The minted belief — the only "done" resume reads.
    """
    return {
        **_schema.tag(SCHEMA_FAMILY, INTENT_LEDGER_SCHEMA),
        "op": OP_STEP_VERIFIED,
        "step_id": str(step_id),
        "sha": str(sha or ""),
        "via": str(via or ""),
        "verdicts": [str(v) for v in verdicts] if verdicts is not None else [],
    }


def suspend_entry(*, reason: str = "", resume_sha: str = "",
                  residual: Iterable[str] | None = None,
                  checkpoint: "SuspendCheckpoint | None" = None) -> dict:
    """Build a SUSPEND entry — a run voluntarily yields (pause; §4).

    `resume_sha` is the recorded resume point at suspend time (a cheaper hint than a
    full re-derivation — but still re-verified at resume, since a suspend an hour ago
    may be stale). `residual` is the remaining step ids at suspend time (forensic).
    Believed as a recorded DECISION (not a progress claim) — but the resume still
    re-checks ancestry (§4).

    `checkpoint` (OPTIONAL — docs/164 F1.5) is the CONVERSATION rewind anchor: a
    `(turn_index, transcript_digest)` the kernel stamped at suspend time, the
    sibling of the git-axis `resume_sha`. The SAME SUSPEND record carries both —
    the git-rewind axis (`resume.resume_plan`) reads `resume_sha`, the
    conversation-rewind axis (`rewind.rewind_plan`) reads these two fields. Written
    only when present, as two additive fields `"checkpoint_turn"` + `"transcript_digest"`.
    PURELY ADDITIVE: a SUSPEND from an older kernel that wrote no checkpoint reads
    back unchanged (the additive-evolution contract above — a new optional field
    never bumps `INTENT_LEDGER_SCHEMA`), and a kernel too OLD to know the fields
    simply ignores them (the skip-unknown tolerant-read rule). The digest is the
    NON-FORGEABLE rewind anchor: the kernel rewinds to a turn IT stamped here, never
    to a turn the agent claims (the §6 conversation-axis litmus).
    """
    e = {
        **_schema.tag(SCHEMA_FAMILY, INTENT_LEDGER_SCHEMA),
        "op": OP_SUSPEND,
        "reason": str(reason or ""),
        "resume_sha": str(resume_sha or ""),
    }
    if residual is not None:
        e["residual"] = [str(s) for s in residual]
    if checkpoint is not None:
        # Two additive fields, written only when a checkpoint was minted. The
        # conversation axis reads these; the git axis reads `resume_sha` above.
        e["checkpoint_turn"] = int(checkpoint.turn_index)
        e["transcript_digest"] = str(checkpoint.transcript_digest or "")
    return e


def resume_proposed_entry(*, predecessor_run_id: str, resume_sha: str = "",
                          residual: Iterable[str] | None = None) -> dict:
    """Build a RESUME_PROPOSED entry — a successor minted a resume point + proposed continuation (§5).

    Recorded on the SUCCESSOR's ledger for forensics + idempotence (§5 req 4): a
    second resume attempt sees this predecessor already proposed-for and does not
    double-propose. `predecessor_run_id` is the dead/parked run being resumed.
    """
    e = {
        **_schema.tag(SCHEMA_FAMILY, INTENT_LEDGER_SCHEMA),
        "op": OP_RESUME_PROPOSED,
        "predecessor_run_id": str(predecessor_run_id),
        "resume_sha": str(resume_sha or ""),
    }
    if residual is not None:
        e["residual"] = [str(s) for s in residual]
    return e
