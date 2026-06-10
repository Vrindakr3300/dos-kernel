"""The verdict registry — the OS-extensibility surface for distrust verbs (docs/86 §2).

`verdict.py` names the *contract* a typed verdict satisfies; this module is the
*registry* of verbs that satisfy it. It is the seam that lets a third party add a
verdict the way you add a device driver: ship a module with a `classify` (the
`verdict.Classifier` shape) and a short spec, `register()` it, and a consumer —
the CLI, the `dos decisions` queue, an MCP tool — can enumerate and dispatch it
WITHOUT the kernel hard-wiring its name.

This is the **verb-analogue of the data registries the kernel already ships**:
`[reasons]` (`ReasonRegistry`), `[lanes]` (`LaneTaxonomy`), `[stamp]`
(`StampConvention`) declare a workspace's *vocabulary* as data; this declares its
set of *verdicts* as registered specs. The combination is the one design pattern
(HACKING.md, the closed-enum-as-data axis) lifted one level up: **an OPEN set of
verbs, each with a CLOSED verdict shape.**

Built *after* there were two real instances to generalize from (`liveness`,
`scope`) — the "generalize last" discipline (docs/86 §4): a registry built before
its instances is machinery imported ahead of need. The two are seed-registered
below, centrally — the registry imports the verbs (consumer → verb, the same
arrow `cli.py` uses), so the pure verb modules stay registry-UNAWARE and there is
no import cycle. A verb must never `import dos.verdicts`.

The four-gate registration test (docs/85 §2) a verdict must pass to be a kernel
verb: (1) it answers a claim about ground-truth state; (2) its evidence is
unforgeable by the agent; (3) it is domain-free; (4) its verdict is a mechanical
closed enum. Gate (4) is machine-checkable here (`verdict.conforms` on a produced
sample); gates (1)–(3) are properties of the verb's DESIGN that no runtime check
can see — they stay a review responsibility, and `register(..., reviewed=...)`
records that a human signed off so a registry audit can surface anything that
slipped in unreviewed.

NOTE on `verify`: it is the third epistemic verb, but `oracle.ShipVerdict` has not
yet been harmonized to the contract (`shipped: bool` + `source`, no `.verdict`
enum / `.reason` — see `verdict.py` and the docs/86 §4 step-1 harmonization). So
it is deliberately NOT seed-registered here; it would fail gate (4) today. That
absence is the honest marker of the remaining drift, not an oversight.

This module is a CONSUMER, on the same side of the layering line as `cli.py` /
`dos_mcp`: nothing under `src/dos/*.py` that is a *verb* imports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import verdict as _verdict


@dataclass(frozen=True)
class VerdictSpec:
    """One registered distrust verb.

      name      — the CLI/MCP verb token (e.g. "liveness", "scope"). Unique.
      classify  — the pure `verdict.Classifier`: `(evidence, policy=...) -> Verdict`.
      summary   — a one-line help string (the `dos <verb> --help` / MCP description).
      distrusts — the claim this verb refuses to take on faith, in one phrase
                  (gate (1) made explicit: "I'm making progress" / "the diff stayed
                  in its lane"). Documentation, and the audit's gate-(1) prompt.
      gather    — OPTIONAL boundary-I/O callable `(args, cfg) -> Evidence`
                  producing the `evidence` argument (the `git_delta`-mold reader).
                  The registry stores it so a CLI/MCP consumer can run `gather()`
                  then `classify()`; None means the consumer supplies evidence
                  itself (e.g. the benchmark sink, which builds evidence inline).

    The remaining fields are the CLI/MCP ADAPTER — everything a *generic* consumer
    (`verdict_cli.attach`) needs to build this verb's surface WITHOUT hard-wiring
    its name. They are what make the wiring modular: adding a verb is a
    `register(...)` with these filled in, and the dispatcher loop does the rest.
    All optional, so a spec used only as a library classifier (or by the bench)
    omits them.

      add_arguments — `(parser) -> None`: add this verb's flags to an argparse
                  subparser (delegates straight to argparse — a callable, not a
                  data-DSL, so we don't reinvent argument parsing). None = no
                  verb-specific flags beyond the shared `--workspace`/`--output`.
      policy_from — `(cfg) -> Policy`: build the verb's Policy from the resolved
                  `SubstrateConfig` (the `dos.toml [<name>]` seam). None = the
                  classifier's own default policy is used.
      exit_codes  — `{verdict.value: int}`: the process exit code per verdict
                  state (e.g. liveness ADVANCING→0/SPINNING→3/STALLED→4). Empty =
                  always exit 0 (the verdict is in stdout regardless).
      reviewed  — whether a human confirmed gates (1)–(3) (which no runtime check
                  can see). A registry audit flags `reviewed=False` entries.
    """

    name: str
    classify: "_verdict.Classifier"
    summary: str
    distrusts: str
    gather: Optional[Callable[..., Any]] = None
    add_arguments: Optional[Callable[[Any], None]] = None
    policy_from: Optional[Callable[[Any], Any]] = None
    exit_codes: dict = field(default_factory=dict)
    reviewed: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("a verdict spec needs a non-empty name")
        if not callable(self.classify):
            raise ValueError(f"verdict {self.name!r}: classify must be callable")


# The registry. Insertion-ordered so `names()` is stable for tests/help output.
_REGISTRY: dict[str, VerdictSpec] = {}


def register(spec: VerdictSpec, *, replace: bool = False) -> VerdictSpec:
    """Register a distrust verb. Raises on a duplicate name unless `replace`.

    The callable/name checks are in `VerdictSpec.__post_init__`. The verdict-shape
    gate (gate 4) is NOT run here — it needs a *produced* verdict, which `register`
    has no evidence to make; use `validate_sample()` with a representative verdict
    (every verb's test suite does — see `test_verdicts`). Keeping `register` cheap
    and total (no verdict construction) is what lets a third party register at
    import time without wiring up evidence first.
    """
    name = spec.name.strip()
    if name in _REGISTRY and not replace:
        raise ValueError(
            f"verdict {name!r} already registered (pass replace=True to override)"
        )
    _REGISTRY[name] = spec
    return spec


def validate_sample(spec: VerdictSpec, sample: Any) -> bool:
    """Gate (4): does a verdict this verb produced satisfy the typed contract?

    `sample` is a verdict the verb's `classify` returned on representative
    evidence. Returns True iff it `verdict.conforms` — a mechanical closed-enum
    `verdict` + a str `reason` + a JSON-shaped `to_dict`. A registry audit / a
    verb's own test calls this; it is the one gate a machine can enforce.
    """
    return _verdict.conforms(sample)


def get(name: str) -> VerdictSpec:
    """The spec for `name`. Raises KeyError if unregistered."""
    return _REGISTRY[name]


def names() -> list[str]:
    """Registered verb names, in registration order (stable)."""
    return list(_REGISTRY)


def all_specs() -> dict[str, VerdictSpec]:
    """A copy of the registry — for a consumer enumerating verbs (cli/mcp/audit)."""
    return dict(_REGISTRY)


def unreviewed() -> list[str]:
    """Verb names registered without a human gate-(1)–(3) sign-off (audit hook)."""
    return [n for n, s in _REGISTRY.items() if not s.reviewed]


# ---------------------------------------------------------------------------
# Seed registration — the two instances that prove the shape (docs/86 §4).
# Central (here), not self-registration in the verb modules, so liveness/scope
# stay pure and registry-unaware (the one-way arrow). `verify` is intentionally
# absent until ShipVerdict is harmonized to the contract (it fails gate 4 today).
# ---------------------------------------------------------------------------
from . import liveness as _liveness  # noqa: E402  (consumer import, after the API)
from . import scope as _scope        # noqa: E402

register(VerdictSpec(
    name="liveness",
    classify=_liveness.classify,
    summary="is the run advancing, or just spinning? (the temporal verdict)",
    distrusts="I'm making progress",
    reviewed=True,
))
register(VerdictSpec(
    name="scope",
    classify=_scope.classify,
    summary="did the diff stay inside the lane it claims? (the footprint verdict)",
    distrusts="the change I stamped as (plan, phase) stays in that phase's lane",
    reviewed=True,
))
