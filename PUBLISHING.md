# Publishing playbook — `dos-kernel`

> **End-to-end, one place.** How DOS goes out the door: the Python package to
> PyPI, the repo to GitHub, the paper to arXiv, and the launch announcement. It
> draws a hard line between **what tooling does for you** (build, validate,
> bundle, upload-via-CI) and **what only the owner can do** (claim a name, get an
> arXiv endorsement, post under your identity). Nothing here puts anything on the
> internet by itself.
>
> *Last refreshed 2026-06-10 against `dos-kernel` v0.20.1.*

This supersedes the older launch runbook (`LAUNCH.md`) as the single entry point.
That runbook records the **security rationale** for going public as a fresh repo
(the history-scrub story) and stays in the private archive — like the seeding
tooling itself, deliberately not part of the public tree; Stage 2 summarizes it.
Releasing *versions* (bump + tag) stays in the [`/release`](.claude/skills/release/SKILL.md)
and [`/stable-release`](.claude/skills/stable-release/SKILL.md) skills; this doc
is about the *outward* steps those don't cover.

---

## The map: four stages, and who takes each step

| Stage | Automatable part (tooling does it) | Manual part (owner only) |
|---|---|---|
| **1. PyPI** | `python -m build` → `twine check` → smoke-import → upload via OIDC CI | One-time trusted-publisher web config; approving the protected `pypi` environment |
| **2. GitHub public** | The seed script scrubs + commits a clean tree; CI runs on push | `gh repo create`, set topics, flip the README badges |
| **3. arXiv** | Regenerate `.tex` → stage figs → `arxiv-latex-cleaner` → tarball | The upload itself (no API), endorsement, license, moderation |
| **4. Announcement** | Drafts are written and staged in `docs/announce/` | Posting to LinkedIn (manual / native scheduler); any cross-post |

The recurring shape: **everything up to the irreversible, outward-facing,
identity-bound action is a script or a CI job; that final action is yours.** This
is the same posture the kernel takes — it *decides and proposes*, it does not
*act* (PDP, not PEP).

> **The one ordering constraint.** PyPI (Stage 1) and the GitHub repo (Stage 2)
> reference each other — the trusted publisher is registered against the public
> repo name, and the README's `pip install` only works once the name is claimed.
> Do them as a pair. arXiv (Stage 3) and the announcement (Stage 4) are
> independent and can happen before, after, or between. A sane order is
> **2 → 1 → 4 → 3** (repo, then package, then announce, then — once endorsement is
> arranged — the paper), but nothing breaks if you reorder.

---

## Pre-flight (do this once, before any stage)

A clean, green tree is the floor for everything below. The working tree on
`master` is often a **hot lane** with several concurrent sessions' in-flight
edits — publish from a checkout where `git status` is clean and the suite passes.

```bash
python -m pytest -q                 # the full kernel suite — must be green (~2970 tests)
dos doctor --workspace .            # confirm the workspace is sane
dos commit-audit --sweep --workspace . origin/master..HEAD   # claims match diffs?
```

`git stash` (or commit on its own lane) any in-flight feature you don't want to
ship. If `dos commit-audit` flags a drift, fix the message or the work before you
publish — you don't want a forged "shipped" claim in the first public history.

---

## Stage 1 — Publish `dos-kernel` to PyPI

The **distribution name is `dos-kernel`**, not `dos` (the bare `dos` on PyPI is an
unrelated squatter — see [SECURITY.md](SECURITY.md) "Supply chain"). The import
name stays `import dos`. The first upload **claims the reserved name**.

### 1a. Build + validate locally (fully reversible — do this first)

DOS ships a native `dos-hook` fast-path binary (docs/125/270) — so the release is
**six per-platform wheels + one pure-source sdist** (docs/286), not a single
`py3-none-any` wheel. Each wheel embeds only its own OS/arch's static binary at
`dos/_bin/`, re-tagged `py3-none-<platform>` so `pip install dos-kernel` downloads
just the one wheel for the installing machine. The binary is a static, no-cgo Go
executable, so **one host cross-compiles all six** (needs the Go toolchain on PATH).

