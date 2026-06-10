"""rewind-evidence — the boundary I/O for the conversation-rewind axis (docs/164 F1.5).

`rewind.rewind_plan` is a PURE verdict over `(TurnRef…, SuspendCheckpoint, FireVerdict)`.
SOMETHING has to gather those off disk: read the run's transcript turns and hash each
(`digest_turn`), read the SUSPEND record's minted checkpoint off the intent ledger, and
build the `FireVerdict` from whichever ground-truth stop verdict fired. That is this
module — the conversation axis's `resume_evidence` sibling: boundary I/O feeding the pure
core, never inside the verdict.

Three boundary jobs, mirroring `resume_evidence`'s shape:

  * **`gather_turns(...)`** — read the run's transcript off disk (the host-owned
    `transcript.jsonl` beside `intent.jsonl`), hashing each turn's bytes into a
    `TurnRef(index, digest)`. The DIGEST is computed HERE (the byte-author of the
    anchor's identity is the kernel's hash, not the judged agent — the
    `evidence.believe_under_floor` framing that makes the checkpoint non-forgeable).
    A missing/unreadable transcript degrades to NO turns (→ the verdict's UNANCHORED
    floor: no live turn can match the checkpoint, so the kernel rewinds to nothing).
  * **`read_checkpoint(...)`** — pull the minted `SuspendCheckpoint` off the run's
    folded `LedgerState` (`intent_ledger.replay`). The checkpoint was stamped at
    `OP_SUSPEND`; `state.suspend_checkpoint` is already the read-side object (the fold
    decoded it). `absent()` when the run never suspended or an older kernel stamped no
    checkpoint — the honest zero that yields UNANCHORED.
  * **`fire_from(...)`** — wrap an already-computed `Resume`/`Convergence` verdict as a
    `FireVerdict`, NEVER re-deriving it (the `resume`/`completion` reuse-not-reimplement
    rule). The boundary computes the ground-truth stop signal upstream; this only adapts
    its type.

The served root/config is passed EXPLICITLY (never the process-global active), so a
long-lived caller fielding several workspaces gets the right tree (the `resume_evidence`
discipline). Every failure mode degrades to the SAFE direction: a transcript we cannot
read is treated as NO turns, so the verdict refuses to rewind (UNANCHORED) rather than
rewinding to a turn it cannot confirm the kernel stamped — fail-closed, the same posture
`resume_evidence` takes for an unresolvable SHA.

The transcript surface is a CONVENTION, not a kernel-owned format: the host writes its
turns as JSONL beside the ledger (one record per turn). The kernel reads bytes and hashes
them; it neither defines nor depends on the turn's internal shape ("the host owns the
transcript", docs/164 P1.5). A host with its turns elsewhere passes them in directly via
`turns_from_records` — the file reader is the convenience default, not the contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from dos import config as _config
from dos import intent_ledger as _il
from dos.completion import Convergence
from dos.intent_ledger import LedgerState, SuspendCheckpoint
from dos.resume import Resume
from dos.rewind import FireVerdict, TurnRef, digest_turn

# The host-owned transcript surface — JSONL, one record per turn, beside intent.jsonl.
# A CONVENTION (not a kernel format): the kernel hashes each record's bytes, never reads
# its internal fields. Named here so the reader and a host writer agree on one path.
TRANSCRIPT_JSONL_NAME = "transcript.jsonl"


def transcript_path_for(
    run_id: str, *, cfg: "_config.SubstrateConfig | None" = None
) -> Path:
    """The ``transcript.jsonl`` path for ``run_id`` — beside its ``intent.jsonl``.

    The conversation-axis sibling of `intent_ledger.ledger_path_for`: the host writes
    its per-turn records here; `gather_turns` hashes them into `TurnRef`s. The kernel
    owns neither the file's existence nor its record shape — a run with no transcript
    simply yields no turns (→ UNANCHORED, the safe floor).
    """
    return _il.run_dir_for(run_id, cfg=cfg) / TRANSCRIPT_JSONL_NAME


def turns_from_records(records: Iterable["bytes | str | dict"]) -> tuple[TurnRef, ...]:
    """Hash an in-memory sequence of turn records into ``TurnRef(index, digest)``.

    The pure-ish core of the reader (no I/O — the caller already has the records): each
    record's bytes are digested by `digest_turn` and paired with its position. A `dict`
    record is canonicalised with sorted keys before hashing so the digest is stable
    across key-order — the kernel's hash is the anchor's identity, so it must be
    deterministic for the same logical turn.

    The byte-author discipline (the reason the anchor is non-forgeable): the DIGEST is
    THIS function's hash of the turn, NOT a value the judged agent supplied. An agent
    cannot forge the identity of its own turn's digest, exactly as `arg_provenance`'s
    mint detector turns on the agent not authoring the identity of its own repeated
    output.
    """
    out: list[TurnRef] = []
    for i, rec in enumerate(records):
        if isinstance(rec, dict):
            # Canonical bytes: sorted keys, no whitespace drift → a stable digest for the
            # same logical turn regardless of how the host serialised it.
            raw = json.dumps(rec, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, default=str)
        elif isinstance(rec, bytes):
            raw = rec
        else:
            raw = str(rec)
        out.append(TurnRef(index=i, digest=digest_turn(raw)))
    return tuple(out)


def gather_turns(
    run_id: str,
    *,
    cfg: "_config.SubstrateConfig | None" = None,
    path: Path | None = None,
) -> tuple[TurnRef, ...]:
    """Read the run's transcript off disk → ``TurnRef``s, hashing each turn. Fail-closed.

    The conversation-axis evidence-gather (the `resume_evidence.gather_ancestry` shape):
    the file read happens HERE; the already-hashed turns are handed to the pure verdict.
    Reads `transcript.jsonl` beside the ledger (or an explicit `path`), one record per
    line, and digests each. Every failure — no file, unreadable, a torn line — degrades
    to the SAFE direction: that turn (or the whole transcript) yields no `TurnRef`, so a
    checkpoint can find no matching live turn and the verdict refuses (UNANCHORED) rather
    than rewinding to a turn it cannot confirm. A torn TAIL line is skipped (the
    `intent_ledger` torn-tail tolerance), not fatal.
    """
    cfg = _config.ensure(cfg)
    p = path or transcript_path_for(run_id, cfg=cfg)
    try:
        text = Path(p).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ()  # no readable transcript → no turns → UNANCHORED (fail-closed)
    records: list[str] = []
    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            continue
        # Hash the LINE bytes as the turn (the host owns the record shape; the kernel
        # hashes what the host wrote). A line that happens to be JSON is hashed as its
        # own bytes here — `turns_from_records` canonicalises only when handed a dict.
        records.append(ln)
    return turns_from_records(records)


def read_checkpoint(state: LedgerState) -> SuspendCheckpoint:
    """The minted conversation rewind anchor off the folded ledger (or ``absent()``).

    `intent_ledger.replay` already decoded the SUSPEND record's `(checkpoint_turn,
    transcript_digest)` into `state.suspend_checkpoint`. This is the trivial accessor
    that names the read for the rewind boundary — the sibling of reading
    `state.suspend_resume_sha` on the git axis. A run that never suspended, or an older
    kernel's SUSPEND that stamped no checkpoint, carries `SuspendCheckpoint.absent()` —
    the honest zero `rewind_plan` maps to UNANCHORED.
    """
    return state.suspend_checkpoint


def fire_from(
    *,
    resume_verdict: Optional[Resume] = None,
    convergence_verdict: Optional[Convergence] = None,
) -> FireVerdict:
    """Adapt an already-computed ground-truth stop verdict into a ``FireVerdict``.

    The boundary computes the stop signal upstream (`resume.resume_plan` → `Resume`;
    `completion.convergence` → `Convergence`) and this wraps it — NEVER re-deriving it
    inside the rewind axis (the reuse-not-reimplement rule). Pass whichever fired; both
    None is a non-firing verdict (→ NO_REWIND, the loop continues).
    """
    return FireVerdict(
        resume_verdict=resume_verdict,
        convergence_verdict=convergence_verdict,
    )
