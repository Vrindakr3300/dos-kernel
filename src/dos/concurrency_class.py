"""Concurrency-class budgets as declared data — the operator surface over the
already-shipped arbiter class-budget enforcement (docs/97 Phase 1-2, C13).

The arbiter ALREADY enforces "at most N of kind K may hold a lease at once":
`arbiter.arbitrate(..., class_budgets={"priority": 3})` counts live leases per
kind on the auto-pick walk, skips budget-exhausted candidates, and returns the
named `CLASS_BUDGET_EXHAUSTED` refuse (`arbiter.py:356,366,714`). What was missing
is the *operator surface* — the budgets were reachable only as a Python parameter.
This module is that surface's data half: a closed `ConcurrencyClass{name,
max_concurrent}` dataclass + a `from_table` reader for the `[[concurrency_class]]`
array-of-tables in `dos.toml`, projecting to the exact `{kind: N}` dict the arbiter
consumes.

This is mechanism-as-data, the `reasons`/`stamp`/`lanes` seam pattern: the kernel
ships the enforcement; the host declares the VALUES per workspace. It names no host
class — `"priority"`, `"apply"`, whatever — those are workspace data, so Law 1
(kernel imports no host) holds. It deliberately carries ONLY a max-concurrent
budget; it does NOT carry lane priority/value ordering — the arbiter refuses to
hard-code "whose work is valuable" (docs/90 §6), so that stays host policy and
never enters this registry.

    [[concurrency_class]]
    name = "priority"
    max_concurrent = 3

    [[concurrency_class]]
    name = "apply"
    max_concurrent = 1

Pure stdlib leaf — the closed-enum-as-data discipline, validated loud-on-malformed
(a host that mis-declared a budget wants it surfaced at load, not silently dropped
to "no budget" which would let the class run unbounded).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConcurrencyClass:
    """One declared budget: at most `max_concurrent` leases of kind `name` at once.

    `name` is the lane-KIND the arbiter keys budgets on (`lease["lane_kind"]`),
    opaque workspace data. `max_concurrent` is a non-negative int — 0 means "admit
    none of this kind" (a valid, if drastic, throttle); a negative value is a
    declaration error.
    """

    name: str
    max_concurrent: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("concurrency_class.name is required (the lane kind)")
        if not isinstance(self.max_concurrent, int) or isinstance(self.max_concurrent, bool):
            raise ValueError(
                f"concurrency_class[{self.name!r}].max_concurrent must be an int, "
                f"got {type(self.max_concurrent).__name__}"
            )
        if self.max_concurrent < 0:
            raise ValueError(
                f"concurrency_class[{self.name!r}].max_concurrent must be ≥ 0, "
                f"got {self.max_concurrent}"
            )


@dataclass(frozen=True)
class ClassBudgets:
    """The declared concurrency-class registry — an ordered set of `ConcurrencyClass`.

    Carries the budgets as data and projects them to the `{kind: max_concurrent}`
    dict `arbiter.arbitrate(class_budgets=...)` already consumes. Empty by default
    (no file / no `[[concurrency_class]]` table → no budgets → today's unbounded-
    per-kind behavior, the additive-degradation floor)."""

    classes: tuple[ConcurrencyClass, ...] = ()

    def as_arbiter_budgets(self) -> dict[str, int]:
        """The `{kind: max_concurrent}` dict the arbiter takes. A duplicate name is a
        last-wins override (the host declared the same class twice — honor the last,
        the toml array's natural order)."""
        out: dict[str, int] = {}
        for c in self.classes:
            out[c.name] = c.max_concurrent
        return out

    @classmethod
    def from_table(cls, table: object) -> "ClassBudgets":
        """Build from a parsed `[[concurrency_class]]` array-of-tables.

        TOML's `[[concurrency_class]]` parses to a LIST of dicts. Tolerant of an
        absent/empty list (→ no budgets). Rejects, with a `ValueError` naming the
        offending entry, anything that is not a `{name, max_concurrent}` table —
        loud-on-malformed, the sibling-seam discipline. Mirrors
        `reason_morphology.MorphologyRuleset.from_table` in shape (the array-of-
        tables reader)."""
        if table is None:
            return cls(())
        if not isinstance(table, (list, tuple)):
            raise ValueError(
                f"[[concurrency_class]] must be an array of tables, "
                f"got {type(table).__name__}"
            )
        out: list[ConcurrencyClass] = []
        for i, item in enumerate(table):
            if not isinstance(item, dict):
                raise ValueError(
                    f"[[concurrency_class]] entry {i} must be a table "
                    f"({{name, max_concurrent}}), got {type(item).__name__}"
                )
            if "name" not in item or "max_concurrent" not in item:
                raise ValueError(
                    f"[[concurrency_class]] entry {i} needs both `name` and "
                    f"`max_concurrent` (got keys {sorted(item)})"
                )
            # ConcurrencyClass.__post_init__ validates the value shapes (name
            # non-empty, max_concurrent a non-negative int).
            out.append(ConcurrencyClass(
                name=str(item["name"]), max_concurrent=item["max_concurrent"]))
        return cls(tuple(out))


# An empty registry — the kernel default (no per-kind budget, today's behavior).
NO_CLASS_BUDGETS = ClassBudgets(())


def parse_cli_budgets(pairs: list[str] | None) -> dict[str, int]:
    """Parse repeatable `--class-budget KIND=N` operator flags into `{kind: N}`.

    Each `pairs` item is a `"KIND=N"` string. Raises `ValueError` (operator error,
    the CLI maps it to a clean contract-error exit, never a traceback) on a malformed
    pair: no `=`, an empty kind, or a non-int / negative N. An empty/None list → {}.
    These OVERLAY the config-declared budgets at the call boundary (a `--class-budget`
    wins over a `[[concurrency_class]]` of the same name — the explicit operator flag
    beats the declared default)."""
    out: dict[str, int] = {}
    for raw in pairs or ():
        if "=" not in raw:
            raise ValueError(
                f"--class-budget must be KIND=N, got {raw!r} (no '=')")
        kind, _, val = raw.partition("=")
        kind = kind.strip()
        if not kind:
            raise ValueError(f"--class-budget {raw!r} has an empty KIND")
        try:
            n = int(val.strip())
        except ValueError:
            raise ValueError(
                f"--class-budget {raw!r}: N must be an integer, got {val.strip()!r}"
            ) from None
        if n < 0:
            raise ValueError(f"--class-budget {raw!r}: N must be ≥ 0, got {n}")
        out[kind] = n
    return out
