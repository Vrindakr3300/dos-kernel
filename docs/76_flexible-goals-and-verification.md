# Flexible goals & verification — where the give is, and where it can't be

> **Verification bends at the edges and is rigid at the center.**

[`HACKING.md`](HACKING.md) is the *how-to* — the four extension axes and how
plugins attach. This note is the *theory under it*: **where flexibility is
allowed to live when a DOS-based system defines a goal and verifies it, and
where it must never go.** If HACKING tells you *how* to declare a new reason or
stamp grammar, this tells you *why* that's the only safe place to put the give —
and what stays bolted down no matter what.

The thesis in one line: **the kernel is flexible about how it can be convinced;
the driver is flexible about what the goal is; neither may flex whether a given
claim, on given evidence, is true.** Those are three different questions, and the
whole substrate only holds together because they don't bleed into each other.

---

## 1. The load-bearing split: `verdict` vs `source`

Everything below follows from one struct. `dos.oracle.ShipVerdict`
(the return type of the `verify()` syscall) carries two things that are easy to
conflate and must not be:

```python
@dataclass
class ShipVerdict:
    shipped: bool          # THE VERDICT — closed, binary, non-negotiable
    source: str = ""       # "registry" | "grep" | "none" — WHICH authority answered
    sha: str | None = None
    summary: str = ""
```

`shipped` is the *judgment*. `source` is the *provenance of the judgment*. The
flexibility in the entire verify path lives on the right of that split:
`verify()` can reach the *same* closed verdict from a run registry, from a
git-log grep, or it can decline to claim a ship at all (`source="none"`). Three
evidentiary paths, one rigid verdict vocabulary.

This is the pattern, stated generally:

> **Flexibility lives in *which authority answered* and *what its evidence looks
> like*. Rigidity lives in *the verdict vocabulary* and *the rule that maps
> evidence to verdict*.**

Read the rest of this doc as four corollaries of that sentence.

---

## 2. Kernel-side flexibility: a *rung ladder*, not a *threshold knob*

The deterministic kernel flexes in exactly one shape: it **degrades through
ordered rungs of decreasing authority, and reports which rung had to answer.**

`oracle.is_shipped()` tries registry-first → grep-fallback → `none`. The no-plan
contract (pinned by `tests/test_verify_no_plan.py`) is precisely this ladder
proving its bottom: strip away the run registry *and* the plan doc, point
`verify()` at a bare git repo, and it still answers — from history alone — and is
**honest about how thin the evidence was** (`source="grep"`, or `"none"` when
even that finds nothing).

This is a real and *bounded* kind of flexibility:

- It is flexible about **how much scaffolding exists.** Full plan registry, or a
  plain git repo with no `docs/*-plan.md` at all — same syscall, graceful
  degradation, no special-casing at the call site.
- It is **not** flexible about the **adjudication rule.** Ancestry is still
  checked. A self-reported "I shipped it" never becomes truth. `source` always
  names the *weakest* authority that had to be consulted, so a thin answer can't
  masquerade as a strong one.

The admission kernel (`arbiter.arbitrate()`) shows the same move in a different
domain. Its `LaneDecision.outcome` is a closed set (`'acquire' | 'refuse'`), and
the *soft* part — whether two file-trees overlap enough to block — is delegated
to `lane_overlap.overlap_verdict(...).admissible`, a **ratio-only, pure**
predicate (admit when ≤30 % of the requested tree shares prefixes with a live
lease). Crucially the arbiter also knows how to **abstain**: where the pick
oracle is blind (it can't see a named lane's file-glob tree), an abstain is
modeled as a *typed* outcome (skip / admit-on-empty), not a soft "maybe." The
kernel flexes by **widening its output to include honest uncertainty**, never by
blurring the certain outcomes.

> **Kernel give:** more rungs, more evidentiary paths, an explicit
> abstain/`none`.
> **Kernel rigidity:** the verdict vocabulary is closed, and the
> evidence→verdict rule is a pure function.

