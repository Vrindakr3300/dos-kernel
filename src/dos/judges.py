"""The judge seam — Axis 6 of hackability: pluggable adjudicators (the JUDGE rung).

Why this exists
===============

Trace one blocked claim through DOS and you find a **hierarchy of adjudicators at
escalating cost and trust**, the scalable-oversight shape in code:

  * **ORACLE** (kernel) — `verify()` / `picker_oracle`: deterministic, forgery-proof,
    grounded in git + on-disk state. Cheap, total, but *narrow* — it can only rule on
    what it can mechanically cross-check, and it ABSTAINS on everything else
    (`UNCLASSIFIED`).
  * **JUDGE** (this seam, lives in a driver) — a model, a heuristic, a debate, a
    fine-tuned verifier: anything that can rule on the residue the oracle abstained on.
    More expensive, *not* forgery-proof — so it is hedged by the four disciplines below.
  * **HUMAN** (the `dos decisions` queue) — the scarce resource, for what neither rung
    could resolve.

`decisions._resolver_for` is the router that classifies each blocked decision into
ORACLE / JUDGE / HUMAN; `drivers/llm_judge` is the first occupant of the JUDGE rung.
This module is the *seam* that occupant plugs into — a domain-neutral protocol a
researcher implements to drop in **their own** adjudicator (a debate judge, a
build/test oracle, a learned verifier) and have DOS compose it under the same
discipline as the built-in one. It is the bring-your-own-adjudicator surface, and the
companion `dos.judge_eval` is the instrument that scores what you plug in.

The unit a judge rules on is a `Claim` — a domain-neutral
``{claim_text, stated_reason, evidence}`` triple (the "claim → unforgeable-evidence →
verdict" schema). A judge is **not** told the answer; it is handed an agent's narration
plus the evidence the kernel could gather, and asked whether the narration is
believable. That decoupling is what lets a judge rule on a ship claim, a refusal, or an
arbitrary external assertion — not just DOS's own no-pick rows.

The four disciplines (what keeps an *open* adjudicator set honest)
==================================================================

This is the highest-trust-leverage axis — a judge's whole job is to rule on the claims
the deterministic oracle could *not* — so the guardrails are structural, mirroring the
renderer rule (pure presentation) and the predicate rule (conjunctive-only):

  1. **Deterministic-first** is the *composition's* job, not the protocol's:
     `judge_eval.compose_deterministic_first` (and `drivers/llm_judge.adjudicate`) run
     the oracle FIRST and only hand the judge the residue. A judge never overrides a
     provable verdict; it is consulted exactly where the oracle abstained.
  2. **Advisory-only** is enforced by *shape*: a judge is handed a frozen `Claim` + a
     read-only `config` and returns a frozen `JudgeVerdict`. It is given nothing it
     could mutate — no lease, no registry, no writable state. A judge can no more
     "believe itself into" a state change than a renderer can mis-verify a ship.
  3. **Fail-to-ABSTAIN, never fail-to-AGREE.** `run_judge` converts any exception — OR
     any non-`JudgeVerdict` return — into an `ABSTAIN`, never an `AGREE`. This is the
     *inverse direction* from the predicate rule on purpose: a safety predicate that
     can't answer fails CLOSED (refuse, the safe direction for admission); an advisory
     judge that can't answer ABSTAINS (punt to the next rung up, the safe direction for
     adjudication). Neither failure mode ever auto-clears a claim. The dangerous cell —
     a judge that AGREES with a claim that is in fact false (a false-clear) — is exactly
     what `judge_eval` measures and what these rules make a judge structurally unable to
     reach *by accident*.
  4. **Abstention is a first-class verdict, not an error.** A judge that says "I can't
     tell" is doing its job — it routes the claim onward to a human. `ABSTAIN` is the
     conservative default, and the built-in `AbstainJudge` (which abstains on
     everything) is the always-available, unshadowable baseline — the judge analogue of
     the `text` renderer: a trusted fallback a plugin can never displace.

Purity & layering
==================

This module is **pure** — a Protocol, two frozen value types, a built-in judge that
abstains, and resolver/runner helpers. It has NO provider surface, no I/O inside a
verdict, and names no host. So it sits in the kernel layer beside `render`/`admission`
(which likewise hold a pure protocol + resolver while the *implementations* live
outside). Every real judge with model/provider/I/O surface lives in a `drivers/*`
module or an installed plugin — `drivers/llm_judge` is the reference one; the kernel
points to it and never imports it (`drivers/__init__`: "they import the kernel; the
kernel never imports them"). Entry-point discovery (the one bit of I/O) happens at the
call boundary in `active_judges`, exactly as `active_predicates` / renderer discovery do.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class Stance(str, enum.Enum):
    """A judge's three-valued ruling on a claim.

    Three-valued by design: a binary agree/disagree would force a judge to guess
    when it cannot tell, and a guess is exactly the false-clear (`AGREE` on a false
    claim) the whole seam is built to make hard. `ABSTAIN` is the honest third
    answer — "I can't adjudicate this; send it up the ladder" — and it is the
    conservative default everything degrades to.
    """

    AGREE = "AGREE"        # the claim is believable given its evidence
    DISAGREE = "DISAGREE"  # the claim looks false / unsupported — flag it
    ABSTAIN = "ABSTAIN"    # cannot tell — punt to the next rung (a human)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Claim:
    """The domain-neutral unit a judge rules on: a narration plus its evidence.

    Deliberately NOT coupled to DOS's no-pick rows — a `Claim` can wrap a ship
    claim ("phase AUTH2 shipped"), a refusal, or an arbitrary external assertion.
    A judge sees the agent's `claim_text` + `stated_reason` (the *narration*, the
    part DOS does not believe) alongside `evidence` (the part it can — git lines,
    file state, a diff), and decides whether the narration is supported. The kernel
    gathers the evidence; the judge weighs it. `subject` is an optional opaque
    correlation handle (a run-id, a phase id) carried through for the caller's
    join — a judge MUST NOT need it to rule.
    """

    claim_text: str                      # what was asserted (the thing to adjudicate)
    stated_reason: str = ""              # the agent's narration / justification, if any
    evidence: tuple[str, ...] = field(default_factory=tuple)  # forgery-resistant facts
    subject: str = ""                    # opaque correlation handle (run-id/phase), optional


@dataclass(frozen=True)
class JudgeVerdict:
    """A judge's frozen, advisory ruling on one `Claim`.

    Three constructors, matching `Stance` — `.agree()`, `.disagree(why)`,
    `.abstain(why)` — and no other way to build one, so a judge's whole expressible
    output is "believable / not / can't-tell" plus prose. It carries NOTHING that
    could mutate state (the advisory-only invariant by shape): it is read by the
    decisions queue / the eval harness / an operator, and acting on it is always a
    separate, explicit step.

    `cost` is an OPTIONAL self-reported cost of producing this verdict (tokens,
    dollars, seconds — the unit is the judge's, summed verbatim by `judge_eval`).
    A judge that does not track cost leaves it 0.0; the rung-occupancy / cost-per-
    claim numbers then simply read 0 for that judge, never crash.

    The stored field is named ``_stance`` (private) so the ergonomic `.agree()`
    CONSTRUCTOR does not collide with a public ``stance`` — read state via the
    ``stance`` / ``agreed`` / ``abstained`` accessors, the same idiom
    `AdmissionVerdict` uses for ``_admit`` / ``.admitted``.
    """

    _stance: Stance
    why: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)
    cost: float = 0.0

    @property
    def stance(self) -> Stance:
        """The three-valued ruling. The public read accessor."""
        return self._stance

    @property
    def agreed(self) -> bool:
        """True iff the judge AGREED the claim is believable."""
        return self._stance is Stance.AGREE

    @property
    def disagreed(self) -> bool:
        """True iff the judge DISAGREED — it flagged the claim as false/unsupported."""
        return self._stance is Stance.DISAGREE

    @property
    def abstained(self) -> bool:
        """True iff the judge ABSTAINED — it could not rule (punt to a human)."""
        return self._stance is Stance.ABSTAIN

    @classmethod
    def agree(cls, why: str = "", *, evidence: tuple[str, ...] = (),
              cost: float = 0.0) -> "JudgeVerdict":
        """The claim is believable. The one verdict that can clear a claim — and the
        one a judge can NEVER reach by failing (see `run_judge`)."""
        return cls(_stance=Stance.AGREE, why=why, evidence=tuple(evidence), cost=cost)

    @classmethod
    def disagree(cls, why: str = "", *, evidence: tuple[str, ...] = (),
                 cost: float = 0.0) -> "JudgeVerdict":
        """The claim looks false / unsupported — the judge flags it."""
        return cls(_stance=Stance.DISAGREE, why=why, evidence=tuple(evidence), cost=cost)

    @classmethod
    def abstain(cls, why: str = "", *, evidence: tuple[str, ...] = (),
                cost: float = 0.0) -> "JudgeVerdict":
        """Cannot tell — punt up the ladder. The conservative default, and what every
        failure (exception, bad return type, no provider) degrades to."""
        return cls(_stance=Stance.ABSTAIN, why=why, evidence=tuple(evidence), cost=cost)

    def to_dict(self) -> dict:
        return {
            "stance": self._stance.value,
            "why": self.why,
            "evidence": list(self.evidence),
            "cost": self.cost,
        }


@runtime_checkable
class Judge(Protocol):
    """The contract a researcher implements to add an adjudicator.

    ``name`` is the token `dos judge-eval --judge <name>` selects and `dos doctor`
    lists. ``rule`` is handed one frozen `Claim` and the active `config` (read-only —
    a judge reads policy from it, e.g. the reason vocabulary, but the type gives it
    nothing to mutate) and returns a `JudgeVerdict`.

    A judge MAY do I/O *inside* ``rule`` (call a model, shell out, read a file) —
    unlike a predicate or a renderer, which are pure. That is the whole reason a real
    judge lives in a driver, outside the kernel boundary: the JUDGE rung is where
    provider surface is allowed. The disciplines that keep it honest are
    advisory-only (it returns a verdict, mutates nothing) and fail-to-abstain
    (enforced by `run_judge`, not by trusting the judge to be careful), NOT purity.
    """

    name: str

    def rule(self, claim: Claim, config: object) -> JudgeVerdict:
        ...


class AbstainJudge:
    """The built-in, always-available judge: it abstains on everything.

    The judge analogue of the `text` renderer — a trusted fallback a plugin can never
    shadow (`resolve_judge` resolves built-ins first). It is the honest zero of the
    seam: a workspace with NO judge wired still has a resolvable judge, and it punts
    every claim to a human (the safe, conservative behavior). It is also the baseline
    `judge_eval` measures every real judge against: a judge that does no better than
    `abstain` on the residue has added nothing but cost.
    """

    name = "abstain"

    def rule(self, claim: Claim, config: object) -> JudgeVerdict:
        return JudgeVerdict.abstain(
            "no adjudicator wired — the built-in judge abstains, routing this "
            "claim to a human (configure a JUDGE-rung driver to rule on it)."
        )


def run_judge(judge: Judge, claim: Claim, config: object) -> JudgeVerdict:
    """Run one judge against one claim, enforcing **fail-to-abstain**.

    This is the wrapper EVERY consumer should call instead of `judge.rule(...)`
    directly — it is what makes "a judge can never auto-clear a claim by failing" a
    structural guarantee rather than a hope:

      * a judge that **raises** (model timeout, bad provider, a bug) → `ABSTAIN`,
        naming the failure. Never propagates; never `AGREE`.
      * a judge that returns **anything that is not a `JudgeVerdict`** (None, a dict,
        a duck-typed look-alike) → `ABSTAIN`. We never read a foreign object's
        `.agreed`, so no false-clear can sneak through a wrong return type.

    Note the deliberate asymmetry with `admission.run_predicates`, which converts the
    same failures to a **refuse**: a predicate guards admission, so its safe failure
    is "deny"; a judge is advisory, so its safe failure is "I don't know — ask a
    human." Both refuse to let a failure become an approval; they differ only in which
    non-approval is the safe one for their role.
    """
    name = getattr(judge, "name", type(judge).__name__)
    try:
        verdict = judge.rule(claim, config)
    except Exception as e:  # fail-to-abstain: a judge that raises cannot rule
        return JudgeVerdict.abstain(
            f"judge {name!r} raised ({e!r}) — abstaining (an advisory adjudicator "
            f"that cannot answer punts to a human, it never auto-clears)."
        )
    if not isinstance(verdict, JudgeVerdict):
        return JudgeVerdict.abstain(
            f"judge {name!r} returned a {type(verdict).__name__}, not a "
            f"JudgeVerdict — abstaining (a judge that does not return the verdict "
            f"type cannot be trusted to clear a claim)."
        )
    return verdict


# ---------------------------------------------------------------------------
# Resolution — built-in first, then the `dos.judges` entry-point group.
# ---------------------------------------------------------------------------

# The entry-point group a workspace/researcher registers a judge under.
JUDGE_ENTRY_POINT_GROUP = "dos.judges"

# The built-in judges, resolvable by name and UNSHADOWABLE by a plugin (a plugin
# registering `abstain` cannot displace this one — built-ins resolve first). Only
# the conservative `abstain` baseline ships in the kernel; every ruling judge lives
# in a driver/plugin (the kernel has no provider surface).
_BUILT_IN_JUDGES: dict[str, type] = {
    AbstainJudge.name: AbstainJudge,
}


def _discover_entry_point_judges(*, _stderr=None) -> list[tuple[str, Judge]]:
    """Find judges registered under the `dos.judges` entry-point group.

    A judge plugin registers ``name = "pkg.module:JudgeClass"`` in its
    ``[project.entry-points."dos.judges"]``. We load each, instantiate it if it is a
    class, and return ``(entry_point_name, judge)`` pairs sorted by name (stable, so
    `dos doctor` order is deterministic). A plugin that fails to load is skipped with
    a one-line stderr note rather than crashing — the same posture
    `admission._discover_entry_point_predicates` / renderer discovery take (a broken
    third-party plugin is the operator's to fix, not a kernel fault).
    """
    stderr = _stderr if _stderr is not None else sys.stderr
    out: list[tuple[str, Judge]] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=JUDGE_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(JUDGE_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash a call
        return out
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            obj = ep.load()
            judge = obj() if isinstance(obj, type) else obj
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: judge plugin {ep.name!r} failed to load ({e}); skipping",
                file=stderr,
            )
            continue
        out.append((ep.name, judge))
    return out


def resolve_judge(name: str, *, _stderr=None) -> Judge:
    """Resolve a judge by name: built-ins first, then `dos.judges` plugins.

    Built-ins (`abstain`) resolve FIRST and cannot be shadowed by a plugin of the
    same name — the trusted-fallback guarantee, identical to `resolve_renderer`. An
    unknown name fails LOUD with the known list (it never silently degrades to
    `abstain`, which would hide a typo'd `--judge`): the caller asked for a specific
    adjudicator and getting a different one silently is exactly the kind of
    unannounced substitution the kernel refuses.
    """
    if name in _BUILT_IN_JUDGES:
        return _BUILT_IN_JUDGES[name]()
    discovered = dict(_discover_entry_point_judges(_stderr=_stderr))
    if name in discovered:
        return discovered[name]
    known = sorted(set(_BUILT_IN_JUDGES) | set(discovered))
    raise ValueError(
        f"unknown judge {name!r}; known: {', '.join(known)}"
    )


def active_judges(*, _stderr=None) -> list[tuple[str, Judge]]:
    """Every resolvable judge as ``(name, judge)`` — built-ins THEN discovered
    plugins, the order `dos doctor` lists. Does ENTRY-POINT DISCOVERY (I/O), so it is
    a call-boundary helper, never called inside a verdict."""
    built = [(n, cls()) for n, cls in _BUILT_IN_JUDGES.items()]
    discovered = _discover_entry_point_judges(_stderr=_stderr)
    return built + discovered


def active_judge_names(*, _stderr=None) -> list[str]:
    """The names of every active judge (built-in + discovered) — what `dos doctor`
    lists so an operator can see which adjudicators the JUDGE rung can call (the
    judge analogue of "see the active predicates / reason set")."""
    return [name for name, _judge in active_judges(_stderr=_stderr)]
