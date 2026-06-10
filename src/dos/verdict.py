"""The typed-verdict contract — one ABI the distrust verbs share (docs/86).

`liveness` and `scope` are two instances of the *same* shape, and `verify`'s
`ShipVerdict` is a third that drifted. This module NAMES that shape as a contract
so a third party can add a verdict the way you add a device driver — and so the
CLI, the `dos decisions` queue, and the MCP server can treat every verdict
uniformly instead of special-casing each verb.

It is deliberately written **after** there were two real instances to generalize
from (`liveness.classify`, `scope.classify`) — the "generalize last" discipline
(docs/86 §4): a contract invented before its instances is machinery imported
ahead of need. This module adds NO behavior to the existing verbs; it is a pure
description (Protocols) plus a conformance check a future verdict registry can
call. Nothing here is imported by `liveness`/`scope`/`oracle` — the arrow points
the other way (a consumer reads this; the verbs don't depend on it).

The contract, in one line:

    classify(Evidence, Policy) -> Verdict[V]

where the pieces are exactly what `liveness`/`scope` already are:

  Evidence  — a frozen dataclass of facts GATHERED BY THE CALLER (no I/O inside
              the verdict). The git read / config read / clock lives at the CLI
              boundary; `classify` receives the already-gathered facts. This is
              what lets a verdict be replay-tested on frozen fixtures.
  Policy    — a frozen dataclass of thresholds, declarable per-workspace in
              `dos.toml [<verb>]` (the `[liveness]`/`[scope]` seam), defaults
              GENERIC. "Mechanism is kernel, knobs are config."
  Verdict   — the typed answer: a CLOSED-ENUM `verdict` (never a bare bool), a
              one-line operator-facing `reason`, the echoed `evidence`, and a
              `to_dict()` for the JSON/MCP/renderer seam. The provenance — which
              rung/signal answered — is carried IN the verdict (liveness's
              `evidence`, scope's spill lists, `ShipVerdict.source`).

This is the three kernel design laws fused into one type: *typed verdict over
binary gate* (the closed enum), *evidence over narrative* (Evidence is gathered
from artifacts, never the agent's claim), and *the give lives in provenance*
(docs/76 — the rung, not the adjudication, is what flexes).

SCOPE — the contract is for the EPISTEMIC verbs only: the ones that answer "is
this claim about ground-truth state true?" (`verify`, `liveness`, `scope`, and
the candidates `acceptance`/`identity`). `arbitrate()` and `spawn/reap` share the
`classify` *shape* (state-in → typed-out, pure) but their output is an EFFECT
decision (acquire/refuse) or an IDENTITY record, not a belief about the world —
they are cousins, not members. Forcing them under this Protocol would make it a
god-type that means nothing; the boundary is part of the contract.

The four-gate registration test a verdict must pass to be a kernel verb (docs/85
§2, enforced by a future `dos.verdicts.register`): (1) it answers a claim about
ground-truth state; (2) its evidence is unforgeable by the agent; (3) it is
domain-free; (4) its verdict is a mechanical closed enum. Fail (1) → it is an
advisory JUDGE (`drivers/llm_judge`), not a verdict. Fail (3) → it is a driver
oracle on the seam, not a kernel verb. Open set of verbs, CLOSED shape per verb —
the closed-enum-as-data hackability pattern (HACKING.md) lifted from vocabularies
to verdicts.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TypedVerdict(Protocol):
    """The shape every distrust verdict returns. `liveness.LivenessVerdict` and
    `scope.ScopeVerdict` satisfy it structurally (no inheritance needed — this is
    a duck-typed Protocol).

      verdict  — a `str`-valued Enum member (the closed verdict vocabulary). The
                 `str` base lets it round-trip through a CLI token / exit-code map
                 without a lookup table; `.value` is the wire form.
      reason   — a one-line, operator-facing summary of WHY this verdict, naming
                 the driving evidence (legible distrust — the renderer seam).
      to_dict  — the JSON shape: the verdict, the reason, and the evidence behind
                 it, so `--output json` / an MCP tool emits the answer AND its
                 grounds in one object.
    """

    @property
    def verdict(self) -> Any:  # a str-valued enum member
        ...

    @property
    def reason(self) -> str:
        ...

    def to_dict(self) -> dict:
        ...


@runtime_checkable
class Classifier(Protocol):
    """A pure verdict function: `classify(evidence, policy) -> TypedVerdict`.

    The shared signature of `liveness.classify` and `scope.classify`. `policy`
    carries a default, so a caller may invoke `classify(evidence)`; a verb's
    `gather()` (the boundary I/O) produces the `evidence` argument. A `Classifier`
    MUST NOT perform I/O — that is the property the conformance check below cannot
    enforce statically but every kernel verb's test suite poisons `subprocess`/
    `open`/`time` to prove (see `test_liveness`/`test_scope`).
    """

    def __call__(self, evidence: Any, policy: Any = ..., /) -> TypedVerdict:
        ...


def conforms(verdict_obj: Any) -> bool:
    """True when `verdict_obj` satisfies the `TypedVerdict` contract at runtime.

    The check a future `dos.verdicts.register` runs on a third party's verdict
    sample before exposing it as a `dos <verb>` subcommand / a decisions-queue row
    / an MCP tool. Structural, not nominal: any object with a `str`-enum `verdict`,
    a `str` `reason`, and a callable `to_dict()` whose result is JSON-shaped passes
    — no base class required.

    Note this validates the *verdict value's* shape, which is gate (4) of the
    four-gate test (a mechanical closed enum + a legible reason). Gates (1)–(3)
    — ground-truth claim, unforgeable evidence, domain-free — are properties of
    the verb's DESIGN that a runtime check cannot see; they stay a review
    responsibility (the contract documents them so the reviewer has the checklist).
    """
    if not isinstance(verdict_obj, TypedVerdict):
        return False
    # `verdict` must be a str-valued enum member (the closed vocabulary), not a
    # bare bool or free string — the "typed verdict over binary gate" law.
    import enum

    v = verdict_obj.verdict
    if not isinstance(v, enum.Enum) or not isinstance(v, str):
        return False
    if not isinstance(verdict_obj.reason, str):
        return False
    try:
        d = verdict_obj.to_dict()
    except Exception:
        return False
    if not isinstance(d, dict) or "verdict" not in d:
        return False
    return True