The anti-pattern this rules out: a `confidence: float` on the verdict, or a
tunable "how sure is sure" threshold *inside the kernel*. The moment "shipped"
becomes "80 % shipped," the kernel stops being the part that doesn't believe the
agents.

---

## 3. Driver-side flexibility: *parameterize the recognizer, as data*

`src/dos/stamp.py` is the cleanest example in the repo of driver-side
flexibility, and it exists because of a real bug. The grep rung used to hardcode
the **reference app's** commit-subject grammar (`docs/<SERIES>:`). Point `verify()`
at any other repo and a perfectly-shipped phase resolved to
`NOT_SHIPPED (via none)` — the kernel literally could not *see* the evidence,
because it only knew one dialect of "ship stamp."

The fix was **not** to make the verdict fuzzy. It was to lift *the grammar of
what evidence looks like* out of the kernel into a `StampConvention` the host
**declares as data** (and `dos.toml [stamp]` reads back):

```
JOB_STAMP_CONVENTION      — subject_dirs = (docs, go, agents, job_search, scripts)
GENERIC_STAMP_CONVENTION  — no dir prefix; a bare "<SERIES>: <PHASE>" / "<SERIES><PHASE>"
```

A `StampConvention` carries **no regex** — it carries the *data* (which dir
prefixes, which summary-subject prefixes count) that `phase_shipped` interpolates
into the patterns *it* compiles and runs. So the driver gets to declare *what a
ship commit looks like in this workspace's dialect*. It does **not** get to
change *whether* a matching commit, once recognized, counts as shipped — that's
still the kernel's ancestry-checked judgment, identical across every host.

> **The line:** a driver tunes the *recognizer's vocabulary*; the kernel owns
> the *judgment*. Declaring a new dialect widens what the kernel can see; it
> never softens what the kernel concludes.

### The goal itself is policy, too — and it's still a predicate

The stable-release gate (`scripts/stable_release_context.py`, the
`/stable-release` skill) is the same move one layer up, on the *definition of the
goal* rather than the recognizer. The reference app's stable gate read apply-loop
hero metrics — meaningless in DOS. So the gate was re-grounded entirely as
driver-side data + a thin script:

| Gate row | Source | Pass condition |
|---|---|---|
| `pytest_suite_green` | `python -m pytest -q` | exit 0 |
| `dos_verify_clean` | `dos verify` (sentinel probe) | well-formed verdict dict + exit ∈ {0,1} |
| `tag_age` | candidate tag's committer date | age ≥ `window_days` |

*Which signals constitute "known-good" was fully redefinable* — that's policy,
and policy is a driver's to own. What could **not** be done, and deliberately
wasn't: make any single row pass on a fuzzy reading. Each row stays a hard
boolean with a *named source*. The flexibility was in *which* booleans, sourced
from *what* — not in softening any one of them.

Two details make this principled rather than just disciplined:

- **`dos_verify_clean` passes on exit 1.** The truth syscall's exit code carries
  the *ship verdict* (0 shipped / 1 not), not execution health. A healthy syscall
  on a no-plan repo returns `shipped=false, source="none"` → exit 1. The gate
  treats *a well-formed verdict dict + exit ∈ {0,1}* as the pass and reserves
  failure for a crash. This is the `verdict`-vs-`source` split (§1) showing up in
  a gate: the gate verifies *the syscall ran and adjudicated*, not *that the
  probe happened to ship*.
