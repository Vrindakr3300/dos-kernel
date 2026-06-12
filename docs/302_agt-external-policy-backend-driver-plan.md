# 302 — `dos.drivers.agt_backend`: dos verdicts in AGT's OPA/Cedar seat

> Microsoft's Agent Governance Toolkit (AGT, `microsoft/agent-governance-toolkit`,
> MIT) gives its policy evaluator a pluggable backend seat: any object with a
> `name` property and an `evaluate(context) -> BackendDecision` method can sit
> beside its native YAML rules, exactly where its own OPA and Cedar backends sit
> (their ADR-0015). This plan ships a driver that puts a dos verdict in that
> seat. An AGT host then gets dos adjudication with one registration line —
> `evaluator.add_backend(DosBackend(workspace="."))` — and dos gets an adoption
> surface inside a governance stack enterprises already deploy. The dependency
> arrow points at us (the adapter speaks AGT's contract; AGT never imports
> dos-kernel), which is why the code lives here, as a layer-4 driver.

*Status: DESIGN — tracking issue
[#53](https://github.com/anthony-chaudhary/dos-kernel/issues/53). Follows
docs/135 (the AGT audit); this is the adoption-surface move, not one of the
docs/135 §2 kernel questions (TRANSFORM, IFC, identity pair — those stay where
they are).*

## 0. The two contracts, side by side

AGT's side (all in `agent-governance-python/agent-os/src/agent_os/policies/`
of their repo):

- `ExternalPolicyBackend` — a runtime-checkable Protocol: `name` property +
  `evaluate(context: dict) -> BackendDecision`. Runtime-checkable means
  conformance is structural; the adapter does not need to inherit anything.
- `BackendDecision` — a dataclass: `allowed / action / reason / backend /
  raw_result / evaluation_ms / error`, plus the high-assurance pair
  `proof_artefact` and `verification_pointers`, which the evaluator copies
  verbatim into the winning decision's `audit_entry`.
- Evaluator semantics (`evaluator.py`): YAML rules first; if none match,
  backends in registration order; **the first decision whose `error is None`
  binds**; a decision with `error` set is skipped; if every backend errors,
  the configured default applies (which can be allow).

dos's side (the two flagship syscalls, both already pure):

- `dos.arbiter.arbitrate(...) -> LaneDecision` — admission: may this actor
  touch this footprint now? `outcome` is `'acquire'` or `'refuse'` + a reason.
- `dos.oracle.is_shipped(...) -> ShipVerdict` — the ship oracle: did this
  claimed effect actually land in git? `shipped` bool + `sha` + a graded
  evidence `source`/`rung` (forgeable subject-grep vs non-forgeable
  file-path/registry).

## 1. The verdict mapping (the design core)

| dos outcome | `BackendDecision` | Effect in AGT's evaluator |
|---|---|---|
| REFUSE / refuted (typed reason) | `allowed=False, action="deny", reason="dos:<reason>"`, `error=None` | binds: deny |
| affirmative (admitted / verified shipped) | `allowed=True, action="allow"`, `error=None` | binds: allow |
| ABSTAIN (context under-specifies, or no signal) | `error="abstain: <why>"` | skipped; falls through |

Three rules carry the dos philosophy into the seat without flattening it:

- **Abstain maps to the skip channel.** AGT skips a backend whose decision
  carries `error`. That is the only honest place for fail-to-abstain — an
  advisor that says nothing false rather than guessing. A context that does not
  name anything dos can adjudicate (no footprint, no claim) abstains; it never
  free-rides an allow.
- **Anything dos wants to bind returns `error=None`.** The upstream asymmetry
  (a *failed* backend and an *abstaining* backend share the skip channel; there
  is no "failed AND bind deny") is AGT's contract gap, tracked upstream — the
  adapter works within current semantics and does not pretend otherwise.
- **Evidence rides the audit fields.** A shipped verdict's `sha` goes in
  `proof_artefact` (`git:<sha>`); `verification_pointers` carries
  `{"source": <graded source>, "rung": <raw rung>, "plan": ..., "phase": ...}`
  so an audit consumer can re-check the decision offline instead of trusting
  the backend's say-so. This is exactly what AGT added those fields for.

