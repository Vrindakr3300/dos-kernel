# The dynamic "Verified by DOS" badge — a live verdict, not an adoption claim

> **The static badge shipped (`docs/assets/verified-by-dos.svg` + `docs/BADGE.md`)
> asserts *adoption* — "this repo wires `dos verify` into its gate" — and shows the
> same green whether the last `verify` answered `SHIPPED` or `NOT_SHIPPED`. The
> *dynamic* badge is the live, per-commit version: its colour and message come from
> an actual `dos verify` verdict over a target repo's git. This note specifies it,
> and the whole risk is that a badge over an UNTRUSTED repo's own claim becomes the
> very self-report DOS exists to distrust — the `103` disease wearing an adoption
> hat. The discipline that forecloses it is the kernel's usual line: the CLI MINTS a
> three-state endpoint payload (`{schemaVersion,label,message,color}`) from a
> verdict it computes over git ancestry at a boundary — it never reads the repo's
> claim, never hosts a service, never renders a colour for a state it did not
> adjudicate. The badge reflects a verdict a *trusted runner* computed, not a number
> a repo POSTed. And the load-bearing honesty rule is three-state, not binary:
> `grep`/`registry`-backed ship → green, `via none` → NEUTRAL (never red — never
> false-accuse a repo that simply does not use DOS ship grammar), `NOT_SHIPPED`
> with real evidence → red. The kernel imports no host, no badge service, and no
> shields client; Phase 1 is a pure local output mode that prints JSON, and the
> hosting question is gated behind it (and behind PyPI publish), never folded into
> the kernel.**

A spec note in the family of [`82_liveness`](82_liveness-oracle-plan.md) (the
verdict-IS-the-exit-code shape this output mode mirrors), [`99`](99_runtime-validation-and-the-actuation-boundary.md)
(the advisory-only actuation boundary — the badge *reports*, it never gates anyone's
CI for them), [`103`](103_memory-is-an-unverified-agent.md) (a self-report re-verified
against ground truth at read time — the exact move a dynamic badge must make over a
repo's claim), [`104`](104_externalizing-the-house-style-verdict.md) (the
external-evidence discipline: a verdict computed with the same pen that wrote the
claim proves nothing), and [`108`](108_the-cheap-lie-and-the-narration-taxonomy.md)
(the cheap "all work completed" line a binary always-accusing badge would mirror).
Its non-engineering twin lives one repo out: `dos-strategy/dispatch-os-iconicity.md`
move #7 ("`dos-verify` GitHub Action — constitutionally three-state … Gated AFTER
PyPI") and the §4 **kill-list** that bars a binary, always-accusing Action. This note
is the *mechanism*; that doc is the *positioning*.

