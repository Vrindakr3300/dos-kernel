# AUR recipe — `dos-kernel`

This dir is the source-of-truth for the [AUR](https://aur.archlinux.org) package
`dos-kernel`, so the Arch/Manjaro population can install the trust substrate with:

```bash
yay -S dos-kernel      # or: paru -S dos-kernel
```

DOS is pure-Python (`python>=3.11`, single runtime dep `python-yaml`), so this is a
textbook `arch=('any')` Python package built from the PyPI sdist — no compilation,
no platform matrix.

## Why the AUR

It is one of the few large distribution channels with a **zero review gate**: a
maintainer pushes a git repo to `ssh://aur@aur.archlinux.org/dos-kernel.git` and the
package is live — no PR, no human merge, no queue. One push buys a standing,
searchable listing for the whole Arch population.

## Publishing (a maintainer action — needs the AUR SSH key)

The push itself is out-of-band (it needs an AUR account + registered SSH key), so it
is a human/maintainer step, not something CI or an agent does. The in-tree files
here are what gets pushed:

```bash
# one-time: clone the (empty) AUR repo next to this one
git clone ssh://aur@aur.archlinux.org/dos-kernel.git aur-dos-kernel
cp packaging/aur/PKGBUILD packaging/aur/.SRCINFO aur-dos-kernel/
cd aur-dos-kernel
# sanity: regenerate .SRCINFO from the PKGBUILD and confirm it matches what we ship
makepkg --printsrcinfo > .SRCINFO        # (on an Arch box; must equal the committed one)
namcap PKGBUILD                          # lint (optional but recommended)
git add PKGBUILD .SRCINFO && git commit -m "dos-kernel 0.26.0" && git push
```

## On every release — bump together (the `/release` downstream-pins step)

`pkgver` and `sha256sums` must track the PyPI sdist in lockstep. After a release:

1. Get the new sdist hash from PyPI:
   `python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('https://pypi.org/pypi/dos-kernel/<VER>/json')); print(next(f['digests']['sha256'] for f in d['urls'] if f['packagetype']=='sdist'))"`
2. Update `pkgver` + `sha256sums` in `PKGBUILD`, set `pkgrel=1`, and mirror both into
   `.SRCINFO` (and bump its `pkgver`).
3. Re-run the publish push above.

A stale `pkgver`/hash is worse than no recipe (it would install an old version or
fail the integrity check), so this dir's version MUST equal the current
`pyproject.toml` version — pinned today at **0.26.0**, sha256
`730ef2be66ede033dfaf15adf6c2cfcfbefd880d774c3787e6904d1bc26e7c08` (the real
0.26.0 sdist on PyPI, not a summary).

> Distribution name note: the package is **`dos-kernel`** (the bare `dos` on PyPI is
> an unrelated squatter — see `SECURITY.md` "Supply chain"). The PKGBUILD `source`
> fetches `dos_kernel-*.tar.gz` accordingly.
