# Paper-authored figure sources (appendix A + §6)

The durable sources for the figures the paper authors itself (rather than copying
from `benchmark/.../_results/`): the three **Appendix A** diagrams ("DOS in plain
words — the Vaseline test") and the **§6** live-payoff figure. `build.py` copies the
rendered `.png`s from here into `../figs/` at build time (this directory is
registered in `meta.FIG_SOURCE_DIRS`), so the paper stays self-contained while the
editable source lives here.

| Source | Render | Paper figure |
|---|---|---|
| `appx_vaseline_mirror.mmd` | `appx_vaseline_mirror.png` | Fig A1 — the Vaseline test (byte-clean vs forgeable) |
| `appx_dos_syscall_map.mmd` | `appx_dos_syscall_map.png` | Fig A2 — the DOS kernel + trust ladder |
| `appx_fix_bakeoff.py` | `appx_fix_bakeoff.png` | Fig A3 — the active-fix bake-off (give-up is the survivor) |
| `payoff_writeadmit_live.py` | `payoff_writeadmit_live.png` | Fig 9 (§6) — Tier-B run live: the out-of-loop payoff (Run A J=0 vs Run B J=5) |

All four figures are full-width (registered in `meta.WIDE_FIGS`).

**The §6 live-payoff figure** (numbers transcribed from
`../_VERIFIED_FACTS_228_2026-06-08.md`, the verbatim read-off of docs/228 — no number
is invented in the script):

```bash
python paper/figs_src/payoff_writeadmit_live.py    # writes payoff_writeadmit_live.png
```

## Regenerate

**The matplotlib figure** (numbers transcribed from `../_VERIFIED_FACTS_2026-06-07.md`,
the live SSOT — no number is invented in the script):

```bash
python paper/figs_src/appx_fix_bakeoff.py     # writes appx_fix_bakeoff.png
```

**The two Mermaid diagrams** — rendered at 3× scale on a white background, the same
convention as `benchmark/toolathlon/_diagrams/`. `mermaid-cli` needs a headless
browser; `pup.json` points it at a system Chrome (edit the path for your machine):

```bash
cd benchmark/toolathlon
npm install --no-save @mermaid-js/mermaid-cli   # one-time; node_modules is gitignored
for n in appx_vaseline_mirror appx_dos_syscall_map; do
  ./node_modules/.bin/mmdc -i "../../paper/figs_src/$n.mmd" \
    -o "../../paper/figs_src/$n.png" -s 3 -b white -p ../../paper/figs_src/pup.json
done
```

Then rebuild the paper: `python paper/build.py`.

`pup.json` and any `node_modules/` are local render tooling; the `.mmd` / `.py`
sources and their committed `.png` renders are the durable deliverables.
