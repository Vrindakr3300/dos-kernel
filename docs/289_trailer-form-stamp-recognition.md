# 289 — trailer-form ship stamps: `verify` learns the Conventional-Commits tail

> Status: SHIPPED (2026-06-10). Routed from a live self-audit on this repo: the
> kernel's own recent commits are invisible to its own truth syscall. Phase 1 is
> the kernel feature; Phase 2 declares it in this repo's `dos.toml` and confirms
> the flip live. See the **Verification checklist** at the bottom.

## TL;DR

Every rung of the ship-stamp grammar anchors the `<SERIES>:?\s+<PHASE>` token at
**subject start** (`stamp.StampConvention.direct_ship_core`, compiled in
`phase_shipped._check_phase_with_cache` as `^<sha>\s+<core>`). This repo moved to
Conventional-Commits subjects — `feat(pypi): … (docs/286 Phase 3)` — which carry
the plan/phase as a parenthesized **trailer at the end**. No spelling of the
`(plan, phase)` query matches a start-anchored grammar against that shape, so:

```
$ dos verify --workspace . docs/286_shipping-the-go-binary-through-pypi-per-platform-wheels "Phase 3"
NOT_SHIPPED … (via none)        # commit 9de9bb0's subject literally ends "(docs/286 Phase 3)"
$ dos doctor --workspace .
verifiability        none of your last 50 commits name a unit of work …
```

Old-style subjects (`liveness: exclude the lease's BIRTH acquire …`) still verify
via the glued `<PHASE>:` form, so the CLAUDE.md dogfood example works while every
recent `docs/28x` phase resolves `via none`. And `cli._verifiability_headline`
itself calls Conventional Commits "the majority" — the same gap blocks
verify-from-history on most external repos.

**Fix: a per-convention opt-in, `[stamp] trailer_stamp = true`,** under which a
subject whose **tail** is `(<PLAN> <PHASE>)` — also `(<PLAN>: <PHASE>)` and
`(refs <PLAN> <PHASE>)` — counts as a direct ship of that `(plan, phase)`. The
flag is data on `StampConvention`; the regex stays in the fragment builders;
the matcher in `phase_shipped` interpolates, same as every other rung.

## Why a trailer rung is sound (and where it must stay tight)

The trailer is exactly as forgeable as the start-anchored subject — whoever wrote
the message authored it — so the rung grades as `grep-subject` (the forgeable
grade, `oracle._grade_grep_source`), identical to the direct rung it mirrors.
What changes is only **where in the subject** the stamp may sit. The tightness
budget that the start anchor used to provide must come from elsewhere:

1. **End anchor + required parens.** The group must close the subject:
   `\(…\)\s*$`. A subject that merely NAMES an id in prose mid-subject
   (`fix the docs/286 Phase 3 leak in CI`) does not match; neither does a
   mid-subject parenthesized mention (`fix the (docs/286 Phase 3) leak`).
2. **The close paren is the phase boundary.** `(docs/286 Phase 30)` cannot match
   a `Phase 3` query — the phase token must abut `)`. No `_BOUNDARY_NEG` needed;
   the paren is stricter.
3. **Progress markers cannot ride a trailer.** `(docs/286 Phase 3 audit)` simply
   fails the adjacency — a progress-marked trailer is *not a ship*, fail-closed.
   (The direct rung demotes via `progress_marker_set`; the trailer rung never
   matches the shape at all.)
4. **Bookkeeping still excludes.** The same post-match guard as Pass 1a: a
   subject matching `bookkeeping_subject_re()` (declared prefixes + the universal
   `… snapshot:` and `archive <run-id>` guards) never ships, trailer or not.
5. **Release/bundle subjects stay on the weak rung.** The trailer pass SKIPS a
   subject matching `summary_subject_re()` (`vX.Y.Z:` + declared bundle
   prefixes); such a line falls through to the release-prefix rung with its
   existing footprint guards (`_grep_verdict_is_release_bump_falsepos`). A
   version-cut that happens to end in a phase trailer must not be promoted to a
   direct ship.

## The plan-id bridge: `docs/286_<slug>` ↔ `docs/286`

