"""verdict-rollup — fold many status-bearing items into ONE surface-agnostic
summary every render surface reproduces identically (C9, the cross-surface-drift fix).

A single per-producer verdict reaches the operator on several surfaces — console,
Slack, an LLM summary, a JSON bundle — and each surface independently decides
whether to show it and how. They drift: a probe a run *requested* but that never
produced output shows on one surface and is silent on another (the
"requested-but-absent → false-pass" class the reference benchmark logged before it
built a per-feature rollup). The fix is to fold the statuses ONCE, here, into a
summary object every surface renders from — so they cannot disagree about the
headline, the all-clean flag, or a missing producer.

This is the **domain-free kernel half** of that rollup. It ships the FOLD; the
status vocabulary is CALLER DATA:

  * The caller supplies a `StatusRank` — its own closed status set mapped to a
    worst-first severity order (`{"failed": 0, "ok": 5, …}`). The kernel hard-codes
    NO status names (no "blktrace", no "ok"/"empty") — those are workspace data, the
    same closed-enum-as-data seam as `reasons`/`stamp`. Law 1 (kernel imports no
    host) holds: a rolled-up status is a string the kernel never interprets beyond
    "where does it rank?".
  * `requested-but-absent` is a FIRST-CLASS synthesized item, not a silence: a
    caller that *expected* a producer (it was requested) but got no item for it
    passes its key to `rollup(..., absent=[…])`, and the fold emits a typed item
    for it at a caller-named `absent_status`. So "we asked for X and got nothing"
    surfaces as a verdict on every surface, never as a missing row one surface
    happens to omit.

The result composes with the `dos.verdict` conventions (a `worst_status` headline
+ `reason` + `to_dict`) so it drops into the same `--output json` / renderer seam
as the other verdicts. Pure stdlib leaf — never raises on a malformed item (it
degrades to a caller-named `unknown_status`), the fail-safe rollup discipline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class StatusRank:
    """A caller's closed status vocabulary as a worst-first severity order.

    `order` maps each status string to an int where SMALLER == more severe (so the
    worst status is the `min`). `unknown_status` is what a malformed/unrankable item
    folds to (must itself be in `order`); `absent_status` is the status a
    requested-but-absent producer is synthesized as (also in `order`). Both default
    to common names but are caller-overridable — the kernel ships no fixed vocabulary.
    """

    order: Mapping[str, int]
    unknown_status: str = "unknown"
    absent_status: str = "requested"

    def rank(self, status: str) -> int:
        """Severity rank of `status` (smaller = worse). An unranked status sorts
        LAST (least severe) so an unknown caller status never masquerades as the
        worst — the headline must not be driven by a typo."""
        return self.order.get(status, max(self.order.values(), default=0) + 1)

    def __post_init__(self) -> None:
        if not self.order:
            raise ValueError("StatusRank.order must be non-empty")
        for name in (self.unknown_status, self.absent_status):
            if name not in self.order:
                raise ValueError(
                    f"StatusRank: {name!r} must appear in `order` "
                    f"(got {sorted(self.order)})")


@dataclass(frozen=True)
class RollupItem:
    """One folded item — a producer's status plus why, surface-agnostic.

    `key` identifies the producer (a device, a check name, …). `status` is one of
    the caller's vocabulary. `reason` is the operator-facing line. `absent` marks a
    synthesized requested-but-absent item (so a surface can style it distinctly).
    `integrity` carries extra flags a surface may highlight even on a status string
    that predates them (the lift's integrity-field idea, generalized to data)."""

    key: str
    status: str
    reason: str = ""
    absent: bool = False
    integrity: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "status": self.status,
            "reason": self.reason,
            "absent": self.absent,
            "integrity": list(self.integrity),
        }