- **`--force-promote` does not lower the gate.** It records a written rationale
  for *overriding* a red row into the evidence file. The override is logged as a
  visible exception, never absorbed as a tolerance. Threshold-creep ("tune the
  window" sliding into "tune what counts as a pass") stays *auditable* because
  every pass is a boolean + a source, and every override leaves a paper trail.

> **Driver give:** redefine *which* signals are the goal, and *what evidence
> looks like* for each.
> **Driver rigidity:** the goal must be expressed as a *checkable predicate* the
> kernel (or a deterministic script) evaluates the same way every time.

---

## 4. The geometry: flexibility moves *up*, determinism stays *down*

There's a clean directional rule, and it matches the layering contract in
`CLAUDE.md`: **push each kind of flexibility to the highest layer that can own
it, and keep the bottom layer a pure, deterministic adjudicator.**

| Question | Decided by | Flexibility | Where it lives |
|---|---|---|---|
| *What does "shipped" / "admitted" mean?* | **Kernel** | none — closed verdict vocab | `ShipVerdict.shipped`, `LaneDecision.outcome` |
| *Which authorities may answer, in what order?* | **Kernel** | rung ladder + abstain | `source` ladder; no-plan fallback |
| *What does evidence look like here?* | **Seam (data)** | declared per workspace | `StampConvention`, `ReasonRegistry`, lane taxonomy |
| *Which signals constitute the goal?* | **Driver (policy)** | fully redefinable | stable-gate rows; `baselines`-shaped data |
| *Is THIS claim true, on THIS evidence?* | **Kernel** | zero — pure function | ancestry check; `overlap_verdict` ratio |

The invariant: a goal can be redefined freely **as long as the redefinition
lands as data or a predicate** — never as a patch to the judgment. This is why
`self-modification` is a flagged hazard (see the memory and `docs/73`): the one
move the architecture forbids is a driver reaching *down* to soften the kernel's
verdict logic. That isn't extensibility — that's the agent editing the part
that's supposed to not believe it.

It's also why openness and verifiability aren't in tension here (HACKING's
`--check` invariant is the enforcement arm of this geometry): because every
flexible thing is *declared data*, a completeness rail can prove the open
vocabulary is still fully defined. You can add any reason, dialect, or gate
signal you like; `--check` / `dos doctor` guarantees nothing you *use* goes
undefined.

---

## 5. Where this is still leaky (named honestly)

A reflection that only lists the clean parts is propaganda. The cracks:

- **The grep rung is not yet fully generic.** `stamp.py` *extracted* the grammar,
  but the readback wiring isn't proven end-to-end for arbitrary hosts, and
  `dos.toml [lanes]`/`[paths]` are scaffolded-but-dead today (the WCR plan,
  `docs/71`). So the *mechanism* for driver-side dialect flexibility exists, but a
  few goals still leak their host dialect into the kernel. That's an unfinished
  extraction (the SCV/WCR/RND/ADM series, `docs/70`–`73`), not a design flaw.
- **`source="none"` is overloaded.** It means both "no evidence found" and
  "checked, genuinely not shipped." Honest, but a consumer who needs to tell *"I
  couldn't check"* apart from *"I checked and the answer is no"* has to work for
  it. A richer abstain in the *verify* domain — the way the arbiter already
  distinguishes refuse from abstain — is a candidate next degree of principled
  flexibility.
- **Flexible goals invite threshold-creep.** `--window-days` is legitimately
  tunable; the slope is from "tune the window" to "tune what counts as a pass."
  The guard is structural, not willpower: every gate row is a boolean with a
  named source, and overrides are logged rationales — so creep is at least
  *visible* in the evidence trail rather than silent.

---

## See also

- [`HACKING.md`](HACKING.md) — the how-to: the four extension axes + the
  `--check` completeness rail.
- `docs/70_stamp-convention-plan.md` — the SCV plan that turned the grep rung's
  subject grammar into `StampConvention` data.
- `docs/71_workspace-config-readback-plan.md` — WCR: making `[lanes]`/`[paths]`
  actually read back (closes the §5 leak).
- `docs/73_admission-predicate-plan.md` — ADM: admission policy as a declared
  predicate (the arbiter analogue of the stamp seam).
- `CLAUDE.md` — the layering contract this geometry instantiates (kernel / seam /
  helpers / drivers, and the rule that release tooling sits *outside* all four).