```bash
python scripts/build_wheels.py      # go-build per arch → build → wheel-tag retag (+ sdist)
#   → dist/dos_kernel-<v>-py3-none-{manylinux2014_x86_64,…,win_amd64,win_arm64}.whl
#   + dist/dos_kernel-<v>.tar.gz     (pure source — installs the Python-verb fallback)
#   --host = only this machine's arch (fast dev build);  --check = plan only.
python -m twine check dist/*         # every wheel + the sdist must render on PyPI
```

> **No Go toolchain?** `python scripts/build_dist.py` still builds the **pure-Python**
> `py3-none-any` wheel + sdist + a clean-venv smoke — publishable, but with **no**
> native binary (every install pays the Python hook cold-start; docs/270). Prefer
> `build_wheels.py` for a real release so pip adopters get the fast path.

This is the local half. It produces the artifacts and proves they're sound; it
does **not** upload. (CI does the same on every push via
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)'s `build` job, which also
runs `build_wheels.py` so a broken matrix build is caught before a tag.)

### 1b. One-time owner setup — register the trusted publisher (web)

The recommended 2026 path is **Trusted Publishing (OIDC)** — GitHub Actions mints
a short-lived token PyPI accepts, so there's **no API token to store or leak**.
The workflow is already written ([`.github/workflows/publish.yml`](.github/workflows/publish.yml));
it does nothing until you create the publisher record. Once, on the web:

1. **PyPI** → <https://pypi.org/manage/account/publishing/> → *Add a pending publisher*:
   - PyPI Project Name: `dos-kernel`
   - Owner: `anthony-chaudhary` · Repository: `dos-kernel` (the **public** repo)
   - Workflow name: `publish.yml` · Environment: `pypi`
   - (A *pending* publisher reserves the name on first publish — this is how
     `dos-kernel` gets claimed, tokenlessly.)
2. **TestPyPI** → <https://test.pypi.org/manage/account/publishing/> → same fields,
   Environment `testpypi` (only if you want the dry-run leg).
3. **GitHub** → repo Settings → Environments → create `pypi` (and `testpypi`). Add
   yourself as a **required reviewer** on `pypi` so each real upload pauses for
   your approval.

### 1c. Dry-run to TestPyPI (recommended before the first real upload)

Validates the entire OIDC path without touching real PyPI:

```
GitHub → Actions → "Publish to PyPI" → Run workflow → target = testpypi
```

It builds, `twine check`s, and uploads to TestPyPI. Confirm the round-trip:

```bash
python -m venv /tmp/dos-test && /tmp/dos-test/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  dos-kernel[mcp]
/tmp/dos-test/bin/dos doctor --workspace .
```

(The `--extra-index-url` lets TestPyPI pull real PyYAML from prod PyPI.)

### 1d. The real publish

Two equivalent triggers, both gated by the `pypi` environment's reviewer prompt:

- **Tag-driven (the normal path):** `/release` pushes a `vX.Y.Z` tag → the
  workflow fires → approve the `pypi` environment → it uploads. The build job
  asserts the tag matches the package version, so a mislabelled wheel can't ship.
- **Manual:** Actions → "Publish to PyPI" → Run workflow → target = `pypi`.

> **Owner fallback (no CI):** you can always upload by hand from a built `dist/`:
> ```bash
> python -m twine upload dist/*       # uses a PyPI API token; claims the name
> ```
> Trusted Publishing is preferred (no stored secret), but the manual path is the
> backstop if the OIDC setup isn't in place yet.

Then confirm from a clean environment:

```bash
python -m venv /tmp/dos-check && /tmp/dos-check/bin/pip install dos-kernel[mcp]
/tmp/dos-check/bin/dos doctor --workspace .
```

---

## Stage 2 — Make the GitHub repo public

