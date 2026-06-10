# Byte-inequality and the derivative problem

> **The bytes a judged agent emitted may never be the bytes that confirm it.**
> That is the whole axiom, stated at the byte level. Everything the kernel calls
> "truth" is a consequence of holding this line; everywhere it is forgeable is a
> place the line has bent. This doc does two things: it states the axiom at full
> strength (sharper than the actor-level "byte-author ≠ judged agent" of
> [docs/138](138_what-is-truth-the-throughline.md)), and it confronts the one case
> where the axiom **cannot be satisfied by separation** — a program *written by an
> LLM loop*, a derivative whose confirmation cannot be byte-distinct from the thing
> confirmed because the thing confirmed IS the agent's output. The resolution is not
> a weaker axiom; it is the axiom moved up a level, by lineage.

This is a throughline/design doc, not a new module. It collects an argument that is
already half-shipped (the non-forgeable rung in `resume_evidence`, the floor in
`evidence`) and names the half that is not (a derivation-lineage rung). Read it
after docs/138 (the truth throughline), docs/117 (the actor-witness split), and
docs/107 (the intent ledger's non-forgeable mint), all of which it stands on.

## 1. The axiom, at the byte level

docs/138 states the invariant as **"evidence counts only when its byte-author is not
the agent being judged."** That is correct but stated at the *actor* level — it
forbids the agent from being the witness. The sharper, byte-level form forbids one
thing more:

> **The bytes used to confirm a claim must not be the bytes the judged agent
> emitted.**

The difference matters because the degenerate failure people actually ship passes
the actor-level test and fails the byte-level one. An agent writes
`{"status": "SUCCESS"}`; a "verifier" reads `obj["status"] == "SUCCESS"`. The
verifier is a *different actor* — a different function, maybe a different process —
so "byte-author ≠ judged agent" looks satisfied. But the **confirming bytes are the
agent's bytes, round-tripped.** The verifier consulted no independent faculty; it
read back the claim and agreed with it. That is not verification, it is a mirror
with a function signature. (This is the disease docs/103 named inward — the memory
store recalling a frozen self-report as fact — and docs/116 named at fleet scale —
a blackboard where agents read each other's claims. Both are the byte-inequality
axiom violated: the confirming bytes are some agent's emitted bytes.)

So the axiom is byte-level, and the evidence ladder of docs/138 is **nothing but
grades of byte-distance from the agent's pen:**

| Rung | Who authored the *confirming* bytes | Distance from the agent's pen |
|---|---|---|
| self-report (`"done": true`) | the agent | zero — same pen |
| commit **subject** naming the phase | the agent (it typed the message) | ~zero — agent-chosen prose, the live `grep-subject` hole |
| commit **diff** under a declared footprint | agent's content, but location is mechanical | partial — the agent cannot change *which files a historical commit touched* |
| git **ancestry** (reachable from a ref?) | the VCS merge mechanism | full — the agent cannot forge reachability from a ref it does not control |
| an external **receiver's** record (ATS email, OS exit code, CI log) | the counterparty / the OS | full — a different process on a different machine wrote them |

Every rung up is bytes further from the pen. "Truth" is just "the highest rung an
un-authored witness reached." The kernel ships the low rungs too (a no-op commit IS
a fossil, just a weak one) but **labels** them, so a reader sees a `grep-subject`
verdict is one a forged commit could have produced — `_NONFORGEABLE_GREP_RUNGS =
frozenset({"file-path"})` (`oracle.py:1031`) is the entire non-forgeable grep set,
and the grep-subject rung is documented as self-certifying *in the oracle itself*
(`oracle.py:1013-1014`). The axiom is enforced where the bytes are far from the pen
and **honestly conceded** where they are not.

This much is docs/138 restated at byte resolution. The new content is §2.

## 2. The case the axiom cannot reach by separation

Every surface in docs/138 assumes the same shape: **truth is a fact about an
effect, and the effect has an external witness.** Did the phase ship → ask git. Was
the email sent → ask the ATS. Did the process succeed → ask the OS exit code. In
each, the thing under judgment (the effect) and the confirming bytes (the witness's
record) are *naturally distinct*, authored by different parties. Separation is
available, so the axiom applies directly.

Now consider an **LLM loop that writes a program** — a derivative, a generated
transform, synthesized code, a refactor, a migration the agent authored end to end.
Ask the axiom's question: *what are the bytes that confirm it, and are they distinct
from the bytes the agent emitted?*

The answer is that **they cannot be distinct, because the artifact IS the agent's
emitted bytes, in their entirety.** When you want to confirm that `deriv.py` —
written wholesale by the loop — is correct, there is no *other* byte-set the agent
didn't author that you can point at and call the witness. The thing under judgment is
the output itself. The receiver-of-the-effect trick that rescued the effect case
does not obviously apply: there is no external counterparty who "received" a
generated function the way an ATS receives an application or an OS receives a process
to run.

This is **not** the same as the intent-mismatch limit docs/138 already concedes
("the artifact exists in git, not that it is the right artifact"). That limit is
about a *named effect* whose semantics the oracle can't read. The derivative problem
is deeper: there is no effect with a witness at all. Truth here is not "did X
happen" but **"is this output the correct image of that input under the intended
transform"** — a *relation between input and output*, and the agent authored the
output side of the relation. No git commit, no exit code, no email attests to a
relation. The witness that saved §1 simply does not exist for §2.

So for derivatives, **the byte-inequality axiom cannot be satisfied by separation.**
You cannot find confirming bytes the agent didn't write, because the artifact is all
of the bytes there are.

### 2.1 Why "just run it" is not the escape (and where it partly is)

The instinct is: confirm a generated program by *running* it — the OS exit code is a
non-forgeable witness (`drivers/os_acceptance.py`), and the agent didn't author the
OS's record of how it ended. True, and it is the right move *when the program's
correctness reduces to an observable effect* — a test suite the agent didn't write,
a property check, a golden-output comparison against bytes the agent didn't produce.
There, the derivative problem collapses back into the effect case: the test
*becomes* the external witness, and the OS records its verdict. The acceptance verb
is exactly this rescue, and it is the strongest thing the kernel can do for a
derivative.

But it only rescues the part of correctness the witness covers, and the gap is
structural:

- **The agent often authors the test too.** A loop that writes `deriv.py` and writes
  `test_deriv.py` has authored both sides — the confirming bytes are the agent's
  bytes again, one layer removed. A green run of an agent-authored test is a
  `grep-subject` rung wearing a lab coat: it satisfies a check the same pen wrote.
  (The floor that saves it is the same one docs/138 §invariant names for the JUDGE
  rung — the test/oracle must descend from bytes the judged agent did not author: a
  human-written acceptance suite, a spec fixture, a property the *counterparty* cares
  about.)
- **Most derivative correctness is not an effect.** "Is this the *faithful*
  translation of that input," "does this refactor *preserve* behavior across the
  whole input domain," "is this generated client *equivalent* to the schema" — these
  are relations over a space too large for any finite run to witness. Running pins a
  point; it does not witness the relation.

So `os_acceptance` is the floor for derivatives, and it is real, but it is partial by
construction. It witnesses *an effect of running the artifact*, never *the artifact's
faithfulness to its source*. The residue — the relation itself — needs the other
move.

## 3. The resolution: lineage is the axiom moved up a level

The base case of the axiom requires *separation* — confirming bytes distinct from
emitted bytes. When separation is impossible (because the artifact is the emitted
bytes), you cannot apply the axiom to the artifact. But you **can** apply it to the
artifact's *derivation*. That is the move.

A derivative is not a free-floating string; it is the output of a step:
`derivative = transform(input)`, and the loop that produced it has, or can be made to
have, a record of *which* input, *which* transform/spec, *which* prior artifact this
descends from. Call that the **lineage** — the provenance edges of the artifact.

The bytes of the artifact are the agent's. But the **claim "this artifact derives
from that ancestor under that recorded spec" is itself a positive claim** — and a
positive claim is exactly what the axiom governs. So apply the axiom to the *edge*,
not the *artifact*:

> A derivative is trusted iff every edge in its provenance chain is recorded by, or
> re-adjudicable against, bytes the judged agent did not author — and the chain
> bottoms out in a believed ancestor.

This is **the same shape as the inductive step in a proof.** The base case
(§1): a leaf claim is true when an un-authored witness attests it. The inductive
step (§3): a derived claim is true when (a) its ancestor is true and (b) the
derivation edge stands on a non-forgeable rung. Lineage is not a *weaker substitute*
for byte-inequality — it is byte-inequality applied **one level up**, to the
derivation record instead of the artifact, recursively, until it grounds in a leaf
the §1 axiom can witness directly.

The critical discipline: **the lineage record must itself obey the base axiom.** If
the agent authors its own provenance graph and the kernel believes it, nothing was
gained — the agent forges the edge instead of the artifact, and we are back to the
mirror. So a lineage edge is trustworthy only to the degree it is **not the agent's
self-report.** Which is precisely the problem the kernel has already solved once.

## 4. The kernel already built the mechanism — for progress, not derivation

The intent ledger (docs/107) faced the identical structure for a *different* claim.
An agent self-reports "I completed step S at SHA H" — `STEP_CLAIMED`, the agent's
pen, the forgeable floor. The kernel does **not** trust that record. It *re-adjudicates*
the edge at read time:

`step_stands_on_nonforgeable_rung(sha, region=...)` (`resume_evidence.py:107-157`)
mints belief in a claimed step **only** when all hold:

1. **In git ancestry** — the SHA is reachable from HEAD (the agent cannot forge
   reachability).
2. **Non-forgeable footprint** — the commit touched ≥1 real file (defeating the
   `--allow-empty` commit whose *subject* names the step — the derivative-world
   analogue of a commit message claiming a transform that produced no bytes).
3. **Footprint intersects the declared region** — the touched files overlap the
   step's declared file region, reusing the kernel's one collision algebra
   (`_tree.lane_trees_disjoint`). This defeats a forged record pointing at *any real
   but unrelated* commit — the attacker needs more than an ancestry SHA, they need
   one whose effect lands *where the step said it would*.

"The agent writes the ledger; it cannot write into the authority set"
(docs/138:139-140). The `STEP_VERIFIED` mint is *stored as a hint* and
*re-adjudicated against git at every read* (`resume.py:230-262`) — the via-tag the
agent wrote is never trusted; only the freshly re-checked ancestry+footprint+region
fact is.

**This is exactly the inductive step of §3, already implemented — for the claim "I
made progress" rather than "this output derives from that input."** The shape
transfers wholesale:

| Intent ledger (shipped, docs/107) | Derivation lineage (the gap) |
|---|---|
| claim: "step S landed at SHA H" | claim: "artifact A derives from ancestor P under spec T" |
| forgeable record: `STEP_CLAIMED` (agent's pen) | forgeable record: an agent-authored provenance note |
| non-forgeable rung: ancestry ∧ footprint ∧ region | non-forgeable rung: **?** (the open design) |
| re-adjudicated at read, never trusted from record | must be re-adjudicated, never trusted from record |
| grounds in: a believed prior SHA | grounds in: a believed ancestor artifact (recurse) |

And the *positive-claim floor* is also already built. `believe_under_floor`
(`evidence.py:48-58`) encodes the rule that a claim which can *upgrade* a verdict
toward belief must have a non-forgeable source ANDed under it: "the worst a
buggy/hostile/lying AGENT_AUTHORED source can do is claim an attestation that is then
ignored for belief." A lineage edge is a positive claim (it argues *for* trusting the
derivative). So it rides the same floor: an agent-authored lineage edge is recorded
and shown, but **structurally incapable of granting belief on its own** — it must be
backed by a non-forgeable rung (an ancestry-anchored ancestor, a recorded spec the
agent didn't author, a deterministic re-derivation), or it stays a hint.

## 5. What the non-forgeable rung for a derivation edge could be

This is the open design — the doc names the shape, not a shipped module. Candidate
rungs for "edge A←P is real," ordered by forgeability (the docs/138 grading
discipline), strongest last:

- **Re-derivation (the gold rung).** If the transform is deterministic and recorded
  (a recorded spec/seed/model-pin — cf. docs/115's `EnvPrint`, "under what did this
  run"), the kernel can *re-run* `transform(P)` and byte-compare to A. The confirming
  bytes are then authored by *the re-derivation the kernel ran*, not the agent — full
  byte-inequality, restored. This is the derivative analogue of the acceptance verb:
  the kernel performs the act and reads the result. It works only for deterministic,
  re-recordable transforms — but where it works, it is the strongest possible rung,
  because it collapses the relation back into an effect the kernel itself witnesses.
- **Ancestry-anchored ancestor + real footprint (the resume rung, re-aimed).** The
  ancestor `P` must itself be a believed artifact (a SHA in ancestry whose footprint
  is real and on-region), and `A`'s commit must touch the derivative's declared
  region. This is `step_stands_on_nonforgeable_rung` applied to the *edge's
  endpoints* — it proves "a real artifact descended from a real ancestor in the right
  place," not yet "by the claimed transform." Partial, but free (the code exists).
- **Counterparty-attested spec.** The transform spec / schema / contract is authored
  by someone other than the judged agent (a human-written spec, a published API
  schema, a golden corpus). Then "A conforms to spec T" has an external referent even
  if the conformance check is the agent's — the docs/123 independence coordinate
  applied to the *spec* rather than the *judge*.
- **The forgeable floor (recorded, never believed alone).** A pure agent-authored
  provenance note ("I generated this from that"). Kept as a hint under
  `believe_under_floor`, shown to the operator, incapable of granting belief by
  itself — exactly `STEP_CLAIMED`'s status.

The honest concession, in the docs/138 register: **for a non-deterministic transform
with no external spec and no re-derivation, there may be no non-forgeable rung at
all.** A creative generation — "write me a function that does X," judged on whether
it is *good* — is the intent-mismatch limit (docs/138 §"oracle abstains on
intent-mismatch") in its purest form: the kernel cannot read "is this the right
artifact," and no lineage edge manufactures a witness for a relation no external
party holds. There, the chain bottoms out not at a non-forgeable leaf but at a
**human or an independent judge** (the ORACLE → JUDGE → HUMAN ladder), and the kernel
must say ABSTAIN rather than narrate a confidence it lacks. Lineage extends the reach
of mechanical truth up the derivation chain; it does not abolish the seed of
irreducible judgment at the bottom.

## 6. Worked examples — where the kernel holds the line and where it bends

The axiom is not aspirational; it is enforced (and conceded) at named line numbers.
This is the evidence base, swept from the code, grouped by whether the line **HELD**
(re-derives from a non-forgeable witness), **BENT** (reads agent-authored bytes as
confirmation, graded), or is a **NAMED ATTACK** (a place the code documents where
confirming-bytes-could-equal-emitted-bytes).

**HELD — the kernel refuses the agent's bytes and re-derives:**

- **`resume_evidence.py:107-157`** (`step_stands_on_nonforgeable_rung`) — the
  archetype. A claimed step earns `STEP_VERIFIED` only on ancestry ∧ real footprint ∧
  region-intersection; "an `--allow-empty` commit … touches NO files, so it fails this
  — exactly the named attack."
- **`resume_evidence.py:196-242`** (`adjudicate_verified_steps`) — re-runs that check
  at **read** time on every stored record, because "a malicious run can append its own
  `STEP_VERIFIED {via:"file-path", sha:<any real ancestry commit>}` for a step it never
  did." The agent writes the ledger; it cannot write into the authority set.
- **`evidence.py:411-484`** (`believe_under_floor`) — belief granted only when a
  non-forgeable (`OS_RECORDED`/`THIRD_PARTY`) source attested; every `AGENT_AUTHORED`
  source is filtered out of the decision (`:445`), recorded but "structurally incapable
  of … moving the verdict from abstain to believe" (`:48-58`).
- **`scope.py:9-11`** — stated in one line: *"The self-report ('I touched the picker')
  is exactly what a believer cannot check; the diff's actual footprint is ground truth
  the agent cannot forge, and this verdict reads it."*
- **`status.py:6-8`** — the fail-closed shape: the status digest "carries **no
  `claimed` field** by construction … a consumer cannot read a self-report, because the
  output type has no slot for one." The axiom enforced by the *type*, not a check.
- **`packet_sidecar.py:30-37,190-212`** (`assert_packet_shippable`) — the thesis at the
  *producer*: "the renderer's exit-0 `Saved:` is a self-report the kernel does not
  trust. This re-reads the artifact from disk (not from the in-memory picks the renderer
  *thinks* it wrote)." The same move, one layer earlier than `verify`.
- **`log_source.py:34-53`** — `AGENT_AUTHORED` "has no path to the oracle classifier by
  construction"; the agent "chose every byte that reached here," so it routes to an
  advisory JUDGE, never a deterministic verdict.
- **`drivers/os_acceptance.py:76-88`** — the contrast case: the OS exit code is
  `OS_RECORDED`, "fixed … the exit code is the OS's record, full stop." The agent can
  author a commit subject; it cannot author a `returncode`.

**BENT — the kernel reads agent-authored bytes, but grades them forgeable:**

- **`oracle.py:137-150, 1006-1031`** — the grep rungs. `direct`/`release-prefix`/
  `body-mention`/`hyg-slug`/`sub-phase-parent` all match a token in the commit
  **subject/body the agent authored**; `_NONFORGEABLE_GREP_RUNGS = frozenset({"file-path"})`
  (`:1031`) is the *entire* non-forgeable grep set. The kernel **clears** the forgeable
  rungs but labels them, so a reader sees the grade.
- **`resume.py:84-91`** (`require_nonforgeable_rung`) — the gate is *configurable*: a
  policy can be set to count a forgeable-rung `STEP_VERIFIED`. That the gate exists is
  itself the concession that the line *can* be relaxed (it defaults closed).

**NAMED ATTACK — the code documents the equality it forbids:**

- **`oracle.py:1013-1014`** — the smoking gun, in the oracle's own comments:
  `git commit --allow-empty -m 'docs/X: PHASE — done'` "satisfies `direct` with zero
  code shipped." The confirming bytes (the subject) ARE the agent's emitted bytes.
- **`intent_ledger.py:82-83, 480-509`** — the asymmetry named as ops: `OP_STEP_CLAIMED`
  = "the agent SAYS it finished … (forgeable)"; `OP_STEP_VERIFIED` = "the kernel
  CONFIRMED … against ancestry on the NON-FORGEABLE rung." Two ops, one trustable.
- **`drivers/paste_log.py:66-131`** — the floor made explicit: pasted text is
  hard-tagged `AGENT_AUTHORED`, "a class-level constant, not a per-call choice, so this
  source can never claim a higher rung."

The shape is consistent across all three: the kernel ships the forgeable rung (a
weak fossil is still a fossil), **labels** it, and structurally bars it from being the
*sole* basis for belief. That is the axiom operating as a gradient, not a gate.

## 7. Prior art — the principle is old, and we should say so

Neither the axiom nor the lineage corollary is novel to DOS. Naming the lineage is
itself an application of the doc's own discipline (a claim of novelty is a self-report;
the un-authored witness is the literature). The principle has been independently
re-derived across security, supply-chain, verification, and science:

**The base axiom (confirmer ≠ producer):**

- **Verifier–prover asymmetry (NP).** Finding a solution is hard; *checking* one is
  easy — so the checker need not trust or re-run the producer. Cook–Levin, 1971. *This
  is the formal root of the whole principle.*
- **Reference monitor / Trusted Computing Base.** A small, tamper-proof, independently
  verifiable mediator decides; the untrusted body is checked by it, never trusted to
  self-validate. Anderson, 1972 — the doctrine CLAUDE.md already cites as DOS's ancestry.
- **Separation of duties / maker-checker (four-eyes).** The actor cannot self-approve;
  a different party validates before the effect takes. Saltzer & Schroeder 1975 ("separation
  of privilege"); Clark–Wilson 1987; the banking control tradition.
- **Schneier's Law.** "Anyone can create an algorithm he himself can't break" — so a
  cipher is trusted only after *others* fail to break it. Self-validation is worthless.
  Schneier, 2011. *The cleanest one-line statement of "you cannot confirm your own work."*
- **Certifying algorithms.** The algorithm emits a *witness/certificate* an independent,
  simpler checker verifies — trust the result without trusting the (possibly buggy)
  algorithm. Mehlhorn & Näher; survey McConnell et al. 2011. *This is the
  `STEP_VERIFIED` shape exactly: produce a checkable certificate, check it independently.*
- **Differential / metamorphic testing & the oracle problem.** No implementation grades
  its own output; cross-implementation disagreement or cross-run invariants are the
  oracle. McKeeman 1998; Chen 1998; Weyuker 1982 ("On Testing Non-testable Programs").

**The lineage corollary (a generated artifact is trusted via its derivation, not the
generator's word) — the closest analogues, and the most important to cite:**

- **Trusting Trust.** A compiler can backdoor both binaries *and itself*, so a
  compiler's own bytes can never vouch for what it produced — clean source is not enough.
  Ken Thompson, Turing lecture, 1984. **The canonical statement that a generator cannot
  self-certify its output — the LLM-derivative problem, 40 years early.**
- **Diverse Double-Compiling.** Recompile the source with a *second, independent*
  compiler and check bit-for-bit identity — confirmation by independent re-derivation,
  never the original compiler's word. David A. Wheeler, ACSAC 2005 / PhD 2009. **The
  direct answer to Trusting Trust, and our single best analogue for the re-derivation
  rung of §5.**
- **Reproducible builds.** Given identical source + recorded environment, *any party*
  recreates a bit-for-bit identical artifact — an independently verifiable source→binary
  path. reproducible-builds.org; Debian, Bitcoin Core, Tor. *rebuilderd's GOOD/BAD
  verdict even mirrors the kernel's verdict vocabulary; the "recorded environment" is
  exactly why the re-derivation rung needs `EnvPrint` (docs/115) first.*
- **SLSA / in-toto / Sigstore.** Graded, signed, tamper-evident build provenance binding
  an artifact to who/what/when/how it was produced, recorded in an independently
  auditable transparency log — trust by attested lineage, not self-report. OpenSSF;
  Torres-Arias et al. 2019; Certificate Transparency lineage (RFC 6962). *The
  industrial form of the `(ancestor, spec_digest, transform_id)` ledger op of §7.*
- **Proof-Carrying Code.** Untrusted code ships *with* a machine-checkable safety proof
  the host's small trusted checker validates — trust neither the producer nor a
  signature. Necula & Lee, 1996.
- **Translation validation.** Don't prove the compiler always-correct; check *each run's
  output* correctly implements its input. Pnueli, Siegel & Singerman, 1998. **The
  strongest analogue to "verify *this* generated program, *this* time, by an independent
  check" — per-derivation validation, exactly the derivative case.**
- **C2PA / Content Credentials.** Cryptographically signed, tamper-evident provenance
  attached to media: AI-generated content is trusted via an attested lineage chain, *not
  by inspecting the pixels* — because the pixels ARE the model's output. Adobe/Arm/BBC/
  Intel/Microsoft/Truepic, 2021. **The media-domain twin of this doc's exact thesis.**
- **Nothing-up-my-sleeve numbers & chain of custody** — the crypto micro-example
  (constants derived from a public reproducible source so the author can't hide a
  backdoor) and the forensic real-world anchor (an artifact is admissible only via an
  unbroken documented provenance trail). Trust-via-derivation, two domains.

**AI-native restatements:**

- **LLM-as-judge independence / self-preference bias.** A model rating its own
  generations is a biased judge; independent or ensemble judges are needed. Zheng et al.
  2023; Panickssery et al. NeurIPS 2024 (*magnitude actively contested in 2025–26 — cite
  as documented and debated*). This maps onto the kernel's own ORACLE→JUDGE→HUMAN and the
  co-resident-judge problem (docs/123): a judge sharing weights/box with the worker is
  grading itself.
- **Reward hacking / Goodhart's law.** When the producer can influence the confirmation
  signal, the signal stops meaning what you think; "when a measure becomes a target it
  ceases to be a good measure." Amodei et al. 2016; Goodhart 1975. *This is precisely the
  `--allow-empty` case — the metric (a token in the log) made gameable by the measured
  party. docs/108:359 calls it "the Goodhart point" by name.*

**Honest-hole caveats (the doc's own discipline applied to its citations):**
Kerckhoffs/Shannon (secrecy ≠ security) and property-based testing (invariants) are
*adjacent*, not strict producer≠checker. **SBOM and ML data/model lineage *declare*
provenance but are only as trustworthy as their own attestation — they have no
independent re-derivation, so they sit at the weak end of the lineage spectrum**, and
are the cautionary case for §5: a lineage record the agent authored, unbacked by a
re-derivation or a non-forgeable anchor, is the forgeable floor wearing a provenance
costume.

## 8. The efficiency dual — caching a verdict without re-forging the floor

A verdict is not free (an ancestry walk, a footprint diff, a re-derivation, a judge
call). The natural optimization is to **cache the adjudication: if a claim was already
checked, don't re-check it — look up the stored verdict.** This is correct and the
kernel already does a version of it. But it has a trap that is *exactly on this doc's
theme*, and getting it wrong silently re-opens the whole axiom.

**The trap: a forgeable cache key lets the agent replay a stale clearance.** If you
memoize "claim X → VERIFIED" and the agent controls the bytes that compute the key for
X, the agent can present a *different* artifact that hashes to a *cleared* key and
inherit a belief it never earned. The cache key is now confirming bytes — and if the
agent authored them, the cache is a mirror with a hash function. Caching a verdict is a
*positive* operation (it grants belief cheaply), so it falls under exactly the
`believe_under_floor` discipline of §4: **the key must be content-addressed over the
non-forgeable evidence, and the stored entry must be a hint that re-grounds, never a
trusted fact.**

The discipline, in four rules:

1. **Key the cache by the bytes you couldn't forge, not the bytes you're judging.** The
   key for "this step is verified" must be the *commit SHA + the touched-file set + the
   region* (the non-forgeable evidence), not "the step id the agent named." A SHA is
   already a content hash the agent cannot forge (you cannot find a different tree with
   the same git SHA); hashing *over* it is sound. Hashing over an agent-chosen label is
   not.
2. **Recompute the digest from the fields; never trust a stored digest.** This is the
   single most important rule, and the kernel **already implements it** for the
   environment print: `EnvPrint.digest` is *recomputed from the fields on every read;
   any stored `"digest"` is ignored*, so "a tampered/stale `digest` in a record can
   never be believed — the field is authoritative, the stored digest merely a
   convenience" (`env_print.py:189-211`). A cache whose key is taken on faith from the
   record is a cache the agent writes into; a cache whose key is *re-derived* from the
   evidence is one it cannot. This is the `resume_evidence` re-adjudicate-at-read move
   (§4) expressed as a hashing rule.
3. **A cache hit is still a hint that must clear the floor.** Memoization may skip the
   *expensive* re-derivation, but it must not skip the *cheap* re-grounding: confirm the
   keyed SHA is still in ancestry (a rebase/force-push can evict it), still touches real
   files, still intersects the region. The cache stores "this was true under this
   environment print"; whether it is *still* true is a `verify()` question at read time
   (the docs/103 memory rule — a stored belief is a lane-journal entry, not a fact). The
   kernel keeps such a store today: `home.py:504` records "a log of resolved-decision
   digests" — a cache of adjudicated decisions, keyed by digest, rebuildable by `dos
   reindex`, never the authority itself.
4. **The environment is part of the key.** A verdict computed under one kernel SHA /
   toolchain / model may not hold under another (docs/115). So the cache key for a
   *derivation* verdict must include the `EnvPrint.digest` — "this derivative was
   confirmed under EnvId Z." A hit under a different EnvId is a miss (or a
   `FLEET_ENV_MISMATCH`, docs/115 §5), because the thing that made it true may have
   changed. This is why the re-derivation rung of §5 *requires* `EnvPrint` first: you
   can neither re-derive nor safely cache a transform whose environment you didn't record.

The payoff is that hashing turns the **transitive** trust of §3 into something
cheap. A derivative's lineage chain can be deep; re-adjudicating every edge on every
read is expensive. But if each edge's verdict is cached under a content hash of *its
non-forgeable evidence + the EnvPrint*, then re-validating a chain is a sequence of
hash lookups that each fall back to a cheap re-grounding, and only a changed edge (a new
SHA, a different environment) pays the full re-derivation. **Content-addressing is how
the inductive step of §3 scales** — the same way reproducible-builds and SLSA cache
provenance by content digest so a consumer verifies a deep dependency tree without
rebuilding all of it. The hash is an *accelerator* for the axiom, never a *substitute*
for it: the moment a cache key is something the judged agent authored, the acceleration
is of a lie.

The one-line test for any verdict cache: **could the judged agent produce a different
artifact that lands on a cleared key?** If yes, the key is forgeable and the cache is a
hole. If the key is content-addressed over evidence the agent could not author (a git
SHA, an OS exit record, a third-party attestation digest) and recomputed-not-trusted at
read, the cache is sound — and it is the same axiom, made fast.

## 9. The two-sentence statement

**For an effect, truth is byte-inequality: the confirming bytes must not be the
agent's emitted bytes, and an external witness to the effect supplies them.** For a
derivative — where the artifact IS the agent's emitted bytes and no external witness
to the relation exists — truth is lineage: byte-inequality applied to each
derivation edge instead of the artifact, recursively, grounding either in a
re-derivation the kernel itself runs, an ancestor anchored to a non-forgeable rung,
or an external spec — and where the chain cannot ground in any of those, the kernel
abstains and hands the seed to a human, rather than confirm an LLM's output with the
LLM's own bytes.

## 10. What this implies for the build (non-normative)

- The grep-subject rung (docs/138 §"Where truth is still forgeable") is the §1 axiom
  *violated in the one place the oracle still trusts agent-chosen bytes* — a commit
  subject is prose the agent typed. Closing it (require the `file-path` rung for a
  green verdict, or demote grep-subject to a hint that must clear it) is the cleanest
  single application of this doc to the shipped oracle. Tracked as the rung-occupancy
  backtest in docs/138 §"how the kernel LEARNS what truth is."
- A derivation-lineage rung would be a new `EvidenceSource` shape under the existing
  `believe_under_floor` floor (`evidence.py`), or a new ledger op beside
  `STEP_VERIFIED` in the intent ledger (`intent_ledger.py`) carrying
  `(ancestor, spec_digest, transform_id)`, re-adjudicated at read exactly as
  `resume_evidence` re-checks a step. Both reuse mechanism that ships today; neither
  is built. The re-derivation rung specifically needs the recorded-environment work
  of docs/115 (`EnvPrint`) as its precondition — you cannot re-run a transform you
  cannot reproduce.
- A verdict cache (§8) would key adjudicated results by a content hash over their
  *non-forgeable* evidence (SHA + footprint + region) **plus** the `EnvPrint.digest`,
  recomputed-not-trusted at read in the `EnvPrint.digest` style (`env_print.py:189-211`),
  with a hit still clearing the cheap re-grounding floor. The kernel already stores a
  log of resolved-decision digests (`home.py:504`); extending it to a verify/lineage
  verdict cache is the efficiency lift that makes the transitive trust of §3 scale.
  Not built as a verdict cache today.
- Nothing here changes the kernel's PDP-not-PEP stance (docs/138 §advisory-only): a
  lineage verdict would *report* "this derivative's chain grounds in a non-forgeable
  rung" / "it does not, here is the forgeable edge," and route the ungrounded case to
  a judge or human. It would not block the artifact. Detection, not prevention — the
  same line the rest of the kernel holds.
