"""dos.drivers.state_diff — the canonical-state-diff read-back witness (docs/181).

The second concept lifted from the 2026 result-state-witness SOTA (docs/180):
**Agent-Diff** (arXiv 2602.11224) defines task success as "whether the expected
change in environment STATE was achieved", computed as a canonical state diff
(inserted / deleted / updated entities) over containerized replicas — explicitly
rejecting "fuzzy trace or parameter matching". This driver is DOS's domain-free,
floor-disciplined version: it snapshots a state surface BEFORE and AFTER the agent's
turn, computes the delta, and witnesses whether a claimed effect-key is PRESENT in
that delta — feeding `effect_witness.witness_effect` a non-forgeable read-back.

Why this is a NON-FORGEABLE witness (the VAGEN "different surface" principle)
=============================================================================

The third SOTA concept (VAGEN, arXiv 2602.00575) is that the verifier must take its
OWN read actions — read the world from a surface the agent did not author. This
driver reads the **state surface itself** (a snapshot of the live store), NOT the
agent's narration of what it wrote and NOT the agent's own tool-call response bytes.
The snapshot is authored by the store, not the agent: the agent cannot forge "row 42
now exists in the orders table" without the row actually existing, because the
snapshot is a fresh read of the store. So this source is tagged `OS_RECORDED` when
the snapshot comes from a local store the kernel reads directly (a sqlite file, a
JSON state dump the OS wrote), and a host that reads a remote third-party store
(a SaaS API, a cloud DB) would register a `THIRD_PARTY`-tagged sibling.

The honest boundary: a snapshot the AGENT produced is forgeable
===============================================================

If the "before"/"after" snapshots are bytes the agent itself emitted (it ran a query
and pasted the result), then actor==witness and the read-back is `AGENT_AUTHORED` —
the forgeable floor, structurally incapable of CONFIRMED under
`effect_witness`/`believe_under_floor`. This driver is only a sound witness when the
KERNEL reads the snapshot (it opens the sqlite file / re-fetches the dump), which is
why the snapshot reader is a parameter (`read_state`) the HOST supplies as an
independent reader, and why the default file reader is the safe, kernel-authored path.

The delta grammar (canonical, domain-free)
==========================================

A "state" is a mapping of `entity_key -> entity_value` (rows by id, files by path,
records by key). The canonical diff over two snapshots is:

  * inserted = keys in AFTER not in BEFORE
  * deleted  = keys in BEFORE not in AFTER
  * updated  = keys in both whose value differs

A claimed effect-key is PRESENT iff it appears in inserted ∪ updated (the agent
claimed it *made* a change to that entity). ABSENT iff it does not. This is the
domain-free "claim ⊆ witnessed-delta" presence check `effect_witness` wants — not a
gold-state correctness check (which a live runtime cannot have; docs/181 §"why
presence not correctness").

Shape & layering
================

A driver — it has the I/O surface the kernel forbids (reading a state store). It
implements the `evidence.EvidenceSource` Protocol so it drops straight into
`gather_evidence` and the belief fold, and a thin `witness_effect_via_state_diff`
convenience that snapshots → diffs → joins the claim. It imports the kernel; the
kernel never imports it (the `drivers/__init__` rule). Advisory: it reports a
read-back; it never mutates state or refuses a lease.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Mapping

# Imports the kernel — never the other way round (the driver rule).
from dos.evidence import Accountability, EvidenceFacts
from dos.effect_witness import EffectClaim, EffectWitnessVerdict, witness_effect


# A state snapshot: entity-key -> an opaque, comparable value (str/number/JSON-able).
State = Mapping[str, object]


@dataclass(frozen=True)
class StateDelta:
    """The canonical diff between two snapshots — inserted / deleted / updated keys."""

    inserted: frozenset[str]
    deleted: frozenset[str]
    updated: frozenset[str]

    @property
    def changed(self) -> frozenset[str]:
        """Keys the agent could have CLAIMED it made: inserted ∪ updated. A delete is
        not a 'made this entity' claim in the presence sense, so it is reported but not
        counted as 'present' (a host that wants delete-claims checks `deleted`)."""
        return self.inserted | self.updated

    def to_dict(self) -> dict:
        return {
            "inserted": sorted(self.inserted),
            "deleted": sorted(self.deleted),
            "updated": sorted(self.updated),
        }


def diff_state(before: State, after: State) -> StateDelta:
    """Canonical, domain-free diff over two snapshots. PURE — no I/O.

    Values are compared by equality; a host whose values are unstable (timestamps,
    auto-ids) should normalize them in its `read_state` reader before snapshotting, so
    the diff reflects semantic change, not churn.
    """
    bkeys = set(before.keys())
    akeys = set(after.keys())
    inserted = akeys - bkeys
    deleted = bkeys - akeys
    updated = {k for k in (akeys & bkeys) if before[k] != after[k]}
    return StateDelta(
        inserted=frozenset(inserted),
        deleted=frozenset(deleted),
        updated=frozenset(updated),
    )


class StateDiffEvidenceSource:
    """An `evidence.EvidenceSource`: witness whether a claimed effect-key is in a delta.

    Constructed with a precomputed `StateDelta` (snapshot/diff happened at the
    boundary) and an `accountability` rung (`OS_RECORDED` when the KERNEL read the
    snapshots; a remote store driver passes `THIRD_PARTY`; never `AGENT_AUTHORED` for a
    sound witness). `gather(subject, config)` reads `subject` as the effect-key and
    answers PRESENT (ATTESTED) / ABSENT (REFUTED) against the delta — never NO_SIGNAL,
    because a computed delta IS a reached read (the absence of a key is a positive
    'not there', not 'could not tell'). The fail-safe degrade lives one level up in
    the snapshot reader (`witness_effect_via_state_diff`): if the snapshots could not
    be read, no source is built and the verdict is UNWITNESSED.
    """

    name = "state_diff"

    def __init__(self, delta: StateDelta, *, accountability: Accountability = Accountability.OS_RECORDED) -> None:
        if accountability.is_agent_authored:
            # Guard the soundness contract loudly: a state-diff witness over
            # agent-authored snapshots is NOT a witness (actor==witness). A host that
            # truly has only agent-authored snapshots should not use this source.
            raise ValueError(
                "state_diff witness requires a non-forgeable snapshot rung "
                "(OS_RECORDED/THIRD_PARTY); an agent-authored snapshot is not a witness"
            )
        self._delta = delta
        self.accountability = accountability

    def gather(self, subject: str, config: object) -> EvidenceFacts:
        key = (subject or "").strip()
        if not key:
            return EvidenceFacts.no_signal(
                self.name, self.accountability, subject,
                detail="no effect-key given — nothing to look for in the delta",
            )
        if key in self._delta.changed:
            where = "inserted" if key in self._delta.inserted else "updated"
            return EvidenceFacts.attest(
                self.name, self.accountability, key,
                detail=f"effect-key {key!r} is in the state delta ({where})",
            )
        return EvidenceFacts.refute(
            self.name, self.accountability, key,
            detail=(
                f"effect-key {key!r} is NOT in the state delta "
                f"(inserted={len(self._delta.inserted)} updated={len(self._delta.updated)}) "
                f"— the claimed change is absent from the world"
            ),
        )


def witness_effect_via_state_diff(
    claim: EffectClaim,
    before: State,
    after: State,
    *,
    accountability: Accountability = Accountability.OS_RECORDED,
) -> EffectWitnessVerdict:
    """Snapshot-diff → join: the one-call convenience for a host with two snapshots.

    Computes the canonical delta, builds the state-diff witness over it, and joins the
    claim through `effect_witness.witness_effect`. The snapshots MUST have been read by
    the kernel/host (a non-forgeable reader), not pasted by the agent — that is the
    `accountability` rung's contract. Returns the four-valued verdict.
    """
    delta = diff_state(before, after)
    source = StateDiffEvidenceSource(delta, accountability=accountability)
    facts = source.gather(claim.probe_subject(), None)
    return witness_effect(claim, [facts])


# ---------------------------------------------------------------------------
# A safe, kernel-authored snapshot reader: a JSON state-dump file.
# `read_state_json(path)` reads a {key: value} JSON object the STORE wrote. Because
# the kernel opens the file (the agent did not hand us the bytes), the resulting
# snapshot is OS_RECORDED. A host with a sqlite store / a SaaS API writes its own
# reader and tags the rung accordingly.
# ---------------------------------------------------------------------------


def read_state_json(path: str) -> State:
    """Read a `{entity_key: value}` JSON object as a state snapshot. Raises on a bad
    read (the caller decides the fail-safe — a missing snapshot → UNWITNESSED, never a
    fabricated empty delta that would falsely REFUTE every claim)."""
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"state snapshot at {path!r} is a {type(obj).__name__}, not an object")
    return obj


# ---------------------------------------------------------------------------
# CLI — `python -m dos.drivers.state_diff KEY --before B.json --after A.json`
# witnesses whether the claimed effect-key is present in the file-snapshot delta.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dos.drivers.state_diff",
        description=__doc__.splitlines()[0],
    )
    ap.add_argument("effect_key", help="the claimed effect-key to look for in the state delta")
    ap.add_argument("--before", required=True, help="path to the BEFORE state snapshot (JSON object the STORE wrote)")
    ap.add_argument("--after", required=True, help="path to the AFTER state snapshot")
    ap.add_argument("--narrated", default="", help="the agent's original claim phrasing (for the operator surface)")
    ap.add_argument("--third-party", action="store_true",
                    help="tag the snapshot rung THIRD_PARTY (a remote store) instead of OS_RECORDED")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    args = ap.parse_args(argv)

    rung = Accountability.THIRD_PARTY if args.third_party else Accountability.OS_RECORDED
    claim = EffectClaim(key=args.effect_key, narrated=args.narrated)

    # Fail-safe at the boundary: an unreadable snapshot → UNWITNESSED (no claim of
    # absence), never a fabricated empty delta.
    try:
        before = read_state_json(args.before)
        after = read_state_json(args.after)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        from dos.effect_witness import witness_effect  # local import keeps module top clean
        v = witness_effect(claim, [])  # no read-backs → UNWITNESSED
        v_dict = v.to_dict()
        v_dict["reason"] = f"UNWITNESSED — could not read a state snapshot ({e}); cannot tell"
        if args.json:
            print(json.dumps(v_dict, indent=2))
        else:
            print(f"VERDICT   UNWITNESSED\nWHY       could not read a snapshot: {e}")
        return 3

    delta = diff_state(before, after)
    v = witness_effect_via_state_diff(claim, before, after, accountability=rung)

    if args.json:
        out = v.to_dict()
        out["delta"] = delta.to_dict()
        print(json.dumps(out, indent=2))
    else:
        print(f"EFFECT    {args.effect_key}")
        print(f"DELTA     +{len(delta.inserted)} ~{len(delta.updated)} -{len(delta.deleted)}")
        print(f"VERDICT   {v.verdict.value}   (believe={v.believe} refuted={v.refuted})")
        print(f"WITNESS   {v.witness or '(none)'} ({v.accountability.value if v.accountability else '-'})")
        print(f"WHY       {v.reason}")

    if v.is_refuted:
        return 1
    if v.is_confirmed:
        return 0
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