@dataclass(frozen=True)
class VerdictRollup:
    """The single surface-agnostic summary every render surface reproduces.

    Composes with the `dos.verdict.TypedVerdict` shape: `worst_status` is the
    headline verdict, `reason` the one-line summary, `to_dict` the JSON seam. Every
    surface reads THESE fields, so they cannot drift in what they claim."""

    label: str
    items: tuple[RollupItem, ...]
    rank: StatusRank = field(repr=False, default=None)  # type: ignore[assignment]

    @property
    def present(self) -> bool:
        """True when there is anything worth surfacing at all."""
        return bool(self.items)

    @property
    def worst_status(self) -> Optional[str]:
        """The single most-severe status across all items (None when empty)."""
        if not self.items:
            return None
        return min((it.status for it in self.items), key=self.rank.rank)

    @property
    def all_clean(self) -> bool:
        """True iff every item is at the LEAST-severe rank and carries no integrity
        flag — i.e. nothing to act on. (Least-severe == the max-rank status, the
        caller's 'ok'.)"""
        if not self.items:
            return True
        best = max(self.rank.order.values())
        return all(
            self.rank.rank(it.status) == best and not it.integrity
            for it in self.items
        )

    @property
    def reason(self) -> str:
        """A counts-by-status headline, worst-first, e.g. ``2 ok, 1 empty``."""
        if not self.items:
            return f"{self.label}: nothing reported"
        counts: dict[str, int] = {}
        for it in self.items:
            counts[it.status] = counts.get(it.status, 0) + 1
        ordered = sorted(counts.items(), key=lambda kv: self.rank.rank(kv[0]))
        return ", ".join(f"{n} {st}" for st, n in ordered)

    # `verdict` is the TypedVerdict headline (the str-valued status). Kept a
    # property (not a field) so the rollup satisfies the Protocol structurally.
    @property
    def verdict(self) -> Optional[str]:
        return self.worst_status

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "verdict": self.worst_status,
            "worst_status": self.worst_status,
            "all_clean": self.all_clean,
            "reason": self.reason,
            "present": self.present,
            "items": [it.to_dict() for it in self.items],
        }


def _coerce_status(raw: Any, rank: StatusRank) -> str:
    """A status the caller's rank knows, or the caller's unknown_status (never raise)."""
    s = str(raw) if raw is not None else rank.unknown_status
    return s if s in rank.order else rank.unknown_status


def rollup(
    items: Sequence[Any],
    *,
    rank: StatusRank,
    label: str = "rollup",
    absent: Sequence[str] | None = None,
    status_of=lambda x: _get(x, "status"),
    key_of=lambda x: _get(x, "key"),
    reason_of=lambda x: _get(x, "reason", ""),
    integrity_of=lambda x: _get(x, "integrity", ()),
) -> VerdictRollup:
    """Fold status-bearing `items` (+ requested-but-absent keys) into one rollup.

    `items` is any sequence of objects or dicts; `status_of`/`key_of`/`reason_of`/
    `integrity_of` extract the fields (defaulting to attr/dict access by those
    names) — so a caller's own collector objects roll up without adapting them.
    A status not in `rank.order` degrades to `rank.unknown_status`; a malformed
    item degrades to one `unknown` row (never raises — the fail-safe discipline).

    `absent` is the load-bearing anti-drift feature: each key in it is a producer
    the caller REQUESTED but got no item for. Each becomes a synthesized
    `RollupItem(absent=True, status=rank.absent_status)` so "requested but missing"
    surfaces as a typed verdict on every surface, not as a silently-dropped row.
    """
    rows: list[RollupItem] = []
    for it in items or ():
        try:
            rows.append(RollupItem(
                key=str(key_of(it) or "?"),
                status=_coerce_status(status_of(it), rank),
                reason=str(reason_of(it) or ""),
                integrity=tuple(str(x) for x in (integrity_of(it) or ())),
            ))
        except Exception:  # noqa: BLE001 — a bad item must not break the fold
            rows.append(RollupItem(
                key="?", status=rank.unknown_status,
                reason="(unreadable item record)"))
    for k in absent or ():
        rows.append(RollupItem(
            key=str(k), status=rank.absent_status, absent=True,
            reason="requested but no result was produced"))
    return VerdictRollup(label=label, items=tuple(rows), rank=rank)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Attr-or-dict access, the duck-typed reader the lift uses."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
