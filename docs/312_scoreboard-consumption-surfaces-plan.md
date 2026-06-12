# 312 — scoreboard consumption surfaces: the opt-in badge + the per-repo `verdict.json`

> The drift scoreboard (docs/307, issue #66) computes a verdict nobody else
> computes: whether a commit's claim is witnessed by bytes the claimant did
> not author. This plan ships the two surfaces that let OTHER parties consume
> that verdict per repo — each copied from a proven distribution mechanic.
> **The badge** (the Snyk-Advisor / OpenSSF-Scorecard move): a
> shields.io-compatible endpoint JSON a repo embeds in its own README, so
> every graded repo becomes a distributor of the scoreboard. **The machine
> endpoint** (the context7 / Tessl-registry move): a versioned per-repo
> `verdict.json` an agent can fetch before believing a dependency's
> agent-written changelog. Plus the growth flow both exemplars share:
> **registration** — the opt-in tier grows by submission. Issue #85 is the
> tracking handle. The companion plan `docs/311` (issue #84, the standing
> per-repo index) owns the human-readable page half; this plan owns the
> machine half, and the two state the SAME verdict — docs/311's opt-in tier
> explicitly waits on this plan's `verdict.json` shape.

*Status: P1–P3 ship with this plan. We are repo #1 — the worked example is
this repository grading itself; no other repo is named by anything here.*

## 0. The facts the design rests on

- **No new verdict, no kernel surface.** Both artifacts are pure projections
  of verdicts that already exist: `dos.commit_audit.sweep_summary` (the
  per-repo fold) as written by `dos commit-audit --sweep --json` or by
  `scripts/drift_scoreboard.py` into `<out>/per-repo/`. The emitters are dev
  tooling under `scripts/` — they `import` nothing from the kernel beyond
  what the JSON already carries; nothing under `src/dos/` knows they exist
  (the same one-way arrow as `drift_scoreboard.py` itself).
- **Opt-in is what lifts the aggregate-only floor.** docs/307's v1 rule
  stands: no repository is named without opt-in. A per-repo `verdict.json`
  names a repo and carries its offending SHAs — so one is PUBLISHED only for
  a repo that registered (P3), and registration must come from someone with
  write access to that repo. The self entry (P2) is opt-in by construction.
- **The badge is a description, never a grade of honesty (the Wall-3 line).**
  The message vocabulary is counts of witnessed/unwitnessed claims with an
  as-of date — "audited clean (as of …)" / "N unwitnessed of M (as of …)" —
  never honest/dishonest. The verdict it summarizes carries the receipts
  (the SHAs), so the badge is inspectable all the way down.
- **Methodology-first still holds.** Every artifact links the docs/307
  methodology page as its contract. The self-badge lands in the README in
  the same push that carries the methodology page; the badge's click-through
  is the methodology, so a reader meets the contract before the number.
- **Static files, canonical in-repo.** The artifacts are tracked files under
  `docs/scoreboard/<org>/<repo>/` — so `master` ancestry carries the
  ship-stamp, `raw.githubusercontent.com` serves them the moment they push
  (shields.io's `endpoint` badge accepts any URL serving the JSON), and the
  Pages site mirrors them at `/scoreboard/<org>/<repo>/` when #84 renders
  pages. An artifact can never include the commit that ships it — its
  `range.head_sha` states exactly what was audited.

## 1. The two schemas (canonical reference)

**`verdict.json` — schema id `dos-scoreboard-verdict/v1`.** The key roster is
the schema; any change to it bumps the version string. Pinned by
`tests/test_scoreboard_surfaces.py`.

| key | meaning |
|---|---|
| `schema` | `"dos-scoreboard-verdict/v1"` — the version contract |
| `repo` | `"<org>/<repo>"` — the graded repo (opt-in tier only) |
| `generated` | ISO date the sweep ran |
| `grader` | `{tool, version}` — what computed the verdict (`dos-kernel commit-audit --sweep`, the installed version) |
| `methodology` | URL of the docs/307 methodology page — the contract |
| `opt_in` | `true` — structural reminder that publication required registration |
| `range` | `{described, head_sha, commits_audited}` — what history was audited |
| `claims` | `{checkable, witnessed, unwitnessed, abstained, drift_rate}` — the fold |
| `by_kind` | the per-claim-kind grid (witnessed/unwitnessed/abstain per kind) |
| `receipts` | `{unwitnessed_shas}` — the actual offenders, so the number is inspectable |
| `advisory` | the fixed Wall-3 sentence: drift is a claim-vs-diff mismatch, never a correctness or malice grade |

**`badge.json` — the shields.io endpoint schema** (`schemaVersion: 1`,
`label`, `message`, `color`; the version field is shields' own contract).
Derived from `verdict.json` by a pure function — the badge can never say
something the verdict does not. Message/color mapping, closed:

| verdict state | message | color |
|---|---|---|
| `unwitnessed == 0`, `checkable > 0` | `audited clean (as of <date>)` | `brightgreen` |
| `unwitnessed > 0` | `<N> unwitnessed of <M> (as of <date>)` | `orange` |
| `checkable == 0` | `no checkable claims (as of <date>)` | `lightgrey` |

Embed form (the worked example, P2):
`https://img.shields.io/endpoint?url=<raw-or-pages URL of badge.json>`,
hyperlinked to the methodology page.

## P1 — the emitters (`scripts/scoreboard_surfaces.py`) + schema tests

1. `verdict_payload(...)` — pure: from a `sweep_summary` dict (or a
   `drift_scoreboard.py` per-repo dict, auto-detected by its `summary` key)
   plus the identity facts (`repo`, `generated`, grader version, methodology
   URL, range description, head SHA) to the v1 verdict object.
2. `badge_payload(verdict)` — pure: the closed mapping above, from the
   verdict object alone (single source; no second computation of the rate).
3. CLI: `python scripts/scoreboard_surfaces.py --summary <json> --repo
   <org>/<repo> --out docs/scoreboard/ [--range ... --head-sha ... --stamp ...]`
   → writes `<out>/<org>/<repo>/verdict.json` + `badge.json`. I/O at the
   boundary only; both payload builders stay pure.
4. Tests (`tests/test_scoreboard_surfaces.py`, script imported by path like
   `test_drift_scoreboard.py`): the v1 key roster (schema pin), the badge
   mapping's three rows, badge↔verdict consistency (the counts in the
   message are the verdict's counts), shields `schemaVersion: 1`, and the
   auto-detect of both input shapes.

Done-condition: suite green; both schemas pinned by test.

## P2 — the worked example: this repo grades itself

Run the self-sweep (`dos commit-audit --sweep --json` over the full visible
history), emit `docs/scoreboard/anthony-chaudhary/dos-kernel/verdict.json` +
`badge.json` with the P1 tool, and embed the badge in the README badge row
(via `docs/readme/00_front-door.md` + the README rebuild), linked to the
methodology page. Two rot-pins in `tests/test_scoreboard_surfaces.py`: the
tracked `badge.json` must equal `badge_payload(verdict.json)` (the badge
cannot drift from its verdict), and the README must reference the tracked
badge path (the embed cannot silently vanish). `docs/BADGE.md` (the static
"verified by DOS" adoption mark) gains a short section distinguishing the
two badges — the static mark says "this repo gates on `dos verify`"; the
audited endpoint badge says "this repo's commit claims were swept, here is
the count" — with the embed recipe.

Done-condition: both artifacts tracked; the README front door carries the
self-badge; the rot-pins are green.

## P3 — the registration flow (the context7 growth mechanic)

Document the opt-in tier on the docs/307 methodology page (a "register your
repo" section): who may register (someone with write access to the repo),
how (a `scoreboard-request` issue on this repo, from the template — the same
issue vocabulary docs/311's opt-in tier names), what happens (the sweep
runs; the requester sees the artifacts BEFORE they publish — docs/311's
right-of-reply rule, constitutive, not a courtesy; then they land under
`/scoreboard/<org>/<repo>/` and the repo embeds the badge), how to leave
(same path — delisting on request), and how to dispute (file the SHA;
re-adjudication; the grader version in every verdict says exactly what
fired). Add the issue template
(`.github/ISSUE_TEMPLATE/scoreboard-request.yml`) so registration is one
click. Refresh cadence stays #84's decision; until then re-sweeps are
operator-run on registration and on dispute.

Done-condition: the methodology page carries the registration section; the
issue template is in tree.

## Out of scope (stays on the open handles)

The standing index itself — scheduled CI re-sweeps, rendered per-repo HTML
pages, any curated non-opt-in tier — is #84. A `dos_scoreboard_lookup` MCP
tool over the endpoint (a thin fetch) waits until the endpoint has consumers.
Publishing any repo other than this one waits for a registration.