The query names the full plan id (`docs/286_shipping-the-go-binary-through-…`);
the trailer names its short series head (`docs/286`). The bridge is the
underscore convention of plan-doc basenames: when the queried series is
`<head>_<slug>` with `<head>` ending in a digit run, the trailer alternation
tries **both** the full id and `<head>`. Pure derivation, lives beside
`_phase_variants` in `phase_shipped` (`_series_variants`); a series with no
`\d+_` head gets no extra variant. The convention's `direct_prefix_re()` is
admitted (optionally) before the series so `(docs/286 …)` matches a dir'd
convention querying bare `286`, and vice versa.

## What changes where (the same seam discipline as SCV)

| Layer | Change |
|---|---|
| `dos.stamp` (seam data) | `StampConvention.trailer_stamp: bool = False` (data, not a regex); `trailer_ship_core(series_alt, phase_alt)` fragment builder (returns `None` when off); `to_dict`/`from_dict` carry the flag (the `DISPATCH_STAMP_CONVENTION` subprocess hand-off — an old payload defaults `False`); `convention_from_table` accepts the key (bool, validated, mirrors `sub_phase_parent_fallback`); `recognizes_direct_ship` grows the trailer probe (so the verifiability headline / 3c coverage rail count what verify would actually catch); `ship_shaped_under_generic` probes with trailer ON — its contract is "would SOME convention recognize this?", and a trailer-stamped CC repo now gets the actionable "0 of N ship-shaped match the active grammar — reconcile [stamp]" instead of the dead-end "none name a unit of work". |
| `dos.phase_shipped` (matcher) | `_series_variants` (the underscore-head bridge); Pass 1a′ in `_check_phase_with_cache`: after the direct pass (direct still wins), before the release-prefix pass; compiles `^<sha>\s+.*<trailer_core>` once per pair, applies guards 4–5, returns `via: "trailer"`. The body scan, file-path backstop, and every other rung are untouched. |
| `dos.cli` (doctor) | `_describe_stamp` appends `+ trailer` to the grammar label (flows into the headline, `--json` `verifiability.grammar`, and the doctor row); the `dos init` scaffold gains the commented key. |
| `dos.toml` (this repo, Phase 2) | `[stamp] trailer_stamp = true`. |
| `docs/HACKING.md` | the `[stamp]` walkthrough gains the key. |

Non-goals, deliberately: no `Phase 3` ↔ `P3` synonym minting beyond what
`_phase_variants` already does (a `(docs/286 P3)` trailer does not satisfy a
`Phase 3` query — declare the convention you actually write); no multi-ref
trailers (`(docs/286 Phase 3, docs/289 P1)` — only the final, end-anchored group
counts); no trailing punctuation after the paren; trailers in commit BODIES stay
unread (the body scan is a release-bundle rung, not a trailer rung).

**Rejected alternative** (the no-code fallback): convention discipline — phase
closeout commits start with the recognized shape (`docs/289: P1 — …`). Cheaper,
but it fixes only this repo going forward; the trailer flag retro-recognizes the
existing history AND gives external CC-majority repos verify-from-history for a
one-line declaration. The flag is the higher-value path; the discipline still
holds for summary lines that want the strong start anchor.

## Verification checklist

- [x] `tests/test_stamp_trailer.py` — the matrix: ships via trailer (full id and
  short head, all three spellings); opt-in off → `via none`; mid-subject /
  prose / progress-marked / `Phase 30` / bookkeeping / snapshot / release
  subjects all refuse; `convention_from_table` + dict round-trip; probe +
  breadth-predicate coverage; doctor headline + `--json` on a real tmp repo.
- [x] Full kernel suite stays green (the JOB + GENERIC defaults are
  byte-unchanged — flag defaults `False` everywhere).
- [x] Phase 2, live on this repo: `dos verify --workspace .
  docs/286_shipping-the-go-binary-through-pypi-per-platform-wheels "Phase 3"` →
  `SHIPPED 9de9bb0 (via grep-subject)`; `dos doctor` verifiability count
  nonzero with grammar `generic (any/no dir prefix) + trailer`.
- [x] Dogfood closure: this plan's own closeout commits stamp `(docs/289
  Phase N)` trailers — the feature verifies its own shipping commit.
