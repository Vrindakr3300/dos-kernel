"""The financial-model artifact + the deterministic recompute engine — the NON-FORGEABLE
witness. PURE, $0, no network, stdlib only.

A `FinModel` is the auditable object the paper says human experts produce: a graph of cells,
each either a LITERAL (an input the modeller typed) or a FORMULA (an arithmetic expression
over OTHER cells — the "correctly linked" property). The model also carries a BALANCE IDENTITY
(assets == liabilities + equity) declared as cell references, plus the SOURCE TRACE for every
literal headline figure (which line item it came from).

The recompute engine is the witness. It re-evaluates every FORMULA cell from its precedents
and compares the result to the STORED value the model carries. Crucially:

  * The model's stored values are AGENT-AUTHORED (the forgeable floor) — the agent could
    write any number into a cell, formula or not. That is exactly the static-value masquerade:
    a cell DECLARED as a formula but STORED with a hand-typed value that the formula would not
    produce.
  * The recompute is computed by THIS engine from the formula's precedents — bytes the agent
    did not author. That is the `OS_RECORDED` rung: the recomputed value is a function of the
    model's structure + its LITERAL inputs, evaluated by code the agent does not control.

So a `RecomputeReport` is a join of two independently-authored facts (docs/179): the stored
value (agent) vs the recomputed value (engine). A cell where they disagree is the docs/156
byte-inequality made concrete — "confirming bytes ≠ emitted bytes."

THE THREE FORGERY CHECKS (each maps to a FrontierFinance failure-catalogue line)
================================================================================
  (a) STATIC_VALUE  — a formula cell whose stored value ≠ its recomputed value. "Replaced
      formulas with static values, producing models that appeared complete but could not be
      updated." The recompute disagrees → REFUTE.
  (b) FABRICATED_BALANCE — the model ASSERTS it balances (assets == L+E) but the recomputed
      identity does NOT hold. "Balanced with implausible, fabricated values merely to satisfy
      the balancing criteria." The recomputed identity disagrees → REFUTE.
  (c) PLUG_BALANCE  — the model balances, but only because a balancing cell was set to a
      LITERAL with no precedent trace (a "plug") rather than a formula deriving it. The
      "~88 hidden white-font rows" / "concealing the workaround" shape: the balance is real on
      its face but achieved by a hard-coded number, not a linked derivation. A balancing cell
      with no precedents (a bare literal occupying a slot the identity expects to be derived)
      → REFUTE.

The engine is deliberately a TINY arithmetic evaluator (literals + + - * / and cell refs),
not a general spreadsheet — enough to express the failure catalogue precisely, no formula
language a synthesizer could not deterministically construct. NO `eval`: a hand-written
recursive-descent over a fixed operator set, so the witness itself is auditable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# The cell — a literal input or a formula over other cells.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """One cell in the model.

    `name`    — the cell's stable id (e.g. "revenue_y1", "total_assets").
    `stored`  — the value the MODEL carries for this cell. AGENT-AUTHORED (forgeable): the
                agent typed it, whether the cell is a literal or a formula. This is the side
                the gate distrusts.
    `formula` — the arithmetic expression that DERIVES this cell from others, or "" if the
                cell is a LITERAL input. A non-empty formula makes this a "linked" cell whose
                stored value the engine can recompute and check.
    `source`  — for a literal headline figure, the source line item it should resolve to
                (the citation_resolve shape, optional). "" if not a traced headline.
    """

    name: str
    stored: float
    formula: str = ""
    source: str = ""

    @property
    def is_formula(self) -> bool:
        return bool(self.formula and self.formula.strip())

    @property
    def is_literal(self) -> bool:
        return not self.is_formula


@dataclass(frozen=True)
class BalanceIdentity:
    """The accounting identity the model asserts holds: lhs == sum(rhs).

    The canonical case is assets == liabilities + equity, declared as cell references so the
    engine can RE-DERIVE it from recomputed cell values rather than trust a stored "balances:
    True" flag the agent could forge. `tol` is the absolute tolerance for the floating compare.

    `closing_cells` names the rhs cells that a SOUND model DERIVES (the balancing "close" — the
    equity roll-forward total, retained earnings). These are the slots a plug hides in: a close
    cell that is a bare LITERAL with no precedents is the fabricated workaround the paper
    describes. A genuine INPUT on the rhs (a `debt` liability the modeller typed) is NOT a
    closing cell and is never flagged — the structural distinction that keeps plug-detection
    from false-refuting an honest literal liability. Empty == no plug check (no close declared).
    """

    lhs: str                       # the cell that must equal the sum of rhs (e.g. "total_assets")
    rhs: tuple[str, ...]           # cells summed on the other side (e.g. liabilities, equity)
    closing_cells: tuple[str, ...] = ()  # rhs cells a sound model DERIVES (where a plug hides)
    tol: float = 1e-6


@dataclass(frozen=True)
class FinModel:
    """A financial model: a graph of cells + an optional balance identity.

    `cells` is keyed by name. `balance` is the asserted accounting identity (or None for a
    model with no balance sheet, e.g. a pure projection). `asserted_balances` is the agent's
    FORGEABLE self-report that the model balances — carried so the gate can compare the CLAIM
    to the recomputed identity (the static-value masquerade's balance analogue).
    """

    cells: dict[str, Cell]
    balance: Optional[BalanceIdentity] = None
    asserted_balances: bool = False
    name: str = ""

    def cell(self, name: str) -> Optional[Cell]:
        return self.cells.get(name)


# ---------------------------------------------------------------------------
# The recompute engine — a tiny, auditable arithmetic evaluator. NO eval().
# ---------------------------------------------------------------------------

# A token is a number, a cell name, an operator, or a paren. Cell names are
# [a-z_][a-z0-9_]* (lower-snake); numbers are plain decimals (no scientific notation needed
# for a synthesized corpus).
_TOKEN_RE = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)|(?P<op>[()+\-*/]))")


class FormulaError(Exception):
    """A formula could not be evaluated (unknown cell, bad syntax, cycle, div-by-zero)."""


def _tokenize(expr: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(expr):
        if expr[i].isspace():
            i += 1
            continue
        m = _TOKEN_RE.match(expr, i)
        if not m:
            raise FormulaError(f"bad token at {expr[i:]!r}")
        i = m.end()
        if m.group("num") is not None:
            out.append(("num", m.group("num")))
        elif m.group("name") is not None:
            out.append(("name", m.group("name")))
        else:
            out.append(("op", m.group("op")))
    return out


class _Parser:
    """Recursive-descent over + - * / and parentheses, evaluating against a resolver.

    `resolve(name)` returns the (already-recomputed) value of a precedent cell. Standard
    precedence: */ binds tighter than +-; left-associative; parentheses group.
    """

    def __init__(self, tokens: list[tuple[str, str]], resolve):
        self.toks = tokens
        self.pos = 0
        self.resolve = resolve

    def _peek(self) -> Optional[tuple[str, str]]:
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def _next(self) -> tuple[str, str]:
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def parse(self) -> float:
        v = self._expr()
        if self.pos != len(self.toks):
            raise FormulaError("trailing tokens in formula")
        return v

    def _expr(self) -> float:
        v = self._term()
        while True:
            t = self._peek()
            if t == ("op", "+"):
                self._next(); v = v + self._term()
            elif t == ("op", "-"):
                self._next(); v = v - self._term()
            else:
                return v

    def _term(self) -> float:
        v = self._factor()
        while True:
            t = self._peek()
            if t == ("op", "*"):
                self._next(); v = v * self._factor()
            elif t == ("op", "/"):
                self._next()
                d = self._factor()
                if d == 0:
                    raise FormulaError("division by zero")
                v = v / d
            else:
                return v

    def _factor(self) -> float:
        t = self._peek()
        if t is None:
            raise FormulaError("unexpected end of formula")
        kind, val = t
        if t == ("op", "("):
            self._next()
            v = self._expr()
            if self._peek() != ("op", ")"):
                raise FormulaError("missing closing paren")
            self._next()
            return v
        if t == ("op", "-"):           # unary minus
            self._next()
            return -self._factor()
        if kind == "num":
            self._next()
            return float(val)
        if kind == "name":
            self._next()
            return self.resolve(val)
        raise FormulaError(f"unexpected token {t!r}")


def precedents(formula: str) -> tuple[str, ...]:
    """The cell names a formula references (its precedents). Empty for a literal."""
    if not (formula and formula.strip()):
        return ()
    names = [val for kind, val in _tokenize(formula) if kind == "name"]
    # de-dup, preserve order
    seen: dict[str, None] = {}
    for n in names:
        seen.setdefault(n, None)
    return tuple(seen.keys())


def _eval_cell(model: FinModel, name: str, memo: dict[str, float], stack: tuple[str, ...]) -> float:
    """Recompute one cell's value from its precedents (a LITERAL recomputes to its own stored
    value; a FORMULA recomputes by evaluating its expression over recomputed precedents).

    Cycles raise FormulaError (a model whose links form a cycle is itself malformed — the
    witness reports it as un-recomputable, never silently believes the stored value)."""
    if name in memo:
        return memo[name]
    if name in stack:
        raise FormulaError(f"cycle through {name!r}")
    cell = model.cell(name)
    if cell is None:
        raise FormulaError(f"unknown cell {name!r}")
    if cell.is_literal:
        # A literal's recomputed value IS its stored value — there is nothing to derive. The
        # static-value check below only flags FORMULA cells; a literal input is the modeller's
        # honest typed datum (the gate distrusts a literal only when it occupies a derived slot
        # — the PLUG_BALANCE check, handled at the balance level, not here).
        memo[name] = cell.stored
        return cell.stored
    toks = _tokenize(cell.formula)
    val = _Parser(toks, lambda n: _eval_cell(model, n, memo, stack + (name,))).parse()
    memo[name] = val
    return val


# ---------------------------------------------------------------------------
# The reports — the witness's structured findings (the OS_RECORDED facts).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CellDiscrepancy:
    """One formula cell whose STORED value disagrees with its RECOMPUTED value."""

    cell: str
    stored: float
    recomputed: float
    formula: str

    def to_dict(self) -> dict:
        return {"cell": self.cell, "stored": self.stored,
                "recomputed": self.recomputed, "formula": self.formula}


@dataclass(frozen=True)
class RecomputeReport:
    """The full witness verdict over a model — the OS_RECORDED structured fact.

    `static_value` — formula cells whose stored ≠ recomputed (the static-value masquerade).
    `balance_ok`   — did the recomputed accounting identity actually hold? (None if no
                     balance sheet.) A model that ASSERTS it balances but whose recomputed
                     identity does NOT → fabricated balance.
    `plug_cells`   — balancing-side cells the identity expects to be DERIVED but that are bare
                     literals with no precedents (the plug / white-font workaround).
    `errors`       — cells that could not be recomputed (cycle, unknown ref, bad formula).
    """

    static_value: tuple[CellDiscrepancy, ...] = ()
    balance_ok: Optional[bool] = None
    plug_cells: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def any_finding(self) -> bool:
        """True iff the witness found ANY mechanical-soundness defect."""
        return bool(self.static_value) or self.balance_ok is False or bool(self.plug_cells)

    def to_dict(self) -> dict:
        return {
            "static_value": [d.to_dict() for d in self.static_value],
            "balance_ok": self.balance_ok,
            "plug_cells": list(self.plug_cells),
            "errors": list(self.errors),
        }


def recompute(model: FinModel, *, tol: float = 1e-6) -> RecomputeReport:
    """RE-EVALUATE every formula cell + the balance identity from precedents — the witness.

    This is the non-forgeable read-back: it reads the model's STRUCTURE (which cells are
    formulas, what they reference) and its LITERAL inputs, and recomputes everything the model
    CLAIMS is derived. It never trusts a stored formula-cell value or a stored "balances" flag.

    Returns a `RecomputeReport`. The three forgery classes surface as: `static_value`
    (formula cell stored ≠ recomputed), `balance_ok is False` (asserted-balance fabricated),
    `plug_cells` (balance achieved by a bare-literal plug with no precedent trace).
    """
    discrepancies: list[CellDiscrepancy] = []
    errors: list[str] = []
    memo: dict[str, float] = {}

    # (a) static-value masquerade: every FORMULA cell must recompute to its stored value.
    for name, cell in sorted(model.cells.items()):
        if not cell.is_formula:
            continue
        try:
            got = _eval_cell(model, name, memo, ())
        except FormulaError as e:
            errors.append(f"{name}: {e}")
            continue
        if abs(got - cell.stored) > tol:
            discrepancies.append(CellDiscrepancy(
                cell=name, stored=cell.stored, recomputed=got, formula=cell.formula))

    # (b)/(c) the balance identity, if the model declares one.
    balance_ok: Optional[bool] = None
    plug_cells: list[str] = []
    if model.balance is not None:
        b = model.balance
        try:
            lhs = _eval_cell(model, b.lhs, memo, ())
            rhs_total = 0.0
            for r in b.rhs:
                rhs_total += _eval_cell(model, r, memo, ())
            balance_ok = abs(lhs - rhs_total) <= max(tol, b.tol)
        except FormulaError as e:
            errors.append(f"balance: {e}")
            balance_ok = None

        # (c) PLUG detection: a CLOSING cell (one a sound model DERIVES — the equity/retained
        # roll-forward total) that is instead a BARE LITERAL with no precedents is a plug — a
        # hard-coded number occupying a slot the model should derive, sized to make the sheet
        # tie. We flag a plug ONLY when the model also asserts it balances AND the recomputed
        # identity holds (a plug that does NOT make it balance is just a bad literal, already
        # caught by the fabricated-balance check; the FORGERY here is the plug that FAKES a
        # clean balance). Only `closing_cells` are eligible — a genuine INPUT liability on the
        # rhs (a `debt` the modeller typed) is a real literal, not a plug, and is never flagged
        # (the structural distinction that keeps this from false-refuting an honest input).
        if balance_ok and model.asserted_balances:
            for r in b.closing_cells:
                cell = model.cell(r)
                if cell is not None and cell.is_literal:
                    plug_cells.append(r)

    return RecomputeReport(
        static_value=tuple(discrepancies),
        balance_ok=balance_ok,
        plug_cells=tuple(plug_cells),
        errors=tuple(errors),
    )