## 2. The seat occupants

`DosBackend(workspace=".", seat="verify")` — one class, two seats, chosen at
construction (not guessed per call):

- **`seat="verify"`** (default): the context names an effect claim via the
  dos-namespaced keys `dos_plan` + `dos_phase`. Shipped → allow (+ evidence
  fields); not shipped → deny (`dos:unverified-claim` — the oracle looked at
  git and found nothing; that is a definite negative, not an abstain); keys
  absent → abstain.
- **`seat="arbitrate"`**: the context names a footprint via `dos_tree` (list of
  repo-relative path prefixes; falls back to a single `path` key). `'acquire'`
  → allow; `'refuse'` → deny with the arbiter's reason; no footprint → abstain.

Both adjudications are pure kernel calls; the driver does the boundary I/O
(reading live leases / oracle state under the workspace root) the same way the
CLI boundary does. Reasons pass through namespaced (`dos:<reason>`) so AGT-side
audit queries can filter dos denials.

## Phase 1 — the adapter + contract tests (the end-to-end slice)

- `src/dos/drivers/agt_backend.py` — `DosBackend` as above. AGT import posture
  follows `notify_slack.py`: the driver imports **nothing** from `agent_os` at
  module load. `BackendDecision` is duck-typed — try the real
  `agent_os.policies.backends.BackendDecision` lazily inside `evaluate`; absent
  → a local structurally-equal dataclass (the evaluator only reads fields, it
  never isinstance-checks). So the kernel dependency set is untouched and
  importing the driver never fails for lack of the extra. The one loud path
  (the silent-cliff rule, docs/229-family): constructing `DosBackend` with
  `require_agt=True` raises with an install hint when `agent_os` is absent —
  for hosts that want the missing-dep case to be an error, not a skipped seat.
- `tests/test_agt_backend.py` — the three-row mapping for both seats (kernel
  calls faked at the driver's seam); evidence-field passthrough; the
  `name == "dos"` property; abstain-on-underspecified-context; the duck-typed
  decision carries exactly the field names AGT's evaluator reads.

Done when: `python -m pytest -q tests/test_agt_backend.py` is green with no
`agent_os` installed.

## Phase 2 — verification against the real published package

Not the clone, not a vendored copy: `pip install agent-governance-toolkit`,
then an integration slice in the same test file, skip-marked when the package
is absent:

- `isinstance(DosBackend(...), ExternalPolicyBackend)` is True (their
  runtime-checkable Protocol, our structural conformance).
- A real `PolicyEvaluator` with no matching YAML rule + a registered
  `DosBackend`: deny binds, allow binds, abstain falls through to the next
  backend / default — observed through their evaluator, not ours.
- `proof_artefact` / `verification_pointers` arrive in the winning
  `PolicyDecision.audit_entry` verbatim.

Done when: the integration tests pass against the installed package version,
and the skip marker names the exact install command.

## Phase 3 — surface + release

- README/FAQ: one entry in the integrations row (the cookbook genre — "AGT
  host? one registration line"), pointing at the driver docstring.
- `/release` so the driver is pip-installable (`pip install dos-kernel` carries
  drivers; no new extra is *required* — `agent-governance-toolkit` stays the
  host's dependency, optionally named as an `[agt]` extra for the integration
  tests).

Done when: the release tag carries the driver and the upstream follow-ons can
point at a pip-installable version.

## Out of scope (deliberately)

- **The upstream error-skip issue** — filed on
  `microsoft/agent-governance-toolkit` as an issue/discussion first (it changes
  documented ADR-0015 semantics); a PR only after maintainer signal.
- **The upstream `examples/dos-governed` example + ADOPTERS.md entry** — after
  Phase 3 ships, so the example pins a published version.
- **Kernel changes of any kind** — this is a layer-4 driver; the docs/135 §2
  kernel questions stay in their own plans.
