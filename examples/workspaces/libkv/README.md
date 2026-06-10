# `libkv` — OSS library + docs workspace

An anonymized published library. The point of this fixture: a **strict,
dir-scoped ship grammar**. `libkv` writes ship commits like
`src/CODEC: CODEC2 — ship varint encoder`, so `verify` must require the `src/`
(or `docs/`) prefix — a bare `CODEC2: ...` would *not* count here, on purpose.

```text
src/            the library             →  lane: lib
docs/           the manual + RFCs       →  lane: docs
README.md       the front page          →  lane: docs
tests/          (worked under lib)
```

Contrast with [`acme-store`](../acme-store/), which uses `subject_dirs = []`
(the bare generic shape). Same mechanism, opposite strictness — `libkv` opted
*into* the dir prefix.

```bash
dos doctor --workspace .                 # stamp convention: src|docs [style=grep]

# In a real libkv checkout, after a ship commit "src/CODEC: CODEC2 — ...":
dos verify --workspace . CODEC CODEC2    # SHIPPED ... (via grep)

# Prove the grammar matches how libkv actually stamps ships:
dos doctor --workspace . --check         # exit 1 + a finding if it doesn't
```

> **Heads-up — run `--check` inside the real repo.** This fixture directory is
> *not its own git repo*, so `--check` walks up to the DOS repo's history and
> (correctly) reports that `src|docs` matches none of *DOS's* commits. That is
> the rail working — it just has the wrong repo to judge against here. In an
> actual `libkv` checkout whose commits use `src/CODEC: ...`, `--check` exits 0.
> See [playbook 06](../../playbooks/06_debug-a-stuck-fleet.md#the-stamp-check-finding-i-didnt-expect)
> for this exact case.

Full walkthrough: [`../../playbooks/03_oss-library-release.md`](../../playbooks/03_oss-library-release.md).