**Status: Phase 0 (the repo-self gate + worn badge) SHIPPED 2026-06-10; Phases 1–3
NOT YET BUILT.** The static badge (`docs/BADGE.md`, `docs/assets/verified-by-dos.svg`)
is shipped, and as of Phase 0 this repo itself wears a LIVE badge: the README's
"verified by DOS" mark is the status of `.github/workflows/dos-gate.yml`, which runs
the repo's own `verify-action` (`dos commit-audit` over each pushed commit +
`dos verify` of this phase's own trailer stamp) — the §4 trust posture 2 ("the runner
is the repo's own CI, the evidence is its own git"), rendered through GitHub's native
workflow badge rather than the shields endpoint JSON. No `dos badge` verb, no
`--shields-endpoint` mode, and no badge service exist in the tree today (a grep of
`src/dos/` for `shields`/`schemaVersion`/`endpoint` returns only the incidental word
"badge" in `_color_verdict_line`'s comment, `cli.py:367`) — the three-state endpoint
renderer remains Phase 1.

---

## 1. Problem (one line)

The shipped badge asserts *adoption* (a fixed green pill), not a *verdict*; a live,
per-commit badge that reflects a target repo's REAL latest `dos verify` result needs
(a) a machine-readable output contract the CLI can emit and (b) a trust model for a
dynamic endpoint that keeps the badge from degrading into the repo's own self-report.

## 2. Goal

A `dos badge` / `dos verify --shields-endpoint` output mode that prints
[shields.io endpoint JSON](https://shields.io/badges/endpoint-badge)
(`{schemaVersion, label, message, color}`) for a `(plan, phase)`, encoding a
**three-state honesty rule** so the badge is green only on real evidence, neutral on
"this repo doesn't use DOS grammar," and red only on an evidenced `NOT_SHIPPED` — plus
the hosting/trust model for the dynamic case, built smallest-first so Phase 1 ships
locally with no service and no new trust surface at all.

---

## 3. The model — the badge is a renderer of the verdict, gated by the three-state rule

A shields **endpoint badge** works by `?url=`-pointing shields.io at a JSON document
the badge author hosts; shields fetches it and paints the pill from its fields. The
document is exactly four fields DOS already has the inputs for:

```jsonc
{ "schemaVersion": 1, "label": "verified by DOS", "message": "SHIPPED AUTH1", "color": "..." }
```

The verdict is the `ShipVerdict` `dos verify` already mints (`src/dos/oracle.py:124`):
`shipped: bool`, `sha: str | None`, `source: str` (`"registry"` | `"grep"` | `"none"`),
and `to_dict()` at `oracle.py:145`. The badge is a **pure projection of that verdict**
— precisely the "renderer is pure presentation, downstream of the kernel, receives
nothing it could decide with" contract `render.py:17` states. So the badge belongs on
the existing renderer seam, not as a new decision path.

### 3.1 The three-state honesty rule (the load-bearing design)

The whole correctness of this feature is that **`shipped=False` is two different
worlds**, and a badge that paints them the same colour is the kill-list's "bot that
cried wolf" (`dispatch-os-iconicity.md` §4). The map from `ShipVerdict` to colour:

| Verdict | `shipped` | `source` | Badge state | Colour | Why |
|---|---|---|---|---|---|
| Evidenced ship | `True` | `grep` / `registry` | **green** | `#2ea44f` (the DOS ship green, same hex as `BADGE.md`) | a real artefact in git ancestry backs the phase |
| No DOS grammar | `False` | `none` | **NEUTRAL** | `lightgrey` / `inactive` | the repo simply does not use DOS ship-stamp grammar — **not** a caught lie. Painting this red would false-accuse the *majority* repo shape (Conventional-Commits, no phase ids) — about as credibility-destroying a first contact as a trust tool can make. |
| Evidenced not-shipped | `False` | `grep`/`registry` (a *registered* phase whose commit never landed) | **red** | `firebrick` | the phase is *known* to the repo's plan/registry yet git proves no ship — a real "dashboard said done, git proved nothing." |

This is the same green/red/neutral tri-state `_color_verdict_line` already encodes for
the TTY (`cli.py:362` — green for `grep`/`registry`, a bold-red `(via none)`), but with
**one deliberate divergence**: the TTY colours `via none` red because there it sits
beside a `NOT_SHIPPED` mark a human is reading in context; the *badge* sits alone on a
stranger's README with no context, so `via none` MUST be neutral. The divergence is the
whole point of a separate badge renderer rather than reusing the TTY colourizer — and
it is pinned by a test (§7).

> **The rung suffix `(via <rung>)` is the verdict's most-differentiated idea
> (`cli.py:321`). The badge's `message`/`color` are a faithful, lossless encoding of
> it: `message` carries the rung (e.g. `SHIPPED AUTH1 a1b2c3d` / `unverified`), so a
> reader who clicks through to the endpoint JSON sees the same evidence grade the CLI
> prints. The badge never *upgrades* the rung — a `via none` is neutral-`unverified`,
> never green.**

### 3.2 Where it lives — the renderer seam, not a new verb path

`dos badge PLAN PHASE` is `cmd_verify` (`cli.py:556`) with a fixed `--output
shields-endpoint` (or the spelled-out `dos verify --shields-endpoint PLAN PHASE`). The
endpoint JSON is produced by a **built-in `shields-endpoint` renderer** added to
`render.py` beside `text`/`json`, implementing `render_verdict(verdict) -> str`
(the required surface, `render.py:56`). It is selected through the existing
`_resolve_output_name` path (`cli.py:177`) and the `--output` argument (`cli.py:2885`),
so:

- the kernel adds **no new decision code** — the badge is `is_shipped(...)`'s verdict,
  rendered;
- the renderer receives only the already-decided `ShipVerdict` (the `render.py:17`
  purity invariant), so a buggy badge can never mis-verify a ship;
- the output is machine-form, so `_color_enabled` returns `False` (`cli.py:348`: an
  explicit `--output` is never ANSI-coloured) — the endpoint JSON is byte-clean for a
  consumer, exactly as `--json` is.

The three-state map lives in the renderer (presentation), reading only `verdict.shipped`
and `verdict.source` — never re-deciding anything. It is the `_color_verdict_line`
logic re-expressed for a no-context surface, kept in `render.py` because it is
pure-presentation, not in a driver.

---

## 4. The trust model — a badge over an untrusted repo must reflect a TRUSTED runner's verdict, not the repo's claim

This is the section the static badge's honesty note (`BADGE.md`) defers, and the reason
the dynamic badge is gated. A shields endpoint badge paints whatever JSON the `?url=`
points at. The hazard is structural:

**If the badge's endpoint JSON is written by the repo being judged, the badge IS the
self-report DOS distrusts.** A repo could host a hand-written
`{ "message": "SHIPPED", "color": "green" }` and wear the mark with zero verification —
the `103` disease (a frozen self-report recalled as fact) wearing an adoption hat, and
the `104` failure (a verdict computed with the same pen that wrote the claim). The badge
would certify nothing and would actively *launder* a lie behind DOS's name.

The resolution is the kernel's reflex, applied to the badge: **the colour must come from
a verdict a trusted party computed over git ancestry, not a value the repo asserted.**
Three trust postures, smallest blast-radius first — they map onto the three phases (§5):

1. **Local (Phase 1) — no trust surface at all.** `dos badge` runs on the operator's
   own machine over their own checkout and prints the endpoint JSON to stdout. There is
   no service, no third party, no remote claim. The "trusted runner" is the operator
   running the kernel. This is the floor that ships first precisely because it adds
   *nothing* to trust — it is `dos verify` with a JSON shape.

2. **CI-computed (Phase 2) — the runner is the repo's own CI, the evidence is its own
   git.** A GitHub Action runs `dos badge` *inside the repo's CI*, over the commit CI
   checked out, and writes the endpoint JSON to a published artifact (gh-pages /
   release asset / a gist the Action owns). The badge then reflects a verdict computed
   by a runner over **git ancestry the runner itself observed**, not a value a human
   typed. The repo can still *choose which phase* to badge (that is policy, theirs to
   set), but it cannot forge the *verdict* without forging git — which is the whole
   `verify` guarantee (`84` most-accountable-fossil). The trust boundary is honest:
   the badge says "a `dos verify` run in this repo's CI, over this commit, returned
   X" — a claim about *structure* (`102`), mechanically checkable by re-running.

3. **Hosted (Phase 3, optional, the trust-heavy one) — a third-party service that
   clones and verifies.** A `verified-by-dos.example` endpoint that, given
   `?repo=…&plan=…&phase=…`, clones the repo at its public default-branch HEAD, runs
   `dos verify` over **the git it just fetched**, and serves the resulting endpoint
   JSON. Here the trusted runner is the *service*, and the trust rests on the service
   computing the verdict from a fresh clone it fetched — never from anything the repo
   submitted. This is the only posture that introduces a real trust surface (who runs
   it, abuse/cost of arbitrary-repo clones, caching staleness), which is exactly why it
   is last and optional.

**Why gated AFTER PyPI publish.** Iconicity is downstream of an outsider successfully
running the kernel (`dispatch-os-iconicity.md` move #1 — "a 404 keeps N=1"). A badge a
stranger cannot `pip install dos-kernel` and reproduce locally is a screenshot of a tool
nobody can run; the badge's whole value is clone-and-rerun reproducibility, which
requires the package to resolve first-try. Phase 2/3 ship *after* `dos-kernel` is on
PyPI; Phase 1 (local JSON) can land now because it needs no distribution to be useful to
the operator who already has the repo.

**The kernel stays out of all three.** The endpoint JSON contract (Phase 1) is a pure
renderer in `render.py`. The Action (Phase 2) is YAML + a `dos` CLI call living under
`.github/`/`examples/`, never imported by `src/dos/`. The hosted service (Phase 3) is a
separate top-level package on the `dos_mcp` precedent (a *consumer* that `import dos`,
which nothing under `src/dos/` imports back) — not a kernel module. A grep of `src/dos/`
for an HTTP server, a clone call, or a badge host returns nothing, by construction.

---

## 5. Phases (throughline-first; each ships an ENABLED slice behind the old behaviour)

The throughline lands in Phase 1: a real, reproducible three-state badge a user can
wire into their own pipeline today, with no service to trust. Phases 2–3 widen *who runs
the verify*, never the verdict logic — the three-state rule is written once in Phase 1
and reused unchanged.

- **Phase 0 — the repo-self gate + worn badge (no new kernel surface).** ☑ SHIPPED
  2026-06-10, stamped `(docs/112 Phase 0)`. Before any endpoint JSON exists, the badge
  must first make sense *on this repo itself* — and after the fresh public seed it did
  not: the squashed history carried **no** ship-stamp `dos verify` could answer
  `SHIPPED` for, so any badge would have been either an unbacked adoption pill or a
  neutral `via none`. Phase 0 closes that: `.github/workflows/dos-gate.yml` runs the
  bundled `verify-action` on this repo itself (`install-from: "."` — the input that
  also makes the Action installable at all pre-PyPI), with two legs — `dos
  commit-audit` over each pushed commit (live teeth: an over-claiming subject reddens
  the badge) and `dos verify docs/112 "Phase 0"` over this phase's own trailer stamp,
  the first stamp in the public history (reddens if `dos.toml [stamp]` stops parsing
  the repo's own grammar or a rewrite drops the stamp from ancestry). The README wears
  the workflow's status badge — §4 trust posture 2 with GitHub's native badge as the
  renderer. **Deliberately repo-self-only:** the workflow badge is binary
  (passing/failing), which is honest *here* because both legs are constitutionally
  abstaining (`commit-audit` never blocks a no-claim subject) and the verified stamp is
  the repo's own declared grammar — never aim this binary form at a foreign repo
  (the §6 kill-list); the three-state endpoint renderer for that is Phase 1, unchanged.

- **Phase 1 — the `shields-endpoint` output mode (pure, local, no service).** ☐ NOT
  BUILT. Add a built-in `shields-endpoint` renderer to `render.py` (beside
  `text`/`json`) implementing `render_verdict` → the four-field shields document, with
  the §3.1 three-state map (`shipped+grep/registry`→green, `none`→neutral,
  `shipped=False+grep/registry`→red). Add `dos badge PLAN PHASE` as `cmd_verify` with
  `--output shields-endpoint` fixed (and accept `dos verify --shields-endpoint`). The
  default `dos verify` text/json output is **byte-unchanged** — the badge is a new
  `--output` selection, off unless asked, so no existing caller regresses (the
  RND byte-faithfulness contract, `render.py:24`). The verdict exit code is preserved
  (`_VERIFY_EXIT_CODES`, `cli.py:552`) so a CI step can still branch on it while also
  emitting the badge JSON. **Ships the whole throughline:** a user redirects
  `dos badge AUTH AUTH1 > badge.json`, hosts it anywhere, and `?url=`-points shields at
  it. No trust surface added.

- **Phase 2 — the `dos-verify` GitHub Action (move #7).** ☐ NOT BUILT. A composite
  Action (`examples/` or a published `dos-kernel/verify-action`, never under
  `src/dos/`) that `pip install dos-kernel`s, runs `dos badge` over the checked-out
  commit, and writes the endpoint JSON to a published artifact the repo's badge URL
  points at. **Constitutionally three-state** (the §4 kill-list constraint): on a
  `grep`/`registry` `NOT_SHIPPED` it may post a caught-lie PR comment; on `via none` it
  posts **no accusation** — it emits the neutral badge and (optionally) the `dos doctor`
  cold-open, never a red mark. Gated AFTER PyPI publish (the install line must resolve).
  Reuses Phase 1's renderer verbatim — the Action contributes *where* verify runs, not
  *how* the badge is coloured.

- **Phase 3 — the optional hosted endpoint (the trust-heavy one).** ☐ NOT BUILT,
  optional, may never ship. A separate consumer package (the `dos_mcp` precedent: under
  `src/` if shipped, `import dos`, never imported by the kernel) that, given a repo +
  plan + phase, clones at public HEAD, runs `dos verify` over the fresh clone, and serves
  the endpoint JSON — verdict from the git *it* fetched, never the repo's submission.
  This is the only phase that adds a real trust/abuse/cost surface (arbitrary-repo
  cloning, cache staleness, who pays/operates), so it is last, opt-in, and explicitly
  may be dropped in favour of Phase 2's CI-computed badge (which needs no central host).

---

## 6. The honesty discipline — tie to the iconicity kill-list

The badge is a *trust* artifact, so its failure mode (a false-green or a
false-accusation) is more damaging than its absence. Two kill-list rules
(`dispatch-os-iconicity.md` §4) are load-bearing constraints, not nice-to-haves:

1. **No binary, always-accusing badge.** On a Conventional-Commits repo with no phase
   ids, *every* phase is `NOT_SHIPPED (via none)`, byte-identical to a real caught lie.
   A badge that paints that red false-accuses the majority repo shape — "the kernel that
   doesn't believe agents" becomes "the bot that cried wolf." Only the **three-state**
   version (§3.1: `via none` → NEUTRAL, never red) survives. This is pinned by a test
   that a `source="none"` verdict yields a neutral colour and an `unverified`-class
   message, never red.
2. **No fabricated frame.** The badge must reflect a verdict over a REAL artifact, never
   a staged claim (§4: the runner computes from git, never from the repo's submission) —
   the same discipline that replaced the staged-demo move with `verify` over a real
   artifact.

The badge inherits `verify`'s scope honesty (`README.md` "What DOS does not do"): it
asserts a ship *happened* (a commit in ancestry backs the phase), **not** that the code
is correct or good. The label is "verified by DOS" — *verified-shipped*, the
deterministic oracle rung — not "approved" or "passing." The message must never imply a
quality judgment the oracle does not make.

---

## 7. Test obligations

- **Three-state map (the core).** Frozen-`ShipVerdict` fixtures →
  `shields-endpoint` render: `shipped=True, source="grep"` → green `#2ea44f`;
  `shipped=False, source="none"` → **neutral** (`lightgrey`/`inactive`), message
  `unverified`, **asserted not red** (the kill-list pin); `shipped=False,
  source="registry"` → red. One test per row.
- **Valid shields schema.** The rendered string is JSON parsing to exactly
  `{schemaVersion: 1, label, message, color}` — no extra/missing keys (shields rejects
  a malformed endpoint document).
- **Renderer purity / byte-faithfulness.** Default `dos verify` text/json output is
  byte-identical with the new renderer registered (the `render.py:24` /
  `tests/test_render.py` contract); the badge renderer receives only a decided
  `ShipVerdict` and no config (the `render.py:17` purity invariant).
- **Divergence from the TTY colourizer.** A `via none` verdict is **red** through
  `_color_verdict_line` (`cli.py:362`, the in-context TTY) but **neutral** through the
  `shields-endpoint` renderer (the no-context badge) — the two rules are deliberately
  different, and a test pins both so neither drifts onto the other.
- **Rung is lossless.** The badge `message` carries the same `source` rung the CLI
  prints (`grep`/`registry`/`none`), never upgrading `none` to a confirmed rung.
- **Exit code preserved.** `dos badge`/`dos verify --shields-endpoint` returns the same
  `_VERIFY_EXIT_CODES` (`cli.py:552`) as plain `verify`, so a CI step can branch on the
  verdict and emit the badge in one run.
- **No kernel trust surface.** Grep `src/dos/` for an HTTP server / clone / badge host /
  `shields` client → nothing (the Phase-2/3 hosting lives outside the kernel, the
  `dos_mcp` one-way-arrow litmus).

## 8. Boundary — DOS vs host, what stays a driver / consumer

| Concern | Where | Why |
|---|---|---|
| The endpoint JSON contract (the three-state map) | **kernel** — a built-in `shields-endpoint` renderer in `render.py` | pure presentation of a `ShipVerdict`; receives nothing it could decide with (`render.py:17`) |
| The verdict it renders | **kernel** — `oracle.is_shipped` (`cmd_verify`, `cli.py:556`) | unchanged; the badge adds no decision code |
| *Which* `(plan, phase)` a repo badges | **host policy** — the repo's `dos.toml` / Action inputs | a repo's own choice of what to advertise, not a kernel concern |
| The GitHub Action (Phase 2) | **consumer** — YAML + `dos` CLI under `.github/`/`examples/` | `import dos` / shells `dos`; never imported by `src/dos/` (the release-tooling / SKP one-way arrow) |
| The hosted endpoint (Phase 3) | **consumer** — a separate top-level package on the `dos_mcp` precedent | a server framework + clone I/O must not enter the near-stdlib kernel; `import dos`, nothing under `src/dos/` imports it |
| Hosting / trust / abuse-cost of a public endpoint | **out of kernel entirely** (Phase 3, optional) | the kernel computes verdicts; it does not run services |

**Non-goals.** The badge never gates the host's CI for them (it *reports*; the
`99`/advisory-only floor — a green badge does not block a merge, the repo's own
exit-code branch does). The kernel never hosts a service, never clones a foreign repo,
and never paints a colour for a state it did not adjudicate. The badge asserts
*verified-shipped*, never code correctness or quality.

## 9. See also

- [`docs/BADGE.md`](BADGE.md) — the shipped **static** badge + the honesty note that
  defers this dynamic plan; `docs/assets/verified-by-dos.svg` the static asset.
- [`src/dos/render.py`](../src/dos/render.py) — the renderer seam (`Renderer`/`BaseRenderer`,
  built-in `text`/`json`) the `shields-endpoint` renderer joins; the purity +
  byte-faithfulness invariants.
- [`src/dos/oracle.py`](../src/dos/oracle.py) (`ShipVerdict`, l.124; `to_dict`, l.145) —
  the verdict the badge projects, with `source ∈ {registry, grep, none}` as the
  three-state input.
- [`src/dos/cli.py`](../src/dos/cli.py) — `cmd_verify` (l.556), `_resolve_output_name`
  (l.177) + `--output` (l.2885) the badge mode rides, `_color_verdict_line`/`_color_enabled`
  (l.362/337) the TTY tri-state the badge deliberately diverges from, `_VERIFY_EXIT_CODES`
  (l.552).
- [`104_externalizing-the-house-style-verdict.md`](104_externalizing-the-house-style-verdict.md) /
  [`103_memory-is-an-unverified-agent.md`](103_memory-is-an-unverified-agent.md) — the
  external-evidence / re-verify-at-read-time disciplines that forbid a repo-authored
  badge value.
- [`108_the-cheap-lie-and-the-narration-taxonomy.md`](108_the-cheap-lie-and-the-narration-taxonomy.md) —
  the "all work completed" line a binary always-accusing badge would mirror.
- `dos-strategy/dispatch-os-iconicity.md` — move #7 (the three-state GitHub Action,
  gated after PyPI) + the §4 kill-list ("a binary, always-accusing GitHub Action … only
  the three-state version survives").
- [`examples/playbooks/cookbook-ci-integration.md`](../examples/playbooks/cookbook-ci-integration.md)
  Recipe 1 — the existing GitHub Actions ship-gate the Phase-2 Action extends.
