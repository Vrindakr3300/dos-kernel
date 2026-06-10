# docs/200 — The schema-refresh: how DOS converts a CURABLE thrash without authoring the fix

> **The question (operator, 2026-06-06):** once the feasibility witness says a thrash
> is CURABLE — a path provably exists — *how can DOS help provide the critical schema
> data*, e.g. a structured mechanism that gets the model to refresh the schema itself?
> **The answer, and why it stays byte-clean:** DOS does not supply the schema. On a
> curable thrash the authoritative correction is **already in the environment's own
> error reply**; the agent diagnoses it and still does not act on it. DOS's job is to
> make that env-authored corrective UN-IGNORABLE — re-surface it as a structured
> forcing function — never to write the schema. The same one rule as [[docs/164]]:
> *replay/constrain un-forgeable bytes; never author-and-believe a correction.*

Status: **MEASURED $0 ceiling + a byte-clean mechanism + the general form.** Builds on
[[docs/198]] (the feasibility split — do this FIRST) and [[docs/164]] (the never-author
rule). Instruments: `benchmark/enterpriseops/schema_refresh.py` (the pure extractor +
the $0 corrective-presence ceiling), `benchmark/_feasibility.py` (the split primitive).
The live realization of the ceiling is the [[docs/199]] curable-slice A/B (`warn` /
`restart_seeded` arms).

---

## §1 — The pivot: the corrective is env-authored, so the mechanism can be too

The dominant prior error (docs/198 §0) was scoring conversion against INFEASIBLE tasks.
The feasibility witness fixes the *population*. This doc answers the next question — on
the population where conversion IS possible (CURABLE), what is the byte-clean lever?

The decisive observation is in the bytes. A CURABLE-tool error on EnterpriseOps is not
opaque; it is a **precise, env-authored correction**:

```
update_vacation_settings -> "start_time must be a valid epoch millisecond timestamp"
update_vacation_settings -> "Invalid Tool Arguments: ['responseBodyHtml: is required',
                              'restrictToContacts: is required', 'restrictToDomain: is required']"
create_draft             -> "message: expected type 'object', got 'string'"
add_new_user             -> "Invalid phone format provided: '+91-98101-00011'"
update_draft             -> "message.payload.body.size: expected type 'integer', got 'number'"
```

The agent (docs/198 §0) **already diagnoses the fix** from these and still fails — it
does not act on the environment's own correction. So the lever is not to TELL the model
the schema (DOS does not know it, and inventing it would be the author-and-believe
violation). The lever is to make the env's correction a **forcing function**: re-surface
the environment's verbatim requirement as a structured checklist the model must satisfy
before it may retry. **DOS authors only the framing; every corrective byte is the
environment's.** That is byte-clean by the same argument as `arg_provenance` /
`precursor_gate` / the rewind no-good note: the judged agent did not author the identity
of the corrective — the env did.

---

## §2 — Not every curable thrash is a SCHEMA thrash (the recursive discipline)

The category-error discipline of docs/198 applies one level down. A thrash on a CURABLE
tool can fail for reasons a schema-refresh **cannot** fix, and folding those into the
schema cell would re-commit the same over-claim. `schema_refresh.extract_corrective`
classifies the env corrective into a KIND:

| KIND | env grammar | the right lever | schema-refresh helps? |
|---|---|---|---|
| **SCHEMA** | `is required` / `expected type 'x' got 'y'` / `must be <format>` / Pydantic `value_error` | re-surface the field/type corrective | **YES** |
| **REFERENCE** | `not found` / `NOT_FOUND` / `does not exist` | a LOOKUP (re-fetch the entity id) | no — needs a different lever |
| **STATE** | `already has` / `already exists` / `conflict` | a RE-PLAN (the op is done/blocked) | no — needs a different lever |
| **OPAQUE** | an error with no actionable detail | early-halt (docs/198 §2) | no |

Measured on the recorded natural corpus (`schema_refresh.py`, the $0 ceiling over the
curable-thrash runs):

| | count | of curable thrashes |
|---|---|---|
| total curable-thrash runs | 17 | — |
| **SCHEMA-convertible** | **13** | **76%** ← the schema-refresh ceiling |
| REFERENCE (needs a lookup) | 1 | 6% |
| STATE (needs a re-plan) | 3 | 18% |
| OPAQUE (early-halt) | 0 | 0% |

