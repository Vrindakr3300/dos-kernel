# Example plan — what a DOS plan doc looks like

> **This is a copyable starter plan.** `dos plan` reads files like this one and
> builds the **work-terrain board**: every phase, the plan's *claim* of done set
> beside the **oracle's** verdict from git. The plan is a *row source*, never the
> truth — `dos plan` asks this file only "what phases exist and what does the plan
> *say* about each?", then rules on every one with `dos verify` (git ancestry +
> the ship-stamp grammar), never from the `SHIPPED` words below. That inversion is
> the whole point: a plan-status view built on the plan's own self-report would be
> a self-narrating worker; one built on the oracle's verdict is the kernel doing
> its job at the plan altitude.
>
> Filename matters: the default `plans_glob` is `docs/**/*-plan.md`, so a plan doc
> must end `-plan.md` and live under `docs/` to be discovered (or point
> `plans_glob` at this dir — see the sibling `README.md`).

The grammar the built-in `markdown` source harvests (`src/dos/plan_source.py`),
stated once so you can copy the shape without re-deriving it:

- A phase is a heading `### N. PLAN PHASE — title`.
  - `N.` is a section number (any integer, then a dot).
  - `PLAN` is the plan id — **starts with a letter** (`AUTH`, `CART`, `IF`).
  - `PHASE` is the exact string `dos verify` takes positionally — it must carry
    **both a letter AND a digit** (`AUTH1`, `P2`, `IF4.1`). A bare ordinal like
    `2` is rejected on purpose (see the footer).
  - The separator after the phase token is **REQUIRED** and is one of
    em-dash `—`, en-dash `–`, hyphen `-`, or colon `:`. No separator → the line
    is read as prose and skipped (the conservative under-harvest the kernel
    prefers over mining prose for phantom phases).
- A `SHIPPED` token anywhere in the lines under a phase is the **plan's CLAIM**
  of done — narration the oracle distrusts. It is shown only to *contrast*
  against the verdict; it never makes a phase verified. A soak/blocked/await word
  (`SOAK`, `BLOCKED`, `AWAITING`, `GATED`, `DEFERRED`) reads as claimed-blocked;
  anything else reads as claimed-open.

What closes a phase for real is a **git commit**, not a word here: a commit whose
subject starts `<PHASE>:` — e.g. `AUTH1: ship the login endpoint` — is what stamps
`AUTH1` shipped under the generic default grammar, exactly as the
[`README`](../../README.md) / [`QUICKSTART`](../../docs/QUICKSTART.md) show. Until
that commit lands, `dos verify AUTH AUTH1` answers `NOT_SHIPPED ... (via none)` no
matter what this file claims.

---

### 1. AUTH AUTH1 — ship the login endpoint

<!-- This phase carries a SHIPPED claim. On the board it lands in one of two
     cells, and that split is the lesson:
       * if a commit `AUTH1: …` is in this repo's git ancestry, the oracle AGREES
         → the row reads `·shipped` (claim and verdict match — boring, correct).
       * if no such commit exists, the oracle DISAGREES → the row reads
         `⚠over-claim` (the divergence headline `dos plan` is built around:
         the plan SAYS done, git says not).
     Stamp it for real with:  git commit -m "AUTH1: ship the login endpoint" -->

Add `POST /login`: check the password hash, issue the session token.

- SHIPPED — stamped by `AUTH1: ship the login endpoint`.
- Verify it yourself: `dos verify --workspace . AUTH AUTH1`
  (`SHIPPED ... (via grep)` once that commit is in history; `NOT_SHIPPED (via
  none)` until then — the over-claim cell).

### 2. AUTH AUTH2 — add the password reset

<!-- An OPEN phase: no claim-word under it, so the source reads it as
     claimed-open. The board shows the bare oracle verdict (`·pending` until a
     commit `AUTH2: …` lands). This is the honest steady state of a phase that
     has not been worked yet. NOTE: the harvester reads a phase's whole section
     text (comments included) for its claim word, so keep the stamp tokens out
     of explanatory comments under an open phase — see the README gotcha. -->

Add `POST /password-reset`, email the one-time link, expire it on use. Not
started — exactly the claim the quickstart's agent swears is done.

- `dos verify --workspace . AUTH AUTH2`  →  `NOT_SHIPPED AUTH AUTH2 (via none)`
  (exit 1) — the truth syscall has no commit to stamp it, and does not believe
  the plan's silence either way.

### 3. AUTH AUTH3 — token refresh and rotation

<!-- A BLOCKED/soaking phase: the SOAK word below reads as claimed-blocked
     (`category` shown on the board), distinct from open. Still just the plan's
     narration — the oracle's verdict is independent of it. -->

Rotate refresh tokens on use; revoke on logout. SOAK — gated behind AUTH2,
awaiting the password-reset soak window before it can be picked.

- `dos verify --workspace . AUTH AUTH3`  →  `NOT_SHIPPED AUTH AUTH3 (via none)`.

---

> **Do NOT copy DOS's own `docs/NN_*.md` design plans as a template — they use a
> DIFFERENT dialect this default does not read.** Those design docs head their
> phases `### Phase 2: …` / `- **1a.** …` — a *bare ordinal* (`2`, `1a` with no
> series letter on the heading token). The built-in `markdown` source deliberately
> rejects digit-only / bare-ordinal phase tokens (`_looks_like_phase_id` requires
> **both** a letter and a digit) so that prose headings like `### 1. The rationale
> — why` are never mis-harvested as phantom phases. That conservatism is the
> tradeoff: a repo whose plans use the `### Phase N:` dialect must ship a
> `dos.plan_sources` plugin (a by-name source registered under the
> `dos.plan_sources` entry-point group) rather than rely on the default — see
> [`docs/HACKING.md`](../../docs/HACKING.md) ("custom plan dialects"). The shape in
> *this* file (`### N. PLAN PHASE —`, letter+digit phase id) is the one the kernel
> default harvests out of the box; copy this, not a design doc.