> **Why a fresh repo, not this one made public:** the private repo's *git
> history* still contains sensitive content recoverable from old commits (strategy
> docs, reverse-engineered internals, a private benchmark's structure). DOS goes
> public as a **fresh repo named `dos-kernel` with clean, single-commit history**;
> the current private repo stays as the archive. The full audit + rationale lives
> in the private archive's launch runbook (`LAUNCH.md`) — read it before seeding.

### 2a. Seed the clean tree (script — reversible; writes a sibling dir)

```bash
pwsh scripts/seed_public_repo.ps1    # runs the leak scan, then seeds ../dos-kernel-public
```

The script's own guard **aborts if any private path survives** the scan, and
refuses a dirty working tree (`-AllowDirty` overrides). It copies the cleaned
tree to `../dos-kernel-public`, `git init`s, and makes one clean commit. (The
seed script and the scanner are private-side tooling, themselves excluded from
the seed — which is why the public tree's CI self-skips the leak-scan job.)

### 2b. Confirm green in the fresh tree, then create the repo (owner)

```bash
cd ../dos-kernel-public
python -m pytest -q                          # green in the fresh tree
python scripts/build_dist.py --no-smoke      # publishable from the clean tree

gh repo create dos-kernel --public --source . --remote origin --push \
  --description "The kernel that doesn't believe the agents — a domain-free trust substrate for fleets of autonomous agents: verify what shipped, arbitrate collisions, refuse with structured reasons."

gh repo edit anthony-chaudhary/dos-kernel \
  --homepage "https://pypi.org/project/dos-kernel/" \
  --add-topic llm-agents --add-topic multi-agent --add-topic agent-orchestration \
  --add-topic mcp --add-topic verification --add-topic trust \
  --add-topic python --add-topic cli --add-topic developer-tools
```

After the push, CI runs and the README badges go live. (The README's CI/PyPI
badges are commented out until this flip — see the note at the top of
[`README.md`](README.md).)

### 2c. Nice-to-haves (not blocking)

- A custom **social preview** image (Settings → Social preview) — the demo SVG's
  framing is a good basis.
- **Pin** the repo on your profile.
- Keep the old private repo **private** (its history carries the scrubbed content).

---

## Stage 3 — Submit the paper to arXiv

**Reality check (verified 2026):** arXiv submission is **not automatable**. There
is no public submission API (the one that was designed is officially "out of
date — disregard"); a first-time `cs.*` author needs an **endorsement**; every
upload is **human-moderated**. What tooling *can* do is produce a correct,
upload-ready tarball in one command. The rest is a web form.

### 3a. Build the source bundle (script)

The paper is **generated** from one source of truth (`paper/sections/*.html` +
`paper/meta.py`) — never hand-edit the `.tex` or `refs.bib`; they're regenerated.
The bundle script regenerates the `.tex`, stages
exactly the figures the paper references, optionally runs `arxiv-latex-cleaner`,
and tars it:

```bash
pip install -e ".[paper]"                       # gets arxiv-latex-cleaner (optional)
python paper/arxiv/make_bundle.py --date 2026-06-09
#   → paper/arxiv/releases/arxiv-<date>.tar.gz  (main.tex + sections/ + figs/ + refs.bib)
#   prints the manual submission checklist below.
```

The tarball is correct even without the cleaner installed (the staging already
excludes aux/unused files); the cleaner just strips comments and compresses
figures toward arXiv's 50 MB limit.

### 3b. Compile once, then re-bundle with the `.bbl` (owner)

No local LaTeX is needed to *build* the bundle, but you must **compile once**
before submitting — the generator is verified statically (balanced envs/braces/
math, no leftover tags), not by a real TeX engine. Easiest is **Overleaf**: upload
`main.tex` + `sections/` + `figs/` and compile with pdfLaTeX. Or locally:

```bash
cd paper/arxiv && pdflatex main && bibtex main && pdflatex main && pdflatex main
```

Fix any straggler a real engine flags **in the `.html` source or
`assemble_arxiv.py`, not the generated `.tex`** (a hand-edit is overwritten on the
next build). Then grab the resulting `main.bbl`, drop it next to `main.tex`, and
**re-run `make_bundle.py`** so the tarball ships the compiled bibliography. arXiv
runs BibTeX itself, but a shipped `.bbl` is used verbatim and removes all
version-skew risk.

### 3c. The author actions arXiv requires (owner — no script can do these)

1. **Endorsement.** A first-time `cs.*` submitter needs one
   (<https://info.arxiv.org/help/endorsement.html>). Arrange it before upload, or
   submit under a co-author with `cs.*` posting history (which removes the gate).
   *Policy is tightening (Dec 2025 / Jan 2026 updates) — confirm the current rule
   for your category at submission time.*
2. **Author line** (`paper/arxiv/main.tex`): confirm the name and add any
   co-authors. (`main.tex` is hand-authored — safe to edit, unlike the sections.)
3. **Upload** the tarball at <https://arxiv.org/submit>.
4. **Categories:** `cs.SE` (primary), `cs.AI`; optionally `cs.DC`. **License:**
   pick one in the web form. Confirm the title/abstract metadata. **Submit** and
   expect human moderation before it appears.

### 3d. Keep the framing honest (already true in the prose)

Lead with the **sound, live results, off the environment's own ground truth**:
coordination **J = 6/8** clobbers prevented; write-admission **J = 10/120 over-claims
blocked at an identical 8.3%** across two model tiers; the give-up gate's **0/1634
false-halts**; the RLVR label purge **60% → 100%**. The downstream peer-B **ΔB is
≈0 at the immediate hop** — do not let any edit inflate it. The asymmetry (the
same verdict is harmful in-loop, valuable out-of-loop) *is* the result.

---

## Stage 4 — Announce the launch

**Reality check:** LinkedIn is **not viably automatable** for a launch post — its
API prohibits automating promotional posts, and third-party "automation" tools
violate its ToS. So the announcement copy is **drafted and staged**; *posting* is
a manual (or LinkedIn-native-scheduler) step you take.

The drafts live in [`docs/announce/`](docs/announce/):

- [`linkedin.md`](docs/announce/linkedin.md) — the LinkedIn post (lead with the
  fleet angle; the canonical "concurrency changes the verdict" wording).
- [`hackernews.md`](docs/announce/hackernews.md) — the "Show HN" title + author's
  first comment (plain text, honest-floor up front; post the repo, paper separately).
- [`blog.md`](docs/announce/blog.md) — a longer launch narrative (blog / Substack
  / the repo's own announcement).
- [`arxiv-abstract.md`](docs/announce/arxiv-abstract.md) — the abstract + the
  short "tweet-length" framings for the paper post.
- [`README.md`](docs/announce/README.md) — what to post where, and in what order.

To post: copy the relevant draft, paste into LinkedIn's composer (or its native
scheduler), attach the demo SVG/screenshot, and publish under your identity.
**Genuinely automatable cross-post targets** (if you want them later): Mastodon
(open API) and Bluesky (AT Protocol). LinkedIn itself stays manual.

---

## Quick reference — the whole thing as commands

```bash
# ── Pre-flight ───────────────────────────────────────────────────────────────
python -m pytest -q                                  # green suite
dos commit-audit --sweep origin/master..HEAD         # honest history

# ── Stage 1: PyPI (local half) ───────────────────────────────────────────────
python scripts/build_wheels.py                       # 6 per-platform wheels + sdist (needs Go)
python -m twine check dist/*                          # all must render on PyPI (no upload)
#   (no Go? scripts/build_dist.py builds the pure-Python wheel — no native binary.)
#   then: register the trusted publisher (web, once) → dry-run to TestPyPI →
#   tag a release (or Actions → Run workflow → pypi) → approve the environment.

# ── Stage 2: GitHub public ───────────────────────────────────────────────────
pwsh scripts/seed_public_repo.ps1                    # scrub + seed ../dos-kernel-public
cd ../dos-kernel-public && python -m pytest -q       # green in the fresh tree
gh repo create dos-kernel --public --source . --push --description "…"

# ── Stage 3: arXiv (automatable half) ────────────────────────────────────────
pip install -e ".[paper]"
python paper/arxiv/make_bundle.py --date $(date +%F) # ready-to-upload tarball
#   then: compile once (Overleaf) → re-bundle with main.bbl → upload at
#   arxiv.org/submit (endorsement + license + moderation are manual).

# ── Stage 4: announce ────────────────────────────────────────────────────────
#   copy docs/announce/linkedin.md → LinkedIn composer; publish under your identity.
```

Each block's first line(s) are things tooling does; the `#   then:` lines are the
owner-only, outward-facing steps. That split is the whole point.