So on this corpus, **76% of curable thrashes carried a SCHEMA corrective the agent
ignored** — the env literally stated the field/type to fix. That is the upper bound a
re-surface could convert; the remaining 24% are curable but need a *different* lever, and
saying so is the discipline (n is small here — the same underpowering docs/198 §3 flags
— so 76% is the *shape* of the ceiling, to be confirmed by the live A/B, not a settled
rate).

---

## §3 — The mechanism, in three forms (least-authored first)

`schema_refresh.refresh_directive(corrective, tool_name, has_introspection=…)` renders
the byte-clean re-prompt. Three forms, degrading gracefully by how much DOS authors —
the **less DOS authors, the safer**:

1. **Re-fetch (the general MCP case, 0% DOS authorship).** Where the environment exposes
   a schema-introspection tool (`tools/list` returns a JSON Schema per tool — the MCP
   norm), DOS routes the agent to **re-fetch the authoritative schema** for the failing
   tool and satisfy every required field before retrying. The schema source is 100%
   env-authored; DOS authors only "go re-read it." This is the cleanest form and the one
   that generalizes beyond any single benchmark.

2. **Re-surface (this gym, framing-only authorship).** This gym exposes **no**
   introspection tool, so the only env-authored schema source is the error reply itself.
   DOS re-surfaces the env's own `is required` / type / format corrective as a structured
   checklist ("the environment reported these fields missing; fill ALL of them; these are
   its verbatim reply, not advice"). DOS authors the *structure*; the constraints are the
   env's verbatim bytes.

3. **Fall through to early-halt (no authorship).** If the corrective is OPAQUE (no
   actionable detail) and there is no introspection tool, there is nothing env-authored
   to surface — the honest fallback is the docs/198 §2 give-up-correctly halt.

The directive **never mints a value**: it surfaces the env's field *name* and *constraint*
but never a candidate value for the field (that would be the author-and-believe
violation). Pinned by `test_schema_refresh.py::test_directive_surfaces_env_corrective_not_a_dos_invention`.

---

## §4 — Why this is the same shape as everything else DOS does

The schema-refresh is not a new trust posture; it is the existing one aimed at a new
moment:

- **Evidence over narrative.** The corrective is the env's verdict on the agent's args,
  not the agent's narration about what it will fix.
- **Author ≠ judged (the docs/138 invariant).** The agent did not author the identity of
  the correction; the environment did. So re-surfacing it is grounding, not the
  consistency-trap of re-deriving the author's own bytes ([[project-dos-consistency-is-not-grounding]]).
- **PDP, not PEP by default.** The directive is advisory — it informs and still lets the
  agent dispatch (the docs/143 WARN rung, the only agent-side rung proven positive live).
  It rides the shipped intervention ladder; BLOCK/rewind are opt-in escalations.
- **The wall is where it stops.** On a WALLED tool the *same* diagnostic bytes appear
  (`create_filter` -> all 9 `criteria.*` is required) but **no valid value exists**, so a
  re-surface cannot convert — which is exactly why the feasibility witness must run FIRST
  and route walls to early-halt, not to schema-refresh.

---

## §5 — The honest ceiling and the open question

- **What is measured ($0):** on the recorded corpus, 76% of curable thrashes carry a
  SCHEMA corrective the agent ignored; 0% are opaque. The corrective is env-authored, so
  the mechanism is byte-clean. The kind-split (schema vs reference vs state) prevents the
  recursive category error.
- **What is NOT measured (live-only):** whether re-surfacing the corrective actually
  *converts* fail→pass. That is the [[docs/199]] curable-slice A/B — and the
  schema-refresh `warn`-rung directive is the natural arm to add to it (`none` /
  `warn` / `restart_seeded` / `schema_refresh`). The $0 ceiling bounds it from above
  (≤76% of curable thrashes are even addressable this way); the live A/B measures how
  much of the ceiling a re-surface realizes.
- **The general claim that survives regardless:** DOS's role in conversion is to **route
  the model back to the environment's authoritative schema** (re-fetch where introspection
  exists, re-surface the error's own corrective where it does not) — never to author the
  schema. The split decides *where* (curable, schema-kind); the witness keeps it honest.
