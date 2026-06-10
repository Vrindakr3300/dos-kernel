# Announce copy: the "no wrapper can fix TOCTOU" claim, scoped (audit oversell #1 closed)

*2026-06-10. Closes finding #1 of the 2026-06-09 paper substance audit
(`paper_durability_audit` lineage / memory `project-dos-paper-audit-substance-findings`).*

## The finding

The launch copy claimed, in universal form, that no wrapper around a single agent
can fix the check-then-act race ("no wrapper around A can fix it", "no wrapper can
patch it", "a race A can't even see"). Basic CS refutes the universal form: where
the shared store offers an atomic conditional primitive — compare-and-swap,
optimistic concurrency control with version stamps, transactions — a single
agent's wrapper CAN fuse check and act into one atomic step. The store itself is
the serialization point; no inter-agent referee is needed. The exposure was acute
because the paper's own headline witness is a tau2 **database** hash — exactly a
store where OCC/CAS would work — so a reviewer or an HN commenter lands the
counterexample immediately.

The defensible scope (and the one the paper itself already states): agents in the
wild act through high-level tool APIs (cancel a reservation, file a ticket, edit a
git tree) that expose only **unconditional writes**, so no atomic check-and-act
exists to wrap; DOS's referee supplies the serialization the store doesn't, and
serializes agents that don't share a transactional store at all.

## What was already fixed before this pass

Commit `882b563` ("concede the wrapper, not the value") landed the concession in
the **paper**:

- `paper/sections/01_abstract.html` — abstract: "Agents act through high-level
  tool APIs that offer no transaction and no conditional write, so no re-run
  wrapper around A can close that race"; intro: "The textbook cure — fuse check
  and write into one atomic step — lives in the *store*…".
- `paper/sections/06_positioning.html` — the full concession: "If the shared store
  offered a transactional primitive (a serializable transaction, a
  compare-and-swap, a conditional write), a wrapper around even a lone agent could
  fuse check and write into one atomic step and close the race with no referee.
  Our claim is scoped to the regime that holds for agents in the wild…".
- The generated `paper/arxiv/sections/*.tex` (regenerated 2026-06-10) carries the
  same qualified form — checked, not hand-edited (the `.tex` is generated; edit
  `sections/*.html` + `assemble_arxiv.py` only).

## What drifted, and how

The **announce docs** drifted back to the universal form. Mechanism: `b5b9729`
("tighten launch-copy prose to the plain-words house style", 2026-06-10) was a
prose-tightening pass that re-derived the punchy unqualified sentence *after*
`882b563` had scoped it. A tightening pass treats the concession as fat; it is
load-bearing.

## What this pass changed (docs/announce only)

Every instance now concedes the primitive and scopes the claim, in the announce
docs' plain-words register:

- `arxiv-abstract.md` — 3 spots: the "as submitted" abstract (re-mirrored to the
  paper's committed sentence), the LinkedIn/X announcement post, tweet variant (b).
- `blog.md` — 3 spots: the fleet paragraph (dropped the bare "no wrapper can patch
  it"), the "systems people" paragraph (now carries the full textbook-cure
  concession: CAS defined inline, store-as-referee conceded, then the tool-API
  scope), the closing boundary paragraph.
- `linkedin.md` — 3 copy spots (main post follow-on, shorter variant, one-liner)
  + a posting note: "Concede the transactional store too."
- `hackernews.md` — the author's first comment (concedes the store before the
  thread does) + a posting note naming the expected "CAS/OCC closes TOCTOU"
  comment.
- `README.md` — the "one rule" paragraph now states the scope and warns the next
  trimming pass not to cut it (with the `b5b9729` precedent named).

The user-approved verbatim 5-sentence opener ("Checking a single agent is easy…
because agent B changed the shared state in between") is untouched everywhere —
the universal claim always lived in the follow-on sentence, which is where the
scoping now lives too.

## Residual (deliberately not touched)

- `paper/sections/01_abstract.html` line ~100 (contributions list): "the race no
  single-agent wrapper can reach" — an anaphor to the already-scoped race, twice
  qualified earlier in the same file; defensible in context. Also the file carries
  a peer session's uncommitted edits (citation swaps), so per the concurrent-edit
  discipline it was left alone.
- The version stamps ("Refreshed … against v0.20.1") were left as-is: they assert
  the *numbers* trace to that paper state, and bumping them without re-checking
  every number would itself be an over-claim.
